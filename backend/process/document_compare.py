import fitz  # PyMuPDF
import difflib
from docx import Document
from openpyxl import load_workbook


# ---------------- COMMON HELPERS ----------------

def extract_lines(text: str):
    """
    Extract lines preserving original content (not normalized).
    Returns list of lines with whitespace stripped.
    """
    lines = text.splitlines()
    return [line.strip() for line in lines if line.strip()]


def unified_line_diff(old_lines, new_lines):
    """
    Generate unified line-by-line diff with status for each line.
    Returns list of dicts: {line_num, status, old_text, new_text}
    Status: 'equal', 'added', 'removed', 'modified'
    """
    diff_result = []
    
    # Use difflib to get unified diff
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    
    line_num = 1
    stats = {"added": 0, "removed": 0, "modified": 0, "equal": 0}
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Lines are the same
            for i in range(i1, i2):
                diff_result.append({
                    "line": line_num,
                    "status": "equal",
                    "text": old_lines[i],
                    "old_text": None,
                    "new_text": None
                })
                stats["equal"] += 1
                line_num += 1
                
        elif tag == 'insert':
            # Lines added in new file
            for j in range(j1, j2):
                diff_result.append({
                    "line": line_num,
                    "status": "added",
                    "text": new_lines[j],
                    "old_text": None,
                    "new_text": new_lines[j]
                })
                stats["added"] += 1
                line_num += 1
                
        elif tag == 'delete':
            # Lines removed from old file
            for i in range(i1, i2):
                diff_result.append({
                    "line": line_num,
                    "status": "removed",
                    "text": old_lines[i],
                    "old_text": old_lines[i],
                    "new_text": None
                })
                stats["removed"] += 1
                line_num += 1
                
        elif tag == 'replace':
            # Lines modified
            old_part = old_lines[i1:i2]
            new_part = new_lines[j1:j2]
            
            max_len = max(len(old_part), len(new_part))
            
            for k in range(max_len):
                old_val = old_part[k] if k < len(old_part) else None
                new_val = new_part[k] if k < len(new_part) else None
                
                if old_val and new_val:
                    diff_result.append({
                        "line": line_num,
                        "status": "modified",
                        "text": new_val,
                        "old_text": old_val,
                        "new_text": new_val
                    })
                    stats["modified"] += 1
                elif new_val:
                    diff_result.append({
                        "line": line_num,
                        "status": "added",
                        "text": new_val,
                        "old_text": None,
                        "new_text": new_val
                    })
                    stats["added"] += 1
                elif old_val:
                    diff_result.append({
                        "line": line_num,
                        "status": "removed",
                        "text": old_val,
                        "old_text": old_val,
                        "new_text": None
                    })
                    stats["removed"] += 1
                    
                line_num += 1
    
    return {
        "lines": diff_result,
        "stats": stats,
        "total_lines": len(diff_result)
    }


# ---------------- PDF ----------------

def extract_pdf(path):
    print(f"[PDF] Extracting text from: {path}")
    doc = fitz.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    lines = extract_lines(text)
    print(f"[PDF] Extracted {len(lines)} lines")
    return lines


def compare_pdfs(old_pdf, new_pdf):
    return unified_line_diff(
        extract_pdf(old_pdf),
        extract_pdf(new_pdf)
    )


# ---------------- DOCX ----------------

def extract_docx(path):
    print(f"[DOCX] Extracting text from: {path}")
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    lines = extract_lines(text)
    print(f"[DOCX] Extracted {len(lines)} lines")
    return lines


def compare_docx(old_docx, new_docx):
    return unified_line_diff(
        extract_docx(old_docx),
        extract_docx(new_docx)
    )


# ---------------- EXCEL ----------------

def extract_excel(path):
    """Extract Excel content as lines (row by row)"""
    print(f"[XLSX] Extracting content from: {path}")
    wb = load_workbook(path)
    lines = []
    
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        lines.append(f"[Sheet: {sheet_name}]")
        
        for row in ws.iter_rows(values_only=True):
            # Convert row to string, filtering None values
            row_str = " | ".join(str(cell) if cell is not None else "" for cell in row)
            if row_str.strip() and row_str.replace("|", "").replace(" ", ""):
                lines.append(row_str)
    
    print(f"[XLSX] Extracted {len(lines)} lines")
    return lines


def compare_excels(old_xlsx, new_xlsx):
    return unified_line_diff(
        extract_excel(old_xlsx),
        extract_excel(new_xlsx)
    )
