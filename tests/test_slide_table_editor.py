"""Regression for the missing packaged Slides table-editing path."""

from copy import deepcopy
from types import SimpleNamespace
import tkinter as tk

import pytest

from leandesk.slide_table_editor import SlideTableEditor, install_table_editor


@pytest.fixture
def owner():
    root = tk.Tk()
    root.withdraw()
    frame = tk.Frame(root)
    frame.tables = [SimpleNamespace(kind="table", object_id="table-1", x=12, y=20,
                                   width=480, height=180,
                                   data={"rows": 2, "cols": 2,
                                         "values": [["old", "B"], ["C", "D"]],
                                         "custom": {"preserve": True}}),
                    SimpleNamespace(kind="table", object_id="table-2", x=60, y=80,
                                    width=200, height=100,
                                    data={"rows": 1, "cols": 1, "values": [["second"]]})]
    frame.shape = SimpleNamespace(kind="shape", object_id="shape-1", data={"text": "keep"})
    frame.current_slide = lambda: SimpleNamespace(objects=[*frame.tables, frame.shape])
    frame.selected_object_id = "table-1"
    frame.dirty = False
    frame.calls = []
    frame.render_slide = lambda: frame.calls.append("render")
    frame._save_recovery = lambda: frame.calls.append("recovery")
    try:
        yield frame
    finally:
        root.destroy()


def enter(dialog, text):
    dialog.value.delete("1.0", "end")
    dialog.value.insert("1.0", text)


def test_apply_edits_current_cell_preserves_geometry_and_other_objects(owner):
    before = deepcopy(owner.tables[0].__dict__)
    dialog = SlideTableEditor(owner)
    enter(dialog, "edited\n\u03a9\u4e2d")
    dialog.apply()
    assert owner.tables[0].data["values"] == [["edited\n\u03a9\u4e2d", "B"], ["C", "D"]]
    assert owner.tables[0].data["custom"] == {"preserve": True}
    for field in ("x", "y", "width", "height", "object_id"):
        assert getattr(owner.tables[0], field) == before[field]
    assert owner.shape.data == {"text": "keep"}
    assert owner.dirty and owner.calls == ["render", "recovery"]


def test_cancel_discards_all_pending_edits(owner):
    before = deepcopy([table.data for table in owner.tables])
    dialog = SlideTableEditor(owner)
    enter(dialog, "discard")
    dialog.next_cell(1)
    dialog.destroy()
    assert [table.data for table in owner.tables] == before
    assert not owner.dirty and owner.calls == []


def test_table_switch_keeps_drafts_until_apply(owner):
    dialog = SlideTableEditor(owner)
    enter(dialog, "first update")
    dialog.selector.current(1)
    dialog.switch_table()
    assert owner.tables[0].data["values"][0][0] == "old"
    enter(dialog, "second update")
    dialog.apply()
    assert owner.tables[0].data["values"][0][0] == "first update"
    assert owner.tables[1].data["values"][0][0] == "second update"


def test_tab_and_shift_tab_commit_and_navigate(owner):
    dialog = SlideTableEditor(owner)
    enter(dialog, "A edited")
    assert dialog.next_cell(1) == "break"
    assert dialog.active_cell == (0, 1)
    enter(dialog, "B edited")
    dialog.next_cell(-1)
    assert dialog.value.get("1.0", "end-1c") == "A edited"
    dialog.apply()
    assert owner.tables[0].data["values"][0] == ["A edited", "B edited"]


def test_selected_imported_table_is_editable_and_noop_is_not_dirty(owner):
    owner.selected_object_id = "table-2"
    dialog = SlideTableEditor(owner)
    assert dialog.active_table == 1
    assert dialog.value.get("1.0", "end-1c") == "second"
    dialog.apply()
    assert not owner.dirty and not owner.calls


def test_discoverable_editor_button_is_installed_in_toolbar(owner):
    toolbar = tk.Frame(owner)
    toolbar.pack(fill="x")
    canvas = tk.Canvas(owner)
    canvas.pack()
    button = install_table_editor(owner, toolbar)
    assert button.cget("text") == "Edit Tables..."
    assert button.master is toolbar
    assert button.pack_info()["side"] == "left"
