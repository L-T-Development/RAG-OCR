import fitz  # PyMuPDF
import difflib
from docx import Document
from openpyxl import load_workbook


# ---------------- COMMON HELPERS ----------------

def normalize_lines(text: str):
    """
    Simple normalization.
    Intentionally weak rules as suggested.
    """
    lines = text.splitlines()
    return [line.strip().lower() for line in lines if line.strip()]


def diff_lines(old_lines, new_lines):
    """
    Core deterministic diff using SequenceMatcher.
    Correctly pairs modified (replaced) lines for clear reporting.
    """
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)

    added = []
    removed = []
    modified = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue

        elif tag == 'insert':
            # Lines present in new but not old
            added.extend(new_lines[j1:j2])

        elif tag == 'delete':
            # Lines present in old but not new
            removed.extend(old_lines[i1:i2])

        elif tag == 'replace':
            # Modified lines
            old_part = old_lines[i1:i2]
            new_part = new_lines[j1:j2]

            for k in range(max(len(old_part), len(new_part))):
                old_val = old_part[k] if k < len(old_part) else None
                new_val = new_part[k] if k < len(new_part) else None

                if old_val and new_val:
                    modified.append(
                        f"OLD: '{old_val}' -> NEW: '{new_val}'"
                    )
                elif old_val:
                    removed.append(
                        f"REPLACED/DELETED: '{old_val}'"
                    )
                elif new_val:
                    added.append(
                        f"REPLACED/ADDED: '{new_val}'"
                    )

    return {
        "added": added,
        "removed": removed,
        "modified": modified
    }


# ---------------- PDF ----------------

def extract_pdf(path):
    print(f"[PDF] Extracting text from: {path}")
    doc = fitz.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    lines = normalize_lines(text)
    print(f"[PDF] Extracted {len(lines)} normalized lines")
    return lines


def compare_pdfs(old_pdf, new_pdf):
    return diff_lines(
        extract_pdf(old_pdf),
        extract_pdf(new_pdf)
    )


# ---------------- DOCX ----------------

def extract_docx(path):
    print(f"[DOCX] Extracting text from: {path}")
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)
    lines = normalize_lines(text)
    print(f"[DOCX] Extracted {len(lines)} normalized lines")
    return lines


def compare_docx(old_docx, new_docx):
    return diff_lines(
        extract_docx(old_docx),
        extract_docx(new_docx)
    )


# ---------------- EXCEL ----------------

def compare_excels(old_xlsx, new_xlsx):
    wb_old = load_workbook(old_xlsx)
    wb_new = load_workbook(new_xlsx)

    added = []
    removed = []
    modified = []

    for sheet in wb_old.sheetnames:
        if sheet not in wb_new.sheetnames:
            continue

        ws_old = wb_old[sheet]
        ws_new = wb_new[sheet]

        max_row = max(ws_old.max_row, ws_new.max_row)
        max_col = max(ws_old.max_column, ws_new.max_column)

        for r in range(1, max_row + 1):
            for c in range(1, max_col + 1):
                old_val = ws_old.cell(row=r, column=c).value
                new_val = ws_new.cell(row=r, column=c).value

                if old_val == new_val:
                    continue

                cell_ref = f"{sheet} ({r},{c})"

                if old_val is None and new_val is not None:
                    added.append(f"{cell_ref}: {new_val}")
                elif old_val is not None and new_val is None:
                    removed.append(f"{cell_ref}: {old_val}")
                else:
                    modified.append(
                        f"{cell_ref}: {old_val} -> {new_val}"
                    )

    return {
        "added": added,
        "removed": removed,
        "modified": modified
    }
