from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from leandesk.core import AppSettings, RecentFiles, RecoveryRecord, RecoveryStore
from leandesk.document_formats import LeanDocument, TagRange, html_to_plain, load_native, plain_to_html, plain_to_rtf, save_native
from leandesk.draw import Drawing, Shape
from leandesk.sheets import SheetModel, WorkbookModel, column_index, column_name, iter_range, safe_number_expression
from leandesk.slides import DeckModel, SlideModel
from leandesk.spellcheck import SpellService, unique_misspelled_words


class CoreTests(unittest.TestCase):
    def test_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            source = AppSettings(theme="Test", autosave_seconds=45, default_zoom=125, live_spellcheck=False)
            source.save(path)
            loaded = AppSettings.load(path)
            self.assertEqual(loaded.theme, "Test")
            self.assertEqual(loaded.autosave_seconds, 45)
            self.assertEqual(loaded.default_zoom, 125)
            self.assertFalse(loaded.live_spellcheck)

    def test_recent_files_deduplicate_and_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            recent = RecentFiles(base / "recent.json", limit=2)
            files = []
            for index in range(3):
                path = base / f"{index}.txt"
                path.write_text(str(index), encoding="utf-8")
                files.append(path)
                recent.add(path, "Writer")
            recent.add(files[-1], "Writer")
            self.assertEqual(len(recent.entries), 2)
            self.assertEqual(Path(recent.entries[0].path), files[-1].resolve())

    def test_remove_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "gone.txt"
            path.write_text("x", encoding="utf-8")
            recent = RecentFiles(Path(temp) / "recent.json")
            recent.add(path)
            path.unlink()
            self.assertEqual(recent.remove_missing(), 1)
            self.assertEqual(recent.entries, [])

    def test_recovery_filter(self):
        with tempfile.TemporaryDirectory() as temp:
            store = RecoveryStore(Path(temp))
            store.save(RecoveryRecord("a", "Writer", "A", "", "2026-01-01T00:00:00", {"text": "a"}))
            store.save(RecoveryRecord("b", "Sheets", "B", "", "2026-01-02T00:00:00", {"text": "b"}))
            self.assertEqual(len(store.list()), 2)
            self.assertEqual([row.recovery_id for row in store.list("Writer")], ["a"])
            store.delete("a")
            self.assertEqual(len(store.list()), 1)


