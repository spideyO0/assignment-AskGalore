from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class Severity(StrEnum):
    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"


FINDING_CODES = {
    "SCHEMA_MISSING_COLUMN": Severity.ERROR,
    "SCHEMA_BAD_NUMBER": Severity.ERROR,
    "SCHEMA_EMPTY_FILE": Severity.ERROR,
    "COA_DUPLICATE_CODE": Severity.ERROR,
    # A parent cycle is unrecoverable, not advisory: any rollup walking parent
    # links recurses forever. ERROR so the run exits 2 rather than reporting a
    # structurally impossible chart as merely worth reviewing.
    "COA_PARENT_CYCLE": Severity.ERROR,
    "COA_PARENT_MISSING": Severity.WARN,
    "SUSPENSE_RATE_EXCEEDED": Severity.ERROR,
    "CURRENCY_NO_RATE": Severity.ERROR,
    "FX_UNKNOWN_RATE_TYPE": Severity.INFO,
    "BOTH_SIDES_NONZERO": Severity.WARN,
    "DUP_ACCOUNT_CURRENCY": Severity.WARN,
    "INCONSISTENT_NAMES": Severity.WARN,
    "ORPHAN_TB_ACCOUNT": Severity.WARN,
    "FX_PERIOD_END_FALLBACK": Severity.WARN,
    "NORMAL_BALANCE_VETO": Severity.WARN,
    "AMBIGUOUS_TIE": Severity.WARN,
    "COA_TBD_CATEGORY": Severity.INFO,
    "COA_CHILDLESS_HEADER": Severity.INFO,
    "COA_ROOT_LEAF": Severity.INFO,
}


@dataclass(frozen=True)
class Finding:
    code: str
    message: str
    refs: tuple[str, ...] = ()

    @property
    def severity(self) -> Severity:
        return FINDING_CODES.get(self.code, Severity.WARN)

    def sort_key(self) -> tuple[int, str]:
        order = {Severity.ERROR: 0, Severity.WARN: 1, Severity.INFO: 2}
        return (order[self.severity], self.code + "|" + self.message)


@dataclass(frozen=True)
class TbRow:
    source: str
    line_no: int
    row_id: str
    account_code: str
    account_name: str
    currency: str
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class CoaNode:
    account_code: str
    account_name: str
    account_type: str
    parent_code: str
    statement: str
    cf_category: str
    normal_balance: str

    @property
    def is_header(self) -> bool:
        return self.account_type == "Header"


@dataclass(frozen=True)
class FxRates:
    average: dict[str, Decimal]
    period_end: dict[str, Decimal]

    def resolve(self, currency: str) -> tuple[Decimal, str] | None:
        if currency == "USD":
            return Decimal("1"), "usd_functional"
        if currency in self.period_end:
            return self.period_end[currency], "period_end"
        if currency in self.average:
            return self.average[currency], "period_average_fallback"
        return None


@dataclass(frozen=True)
class AccountAggregate:
    source: str
    account_code: str
    account_name: str
    usd_net: Decimal
    usd_debit_total: Decimal
    usd_credit_total: Decimal
    dominant_side: str
    row_ids: tuple[str, ...]
    currencies: tuple[str, ...]
    rate_by_row: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CandidateScore:
    node: CoaNode
    tier: str
    confidence: Decimal
    features: dict[str, float]
    weights_used: dict[str, float]
    balance_evidence: bool


@dataclass(frozen=True)
class Decision:
    source: str
    account_code: str
    account_name: str
    disposition: str
    tier: str
    confidence: Decimal
    mapped_code: str
    mapped_name: str
    runner_up_code: str
    runner_up_confidence: Decimal
    margin: Decimal
    features: dict[str, float] = field(default_factory=dict)
    weights_used: dict[str, float] = field(default_factory=dict)
    flags: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    usd_net: Decimal = Decimal("0")
    row_ids: tuple[str, ...] = ()
    rate_notes: tuple[str, ...] = ()


@dataclass
class SourceResult:
    source: str
    decisions: list[Decision]
    aggregates: list[AccountAggregate]
    input_row_count: int
    input_usd_abs_total: Decimal
