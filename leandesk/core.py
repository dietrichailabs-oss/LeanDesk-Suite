from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .data_boundary import (
    DataBoundaryError,
    DataCorruptionError,
    DuplicateKeyError,
    JsonLoadResult,
    UnsupportedSchemaVersion,
    load_json_or_default,
    merge_known_and_extra,
    quarantine_move,
    read_bounded,
    strict_json_load_bytes,
)

APP_NAME = "LeanDesk Suite"
APP_VERSION = "0.8.1"
PUBLISHER = "Dietrich AI Labs"
SETTINGS_SCHEMA_VERSION = 1
STORE_SCHEMA_VERSION = 1

DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / PUBLISHER / APP_NAME
SETTINGS_FILE = DATA_ROOT / "settings.json"
RECENT_FILE = DATA_ROOT / "recent_files.json"
RECOVERY_ROOT = DATA_ROOT / "Recovery"
TEMPLATE_ROOT = DATA_ROOT / "Templates"
PERSONAL_DICTIONARY_FILE = DATA_ROOT / "personal_dictionary.json"
NOTES_FILE = DATA_ROOT / "notes.json"
TASKS_FILE = DATA_ROOT / "tasks.json"
CALENDAR_FILE = DATA_ROOT / "calendar.json"
CONTACTS_FILE = DATA_ROOT / "contacts.json"
UPDATE_STATE_FILE = DATA_ROOT / "update_state.json"
ASSET_ROOT = DATA_ROOT / "Assets"


class LocalDataReadOnlyError(RuntimeError):
    pass


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        raise OSError("Refusing to write through a symbolic-link directory.")
    with tempfile.NamedTemporaryFile(
        "w", encoding=encoding, delete=False, dir=str(path.parent), suffix=".tmp", newline="\n"
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False))


def read_json_result(path: Path, default_factory: Callable[[], Any]) -> JsonLoadResult:
    return load_json_or_default(Path(path), default_factory)


def read_json(path: Path, default: Any) -> Any:
    """Compatibility helper that is strict and non-destructive on failure."""
    factory = (lambda: default.copy()) if isinstance(default, (dict, list, set)) else (lambda: default)
    return read_json_result(Path(path), factory).value


@dataclass
class AppSettings:
    theme: str = "Midnight Copper"
    autosave_seconds: int = 30
    default_zoom: int = 100
    reopen_last_document: bool = False
    show_word_count: bool = True
    default_format: str = "ldoc"
    live_spellcheck: bool = True
    sidebar_collapsed: bool = False
    auto_check_updates: bool = True
    _extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)
    _schema_version: int = field(default=SETTINGS_SCHEMA_VERSION, repr=False, compare=False)
    _read_only: bool = field(default=False, repr=False, compare=False)
    _load_error: str | None = field(default=None, repr=False, compare=False)

    @classmethod
    def load(cls, path: Path = SETTINGS_FILE) -> "AppSettings":
        result = load_json_or_default(Path(path), dict, expected_type=dict)
        payload = result.value if isinstance(result.value, dict) else {}
        schema = payload.get("schema_version", SETTINGS_SCHEMA_VERSION)
        if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
            schema = SETTINGS_SCHEMA_VERSION
            result = JsonLoadResult(payload, read_only=True, error="Invalid settings schema_version.")
        future = schema > SETTINGS_SCHEMA_VERSION
        allowed = {
            "theme",
            "autosave_seconds",
            "default_zoom",
            "reopen_last_document",
            "show_word_count",
            "default_format",
            "live_spellcheck",
            "sidebar_collapsed",
            "auto_check_updates",
        }
        clean = {key: payload[key] for key in allowed if key in payload}
        extra = {key: value for key, value in payload.items() if key not in allowed and key != "schema_version"}
        bool_fields = {"reopen_last_document", "show_word_count", "live_spellcheck", "sidebar_collapsed", "auto_check_updates"}
        int_fields = {"autosave_seconds", "default_zoom"}
        str_fields = {"theme", "default_format"}
        invalid_fields = [
            key for key, value in clean.items()
            if (key in bool_fields and not isinstance(value, bool))
            or (key in int_fields and (isinstance(value, bool) or not isinstance(value, int)))
            or (key in str_fields and not isinstance(value, str))
        ]
        try:
            if invalid_fields:
                raise TypeError(f"Invalid settings fields: {', '.join(sorted(invalid_fields))}")
            obj = cls(**clean)
        except (TypeError, ValueError):
            obj = cls()
            obj._load_error = "Invalid settings values; defaults are active and the original file is preserved."
            obj._read_only = True
        obj._extra = extra
        obj._schema_version = schema
        obj._read_only = obj._read_only or result.read_only or future
        obj._load_error = obj._load_error or result.error or (
            f"Settings schema {schema} is newer than this LeanDesk build; settings are read-only."
            if future
            else None
        )
        obj.autosave_seconds = max(10, min(3600, int(obj.autosave_seconds)))
        obj.default_zoom = max(50, min(200, int(obj.default_zoom)))
        obj.auto_check_updates = bool(obj.auto_check_updates)
        return obj

    @property
    def read_only(self) -> bool:
        return self._read_only

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def to_dict(self) -> dict[str, Any]:
        known = {
            "schema_version": self._schema_version,
            "theme": self.theme,
            "autosave_seconds": int(self.autosave_seconds),
            "default_zoom": int(self.default_zoom),
            "reopen_last_document": bool(self.reopen_last_document),
            "show_word_count": bool(self.show_word_count),
            "default_format": self.default_format,
            "live_spellcheck": bool(self.live_spellcheck),
            "sidebar_collapsed": bool(self.sidebar_collapsed),
            "auto_check_updates": bool(self.auto_check_updates),
        }
        return merge_known_and_extra(known, self._extra)

    def save(self, path: Path = SETTINGS_FILE) -> bool:
        if self._read_only:
            return False
        atomic_write_json(Path(path), self.to_dict())
        return True


