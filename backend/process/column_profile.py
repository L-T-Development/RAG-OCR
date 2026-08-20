"""
Value-shape column detection — finding the part column when its *name* is unknown.
================================================================================

`field_schema.resolve_header` matches a column by its header text. That covers
every label we have seen, but a new document family can always invent another
("Works P/N", "Ident No", "Sach-Nr."), and a continuation page can lose its header
row entirely and end up with `Column_3`. In both cases the comparison fails with
"Column Not Found" even though the data is right there.

This module answers the same question from the other side: *which column contains
values shaped like part numbers?* It is deliberately a *fallback* — header
resolution is more precise and stays first — and it is deterministic and
inspectable: each candidate gets a score built from counted properties, and the
winner must clear an absolute threshold, so "no idea" stays possible.

    profile_column(values)          → {field: score in 0..1}
    detect_column(field, columns)   → (header, score, why) or None
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .field_schema import is_empty_value, normalize_value

# ── Value shapes ───────────────────────────────────────────────────────────────

_NSN_RE = re.compile(r"^\d{4}[- ]?\d{2}[- ]?\d{3}[- ]?\d{4}$")
_CODEY_RE = re.compile(r"^(?=.*\d)[A-Z0-9][A-Z0-9\-/_. ]{2,63}$")
_SERIAL_RE = re.compile(r"^\(?\d{1,4}\)?[.)]?$")
_QTY_RE = re.compile(r"^\d{1,4}(\.\d{1,2})?$")
_WORDY_RE = re.compile(r"^[A-Z][A-Z\s,()/&.\-]{3,}$")


def _digit_ratio(v: str) -> float:
    return sum(c.isdigit() for c in v) / len(v) if v else 0.0


def _clean(values: Iterable[str]) -> List[str]:
    out = []
    for v in values:
        if v is None:
            continue
        s = normalize_value(v)
        if s and not is_empty_value(s):
            out.append(s)
    return out


def profile_column(values: Sequence[str]) -> Dict[str, float]:
    """
    Score one column's values for each canonical concept, in 0..1.

    Scores are fractions of the column's non-empty values that match a shape,
    adjusted by distinctness — an identifier column is mostly distinct values,
    while a quantity column repeats "1" hundreds of times.
    """
    vals = _clean(values)
    n = len(vals)
    if n < 3:
        return {}

    distinct = len(set(vals)) / n
    codey = sum(bool(_CODEY_RE.match(v)) for v in vals) / n
    nsn = sum(bool(_NSN_RE.match(v)) for v in vals) / n
    serial = sum(bool(_SERIAL_RE.match(v)) for v in vals) / n
    qty = sum(bool(_QTY_RE.match(v)) for v in vals) / n
    wordy = sum(bool(_WORDY_RE.match(v)) for v in vals) / n
    has_alpha = sum(any(c.isalpha() for c in v) for v in vals) / n
    long_enough = sum(len(v) >= 5 for v in vals) / n
    mid_digits = sum(0.2 <= _digit_ratio(v) <= 0.95 for v in vals) / n

    # A part number: code-shaped, long enough, mostly distinct, and not a plain
    # 1..N counter. Serial columns are code-shaped too, hence the explicit penalty.
    part = codey * long_enough * (0.35 + 0.65 * distinct) * (1.0 - serial)
    part *= (0.6 + 0.4 * mid_digits)

    return {
        "part_no": round(min(part, 1.0), 3),
        "nsn": round(nsn, 3),
        "drawing_no": round(min(codey * long_enough * has_alpha * distinct, 1.0), 3),
        "qty": round(min(qty * (1.0 - distinct), 1.0), 3),
        "serial": round(serial, 3),
        "nomenclature": round(wordy, 3),
        "_distinct": round(distinct, 3),
    }


_MIN_SCORE = {"part_no": 0.45, "drawing_no": 0.45, "nsn": 0.5,
              "nomenclature": 0.5, "qty": 0.5, "serial": 0.6}


def detect_column(field: str, columns: Dict[str, Sequence[str]],
                  exclude: Iterable[str] = ()) -> Optional[Tuple[str, float, str]]:
    """
    Best column for `field` judged only by its values.

    `columns` is {header: values}. Returns (header, score, explanation) or None
    when nothing clears the threshold — "no idea" is a valid, and safer, answer.
    """
    skip = {str(c) for c in exclude}
    scored = []
    for header, values in columns.items():
        if str(header) in skip or str(header).startswith("_"):
            continue
        p = profile_column(values)
        if p.get(field):
            scored.append((p[field], str(header), p))
    if not scored:
        return None
    scored.sort(reverse=True)
    score, header, prof = scored[0]
    if score < _MIN_SCORE.get(field, 0.5):
        return None
    # Require a clear winner: an ambiguous tie between two columns is not a
    # confident answer, and guessing wrong is worse than reporting "not found".
    if len(scored) > 1 and scored[1][0] > score * 0.85:
        return None
    why = (f"values look like {field.replace('_', ' ')} "
           f"({int(prof.get('_distinct', 0) * 100)}% distinct, score {score:.2f})")
    return header, score, why


def identifier_columns(columns: Dict[str, Sequence[str]],
                       limit: int = 5) -> List[Tuple[str, str]]:
    """
    Columns that *hold identifiers*, best first, as (header, why).

    This is what value shape can honestly establish. It cannot reliably tell a
    part number from a stock number or a drawing number — measured on real MRLS /
    ISPL pairs, an `NSN Nos.` column outscores the actual part column, because
    both are long, distinct, code-shaped values. So this never picks a column on
    the user's behalf; it powers a *suggestion* when header resolution fails
    ("these columns hold identifiers — name one explicitly"), leaving the choice
    with the person who can read the document.
    """
    out = []
    for header, values in columns.items():
        if str(header).startswith("_"):
            continue
        p = profile_column(values)
        if not p:
            continue
        score = max(p.get("part_no", 0), p.get("drawing_no", 0), p.get("nsn", 0))
        if score >= 0.4 and p.get("serial", 0) < 0.5:
            kind = ("stock numbers" if p.get("nsn", 0) >= 0.5 else "identifiers")
            out.append((score, str(header),
                        f"{kind}, {int(p.get('_distinct', 0) * 100)}% distinct"))
    out.sort(reverse=True)
    return [(h, why) for _s, h, why in out[:limit]]


def looks_like_counter(values: Sequence[str]) -> bool:
    """True if a column is a 1..N serial counter — never a part identifier."""
    p = profile_column(values)
    return bool(p) and p.get("serial", 0) >= 0.7


def columns_from_frames(dfs) -> Dict[str, List[str]]:
    """{header: all values} across a document's DataFrames (pandas, from the engine)."""
    import pandas as pd
    out: Dict[str, List[str]] = {}
    for df in dfs:
        for c in df.columns:
            if str(c).startswith("_"):
                continue
            vals = [str(v) for v in df[c].tolist() if pd.notna(v)]
            out.setdefault(str(c), []).extend(vals)
    return out
