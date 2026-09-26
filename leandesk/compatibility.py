from __future__ import annotations

"""Format registry and isolated compatibility conversion.

LeanDesk never edits the source supplied to this module.  LibreOffice conversion runs
without a shell, in a one-use profile and output directory, and the converted bytes are
copied into memory before every temporary file/profile is removed.  Callers consume the
``payload`` field instead of holding a path into a leaked temporary directory.
"""

from dataclasses import dataclass
import io
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile
from xml.etree import ElementTree as ET

WRITER_NATIVE = {".ldoc", ".docx", ".txt", ".md", ".html", ".htm", ".rtf"}
WRITER_COMPAT = {".doc", ".odt", ".ott", ".docm", ".dot", ".dotx", ".dotm", ".wps", ".wpd", ".abw", ".sxw", ".lwp", ".cwk", ".pages"}
SHEETS_NATIVE = {".lsheet", ".xlsx", ".csv"}
SHEETS_COMPAT = {".xls", ".xlsm", ".xlsb", ".ods", ".ots", ".tsv", ".dif", ".dbf", ".numbers", ".123", ".wk1", ".wk3", ".wk4", ".wks"}
SLIDES_NATIVE = {".ldeck", ".pptx"}
SLIDES_COMPAT = {".ppt", ".pptm", ".pps", ".ppsx", ".odp", ".otp", ".sxi", ".key"}
DRAW_NATIVE = {".ldraw"}

ALL_WRITER = WRITER_NATIVE | WRITER_COMPAT
ALL_SHEETS = SHEETS_NATIVE | SHEETS_COMPAT
ALL_SLIDES = SLIDES_NATIVE | SLIDES_COMPAT
ALL_SUPPORTED = ALL_WRITER | ALL_SHEETS | ALL_SLIDES | DRAW_NATIVE

MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_CONVERTED_BYTES = 256 * 1024 * 1024
CONVERSION_TIMEOUT_SECONDS = 45
ODT_MAX_MEMBERS = 4096
ODT_MAX_XML_BYTES = 32 * 1024 * 1024


@dataclass(frozen=True)
class ConversionResult:
    source: Path
    converted: Path
    module: str
    fidelity: str
    note: str
    payload: bytes
    target_suffix: str

    def as_file(self) -> io.BytesIO:
        return io.BytesIO(self.payload)


def module_for_suffix(suffix: str) -> str:
    suffix = suffix.lower()
    if suffix in ALL_SHEETS:
        return "Sheets"
    if suffix in ALL_SLIDES:
        return "Slides"
    if suffix in DRAW_NATIVE:
        return "Draw"
    return "Writer"


def find_libreoffice() -> str | None:
    env = os.environ.get("LEANDESK_SOFFICE")
    if env and Path(env).is_file():
        return str(Path(env).resolve())
    names = ("soffice.exe", "soffice") if os.name == "nt" else ("soffice", "libreoffice")
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    candidates: list[Path] = []
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)")):
            if base:
                candidates.append(Path(base) / "LibreOffice" / "program" / "soffice.exe")
    elif sys_platform() == "darwin":
        candidates.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def sys_platform() -> str:
    import sys

    return sys.platform


def _safe_run(args: list[str], timeout: int = CONVERSION_TIMEOUT_SECONDS) -> subprocess.CompletedProcess[str]:
    flags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        flags = subprocess.CREATE_NO_WINDOW
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        creationflags=flags,
        shell=False,
        check=False,
        env={**os.environ, "SAL_DISABLE_CRASHREPORT": "1"},
    )


def _assert_regular_source(source: Path) -> Path:
    source = source.expanduser().resolve(strict=True)
    info = source.lstat()
    if source.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise RuntimeError("Compatibility source must be a regular local file.")
    if info.st_size > MAX_SOURCE_BYTES:
        raise RuntimeError("Compatibility source exceeds the 512 MiB safety limit.")
    return source


