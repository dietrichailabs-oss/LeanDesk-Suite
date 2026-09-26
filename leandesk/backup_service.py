from __future__ import annotations

"""Transactional LeanDesk profile backup and restore service."""

from dataclasses import dataclass
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any
import uuid
import zipfile

from . import backup_integrity as _backup_integrity
from .backup_integrity import (
    BACKUP_SCHEMA,
    MANIFEST_NAME,
    MAX_FILES,
    MAX_MEMBER_BYTES,
    MAX_TOTAL_BYTES,
    BackupIntegrityError,
    _is_reparse,
    _walk_regular_files,
    safe_member,
    semantic_validate_path,
    sha256_file,
    verify_backup_artifact,
)
from .core import DATA_ROOT

PROFILE_PREFIX = "profile"
_MAX_BACKUP_ARCHIVE_BYTES = MAX_TOTAL_BYTES + (16 * 1024 * 1024)
_ACTIVE_BACKUP_SOURCE_GUARD: ContextVar["_BackupSourceGuard | None"] = ContextVar(
    "leandesk_active_backup_source_guard", default=None
)


@dataclass(frozen=True)
class _PathIdentity:
    device: int
    inode: int
    kind: int
    attributes: int
    size: int | None = None
    mtime_ns: int | None = None


@dataclass(frozen=True)
class _RestorePathGuard:
    target: Path
    parent: Path
    parent_identity: _PathIdentity
    target_identity: _PathIdentity | None


@dataclass(frozen=True)
class _BackupDestinationGuard:
    target: Path
    parent: Path
    parent_identity: _PathIdentity
    target_identity: _PathIdentity | None


@dataclass(frozen=True)
class _BackupSourceGuard:
    """Raw, unresolved profile-root containment and filesystem identities."""

    root: Path
    chain: tuple[tuple[Path, _PathIdentity], ...]


def _absolute_without_resolution(value: os.PathLike[str] | str) -> Path:
    """Return an absolute normalized path without following any filesystem link."""

    expanded = Path(value).expanduser()
    return Path(os.path.abspath(os.fspath(expanded)))


