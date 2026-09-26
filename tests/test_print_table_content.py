"""Regressions from the actual 6f361d6 normal-user print-content failure."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from leandesk.document_formats import LeanDocument
from leandesk.print_rtf import writer_print_rtf
from leandesk.windows_print import PrintUnavailableError, print_rtf_document


def fixture_document():
    return LeanDocument(title="QA", text="Before table.\n\nAfter table.", metadata={
        "objects": [{"kind": "table", "index": "2.0", "rows": 3, "cols": 3,
                     "data": [["F2-A11", "F2-B22", ""], ["8DC-F2", "6033c9c5", ""],
                              ["6F361D6", "0ee11278", ""]]}]})


def test_print_retains_actual_failed_fixture_table_and_order():
    value = writer_print_rtf(fixture_document())
    assert value.count(r"\trowd") == 3
    assert value.count(r"\cell ") == 9
    assert value.count(r"\cellx") == 9
    assert value.index("Before table.") < value.index("F2-A11") < value.index("6F361D6") < value.index("After table.")
    assert r"\clbrdrt\brdrs" in value
    assert "0ee11278" in value


def test_print_unicode_and_rtf_syntax_are_escaped():
    doc = fixture_document()
    doc.metadata["objects"][0]["data"][0][0] = "{\\x}\n\u03a9\U0001f600"
    value = writer_print_rtf(doc)
    assert value.isascii()
    assert r"\{\\x\}\line \u937?\u-10179?\u-8704?" in value


def test_multiple_embedded_windows_use_utf16_offsets_without_losing_text():
    doc = LeanDocument(text="\U0001f600AB", metadata={"objects": [
        {"kind": "table", "index": "1.2", "rows": 1, "cols": 1, "data": [["FIRST"]]},
        {"kind": "table", "index": "1.4", "rows": 1, "cols": 1, "data": [["SECOND"]]},
    ]})
    value = writer_print_rtf(doc)
    assert value.index("FIRST") < value.index(r"\fs22 A\par") < value.index("SECOND") < value.index(r"\fs22 B\par")


@pytest.mark.parametrize("item", [
    {"kind": "image"},
    {"kind": "table", "rows": 1, "cols": 2, "data": [["missing"]]},
    {"kind": "table", "rows": 0, "cols": 1, "data": []},
])
def test_unsupported_or_malformed_content_is_not_silently_omitted(item):
    with pytest.raises(ValueError):
        writer_print_rtf(LeanDocument(text="before", metadata={"objects": [item]}))


@pytest.mark.skipif(os.name != "nt", reason="Windows print dispatch")
def test_real_dispatch_serializes_table_and_removes_temporary_file():
    paths = []

    def operation(command, **kwargs):
        path = Path(kwargs["env"]["LEANDESK_PRINT_RTF"])
        paths.append(path)
        content = path.read_text(encoding="ascii")
        assert r"\trowd" in content and "6F361D6" in content
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "cancelled"}))

    with patch("leandesk.windows_print.subprocess.run", side_effect=operation):
        assert print_rtf_document(fixture_document()) == "cancelled"
    assert paths and not paths[0].exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows print dispatch")
def test_dispatch_fails_before_spawning_for_unsupported_objects():
    doc = LeanDocument(text="before", metadata={"objects": [{"kind": "image"}]})
    with patch("leandesk.windows_print.subprocess.run") as operation:
        with pytest.raises(PrintUnavailableError, match="embedded object"):
            print_rtf_document(doc)
    operation.assert_not_called()
