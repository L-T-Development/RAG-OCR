"""
Canonical field registry + per-category header schema.
================================================================================

WHY THIS EXISTS
---------------
The same real-world concept is labelled differently in every document type:

    concept "part identifier"
        MRLS  page calls it →  "Manufacturer's Part No."
        ISPL  page calls it →  "DS Cat No."  (or "Manufacturer's Part No.")
        a Catalog might call it → "Part No" / "Item Code" / "P/N"

When a user asks to *"compare part"*, we must translate that single request into
the correct real column **for each document, according to its category**. Naive
substring matching ("does the header contain the word 'part'?") fails the moment a
document uses a different label (e.g. ISPL "DS Cat No.").

HOW IT WORKS
------------
1. CANONICAL_FIELDS   — the internal, standard field names + the words a user might
                        type to mean each one. ("part", "p/n" → part_no)
2. CATEGORY_SCHEMA    — per document category, each canonical field → an ORDERED list
                        of header patterns (case-insensitive substrings). Order = priority.
3. resolve_header()   — given (user term, a table's real headers, the doc category),
                        returns the actual header string to use, or None.

TO EXTEND
---------
Add a new document type by adding a key to CATEGORY_SCHEMA. Add a new comparable
concept by adding a key to CANONICAL_FIELDS *and* an entry under each category.
Patterns are matched as lowercased substrings, so "manufacturer's part no" also
matches "Manufacturer's Part No.\n(block letters)" etc.
"""

import re

# Unify the many quote/apostrophe glyphs PDFs use so pattern matching is stable.
# e.g. curly "Manufacturer's" (U+2019) vs straight "Manufacturer's" (U+0027).
_QUOTE_MAP = {"’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'",
              "“": '"', "”": '"'}
_QUOTE_RE = re.compile("|".join(map(re.escape, _QUOTE_MAP)))


def _canon(text) -> str:
    """Lowercase, unify quote glyphs, and collapse whitespace for robust matching."""
    s = _QUOTE_RE.sub(lambda m: _QUOTE_MAP[m.group()], str(text).lower())
    return re.sub(r"\s+", " ", s).strip()


def _canon_loose(text) -> str:
    """As _canon, but punctuation becomes a separator, so a name the user typed
    matches the header however either side punctuates it:
    "Firms part no." / "Firms Part No" / "FIRM'S PART-NO." → "firms part no"."""
    return re.sub(r"[^a-z0-9]+", " ", _canon(text)).strip()


# ── 1. Canonical fields: internal name → words a user might type for it ──────────
# Used to turn a free-text column word from the query ("part", "drawing no") into a
# canonical field key. Keep the words lowercase.
CANONICAL_FIELDS = {
    "part_no":      ["part", "part no", "part number", "part.no", "partno", "p/n", "pn",
                     "cat no", "ds cat", "catalogue no", "item code"],
    "nomenclature": ["nomenclature", "description", "designation", "name", "desc"],
    "drawing_no":   ["drg", "drg no", "drawing", "drawing no", "dwg", "dwg no"],
    "nsn":          ["nsn", "n.s.n", "stock number", "national stock"],
    "qty":          ["qty", "quantity", "qnty", "no off", "no. off", "total qty"],
    "serial":       ["sr", "sr no", "sl", "sl no", "serial", "serial no"],
    "reference":    ["ref", "reference", "ref no", "para ref", "ispl ref", "cct ref",
                     "fig", "figure", "item no"],
}

