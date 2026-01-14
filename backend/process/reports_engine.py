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
            
            for i, line in enumerate(lines):
                if '|' in line:
                    cells = [c.strip() for c in line.split('|') if c.strip()]
                    if i + 1 < len(lines) and '---' in lines[i + 1]:
                        for idx, cell in enumerate(cells):
                            if cell == column_name:
                                column_index = idx
                                break
                    elif column_index >= 0 and column_index < len(cells):
                        val = cells[column_index].strip()
                        if val and val != column_name and self._is_valid_value(val):
                            values.add(val)
            
            self._log(f"✓ Extracted {len(values)} values from PDF column")
            return values
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return set()
    
    def _extract_image_column(self, file_path: str, column_name: str) -> Set[str]:
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
        Search values in PDF using Docling + PyPDF2 for accurate page numbers.
        This is the HYBRID approach from Comparator-main.
        """
        found = {}
        not_found = set(search_values)
        
        # Step 1: Use Docling to find which values exist in PDF
        values_in_pdf = set()
        
        if self.converter:
            try:
                self._log("  → Converting PDF with Docling...")
                result = self.converter.convert(str(file_path))
                full_text = result.document.export_to_markdown()
                
                for search_val in search_values:
                    if str(search_val).strip() in full_text:
                        values_in_pdf.add(search_val)
                
                self._log(f"  → Docling found {len(values_in_pdf)} values in text")
            except Exception as e:
                self._log(f"  → Docling error: {e}, using PyPDF2 only")
                values_in_pdf = search_values
        else:
            values_in_pdf = search_values
        
        # Step 2: Use PyPDF2 for accurate page number detection
        # This is the KEY improvement - scan each page ONCE for all values
        try:
            import PyPDF2
            
            with open(file_path, 'rb') as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                total_pages = len(pdf_reader.pages)
                self._log(f"  → Total pages to scan: {total_pages}")
                
                # Track pages for each value
                value_pages = {val: [] for val in values_in_pdf}
                matches_found = 0
                
                # OPTIMIZED: Scan each page once and check ALL values
                for page_num in range(total_pages):
                    try:
                        page = pdf_reader.pages[page_num]
                        page_text = page.extract_text() or ""
                        
                        page_matches = 0
                        # Check all values against this page
                        for search_val in values_in_pdf:
                            search_str = str(search_val).strip()
                            if search_str in page_text:
                                if not value_pages[search_val]:  # First time finding this value
                                    matches_found += 1
                                value_pages[search_val].append(page_num + 1)
                                page_matches += 1
                        
                        # Progress every 10 pages or if matches found
                        if (page_num + 1) % 10 == 0 or page_num == total_pages - 1:
                            self._log(f"  → Page {page_num + 1}/{total_pages} done | Matches: {matches_found}/{len(values_in_pdf)}")
                        elif page_matches > 0:
                            self._log(f"  → Page {page_num + 1}: Found {page_matches} value(s)")
                            
                    except Exception as page_err:
                        self._log(f"  → Page {page_num + 1}: Error reading - {page_err}")
                        continue
                
                self._log(f"  → Scan complete: {matches_found} values found across {total_pages} pages")
                
                # Build results
                final_found = 0
                for search_val, pages in value_pages.items():
                    if pages:
                        found[search_val] = pages
                        not_found.discard(search_val)
                        final_found += 1
                    elif search_val in values_in_pdf:
                        # Docling found it but PyPDF2 didn't (might be in images)
                        found[search_val] = ["Found (page detection failed)"]
                        not_found.discard(search_val)
                        final_found += 1
                
                self._log(f"  → Results: {final_found} found, {len(not_found)} not found")
                        
        except ImportError:
            self._log("  → PyPDF2 not available")
            # Fallback: mark Docling-found values without page numbers
            for val in values_in_pdf:
                found[val] = ["Page info unavailable"]
                not_found.discard(val)
        except Exception as e:
            self._log(f"  → PyPDF2 error: {e}")
        
        return {'found': found, 'not_found': not_found}
    
    def _search_in_image(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        if not self.converter:
            return {'found': {}, 'not_found': search_values}
        try:
            result = self.converter.convert(str(file_path))
            text = result.document.export_to_markdown()
            
            found = {}
            for search_val in search_values:
                if str(search_val).strip() in text:
                    found[search_val] = ["Image"]
            
            not_found = search_values - set(found.keys())
            return {'found': found, 'not_found': not_found}
        except Exception as e:
            self._log(f"✗ Error: {e}")
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
            
            # Found values with locations
            found_rows = []
            for value, pdf_locations in result.get('all_found', {}).items():
                for pdf_name, locations in pdf_locations.items():
                    if isinstance(locations, list):
                        pages_str = ', '.join(f"Page {p}" for p in locations)
                        page_count = len(locations)
                    else:
                        pages_str = str(locations)
                        page_count = 1
                    found_rows.append({
                        'Value': value,
                        'Status': '✓ Found',
                        'PDF File': pdf_name,
                        'Pages': pages_str,
                        'Page Count': page_count
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
    """Quick helper to get columns."""
    comparator = AdvancedComparator(use_ocr=False)
    return comparator.get_columns(file_path)
