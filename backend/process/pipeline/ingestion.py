"""
Document ingestion pipeline.

PDF flow (preferred):
  OpenDataLoader → extract text blocks + tables → chunk → embed → store

PDF flow (fallback when ODL unavailable):
  PyMuPDF → extract text + tables → chunk → embed → store

Excel / Word / Image: dedicated extractors → same shared embed+store step.
"""

import glob
import json
import os
import re
import tempfile
import time

import fitz  # PyMuPDF
import openpyxl
from docx import Document as DocxDocument
from PIL import Image

from .config import CHROMA_BATCH_SIZE
from .embedding import model_manager
from .storage import get_collection
from .tables import store_table

# ── OpenDataLoader availability ───────────────────────────────────────────────
try:
    import opendataloader_pdf
    _ODL_AVAILABLE = True
except ImportError:
    opendataloader_pdf = None
    _ODL_AVAILABLE = False

# JVM memory for OpenDataLoader Java process
_ODL_JAVA_OPTS = os.getenv("ODL_JAVA_OPTS", "-Xms512m -Xmx6g -XX:+UseG1GC")
_ODL_BATCH_SIZE = int(os.getenv("ODL_PAGE_BATCH_SIZE", "120"))


# ── Ingestion progress helper ─────────────────────────────────────────────────

def _progress(doc_id, pct: int, detail: str = "", status: str = "processing"):
    """Write progress to the Document row. Fire-and-forget — never raises."""
    try:
        from process.models import Document
        Document.objects.filter(id=doc_id).update(
            status=status,
            progress=min(max(pct, 0), 100),
            progress_detail=detail[:255],
        )
    except Exception:
        pass


# ── Noise filtering ───────────────────────────────────────────────────────────

_NOISE_RE = [
    re.compile(r"^page\s+\d+(\s*(of|/)\s*\d+)?$", re.I),   # "Page 1 of 45"
    re.compile(r"^-\s*\d+\s*-$"),                            # "- 12 -"
    re.compile(r"^\d{1,4}$"),                                 # bare page number
    re.compile(r"^[-–—_=.*•·\s]{3,}$"),                      # separator lines
    re.compile(r"^(confidential|restricted|draft|unclassified|proprietary|for official use only)\b", re.I),
]


def _is_noise_line(line: str) -> bool:
    line = line.strip()
    if len(line) < 3:
        return True
    if len(line) <= 20 and not any(c.isalpha() for c in line):
        return True
    return any(p.match(line) for p in _NOISE_RE)


def _clean_text(text: str) -> str:
    """Remove noise lines (page numbers, separators, watermarks) from extracted text."""
    lines = text.split("\n")
    clean = [l for l in lines if not _is_noise_line(l)]
    return "\n".join(clean)


# ── Text chunking ─────────────────────────────────────────────────────────────

def smart_chunk_text(text, max_words=200, overlap=40):
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + max_words
        chunk = " ".join(words[start:end])
        if len(chunk.strip()) > 50:
            chunks.append(chunk)
        start = end - overlap
    return chunks


# ── Shared embed + batch-store ────────────────────────────────────────────────

def _embed_and_store(chunks, metas, ids, collection):
    if not chunks:
        return 0
    embeddings = model_manager.encode(chunks).tolist()
    for i in range(0, len(chunks), CHROMA_BATCH_SIZE):
        end = min(i + CHROMA_BATCH_SIZE, len(chunks))
        collection.add(
            documents=chunks[i:end],
            embeddings=embeddings[i:end],
            metadatas=metas[i:end],
            ids=ids[i:end],
        )
    # Mirror chunks into BM25 index for hybrid search
    from .bm25 import bm25_index
    bm25_index.add_batch(list(zip(ids, chunks, metas)))
    return len(chunks)


def _meta(doc_id, thread_id, parent_id, filename, page, chunk_type="text", **extra):
    m = {
        "doc_id": str(doc_id),
        "thread_id": str(thread_id),
        "parent_id": str(parent_id) if parent_id else "none",
        "source": filename,
        "page": page,
        "type": chunk_type,
    }
    m.update(extra)
    return m


# ── Table quality gate ────────────────────────────────────────────────────────

