"""
Table Search Engine for RAG Chatbot
Integrates pdfplumber-based table extraction with chatbot queries
"""

import pandas as pd
import pdfplumber
from pathlib import Path
from typing import Dict, List, Any, Optional
import re
from collections import defaultdict

from .models import ExtractedTable, ConfirmedMatch
from .field_schema import (
    resolve_header, normalize_value, is_empty_value, is_boilerplate_value,
    pair_likely_values, canonical_field_for_query, _canon_loose, _levenshtein,
)
from .column_roles import resolve as resolve_column

def words_from_fitz_page(fitz_page) -> List[Dict]:
    """
    Word boxes from a PyMuPDF page, shaped like pdfplumber's `extract_words()`.

    The anchor extractor only ever reads x0/x1/top/bottom/text, and both libraries
    report those in points relative to the visible (cropped) page, so the geometry
    is interchangeable — but PyMuPDF returns them from C in about a millisecond a
    page instead of ~80 ms. Blank tokens are dropped to match
    `keep_blank_chars=False`.
    """
    out = []
    for x0, y0, x1, y1, text, *_rest in fitz_page.get_text("words"):
        t = (text or "").strip()
        if t:
            out.append({"x0": x0, "x1": x1, "top": y0, "bottom": y1, "text": t})
    return out


_LEADING_NUM_RE = re.compile(r'^\s*(\d+(?:[.,]\d+)?)')


def _leading_number(value: str):
    """The number a quantity cell starts with: '1 no.' → 1.0, '01' → 1.0, 'AR' → None."""
    m = _LEADING_NUM_RE.match(value or '')
    if not m:
        return None
    try:
        return float(m.group(1).replace(',', ''))
    except ValueError:
        return None


