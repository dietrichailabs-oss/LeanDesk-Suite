"""Issue #7 source GUI reproductions, not packaged or physical-input QA.

Run with LOCALAPPDATA pointing to a disposable directory before Python starts.
These tests intentionally precede implementation corrections. Native printing,
physical formula drag, DPI, and full lifecycle evidence remain separate gates.
"""
from pathlib import Path
import os
import subprocess
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk

import pytest

from leandesk import notes, sheets, slides, writer
from leandesk.core import AppSettings, RecentFiles
from leandesk.ui import configure_suite_styles, apply_suite_theme


@pytest.fixture
def root(tmp_path, monkeypatch):
    profile = os.environ.get("LEANDESK_GUI_REPRO_PROFILE", "")
    assert profile and Path(os.environ["LOCALAPPDATA"]).resolve() == Path(profile).resolve(), "Require an explicitly isolated test profile"
    monkeypatch.setattr(notes, "NOTES_FILE", tmp_path / "notes.json")
    window = tk.Tk()
    window.geometry("1365x768+0+0")
    configure_suite_styles(window, "Midnight Copper")
    yield window
    for job in window.tk.call("after", "info"):
        # Cancel scheduling without deleting commands owned by child widgets.
        # Their destroy() methods release their own registered Tcl commands.
        window.tk.call("after", "cancel", job)
    window.destroy()


def mount(root, cls):
    sidebar = ttk.Frame(root, width=210)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
    kwargs = {"recent": RecentFiles()}
    if cls is writer.WriterFrame:
        kwargs["settings"] = AppSettings()
    frame = cls(root, **kwargs)
    frame.pack(side="left", fill="both", expand=True)
    root.update()
    return frame


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


@pytest.mark.parametrize("title", ["x", "Meeting notes", "QA Summary"])
def test_gui01_new_note_does_not_copy_previous_editor(root, monkeypatch, title):
    frame = mount(root, notes.NotesFrame)
    original = frame.notes[0].to_dict()
    monkeypatch.setattr(notes.simpledialog, "askstring", lambda *a, **k: title)
    frame.new_note()
    root.update()
    created = frame.get_note(frame.current_id)
    assert created.title == title
    assert created.body == ""
    assert sum(n.title == "Welcome to LeanDesk Notes" for n in frame.notes) == 1
    assert frame.save_now()
    frame.load()
    assert any(n.title == title and n.body == "" for n in frame.notes)
    assert frame.get_note(original["note_id"]).body == original["body"]


def test_gui01_cancel_new_note_does_not_create(root, monkeypatch):
    frame = mount(root, notes.NotesFrame)
    count = len(frame.notes)
    monkeypatch.setattr(notes.simpledialog, "askstring", lambda *a, **k: None)
    frame.new_note()
    assert len(frame.notes) == count


@pytest.mark.parametrize("cls", [sheets.SheetsFrame, slides.SlidesFrame, notes.NotesFrame])
def test_gui02_essential_toolbar_buttons_are_reachable(root, cls):
    frame = mount(root, cls)
    ribbon = frame.winfo_children()[0]
    buttons = [w for w in ribbon.winfo_children() if isinstance(w, ttk.Button)]
    assert buttons
    hidden = [w.cget("text") for w in buttons if not w.winfo_ismapped() or w.winfo_rootx() + w.winfo_width() > ribbon.winfo_rootx() + ribbon.winfo_width()]
    assert not hidden, f"Essential commands clipped at 1365x768: {hidden}"


def test_gui02_notes_list_has_usable_width(root):
    frame = mount(root, notes.NotesFrame)
    assert frame.note_list.winfo_width() >= 180


