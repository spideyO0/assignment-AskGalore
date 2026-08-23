from __future__ import annotations

from decimal import Decimal

from .matcher import MatchConfig, Matcher, runner_up_margin
from .models import AccountAggregate, Decision, TbRow


def synthesize_untranslated(
    source: str,
    rows: list[TbRow],
    untranslatable_codes: set[str],
    partial_by_code: dict[str, AccountAggregate] | None = None,
) -> dict[str, Decision]:
    """One SUSPENSE decision per account holding an untranslatable row.

    An account can be partly translatable: 1110 might carry USD and EUR rows that
    translate fine alongside a JPY row with no published rate. Two things used to
    go wrong there. The stub hardcoded usd_net=0, so suspense reported $0.00 for
    an account holding real money; and the pipeline still emitted a separate
    decision for the translatable aggregate, so the account was counted twice and
    USD conservation broke by exactly the translatable amount.

    Now the decision carries the translatable subtotal, claims every row of the
    account, and the reason states plainly that the figure is partial and which
    currencies are missing — an understated-but-labelled number instead of a
    confident zero.
    """
    partial_by_code = partial_by_code or {}
    grouped: dict[str, list[TbRow]] = {}
    for row in rows:
        if row.account_code in untranslatable_codes:
            grouped.setdefault(row.account_code, []).append(row)
    out: dict[str, Decision] = {}
    for code in sorted(grouped):
        entries = grouped[code]
        partial = partial_by_code.get(code)
        missing: list[str] = []
        for row in entries:
            if row.currency not in missing and (
                partial is None or row.currency not in partial.currencies
            ):
                missing.append(row.currency)
        currencies: list[str] = []
        for row in entries:
            if row.currency not in currencies:
                currencies.append(row.currency)

        stub = AccountAggregate(
            source=source,
            account_code=code,
            account_name=entries[0].account_name,
            usd_net=partial.usd_net if partial else Decimal("0.00"),
            usd_debit_total=partial.usd_debit_total if partial else Decimal("0.00"),
            usd_credit_total=partial.usd_credit_total if partial else Decimal("0.00"),
            dominant_side=partial.dominant_side if partial else "Debit",
            row_ids=tuple(r.row_id for r in entries),
            currencies=tuple(currencies),
            rate_by_row=partial.rate_by_row if partial else (),
        )
        if partial is not None:
            reason = (
                f"no FX rate for currency {','.join(missing)}; those rows cannot be "
                f"translated and are never guessed. The ${stub.usd_net:,.2f} shown is the "
                f"translatable portion only ({','.join(partial.currencies)}) and understates "
                f"this account until the missing rate is published"
            )
        else:
            reason = (
                f"no FX rate for currency {','.join(missing)}; rows cannot be translated "
                f"and are never guessed. No portion of this account is translatable, so no "
                f"dollar amount can be stated"
            )
        out[code] = decide(stub, None, MatchConfig(), force_suspense_reason=reason)
    return out


def _fmt(x: float) -> str:
    return f"{x:.4f}"


def _features_text(features: dict[str, float]) -> str:
    return ";".join(f"{k}={_fmt(v)}" for k, v in sorted(features.items()))


