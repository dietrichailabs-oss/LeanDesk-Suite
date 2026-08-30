from __future__ import annotations

"""Bounded plain-text RTF import/export for LeanDesk Writer.

The codec intentionally imports text rather than attempting to preserve every RTF
formatting feature. It implements destination groups, code pages, hex escapes,
``\\ucN`` fallback counts, signed ``\\uN`` UTF-16 code units, surrogate pairs,
escaped punctuation, and common paragraph/text control words. Output is ASCII-only
RTF with explicit Unicode escapes so Word and LibreOffice read it consistently.
"""

from dataclasses import dataclass, replace
import codecs


class RTFFormatError(ValueError):
    """Controlled failure for malformed or unsupported RTF input."""


MAX_RTF_BYTES = 64 * 1024 * 1024
MAX_GROUP_DEPTH = 512
MAX_CONTROL_WORD = 96
MAX_UC_SKIP = 32

_SKIP_DESTINATIONS = {
    "annotation", "atnauthor", "atndate", "atnid", "atnparent", "author",
    "buptim", "category", "colortbl", "colorschememapping", "comment",
    "company", "creatim", "datafield", "datastore", "doccomm", "docvar",
    "factoidname", "falt", "file", "filetbl", "fldinst", "fontemb",
    "fontfile", "fonttbl", "footer", "footerf", "footerl", "footerr",
    "footnote", "generator", "header", "headerf", "headerl", "headerr",
    "hlinkbase", "htmltag", "info", "keywords", "latentstyles", "list",
    "listlevel", "listname", "listoverride", "listoverridetable", "listpicture",
    "listtable", "manager", "mmathpr", "nonshppict", "objalias", "objclass",
    "objdata", "object", "objname", "objsect", "objtime", "operator", "pict",
    "pn", "pnseclvl", "pntext", "printim", "private", "revtim", "rsidtbl",
    "shp", "shpgrp", "shpinst", "shppict", "stylesheet", "subject", "template",
    "themedata", "title", "userprops", "xmlattrname", "xmlattrvalue", "xmlclose",
    "xmlname", "xmlnstbl", "xmlopen",
}

_TEXT_CONTROLS = {
    "emdash": "—",
    "endash": "–",
    "bullet": "•",
    "lquote": "‘",
    "rquote": "’",
    "ldblquote": "“",
    "rdblquote": "”",
    "enspace": "\u2002",
    "emspace": "\u2003",
    "qmspace": "\u2005",
    "zwj": "\u200d",
    "zwnj": "\u200c",
}


@dataclass
class _State:
    skip: bool = False
    uc_skip: int = 1
    codec: str = "cp1252"


def _codec_for_codepage(number: int) -> str:
    if number <= 0 or number > 65535:
        raise RTFFormatError("RTF declares an invalid ANSI code page.")
    name = f"cp{number}"
    try:
        codecs.lookup(name)
    except LookupError as exc:
        raise RTFFormatError(f"RTF uses an unsupported code page: {number}") from exc
    return name


def _signed_utf16(value: int) -> int:
    if value < -32768 or value > 65535:
        raise RTFFormatError("RTF Unicode escape is outside the UTF-16 range.")
    return value + 65536 if value < 0 else value


