from __future__ import annotations

"""Central write-boundary policy for imported and native LeanDesk documents."""

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Callable, Iterator


class SavePolicyError(RuntimeError):
    pass


class ImportedSourceProtectionError(SavePolicyError):
    pass


class UnsupportedSaveFormatError(SavePolicyError):
    pass


@dataclass(frozen=True)
class ModuleSavePolicy:
    module: str
    native_extensions: frozenset[str]
    writable_extensions: frozenset[str]
    export_only_extensions: frozenset[str] = frozenset()


POLICIES: dict[str, ModuleSavePolicy] = {
    "Writer": ModuleSavePolicy(
        "Writer",
        frozenset({".ldoc"}),
        frozenset({".ldoc", ".docx", ".txt", ".md", ".html", ".htm", ".rtf"}),
        frozenset({".pdf"}),
    ),
    "Sheets": ModuleSavePolicy(
        "Sheets",
        frozenset({".lsheet"}),
        frozenset({".lsheet", ".xlsx"}),
        frozenset({".csv"}),
    ),
    "Slides": ModuleSavePolicy(
        "Slides",
        frozenset({".ldeck"}),
        frozenset({".ldeck", ".pptx"}),
    ),
    "Draw": ModuleSavePolicy(
        "Draw",
        frozenset({".ldraw"}),
        frozenset({".ldraw"}),
        frozenset({".png", ".svg"}),
    ),
}


def policy_for(module: str) -> ModuleSavePolicy:
    try:
        return POLICIES[module]
    except KeyError as exc:
        raise SavePolicyError(f"Unknown save policy module: {module}") from exc


def canonical_path(path: os.PathLike[str] | str) -> Path:
    value = Path(path).expanduser()
    try:
        return value.resolve(strict=False)
    except OSError:
        return Path(os.path.abspath(os.fspath(value)))


def same_file_identity(left: os.PathLike[str] | str, right: os.PathLike[str] | str) -> bool:
    a = canonical_path(left)
    b = canonical_path(right)
    try:
        if a.exists() and b.exists() and os.path.samefile(a, b):
            return True
    except OSError:
        pass
    a_text = os.path.normcase(os.path.normpath(os.fspath(a)))
    b_text = os.path.normcase(os.path.normpath(os.fspath(b)))
    if os.name == "nt":
        return a_text.casefold() == b_text.casefold()
    return a_text == b_text


def is_native_path(module: str, path: os.PathLike[str] | str | None) -> bool:
    if path is None:
        return False
    return Path(path).suffix.lower() in policy_for(module).native_extensions


def imported_source_for(module: str, path: os.PathLike[str] | str | None) -> Path | None:
    if path is None:
        return None
    candidate = canonical_path(path)
    if candidate.suffix.lower() in policy_for(module).native_extensions:
        return None
    return candidate


def validate_destination(
    module: str,
    destination: os.PathLike[str] | str,
    *,
    imported_source: os.PathLike[str] | str | None = None,
    allow_export_only: bool = False,
) -> Path:
    policy = policy_for(module)
    dest = canonical_path(destination)
    suffix = dest.suffix.lower()
    allowed = set(policy.writable_extensions)
    if allow_export_only:
        allowed.update(policy.export_only_extensions)
    if suffix not in allowed:
        import_only = sorted(
            ext for ext in {
                ".doc", ".docm", ".dot", ".dotx", ".dotm", ".odt", ".ott", ".wps", ".wpd", ".abw", ".sxw", ".lwp", ".cwk", ".pages",
                ".xls", ".xlsm", ".xlsb", ".ods", ".ots", ".tsv", ".dif", ".dbf", ".numbers", ".123", ".wk1", ".wk3", ".wk4", ".wks",
                ".ppt", ".pptm", ".pps", ".ppsx", ".odp", ".otp", ".sxi", ".key",
            }
            if ext not in allowed
        )
        if suffix in import_only:
            raise UnsupportedSaveFormatError(
                f"{suffix or 'That format'} is import-only in LeanDesk {module}. "
                "Choose a LeanDesk-native or supported export format instead."
            )
        raise UnsupportedSaveFormatError(
            f"LeanDesk {module} cannot write {suffix or 'a file without an extension'}."
        )
    if imported_source is not None and same_file_identity(dest, imported_source):
        raise ImportedSourceProtectionError(
            "The original imported file is protected. Choose a different filename or folder so LeanDesk can save a new copy."
        )
    if dest.exists() and dest.is_dir():
        raise SavePolicyError("The selected destination is a folder, not a file.")
    return dest


@contextmanager
def atomic_destination(destination: os.PathLike[str] | str) -> Iterator[Path]:
    """Yield a same-directory temporary path and atomically replace on success."""
    dest = canonical_path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f".{dest.stem}.",
        suffix=f".tmp{dest.suffix}",
        dir=str(dest.parent),
    )
    os.close(fd)
    temp_path = Path(name)
    try:
        yield temp_path
        if not temp_path.is_file():
            raise SavePolicyError("The save operation did not produce an output file.")
        with temp_path.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temp_path, dest)
        try:
            directory_fd = os.open(dest.parent, os.O_RDONLY)
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
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def write_atomically(destination: os.PathLike[str] | str, writer: Callable[[Path], None]) -> Path:
    dest = canonical_path(destination)
    with atomic_destination(dest) as temporary:
        writer(temporary)
    return dest


def mark_save_boundary(function):
    """Attach the historical QA marker without method-name monkeypatching."""
    function.__leandesk_import_save_guard__ = True
    function.__leandesk_save_policy_boundary__ = True
    return function
