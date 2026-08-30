from __future__ import annotations

"""Mandatory Windows and fail-closed regressions for Correction 6."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import zipfile

from leandesk.backup_integrity import ensure_zip_manifest, sha256_file, verify_backup_artifact
from leandesk.backup_service import create_backup, restore_backup
from tools.source_manifest import build_manifest, sha256_file as source_sha256_file, verify_manifest

ROOT = Path(__file__).resolve().parents[1]


def _profile(path: Path, marker: str) -> Path:
    path.mkdir(parents=True)
    (path / "state.txt").write_text(marker, encoding="utf-8")
    return path


def _write_capable_fsync(real_fsync, observed: list[int]):
    def checked(descriptor: int) -> None:
        assert os.write(descriptor, b"") == 0
        observed.append(descriptor)
        real_fsync(descriptor)

    return checked


def test_windows_manifest_flush_uses_write_capable_descriptor(tmp_path: Path) -> None:
    archive = tmp_path / "manifest.ldbackup"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("settings.json", '{"ok":true}')
    observed: list[int] = []
    with patch(
        "leandesk.backup_integrity.os.fsync",
        side_effect=_write_capable_fsync(os.fsync, observed),
    ):
        ensure_zip_manifest(archive)
    assert observed
    assert verify_backup_artifact(archive, require_manifest=True)["valid"] is True


def test_windows_transactional_backup_replace_verify_and_restore(tmp_path: Path) -> None:
    destination = tmp_path / "profile.ldbackup"
    create_backup(destination, data_root=_profile(tmp_path / "old-source", "OLD"))
    old_sha = sha256_file(destination)
    result = create_backup(destination, data_root=_profile(tmp_path / "new-source", "NEW"))
    assert result["committed"] is True
    assert result["sha256"] == sha256_file(destination)
    assert result["sha256"] != old_sha
    assert verify_backup_artifact(destination, require_manifest=True)["valid"] is True

    live = _profile(tmp_path / "live", "LIVE")
    restored = restore_backup(destination, data_root=live)
    assert restored["committed"] is True
    assert (live / "state.txt").read_text(encoding="utf-8") == "NEW"


def test_windows_backup_service_flushes_are_write_capable(tmp_path: Path) -> None:
    observed: list[int] = []
    with patch(
        "leandesk.backup_service.os.fsync",
        side_effect=_write_capable_fsync(os.fsync, observed),
    ):
        destination = tmp_path / "profile.ldbackup"
        create_backup(destination, data_root=_profile(tmp_path / "source", "SAFE"))
        restore_backup(destination, data_root=_profile(tmp_path / "live", "OLD"))
    assert observed


def test_authoritative_runner_owns_and_records_isolated_basetemp() -> None:
    source = (ROOT / "tools" / "run_authoritative_tests.py").read_text(encoding="utf-8")
    assert "--basetemp" in source
    assert "pytest_temp_root" in source
    assert "pytest_collection_basetemp" in source
    assert "pytest_execution_basetemp" in source
    assert "shutil.rmtree(owner)" in source
    assert '"tests/test_correction_6_qa.py"' in source


def test_failed_gate_cannot_create_packaging_authorization(tmp_path: Path) -> None:
    source_id = (ROOT / "SOURCE_TREE_ID.txt").read_text(encoding="ascii").strip()
    manifest_sha = source_sha256_file(ROOT / "SOURCE_MANIFEST.json")
    failed_report = tmp_path / "FAILED_GATE.json"
    failed_report.write_text(
        json.dumps(
            {
                "collection_exit_code": 0,
                "compile_pass": True,
                "compile_failures": [],
                "test_exit_code": 1,
                "status": "FAIL",
                "minimum_expected_tests": 355,
                "collected_tests": 355,
                "missing_required_test_files": [],
                "required_test_files": ["tests/test_correction_6_qa.py"],
                "pytest_temp_root": str(tmp_path / "owned-temp"),
                "pytest_temp_error": None,
                "source_identity_match": True,
                "source_tree_id_before": source_id,
                "source_tree_id_after": source_id,
                "source_manifest_sha256_before": manifest_sha,
                "source_manifest_sha256_after": manifest_sha,
            }
        ),
        encoding="utf-8",
    )
    shipping = tmp_path / "shipping"
    authorization = shipping / "BUILD_GATE_AUTHORIZATION.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_build_gate.py"),
            "--report",
            str(failed_report),
            "--source-root",
            str(ROOT),
            "--expected-source-id",
            source_id,
            "--expected-manifest-sha256",
            manifest_sha,
            "--authorization",
            str(authorization),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not authorization.exists()
    assert not shipping.exists() or not list(shipping.rglob("*.exe"))
    assert not shipping.exists() or not list(shipping.rglob("*.zip"))


def test_builder_validates_gate_and_identity_before_packaging() -> None:
    source = (ROOT / "BUILD_LEANDESK_SUITE.ps1").read_text(encoding="utf-8-sig")
    validator = source.index("validate_build_gate.py")
    pyinstaller = source.index("-m PyInstaller")
    inno = source.index("Build installer")
    assert validator < pyinstaller < inno
    assert "AcceptedSourceTreeId" in source
    assert "GateAuthorization" in source
    assert "Require-File $GateAuthorization" in source
    assert "BUILD_PROVENANCE.json" in source


def test_shipping_manifest_is_recursive_and_excludes_only_itself() -> None:
    source = (ROOT / "BUILD_LEANDESK_SUITE.ps1").read_text(encoding="utf-8-sig")
    checksum_section = source[source.index('Write-Step "Create complete shipping checksums"'):]
    assert "Get-ChildItem $ReleaseRoot -File -Recurse" in checksum_section
    assert "GetRelativePath" in checksum_section
    assert 'SHA256SUMS.txt' in checksum_section


def test_correction_6_source_manifest_is_current_and_deterministic() -> None:
    result = verify_manifest(ROOT)
    manifest = build_manifest(ROOT)
    assert result["valid"], result["errors"]
    assert manifest["candidate"] == "0.8.1-hotfix"
    assert manifest["source_tree_id"] == (ROOT / "SOURCE_TREE_ID.txt").read_text(encoding="ascii").strip()
