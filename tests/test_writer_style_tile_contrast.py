"""Real Writer style tiles retain readable semantic colors in all ten themes."""

import tkinter as tk

import pytest

from leandesk.core import AppSettings, RecentFiles
from leandesk.themes import SUITE_THEMES, get_theme
from leandesk.ui import apply_suite_theme, configure_suite_styles, set_suite_theme
from leandesk.writer import WriterFrame


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _assert_tiles(frame, theme_name):
    colors = get_theme(theme_name).colors
    labels = {"Normal", "Heading 1", "Heading 2", "Heading 3", "Title"}
    tiles = [w for w in _descendants(frame.ribbon_body)
             if isinstance(w, tk.Button) and w.cget("text") in labels]
    assert len(tiles) == len(labels)
    for button in tiles:
        normal = button.cget("text") == "Normal"
        expected = {
            "background": "button_pressed" if normal else "button_bg",
            "foreground": "button_active_text" if normal else "button_text",
            "activebackground": "button_hover",
            "activeforeground": "button_active_text",
        }
        assert button._leandesk_theme_roles == expected
        for option, role in expected.items():
            assert str(button.cget(option)) == colors[role], (theme_name, button.cget("text"), option)
        for state, fg_option, bg_option in (
            ("normal", "foreground", "background"),
            ("active", "activeforeground", "activebackground"),
        ):
            button.configure(state=state)
            fg, bg = str(button.cget(fg_option)), str(button.cget(bg_option))
            light, dark = sorted((_luminance(fg), _luminance(bg)), reverse=True)
            assert (light + 0.05) / (dark + 0.05) >= 4.5, (theme_name, button.cget("text"), state, fg, bg)
        button.configure(state="normal")


@pytest.mark.parametrize("theme_name", tuple(SUITE_THEMES))
def test_writer_style_tiles_fresh_live_switch_and_rebuild(tmp_path, monkeypatch, theme_name):
    for key in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME"):
        monkeypatch.setenv(key, str(tmp_path))
    root = tk.Tk()
    root.withdraw()
    try:
        configure_suite_styles(root, theme_name)
        frame = WriterFrame(root, recent=RecentFiles(tmp_path / "recent.json"), settings=AppSettings())
        frame.pack()
        root.update_idletasks()
        _assert_tiles(frame, theme_name)
        other = "Light" if theme_name == "Dark" else "Dark"
        apply_suite_theme(root, other)
        root.update_idletasks()
        _assert_tiles(frame, other)
        apply_suite_theme(root, theme_name)
        root.update_idletasks()
        _assert_tiles(frame, theme_name)
        frame._show_ribbon_tab("Insert")
        frame._show_ribbon_tab("Home")
        root.update_idletasks()
        _assert_tiles(frame, theme_name)
    finally:
        for job in root.tk.call("after", "info"):
            # Cancel scheduling without deleting another widget's registered
            # Tcl command; its owning widget releases that during destroy().
            root.tk.call("after", "cancel", job)
        root.destroy()
        set_suite_theme("Dark")
