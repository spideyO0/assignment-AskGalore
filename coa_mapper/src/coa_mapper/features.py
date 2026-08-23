from __future__ import annotations

from decimal import Decimal

from rapidfuzz import fuzz

from .normalize import normalize_name, significant_tokens


def name_similarity(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    return max(fuzz.ratio(na, nb), fuzz.token_sort_ratio(na, nb)) / 100.0


def token_overlap(a: str, b: str) -> float:
    ta, tb = significant_tokens(a), significant_tokens(b)
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


def code_proximity(source_code: str, candidate_code: str) -> float:
    sc, cc = source_code.strip(), candidate_code.strip()
    matched = 0
    for a, b in zip(sc, cc, strict=False):  # shortest-prefix compare is intended
        if a == b:
            matched += 1
        else:
            break
    limit = max(len(sc), len(cc))
    return matched / limit if limit else 0.0


def balance_continuity(
    source_balance: Decimal | None, candidate_balance: Decimal | None
) -> float | None:
    if source_balance is None or candidate_balance is None:
        return None
    if source_balance == 0 or candidate_balance == 0:
        return None
    larger = max(abs(source_balance), abs(candidate_balance))
    drift = abs(source_balance - candidate_balance) / larger
    return 1.0 - min(1.0, float(drift))


FEATURE_WEIGHTS_DEFAULT = {
    "name_similarity": 0.45,
    "token_overlap": 0.15,
    "code_proximity": 0.10,
    "balance_continuity": 0.30,
}

# Weight for the optional semantic feature. Deliberately NOT in the default set:
# with no provider configured the feature is never emitted, the config echo does
# not mention it, and the artifacts are byte-identical to a build without
# semantic.py at all. It is merged into the weights only when enabled.
SEMANTIC_WEIGHT_DEFAULT = 0.25
