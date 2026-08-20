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

TO EXTEND — WITHOUT A REBUILD
------------------------------
The tables below are the shipped defaults. They can be extended or overridden by a
JSON file that is re-read whenever it changes (no restart needed):

    <RAGOCR_DATA_DIR>/field_schema.json      (packaged / standalone app)
    <backend>/field_schema.json              (dev, when RAGOCR_DATA_DIR is unset)

Format (see field_schema.example.json next to manage.py):

    {
      "canonical_fields": { "part_no": ["firms part no", "oem p/n"] },   # words APPENDED
      "category_schema": {
        "ispl":  { "part_no": ["firms part no", "manufacturer's part no", "part no"] },
        "mmme":  { "part_no": ["firms part no"], "nomenclature": ["description"] }
      }                                                                # lists REPLACED
    }

* `canonical_fields` words are appended to the built-in list for that key.
* `category_schema[category][field]` REPLACES the built-in ordered list for that
  category+field (order is priority, so you must be able to control it fully).
  Unknown categories are simply added.
* Header patterns are matched first as lowercased substrings of the real header
  ("manufacturer's part no" ⊂ "Manufacturer's Part No.\n(block letters)"), then
  punctuation-insensitively on whole tokens ("part no" ≡ "Part-No." ≡ "PART NO").