class DocumentFormatTests(unittest.TestCase):
    def test_native_round_trip(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "doc.ldoc"
            source = LeanDocument("Demo", "Hello", [TagRange("fmt_bold", "1.0", "1.5")])
            save_native(source, path)
            loaded = load_native(path)
            self.assertEqual(loaded.title, "Demo")
            self.assertEqual(loaded.text, "Hello")
            self.assertEqual(loaded.tags[0].tag, "fmt_bold")

    def test_html_escape_and_extract(self):
        rendered = plain_to_html("One < Two\n\nSecond line", "Test & Demo")
        self.assertIn("One &lt; Two", rendered)
        self.assertIn("Test &amp; Demo", rendered)
        extracted = html_to_plain(rendered)
        self.assertIn("One < Two", extracted)
        self.assertIn("Second line", extracted)

    def test_rtf_escape(self):
        rendered = plain_to_rtf("A {test} \\ path\nNext")
        self.assertIn(r"\{test\}", rendered)
        self.assertIn(r"\\ path", rendered)
        self.assertIn(r"\par", rendered)


class SpellCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = SpellService(Path(self.temp.name) / "personal.json")

    def tearDown(self):
        self.temp.cleanup()

    def test_extensive_bundled_dictionary_loaded(self):
        self.assertGreater(self.service.dictionary_size, 100000)
        self.assertTrue(self.service.is_correct("elephant"))
        self.assertTrue(self.service.is_correct("productivity"))

    def test_misspelling_and_suggestion(self):
        self.assertFalse(self.service.is_correct("documant"))
        suggestions = self.service.suggestions("documant")
        self.assertIn("document", suggestions)
        rows = self.service.misspellings("This documant has a spelngg.")
        words = {row.word.lower() for row in rows}
        self.assertIn("documant", words)
        self.assertIn("spelngg", words)

    def test_personal_dictionary(self):
        self.assertFalse(self.service.is_correct("nyxgpt"))
        self.service.add_personal("NyxGPT")
        self.assertTrue(self.service.is_correct("nyxgpt"))
        reloaded = SpellService(Path(self.temp.name) / "personal.json")
        self.assertTrue(reloaded.is_correct("nyxgpt"))

    def test_unique_words(self):
        words = unique_misspelled_words("documant documant eror", self.service)
        self.assertEqual([word.lower() for word in words], ["documant", "eror"])


class SheetsTests(unittest.TestCase):
    def test_column_conversion(self):
        for index in (0, 25, 26, 51, 701):
            self.assertEqual(column_index(column_name(index)), index)

    def test_range_iteration(self):
        self.assertEqual(list(iter_range("A1", "B2")), ["A1", "B1", "A2", "B2"])

    def test_safe_math(self):
        self.assertEqual(safe_number_expression("2+3*4"), 14)
        with self.assertRaises(ValueError):
            safe_number_expression("__import__('os')")

    def test_formulas(self):
        sheet = SheetModel()
        sheet.set("A1", "2")
        sheet.set("A2", "3")
        sheet.set("B1", "=A1*A2")
        sheet.set("B2", "=SUM(A1:A2)")
        sheet.set("B3", "=AVERAGE(A1:A2)")
        self.assertEqual(sheet.value("B1"), 6)
        self.assertEqual(sheet.value("B2"), 5)
        self.assertEqual(sheet.value("B3"), 2.5)

    def test_cycle(self):
        sheet = SheetModel()
        sheet.set("A1", "=A2")
        sheet.set("A2", "=A1")
        self.assertIn(sheet.value("A1"), ("#ERROR!", "#CYCLE!"))

    def test_workbook_round_trip(self):
        source = WorkbookModel("Budget", [SheetModel("Data", {"A1": "10"})])
        loaded = WorkbookModel.from_dict(asdict(source))
        self.assertEqual(loaded.title, "Budget")
        self.assertEqual(loaded.sheets[0].raw("A1"), "10")


class SlidesAndDrawTests(unittest.TestCase):
    def test_deck_round_trip(self):
        source = DeckModel("Demo", [SlideModel("Title", "Body", "Ocean", "notes")])
        loaded = DeckModel.from_dict(asdict(source))
        self.assertEqual(loaded.slides[0].theme, "Ocean")
        self.assertEqual(loaded.slides[0].notes, "notes")

    def test_drawing_round_trip(self):
        source = Drawing("Demo", shapes=[Shape("1", "rectangle", 1, 2, 30, 40)])
        loaded = Drawing.from_dict(asdict(source))
        self.assertEqual(loaded.shapes[0].kind, "rectangle")
        self.assertEqual(loaded.width, 1200)

    def test_draw_svg_source_has_export(self):
        root = Path(__file__).resolve().parent
        source = (root / "leandesk" / "draw.py").read_text(encoding="utf-8")
        self.assertIn("def to_svg", source)
        self.assertIn("def export_png", source)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent

    def test_expected_modules(self):
        expected = [
            "writer.py", "spellcheck.py", "sheets.py", "slides.py", "notes.py",
            "draw.py", "organizer.py", "app.py", "ui.py",
        ]
        for name in expected:
            self.assertTrue((self.root / "leandesk" / name).is_file(), name)

    def test_expected_release_files(self):
        expected = [
            "lean_desk_suite.py", "make_artwork.py", "README.md", "EULA.txt",
            "LeanDesk_Suite_Installer.iss", "BUILD_LEANDESK_SUITE.bat",
            "BUILD_LEANDESK_SUITE.ps1", "version_info.txt", "ROADMAP.md",
        ]
        for name in expected:
            self.assertTrue((self.root / name).is_file(), name)

    def test_dictionary_is_large(self):
        path = self.root / "assets" / "english_words.txt"
        self.assertTrue(path.is_file())
        self.assertGreater(len(path.read_text(encoding="utf-8").splitlines()), 100000)

    def test_readme_lists_all_modules(self):
        text = (self.root / "README.md").read_text(encoding="utf-8")
        for name in ("Writer", "Sheets", "Slides", "Notes", "Draw", "Tasks", "Calendar", "Contacts"):
            self.assertIn(name, text)

    def test_artwork_dimensions(self):
        from PIL import Image
        with Image.open(self.root / "assets" / "leandesk-suite-banner.png") as image:
            self.assertEqual(image.size, (1400, 360))
        with Image.open(self.root / "assets" / "leandesk-suite-social-preview.png") as image:
            self.assertEqual(image.size, (1280, 640))

    def test_installer_model(self):
        text = (self.root / "LeanDesk_Suite_Installer.iss").read_text(encoding="utf-8")
        self.assertIn("LicenseFile=EULA.txt", text)
        self.assertIn("UninstallDisplayIcon", text)
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn('Name: "associations"', text)
        for extension in (".ldoc", ".lsheet", ".ldeck", ".ldraw"):
            self.assertIn(extension, text)

    def test_writer_clean_ribbon_and_spellcheck(self):
        source = (self.root / "leandesk" / "writer.py").read_text(encoding="utf-8")
        for tab in ("Home", "Insert", "Layout", "Review", "View", "Help"):
            self.assertIn(f'"{tab}"', source)
        for group in ("Clipboard", "Font", "Paragraph", "Styles", "Editing", "Proofing"):
            self.assertIn(f'"{group}"', source)
        self.assertIn("Live spell check", source)
        self.assertIn("Check Document", source)
        self.assertIn("Personal Dictionary", source)
        self.assertNotIn("Spell checking and comments are planned", source)
        self.assertNotIn("Tables, images, headers, footers", source)

    def test_build_collects_dependencies_and_assets(self):
        source = (self.root / "BUILD_LEANDESK_SUITE.ps1").read_text(encoding="utf-8")
        for value in ("openpyxl", "pptx", "spellchecker", 'assets;assets'):
            self.assertIn(value, source)


if __name__ == "__main__":
    unittest.main()