def _is_quality_table(headers, data_rows):
    """
    Return True only if the table has enough content to be useful.
    Rejects: single-row tables, mostly-empty tables, single-column tables.
    """
    if not data_rows or len(data_rows) < 1:
        return False
    max_cols = max((len(r) for r in data_rows), default=0)
    if max_cols < 2:
        return False
    total = sum(len(r) for r in data_rows)
    if total == 0:
        return False
    non_empty = sum(
        1 for r in data_rows for c in r
        if c is not None and str(c).strip() not in ("", "None", "-", "N/A", "n/a")
    )
    return (non_empty / total) >= 0.25  # at least 25% cells filled


# ── OpenDataLoader helpers ────────────────────────────────────────────────────

def _as_table_matrix(table_payload):
    """Normalise ODL table payload into list[list[str]]."""
    if isinstance(table_payload, list):
        if table_payload and isinstance(table_payload[0], (list, tuple)):
            return [[str(c) if c is not None else "" for c in row] for row in table_payload]
        return []
    if isinstance(table_payload, dict):
        rows = table_payload.get("rows")
        headers = table_payload.get("headers")
        if isinstance(rows, list) and rows and isinstance(rows[0], (list, tuple)):
            matrix = [[str(c) if c is not None else "" for c in row] for row in rows]
            if isinstance(headers, list) and headers:
                header_row = [str(h) if h is not None else "" for h in headers]
                return [header_row] + matrix
            return matrix
    return []


def _collect_odl_dir(output_dir):
    """Read ODL output from a temp directory; returns (text_blocks, tables)."""
    text_blocks, tables = [], []

    for json_file in glob.glob(os.path.join(output_dir, "**", "*.json"), recursive=True):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue

        elements = []
        if isinstance(payload, list):
            elements = payload
        elif isinstance(payload, dict):
            for key in ("elements", "data", "content", "blocks", "items"):
                if isinstance(payload.get(key), list):
                    elements = payload[key]
                    break

        for el in elements:
            if not isinstance(el, dict):
                continue
            el_type = str(el.get("type", "")).lower().strip()
            page = 1
            try:
                page = int(el.get("page") or el.get("page_number") or el.get("page number") or 1)
            except Exception:
                pass

            content = el.get("content")
            if isinstance(content, str) and content.strip():
                text_blocks.append({"page": page, "text": content.strip(), "type": el_type or "text"})
            if el_type in ("heading", "title", "h1", "h2", "h3", "section"):
                if isinstance(content, str) and content.strip():
                    text_blocks.append({"page": page, "text": content.strip(), "type": "heading"})
            if el_type == "table":
                matrix = _as_table_matrix(content)
                if matrix:
                    tables.append({"page": page, "matrix": matrix})

    # Fallback to markdown if JSON had no text
    if not text_blocks:
        for md_file in glob.glob(os.path.join(output_dir, "**", "*.md"), recursive=True):
            try:
                with open(md_file, "r", encoding="utf-8") as f:
                    md_text = f.read().strip()
                if md_text:
                    text_blocks.append({"page": 1, "text": md_text, "type": "markdown"})
            except Exception:
                continue

    return text_blocks, tables


def _run_opendataloader(file_path):
    """Run ODL over all pages in batches; returns (text_blocks, tables)."""
    if not os.getenv("JAVA_TOOL_OPTIONS"):
        os.environ["JAVA_TOOL_OPTIONS"] = _ODL_JAVA_OPTS

    with fitz.open(file_path) as doc:
        total_pages = len(doc)

    page_ranges = [
        (s, min(s + _ODL_BATCH_SIZE - 1, total_pages))
        for s in range(1, total_pages + 1, _ODL_BATCH_SIZE)
    ]
    print(f"[INGEST] ODL batches: {len(page_ranges)} for {total_pages} pages")

    all_text, all_tables = [], []
    for start, end in page_ranges:
        with tempfile.TemporaryDirectory(prefix="odl_") as tmp:
            opendataloader_pdf.convert(
                input_path=[file_path],
                output_dir=tmp,
                format="markdown,json",
                pages=f"{start}-{end}",
                quiet=True,
                table_method="cluster",
                reading_order="xycut",
            )
            batch_text, batch_tables = _collect_odl_dir(tmp)

        # Shift batch-relative page numbers to absolute
        batch_span = end - start + 1
        observed_max = max(
            [b.get("page", 1) for b in batch_text] + [t.get("page", 1) for t in batch_tables],
            default=0,
        )
        if start > 1 and observed_max <= batch_span:
            offset = start - 1
            for item in batch_text:
                item["page"] = int(item.get("page", 1)) + offset
            for item in batch_tables:
                item["page"] = int(item.get("page", 1)) + offset

        all_text.extend(batch_text)
        all_tables.extend(batch_tables)

    return all_text, all_tables


