"""
manage.py reextract_tables — back-fill / refresh the structured table store.

Documents uploaded before the pdfplumber grid + anchor table pass existed (or
before a later fix to it) have no — or stale — ExtractedTable rows, so the fast
DB-backed comparison path either fails ("no extracted tables") or gives worse
numbers than re-reading the PDF. This command re-runs *only* the table pass for
PDFs on disk; nothing is re-embedded, Ollama is not needed, and chat is unaffected
while it runs.

    manage.py reextract_tables                 # PDFs that have no pdfplumber tables yet
    manage.py reextract_tables --all           # every PDF (refresh after an extractor fix)
    manage.py reextract_tables --source SSBS   # filename substring
    manage.py reextract_tables --thread <id> | --doc <id>
    manage.py reextract_tables --dry-run

Existing pdfplumber tables (`…_table_pp_…`) for a document are replaced; tables from
the ODL / PyMuPDF text-ingestion pass are left alone.
"""
import os
import time

from django.core.management.base import BaseCommand
from django.db.models import Q

from process.models import Document, ExtractedTable


class Command(BaseCommand):
    help = "Re-run the pdfplumber table extraction (grid + anchor) for uploaded PDFs into the DB."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true",
                            help="Re-extract every PDF, not just those without pdfplumber tables.")
        parser.add_argument("--doc", help="Only this document id.")
        parser.add_argument("--thread", help="Only documents in this thread id.")
        parser.add_argument("--source", help="Only documents whose filename contains this text.")
        parser.add_argument("--keep-existing", action="store_true",
                            help="Do not delete the document's existing pdfplumber tables first "
                                 "(same-id tables are still overwritten).")
        parser.add_argument("--dry-run", action="store_true", help="List what would be done.")

    def handle(self, *args, **opts):
        from process.pipeline.ingestion import _ingest_pdfplumber_tables

        docs = Document.objects.filter(filename__iendswith=".pdf").order_by("uploaded_at")
        if opts["doc"]:
            docs = docs.filter(id=opts["doc"].replace("-", ""))
        if opts["thread"]:
            docs = docs.filter(thread_id=opts["thread"].replace("-", ""))
        if opts["source"]:
            docs = docs.filter(filename__icontains=opts["source"])

        todo, skipped = [], []
        for d in docs:
            doc_key = str(d.id).replace("-", "")
            have = ExtractedTable.objects.filter(
                Q(doc_id=doc_key) | Q(doc_id=str(d.id)), id__contains="_table_pp_").count()
            path = self._path(d)
            if not path:
                skipped.append((d, "file not on disk"))
                continue
            if have and not (opts["all"] or opts["doc"] or opts["source"]):
                skipped.append((d, f"already has {have} pdfplumber table(s); use --all to refresh"))
                continue
            todo.append((d, have, path))

        for d, why in skipped:
            self.stdout.write(f"  skip  {d.filename}  ({why})")
        if not todo:
            self.stdout.write(self.style.WARNING("Nothing to do."))
            return
        self.stdout.write(f"{len(todo)} document(s) to re-extract"
                          + (" (dry run)" if opts["dry_run"] else "") + ":")
        for d, have, path in todo:
            self.stdout.write(f"  -     {d.filename}  [{d.category}]  existing pp tables: {have}")
        if opts["dry_run"]:
            return

        total_new = 0
        t_all = time.time()
        for d, have, path in todo:
            doc_key = str(d.id).replace("-", "")
            t0 = time.time()
            if have and not opts["keep_existing"]:
                n, _ = ExtractedTable.objects.filter(
                    Q(doc_id=doc_key) | Q(doc_id=str(d.id)), id__contains="_table_pp_").delete()
                self.stdout.write(f"  {d.filename}: removed {n} old pdfplumber table(s)")
            parent_id = str(d.thread.parent_id) if d.thread and d.thread.parent_id else None
            try:
                n = _ingest_pdfplumber_tables(path, doc_key, str(d.thread_id), parent_id, d.filename)
            except Exception as e:                       # one bad PDF must not stop the batch
                self.stdout.write(self.style.ERROR(f"  {d.filename}: FAILED — {e}"))
                continue
            total_new += n
            self.stdout.write(self.style.SUCCESS(
                f"  {d.filename}: stored {n} table(s) in {time.time() - t0:.1f}s"))
        self.stdout.write(self.style.SUCCESS(
            f"Done: {total_new} table(s) across {len(todo)} document(s) in {time.time() - t_all:.1f}s"))

    @staticmethod
    def _path(doc):
        try:
            p = doc.file.path
            return p if p and os.path.exists(p) else None
        except Exception:
            return None
