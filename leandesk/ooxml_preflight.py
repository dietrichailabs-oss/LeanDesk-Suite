from __future__ import annotations

"""Shared bounded OOXML preflight for Writer, Sheets, and Slides.

Third-party Office parsers receive only an immutable in-memory copy after this module
has rejected ambiguous ZIP structure, unsafe paths, links/special entries, encryption,
resource-limit violations, malformed XML/relationships, and unsafe external targets.
"""

from dataclasses import dataclass
import io
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import time
from typing import BinaryIO, Callable, Literal
from urllib.parse import unquote, urlsplit
import unicodedata
import zipfile
from xml.etree import ElementTree as ET
from xml.parsers import expat

OOXMLKind = Literal["docx", "xlsx", "pptx"]
CancelCheck = Callable[[], bool]
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_REL_NS = {
    "http://schemas.openxmlformats.org/package/2006/relationships",
    "http://purl.oclc.org/ooxml/package/relationships",
}
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELATIONSHIP_CONTENT_TYPE = "application/vnd.openxmlformats-package.relationships+xml"
_MAIN_PARTS: dict[OOXMLKind, str] = {
    "docx": "word/document.xml",
    "xlsx": "xl/workbook.xml",
    "pptx": "ppt/presentation.xml",
}
_MAIN_REL_PARTS: dict[OOXMLKind, str | None] = {
    "docx": None,
    "xlsx": "xl/_rels/workbook.xml.rels",
    "pptx": "ppt/_rels/presentation.xml.rels",
}
_MEDIA_PREFIXES = ("word/media/", "xl/media/", "ppt/media/")
_ALLOWED_EXTERNAL_SCHEMES = {"http", "https", "mailto"}
_ALLOWED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


class OOXMLPreflightError(ValueError):
    pass


class OOXMLPreflightCancelled(OOXMLPreflightError):
    pass


class OOXMLPreflightTimeout(OOXMLPreflightError):
    pass


@dataclass(frozen=True)
class OOXMLLimits:
    max_archive_bytes: int = 128 * 1024 * 1024
    max_entries: int = 4096
    max_member_compressed_bytes: int = 64 * 1024 * 1024
    max_member_expanded_bytes: int = 64 * 1024 * 1024
    max_xml_bytes: int = 16 * 1024 * 1024
    max_media_bytes: int = 64 * 1024 * 1024
    max_total_expanded_bytes: int = 256 * 1024 * 1024
    max_total_xml_bytes: int = 64 * 1024 * 1024
    max_compression_ratio: float = 200.0
    max_xml_nodes: int = 500_000
    max_xml_depth: int = 256
    timeout_seconds: float = 8.0
    read_chunk_bytes: int = 1024 * 1024


DEFAULT_LIMITS = OOXMLLimits()


@dataclass(frozen=True)
class OOXMLPreflightReport:
    kind: OOXMLKind
    archive_bytes: int
    entries: int
    expanded_bytes: int
    xml_bytes: int
    relationship_files: int


@dataclass(frozen=True)
class PreparedOOXML:
    payload: bytes
    report: OOXMLPreflightReport

    def open(self) -> io.BytesIO:
        return io.BytesIO(self.payload)


@dataclass(frozen=True)
class _ContentTypeTable:
    overrides: dict[str, str]
    defaults: dict[str, str]

    def for_part(self, name: str) -> str | None:
        direct = self.overrides.get(name)
        if direct is not None:
            return direct
        leaf = PurePosixPath(name).name
        if leaf.startswith(".") and leaf.count(".") == 1:
            extension = leaf[1:]
        else:
            suffix = PurePosixPath(name).suffix
            extension = suffix[1:] if suffix else ""
        if not extension:
            return None
        return self.defaults.get(extension.casefold())


def _check_budget(*, deadline: float, cancel_check: CancelCheck | None, clock: Callable[[], float]) -> None:
    if cancel_check is not None:
        try:
            cancelled = bool(cancel_check())
        except Exception as exc:
            raise OOXMLPreflightCancelled("Office package validation was cancelled.") from exc
        if cancelled:
            raise OOXMLPreflightCancelled("Office package validation was cancelled.")
    if clock() > deadline:
        raise OOXMLPreflightTimeout("Office package validation exceeded its time limit.")


