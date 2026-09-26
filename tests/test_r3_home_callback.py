"""Regression for the existing Home callback's empty ttk wrap-length value."""
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from unittest.mock import Mock

from leandesk.app import LeanDeskApp
from leandesk.ui import configure_suite_styles


def test_home_resize_handles_unset_wraplength_without_callback_errors():
    profile = os.environ.get('LEANDESK_GUI_REPRO_PROFILE')
    assert profile and Path(os.environ['LOCALAPPDATA']).resolve() == Path(profile).resolve()
    root = tk.Tk()
    failures = []
    root.report_callback_exception = lambda *args: failures.append(args)
    configure_suite_styles(root, 'Midnight Copper')
    root.geometry('1024x768')
    harness = Mock()
    harness.home_frame = None
    harness.recent_tree = None
    harness.content = ttk.Frame(root)
    harness.content.pack(fill='both', expand=True)
    try:
        LeanDeskApp.show_home(harness)
        for width in (1024, 1365, 1024):
            root.geometry(f'{width}x768')
            root.update_idletasks()
            root.update()
        assert not failures, [(str(kind), str(value)) for kind, value, _ in failures]
    finally:
        for job in root.tk.call('after', 'info'):
            root.tk.call('after', 'cancel', job)
        root.destroy()
