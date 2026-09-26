from __future__ import annotations

"""LeanDesk Writer native and text-format boundaries.

The native ``.ldoc`` loader is deliberately strict: duplicate JSON keys, malformed
UTF-8, unsupported future versions, invalid tag rows, and oversized payloads are
controlled errors.  The loader never rewrites an input file.  Unknown fields from a
supported schema are retained so a normal round trip does not silently discard data.
"""

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .core import atomic_write_text
from .rtf_codec import plain_to_rtf, rtf_to_plain
from .data_boundary import (
    DataCorruptionError,
    UnsupportedSchemaVersion,
    merge_known_and_extra,
    read_bounded,
    strict_json_load_bytes,
)

NATIVE_FORMAT_VERSION = 1
MAX_NATIVE_BYTES = 32 * 1024 * 1024
MAX_TEXT_BYTES = 64 * 1024 * 1024
MAX_TAGS = 250_000


@dataclass
class TagRange:
    tag: str
    start: str
    end: str
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TagRange":
        if not all(isinstance(payload.get(k), str) for k in ("tag", "start", "end")):
            raise DataCorruptionError("Invalid formatting range in LeanDesk document.")
        known = {"tag", "start", "end"}
        return cls(
            tag=payload["tag"],
            start=payload["start"],
            end=payload["end"],
            extra={k: v for k, v in payload.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return merge_known_and_extra(
            {"tag": self.tag, "start": self.start, "end": self.end}, self.extra
        )


@dataclass
class LeanDocument:
    title: str = "Untitled Document"
    text: str = ""
    tags: list[TagRange] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    format_version: int = NATIVE_FORMAT_VERSION
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "LeanDocument":
        if not isinstance(payload, dict):
            raise DataCorruptionError("Invalid LeanDesk document root.")
        raw_version = payload.get("format_version", NATIVE_FORMAT_VERSION)
        if isinstance(raw_version, bool) or not isinstance(raw_version, int) or raw_version < 1:
            raise DataCorruptionError("Invalid LeanDesk document format version.")
        if raw_version > NATIVE_FORMAT_VERSION:
            raise UnsupportedSchemaVersion(raw_version, NATIVE_FORMAT_VERSION)

        raw_title = payload.get("title", "Untitled Document")
        raw_text = payload.get("text", "")
        raw_tags = payload.get("tags", [])
        raw_metadata = payload.get("metadata", {})
        if not isinstance(raw_title, str) or not isinstance(raw_text, str):
            raise DataCorruptionError("LeanDesk document title/text must be strings.")
        if not isinstance(raw_tags, list) or len(raw_tags) > MAX_TAGS:
            raise DataCorruptionError("LeanDesk document formatting data is invalid or too large.")
        if not isinstance(raw_metadata, dict):
            raise DataCorruptionError("LeanDesk document metadata must be an object.")

        tags: list[TagRange] = []
        for row in raw_tags:
            if not isinstance(row, dict):
                raise DataCorruptionError("LeanDesk document contains an invalid formatting range.")
            tags.append(TagRange.from_dict(row))

        known = {"title", "text", "tags", "metadata", "format_version"}
        return cls(
            title=raw_title,
            text=raw_text,
            tags=tags,
            metadata=dict(raw_metadata),
            format_version=raw_version,
            extra={k: v for k, v in payload.items() if k not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return merge_known_and_extra(
            {
                "format_version": NATIVE_FORMAT_VERSION,
                "title": self.title,
                "text": self.text,
                "tags": [row.to_dict() for row in self.tags],
                "metadata": dict(self.metadata),
            },
            self.extra,
        )


def save_native(document: LeanDocument, path: Path) -> None:
    import json

    if document.format_version > NATIVE_FORMAT_VERSION:
        raise UnsupportedSchemaVersion(document.format_version, NATIVE_FORMAT_VERSION)
    atomic_write_text(
        Path(path),
        json.dumps(document.to_dict(), indent=2, ensure_ascii=False, sort_keys=False),
    )


def load_native(path: Path) -> LeanDocument:
    payload = strict_json_load_bytes(read_bounded(Path(path), limit=MAX_NATIVE_BYTES))
    if not isinstance(payload, dict):
        raise DataCorruptionError("Invalid LeanDesk document.")
    return LeanDocument.from_dict(payload)


def plain_to_html(text: str, title: str = "Document") -> str:
    paragraphs = text.split("\n\n")
    body = []
    for paragraph in paragraphs:
        escaped = html.escape(paragraph).replace("\n", "<br>\n")
        body.append(f"<p>{escaped}</p>")
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ max-width: 850px; margin: 48px auto; padding: 0 24px; font-family: Arial, sans-serif; line-height: 1.55; color: #202124; }}
p {{ margin: 0 0 1em; }}
</style>
</head>
<body>
{body}
</body>
</html>
""".format(title=html.escape(title), body="\n".join(body))


class _TextHTMLParser(HTMLParser):
    BLOCKS = {"p", "div", "h1", "h2", "h3", "li", "br", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "li":
            self.parts.append("• ")
        elif tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self.BLOCKS and (not self.parts or not self.parts[-1].endswith("\n")):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        value = "".join(self.parts)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return html.unescape(value).strip()


def html_to_plain(source: str) -> str:
    parser = _TextHTMLParser()
    parser.feed(source)
    parser.close()
    return parser.text()


def _read_text(path: Path) -> str:
    data = read_bounded(Path(path), limit=MAX_TEXT_BYTES)
    return data.decode("utf-8", errors="replace")


def read_text_document(path: Path) -> LeanDocument:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".ldoc":
        return load_native(path)
    if suffix == ".rtf":
        data = read_bounded(path, limit=MAX_TEXT_BYTES)
        return LeanDocument(title=path.stem, text=rtf_to_plain(data))
    raw = _read_text(path)
    if suffix in {".html", ".htm"}:
        return LeanDocument(title=path.stem, text=html_to_plain(raw))
    return LeanDocument(title=path.stem, text=raw)


def write_text_document(document: LeanDocument, path: Path) -> None:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".ldoc":
        save_native(document, path)
    elif suffix in {".html", ".htm"}:
        atomic_write_text(path, plain_to_html(document.text, document.title))
    elif suffix == ".rtf":
        atomic_write_text(path, plain_to_rtf(document.text))
    else:
        atomic_write_text(path, document.text)