# ── Heading extraction (PyMuPDF) ─────────────────────────────────────────────

_HEADING_RE = re.compile(r"^\d+[\.\d]*\s+\w")  # "3.2 Section Name"


def _extract_headings_pymupdf(page):
    """
    Return [(text, y), ...] for likely headings on a PyMuPDF page.
    Headings are detected by font size (≥ 1.2× median) or bold weight
    or a numbered-section pattern like "3.2 Title".
    """
    try:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
    except Exception:
        return []

    spans = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                size = span.get("size", 0)
                if text and size > 0:
                    spans.append({
                        "text": text,
                        "size": size,
                        "bold": "bold" in span.get("font", "").lower(),
                        "y":    span.get("origin", (0, 0))[1],
                    })

    if not spans:
        return []

    sizes = sorted(s["size"] for s in spans)
    median = sizes[len(sizes) // 2]
    threshold = median * 1.2

    headings = []
    for s in spans:
        if (
            s["size"] >= threshold
            or s["bold"]
            or _HEADING_RE.match(s["text"])
        ) and len(s["text"]) > 3:
            headings.append((s["text"], s["y"]))
    return headings


def _nearest_heading(table_y, headings):
    """Return the text of the closest heading above the given y-coordinate."""
    above = [(txt, y) for txt, y in headings if y < table_y]
    if not above:
        return ""
    return max(above, key=lambda h: h[1])[0]


# ── PyMuPDF table helpers (fallback) ─────────────────────────────────────────

def _extract_page_tables(page):
    tables = []
    try:
        for idx, tab in enumerate(page.find_tables()):
            data = tab.extract()
            if not data or len(data) < 2:
                continue
            headers = data[0] or []
            rows = data[1:]
            if not _is_quality_table(headers, rows):
                continue
            preview = (
                f"Table {idx+1}:\nColumns: "
                + " | ".join(str(h) for h in headers if h)
                + "\n"
            )
            for row in rows[:10]:
                preview += " | ".join(str(c) for c in row if c) + "\n"
            tables.append({
                "index": idx,
                "text": preview.strip(),
                "data": data,
                "headers": headers,
                "row_count": len(rows),
                "column_count": len(headers),
                "y": tab.bbox[1] if hasattr(tab, "bbox") and tab.bbox else 0,
            })
    except Exception as e:
        print(f"[INGEST] PyMuPDF table error: {e}")
    return tables


def _is_table_continuation(prev, curr):
    if abs(prev["column_count"] - curr["column_count"]) > 1:
        return False
    if not curr["headers"] or all(not str(h).strip() for h in curr["headers"]):
        return True
    hs = " ".join(str(h) for h in curr["headers"] if h)
    if len(hs) < 10:
        return True
    if prev["headers"]:
        ps = " ".join(str(h) for h in prev["headers"] if h).lower()
        sim = sum(1 for w in hs.lower().split() if w in ps) / max(len(hs.lower().split()), 1)
        if sim < 0.3:
            return True
    return False


def _flush_table(pending, doc_id, thread_id, parent_id, filename):
    table_id = f"{doc_id}_{pending['page_num']}_table_{pending['index']}"
    store_table(
        table_id=table_id,
        doc_id=doc_id,
        thread_id=thread_id,
        parent_id=parent_id,
        source=filename,
        page=pending["start_page"],
        table_index=pending["index"],
        headers=pending["headers"],
        row_count=pending["row_count"],
        column_count=pending["column_count"],
        table_data=pending["data"],
        caption=pending.get("caption", ""),
    )


# ── PDF ingestion ─────────────────────────────────────────────────────────────

def _ingest_pdf_odl(file_path, doc_id, thread_id, parent_id, filename):
    """Primary PDF path: OpenDataLoader for text + tables."""
    collection = get_collection()
    chunks, metas, ids = [], [], []
    table_count = 0

    _progress(doc_id, 5, "Running OpenDataLoader…")
    text_blocks, odl_tables = _run_opendataloader(file_path)
    _progress(doc_id, 50, f"Extracted {len(text_blocks)} text blocks, {len(odl_tables)} tables")

    # Build page → [heading text] lookup from ODL heading elements
    page_headings: dict[int, list[str]] = {}
    for block in text_blocks:
        if block.get("type") == "heading":
            page_headings.setdefault(block["page"], []).append(block["text"])

    def _odl_caption(page_num):
        """Return the last heading on this page, or the closest earlier page."""
        for p in range(page_num, 0, -1):
            if page_headings.get(p):
                return page_headings[p][-1]
        return ""

    # Group text blocks by page and chunk
    page_text: dict = {}
    for block in text_blocks:
        if block.get("type") != "heading":
            page_text.setdefault(block["page"], []).append(block["text"])

    for page in sorted(page_text.keys()):
        merged = _clean_text("\n".join(page_text[page])).strip()
        for i, chunk in enumerate(smart_chunk_text(merged)):
            chunks.append(chunk)
            ids.append(f"{doc_id}_{page-1}_{i}")
            metas.append(_meta(doc_id, thread_id, parent_id, filename, page))

    # Store ODL tables with caption
    for idx, table in enumerate(odl_tables):
        matrix = table.get("matrix", [])
        if len(matrix) < 2:
            continue
        headers = matrix[0]
        rows = matrix[1:]
        if not _is_quality_table(headers, rows):
            continue
        page = table.get("page", 1)
        store_table(
            table_id=f"{doc_id}_{page-1}_table_odl_{idx}",
            doc_id=doc_id,
            thread_id=thread_id,
            parent_id=parent_id,
            source=filename,
            page=page,
            table_index=idx,
            headers=headers,
            row_count=len(rows),
            column_count=len(headers) if headers else (len(rows[0]) if rows else 0),
            table_data=matrix,
            caption=_odl_caption(page),
        )
        table_count += 1

    _progress(doc_id, 75, f"Embedding {len(chunks)} chunks…")
    n = _embed_and_store(chunks, metas, ids, collection)
    _progress(doc_id, 100, f"Done — {n} chunks, {table_count} tables", status="done")
    print(f"[INGEST] ODL done: {n} chunks + {table_count} tables")
    return {"text_chunks": n, "table_chunks": table_count}


def _ingest_pdf_pymupdf(file_path, doc_id, thread_id, parent_id, filename):
    """Fallback PDF path: PyMuPDF with multi-page table merging."""
    collection = get_collection()
    chunks, metas, ids = [], [], []
    table_count = 0
    pending_table = None

    doc = fitz.open(file_path)
    total = len(doc)
    print(f"[INGEST] PyMuPDF: {filename} ({total} pages)")
    _progress(doc_id, 2, f"Parsing {total} pages…")

    _REPORT_EVERY = max(1, total // 20)  # ~5% steps

    for page_num, page in enumerate(doc):
        for i, chunk in enumerate(smart_chunk_text(_clean_text(page.get_text()))):
            chunks.append(chunk)
            ids.append(f"{doc_id}_{page_num}_{i}")
            metas.append(_meta(doc_id, thread_id, parent_id, filename, page_num + 1))

        headings = _extract_headings_pymupdf(page)
        for table in _extract_page_tables(page):
            caption = _nearest_heading(table.get("y", 0), headings)
            if pending_table and table["index"] == 0 and _is_table_continuation(pending_table, table):
                pending_table["data"].extend(table["data"])
                pending_table["row_count"] += table["row_count"]
                if caption and not pending_table.get("caption"):
                    pending_table["caption"] = caption
                continue
            if pending_table:
                _flush_table(pending_table, doc_id, thread_id, parent_id, filename)
                table_count += 1
            pending_table = {**table, "start_page": page_num + 1, "page_num": page_num, "caption": caption}

        if (page_num + 1) % _REPORT_EVERY == 0 or (page_num + 1) == total:
            pct = int((page_num + 1) / total * 70)  # pages → 0-70%
            _progress(doc_id, pct, f"Page {page_num+1}/{total} — {len(chunks)} chunks, {table_count} tables")
            print(f"[INGEST] {page_num+1}/{total} pages | {len(chunks)} chunks | {table_count} tables")

    if pending_table:
        _flush_table(pending_table, doc_id, thread_id, parent_id, filename)
        table_count += 1

    doc.close()
    _progress(doc_id, 75, f"Embedding {len(chunks)} chunks…")
    n = _embed_and_store(chunks, metas, ids, collection)
    _progress(doc_id, 100, f"Done — {n} chunks, {table_count} tables", status="done")
    print(f"[INGEST] PyMuPDF done: {n} chunks + {table_count} tables")
    return {"text_chunks": n, "table_chunks": table_count}


def _ingest_pdfplumber_tables(file_path, doc_id, thread_id, parent_id, filename):
    """
    Supplementary pass: persist tables via pdfplumber — both line-based GRID tables
    and the numbered "1 2 … N" reference-row ANCHOR extractor for line-less spares
    lists (MRLS/ISPL etc.). Covers the tabular forms that ODL/PyMuPDF miss, so the
    tables land in the structured DB and the fast comparison path works.

    Values dedupe by value at compare time, so any overlap with tables the primary
    ODL/PyMuPDF path already stored is harmless.
    """
    import pdfplumber
    from process.table_search_engine import TableSearchEngine

    engine = TableSearchEngine()
    count = 0
    # Header printed on the page a table starts, carried to the pages it
    # continues onto — otherwise those pages persist a data row as their header.
    header_memo = {}
    try:
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                matrices = []  # list of [headers, *rows]

                # 1. Line-based grid tables
                try:
                    for t in (page.extract_tables() or []):
                        if not t or len(t) < 2:
                            continue
                        ct = engine._clean_table_structure(t)
                        if ct and len(ct) >= 2:
                            matrices.append(engine._with_carried_header(ct, header_memo))
                except Exception:
                    pass

                # 2. Line-less anchor tables
                try:
                    for df in engine._extract_anchor_tables(page, page_num, header_memo):
                        if df.empty:
                            continue
                        cols = [c for c in df.columns if not str(c).startswith('_')]
                        matrices.append(
                            [[str(c) for c in cols]] + df[cols].astype(str).values.tolist())
                except Exception:
                    pass

                for idx, matrix in enumerate(matrices):
                    headers = [str(h) for h in matrix[0]]
                    rows = matrix[1:]
                    if not _is_quality_table(headers, rows):
                        continue
                    store_table(
                        table_id=f"{doc_id}_{page_num-1}_table_pp_{idx}",
                        doc_id=doc_id,
                        thread_id=thread_id,
                        parent_id=parent_id,
                        source=filename,
                        page=page_num,
                        table_index=1000 + idx,
                        headers=headers,
                        row_count=len(rows),
                        column_count=len(headers),
                        table_data=matrix,
                        caption="",
                    )
                    count += 1
    except Exception as e:
        print(f"[INGEST] pdfplumber table pass error: {e}")
    if count:
        print(f"[INGEST] pdfplumber pass stored {count} table(s)")
    return count


def _ingest_pdf(file_path, doc_id, thread_id, parent_id, filename):
    """
    Try OpenDataLoader first (best table accuracy).
    Falls back to PyMuPDF if ODL is not installed or fails.
    Then a supplementary anchor pass captures line-less tables both miss.
    """
    model_manager.load_model()
    if not model_manager.is_ready():
        raise RuntimeError("Embedding model not loaded.")

    result = None
    if _ODL_AVAILABLE:
        try:
            print(f"[INGEST] Using OpenDataLoader for: {filename}")
            result = _ingest_pdf_odl(file_path, doc_id, thread_id, parent_id, filename)
        except Exception as e:
            print(f"[INGEST] ODL failed ({e}), falling back to PyMuPDF")

    if result is None:
        result = _ingest_pdf_pymupdf(file_path, doc_id, thread_id, parent_id, filename)

    pp_n = _ingest_pdfplumber_tables(file_path, doc_id, thread_id, parent_id, filename)
    if pp_n:
        result["table_chunks"] = result.get("table_chunks", 0) + pp_n
    return result


# ── Excel ingestion ───────────────────────────────────────────────────────────

def _ingest_excel(file_path, doc_id, thread_id, parent_id, filename):
    model_manager.load_model()
    if not model_manager.is_ready():
        raise RuntimeError("Embedding model not loaded.")

    collection = get_collection()
    chunks, metas, ids = [], [], []
    table_count = 0

    wb = openpyxl.load_workbook(file_path, data_only=True)
    total_sheets = len(wb.sheetnames)
    _progress(doc_id, 5, f"Reading {total_sheets} sheet(s)…")
    for sheet_idx, sheet_name in enumerate(wb.sheetnames):
        sheet = wb[sheet_name]
        rows_data, text_rows, headers = [], [], None

        for row_idx, row in enumerate(sheet.iter_rows(values_only=True)):
            if not any(c is not None for c in row):
                continue
            vals = [str(c) if c is not None else "" for c in row]
            rows_data.append(vals)
            if row_idx == 0:
                headers = vals
            text_rows.append(" | ".join(str(c) for c in row if c is not None))

        if len(rows_data) > 1 and headers and _is_quality_table(headers, rows_data[1:]):
            store_table(
                table_id=f"{doc_id}_sheet_{sheet_idx}_table_0",
                doc_id=doc_id, thread_id=thread_id, parent_id=parent_id,
                source=filename, page=sheet_idx + 1, table_index=0,
                headers=headers, row_count=len(rows_data) - 1,
                column_count=len(headers), table_data=rows_data,
                caption=sheet_name,
            )
            table_count += 1

        for i, chunk in enumerate(smart_chunk_text(f"Sheet: {sheet_name}\n" + "\n".join(text_rows))):
            chunks.append(chunk)
            ids.append(f"{doc_id}_sheet_{sheet_idx}_{i}")
            metas.append(_meta(doc_id, thread_id, parent_id, filename, sheet_idx + 1,
                                chunk_type="excel_text", sheet_name=sheet_name))
        pct = int((sheet_idx + 1) / total_sheets * 70)
        _progress(doc_id, pct, f"Sheet {sheet_idx+1}/{total_sheets}: {sheet_name}")
    wb.close()

    _progress(doc_id, 80, f"Embedding {len(chunks)} chunks…")
    n = _embed_and_store(chunks, metas, ids, collection)
    _progress(doc_id, 100, f"Done — {n} chunks, {table_count} tables", status="done")
    print(f"[INGEST] Excel done: {n} chunks + {table_count} tables")
    return {"text_chunks": n, "table_chunks": table_count}


# ── Word ingestion ────────────────────────────────────────────────────────────

def _ingest_word(file_path, doc_id, thread_id, parent_id, filename):
    model_manager.load_model()
    if not model_manager.is_ready():
        raise RuntimeError("Embedding model not loaded.")

    collection = get_collection()
    chunks, metas, ids = [], [], []
    table_count = 0

    _progress(doc_id, 5, "Reading Word document…")
    doc = DocxDocument(file_path)
    para_text = "\n\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
    for i, chunk in enumerate(smart_chunk_text(para_text)):
        chunks.append(chunk)
        ids.append(f"{doc_id}_para_{i}")
        metas.append(_meta(doc_id, thread_id, parent_id, filename, 1, chunk_type="word_text"))

    # Build a lookup: table object → preceding paragraph text (as caption)
    from docx.oxml.ns import qn as _qn
    def _preceding_para(tbl_element, all_paras):
        """Return the text of the paragraph immediately before this table element."""
        siblings = list(tbl_element.getparent())
        idx = siblings.index(tbl_element)
        for i in range(idx - 1, -1, -1):
            sib = siblings[i]
            if sib.tag.endswith("}p"):
                text = "".join(t.text or "" for t in sib.iter() if t.tag.endswith("}t")).strip()
                if text:
                    return text
        return ""

    for table_idx, table in enumerate(doc.tables):
        rows_data = [[c.text.strip() for c in row.cells] for row in table.rows]
        if not rows_data:
            continue
        headers = rows_data[0]
        if not _is_quality_table(headers, rows_data[1:]):
            continue
        caption = _preceding_para(table._tbl, doc.paragraphs)
        store_table(
            table_id=f"{doc_id}_table_{table_idx}",
            doc_id=doc_id, thread_id=thread_id, parent_id=parent_id,
            source=filename, page=1, table_index=table_idx,
            headers=headers, row_count=max(0, len(rows_data) - 1),
            column_count=len(headers), table_data=rows_data,
            caption=caption,
        )
        table_count += 1
        tbl_preview = (
            f"Table {table_idx+1}:\nHeaders: {', '.join(str(h) for h in headers if h)}\n"
            + "\n".join(" | ".join(str(c) for c in r if c) for r in rows_data[1:6])
        )
        chunks.append(tbl_preview)
        ids.append(f"{doc_id}_table_{table_idx}_text")
        metas.append(_meta(doc_id, thread_id, parent_id, filename, 1,
                            chunk_type="word_table",
                            table_id=f"{doc_id}_table_{table_idx}"))

    _progress(doc_id, 80, f"Embedding {len(chunks)} chunks…")
    n = _embed_and_store(chunks, metas, ids, collection)
    _progress(doc_id, 100, f"Done — {n} chunks, {table_count} tables", status="done")
    print(f"[INGEST] Word done: {n} chunks + {table_count} tables")
    return {"text_chunks": n, "table_chunks": table_count}


# ── Image ingestion ───────────────────────────────────────────────────────────

def _ingest_image(file_path, doc_id, thread_id, parent_id, filename):
    model_manager.load_model()
    if not model_manager.is_ready():
        raise RuntimeError("Embedding model not loaded.")

    collection = get_collection()
    try:
        img = Image.open(file_path)
        w, h = img.size
        fmt = img.format or "Unknown"
        mode = img.mode
        img.close()
        text = (
            f"Image: {filename}\nFormat: {fmt}\nDimensions: {w}x{h}\n"
            f"Color Mode: {mode}\nFile Type: Image Document"
        )
    except Exception:
        text = f"Image: {filename}\nFile Type: Image Document"

    n = _embed_and_store(
        [text],
        [_meta(doc_id, thread_id, parent_id, filename, 1, chunk_type="image_metadata")],
        [f"{doc_id}_img_metadata"],
        collection,
    )
    print(f"[INGEST] Image done: {n} metadata chunk")
    return {"text_chunks": n, "table_chunks": 0}


# ── Public API ────────────────────────────────────────────────────────────────

_DISPATCH = {
    ".pdf":  _ingest_pdf,
    ".xlsx": _ingest_excel,
    ".xls":  _ingest_excel,
    ".docx": _ingest_word,
    ".jpg":  _ingest_image,
    ".jpeg": _ingest_image,
    ".png":  _ingest_image,
    ".bmp":  _ingest_image,
    ".tiff": _ingest_image,
    ".tif":  _ingest_image,
}


def process_document(file_path, doc_id, thread_id, parent_id, filename):
    ext = os.path.splitext(filename)[1].lower()
    fn = _DISPATCH.get(ext)
    if fn is None:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {', '.join(_DISPATCH.keys())}")
    return fn(file_path, doc_id, thread_id, parent_id, filename)


# Backward-compat aliases
def process_pdf(file_path, doc_id, thread_id, parent_id, filename):
    return _ingest_pdf(file_path, doc_id, thread_id, parent_id, filename)

def process_excel(file_path, doc_id, thread_id, parent_id, filename):
    return _ingest_excel(file_path, doc_id, thread_id, parent_id, filename)

def process_word(file_path, doc_id, thread_id, parent_id, filename):
    return _ingest_word(file_path, doc_id, thread_id, parent_id, filename)

def process_image(file_path, doc_id, thread_id, parent_id, filename):
    return _ingest_image(file_path, doc_id, thread_id, parent_id, filename)


def extract_pdf_title(file_path):
    try:
        doc = fitz.open(file_path)
        meta = doc.metadata
        if meta and meta.get("title") and len(meta["title"].strip()) > 5:
            doc.close()
            return meta["title"].strip()[:100]
        if len(doc) > 0:
            lines = [l.strip() for l in doc[0].get_text().split("\n") if l.strip()]
            for line in lines[:5]:
                if 5 < len(line) < 100:
                    doc.close()
                    return line[:100]
        doc.close()
    except Exception:
        pass
    return os.path.splitext(os.path.basename(file_path))[0]