def test_gui03_print_does_not_depend_on_rtf_shell_verb(root, monkeypatch, tmp_path):
    frame = mount(root, writer.WriterFrame)
    frame.text.insert("1.0", "Print preservation sentinel")
    before = frame.text.get("1.0", "end-1c")
    calls, errors = [], []
    def association_missing(path, operation):
        calls.append((path, operation))
        raise OSError(1155, "No application is associated with this file")
    monkeypatch.setattr(writer.os, "startfile", association_missing)
    monkeypatch.setattr(writer.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(writer.messagebox, "showerror", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(writer.messagebox, "showinfo", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout='{"status":"cancelled"}', stderr=""))
    frame.print_document()
    assert frame.text.get("1.0", "end-1c") == before
    assert not any(Path(p).suffix.lower() == ".rtf" and op == "print" for p, op in calls), "Writer still relies on a registered RTF shell print verb"
    assert not list(tmp_path.glob("LeanDesk_Print*")), "Print temporary file was leaked"


def contrast(widget, foreground, background):
    def luminance(color):
        values = [v / 65535 for v in widget.winfo_rgb(color)]
        linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
        return sum(a * b for a, b in zip(linear, (.2126, .7152, .0722)))
    lo, hi = sorted((luminance(foreground), luminance(background)))
    return (hi + .05) / (lo + .05)


def test_gui04_light_notes_labels_have_readable_contrast(root):
    frame = mount(root, notes.NotesFrame)
    apply_suite_theme(root, "Light")
    root.update()
    failures = []
    for widget in descendants(frame):
        if isinstance(widget, tk.Label) and widget.winfo_ismapped():
            ratio = contrast(widget, widget.cget("foreground"), widget.cget("background"))
            if ratio < 4.5:
                failures.append((widget.cget("text"), round(ratio, 2)))
    assert not failures, failures


def test_gui05_rename_preserves_active_sheet_and_edit_target(root, monkeypatch):
    frame = mount(root, sheets.SheetsFrame)
    frame.workbook.sheets.append(sheets.SheetModel(name="Sheet2"))
    frame.rebuild_tabs()
    frame.notebook.select(1)
    root.update()
    target = frame.active_sheet()
    monkeypatch.setattr(sheets.simpledialog, "askstring", lambda *a, **k: "QA Summary")
    frame.rename_sheet()
    root.update()
    assert frame.active_sheet() is target
    assert frame.active_sheet().name == "QA Summary"
    frame.active_grid().set_cells([("A1", "renamed sheet edit")])
    assert target.raw("A1") == "renamed sheet edit"
    assert frame.workbook.sheets[0].raw("A1") == ""


@pytest.mark.parametrize("start,end,expected", [("A1", "B1", "A1:B1"), ("A1", "A2", "A1:A2"), ("B1", "A1", "A1:B1"), ("A1", "B2", "A1:B2")])
def test_gui06_synthetic_drag_reference_contract(root, start, end, expected):
    """Synthetic source event test only; physical packaged reproduction is required."""
    frame = mount(root, sheets.SheetsFrame)
    grid = frame.active_grid()
    grid.set_cells([("A1", "12"), ("B1", "24")])
    grid.select_address("C1")
    frame.formula_var.set("=SUM(")
    frame.formula_entry.focus_force()
    frame.formula_entry.icursor("end")
    root.update()
    # Focus-in processing can reset an Entry's caret; establish the actual
    # precondition only after queued focus events have completed.
    frame.formula_entry.icursor("end")
    assert frame.focus_get() == frame.formula_entry
    assert frame.formula_entry.index(tk.INSERT) == len("=SUM(")
    def point(address):
        row, col = sheets.split_cell(address)
        x1, y1, x2, y2 = grid._cell_bounds(row, col)
        return int((x1 + x2) / 2), int((y1 + y2) / 2)
    x, y = point(start)
    grid.canvas.event_generate("<ButtonPress-1>", x=x, y=y)
    root.update()
    x, y = point(end)
    grid.canvas.event_generate("<B1-Motion>", x=x, y=y)
    grid.canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
    root.update()
    assert frame.formula_var.get() == "=SUM(" + expected
    frame.formula_var.set(frame.formula_var.get() + ")")
    frame.commit_formula_bar()
    if expected == "A1:B1":
        assert frame.active_sheet().value("C1") == 36


@pytest.mark.parametrize("theme", ["Dark", "Light", "Midnight Copper", "Slate Blue", "Forest Slate", "Burgundy Office", "Desert Sand", "Ocean Mist", "Graphite Teal", "Lavender Office"])
def test_gui04_explicit_ttk_foreground_roundtrip(root, theme):
    from leandesk.ui import COLORS
    label = ttk.Label(root, text="LEANDESK", foreground=COLORS["text"])
    label.pack()
    apply_suite_theme(root, theme)
    root.update()
    assert str(label.cget("foreground")).lower() == COLORS["text"].lower()
    apply_suite_theme(root, "Midnight Copper")
    apply_suite_theme(root, theme)
    assert str(label.cget("foreground")).lower() == COLORS["text"].lower()


def test_gui02_slide_background_fits_actual_preview(root):
    frame = mount(root, slides.SlidesFrame)
    root.geometry("1024x700")
    root.update()
    frame.render_slide()
    rectangles = [i for i in frame.canvas.find_all() if frame.canvas.type(i) == "rectangle"]
    x1, y1, x2, y2 = frame.canvas.coords(rectangles[0])
    assert 0 <= x1 < x2 <= frame.canvas.winfo_width()
    assert 0 <= y1 < y2 <= frame.canvas.winfo_height()


@pytest.mark.parametrize("outcome", ["submitted", "cancelled", "error", "timeout"])
def test_gui03_native_print_dispatch_cleanup(root, monkeypatch, tmp_path, outcome):
    from leandesk.windows_print import print_rtf_document, PrintUnavailableError
    from leandesk.document_formats import LeanDocument
    seen = []
    def run(command, **kwargs):
        path = Path(kwargs["env"]["LEANDESK_PRINT_RTF"])
        assert path.is_file()
        seen.append(path)
        assert "-STA" in command
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        if outcome == "error":
            return SimpleNamespace(returncode=1, stdout='{"status":"error","message":"No printer available"}', stderr="")
        return SimpleNamespace(returncode=0, stdout='{"status":"' + outcome + '"}', stderr="")
    monkeypatch.setattr(subprocess, "run", run)
    if outcome in {"error", "timeout"}:
        with pytest.raises(PrintUnavailableError):
            print_rtf_document(LeanDocument(), owner=root.winfo_id())
    else:
        assert print_rtf_document(LeanDocument(), owner=root.winfo_id()) == outcome
    assert seen and all(not p.exists() for p in seen)