def _lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _info_is_reparse(info: os.stat_result) -> bool:
    return bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _identity(path: Path, *, include_file_state: bool = False) -> _PathIdentity:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BackupIntegrityError(f"filesystem path identity is unavailable: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or _info_is_reparse(info):
        raise BackupIntegrityError(f"filesystem path is linked or a reparse point: {path}")
    return _PathIdentity(
        int(info.st_dev),
        int(info.st_ino),
        stat.S_IFMT(info.st_mode),
        int(getattr(info, "st_file_attributes", 0)),
        int(info.st_size) if include_file_state else None,
        int(info.st_mtime_ns) if include_file_state else None,
    )


def _chain_components(path: Path) -> list[Path]:
    if not path.is_absolute() or not path.anchor:
        raise BackupIntegrityError("filesystem path must be absolute")
    anchor = Path(path.anchor)
    components = [anchor]
    current = anchor
    # The first part is the anchor for POSIX, drive, and UNC paths.
    for part in path.parts[1:]:
        current = current / part
        components.append(current)
    return components


def _assert_safe_directory_component(path: Path, *, allow_anchor_mount: bool = False) -> _PathIdentity:
    info = _lstat_or_none(path)
    if info is None:
        raise BackupIntegrityError(f"required directory is missing: {path}")
    if stat.S_ISLNK(info.st_mode) or _info_is_reparse(info):
        raise BackupIntegrityError(f"directory path is linked or a reparse point: {path}")
    if not stat.S_ISDIR(info.st_mode):
        raise BackupIntegrityError(f"path component is not a directory: {path}")
    if not allow_anchor_mount and os.path.ismount(path):
        raise BackupIntegrityError(f"directory path crosses a mount redirection: {path}")
    return _identity(path)


def _capture_safe_directory_chain(
    path: Path,
    *,
    create_missing: bool = False,
) -> tuple[tuple[Path, _PathIdentity], ...]:
    """Capture every unresolved directory identity in ``path``.

    Non-anchor mounts, symbolic links, junction/reparse points, non-directory
    components, and missing components (unless explicitly created) are refused.
    Keeping the complete chain lets backup enumeration recheck the raw containment
    boundary instead of trusting a one-time ``resolve()`` result.
    """

    rows: list[tuple[Path, _PathIdentity]] = []
    for index, component in enumerate(_chain_components(path)):
        info = _lstat_or_none(component)
        if info is None:
            if not create_missing:
                raise BackupIntegrityError(f"required directory is missing: {component}")
            try:
                os.mkdir(component, 0o700)
            except OSError as exc:
                raise BackupIntegrityError(f"could not create protected directory: {component}") from exc
        identity = _assert_safe_directory_component(component, allow_anchor_mount=index == 0)
        rows.append((component, identity))
    return tuple(rows)


def _ensure_safe_directory_chain(path: Path) -> _PathIdentity:
    """Create missing directories one component at a time without following links."""

    return _capture_safe_directory_chain(path, create_missing=True)[-1][1]


def _validate_safe_existing_chain(path: Path) -> _PathIdentity:
    return _capture_safe_directory_chain(path, create_missing=False)[-1][1]


def _prepare_backup_source(
    data_root: os.PathLike[str] | str,
    *,
    create: bool = False,
) -> _BackupSourceGuard:
    root = _absolute_without_resolution(data_root)
    chain = _capture_safe_directory_chain(root, create_missing=create)
    return _BackupSourceGuard(root=root, chain=chain)


def _recheck_backup_source_guard(guard: _BackupSourceGuard) -> None:
    current = _capture_safe_directory_chain(guard.root, create_missing=False)
    if current != guard.chain:
        raise BackupIntegrityError("LeanDesk data-root containment changed during backup")


def _prepare_restore_guard(data_root: os.PathLike[str] | str) -> _RestorePathGuard:
    target = _absolute_without_resolution(data_root)
    parent = target.parent
    parent_identity = _ensure_safe_directory_chain(parent)
    info = _lstat_or_none(target)
    target_identity: _PathIdentity | None = None
    if info is not None:
        if stat.S_ISLNK(info.st_mode) or _info_is_reparse(info):
            raise BackupIntegrityError("LeanDesk restore target is linked or a reparse point")
        if not stat.S_ISDIR(info.st_mode):
            raise BackupIntegrityError("LeanDesk restore target is not a directory")
        if os.path.ismount(target):
            raise BackupIntegrityError("LeanDesk restore target is a mount redirection")
        target_identity = _identity(target)
    return _RestorePathGuard(target, parent, parent_identity, target_identity)


def _recheck_restore_guard(
    guard: _RestorePathGuard,
    *,
    expected_target: _PathIdentity | None,
) -> None:
    """Recheck raw containment and identity immediately before a rename boundary."""

    current_parent = _validate_safe_existing_chain(guard.parent)
    if current_parent != guard.parent_identity:
        raise BackupIntegrityError("LeanDesk profile parent changed during restore")
    info = _lstat_or_none(guard.target)
    if expected_target is None:
        if info is not None:
            raise BackupIntegrityError("LeanDesk restore target appeared or changed during restore")
        return
    if info is None:
        raise BackupIntegrityError("LeanDesk restore target disappeared during restore")
    current_target = _identity(guard.target)
    if current_target != expected_target:
        raise BackupIntegrityError("LeanDesk restore target identity changed during restore")


def _prepare_backup_destination(destination: os.PathLike[str] | str) -> _BackupDestinationGuard:
    target = _absolute_without_resolution(destination)
    parent = target.parent
    parent_identity = _ensure_safe_directory_chain(parent)
    info = _lstat_or_none(target)
    target_identity: _PathIdentity | None = None
    if info is not None:
        if stat.S_ISLNK(info.st_mode) or _info_is_reparse(info):
            raise BackupIntegrityError("backup destination is linked or a reparse point")
        if not stat.S_ISREG(info.st_mode):
            raise BackupIntegrityError("backup destination must be a regular file path")
        target_identity = _identity(target, include_file_state=True)
    return _BackupDestinationGuard(target, parent, parent_identity, target_identity)


def _recheck_backup_destination(guard: _BackupDestinationGuard) -> None:
    current_parent = _validate_safe_existing_chain(guard.parent)
    if current_parent != guard.parent_identity:
        raise BackupIntegrityError("backup destination directory changed during creation")
    info = _lstat_or_none(guard.target)
    if guard.target_identity is None:
        if info is not None:
            raise BackupIntegrityError("backup destination appeared during creation")
        return
    if info is None or _identity(guard.target, include_file_state=True) != guard.target_identity:
        raise BackupIntegrityError("existing backup destination changed during creation")


def _regular_profile_root(root: Path, *, create: bool = False) -> Path:
    """Return a raw, containment-checked profile root without following links."""

    return _prepare_backup_source(root, create=create).root


def _hash_profile_file(path: Path, logical: str, guard: _BackupSourceGuard) -> tuple[int, str]:
    """Hash one regular profile file while binding path, handle, and root identities."""

    _recheck_backup_source_guard(guard)
    try:
        before = path.lstat()
    except OSError as exc:
        raise BackupIntegrityError(f"profile file disappeared during manifest creation: {logical}") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _info_is_reparse(before)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink > 1
    ):
        raise BackupIntegrityError(f"profile file is linked or non-regular: {logical}")
    if before.st_size > MAX_MEMBER_BYTES:
        raise BackupIntegrityError(f"profile file exceeds backup member limit: {logical}")

    digest = hashlib.sha256()
    total = 0
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            if _file_signature(opened) != _file_signature(before):
                raise BackupIntegrityError(f"profile file identity changed before hashing: {logical}")
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > MAX_MEMBER_BYTES or total > before.st_size:
                    raise BackupIntegrityError(f"profile file changed or exceeded limits: {logical}")
                digest.update(block)
            opened_after = os.fstat(handle.fileno())
    except BackupIntegrityError:
        raise
    except OSError as exc:
        raise BackupIntegrityError(f"could not safely read profile file: {logical}") from exc

    try:
        after = path.lstat()
    except OSError as exc:
        raise BackupIntegrityError(f"profile file disappeared after hashing: {logical}") from exc
    _recheck_backup_source_guard(guard)
    if _file_signature(opened_after) != _file_signature(before) or _file_signature(after) != _file_signature(before):
        raise BackupIntegrityError(f"profile file changed while its manifest identity was created: {logical}")
    if total != before.st_size:
        raise BackupIntegrityError(f"profile file size changed while hashing: {logical}")
    return total, digest.hexdigest().upper()


