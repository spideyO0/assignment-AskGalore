from __future__ import annotations

import re
import unicodedata

STOPWORDS = {"and", "the", "of"}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_name(name: str) -> str:
    lowered = unicodedata.normalize("NFKC", name).casefold()
    return _NON_ALNUM.sub(" ", lowered).strip()


def significant_tokens(name: str) -> frozenset[str]:
    return frozenset(
        tok for tok in normalize_name(name).split() if len(tok) > 1 and tok not in STOPWORDS
    )


def canonical_key(name: str) -> str:
    return " ".join(
        tok for tok in normalize_name(name).split() if len(tok) > 1 and tok not in STOPWORDS
    )


def normalize_code(code: str) -> str:
    stripped = code.strip()
    if stripped.isdigit():
        return stripped.zfill(4)
    return stripped
