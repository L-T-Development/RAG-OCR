"""
Regression tests for document comparison.
================================================================================

Run with:   python manage.py test process                      (fast — under a second)
            python manage.py test process.tests.MatchingRuleTests   (one class)

            RAGOCR_CORPUS_TESTS=1 python manage.py test process
                adds `RealCorpusTests`, which re-extracts the real PDFs in
                `backend/pdfs/` and checks the pinned baselines. Takes minutes, and
                skips itself when those files are not on this machine. Worth running
                before touching extraction, matching, or storage.

WHY THESE EXIST
---------------
The comparison engine is a stack of deterministic rules that were each added to fix a
specific, observed way real documents lie to a naive string comparison — a part number
that wrapped inside its cell, a leading zero, an annotation suffix, a header that only
appears on the first page of a table. Every one of those rules is invisible until it
regresses, and when it does it does not crash: it silently reports a part as *missing*
from a document that contains it, or worse, silently matches the wrong column.

So the important assertions here are about **buckets and counts**, not return codes.

FIXTURES ARE SYNTHETIC ON PURPOSE
---------------------------------
These tests build their own ExtractedTable rows in the test database. They deliberately
do NOT read `backend/pdfs/` or `backend/db.sqlite3`: during development the source PDFs
for the original baselines were deleted from disk by ordinary app use, which silently
disabled the file-path regressions. Tests that can evaporate are not tests.
`RealCorpusTests` at the bottom is the exception, and it skips itself when the files are
absent.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from process import column_profile, column_roles, comparison, mentions
from process.field_schema import (canonical_field_for_query, is_boilerplate_value,
                                  normalize_value, pair_likely_values, resolve_header)
from process.models import (ColumnRole, ConfirmedMatch, Document, ExtractedTable,
                            IdentifierMention, TableCell, TableRow, Thread)
from process.pipeline.tables import store_table


# ══════════════════════════════════════════════════════════════════════════════
#  Pure functions — no database, no fixtures
# ══════════════════════════════════════════════════════════════════════════════

class HeaderResolutionTests(SimpleTestCase):
    """The same concept is labelled differently in every document family."""

    def test_mrls_and_ispl_both_reach_the_manufacturer_part_column(self):
        # The cross-document identifier must win in BOTH families, or MRLS and
        # ISPL parts never line up.
        self.assertEqual(
            resolve_header("part", ["Sr. No.", "Manufacturer's Part No.", "Nomenclature"], "mrls"),
            "Manufacturer's Part No.")
        self.assertEqual(
            resolve_header("part", ["Sl. No.", "DS Cat No.", "Manufacturer’s Part No."], "ispl"),
            "Manufacturer’s Part No.")

    def test_ispl_falls_back_to_ds_cat_no_only_when_nothing_better_exists(self):
        self.assertEqual(resolve_header("part", ["Sl No", "DS Cat No.", "Description"], "ispl"),
                         "DS Cat No.")

    def test_firms_part_no_outranks_ds_cat_no(self):
        # The MMME ISPL case: both columns exist, and picking DS Cat No. here is a
        # silent wrong-column comparison rather than an error.
        self.assertEqual(
            resolve_header("part", ["Sl No", "DS Cat No.", "Firm's Part No"], "ispl"),
            "Firm's Part No")

    def test_punctuation_and_quote_glyphs_do_not_matter(self):
        for header in ["Firms Part No.", "Firm's Part-No.", "FIRMS PART NO", "Part-No"]:
            with self.subTest(header=header):
                self.assertEqual(resolve_header("part", ["Sl No", header, "Qty"], "ispl"), header)

    def test_manual_and_drawing_categories_have_real_schema_rows(self):
        self.assertEqual(resolve_header("part", ["Item", "Part No", "Qty"], "manual"), "Part No")
        self.assertEqual(resolve_header("drg", ["Item", "Drg No.", "Qty"], "drawing"), "Drg No.")

    def test_nsn_and_part_are_different_concepts_in_an_ispl(self):
        headers = ["Sl No", "DS Cat No.", "Manufacturer's Part No."]
        self.assertEqual(resolve_header("nsn", headers, "ispl"), "DS Cat No.")
        self.assertEqual(resolve_header("part", headers, "ispl"), "Manufacturer's Part No.")

    def test_unknown_column_resolves_to_nothing_rather_than_guessing(self):
        self.assertIsNone(resolve_header("unit price", ["Sr. No.", "Part No", "Qty"], "mrls"))

    def test_canonical_field_mapping(self):
        self.assertEqual(canonical_field_for_query("firm's part no."), "part_no")
        self.assertEqual(canonical_field_for_query("mfr p/n"), "part_no")
        self.assertEqual(canonical_field_for_query("stock no"), "nsn")


class MatchingRuleTests(SimpleTestCase):
    """`pair_likely_values` — every rule here exists because of a real false 'missing'."""

    @staticmethod
    def _reason(a, b):
        pairs = pair_likely_values({a}, {b})
        return pairs[0][2] if pairs else None

    def test_spacing_from_a_wrapped_cell(self):
        # Reported by the user: present in both files, called missing.
        reason = self._reason("442 071 820394", "442 071 820 394")
        self.assertIsNotNone(reason)
        self.assertIn("spacing", reason)

    def test_leading_zeros(self):
        self.assertIn("leading zeros", self._reason("1534601", "01534601"))

    def test_annotation_prefix_and_suffix(self):
        self.assertIn("annotation", self._reason("NAMP-08020000", "DIC-NAMP-08020000"))
        self.assertIn("annotation", self._reason("XL17461 NAMICA", "XL17461"))

    def test_typo_tolerated_in_words_but_never_in_catalogue_codes(self):
        # One dropped character in a word-like designation.
        self.assertIsNotNone(self._reason("Drain Plug", "Drai Plug"))
        # Sequential part numbers are one character apart and are DIFFERENT parts.
        self.assertIsNone(self._reason("10106255", "10106256"))

    def test_typo_tolerance_is_bounded_by_length(self):
        # A transposition is two edits; at 15 characters only one is allowed, so
        # this stays unpaired rather than being quietly merged.
        self.assertIsNone(self._reason("WELDABLE NIPPLE", "WELDABLE NIPPEL"))

    def test_each_value_is_paired_at_most_once(self):
        pairs = pair_likely_values({"1534601", "1534602"}, {"01534601"})
        self.assertEqual(len(pairs), 1)

    def test_genuinely_different_values_are_left_alone(self):
        self.assertIsNone(self._reason("2608300", "DD901201-1"))

    def test_normalize_value_joins_wrapped_hyphens_and_strips_newlines(self):
        self.assertEqual(normalize_value("DIC-NAMP-\n01210000"), "DIC-NAMP-01210000")
        self.assertEqual(normalize_value("ABC - 123"), "ABC-123")

    def test_boilerplate_is_not_a_part_identifier(self):
        for value in ["Standard Item", "STANDAR ITEM", "[3]", "As Required", "TBD"]:
            with self.subTest(value=value):
                self.assertTrue(is_boilerplate_value(value))
        # A real alphabetic part designation must survive.
        self.assertFalse(is_boilerplate_value("ROTHE-ERDEMAKE"))

    def test_empty_markers_are_handled_separately_from_boilerplate(self):
        # "N/A" and friends are *empty*, not placeholder designations — different
        # function, and they never reach the comparison at all.
        from process.field_schema import is_empty_value
        for value in ["", "-", "N/A", "NIL", "None"]:
            with self.subTest(value=value):
                self.assertTrue(is_empty_value(value))


class IdentifierExtractionTests(SimpleTestCase):
    """What counts as an identifier when scanning a manual's prose."""

    def test_catalogue_shapes_are_identifiers(self):
        found = mentions.extract_identifiers(
            "Fit XL17461 and NAMP-08020000 to the assembly; see 442 071 820394.")
        self.assertIn("XL17461", found)
        self.assertIn("NAMP-08020000", found)

    def test_prose_numbers_are_not_identifiers(self):
        found = mentions.extract_identifiers("In 2024 the 3 units were checked at 12.50 bar.")
        self.assertEqual(found, [], f"prose leaked into the index: {found}")

    def test_norm_forms_gives_spaced_and_unspaced(self):
        self.assertEqual(mentions.norm_forms("442 071 820 394"),
                         ("442 071 820 394", "442071820394"))


