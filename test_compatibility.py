from pathlib import Path
import unittest

from leandesk.compatibility import (
    module_for_suffix, WRITER_COMPAT, SHEETS_COMPAT, SLIDES_COMPAT,
    registered_extensions,
)

class CompatibilityRoutingTests(unittest.TestCase):
    def test_writer_routing(self):
        for ext in (".docx", ".doc", ".odt", ".rtf", ".wpd", ".pages"):
            self.assertEqual(module_for_suffix(ext), "Writer")

    def test_sheets_routing(self):
        for ext in (".xlsx", ".xls", ".ods", ".csv", ".numbers"):
            self.assertEqual(module_for_suffix(ext), "Sheets")

    def test_slides_routing(self):
        for ext in (".pptx", ".ppt", ".odp", ".key"):
            self.assertEqual(module_for_suffix(ext), "Slides")

    def test_macro_formats_are_compatibility_only(self):
        self.assertIn(".docm", WRITER_COMPAT)
        self.assertIn(".xlsm", SHEETS_COMPAT)
        self.assertIn(".pptm", SLIDES_COMPAT)

    def test_registry_lists_major_formats(self):
        formats = registered_extensions()
        self.assertIn(".docx", formats["Writer"])
        self.assertIn(".odt", formats["Writer"])
        self.assertIn(".xlsx", formats["Sheets"])
        self.assertIn(".ods", formats["Sheets"])
        self.assertIn(".pptx", formats["Slides"])
        self.assertIn(".odp", formats["Slides"])

    def test_installer_registers_open_with_without_foreign_default_hijack(self):
        iss = (Path(__file__).parent / "LeanDesk_Suite_Installer.iss").read_text(encoding="utf-8")
        formats = registered_extensions()
        native = {".ldoc", ".lsheet", ".ldeck", ".ldraw"}
        for module, extensions in formats.items():
            progid = f"LeanDesk.{module}"
            for extension in extensions:
                capability = (
                    rf'Subkey: "Software\Dietrich AI Labs\LeanDesk Suite\Capabilities\FileAssociations"; '
                    rf'ValueType: string; ValueName: "{extension}"; ValueData: "{progid}"'
                )
                self.assertIn(capability, iss, extension)
                if extension in native:
                    default = (
                        rf'Subkey: "Software\Classes\{extension}"; ValueType: string; '
                        rf'ValueData: "{progid}"'
                    )
                    self.assertIn(default, iss, extension)
                else:
                    self.assertIn(rf"Software\Classes\{extension}\OpenWithProgids", iss, extension)
                    foreign_default = (
                        rf'Subkey: "Software\Classes\{extension}"; ValueType: string; '
                        rf'ValueData: "{progid}"'
                    )
                    self.assertNotIn(foreign_default, iss, extension)
        self.assertIn(r"Software\RegisteredApplications", iss)

    def test_startup_routing_uses_shared_registry(self):
        app = (Path(__file__).parent / "leandesk" / "app.py").read_text(encoding="utf-8")
        self.assertIn("return module_for_suffix(path.suffix)", app)

if __name__ == "__main__":
    unittest.main()