def decide(
    agg: AccountAggregate,
    matcher: Matcher | None,
    config: MatchConfig,
    source_balances: dict[str, Decimal] | None = None,
    force_suspense_reason: str | None = None,
) -> Decision:
    if force_suspense_reason is not None:
        return Decision(
            source=agg.source,
            account_code=agg.account_code,
            account_name=agg.account_name,
            disposition="SUSPENSE",
            tier="UNTRANSLATABLE",
            confidence=Decimal("0.0000"),
            mapped_code="",
            mapped_name="",
            runner_up_code="",
            runner_up_confidence=Decimal("0.0000"),
            margin=Decimal("0.0000"),
            features={},
            weights_used={},
            flags=("NO_FX_RATE",),
            reasons=(force_suspense_reason,),
            usd_net=agg.usd_net,
            row_ids=agg.row_ids,
        )

    if matcher is None:
        # matcher may only be omitted on the force_suspense path, which returned
        # above. Reaching here without one is a caller bug, not a data problem —
        # fail loudly rather than crash later with an opaque AttributeError.
        raise ValueError(
            f"decide() for {agg.source}:{agg.account_code} needs a Matcher unless "
            f"force_suspense_reason is given"
        )

    best, runners = matcher.match_aggregate(agg, source_balances)

    if best.tier == "EXACT_CODE":
        return Decision(
            source=agg.source,
            account_code=agg.account_code,
            account_name=agg.account_name,
            disposition="AUTO_APPLIED",
            tier=best.tier,
            confidence=best.confidence,
            mapped_code=best.node.account_code,
            mapped_name=best.node.account_name,
            runner_up_code="",
            runner_up_confidence=Decimal("0.0000"),
            margin=Decimal("1.0000"),
            features=dict(best.features),
            weights_used=dict(best.weights_used),
            flags=(),
            reasons=(
                f"{best.tier.lower()}: TB '{agg.account_name}' resolves deterministically to "
                f"COA {best.node.account_code} '{best.node.account_name}'",
            ),
            usd_net=agg.usd_net,
            row_ids=agg.row_ids,
            rate_notes=tuple(f"{c}:{o}" for c, o in agg.rate_by_row),
        )

    if best.node is None:
        return Decision(
            source=agg.source,
            account_code=agg.account_code,
            account_name=agg.account_name,
            disposition="SUSPENSE",
            tier="NO_CANDIDATE",
            confidence=Decimal("0.0000"),
            mapped_code="",
            mapped_name="",
            runner_up_code="",
            runner_up_confidence=Decimal("0.0000"),
            margin=Decimal("0.0000"),
            features={},
            weights_used={},
            flags=("NO_CANDIDATE",),
            reasons=(
                f"no COA leaf scored at or above review floor {config.review_min}; held in "
                f"suspense, not guessed",
            ),
            usd_net=agg.usd_net,
            row_ids=agg.row_ids,
        )

    margin = runner_up_margin(best, runners)
    runner = runners[0] if runners else None
    flags: list[str] = []
    reasons: list[str] = [
        f"tier={best.tier} confidence={best.confidence} margin={margin} "
        f"features[{_features_text(best.features)}]",
    ]

    balance_veto = (
        best.tier != "EXACT_CODE"
        and best.node is not None
        and best.node.normal_balance != agg.dominant_side
    )
    ambiguous_tie = (
        best.confidence >= config.auto_min
        and float(margin) < config.tie_epsilon
        and runner is not None
    )

    if balance_veto:
        flags.append("NORMAL_BALANCE_VETO")
        reasons.append(
            f"veto: proposed target {best.node.account_code} normal_balance="
            f"{best.node.normal_balance} conflicts with observed dominant side "
            f"{agg.dominant_side} (net {agg.usd_net}); auto-apply blocked"
        )
    if ambiguous_tie:
        assert runner is not None  # guaranteed by ambiguous_tie's own condition
        flags.append("AMBIGUOUS_TIE")
        reasons.append(
            f"tie: top candidate {best.node.account_code} leads {runner.node.account_code} by "
            f"only {margin} (< epsilon {config.tie_epsilon}); auto-apply blocked"
        )
    if not best.balance_evidence and best.tier == "FUZZY_COMPOSITE":
        reasons.append(
            "note: no cross-period balance evidence available for continuity feature; score "
            "renormalized over remaining weights"
        )
    if runner is not None and runner.node is not None:
        reasons.append(
            f"runner-up: {runner.node.account_code} '{runner.node.account_name}' at "
            f"{runner.confidence}"
        )

    if balance_veto or ambiguous_tie:
        disposition = "REVIEW"
    elif best.confidence >= config.auto_min:
        disposition = "AUTO_APPLIED"
        reasons.append(f"composite {best.confidence} >= auto threshold {config.auto_min}; applied")
    elif best.confidence >= config.review_min:
        disposition = "REVIEW"
        reasons.append(
            f"composite {best.confidence} within review band "
            f"[{config.review_min}, {config.auto_min}); queued for human sign-off"
        )
    else:
        disposition = "SUSPENSE"
        reasons.append(
            f"composite {best.confidence} below review floor {config.review_min}; held in "
            f"suspense"
        )

    return Decision(
        source=agg.source,
        account_code=agg.account_code,
        account_name=agg.account_name,
        disposition=disposition,
        tier=best.tier,
        confidence=best.confidence,
        mapped_code=best.node.account_code,
        mapped_name=best.node.account_name,
        runner_up_code=runner.node.account_code if runner is not None and runner.node else "",
        runner_up_confidence=runner.confidence if runner is not None else Decimal("0.0000"),
        margin=margin,
        features=dict(best.features),
        weights_used=dict(best.weights_used),
        flags=tuple(flags),
        reasons=tuple(reasons),
        usd_net=agg.usd_net,
        row_ids=agg.row_ids,
        rate_notes=tuple(f"{c}:{o}" for c, o in agg.rate_by_row),
    )