def _manifest_rows(
    root: Path,
    *,
    excluded: set[Path] | None = None,
    source_guard: _BackupSourceGuard | None = None,
) -> list[dict[str, Any]]:
    guard = source_guard or _prepare_backup_source(root)
    excluded_raw = {_absolute_without_resolution(path) for path in (excluded or set())}
    rows: list[dict[str, Any]] = []
    total = 0
    _recheck_backup_source_guard(guard)
    for path in _walk_regular_files(root):
        _recheck_backup_source_guard(guard)
        raw_path = _absolute_without_resolution(path)
        if raw_path in excluded_raw:
            continue
        relative = path.relative_to(root).as_posix()
        logical = safe_member(f"{PROFILE_PREFIX}/{relative}").as_posix()
        size, digest = _hash_profile_file(path, logical, guard)
        total += size
        if total > MAX_TOTAL_BYTES or len(rows) >= MAX_FILES:
            raise BackupIntegrityError("LeanDesk profile exceeds backup limits")
        rows.append({"path": logical, "size": size, "sha256": digest})
    _recheck_backup_source_guard(guard)
    rows.sort(key=lambda row: row["path"].casefold())
    return rows


def _file_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        stat.S_IFMT(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_nlink),
    )


def _write_profile_member(
    archive: zipfile.ZipFile,
    source: Path,
    logical: str,
    expected: dict[str, Any],
    *,
    source_guard: _BackupSourceGuard | None = None,
) -> None:
    """Stream one immutable profile file into the temporary backup."""

    active_guard = source_guard or _ACTIVE_BACKUP_SOURCE_GUARD.get()
    if active_guard is not None:
        _recheck_backup_source_guard(active_guard)
    try:
        before = source.lstat()
    except OSError as exc:
        raise BackupIntegrityError(f"profile file disappeared during backup: {logical}") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or _info_is_reparse(before)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink > 1
    ):
        raise BackupIntegrityError(f"profile file became linked or non-regular: {logical}")
    if before.st_size != expected["size"]:
        raise BackupIntegrityError(f"profile file changed size during backup: {logical}")

    digest = hashlib.sha256()
    written = 0
    try:
        with source.open("rb") as incoming:
            opened = os.fstat(incoming.fileno())
            if _file_signature(opened) != _file_signature(before):
                raise BackupIntegrityError(f"profile file identity changed before backup read: {logical}")
            with archive.open(logical, "w", force_zip64=True) as outgoing:
                while True:
                    block = incoming.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > expected["size"] or written > MAX_MEMBER_BYTES:
                        raise BackupIntegrityError(f"profile file changed or exceeded limits: {logical}")
                    digest.update(block)
                    outgoing.write(block)
            opened_after = os.fstat(incoming.fileno())
    except BackupIntegrityError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise BackupIntegrityError(f"could not safely write backup member {logical}: {type(exc).__name__}") from exc

    try:
        path_after = source.lstat()
    except OSError as exc:
        raise BackupIntegrityError(f"profile file disappeared after backup read: {logical}") from exc
    if active_guard is not None:
        _recheck_backup_source_guard(active_guard)
    if _file_signature(opened_after) != _file_signature(before) or _file_signature(path_after) != _file_signature(before):
        raise BackupIntegrityError(f"profile file changed while backup was being created: {logical}")
    if written != expected["size"] or digest.hexdigest().upper() != str(expected["sha256"]).upper():
        raise BackupIntegrityError(f"profile file identity does not match the backup manifest: {logical}")


def _identity_from_stat(info: os.stat_result, *, include_file_state: bool = False) -> _PathIdentity:
    return _PathIdentity(
        int(info.st_dev),
        int(info.st_ino),
        stat.S_IFMT(info.st_mode),
        int(getattr(info, "st_file_attributes", 0)),
        int(info.st_size) if include_file_state else None,
        int(info.st_mtime_ns) if include_file_state else None,
    )


