"""Native scrollbar reachability, not a substitute for packaged Windows QA."""
import os
import subprocess
import sys

import pytest


PROCESS = r'''
import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import leandesk.app as app_module
from leandesk.core import AppSettings
from leandesk.ui import AccessibleViewport


def exercise(width, height, percent):
    profile = os.environ.get("LEANDESK_GUI_REPRO_PROFILE")
    assert profile and Path(os.environ["LOCALAPPDATA"]).resolve() == Path(profile).resolve()
    settings = AppSettings.load()
    settings.auto_check_updates = False
    settings.save()
    original = app_module.configure_suite_styles

    def configure(root, theme):
        root.tk.call("tk", "scaling", (96 / 72) * percent / 100)
        return original(root, theme)

    app_module.configure_suite_styles = configure
    app = app_module.LeanDeskApp()
    failures = []
    app.report_callback_exception = lambda *args: failures.append(args)

    def settle():
        for _ in range(4):
            app.update_idletasks()
            app.update()

    def assert_scrollbar_reachable(bar, viewport):
        assert bar.winfo_ismapped()
        x, y = bar.winfo_rootx(), bar.winfo_rooty()
        assert x >= viewport.winfo_rootx() and y >= viewport.winfo_rooty()
        assert x + bar.winfo_width() <= viewport.winfo_rootx() + viewport.winfo_width()
        assert y + bar.winfo_height() <= viewport.winfo_rooty() + viewport.winfo_height()
        center = (x + bar.winfo_width() // 2, y + bar.winfo_height() // 2)
        assert app.winfo_containing(*center) is bar, (
            f"Native scrollbar covered at {center}: {app.winfo_containing(*center)}"
        )

    try:
        shell = next(w for w in app.winfo_children() if isinstance(w, ttk.Frame))
        viewports = [w for w in shell.winfo_children() if isinstance(w, AccessibleViewport)]
        assert len(viewports) == 2
        for current_width in (width, 640, width):
            app.geometry(f"{current_width}x{height}+0+0")
            settle()
            for viewport in viewports:
                for position in (0.0, 1.0, 0.0):
                    viewport.canvas.xview_moveto(position)
                    viewport.canvas.yview_moveto(position)
                    settle()
                    assert_scrollbar_reachable(viewport.vertical, viewport)
                    assert_scrollbar_reachable(viewport.horizontal, viewport)
                assert viewport.page.master is viewport.canvas
        assert not failures, [(str(kind), str(value)) for kind, value, _ in failures]
    finally:
        for job in app.tk.call("after", "info"):
            app.tk.call("after", "cancel", job)
        app.destroy()

exercise(*(int(value) for value in sys.argv[1:]))
print("NATIVE_SCROLLBAR_REACHABILITY_PASS", flush=True)
'''


@pytest.mark.parametrize("width,height", [(1024, 768), (1365, 768), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize("percent", [100, 125, 150, 175, 200])
def test_real_shell_scrollbars_are_not_covered_by_oversized_pages(tmp_path, width, height, percent):
    env = os.environ.copy()
    profile = str(tmp_path / "profile")
    env.update(LOCALAPPDATA=profile, LEANDESK_GUI_REPRO_PROFILE=profile,
               PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [sys.executable, "-c", PROCESS, str(width), str(height), str(percent)],
        env=env, capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_SCROLLBAR_REACHABILITY_PASS" in result.stdout
