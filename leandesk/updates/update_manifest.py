from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..data_boundary import DataCorruptionError, strict_json_load_bytes
from .version_compare import Version, VersionError

PRODUCT = "leandesk-suite"
OFFICIAL_HOST = "www.dietrichailabs.com"
OFFICIAL_DOWNLOAD_HOST = "downloads.dietrichailabs.com"
MANIFEST_URL = "https://www.dietrichailabs.com/updates/leandesk.json"
MAX_RESPONSE_BYTES = 64 * 1024


class ManifestError(ValueError):
    pass


def _official_https(
    value: Any,
    *,
    field: str,
    allowed_hosts: tuple[str, ...] = (OFFICIAL_HOST,),
    required_path_prefixes: tuple[str, ...] = (),
) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 2048:
        raise ManifestError(f"Invalid {field}.")
    parts = urlsplit(value)
    if (
        parts.scheme.lower() != "https"
        or (parts.hostname or "").lower() not in allowed_hosts
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
        or parts.fragment
    ):
        raise ManifestError(f"{field} must be a credential-free official Dietrich AI Labs HTTPS URL.")
    if required_path_prefixes:
        accepted = False
        for required_path_prefix in required_path_prefixes:
            prefix = required_path_prefix.rstrip("/") or "/"
            if (
                parts.path == prefix
                or parts.path.startswith(prefix + "/")
                or (prefix.endswith("_") and parts.path.startswith(prefix))
            ):
                accepted = True
                break
        if not accepted:
            raise ManifestError(f"Unexpected {field} path.")
    host = (parts.hostname or "").lower()
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def validate_final_manifest_url(value: str) -> None:
    normalized = _official_https(value, field="final manifest URL", required_path_prefixes=("/updates/",))
    if normalized != MANIFEST_URL:
        raise ManifestError("The update manifest response did not come from the approved fixed endpoint.")


@dataclass(frozen=True)
class UpdateManifest:
    product: str
    latest_version: str
    release_name: str
    published_at: str | None
    release_url: str | None
    download_url: str | None
    sha256: str | None
    message: str | None


def parse_manifest(data: bytes) -> UpdateManifest:
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_RESPONSE_BYTES:
        raise ManifestError("Update manifest exceeds the size limit.")
    try:
        obj = strict_json_load_bytes(bytes(data))
    except DataCorruptionError as exc:
        raise ManifestError(str(exc)) from exc
    if not isinstance(obj, dict) or obj.get("product") != PRODUCT:
        raise ManifestError("Update manifest product mismatch.")
    latest = obj.get("latest_version")
    try:
        Version.parse(latest)
    except (VersionError, TypeError) as exc:
        raise ManifestError("Invalid latest_version.") from exc

    release_name = obj.get("release_name", f"LeanDesk Suite {latest}")
    if not isinstance(release_name, str) or not release_name.strip() or len(release_name) > 200:
        raise ManifestError("Invalid release_name.")
    published_at = obj.get("published_at")
    if published_at not in (None, ""):
        if not isinstance(published_at, str) or len(published_at) > 64:
            raise ManifestError("Invalid published_at.")
        try:
            parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except ValueError as exc:
            raise ManifestError("Invalid published_at timestamp.") from exc
    else:
        published_at = None

    release_url = _official_https(
        obj.get("release_url"), field="release_url",
        required_path_prefixes=("/leandesk.html", "/apps/leandesk"),
    )
    download_url = _official_https(
        obj.get("download_url"), field="download_url",
        allowed_hosts=(OFFICIAL_HOST, OFFICIAL_DOWNLOAD_HOST),
        required_path_prefixes=("/downloads", "/LeanDesk_", "/LeandDesk_"),
    )
    if release_url is None and download_url is None:
        raise ManifestError("The update manifest must provide an official release_url or download_url.")
    sha = obj.get("sha256") or None
    if sha is not None:
        if not isinstance(sha, str) or not re.fullmatch(r"[A-Fa-f0-9]{64}", sha):
            raise ManifestError("Invalid sha256 field.")
        sha = sha.upper()
    message = obj.get("message")
    if message is not None and (not isinstance(message, str) or len(message) > 1000):
        raise ManifestError("Invalid update message.")
    return UpdateManifest(
        product=PRODUCT,
        latest_version=latest,
        release_name=release_name.strip(),
        published_at=published_at,
        release_url=release_url,
        download_url=download_url,
        sha256=sha,
        message=message,
    )