@dataclass
class RecentEntry:
    path: str
    module: str
    opened_at: str
    display_name: str = ""
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecentEntry":
        known = {"path", "module", "opened_at", "display_name"}
        return cls(
            path=str(payload.get("path", "")),
            module=str(payload.get("module", "Writer")),
            opened_at=str(payload.get("opened_at", "")),
            display_name=str(payload.get("display_name", "")),
            extra={key: value for key, value in payload.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return merge_known_and_extra(
            {
                "path": self.path,
                "module": self.module,
                "opened_at": self.opened_at,
                "display_name": self.display_name,
            },
            self.extra,
        )


class RecentFiles:
    def __init__(self, path: Path = RECENT_FILE, limit: int = 30) -> None:
        self.path = Path(path)
        self.limit = max(1, min(500, int(limit)))
        self.entries: list[RecentEntry] = []
        self.read_only = False
        self.load_error: str | None = None
        self.load()

    def load(self) -> list[RecentEntry]:
        result = load_json_or_default(self.path, list, expected_type=list)
        rows = result.value if isinstance(result.value, list) else []
        self.read_only = result.read_only
        self.load_error = result.error
        self.entries = [
            RecentEntry.from_dict(row)
            for row in rows
            if isinstance(row, dict) and row.get("path")
        ][: self.limit]
        return list(self.entries)

    def save(self) -> bool:
        if self.read_only:
            return False
        atomic_write_json(self.path, [item.to_dict() for item in self.entries[: self.limit]])
        return True

    def add(self, path: str | Path, module: str = "Writer") -> None:
        resolved = str(Path(path).expanduser().resolve(strict=False))
        self.entries = [item for item in self.entries if os.path.normcase(item.path) != os.path.normcase(resolved)]
        self.entries.insert(
            0,
            RecentEntry(
                path=resolved,
                module=module,
                opened_at=datetime.now().isoformat(timespec="seconds"),
                display_name=Path(resolved).name,
            ),
        )
        self.entries = self.entries[: self.limit]
        self.save()

    def remove_missing(self) -> int:
        before = len(self.entries)
        self.entries = [item for item in self.entries if Path(item.path).exists()]
        if len(self.entries) != before:
            self.save()
        return before - len(self.entries)

    def clear(self) -> None:
        self.entries = []
        self.save()


@dataclass
class RecoveryRecord:
    recovery_id: str
    module: str
    title: str
    original_path: str
    saved_at: str
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = STORE_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RecoveryRecord":
        allowed = {"recovery_id", "module", "title", "original_path", "saved_at", "payload", "schema_version"}
        unknown = set(payload) - allowed
        if unknown:
            # Unknown fields in recovery records indicate incompatible/corrupt state.
            raise DataCorruptionError(f"Unknown recovery fields: {sorted(unknown)}")
        schema = payload.get("schema_version", STORE_SCHEMA_VERSION)
        if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
            raise DataCorruptionError("Invalid recovery schema version.")
        if schema > STORE_SCHEMA_VERSION:
            raise UnsupportedSchemaVersion(schema, STORE_SCHEMA_VERSION)
        required_strings = ("recovery_id", "module", "title", "original_path", "saved_at")
        if any(not isinstance(payload.get(name, ""), str) for name in required_strings):
            raise DataCorruptionError("Recovery record contains an invalid text field.")
        recovery_payload = payload.get("payload")
        if not isinstance(recovery_payload, dict):
            raise DataCorruptionError("Recovery record payload must be an object.")
        return cls(
            recovery_id=payload.get("recovery_id", ""),
            module=payload.get("module", ""),
            title=payload.get("title", ""),
            original_path=payload.get("original_path", ""),
            saved_at=payload.get("saved_at", ""),
            payload=recovery_payload,
            schema_version=schema,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": STORE_SCHEMA_VERSION,
            "recovery_id": self.recovery_id,
            "module": self.module,
            "title": self.title,
            "original_path": self.original_path,
            "saved_at": self.saved_at,
            "payload": self.payload,
        }


_RECOVERY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_ALLOWED_MODULES = {"Writer", "Sheets", "Slides", "Notes", "Draw", "Tasks", "Calendar", "Contacts"}


def _is_reparse(path: Path) -> bool:
    try:
        attrs = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


class RecoveryStore:
    def __init__(self, root: Path = RECOVERY_ROOT) -> None:
        self.root = Path(root)
        self.quarantine_root = self.root / "Quarantine"

    @staticmethod
    def validate_id(recovery_id: str) -> str:
        if not isinstance(recovery_id, str) or not _RECOVERY_ID.fullmatch(recovery_id):
            raise ValueError("Invalid recovery identifier.")
        if recovery_id.upper() in _WINDOWS_RESERVED:
            raise ValueError("Reserved recovery identifier.")
        return recovery_id

    def _resolved_root(self, *, create: bool = True) -> Path:
        if create:
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.exists():
            raise ValueError("Recovery directory is missing.")
        if self.root.is_symlink() or _is_reparse(self.root):
            raise ValueError("Recovery directory cannot be a symbolic link or reparse point.")
        resolved = self.root.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("Recovery root is not a directory.")
        return resolved

    def _path(self, recovery_id: str, *, create_root: bool = True) -> Path:
        identifier = self.validate_id(recovery_id)
        root = self._resolved_root(create=create_root)
        candidate = root / f"{identifier}.json"
        if candidate.parent.resolve(strict=True) != root:
            raise ValueError("Recovery path escaped its root.")
        if candidate.exists():
            info = candidate.lstat()
            if candidate.is_symlink() or _is_reparse(candidate) or not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
                raise ValueError("Recovery file is linked or non-regular.")
        return candidate

    def save(self, record: RecoveryRecord) -> Path:
        if record.module not in _ALLOWED_MODULES:
            raise ValueError("Unknown recovery module.")
        path = self._path(record.recovery_id)
        atomic_write_json(path, record.to_dict())
        return path

    def _quarantine_damaged(self, path: Path, reason: str) -> Path | None:
        return quarantine_move(path, reason, directory=self.quarantine_root)

    def list(self, module: str | None = None) -> list[RecoveryRecord]:
        if module is not None and module not in _ALLOWED_MODULES:
            raise ValueError("Unknown recovery module.")
        if not self.root.exists():
            return []
        root = self._resolved_root(create=False)
        records: list[RecoveryRecord] = []
        for entry in os.scandir(root):
            path = Path(entry.path)
            if entry.name == "Quarantine":
                continue
            if not entry.name.lower().endswith(".json"):
                continue
            try:
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    raise DataCorruptionError("Recovery member is linked or non-regular.")
                info = path.lstat()
                if _is_reparse(path) or info.st_nlink > 1:
                    raise DataCorruptionError("Recovery member is linked or multiply linked.")
                identifier = path.stem
                self.validate_id(identifier)
                payload = strict_json_load_bytes(read_bounded(path, limit=64 * 1024 * 1024))
                if not isinstance(payload, dict):
                    raise DataCorruptionError("Recovery payload is not an object.")
                row = RecoveryRecord.from_dict(payload)
                if row.recovery_id != identifier:
                    raise DataCorruptionError("Recovery identifier does not match its filename.")
                if row.module not in _ALLOWED_MODULES:
                    raise DataCorruptionError("Recovery record names an unsupported module.")
                if module is None or row.module == module:
                    records.append(row)
            except (DataBoundaryError, OSError, TypeError, ValueError) as exc:
                self._quarantine_damaged(path, type(exc).__name__)
        return sorted(records, key=lambda item: item.saved_at, reverse=True)

    def delete(self, recovery_id: str) -> None:
        # Validate first so traversal/device identifiers are always rejected, even when
        # the Recovery directory does not yet exist.
        self.validate_id(recovery_id)
        if not self.root.exists():
            return
        path = self._path(recovery_id, create_root=False)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def clear(self) -> None:
        if not self.root.exists():
            return
        for row in self.list():
            self.delete(row.recovery_id)
