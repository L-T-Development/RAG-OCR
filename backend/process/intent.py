"""
What is this question asking us to compare?
================================================================================

Both chat routers used to answer that with overlapping keyword lists — seventeen
words here, nine there, a "strict assessment" rule, a mention-phrase rule, an
assessment-terms rule. Each list was added to catch a phrasing that had failed, and
together they had three problems: a question could match one router's list and not
the other's, adding a word to one branch could steal queries from another, and when
nothing matched the only recourse was to tell the user to "use this exact format".

This module replaces those lists with one parse. It reads a question once and
returns everything a comparison needs — which documents, which concept, which
columns if the user named them outright, and what kind of answer is wanted — plus
the evidence it used, so a routing decision can be explained instead of guessed at.

    parse(query, available_files=…, doc_count=…) → ComparisonIntent

It is deliberately deterministic. An LLM pass for genuinely ambiguous questions was
considered and left out: it would make routing non-reproducible and slow, and the
comparison wizard (ComparePanel) now covers the case where words fail, by letting
someone point at the documents and columns directly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .field_schema import CANONICAL_FIELDS, canonical_field_for_query

# ── Vocabulary ────────────────────────────────────────────────────────────────
# Words that say "hold two things side by side", in any phrasing users actually use.
_COMPARE_WORDS = (
    "compare", "comparison", "comparing", "difference", "differences", "differ",
    "diff", "versus", " vs ", " vs.", "contrast", "mismatch", "match between",
    "cross-check", "cross check", "crosscheck", "reconcile", "tally",
)
# Words that ask whether something is *there*.
_PRESENCE_WORDS = (
    "missing", "not in", "only in", "absent", "present", "presence of", "found",
    "not found", "exists", "existing in", "available in", "covered in", "listed in",
    "included in", "appear", "appears", "mentioned", "mention", "anywhere",
    "referenced", "referred",
)
# Words that ask us to check, without naming the operation.
_ASSESS_WORDS = (
    "assessment", "assess", "confirm", "verify", "check", "whether", "validate",
    "audit", "ensure",
)
# "…in every one of these documents"
_ALL_FILES_RE = re.compile(
    r"\b(?:all|every|each|both)\s+(?:the\s+|of\s+the\s+|other\s+)*"
    r"(?:files?|documents?|docs?|pdfs?|manuals?|sources?)\b", re.I)
_QUOTED_RE = re.compile(r'["“”]([^"“”]{2,60})["“”]')

_TYPE_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("all", ("present or not", "present/not", "found or not found", "found or not",
             "similar", "similarity", "same", "assessment", "assess", "confirm",
             "whether", "in there or not", "exists or not")),
    ("difference", ("difference", "not in", "missing", "only in", "absent")),
    ("common", ("common", "in both", "shared", "overlap")),
    ("unique_both", ("unique to each", "unique")),
)

# Phrasings that mean "search the whole document, not a matching column".
_TEXT_MODE_WORDS = (
    "mentioned", "mention", "anywhere", "appear in", "appears in", "referenced",
    "referred", "in the text", "full text", "covered in", "listed in",
)


@dataclass
class ComparisonIntent:
    """What a question asks for. `is_comparison` is the routing decision."""
    is_comparison: bool = False
    files: List[str] = field(default_factory=list)
    all_files: bool = False
    concept: str = "part"
    concept_field: Optional[str] = None
    columns: Tuple[Optional[str], Optional[str]] = (None, None)
    prefer_literal: bool = False
    mode: str = "columns"                 # "columns" | "mentions"
    comparison_type: str = "all"
    match_any_column: bool = False
    evidence: List[str] = field(default_factory=list)

    @property
    def named_two_files(self) -> bool:
        return len(self.files) >= 2

    def describe(self) -> str:
        """One line, for logs — why this was or was not treated as a comparison."""
        return (f"comparison={self.is_comparison} concept={self.concept!r} "
                f"mode={self.mode} type={self.comparison_type} "
                f"files={self.files or ('ALL' if self.all_files else [])} "
                f"because[{', '.join(self.evidence) or 'nothing'}]")


def _has(query_lower: str, words: Sequence[str]) -> Optional[str]:
    for w in words:
        if w in query_lower:
            return w.strip()
    return None


def _find_concept(query: str) -> Tuple[str, Optional[str]]:
    """
    The concept being compared, taken from the schema's own vocabulary rather than a
    list maintained here — so teaching `field_schema.json` a new word for "part"
    teaches the router too.

    Returns (term as the user wrote it, canonical field) and defaults to "part",
    which is what a spares comparison means when nobody says otherwise.
    """
    ql = f" {query.lower()} "
    best: Tuple[int, str, str] = (0, "", "")
    for canonical, words in CANONICAL_FIELDS.items():
        for word in words:
            w = word.lower()
            # Whole-word-ish: avoid "part" inside "partial", "qty" inside "qtybox".
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", ql):
                if len(w) > best[0]:
                    best = (len(w), word, canonical)
    if best[0]:
        return best[1], best[2]
    return "part", "part_no"


def parse(query: str, available_files: Optional[Sequence[str]] = None,
          doc_count: Optional[int] = None) -> ComparisonIntent:
    """
    Read a question once and return what it asks for.

    `available_files` (filenames in scope) lets "compare all the documents" and
    plain-name mentions resolve; `doc_count` lets a question with no filenames at all
    still be recognised as a comparison when the thread obviously holds a pair.
    """
    from .comparison import mentioned_files          # local: avoids an import cycle

    q = query or ""
    ql = q.lower()
    intent = ComparisonIntent()

    # ── what documents ────────────────────────────────────────────────────────
    intent.files = mentioned_files(q)
    intent.all_files = bool(_ALL_FILES_RE.search(q)) and not intent.files
    if intent.all_files and available_files:
        intent.files = list(available_files)
        intent.evidence.append("all-documents")
    elif intent.files:
        intent.evidence.append(f"{len(intent.files)} file(s) named")

    # ── what to compare ───────────────────────────────────────────────────────
    quoted = [t.strip() for t in _QUOTED_RE.findall(q)
              if t.strip() and not t.strip().lower().endswith(
                  (".pdf", ".xlsx", ".xls", ".docx"))]
    if quoted:
        intent.columns = (quoted[0], quoted[1] if len(quoted) > 1 else None)
        intent.prefer_literal = True
        intent.concept = quoted[0]
        intent.concept_field = canonical_field_for_query(quoted[0])
        intent.evidence.append("column named in quotes")
    else:
        intent.concept, intent.concept_field = _find_concept(q)
        if intent.concept_field:
            intent.evidence.append(f"concept={intent.concept_field}")

    # ── what kind of answer ───────────────────────────────────────────────────
    for label, words in _TYPE_RULES:
        if _has(ql, words):
            intent.comparison_type = label
            break

    if _has(ql, _TEXT_MODE_WORDS):
        intent.mode = "mentions"
        intent.evidence.append("asks about mentions")

    intent.match_any_column = any(p in ql for p in (
        "any column", "to any column", "with contents", "against contents",
        "match in any column", "compare this column"))

    # ── is this a comparison at all ───────────────────────────────────────────
    compare_word = _has(ql, _COMPARE_WORDS)
    presence_word = _has(ql, _PRESENCE_WORDS)
    assess_word = _has(ql, _ASSESS_WORDS)
    if compare_word:
        intent.evidence.append(f"says {compare_word!r}")
    if presence_word:
        intent.evidence.append(f"says {presence_word!r}")
    if assess_word and not (compare_word or presence_word):
        intent.evidence.append(f"says {assess_word!r}")

    asks_something = bool(compare_word or presence_word or assess_word)
    enough_documents = (len(intent.files) >= 2 or intent.all_files
                        or (doc_count or 0) >= 2)

    # Two documents named plus any comparing/presence word is unambiguous. So is
    # "compare X across all the documents". Without named files we need both an
    # explicit ask and a concept, so an ordinary question about one part number
    # ("what is XL17461?") still goes to retrieval.
    if asks_something and len(intent.files) >= 2:
        intent.is_comparison = True
    elif asks_something and intent.all_files:
        intent.is_comparison = True
    elif (compare_word or presence_word) and intent.concept_field and enough_documents:
        intent.is_comparison = True
    elif assess_word and intent.concept_field and enough_documents and (
            presence_word or "or not" in ql or intent.mode == "mentions"):
        intent.is_comparison = True

    if not intent.is_comparison:
        intent.evidence.append("no comparison intent")
    return intent
