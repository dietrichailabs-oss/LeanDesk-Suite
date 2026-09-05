"""GUI-06 acceptance beyond the separately recorded physical reproduction."""
import json
import os
import tkinter as tk
from unittest.mock import Mock

import pytest

from leandesk.sheets import SheetsFrame, WorkbookModel


@pytest.fixture
def sheet_frame():
    assert os.environ.get("LOCALAPPDATA") == os.environ.get("LEANDESK_GUI_REPRO_PROFILE")
    root = tk.Tk()
    root.geometry("1024x700")
    frame = SheetsFrame(root, recent=Mock())
    frame.pack(fill="both", expand=True)
    root.update()
    grid = frame.active_grid()
    grid.set_cells([("A1", "12"), ("B1", "24"), ("A2", "3"), ("B2", "4")])
    grid.select_address("C1")
    root.update()
    yield root, frame, grid
    for job in root.tk.call("after", "info"):
        root.tk.call("after", "cancel", job)
    root.destroy()


def draft(root, frame, value):
    frame.formula_var.set(value)
    frame.formula_entry.focus_force()
    root.update()
    frame.formula_entry.icursor(tk.END)
    assert root.focus_get() == frame.formula_entry


def drag(root, grid, start, end):
    def center(cell):
        x1, y1, x2, y2 = grid._cell_bounds(*cell)
        return int((x1 + x2) / 2), int((y1 + y2) / 2)
    x, y = center(start)
    grid.canvas.event_generate("<ButtonPress-1>", x=x, y=y)
    root.update()
    x, y = center(end)
    grid.canvas.event_generate("<B1-Motion>", x=x, y=y, state=0x100)
    root.update()
    grid.canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
    root.update()


@pytest.mark.parametrize("start,end,reference,result", [
    ((0, 0), (0, 1), "A1:B1", 36),
    ((0, 0), (1, 0), "A1:A2", 15),
    ((0, 1), (0, 0), "A1:B1", 36),
    ((1, 1), (0, 0), "A1:B2", 43),
])
def test_reference_commit_preserves_target_and_roundtrips(sheet_frame, tmp_path, start, end, reference, result):
    root, frame, grid = sheet_frame
    draft(root, frame, "=SUM(")
    drag(root, grid, start, end)
    assert frame.active_address.get() == "C1"
    assert grid.active_address == "C1"
    assert frame.formula_var.get() == "=SUM(" + reference
    frame.formula_var.set(frame.formula_var.get() + ")")
    frame.formula_entry.event_generate("<Return>")
    root.update()
    assert grid.model.raw("C1") == "=SUM(" + reference + ")"
    assert grid.model.value("C1") == result
    path = tmp_path / "range-roundtrip.json"
    path.write_text(json.dumps(frame.workbook.to_dict()), encoding="utf-8")
    restored = WorkbookModel.from_dict(json.loads(path.read_text(encoding="utf-8")))
    assert restored.sheets[0].raw("C1") == grid.model.raw("C1")
    assert restored.sheets[0].value("C1") == result
    assert not grid.canvas.find_withtag("formula-reference")


def test_reference_drag_has_distinct_visible_range_outline(sheet_frame):
    root, frame, grid = sheet_frame
    draft(root, frame, "=SUM(")
    drag(root, grid, (0, 0), (1, 1))
    marks = grid.canvas.find_withtag("formula-reference")
    assert len(marks) == 1
    assert float(grid.canvas.itemcget(marks[0], "width")) >= 2
    x1, y1, _, _ = grid._cell_bounds(0, 0)
    _, _, x2, y2 = grid._cell_bounds(1, 1)
    assert grid.canvas.coords(marks[0]) == pytest.approx([x1 + 1, y1 + 1, x2 - 1, y2 - 1])
    assert grid.selection.label() == "C1"


def test_escape_cancels_formula_without_changing_cells(sheet_frame):
    root, frame, grid = sheet_frame
    before = frame.workbook.to_dict()
    draft(root, frame, "=SUM(")
    drag(root, grid, (0, 0), (0, 1))
    frame.formula_entry.event_generate("<Escape>")
    root.update()
    assert frame.workbook.to_dict() == before
    assert frame.formula_var.get() == grid.model.raw("C1")
    assert grid.active_address == "C1"
    assert not grid.canvas.find_withtag("formula-reference")


def test_multiple_ranges_keep_separate_reference_spans(sheet_frame):
    root, frame, grid = sheet_frame
    draft(root, frame, "=SUM(")
    drag(root, grid, (0, 0), (0, 1))
    draft(root, frame, frame.formula_var.get() + ",")
    drag(root, grid, (1, 0), (1, 1))
    assert frame.formula_var.get() == "=SUM(A1:B1,A2:B2"
    assert grid.active_address == "C1"
    frame.formula_var.set(frame.formula_var.get() + ")")
    frame.commit_formula_bar()
    assert grid.model.value("C1") == 43
