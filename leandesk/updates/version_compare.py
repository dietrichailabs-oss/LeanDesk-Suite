from __future__ import annotations

"""Strict prerelease-aware version comparison used by LeanDesk updates.

LeanDesk accepts one to four numeric release components so historic Windows-style
versions remain comparable, while prerelease precedence follows Semantic Versioning:
numeric identifiers sort before nonnumeric identifiers, stable releases sort after
prereleases, build metadata is ignored for precedence, and numeric prerelease
identifiers may not contain leading zeroes.
"""

from dataclasses import dataclass
from functools import total_ordering
import re

_VERSION_RE = re.compile(
    r"^v?(?P<core>0|[1-9]\d*)(?:\.(?P<minor>0|[1-9]\d*))?"
    r"(?:\.(?P<patch>0|[1-9]\d*))?(?:\.(?P<fourth>0|[1-9]\d*))?"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


class VersionError(ValueError):
    """Raised when a version cannot be parsed or ordered unambiguously."""


def _compare_prerelease(left: tuple[str, ...], right: tuple[str, ...]) -> int:
    if not left and not right:
        return 0
    if not left:
        return 1
    if not right:
        return -1

    for left_id, right_id in zip(left, right):
        if left_id == right_id:
            continue
        left_numeric = left_id.isascii() and left_id.isdigit()
        right_numeric = right_id.isascii() and right_id.isdigit()
        if left_numeric and right_numeric:
            left_number = int(left_id)
            right_number = int(right_id)
            return -1 if left_number < right_number else 1
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_id < right_id else 1

    if len(left) == len(right):
        return 0
    return -1 if len(left) < len(right) else 1


@total_ordering
@dataclass(frozen=True)
class Version:
    core: tuple[int, int, int, int]
    prerelease: tuple[str, ...] = ()

    @classmethod
    def parse(cls, value: str) -> "Version":
        if not isinstance(value, str) or len(value) > 96:
            raise VersionError("Version must be a short string.")
        match = _VERSION_RE.fullmatch(value.strip())
        if not match:
            raise VersionError(f"Malformed version: {value!r}")

        prerelease = tuple((match.group("pre") or "").split(".")) if match.group("pre") else ()
        for identifier in prerelease:
            if identifier.isascii() and identifier.isdigit() and len(identifier) > 1 and identifier.startswith("0"):
                raise VersionError(
                    f"Malformed version: numeric prerelease identifier has a leading zero: {identifier!r}"
                )

        core = tuple(
            int(match.group(name) or 0)
            for name in ("core", "minor", "patch", "fourth")
        )
        return cls(core=core, prerelease=prerelease)

    def _compare(self, other: "Version") -> int:
        if self.core != other.core:
            return -1 if self.core < other.core else 1
        return _compare_prerelease(self.prerelease, other.prerelease)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return self._compare(other) < 0

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Version) and self._compare(other) == 0


def compare_versions(left: str, right: str) -> int:
    """Return -1, 0, or 1 using one internally consistent ordering relation."""

    return Version.parse(left)._compare(Version.parse(right))


def is_newer(candidate: str, current: str) -> bool:
    return compare_versions(candidate, current) > 0
