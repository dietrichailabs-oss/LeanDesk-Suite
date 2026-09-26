from __future__ import annotations

import pytest

from leandesk.organizer_exchange import (
    CONTACT_FIELDS,
    TASK_FIELDS,
    export_csv,
    export_ics,
    export_vcards,
    import_csv,
    import_ics,
    import_vcards,
)


@pytest.mark.parametrize("recurrence", ["daily", "weekly", "monthly", "yearly"])
def test_calendar_ics_round_trip_recurrence_reminder_and_unicode(recurrence):
    event = {"id": "evt-1", "title": "Café planning", "start": "2026-09-03T14:00:00", "end": "2026-09-03T15:30:00", "location": "Room 2", "notes": "Line 1\nLine 2", "categories": ["Work", "Blue"], "recurrence": recurrence, "reminder": 15}
    payload = export_ics([event])
    restored = import_ics(payload)[0]
    assert restored["title"] == event["title"]
    assert restored["recurrence"] == recurrence
    assert restored["reminder"] == 15
    assert restored["notes"] == event["notes"]


def test_calendar_all_day_round_trip():
    restored = import_ics(export_ics([{"title": "Holiday", "start": "2026-09-03", "end": "2026-09-04", "all_day": True}]))[0]
    assert restored["all_day"] is True
    assert restored["start"] == "2026-09-03"


@pytest.mark.parametrize("recurrence", ["HOURLY", "SECONDLY", "INVALID"])
def test_calendar_rejects_unsupported_recurrence(recurrence):
    with pytest.raises(ValueError):
        export_ics([{"title": "Bad", "start": "2026-09-03", "all_day": True, "recurrence": recurrence}])


@pytest.mark.parametrize("payload", ["", "BEGIN:VCALENDAR\nBEGIN:VEVENT", "BEGIN:VCALENDAR\nBEGIN:VEVENT\nEND:VCALENDAR"])
def test_calendar_rejects_malformed_envelopes(payload):
    with pytest.raises(ValueError):
        import_ics(payload)


def test_contact_vcard_round_trip_all_common_fields():
    contact = {"first_name": "Ada", "middle_name": "M", "last_name": "Lovelace", "display_name": "Ada Lovelace", "company": "Analytical Engines", "job_title": "Programmer", "email": "ada@example.test", "phone": "+1 555 0100", "mobile": "+1 555 0101", "address": "1 Computing Way", "birthday": "1815-12-10", "notes": "First programmer", "categories": ["VIP", "Work"]}
    restored = import_vcards(export_vcards([contact]))[0]
    for field in CONTACT_FIELDS:
        assert restored.get(field) == contact.get(field)


def test_multiple_vcards_remain_distinct():
    restored = import_vcards(export_vcards([{"first_name": "A", "last_name": "One"}, {"first_name": "B", "last_name": "Two"}]))
    assert [item["last_name"] for item in restored] == ["One", "Two"]


@pytest.mark.parametrize("fields", [CONTACT_FIELDS, TASK_FIELDS])
def test_csv_round_trip_unicode_quoting_and_newlines(fields):
    record = {field: f"value,{field}\nnext" for field in fields}
    restored = import_csv(export_csv([record], fields), fields)[0]
    assert restored == record


def test_csv_rejects_unknown_columns():
    with pytest.raises(ValueError):
        import_csv("title,unexpected\r\nTask,x\r\n", TASK_FIELDS)


def test_exchange_bounds_fail_closed():
    with pytest.raises(ValueError):
        export_vcards([{"notes": "x" * 100_001}])
    with pytest.raises(ValueError):
        export_ics([{"title": "x", "start": "2026-09-03", "all_day": True, "reminder": 600_000}])


def test_csv_preserves_record_count_at_scale():
    records = [{"title": f"Task {index}", "status": "open"} for index in range(2_000)]
    assert len(import_csv(export_csv(records, TASK_FIELDS), TASK_FIELDS)) == 2_000
