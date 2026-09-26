"""Partly visible Sheets canvas regression, including toolbar offset."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROBE = r'''
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
    viewport = AccessibleViewport(master=root, minimum_width=1, minimum_height=1)
    root.update()
    available = viewport.canvas.winfo_height()
    # A toolbar consumes the top half. The grid itself fits the viewport,
    # but its bottom lies below it: the case the oversized-widget test misses.
    viewport.minimum_height = round((available + available // 4) / max(1, percent / 100))
    toolbar = ttk.Frame(viewport.page, height=available // 2)
    toolbar.pack(fill="x")
    toolbar.pack_propagate(False)
    button = ttk.Button(toolbar, text="Toolbar focus")
    button.pack()
    model = SheetModel()
    grid = SheetGrid(viewport.page, model, lambda: None, lambda *args: None)
    grid.pack(fill="both", expand=True)
    root.update()
    viewport.canvas.xview_moveto(0)
    viewport.canvas.yview_moveto(0)
    button.focus_force()
    root.update()
    origin = (viewport.canvas.canvasx(0), viewport.canvas.canvasy(0))
    top = grid.canvas.winfo_rooty() - viewport.canvas.winfo_rooty()
    assert 0 < top < viewport.canvas.winfo_height()
    assert grid.canvas.winfo_height() <= viewport.canvas.winfo_height()
    assert top + grid.canvas.winfo_height() > viewport.canvas.winfo_height()
    left, top, right, bottom = grid._cell_bounds(0, 2)
    point = (grid.canvas.winfo_rootx() + (left + right) / 2,
             grid.canvas.winfo_rooty() + (top + bottom) / 2)
    def event():
        return SimpleNamespace(x=point[0] - grid.canvas.winfo_rootx(),
                               y=point[1] - grid.canvas.winfo_rooty(), state=0)
    assert grid._address_from_event(event()) == "C1"
    grid.canvas.event_generate("<ButtonPress-1>", x=int(event().x), y=int(event().y))
    root.update()
    grid.canvas.event_generate("<ButtonRelease-1>", x=int(event().x), y=int(event().y))
    root.update()
    # Focus must not move the target before the second click arrives.
    after = (viewport.canvas.canvasx(0), viewport.canvas.canvasy(0))
    assert all(abs(a-b) <= 1 for a,b in zip(origin,after)), ("POINTER_TARGET_MOVED", origin, after)
    assert grid._address_from_event(event()) == "C1"
    grid.begin_edit(event())
    root.update()
    assert grid.editor is not None
    assert grid.active_address == grid.selection.anchor == grid.selection.active == "C1"
    assert all(abs(a-b) <= 1 for a,b in zip(origin, (viewport.canvas.canvasx(0), viewport.canvas.canvasy(0))))
    grid.cancel_edit()
    root.update()
    assert grid.active_address == grid.selection.active == "C1"
    assert model.raw("C1") == ""
    assert not errors, errors
    print("PARTIAL_EDITOR_FOCUS_PASS", width, height, percent)
finally:
    root.destroy()
'''


@pytest.mark.parametrize("size", [(1024, 768), (1365, 768), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize("percent", [100, 125, 150, 175, 200])
def test_partial_grid_pointer_target_stable(tmp_path, size, percent):
    env = os.environ.copy()
    for name in ("LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        folder = tmp_path / name
        folder.mkdir()
        env[name] = str(folder)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", PROBE, str(size[0]), str(size[1]), str(percent)],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PARTIAL_EDITOR_FOCUS_PASS" in result.stdout
