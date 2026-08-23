from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from .features import FEATURE_WEIGHTS_DEFAULT


@dataclass(frozen=True)
class MapperConfig:
    auto_min: float = 0.90
    review_min: float = 0.60
    tie_epsilon: float = 0.03
    top_k: int = 3
    # Presence-based exit codes cannot tell one suspense row from every row: a COA
    # with no usable targets sent 90/90 accounts to suspense and still reported
    # "pass with disclosed exceptions". Past this share, the run is a hard failure.
    max_suspense_ratio: float = 0.50
    weights: dict[str, float] = field(default_factory=lambda: dict(FEATURE_WEIGHTS_DEFAULT))
    inputs_dir: Path = Path("inputs")
    output_dir: Path = Path("output")
    entities_dir: Path = Path("config/entities")
    sources: tuple[str, ...] = ("current", "prior")
    # Which per-entity policy file (if any) was layered over the base config.
    # Echoed into the validation report so an artifact always names the policy
    # that produced it — "which thresholds were in force" is an audit question.
    entity: str = ""
    entity_name: str = ""

    def as_dict(self) -> dict:
        out = {
            "auto_min": self.auto_min,
            "review_min": self.review_min,
            "tie_epsilon": self.tie_epsilon,
            "top_k": self.top_k,
            "max_suspense_ratio": self.max_suspense_ratio,
            "weights": dict(sorted(self.weights.items())),
            "sources": list(self.sources),
        }
        if self.entity:
            out["entity"] = self.entity
            out["entity_name"] = self.entity_name
        return out


def load_config(path: Path | None) -> MapperConfig:
    if path is None or not path.exists():
        return MapperConfig()
    raw = yaml.safe_load(path.read_text()) or {}
    thresholds = raw.get("thresholds", {}) or {}
    weights_raw = raw.get("weights", {}) or {}
    weights = dict(FEATURE_WEIGHTS_DEFAULT)
    weights.update({k: float(v) for k, v in weights_raw.items()})
    paths = raw.get("paths", {}) or {}
    return MapperConfig(
        auto_min=float(thresholds.get("auto_min", 0.90)),
        review_min=float(thresholds.get("review_min", 0.60)),
        tie_epsilon=float(thresholds.get("tie_epsilon", 0.03)),
        top_k=int(thresholds.get("top_k", 3)),
        max_suspense_ratio=float(thresholds.get("max_suspense_ratio", 0.50)),
        weights=weights,
        inputs_dir=Path(paths.get("inputs_dir", "inputs")),
        output_dir=Path(paths.get("output_dir", "output")),
        entities_dir=Path(paths.get("entities_dir", "config/entities")),
        sources=tuple(raw.get("sources", ["current", "prior"])),
    )


class EntityPolicyError(ValueError):
    """A named entity policy could not be loaded. Never silently ignored: running
    with base thresholds when the operator asked for an entity's would apply the
    wrong policy under the entity's name."""


def apply_entity_policy(config: MapperConfig, entity: str) -> MapperConfig:
    """Layer `config/entities/<entity>.yaml` over the base config.

    Only keys present in the entity file override the base. One global auto_min
    is the wrong shape at scale — the tolerable false-auto-map rate differs by
    chart and by account class — so policy lives per entity, versioned next to
    the code, rather than as a flag someone remembers to pass.
    """
    path = config.entities_dir / f"{entity}.yaml"
    if not path.exists():
        available = (
            sorted(p.stem for p in config.entities_dir.glob("*.yaml") if not p.stem.startswith("_"))
            if config.entities_dir.exists()
            else []
        )
        raise EntityPolicyError(
            f"no entity policy '{entity}' at {path}. Available: {available or 'none'}"
        )

    raw = yaml.safe_load(path.read_text()) or {}
    thresholds = raw.get("thresholds") or {}
    weights = dict(config.weights)
    weights.update({k: float(v) for k, v in (raw.get("weights") or {}).items()})
    meta = raw.get("entity") or {}

    return replace(
        config,
        auto_min=float(thresholds.get("auto_min", config.auto_min)),
        review_min=float(thresholds.get("review_min", config.review_min)),
        tie_epsilon=float(thresholds.get("tie_epsilon", config.tie_epsilon)),
        top_k=int(thresholds.get("top_k", config.top_k)),
        max_suspense_ratio=float(thresholds.get("max_suspense_ratio", config.max_suspense_ratio)),
        weights=weights,
        entity=entity,
        entity_name=str(meta.get("name", "") or ""),
    )
