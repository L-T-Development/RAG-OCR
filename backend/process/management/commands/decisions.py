"""
manage.py decisions — move your corrections between installs, and back them up.

The tables, embeddings and mention index can all be rebuilt by re-uploading a
document. Confirmed matches and pinned columns cannot: they are judgments someone
made while reading. This command is how they leave one machine and reach another.

    manage.py decisions export                     # to stdout
    manage.py decisions export --out my.json
    manage.py decisions import --in my.json --dry-run
    manage.py decisions import --in my.json [--overwrite] [--apply-schema]
    manage.py decisions backup [--out file.zip] [--no-media] [--no-vectors]

Import is additive and safe to repeat: an existing decision is left alone unless
--overwrite. Always worth a --dry-run first; it reports exactly what a real run
would change, including any document this machine does not have yet.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from process.portability import (backup_data_dir, export_decisions,
                                 import_decisions, summarize)


class Command(BaseCommand):
    help = "Export, import or back up the decisions a person has made (matches, pinned columns)."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["export", "import", "backup"])
        parser.add_argument("--out", help="File to write (export/backup).")
        parser.add_argument("--in", dest="infile", help="File to read (import).")
        parser.add_argument("--thread", help="Export only this thread's decisions.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Import: report what would change, write nothing.")
        parser.add_argument("--overwrite", action="store_true",
                            help="Import: let the file win over decisions already here.")
        parser.add_argument("--apply-schema", action="store_true",
                            help="Import: also write the field_schema.json override.")
        parser.add_argument("--no-media", action="store_true",
                            help="Backup: leave out uploaded files.")
        parser.add_argument("--no-vectors", action="store_true",
                            help="Backup: leave out the vector store.")

    def handle(self, *args, **opts):
        action = opts["action"]

        if action == "export":
            payload = export_decisions(thread_id=opts.get("thread"))
            text = json.dumps(payload, indent=2, ensure_ascii=False)
            if opts.get("out"):
                with open(opts["out"], "w", encoding="utf-8") as fh:
                    fh.write(text)
                self.stdout.write(self.style.SUCCESS(
                    f"Wrote {opts['out']} — {summarize(payload)}"))
            else:
                self.stdout.write(text)
            return

        if action == "import":
            if not opts.get("infile"):
                raise CommandError("--in <file> is required")
            try:
                with open(opts["infile"], encoding="utf-8") as fh:
                    payload = json.load(fh)
            except (OSError, json.JSONDecodeError) as e:
                raise CommandError(f"Could not read {opts['infile']}: {e}")

            self.stdout.write(f"File contains: {summarize(payload)}")
            report = import_decisions(payload, dry_run=opts["dry_run"],
                                      overwrite=opts["overwrite"],
                                      apply_schema=opts["apply_schema"])
            if not report.get("ok"):
                raise CommandError(report.get("error", "import failed"))

            head = "Would apply" if opts["dry_run"] else "Applied"
            cm, cr = report["confirmed_matches"], report["column_roles"]
            self.stdout.write(self.style.SUCCESS(
                f"\n{head}:\n"
                f"  confirmed matches : +{cm['added']} added, {cm['updated']} updated, "
                f"{cm['unchanged']} already here\n"
                f"  column roles      : +{cr['added']} added, {cr['updated']} updated, "
                f"{cr['unchanged']} already here\n"
                f"  schema override   : {report['field_schema_override']}"))

            if cr["no_such_document"]:
                self.stdout.write(self.style.WARNING(
                    "\n  Not applied — these documents are not on this machine yet. "
                    "Upload them, then run the import again:"))
                for name in sorted(set(cr["no_such_document"])):
                    self.stdout.write(f"    - {name}")
            for label, bad in (("confirmed match", cm["invalid"]),
                               ("column role", cr["invalid"])):
                if bad:
                    self.stdout.write(self.style.ERROR(
                        f"\n  {len(bad)} {label}(s) skipped as malformed"))
            if opts["dry_run"]:
                self.stdout.write("\nNothing was written (--dry-run).")
            return

        result = backup_data_dir(opts.get("out"),
                                 include_media=not opts["no_media"],
                                 include_vectors=not opts["no_vectors"])
        if not result.get("ok"):
            raise CommandError(result.get("error", "backup failed"))
        mb = result["bytes_zip"] / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f"Backed up {result['files']} file(s) -> {result['path']} ({mb:.1f} MB)"))
        if not result["included"]["vectors"] or not result["included"]["media"]:
            self.stdout.write(
                "  (uploads/vectors left out — rebuildable by re-uploading; the "
                "database, and every decision in it, is included)")
