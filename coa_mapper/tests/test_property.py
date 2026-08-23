from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from coa_mapper.fx import aggregate_rows
from coa_mapper.models import FxRates, TbRow

codes = st.sampled_from(["1110", "1120", "6900", "9998", "7777"])
currencies = st.sampled_from(["USD", "EUR", "GBP"])
amounts = st.decimals(
    min_value=-10_000_000,
    max_value=10_000_000,
    allow_nan=False,
    allow_infinity=False,
    places=2,
)

RATES = FxRates(
    average={"EUR": Decimal("1.082"), "GBP": Decimal("1.264")},
    period_end={"EUR": Decimal("1.095")},
)


def _to_rows(triples):
    rows = []
    for idx, (code, currency, amount) in enumerate(triples, start=2):
        if amount >= 0:
            debit, credit = amount, Decimal("0")
        else:
            debit, credit = Decimal("0"), -amount
        rows.append(
            TbRow(
                source="prop",
                line_no=idx,
                row_id=f"prop:{idx}",
                account_code=code,
                account_name=f"Account {code}",
                currency=currency,
                debit=debit,
                credit=credit,
            )
        )
    return rows


@settings(max_examples=50, deadline=None)
@given(data=st.data())
def test_partition_and_total_invariants(data):
    triples = data.draw(st.lists(st.tuples(codes, currencies, amounts), min_size=1, max_size=40))
    rows = _to_rows(triples)
    aggregates, findings, total_abs, untranslatable = aggregate_rows("prop", rows, RATES)
    del findings

    covered_codes = {agg.account_code for agg in aggregates} | untranslatable
    input_codes = {row.account_code for row in rows}
    assert covered_codes == input_codes

    per_code: dict[str, Decimal] = {}
    for row in rows:
        resolved = RATES.resolve(row.currency)
        assert resolved is not None or row.currency not in ("USD", "EUR", "GBP")
        if resolved is None:
            continue
        rate, _ = resolved
        # ROUND_HALF_UP is the money convention the pipeline documents and uses.
        # A bare quantize() here would assert banker's rounding instead, and a
        # .xx5 amount (595.00 x 1.095 = 651.525) makes the two disagree by a cent.
        net = ((row.debit - row.credit) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        per_code[row.account_code] = per_code.get(row.account_code, Decimal("0")) + net

    recomputed_abs = sum((abs(v) for v in per_code.values()), Decimal("0"))
    assert recomputed_abs == total_abs

    agg_by_code = {agg.account_code: agg for agg in aggregates}
    for code, expected_net in per_code.items():
        assert agg_by_code[code].usd_net == expected_net


@settings(max_examples=25, deadline=None)
@given(data=st.data())
def test_untranslatable_currencies_routed_not_dropped(data):
    rows = _to_rows(
        data.draw(st.lists(st.tuples(codes, st.just("JPY"), amounts), min_size=1, max_size=10))
    )
    aggregates, findings, _, untranslatable = aggregate_rows("prop", rows, RATES)
    del aggregates
    codes_untranslated = {row.account_code for row in rows}
    assert untranslatable == codes_untranslated
    assert any(f.code == "CURRENCY_NO_RATE" for f in findings)