class TableSearchEngine:
    """
    Search engine for extracting and querying tables from PDFs.
    Supports part number, drawing number, and general text searches.
    """
    
    def __init__(self):
        self.extracted_tables = {}  # {pdf_name: [dataframes]}
        self.table_metadata = {}  # {pdf_name: metadata}
    
    def extract_tables_from_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """
        Extract all tables from PDF and store them.
        Returns metadata about extracted tables.
        """
        pdf_name = Path(pdf_path).name
        all_tables = []
        # Last real header seen per column count, so continuation pages of a
        # multi-page table inherit the header printed on its first page.
        header_memo: Dict[int, List[str]] = {}

        # Word boxes come from PyMuPDF (see words_from_fitz_page): identical
        # geometry, ~200x faster than deriving them through pdfplumber.
        try:
            import fitz
            fdoc = fitz.open(pdf_path)
        except Exception as e:
            print(f"[TABLE] PyMuPDF unavailable ({e}); using pdfplumber words")
            fdoc = None

        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)

            for page_num, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()

                if tables:
                    for table in tables:
                        if not table or len(table) < 2:
                            continue

                        # Clean and validate table structure
                        cleaned_table = self._clean_table_structure(table)
                        if not cleaned_table or len(cleaned_table) < 2:
                            continue

                        cleaned_table = self._with_carried_header(cleaned_table, header_memo)

                        # Convert to DataFrame with proper column handling
                        df = self._create_dataframe_from_table(cleaned_table, page_num)

                        if not df.empty:
                            all_tables.append(df)

                # Fallback for line-less tabular forms (e.g. MRLS/ISPL spares
                # lists) that pdfplumber's line strategy cannot detect. Uses a
                # numbered "1 2 ... N" column-reference row as column anchors.
                try:
                    fwords = (words_from_fitz_page(fdoc[page_num - 1])
                              if fdoc is not None and page_num <= len(fdoc) else None)
                    for adf in self._extract_anchor_tables(page, page_num, header_memo,
                                                           words=fwords):
                        if not adf.empty:
                            all_tables.append(adf)
                except Exception as e:
                    print(f"[TABLE] anchor fallback error on page {page_num}: {e}")

        if fdoc is not None:
            fdoc.close()

        # Merge tables with same column structure
        merged_tables = self._merge_similar_tables(all_tables)
        
        self.extracted_tables[pdf_name] = merged_tables
        self.table_metadata[pdf_name] = {
            'total_tables': len(merged_tables),
            'total_rows': sum(len(df) for df in merged_tables),
            'columns': list(set(col for df in merged_tables for col in df.columns if not col.startswith('_')))
        }
        
        return self.table_metadata[pdf_name]
    
    def _clean_table_structure(self, table: List[List]) -> List[List]:
        """
        Clean table structure by:
        1. Removing completely empty rows
        2. Ensuring consistent column count
        3. Handling merged cells
        """
        if not table:
            return []
        
        # Remove completely empty rows
        cleaned = []
        for row in table:
            if row and any(cell and str(cell).strip() for cell in row):
                cleaned.append(row)
        
        if not cleaned:
            return []
        
        # Get the most common column count (from header rows typically)
        from collections import Counter
        col_counts = Counter(len(row) for row in cleaned[:5])  # Check first 5 rows
        target_cols = col_counts.most_common(1)[0][0]
        
        # Standardize all rows to have target column count
        standardized = []
        for row in cleaned:
            if len(row) < target_cols:
                # Pad with empty strings
                row = row + [''] * (target_cols - len(row))
            elif len(row) > target_cols:
                # Truncate or merge excess cells
                row = row[:target_cols]
            standardized.append(row)
        
        return standardized
    
    # ── Header carry-forward across continuation pages ──────────────────────
    # A long spares table prints its header once, on the page where it starts.
    # Every later page begins straight into data, so the "row 0 is the header"
    # rule below turns catalogue values into column names ("9900905066",
    # "BEML"), and nothing downstream can resolve a column any more. We detect
    # that case and re-use the last real header of the same width.

    _PLACEHOLDER_COL_RE = re.compile(r'Column_\d+(_\d+)?$')

    @classmethod
    def _looks_like_header(cls, row) -> bool:
        """True when a row reads as column labels rather than data.

        Two things separate a header from a data row:

        * it names most of its columns, so a line with one filled cell and the
          rest blank is a stray data row, not a header;
        * its cells read as words rather than codes. Digits alone do not
          disqualify a label — "18 Months 500 Hour" is a perfectly good column
          name — but letters must outweigh them, which excludes "9900905066" and
          "45-0867". Reconstruction placeholders ("Column_7") never count.
        """
        width = len(row)
        if width < 2:
            return False
        cells = [re.sub(r'\s+', ' ', str(c)).strip()
                 for c in row if c is not None and str(c).strip()]
        if len(cells) < 2 or len(cells) * 2 < width:
            return False
        labelish = 0
        for c in cells:
            if cls._PLACEHOLDER_COL_RE.match(c):
                continue
            letters = sum(ch.isalpha() for ch in c)
            if letters >= 2 and letters > sum(ch.isdigit() for ch in c):
                labelish += 1
        return labelish * 2 >= len(cells)

    def _with_carried_header(self, matrix: List[List], memo: Dict[int, List[str]]) -> List[List]:
        """Guarantee `matrix` starts with a header row.

        Records row 0 in `memo` when it reads as labels. When it does not — a
        continuation page — the remembered header of the same width is prepended,
        which also keeps that first row where it belongs, in the data.
        """
        if not matrix:
            return matrix
        width = len(matrix[0])
        if self._looks_like_header(matrix[0]):
            memo[width] = [str(c) if c is not None else '' for c in matrix[0]]
            return matrix
        carried = memo.get(width)
        if carried:
            return [list(carried)] + matrix
        return matrix

    def _create_dataframe_from_table(self, table: List[List], page_num: int) -> pd.DataFrame:
        """
        Create DataFrame from table with robust column handling.
        """
        if not table or len(table) < 2:
            return pd.DataFrame()
        
        # Extract header and data
        header = table[0]
        data_rows = table[1:]
        
        # Clean header: handle None, empty, and duplicate column names
        cleaned_header = []
        seen_names = {}
        
        for i, col in enumerate(header):
            # Convert to string and clean
            if col is None or not str(col).strip():
                col_name = f'Column_{i+1}'
            else:
                col_name = str(col).strip()
            
            # Handle duplicates by adding suffix
            if col_name in seen_names:
                seen_names[col_name] += 1
                col_name = f"{col_name}_{seen_names[col_name]}"
            else:
                seen_names[col_name] = 0
            
            cleaned_header.append(col_name)
        
        # Create DataFrame
        try:
            df = pd.DataFrame(data_rows, columns=cleaned_header)
            
            # Clean data: convert None to empty string
            df = df.fillna('')
            
            # Remove rows where all values are empty
            df = df[df.astype(str).apply(lambda x: x.str.strip().str.len().sum(), axis=1) > 0]
            
            # Remove columns where all values are empty
            df = df.loc[:, df.astype(str).apply(lambda x: x.str.strip().str.len().sum()) > 0]
            
            if not df.empty:
                # Store page number
                df['_source_page'] = page_num
            
            return df
            
        except Exception as e:
            print(f"Error creating DataFrame: {e}")
            return pd.DataFrame()
    
    # ── Anchor-based extraction for line-less tabular forms ──────────────────
    # Many defence/engineering spares forms (MRLS, ISPL, ...) draw their tables
    # with whitespace-separated columns and no vertical rules, so pdfplumber's
    # line strategy finds nothing. These forms carry a numbered "1 2 ... N"
    # column-reference row directly under the header; we use the x-centres of
    # those numbers as column anchors and bucket every word into a column.

    _FOOTER_RE = re.compile(r'^(RESTRICTED|MRLS|ISPL|Page\b|NOTE\b|WARNING\b|CAUTION\b)', re.I)
    # A line matching this (after data has started) marks the end of the table body;
    # everything below is footnotes/annotations that must not bleed into data cells.
    _TERMINATOR_RE = re.compile(
        r'(\*\s*denote|given\s+is\s+for|total\s+qty.{0,4}\s+given|refer\s+table|'
        r'^\s*note\s*[:\-]|^\s*\*)', re.I)

    def _cluster_words_into_lines(self, words: List[Dict], ytol: float = 3.0) -> List[Dict]:
        """Group extracted words into visual lines by vertical centre."""
        lines: List[Dict] = []
        for w in sorted(words, key=lambda w: (round(w['top']), w['x0'])):
            yc = (w['top'] + w['bottom']) / 2
            for ln in lines:
                if abs(ln['yc'] - yc) <= ytol:
                    ln['words'].append(w)
                    ln['yc'] = (ln['yc'] * (len(ln['words']) - 1) + yc) / len(ln['words'])
                    break
            else:
                lines.append({'yc': yc, 'words': [w]})
        for ln in lines:
            ln['words'].sort(key=lambda w: w['x0'])
        return sorted(lines, key=lambda l: l['yc'])

    def _find_numbered_anchor(self, lines: List[Dict], min_cols: int = 6):
        """Locate the '1 2 3 ... N' reference row; return (index, x-centres)."""
        for idx, ln in enumerate(lines):
            toks = [w for w in ln['words'] if re.fullmatch(r'\d{1,2}', w['text'])]
            seq = [w['text'] for w in toks]
            n = 0
            for i, t in enumerate(seq):
                if t == str(i + 1):
                    n = i + 1
                else:
                    break
            if n >= min_cols:
                centres = [(w['x0'] + w['x1']) / 2 for w in toks[:n]]
                return idx, centres
        return None, None

    def _column_bounds(self, centres: List[float]) -> List[float]:
        bounds = [-1.0]
        for a, b in zip(centres, centres[1:]):
            bounds.append((a + b) / 2)
        bounds.append(1e9)
        return bounds

    @staticmethod
    def _assign_col(word: Dict, bounds: List[float]) -> int:
        xc = (word['x0'] + word['x1']) / 2
        for i in range(len(bounds) - 1):
            if bounds[i] <= xc < bounds[i + 1]:
                return i
        return len(bounds) - 2

    # The part-number column is labelled differently per document family:
    # "Manufacturer's Part No." (NAMICA/TGS MRLS), "Firms Part No." (MMME ISPL),
    # plain "Part No", "DS Cat No.". Any of them marks a spares list.
    _PART_HDR_RE = re.compile(r"manufactur|firm|part\s*\.?\s*no|p/n|ds\s*cat", re.I)
    # ...but only alongside one of the other columns a spares list always carries,
    # so ordinary prose tables are not rewritten.
    _SPARES_CTX_RE = re.compile(
        r"nomenclature|description|source\s+of\s+supply|cct\s*ref|para\s*ref|"
        r"ispl\s*ref|no\.?\s*off|qty|remark", re.I)

    def _canonicalise_spares_headers(self, headers: List[str]) -> List[str]:
        """Map noisy reconstructed headers of an MRLS/ISPL-style spares table to
        canonical column names by keyword. Returns headers unchanged when the
        spares-list signature is absent."""
        band = ' '.join(headers)
        if not self._PART_HDR_RE.search(band) or not self._SPARES_CTX_RE.search(band):
            return headers  # not a spares list — leave reconstructed names as-is

        out = list(headers)
        for i, h in enumerate(headers):
            hl = h.lower()
            if i == 0:
                out[i] = 'Sr. No.'                        # serial column, never "part"
            elif 'manufactur' in hl or 'firm' in hl:
                out[i] = "Manufacturer's Part No."        # the part-number column
            elif 'source' in hl:
                out[i] = 'Source of Supply'
            elif 'nomenclature' in hl or 'description' in hl:
                out[i] = 'Nomenclature'
            elif 'ispl' in hl or 'figure' in hl:
                out[i] = 'ISPL Ref. No. (Figure No.)'     # drop stray "Item No." token
            elif 'remark' in hl:
                out[i] = 'Remarks'
        # Guarantee a part column exists even if "Manufacturer's" wrapped away.
        if not any('part' in h.lower() for h in out) and len(out) > 1:
            out[1] = "Manufacturer's Part No."
        return out

    def _extract_anchor_tables(self, page, page_num: int,
                               header_memo: Optional[Dict[int, List[str]]] = None,
                               words: Optional[List[Dict]] = None) -> List[pd.DataFrame]:
        """
        Reconstruct a line-less table using its numbered reference row.

        `words` lets a caller supply the word boxes instead of having pdfplumber
        derive them. Only x0/x1/top/bottom/text are used, and pdfplumber builds
        those in Python from pdfminer characters at ~81 ms/page where PyMuPDF
        returns them from C at ~1 ms/page — a 77x difference on identical data,
        and the single largest cost in ingesting a large spares list. See
        `words_from_fitz_page()`.
        """
        if words is None:
            try:
                words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            except Exception:
                return []
        if not words:
            return []
        # Drop the rotated "RESTRICTED" watermark and page furniture.
        words = [w for w in words if w['text'].strip().upper() != 'RESTRICTED']

        lines = self._cluster_words_into_lines(words)
        anchor_idx, centres = self._find_numbered_anchor(lines)
        if not centres:
            return []

        bounds = self._column_bounds(centres)
        ncols = len(centres)
        anchor_yc = lines[anchor_idx]['yc']

        # Header: bucket the band of lines just above the reference row.
        header_cells = [[] for _ in range(ncols)]
        for ln in lines[:anchor_idx]:
            if ln['yc'] >= anchor_yc - 60:
                for w in ln['words']:
                    header_cells[self._assign_col(w, bounds)].append(w['text'])
        headers = []
        for i, cell in enumerate(header_cells):
            name = ' '.join(cell).strip()
            headers.append(name if name else f'Column_{i + 1}')

        # Reconstructed headers from wrapped multi-line bands are noisy (e.g.
        # "Manufacturer's" and "Part No." land on different rows/columns). When
        # the band shows the spares-list signature, snap columns to canonical
        # names by keyword so downstream column matching is reliable and the
        # serial column never masquerades as the part column.
        headers = self._canonicalise_spares_headers(headers)

        # On a continuation page the numbered reference row is reprinted but the
        # header band above it is not, leaving every name as "Column_N". Replace
        # those with the header this table carried on the page it started.
        if header_memo is not None:
            if self._looks_like_header(headers):
                header_memo[ncols] = list(headers)
            elif ncols in header_memo:
                headers = list(header_memo[ncols])

        # Data rows: a new logical row begins when column 0 holds a serial
        # number ("11."); other lines are wrapped continuations of the row above.
        rows: List[List[str]] = []
        for ln in lines[anchor_idx + 1:]:
            joined = ' '.join(w['text'] for w in ln['words']).strip()
            # Once data rows exist, a footnote/annotation line ends the table body.
            if rows and self._TERMINATOR_RE.search(joined):
                break
            if self._FOOTER_RE.match(joined):
                continue
            cells = [[] for _ in range(ncols)]
            for w in ln['words']:
                cells[self._assign_col(w, bounds)].append(w['text'])
            cell_text = [' '.join(c).strip() for c in cells]
            if not any(cell_text):
                continue
            if re.match(r'^\d{1,3}\.?$', cell_text[0]) or not rows:
                rows.append(cell_text)
            else:
                for i, t in enumerate(cell_text):
                    if t:
                        rows[-1][i] = (rows[-1][i] + ' ' + t).strip()
        if not rows:
            return []

        df = self._create_dataframe_from_table([headers] + rows, page_num)
        return [df] if not df.empty else []

    def _merge_similar_tables(self, tables: List[pd.DataFrame]) -> List[pd.DataFrame]:
        """Merge tables with same column structure."""
        if not tables:
            return []
        
        # Group by column signature
        groups = defaultdict(list)
        for df in tables:
            # Filter out internal columns and None values
            col_sig = tuple(sorted([str(c) for c in df.columns 
                                  if c is not None and not str(c).startswith('_')]))
            groups[col_sig].append(df)
        
        # Merge each group
        merged = []
        for dfs_list in groups.values():
            if len(dfs_list) == 1:
                merged.append(dfs_list[0])
            else:
                merged_df = pd.concat(dfs_list, ignore_index=True)
                merged.append(merged_df)
        
        return merged
    
    def search_value(self, pdf_name: str, search_term: str, 
                    column_name: Optional[str] = None,
                    exact_match: bool = False) -> Dict[str, Any]:
        """
        Search for a value in extracted tables.
        
        Args:
            pdf_name: Name of PDF file
            search_term: Term to search for
            column_name: Specific column to search in (None = search all columns)
            exact_match: If True, use exact matching; otherwise use contains
        
        Returns:
            Dictionary with search results and summary
        """
        if pdf_name not in self.extracted_tables:
            return {'error': f'No tables extracted from {pdf_name}'}
        
        results = []
        search_term_lower = str(search_term).lower()
        
        for table_idx, df in enumerate(self.extracted_tables[pdf_name], 1):
            # Determine which columns to search
            if column_name:
                # Find matching column (case-insensitive, partial match)
                search_cols = [col for col in df.columns 
                             if not col.startswith('_') and column_name.lower() in col.lower()]
            else:
                search_cols = [col for col in df.columns if not col.startswith('_')]
            
            for col in search_cols:
                # Search in this column
                if exact_match:
                    mask = df[col].astype(str).str.lower() == search_term_lower
                else:
                    mask = df[col].astype(str).str.lower().str.contains(search_term_lower, na=False, regex=False)
                
                matches = df[mask]
                
                if not matches.empty:
                    for _, row in matches.iterrows():
                        result_data = {
                            'table_index': table_idx,
                            'matched_column': col,
                            'matched_value': str(row[col]),
                            'page': int(row.get('_source_page', 0)) if '_source_page' in row else None,
                            'row_data': {}
                        }
                        
                        # Include all row data (except internal columns)
                        for c in df.columns:
                            if not c.startswith('_'):
                                result_data['row_data'][c] = str(row[c]) if pd.notna(row[c]) else ''
                        
                        results.append(result_data)
        
        return self._create_summary(search_term, column_name, results)
    
    def _create_summary(self, search_term: str, column_name: Optional[str], 
                       results: List[Dict]) -> Dict[str, Any]:
        """Create a summary of search results."""
        if not results:
            return {
                'found': False,
                'search_term': search_term,
                'column': column_name,
                'total_matches': 0,
                'message': f"No matches found for '{search_term}'" + 
                          (f" in column '{column_name}'" if column_name else ""),
                'results': []
            }
        
        # Group results by page
        by_page = defaultdict(list)
        for r in results:
            if r['page']:
                by_page[r['page']].append(r)
        
        summary = {
            'found': True,
            'search_term': search_term,
            'column': column_name,
            'total_matches': len(results),
            'pages_with_matches': sorted(by_page.keys()),
            'results': results[:50],  # Limit to first 50 results
            'summary_text': self._generate_summary_text(search_term, results)
        }
        
        return summary
    
    def _generate_summary_text(self, search_term: str, results: List[Dict]) -> str:
        """Generate human-readable summary text."""
        total = len(results)
        pages = sorted(set(r['page'] for r in results if r['page']))
        
        summary = f"Found {total} match(es) for '{search_term}'"
        
        if pages:
            if len(pages) <= 5:
                summary += f" on page(s): {', '.join(map(str, pages))}"
            else:
                summary += f" across {len(pages)} pages (pages {pages[0]}-{pages[-1]})"
        
        # Add sample matches
        if results:
            summary += "\n\nSample matches:"
            for i, r in enumerate(results[:3], 1):
                matched_col = r['matched_column']
                matched_val = r['matched_value']
                page = r['page']
                
                summary += f"\n{i}. {matched_col}: {matched_val}"
                if page:
                    summary += f" (Page {page})"
                
                # Add related fields for context
                row_data = r['row_data']
                important_fields = ['DESIGNATION', 'PART NO.', 'DRG. NO.', 'NSN', 
                                   'Nomenclature', 'DESCRIPTION', 'NO.\nOFF']
                
                for field in important_fields:
                    # Case-insensitive partial match
                    matching_keys = [k for k in row_data.keys() 
                                   if field.lower() in k.lower() and k != matched_col]
                    if matching_keys:
                        key = matching_keys[0]
                        val = row_data[key]
                        if val and val.strip():
                            summary += f"\n   {key}: {val}"
        
        if total > 3:
            summary += f"\n\n... and {total - 3} more matches"
        
        return summary
    
    def search_drawing_number(self, pdf_name: str, drawing_number: str) -> Dict[str, Any]:
        """Specialized search for drawing numbers."""
        # Try common drawing number column names
        column_patterns = ['DRG', 'DRAWING', 'DWG']
        
        for pattern in column_patterns:
            result = self.search_value(pdf_name, drawing_number, column_name=pattern, exact_match=False)
            if result.get('found'):
                return result
        
        # Fallback to general search
        return self.search_value(pdf_name, drawing_number, exact_match=False)
    
    def search_part_number(self, pdf_name: str, part_number: str) -> Dict[str, Any]:
        """Specialized search for part numbers."""
        # Try common part number column names
        column_patterns = ['PART', 'ITEM', 'P/N', 'PART NO']
        
        for pattern in column_patterns:
            result = self.search_value(pdf_name, part_number, column_name=pattern, exact_match=False)
            if result.get('found'):
                return result
        
        # Fallback to general search
        return self.search_value(pdf_name, part_number, exact_match=False)

    def _get_confirmed_pairs(self, pdf1_name: str, pdf2_name: str, column_key: str):
        """Previously confirmed value pairs for this document pair + concept,
        returned as (value_for_pdf1, value_for_pdf2, note) — direction-normalized
        regardless of which file was "A" when the confirmation was stored."""
        from django.db.models import Q
        qs = ConfirmedMatch.objects.filter(
            Q(source_a__iexact=pdf1_name, source_b__iexact=pdf2_name) |
            Q(source_a__iexact=pdf2_name, source_b__iexact=pdf1_name),
            column_key=column_key,
        )
        pairs = []
        for m in qs:
            if m.source_a.lower() == pdf1_name.lower():
                pairs.append((m.value_a, m.value_b, m.note))
            else:
                pairs.append((m.value_b, m.value_a, m.note))
        return pairs

    def confirm_match(self, source_a: str, source_b: str, column_name: str,
                      value_a: str, value_b: str, note: str = "",
                      thread_id: Optional[str] = None) -> Dict[str, Any]:
        """Persist a human-confirmed 'these are the same item' pairing so future
        comparisons of these two documents treat it as matched, not missing."""
        column_key = canonical_field_for_query(column_name) or column_name.strip().lower()
        na, nb = normalize_value(value_a), normalize_value(value_b)
        if not na or not nb:
            return {'ok': False, 'error': 'Both values must be non-empty.'}
        obj, created = ConfirmedMatch.objects.update_or_create(
            source_a=source_a, source_b=source_b, column_key=column_key,
            value_a=na, value_b=nb,
            defaults={'note': note, 'thread_id': thread_id},
        )
        return {'ok': True, 'created': created, 'value_a': na, 'value_b': nb, 'column_key': column_key}

    def compare_tables(self, pdf1_name: str, pdf2_name: str,
                      column_name: str,
                      column_name_pdf2: Optional[str] = None,
                      match_any_column_in_pdf2: bool = False,
                      comparison_type: str = 'difference',
                      category1: Optional[str] = None,
                      category2: Optional[str] = None,
                      prefer_literal: bool = False,
                      doc1_id: Optional[str] = None,
                      doc2_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Compare a specific column between two PDFs.

        doc1_id/doc2_id are optional but let a user's pinned column choice
        (process/column_roles.py) override header resolution for that document —
        the person who read the document beats any rule we could write.

        Args:
            pdf1_name: First PDF name (e.g., 'mrls.pdf')
            pdf2_name: Second PDF name (e.g., 'ISPL_Vol-I.pdf')
            column_name: Column to compare (e.g., 'Part Number', 'DRG No')
            comparison_type: 'difference' (items in pdf1 not in pdf2),
                           'common' (items in both),
                           'unique_both' (items unique to each),
                           'all' (show all comparisons)
        
        Returns:
            Dictionary with comparison results
        """
        # Ensure both PDFs are extracted
        if pdf1_name not in self.extracted_tables:
            return {'error': f'No tables extracted from {pdf1_name}'}
        if pdf2_name not in self.extracted_tables:
            return {'error': f'No tables extracted from {pdf2_name}'}
        
        # Resolve the comparison column per document via the canonical field +
        # per-category schema, so e.g. "part" maps to "Manufacturer's Part No." in
        # an MRLS but "DS Cat No." in an ISPL. Falls back to the generic schema
        # when a category has no tuned profile.
        target1 = column_name
        target2 = column_name_pdf2 or column_name

        available_cols_pdf1 = sorted(list({
            str(col) for df in self.extracted_tables[pdf1_name] for col in df.columns if not str(col).startswith('_')
        }))
        available_cols_pdf2 = sorted(list({
            str(col) for df in self.extracted_tables[pdf2_name] for col in df.columns if not str(col).startswith('_')
        }))

        def _collect(pdf_name, target, category, match_any=False, doc_id=None):
            """Extract normalized values (+ row context) from the resolved column
            of every table in a document. Returns (value_set, rows, resolved_header)."""
            values, rows, resolved = set(), [], None
            for df in self.extracted_tables[pdf_name]:
                data_cols = [c for c in df.columns if not str(c).startswith('_')]
                if match_any:
                    cols = data_cols
                else:
                    col = resolve_column(target, data_cols, category, doc_id=doc_id,
                                         prefer_literal=prefer_literal)
                    if not col:
                        continue
                    resolved = resolved or col
                    cols = [col]
                for col in cols:
                    for _, row in df.iterrows():
                        raw = str(row[col]) if pd.notna(row[col]) else ''
                        if is_empty_value(raw):
                            continue
                        nv = normalize_value(raw)
                        values.add(nv)
                        row_dict = {c: str(row[c]) if pd.notna(row[c]) else ''
                                    for c in df.columns if not str(c).startswith('_')}
                        row_dict['_matched_column'] = col
                        row_dict['_matched_value'] = raw.strip()
                        row_dict['_norm_value'] = nv
                        row_dict['_source_pdf'] = pdf_name
                        if '_source_page' in row:
                            row_dict['_page'] = int(row['_source_page'])
                        rows.append(row_dict)
            return values, rows, resolved

        pdf1_values, pdf1_rows, resolved_col1 = _collect(pdf1_name, target1, category1,
                                                        doc_id=doc1_id)
        pdf2_values, pdf2_rows, resolved_col2 = _collect(
            pdf2_name, target2, category2, match_any=match_any_column_in_pdf2,
            doc_id=doc2_id)
        
        # If no values extracted on one or both sides, requested column likely missing.
        if not pdf1_values or not pdf2_values:
            return {
                'found': False,
                'error': (
                    f"Could not find comparable values for columns '{column_name}' and "
                    f"'{column_name_pdf2 or column_name}' in one or both files."
                ),
                'column': column_name if not column_name_pdf2 else f"{column_name} -> {column_name_pdf2}",
                'pdf1': pdf1_name,
                'pdf2': pdf2_name,
                'available_columns_pdf1': available_cols_pdf1,
                'available_columns_pdf2': available_cols_pdf2,
            }

        # Perform comparisons
        in_pdf1_only = pdf1_values - pdf2_values
        in_pdf2_only = pdf2_values - pdf1_values
        common_values = pdf1_values & pdf2_values

        # How many rows in pdf2 carry each value — e.g. a part number that shows
        # up on 3 different pages of the ISPL because it's used in 3 assemblies.
        # The set-based comparison above dedupes to "present or not"; this answers
        # the separate question of how many times.
        pdf2_occurrences = defaultdict(int)
        for r in pdf2_rows:
            pdf2_occurrences[r['_norm_value']] += 1

        # User-confirmed pairs take priority over every algorithmic rule below —
        # a human already decided these are the same item, so they're pulled out
        # first and never re-litigated by the deterministic passes.
        column_key = canonical_field_for_query(column_name) or column_name.strip().lower()
        confirmed_pairs = self._get_confirmed_pairs(pdf1_name, pdf2_name, column_key)
        confirmed_pairs = [(a, b, note) for a, b, note in confirmed_pairs
                           if a in in_pdf1_only and b in in_pdf2_only]
        if confirmed_pairs:
            in_pdf1_only = in_pdf1_only - {p[0] for p in confirmed_pairs}
            in_pdf2_only = in_pdf2_only - {p[1] for p in confirmed_pairs}

        # Generic placeholder text ("Standard Item", footnote markers) is not a
        # unique part identifier — reporting it as a missing/extra part is noise,
        # not a finding. Pulled out before the pairing passes so it isn't spent
        # matching placeholder typos against each other either.
        excluded_pdf1 = {v for v in in_pdf1_only if is_boilerplate_value(v)}
        excluded_pdf2 = {v for v in in_pdf2_only if is_boilerplate_value(v)}
        in_pdf1_only -= excluded_pdf1
        in_pdf2_only -= excluded_pdf2

        # Pair leftover values that are likely the same item written differently
        # (leading zeros, annotation prefixes/suffixes). Deterministic rules only —
        # see field_schema.pair_likely_values. Paired values move out of the
        # "missing" lists into their own reviewable category.
        likely_pairs = pair_likely_values(in_pdf1_only, in_pdf2_only)
        if likely_pairs:
            in_pdf1_only = in_pdf1_only - {p[0] for p in likely_pairs}
            in_pdf2_only = in_pdf2_only - {p[1] for p in likely_pairs}

        # Second chance: a leftover may be a formatting variant of a value the
        # other file DOES contain but which already matched exactly (e.g. MRLS
        # lists both "XL17461" and "XL17461 NAMICA" — the plain form lands in
        # common, leaving the annotated one stranded as "missing").
        second1 = pair_likely_values(in_pdf1_only, pdf2_values - in_pdf2_only)
        if second1:
            in_pdf1_only = in_pdf1_only - {p[0] for p in second1}
            likely_pairs.extend(second1)
        second2 = pair_likely_values(in_pdf2_only, pdf1_values - in_pdf1_only)
        if second2:
            in_pdf2_only = in_pdf2_only - {p[0] for p in second2}
            # flip so pdf1_value/pdf2_value keep their meaning
            likely_pairs.extend((b, a, reason) for a, b, reason in second2)
        
        # Prepare results. Show the ACTUAL resolved headers so the user sees which
        # real columns were compared (e.g. "Manufacturer's Part No. ↔ DS Cat No.").
        def _clean_label(h):
            return re.sub(r'\s+', ' ', str(h)).strip()
        if resolved_col1 and (resolved_col2 or match_any_column_in_pdf2):
            col_label = f"{_clean_label(resolved_col1)} ↔ {_clean_label(resolved_col2) if resolved_col2 else 'any column'}"
        else:
            col_label = column_name if not column_name_pdf2 else f"{column_name} -> {column_name_pdf2}"
        result = {
            'column': col_label,
            'pdf1': pdf1_name,
            'pdf2': pdf2_name,
            'pdf1_total': len(pdf1_values),
            'pdf2_total': len(pdf2_values),
            'comparison_type': comparison_type,
            'results': {}
        }

        if likely_pairs:
            result['results']['likely_matches'] = {
                'count': len(likely_pairs),
                'pairs': [
                    {'pdf1_value': a, 'pdf2_value': b, 'reason': reason,
                     'count_in_pdf2': pdf2_occurrences.get(b, 0)}
                    for a, b, reason in likely_pairs
                ],
            }

        # Same item, different details. Presence/absence is only half the question:
        # a part listed in both documents can still disagree on quantity, drawing
        # number or nomenclature, and that discrepancy is exactly what a revision
        # check is looking for. Only the values that matched are examined, and only
        # the other concepts that BOTH documents actually have a column for.
        modified = self._row_differences(
            common_values, pdf1_rows, pdf2_rows, category1, category2,
            doc1_id=doc1_id, doc2_id=doc2_id,
            pairs=[(a, b) for a, b, _r in likely_pairs] +
                  [(a, b) for a, b, _n in confirmed_pairs])
        if modified:
            result['results']['modified'] = {'count': len(modified), 'items': modified}

        if confirmed_pairs:
            result['results']['confirmed_matches'] = {
                'count': len(confirmed_pairs),
                'pairs': [
                    {'pdf1_value': a, 'pdf2_value': b, 'note': note,
                     'count_in_pdf2': pdf2_occurrences.get(b, 0)}
                    for a, b, note in confirmed_pairs
                ],
            }

        excluded_values = excluded_pdf1 | excluded_pdf2
        if excluded_values:
            result['results']['excluded'] = {
                'count': len(excluded_values),
                'values': sorted(excluded_values),
                'reason': 'generic placeholder text, not a unique part identifier',
            }

        if comparison_type in ['difference', 'all']:
            # Items in PDF1 but not in PDF2
            result['results']['in_pdf1_only'] = {
                'count': len(in_pdf1_only),
                'values': sorted(list(in_pdf1_only)),
                'rows': [r for r in pdf1_rows if r['_norm_value'] in in_pdf1_only]
            }
        
        if comparison_type in ['common', 'all']:
            # Items in both PDFs
            result['results']['common'] = {
                'count': len(common_values),
                'values': sorted(list(common_values)),
                'rows': [r for r in pdf1_rows if r['_norm_value'] in common_values],
                'occurrences_in_pdf2': {v: pdf2_occurrences.get(v, 0) for v in common_values},
            }
        
        if comparison_type in ['unique_both', 'all']:
            result['results']['in_pdf1_only'] = {
                'count': len(in_pdf1_only),
                'values': sorted(list(in_pdf1_only)),
                'rows': [r for r in pdf1_rows if r['_norm_value'] in in_pdf1_only]
            }
            result['results']['in_pdf2_only'] = {
                'count': len(in_pdf2_only),
                'values': sorted(list(in_pdf2_only)),
                'rows': [r for r in pdf2_rows if r['_norm_value'] in in_pdf2_only]
            }
        
        # Generate summary
        result['summary'] = self._generate_comparison_summary(result)
        result['found'] = True
        
        return result

    # Concepts worth cross-checking on a row that matched. Deliberately NOT:
    #   • the identifier itself — that is what matched;
    #   • drawing_no / reference — an MRLS writes "Figure3- 12,Item No.1" where the
    #     ISPL writes "Figure 3-12 1" for the same thing, so every row would be
    #     flagged for a difference that is purely house style.
    # Measured on the NAMICA pair, restricting the list and normalising harder took
    # this from 71 of 71 matched rows (pure noise) to the handful that really differ.
    _DIFF_FIELDS = ('nomenclature', 'qty', 'nsn')
    # Concepts whose meaning depends on the column's own wording, so they may only
    # be compared between columns that are labelled the same in both documents.
    _SAME_HEADER_ONLY = ('qty',)

    def _row_differences(self, common_values, pdf1_rows, pdf2_rows,
                         category1, category2, doc1_id=None, doc2_id=None,
                         pairs=()) -> List[Dict[str, Any]]:
        """
        For values present in BOTH documents, report the other columns that
        disagree. Returns [{value, differences: [{field, header_a/b, value_a/b}]}].

        Conservative by design — a difference is reported only when both sides have
        a column for the concept and both cells are non-empty, and never when one
        value is simply a truncation of the other (wrapped cells are common and are
        not a real discrepancy).
        """
        if not common_values and not pairs:
            return []

        def _first_by_value(rows):
            out = {}
            for r in rows:
                out.setdefault(r['_norm_value'], r)
            return out

        left, right = _first_by_value(pdf1_rows), _first_by_value(pdf2_rows)
        checks = [(v, v) for v in sorted(common_values)] + [
            (a, b) for a, b in pairs if a in left and b in right]

        out = []
        for va, vb in checks:
            r1, r2 = left.get(va), right.get(vb)
            if not r1 or not r2:
                continue
            keys1 = [k for k in r1 if not k.startswith('_')]
            keys2 = [k for k in r2 if not k.startswith('_')]
            diffs = []
            for field in self._DIFF_FIELDS:
                h1 = resolve_column(field, keys1, category1, doc_id=doc1_id)
                h2 = resolve_column(field, keys2, category2, doc_id=doc2_id)
                if not h1 or not h2:
                    continue
                # Quantities are only comparable when both documents label the
                # column the same way. An MRLS "Total Qty. / Launcher" (fleet total)
                # and an ISPL "No. Off" (fitted in one assembly) both resolve to
                # `qty`, but they count different things — "18 nos." vs "1" is not a
                # discrepancy, it is two different questions. Same-header pairs are
                # the revision-vs-revision case, where a change IS meaningful.
                if field in self._SAME_HEADER_ONLY and _canon_loose(h1) != _canon_loose(h2):
                    continue
                a_raw, b_raw = str(r1.get(h1, '')), str(r2.get(h2, ''))
                if is_empty_value(a_raw) or is_empty_value(b_raw):
                    continue
                a, b = normalize_value(a_raw), normalize_value(b_raw)
                if a == b or self._same_enough(field, a, b):
                    continue
                diffs.append({
                    'field': field,
                    'header_a': re.sub(r'\s+', ' ', str(h1)).strip(),
                    'header_b': re.sub(r'\s+', ' ', str(h2)).strip(),
                    'value_a': re.sub(r'\s+', ' ', a_raw).strip(),
                    'value_b': re.sub(r'\s+', ' ', b_raw).strip(),
                })
            if diffs:
                entry = {'value': va, 'differences': diffs}
                if vb != va:
                    entry['matched_value'] = vb
                out.append(entry)
        return out

    @staticmethod
    def _same_enough(field: str, a: str, b: str) -> bool:
        """
        True when a textual difference is a formatting artefact, not a change.

        PDF extraction is the main source of noise here: the same description comes
        out as "Set ofFuelLine- 1setconsist of:" from one document and
        "Set of Fuel Line - 1 set consist of:" from the other, and a quantity is
        "1 no." in a schedule but "01" in a parts list. Neither is a discrepancy,
        and reporting them buries the ones that are.
        """
        if field == 'qty':
            na, nb = _leading_number(a), _leading_number(b)
            if na is not None and nb is not None:
                return na == nb

        # Compare with every separator removed — this is the same spaced/no-space
        # trick the value matcher uses, for the same reason.
        ta = re.sub(r'[^A-Z0-9]', '', a)
        tb = re.sub(r'[^A-Z0-9]', '', b)
        if ta == tb:
            return True
        # A wrapped or truncated cell ("ANTIFRICTION RING" vs "ANTIFRICTION RING
        # OUTER DIA 115MM") is not a discrepancy worth reporting.
        short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if len(short) >= 4 and short in long_:
            return True
        # Descriptive text picks up character-level extraction damage
        # ("Drai Plug" vs "Drain plug"). Tolerate a couple of characters in a long
        # description — but never for identifiers, where one character is a
        # different part (see the note on pair_likely_values).
        if field == 'nomenclature' and len(short) >= 12:
            allowed = max(2, int(len(long_) * 0.05))
            return _levenshtein(ta, tb) <= allowed
        return False

    def load_structured_tables(self, source_name: str, doc_id: Optional[str] = None,
                               thread_ids: Optional[List[str]] = None) -> List[pd.DataFrame]:
        """Load table data from persisted ExtractedTable records instead of reopening PDFs."""
        query = ExtractedTable.objects.filter(source__iexact=source_name).prefetch_related('rows__cells')

        if doc_id:
            query = query.filter(doc_id=doc_id)
        if thread_ids:
            query = query.filter(thread_id__in=thread_ids)

        all_tables = []
        # Same continuation-page problem as the live extractor, except the bad
        # header is already persisted. Page order matters, so the header of a
        # table reaches the pages that continue it.
        header_memo: Dict[int, List[str]] = {}

        for table in query.order_by('page', 'table_index'):
            table_dict = table.to_dict()
            headers = table_dict.get('headers', []) or []
            table_data = table_dict.get('data', []) or []

            if headers and len(table_data) > 1:
                data_rows = table_data[1:]
            elif headers:
                data_rows = []
            else:
                data_rows = table_data

            if not data_rows:
                continue

            width = len(headers) if headers else max((len(r) for r in data_rows), default=0)
            if headers and self._looks_like_header(headers):
                header_memo[width] = [str(h) for h in headers]
            elif width in header_memo:
                if headers:
                    # What was stored as the header is really this page's first
                    # data row — put it back before adopting the real header.
                    data_rows = [list(headers)] + list(data_rows)
                headers = list(header_memo[width])

            if headers and any(str(h).strip() for h in headers):
                clean_headers = []
                seen_names = {}
                for i, h in enumerate(headers):
                    col_name = str(h).strip() if str(h).strip() else f'Column_{i+1}'
                    if col_name in seen_names:
                        seen_names[col_name] += 1
                        col_name = f"{col_name}_{seen_names[col_name]}"
                    else:
                        seen_names[col_name] = 0
                    clean_headers.append(col_name)

                target_cols = len(clean_headers)
                normalized_rows = []
                for row in data_rows:
                    row_vals = list(row)
                    if len(row_vals) < target_cols:
                        row_vals += [''] * (target_cols - len(row_vals))
                    elif len(row_vals) > target_cols:
                        row_vals = row_vals[:target_cols]
                    normalized_rows.append(row_vals)

                df = pd.DataFrame(normalized_rows, columns=clean_headers)
            else:
                target_cols = max((len(r) for r in data_rows), default=0)
                if target_cols == 0:
                    continue
                normalized_rows = []
                for row in data_rows:
                    row_vals = list(row)
                    if len(row_vals) < target_cols:
                        row_vals += [''] * (target_cols - len(row_vals))
                    elif len(row_vals) > target_cols:
                        row_vals = row_vals[:target_cols]
                    normalized_rows.append(row_vals)
                generated_headers = [f'Column_{i+1}' for i in range(target_cols)]
                df = pd.DataFrame(normalized_rows, columns=generated_headers)

            if not df.empty:
                df = df.fillna('')
                df['_source_page'] = table.page
                all_tables.append(df)

        return self._merge_similar_tables(all_tables)
    
    def _generate_comparison_summary(self, result: Dict) -> str:
        """Generate human-readable comparison summary."""
        pdf1 = result['pdf1']
        pdf2 = result['pdf2']
        column = result['column']
        comparison_type = result['comparison_type']
        
        summary = f"Comparison of '{column}' column:\n"
        summary += f"• {pdf1}: {result['pdf1_total']} unique values\n"
        summary += f"• {pdf2}: {result['pdf2_total']} unique values\n\n"
        
        results_data = result['results']
        
        if 'in_pdf1_only' in results_data:
            count = results_data['in_pdf1_only']['count']
            summary += f"Items in {pdf1} but NOT in {pdf2}: {count}\n"
            if count > 0:
                sample = results_data['in_pdf1_only']['values'][:5]
                summary += f"  Examples: {', '.join(sample)}\n"
                if count > 5:
                    summary += f"  ... and {count - 5} more\n"
        
        if 'in_pdf2_only' in results_data:
            count = results_data['in_pdf2_only']['count']
            summary += f"\nItems in {pdf2} but NOT in {pdf1}: {count}\n"
            if count > 0:
                sample = results_data['in_pdf2_only']['values'][:5]
                summary += f"  Examples: {', '.join(sample)}\n"
                if count > 5:
                    summary += f"  ... and {count - 5} more\n"
        
        if 'common' in results_data:
            count = results_data['common']['count']
            summary += f"\nCommon items (in both PDFs): {count}\n"
            if count > 0:
                sample = results_data['common']['values'][:5]
                summary += f"  Examples: {', '.join(sample)}\n"
                if count > 5:
                    summary += f"  ... and {count - 5} more\n"
        
        return summary
    
    def get_table_info(self, pdf_name: str) -> Dict[str, Any]:
        """Get information about extracted tables."""
        if pdf_name not in self.table_metadata:
            return {'error': f'No tables extracted from {pdf_name}'}
        
        metadata = self.table_metadata[pdf_name].copy()
        
        # Add sample data
        if pdf_name in self.extracted_tables and self.extracted_tables[pdf_name]:
            first_table = self.extracted_tables[pdf_name][0]
            metadata['sample_columns'] = [c for c in first_table.columns if not c.startswith('_')]
            metadata['sample_rows'] = first_table.head(3).to_dict('records')
        
        return metadata


# Global instance
_search_engine = TableSearchEngine()
_MISSING = object()   # sentinel: "key was absent" when saving/restoring cache entries


def extract_and_index_pdf(pdf_path: str) -> Dict[str, Any]:
    """Extract tables from PDF and index them for searching."""
    return _search_engine.extract_tables_from_pdf(pdf_path)


def search_in_pdf(pdf_path: str, query: str, query_type: str = 'general') -> Dict[str, Any]:
    """
    Search for a query in PDF tables.
    
    Args:
        pdf_path: Path to PDF file
        query: Search query
        query_type: 'drawing_number', 'part_number', or 'general'
    """
    pdf_name = Path(pdf_path).name
    
    # Extract tables if not already done
    if pdf_name not in _search_engine.extracted_tables:
        extract_and_index_pdf(pdf_path)
    
    if query_type == 'drawing_number':
        return _search_engine.search_drawing_number(pdf_name, query)
    elif query_type == 'part_number':
        return _search_engine.search_part_number(pdf_name, query)
    else:
        return _search_engine.search_value(pdf_name, query)


def get_pdf_table_info(pdf_path: str) -> Dict[str, Any]:
    """Get information about tables in a PDF."""
    pdf_name = Path(pdf_path).name
    
    if pdf_name not in _search_engine.extracted_tables:
        extract_and_index_pdf(pdf_path)
    
    return _search_engine.get_table_info(pdf_name)


def compare_pdfs(pdf1_path: str, pdf2_path: str, column_name: str,
                column_name_pdf2: Optional[str] = None,
                match_any_column_in_pdf2: bool = False,
                comparison_type: str = 'difference',
                category1: Optional[str] = None,
                category2: Optional[str] = None,
                prefer_literal: bool = False,
                force_extract: bool = False,
                doc1_id: Optional[str] = None,
                doc2_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Compare a specific column between two PDFs.

    Args:
        pdf1_path: Path to first PDF (e.g., MRLS)
        pdf2_path: Path to second PDF (e.g., ISPL)
        column_name: Column to compare (e.g., 'Part Number', 'DRG')
        comparison_type: 'difference', 'common', 'unique_both', or 'all'
        force_extract: re-read both PDFs even if tables for these filenames are
            already cached (the cache is keyed by bare filename, so a caller that
            just ran the DB-backed compare must not be handed those tables back)
    
    Returns:
        Dictionary with comparison results
    """
    pdf1_name = Path(pdf1_path).name
    pdf2_name = Path(pdf2_path).name
    
    # Extract tables if not already done
    if force_extract or pdf1_name not in _search_engine.extracted_tables:
        extract_and_index_pdf(pdf1_path)
    
    if force_extract or pdf2_name not in _search_engine.extracted_tables:
        extract_and_index_pdf(pdf2_path)
    
    return _search_engine.compare_tables(
        pdf1_name,
        pdf2_name,
        column_name,
        column_name_pdf2,
        match_any_column_in_pdf2,
        comparison_type,
        category1=category1,
        category2=category2,
        prefer_literal=prefer_literal,
        doc1_id=doc1_id,
        doc2_id=doc2_id,
    )


def compare_structured_sources(source1_name: str, source2_name: str, column_name: str,
                               column_name_pdf2: Optional[str] = None,
                               match_any_column_in_pdf2: bool = False,
                               comparison_type: str = 'difference',
                               doc1_id: Optional[str] = None,
                               doc2_id: Optional[str] = None,
                               thread_ids: Optional[List[str]] = None,
                               category1: Optional[str] = None,
                               category2: Optional[str] = None,
                               prefer_literal: bool = False) -> Dict[str, Any]:
    """
    Compare values by reading persisted structured tables from DB.
    This avoids file-path dependency and works even when uploaded PDFs are no longer on disk.
    """
    source1_tables = _search_engine.load_structured_tables(source1_name, doc_id=doc1_id, thread_ids=thread_ids)
    source2_tables = _search_engine.load_structured_tables(source2_name, doc_id=doc2_id, thread_ids=thread_ids)

    if not source1_tables or not source2_tables:
        return {'found': False, 'error': 'Structured tables not available for one or both sources'}

    # compare_tables reads from the engine's filename-keyed cache, so the DB
    # tables are placed there for the duration of the call only. Whatever the
    # cache held before (file-extracted tables for a same-named PDF, or nothing)
    # is put back afterwards — otherwise the file-based fallback that callers run
    # next would silently reuse these DB tables instead of re-reading the PDF.
    cache = _search_engine.extracted_tables
    saved = {name: cache.get(name, _MISSING) for name in (source1_name, source2_name)}
    cache[source1_name] = source1_tables
    cache[source2_name] = source2_tables
    try:
        return _search_engine.compare_tables(
            source1_name,
            source2_name,
            column_name,
            column_name_pdf2,
            match_any_column_in_pdf2,
            comparison_type,
            category1=category1,
            category2=category2,
            prefer_literal=prefer_literal,
            doc1_id=doc1_id,
            doc2_id=doc2_id,
        )
    finally:
        for name, prev in saved.items():
            if prev is _MISSING:
                cache.pop(name, None)
            else:
                cache[name] = prev


def confirm_match(source_a: str, source_b: str, column_name: str,
                  value_a: str, value_b: str, note: str = "",
                  thread_id: Optional[str] = None) -> Dict[str, Any]:
    """Persist a human-confirmed value pairing (see TableSearchEngine.confirm_match)."""
    return _search_engine.confirm_match(source_a, source_b, column_name, value_a, value_b,
                                        note=note, thread_id=thread_id)


def detect_conflicts(pdf1_path: str, pdf2_path: str = None) -> Dict[str, Any]:
    """
    Detect data conflicts within a PDF or between two PDFs:
    - Same nomenclature with different part numbers
    - Same part number with different nomenclatures
    
    Args:
        pdf1_path: Path to first PDF (required)
        pdf2_path: Path to second PDF (optional, for cross-file conflicts)
    
    Returns:
        Dictionary with conflict analysis
    """
    pdf1_name = Path(pdf1_path).name
    
    # Extract tables if not already done
    if pdf1_name not in _search_engine.extracted_tables:
        extract_and_index_pdf(pdf1_path)
    
    # Collect all part-nomenclature mappings
    part_to_nomenclature = {}  # {part_number: [nomenclature1, nomenclature2, ...]}
    nomenclature_to_part = {}  # {nomenclature: [part_number1, part_number2, ...]}
    
    def extract_mappings(pdf_name, source_label):
        """Extract part number and nomenclature mappings from a PDF."""
        tables = _search_engine.extracted_tables.get(pdf_name, [])
        
        for df in tables:
            # Find part number columns
            part_cols = [col for col in df.columns if not col.startswith('_') and 
                        any(kw in col.lower() for kw in ['part', 'p/n', 'drg', 'dwg', 'drawing'])]
            
            # Find nomenclature columns
            nom_cols = [col for col in df.columns if not col.startswith('_') and 
                       any(kw in col.lower() for kw in ['nomenclature', 'designation', 'description', 'name', 'item'])]
            
            if not part_cols or not nom_cols:
                continue
            
            # Use first matching columns
            part_col = part_cols[0]
            nom_col = nom_cols[0]
            
            for _, row in df.iterrows():
                part_val = str(row[part_col]).strip().upper() if pd.notna(row[part_col]) else ''
                nom_val = str(row[nom_col]).strip().upper() if pd.notna(row[nom_col]) else ''
                
                if not part_val or not nom_val or part_val.lower() in ['nan', 'none', ''] or nom_val.lower() in ['nan', 'none', '']:
                    continue
                
                # Track mappings with source info
                if part_val not in part_to_nomenclature:
                    part_to_nomenclature[part_val] = []
                
                entry = {'nomenclature': nom_val, 'source': source_label}
                if '_source_page' in row:
                    entry['page'] = int(row['_source_page'])
                
                # Avoid duplicate entries
                if not any(e['nomenclature'] == nom_val for e in part_to_nomenclature[part_val]):
                    part_to_nomenclature[part_val].append(entry)
                
                if nom_val not in nomenclature_to_part:
                    nomenclature_to_part[nom_val] = []
                
                part_entry = {'part': part_val, 'source': source_label}
                if '_source_page' in row:
                    part_entry['page'] = int(row['_source_page'])
                
                if not any(e['part'] == part_val for e in nomenclature_to_part[nom_val]):
                    nomenclature_to_part[nom_val].append(part_entry)
    
    # Extract from PDF1
    extract_mappings(pdf1_name, pdf1_name)
    
    # Extract from PDF2 if provided
    if pdf2_path:
        pdf2_name = Path(pdf2_path).name
        if pdf2_name not in _search_engine.extracted_tables:
            extract_and_index_pdf(pdf2_path)
        extract_mappings(pdf2_name, pdf2_name)
    
    # Find conflicts
    conflicts = {
        'part_number_conflicts': [],  # Same part with different nomenclatures
        'nomenclature_conflicts': []  # Same nomenclature with different parts
    }
    
    # Check for part number conflicts
    for part, entries in part_to_nomenclature.items():
        unique_nomenclatures = list(set(e['nomenclature'] for e in entries))
        if len(unique_nomenclatures) > 1:
            conflicts['part_number_conflicts'].append({
                'part_number': part,
                'nomenclatures': unique_nomenclatures,
                'count': len(unique_nomenclatures),
                'sources': entries
            })
    
    # Check for nomenclature conflicts
    for nomenclature, entries in nomenclature_to_part.items():
        unique_parts = list(set(e['part'] for e in entries))
        if len(unique_parts) > 1:
            conflicts['nomenclature_conflicts'].append({
                'nomenclature': nomenclature,
                'part_numbers': unique_parts,
                'count': len(unique_parts),
                'sources': entries
            })
    
    # Generate summary
    summary = "## 🔍 Data Conflict Analysis\n\n"
    
    if pdf2_path:
        summary += f"**Comparing:** {pdf1_name} ↔️ {Path(pdf2_path).name}\n\n"
    else:
        summary += f"**Analyzing:** {pdf1_name}\n\n"
    
    part_conflicts = len(conflicts['part_number_conflicts'])
    nom_conflicts = len(conflicts['nomenclature_conflicts'])
    
    if part_conflicts == 0 and nom_conflicts == 0:
        summary += "✅ **No conflicts detected!** All part numbers have consistent nomenclatures.\n"
    else:
        if part_conflicts > 0:
            summary += f"⚠️ **{part_conflicts} Part Number Conflicts** - Same part with different nomenclatures\n"
        if nom_conflicts > 0:
            summary += f"⚠️ **{nom_conflicts} Nomenclature Conflicts** - Same nomenclature with different parts\n"
    
    conflicts['summary'] = summary
    conflicts['found'] = True
    conflicts['total_conflicts'] = part_conflicts + nom_conflicts
    
    return conflicts
