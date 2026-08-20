"""
manage.py build_mention_index — populate the identifier mention index.

The index (process/mentions.py) is what lets a spares list be compared against a
*manual*: it records every identifier-shaped token in a document's prose and table
cells, with page numbers, so "is every part in the MRLS mentioned anywhere in this
manual?" is a database question rather than a re-parse of the PDF.

New uploads are indexed automatically during ingestion. Documents uploaded before
this existed need one pass of this command. Prose is re-read from the PDF with
PyMuPDF (no OCR, no embedding, Ollama not required); table cells come from the
already-persisted ExtractedTable rows, so xlsx/docx get their tables indexed even
though only PDFs can have their text re-read.

    manage.py build_mention_index                # documents with no index yet
    manage.py build_mention_index --all          # rebuild everything
    manage.py build_mention_index --source ISPL  # filename substring
    manage.py build_mention_index --thread <id> | --doc <id> | --dry-run
"""
import os
import re
import time

from django.core.management.base import BaseCommand

from process.models import Document, DocumentPageText, ExtractedTable


class Command(BaseCommand):
    help = "Build/refresh the identifier mention index used to compare tables against manuals."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Rebuild even if already indexed.")
        parser.add_argument("--doc", help="Only this document id.")
        parser.add_argument("--thread", help="Only documents in this thread id.")
        parser.add_argument("--source", help="Only documents whose filename contains this text.")
        parser.add_argument("--dry-run", action="store_true", help="List what would be done.")

    def handle(self, *args, **opts):
        from process.mentions import index_chunks, index_tables

        docs = Document.objects.all().order_by("uploaded_at")
        if opts["doc"]:
            docs = docs.filter(id=opts["doc"].replace("-", ""))
        if opts["thread"]:
            docs = docs.filter(thread_id=opts["thread"].replace("-", ""))
        if opts["source"]:
            docs = docs.filter(filename__icontains=opts["source"])

        todo = []
        for d in docs:
            key = str(d.id).replace("-", "")
            indexed = DocumentPageText.objects.filter(doc_id=key).exists()
            if indexed and not (opts["all"] or opts["doc"] or opts["source"]):
                self.stdout.write(f"  skip  {d.filename}  (already indexed; --all to rebuild)")
                continue
            todo.append((d, key))

        if not todo:
            self.stdout.write(self.style.WARNING("Nothing to do."))
            return
        self.stdout.write(f"{len(todo)} document(s) to index"
                          + (" (dry run)" if opts["dry_run"] else "") + ":")
        for d, _ in todo:
            self.stdout.write(f"  -     {d.filename}  [{d.category}]")
        if opts["dry_run"]:
            return

        t_all = time.time()
        total_text = total_tables = 0
        for d, key in todo:
            t0 = time.time()
            parent_id = str(d.thread.parent_id) if d.thread and d.thread.parent_id else None
            n_text = 0
            path = self._path(d)
            if path and d.filename.lower().endswith(".pdf"):
                try:
                    chunks, metas = self._pdf_pages(path, key, d, parent_id)
                    n_text = index_chunks(key, str(d.thread_id), parent_id, d.filename, chunks, metas)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  {d.filename}: text pass FAILED — {e}"))
            elif not path:
                self.stdout.write(f"  {d.filename}: no file on disk — tables only")

            try:
                n_tab = index_tables(key, str(d.thread_id), parent_id, d.filename)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  {d.filename}: table pass FAILED — {e}"))
                n_tab = 0

            total_text += n_text
            total_tables += n_tab
            has_tables = ExtractedTable.objects.filter(doc_id=key).exists()
            note = "" if (n_text or n_tab) else (
                "  ← nothing indexed (no text layer? scanned PDF?)" if not has_tables else "")
            self.stdout.write(self.style.SUCCESS(
                f"  {d.filename}: {n_text} from text + {n_tab} from tables "
                f"in {time.time() - t0:.1f}s{note}"))

        self.stdout.write(self.style.SUCCESS(
            f"Done: {total_text} text + {total_tables} table mention(s) across "
            f"{len(todo)} document(s) in {time.time() - t_all:.1f}s"))

    @staticmethod
    def _pdf_pages(path, key, doc, parent_id):
        """Page text straight from the PDF, shaped like ingestion's (chunks, metas)."""
        import fitz
        chunks, metas = [], []
        with fitz.open(path) as pdf:
            for i, page in enumerate(pdf, 1):
                text = page.get_text("text") or ""
                if not text.strip():
                    continue
                chunks.append(re.sub(r"[ \t]+", " ", text))
                metas.append({"doc_id": key, "thread_id": str(doc.thread_id),
                              "parent_id": parent_id or "none",
                              "source": doc.filename, "page": i, "type": "text"})
        return chunks, metas

    @staticmethod
    def _path(doc):
        try:
            p = doc.file.path
            return p if p and os.path.exists(p) else None
        except Exception:
            return None
