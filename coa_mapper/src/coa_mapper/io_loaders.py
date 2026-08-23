from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import CoaNode, Finding, FxRates, TbRow

TB_COLUMNS = {"account_code", "account_name", "currency", "debit", "credit"}
COA_COLUMNS = {
    "account_code",
    "account_name",
    "account_type",
    "parent_code",
    "statement",
    "cf_category",
    "normal_balance",
}
FX_COLUMNS = {"currency", "rate_type", "rate", "period"}


def _read_rows(path: Path) -> tuple[list[dict[str, str]], Finding | None]:
    if not path.exists():
        return [], Finding("SCHEMA_MISSING_COLUMN", f"input file not found: {path}", (str(path),))
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = set(reader.fieldnames or [])
        required = (
            TB_COLUMNS
            if path.name.startswith(("trial_balance", "prior_period_tb"))
            else COA_COLUMNS if path.name.startswith("chart_of_accounts") else FX_COLUMNS
        )
        absent = sorted(required - header)
        if absent:
            return [], Finding(
                "SCHEMA_MISSING_COLUMN",
                f"{path.name}: missing columns {absent}",
                (path.name,),
            )
        rows = list(reader)
        if not rows:
            return [], Finding("SCHEMA_EMPTY_FILE", f"{path.name}: no data rows", (path.name,))
        return rows, None


def _decimal(value: str) -> Decimal | None:
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        return None
    if not parsed.is_finite():
        return None
    return parsed


def load_tb(path: Path, source: str) -> tuple[list[TbRow], list[Finding]]:
    raw, fatal = _read_rows(path)
    if fatal is not None:
        return [], [fatal]
    rows: list[TbRow] = []
    findings: list[Finding] = []
    for idx, rec in enumerate(raw, start=2):
        debit = _decimal(rec["debit"])
        credit = _decimal(rec["credit"])
        if debit is None or credit is None:
            findings.append(
                Finding(
                    "SCHEMA_BAD_NUMBER",
                    f"{path.name}:{idx} account {rec['account_code']}: non-numeric amount "
                    f"debit={rec['debit']!r} credit={rec['credit']!r}; row refused",
                    (f"{source}:{idx}",),
                )
            )
            continue
        code = rec["account_code"].strip()
        currency = rec["currency"].strip().upper()
        name = rec["account_name"].strip()
        row = TbRow(
            source=source,
            line_no=idx,
            row_id=f"{source}:{idx}",
            account_code=code,
            account_name=name,
            currency=currency,
            debit=debit,
            credit=credit,
        )
        rows.append(row)
        if debit != 0 and credit != 0:
            findings.append(
                Finding(
                    "BOTH_SIDES_NONZERO",
                    f"{row.row_id} account {code} ({currency}): both debit={debit} and "
                    f"credit={credit} nonzero; netting to {debit - credit}",
                    (row.row_id,),
                )
            )
    return rows, findings


def load_coa(path: Path) -> tuple[list[CoaNode], list[Finding]]:
    raw, fatal = _read_rows(path)
    if fatal is not None:
        return [], [fatal]
    nodes: list[CoaNode] = []
    findings: list[Finding] = []
    seen: dict[str, int] = {}
    for _idx, rec in enumerate(raw, start=2):
        code = normalize_code_key(rec["account_code"])
        seen[code] = seen.get(code, 0) + 1
        nodes.append(
            CoaNode(
                account_code=code,
                account_name=rec["account_name"].strip(),
                account_type=rec["account_type"].strip(),
                parent_code=normalize_code_key(rec["parent_code"]),
                statement=rec["statement"].strip(),
                cf_category=rec["cf_category"].strip(),
                normal_balance=rec["normal_balance"].strip().capitalize() or "Debit",
            )
        )
    for code, count in sorted(seen.items()):
        if count > 1:
            findings.append(
                Finding(
                    "COA_DUPLICATE_CODE",
                    f"{path.name}: account code {code} defined {count} times; COA index ambiguous",
                    (code,),
                )
            )
    return nodes, findings


def normalize_code_key(code: str) -> str:
    stripped = code.strip()
    if stripped.isdigit():
        return stripped.zfill(4)
    return stripped


def load_fx(path: Path) -> tuple[FxRates, list[Finding]]:
    raw, fatal = _read_rows(path)
    if fatal is not None:
        return FxRates(average={}, period_end={}), [fatal]
    average: dict[str, Decimal] = {}
    period_end: dict[str, Decimal] = {}
    findings: list[Finding] = []
    for idx, rec in enumerate(raw, start=2):
        rate = _decimal(rec["rate"])
        currency = rec["currency"].strip().upper()
        kind = rec["rate_type"].strip()
        if rate is None or rate <= 0:
            findings.append(
                Finding(
                    "SCHEMA_BAD_NUMBER",
                    f"{path.name}:{idx} currency {currency}: invalid rate {rec['rate']!r}",
                    (f"fx:{idx}",),
                )
            )
            continue
        if kind == "period_average":
            average[currency] = rate
        elif kind == "period_end":
            period_end[currency] = rate
        else:
            findings.append(
                Finding(
                    "FX_UNKNOWN_RATE_TYPE",
                    f"{path.name}:{idx} currency {currency}: rate_type {kind!r} not consumed "
                    f"by mapping policy (point-in-time balances use period_end); ignored",
                    (f"fx:{idx}",),
                )
            )
    return FxRates(average=average, period_end=period_end), findings
