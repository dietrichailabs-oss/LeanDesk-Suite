"""Actual source widgets at requested viewport/scaling; not Windows DPI proof."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


PROCESS = r'''
import sys
import tkinter as tk
from tkinter import ttk
import leandesk.app as module
from leandesk.core import AppSettings

width, height, percent = map(int, sys.argv[1:])
original = module.configure_suite_styles
def configure(root, theme):
    root.tk.call('tk', 'scaling', (96 / 72) * percent / 100)
    return original(root, theme)
module.configure_suite_styles = configure
settings = AppSettings.load()
settings.auto_check_updates = False
settings.save()
app = module.LeanDeskApp()
def settle():
    for _ in range(3):
        app.update_idletasks()
        app.update()
def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)
def visible(control):
    x, y = control.winfo_rootx(), control.winfo_rooty()
    assert control.winfo_ismapped(), str(control)
    assert x >= app.winfo_rootx() and y >= app.winfo_rooty(), str(control)
    assert x + control.winfo_width() <= app.winfo_rootx() + app.winfo_width(), str(control)
    assert y + control.winfo_height() <= app.winfo_rooty() + app.winfo_height(), str(control)

try:
    for current_width in (width, 1024, width):
        app.geometry(f'{current_width}x{height}+0+0')
        settle()
        assert app.winfo_width() == current_width
        for view in ('Home', 'Writer', 'Sheets', 'Slides', 'Notes', 'Draw', 'Tasks', 'Calendar', 'Contacts', 'Settings'):
            if view == 'Home': app.show_home()
            elif view == 'Settings': app.show_settings()
            else: app.show_module(view)
            settle()
            for control in descendants(app):
                if not isinstance(control, (ttk.Button, tk.Button, ttk.Combobox, ttk.Entry)):
                    continue
                # Only the current page and navigation, not packed-away modules.
                parent = control.master
                ancestors_visible = True
                while parent is not app:
                    if not parent.winfo_ismapped(): ancestors_visible = False; break
                    parent = parent.master
                if not ancestors_visible: continue
                control.focus_force()
                settle()
                visible(control)
            print('R3_LAYOUT_VIEW', current_width, height, percent, view, flush=True)
finally:
    for job in app.tk.call('after', 'info'): app.tk.call('after', 'cancel', job)
    app.destroy()
'''


@pytest.mark.parametrize('width,height', [(1024, 768), (1365, 768), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize('percent', [100, 125, 150, 175, 200])
def test_all_views_controls_remain_reachable_at_viewport_and_scaling(tmp_path, width, height, percent):
    environment = os.environ.copy()
    environment['LOCALAPPDATA'] = str(tmp_path / 'profile')
    environment['LEANDESK_GUI_REPRO_PROFILE'] = environment['LOCALAPPDATA']
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    result = subprocess.run([sys.executable, '-c', PROCESS, str(width), str(height), str(percent)],
                            env=environment, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count('R3_LAYOUT_VIEW') == 30
