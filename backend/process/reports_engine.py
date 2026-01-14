"""
Reports Engine - Multi-PDF Comparator Integration
Ported from Comparator-main folder with Django integration

Features:
- Column extraction from Excel/PDF/Images
- Multi-PDF comparison against Excel values
- Detailed location tracking (page numbers)
- Report generation with Excel export
- Real-time progress updates
"""

import pandas as pd
from pathlib import Path
from typing import Set, List, Dict, Any, Callable
import re
import os
import tempfile
from datetime import datetime
import json


def log_progress(message: str):
    """Simple progress logger that prints to console."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


class AdvancedComparator:
    """
    Compare specific column values from source file (Excel/PDF/Image) 
    against target files (PDF/Excel/Image).
    """
    
    def __init__(self, use_ocr: bool = True, progress_callback: Callable = None):
        """
        Initialize comparator with optional OCR support.
        
        Args:
            use_ocr: Enable OCR for scanned PDFs and images
            progress_callback: Optional callback for progress updates
        """
        self.use_ocr = use_ocr
        self.converter = None
        self.progress_callback = progress_callback or log_progress
        self._init_docling()
    
    def _log(self, message: str):
        """Log message using callback."""
        if self.progress_callback:
            self.progress_callback(message)
    
    def _init_docling(self):
        """Initialize Docling converter with appropriate settings."""
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
            
        except ImportError as e:
            self._log(f"⚠ Docling not available - using PyPDF2 fallback")
            self.converter = None
        except Exception as e:
            self._log(f"⚠ Docling init error: {e}")
            self.converter = None
    
    # ==================== COLUMN EXTRACTION ====================
    
    def get_columns(self, file_path: str) -> List[str]:
        """Get list of column names from file."""
        ext = Path(file_path).suffix.lower()
        filename = Path(file_path).name
        self._log(f"📂 Reading columns from: {filename}")
        
        if ext in ['.xlsx', '.xls']:
            return self._get_excel_columns(file_path)
        elif ext == '.pdf':
            return self._get_pdf_columns(file_path)
        elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            return self._get_image_columns(file_path)
        else:
            self._log(f"⚠ Unsupported file type: {ext}")
            return []
    
    def _get_excel_columns(self, file_path: str) -> List[str]:
        """Extract column headers from Excel file."""
        try:
            df = pd.read_excel(file_path)
            columns = list(df.columns)
            self._log(f"✓ Found {len(columns)} columns in Excel")
            return columns
        except Exception as e:
            self._log(f"✗ Error reading Excel: {e}")
            return []
    
    def _get_pdf_columns(self, file_path: str) -> List[str]:
        """Extract column headers from PDF tables using Docling."""
        if not self.converter:
            return ["[All extracted text]"]
        
        try:
            self._log("📄 Converting PDF to extract columns...")
            result = self.converter.convert(str(file_path))
            markdown = result.document.export_to_markdown()
            
            columns = set()
            lines = markdown.split('\n')
            
            for i, line in enumerate(lines):
                if '|' in line:
                    if i + 1 < len(lines) and '---' in lines[i + 1]:
                        cells = [c.strip() for c in line.split('|') if c.strip()]
                        columns.update(cells)
            
            if columns:
                result_cols = sorted(list(columns))
                self._log(f"✓ Found {len(result_cols)} table columns in PDF")
                return result_cols
            else:
                self._log("ℹ No tables found in PDF")
                return ["[All extracted text]"]
                
        except Exception as e:
            self._log(f"✗ Error reading PDF: {e}")
            return []
    
    def _get_image_columns(self, file_path: str) -> List[str]:
        """Extract column headers from image using OCR."""
        if not self.converter:
            return ["[All extracted text]"]
        
        try:
            self._log("🖼 Processing image with OCR...")
            result = self.converter.convert(str(file_path))
            markdown = result.document.export_to_markdown()
            
            columns = set()
            lines = markdown.split('\n')
            
            for i, line in enumerate(lines):
                if '|' in line:
                    if i + 1 < len(lines) and '---' in lines[i + 1]:
                        cells = [c.strip() for c in line.split('|') if c.strip()]
                        columns.update(cells)
            
            if columns:
                return sorted(list(columns))
            return ["[All extracted text]"]
            
        except Exception as e:
            self._log(f"✗ Error reading image: {e}")
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
        else:
            return set()
    
    def _extract_excel_column(self, file_path: str, column_name: str) -> Set[str]:
        """Extract values from Excel column."""
        try:
            df = pd.read_excel(file_path)
            
            if column_name not in df.columns:
                self._log(f"✗ Column '{column_name}' not found!")
                return set()
            
            values = df[column_name].dropna().astype(str).unique()
            values = {str(v).strip() for v in values if str(v).strip()}
            
            self._log(f"✓ Extracted {len(values)} unique values from '{column_name}'")
            return values
            
        except Exception as e:
            self._log(f"✗ Error: {e}")
            return set()
    
    def _extract_pdf_column(self, file_path: str, column_name: str) -> Set[str]:
        """Extract values from PDF column."""
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
                        if val and val != column_name:
                            values.add(val)
            
            self._log(f"✓ Extracted {len(values)} values from PDF column")
            return values
            
        except Exception as e:
            self._log(f"✗ Error extracting from PDF: {e}")
            return set()
    
    def _extract_image_column(self, file_path: str, column_name: str) -> Set[str]:
        """Extract values from image column using OCR."""
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
                        if val and val != column_name:
                            values.add(val)
            
            return values
            
        except Exception as e:
            self._log(f"✗ Error extracting from image: {e}")
            return set()
    
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
        else:
            return {'found': {}, 'not_found': search_values, 'has_pages': False}
    
    def _search_in_excel(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """Search values in Excel file."""
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
            return {'found': found, 'not_found': not_found, 'has_pages': False}
            
        except Exception as e:
            self._log(f"✗ Error searching Excel: {e}")
            return {'found': {}, 'not_found': search_values, 'has_pages': False}
    
    def _search_in_pdf(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """Search values in PDF with page number tracking."""
        try:
            import PyPDF2
            
            # First pass with Docling to find which values exist
            values_in_pdf = set()
            if self.converter:
                self._log("  → Converting PDF for text extraction...")
                result = self.converter.convert(str(file_path))
                full_text = result.document.export_to_markdown()
                
                for search_val in search_values:
                    if str(search_val).strip() in full_text:
                        values_in_pdf.add(search_val)
                
                self._log(f"  → Found {len(values_in_pdf)} values in PDF text")
            else:
                values_in_pdf = search_values
            
            # Second pass: use PyPDF2 for page numbers
            found = {}
            
            with open(file_path, 'rb') as pdf_file:
                pdf_reader = PyPDF2.PdfReader(pdf_file)
                total_pages = len(pdf_reader.pages)
                self._log(f"  → Scanning {total_pages} pages for matches...")
                
                value_pages = {val: [] for val in values_in_pdf}
                
                for page_num in range(total_pages):
                    try:
                        page = pdf_reader.pages[page_num]
                        page_text = page.extract_text() or ""
                        
                        for search_val in values_in_pdf:
                            if str(search_val).strip() in page_text:
                                value_pages[search_val].append(page_num + 1)
                        
                        # Progress update every 25 pages
                        if (page_num + 1) % 25 == 0 or page_num == total_pages - 1:
                            self._log(f"  → Scanned {page_num + 1}/{total_pages} pages")
                            
                    except Exception:
                        continue
                
                for search_val, pages in value_pages.items():
                    if pages:
                        found[search_val] = pages
                    elif search_val in values_in_pdf:
                        found[search_val] = ["Found (page unknown)"]
            
            not_found = search_values - set(found.keys())
            return {'found': found, 'not_found': not_found, 'has_pages': True}
            
        except ImportError:
            return self._search_in_pdf_docling_only(file_path, search_values)
        except Exception as e:
            self._log(f"✗ Error searching PDF: {e}")
            return {'found': {}, 'not_found': search_values, 'has_pages': False}
    
    def _search_in_pdf_docling_only(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """Fallback PDF search using only Docling."""
        if not self.converter:
            return {'found': {}, 'not_found': search_values, 'has_pages': False}
        
        try:
            result = self.converter.convert(str(file_path))
            full_text = result.document.export_to_markdown()
            
            found = {}
            for search_val in search_values:
                if str(search_val).strip() in full_text:
                    found[search_val] = ["Page info unavailable"]
            
            not_found = search_values - set(found.keys())
            return {'found': found, 'not_found': not_found, 'has_pages': False}
            
        except Exception as e:
            return {'found': {}, 'not_found': search_values, 'has_pages': False}
    
    def _search_in_image(self, file_path: str, search_values: Set[str]) -> Dict[str, Any]:
        """Search values in image using OCR."""
        if not self.converter:
            return {'found': {}, 'not_found': search_values, 'has_pages': False}
        
        try:
            result = self.converter.convert(str(file_path))
            text = result.document.export_to_markdown()
            
            found = {}
            for search_val in search_values:
                if search_val in text:
                    found[search_val] = ["Image"]
            
            not_found = search_values - set(found.keys())
            return {'found': found, 'not_found': not_found, 'has_pages': False}
            
        except Exception as e:
            return {'found': {}, 'not_found': search_values, 'has_pages': False}


class MultiPDFComparator:
    """Compare values from Excel/PDF against multiple PDF files."""
    
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
        """
        Compare source column values against multiple PDF files.
        """
        self._log("="*60)
        self._log("🚀 STARTING MULTI-PDF COMPARISON")
        self._log("="*60)
        
        # Extract values from source
        source_name = Path(source_file).name
        self._log(f"\n📋 Step 1: Extracting values from '{column_name}'")
        self._log(f"   Source: {source_name}")
        
        search_values = self.comparator.extract_values_from_file(source_file, column_name)
        total_values = len(search_values)
        
        if total_values == 0:
            self._log("✗ No values found to search!")
            return {
                'error': 'No values found in source column',
                'source_file': source_name,
                'column_name': column_name
            }
        
        self._log(f"   ✓ Found {total_values} unique values to search")
        
        # Track results
        all_found = {}
        still_not_found = set(search_values)
        pdf_results = []
        
        # Search in each PDF
        total_pdfs = len(pdf_files)
        for i, pdf_file in enumerate(pdf_files, 1):
            pdf_name = Path(pdf_file).name
            
            self._log(f"\n📄 Step {i+1}: Searching in PDF {i}/{total_pdfs}")
            self._log(f"   File: {pdf_name}")
            self._log(f"   Remaining values to find: {len(still_not_found)}")
            
            # Update job progress
            if job_updater:
                progress = 20 + int((i / total_pdfs) * 70)
                job_updater(progress, f"Searching PDF {i}/{total_pdfs}: {pdf_name}")
            
            result = self.comparator.search_values_in_file(pdf_file, still_not_found)
            
            found_in_this_pdf = result['found']
            found_count = len(found_in_this_pdf)
            
            self._log(f"   ✓ Found {found_count} matches in this PDF")
            
            # Show sample of what was found
            if found_count > 0:
                samples = list(found_in_this_pdf.keys())[:3]
                self._log(f"   Sample matches: {samples}")
            
            # Update tracking
            for value, locations in found_in_this_pdf.items():
                if value not in all_found:
                    all_found[value] = {}
                all_found[value][pdf_name] = locations
                still_not_found.discard(value)
            
            pdf_results.append({
                'pdf_name': pdf_name,
                'pdf_path': pdf_file,
                'found_count': found_count,
                'found': found_in_this_pdf
            })
        
        # Calculate summary
        total_found = len(all_found)
        total_not_found = len(still_not_found)
        match_percentage = (total_found / total_values * 100) if total_values > 0 else 0
        
        self._log("\n" + "="*60)
        self._log("📊 COMPARISON COMPLETE - SUMMARY")
        self._log("="*60)
        self._log(f"   Total values searched: {total_values}")
        self._log(f"   ✓ Found: {total_found} ({match_percentage:.1f}%)")
        self._log(f"   ✗ Not found: {total_not_found}")
        self._log(f"   PDFs searched: {total_pdfs}")
        
        # Show not found samples
        if total_not_found > 0 and total_not_found <= 10:
            self._log(f"\n   Not found values: {list(still_not_found)}")
        elif total_not_found > 10:
            self._log(f"\n   Sample not found: {list(still_not_found)[:5]}...")
        
        self._log("="*60)
        
        return {
            'source_file': Path(source_file).name,
            'column_name': column_name,
            'pdf_files': [Path(p).name for p in pdf_files],
            'total_values': total_values,
            'all_found': {k: v for k, v in all_found.items()},
            'not_found': list(still_not_found),
            'found_count': total_found,
            'not_found_count': total_not_found,
            'match_percentage': round(match_percentage, 2),
            'pdf_results': pdf_results,
            'timestamp': datetime.now().isoformat()
        }
    
    def export_to_excel(self, result: Dict[str, Any], output_file: str) -> str:
        """Export comparison results to Excel file."""
        self._log(f"\n📥 Exporting report to Excel...")
        
        try:
            from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
            from openpyxl.utils import get_column_letter
            
            # Summary sheet
            summary_data = {
                'Metric': [
                    'Source File', 'Column Name', 'Number of PDFs Searched',
                    'Total Values', 'Found (Total)', 'Not Found', 'Match %',
                    'Generated At'
                ],
                'Value': [
                    result['source_file'], result['column_name'],
                    len(result['pdf_files']), result['total_values'],
                    result['found_count'], result['not_found_count'],
                    f"{result['match_percentage']:.1f}%",
                    result.get('timestamp', datetime.now().isoformat())
                ]
            }
            df_summary = pd.DataFrame(summary_data)
            
            # PDF summary
            pdf_summary_rows = []
            for pdf_result in result.get('pdf_results', []):
                pdf_summary_rows.append({
                    'PDF File': pdf_result['pdf_name'],
                    'Matches Found': pdf_result['found_count']
                })
            df_pdf_summary = pd.DataFrame(pdf_summary_rows) if pdf_summary_rows else pd.DataFrame()
            
            # Found values with locations
            found_rows = []
            for value, pdf_locations in result.get('all_found', {}).items():
                for pdf_name, locations in pdf_locations.items():
                    if isinstance(locations, list):
                        pages_str = ', '.join(f"Page {loc}" for loc in locations)
                        page_count = len(locations)
                    else:
                        pages_str = str(locations)
                        page_count = 1
                    found_rows.append({
                        'Value': value,
                        'Status': '✓ Found',
                        'PDF File': pdf_name,
                        'Location': pages_str,
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
            with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
                df_summary.to_excel(writer, sheet_name='Summary', index=False)
                if not df_pdf_summary.empty:
                    df_pdf_summary.to_excel(writer, sheet_name='PDF Summary', index=False)
                if not df_found.empty:
                    df_found.to_excel(writer, sheet_name='Found Values', index=False)
                if not df_not_found.empty:
                    df_not_found.to_excel(writer, sheet_name='Not Found', index=False)
                
                # Apply styling
                workbook = writer.book
                header_fill = PatternFill(start_color="667EEA", end_color="667EEA", fill_type="solid")
                header_font = Font(bold=True, color="FFFFFF")
                found_fill = PatternFill(start_color="D4EDDA", end_color="D4EDDA", fill_type="solid")
                not_found_fill = PatternFill(start_color="F8D7DA", end_color="F8D7DA", fill_type="solid")
                
                for sheet_name in workbook.sheetnames:
                    ws = workbook[sheet_name]
                    
                    # Auto-adjust column widths
                    for column in ws.columns:
                        max_length = 0
                        column_letter = get_column_letter(column[0].column)
                        for cell in column:
                            try:
                                if len(str(cell.value)) > max_length:
                                    max_length = len(str(cell.value))
                            except:
                                pass
                        ws.column_dimensions[column_letter].width = min(max_length + 2, 50)
                    
                    # Style header
                    for cell in ws[1]:
                        cell.fill = header_fill
                        cell.font = header_font
                        cell.alignment = Alignment(horizontal='center')
                    
                    # Style data rows
                    if sheet_name == 'Found Values':
                        for row in ws.iter_rows(min_row=2):
                            for cell in row:
                                cell.fill = found_fill
                    elif sheet_name == 'Not Found':
                        for row in ws.iter_rows(min_row=2):
                            for cell in row:
                                cell.fill = not_found_fill
            
            self._log(f"   ✓ Report saved: {Path(output_file).name}")
            return output_file
            
        except Exception as e:
            self._log(f"   ✗ Error exporting to Excel: {e}")
            import traceback
            traceback.print_exc()
            raise


# ==================== DJANGO INTEGRATION HELPERS ====================

# Background job storage
_report_jobs = {}


def create_report_job(
    source_path: str,
    source_filename: str,
    column_name: str,
    pdf_paths: List[str],
    pdf_filenames: List[str],
    use_ocr: bool = False
) -> str:
    """Create a background report job."""
    import threading
    import uuid
    
    job_id = str(uuid.uuid4())
    
    _report_jobs[job_id] = {
        'status': 'pending',
        'progress': 0,
        'progress_message': 'Starting...',
        'result': None,
        'error': None,
        'source_file': source_filename,
        'column_name': column_name,
        'pdf_count': len(pdf_paths),
        'logs': []
    }
    
    def add_log(message: str):
        """Add log message to job."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        _report_jobs[job_id]['logs'].append(log_entry)
        print(log_entry)  # Also print to console
    
    def update_progress(progress: int, message: str = ""):
        """Update job progress."""
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
            
            # Generate Excel report
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            reports_dir = os.path.join(os.path.dirname(__file__), '..', 'reports')
            os.makedirs(reports_dir, exist_ok=True)
            output_file = os.path.join(reports_dir, f'Report_{timestamp}.xlsx')
            
            comparator.export_to_excel(result, output_file)
            result['excel_report'] = output_file
            result['excel_filename'] = f'Report_{timestamp}.xlsx'
            
            _report_jobs[job_id]['status'] = 'completed'
            update_progress(100, 'Complete!')
            _report_jobs[job_id]['result'] = result
            
            add_log("✓ Job completed successfully!")
            
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
    """Get status of a report job."""
    return _report_jobs.get(job_id, None)


def get_file_columns(file_path: str) -> List[str]:
    """Quick helper to get columns from a file."""
    comparator = AdvancedComparator(use_ocr=False)
    return comparator.get_columns(file_path)
