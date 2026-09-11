"""Exercise native menu teardown, not only a direct on_close invocation."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows native Tk menu regression")
def test_file_menu_exit_after_live_theme_changes(tmp_path):
    source = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for key, leaf in (("LOCALAPPDATA", "Local"), ("APPDATA", "Roaming"), ("TEMP", "Temp"), ("TMP", "Temp")):
        folder = tmp_path / leaf
        folder.mkdir(exist_ok=True)
        env[key] = str(folder)
    code = r'''
import faulthandler
faulthandler.enable()
from tkinter import ttk
from leandesk.app import LeanDeskApp
app = LeanDeskApp()
errors = []
completed = []
app.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)
def exercise():
    menu = app.nametowidget(app.cget("menu"))
    sections = {menu.entrycget(i, "label"): app.nametowidget(menu.entrycget(i, "menu"))
                for i in range(menu.index("end") + 1) if menu.type(i) == "cascade"}
    modules = sections["Modules"]
    names = {"Writer", "Sheets", "Slides", "Notes", "Draw", "Tasks", "Calendar", "Contacts"}
    visited = set()
    for i in range(modules.index("end") + 1):
        if modules.type(i) == "command" and modules.entrycget(i, "label") in names:
            visited.add(modules.entrycget(i, "label"))
            modules.invoke(i)
            app.update_idletasks()
    assert visited == names
    app.show_settings()
    picker = next(w for w in walk(app) if isinstance(w, ttk.Combobox) and "Midnight Copper" in w.cget("values"))
    for name in ("Midnight Copper", "Dark"):
        app.tk.call("ttk::combobox::Post", picker)
        app.update()
        app.tk.call("ttk::combobox::Unpost", picker)
        picker.set(name)
        picker.event_generate("<<ComboboxSelected>>")
        app.update()
    file_menu = sections["File"]
    index = next(i for i in range(file_menu.index("end") + 1)
                 if file_menu.type(i) == "command" and file_menu.entrycget(i, "label") == "Exit")
    file_menu.invoke(index)
    # The menu callback must unwind before root/widget destruction begins.
    assert app.winfo_exists()
    assert app._close_scheduled
    completed.append(True)
app.after(100, exercise)
app.mainloop()
assert completed == [True], completed
assert not errors, errors
print("NATIVE_MENU_SHUTDOWN_PASS", flush=True)
'''
    result = subprocess.run([sys.executable, "-B", "-u", "-c", code], cwd=source, env=env,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_MENU_SHUTDOWN_PASS" in result.stdout
    assert not result.stderr, result.stderr
