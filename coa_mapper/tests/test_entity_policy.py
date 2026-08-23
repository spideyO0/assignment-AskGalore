"""Per-entity policy overrides.

One global auto_min is the wrong shape at scale: the tolerable false-auto-map
rate differs by chart and by account class. Policy therefore lives in
`config/entities/<entity>.yaml`, versioned next to the code, layered over the
base config, and echoed into the report so an artifact always names the policy
that produced it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from coa_mapper.cli import main
from coa_mapper.config import (
    EntityPolicyError,
    MapperConfig,
    apply_entity_policy,
    load_config,
)
from coa_mapper.pipeline import EXIT_DISCLOSED, EXIT_HARD, run

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT.parent / "inputs"
ENTITIES = REPO_ROOT / "config" / "entities"


@pytest.fixture
def base():
    return MapperConfig(inputs_dir=INPUTS, entities_dir=ENTITIES)


def test_shipped_entity_file_loads(base):
    cfg = apply_entity_policy(base, "acme_us")
    assert cfg.entity == "acme_us"
    assert "Acme US" in cfg.entity_name


def test_only_declared_keys_are_overridden(base):
    """acme_us sets tie_epsilon and two weights; everything else must survive."""
    cfg = apply_entity_policy(base, "acme_us")

    assert cfg.tie_epsilon == 0.05  # overridden
    assert cfg.auto_min == base.auto_min  # untouched
    assert cfg.review_min == base.review_min
    assert cfg.max_suspense_ratio == base.max_suspense_ratio


def test_weight_override_is_a_merge_not_a_replace(base):
    cfg = apply_entity_policy(base, "acme_us")

    assert cfg.weights["code_proximity"] == 0.15  # overridden
    assert cfg.weights["token_overlap"] == 0.10  # overridden
    assert cfg.weights["name_similarity"] == base.weights["name_similarity"]  # kept
    assert cfg.weights["balance_continuity"] == base.weights["balance_continuity"]
    assert set(cfg.weights) == set(base.weights), "no feature may appear or vanish"


def test_unknown_entity_raises_rather_than_falling_back(base):
    """Silently using base thresholds under an entity's name applies the wrong
    policy and labels it as the right one."""
    with pytest.raises(EntityPolicyError) as exc:
        apply_entity_policy(base, "does_not_exist")

    assert "acme_us" in str(exc.value), "the error should list what IS available"


def test_unknown_entity_is_a_hard_failure_at_the_cli(tmp_path, capsys):
    code = main(["run", "--inputs", str(INPUTS), "--out", str(tmp_path / "o"), "--entity", "nope"])
    assert code == EXIT_HARD
    assert "no entity policy" in capsys.readouterr().err


def test_template_is_not_selectable_as_an_entity(base):
    """`_template.yaml` is documentation, not a policy."""
    assert (ENTITIES / "_template.yaml").exists()
    with pytest.raises(EntityPolicyError) as exc:
        apply_entity_policy(base, "does_not_exist")
    assert "_template" not in str(exc.value)


def test_entity_is_echoed_into_the_report(base):
    outcome = run(apply_entity_policy(base, "acme_us"))
    report = outcome.artifacts["validation_report.md"]

    assert "acme_us" in report, "the artifact must name the policy that produced it"


def test_base_run_records_no_entity(base):
    outcome = run(base)
    assert '"entity"' not in outcome.artifacts["validation_report.md"]


def test_acme_policy_does_not_change_any_disposition(base):
    """The shipped example is a mechanism demo, not a behaviour change. If this
    ever fails, the committed output/ and the entity file have diverged."""
    plain = {(d.source, d.account_code): d.disposition for d in run(base).decisions}
    entity = {
        (d.source, d.account_code): d.disposition
        for d in run(apply_entity_policy(base, "acme_us")).decisions
    }
    assert plain == entity


def test_entity_policy_survives_path_overrides(base, tmp_path):
    """--entity then --out must not lose the entity, and vice versa."""
    code = main(
        [
            "run",
            "--inputs",
            str(INPUTS),
            "--out",
            str(tmp_path / "o"),
            "--entity",
            "acme_us",
        ]
    )
    assert code == EXIT_DISCLOSED
    assert "acme_us" in (tmp_path / "o" / "validation_report.md").read_text()


def test_entities_dir_is_configurable(tmp_path):
    (tmp_path / "e").mkdir()
    (tmp_path / "e" / "custom.yaml").write_text(
        "entity:\n  name: Custom\nthresholds:\n  auto_min: 0.75\n"
    )
    cfg = apply_entity_policy(MapperConfig(entities_dir=tmp_path / "e"), "custom")

    assert cfg.auto_min == 0.75
    assert cfg.entity_name == "Custom"


def test_config_yaml_can_point_at_an_entities_dir(tmp_path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("paths:\n  entities_dir: some/where\n")
    assert load_config(cfg_file).entities_dir == Path("some/where")
