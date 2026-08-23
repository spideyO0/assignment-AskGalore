"""The optional semantic feature, and the cache that keeps it reproducible.

The contract this file defends: a model may contribute *evidence* to the same
weighted vector every other feature lives in, and may never contribute a
decision. Off by default, byte-identical when off, deterministic when on.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from coa_mapper.config import MapperConfig
from coa_mapper.matcher import Matcher, match_config_from
from coa_mapper.models import AccountAggregate
from coa_mapper.pipeline import run
from coa_mapper.semantic import (
    CACHE_VERSION,
    FEATURE_NAME,
    CacheMiss,
    LookupProvider,
    SemanticCache,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INPUTS = REPO_ROOT.parent / "inputs"


def agg(code="6905", name="Sundry Operating Expenses"):
    return AccountAggregate(
        source="prior",
        account_code=code,
        account_name=name,
        usd_net=Decimal("132000.00"),
        usd_debit_total=Decimal("132000.00"),
        usd_credit_total=Decimal("0.00"),
        dominant_side="Debit",
        row_ids=("prior:34",),
        currencies=("USD",),
        rate_by_row=(),
    )


class TestDisabledByDefault:
    """No provider means no feature, and output identical to a build without it."""

    def test_no_provider_emits_no_feature(self):
        cache = SemanticCache()
        assert cache.similarity("a", "b") is None

    def test_default_weights_do_not_mention_the_feature(self):
        from coa_mapper.features import FEATURE_WEIGHTS_DEFAULT

        assert FEATURE_NAME not in FEATURE_WEIGHTS_DEFAULT

    def test_config_echo_stays_silent_when_disabled(self):
        report = run(MapperConfig(inputs_dir=INPUTS)).artifacts["validation_report.md"]
        assert FEATURE_NAME not in report

    def test_no_decision_carries_the_feature_when_disabled(self):
        outcome = run(MapperConfig(inputs_dir=INPUTS))
        assert all(FEATURE_NAME not in d.features for d in outcome.decisions)


class TestFeatureNotVerdict:
    """Enabled, the score joins the vector and is still gated like everything else."""

    def _matcher(self, nodes, table, weights=None):
        cfg = MapperConfig(inputs_dir=INPUTS)
        if weights:
            cfg = MapperConfig(inputs_dir=INPUTS, weights={**cfg.weights, **weights})
        cache = SemanticCache(provider=LookupProvider(table=table))
        return Matcher(nodes, match_config_from(cfg), semantic=cache)

    @pytest.fixture
    def nodes(self):
        from coa_mapper.io_loaders import load_coa

        return load_coa(INPUTS / "chart_of_accounts.csv")[0]

    def test_score_appears_in_the_published_feature_vector(self, nodes):
        m = self._matcher(nodes, {("Sundry Operating Expenses", "Other Operating Expenses"): 0.95})
        best, _ = m.match_aggregate(agg())

        assert FEATURE_NAME in best.features
        assert best.features[FEATURE_NAME] == 0.95

    def test_confidence_still_reconciles_with_the_published_vector(self, nodes):
        m = self._matcher(nodes, {("Sundry Operating Expenses", "Other Operating Expenses"): 0.95})
        best, _ = m.match_aggregate(agg())

        num = sum(
            Decimal(str(v)) * Decimal(str(best.weights_used[k])) for k, v in best.features.items()
        )
        den = sum(Decimal(str(best.weights_used[k])) for k in best.features)
        assert (num / den).quantize(Decimal("0.0001")) == best.confidence

    def test_a_maximal_score_cannot_by_itself_force_an_auto_apply(self, nodes):
        """Even a 1.0 from the model is one weighted term among several."""
        m = self._matcher(nodes, {("Sundry Operating Expenses", "Other Operating Expenses"): 1.0})
        best, _ = m.match_aggregate(agg())

        assert best.confidence < Decimal(
            "1.0000"
        ), "the model must not be able to saturate the score"

    def test_provider_returning_out_of_range_is_rejected(self):
        cache = SemanticCache(provider=LookupProvider(table={("a", "b"): 4.2}))
        with pytest.raises(ValueError, match=r"must be in \[0, 1\]"):
            cache.similarity("a", "b")


class TestCacheDeterminism:
    def test_repeated_lookup_hits_the_cache(self):
        cache = SemanticCache(provider=LookupProvider(table={("a", "b"): 0.5}))
        assert cache.similarity("a", "b") == 0.5
        assert cache.similarity("a", "b") == 0.5

        assert cache.stats["computed"] == 1
        assert cache.stats["hits"] == 1

    def test_key_is_content_addressed_on_both_names(self):
        cache = SemanticCache(provider=LookupProvider(table={}))
        assert cache.key("a", "b") != cache.key("b", "a")
        assert cache.key("a", "b") == cache.key("a", "b")

    def test_changing_prompt_version_changes_the_key(self):
        a = SemanticCache(provider=LookupProvider(table={}, prompt_version="1"))
        b = SemanticCache(provider=LookupProvider(table={}, prompt_version="2"))
        assert a.key("x", "y") != b.key("x", "y")

    def test_changing_provider_changes_the_key(self):
        a = SemanticCache(provider=LookupProvider(table={}, id="alpha"))
        b = SemanticCache(provider=LookupProvider(table={}, id="beta"))
        assert a.key("x", "y") != b.key("x", "y")

    def test_strict_mode_refuses_to_call_out_on_a_miss(self):
        cache = SemanticCache(provider=LookupProvider(table={("a", "b"): 0.5}), strict=True)
        with pytest.raises(CacheMiss, match="strict mode"):
            cache.similarity("a", "b")

    def test_strict_mode_serves_a_warm_cache(self, tmp_path):
        """The CI shape: populate deliberately, then run reproducibly offline."""
        path = tmp_path / "semantic_cache.json"
        warm = SemanticCache(path=path, provider=LookupProvider(table={("a", "b"): 0.5}))
        warm.similarity("a", "b")
        warm.save()

        cold = SemanticCache(path=path, provider=LookupProvider(table={}), strict=True)
        assert cold.similarity("a", "b") == 0.5
        assert cold.stats["hits"] == 1

    def test_expired_entries_are_discarded_not_served(self, tmp_path):
        path = tmp_path / "c.json"
        old = SemanticCache(
            path=path, provider=LookupProvider(table={("a", "b"): 0.5}), now=0.0, ttl_days=90
        )
        old.similarity("a", "b")
        old.save()

        much_later = SemanticCache(
            path=path,
            provider=LookupProvider(table={("a", "b"): 0.9}),
            now=100 * 86400.0,
            ttl_days=90,
        )
        assert much_later.similarity("a", "b") == 0.9
        assert much_later.stats["expired"] == 1

    def test_a_cache_version_bump_discards_rather_than_migrates(self, tmp_path):
        path = tmp_path / "c.json"
        path.write_text(json.dumps({"cache_version": "not-" + CACHE_VERSION, "entries": {"k": {}}}))

        cache = SemanticCache(path=path, provider=LookupProvider(table={}))
        assert cache.entries == {}, "a stale generation must not be silently mixed in"

    def test_saved_file_is_stable_across_writes(self, tmp_path):
        path = tmp_path / "c.json"
        for _ in range(2):
            c = SemanticCache(path=path, provider=LookupProvider(table={("a", "b"): 0.5}), now=1.0)
            c.similarity("a", "b")
            c.save()
        first = path.read_text()

        c = SemanticCache(path=path, provider=LookupProvider(table={("a", "b"): 0.5}), now=1.0)
        c.similarity("a", "b")
        c.save()
        assert path.read_text() == first

    def test_summary_reports_provenance_and_accounting(self):
        cache = SemanticCache(provider=LookupProvider(table={("a", "b"): 0.5}))
        cache.similarity("a", "b")
        cache.similarity("a", "b")
        s = cache.summary()

        assert s["provider"] == "lookup"
        assert s["prompt_version"] == "1"
        assert s["cached_entries"] == 1
        assert s["hits"] == 1 and s["computed"] == 1