def _open_bound_regular(path: Path, *, label: str):
    """Open one pathname without following its final link and bind it to lstat."""

    try:
        before = path.lstat()
    except OSError as exc:
        raise BackupIntegrityError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or _info_is_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise BackupIntegrityError(f"{label} must be a regular, non-linked file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BackupIntegrityError(f"{label} could not be opened safely") from exc
    handle = os.fdopen(descriptor, "rb", closefd=True)
    opened = os.fstat(handle.fileno())
    if _file_signature(opened) != _file_signature(before):
        handle.close()
        raise BackupIntegrityError(f"{label} identity changed while it was opened")
    return handle, before


def _hash_regular_path_bound(path: Path, *, label: str) -> tuple[str, _PathIdentity]:
    """Hash exactly one regular pathname occupant and reject identity changes."""

    handle, before = _open_bound_regular(path, label=label)
    digest = hashlib.sha256()
    total = 0
    try:
        with handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > _MAX_BACKUP_ARCHIVE_BYTES:
                    raise BackupIntegrityError(f"{label} exceeds the backup archive size limit")
                digest.update(block)
            opened_after = os.fstat(handle.fileno())
    except BackupIntegrityError:
        raise
    except OSError as exc:
        raise BackupIntegrityError(f"{label} could not be hashed safely") from exc
    try:
        after = path.lstat()
    except OSError as exc:
        raise BackupIntegrityError(f"{label} disappeared while it was hashed") from exc
    if _file_signature(opened_after) != _file_signature(before) or _file_signature(after) != _file_signature(before):
        raise BackupIntegrityError(f"{label} changed while it was hashed")
    if total != before.st_size:
        raise BackupIntegrityError(f"{label} size changed while it was hashed")
    return digest.hexdigest().upper(), _identity_from_stat(opened_after, include_file_state=True)


def _copy_restore_source_snapshot(source: Path, destination: Path) -> str:
    """Copy one selected backup through a stable handle into private restore staging.

    The source is read twice through the same open handle.  A mutation during the
    first pass therefore cannot authorize a mixed private copy.  Path replacement
    after this function returns is harmless because verification and extraction use
    only ``destination``.
    """

    handle, before = _open_bound_regular(source, label="backup restore source")
    digest = hashlib.sha256()
    total = 0
    try:
        with handle, destination.open("xb") as outgoing:
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                total += len(block)
                if total > _MAX_BACKUP_ARCHIVE_BYTES or total > before.st_size:
                    raise BackupIntegrityError("backup restore source changed or exceeds limits")
                digest.update(block)
                outgoing.write(block)
            outgoing.flush()
            os.fsync(outgoing.fileno())
            opened_after_copy = os.fstat(handle.fileno())

            # Re-read the same open file identity to detect in-place concurrent writes.
            handle.seek(0)
            confirmation = hashlib.sha256()
            confirmed_total = 0
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                confirmed_total += len(block)
                if confirmed_total > _MAX_BACKUP_ARCHIVE_BYTES:
                    raise BackupIntegrityError("backup restore source exceeds limits")
                confirmation.update(block)
            opened_after_confirm = os.fstat(handle.fileno())
    except BackupIntegrityError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise BackupIntegrityError("backup restore source could not be copied safely") from exc

    try:
        path_after = source.lstat()
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise BackupIntegrityError("backup restore source changed while it was copied") from exc
    expected_signature = _file_signature(before)
    if (
        _file_signature(opened_after_copy) != expected_signature
        or _file_signature(opened_after_confirm) != expected_signature
        or _file_signature(path_after) != expected_signature
        or total != before.st_size
        or confirmed_total != total
        or confirmation.digest() != digest.digest()
    ):
        destination.unlink(missing_ok=True)
        raise BackupIntegrityError("backup restore source changed while it was copied")
    snapshot_sha, _ = _hash_regular_path_bound(destination, label="private backup restore snapshot")
    if snapshot_sha != digest.hexdigest().upper():
        destination.unlink(missing_ok=True)
        raise BackupIntegrityError("private backup restore snapshot identity mismatch")
    return snapshot_sha


def _restore_backup_destination_after_failed_commit(
    target: Path,
    rollback: Path,
    *,
    had_previous: bool,
    previous_sha256: str = "",
    previous_identity: _PathIdentity | None = None,
) -> None:
    """Restore the exact prior destination or remove an uncommitted new target.

    When a destination existed, the rollback pathname is itself rebound to the
    previously hashed identity before it is allowed to replace the failed target.
    This prevents a second race from turning error recovery into an attacker-selected
    backup.  The restored target is then hashed again before success is reported.
    """

    try:
        if had_previous:
            if _lstat_or_none(rollback) is None:
                raise BackupIntegrityError("previous backup rollback copy is missing")
            rollback_sha, rollback_identity = _hash_regular_path_bound(
                rollback, label="previous backup rollback copy"
            )
            if (
                previous_identity is None
                or rollback_identity != previous_identity
                or not previous_sha256
                or rollback_sha != previous_sha256
            ):
                raise BackupIntegrityError(
                    "previous backup rollback copy changed; refusing unsafe reactivation"
                )
            os.replace(rollback, target)
            restored_sha, restored_identity = _hash_regular_path_bound(
                target, label="restored previous backup destination"
            )
            if restored_identity != previous_identity or restored_sha != previous_sha256:
                raise BackupIntegrityError(
                    "previous backup destination identity changed during reactivation"
                )
        else:
            info = _lstat_or_none(target)
            if info is not None:
                if stat.S_ISLNK(info.st_mode) or _info_is_reparse(info) or not stat.S_ISREG(info.st_mode):
                    raise BackupIntegrityError("failed backup target changed to an unsafe object")
                target.unlink()
        _sync_directory(target.parent)
    except BackupIntegrityError:
        raise
    except OSError as exc:
        raise BackupIntegrityError(
            f"backup commit failed; the previous destination is retained at {rollback}"
        ) from exc


def create_backup(destination: os.PathLike[str] | str, *, data_root: os.PathLike[str] | str = DATA_ROOT) -> dict[str, Any]:
    """Create and commit a verified profile backup transactionally.

    The candidate is verified before the existing destination is moved.  The exact
    candidate identity is then checked again after installation.  Any detected swap,
    invalid post-commit file, or hash mismatch atomically restores the previous
    destination (or removes the new target when no previous destination existed).
    """

    source_guard = _prepare_backup_source(data_root, create=True)
    root = source_guard.root
    guard = _prepare_backup_destination(destination)
    target = guard.target

    try:
        excluded = {target} if target.is_relative_to(root) else set()
    except ValueError:
        excluded = set()
    rows = _manifest_rows(root, excluded=excluded, source_guard=source_guard)
    manifest = {
        "schema": BACKUP_SCHEMA,
        "product": "leandesk-suite",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": rows,
    }

    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    temporary = Path(name)
    rollback = target.parent / f".{target.name}.previous-{uuid.uuid4().hex}.tmp"
    candidate_installed = False
    rollback_active = False
    committed = False
    verification: dict[str, Any] = {}
    candidate_sha256 = ""
    candidate_identity: _PathIdentity | None = None
    previous_sha256 = ""
    previous_identity: _PathIdentity | None = None
    active_token = _ACTIVE_BACKUP_SOURCE_GUARD.set(source_guard)
    try:
        temp_info = temporary.lstat()
        if stat.S_ISLNK(temp_info.st_mode) or _info_is_reparse(temp_info) or not stat.S_ISREG(temp_info.st_mode):
            raise BackupIntegrityError("backup temporary file is not a regular local file")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for row in rows:
                logical = str(row["path"])
                relative = PurePath(logical).relative_to(PROFILE_PREFIX)
                source = root.joinpath(*relative.parts)
                # Keep the historical four-argument call shape so independent fault
                # injectors and older tests continue to exercise the real helper.
                _write_profile_member(archive, source, logical, row)
            _recheck_backup_source_guard(source_guard)
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )

        # os.fsync maps to FlushFileBuffers on Windows and therefore requires a
        # write-capable descriptor even though no additional bytes are written.
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())

        # PRE-COMMIT: the old selected destination is still the active file.
        verification = verify_backup_artifact(temporary, require_manifest=True)
        candidate_sha256, candidate_identity = _hash_regular_path_bound(
            temporary, label="verified backup candidate"
        )
        _recheck_backup_source_guard(source_guard)
        _recheck_backup_destination(guard)

        # Bind the old destination to a byte identity before moving it.  A later
        # failed candidate commit can reactivate only this exact archive.
        if guard.target_identity is not None:
            previous_sha256, previous_identity = _hash_regular_path_bound(
                target, label="existing backup destination"
            )
            if previous_identity != guard.target_identity:
                raise BackupIntegrityError("existing backup destination changed before commit")
            _recheck_backup_destination(guard)

        # Preserve the exact old destination by atomic rename before consuming the
        # candidate pathname.  It remains recoverable until post-commit verification.
        if guard.target_identity is not None:
            if _lstat_or_none(rollback) is not None:
                raise BackupIntegrityError("backup rollback path unexpectedly exists")
            os.replace(target, rollback)
            rollback_active = True
            moved_sha, moved_identity = _hash_regular_path_bound(
                rollback, label="previous backup rollback copy"
            )
            if moved_identity != previous_identity or moved_sha != previous_sha256:
                raise BackupIntegrityError("existing backup changed while entering rollback")
            _sync_directory(target.parent)

        # A swap after the hash but before this rename is detected by the post-commit
        # identity/hash/manifest checks, after which the old destination is restored.
        os.replace(temporary, target)
        candidate_installed = True

        committed_sha, committed_identity = _hash_regular_path_bound(
            target, label="committed backup destination"
        )
        if committed_identity != candidate_identity or committed_sha != candidate_sha256:
            raise BackupIntegrityError("verified backup temporary file changed before replacement; committed bytes do not match")
        verification = _backup_integrity.verify_backup_artifact(target, require_manifest=True)
        final_sha, final_identity = _hash_regular_path_bound(
            target, label="committed backup destination"
        )
        if final_identity != candidate_identity or final_sha != candidate_sha256:
            raise BackupIntegrityError("committed backup changed during final verification")
        committed = True
    except BackupIntegrityError:
        if candidate_installed or rollback_active:
            _restore_backup_destination_after_failed_commit(
                target,
                rollback,
                had_previous=guard.target_identity is not None,
                previous_sha256=previous_sha256,
                previous_identity=previous_identity,
            )
            rollback_active = False
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if candidate_installed or rollback_active:
            try:
                _restore_backup_destination_after_failed_commit(
                    target,
                    rollback,
                    had_previous=guard.target_identity is not None,
                    previous_sha256=previous_sha256,
                    previous_identity=previous_identity,
                )
                rollback_active = False
            except BackupIntegrityError as restore_exc:
                raise restore_exc from exc
        raise BackupIntegrityError(f"backup creation failed: {type(exc).__name__}") from exc
    finally:
        _ACTIVE_BACKUP_SOURCE_GUARD.reset(active_token)
        if not committed:
            temporary.unlink(missing_ok=True)
        if not rollback_active:
            rollback.unlink(missing_ok=True)

    durability_warnings: list[str] = []
    try:
        _sync_directory(target.parent)
    except OSError as exc:
        durability_warnings.append(
            "The verified backup replaced the destination, but the destination-directory "
            f"durability flush failed: {type(exc).__name__}."
        )

    if rollback_active:
        try:
            rollback.unlink()
            _sync_directory(target.parent)
            rollback_active = False
        except OSError as exc:
            durability_warnings.append(
                "The new backup is verified and live, but the previous backup safety copy "
                f"was retained at {rollback}: {type(exc).__name__}."
            )

    verification.update(
        {
            "path": str(target),
            "sha256": candidate_sha256,
            "committed": True,
            "durability_warning": "\n".join(durability_warnings),
            "previous_destination_retained": rollback_active,
            "previous_destination_path": str(rollback) if rollback_active else "",
        }
    )
    return verification


