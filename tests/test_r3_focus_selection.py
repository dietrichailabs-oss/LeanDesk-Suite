"""Focus/selection regressions; logical Tk scaling, not Windows DPI acceptance."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROBE = r"""
import sys
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

from leandesk.ui import AccessibleViewport, configure_suite_styles
from leandesk.sheets import SheetGrid, SheetModel

width, height, percent = map(int, sys.argv[1:])
root = tk.Tk()
errors = []
root.report_callback_exception = lambda *args: errors.append(repr(args))
try:
    root.tk.call("tk", "scaling", (96 / 72) * percent / 100)
    root.geometry(f"{width}x{height}")
    configure_suite_styles(root)
    viewport = AccessibleViewport(
        master=root, minimum_width=width + 320, minimum_height=height + 240
    )
    reported = []
    model = SheetModel()
    grid = SheetGrid(
        viewport.page, model, lambda: None,
        lambda address, raw: reported.append((address, raw)),
    )
    grid.pack(fill="both", expand=True)
    root.update()
    viewport.canvas.xview_moveto(0)
    viewport.canvas.yview_moveto(0)
    root.update()
    origin = (viewport.canvas.canvasx(0), viewport.canvas.canvasy(0))
    bounds = grid._cell_bounds(0, 0)
    point = (
        grid.canvas.winfo_rootx() + (bounds[0] + bounds[2]) / 2,
        grid.canvas.winfo_rooty() + (bounds[1] + bounds[3]) / 2,
    )
    assert grid.canvas.winfo_width() > viewport.canvas.winfo_width()
    assert grid.canvas.winfo_height() > viewport.canvas.winfo_height()
    viewport._reveal(grid.canvas)
    grid.canvas.focus_force()
    root.update()
    after = (viewport.canvas.canvasx(0), viewport.canvas.canvasy(0))
    assert all(abs(a - b) <= 1 for a, b in zip(origin, after)), (origin, after)
    event = SimpleNamespace(
        x=point[0] - grid.canvas.winfo_rootx(),
        y=point[1] - grid.canvas.winfo_rooty(),
        state=0,
    )
    assert grid._address_from_event(event) == "A1"

    # The edit target can differ from the previous selection after a mouse
    # gesture. Begin/cancel must not leave address, range and highlight split.
    grid.select_address("A1")
    left, top, right, bottom = grid._cell_bounds(0, 2)
    edit_event = SimpleNamespace(
        x=(left + right) / 2 - grid.canvas.canvasx(0),
        y=(top + bottom) / 2 - grid.canvas.canvasy(0),
    )
    grid.begin_edit(edit_event)
    root.update()
    assert grid.editor is not None
    assert grid.active_address == "C1"
    assert grid.selection.anchor == grid.selection.active == "C1"
    assert reported[-1][0] == "C1"
    grid.editor.insert(0, "discard-me")
    grid.cancel_edit()
    root.update()
    assert grid.editor is None
    assert model.raw("C1") == ""
    assert grid.active_address == grid.selection.anchor == grid.selection.active == "C1"
    assert reported[-1][0] == "C1"

    grid.begin_edit()
    grid.editor.insert(0, "7")
    grid.commit_edit("C1")
    root.update()
    assert model.raw("C1") == "7"
    assert grid.active_address == grid.selection.active == "C1"

    # Preserve keyboard accessibility for an ordinary offscreen control.
    entry = ttk.Entry(viewport.page, width=12)
    entry.place(x=width + 80, y=height + 80)
    root.update()
    viewport._reveal(entry)
    root.update()
    left = entry.winfo_rootx() - viewport.canvas.winfo_rootx()
    top = entry.winfo_rooty() - viewport.canvas.winfo_rooty()
    assert left >= -2 and top >= -2, (left, top)
    assert left + entry.winfo_width() <= viewport.canvas.winfo_width() + 2
    assert top + entry.winfo_height() <= viewport.canvas.winfo_height() + 2
    assert not errors, errors
    print("FOCUS_SELECTION_PASS", width, height, percent)
finally:
    root.destroy()
"""


@pytest.mark.parametrize("size", [(1024, 768), (1365, 768), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize("percent", [100, 125, 150, 175, 200])
def test_focus_and_edit_selection_in_fresh_interpreter(tmp_path, size, percent):
    env = os.environ.copy()
    for name in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        folder = tmp_path / name
        folder.mkdir()
        env[name] = str(folder)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", PROBE, str(size[0]), str(size[1]), str(percent)],
        cwd=Path(__file__).resolve().parents[1],
        env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FOCUS_SELECTION_PASS" in result.stdout

