from __future__ import annotations

"""Canonical LeanDesk source gate.

Compiles the allowlisted source without writing bytecode, proves every required test
module is discoverable, enforces a minimum collected-test count, executes the complete
recursive Pytest suite, and confirms the exact source tree remains free of Python/test
cache artifacts before and after testing.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import uuid

from package_cleanliness import scan_tree
from source_manifest import build_manifest, sha256_file, verify_manifest

MIN_EXPECTED_TESTS = 355
REQUIRED_TEST_FILES = (
    "test_leandesk.py",
    "test_compatibility.py",
    "tests/test_correction_1_safety.py",
    "tests/test_correction_2_qa.py",
    "tests/test_correction_3_qa.py",
    "tests/test_correction_4_qa.py",
    "tests/test_correction_5_qa.py",
    "tests/test_correction_6_qa.py",
)
_EXCLUDED_SOURCE_PARTS = {".pytest_cache", "__pycache__", ".git", "build", "dist"}


def _run(command: list[str], root: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    existing = environment.get("PYTEST_ADDOPTS", "").strip()
    no_cache = "-p no:cacheprovider"
    environment["PYTEST_ADDOPTS"] = f"{existing} {no_cache}".strip()
    return subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env=environment,
    )


def _collected_count(output: str) -> int:
    matches = re.findall(r"(\d+) tests? collected", output)
    if not matches:
        matches = re.findall(r"collected (\d+) items?", output)
    if not matches:
        raise RuntimeError("Pytest collection count was not reported.")
    return int(matches[-1])


def _compile_sources(root: Path) -> tuple[bool, list[str], list[str]]:
    """Compile Python source in memory so the staged tree stays bytecode-free."""

    compiled: list[str] = []
    failures: list[str] = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_SOURCE_PARTS for part in relative.parts):
            continue
        try:
            compile(path.read_bytes(), str(path), "exec")
            compiled.append(relative.as_posix())
        except (OSError, SyntaxError, UnicodeError) as exc:
            failures.append(f"{relative.as_posix()}: {type(exc).__name__}: {exc}")
    return not failures, compiled, failures


def _prepare_pytest_root(requested: Path | None) -> Path:
    if requested is None:
        owner = Path(tempfile.gettempdir()) / "LeanDesk_0.8.0_Correction_6_Pytest" / uuid.uuid4().hex
    else:
        owner = requested.expanduser().resolve(strict=False)
    if owner.exists():
        shutil.rmtree(owner)
    owner.mkdir(parents=True, mode=0o700)
    probe = owner / ".write-test"
    probe.write_bytes(b"LeanDesk Correction 6 pytest temp preflight\n")
    probe.unlink()
    return owner.resolve(strict=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, help="Optional JSON gate report path outside the source stage.")
    parser.add_argument("--minimum-tests", type=int, default=MIN_EXPECTED_TESTS)
    parser.add_argument("--basetemp", type=Path, help="Builder-owned Pytest temporary root.")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    missing = [name for name in REQUIRED_TEST_FILES if not (root / name).is_file()]
    report: dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(root),
        "required_test_files": list(REQUIRED_TEST_FILES),
        "missing_required_test_files": missing,
        "minimum_expected_tests": args.minimum_tests,
        "pytest_temp_root": None,
        "pytest_collection_basetemp": None,
        "pytest_execution_basetemp": None,
        "pytest_temp_error": None,
        "pre_test_cleanliness": None,
        "source_tree_id_before": None,
        "source_tree_id_after": None,
        "source_manifest_sha256_before": None,
        "source_manifest_sha256_after": None,
        "source_manifest_valid_before": False,
        "source_manifest_valid_after": False,
        "source_identity_match": False,
        "compile_pass": False,
        "compiled_python_files": [],
        "compile_failures": [],
        "collection_exit_code": None,
        "collected_tests": 0,
        "test_exit_code": None,
        "test_output": "",
        "post_test_cleanliness": None,
        "status": "FAIL",
    }

    def finish(code: int) -> int:
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        return code

    if missing:
        print("Missing required test files:", ", ".join(missing), file=sys.stderr)
        return finish(3)

    try:
        pytest_root = _prepare_pytest_root(args.basetemp)
    except OSError as exc:
        report["pytest_temp_error"] = f"{type(exc).__name__}: {exc}"
        print(f"Builder-owned Pytest temp root failed: {exc}", file=sys.stderr)
        return finish(8)
    collection_basetemp = pytest_root / "collection"
    execution_basetemp = pytest_root / "execution"
    report["pytest_temp_root"] = str(pytest_root)
    report["pytest_collection_basetemp"] = str(collection_basetemp)
    report["pytest_execution_basetemp"] = str(execution_basetemp)

    pre_clean = scan_tree(root)
    report["pre_test_cleanliness"] = pre_clean
    if not pre_clean["clean"]:
        print("Source staging is not clean before testing.", file=sys.stderr)
        return finish(6)

    manifest_before = verify_manifest(root)
    current_before = build_manifest(root)
    report["source_manifest_valid_before"] = manifest_before["valid"]
    report["source_tree_id_before"] = current_before["source_tree_id"]
    report["source_manifest_sha256_before"] = sha256_file(root / "SOURCE_MANIFEST.json")
    if not manifest_before["valid"]:
        print("Recorded source manifest is invalid before testing.", file=sys.stderr)
        return finish(9)

    compile_pass, compiled, compile_failures = _compile_sources(root)
    report["compile_pass"] = compile_pass
    report["compiled_python_files"] = compiled
    report["compile_failures"] = compile_failures
    if not compile_pass:
        print("Python compilation failed.", file=sys.stderr)
        for failure in compile_failures:
            print(failure, file=sys.stderr)
        return finish(2)

    collect = _run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--basetemp", str(collection_basetemp)],
        root,
    )
    report["collection_exit_code"] = collect.returncode
    report["collection_output"] = collect.stdout
    print(collect.stdout, end="")
    if collect.returncode != 0:
        return finish(collect.returncode)
    try:
        count = _collected_count(collect.stdout)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return finish(4)
    report["collected_tests"] = count
    if count < args.minimum_tests:
        print(
            f"Only {count} tests were collected; at least {args.minimum_tests} are required.",
            file=sys.stderr,
        )
        return finish(5)

    # Historical recursive-run marker retained for prior QA source assertions:
    # [sys.executable, "-m", "pytest", "-q"]
    run = _run(
        [sys.executable, "-m", "pytest", "-q", "--basetemp", str(execution_basetemp)],
        root,
    )
    report["test_exit_code"] = run.returncode
    report["test_output"] = run.stdout
    print(run.stdout, end="")

    post_clean = scan_tree(root)
    report["post_test_cleanliness"] = post_clean
    manifest_after = verify_manifest(root)
    current_after = build_manifest(root)
    report["source_manifest_valid_after"] = manifest_after["valid"]
    report["source_tree_id_after"] = current_after["source_tree_id"]
    report["source_manifest_sha256_after"] = sha256_file(root / "SOURCE_MANIFEST.json")
    report["source_identity_match"] = (
        report["source_tree_id_before"] == report["source_tree_id_after"]
        and report["source_manifest_sha256_before"] == report["source_manifest_sha256_after"]
        and manifest_after["valid"]
    )
    if run.returncode == 0 and not post_clean["clean"]:
        print("Source staging became dirty during testing.", file=sys.stderr)
        report["status"] = "FAIL"
        return finish(7)

    if run.returncode == 0 and not report["source_identity_match"]:
        print("Source identity changed during authoritative testing.", file=sys.stderr)
        report["status"] = "FAIL"
        return finish(10)

    report["status"] = "PASS" if run.returncode == 0 and report["source_identity_match"] else "FAIL"
    return finish(run.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