def _read_bounded_source(
    source: os.PathLike[str] | str | BinaryIO,
    *,
    limits: OOXMLLimits,
    deadline: float,
    cancel_check: CancelCheck | None,
    clock: Callable[[], float],
) -> bytes:
    chunks: list[bytes] = []
    total = 0

    def read_stream(stream: BinaryIO) -> None:
        nonlocal total
        while True:
            _check_budget(deadline=deadline, cancel_check=cancel_check, clock=clock)
            block = stream.read(limits.read_chunk_bytes)
            if not block:
                break
            if not isinstance(block, (bytes, bytearray, memoryview)):
                raise OOXMLPreflightError("Office package source did not return bytes.")
            data = bytes(block)
            total += len(data)
            if total > limits.max_archive_bytes:
                raise OOXMLPreflightError("Office package exceeds the compressed-size limit.")
            chunks.append(data)

    if isinstance(source, (str, os.PathLike)):
        supplied = Path(source).expanduser()
        supplied_info = supplied.lstat()
        supplied_attrs = getattr(supplied_info, "st_file_attributes", 0)
        if supplied.is_symlink() or supplied_attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise OOXMLPreflightError("Office package source must not be a link or reparse point.")
        path = supplied.resolve(strict=True)
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise OOXMLPreflightError("Office package source must be a regular local file.")
        if before.st_size <= 0 or before.st_size > limits.max_archive_bytes:
            raise OOXMLPreflightError("Office package is empty or exceeds the compressed-size limit.")
        with path.open("rb") as handle:
            read_stream(handle)
        after = path.lstat()
        before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_identity != after_identity or total != before.st_size:
            raise OOXMLPreflightError("Office package changed while it was being validated.")
    else:
        stream = source
        try:
            original_position = stream.tell()
        except Exception:
            original_position = None
        try:
            try:
                stream.seek(0)
            except Exception as exc:
                raise OOXMLPreflightError("Office package stream must be seekable.") from exc
            read_stream(stream)
        finally:
            if original_position is not None:
                try:
                    stream.seek(original_position)
                except Exception:
                    pass
    if total == 0:
        raise OOXMLPreflightError("Office package is empty.")
    return b"".join(chunks)


def _validate_component(component: str) -> None:
    if component in {"", ".", ".."}:
        raise OOXMLPreflightError("Office package contains a relative or empty path component.")
    if component[-1:] in {" ", "."}:
        raise OOXMLPreflightError("Office package contains a Windows-ambiguous path component.")
    if any(ord(char) < 32 or ord(char) == 127 for char in component):
        raise OOXMLPreflightError("Office package path contains control characters.")
    if ":" in component:
        raise OOXMLPreflightError("Office package path contains a drive or stream separator.")
    if component.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise OOXMLPreflightError("Office package path contains a reserved Windows device name.")


def _safe_member_name(name: str, *, is_directory: bool) -> str:
    if not isinstance(name, str) or not name or len(name) > 1024 or "\x00" in name:
        raise OOXMLPreflightError("Office package contains an invalid member name.")
    if "\\" in name or "//" in name:
        raise OOXMLPreflightError("Office package contains an ambiguous member separator.")
    if name.startswith(("/", "//", "\\", "\\\\", "\\?\\", "\\.\\")) or _DRIVE_PREFIX.match(name):
        raise OOXMLPreflightError("Office package contains an absolute or device-qualified member.")
    candidate = name[:-1] if is_directory and name.endswith("/") else name
    if not candidate or candidate.endswith("/"):
        raise OOXMLPreflightError("Office package contains an invalid directory member.")
    path = PurePosixPath(candidate)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise OOXMLPreflightError("Office package contains a traversal member.")
    for component in path.parts:
        _validate_component(component)
    return path.as_posix()