def rtf_to_plain(data: bytes) -> str:
    """Extract visible plain text from bounded RTF bytes.

    RTF ANSI text is a byte stream, not a sequence of independently decodable
    bytes.  A selected code page may therefore retain decoder state across raw
    bytes, hexadecimal escapes, formatting controls, and same-code-page groups.
    Semantic Unicode/control output and actual code-page changes form explicit
    boundaries and require the pending byte sequence to be complete.
    """

    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("RTF input must be bytes.")
    raw = bytes(data)
    if len(raw) > MAX_RTF_BYTES:
        raise RTFFormatError("RTF document exceeds the 64 MiB safety limit.")
    if not raw.lstrip().startswith(b"{\\rtf"):
        raise RTFFormatError("The file is not a recognizable RTF document.")

    out: list[str] = []
    states: list[_State] = [_State()]
    fallback_remaining = 0
    pending_high: int | None = None
    decoder: codecs.IncrementalDecoder | None = None
    decoder_codec: str | None = None
    pending_byte_origin: str | None = None
    i = 0

    def emit_text(value: str) -> None:
        nonlocal pending_high
        if not value:
            return
        if pending_high is not None:
            out.append("\ufffd")
            pending_high = None
        out.append(value)

    def emit_code_unit(unit: int) -> None:
        nonlocal pending_high
        if 0xD800 <= unit <= 0xDBFF:
            if pending_high is not None:
                out.append("\ufffd")
            pending_high = unit
            return
        if 0xDC00 <= unit <= 0xDFFF:
            if pending_high is None:
                out.append("\ufffd")
                return
            codepoint = 0x10000 + ((pending_high - 0xD800) << 10) + (unit - 0xDC00)
            out.append(chr(codepoint))
            pending_high = None
            return
        if pending_high is not None:
            out.append("\ufffd")
            pending_high = None
        out.append(chr(unit))

    def flush_encoded(*, context: str = "RTF text") -> None:
        """Finish the active byte sequence at a semantic/code-page boundary."""

        nonlocal decoder, decoder_codec, pending_byte_origin
        if decoder is None:
            pending_byte_origin = None
            return
        try:
            value = decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            decoder = None
            decoder_codec = None
            raise RTFFormatError(
                f"{context} ends with an incomplete or invalid code-page byte sequence."
            ) from exc
        decoder = None
        decoder_codec = None
        pending_byte_origin = None
        emit_text(value)

    def ensure_decoder(codec: str) -> codecs.IncrementalDecoder:
        nonlocal decoder, decoder_codec
        if decoder is not None and decoder_codec != codec:
            flush_encoded(context="RTF code-page change")
        if decoder is None:
            try:
                factory = codecs.getincrementaldecoder(codec)
                decoder = factory(errors="strict")
            except (LookupError, TypeError) as exc:
                raise RTFFormatError(f"RTF uses an unsupported code page: {codec}") from exc
            decoder_codec = codec
        return decoder

    def feed_encoded_byte(value: int, *, context: str, origin: str) -> None:
        """Feed one RTF text byte while retaining multibyte decoder state.

        ``origin`` records whether a newly pending lead byte came from literal raw
        RTF text or an explicit RTF escape.  That distinction resolves a genuine
        lexical ambiguity: a raw DBCS lead can make backslash, ``{`` or ``}`` its
        legal trail byte, while a lead introduced by ``\'hh`` may intentionally
        be followed by an RTF control/group boundary before its next escaped byte.
        """

        nonlocal fallback_remaining, pending_byte_origin
        state = states[-1]
        if state.skip:
            return
        if fallback_remaining:
            fallback_remaining -= 1
            return
        was_pending = encoded_sequence_pending()
        active = ensure_decoder(state.codec)
        try:
            decoded = active.decode(bytes((value,)), final=False)
        except UnicodeDecodeError as exc:
            raise RTFFormatError(f"{context} is invalid for code page {state.codec}.") from exc
        now_pending = encoded_sequence_pending()
        if now_pending and not was_pending:
            pending_byte_origin = origin
        elif not now_pending:
            pending_byte_origin = None
        emit_text(decoded)

    def consume_semantic(value: str) -> None:
        """Emit a non-byte RTF text/control token at a decoder boundary."""

        nonlocal fallback_remaining
        state = states[-1]
        if state.skip:
            return
        if fallback_remaining:
            fallback_remaining -= 1
            return
        flush_encoded(context="RTF text before a control boundary")
        emit_text(value)

    def select_codec(codec: str) -> None:
        state = states[-1]
        if state.codec != codec:
            flush_encoded(context="RTF code-page change")
            state.codec = codec

    def _decoder_state() -> object | None:
        if decoder is None:
            return None
        try:
            return decoder.getstate()
        except (AttributeError, TypeError, ValueError):
            return None

    def encoded_sequence_pending() -> bool:
        """Return whether the active codec is waiting for one or more trail bytes."""

        state = _decoder_state()
        if state is None:
            return False
        buffered = state[0] if isinstance(state, tuple) and state else state
        return bool(buffered)

    def pending_sequence_accepts(value: int) -> bool:
        """Probe whether a syntax byte is really the pending byte sequence's trail.

        RTF syntax bytes overlap legal CP932 trail bytes.  We must not globally
        treat every brace/backslash after a lead byte as text: for example,
        ``\\'82\\'a0`` and formatting/group boundaries intentionally use the
        backslash/brace as RTF syntax while the decoder is pending.  A cloned
        strict decoder state provides an unambiguous lexical decision: syntax is
        preempted only when that exact byte is valid in the active sequence.
        """

        state = _decoder_state()
        if (
            state is None
            or decoder_codec is None
            or pending_byte_origin != "raw"
            or not encoded_sequence_pending()
        ):
            return False
        try:
            probe = codecs.getincrementaldecoder(decoder_codec)(errors="strict")
            probe.setstate(state)
            probe.decode(bytes((value,)), final=False)
        except (LookupError, AttributeError, TypeError, ValueError, UnicodeDecodeError):
            return False
        return True

    while i < len(raw):
        byte = raw[i]
        # In DBCS encodings, bytes used by RTF syntax can be legal trail bytes.
        # Preempt lexical syntax only when a cloned strict decoder proves the
        # exact byte is valid for the currently pending sequence.  Otherwise the
        # ordinary RTF lexer handles the control, escape, or group boundary.
        if byte in (0x5C, 0x7B, 0x7D) and pending_sequence_accepts(byte):
            i += 1
            feed_encoded_byte(byte, context="RTF raw multibyte trail byte", origin="raw")
            continue
        if byte == 0x7B:  # {
            if len(states) >= MAX_GROUP_DEPTH:
                raise RTFFormatError("RTF group nesting exceeds the safety limit.")
            states.append(replace(states[-1]))
            i += 1
            continue
        if byte == 0x7D:  # }
            if len(states) == 1:
                raise RTFFormatError("RTF contains an unmatched closing group.")
            child_codec = states[-1].codec
            states.pop()
            if child_codec != states[-1].codec:
                flush_encoded(context="RTF group code-page boundary")
            i += 1
            continue
        if byte != 0x5C:  # backslash
            i += 1
            if byte in (0x0A, 0x0D):
                # Source line wrapping is not document text and does not break a
                # multibyte sequence.
                continue
            if byte < 0x20:
                continue
            feed_encoded_byte(byte, context="RTF raw text byte", origin="raw")
            continue

        i += 1
        if i >= len(raw):
            raise RTFFormatError("RTF ends after an incomplete control marker.")
        symbol = raw[i]

        if symbol in (0x5C, 0x7B, 0x7D):
            # Escaped syntax characters are encoded text bytes.  Feeding them to
            # the active decoder is essential when one is the trail byte of a
            # multibyte character.
            i += 1
            feed_encoded_byte(symbol, context="RTF escaped text byte", origin="escape")
            continue
        if symbol == 0x27:  # \'hh
            if i + 2 >= len(raw):
                raise RTFFormatError("RTF contains an incomplete hexadecimal escape.")
            token = raw[i + 1:i + 3]
            try:
                value = int(token.decode("ascii"), 16)
            except (UnicodeDecodeError, ValueError) as exc:
                raise RTFFormatError("RTF contains an invalid hexadecimal escape.") from exc
            i += 3
            feed_encoded_byte(value, context="RTF hexadecimal escape", origin="escape")
            continue
        if symbol == 0x2A:  # \* ignorable destination marker
            states[-1].skip = True
            i += 1
            continue
        if symbol in (0x0A, 0x0D):
            i += 1
            if symbol == 0x0D and i < len(raw) and raw[i] == 0x0A:
                i += 1
            continue
        if not (0x41 <= symbol <= 0x5A or 0x61 <= symbol <= 0x7A):
            i += 1
            mapping = {0x7E: "\u00a0", 0x2D: "\u00ad", 0x5F: "\u2011"}
            if symbol in mapping:
                consume_semantic(mapping[symbol])
            continue

        start = i
        while i < len(raw) and (0x41 <= raw[i] <= 0x5A or 0x61 <= raw[i] <= 0x7A):
            i += 1
            if i - start > MAX_CONTROL_WORD:
                raise RTFFormatError("RTF control word exceeds the safety limit.")
        word = raw[start:i].decode("ascii").lower()

        sign = 1
        if i < len(raw) and raw[i] == 0x2D:
            sign = -1
            i += 1
        number_start = i
        while i < len(raw) and 0x30 <= raw[i] <= 0x39:
            i += 1
        number = sign * int(raw[number_start:i].decode("ascii")) if i > number_start else None

        if i < len(raw) and raw[i] == 0x20:
            i += 1

        state = states[-1]
        if word in _SKIP_DESTINATIONS:
            state.skip = True
            continue
        if word == "bin":
            if number is None or number < 0 or i + number > len(raw):
                raise RTFFormatError("RTF binary destination length is invalid.")
            if not state.skip:
                flush_encoded(context="RTF binary-control boundary")
            i += number
            continue
        if state.skip:
            continue
        if word == "uc":
            if number is None or number < 0 or number > MAX_UC_SKIP:
                raise RTFFormatError("RTF Unicode fallback count is invalid.")
            state.uc_skip = number
            continue
        if word == "u":
            if number is None:
                raise RTFFormatError("RTF Unicode escape is missing its value.")
            flush_encoded(context="RTF Unicode-control boundary")
            emit_code_unit(_signed_utf16(number))
            fallback_remaining = state.uc_skip
            continue
        if word == "ansicpg":
            if number is None:
                raise RTFFormatError("RTF ANSI code page is missing its value.")
            select_codec(_codec_for_codepage(number))
            continue
        if word == "ansi":
            select_codec("cp1252")
            continue
        if word == "mac":
            select_codec("mac_roman")
            continue
        if word == "pc":
            select_codec("cp437")
            continue
        if word == "pca":
            select_codec("cp850")
            continue
        if word in {"par", "line"}:
            consume_semantic("\n")
            continue
        if word == "tab":
            consume_semantic("\t")
            continue
        if word in {"page", "sect"}:
            consume_semantic("\n\n")
            continue
        if word in _TEXT_CONTROLS:
            consume_semantic(_TEXT_CONTROLS[word])
            continue
        # Formatting and unknown controls do not terminate an encoded byte
        # sequence.  This permits legal DBCS/UTF-8 text to span such controls.

    if len(states) != 1:
        raise RTFFormatError("RTF contains an unclosed group.")
    flush_encoded(context="RTF document")
    if pending_high is not None:
        out.append("\ufffd")
    return "".join(out)