# ── 2. Per-category schema: category → canonical field → ordered header patterns ─
# The FIRST pattern that matches a real header in the table wins. Put the most
# doc-type-specific / most-preferred header first.
CATEGORY_SCHEMA = {
    # 🔧 MRLS — Maintenance Repair List of Spares
    "mrls": {
        "part_no":      ["manufacturer's part no", "manufacturer part no", "part no", "part"],
        "nomenclature": ["nomenclature", "description"],
        "drawing_no":   ["ispl ref", "figure no"],
        "qty":          ["total qty", "qty"],
        "serial":       ["sr. no", "sr no", "sl no"],
        "reference":    ["ispl ref", "figure"],
    },

    # 📋 ISPL — Illustrated Spare Parts List
    "ispl": {
        # Prefer Manufacturer's Part No. (shared with MRLS → parts line up), then DS Cat No.
        "part_no":      ["manufacturer's part no", "manufacturer part no", "ds cat no", "part no"],
        "nomenclature": ["description", "nomenclature"],
        "drawing_no":   ["fig", "item"],
        "nsn":          ["ds cat no"],
        "qty":          ["no. off", "no off", "qty"],
        "serial":       ["sl. no", "sl no", "sr no"],
        "reference":    ["para ref", "cct ref", "fig", "item"],
    },

    # 📚 Catalog — Parts Catalogue
    "catalog": {
        "part_no":      ["part no", "part number", "cat no", "item code", "p/n", "part"],
        "nomenclature": ["description", "nomenclature", "item name", "part name"],
        "drawing_no":   ["drg", "drawing", "dwg"],
        "nsn":          ["nsn", "stock number"],
        "qty":          ["qty", "quantity"],
        "serial":       ["sr no", "sl no", "serial"],
    },

    # Fallback used for manual / specification / drawing / other, or any unknown
    # category. Deliberately generous so comparison still works before a document
    # type has a tuned profile.
    "_default": {
        "part_no":      ["manufacturer's part no", "part no", "part number", "p/n",
                         "cat no", "ds cat no", "item code", "part"],
        "nomenclature": ["nomenclature", "description", "designation", "item name", "part name"],
        "drawing_no":   ["drg", "drawing", "dwg"],
        "nsn":          ["nsn", "stock number"],
        "qty":          ["qty", "quantity", "no. off", "total qty"],
        "serial":       ["sr", "sl", "serial"],
        "reference":    ["ref", "reference", "fig", "figure", "item"],
    },
}


# ── 3. Resolution ───────────────────────────────────────────────────────────────

def canonical_field_for_query(user_term: str):
    """Map a user's column word ('part', 'drawing no', 'DS Cat No') to a canonical
    field key ('part_no', 'drawing_no', ...). Returns None if nothing matches."""
    t = _canon(user_term)
    if not t:
        return None
    if t in CANONICAL_FIELDS:            # already a canonical key
        return t
    best = None
    for field, words in CANONICAL_FIELDS.items():
        for w in words:
            wc = _canon(w)
            if wc == t:                  # exact word hit → strongest
                return field
            if wc in t or t in wc:       # partial ("part no." ⊇ "part")
                best = best or field
    return best


def _schema_for(category):
    """Return the schema dict for a category, falling back to _default."""
    if category and category.lower() in CATEGORY_SCHEMA:
        return CATEGORY_SCHEMA[category.lower()]
    return CATEGORY_SCHEMA["_default"]


def resolve_header(user_term: str, headers, category=None, prefer_literal: bool = False):
    """
    Translate a user's column word into the actual header present in `headers`,
    honouring the document `category`.

    Resolution order:
      0. the user's own words, matched exactly (punctuation-insensitively)
      1. that same term as a substring, when the user named a header outright
         (`prefer_literal`) — a name they typed must not be second-guessed
      2. category-specific patterns for the canonical field (in priority order)
      3. _default patterns for the canonical field
      4. direct substring of the user term itself (last resort)

    Step 0 is skipped for single-word terms such as "part", which name a concept
    rather than a header and must keep going through the schema so each document
    type resolves them to its own column.

    Returns the original header string (as it appears in `headers`) or None.
    """
    pairs = [(h, _canon(h), _canon_loose(h)) for h in headers]
    term = _canon(user_term)
    term_loose = _canon_loose(user_term)

    if term_loose and (prefer_literal or " " in term_loose):
        for orig, _hl, hloose in pairs:
            if hloose == term_loose:
                return orig

    # An explicitly named column beats any schema guess. Without this, asking for
    # ISPL "Firms Part No." resolves to "DS Cat No." — both are part_no, and the
    # schema lists DS Cat No. first.
    if prefer_literal and term_loose:
        for orig, _hl, hloose in pairs:
            if term_loose in hloose:
                return orig

    field = canonical_field_for_query(user_term)

    schemas = []
    if category and category.lower() in CATEGORY_SCHEMA:
        schemas.append(CATEGORY_SCHEMA[category.lower()])
    schemas.append(CATEGORY_SCHEMA["_default"])

    if field:
        for schema in schemas:
            for pat in schema.get(field, []):
                patc = _canon(pat)
                for orig, hl, _hloose in pairs:
                    if patc in hl:
                        return orig

    # Last resort: match the user's literal term against the headers.
    if term:
        for orig, hl, _hloose in pairs:
            if term in hl:
                return orig
    return None


