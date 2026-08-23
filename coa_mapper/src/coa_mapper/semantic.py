"""Optional semantic-similarity feature, and the cache that makes it reproducible.

`architecture.md` §3 argues an LLM belongs in this pipeline in exactly one shape:
as **one more scored feature inside the existing weighted vector**, never as its
own code path and never as a decision. This module is that slot.

Three properties the design turns on:

1. **It is a feature, not a verdict.** The provider returns a similarity in
   [0, 1] for one (source account, candidate account) pair. That number joins
   `name_similarity` and friends in the same weighted mean, faces the same
   `auto_min` gate, the same normal-balance veto, and the same tie guard, and is
   written into `decisions.jsonl` like any other feature. Swapping the provider
   out changes a number, not the control flow.

   This is deliberately unlike the common pattern of asking a model for its own
   `"confidence": "high|medium|low"` and applying the classification regardless,
   with the self-reported confidence driving nothing more than an advisory
   warning. A model's estimate of its own certainty is not a probability of
   anything, so here it is evidence to be weighed, not a gate to be trusted.

2. **Determinism is enforced, not hoped for.** Every lookup is content-addressed
   on (cache version, provider id, prompt version, source, candidate). With
   `strict=True` a miss raises instead of calling out, so a CI run either
   reproduces from the committed cache byte-for-byte or fails loudly. A pipeline
   whose output depends on whether a network call succeeded is not auditable.

3. **Off by default.** No provider configured means no feature emitted, the
   weights renormalise over what remains, and the artifacts are byte-identical
   to a run without this module. The provided dataset needs no model — the
   `6905 -> 6900` rename is caught by `balance_continuity` alone.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

CACHE_VERSION = "1"
DEFAULT_TTL_DAYS = 90
FEATURE_NAME = "semantic_similarity"


class SemanticProvider(Protocol):
    """Scores how likely two account names refer to the same account.

    Implementations may call a model, an embedding index, or a lookup table. The
    pipeline only requires that the result is a float in [0, 1] and that `id`
    changes whenever the scoring behaviour changes, so stale cache entries cannot
    be silently reused across a behaviour change.
    """

    @property
    def id(self) -> str: ...

    @property
    def prompt_version(self) -> str: ...

    def similarity(self, source_name: str, candidate_name: str) -> float: ...


class CacheMiss(LookupError):
    """Raised in strict mode when a value is absent and calling out is forbidden."""


@dataclass
class SemanticCache:
    """Content-addressed cache with TTL, versioning, and hit/miss accounting.

    Persisted as sorted JSON so a diff between two runs is readable and the file
    can be committed alongside the artifacts it explains.
    """

    path: Path | None = None
    provider: SemanticProvider | None = None
    ttl_days: int = DEFAULT_TTL_DAYS
    strict: bool = False
    now: float = field(default_factory=time.time)
    entries: dict[str, dict] = field(default_factory=dict)
    stats: dict[str, int] = field(
        default_factory=lambda: {"hits": 0, "misses": 0, "expired": 0, "computed": 0}
    )

    def __post_init__(self) -> None:
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text())
            if raw.get("cache_version") == CACHE_VERSION:
                self.entries = raw.get("entries", {})
            # A version bump discards rather than migrates: a stale score is
            # worse than a recomputed one, and silently mixing generations
            # produces a feature vector nobody can reproduce.

    def key(self, source_name: str, candidate_name: str) -> str:
        provider_id = self.provider.id if self.provider else "none"
        prompt_version = self.provider.prompt_version if self.provider else "none"
        material = "|".join(
            [CACHE_VERSION, provider_id, prompt_version, source_name, candidate_name]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def similarity(self, source_name: str, candidate_name: str) -> float | None:
        """Cached score, or None when no provider is configured."""
        if self.provider is None:
            return None

        k = self.key(source_name, candidate_name)
        hit = self.entries.get(k)
        if hit is not None:
            if self._fresh(hit):
                self.stats["hits"] += 1
                return float(hit["value"])
            self.stats["expired"] += 1
            del self.entries[k]

        self.stats["misses"] += 1
        if self.strict:
            raise CacheMiss(
                f"no cached semantic score for {source_name!r} -> {candidate_name!r} "
                f"and strict mode forbids calling the provider. Refresh the cache "
                f"deliberately rather than letting a run depend on a live call."
            )

        value = float(self.provider.similarity(source_name, candidate_name))
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"provider {self.provider.id} returned {value} for "
                f"{source_name!r} -> {candidate_name!r}; a feature must be in [0, 1]"
            )
        self.stats["computed"] += 1
        self.entries[k] = {
            "value": value,
            "stored_at": self.now,
            "source_name": source_name,
            "candidate_name": candidate_name,
            "provider": self.provider.id,
            "prompt_version": self.provider.prompt_version,
        }
        return value

    def _fresh(self, entry: dict) -> bool:
        if self.ttl_days <= 0:
            return True
        age_days = (self.now - float(entry.get("stored_at", 0))) / 86400.0
        return age_days <= self.ttl_days

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "cache_version": CACHE_VERSION,
            "ttl_days": self.ttl_days,
            "entries": dict(sorted(self.entries.items())),
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def summary(self) -> dict:
        return {
            "provider": self.provider.id if self.provider else None,
            "prompt_version": self.provider.prompt_version if self.provider else None,
            "cached_entries": len(self.entries),
            **self.stats,
        }


@dataclass(frozen=True)
class LookupProvider:
    """Deterministic provider backed by an explicit table.

    Used in tests, and usable in production as a curated override list — a
    finance team's own "these two are the same account" rulings, which are
    better evidence than any model and cost nothing to score.
    """

    table: dict[tuple[str, str], float]
    id: str = "lookup"
    prompt_version: str = "1"

    def similarity(self, source_name: str, candidate_name: str) -> float:
        return self.table.get((source_name, candidate_name), 0.0)
