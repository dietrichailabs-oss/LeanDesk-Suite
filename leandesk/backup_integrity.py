from __future__ import annotations

"""Bounded integrity validation for LeanDesk profile backups.

All archive members are streamed through temporary files before semantic validation.
No member is extracted into the live profile by this module.
"""

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile
from typing import Any, BinaryIO, Iterable
import zipfile

from .data_boundary import DataBoundaryError, strict_json_load_bytes

MANIFEST_NAME = "LEANDESK_BACKUP_MANIFEST.json"
BACKUP_SCHEMA = 1
MAX_FILES = 4_096
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_NESTED_FILES = 1_024
MAX_NESTED_TOTAL_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 250
_COPY_CHUNK = 1024 * 1024
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class BackupIntegrityError(RuntimeError):
    pass


def _is_reparse(path: Path) -> bool:
    try:
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _sha256_stream(fp: BinaryIO) -> str:
    digest = hashlib.sha256()
    for block in iter(lambda: fp.read(_COPY_CHUNK), b""):
        digest.update(block)
    return digest.hexdigest().upper()


def sha256_file(path: os.PathLike[str] | str) -> str:
    with Path(path).open("rb") as handle:
        return _sha256_stream(handle)


def _validate_component(component: str) -> None:
    if component in {"", ".", ".."}:
        raise BackupIntegrityError("backup member contains an empty or relative path component")
    if component[-1:] in {" ", "."}:
        raise BackupIntegrityError("backup member contains a Windows-ambiguous trailing character")
    if any(ord(char) < 32 or ord(char) == 127 for char in component):
        raise BackupIntegrityError("backup member contains control characters")
    if ":" in component:
        raise BackupIntegrityError("backup member contains a drive/stream separator")
    stem = component.split(".", 1)[0].upper()
    if stem in _WINDOWS_RESERVED:
        raise BackupIntegrityError("backup member contains a reserved Windows device name")


def safe_member(name: str) -> PurePosixPath:
    if not isinstance(name, str):
        raise BackupIntegrityError("backup member path is not text")
    if not name or len(name) > 768 or "\x00" in name:
        raise BackupIntegrityError(f"unsafe backup member path: {name!r}")
    if name.startswith(("/", "\\", "//", "\\\\", "\\?\\", "\\.\\")) or _DRIVE_PREFIX.match(name):
        raise BackupIntegrityError(f"absolute/device-qualified backup member: {name!r}")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_PREFIX.match(normalized):
        raise BackupIntegrityError(f"absolute/drive-qualified backup member: {name!r}")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BackupIntegrityError(f"unsafe backup member path: {name!r}")
    for component in path.parts:
        _validate_component(component)
    return path


# Historical internal name kept for compatibility with prior QA scripts.
_safe_member = safe_member


def _zip_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0xFFFF


def _is_zip_link_or_special(info: zipfile.ZipInfo) -> bool:
    mode = _zip_mode(info)
    kind = stat.S_IFMT(mode)
    # ZIP creators commonly store permission bits without POSIX file-type bits.
    if kind == 0:
        return False
    return kind not in {stat.S_IFREG, stat.S_IFDIR}


def _check_zip_info(info: zipfile.ZipInfo, *, nested: bool = False) -> PurePosixPath:
    path = safe_member(info.filename)
    if _is_zip_link_or_special(info):
        raise BackupIntegrityError(f"linked/special archive member is forbidden: {info.filename}")
    limit = MAX_MEMBER_BYTES if not nested else min(MAX_MEMBER_BYTES, MAX_NESTED_TOTAL_BYTES)
    if info.file_size < 0 or info.file_size > limit:
        raise BackupIntegrityError(f"oversized archive member: {info.filename}")
    if info.compress_size == 0:
        if info.file_size > 0:
            raise BackupIntegrityError(f"invalid compression metadata: {info.filename}")
    elif info.file_size / max(1, info.compress_size) > MAX_COMPRESSION_RATIO:
        raise BackupIntegrityError(f"archive member exceeds compression-ratio limit: {info.filename}")
    return path