# ── 4. Value normalisation (so "missing" means genuinely missing) ───────────────

_WS_RE = re.compile(r"\s+")

def normalize_value(value: str) -> str:
    """
    Canonical form of a cell value for equality comparison. Conservative on purpose
    — it removes formatting noise that causes false "missing" hits, but does NOT
    strip leading zeros or alter alphanumerics (those can be significant in defence
    catalogue numbers).

    Handles: embedded newlines, repeated/space-padded whitespace, surrounding
    punctuation, and case. e.g. "DIC-NAMP-\\n01210000" → "DIC-NAMP-01210000".
    """
    if value is None:
        return ""
    s = str(value).replace("\n", "").replace("\r", "")
    s = _WS_RE.sub(" ", s).strip()
    s = s.strip(" .,;:'\"")
    # Join tokens split only by spaces around hyphens ("ABC - 123" → "ABC-123")
    s = re.sub(r"\s*-\s*", "-", s)
    return s.upper()


def is_empty_value(value: str) -> bool:
    """True for cells that carry no comparable content."""
    return normalize_value(value) in ("", "-", "N/A", "NA", "NONE", "NIL")


# ── 5. Likely-same pairing for code-like values ─────────────────────────────────
# After the exact set-difference, values like "1534601" vs "01534601" or
# "NAMP-12130000-NAMICA" vs "NAMP-12130000" land in the "missing" lists even
# though they are almost certainly the same item written differently. These
# DETERMINISTIC rules pair them up. We intentionally do NOT use character
# similarity ratios: catalogues are full of sequential part numbers
# (10106255 / 10106256) that are >85% similar yet genuinely different parts —
# a fuzzy ratio would silently merge them. False "missing" beats false "same".

def _zero_core(v: str):
    """Numeric core with leading zeros stripped, or None if not purely numeric."""
    if v.isdigit():
        return v.lstrip("0") or "0"
    return None


def _token_eq(a: str, b: str) -> bool:
    """Hyphen-token equality, tolerant of leading zeros on numeric tokens."""
    if a == b:
        return True
    za, zb = _zero_core(a), _zero_core(b)
    return za is not None and za == zb


def _containment_reason(a: str, b: str):
    """
    If the shorter value's hyphen-tokens appear as a contiguous run inside the
    longer value's tokens (e.g. "NAMP-12130000" inside "NAMP-12130000-NAMICA",
    or "NAMP-01210000" inside "DIC-NAMP-01210000"), the extra tokens are almost
    always an annotation prefix/suffix. Returns a reason string, or None.
    """
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 6:
        return None                      # too short to trust containment
    ts = re.split(r"[-\s]+", short)      # hyphen OR space separated annotations
    tl = re.split(r"[-\s]+", long_)
    if len(ts) >= len(tl):
        return None
    for i in range(len(tl) - len(ts) + 1):
        if all(_token_eq(ts[j], tl[i + j]) for j in range(len(ts))):
            extra = [t for k, t in enumerate(tl) if k < i or k >= i + len(ts)]
            return f"'{long_}' carries extra annotation '{'-'.join(extra)}'"
    return None


def pair_likely_values(only_a, only_b, max_scan=1_000_000):
    """
    Pair values from two "missing" sets that are likely the same item written
    differently. Each value is used at most once (greedy, deterministic order).

    Returns [(value_a, value_b, reason), ...].
    """
    pairs, used_b = [], set()

    # Pass 1 — leading-zero variants, via an O(n) index on the numeric core.
    core_index = {}
    for b in only_b:
        zc = _zero_core(b)
        if zc is not None:
            core_index.setdefault(zc, []).append(b)
    for a in sorted(only_a):
        zc = _zero_core(a)
        if zc is None:
            continue
        for b in sorted(core_index.get(zc, [])):
            if b not in used_b:
                pairs.append((a, b, "differs only by leading zeros"))
                used_b.add(b)
                break

    # Pass 2 — annotation prefix/suffix containment (guarded O(n·m)).
    paired_a = {p[0] for p in pairs}
    if len(only_a) * len(only_b) <= max_scan:
        for a in sorted(only_a):
            if a in paired_a:
                continue
            for b in sorted(only_b):
                if b in used_b:
                    continue
                reason = _containment_reason(a, b)
                if reason:
                    pairs.append((a, b, reason))
                    used_b.add(b)
                    break
    return pairs