def _zip_is_link_or_special(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    return kind != 0 and kind not in {stat.S_IFREG, stat.S_IFDIR}


def _xml_local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_namespace(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") and "}" in tag else ""


def _expanded_xml_name(name: str) -> str:
    """Convert pyexpat namespace-expanded names to ElementTree notation."""

    return f"{{{name}" if "}" in name else name


def _parse_xml(
    name: str,
    payload: bytes,
    *,
    limits: OOXMLLimits,
    deadline: float,
    cancel_check: CancelCheck | None,
    clock: Callable[[], float],
) -> ET.Element:
    """Parse one XML part with DTD/entity processing disabled at parser level.

    ``pyexpat`` sees the declared XML encoding itself (including UTF-16), so the
    security decision does not depend on a raw ASCII prefix scan.  The handlers
    reject every DTD/entity entry point before a third-party Office parser can
    receive the package.  Node/depth and cancellation/deadline checks execute
    during parsing rather than only after a complete tree has been allocated.
    """

    root: ET.Element | None = None
    stack: list[ET.Element] = []
    node_count = 0

    def check() -> None:
        _check_budget(deadline=deadline, cancel_check=cancel_check, clock=clock)

    def start_element(raw_name: str, attributes: dict[str, str]) -> None:
        nonlocal root, node_count
        check()
        node_count += 1
        if node_count > limits.max_xml_nodes:
            raise OOXMLPreflightError(f"Office XML contains too many nodes: {name}")
        depth = len(stack) + 1
        if depth > limits.max_xml_depth:
            raise OOXMLPreflightError(f"Office XML nesting exceeds the safety limit: {name}")
        element = ET.Element(
            _expanded_xml_name(raw_name),
            {_expanded_xml_name(key): value for key, value in attributes.items()},
        )
        if stack:
            stack[-1].append(element)
        elif root is None:
            root = element
        else:
            raise OOXMLPreflightError(f"Office XML contains multiple document roots: {name}")
        stack.append(element)

    def end_element(_raw_name: str) -> None:
        check()
        if not stack:
            raise OOXMLPreflightError(f"Office XML has an invalid element boundary: {name}")
        stack.pop()

    def reject_declaration(*_args: object) -> None:
        raise OOXMLPreflightError(
            f"Office XML contains a forbidden DTD/entity declaration: {name}"
        )

    def reject_external_entity(*_args: object) -> int:
        reject_declaration()
        return 0

    try:
        parser = expat.ParserCreate(namespace_separator="}")
        parser.buffer_text = True
        parser.StartElementHandler = start_element
        parser.EndElementHandler = end_element
        parser.StartDoctypeDeclHandler = reject_declaration
        parser.EntityDeclHandler = reject_declaration
        parser.UnparsedEntityDeclHandler = reject_declaration
        parser.ExternalEntityRefHandler = reject_external_entity
        parser.SkippedEntityHandler = reject_declaration
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

        # Smaller XML feed chunks keep cancellation and deadline handling prompt
        # even when the ZIP read chunk is configured very large.
        feed_size = max(1024, min(int(limits.read_chunk_bytes), 64 * 1024))
        for offset in range(0, len(payload), feed_size):
            check()
            parser.Parse(payload[offset : offset + feed_size], False)
        check()
        parser.Parse(b"", True)
    except OOXMLPreflightError:
        raise
    except expat.ExpatError as exc:
        raise OOXMLPreflightError(f"Office XML is malformed: {name}") from exc
    except (UnicodeError, ValueError) as exc:
        raise OOXMLPreflightError(f"Office XML could not be decoded safely: {name}") from exc

    if root is None or stack:
        raise OOXMLPreflightError(f"Office XML is malformed: {name}")
    return root


def _relationship_source_part(rel_path: str) -> str:
    if rel_path == "_rels/.rels":
        return ""
    path = PurePosixPath(rel_path)
    if path.parent.name != "_rels" or not path.name.casefold().endswith(".rels"):
        raise OOXMLPreflightError(f"Malformed relationship-part location: {rel_path}")
    source_name = path.name[:-5]
    if not source_name:
        raise OOXMLPreflightError(f"Malformed relationship-part name: {rel_path}")
    return (path.parent.parent / source_name).as_posix()


def _resolve_internal_target(rel_path: str, target: str, rel_type: str) -> str | None:
    if not isinstance(target, str) or not target or len(target) > 2048 or "\x00" in target:
        raise OOXMLPreflightError(f"Relationship target is invalid in {rel_path}")
    decoded = unquote(target)
    if "\\" in decoded or any(ord(char) < 32 for char in decoded):
        raise OOXMLPreflightError(f"Relationship target is unsafe in {rel_path}")
    if rel_type.endswith("/hyperlink") and decoded.startswith("#"):
        return None
    split = urlsplit(decoded)
    if split.scheme or split.netloc or split.query:
        raise OOXMLPreflightError(f"Internal relationship target is not a package path in {rel_path}")
    if split.fragment and not rel_type.endswith("/hyperlink"):
        raise OOXMLPreflightError(f"Unexpected relationship fragment in {rel_path}")
    target_path = split.path
    base = posixpath.dirname(_relationship_source_part(rel_path))
    normalized = posixpath.normpath(target_path.lstrip("/")) if target_path.startswith("/") else posixpath.normpath(posixpath.join(base, target_path))
    if normalized in {"", ".", ".."} or normalized.startswith("../"):
        raise OOXMLPreflightError(f"Relationship target escapes the Office package in {rel_path}")
    return _safe_member_name(normalized, is_directory=False)


def _validate_external_target(rel_path: str, target: str, rel_type: str) -> None:
    if not rel_type.endswith("/hyperlink"):
        raise OOXMLPreflightError(f"Unsupported external relationship in {rel_path}")
    if not isinstance(target, str) or not target or len(target) > 2048:
        raise OOXMLPreflightError(f"External hyperlink target is invalid in {rel_path}")
    split = urlsplit(target)
    if split.scheme.casefold() not in _ALLOWED_EXTERNAL_SCHEMES:
        raise OOXMLPreflightError(f"External hyperlink uses an unsafe scheme in {rel_path}")
    if split.scheme.casefold() in {"http", "https"} and (not split.netloc or split.username is not None or split.password is not None):
        raise OOXMLPreflightError(f"External hyperlink host is invalid in {rel_path}")


def _validate_relationships(rel_path: str, root: ET.Element, *, member_names: set[str]) -> list[tuple[str, str, str | None]]:
    if _xml_local(root.tag) != "Relationships" or _xml_namespace(root.tag) not in _REL_NS:
        raise OOXMLPreflightError(f"Relationship XML has the wrong root/namespace: {rel_path}")
    identifiers: set[str] = set()
    rows: list[tuple[str, str, str | None]] = []
    for child in list(root):
        if _xml_local(child.tag) != "Relationship":
            raise OOXMLPreflightError(f"Unexpected element in relationship file: {rel_path}")
        rel_id, rel_type, target = child.attrib.get("Id"), child.attrib.get("Type"), child.attrib.get("Target")
        if not rel_id or not rel_type or not target or rel_id in identifiers:
            raise OOXMLPreflightError(f"Relationship entry is missing fields or duplicates an Id: {rel_path}")
        identifiers.add(rel_id)
        mode = child.attrib.get("TargetMode", "Internal")
        if mode == "External":
            _validate_external_target(rel_path, target, rel_type)
            resolved = None
        elif mode == "Internal":
            resolved = _resolve_internal_target(rel_path, target, rel_type)
            if resolved is not None and resolved not in member_names:
                raise OOXMLPreflightError(f"Relationship target is missing from the Office package: {rel_path} -> {resolved}")
        else:
            raise OOXMLPreflightError(f"Relationship TargetMode is invalid in {rel_path}")
        rows.append((rel_id, rel_type, resolved))
    return rows


def _valid_content_type(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) > 255:
        return False
    if any(ord(char) < 33 or ord(char) > 126 for char in value):
        return False
    # OOXML package content types are bare media types, not parameterized values.
    return bool(re.fullmatch(r"[A-Za-z0-9!#$&^_.+\-]+/[A-Za-z0-9!#$&^_.+\-]+", value))


def _is_xml_content_type(value: str) -> bool:
    normalized = value.casefold()
    return normalized in {"application/xml", "text/xml"} or normalized.endswith("+xml")


def _validate_content_types(
    root: ET.Element,
    *,
    member_names: set[str],
    main_part: str,
) -> _ContentTypeTable:
    """Validate and materialize the semantic content-type map for every part."""

    if _xml_local(root.tag) != "Types" or _xml_namespace(root.tag) != _CONTENT_TYPES_NS:
        raise OOXMLPreflightError("[Content_Types].xml has the wrong root or namespace.")
    override_keys: set[str] = set()
    default_keys: set[str] = set()
    overrides: dict[str, str] = {}
    defaults: dict[str, str] = {}
    main_found = False
    for child in list(root):
        local = _xml_local(child.tag)
        if local == "Override":
            part_name, content_type = child.attrib.get("PartName"), child.attrib.get("ContentType")
            if (
                not part_name
                or not content_type
                or not part_name.startswith("/")
                or not _valid_content_type(content_type)
            ):
                raise OOXMLPreflightError("Content type override is malformed.")
            normalized = _safe_member_name(part_name.lstrip("/"), is_directory=False)
            key = unicodedata.normalize("NFC", normalized).casefold()
            if key in override_keys:
                raise OOXMLPreflightError("Content type overrides contain a duplicate/case collision.")
            override_keys.add(key)
            if normalized not in member_names:
                raise OOXMLPreflightError(f"Content type override points to a missing part: {normalized}")
            overrides[normalized] = content_type
            if normalized == main_part:
                main_found = True
        elif local == "Default":
            extension, content_type = child.attrib.get("Extension"), child.attrib.get("ContentType")
            if (
                not extension
                or not content_type
                or any(char in extension for char in "/\\:")
                or extension.startswith(".")
                or any(ord(char) < 33 or ord(char) > 126 for char in extension)
                or not _valid_content_type(content_type)
            ):
                raise OOXMLPreflightError("Content type default is malformed.")
            key = unicodedata.normalize("NFC", extension).casefold()
            if key in default_keys:
                raise OOXMLPreflightError("Content type defaults contain a duplicate/case collision.")
            default_keys.add(key)
            defaults[key] = content_type
        else:
            raise OOXMLPreflightError("[Content_Types].xml contains an unexpected element.")
    if not main_found:
        raise OOXMLPreflightError("The main Office document part has no content type override.")

    table = _ContentTypeTable(overrides=overrides, defaults=defaults)
    missing = sorted(
        name for name in member_names
        if name != "[Content_Types].xml" and table.for_part(name) is None
    )
    if missing:
        raise OOXMLPreflightError(
            "Office package parts are missing semantic content types: " + ", ".join(missing[:8])
        )
    return table


def prepare_ooxml(
    source: os.PathLike[str] | str | BinaryIO,
    kind: OOXMLKind,
    *,
    limits: OOXMLLimits = DEFAULT_LIMITS,
    cancel_check: CancelCheck | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> PreparedOOXML:
    """Return an immutable OOXML payload only after semantic package preflight.

    XML policy is selected from the package content-type table as well as the member
    name.  XML declared under ``.dat``, extensionless, mixed-case, or default-mapped
    names therefore receives the same DTD/entity, resource, timeout, and cancellation
    protections as conventional ``.xml`` parts.
    """

    if kind not in _MAIN_PARTS:
        raise ValueError(f"Unsupported OOXML kind: {kind!r}")
    deadline = clock() + max(0.05, float(limits.timeout_seconds))
    payload = _read_bounded_source(
        source,
        limits=limits,
        deadline=deadline,
        cancel_check=cancel_check,
        clock=clock,
    )

    xml_roots: dict[str, ET.Element] = {}
    member_names: set[str] = set()
    exact_names: set[str] = set()
    folded_names: set[str] = set()
    info_by_name: dict[str, zipfile.ZipInfo] = {}
    expanded_total = 0
    xml_total = 0
    relationship_files = 0
    relationship_parts: set[str] = set()

    def read_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, canonical: str, *, collect: bool) -> bytes:
        read_total = 0
        chunks: list[bytes] | None = [] if collect else None
        with archive.open(info, "r") as handle:
            while True:
                _check_budget(deadline=deadline, cancel_check=cancel_check, clock=clock)
                block = handle.read(limits.read_chunk_bytes)
                if not block:
                    break
                read_total += len(block)
                if read_total > info.file_size or read_total > limits.max_member_expanded_bytes:
                    raise OOXMLPreflightError(
                        f"Office member expanded beyond its declared/safe size: {canonical}"
                    )
                if chunks is not None:
                    chunks.append(block)
        if read_total != info.file_size:
            raise OOXMLPreflightError(f"Office package member size is inconsistent: {canonical}")
        return b"".join(chunks or ())

    try:
        with zipfile.ZipFile(io.BytesIO(payload), "r") as archive:
            infos = archive.infolist()
            if not infos or len(infos) > limits.max_entries:
                raise OOXMLPreflightError("Office package has no members or too many members.")

            # Pass 1: reject ambiguous/unsafe ZIP structure and capture exact metadata.
            for info in infos:
                _check_budget(deadline=deadline, cancel_check=cancel_check, clock=clock)
                # Windows zipfile normalizes backslashes in ``filename``. Validate
                # the preserved archive spelling so ambiguous raw separators cannot
                # become silently accepted package paths.
                raw_name = getattr(info, "orig_filename", info.filename)
                canonical = _safe_member_name(raw_name, is_directory=info.is_dir())
                folded = unicodedata.normalize("NFC", canonical).casefold()
                if canonical in exact_names:
                    raise OOXMLPreflightError(f"Office package contains an exact duplicate member: {canonical}")
                if folded in folded_names:
                    raise OOXMLPreflightError(
                        f"Office package contains a case/Unicode-colliding member: {canonical}"
                    )
                exact_names.add(canonical)
                folded_names.add(folded)
                if _zip_is_link_or_special(info):
                    raise OOXMLPreflightError(f"Office package contains a linked or special member: {canonical}")
                if info.flag_bits & 0x1:
                    raise OOXMLPreflightError(f"Office package contains an encrypted member: {canonical}")
                if info.compress_type not in _ALLOWED_COMPRESSION:
                    raise OOXMLPreflightError(
                        f"Office package uses an unsupported compression method: {canonical}"
                    )
                if info.compress_size < 0 or info.compress_size > limits.max_member_compressed_bytes:
                    raise OOXMLPreflightError(
                        f"Office package member exceeds the compressed-size limit: {canonical}"
                    )
                if info.file_size < 0 or info.file_size > limits.max_member_expanded_bytes:
                    raise OOXMLPreflightError(
                        f"Office package member exceeds the expansion limit: {canonical}"
                    )
                if info.file_size and info.compress_size == 0:
                    raise OOXMLPreflightError(
                        f"Office package member has invalid compression metadata: {canonical}"
                    )
                if info.compress_size and info.file_size / max(1, info.compress_size) > limits.max_compression_ratio:
                    raise OOXMLPreflightError(
                        f"Office package member exceeds the compression-ratio limit: {canonical}"
                    )
                if info.is_dir():
                    continue
                member_names.add(canonical)
                info_by_name[canonical] = info
                # Preserve the historical early media budget gate even for a
                # malformed package whose newly added media part has no content
                # type declaration.  Semantic mapping is still enforced later,
                # but an oversized media member must never be read or masked by
                # a subsequent content-type error.
                if (
                    canonical.casefold().startswith(_MEDIA_PREFIXES)
                    and info.file_size > limits.max_media_bytes
                ):
                    raise OOXMLPreflightError(
                        f"Office media part exceeds the media size limit: {canonical}"
                    )
                expanded_total += info.file_size
                if expanded_total > limits.max_total_expanded_bytes:
                    raise OOXMLPreflightError("Office package exceeds the total expansion limit.")

            required = {"[Content_Types].xml", "_rels/.rels", _MAIN_PARTS[kind]}
            missing = sorted(required - member_names)
            if missing:
                raise OOXMLPreflightError(
                    f"Office package is missing required parts: {', '.join(missing)}"
                )
            main_rel = _MAIN_REL_PARTS[kind]
            if main_rel is not None and main_rel not in member_names:
                raise OOXMLPreflightError(
                    f"Office package is missing its main relationship part: {main_rel}"
                )

            # Pass 2 begins with the authoritative semantic map.  This part is always
            # protected XML regardless of what any filename/default declaration says.
            content_info = info_by_name["[Content_Types].xml"]
            if content_info.file_size > limits.max_xml_bytes:
                raise OOXMLPreflightError("[Content_Types].xml exceeds the XML size limit.")
            content_payload = read_member(
                archive, content_info, "[Content_Types].xml", collect=True
            )
            xml_total = len(content_payload)
            if xml_total > limits.max_total_xml_bytes:
                raise OOXMLPreflightError("Office package exceeds the total XML budget.")
            content_root = _parse_xml(
                "[Content_Types].xml",
                content_payload,
                limits=limits,
                deadline=deadline,
                cancel_check=cancel_check,
                clock=clock,
            )
            xml_roots["[Content_Types].xml"] = content_root
            content_types = _validate_content_types(
                content_root,
                member_names=member_names,
                main_part=_MAIN_PARTS[kind],
            )

            # Pass 3: stream every member and parse every semantically XML part.
            for canonical, info in info_by_name.items():
                if canonical == "[Content_Types].xml":
                    continue
                _check_budget(deadline=deadline, cancel_check=cancel_check, clock=clock)
                content_type = content_types.for_part(canonical)
                if content_type is None:  # guarded by table validation; defense in depth
                    raise OOXMLPreflightError(
                        f"Office package part has no semantic content type: {canonical}"
                    )
                folded_name = canonical.casefold()
                name_xml = folded_name.endswith((".xml", ".rels"))
                semantic_xml = _is_xml_content_type(content_type)
                semantic_relationship = content_type.casefold() == _RELATIONSHIP_CONTENT_TYPE
                if name_xml and not semantic_xml:
                    raise OOXMLPreflightError(
                        f"Office XML-named part is declared as non-XML: {canonical}"
                    )
                if folded_name.endswith(".rels") and not semantic_relationship:
                    raise OOXMLPreflightError(
                        f"Office relationship-named part has the wrong content type: {canonical}"
                    )
                is_xml = name_xml or semantic_xml
                is_media = canonical.casefold().startswith(_MEDIA_PREFIXES)
                if is_xml and info.file_size > limits.max_xml_bytes:
                    raise OOXMLPreflightError(
                        f"Office XML part exceeds the XML size limit: {canonical}"
                    )
                if is_media and info.file_size > limits.max_media_bytes:
                    raise OOXMLPreflightError(
                        f"Office media part exceeds the media size limit: {canonical}"
                    )
                member_payload = read_member(archive, info, canonical, collect=is_xml)
                if is_xml:
                    xml_total += len(member_payload)
                    if xml_total > limits.max_total_xml_bytes:
                        raise OOXMLPreflightError("Office package exceeds the total XML budget.")
                    xml_roots[canonical] = _parse_xml(
                        canonical,
                        member_payload,
                        limits=limits,
                        deadline=deadline,
                        cancel_check=cancel_check,
                        clock=clock,
                    )
                    if semantic_relationship:
                        relationship_parts.add(canonical)
                        relationship_files += 1
    except OOXMLPreflightError:
        raise
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError) as exc:
        raise OOXMLPreflightError(
            f"Office package is not a valid bounded ZIP container: {type(exc).__name__}"
        ) from exc

    root_relationships = None
    for rel_path in sorted(relationship_parts):
        root = xml_roots.get(rel_path)
        if root is None:  # semantic relationship parts must always take the protected XML path
            raise OOXMLPreflightError(f"Relationship part was not securely parsed: {rel_path}")
        rows = _validate_relationships(rel_path, root, member_names=member_names)
        if rel_path == "_rels/.rels":
            root_relationships = rows
    if root_relationships is None:
        raise OOXMLPreflightError("Office package root relationships are missing or malformed.")
    office_targets = [
        target
        for _, rel_type, target in root_relationships
        if rel_type.endswith("/officeDocument") and target is not None
    ]
    if office_targets != [_MAIN_PARTS[kind]]:
        raise OOXMLPreflightError(
            "Office package root relationship does not identify exactly one expected main part."
        )
    _check_budget(deadline=deadline, cancel_check=cancel_check, clock=clock)
    return PreparedOOXML(
        payload,
        OOXMLPreflightReport(
            kind,
            len(payload),
            len(exact_names),
            expanded_total,
            xml_total,
            relationship_files,
        ),
    )