def _copy_member_to_temp(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[Path, int, str]:
    fd, name = tempfile.mkstemp(prefix="leandesk-backup-member-", suffix=".tmp")
    temp = Path(name)
    count = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out, zf.open(info, "r") as src:
            while True:
                block = src.read(_COPY_CHUNK)
                if not block:
                    break
                count += len(block)
                if count > MAX_MEMBER_BYTES or count > info.file_size:
                    raise BackupIntegrityError(f"archive member expanded beyond declared/safe size: {info.filename}")
                digest.update(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if count != info.file_size:
            raise BackupIntegrityError(f"archive member size mismatch: {info.filename}")
        return temp, count, digest.hexdigest().upper()
    except (BackupIntegrityError, zipfile.BadZipFile, RuntimeError, OSError) as exc:
        temp.unlink(missing_ok=True)
        if isinstance(exc, BackupIntegrityError):
            raise
        raise BackupIntegrityError(f"could not safely read archive member {info.filename}: {type(exc).__name__}") from exc


def _strict_json_path(path: Path, label: str) -> Any:
    try:
        size = path.stat().st_size
        if size > MAX_JSON_BYTES:
            raise BackupIntegrityError(f"JSON payload exceeds limit: {label}")
        return strict_json_load_bytes(path.read_bytes())
    except BackupIntegrityError:
        raise
    except (DataBoundaryError, UnicodeError, OSError) as exc:
        raise BackupIntegrityError(f"invalid JSON payload in {label}: {exc}") from exc


def _validate_sqlite_path(path: Path, label: str) -> None:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
            if not row or str(row[0]).casefold() != "ok":
                raise BackupIntegrityError(f"SQLite integrity check failed for {label}")
        finally:
            connection.close()
    except BackupIntegrityError:
        raise
    except sqlite3.Error as exc:
        raise BackupIntegrityError(f"invalid SQLite database in {label}: {type(exc).__name__}") from exc


def _validate_nested_native(path: Path, label: str) -> None:
    try:
        with zipfile.ZipFile(path, "r") as nested:
            infos = nested.infolist()
            if len(infos) > MAX_NESTED_FILES:
                raise BackupIntegrityError(f"nested native document has too many members: {label}")
            seen: set[str] = set()
            total = 0
            json_members = 0
            for info in infos:
                member = _check_zip_info(info, nested=True)
                key = member.as_posix().casefold()
                if key in seen:
                    raise BackupIntegrityError(f"duplicate/case-colliding nested member: {label}:{info.filename}")
                seen.add(key)
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_NESTED_TOTAL_BYTES:
                    raise BackupIntegrityError(f"nested native document exceeds expansion limit: {label}")
                temp, _, _ = _copy_member_to_temp(nested, info)
                try:
                    if member.suffix.casefold() == ".json":
                        _strict_json_path(temp, f"{label}:{member.as_posix()}")
                        json_members += 1
                finally:
                    temp.unlink(missing_ok=True)
            if json_members == 0:
                raise BackupIntegrityError(f"nested native document has no structured payload: {label}")
    except BackupIntegrityError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise BackupIntegrityError(f"invalid nested native document {label}: {type(exc).__name__}") from exc


def semantic_validate_path(name: str, path: Path) -> None:
    lower = name.casefold()
    native = lower.endswith((".ldoc", ".lsheet", ".ldeck", ".ldraw"))
    if lower.endswith(".json") or native:
        with path.open("rb") as handle:
            prefix = handle.read(4).lstrip()
        if prefix.startswith((b"{", b"[")):
            obj = _strict_json_path(path, name)
            if not isinstance(obj, (dict, list)):
                raise BackupIntegrityError(f"unexpected structured payload in {name}")
        elif native and zipfile.is_zipfile(path):
            _validate_nested_native(path, name)
        else:
            raise BackupIntegrityError(f"unrecognized native/JSON payload: {name}")
    elif lower.endswith((".sqlite", ".sqlite3", ".db")):
        _validate_sqlite_path(path, name)
    elif lower.endswith((".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")):
        try:
            from PIL import Image
            with Image.open(path) as image:
                image.verify()
        except ImportError:
            if path.stat().st_size == 0:
                raise BackupIntegrityError(f"empty image asset: {name}")
        except Exception as exc:
            raise BackupIntegrityError(f"invalid image asset {name}: {type(exc).__name__}") from exc


def _parse_manifest(path: Path) -> dict[str, Any]:
    obj = _strict_json_path(path, MANIFEST_NAME)
    if not isinstance(obj, dict) or obj.get("schema") != BACKUP_SCHEMA or obj.get("product") != "leandesk-suite":
        raise BackupIntegrityError("backup manifest schema/product mismatch")
    rows = obj.get("files")
    if not isinstance(rows, list) or len(rows) > MAX_FILES:
        raise BackupIntegrityError("backup manifest file list is invalid")
    return obj


def _listed_identity(manifest: dict[str, Any]) -> dict[str, tuple[int, str]]:
    listed: dict[str, tuple[int, str]] = {}
    keys: set[str] = set()
    for row in manifest.get("files", []):
        if not isinstance(row, dict) or set(row) - {"path", "size", "sha256"}:
            raise BackupIntegrityError("malformed backup manifest row")
        name = safe_member(row.get("path", "")).as_posix()
        key = name.casefold()
        if key in keys:
            raise BackupIntegrityError(f"duplicate/case-colliding manifest path: {name}")
        keys.add(key)
        try:
            size = int(row.get("size", -1))
        except (TypeError, ValueError, OverflowError) as exc:
            raise BackupIntegrityError(f"invalid manifest size: {name}") from exc
        digest = str(row.get("sha256", "")).upper()
        if not (0 <= size <= MAX_MEMBER_BYTES) or not re.fullmatch(r"[A-F0-9]{64}", digest):
            raise BackupIntegrityError(f"invalid manifest identity: {name}")
        listed[name] = (size, digest)
    return listed


def verify_backup_artifact(path: os.PathLike[str] | str, *, require_manifest: bool = False) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.exists() or candidate.is_symlink() or _is_reparse(candidate):
        raise BackupIntegrityError("backup path is missing, linked, or a reparse point")
    if candidate.is_dir():
        return verify_backup_directory(candidate, require_manifest=require_manifest)
    if not candidate.is_file() or not zipfile.is_zipfile(candidate):
        raise BackupIntegrityError("backup artifact is not a regular ZIP archive")

    seen: set[str] = set()
    payload: dict[str, tuple[int, str]] = {}
    total = 0
    manifest: dict[str, Any] | None = None
    try:
        with zipfile.ZipFile(candidate, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_FILES + 1:
                raise BackupIntegrityError("backup contains too many members")
            for info in infos:
                member = _check_zip_info(info)
                key = member.as_posix().casefold()
                if key in seen:
                    raise BackupIntegrityError(f"duplicate/case-colliding backup member: {info.filename}")
                seen.add(key)
                if info.is_dir():
                    continue
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise BackupIntegrityError("backup expands beyond validation limit")
                temp, size, digest = _copy_member_to_temp(archive, info)
                try:
                    if member.as_posix() == MANIFEST_NAME:
                        if manifest is not None:
                            raise BackupIntegrityError("duplicate backup manifest")
                        manifest = _parse_manifest(temp)
                    else:
                        semantic_validate_path(member.as_posix(), temp)
                        payload[member.as_posix()] = (size, digest)
                finally:
                    temp.unlink(missing_ok=True)
    except BackupIntegrityError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise BackupIntegrityError(f"backup ZIP validation failed: {type(exc).__name__}") from exc

    if manifest is None:
        if require_manifest:
            raise BackupIntegrityError("strict backup manifest is missing")
        return {"valid": True, "legacy": True, "files": len(payload), "bytes": total}
    listed = _listed_identity(manifest)
    if listed != payload:
        missing = sorted(set(listed) - set(payload))
        extra = sorted(set(payload) - set(listed))
        changed = sorted(key for key in set(listed) & set(payload) if listed[key] != payload[key])
        raise BackupIntegrityError(
            f"backup manifest identity mismatch; missing={missing}, extra={extra}, changed={changed}"
        )
    return {"valid": True, "legacy": False, "files": len(payload), "bytes": total}


def _walk_regular_files(root: Path) -> Iterable[Path]:
    count = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise BackupIntegrityError(f"could not inspect backup directory: {type(exc).__name__}") from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                info = path.lstat()
            except OSError as exc:
                raise BackupIntegrityError(f"could not inspect backup member: {entry.name}") from exc
            if entry.is_symlink() or _is_reparse(path):
                raise BackupIntegrityError(f"linked/reparse backup member is forbidden: {path}")
            if stat.S_ISDIR(info.st_mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise BackupIntegrityError(f"non-regular/multiply-linked backup file: {path}")
            count += 1
            if count > MAX_FILES + 1:
                raise BackupIntegrityError("backup contains too many files")
            yield path


def verify_backup_directory(root: os.PathLike[str] | str, *, require_manifest: bool = False) -> dict[str, Any]:
    raw_root = Path(root)
    if not raw_root.exists() or raw_root.is_symlink() or _is_reparse(raw_root):
        raise BackupIntegrityError("backup directory is missing or linked")
    resolved = raw_root.resolve(strict=True)
    if not resolved.is_dir():
        raise BackupIntegrityError("backup directory is not a directory")
    manifest: dict[str, Any] | None = None
    payload: dict[str, tuple[int, str]] = {}
    total = 0
    for path in _walk_regular_files(resolved):
        relative = path.relative_to(resolved).as_posix()
        safe_member(relative)
        size = path.stat().st_size
        if size > MAX_MEMBER_BYTES:
            raise BackupIntegrityError(f"oversized backup file: {relative}")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise BackupIntegrityError("backup directory exceeds expansion limit")
        if relative == MANIFEST_NAME:
            manifest = _parse_manifest(path)
            continue
        semantic_validate_path(relative, path)
        payload[relative] = (size, sha256_file(path))
    if manifest is None:
        if require_manifest:
            raise BackupIntegrityError("strict backup manifest is missing")
        return {"valid": True, "legacy": True, "files": len(payload), "bytes": total}
    if _listed_identity(manifest) != payload:
        raise BackupIntegrityError("backup directory manifest identity mismatch")
    return {"valid": True, "legacy": False, "files": len(payload), "bytes": total}


def _manifest_for_zip(archive: zipfile.ZipFile) -> dict[str, Any]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    total = 0
    for info in archive.infolist():
        member = _check_zip_info(info)
        key = member.as_posix().casefold()
        if key in seen:
            raise BackupIntegrityError(f"duplicate/case-colliding backup member: {info.filename}")
        seen.add(key)
        if info.is_dir() or member.as_posix() == MANIFEST_NAME:
            continue
        total += info.file_size
        if total > MAX_TOTAL_BYTES or len(rows) >= MAX_FILES:
            raise BackupIntegrityError("backup exceeds bounded validation limits")
        temp, size, digest = _copy_member_to_temp(archive, info)
        try:
            semantic_validate_path(member.as_posix(), temp)
        finally:
            temp.unlink(missing_ok=True)
        rows.append({"path": member.as_posix(), "size": size, "sha256": digest})
    rows.sort(key=lambda row: row["path"].casefold())
    return {"schema": BACKUP_SCHEMA, "product": "leandesk-suite", "files": rows}


def ensure_zip_manifest(path: os.PathLike[str] | str) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file() or candidate.is_symlink() or _is_reparse(candidate):
        raise BackupIntegrityError("backup archive must be a regular unlinked file")
    temporary: Path | None = None
    try:
        with zipfile.ZipFile(candidate, "r") as source:
            manifest = _manifest_for_zip(source)
            fd, name = tempfile.mkstemp(prefix=f".{candidate.name}.", suffix=".tmp", dir=str(candidate.parent))
            os.close(fd)
            temporary = Path(name)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
                for info in source.infolist():
                    member = _check_zip_info(info)
                    if member.as_posix() == MANIFEST_NAME:
                        continue
                    if info.is_dir():
                        output.writestr(info, b"")
                        continue
                    with source.open(info, "r") as src, output.open(info, "w", force_zip64=False) as dst:
                        shutil.copyfileobj(src, dst, length=_COPY_CHUNK)
                output.writestr(
                    MANIFEST_NAME,
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                )
        # Windows requires a write-capable descriptor for FlushFileBuffers and
        # requires the old candidate handle to be closed before atomic replacement.
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, candidate)
    except BackupIntegrityError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise BackupIntegrityError(f"could not create backup manifest: {type(exc).__name__}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return verify_backup_artifact(candidate, require_manifest=True)


# Compatibility hook retained for downstream code, but the application now calls the
# real backup_service workflow directly. This no longer monkeypatches arbitrary methods.
def install_guards(namespace: dict[str, Any]) -> None:
    return None