# Local alias avoids platform-specific PurePath behavior in code above.
from pathlib import PurePosixPath as PurePath


def _extract_to_staging(archive_path: Path, staging_profile: Path) -> None:
    total = 0
    count = 0
    with zipfile.ZipFile(archive_path, "r") as archive:
        for info in archive.infolist():
            member = safe_member(info.filename)
            if member.as_posix() == MANIFEST_NAME or info.is_dir():
                continue
            if not member.parts or member.parts[0] != PROFILE_PREFIX or len(member.parts) < 2:
                raise BackupIntegrityError(f"unexpected restore member outside profile/: {info.filename}")
            relative = PurePath(*member.parts[1:])
            destination = staging_profile.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.parent.is_symlink() or _is_reparse(destination.parent):
                raise BackupIntegrityError("restore staging path became linked")
            count += 1
            total += info.file_size
            if count > MAX_FILES or info.file_size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                raise BackupIntegrityError("restore exceeds bounded extraction limits")
            written = 0
            with archive.open(info, "r") as src, destination.open("xb") as dst:
                while True:
                    block = src.read(1024 * 1024)
                    if not block:
                        break
                    written += len(block)
                    if written > info.file_size or written > MAX_MEMBER_BYTES:
                        raise BackupIntegrityError(f"restore member exceeded declared size: {info.filename}")
                    dst.write(block)
                dst.flush()
                os.fsync(dst.fileno())
            if written != info.file_size:
                raise BackupIntegrityError(f"restore member size mismatch: {info.filename}")
            semantic_validate_path(member.as_posix(), destination)