class ColumnProfileTests(SimpleTestCase):
    """Value shape is advisory: it finds identifier columns, it never picks one."""

    def test_serial_counter_is_recognised_and_never_offered(self):
        self.assertTrue(column_profile.looks_like_counter([str(i) for i in range(1, 30)]))
        suggestions = column_profile.identifier_columns({
            "Sr. No.": [str(i) for i in range(1, 30)],
            "Part No": [f"NAMP-{i:08d}" for i in range(1, 30)],
        })
        headers = [h for h, _why in suggestions]
        self.assertIn("Part No", headers)
        self.assertNotIn("Sr. No.", headers)


# ══════════════════════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════════════════════

class FixtureMixin:
    """Builds documents whose tables are written through the real storage path."""

    MRLS_HEADERS = ["Sr. No.", "Manufacturer's Part No.", "Nomenclature", "Total Qty."]
    MRLS_ROWS = [
        ["1", "XL17461 NAMICA", "Limit Switch", "2"],        # annotation suffix
        ["2", "1534601", "Seal Kit", "1"],                    # leading-zero variant
        ["3", "442 071 820394", "Weldable Nipple", "4"],      # wrapped-cell spacing
        ["4", "NAMP-08020000", "Bracket", "1"],               # exact match
        ["5", "DD901201-1", "Relay Board", "1"],              # genuinely missing
        ["6", "Standard Item", "Hex Screw", "8"],             # boilerplate
        ["7", "S067327-LC-001", "PKT Sight", "1"],            # differs in description
    ]

    ISPL_HEADERS = ["Sl. No.", "DS Cat No.", "Firm's Part No", "Description", "No. Off"]
    ISPL_ROWS = [
        ["1", "9999-11-111-1111", "XL17461", "Limit Switch", "1"],
        ["2", "9999-11-111-2222", "01534601", "Seal Kit", "1"],
        ["3", "9999-11-111-3333", "442 071 820 394", "Weldable Nipple", "1"],
        ["4", "9999-11-111-4444", "NAMP-08020000", "Bracket", "1"],
        ["5", "9999-11-111-5555", "ZZ-EXTRA-0001", "Extra Part Only In ISPL", "1"],
        ["6", "9999-11-111-6666", "STANDAR ITEM", "Hex Screw", "1"],   # real typo
        ["7", "9999-11-111-7777", "S067327-LC-001", "Night Sight", "1"],
    ]

    def make_thread(self, name="test", parent=None):
        return Thread.objects.create(name=name, parent=parent)

    def make_doc(self, thread, filename, category):
        return Document.objects.create(
            thread=thread, file=f"pdfs/{filename}", filename=filename,
            category=category, status="done")

    def add_table(self, doc, headers, rows, page=1, index=0):
        store_table(
            table_id=f"{doc.id}_{page}_t{index}", doc_id=str(doc.id),
            thread_id=str(doc.thread_id), parent_id=None, source=doc.filename,
            page=page, table_index=index, headers=headers,
            row_count=len(rows), column_count=len(headers),
            table_data=[headers] + rows, caption="")

    def build_pair(self):
        thread = self.make_thread()
        mrls = self.make_doc(thread, "MRLS_TEST.pdf", "mrls")
        ispl = self.make_doc(thread, "ISPL_TEST.pdf", "ispl")
        self.add_table(mrls, self.MRLS_HEADERS, self.MRLS_ROWS)
        self.add_table(ispl, self.ISPL_HEADERS, self.ISPL_ROWS)
        return thread, mrls, ispl

    @staticmethod
    def buckets(result):
        res = result.get("results", {})
        return {
            "common": res.get("common", {}).get("count", 0),
            "likely": res.get("likely_matches", {}).get("count", 0),
            "missing": res.get("in_pdf1_only", {}).get("count", 0),
            "extra": res.get("in_pdf2_only", {}).get("count", 0),
            "excluded": res.get("excluded", {}).get("count", 0),
            "confirmed": res.get("confirmed_matches", {}).get("count", 0),
            "modified": res.get("modified", {}).get("count", 0),
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Storage
# ══════════════════════════════════════════════════════════════════════════════

class StorageTests(FixtureMixin, TestCase):
    """`store_table` writes one transaction with bulk inserts — it must still be exact."""

    def test_every_cell_round_trips(self):
        thread = self.make_thread()
        doc = self.make_doc(thread, "STORE.pdf", "mrls")
        self.add_table(doc, self.MRLS_HEADERS, self.MRLS_ROWS)

        table = ExtractedTable.objects.get(doc_id=str(doc.id))
        self.assertEqual(table.column_count, len(self.MRLS_HEADERS))
        header_row = table.rows.get(is_header=True)
        self.assertEqual([c.value for c in header_row.cells.order_by("column_index")],
                         self.MRLS_HEADERS)

        data_rows = table.rows.filter(is_header=False).order_by("row_index")
        self.assertEqual(data_rows.count(), len(self.MRLS_ROWS))
        for stored, expected in zip(data_rows, self.MRLS_ROWS):
            self.assertEqual([c.value for c in stored.cells.order_by("column_index")], expected)

    def test_restoring_the_same_table_replaces_rather_than_duplicates(self):
        thread = self.make_thread()
        doc = self.make_doc(thread, "STORE.pdf", "mrls")
        self.add_table(doc, self.MRLS_HEADERS, self.MRLS_ROWS)
        before = (TableRow.objects.count(), TableCell.objects.count())
        self.add_table(doc, self.MRLS_HEADERS, self.MRLS_ROWS)   # same id again
        self.assertEqual(ExtractedTable.objects.filter(doc_id=str(doc.id)).count(), 1)
        self.assertEqual((TableRow.objects.count(), TableCell.objects.count()), before)


# ══════════════════════════════════════════════════════════════════════════════
#  Comparison
# ══════════════════════════════════════════════════════════════════════════════

class ComparisonTests(FixtureMixin, TestCase):

    def setUp(self):
        self.thread, self.mrls, self.ispl = self.build_pair()

    def compare(self, **kw):
        return comparison.compare_documents(self.mrls, self.ispl, kw.pop("column", "part"),
                                            thread=self.thread, **kw)

    def test_the_whole_cascade_in_one_comparison(self):
        b = self.buckets(self.compare())
        # exact: NAMP-08020000, and S067327-LC-001 (same part, different description)
        self.assertEqual(b["common"], 2)
        # spacing + leading zeros + annotation suffix
        self.assertEqual(b["likely"], 3)
        # only the genuinely absent part
        self.assertEqual(b["missing"], 1)
        # "Standard Item" / "STANDAR ITEM" are placeholders on both sides: pulled
        # out before pairing, so they inflate neither `missing` nor `likely`.
        self.assertEqual(b["excluded"], 2, "boilerplate was not excluded")

    def test_the_missing_value_is_the_right_one(self):
        result = self.compare()
        self.assertEqual(result["results"]["in_pdf1_only"]["values"], ["DD901201-1"])

    def test_each_near_match_says_why(self):
        pairs = self.compare()["results"]["likely_matches"]["pairs"]
        reasons = {p["pdf1_value"]: p["reason"] for p in pairs}
        self.assertIn("spacing", reasons["442 071 820394"])
        self.assertIn("leading zeros", reasons["1534601"])
        self.assertIn("annotation", reasons["XL17461 NAMICA"])

    def test_the_resolved_columns_are_reported(self):
        # Both sides must name a real header, so a wrong column is visible.
        self.assertIn("Manufacturer's Part No.", self.compare()["column"])
        self.assertIn("Firm's Part No", self.compare()["column"])

    def test_row_level_diff_finds_the_changed_description_only(self):
        modified = self.compare()["results"].get("modified", {})
        self.assertEqual(modified.get("count"), 1)
        item = modified["items"][0]
        self.assertEqual(item["value"], "S067327-LC-001")
        self.assertEqual(item["differences"][0]["field"], "nomenclature")

    def test_quantities_are_not_compared_across_differently_named_columns(self):
        # "Total Qty." (fleet) vs "No. Off" (per assembly) count different things;
        # comparing them flags every matched row.
        for item in self.compare()["results"].get("modified", {}).get("items", []):
            self.assertNotIn("qty", [d["field"] for d in item["differences"]])

    def test_a_confirmed_match_moves_out_of_missing(self):
        ConfirmedMatch.objects.create(
            source_a=self.mrls.filename, source_b=self.ispl.filename,
            column_key="part_no", value_a="DD901201-1", value_b="ZZ-EXTRA-0001",
            thread=self.thread)
        b = self.buckets(self.compare())
        self.assertEqual(b["missing"], 0)
        self.assertEqual(b["confirmed"], 1)

    def test_unknown_column_fails_loudly_with_the_real_headers(self):
        result = self.compare(column="unit price")
        self.assertFalse(result.get("found"))
        self.assertTrue(result.get("available_columns_pdf1"))

    def test_quoted_header_is_taken_literally(self):
        # Naming DS Cat No. explicitly must not be redirected to the part column.
        result = comparison.compare_documents(
            self.mrls, self.ispl, "Manufacturer's Part No.",
            column_b="DS Cat No.", prefer_literal=True, thread=self.thread)
        self.assertIn("DS Cat No.", result["column"])

    def test_inherited_documents_are_in_scope(self):
        child = self.make_thread("child", parent=self.thread)
        self.assertEqual(comparison.documents_in_scope(child).count(), 2)


class MultiFileComparisonTests(FixtureMixin, TestCase):

    def test_three_files_produce_a_presence_matrix_not_a_silent_pair(self):
        thread, mrls, ispl = self.build_pair()
        second = self.make_doc(thread, "ISPL_TWO.pdf", "ispl")
        self.add_table(second, self.ISPL_HEADERS, self.ISPL_ROWS[:1])

        m = comparison.compare_many(mrls, [ispl, second], "part", thread=thread)
        self.assertEqual(sorted(m["ok_targets"]), ["ISPL_TEST.pdf", "ISPL_TWO.pdf"])
        # DD901201-1 is in neither target.
        self.assertIn("DD901201-1", m["missing_everywhere"])
        # A part only the first ISPL carries is partial, not missing.
        self.assertIn("NAMP-08020000", m["partial"])


# ══════════════════════════════════════════════════════════════════════════════
#  Text mode (compare a column against a manual's prose)
# ══════════════════════════════════════════════════════════════════════════════

class TextModeTests(FixtureMixin, TestCase):

    def setUp(self):
        self.thread, self.mrls, _ispl = self.build_pair()
        self.manual = self.make_doc(self.thread, "MANUAL.pdf", "manual")
        # A manual mentions parts in running text, not in a part column.
        pages = {
            3: "Remove the limit switch XL17461 before servicing the bracket.",
            7: "Torque NAMP-08020000 to 40 Nm. Nipple 442 071 820 394 is a spare.",
        }
        mentions.index_chunks(
            str(self.manual.id), str(self.thread.id), None, self.manual.filename,
            list(pages.values()),
            [{"page": p, "doc_id": str(self.manual.id)} for p in pages])

    def test_values_are_found_in_prose_with_page_numbers(self):
        hits = mentions.lookup_values(["XL17461", "NAMP-08020000"], str(self.manual.id))
        self.assertEqual([h["page"] for h in hits["XL17461"]], [3])
        self.assertEqual([h["page"] for h in hits["NAMP-08020000"]], [7])

    def test_spacing_differences_still_match_in_prose(self):
        hits = mentions.lookup_values(["442 071 820394"], str(self.manual.id))
        self.assertTrue(hits, "wrapped-cell value not found in the manual's text")

    def test_absent_value_is_absent(self):
        self.assertNotIn("DD901201-1", mentions.lookup_values(["DD901201-1"], str(self.manual.id)))

    def test_text_mode_reports_variants_separately_from_exact_mentions(self):
        m = comparison.compare_against_text(self.mrls, [self.manual], "part", thread=self.thread)
        self.assertTrue(m["found"])
        # "XL17461 NAMICA" is mentioned only as "XL17461" — a variant, not a match.
        self.assertIn("XL17461 NAMICA", m["near_anywhere"])
        self.assertIn("DD901201-1", m["missing_everywhere"])

    def test_index_is_removed_with_the_document(self):
        mentions.delete_for(doc_id=str(self.manual.id))
        self.assertFalse(IdentifierMention.objects.filter(
            doc_id=mentions.doc_key(self.manual.id)).exists())


# ══════════════════════════════════════════════════════════════════════════════
#  Per-document column roles
# ══════════════════════════════════════════════════════════════════════════════

class ColumnRoleTests(FixtureMixin, TestCase):

    def setUp(self):
        self.thread, self.mrls, self.ispl = self.build_pair()

    def test_a_pinned_column_overrides_the_schema(self):
        # The schema would pick Firm's Part No; the human says use DS Cat No.
        self.assertEqual(column_roles.set_role(self.ispl, "part_no", "DS Cat No.")["ok"], True)
        result = comparison.compare_documents(self.mrls, self.ispl, "part", thread=self.thread)
        self.assertIn("DS Cat No.", result["column"])

    def test_clearing_a_pin_restores_schema_behaviour(self):
        column_roles.set_role(self.ispl, "part_no", "DS Cat No.")
        column_roles.set_role(self.ispl, "part_no", None)
        self.assertFalse(ColumnRole.objects.filter(doc_id=column_roles._key(self.ispl.id)).exists())
        result = comparison.compare_documents(self.mrls, self.ispl, "part", thread=self.thread)
        self.assertIn("Firm's Part No", result["column"])

    def test_a_header_that_is_not_in_the_document_is_rejected(self):
        outcome = column_roles.set_role(self.ispl, "part_no", "No Such Column")
        self.assertFalse(outcome["ok"])
        self.assertIn("available_columns", outcome)

    def test_an_unknown_concept_is_rejected(self):
        self.assertFalse(column_roles.set_role(self.ispl, "not_a_field", "DS Cat No.")["ok"])

    def test_describe_reports_where_each_answer_came_from(self):
        column_roles.set_role(self.ispl, "part_no", "DS Cat No.")
        described = column_roles.describe(self.ispl)
        self.assertEqual(described["roles"]["part_no"]["origin"], "user")
        self.assertEqual(described["roles"]["nomenclature"]["origin"], "schema")


# ══════════════════════════════════════════════════════════════════════════════
#  Schema override file
# ══════════════════════════════════════════════════════════════════════════════

class SchemaOverrideTests(SimpleTestCase):
    """`field_schema.json` must be live-reloadable and must never break on bad input."""

    def setUp(self):
        from process import field_schema
        self.fs = field_schema
        self.tmp = tempfile.mkdtemp()
        self._old_env = os.environ.get("RAGOCR_DATA_DIR")
        os.environ["RAGOCR_DATA_DIR"] = self.tmp
        self.fs._loaded_mtime = None
        self.addCleanup(self._restore)

    def _restore(self):
        if self._old_env is None:
            os.environ.pop("RAGOCR_DATA_DIR", None)
        else:
            os.environ["RAGOCR_DATA_DIR"] = self._old_env
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.fs._loaded_mtime = None
        self.fs._reset_to_defaults()

    def _write(self, text):
        path = os.path.join(self.tmp, "field_schema.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        self.fs._loaded_mtime = None      # force a re-read regardless of clock resolution
        return path

    def test_an_override_changes_resolution_without_a_restart(self):
        headers = ["Sl No", "DS Cat No.", "Manufacturer's Part No."]
        self.assertEqual(resolve_header("part", headers, "ispl"), "Manufacturer's Part No.")
        self._write('{"category_schema": {"ispl": {"part_no": ["ds cat no", "part no"]}}}')
        self.assertEqual(resolve_header("part", headers, "ispl"), "DS Cat No.")

    def test_a_broken_file_is_ignored_and_the_last_good_schema_survives(self):
        self._write("{ not json")
        effective = self.fs.effective_schema()
        self.assertIsNotNone(effective["override_error"])
        self.assertEqual(
            resolve_header("part", ["Sl No", "Manufacturer's Part No."], "ispl"),
            "Manufacturer's Part No.")

    def test_an_unknown_field_is_rejected(self):
        self._write('{"category_schema": {"ispl": {"nope": ["x"]}}}')
        self.assertIn("unknown canonical field", self.fs.effective_schema()["override_error"])


# ══════════════════════════════════════════════════════════════════════════════
#  HTTP surface
# ══════════════════════════════════════════════════════════════════════════════

class ApiTests(FixtureMixin, TestCase):

    def setUp(self):
        self.thread, self.mrls, self.ispl = self.build_pair()

    def test_field_schema_endpoint_reports_the_effective_schema(self):
        body = self.client.get("/api/field-schema/").json()
        self.assertIn("ispl", body["category_schema"])
        self.assertIn("part_no", body["canonical_fields"])
        self.assertIn("override_path", body)

    def test_columns_endpoint_round_trips_a_pin(self):
        url = f"/api/documents/{self.ispl.id}/columns/"
        self.assertEqual(self.client.get(url).json()["roles"]["part_no"]["origin"], "schema")

        response = self.client.post(url, data={"field": "part_no", "header": "DS Cat No."},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(url).json()["roles"]["part_no"],
                         {"header": "DS Cat No.", "origin": "user"})

    def test_columns_endpoint_rejects_a_header_the_document_does_not_have(self):
        response = self.client.post(
            f"/api/documents/{self.ispl.id}/columns/",
            data={"field": "part_no", "header": "Nope"}, content_type="application/json")
        self.assertEqual(response.status_code, 400)


class RunComparisonApiTests(FixtureMixin, TestCase):
    """The endpoint the wizard drives — same engine as chat, no phrasing involved."""

    def setUp(self):
        self.thread, self.mrls, self.ispl = self.build_pair()

    def run_compare(self, **body):
        import json
        payload = {"thread_id": str(self.thread.id),
                   "doc_ids": [str(self.mrls.id), str(self.ispl.id)],
                   "column": "part"}
        payload.update(body)
        return self.client.post("/api/comparison/run/", data=json.dumps(payload),
                                content_type="application/json")

    def test_pairwise_returns_the_same_buckets_as_the_engine(self):
        body = self.run_compare().json()
        self.assertEqual(body["mode"], "columns")
        summary = body["summary"]
        self.assertEqual(summary["kind"], "pairwise")
        self.assertEqual(summary["common"]["count"], 2)
        self.assertEqual(summary["likely"]["count"], 3)
        self.assertEqual(summary["missing"]["count"], 1)
        self.assertEqual(summary["missing"]["values"], ["DD901201-1"])
        self.assertEqual(summary["modified"]["count"], 1)
        self.assertTrue(body["report_job_id"], "an Excel report should be registered")

    def test_the_resolved_columns_come_back_for_display(self):
        body = self.run_compare().json()
        self.assertIn("Manufacturer's Part No.", body["column"])
        self.assertIn("Firm's Part No", body["column"])

    def test_a_literal_header_is_honoured(self):
        body = self.run_compare(column="Manufacturer's Part No.",
                                column_b="DS Cat No.", literal=True).json()
        self.assertIn("DS Cat No.", body["column"])

    def test_three_documents_return_a_matrix(self):
        third = self.make_doc(self.thread, "ISPL_TWO.pdf", "ispl")
        self.add_table(third, self.ISPL_HEADERS, self.ISPL_ROWS[:1])
        body = self.run_compare(doc_ids=[str(self.mrls.id), str(self.ispl.id),
                                         str(third.id)]).json()
        self.assertEqual(body["summary"]["kind"], "matrix")
        self.assertIn("DD901201-1", body["summary"]["missing_values"])

    def test_mention_mode(self):
        manual = self.make_doc(self.thread, "MANUAL.pdf", "manual")
        mentions.index_chunks(str(manual.id), str(self.thread.id), None, manual.filename,
                              ["Fit XL17461 and NAMP-08020000 during overhaul."],
                              [{"page": 1, "doc_id": str(manual.id)}])
        body = self.run_compare(doc_ids=[str(self.mrls.id), str(manual.id)],
                                mode="mentions").json()
        self.assertEqual(body["summary"]["kind"], "mentions")
        self.assertIn("DD901201-1", body["summary"]["missing_values"])

    def test_warnings_travel_with_the_result(self):
        self.ispl.extraction_stats = {"pages": 20, "textless_pages": 5,
                                      "scanned_pages": 5, "blank_pages": 0}
        self.ispl.save(update_fields=["extraction_stats"])
        self.assertTrue(any("scanned" in w for w in self.run_compare().json()["warnings"]))

    def test_a_document_outside_the_thread_is_refused(self):
        other = self.make_doc(self.make_thread("elsewhere"), "OTHER.pdf", "ispl")
        response = self.run_compare(doc_ids=[str(self.mrls.id), str(other.id)])
        self.assertEqual(response.status_code, 400)
        self.assertIn("Not in this thread", response.json()["error"])

    def test_fewer_than_two_documents_is_refused(self):
        self.assertEqual(self.run_compare(doc_ids=[str(self.mrls.id)]).status_code, 400)


class ChatRoutingTests(FixtureMixin, TestCase):
    """Both routers must reach the same engine — the bug that started Phase 0."""

    def setUp(self):
        self.thread, self.mrls, self.ispl = self.build_pair()

    def ask(self, query):
        import json
        response = self.client.post(
            f"/api/chat/{self.thread.id}/", data=json.dumps({"query": query}),
            content_type="application/json")
        return response.json().get("answer", "")

    def test_a_plain_comparison_question_is_answered_by_the_comparison_engine(self):
        answer = self.ask("compare part no between @MRLS_TEST.pdf and @ISPL_TEST.pdf")
        self.assertIn("Comparison:", answer)
        self.assertIn("Matched exactly", answer)

    def test_a_mention_question_uses_text_mode(self):
        manual = self.make_doc(self.thread, "MANUAL.pdf", "manual")
        mentions.index_chunks(str(manual.id), str(self.thread.id), None, manual.filename,
                              ["Fit XL17461 during overhaul."],
                              [{"page": 1, "doc_id": str(manual.id)}])
        answer = self.ask("are all the part numbers in @MRLS_TEST.pdf "
                          "mentioned anywhere in @MANUAL.pdf")
        self.assertIn("Mention check", answer)

    def test_naming_a_file_that_is_not_here_says_so(self):
        # Regression: this used to fall through to "just use the first two
        # documents" and confidently compare a pair the user never asked for.
        answer = self.ask("compare part no between @MRLS_TEST.pdf and @NOPE.pdf")
        self.assertNotIn("Matched exactly", answer)
        self.assertIn("NOPE.pdf", answer)
        self.assertIn("ISPL_TEST.pdf", answer, "should list what IS available")


# ══════════════════════════════════════════════════════════════════════════════
#  Portability — the decisions must survive this machine
# ══════════════════════════════════════════════════════════════════════════════

class DecisionExportTests(FixtureMixin, TestCase):

    def setUp(self):
        self.thread, self.mrls, self.ispl = self.build_pair()
        ConfirmedMatch.objects.create(
            source_a=self.mrls.filename, source_b=self.ispl.filename,
            column_key="part_no", value_a="DD901201-1", value_b="ZZ-EXTRA-0001",
            note="same relay board", thread=self.thread)
        column_roles.set_role(self.ispl, "part_no", "DS Cat No.")

    def test_export_carries_both_kinds_of_decision(self):
        from process.portability import export_decisions
        payload = export_decisions()
        self.assertEqual(payload["format"], "ragocr-decisions")
        self.assertEqual(len(payload["confirmed_matches"]), 1)
        self.assertEqual(payload["confirmed_matches"][0]["value_b"], "ZZ-EXTRA-0001")
        self.assertEqual(len(payload["column_roles"]), 1)
        self.assertEqual(payload["column_roles"][0]["header_text"], "DS Cat No.")

    def test_column_roles_are_keyed_by_filename_not_by_local_id(self):
        # The whole point of the format: a document id is generated per install, so
        # exporting it would produce a file that applies to nothing elsewhere.
        from process.portability import export_decisions
        role = export_decisions()["column_roles"][0]
        self.assertEqual(role["source"], "ISPL_TEST.pdf")
        self.assertNotIn("doc_id", role)

    def test_the_endpoint_offers_it_as_a_download(self):
        response = self.client.get("/api/decisions/export/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertEqual(json.loads(response.content)["format"], "ragocr-decisions")


class DecisionImportTests(FixtureMixin, TestCase):
    """Importing must behave as if it landed on a different machine."""

    EXPORTED = {
        "format": "ragocr-decisions", "version": 1,
        "confirmed_matches": [{
            "source_a": "MRLS_TEST.pdf", "source_b": "ISPL_TEST.pdf",
            "column_key": "part_no", "value_a": "DD901201-1",
            "value_b": "ZZ-EXTRA-0001", "note": "same relay board",
        }],
        "column_roles": [{
            "source": "ISPL_TEST.pdf", "field": "part_no",
            "header_text": "DS Cat No.", "note": "",
        }],
        "field_schema_override": {"category_schema": {"ispl": {"part_no": ["ds cat no"]}}},
    }

    def setUp(self):
        # A fresh install: same documents, different ids, no decisions.
        self.thread, self.mrls, self.ispl = self.build_pair()

    def test_a_dry_run_changes_nothing(self):
        from process.portability import import_decisions
        report = import_decisions(self.EXPORTED, dry_run=True)
        self.assertTrue(report["ok"])
        self.assertEqual(report["confirmed_matches"]["added"], 1)
        self.assertEqual(report["column_roles"]["added"], 1)
        self.assertEqual(ConfirmedMatch.objects.count(), 0)
        self.assertEqual(ColumnRole.objects.count(), 0)

    def test_import_applies_to_this_machines_documents(self):
        from process.portability import import_decisions
        import_decisions(self.EXPORTED)
        self.assertEqual(ConfirmedMatch.objects.count(), 1)

        role = ColumnRole.objects.get()
        self.assertEqual(role.header_text, "DS Cat No.")
        # Resolved against THIS install's document id, not the exporter's.
        self.assertEqual(role.doc_id, column_roles._key(self.ispl.id))

    def test_the_imported_decision_actually_changes_a_comparison(self):
        from process.portability import import_decisions
        before = comparison.compare_documents(self.mrls, self.ispl, "part",
                                              thread=self.thread)
        self.assertIn("Firm's Part No", before["column"])

        import_decisions(self.EXPORTED)
        after = comparison.compare_documents(self.mrls, self.ispl, "part",
                                             thread=self.thread)
        self.assertIn("DS Cat No.", after["column"])

    def test_importing_twice_is_harmless(self):
        from process.portability import import_decisions
        import_decisions(self.EXPORTED)
        second = import_decisions(self.EXPORTED)
        self.assertEqual(second["confirmed_matches"]["added"], 0)
        self.assertEqual(second["confirmed_matches"]["unchanged"], 1)
        self.assertEqual(ColumnRole.objects.count(), 1)

    def test_an_existing_decision_is_kept_unless_overwrite(self):
        from process.portability import import_decisions
        column_roles.set_role(self.ispl, "part_no", "Firm's Part No")

        import_decisions(self.EXPORTED)
        self.assertEqual(ColumnRole.objects.get().header_text, "Firm's Part No")

        import_decisions(self.EXPORTED, overwrite=True)
        self.assertEqual(ColumnRole.objects.get().header_text, "DS Cat No.")

    def test_a_document_this_machine_does_not_have_is_reported_not_dropped(self):
        from process.portability import import_decisions
        payload = json.loads(json.dumps(self.EXPORTED))
        payload["column_roles"][0]["source"] = "SOMETHING_ELSE.pdf"
        report = import_decisions(payload)
        self.assertEqual(report["column_roles"]["added"], 0)
        self.assertIn("SOMETHING_ELSE.pdf", report["column_roles"]["no_such_document"])

    def test_the_schema_override_is_only_written_when_asked(self):
        from process.portability import import_decisions
        self.assertIn("not applied", import_decisions(self.EXPORTED)["field_schema_override"])

    def test_a_foreign_file_is_refused(self):
        from process.portability import import_decisions
        self.assertFalse(import_decisions({"format": "something-else"})["ok"])
        self.assertFalse(import_decisions({"format": "ragocr-decisions",
                                           "version": 99})["ok"])

    def test_malformed_entries_are_reported_rather_than_crashing(self):
        from process.portability import import_decisions
        report = import_decisions({
            "format": "ragocr-decisions", "version": 1,
            "confirmed_matches": [{"source_a": "a.pdf"}],
            "column_roles": [{"source": "ISPL_TEST.pdf", "field": "not_a_field",
                              "header_text": "x"}],
        })
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["confirmed_matches"]["invalid"]), 1)
        self.assertEqual(len(report["column_roles"]["invalid"]), 1)

    def test_the_import_endpoint_round_trips(self):
        response = self.client.post(
            "/api/decisions/import/",
            data=json.dumps({"payload": self.EXPORTED, "dry_run": True}),
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["dry_run"])
        self.assertEqual(ConfirmedMatch.objects.count(), 0)


class BackupTests(TestCase):

    def test_a_backup_contains_the_database(self):
        import zipfile
        from process.portability import backup_data_dir, data_dir

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        with self.settings(DATA_DIR=tmp):
            os.environ["RAGOCR_DATA_DIR"] = tmp
            self.addCleanup(os.environ.pop, "RAGOCR_DATA_DIR", None)
            (Path(tmp) / "db.sqlite3").write_bytes(b"pretend-database")
            (Path(tmp) / "logs").mkdir()
            (Path(tmp) / "logs" / "ragocr.log").write_text("noise")

            (Path(tmp) / "media").mkdir()
            (Path(tmp) / "media" / "a.pdf").write_bytes(b"pretend-pdf")
            # In development the data dir IS the source tree, so a backup must take
            # only what it knows to be data — never everything it finds.
            (Path(tmp) / "views.py").write_text("source code, not data")

            out = os.path.join(tmp, "backup.zip")
            result = backup_data_dir(out)
            self.assertTrue(result["ok"])
            names = zipfile.ZipFile(out).namelist()
            self.assertIn("db.sqlite3", names)
            self.assertIn("media/a.pdf", names)
            self.assertNotIn("views.py", names, "a backup must not archive source")
            # Logs are noise, not something worth restoring.
            self.assertFalse([n for n in names if n.startswith("logs/")])

    def test_uploads_and_vectors_can_be_left_out(self):
        import zipfile
        from process.portability import backup_data_dir

        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.environ["RAGOCR_DATA_DIR"] = tmp
        self.addCleanup(os.environ.pop, "RAGOCR_DATA_DIR", None)
        (Path(tmp) / "db.sqlite3").write_bytes(b"pretend-database")
        (Path(tmp) / "media").mkdir()
        (Path(tmp) / "media" / "big.pdf").write_bytes(b"x" * 5000)
        (Path(tmp) / "local_chroma_db").mkdir()
        (Path(tmp) / "local_chroma_db" / "chroma.sqlite3").write_bytes(b"y" * 5000)

        out = os.path.join(tmp, "small.zip")
        backup_data_dir(out, include_media=False, include_vectors=False)
        names = zipfile.ZipFile(out).namelist()
        self.assertEqual(names, ["db.sqlite3"],
                         "the small backup keeps only what cannot be rebuilt")


# ══════════════════════════════════════════════════════════════════════════════
#  Intent parsing — one parse instead of two routers' keyword lists
# ══════════════════════════════════════════════════════════════════════════════

class IntentTests(SimpleTestCase):
    """
    Every phrasing here is one a router previously had to be taught by hand, plus the
    questions that must NOT be dragged into a comparison.
    """

    FILES = ["MRLS_MMME.pdf", "ISPL_MMME.pdf", "manual.pdf"]

    def parse(self, query, doc_count=3):
        from process.intent import parse
        return parse(query, available_files=self.FILES, doc_count=doc_count)

    # ── recognised as comparisons ────────────────────────────────────────────
    def test_the_phrasings_that_must_route_to_a_comparison(self):
        for query in [
            "compare part no between @MRLS_MMME.pdf and @ISPL_MMME.pdf",
            "difference between @MRLS_MMME.pdf and @ISPL_MMME.pdf",
            "@MRLS_MMME.pdf vs @ISPL_MMME.pdf part numbers",
            "what parts are in @MRLS_MMME.pdf but not in @ISPL_MMME.pdf",
            "which part numbers are missing from the ispl",
            "are all the part numbers in @MRLS_MMME.pdf mentioned anywhere in @manual.pdf",
            "check whether the drawing numbers are present or not in both files",
            "cross-check the nsn against all the documents",
            "reconcile part numbers across every document",
            "confirm the part numbers are found or not found in the ispl",
            "is every spare in @MRLS_MMME.pdf listed in @manual.pdf",
            "compare part no, nomenclature between @MRLS_MMME.pdf and @manual.pdf",
        ]:
            with self.subTest(query=query):
                self.assertTrue(self.parse(query).is_comparison,
                                f"should be a comparison: {self.parse(query).describe()}")

    # ── NOT comparisons ──────────────────────────────────────────────────────
    def test_ordinary_questions_are_left_to_retrieval(self):
        for query in [
            "what is XL17461",
            "summarise this document",
            "how do I replace the hydraulic seal",
            "show me the part number for the limit switch",
            "what does RESTRICTED mean on these pages",
            "list all the tables",
            "who approved revision 3",
        ]:
            with self.subTest(query=query):
                intent = self.parse(query)
                self.assertFalse(intent.is_comparison,
                                 f"should NOT be a comparison: {intent.describe()}")

    def test_a_single_document_question_is_not_a_comparison(self):
        # One file named, no comparing word: this is a lookup.
        self.assertFalse(self.parse("what is in @manual.pdf", doc_count=3).is_comparison)

    # ── the details it extracts ──────────────────────────────────────────────
    def test_it_picks_up_the_files_named(self):
        intent = self.parse("compare part between @MRLS_MMME.pdf and @ISPL_MMME.pdf")
        self.assertEqual(intent.files, ["MRLS_MMME.pdf", "ISPL_MMME.pdf"])

    def test_all_documents_expands_to_the_thread(self):
        intent = self.parse("compare part numbers across all the documents")
        self.assertTrue(intent.all_files)
        self.assertEqual(intent.files, self.FILES)

    def test_the_concept_comes_from_the_schema_vocabulary(self):
        self.assertEqual(self.parse("compare drawing numbers in both").concept_field,
                         "drawing_no")
        self.assertEqual(self.parse("compare the nsn across all files").concept_field, "nsn")
        self.assertEqual(self.parse("compare nomenclature between the two").concept_field,
                         "nomenclature")
        # A word only in field_schema — proves the router reads the schema, not a
        # list of its own.
        self.assertEqual(self.parse("compare firms part no in both files").concept_field,
                         "part_no")

    def test_part_is_the_default_when_no_concept_is_named(self):
        self.assertEqual(self.parse("compare @MRLS_MMME.pdf and @ISPL_MMME.pdf").concept_field,
                         "part_no")

    def test_a_quoted_header_is_taken_literally(self):
        intent = self.parse('compare "Firms Part No." in @a.pdf with "Part No" in @b.pdf')
        self.assertTrue(intent.prefer_literal)
        self.assertEqual(intent.columns, ("Firms Part No.", "Part No"))

    def test_mention_phrasing_selects_text_mode(self):
        self.assertEqual(
            self.parse("are the parts mentioned anywhere in @manual.pdf").mode, "mentions")
        self.assertEqual(
            self.parse("compare part no between @a.pdf and @b.pdf").mode, "columns")

    def test_the_kind_of_answer_is_read_from_the_question(self):
        self.assertEqual(self.parse("what is missing from the ispl").comparison_type,
                         "difference")
        self.assertEqual(self.parse("what is common to both files").comparison_type, "common")
        self.assertEqual(
            self.parse("confirm part numbers present or not in both").comparison_type, "all")

    def test_a_word_inside_another_word_does_not_count(self):
        # "partial" must not read as "part"; this is why matching is whole-word.
        intent = self.parse("explain the partial shipment process", doc_count=3)
        self.assertFalse(intent.is_comparison)

    def test_the_decision_can_be_explained(self):
        intent = self.parse("compare part between @MRLS_MMME.pdf and @ISPL_MMME.pdf")
        self.assertIn("comparison=True", intent.describe())
        self.assertTrue(intent.evidence)


# ══════════════════════════════════════════════════════════════════════════════
#  Reports page — must not disagree with the chat about the same documents
# ══════════════════════════════════════════════════════════════════════════════

class ReportsEngineTests(SimpleTestCase):
    """
    The Reports page compares ad-hoc uploaded files, so it cannot use the main
    engine — but it must apply the same *value* rules, or the two surfaces answer
    the same question differently.
    """

    def _pdf(self, lines):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        y = 90
        for line in lines:
            page.insert_text((60, y), line, fontsize=11)
            y += 18
        path = os.path.join(tempfile.mkdtemp(), "target.pdf")
        doc.save(path)
        doc.close()
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        return path

    def test_vocabulary_reads_identifiers_out_of_a_pdf(self):
        from process.reports_engine import _target_vocabulary
        vocab = _target_vocabulary(self._pdf(["Fit XL17461 to the bracket",
                                              "Torque NAMP-08020000 to 40 Nm"]))
        self.assertIn("XL17461", vocab)
        self.assertIn("NAMP-08020000", vocab)

    def test_a_wrapped_value_is_caught_by_the_existing_space_insensitive_search(self):
        # A value that differs only by spacing never needs the near-match tier: the
        # page search already compares a space-free form of both sides.
        from process.reports_engine import _contains_value, _normalize_for_match
        spaced, nospace = _normalize_for_match("Also 442 071 820 394 in stock")
        self.assertTrue(_contains_value(spaced, nospace, "442 071 820394"))

    def test_a_value_present_only_as_a_variant_is_reported_for_review(self):
        # The whole point: the chat calls "XL17461 NAMICA" a near-match of "XL17461",
        # and Reports used to call it missing. Containment cannot catch this one —
        # the annotated form is not a substring of the page — so it is what the
        # near-match tier is for.
        from process.field_schema import pair_likely_values
        from process.reports_engine import (_contains_value, _normalize_for_match,
                                            _target_vocabulary)
        page = "Part XL17461 fitted here"
        spaced, nospace = _normalize_for_match(page)
        self.assertFalse(_contains_value(spaced, nospace, "XL17461 NAMICA"),
                         "precondition: plain search must miss it")

        pairs = pair_likely_values({"XL17461 NAMICA"}, _target_vocabulary(self._pdf([page])))
        self.assertEqual(len(pairs), 1)
        self.assertIn("annotation", pairs[0][2])

    def test_placeholder_values_are_excluded_the_same_way(self):
        from process.field_schema import is_boilerplate_value
        values = {"XL17461", "Standard Item", "N/A", "[3]"}
        kept = {v for v in values if not is_boilerplate_value(v)}
        self.assertIn("XL17461", kept)
        self.assertNotIn("Standard Item", kept)


class ReportDownloadTests(TestCase):
    """Regression: the Reports page could not download its own report."""

    def test_a_completed_report_downloads(self):
        # The endpoint used to read a *different* module's job store — a
        # near-duplicate of reports_engine whose dict was always empty — so every
        # Reports-page download returned 404. That module has been deleted.
        from process import reports_engine
        job_id = "0000dead-0000-4000-8000-00000000beef"
        reports_engine._report_jobs[job_id] = {
            "status": "completed",
            "result": {"excel_filename": "report.xlsx"},
            "excel_bytes": b"fake-xlsx-bytes",
        }
        self.addCleanup(reports_engine._report_jobs.pop, job_id, None)

        response = self.client.get(f"/api/reports/download/{job_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-xlsx-bytes")
        self.assertIn("report.xlsx", response["Content-Disposition"])

    def test_an_unknown_report_is_a_clean_404(self):
        response = self.client.get("/api/reports/download/11110000-0000-4000-8000-000000000000/")
        self.assertEqual(response.status_code, 404)

    def test_the_duplicate_engine_module_is_gone(self):
        import importlib
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("process.reports_engine_merge")


# ══════════════════════════════════════════════════════════════════════════════
#  Extraction quality — saying out loud what could not be read
# ══════════════════════════════════════════════════════════════════════════════

class TextCoverageTests(SimpleTestCase):
    """A page with no text layer must be counted, and a scan told from a blank."""

    def _pdf(self, pages):
        """Build a PDF in a temp file: each entry is text, or None for an empty page."""
        import fitz
        doc = fitz.open()
        for text in pages:
            page = doc.new_page()
            if text:
                page.insert_text((72, 144), text, fontsize=11)
        path = os.path.join(tempfile.mkdtemp(), "probe.pdf")
        doc.save(path)
        doc.close()
        self.addCleanup(shutil.rmtree, os.path.dirname(path), ignore_errors=True)
        return path

    def test_counts_pages_with_and_without_text(self):
        from process.extraction_qa import scan_text_coverage
        path = self._pdf(["This page carries a real paragraph of text content.", None, None])
        cov = scan_text_coverage(path)
        self.assertEqual(cov["pages"], 3)
        self.assertEqual(cov["textless_pages"], 2)
        self.assertEqual(cov["textless_page_numbers"], [2, 3])

    def test_a_textless_page_with_no_image_is_blank_not_a_scan(self):
        # Only a page carrying an image is worth OCR; an empty page is just empty.
        from process.extraction_qa import scan_text_coverage
        cov = scan_text_coverage(self._pdf(["Readable text on the first page here.", None]))
        self.assertEqual(cov["scanned_pages"], 0)
        self.assertEqual(cov["blank_pages"], 1)

    def test_a_missing_file_does_not_raise(self):
        from process.extraction_qa import scan_text_coverage
        self.assertIn("error", scan_text_coverage(r"no\such\file.pdf"))


class ExtractionQaTests(FixtureMixin, TestCase):

    def setUp(self):
        self.thread, self.mrls, self.ispl = self.build_pair()

    def test_a_clean_document_produces_no_warnings(self):
        from process.extraction_qa import warnings_for
        self.assertEqual(warnings_for(self.mrls), [])

    def test_scanned_pages_are_reported(self):
        from process.extraction_qa import warnings_for
        self.mrls.extraction_stats = {"pages": 100, "textless_pages": 12,
                                      "scanned_pages": 12, "blank_pages": 0}
        self.mrls.save(update_fields=["extraction_stats"])
        warning = " ".join(warnings_for(self.mrls))
        self.assertIn("12 page", warning)
        self.assertIn("no OCR", warning)

    def test_a_document_with_no_tables_says_so(self):
        from process.extraction_qa import warnings_for
        empty = self.make_doc(self.thread, "EMPTY.pdf", "manual")
        self.assertIn("No tables were extracted", " ".join(warnings_for(empty)))

    def test_a_document_with_tables_but_no_part_column_says_so(self):
        odd = self.make_doc(self.thread, "ODD.pdf", "other")
        self.add_table(odd, ["Column_1", "Colour", "Weight"],
                       [["a", "red", "2"], ["b", "blue", "3"]])
        from process.extraction_qa import warnings_for
        self.assertIn("No part-number column", " ".join(warnings_for(odd)))

    def test_document_qa_reports_resolved_columns(self):
        from process.extraction_qa import document_qa
        qa = document_qa(self.ispl)
        self.assertTrue(qa["has_part_column"])
        self.assertEqual(qa["tables"], 1)
        self.assertEqual(qa["headerless_tables"], 0)

    def test_the_warning_reaches_the_comparison_answer(self):
        # The whole point: an unreadable document must be flagged ON the report that
        # would otherwise call everything on those pages "missing".
        self.ispl.extraction_stats = {"pages": 50, "textless_pages": 9,
                                      "scanned_pages": 9, "blank_pages": 0}
        self.ispl.save(update_fields=["extraction_stats"])
        answer = comparison.run_comparison(
            self.thread, [self.mrls, self.ispl], "part")["formatted_answer"]
        self.assertIn("Before trusting this comparison", answer)
        self.assertIn("scanned images", answer)
        self.assertIn("Matched exactly", answer, "the comparison itself must still render")

    def test_extraction_endpoint(self):
        body = self.client.get(f"/api/documents/{self.ispl.id}/extraction/").json()
        self.assertEqual(body["filename"], "ISPL_TEST.pdf")
        self.assertIn("part_no", body["resolved_concepts"])
        self.assertIn("warnings", body)


# ══════════════════════════════════════════════════════════════════════════════
#  Real corpus — skipped unless the PDFs happen to be present
# ══════════════════════════════════════════════════════════════════════════════

_PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pdfs")

_BASELINES = [
    # (label, mrls file, ispl file, common, likely, missing, extra, verified)
    #
    # verified=True  → checked by hand against the documents; a change here is a
    #                  behaviour regression.
    # verified=False → a snapshot of current behaviour, kept as a change detector.
    #                  A difference means "look at this", not necessarily "bug".
    ("NAMICA", "DT0330_U0700_NAMICA_D0_updated.pdf", "DT0330_U0521_Namica_D0_New.pdf",
     64, 7, 3, 54, True),
    ("SSBS R0", "DT0081_U0700_SSBS_10M_P3.pdf", "DT0081_U0110_SSBS_10M_R0.pdf",
     102, 9, 0, 35, True),
    # MRLS vs a *later revision* of the ISPL, so a large "missing" count is expected —
    # the two documents genuinely describe different part sets. Notable for resolving
    # the ISPL's part column to `FIRMS PART NO.`, the header that Phase 0 was built for.
    ("SSBS R3", "DT0081_U0700_SSBS_10M_P3.pdf", "DT0081_U0500_SSBS_10M_R3.pdf",
     44, 5, 64, 699, False),
]


class RealCorpusTests(TestCase):
    """
    The historical baselines, if the source PDFs are still on this machine.

    These are the numbers that were verified by hand against the real documents, so a
    change that moves them is a real behaviour change. They skip rather than fail when
    the files are absent — deleting a document in the app also deletes its PDF, which
    has already happened once during development.
    """

    def test_baselines(self):
        from process.table_search_engine import compare_pdfs
        if not os.environ.get("RAGOCR_CORPUS_TESTS"):
            self.skipTest("slow (re-extracts whole PDFs) — set RAGOCR_CORPUS_TESTS=1 to run")
        ran = 0
        for label, mrls, ispl, common, likely, missing, extra, _verified in _BASELINES:
            a, b = os.path.join(_PDF_DIR, mrls), os.path.join(_PDF_DIR, ispl)
            if not (os.path.exists(a) and os.path.exists(b)):
                continue
            with self.subTest(pair=label):
                result = compare_pdfs(a, b, "part", comparison_type="all",
                                      category1="mrls", category2="ispl",
                                      force_extract=True)
                res = result["results"]
                self.assertEqual(res["common"]["count"], common)
                self.assertEqual(res.get("likely_matches", {}).get("count", 0), likely)
                self.assertEqual(res["in_pdf1_only"]["count"], missing)
                self.assertEqual(res["in_pdf2_only"]["count"], extra)
                ran += 1
        if not ran:
            self.skipTest(f"no baseline PDFs present in {_PDF_DIR}")
