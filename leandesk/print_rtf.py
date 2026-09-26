"""Bounded Writer print serialization retaining embedded table positions.

This is a print boundary, not the deliberately plain-text RTF import/export codec.
Unsupported embedded content fails before a printer is offered, never disappears.
"""
from bisect import bisect_right

from .rtf_codec import MAX_RTF_BYTES


def _text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("Printable text must be a string.")
    parts = []
    for char in value.replace("\r\n", "\n").replace("\r", "\n"):
        if char in "\\{}":
            parts.append("\\" + char)
        elif char == "\n":
            parts.append(r"\line ")
        elif char == "\t":
            parts.append(r"\tab ")
        elif 32 <= ord(char) <= 126:
            parts.append(char)
        else:
            encoded = char.encode("utf-16-le", errors="strict")
            for offset in range(0, len(encoded), 2):
                unit = int.from_bytes(encoded[offset:offset + 2], "little", signed=True)
                parts.append(f"\\u{unit}?")
    return "".join(parts)


def writer_print_rtf(document) -> str:
    """Create WPF-readable paragraphs and bordered RTF tables, in Writer order."""
    if not isinstance(document.text, str) or not isinstance(document.metadata, dict):
        raise ValueError("Invalid Writer print document.")
    objects = document.metadata.get("objects", [])
    if not isinstance(objects, list) or len(objects) > 10000:
        raise ValueError("Invalid or excessive embedded print objects.")
    lines = document.text.split("\n")
    by_line = {}
    for ordinal, item in enumerate(objects):
        if not isinstance(item, dict) or item.get("kind") != "table":
            raise ValueError("An embedded object is not supported by direct printing; export a PDF instead.")
        rows, cols = item.get("rows"), item.get("cols")
        if type(rows) is not int or type(cols) is not int or not 1 <= rows <= 1000 or not 1 <= cols <= 63:
            raise ValueError("Print tables require 1-1000 rows and 1-63 columns.")
        data = item.get("data", [])
        if not isinstance(data, list) or len(data) != rows or any(not isinstance(row, list) or len(row) != cols for row in data):
            raise ValueError("Print table dimensions do not match its cell data.")
        position = str(item.get("index", "end-1c")).split(".")
        if len(position) == 2 and all(part.isdigit() for part in position):
            line_no = max(1, min(len(lines), int(position[0])))
            column = int(position[1])
        else:
            line_no = len(lines)
            column = len(lines[-1].encode("utf-16-le")) // 2 + len(objects)
        by_line.setdefault(line_no, []).append((column, ordinal, item))

    parts = [r"{\rtf1\ansi\ansicpg1252\deff0\uc1", "\n",
             r"{\fonttbl{\f0\fnil\fcharset0 Segoe UI;}}", "\n"]
    size = sum(map(len, parts))

    def append(value):
        nonlocal size
        size += len(value)
        if size > MAX_RTF_BYTES:
            raise ValueError("Printable RTF exceeds the 64 MiB safety limit.")
        parts.append(value)

    def paragraph(value):
        append(r"\pard\f0\fs22 " + _text(value) + "\\par\n")

    for line_no, line in enumerate(lines, 1):
        events = sorted(by_line.get(line_no, []), key=lambda row: row[:2])
        boundaries = [0]
        for char in line:
            boundaries.append(boundaries[-1] + len(char.encode("utf-16-le")) // 2)
        cursor = 0
        for window_slots, (column, _, item) in enumerate(events):
            offset = max(cursor, min(len(line), bisect_right(boundaries, max(0, column - window_slots)) - 1))
            if offset > cursor:
                paragraph(line[cursor:offset])
            cursor = offset
            cols = item["cols"]
            for row in item["data"]:
                append(r"\trowd\trgaph108\trleft0 ")
                for col in range(cols):
                    append(r"\clbrdrt\brdrs\brdrw10\clbrdrl\brdrs\brdrw10"
                           r"\clbrdrb\brdrs\brdrw10\clbrdrr\brdrs\brdrw10"
                           + f"\\cellx{round(9000 * (col + 1) / cols)} ")
                for value in row:
                    append(r"\pard\intbl\f0\fs22 " + _text(str(value)) + r"\cell ")
                append("\\row\n")
            append(r"\pard ")
        if cursor < len(line) or not events:
            paragraph(line[cursor:])
    append("}")
    return "".join(parts)
