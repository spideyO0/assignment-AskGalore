from __future__ import annotations

from decimal import Decimal

from coa_mapper.gate import decide
from coa_mapper.matcher import MatchConfig, Matcher
from coa_mapper.models import AccountAggregate, CoaNode


def make_node(code, name, normal="Debit", type_="Expense"):
    return CoaNode(
        account_code=code,
        account_name=name,
        account_type=type_,
        parent_code="6000",
        statement="PL",
        cf_category="",
        normal_balance=normal,
    )


def make_agg(code, name, net=Decimal("62000")):
    return AccountAggregate(
        source="prior",
        account_code=code,
        account_name=name,
        usd_net=net,
        usd_debit_total=max(net, Decimal("0")),
        usd_credit_total=max(-net, Decimal("0")),
        dominant_side="Debit" if net >= 0 else "Credit",
        row_ids=("prior:1",),
        currencies=("USD",),
        rate_by_row=(("USD", "usd_functional"),),
    )


CFG = MatchConfig()


def test_exact_code_short_circuits_fuzzy():
    nodes = [make_node("1110", "Cash and Cash Equivalents")]
    matcher = Matcher(nodes, CFG)
    decision = decide(make_agg("1110", "Completely Different Name Ltd"), matcher, CFG)
    assert decision.disposition == "AUTO_APPLIED"
    assert decision.tier == "EXACT_CODE"
    assert decision.confidence == Decimal("1.0000")
    assert decision.mapped_code == "1110"


def test_unique_normalized_name_matches():
    nodes = [make_node("1110", "Cash  &  Equivalents!")]
    matcher = Matcher(nodes, CFG)
    decision = decide(make_agg("9991", "cash and equivalents"), matcher, CFG)
    assert decision.tier == "NORMALIZED_NAME"
    assert decision.mapped_code == "1110"


def test_normal_balance_mismatch_blocks_auto_apply():
    nodes = [make_node("2110", "Vendor Costs Payable", normal="Credit", type_="Liability")]
    matcher = Matcher(nodes, CFG)
    loose = MatchConfig(auto_min=Decimal("0.50"), review_min=Decimal("0.30"))
    decision = decide(make_agg("9100", "Vendor Costs Payable"), matcher, loose)
    assert decision.tier == "NORMALIZED_NAME"
    assert decision.confidence >= loose.auto_min
    assert decision.disposition == "REVIEW"
    assert "NORMAL_BALANCE_VETO" in decision.flags


def test_high_confidence_with_clear_margin_auto_applies():
    nodes = [
        make_node("6220", "Office Supplies"),
        make_node("8200", "Deferred Tax Expense"),
    ]
    matcher = Matcher(nodes, CFG)
    source = {"6221": Decimal("62000")}
    decision = decide(
        make_agg("6221", "Office Supplies Costs"),
        matcher,
        MatchConfig(auto_min=Decimal("0.75")),
        source_balances=source,
    )
    assert decision.tier == "FUZZY_COMPOSITE"
    assert decision.disposition == "AUTO_APPLIED"
    assert decision.mapped_code == "6220"


def test_below_review_floor_goes_suspense():
    nodes = [make_node("1230", "Goodwill")]
    matcher = Matcher(nodes, CFG)
    decision = decide(make_agg("9999", "Suspense - Unmapped", net=Decimal("12400")), matcher, CFG)
    assert decision.disposition == "SUSPENSE"
    assert decision.usd_net == Decimal("12400")


def test_force_suspense_reason_overrides_everything():
    nodes = [make_node("1110", "Cash and Cash Equivalents")]
    matcher = Matcher(nodes, CFG)
    decision = decide(
        make_agg("1110", "Cash and Cash Equivalents"),
        matcher,
        CFG,
        force_suspense_reason="no FX rate for currency; never guessed",
    )
    assert decision.disposition == "SUSPENSE"
    assert decision.flags == ("NO_FX_RATE",)


def test_continuity_feature_boosts_rename_candidate():
    target = make_node("6900", "Other Operating Expenses")
    decoys = [make_node(f"{code}", f"Filler Account {code}") for code in ("7210", "7310")]
    nodes = [target] + decoys
    source = {"6905": Decimal("132000")}
    reference = {"6900": Decimal("140000")}

    with_evidence = decide(
        make_agg("6905", "Sundry Operating Expenses", net=Decimal("132000")),
        Matcher(nodes, CFG, reference_balances=reference),
        CFG,
        source_balances=source,
    )
    without_evidence = decide(
        make_agg("6905", "Sundry Operating Expenses", net=Decimal("132000")),
        Matcher(nodes, CFG, reference_balances=None),
        CFG,
        source_balances=None,
    )
    assert with_evidence.features.get("balance_continuity") is not None
    assert "balance_continuity" not in without_evidence.features
    assert float(with_evidence.confidence) > float(without_evidence.confidence)


def test_ambiguous_tie_downgrades_to_review():
    nodes = [
        make_node("6411", "Freight Expense Inbound"),
        make_node("6412", "Freight Expense Outbound"),
    ]
    matcher = Matcher(nodes, CFG)
    decision = decide(
        make_agg("6499", "Freight Expense Regional"),
        matcher,
        MatchConfig(auto_min=Decimal("0.60"), tie_epsilon=0.05),
    )
    assert decision.disposition == "REVIEW"
    assert "AMBIGUOUS_TIE" in decision.flags
