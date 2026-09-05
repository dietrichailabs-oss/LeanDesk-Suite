"""Strict local interchange helpers for LeanDesk Calendar, Contacts, and Tasks."""

from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
import re
from typing import Any, Iterable


MAX_RECORDS = 10_000
MAX_FIELD = 100_000
_SUPPORTED_RECURRENCE = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}


def _bounded(value: Any) -> str:
    text = "" if value is None else str(value)
    if len(text) > MAX_FIELD or "\x00" in text:
        raise ValueError("Organizer field exceeds safe bounds")
    return text


def _ics_escape(value: Any) -> str:
    return _bounded(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def _ics_unescape(value: str) -> str:
    result = []
    escaped = False
    for char in value:
        if escaped:
            result.append("\n" if char in "nN" else char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)


def _ics_datetime(value: Any, all_day: bool = False) -> str:
    text = _bounded(value).strip()
    if all_day:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%Y%m%d")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.strftime("%Y%m%dT%H%M%SZ")


def export_ics(events: Iterable[dict[str, Any]]) -> str:
    rows = list(events)
    if len(rows) > MAX_RECORDS:
        raise ValueError("Too many calendar events")
    output = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Dietrich AI Labs//LeanDesk//EN", "CALSCALE:GREGORIAN"]
    for index, event in enumerate(rows, 1):
        if not isinstance(event, dict):
            raise ValueError("Calendar event must be an object")
        all_day = bool(event.get("all_day", False))
        uid = _ics_escape(event.get("id") or f"leandesk-{index}")
        output.extend(["BEGIN:VEVENT", f"UID:{uid}", f"SUMMARY:{_ics_escape(event.get('title', ''))}"])
        start = event.get("start") or event.get("start_time")
        end = event.get("end") or event.get("end_time") or start
        if not start:
            raise ValueError("Calendar event start is required")
        prefix = ";VALUE=DATE" if all_day else ""
        output.append(f"DTSTART{prefix}:{_ics_datetime(start, all_day)}")
        output.append(f"DTEND{prefix}:{_ics_datetime(end, all_day)}")
        for key, field in (("location", "LOCATION"), ("notes", "DESCRIPTION"), ("categories", "CATEGORIES")):
            value = event.get(key)
            if value:
                if isinstance(value, list):
                    value = ",".join(str(item) for item in value)
                output.append(f"{field}:{_ics_escape(value)}")
        recurrence = _bounded(event.get("recurrence", "")).upper()
        if recurrence:
            frequency = recurrence.split(";", 1)[0].removeprefix("FREQ=")
            if frequency not in _SUPPORTED_RECURRENCE:
                raise ValueError("Unsupported recurrence")
            output.append(f"RRULE:FREQ={frequency}")
        reminder = event.get("reminder")
        if reminder not in (None, "", False):
            minutes = int(reminder)
            if not 0 <= minutes <= 525_600:
                raise ValueError("Reminder is outside supported bounds")
            output.extend(["BEGIN:VALARM", f"TRIGGER:-PT{minutes}M", "ACTION:DISPLAY", "DESCRIPTION:LeanDesk reminder", "END:VALARM"])
        output.append("END:VEVENT")
    output.append("END:VCALENDAR")
    return "\r\n".join(output) + "\r\n"


def import_ics(payload: str) -> list[dict[str, Any]]:
    text = _bounded(payload)
    physical = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines: list[str] = []
    for line in physical:
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        elif line:
            lines.append(line)
    if not lines or lines[0] != "BEGIN:VCALENDAR" or lines[-1] != "END:VCALENDAR":
        raise ValueError("Invalid ICS envelope")
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_alarm = False
    for line in lines[1:-1]:
        if line == "BEGIN:VEVENT":
            if current is not None:
                raise ValueError("Nested calendar event")
            current = {}
            continue
        if line == "END:VEVENT":
            if current is None or "start" not in current:
                raise ValueError("Incomplete calendar event")
            events.append(current)
            if len(events) > MAX_RECORDS:
                raise ValueError("Too many calendar events")
            current = None
            continue
        if line == "BEGIN:VALARM":
            in_alarm = True
            continue
        if line == "END:VALARM":
            in_alarm = False
            continue
        if current is None or ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        name = name_part.split(";", 1)[0].upper()
        all_day = "VALUE=DATE" in name_part.upper()
        if name == "UID": current["id"] = _ics_unescape(value)
        elif name == "SUMMARY": current["title"] = _ics_unescape(value)
        elif name in {"DTSTART", "DTEND"}:
            parsed = datetime.strptime(value, "%Y%m%d" if all_day else "%Y%m%dT%H%M%SZ")
            current["start" if name == "DTSTART" else "end"] = parsed.date().isoformat() if all_day else parsed.isoformat()
            current["all_day"] = all_day
        elif name == "LOCATION": current["location"] = _ics_unescape(value)
        elif name == "DESCRIPTION" and not in_alarm: current["notes"] = _ics_unescape(value)
        elif name == "CATEGORIES": current["categories"] = [item for item in _ics_unescape(value).split(",") if item]
        elif name == "RRULE":
            frequency = value.upper().split(";", 1)[0].removeprefix("FREQ=")
            if frequency not in _SUPPORTED_RECURRENCE:
                raise ValueError("Unsupported recurrence")
            current["recurrence"] = frequency.lower()
        elif name == "TRIGGER":
            match = re.fullmatch(r"-PT([0-9]{1,6})M", value)
            if match: current["reminder"] = int(match.group(1))
    if current is not None:
        raise ValueError("Unterminated calendar event")
    return events


def _vcard_escape(value: Any) -> str:
    return _ics_escape(value)


def export_vcards(contacts: Iterable[dict[str, Any]]) -> str:
    rows = list(contacts)
    if len(rows) > MAX_RECORDS:
        raise ValueError("Too many contacts")
    output: list[str] = []
    for contact in rows:
        first = _vcard_escape(contact.get("first_name", ""))
        middle = _vcard_escape(contact.get("middle_name", ""))
        last = _vcard_escape(contact.get("last_name", ""))
        display = _vcard_escape(contact.get("display_name") or " ".join(item for item in (first, middle, last) if item))
        output.extend(["BEGIN:VCARD", "VERSION:3.0", f"N:{last};{first};{middle};;", f"FN:{display}"])
        mapping = (("company", "ORG"), ("job_title", "TITLE"), ("email", "EMAIL;TYPE=INTERNET"), ("phone", "TEL;TYPE=VOICE"), ("mobile", "TEL;TYPE=CELL"), ("address", "ADR;TYPE=HOME"), ("birthday", "BDAY"), ("notes", "NOTE"), ("categories", "CATEGORIES"))
        for key, field in mapping:
            value = contact.get(key)
            if value:
                if isinstance(value, list): value = ",".join(str(item) for item in value)
                output.append(f"{field}:{_vcard_escape(value)}")
        output.append("END:VCARD")
    return "\r\n".join(output) + ("\r\n" if output else "")


def import_vcards(payload: str) -> list[dict[str, Any]]:
    lines = _bounded(payload).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    contacts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        if line == "BEGIN:VCARD": current = {}
        elif line == "END:VCARD":
            if current is None: raise ValueError("Unexpected vCard terminator")
            contacts.append(current); current = None
        elif current is not None and ":" in line:
            field, value = line.split(":", 1)
            base = field.split(";", 1)[0].upper()
            value = _ics_unescape(value)
            if base == "N":
                parts = value.split(";") + [""] * 5
                current.update(last_name=parts[0], first_name=parts[1], middle_name=parts[2])
            elif base == "FN": current["display_name"] = value
            elif base == "ORG": current["company"] = value
            elif base == "TITLE": current["job_title"] = value
            elif base == "EMAIL": current["email"] = value
            elif base == "TEL": current["mobile" if "CELL" in field.upper() else "phone"] = value
            elif base == "ADR": current["address"] = value
            elif base == "BDAY": current["birthday"] = value
            elif base == "NOTE": current["notes"] = value
            elif base == "CATEGORIES": current["categories"] = [item for item in value.split(",") if item]
    if current is not None:
        raise ValueError("Unterminated vCard")
    if len(contacts) > MAX_RECORDS:
        raise ValueError("Too many contacts")
    return contacts


CONTACT_FIELDS = ("first_name", "middle_name", "last_name", "display_name", "company", "job_title", "email", "phone", "mobile", "address", "birthday", "notes", "categories")
TASK_FIELDS = ("title", "notes", "start_date", "due_date", "priority", "status", "percent_complete", "recurrence", "reminder", "categories")


def export_csv(records: Iterable[dict[str, Any]], fields: tuple[str, ...]) -> str:
    rows = list(records)
    if len(rows) > MAX_RECORDS:
        raise ValueError("Too many organizer records")
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: ";".join(map(str, row.get(field, []))) if isinstance(row.get(field), list) else _bounded(row.get(field, "")) for field in fields})
    return stream.getvalue()


def import_csv(payload: str, fields: tuple[str, ...]) -> list[dict[str, str]]:
    stream = StringIO(_bounded(payload), newline="")
    reader = csv.DictReader(stream)
    if reader.fieldnames is None or any(field not in fields for field in reader.fieldnames):
        raise ValueError("CSV contains unsupported fields")
    rows = []
    for row in reader:
        rows.append({field: _bounded(value) for field, value in row.items() if field in fields})
        if len(rows) > MAX_RECORDS:
            raise ValueError("Too many organizer records")
    return rows
