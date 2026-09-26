from __future__ import annotations

"""Exact staging-tree cleanliness gate for LeanDesk source handoffs."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
from typing import Any

FORBIDDEN_DIRECTORY_NAMES = {".pytest_cache", "__pycache__"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo"}


def scan_tree(root: os.PathLike[str] | str) -> dict[str, Any]:
    candidate = Path(root)
    issues: list[dict[str, str]] = []
    files = 0
    directories = 0

    try:
        root_info = candidate.lstat()
    except OSError as exc:
        return {
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "root": str(candidate),
            "clean": False,
            "files": 0,
            "directories": 0,
            "issues": [{"path": ".", "reason": f"root unavailable: {type(exc).__name__}"}],
        }
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        issues.append({"path": ".", "reason": "staging root is linked or not a directory"})

    for current, dirnames, filenames in os.walk(candidate, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(dirnames):
            path = current_path / name
            rel = path.relative_to(candidate).as_posix()
            try:
                info = path.lstat()
            except OSError as exc:
                issues.append({"path": rel, "reason": f"directory unavailable: {type(exc).__name__}"})
                continue
            directories += 1
            if stat.S_ISLNK(info.st_mode):
                issues.append({"path": rel, "reason": "symbolic-link directory"})
                continue
            attrs = getattr(info, "st_file_attributes", 0)
            if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                issues.append({"path": rel, "reason": "reparse-point directory"})
                continue
            if name in FORBIDDEN_DIRECTORY_NAMES:
                issues.append({"path": rel, "reason": "forbidden Python/test cache directory"})
                continue
            kept.append(name)
        dirnames[:] = kept

        for name in sorted(filenames):
            path = current_path / name
            rel = path.relative_to(candidate).as_posix()
            files += 1
            try:
                info = path.lstat()
            except OSError as exc:
                issues.append({"path": rel, "reason": f"file unavailable: {type(exc).__name__}"})
                continue
            if stat.S_ISLNK(info.st_mode):
                issues.append({"path": rel, "reason": "symbolic-link file"})
            attrs = getattr(info, "st_file_attributes", 0)
            if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                issues.append({"path": rel, "reason": "reparse-point file"})
            if path.suffix.casefold() in FORBIDDEN_SUFFIXES:
                issues.append({"path": rel, "reason": "compiled Python artifact"})

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(candidate.resolve(strict=False)),
        "clean": not issues,
        "files": files,
        "directories": directories,
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = scan_tree(args.root)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
