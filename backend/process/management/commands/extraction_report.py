"""
manage.py extraction_report — what could NOT be read, per document.

A comparison silently inherits every extraction failure beneath it: a scanned page
has no text, so every part printed on it is reported as *missing*; a table that lost
its header row has columns called `Column_3`, so no concept resolves to it. Neither
raises an error. This command puts those numbers on screen, and refreshes the stored
text-coverage stats for documents ingested before they were recorded.

    manage.py extraction_report                 # every document
    manage.py extraction_report --problems      # only documents with warnings
    manage.py extraction_report --source ISPL   # filename substring
    manage.py extraction_report --doc <id> | --thread <id>
    manage.py extraction_report --no-rescan     # use stored stats, do not re-read PDFs
"""
import os

from django.core.management.base import BaseCommand

from process.extraction_qa import document_qa, record_for_document
from process.models import Document


class Command(BaseCommand):
    help = "Report pages with no text layer, headerless tables and unresolved columns."

    def add_arguments(self, parser):
        parser.add_argument("--doc", help="Only this document id.")
        parser.add_argument("--thread", help="Only documents in this thread id.")
        parser.add_argument("--source", help="Only documents whose filename contains this.")
        parser.add_argument("--problems", action="store_true",
                            help="Only show documents that have warnings.")
        parser.add_argument("--no-rescan", action="store_true",
                            help="Do not re-read the PDFs; use whatever was stored at ingest.")

    def handle(self, *args, **opts):
        docs = Document.objects.all().order_by("uploaded_at")
        if opts["doc"]:
            docs = docs.filter(id=opts["doc"].replace("-", ""))
        if opts["thread"]:
            docs = docs.filter(thread_id=opts["thread"].replace("-", ""))
        if opts["source"]:
            docs = docs.filter(filename__icontains=opts["source"])
        if not docs:
            self.stdout.write(self.style.WARNING("No documents matched."))
            return

        shown = 0
        totals = {"pages": 0, "scanned": 0, "tables": 0, "headerless": 0}
        for doc in docs:
            if not opts["no_rescan"]:
                record_for_document(doc)
                doc.refresh_from_db()
            qa = document_qa(doc)
            cov = qa["text_coverage"] or {}
            totals["pages"] += cov.get("pages", 0)
            totals["scanned"] += cov.get("scanned_pages", 0)
            totals["tables"] += qa["tables"]
            totals["headerless"] += qa["headerless_tables"]

            if opts["problems"] and not qa["warnings"]:
                continue
            shown += 1

            style = self.style.ERROR if qa["warnings"] else self.style.SUCCESS
            self.stdout.write(style(f"\n{doc.filename}  [{doc.category}]"))
            self.stdout.write(
                f"  pages: {cov.get('pages', '?')}"
                f"   no text layer: {cov.get('textless_pages', '?')}"
                f"   of those scans: {cov.get('scanned_pages', '?')}"
                f"   blank: {cov.get('blank_pages', '?')}")
            self.stdout.write(
                f"  tables: {qa['tables']}   headerless: {qa['headerless_tables']}")
            resolved = qa["resolved_concepts"]
            if resolved:
                self.stdout.write("  columns: " + ", ".join(
                    f"{f} → {h}" for f, h in sorted(resolved.items())))
            else:
                self.stdout.write("  columns: none resolved")
            for w in qa["warnings"]:
                self.stdout.write(self.style.WARNING("  ! " + _plain(w)))

        self.stdout.write(self.style.SUCCESS(
            f"\n{shown} document(s) shown — {totals['pages']} pages, "
            f"{totals['scanned']} scanned (not searchable), {totals['tables']} tables, "
            f"{totals['headerless']} headerless"))
        if totals["scanned"]:
            self.stdout.write(self.style.WARNING(
                "Scanned pages carry no searchable text. There is no OCR in this build, "
                "so nothing printed on them can be found or compared."))


def _plain(text):
    return text.replace("**", "").replace("`", "")
