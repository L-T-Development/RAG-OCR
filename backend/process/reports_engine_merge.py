"""
Reports Engine - Multi-PDF Comparator Integration
Ported from Comparator-main with proper OCR/scanning logic

Features:
- Column extraction from Excel/PDF/Images
- Multi-PDF comparison against source values
- Accurate page number detection using PyPDF2
- Real-time progress updates
- In-memory Excel report generation
"""

import pandas as pd
from pathlib import Path
from typing import Set, List, Dict, Any, Callable
import re
import os
import io
from datetime import datetime


def log_progress(message: str):
    """Simple progress logger."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def _md_cells(line: str) -> List[str]:
    if '|' not in line:
        return []
    cells = [c.strip() for c in line.split('|') if c.strip()]
    if not cells:
        return []
    return cells


def _normalize_for_match(text: str) -> tuple:
    """
    Return (spaced, nospace) variants of `text` for resilient substring matching.
    PDF extractors often drop spaces when a cell spans multiple lines, so a value like
    'BIG LAUNCHER PAD' (source) becomes 'BIG LAUNCHERPAD' in the target text. Matching
    on `nospace` recovers those cases without false positives, because we strip ALL
    whitespace on both sides before comparing.
    """
    if text is None:
        return "", ""
    s = str(text).lower()
    spaced = re.sub(r"\s+", " ", s).strip()
    nospace = re.sub(r"\s+", "", s)
    return spaced, nospace


def _contains_value(haystack_spaced: str, haystack_nospace: str, needle: str) -> bool:
    """True if `needle` appears in either the space-normalized or the no-space haystack."""
    n_spaced, n_nospace = _normalize_for_match(needle)
    if not n_nospace:
        return False
    if n_spaced and n_spaced in haystack_spaced:
        return True
    return n_nospace in haystack_nospace


def _is_continuation_row(cells: List[str], headers: List[str]) -> bool:
    if not headers or not cells:
        return False
    min_cols = 1 if len(headers) == 1 else 2
    return len(cells) >= max(min_cols, len(headers) - 2) and len(cells) <= len(headers) + 2

class AdvancedComparator:
    """
    Compare specific column values from source file against target files.
    Uses Docling for text extraction + PyPDF2 for accurate page numbers.
    """
    
    def __init__(self, use_ocr: bool = True, progress_callback: Callable = None):
        self.use_ocr = use_ocr
        self.converter = None
        self.progress_callback = progress_callback or log_progress
        self._init_docling()
    
    def _log(self, message: str):
        if self.progress_callback:
            self.progress_callback(message)
    
    def _init_docling(self):
        """Initialize Docling with OCR settings."""
        try:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = self.use_ocr
            pipeline_options.do_table_structure = True
            
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options
                    )
                }
            )
            self._log("✓ Docling OCR engine initialized")
        except ImportError:
            self._log("⚠ Docling not available - using PyPDF2 only")
            self.converter = None
        except Exception as e:
            self._log(f"⚠ Docling init error: {e}")
            self.converter = None
    
    # ==================== COLUMN EXTRACTION ====================
    
    def get_columns(self, file_path: str) -> List[str]:
        """Get column names from file."""
        ext = Path(file_path).suffix.lower()
        filename = Path(file_path).name
        self._log(f"📂 Reading columns from: {filename}")
        
        if ext in ['.xlsx', '.xls']:
            return self._get_excel_columns(file_path)
        elif ext == '.pdf':
            return self._get_pdf_columns(file_path)
        elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            return self._get_image_columns(file_path)
        return []
    
    def _get_excel_columns(self, file_path: str) -> List[str]:
        try:
            df = pd.read_excel(file_path)
            columns = list(df.columns)
            self._log(f"✓ Found {len(columns)} columns")
            return columns
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return []
    
    def _get_pdf_columns(self, file_path: str) -> List[str]:
        if not self.converter:
            return ["[All extracted text]"]
        try:
            result = self.converter.convert(str(file_path))
            markdown = result.document.export_to_markdown()
            
            columns = set()
            lines = markdown.split('\n')
            for i, line in enumerate(lines):
                if '|' in line and i + 1 < len(lines) and '---' in lines[i + 1]:
                    cells = [c.strip() for c in line.split('|') if c.strip()]
                    columns.update(cells)
            
            if columns:
                self._log(f"✓ Found {len(columns)} table columns")
                return sorted(list(columns))
            return ["[All extracted text]"]
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return []
    
    def _get_image_columns(self, file_path: str) -> List[str]:
        if not self.converter:
            return ["[All extracted text]"]
        try:
            result = self.converter.convert(str(file_path))
            markdown = result.document.export_to_markdown()
            
            columns = set()
            lines = markdown.split('\n')
            for i, line in enumerate(lines):
                if '|' in line and i + 1 < len(lines) and '---' in lines[i + 1]:
                    cells = [c.strip() for c in line.split('|') if c.strip()]
                    columns.update(cells)
            
            return sorted(list(columns)) if columns else ["[All extracted text]"]
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return []
    
    # ==================== VALUE EXTRACTION ====================
    
    def extract_values_from_file(self, file_path: str, column_name: str) -> Set[str]:
        """Extract values from a specific column."""
        ext = Path(file_path).suffix.lower()
        
        if ext in ['.xlsx', '.xls']:
            return self._extract_excel_column(file_path, column_name)
        elif ext == '.pdf':
            return self._extract_pdf_column(file_path, column_name)
        elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            return self._extract_image_column(file_path, column_name)
        return set()
    
    def _is_valid_value(self, value: str) -> bool:
        """Check if a value is valid (not just separators/dashes/empty)."""
        if not value or not value.strip():
            return False
        v = value.strip()
        # Skip values that are just dashes, dots, underscores, or other separators
        if all(c in '-_.=~*#|/' for c in v):
            return False
        # Skip very short values (likely noise)
        if len(v) < 2:
            return False
        # Skip values that are mostly dashes/dots (like "----" or "...")
        separator_count = sum(1 for c in v if c in '-_.=~')
        if separator_count > len(v) * 0.7:
            return False
        return True
    
    def _extract_excel_column(self, file_path: str, column_name: str) -> Set[str]:
        try:
            df = pd.read_excel(file_path)
            if column_name not in df.columns:
                self._log(f"✗ Column '{column_name}' not found!")
                return set()
            
            values = df[column_name].dropna().astype(str).unique()
            values = {str(v).strip() for v in values if self._is_valid_value(str(v))}
            self._log(f"✓ Extracted {len(values)} unique values from '{column_name}'")
            return values
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return set()
    
    def _extract_pdf_column(self, file_path: str, column_name: str) -> Set[str]:
        if not self.converter:
            return set()
        try:
            result = self.converter.convert(str(file_path))
            markdown = result.document.export_to_markdown()
            
            values = set()
            lines = markdown.split('\n')
            column_index = -1
            current_table_headers = []
            in_table = False
            
            for i, line in enumerate(lines):
                cells = _md_cells(line)
                if not cells:
                    if in_table and not line.strip():
                        # Empty line indicates end of table, keep headers for continuation
                        in_table = False
                    continue

                # Detect table header row (followed by separator line)
                if i + 1 < len(lines) and '---' in lines[i + 1]:
                    current_table_headers = cells
                    column_index = -1
                    in_table = True

                    # Find exact column match
                    for idx, cell in enumerate(cells):
                        if cell == column_name:
                            column_index = idx
                            self._log(f"  ??? Found column '{column_name}' at position {idx+1}/{len(cells)}")
                            break

                # Extract data from the correct column only (allow continuation across pages)
                elif (in_table or _is_continuation_row(cells, current_table_headers)) and column_index >= 0:
                    in_table = True
                    # More lenient: allow extraction if column position exists
                    # OCR may have inconsistent cell counts
                    if column_index < len(cells):
                        val = cells[column_index].strip()
                        if val and val != column_name and self._is_valid_value(val):
                            values.add(val)
                    # Only reset if cell count is drastically different (not just +/- 1-2)
                    elif len(cells) < len(current_table_headers) - 2:
                        # Major structure change, reset
                        in_table = False
                        column_index = -1
                        current_table_headers = []
            self._log(f"✓ Extracted {len(values)} values from PDF column '{column_name}'")
            return values
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return set()
    
    def _extract_image_column(self, file_path: str, column_name: str) -> Set[str]:
        """Extract column from image using same logic as PDF - maintains column structure."""
        return self._extract_pdf_column(file_path, column_name)
    
    # ==================== SEARCH FUNCTIONS ====================
    
    def search_values_in_file(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """Search for values in target file."""
        ext = Path(file_path).suffix.lower()
        
        if ext in ['.xlsx', '.xls']:
            return self._search_in_excel(file_path, search_values)
        elif ext == '.pdf':
            return self._search_in_pdf(file_path, search_values)
        elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            return self._search_in_image(file_path, search_values)
        return {'found': {}, 'not_found': search_values}
    
    def _search_in_excel(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        try:
            df = pd.read_excel(file_path)
            found = {}
            
            for col in df.columns:
                for idx, value in enumerate(df[col].dropna(), start=2):
                    value_str = str(value).strip()
                    for search_val in search_values:
                        if search_val in value_str or value_str in search_val:
                            if search_val not in found:
                                found[search_val] = []
                            location = f"Row {idx}"
                            if location not in found[search_val]:
                                found[search_val].append(location)
            
            not_found = search_values - set(found.keys())
            return {'found': found, 'not_found': not_found}
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return {'found': {}, 'not_found': search_values}
    
    def _search_in_pdf(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """
        Search values in PDF using HYBRID approach:
        1. PyPDF2 for text extraction and page numbers
        2. Docling OCR for scanned/image pages
        Handles mixed documents with both text and scanned photos/tables.
        """
        found = {}
        not_found = set(search_values)
        
        # Step 1: Try PyPDF2 text extraction first (fast for text PDFs)
        page_texts_pypdf = {}
        scanned_pages = []  # Pages that need OCR
        
        try:
            import PyPDF2
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                total_pages = len(reader.pages)
                self._log(f"  → Scanning {total_pages} pages...")
                
                for page_num in range(total_pages):
                    page_text = reader.pages[page_num].extract_text() or ""
                    page_texts_pypdf[page_num + 1] = page_text
                    
                    # If page has very little text, it might be scanned
                    if len(page_text.strip()) < 50:
                        scanned_pages.append(page_num + 1)
                
                if scanned_pages:
                    self._log(f"  → {len(scanned_pages)} pages may be scanned (need OCR)")
        except Exception as e:
            self._log(f"  → PyPDF2 error: {e}")
            # Fallback to OCR for entire document
            scanned_pages = list(range(1, 100))  # Assume all pages need OCR
        
        # Step 2: Use Docling OCR for scanned pages (handles images, tables, text)
        ocr_full_text = ""
        if self.converter and (scanned_pages or not page_texts_pypdf):
            try:
                self._log("  → Running OCR with Docling (handles scanned photos, tables, text)...")
                result = self.converter.convert(str(file_path))
                ocr_full_text = result.document.export_to_markdown()
                self._log(f"  → OCR extracted {len(ocr_full_text)} characters")
            except Exception as e:
                self._log(f"  → OCR error: {e}")
        
        # Step 3: Combine PyPDF2 and OCR results for comprehensive search
        values_in_pdf = set()
        
        # Step 4: Search page-by-page with hybrid text (PyPDF2 + OCR)
        value_pages = {val: [] for val in search_values}
        matches_found = 0
        
        # Scan each page with PyPDF2 text
        for page_num, page_text in page_texts_pypdf.items():
            # For scanned pages, also check OCR text
            if page_num in scanned_pages and ocr_full_text:
                # OCR text contains all pages merged, but we search it anyway
                combined_text = page_text + "\n" + ocr_full_text
            else:
                combined_text = page_text

            # Pre-normalize page text once — search_values is iterated for every page.
            haystack_spaced, haystack_nospace = _normalize_for_match(combined_text)

            page_matches = 0
            for search_val in search_values:
                if _contains_value(haystack_spaced, haystack_nospace, search_val):
                    if not value_pages[search_val]:  # First match
                        matches_found += 1
                    if page_num not in value_pages[search_val]:
                        value_pages[search_val].append(page_num)
                    page_matches += 1
            
            # Progress logging
            if page_num % 10 == 0 or page_num == len(page_texts_pypdf):
                self._log(f"  → Page {page_num}/{len(page_texts_pypdf)} | Found: {matches_found}/{len(search_values)}")
            elif page_matches > 0:
                self._log(f"  → Page {page_num}: {page_matches} match(es)")
        
        # Step 5: For values still not found, do a final OCR-only check
        if ocr_full_text:
            ocr_spaced, ocr_nospace = _normalize_for_match(ocr_full_text)
            for search_val in search_values:
                if not value_pages[search_val]:  # Not found in PyPDF2 text
                    if _contains_value(ocr_spaced, ocr_nospace, search_val):
                        value_pages[search_val].append("OCR Detected")
                        matches_found += 1
                        self._log(f"  -> '{str(search_val).strip()}' found via OCR (scanned content)")
        
        # Build final results with page numbers
        for search_val, pages in value_pages.items():
            if pages:
                found[search_val] = pages
                not_found.discard(search_val)
        
        self._log(f"  → Final: {len(found)} found, {len(not_found)} not found")
        
        return {'found': found, 'not_found': not_found}
    
    def _search_in_image(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """Search in image files with OCR - handles scanned photos with tables and text."""
        if not self.converter:
            self._log("  → No OCR engine available for image")
            return {'found': {}, 'not_found': search_values}
        try:
            self._log("  → Running OCR on image (handles tables, text, photos)...")
            result = self.converter.convert(str(file_path))
            text = result.document.export_to_markdown()
            
            self._log(f"  → OCR extracted {len(text)} characters")
            
            found = {}
            for search_val in search_values:
                search_str = str(search_val).strip()
                if search_str in text:
                    found[search_val] = ["Image (OCR)"]
                    self._log(f"  → Found '{search_str}' in image")
            
            not_found = search_values - set(found.keys())
            self._log(f"  → Image results: {len(found)} found, {len(not_found)} not found")
            return {'found': found, 'not_found': not_found}
        except Exception as e:
            self._log(f"✗ OCR Error: {e}")
            return {'found': {}, 'not_found': search_values}


class MultiPDFComparator:
    """Compare values from source file against multiple PDFs."""
    
    def __init__(self, use_ocr: bool = False, progress_callback: Callable = None):
        self.progress_callback = progress_callback or log_progress
        self.comparator = AdvancedComparator(use_ocr=use_ocr, progress_callback=self.progress_callback)
    
    def _log(self, message: str):
        if self.progress_callback:
            self.progress_callback(message)
    
    def compare_against_multiple_pdfs(
        self, 
        source_file: str, 
        column_name: str, 
        pdf_files: List[str],
        job_updater: Callable = None
    ) -> Dict[str, Any]:
        """Compare source column values against multiple PDFs."""
        
        self._log("=" * 60)
        self._log("🚀 STARTING MULTI-PDF COMPARISON")
        self._log("=" * 60)
        
        # Extract values from source
        source_name = Path(source_file).name
        self._log(f"\n📋 Extracting values from '{column_name}'")
        self._log(f"   Source: {source_name}")
        
        search_values = self.comparator.extract_values_from_file(source_file, column_name)
        total_values = len(search_values)
        
        if total_values == 0:
            self._log("✗ No values found!")
            return {'error': 'No values found in source column'}
        
        self._log(f"   ✓ Found {total_values} unique values to search")
        
        # Track results
        all_found = {}  # {value: {pdf_name: [pages]}}
        still_not_found = set(search_values)
        pdf_results = []
        
        # Search each PDF
        total_pdfs = len(pdf_files)
        for i, pdf_file in enumerate(pdf_files, 1):
            pdf_name = Path(pdf_file).name
            
            self._log(f"\n📄 Searching PDF {i}/{total_pdfs}: {pdf_name}")
            self._log(f"   Values remaining: {len(still_not_found)}")
            
            if job_updater:
                progress = 15 + int((i / total_pdfs) * 75)
                job_updater(progress, f"Searching {pdf_name}...")
            
            result = self.comparator.search_values_in_file(pdf_file, still_not_found)
            
            found_in_pdf = result['found']
            found_count = len(found_in_pdf)
            
            self._log(f"   ✓ Found {found_count} matches")
            
            # Show samples
            if found_count > 0:
                samples = list(found_in_pdf.keys())[:3]
                self._log(f"   Sample: {samples}")
            
            # Update tracking
            for value, locations in found_in_pdf.items():
                if value not in all_found:
                    all_found[value] = {}
                all_found[value][pdf_name] = locations
                still_not_found.discard(value)
            
            pdf_results.append({
                'pdf_name': pdf_name,
                'found_count': found_count,
                'found': found_in_pdf
            })
        
        # Summary
        total_found = len(all_found)
        total_not_found = len(still_not_found)
        match_pct = (total_found / total_values * 100) if total_values > 0 else 0
        
        self._log("\n" + "=" * 60)
        self._log("📊 COMPARISON COMPLETE")
        self._log("=" * 60)
        self._log(f"   Total searched: {total_values}")
        self._log(f"   ✓ Found: {total_found} ({match_pct:.1f}%)")
        self._log(f"   ✗ Not found: {total_not_found}")
        
        if total_not_found > 0 and total_not_found <= 10:
            self._log(f"   Missing: {list(still_not_found)}")
        elif total_not_found > 10:
            self._log(f"   Missing (first 5): {list(still_not_found)[:5]}")
        
        return {
            'source_file': Path(source_file).name,
            'column_name': column_name,
            'pdf_files': [Path(p).name for p in pdf_files],
            'total_values': total_values,
            'all_found': {k: v for k, v in all_found.items()},
            'not_found': list(still_not_found),
            'found_count': total_found,
            'not_found_count': total_not_found,
            'match_percentage': round(match_pct, 2),
            'pdf_results': pdf_results,
            'timestamp': datetime.now().isoformat()
        }
    
    def generate_excel_bytes(self, result: Dict[str, Any]) -> bytes:
        """Generate Excel report as bytes (for direct download)."""
        self._log("\n📥 Generating Excel report...")
        
        output = io.BytesIO()
        
        try:
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
            
            # Summary data
            summary_data = {
                'Metric': [
                    'Source File', 'Column Name', 'PDFs Searched',
                    'Total Values', 'Found', 'Not Found', 'Match %', 'Generated'
                ],
                'Value': [
                    result.get('source_file', ''),
                    result.get('column_name', ''),
                    len(result.get('pdf_files', [])),
                    result.get('total_values', 0),
                    result.get('found_count', 0),
                    result.get('not_found_count', 0),
                    f"{result.get('match_percentage', 0):.1f}%",
                    result.get('timestamp', datetime.now().isoformat())
                ]
            }
            df_summary = pd.DataFrame(summary_data)
            
            # PDF summary
            pdf_rows = []
            for pr in result.get('pdf_results', []):
                pdf_rows.append({
                    'PDF File': pr['pdf_name'],
                    'Matches Found': pr['found_count']
                })
            df_pdf_summary = pd.DataFrame(pdf_rows) if pdf_rows else pd.DataFrame()
            
            # Found values with locations (like Comparator-main format)
            found_rows = []
            for value, pdf_locations in result.get('all_found', {}).items():
                for pdf_name, locations in pdf_locations.items():
                    if isinstance(locations, list):
                        # Format: "Page 1, Page 3, Page 5" or "OCR Detected"
                        pages_formatted = []
                        for loc in locations:
                            if isinstance(loc, int):
                                pages_formatted.append(f"Page {loc}")
                            else:
                                pages_formatted.append(str(loc))
                        pages_str = ', '.join(pages_formatted)
                        page_count = len(locations)
                    else:
                        pages_str = str(locations)
                        page_count = 1
                    found_rows.append({
                        'Value': value,
                        'Status': '✓ Found',
                        'PDF File': pdf_name,
                        'Found At': pages_str,
                        'Occurrences': page_count
                    })
            df_found = pd.DataFrame(found_rows) if found_rows else pd.DataFrame()
            
            # Not found values
            not_found_list = result.get('not_found', [])
            df_not_found = pd.DataFrame({
                'Value': list(not_found_list),
                'Status': ['✗ Not Found'] * len(not_found_list)
            }) if not_found_list else pd.DataFrame()
            
            # Write to Excel with formatting
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_summary.to_excel(writer, sheet_name='Summary', index=False)
                if not df_pdf_summary.empty:
                    df_pdf_summary.to_excel(writer, sheet_name='PDF Summary', index=False)
                if not df_found.empty:
                    df_found.to_excel(writer, sheet_name='Found Values', index=False)
                if not df_not_found.empty:
                    df_not_found.to_excel(writer, sheet_name='Not Found', index=False)
                
                # Style workbook
                workbook = writer.book
                header_fill = PatternFill(start_color="667EEA", end_color="667EEA", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF")
                found_fill = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
                not_found_fill = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
                
                for sheet_name in workbook.sheetnames:
                    ws = workbook[sheet_name]
                    
                    # Auto-width columns
                    for column in ws.columns:
                        max_len = 0
                        col_letter = get_column_letter(column[0].column)
                        for cell in column:
                            try:
                                if len(str(cell.value)) > max_len:
                                    max_len = len(str(cell.value))
                            except:
                                pass
                        ws.column_dimensions[col_letter].width = min(max_len + 2, 60)
                    
                    # Header style
                    for cell in ws[1]:
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.alignment = Alignment(horizontal='center')
                    
                    # Data style
                    if sheet_name == 'Found Values':
                        for row in ws.iter_rows(min_row=2):
                            for cell in row:
                                cell.fill = found_fill
                    elif sheet_name == 'Not Found':
                        for row in ws.iter_rows(min_row=2):
                            for cell in row:
                                cell.fill = not_found_fill
            
            self._log("   ✓ Excel report generated")
            output.seek(0)
            return output.getvalue()
            
        except Exception as e:
            self._log(f"   ✗ Error generating Excel: {e}")
            import traceback
            traceback.print_exc()
            raise


# ==================== DJANGO INTEGRATION ====================

_report_jobs = {}


def create_report_job(
    source_path: str,
    source_filename: str,
    column_name: str,
    pdf_paths: List[str],
    pdf_filenames: List[str],
    use_ocr: bool = False
) -> str:
    """Create background report job."""
    import threading
    import uuid
    
    job_id = str(uuid.uuid4())
    
    _report_jobs[job_id] = {
        'status': 'pending',
        'progress': 0,
        'progress_message': 'Starting...',
        'result': None,
        'excel_bytes': None,
        'error': None,
        'source_file': source_filename,
        'column_name': column_name,
        'pdf_count': len(pdf_paths),
        'logs': []
    }
    
    def add_log(message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        _report_jobs[job_id]['logs'].append(log_entry)
        print(log_entry)
    
    def update_progress(progress: int, message: str = ""):
        _report_jobs[job_id]['progress'] = progress
        if message:
            _report_jobs[job_id]['progress_message'] = message
    
    def run_comparison():
        try:
            _report_jobs[job_id]['status'] = 'processing'
            update_progress(5, 'Initializing...')
            add_log("🚀 Job started")
            
            comparator = MultiPDFComparator(use_ocr=use_ocr, progress_callback=add_log)
            
            update_progress(10, 'Extracting values from source...')
            
            result = comparator.compare_against_multiple_pdfs(
                source_file=source_path,
                column_name=column_name,
                pdf_files=pdf_paths,
                job_updater=update_progress
            )
            
            update_progress(92, 'Generating Excel report...')
            
            # Generate Excel in memory (no file save)
            excel_bytes = comparator.generate_excel_bytes(result)
            
            # Store for download
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            result['excel_filename'] = f'Report_{timestamp}.xlsx'
            
            _report_jobs[job_id]['status'] = 'completed'
            _report_jobs[job_id]['result'] = result
            _report_jobs[job_id]['excel_bytes'] = excel_bytes
            update_progress(100, 'Complete!')
            
            add_log("✓ Job completed!")
            
            # Cleanup temp files
            try:
                os.unlink(source_path)
                for pdf_path in pdf_paths:
                    os.unlink(pdf_path)
            except:
                pass
                
        except Exception as e:
            add_log(f"✗ Job failed: {e}")
            import traceback
            traceback.print_exc()
            _report_jobs[job_id]['status'] = 'failed'
            _report_jobs[job_id]['error'] = str(e)
    
    thread = threading.Thread(target=run_comparison)
    thread.start()
    
    return job_id


def get_report_job_status(job_id: str) -> Dict[str, Any]:
    """Get job status."""
    return _report_jobs.get(job_id, None)


def get_report_excel_bytes(job_id: str) -> bytes:
    """Get Excel bytes for download."""
    job = _report_jobs.get(job_id)
    if job and job.get('status') == 'completed':
        return job.get('excel_bytes')
    return None


def get_file_columns(file_path: str) -> List[str]:
    """Quick helper to get columns only (fast, no preview)."""
    comparator = AdvancedComparator(use_ocr=True)
    return comparator.get_columns(file_path)


def get_column_preview(file_path: str, column_name: str, preview_count: int = 10) -> Dict[str, Any]:
    """
    Get preview for a SPECIFIC column (lazy loading).
    Returns: {"column": "col_name", "preview": ["val1", "val2", ...], "total_count": 123}
    """
    comparator = AdvancedComparator(use_ocr=True)
    ext = Path(file_path).suffix.lower()
    filename = Path(file_path).name
    
    print(f"[Preview] Fetching preview for column '{column_name}' from {filename}")
    
    preview_values = []
    total_count = 0
    
    if ext in ['.xlsx', '.xls']:
        # Excel files - read specific column
        try:
            df = pd.read_excel(file_path)
            if column_name in df.columns:
                all_values = df[column_name].dropna().astype(str)
                # Filter valid values
                valid_values = [str(v).strip() for v in all_values if comparator._is_valid_value(str(v))]
                unique_values = list(dict.fromkeys(valid_values))  # Preserve order, remove duplicates
                total_count = len(unique_values)
                preview_values = unique_values[:preview_count]
            print(f"[Preview] Excel column '{column_name}': {total_count} values")
        except Exception as e:
            print(f"[Preview] Excel error: {e}")
    
    elif ext == '.pdf':
        # PDF files - extract specific column using Docling with strict position tracking
        try:
            if comparator.converter:
                result = comparator.converter.convert(str(file_path))
                markdown = result.document.export_to_markdown()
                
                lines = markdown.split('\n')
                column_values = []
                current_headers = []
                column_index = -1
                table_active = False
                
                for i, line in enumerate(lines):
                    cells = _md_cells(line)
                    if not cells:
                        if table_active and not line.strip():
                            # Empty line ends table, keep headers for continuation
                            table_active = False
                        continue

                    # Header row (followed by separator)
                    if i + 1 < len(lines) and '---' in lines[i + 1]:
                        current_headers = cells
                        table_active = True
                        column_index = -1
                        # Find exact column match
                        for idx, h in enumerate(cells):
                            if h == column_name:
                                column_index = idx
                                print(f"[Preview] Column '{column_name}' at position {idx+1}/{len(cells)}")
                                break
                    # Data row - more lenient for OCR variations, allow continuation
                    elif (table_active or _is_continuation_row(cells, current_headers)) and column_index >= 0:
                        table_active = True
                        if column_index < len(cells):
                            cell = cells[column_index].strip()
                            if comparator._is_valid_value(cell) and cell not in column_values:
                                column_values.append(cell)
                        # Only reset if drastically different structure
                        elif len(cells) < len(current_headers) - 2:
                            table_active = False
                            column_index = -1
                            current_headers = []
                # Handle [All extracted text]
                if column_name == "[All extracted text]":
                    text_lines = [l.strip() for l in lines if l.strip() and '|' not in l and '---' not in l]
                    column_values = [t[:80] + '...' if len(t) > 80 else t for t in text_lines]
                
                total_count = len(column_values)
                preview_values = column_values[:preview_count]
                print(f"[Preview] PDF column '{column_name}': {total_count} values")
            else:
                # Fallback PyPDF2
                import PyPDF2
                with open(file_path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    text = ""
                    for page in reader.pages[:5]:
                        text += page.extract_text() or ""
                    lines = [l.strip() for l in text.split('\n') if l.strip()]
                    total_count = len(lines)
                    preview_values = lines[:preview_count]
        except Exception as e:
            print(f"[Preview] PDF error: {e}")
    
    elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
        # Image files - use Docling OCR
        try:
            if comparator.converter:
                result = comparator.converter.convert(str(file_path))
                markdown = result.document.export_to_markdown()
                
                lines = markdown.split('\n')
                column_values = []
                current_headers = []
                column_index = -1
                table_active = False
                
                for i, line in enumerate(lines):
                    cells = _md_cells(line)
                    if not cells:
                        if table_active and not line.strip():
                            table_active = False
                        continue

                    if i + 1 < len(lines) and '---' in lines[i + 1]:
                        current_headers = cells
                        table_active = True
                        column_index = -1
                        for idx, h in enumerate(cells):
                            if h == column_name:
                                column_index = idx
                                break
                    elif (table_active or _is_continuation_row(cells, current_headers)) and column_index >= 0:
                        table_active = True
                        if column_index < len(cells):
                            cell = cells[column_index].strip()
                            if comparator._is_valid_value(cell) and cell not in column_values:
                                column_values.append(cell)
                        elif len(cells) < len(current_headers) - 2:
                            table_active = False
                            column_index = -1
                            current_headers = []
                if column_name == "[All extracted text]":
                    text_lines = [l.strip() for l in lines if l.strip() and '|' not in l and '---' not in l]
                    column_values = [t[:80] + '...' if len(t) > 80 else t for t in text_lines]
                
                total_count = len(column_values)
                preview_values = column_values[:preview_count]
                print(f"[Preview] Image column '{column_name}': {total_count} values")
        except Exception as e:
            print(f"[Preview] Image error: {e}")
    
    return {
        "column": column_name,
        "preview": preview_values,
        "total_count": total_count
    }


def get_file_columns_with_preview(file_path: str, preview_count: int = 5) -> Dict[str, Any]:
    """
    Get columns with preview of sample values for ALL file types.
    Returns: {"columns": [...], "preview": {"col1": ["val1", "val2", ...], ...}}
    """
    # Use OCR for better extraction from PDFs and images
    comparator = AdvancedComparator(use_ocr=True)
    columns = comparator.get_columns(file_path)
    preview = {}
    
    ext = Path(file_path).suffix.lower()
    filename = Path(file_path).name
    print(f"[Preview] Extracting preview for {filename} ({ext})")
    
    if ext in ['.xlsx', '.xls']:
        # Excel files - read directly with pandas
        try:
            df = pd.read_excel(file_path)
            for col in columns:
                if col in df.columns:
                    # Get first N non-null unique values
                    values = df[col].dropna().astype(str).unique()
                    preview_vals = [str(v).strip() for v in values[:preview_count * 2] 
                                   if comparator._is_valid_value(str(v))]
                    preview[col] = preview_vals[:preview_count]
            print(f"[Preview] Excel: Found previews for {len(preview)} columns")
        except Exception as e:
            print(f"[Preview] Excel error: {e}")
    
    elif ext == '.pdf':
        # PDF files - use Docling to extract table data
        try:
            if comparator.converter:
                result = comparator.converter.convert(str(file_path))
                markdown = result.document.export_to_markdown()
                
                # Parse markdown tables with strict column position tracking
                lines = markdown.split('\n')
                table_data = {}  # {column_name: [values]}
                current_headers = []
                table_active = False
                
                for i, line in enumerate(lines):
                    cells = _md_cells(line)
                    if not cells:
                        if table_active and not line.strip():
                            # Empty line ends table, keep headers for continuation
                            table_active = False
                        continue

                    # Check if this is a header row (next line has ---)
                    if i + 1 < len(lines) and '---' in lines[i + 1]:
                        current_headers = cells
                        table_active = True
                        for h in current_headers:
                            if h not in table_data:
                                table_data[h] = []
                        print(f"[Preview] Found table with {len(current_headers)} columns: {current_headers[:3]}...")

                    # Data row - lenient for OCR variations, allow continuation
                    elif (table_active or _is_continuation_row(cells, current_headers)) and current_headers:
                        table_active = True
                        # Process cells that exist, even if count doesn't match exactly
                        max_idx = min(len(cells), len(current_headers))
                        for idx in range(max_idx):
                            cell = cells[idx]
                            header = current_headers[idx]
                            if header in table_data and comparator._is_valid_value(cell):
                                if cell not in table_data[header]:  # Avoid duplicates
                                    table_data[header].append(cell)
                        # Only reset if drastically different
                        if len(cells) < len(current_headers) - 2:
                            table_active = False
                            current_headers = []
                # Build preview from extracted data
                for col in columns:
                    if col in table_data and table_data[col]:
                        preview[col] = table_data[col][:preview_count]
                    elif col == "[All extracted text]":
                        # Extract some sample text snippets
                        text_lines = [l.strip() for l in lines if l.strip() and '|' not in l and '---' not in l]
                        sample_texts = [t[:50] + '...' if len(t) > 50 else t for t in text_lines[:preview_count]]
                        preview[col] = sample_texts
                
                print(f"[Preview] PDF: Found previews for {len(preview)} columns")
            else:
                # Fallback: try PyPDF2 text extraction
                try:
                    import PyPDF2
                    with open(file_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        text = ""
                        for page in reader.pages[:3]:  # First 3 pages
                            text += page.extract_text() or ""
                        
                        if text.strip():
                            lines = [l.strip() for l in text.split('\n') if l.strip()]
                            preview["[All extracted text]"] = lines[:preview_count]
                except Exception as e2:
                    print(f"[Preview] PyPDF2 fallback error: {e2}")
                    
        except Exception as e:
            print(f"[Preview] PDF error: {e}")
    
    elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
        # Image files - use Docling OCR
        try:
            if comparator.converter:
                result = comparator.converter.convert(str(file_path))
                markdown = result.document.export_to_markdown()
                
                # Parse with strict column structure validation (same as PDF)
                lines = markdown.split('\n')
                table_data = {}
                current_headers = []
                table_active = False
                
                for i, line in enumerate(lines):
                    cells = _md_cells(line)
                    if not cells:
                        if table_active and not line.strip():
                            table_active = False
                        continue

                    if i + 1 < len(lines) and '---' in lines[i + 1]:
                        current_headers = cells
                        table_active = True
                        for h in current_headers:
                            if h not in table_data:
                                table_data[h] = []
                        print(f"[Preview] Image table: {len(current_headers)} columns")

                    elif (table_active or _is_continuation_row(cells, current_headers)) and current_headers:
                        table_active = True
                        # More lenient: process available cells
                        max_idx = min(len(cells), len(current_headers))
                        for idx in range(max_idx):
                            cell = cells[idx]
                            header = current_headers[idx]
                            if header in table_data and comparator._is_valid_value(cell):
                                if cell not in table_data[header]:
                                    table_data[header].append(cell)
                        # Only reset if major structure change
                        if len(cells) < len(current_headers) - 2:
                            table_active = False
                            current_headers = []
                for col in columns:
                    if col in table_data and table_data[col]:
                        preview[col] = table_data[col][:preview_count]
                    elif col == "[All extracted text]":
                        text_lines = [l.strip() for l in lines if l.strip() and '|' not in l and '---' not in l]
                        sample_texts = [t[:50] + '...' if len(t) > 50 else t for t in text_lines[:preview_count]]
                        preview[col] = sample_texts
                
                print(f"[Preview] Image: Found previews for {len(preview)} columns")
            else:
                preview["[All extracted text]"] = ["OCR not available - install Docling"]
        except Exception as e:
            print(f"[Preview] Image error: {e}")
    
    return {"columns": columns, "preview": preview}


# ==================== SINGLE PDF COMPARISON ====================

class SinglePDFComparator:
    """
    Compare values from source file against a SINGLE PDF.
    Uses hybrid text extraction + OCR for mixed text/scanned documents.
    """
    
    def __init__(self, use_ocr: bool = True, progress_callback: Callable = None):
        self.use_ocr = use_ocr
        self.progress_callback = progress_callback or log_progress
        self.converter = None
        self._init_engines()
    
    def _log(self, message: str):
        if self.progress_callback:
            self.progress_callback(message)
    
    def _init_engines(self):
        """Initialize both PyPDF2 and Docling for hybrid extraction."""
        # Initialize Docling for OCR
        try:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = self.use_ocr
            pipeline_options.do_table_structure = True
            
            self.converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options
                    )
                }
            )
            self._log("✓ Hybrid OCR engine initialized")
        except ImportError:
            self._log("⚠ Docling not available - using text extraction only")
            self.converter = None
        except Exception as e:
            self._log(f"⚠ Docling init error: {e}")
            self.converter = None
    
    def compare(self, source_path: str, column_name: str, pdf_path: str) -> Dict[str, Any]:
        """
        Compare source column values against a single PDF using hybrid extraction.
        Returns detailed results with page locations.
        """
        source_name = Path(source_path).name
        pdf_name = Path(pdf_path).name
        
        self._log(f"📊 Single PDF Comparison Started")
        self._log(f"   Source: {source_name}")
        self._log(f"   Column: {column_name}")
        self._log(f"   Target: {pdf_name}")
        self._log("-" * 50)
        
        # Extract values from source
        comparator = AdvancedComparator(use_ocr=False, progress_callback=self.progress_callback)
        source_values = comparator.extract_values_from_file(source_path, column_name)
        
        if not source_values:
            self._log("✗ No values extracted from source!")
            return {
                "status": "error",
                "message": "No values found in source column",
                "found": {},
                "not_found": []
            }
        
        self._log(f"📋 Searching for {len(source_values)} values in PDF...")
        
        # Search using hybrid method
        results = self._hybrid_search(pdf_path, source_values)
        
        found_count = len(results['found'])
        not_found_count = len(results['not_found'])
        
        self._log("-" * 50)
        self._log(f"✅ Found: {found_count} values")
        self._log(f"❌ Not Found: {not_found_count} values")
        
        return {
            "status": "completed",
            "source_file": source_name,
            "column": column_name,
            "pdf_file": pdf_name,
            "total_values": len(source_values),
            "found": results['found'],
            "not_found": list(results['not_found'])
        }
    
    def _hybrid_search(self, pdf_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """
        Hybrid search: Try text extraction first, then OCR for pages with no text.
        This handles PDFs with mixed text and scanned content.
        """
        found = {}
        page_texts = {}
        
        # First pass: PyPDF2 text extraction
        try:
            import PyPDF2
            with open(pdf_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                total_pages = len(reader.pages)
                self._log(f"📄 PDF has {total_pages} pages")
                
                pages_with_text = 0
                pages_need_ocr = []
                
                for page_num in range(total_pages):
                    text = reader.pages[page_num].extract_text() or ""
                    page_texts[page_num + 1] = text
                    
                    if len(text.strip()) > 50:
                        pages_with_text += 1
                    else:
                        pages_need_ocr.append(page_num + 1)
                
                self._log(f"   Text found on {pages_with_text} pages")
                if pages_need_ocr:
                    self._log(f"   {len(pages_need_ocr)} pages may need OCR")
        except Exception as e:
            self._log(f"⚠ PyPDF2 error: {e}")
            total_pages = 0
        
        # Second pass: If OCR enabled and converter available, process scanned pages
        # This handles scanned photos with tables and text
        if self.use_ocr and self.converter and pages_need_ocr:
            self._log(f"🔍 Running OCR on {len(pages_need_ocr)} scanned pages...")
            self._log("   (Detecting tables, text, and images in scanned content)")
            try:
                result = self.converter.convert(str(pdf_path))
                ocr_text = result.document.export_to_markdown()
                
                self._log(f"   OCR extracted {len(ocr_text)} characters from scanned pages")
                
                # For OCR results, enhance scanned page texts
                # Since Docling gives full document, we add it to scanned pages
                for page_num in pages_need_ocr:
                    if page_num in page_texts:
                        # Combine existing text with OCR (OCR contains tables/images)
                        page_texts[page_num] = page_texts[page_num] + "\n" + ocr_text
                    else:
                        page_texts[page_num] = ocr_text
                        
                self._log(f"   Enhanced {len(pages_need_ocr)} pages with OCR data")
            except Exception as e:
                self._log(f"⚠ OCR error: {e}")
        
        # Search through all page texts
        self._log(f"🔎 Searching through {len(page_texts)} pages...")
        
        for page_num, text in page_texts.items():
            if page_num % 10 == 0:
                self._log(f"   Scanned {page_num}/{total_pages} pages...")
            
            for value in search_values:
                if value in text:
                    if value not in found:
                        found[value] = []
                    location = f"Page {page_num}"
                    if location not in found[value]:
                        found[value].append(location)
        
        not_found = search_values - set(found.keys())
        
        return {'found': found, 'not_found': not_found}


def create_single_pdf_job(source_path: str, column_name: str, pdf_path: str, 
                          use_ocr: bool = True) -> str:
    """Create and start a single PDF comparison job."""
    import uuid
    import threading
    
    job_id = str(uuid.uuid4())[:8]
    
    _report_jobs[job_id] = {
        'status': 'processing',
        'progress': [],
        'result': None
    }
    
    def progress_handler(msg):
        if job_id in _report_jobs:
            _report_jobs[job_id]['progress'].append(msg)
        print(f"[Job {job_id}] {msg}")
    
    def run_job():
        try:
            comparator = SinglePDFComparator(use_ocr=use_ocr, progress_callback=progress_handler)
            result = comparator.compare(source_path, column_name, pdf_path)
            
            if job_id in _report_jobs:
                _report_jobs[job_id]['status'] = 'completed'
                _report_jobs[job_id]['result'] = result
                
                # Generate Excel report
                excel_bytes = generate_single_pdf_excel(result)
                _report_jobs[job_id]['excel_bytes'] = excel_bytes
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            if job_id in _report_jobs:
                _report_jobs[job_id]['status'] = 'error'
                _report_jobs[job_id]['error'] = str(e)
    
    thread = threading.Thread(target=run_job)
    thread.start()
    
    return job_id


def get_multi_pdf_columns_with_preview(pdf_paths: List[str], preview_count: int = 10) -> Dict[str, Any]:
    """
    Extract columns from multiple PDFs and merge tables with matching column names.
    If tables have same columns, merge data; otherwise keep separate.
    
    Returns: {"columns": [...], "preview": {"col1": [values...], ...}, "merged_tables": int}
    """
    from collections import defaultdict
    
    print(f"[MultiPDF] Processing {len(pdf_paths)} PDFs for column extraction...")
    
    # Track all columns and their data across PDFs
    all_column_data = defaultdict(list)  # {column_name: [values from all PDFs]}
    all_columns_set = set()
    merged_count = 0
    
    comparator = AdvancedComparator(use_ocr=True)
    
    for i, pdf_path in enumerate(pdf_paths, 1):
        pdf_name = Path(pdf_path).name
        print(f"[MultiPDF] Processing PDF {i}/{len(pdf_paths)}: {pdf_name}")
        
        try:
            # Get columns and preview from this PDF
            result = get_file_columns_with_preview(pdf_path, preview_count=preview_count * 2)
            pdf_columns = result.get('columns', [])
            pdf_preview = result.get('preview', {})
            
            print(f"[MultiPDF]   Found {len(pdf_columns)} columns in {pdf_name}")
            
            # Check which columns match with existing ones (for merging)
            for col in pdf_columns:
                if col in all_columns_set:
                    # Column exists - merge data
                    print(f"[MultiPDF]   Merging column '{col}' from {pdf_name}")
                    merged_count += 1
                    if col in pdf_preview:
                        # Add new values, avoiding duplicates
                        for val in pdf_preview[col]:
                            if val not in all_column_data[col]:
                                all_column_data[col].append(val)
                else:
                    # New column
                    all_columns_set.add(col)
                    if col in pdf_preview:
                        all_column_data[col].extend(pdf_preview[col])
        
        except Exception as e:
            print(f"[MultiPDF] Error processing {pdf_name}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Limit preview values
    final_preview = {}
    for col, values in all_column_data.items():
        # Remove duplicates while preserving order
        unique_values = []
        seen = set()
        for val in values:
            if val not in seen:
                unique_values.append(val)
                seen.add(val)
        final_preview[col] = unique_values[:preview_count]
    
    all_columns = sorted(list(all_columns_set))
    
    print(f"[MultiPDF] Complete: {len(all_columns)} unique columns, {merged_count} merges")
    
    return {
        "columns": all_columns,
        "preview": final_preview,
        "merged_tables": merged_count,
        "total_pdfs": len(pdf_paths)
    }


def generate_single_pdf_excel(result: Dict[str, Any]) -> bytes:
    """Generate Excel report for single PDF comparison."""
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
    
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Summary sheet
        summary_data = [
            ['Single PDF Comparison Report', ''],
            ['Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['', ''],
            ['Source File', result.get('source_file', 'N/A')],
            ['Column', result.get('column', 'N/A')],
            ['PDF File', result.get('pdf_file', 'N/A')],
            ['', ''],
            ['Total Values', result.get('total_values', 0)],
            ['Found', len(result.get('found', {}))],
            ['Not Found', len(result.get('not_found', []))]
        ]
        summary_df = pd.DataFrame(summary_data, columns=['Field', 'Value'])
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
        
        # Found Values sheet
        found_data = []
        for value, locations in result.get('found', {}).items():
            found_data.append([value, ', '.join(locations)])
        
        if found_data:
            found_df = pd.DataFrame(found_data, columns=['Value', 'Found At'])
            found_df.to_excel(writer, sheet_name='Found Values', index=False)
        
        # Not Found Values sheet
        not_found = result.get('not_found', [])
        if not_found:
            nf_df = pd.DataFrame({'Value': not_found, 'Status': ['NOT FOUND'] * len(not_found)})
            nf_df.to_excel(writer, sheet_name='Not Found', index=False)
        
        # Style the workbook
        workbook = writer.book
        green_fill = PatternFill(start_color='C6EFCE', end_color='C6EFCE', fill_type='solid')
        red_fill = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid')
        
        # Style Found sheet
        if 'Found Values' in workbook.sheetnames:
            ws = workbook['Found Values']
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                for cell in row:
                    cell.fill = green_fill
        
        # Style Not Found sheet
        if 'Not Found' in workbook.sheetnames:
            ws = workbook['Not Found']
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                for cell in row:
                    cell.fill = red_fill
    
    output.seek(0)
    return output.getvalue()