from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from .models import AccountAggregate, Finding, FxRates, TbRow

CENT = Decimal("0.01")


def to_usd(amount: Decimal, rate: Decimal) -> Decimal:
    return (amount * rate).quantize(CENT, rounding=ROUND_HALF_UP)


def row_translation_table(rows: Iterable[TbRow], rates: FxRates) -> dict[str, tuple[Decimal, str]]:
    table: dict[str, tuple[Decimal, str]] = {}
    for row in rows:
        resolved = rates.resolve(row.currency)
        if resolved is not None:
            table[row.row_id] = resolved
    return table


def aggregate_rows(
    source: str,
    rows: Iterable[TbRow],
    rates: FxRates,
) -> tuple[list[AccountAggregate], list[Finding], Decimal, set[str]]:
    findings: list[Finding] = []
    untranslatable: list[TbRow] = []
    resolved: list[tuple[TbRow, Decimal, str]] = []
    fallback_currencies: dict[str, list[str]] = {}
    for row in rows:
        resolved_rate = rates.resolve(row.currency)
        if resolved_rate is None:
            untranslatable.append(row)
            continue
        rate, origin = resolved_rate
        if origin == "period_average_fallback":
            codes = fallback_currencies.setdefault(row.currency, [])
            if row.account_code not in codes:
                codes.append(row.account_code)
        resolved.append((row, rate, origin))

    for currency in sorted(fallback_currencies):
        code_list = ",".join(sorted(fallback_currencies[currency]))
        findings.append(
            Finding(
                "FX_PERIOD_END_FALLBACK",
                f"currency {currency}: no period_end rate; translated at period_average "
                f"fallback for accounts [{code_list}]; provisional",
                (f"fx:{currency}",),
            )
        )
    for row in sorted(untranslatable, key=lambda r: r.row_id):
        findings.append(
            Finding(
                "CURRENCY_NO_RATE",
                f"{row.row_id} account {row.account_code}: no FX rate for currency "
                f"{row.currency}; row routed to suspense, never guessed",
                (row.row_id,),
            )
        )

    grouped: dict[str, list[tuple[TbRow, Decimal, str]]] = {}
    for row, rate, origin in resolved:
        grouped.setdefault(row.account_code, []).append((row, rate, origin))

    aggregates: list[AccountAggregate] = []
    total_abs = Decimal("0")
    for code in sorted(grouped):
        entries = grouped[code]
        names = {e[0].account_name for e in entries}
        if len(names) > 1:
            findings.append(
                Finding(
                    "INCONSISTENT_NAMES",
                    f"{source} account {code}: {len(names)} distinct names across rows "
                    f"{sorted(names)!r}",
                    (f"{source}:{code}",),
                )
            )
        usd_debit_total = Decimal("0")
        usd_credit_total = Decimal("0")
        row_ids: list[str] = []
        currencies: list[str] = []
        rate_notes: list[tuple[str, str]] = []
        per_currency_seen: dict[str, int] = {}
        for row, rate, origin in entries:
            usd_debit_total += to_usd(row.debit, rate)
            usd_credit_total += to_usd(row.credit, rate)
            row_ids.append(row.row_id)
            if row.currency not in currencies:
                currencies.append(row.currency)
            rate_notes.append((row.currency, origin))
            per_currency_seen[row.currency] = per_currency_seen.get(row.currency, 0) + 1
        for currency, count in sorted(per_currency_seen.items()):
            if count > 1:
                findings.append(
                    Finding(
                        "DUP_ACCOUNT_CURRENCY",
                        f"{source} account {code} currency {currency}: {count} rows with same "
                        f"code+currency; summed per convention but flagged as double-post "
                        f"signature",
                        (f"{source}:{code}", currency),
                    )
                )
        net = (usd_debit_total - usd_credit_total).quantize(CENT, rounding=ROUND_HALF_UP)
        dominant = "Debit" if net >= 0 else "Credit"
        aggregate = AccountAggregate(
            source=source,
            account_code=code,
            account_name=entries[0][0].account_name,
            usd_net=net,
            # Half-up, explicitly. A bare quantize() defaults to banker's rounding,
            # so a .xx5 total rounded here disagreed with the same figure rounded
            # half-up two lines above: 595.00 x 1.095 = 651.525 became net 651.53
            # but debit_total 651.52. Hypothesis found it; one convention only.
            usd_debit_total=usd_debit_total.quantize(CENT, rounding=ROUND_HALF_UP),
            usd_credit_total=usd_credit_total.quantize(CENT, rounding=ROUND_HALF_UP),
            dominant_side=dominant,
            row_ids=tuple(row_ids),
            currencies=tuple(currencies),
            rate_by_row=tuple(rate_notes),
        )
        aggregates.append(aggregate)
        total_abs += abs(net)

    untranslatable_codes = {row.account_code for row in untranslatable}
    return aggregates, findings, total_abs, untranslatable_codes