def _unicode_escape(code_unit: int) -> str:
    signed = code_unit if code_unit < 0x8000 else code_unit - 0x10000
    return f"\\u{signed}?"


def plain_to_rtf(text: str) -> str:
    """Encode plain Unicode text as interoperable ASCII-only RTF."""

    if not isinstance(text, str):
        raise TypeError("RTF text must be a string.")
    pieces = [
        r"{\rtf1\ansi\ansicpg1252\deff0\uc1", "\n",
        r"{\fonttbl{\f0\fnil\fcharset0 Segoe UI;}}", "\n",
        r"\viewkind4\pard\f0\fs22 ",
    ]
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for char in normalized:
        codepoint = ord(char)
        if char == "\n":
            pieces.append("\\par\n")
        elif char == "\t":
            pieces.append("\\tab ")
        elif char in "\\{}":
            pieces.append("\\" + char)
        elif 0x20 <= codepoint <= 0x7E:
            pieces.append(char)
        elif codepoint <= 0xFFFF:
            pieces.append(_unicode_escape(codepoint))
        else:
            value = codepoint - 0x10000
            pieces.append(_unicode_escape(0xD800 + (value >> 10)))
            pieces.append(_unicode_escape(0xDC00 + (value & 0x3FF)))
    pieces.append("}")
    return "".join(pieces)
