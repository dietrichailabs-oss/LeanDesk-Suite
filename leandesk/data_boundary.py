from __future__ import annotations

"""Strict, bounded JSON and local-data helpers.

This module is intentionally independent from the UI.  It provides one data boundary
for settings, native documents, recovery records, and the small JSON stores used by
LeanDesk.  Malformed input is never silently reinterpreted as empty data.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable, Iterable

DEFAULT_JSON_LIMIT = 32 * 1024 * 1024
CURRENT_SCHEMA_VERSION = 1


class DataBoundaryError(ValueError):
    """Base class for controlled local-data failures."""


class DuplicateKeyError(DataBoundaryError):
    pass


class UnsupportedSchemaVersion(DataBoundaryError):
    def __init__(self, found: int, supported: int = CURRENT_SCHEMA_VERSION) -> None:
        super().__init__(f"Unsupported future schema version {found}; this build supports {supported}.")
        self.found = found
        self.supported = supported


class DataCorruptionError(DataBoundaryError):
    pass


@dataclass(frozen=True)
class JsonLoadResult:
    value: Any
    read_only: bool = False
    error: str | None = None
    quarantine_copy: Path | None = None


def _reject_duplicate_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def strict_json_loads(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except DuplicateKeyError:
        raise
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError) as exc:
        raise DataCorruptionError(f"Invalid JSON data: {exc}") from exc


def strict_json_load_bytes(data: bytes) -> Any:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DataCorruptionError("JSON data is not valid UTF-8.") from exc
    return strict_json_loads(text)


def read_bounded(path: Path, *, limit: int = DEFAULT_JSON_LIMIT) -> bytes:
    try:
        stat_result = path.stat()
    except OSError as exc:
        raise DataCorruptionError(f"Could not inspect {path.name}: {exc}") from exc
    if not path.is_file() or path.is_symlink():
        raise DataCorruptionError(f"{path.name} is not a regular local file.")
    if stat_result.st_size > limit:
        raise DataCorruptionError(f"{path.name} exceeds the {limit}-byte safety limit.")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DataCorruptionError(f"Could not read {path.name}: {exc}") from exc
    if len(data) > limit:
        raise DataCorruptionError(f"{path.name} exceeds the {limit}-byte safety limit.")
    return data


def load_json_file(path: Path, *, limit: int = DEFAULT_JSON_LIMIT) -> Any:
    return strict_json_load_bytes(read_bounded(path, limit=limit))


def schema_version(payload: Any, *, field: str = "schema_version", default: int = 1) -> int:
    if not isinstance(payload, dict):
        return default
    value = payload.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise DataCorruptionError(f"Invalid {field!r} value.")
    return value


def require_supported_schema(
    payload: Any,
    *,
    field: str = "schema_version",
    supported: int = CURRENT_SCHEMA_VERSION,
    default: int = 1,
) -> int:
    found = schema_version(payload, field=field, default=default)
    if found > supported:
        raise UnsupportedSchemaVersion(found, supported)
    return found


def _safe_reason(reason: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", reason.strip().lower()).strip("-")
    return value[:48] or "invalid"


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest().upper()


def quarantine_copy(path: Path, reason: str, *, directory: Path | None = None) -> Path | None:
    """Copy original bytes to a deterministic quarantine directory without deleting them."""
    if not path.is_file() or path.is_symlink():
        return None
    directory = directory or (path.parent / "Quarantine")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        digest = _stream_sha256(path)[:16]
    except OSError:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"{path.name}.{stamp}.{_safe_reason(reason)}.{digest}.quarantine"
    counter = 1
    while destination.exists():
        destination = directory / f"{path.name}.{stamp}.{_safe_reason(reason)}.{digest}.{counter}.quarantine"
        counter += 1
    try:
        shutil.copy2(path, destination, follow_symlinks=False)
    except OSError:
        return None
    return destination


def quarantine_move(path: Path, reason: str, *, directory: Path | None = None) -> Path | None:
    """Move a damaged regular file into quarantine while preserving exact bytes."""
    if not path.is_file() or path.is_symlink():
        return None
    directory = directory or (path.parent / "Quarantine")
    directory.mkdir(parents=True, exist_ok=True)
    try:
        digest = _stream_sha256(path)[:16]
    except OSError:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = directory / f"{path.name}.{stamp}.{_safe_reason(reason)}.{digest}.corrupt"
    counter = 1
    while destination.exists():
        destination = directory / f"{path.name}.{stamp}.{_safe_reason(reason)}.{digest}.{counter}.corrupt"
        counter += 1
    try:
        os.replace(path, destination)
    except OSError:
        try:
            shutil.copy2(path, destination, follow_symlinks=False)
            path.unlink()
        except OSError:
            return None
    return destination


def load_json_or_default(
    path: Path,
    default_factory: Callable[[], Any],
    *,
    expected_type: type | tuple[type, ...] | None = None,
    limit: int = DEFAULT_JSON_LIMIT,
    quarantine: bool = True,
) -> JsonLoadResult:
    if not path.exists():
        return JsonLoadResult(default_factory())
    try:
        value = load_json_file(path, limit=limit)
        if expected_type is not None and not isinstance(value, expected_type):
            raise DataCorruptionError(f"Unexpected JSON root type in {path.name}.")
        return JsonLoadResult(value)
    except DataBoundaryError as exc:
        copy = quarantine_copy(path, type(exc).__name__) if quarantine else None
        return JsonLoadResult(default_factory(), read_only=True, error=str(exc), quarantine_copy=copy)
    except OSError as exc:
        copy = quarantine_copy(path, "read-error") if quarantine else None
        return JsonLoadResult(default_factory(), read_only=True, error=str(exc), quarantine_copy=copy)


def merge_known_and_extra(known: dict[str, Any], extra: dict[str, Any] | None) -> dict[str, Any]:
    result = dict(extra or {})
    result.update(known)
    return result
