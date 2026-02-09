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
                        
                        # Convert to DataFrame with proper column handling
                        df = self._create_dataframe_from_table(cleaned_table, page_num)
                        
                        if not df.empty:
                            all_tables.append(df)
        
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
    
    def compare_tables(self, pdf1_name: str, pdf2_name: str, 
                      column_name: str,
                      comparison_type: str = 'difference') -> Dict[str, Any]:
        """
        Compare a specific column between two PDFs.
        
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
        
        # Find the column in both PDFs
        pdf1_values = set()
        pdf1_rows = []  # Store full row data
        
        for df in self.extracted_tables[pdf1_name]:
            matching_cols = [col for col in df.columns 
                           if not col.startswith('_') and column_name.lower() in col.lower()]
            
            for col in matching_cols:
                for _, row in df.iterrows():
                    val = str(row[col]).strip() if pd.notna(row[col]) else ''
                    if val and val.lower() not in ['nan', 'none', '']:
                        pdf1_values.add(val.upper())
                        # Store row data
                        row_dict = {c: str(row[c]) if pd.notna(row[c]) else '' 
                                  for c in df.columns if not c.startswith('_')}
                        row_dict['_matched_column'] = col
                        row_dict['_matched_value'] = val
                        row_dict['_source_pdf'] = pdf1_name
                        if '_source_page' in row:
                            row_dict['_page'] = int(row['_source_page'])
                        pdf1_rows.append(row_dict)
        
        pdf2_values = set()
        pdf2_rows = []
        
        for df in self.extracted_tables[pdf2_name]:
            matching_cols = [col for col in df.columns 
                           if not col.startswith('_') and column_name.lower() in col.lower()]
            
            for col in matching_cols:
                for _, row in df.iterrows():
                    val = str(row[col]).strip() if pd.notna(row[col]) else ''
                    if val and val.lower() not in ['nan', 'none', '']:
                        pdf2_values.add(val.upper())
                        row_dict = {c: str(row[c]) if pd.notna(row[c]) else '' 
                                  for c in df.columns if not c.startswith('_')}
                        row_dict['_matched_column'] = col
                        row_dict['_matched_value'] = val
                        row_dict['_source_pdf'] = pdf2_name
                        if '_source_page' in row:
                            row_dict['_page'] = int(row['_source_page'])
                        pdf2_rows.append(row_dict)
        
        # Perform comparisons
        in_pdf1_only = pdf1_values - pdf2_values
        in_pdf2_only = pdf2_values - pdf1_values
        common_values = pdf1_values & pdf2_values
        
        # Prepare results
        result = {
            'column': column_name,
            'pdf1': pdf1_name,
            'pdf2': pdf2_name,
            'pdf1_total': len(pdf1_values),
            'pdf2_total': len(pdf2_values),
            'comparison_type': comparison_type,
            'results': {}
        }
        
        if comparison_type in ['difference', 'all']:
            # Items in PDF1 but not in PDF2
            result['results']['in_pdf1_only'] = {
                'count': len(in_pdf1_only),
                'values': sorted(list(in_pdf1_only))[:100],  # Limit to 100
                'rows': [r for r in pdf1_rows if r['_matched_value'].upper() in in_pdf1_only][:50]
            }
        
        if comparison_type in ['common', 'all']:
            # Items in both PDFs
            result['results']['common'] = {
                'count': len(common_values),
                'values': sorted(list(common_values))[:100],
                'rows': [r for r in pdf1_rows if r['_matched_value'].upper() in common_values][:50]
            }
        
        if comparison_type in ['unique_both', 'all']:
            result['results']['in_pdf1_only'] = {
                'count': len(in_pdf1_only),
                'values': sorted(list(in_pdf1_only))[:100],
                'rows': [r for r in pdf1_rows if r['_matched_value'].upper() in in_pdf1_only][:50]
            }
            result['results']['in_pdf2_only'] = {
                'count': len(in_pdf2_only),
                'values': sorted(list(in_pdf2_only))[:100],
                'rows': [r for r in pdf2_rows if r['_matched_value'].upper() in in_pdf2_only][:50]
            }
        
        # Generate summary
        result['summary'] = self._generate_comparison_summary(result)
        result['found'] = True
        
        return result
    
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
                comparison_type: str = 'difference') -> Dict[str, Any]:
    """
    Compare a specific column between two PDFs.
    
    Args:
        pdf1_path: Path to first PDF (e.g., MRLS)
        pdf2_path: Path to second PDF (e.g., ISPL)
        column_name: Column to compare (e.g., 'Part Number', 'DRG')
        comparison_type: 'difference', 'common', 'unique_both', or 'all'
    
    Returns:
        Dictionary with comparison results
    """
    pdf1_name = Path(pdf1_path).name
    pdf2_name = Path(pdf2_path).name
    
    # Extract tables if not already done
    if pdf1_name not in _search_engine.extracted_tables:
        extract_and_index_pdf(pdf1_path)
    
    if pdf2_name not in _search_engine.extracted_tables:
        extract_and_index_pdf(pdf2_path)
    
    return _search_engine.compare_tables(pdf1_name, pdf2_name, column_name, comparison_type)