`effective_schema()` returns the merged result (exposed at GET /api/field-schema/).
"""

import json
import os
import re
import threading
from copy import deepcopy
from pathlib import Path

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
_DEFAULT_CANONICAL_FIELDS = {
    "part_no":      ["part", "part no", "part number", "part.no", "partno", "p/n", "pn",
                     "part ref", "part code", "cat no", "ds cat", "ds cat no",
                     "catalogue no", "catalog no", "item code",
                     "manufacturer's part no", "manufacturer part no", "mfr part no",
                     "mfg part no", "maker's part no", "oem part no", "oem p/n",
                     "vendor part no", "supplier part no", "firms part no",
                     "firm's part no", "firm part no"],
    "nomenclature": ["nomenclature", "description", "designation", "name", "desc",
                     "item name", "part name", "item description"],
    "drawing_no":   ["drg", "drg no", "drawing", "drawing no", "dwg", "dwg no",
                     "drawing number", "drg number"],
    "nsn":          ["nsn", "n.s.n", "stock number", "national stock", "nato stock",
                     "stock no"],
    "qty":          ["qty", "quantity", "qnty", "no off", "no. off", "total qty",
                     "qty per", "qty reqd"],
    "serial":       ["sr", "sr no", "sl", "sl no", "serial", "serial no", "s no", "s. no"],
    "reference":    ["ref", "reference", "ref no", "para ref", "ispl ref", "cct ref",
                     "fig", "figure", "item no", "fig no", "plate no", "plate ref"],
}

# ── 2. Per-category schema: category → canonical field → ordered header patterns ─
# The FIRST pattern that matches a real header in the table wins. Put the most
# doc-type-specific / most-preferred header first.
#
# Part-identifier priority, shared by every category: a *manufacturer's* / OEM /
# firm's part number is the identifier that lines up across MRLS ↔ ISPL ↔ catalog,
# so it always outranks a service-internal "DS Cat No." / "Cat No." / plain "Part".
_PART_ID_PATTERNS = [
    "manufacturer's part no", "manufacturer part no", "manufacturers part no",
    "mfr part no", "mfrs part no", "mfg part no", "maker's part no", "makers part no",
    "oem part no", "oem p/n", "vendor part no", "supplier part no",
    "firm's part no", "firms part no", "firm part no",
]

_DEFAULT_CATEGORY_SCHEMA = {
    # 🔧 MRLS — Maintenance Repair List of Spares
    "mrls": {
        "part_no":      _PART_ID_PATTERNS + ["part no", "part number", "part code", "p/n", "part"],
        "nomenclature": ["nomenclature", "description", "designation"],
        "drawing_no":   ["ispl ref", "figure no", "drg", "drawing", "dwg"],
        "nsn":          ["nsn", "stock number", "stock no"],
        "qty":          ["total qty", "qty", "quantity"],
        "serial":       ["sr. no", "sr no", "sl no", "s. no", "s no"],
        "reference":    ["ispl ref", "figure", "fig", "ref"],
    },

    # 📋 ISPL — Illustrated Spare Parts List
    "ispl": {
        # Prefer the manufacturer's / firm's part number (shared with MRLS → parts
        # line up), then the service catalogue number, then a plain "Part No".
        "part_no":      _PART_ID_PATTERNS + ["ds cat no", "cat no", "catalogue no",
                                             "part no", "part number", "p/n", "part"],
        "nomenclature": ["description", "nomenclature", "designation"],
        "drawing_no":   ["drg", "drawing", "dwg", "fig", "item"],
        "nsn":          ["nsn", "ds cat no", "stock number", "stock no"],
        "qty":          ["no. off", "no off", "qty", "quantity"],
        "serial":       ["sl. no", "sl no", "sr no", "s. no", "s no"],
        "reference":    ["para ref", "cct ref", "fig", "item", "ref"],
    },

    # 📚 Catalog — Parts Catalogue
    "catalog": {
        "part_no":      _PART_ID_PATTERNS + ["part no", "part number", "cat no",
                                             "catalogue no", "item code", "part code",
                                             "p/n", "part"],
        "nomenclature": ["description", "nomenclature", "item name", "part name", "designation"],
        "drawing_no":   ["drg", "drawing", "dwg"],
        "nsn":          ["nsn", "stock number", "stock no"],
        "qty":          ["qty", "quantity"],
        "serial":       ["sr no", "sl no", "serial", "s. no"],
        "reference":    ["ref", "reference", "fig", "figure", "item"],
    },

    # 📖 Manual — technical / user manuals. Tables here are usually maintenance
    # schedules or tool lists; the part column, when present, is a plain "Part No".
    "manual": {
        "part_no":      _PART_ID_PATTERNS + ["part no", "part number", "part code",
                                             "cat no", "item code", "p/n", "part"],
        "nomenclature": ["nomenclature", "description", "designation", "item name", "part name", "item"],
        "drawing_no":   ["drg", "drawing", "dwg", "fig", "figure"],
        "nsn":          ["nsn", "stock number", "stock no"],
        "qty":          ["qty", "quantity", "no. off", "total qty"],
        "serial":       ["sr", "sl", "serial", "s. no"],
        "reference":    ["ref", "reference", "para", "fig", "figure", "item"],
    },

    # 📐 Specification — parameter tables; a "part" column is rare, drawing/ref common.
    "specification": {
        "part_no":      _PART_ID_PATTERNS + ["part no", "part number", "p/n", "cat no", "part"],
        "nomenclature": ["parameter", "description", "nomenclature", "designation", "item"],
        "drawing_no":   ["drg", "drawing", "dwg"],
        "nsn":          ["nsn", "stock number"],
        "qty":          ["qty", "quantity"],
        "serial":       ["sr", "sl", "serial", "s. no"],
        "reference":    ["ref", "reference", "clause", "para", "spec"],
    },

    # 📝 Drawing — parts lists / BOM tables on engineering drawings.
    "drawing": {
        "part_no":      _PART_ID_PATTERNS + ["part no", "part number", "drg no", "drawing no",
                                             "item code", "p/n", "part"],
        "nomenclature": ["description", "nomenclature", "designation", "title", "item name"],
        "drawing_no":   ["drg no", "drawing no", "drg", "drawing", "dwg", "sheet"],
        "nsn":          ["nsn", "stock number"],
        "qty":          ["qty", "quantity", "no. off", "no off"],
        "serial":       ["item no", "item", "sr", "sl", "pos"],
        "reference":    ["ref", "reference", "zone", "sheet"],
    },

    # Fallback used for "other" or any unknown category. Deliberately generous so
    # comparison still works before a document type has a tuned profile.
    "_default": {
        "part_no":      _PART_ID_PATTERNS + ["part no", "part number", "p/n",
                                             "cat no", "ds cat no", "catalogue no",
                                             "item code", "part code", "part"],
        "nomenclature": ["nomenclature", "description", "designation", "item name", "part name"],
        "drawing_no":   ["drg", "drawing", "dwg"],
        "nsn":          ["nsn", "stock number", "stock no"],
        "qty":          ["qty", "quantity", "no. off", "total qty"],
        "serial":       ["sr", "sl", "serial", "s. no"],
        "reference":    ["ref", "reference", "fig", "figure", "item"],
    },
}
_DEFAULT_CATEGORY_SCHEMA["other"] = deepcopy(_DEFAULT_CATEGORY_SCHEMA["_default"])

# The live, effective tables. Mutated IN PLACE by _ensure_loaded() so that any
# module holding a reference keeps seeing the current values.
CANONICAL_FIELDS: dict = deepcopy(_DEFAULT_CANONICAL_FIELDS)
CATEGORY_SCHEMA: dict = deepcopy(_DEFAULT_CATEGORY_SCHEMA)


# ── 2b. Runtime override file ───────────────────────────────────────────────────

_OVERRIDE_FILENAME = "field_schema.json"
_load_lock = threading.Lock()
_loaded_mtime = None          # mtime of the override file last applied (None = defaults)
_override_error = None        # last parse/validation error, surfaced by effective_schema()


def override_path() -> Path:
    """Where the optional JSON override lives (data dir in packaged app, else backend/)."""
    root = os.environ.get("RAGOCR_DATA_DIR")
    if root:
        return Path(root) / _OVERRIDE_FILENAME
    return Path(__file__).resolve().parents[1] / _OVERRIDE_FILENAME


def _as_str_list(value, where: str):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"{where} must be a list of strings")
    return [v.strip().lower() for v in value if v.strip()]


def _apply_override(data: dict):
    """Validate + merge one parsed override document over the defaults."""
    if not isinstance(data, dict):
        raise ValueError("top level must be an object")
    fields = deepcopy(_DEFAULT_CANONICAL_FIELDS)
    schema = deepcopy(_DEFAULT_CATEGORY_SCHEMA)

    for key, words in (data.get("canonical_fields") or {}).items():
        words = _as_str_list(words, f"canonical_fields.{key}")
        existing = fields.setdefault(key, [])
        for w in words:
            if w not in existing:
                existing.append(w)

    for cat, per_field in (data.get("category_schema") or {}).items():
        if not isinstance(per_field, dict):
            raise ValueError(f"category_schema.{cat} must be an object")
        cat_key = str(cat).strip().lower()
        target = schema.setdefault(cat_key, {})
        for field, patterns in per_field.items():
            target[field] = _as_str_list(patterns, f"category_schema.{cat}.{field}")

    # Any category may only reference known canonical fields.
    for cat, per_field in schema.items():
        for field in per_field:
            if field not in fields:
                raise ValueError(f"category_schema.{cat}.{field}: unknown canonical field "
                                 f"(known: {', '.join(sorted(fields))})")

    CANONICAL_FIELDS.clear(); CANONICAL_FIELDS.update(fields)
    CATEGORY_SCHEMA.clear();  CATEGORY_SCHEMA.update(schema)


def _reset_to_defaults():
    CANONICAL_FIELDS.clear(); CANONICAL_FIELDS.update(deepcopy(_DEFAULT_CANONICAL_FIELDS))
    CATEGORY_SCHEMA.clear();  CATEGORY_SCHEMA.update(deepcopy(_DEFAULT_CATEGORY_SCHEMA))


def _ensure_loaded():
    """(Re)apply the override file if it appeared, changed, or was removed since the
    last call. One os.stat per call — cheap enough to run on every resolve."""
    global _loaded_mtime, _override_error
    path = override_path()
    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = None
    if mtime == _loaded_mtime:
        return
    with _load_lock:
        if mtime == _loaded_mtime:
            return
        if mtime is None:
            _reset_to_defaults()
            _override_error = None
        else:
            try:
                with open(path, encoding="utf-8") as f:
                    _apply_override(json.load(f))
                _override_error = None
                print(f"[SCHEMA] Loaded header-schema override from {path}")
            except Exception as e:           # keep the last good tables on a bad file
                _override_error = f"{type(e).__name__}: {e}"
                print(f"[SCHEMA] Ignoring invalid override {path}: {_override_error}")
        _loaded_mtime = mtime


def effective_schema() -> dict:
    """The merged schema currently in force, plus where the override is read from."""
    _ensure_loaded()
    return {
        "override_path": str(override_path()),
        "override_active": _loaded_mtime is not None and _override_error is None,
        "override_error": _override_error,
        "canonical_fields": deepcopy(CANONICAL_FIELDS),
        "category_schema": deepcopy(CATEGORY_SCHEMA),
    }


# ── 3. Resolution ───────────────────────────────────────────────────────────────

def canonical_field_for_query(user_term: str):
    """Map a user's column word ('part', 'drawing no', 'DS Cat No') to a canonical
    field key ('part_no', 'drawing_no', ...). Returns None if nothing matches."""
    _ensure_loaded()
    t = _canon(user_term)
    if not t:
        return None
    if t in CANONICAL_FIELDS:            # already a canonical key
        return t
    t_loose = _canon_loose(user_term)
    best = None
    for field, words in CANONICAL_FIELDS.items():
        for w in words:
            wc = _canon(w)
            if wc == t or _canon_loose(w) == t_loose:   # exact word hit → strongest
                return field
            if wc in t or t in wc:       # partial ("part no." ⊇ "part")
                best = best or field
    return best


def _schema_for(category):
    """Return the schema dict for a category, falling back to _default."""
    _ensure_loaded()
    if category and category.lower() in CATEGORY_SCHEMA:
        return CATEGORY_SCHEMA[category.lower()]
    return CATEGORY_SCHEMA["_default"]


def _token_re(pattern_loose: str):
    """Regex matching `pattern_loose` as a run of whole tokens inside a loose header."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(pattern_loose) + r"(?![a-z0-9])")


