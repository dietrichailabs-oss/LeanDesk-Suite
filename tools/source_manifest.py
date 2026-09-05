from __future__ import annotations

"""Generate and verify LeanDesk's deterministic source-tree identity."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

EXCLUDED_IDENTITY_FILES = {"SOURCE_MANIFEST.json", "SOURCE_TREE_ID.txt"}
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", ".git", "build", "dist", "release"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def source_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda value: value.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.as_posix() in EXCLUDED_IDENTITY_FILES:
            continue
        if any(part.casefold() in EXCLUDED_PARTS for part in relative.parts) or path.suffix in EXCLUDED_SUFFIXES:
            continue
        rows.append(
            {
                "path": relative.as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def tree_identity(rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest().upper()


def build_manifest(root: Path) -> dict[str, Any]:
    rows = source_rows(root)
    identity = tree_identity(rows)
    return {
        "schema": 2,
        "candidate": "0.9.0-office-completion",
        "classification": "ENGINEERING_SOURCE_QA_CANDIDATE_NOT_RELEASE_APPROVED",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_tree_id": identity,
        "identity_algorithm": (
            "SHA-256 of UTF-8 canonical JSON for the sorted files array using "
            "sort_keys=True and separators=(comma,colon); SOURCE_MANIFEST.json and "
            "SOURCE_TREE_ID.txt are intentionally excluded from the files array."
        ),
        "excluded_identity_files": sorted(EXCLUDED_IDENTITY_FILES),
        "file_count": len(rows),
        "total_bytes": sum(row["size"] for row in rows),
        "files": rows,
    }


def write_manifest(root: Path) -> dict[str, Any]:
    manifest = build_manifest(root)
    (root / "SOURCE_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (root / "SOURCE_TREE_ID.txt").write_text(manifest["source_tree_id"] + "\n", encoding="ascii")
    return manifest


def verify_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "SOURCE_MANIFEST.json"
    tree_path = root / "SOURCE_TREE_ID.txt"
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = build_manifest(root)
    errors: list[str] = []
    if recorded.get("files") != current["files"]:
        errors.append("source file rows differ")
    if recorded.get("source_tree_id") != current["source_tree_id"]:
        errors.append("source tree identity differs")
    if tree_path.read_text(encoding="ascii").strip() != current["source_tree_id"]:
        errors.append("SOURCE_TREE_ID.txt differs")
    return {
        "valid": not errors,
        "errors": errors,
        "source_tree_id": current["source_tree_id"],
        "file_count": current["file_count"],
        "total_bytes": current["total_bytes"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    result = verify_manifest(root) if args.verify else write_manifest(root)
    print(json.dumps(result, indent=2))
    return 0 if not args.verify or result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
