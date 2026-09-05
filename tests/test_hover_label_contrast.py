"""Resolved ttk state colors must remain semantic across every suite theme."""

import tkinter as tk
from tkinter import ttk

import pytest

from leandesk.themes import SUITE_THEMES, get_theme
from leandesk.ui import apply_suite_theme, configure_suite_styles, set_suite_theme


def _luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _assert_state_colors(root, theme_name):
    style = ttk.Style(root)
    colors = get_theme(theme_name).colors
    hover_roles = {
        "TButton": "button_hover",
        "Primary.TButton": "accent_hover",
        "Sidebar.TButton": "panel2",
        "TCheckbutton": "button_hover",
        "TRadiobutton": "button_hover",
    }
    for name, hover_role in hover_roles.items():
        for state, bg_role in (
            (("active",), hover_role),
            (("active", "selected"), hover_role),
            (("pressed", "active"), "button_pressed"),
        ):
            fg = str(style.lookup(name, "foreground", state))
            bg = str(style.lookup(name, "background", state))
            assert fg == colors["button_active_text"], (theme_name, name, state, fg)
            assert bg == colors[bg_role], (theme_name, name, state, bg)
            light, dark = sorted((_luminance(fg), _luminance(bg)), reverse=True)
            assert (light + 0.05) / (dark + 0.05) >= 4.5, (theme_name, name, state, fg, bg)
        assert str(style.lookup(name, "foreground", ("disabled", "active"))) == colors["disabled_text"]
    assert str(style.lookup("TNotebook.Tab", "foreground", ("active",))) == colors["button_active_text"]
    assert str(style.lookup("TNotebook.Tab", "background", ("active",))) == colors["tab_hover"]
    assert colors["paper"] == "#ffffff"
    assert colors["paper_text"] == "#202124"


@pytest.mark.parametrize("theme_name", tuple(SUITE_THEMES))
def test_hover_labels_fresh_and_live_round_trip(theme_name):
    root = tk.Tk()
    root.withdraw()
    try:
        configure_suite_styles(root, theme_name)
        # Construct the actual control classes, not a mocked style object.
        ttk.Checkbutton(root, text="Automatically check for updates").pack()
        ttk.Radiobutton(root, text="Update cadence").pack()
        ttk.Button(root, text="Check now", style="Primary.TButton").pack()
        root.update_idletasks()
        _assert_state_colors(root, theme_name)
        apply_suite_theme(root, "Light" if theme_name == "Dark" else "Dark")
        apply_suite_theme(root, theme_name)
        root.update_idletasks()
        _assert_state_colors(root, theme_name)
    finally:
        root.destroy()
        set_suite_theme("Dark")