def _first_header_matching(pattern: str, pairs):
    """First header whose canonical form contains `pattern` (strict, the historical
    rule), else the first whose punctuation-stripped form contains it as whole
    tokens ("part no" ≡ "Part-No." ≡ "PART NO"). Returns the original header or None."""
    patc = _canon(pattern)
    for orig, hl, _hloose in pairs:
        if patc in hl:
            return orig
    # Loose pass: the header may punctuate the same words differently
    # ("Part-No.", "Firm's Part No" vs pattern "firms part no").
    pat_loose = _canon_loose(pattern)
    if pat_loose:
        rx = _token_re(pat_loose)
        for orig, _hl, hloose in pairs:
            if rx.search(hloose):
                return orig
    return None


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
    _ensure_loaded()
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
                hit = _first_header_matching(pat, pairs)
                if hit is not None:
                    return hit

    # Last resort: match the user's literal term against the headers.
    if term:
        hit = _first_header_matching(user_term, pairs)
        if hit is not None:
            return hit
    return None


def resolve_all_headers(headers, category=None) -> dict:
    """Best-effort map of canonical field → real header for one table, using the
    same rules as resolve_header. Used to show/inspect how a document's columns
    are understood ("Part No ← Firms Part No.")."""
    out = {}
    for field in CANONICAL_FIELDS:
        h = resolve_header(field, headers, category)
        if h is not None:
            out[field] = h
    return out


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