def cleanup_stale_conversion_roots(root: Path | None = None, *, older_than_seconds: int = 24 * 3600) -> int:
    """Remove only stale LeanDesk-owned compatibility roots under a selected temp root."""
    base = Path(root or tempfile.gettempdir())
    if not base.is_dir() or base.is_symlink():
        return 0
    threshold = time.time() - max(3600, int(older_than_seconds))
    removed = 0
    for child in base.iterdir():
        if not child.name.startswith(("leandesk_compat_", "leandesk_lo_profile_")):
            continue
        try:
            if child.is_symlink() or child.stat().st_mtime > threshold:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            elif child.is_file():
                child.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def convert_with_libreoffice(source: Path, module: str, output_dir: Path | None = None) -> ConversionResult:
    if module not in {"Writer", "Sheets", "Slides"}:
        raise ValueError("Unknown compatibility target module.")
    soffice = find_libreoffice()
    if not soffice:
        raise RuntimeError(
            "This document needs the LeanDesk compatibility engine. "
            "Install LibreOffice (or set LEANDESK_SOFFICE to soffice) and try again."
        )
    source = _assert_regular_source(Path(source))
    target_ext = {"Writer": "docx", "Sheets": "xlsx", "Slides": "pptx"}[module]

    base = None
    if output_dir is not None:
        base = Path(output_dir).expanduser().resolve(strict=False)
        base.mkdir(parents=True, exist_ok=True)
        if base.is_symlink():
            raise RuntimeError("Compatibility output root cannot be a symbolic link.")

    work = Path(tempfile.mkdtemp(prefix="leandesk_compat_", dir=str(base) if base else None)).resolve()
    profile = Path(tempfile.mkdtemp(prefix="leandesk_lo_profile_", dir=str(base) if base else None)).resolve()
    converted = work / f"{source.stem}.{target_ext}"
    try:
        cmd = [
            soffice,
            "--headless",
            "--safe-mode",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--norestore",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to",
            target_ext,
            "--outdir",
            str(work),
            str(source),
        ]
        try:
            result = _safe_run(cmd)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Compatibility conversion timed out safely.") from exc
        if result.returncode != 0 or not converted.is_file() or converted.is_symlink():
            detail = (result.stderr or result.stdout or "conversion failed").strip()
            raise RuntimeError(f"Compatibility conversion failed: {detail[:500]}")
        size = converted.stat().st_size
        if size <= 0 or size > MAX_CONVERTED_BYTES:
            raise RuntimeError("Converted document is empty or exceeds the safety limit.")
        payload = converted.read_bytes()
        if len(payload) != size:
            raise RuntimeError("Converted document changed while it was being read.")
        return ConversionResult(
            source=source,
            converted=converted,
            module=module,
            fidelity="compatibility",
            note="Converted from a foreign/legacy format. Original file was not modified.",
            payload=payload,
            target_suffix=f".{target_ext}",
        )
    finally:
        # The returned ``converted`` path is intentionally stale.  The immutable bytes in
        # ``payload`` are the only supported result and no user document/profile remains.
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(profile, ignore_errors=True)


def _safe_zip_name(name: str) -> PurePosixPath:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise RuntimeError("Unsafe OpenDocument member name.")
    p = PurePosixPath(name)
    if p.is_absolute() or any(part in {"", ".", ".."} for part in p.parts):
        raise RuntimeError("Unsafe OpenDocument member path.")
    return p


def extract_odt_text(path: Path) -> str:
    """Read basic ODT text when LibreOffice is unavailable, without claiming formatting fidelity."""
    path = _assert_regular_source(Path(path))
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        if len(infos) > ODT_MAX_MEMBERS:
            raise RuntimeError("ODT contains too many package members.")
        seen: set[str] = set()
        content = None
        for info in infos:
            name = _safe_zip_name(info.filename).as_posix()
            key = name.casefold()
            if key in seen:
                raise RuntimeError("ODT contains duplicate package members.")
            seen.add(key)
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise RuntimeError("ODT contains a linked package member.")
            if name == "content.xml":
                if info.file_size > ODT_MAX_XML_BYTES:
                    raise RuntimeError("ODT content.xml exceeds the safety limit.")
                content = zf.read(info)
        if content is None:
            raise RuntimeError("ODT content.xml is missing.")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise RuntimeError("ODT content XML is invalid.") from exc
    out: list[str] = []
    for elem in root.iter():
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag in {"p", "h"}:
            text = "".join(elem.itertext()).strip()
            if text:
                out.append(text)
    return "\n".join(out)


def needs_compatibility(path: Path) -> bool:
    return Path(path).suffix.lower() in (WRITER_COMPAT | SHEETS_COMPAT | SLIDES_COMPAT)


def registered_extensions() -> dict[str, tuple[str, ...]]:
    return {
        "Writer": tuple(sorted(ALL_WRITER)),
        "Sheets": tuple(sorted(ALL_SHEETS)),
        "Slides": tuple(sorted(ALL_SLIDES)),
        "Draw": tuple(sorted(DRAW_NATIVE)),
    }
