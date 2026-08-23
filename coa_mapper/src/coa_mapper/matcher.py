from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from .coa import leaf_nodes, token_index
from .features import (
    FEATURE_WEIGHTS_DEFAULT,
    SEMANTIC_WEIGHT_DEFAULT,
    balance_continuity,
    code_proximity,
    name_similarity,
    token_overlap,
)
from .models import AccountAggregate, CandidateScore, CoaNode
from .normalize import canonical_key, normalize_code
from .semantic import FEATURE_NAME as SEMANTIC_FEATURE
from .semantic import SemanticCache

_Q4 = Decimal("0.0001")


def _dec(x) -> Decimal:
    return Decimal(str(x))


def _q4(x) -> Decimal:
    """Quantize to the 4dp the artifacts publish, half-up so a human recomputing
    the weighted mean by hand lands on the same digit."""
    return _dec(x).quantize(_Q4, rounding=ROUND_HALF_UP)


def match_config_from(config) -> MatchConfig:
    """Single construction path for gate thresholds, used by pipeline AND verifier.

    They built this separately and drifted: the pipeline wrapped the thresholds in
    Decimal, the verifier passed the raw floats. float 0.90 is 0.9000000000000000222,
    so a candidate scoring exactly 0.9000 auto-applied in the pipeline and went to
    REVIEW in the verifier — a spurious decision_reproduction failure that would
    have exited 2 on a correct mapping. One factory, so they cannot disagree again.
    """
    return MatchConfig(
        auto_min=Decimal(str(config.auto_min)),
        review_min=Decimal(str(config.review_min)),
        tie_epsilon=config.tie_epsilon,
        top_k=config.top_k,
        weights=dict(config.weights),
    )


@dataclass(frozen=True)
class MatchConfig:
    auto_min: Decimal = Decimal("0.90")
    review_min: Decimal = Decimal("0.60")
    tie_epsilon: float = 0.03
    top_k: int = 3
    weights: dict[str, float] | None = None

    def weight(self, key: str) -> float:
        weights = self.weights or FEATURE_WEIGHTS_DEFAULT
        if key == SEMANTIC_FEATURE:
            return weights.get(key, SEMANTIC_WEIGHT_DEFAULT)
        return weights[key]


class Matcher:
    def __init__(
        self,
        nodes: list[CoaNode],
        config: MatchConfig,
        reference_balances: dict[str, Decimal] | None = None,
        semantic: SemanticCache | None = None,
    ) -> None:
        self.semantic = semantic
        self.leaves = {n.account_code: n for n in leaf_nodes(nodes)}
        self.by_canonical_name: dict[str, list[CoaNode]] = {}
        for node in self.leaves.values():
            self.by_canonical_name.setdefault(canonical_key(node.account_name), []).append(node)
        self.tokens = token_index(list(self.leaves.values()))
        self.config = config
        self.reference_balances = reference_balances or {}

    def match_aggregate(
        self,
        agg: AccountAggregate,
        source_balances: dict[str, Decimal] | None = None,
    ) -> tuple[CandidateScore, list[CandidateScore]]:
        code = normalize_code(agg.account_code)
        if code in self.leaves:
            exact = self.leaves[code]
            return (
                CandidateScore(
                    node=exact,
                    tier="EXACT_CODE",
                    confidence=Decimal("1.0000"),
                    features={"exact_code": 1.0},
                    weights_used={"exact_code": 1.0},
                    balance_evidence=False,
                ),
                [],
            )

        key = canonical_key(agg.account_name)
        if key in self.by_canonical_name and len(self.by_canonical_name[key]) == 1:
            node = self.by_canonical_name[key][0]
            return (
                CandidateScore(
                    node=node,
                    tier="NORMALIZED_NAME",
                    confidence=Decimal("0.9900"),
                    features={"unique_normalized_name": 1.0},
                    weights_used={"unique_normalized_name": 1.0},
                    balance_evidence=False,
                ),
                [],
            )

        scored = [self._score_fuzzy(agg, node, source_balances) for node in self.leaves.values()]
        scored.sort(key=lambda c: (-c.confidence, c.node.account_code))
        best_k = scored[: self.config.top_k]
        if not best_k or best_k[0].confidence < self.config.review_min:
            tier = "NO_CANDIDATE"
            if best_k:
                fallback = CandidateScore(
                    node=best_k[0].node,
                    tier=tier,
                    confidence=best_k[0].confidence,
                    features=best_k[0].features,
                    weights_used=best_k[0].weights_used,
                    balance_evidence=best_k[0].balance_evidence,
                )
                return fallback, best_k[1:]
            return (
                CandidateScore(
                    node=None,  # type: ignore[arg-type]
                    tier=tier,
                    confidence=Decimal("0.0000"),
                    features={},
                    weights_used={},
                    balance_evidence=False,
                ),
                [],
            )
        return best_k[0], best_k[1:]

    def _score_fuzzy(
        self,
        agg: AccountAggregate,
        node: CoaNode,
        source_balances: dict[str, Decimal] | None,
    ) -> CandidateScore:
        feats: dict[str, float] = {}
        wts: dict[str, float] = {}

        feats["name_similarity"] = name_similarity(agg.account_name, node.account_name)
        wts["name_similarity"] = self.config.weight("name_similarity")

        overlap = token_overlap(agg.account_name, node.account_name)
        feats["token_overlap"] = overlap
        wts["token_overlap"] = self.config.weight("token_overlap")

        proximity = code_proximity(normalize_code(agg.account_code), node.account_code)
        feats["code_proximity"] = proximity
        wts["code_proximity"] = self.config.weight("code_proximity")

        if self.semantic is not None:
            score = self.semantic.similarity(agg.account_name, node.account_name)
            if score is not None:
                feats[SEMANTIC_FEATURE] = score
                wts[SEMANTIC_FEATURE] = self.config.weight(SEMANTIC_FEATURE)

        candidate_balance: Decimal | None = self.reference_balances.get(node.account_code)
        source_balance: Decimal | None = (source_balances or {}).get(agg.account_code)
        continuity = balance_continuity(source_balance, candidate_balance)
        balance_evidence = continuity is not None
        if continuity is not None:
            feats["balance_continuity"] = continuity
            wts["balance_continuity"] = self.config.weight("balance_continuity")

        # Publish first, then score from what was published. Scoring off the raw
        # floats and rounding the feature vector separately means an auditor
        # recomputing the weighted mean from decisions.jsonl gets a different
        # number than the one recorded there (9999 published 0.5455 -> 0.3507,
        # while the run recorded 0.3506 from the unrounded 6/11). Half-up, not
        # Python's round(), so the recomputation matches by hand too.
        published = {k: _q4(v) for k, v in sorted(feats.items())}
        denom = sum(_dec(w) for w in wts.values())
        confidence = (
            _q4(sum(published[k] * _dec(wts[k]) for k in published) / denom)
            if denom
            else Decimal("0.0000")
        )
        return CandidateScore(
            node=node,
            tier="FUZZY_COMPOSITE",
            confidence=confidence,
            features={k: float(v) for k, v in published.items()},
            weights_used=dict(sorted(wts.items())),
            balance_evidence=balance_evidence,
        )


def runner_up_margin(best: CandidateScore, runners: list[CandidateScore]) -> Decimal:
    if not runners:
        return Decimal("1.0000")
    # Decimal subtraction of two already-quantized confidences: the margin is
    # exactly reproducible from the two numbers printed next to it.
    return _q4(best.confidence - runners[0].confidence)
