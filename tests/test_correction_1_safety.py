from __future__ import annotations
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from leandesk.backup_integrity import BackupIntegrityError, ensure_zip_manifest, verify_backup_artifact
from leandesk.import_safety import ImportedSourceProtectionError, install_save_guards
from leandesk.update_checker import check_for_updates

class FakeResponse:
    def __init__(self, body: bytes):
        self._body = io.BytesIO(body)
        self.headers = {"Content-Length": str(len(body))}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self, n=-1): return self._body.read(n)

class CorrectionTests(unittest.TestCase):
    def test_update_check_is_weekly_and_fixed_product(self):
        calls=[]
        body=json.dumps({"product":"leandesk-suite","latest_version":"0.8.1","release_name":"LeanDesk Suite 0.8.1","published_at":"2026-08-23T00:00:00Z","release_url":"https://www.dietrichailabs.com/apps/leandesk/","download_url":"https://www.dietrichailabs.com/downloads/","sha256":"","message":"Update available"}).encode()
        def opener(req, timeout):
            calls.append(req.full_url); return FakeResponse(body)
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)/"state.json"
            now=datetime(2026,8,23,tzinfo=timezone.utc)
            first=check_for_updates("0.8.0", opener=opener, state_path=state, now=now)
            second=check_for_updates("0.8.0", opener=opener, state_path=state, now=now)
            self.assertEqual(first.status,"update_available")
            self.assertEqual(second.status,"not_due")
            self.assertEqual(calls,["https://www.dietrichailabs.com/updates/leandesk.json"])
    def test_backup_manifest_detects_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"backup.zip"
            with zipfile.ZipFile(p,"w") as z: z.writestr("settings.json",'{"ok":true}')
            ensure_zip_manifest(p)
            self.assertFalse(verify_backup_artifact(p,require_manifest=True)["legacy"])
            with zipfile.ZipFile(p,"a") as z: z.writestr("settings.json",'{"ok":false}')
            with self.assertRaises(BackupIntegrityError): verify_backup_artifact(p,require_manifest=True)
    def test_backup_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"bad.zip"
            with zipfile.ZipFile(p,"w") as z: z.writestr("../escape.json",'{}')
            with self.assertRaises(BackupIntegrityError): verify_backup_artifact(p)
    def test_imported_foreign_source_requires_save_as(self):
        class Editor:
            def __init__(self): self.current_file="example.docx"
            def save(self): return "bad"
            def save_as(self,path): return path
        install_save_guards(locals())
        e=Editor()
        with self.assertRaises(ImportedSourceProtectionError): e.save()
        self.assertEqual(e.save_as("copy.ldoc"),"copy.ldoc")

if __name__ == "__main__": unittest.main()
