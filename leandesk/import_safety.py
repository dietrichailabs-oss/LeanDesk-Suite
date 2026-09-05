from __future__ import annotations

"""Compatibility facade for the old Correction-1 import guard API.

Current modules enforce policy at their final write boundary through save_policy.py.
This module remains so older integrations/tests receive the same controlled exception.
"""

import os
from pathlib import Path
from typing import Any

from .save_policy import (
    ImportedSourceProtectionError,
    SavePolicyError,
    UnsupportedSaveFormatError,
    imported_source_for,
    mark_save_boundary,
    same_file_identity,
)

FOREIGN_WRITER = {".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm", ".odt", ".ott", ".rtf", ".txt", ".md", ".html", ".htm", ".wps", ".wpd", ".abw", ".sxw", ".lwp", ".cwk", ".pages"}
FOREIGN_SHEETS = {".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".ots", ".csv", ".tsv", ".dif", ".dbf", ".numbers", ".123", ".wk1", ".wk3", ".wk4", ".wks"}
FOREIGN_SLIDES = {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".odp", ".otp", ".sxi", ".key"}
FOREIGN = FOREIGN_WRITER | FOREIGN_SHEETS | FOREIGN_SLIDES
NATIVE = {".ldoc", ".lsheet", ".ldeck", ".ldraw"}


def _path_from_object(obj: Any) -> Path | None:
    for name in (
        "imported_source_path",
        "source_path",
        "current_file",
        "current_path",
        "file_path",
        "filename",
        "document_path",
        "path",
    ):
        value = getattr(obj, name, None)
        if isinstance(value, (str, os.PathLike)) and str(value):
            try:
                return Path(value).expanduser().resolve(strict=False)
            except Exception:
                continue
    return None


def _explicit_destination(args, kwargs) -> Path | None:
    for key in ("destination", "dest", "path", "filename", "file_path", "output_path", "target"):
        value = kwargs.get(key)
        if isinstance(value, (str, os.PathLike)) and str(value):
            return Path(value).expanduser().resolve(strict=False)
    for value in args[1:]:
        if isinstance(value, (str, os.PathLike)) and str(value):
            return Path(value).expanduser().resolve(strict=False)
    return None


def _wrap_save(fn):
    if getattr(fn, "__leandesk_import_save_guard__", False):
        return fn

    @mark_save_boundary
    def guarded(*args, **kwargs):
        obj = args[0] if args else None
        source = _path_from_object(obj) if obj is not None else None
        destination = _explicit_destination(args, kwargs)
        if source and source.suffix.lower() in FOREIGN:
            if destination is None or same_file_identity(destination, source):
                raise ImportedSourceProtectionError(
                    "Imported documents are protected. Use Save As/Export to a new file; "
                    "LeanDesk will not overwrite the foreign source during ordinary Save."
                )
        return fn(*args, **kwargs)

    guarded.__name__ = getattr(fn, "__name__", "guarded")
    guarded.__doc__ = getattr(fn, "__doc__", None)
    return guarded


def install_save_guards(namespace: dict[str, Any]) -> None:
    """Legacy opt-in wrapper; current LeanDesk modules do not depend on it."""
    save_names = {
        "save",
        "save_file",
        "save_document",
        "save_current",
        "on_save",
        "_save",
        "_save_file",
        "_save_document",
        "save_as",
        "_write",
        "_write_to",
    }
    for obj in list(namespace.values()):
        if not isinstance(obj, type):
            continue
        for attr in dir(obj):
            if attr.lower() in save_names:
                raw = getattr(obj, attr, None)
                if callable(raw):
                    setattr(obj, attr, _wrap_save(raw))


__all__ = [
    "FOREIGN_WRITER",
    "FOREIGN_SHEETS",
    "FOREIGN_SLIDES",
    "FOREIGN",
    "NATIVE",
    "ImportedSourceProtectionError",
    "SavePolicyError",
    "UnsupportedSaveFormatError",
    "install_save_guards",
]