class BackupRestoreStateError(BackupIntegrityError):
    """Restore failure carrying a truthful description of surviving profile state."""

    def __init__(
        self,
        message: str,
        *,
        profile_state: str,
        rollback_path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.profile_state = profile_state
        self.rollback_path = str(rollback_path) if rollback_path is not None else None


def _sync_directory(path: Path) -> None:
    """Flush directory-entry changes where Python exposes a portable operation."""

    if os.name == "nt":
        # Python cannot portably open/fsync a directory handle on Windows.  File data is
        # still flushed before the atomic directory renames.
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sync_staging_tree(root: Path) -> None:
    """Flush every staged file and directory before the first live-profile rename."""

    for path in _walk_regular_files(root):
        with path.open("r+b") as handle:
            os.fsync(handle.fileno())
    directories = [root, *(path for path in root.rglob("*") if path.is_dir())]
    for directory in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        _sync_directory(directory)


def _restore_patterns(target: Path) -> tuple[str, str]:
    return (f".{target.name}.restore-staging-*", f".{target.name}.rollback-*")


def _safe_transaction_directory(path: Path, *, label: str) -> Path:
    info = _lstat_or_none(path)
    if (
        info is None
        or stat.S_ISLNK(info.st_mode)
        or _info_is_reparse(info)
        or not stat.S_ISDIR(info.st_mode)
        or os.path.ismount(path)
    ):
        raise BackupRestoreStateError(
            f"Unsafe abandoned {label} path requires manual review.",
            profile_state="unknown",
            rollback_path=path if label == "rollback" else None,
        )
    return path


def recover_abandoned_restore_state(
    *, data_root: os.PathLike[str] | str = DATA_ROOT
) -> dict[str, Any]:
    """Conservatively recover artifacts left by an interrupted restore.

    The raw supplied target and every existing parent component are inspected before
    any path resolution.  Linked, junction/reparse, or mounted redirections are
    refused.  Filesystem identities are rechecked immediately before a recovery
    rename so a caller-controlled path cannot be swapped after validation.
    """

    try:
        guard = _prepare_restore_guard(data_root)
    except BackupIntegrityError as exc:
        raise BackupRestoreStateError(
            str(exc),
            profile_state="unknown",
        ) from exc
    target = guard.target
    parent = guard.parent

    staging_pattern, rollback_pattern = _restore_patterns(target)
    staging_roots = sorted(parent.glob(staging_pattern), key=lambda value: value.name)
    rollbacks = sorted(parent.glob(rollback_pattern), key=lambda value: value.name)
    warnings: list[str] = []
    recovered_previous = False

    rollback_identities: dict[Path, _PathIdentity] = {}
    for rollback in rollbacks:
        _safe_transaction_directory(rollback, label="rollback")
        rollback_identities[rollback] = _identity(rollback)

    if _lstat_or_none(target) is None and rollbacks:
        if len(rollbacks) != 1:
            raise BackupRestoreStateError(
                "LeanDesk found multiple retained rollback profiles and will not guess which one to restore.",
                profile_state="previous_profile_retained",
                rollback_path=rollbacks[0],
            )
        rollback = rollbacks[0]
        try:
            _recheck_restore_guard(guard, expected_target=None)
            if _identity(rollback) != rollback_identities[rollback]:
                raise BackupIntegrityError("retained rollback identity changed before recovery")
            os.replace(rollback, target)
        except (OSError, BackupIntegrityError) as exc:
            raise BackupRestoreStateError(
                "LeanDesk could not reactivate the retained previous profile after an interrupted restore.",
                profile_state="previous_profile_retained",
                rollback_path=rollback,
            ) from exc
        recovered_previous = True
        rollbacks = []
        try:
            _sync_directory(parent)
        except OSError as exc:
            warnings.append(
                "The previous profile was reactivated, but its parent-directory durability "
                f"flush failed: {type(exc).__name__}."
            )

    # If recovery did not activate a target, its expected identity remains the
    # original guarded value.  If it did, capture the new live identity before any
    # staging cleanup.
    cleanup_expected = _identity(target) if recovered_previous else guard.target_identity
    cleanup_guard = _RestorePathGuard(target, parent, guard.parent_identity, cleanup_expected)
    for staging in staging_roots:
        _safe_transaction_directory(staging, label="staging")
        staging_identity = _identity(staging)
        try:
            _recheck_restore_guard(cleanup_guard, expected_target=cleanup_expected)
            if _identity(staging) != staging_identity:
                raise BackupIntegrityError("abandoned staging identity changed before cleanup")
            shutil.rmtree(staging)
        except (OSError, BackupIntegrityError):
            warnings.append(f"Abandoned restore staging could not be removed: {staging}")

    return {
        "recovered_previous_profile": recovered_previous,
        "retained_rollback_paths": [str(path) for path in rollbacks],
        "cleanup_warnings": warnings,
    }


def _write_rebased_manifest(archive_path: Path, staging_profile: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
    rebased = []
    for row in manifest["files"]:
        member = safe_member(row["path"])
        if member.parts[0] != PROFILE_PREFIX:
            raise BackupIntegrityError("manifest contains a non-profile restore path")
        rebased.append(
            {
                "path": PurePath(*member.parts[1:]).as_posix(),
                "size": row["size"],
                "sha256": row["sha256"],
            }
        )
    manifest_path = staging_profile / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {"schema": BACKUP_SCHEMA, "product": "leandesk-suite", "files": rebased},
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    with manifest_path.open("r+b") as handle:
        os.fsync(handle.fileno())


def restore_backup(
    source: os.PathLike[str] | str,
    *,
    data_root: os.PathLike[str] | str = DATA_ROOT,
) -> dict[str, Any]:
    """Transactionally replace the LeanDesk profile with a verified backup.

    A successful ``os.replace(staging_profile, target)`` is the commit point.  Every
    failure before it restores or retains the previous profile.  Every failure after it
    is a nonfatal cleanup/durability warning and is never misreported as an unchanged
    profile.  The raw target path and its parent chain are never resolved through links;
    their filesystem identities are rechecked immediately before each rename boundary.
    """

    archive_path = _absolute_without_resolution(source)

    # Recovery performs its own raw-path containment checks.  Capture a fresh guard
    # afterwards because recovery may have reactivated a retained profile.
    recovery = recover_abandoned_restore_state(data_root=data_root)
    try:
        guard = _prepare_restore_guard(data_root)
    except BackupIntegrityError as exc:
        raise BackupRestoreStateError(str(exc), profile_state="unknown") from exc
    target = guard.target
    parent = guard.parent

    token = uuid.uuid4().hex
    staging_root = parent / f".{target.name}.restore-staging-{token}"
    rollback = parent / f".{target.name}.rollback-{token}"
    try:
        _recheck_restore_guard(guard, expected_target=guard.target_identity)
        if _lstat_or_none(staging_root) is not None or _lstat_or_none(rollback) is not None:
            raise BackupIntegrityError("restore transaction path unexpectedly already exists")
        staging_root.mkdir(mode=0o700)
        staging_profile = staging_root / target.name
        staging_profile.mkdir(mode=0o700)
    except (OSError, BackupIntegrityError) as exc:
        raise BackupRestoreStateError(
            "LeanDesk could not create a private restore staging directory.",
            profile_state="profile_unchanged" if guard.target_identity is not None else "no_previous_profile",
        ) from exc

    private_archive = staging_root / "verified-source.ldbackup"
    snapshot_sha256 = ""
    verification: dict[str, Any] = {}
    moved_current = False
    committed = False
    cleanup_warnings: list[str] = list(recovery["cleanup_warnings"])
    rollback_retained = False
    rollback_identity: _PathIdentity | None = None

    try:
        # Bind verification and extraction to one private immutable copy.  Replacing,
        # renaming, truncating, or relinking the user-selected pathname after this copy
        # cannot change the bytes that authorize and populate the restore.
        snapshot_sha256 = _copy_restore_source_snapshot(archive_path, private_archive)
        verification = verify_backup_artifact(private_archive, require_manifest=True)
        verified_snapshot_sha, _ = _hash_regular_path_bound(
            private_archive, label="verified private restore snapshot"
        )
        if verified_snapshot_sha != snapshot_sha256:
            raise BackupIntegrityError("private restore snapshot changed after verification")

        _extract_to_staging(private_archive, staging_profile)
        _write_rebased_manifest(private_archive, staging_profile)
        from .backup_integrity import verify_backup_directory

        verify_backup_directory(staging_profile, require_manifest=True)
        (staging_profile / MANIFEST_NAME).unlink()
        _sync_staging_tree(staging_profile)
        staging_identity = _identity(staging_profile)

        if guard.target_identity is not None:
            _recheck_restore_guard(guard, expected_target=guard.target_identity)
            if _lstat_or_none(rollback) is not None:
                raise BackupIntegrityError("restore rollback path appeared before commit")
            os.replace(target, rollback)
            moved_current = True
            rollback_identity = _identity(rollback)
            _sync_directory(parent)

        # COMMIT POINT: after this rename returns, the validated new profile is live.
        _recheck_restore_guard(guard, expected_target=None)
        if _identity(staging_profile) != staging_identity:
            raise BackupIntegrityError("restore staging identity changed before commit")
        if moved_current and (rollback_identity is None or _identity(rollback) != rollback_identity):
            raise BackupIntegrityError("restore rollback identity changed before commit")
        os.replace(staging_profile, target)
        committed = True

    except Exception as exc:
        rollback_failure: Exception | None = None
        if moved_current and not committed and rollback_identity is not None:
            try:
                _recheck_restore_guard(guard, expected_target=None)
                if _identity(rollback) != rollback_identity:
                    raise BackupIntegrityError("rollback identity changed before reactivation")
                os.replace(rollback, target)
                _sync_directory(parent)
            except Exception as restore_exc:
                # The rollback remains untouched for deterministic restart/manual recovery.
                rollback_failure = restore_exc

        try:
            if _lstat_or_none(staging_root) is not None:
                _safe_transaction_directory(staging_root, label="staging")
                shutil.rmtree(staging_root)
        except (OSError, BackupRestoreStateError):
            # This contains only an uncommitted staging copy.  Preserve it rather than
            # risking the previous profile to make cleanup appear successful.
            pass

        if rollback_failure is not None:
            raise BackupRestoreStateError(
                "Restore did not commit. The previous profile is retained in a rollback "
                "directory but could not be reactivated automatically.",
                profile_state="previous_profile_retained",
                rollback_path=rollback,
            ) from rollback_failure

        target_info = _lstat_or_none(target)
        if target_info is not None and not stat.S_ISLNK(target_info.st_mode) and not _info_is_reparse(target_info):
            state = "previous_profile_active" if moved_current else "profile_unchanged"
            message = "Restore failed before the new profile was committed; the previous profile is active."
        elif _lstat_or_none(rollback) is not None:
            state = "previous_profile_retained"
            message = "Restore failed before commit; the previous profile is retained in a rollback directory."
        elif target_info is not None:
            state = "unknown"
            message = "Restore failed before commit and the profile target changed unexpectedly."
        else:
            state = "no_previous_profile"
            message = "Restore failed before a new profile was committed."

        if isinstance(exc, BackupRestoreStateError):
            raise
        if isinstance(exc, BackupIntegrityError):
            raise BackupRestoreStateError(
                str(exc),
                profile_state=state,
                rollback_path=rollback if _lstat_or_none(rollback) is not None else None,
            ) from exc
        raise BackupRestoreStateError(
            f"{message} Cause: {type(exc).__name__}",
            profile_state=state,
            rollback_path=rollback if _lstat_or_none(rollback) is not None else None,
        ) from exc

    # Everything below is post-commit.  It can only add truthful nonfatal warnings.
    try:
        _sync_directory(parent)
    except OSError as exc:
        cleanup_warnings.append(
            "The restored profile is live, but the parent-directory durability flush "
            f"failed: {type(exc).__name__}."
        )

    if moved_current and _lstat_or_none(rollback) is not None:
        try:
            _safe_transaction_directory(rollback, label="rollback")
            if rollback_identity is not None and _identity(rollback) != rollback_identity:
                raise BackupIntegrityError("rollback identity changed after commit")
            shutil.rmtree(rollback)
            _sync_directory(parent)
        except (OSError, BackupIntegrityError, BackupRestoreStateError) as exc:
            rollback_retained = _lstat_or_none(rollback) is not None
            if rollback_retained:
                cleanup_warnings.append(
                    "The restored profile is live, but the previous profile safety copy "
                    f"could not be removed and was retained at {rollback}: {type(exc).__name__}."
                )
            else:
                cleanup_warnings.append(
                    "The restored profile is live. Cleanup reported an error after the "
                    f"previous safety copy had already been removed: {type(exc).__name__}."
                )

    if _lstat_or_none(staging_root) is not None:
        try:
            _safe_transaction_directory(staging_root, label="staging")
            shutil.rmtree(staging_root)
            _sync_directory(parent)
        except (OSError, BackupRestoreStateError) as exc:
            cleanup_warnings.append(
                "The restored profile is live, but a restore-staging directory could not "
                f"be removed: {type(exc).__name__}."
            )

    verification.update(
        {
            "restored_to": str(target),
            "source_sha256": snapshot_sha256,
            "committed": True,
            "cleanup_warning": "\n".join(cleanup_warnings) if cleanup_warnings else "",
            "rollback_retained": rollback_retained,
            "rollback_path": str(rollback) if rollback_retained else "",
            "recovered_abandoned_profile": bool(recovery["recovered_previous_profile"]),
            "preexisting_retained_rollbacks": list(recovery["retained_rollback_paths"]),
        }
    )
    return verification