# ── 5. Boilerplate values — not unique part identifiers ─────────────────────────
# Defence/engineering catalogues use standing designations in the part-number
# column when no specific catalogue number applies ("use a generic/standard
# item"). Two documents rarely spell these identically ("STANDARD ITEM" vs
# "STANDAR ITEM" is a real typo seen in production data), so they land in the
# "missing" buckets and get reported as absent parts — which is misleading,
# since they were never unique parts to begin with. Kept as an explicit,
# reviewed list rather than a heuristic ("looks like English words") so a
# genuine alphabetic part designation (e.g. "ROTHE-ERDEMAKE") is never dropped.
_BOILERPLATE_VALUES = {
    "STANDARD ITEM", "STANDAR ITEM", "STANDARD", "COMMERCIAL", "COMMERCIAL ITEM",
    "LOCAL PURCHASE", "LP", "AS REQUIRED", "AR", "TO BE DECIDED", "TBD",
    "REFER DRAWING", "SEE DRAWING", "NOT APPLICABLE", "N.A.",
}
_FOOTNOTE_MARKER_RE = re.compile(r"^\[\d+\]$")


def is_boilerplate_value(value: str) -> bool:
    """True for generic placeholder text that isn't a unique part identifier
    (standing catalogue designations, footnote markers like "[3]")."""
    v = normalize_value(value)
    return v in _BOILERPLATE_VALUES or bool(_FOOTNOTE_MARKER_RE.match(v))


# ── 5b. Likely-same pairing for code-like values ────────────────────────────────
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


def _levenshtein(a: str, b: str) -> int:
    """Edit distance. Values here are short header-cell strings, so plain O(n·m)
    DP is cheap — no need for a library."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = cur
    return prev[-1]


def _is_wordlike(v: str) -> bool:
    """True for text tokens, false for catalogue-code-shaped values.

    Typo-tolerance is only safe on the former: two catalogue codes that are one
    character apart ("10106255" vs "10106256") are routinely different, sequential
    parts, not typos of each other — see the module note on `pair_likely_values`.
    A value is "wordlike" when digits make up less than a third of it.
    """
    if len(v) < 4:
        return False
    digits = sum(c.isdigit() for c in v)
    return digits / len(v) < 0.34


def _typo_reason(a: str, b: str):
    """If both values are wordlike and differ by a small edit distance, they're
    almost certainly the same designation with a typo. Returns a reason or None."""
    if not (_is_wordlike(a) and _is_wordlike(b)):
        return None
    max_dist = 1 if max(len(a), len(b)) <= 15 else 2
    if abs(len(a) - len(b)) > max_dist:
        return None
    d = _levenshtein(a, b)
    if 0 < d <= max_dist:
        return f"differs from '{b}' by a likely typo ({d} character{'s' if d > 1 else ''})"
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

    # Pass 3 — typo tolerance, text tokens only (guarded O(n·m), same cap as pass 2).
    # Deliberately last: passes 1-2 are near-certain, so any value they can already
    # explain is left alone rather than re-matched on weaker edit-distance grounds.
    paired_a = {p[0] for p in pairs}
    if len(only_a) * len(only_b) <= max_scan:
        for a in sorted(only_a):
            if a in paired_a:
                continue
            for b in sorted(only_b):
                if b in used_b:
                    continue
                reason = _typo_reason(a, b)
                if reason:
                    pairs.append((a, b, reason))
                    used_b.add(b)
                    break
    return pairs
