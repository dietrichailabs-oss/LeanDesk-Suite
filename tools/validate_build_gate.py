from __future__ import annotations

"""Fail-closed authorization boundary between source QA and packaging."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from source_manifest import sha256_file, verify_manifest

REQUIRED_REGRESSION_TEST = "tests/test_correction_6_qa.py"


def validate_gate(
    report_path: Path,
    source_root: Path,
    expected_source_id: str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    errors: list[str] = []
    expected_source_id = expected_source_id.upper()
    expected_manifest_sha256 = expected_manifest_sha256.upper()
    if not re.fullmatch(r"[A-F0-9]{64}", expected_source_id):
        errors.append("accepted source-tree ID is malformed")
    if not re.fullmatch(r"[A-F0-9]{64}", expected_manifest_sha256):
        errors.append("source manifest SHA-256 is malformed")

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"authorized": False, "errors": [f"gate report unreadable: {type(exc).__name__}"]}

    required_files = report.get("required_test_files")
    minimum = report.get("minimum_expected_tests")
    collected = report.get("collected_tests")
    checks = (
        (report.get("collection_exit_code") == 0, "collection did not pass"),
        (report.get("compile_pass") is True, "source compilation did not pass"),
        (not report.get("compile_failures"), "source compilation recorded failures"),
        (report.get("test_exit_code") == 0, "test exit code is nonzero"),
        (report.get("status") == "PASS", "gate status is not PASS"),
        (isinstance(minimum, int) and isinstance(collected, int) and collected >= minimum, "too few tests collected"),
        (not report.get("missing_required_test_files"), "required test files are missing"),
        (isinstance(required_files, list) and REQUIRED_REGRESSION_TEST in required_files, "Correction 6 regression is not mandatory"),
        (bool(report.get("pytest_temp_root")), "builder-owned Pytest temp root is missing"),
        (report.get("pytest_temp_error") in (None, ""), "Pytest temp-root preflight failed"),
        (report.get("source_identity_match") is True, "pre/post test source identity differs"),
        (report.get("source_tree_id_before") == expected_source_id, "pre-test source-tree ID mismatch"),
        (report.get("source_tree_id_after") == expected_source_id, "post-test source-tree ID mismatch"),
        (report.get("source_manifest_sha256_before") == expected_manifest_sha256, "pre-test source manifest SHA-256 mismatch"),
        (report.get("source_manifest_sha256_after") == expected_manifest_sha256, "post-test source manifest SHA-256 mismatch"),
    )
    errors.extend(message for passed, message in checks if not passed)

    manifest_result = verify_manifest(source_root)
    if not manifest_result["valid"]:
        errors.append("current source manifest verification failed")
    if manifest_result["source_tree_id"] != expected_source_id:
        errors.append("current source-tree ID mismatch")
    manifest_path = source_root / "SOURCE_MANIFEST.json"
    if not manifest_path.is_file() or sha256_file(manifest_path) != expected_manifest_sha256:
        errors.append("current source manifest SHA-256 mismatch")

    return {
        "authorized": not errors,
        "errors": errors,
        "accepted_source_tree_id": expected_source_id,
        "source_manifest_sha256": expected_manifest_sha256,
        "authoritative_test_gate_sha256": sha256_file(report_path),
        "collected_tests": collected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-source-id", required=True)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    args = parser.parse_args()

    args.authorization.unlink(missing_ok=True)
    result = validate_gate(
        args.report.resolve(),
        args.source_root.resolve(),
        args.expected_source_id,
        args.expected_manifest_sha256,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if not result["authorized"]:
        return 1
    authorization = dict(result)
    authorization["generated_utc"] = datetime.now(timezone.utc).isoformat()
    args.authorization.parent.mkdir(parents=True, exist_ok=True)
    args.authorization.write_text(json.dumps(authorization, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
