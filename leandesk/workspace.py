from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import re

from .core import TEMPLATE_ROOT, atomic_write_json
from .data_boundary import DataCorruptionError, read_bounded, strict_json_load_bytes

MAX_TEMPLATE_BYTES = 4 * 1024 * 1024
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}$")


@dataclass(frozen=True)
class SearchResult:
    module: str
    title: str
    detail: str
    identity: str = ""


@dataclass(frozen=True)
class TemplateDefinition:
    name: str
    module: str
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TemplateDefinition":
        if not isinstance(payload, dict) or not isinstance(payload.get("payload"), dict):
            raise DataCorruptionError("Invalid template definition")
        name, module = payload.get("name"), payload.get("module")
        if not isinstance(name, str) or not _SAFE_NAME.fullmatch(name) or module not in {"Writer", "Sheets", "Slides", "Notes", "Draw"}:
            raise DataCorruptionError("Invalid template name or module")
        return cls(name, module, dict(payload["payload"]))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "module": self.module, "payload": self.payload}


BUILTIN_TEMPLATES = (
    TemplateDefinition("Business Letter", "Writer", {"text": "Your Name\nAddress\n\nDate\n\nRecipient\n\nDear Recipient,\n\n\n\nSincerely,\nYour Name"}),
    TemplateDefinition("Project Budget", "Sheets", {"headers": ["Item", "Category", "Budget", "Actual", "Variance"]}),
    TemplateDefinition("Status Presentation", "Slides", {"title": "Project Status", "body": "Summary\nProgress\nRisks\nNext steps"}),
    TemplateDefinition("Meeting Notes", "Notes", {"title": "Meeting Notes", "body": "# Meeting Notes\n\n## Attendees\n\n## Agenda\n\n## Decisions\n\n## Actions\n- [ ] "}),
)


class TemplateStore:
    def __init__(self, root: Path = TEMPLATE_ROOT) -> None:
        self.root = Path(root)

    def save(self, template: TemplateDefinition) -> Path:
        if not _SAFE_NAME.fullmatch(template.name):
            raise ValueError("Template name contains unsupported characters")
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{template.name}.json"
        if target.parent.resolve() != self.root.resolve():
            raise ValueError("Template path escaped its root")
        atomic_write_json(target, template.to_dict())
        return target

    def list(self) -> list[TemplateDefinition]:
        rows = list(BUILTIN_TEMPLATES)
        if not self.root.exists():
            return rows
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = strict_json_load_bytes(read_bounded(path, limit=MAX_TEMPLATE_BYTES))
                rows.append(TemplateDefinition.from_dict(payload))
            except (OSError, ValueError, DataCorruptionError):
                continue
        return rows


def search_records(query: str, records: Iterable[SearchResult], limit: int = 200) -> list[SearchResult]:
    terms = [term.casefold() for term in query.split() if term]
    if not terms:
        return []
    matches = []
    for row in records:
        haystack = f"{row.module}\n{row.title}\n{row.detail}".casefold()
        if all(term in haystack for term in terms):
            matches.append(row)
            if len(matches) >= limit:
                break
    return matches
