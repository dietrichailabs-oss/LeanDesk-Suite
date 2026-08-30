from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import socket
import ssl
import tempfile
import threading
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..core import UPDATE_STATE_FILE
from ..data_boundary import load_json_or_default
from .update_manifest import MANIFEST_URL, MAX_RESPONSE_BYTES, UpdateManifest, parse_manifest, validate_final_manifest_url
from .version_compare import Version, VersionError, is_newer

LOGGER = logging.getLogger("leandesk.updates")
INTERVAL = timedelta(days=7)
TIMEOUT_SECONDS = 5.0
UP_TO_DATE = "UP_TO_DATE"
UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
CHECK_FAILED = "CHECK_FAILED"
STATE_SCHEMA_VERSION = 1


class UpdateStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateResult:
    status: str
    checked: bool
    current_version: str
    latest_version: str | None = None
    release_name: str | None = None
    published_at: str | None = None
    release_url: str | None = None
    download_url: str | None = None
    sha256: str | None = None
    message: str | None = None
    error: str | None = None
    error_category: str | None = None

    @property
    def code(self) -> str:
        if self.status == "update_available":
            return UPDATE_AVAILABLE
        if self.status == "current":
            return UP_TO_DATE
        return CHECK_FAILED


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _diagnose_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, HTTPError):
        return "service", f"Update service returned HTTP {exc.code}."
    if isinstance(exc, ssl.SSLError):
        return "secure_connection", "A secure TLS connection to the update service could not be established."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "The update service did not respond before the safety timeout."
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return "secure_connection", "A secure TLS connection to the update service could not be established."
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout", "The update service did not respond before the safety timeout."
        return "network", "The official update service could not be reached. Check the network connection and try again."
    if isinstance(exc, (ValueError, TypeError)):
        return "metadata", "The official update service returned metadata that did not pass LeanDesk safety validation."
    return "internal", "LeanDesk could not complete the update check safely."


def _state_path() -> Path:
    return UPDATE_STATE_FILE


def _read_state(path: Path | None = None) -> dict[str, Any]:
    target = Path(path or _state_path())
    result = load_json_or_default(target, dict, expected_type=dict, limit=64 * 1024)
    if result.read_only:
        raise UpdateStateError("Stored update state is malformed or unreadable; original bytes were preserved.")
    state = dict(result.value) if isinstance(result.value, dict) else {}
    schema = state.get("schema_version", STATE_SCHEMA_VERSION)
    if isinstance(schema, bool) or not isinstance(schema, int) or schema < 1:
        raise UpdateStateError("Stored update state has an invalid schema version.")
    if schema > STATE_SCHEMA_VERSION:
        raise UpdateStateError("Stored update state belongs to a newer LeanDesk build.")
    return state


def _atomic_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = Path(path or _state_path())
    state = dict(state)
    state["schema_version"] = STATE_SCHEMA_VERSION
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink():
        raise RuntimeError("Update state directory must not be a symbolic link.")
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def set_enabled(enabled: bool, *, state_path: Path | None = None) -> None:
    state = _read_state(state_path)
    state["enabled"] = bool(enabled)
    _atomic_state(state, state_path)


def is_enabled(*, state_path: Path | None = None) -> bool:
    try:
        return bool(_read_state(state_path).get("enabled", True))
    except UpdateStateError:
        return True


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _fetch(opener: Callable[..., Any] | None = None) -> UpdateManifest:
    req = Request(
        MANIFEST_URL,
        headers={"Accept": "application/json", "User-Agent": "LeanDesk-Suite-Update-Check"},
        method="GET",
    )
    open_fn = opener or urlopen
    with open_fn(req, timeout=TIMEOUT_SECONDS) as response:
        final_url = response.geturl() if hasattr(response, "geturl") else MANIFEST_URL
        validate_final_manifest_url(final_url)
        status = getattr(response, "status", None)
        if status is not None and not (200 <= int(status) < 300):
            raise RuntimeError(f"Update service returned HTTP {status}.")
        headers = getattr(response, "headers", None)
        length = headers.get("Content-Length") if headers is not None else None
        if length not in (None, ""):
            try:
                if int(length) > MAX_RESPONSE_BYTES:
                    raise ValueError("Update manifest exceeds the size limit.")
            except (TypeError, ValueError) as exc:
                if "exceeds" in str(exc):
                    raise
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("Update manifest exceeds the size limit.")
    return parse_manifest(body)


def check_for_updates(
    current_version: str,
    *,
    force: bool = False,
    opener=None,
    state_path: Path | None = None,
    now: datetime | None = None,
) -> UpdateResult:
    try:
        Version.parse(current_version)
    except VersionError as exc:
        return UpdateResult("error", False, current_version, error=f"Invalid local version: {exc}", error_category="local_version")

    now = (now or _utcnow()).astimezone(timezone.utc)
    try:
        state = _read_state(state_path)
    except UpdateStateError as exc:
        LOGGER.info("Update state could not be read safely: %s", type(exc).__name__)
        return UpdateResult("error", False, current_version, error=str(exc), error_category="state")
    if not state.get("enabled", True) and not force:
        return UpdateResult("disabled", False, current_version)
    last = _parse_time(state.get("last_attempt_utc"))
    # A future timestamp is treated as recently attempted to avoid clock-skew polling.
    if not force and last and (now <= last or now - last < INTERVAL):
        return UpdateResult("not_due", False, current_version, latest_version=state.get("latest_version"))

    # Persist the attempt before network I/O so offline failures cannot trigger launch-time polling.
    state["last_attempt_utc"] = now.isoformat().replace("+00:00", "Z")
    try:
        _atomic_state(state, state_path)
    except Exception as exc:
        LOGGER.warning("Update check state could not be stored: %s", type(exc).__name__)
        return UpdateResult("error", False, current_version, error="Could not safely record the update-check time.", error_category="state")

    try:
        manifest = _fetch(opener)
        state.update(
            {
                "latest_version": manifest.latest_version,
                "last_success_utc": now.isoformat().replace("+00:00", "Z"),
            }
        )
        try:
            _atomic_state(state, state_path)
        except Exception:
            LOGGER.warning("Successful update state could not be stored.")
        available = is_newer(manifest.latest_version, current_version)
        return UpdateResult(
            "update_available" if available else "current",
            True,
            current_version,
            latest_version=manifest.latest_version,
            release_name=manifest.release_name,
            published_at=manifest.published_at,
            release_url=manifest.release_url,
            download_url=manifest.download_url,
            sha256=manifest.sha256,
            message=manifest.message,
        )
    except Exception as exc:
        LOGGER.info("Update check failed safely: %s", type(exc).__name__)
        category, diagnostic = _diagnose_error(exc)
        return UpdateResult("error", True, current_version, error=diagnostic, error_category=category)


def check_async(current_version: str, callback: Callable[[UpdateResult], None], **kwargs) -> threading.Thread:
    def worker() -> None:
        callback(check_for_updates(current_version, **kwargs))

    thread = threading.Thread(target=worker, name="LeanDeskUpdateCheck", daemon=True)
    thread.start()
    return thread
