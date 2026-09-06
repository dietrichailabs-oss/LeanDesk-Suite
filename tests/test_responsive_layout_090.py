"""Issue #7 actual widget geometry at small and normal desktop viewports.

Source GUI regressions, not substitutes for signed Windows lifecycle evidence.
Each case runs in a fresh interpreter in the authoritative gate.
"""
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

import pytest

from leandesk.app import LeanDeskApp
from leandesk.core import AppSettings, RecentFiles
from leandesk.draw import DrawFrame
from leandesk.ui import configure_suite_styles
from leandesk.writer import WriterFrame


@pytest.fixture
def root():
    profile = os.environ.get("LEANDESK_GUI_REPRO_PROFILE")
    assert profile and Path(os.environ["LOCALAPPDATA"]).resolve() == Path(profile).resolve()
    window = tk.Tk()
    configure_suite_styles(window, "Midnight Copper")
    yield window
    for job in window.tk.call("after", "info"):
        window.tk.call("after", "cancel", job)
    window.destroy()


def settle(root):
    for _ in range(4):
        root.update_idletasks()
        root.update()


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def assert_inside(widget, container):
    assert widget.winfo_ismapped(), str(widget)
    x = widget.winfo_rootx() - container.winfo_rootx()
    y = widget.winfo_rooty() - container.winfo_rooty()
    assert x >= 0 and y >= 0, str(widget)
    assert x + widget.winfo_width() <= container.winfo_width(), str(widget)
    assert y + widget.winfo_height() <= container.winfo_height(), str(widget)
    assert widget.winfo_width() >= widget.winfo_reqwidth(), str(widget)
    assert widget.winfo_height() >= widget.winfo_reqheight(), str(widget)


def shell(root, width):
    root.geometry(f"{width}x768+0+0")
    sidebar = ttk.Frame(root, width=196)
    sidebar.pack(side="left", fill="y")
    sidebar.pack_propagate(False)
    content = ttk.Frame(root)
    content.pack(side="left", fill="both", expand=True)
    return content


class HomeHarness:
    """Exercise the real Home builder without starting unrelated modules/network."""
    home_frame = None
    recent_tree = None

    def __init__(self, content):
        self.content = content

    def _clear_view(self):
        pass

    def _set_active(self, name):
        pass

    def title(self, value):
        pass

    def refresh_home_recent(self):
        pass

    def clean_missing(self):
        pass

    def open_selected_recent(self, event=None):
        pass

    def show_module(self, name):
        self.opened_module = name


@pytest.mark.parametrize("width", [1024, 1365, 1920])
def test_home_cards_wrap_without_overlap_and_open_buttons_work(root, width):
    home = HomeHarness(shell(root, width))
    LeanDeskApp.show_home(home)
    for viewport in (width, 1024, width):
        root.geometry(f"{viewport}x768+0+0")
        settle(root)
        badges = [w for w in descendants(home.home_frame) if isinstance(w, ttk.Label) and w.cget("text") == "READY FOR TESTING"]
        assert len(badges) == 6
        cards = [w.master for w in badges]
        assert len({w.winfo_y() for w in cards}) == 2
        for badge in badges:
            card = badge.master
            assert_inside(card, root)
            labels = [w for w in card.winfo_children() if isinstance(w, ttk.Label)]
            for label in labels:
                assert_inside(label, card)
            for first, second in zip(labels, labels[1:]):
                assert first.winfo_y() + first.winfo_height() <= second.winfo_y()
            title, _, description = labels
            assert int(description.cget("wraplength")) <= card.winfo_width() - 32
            button = next(w for w in card.winfo_children() if isinstance(w, ttk.Button))
            assert_inside(button, card)
            button.invoke()
            expected = title.cget("text").title()
            assert home.opened_module == ("Tasks" if expected == "Organizer" else expected)


@pytest.mark.parametrize("width", [1024, 1365, 1920])
@pytest.mark.parametrize("tab", ["Home", "Insert", "Layout", "Review", "View", "Help"])
def test_writer_ribbon_controls_fit_and_remain_reachable_after_resize(root, width, tab):
    frame = WriterFrame(shell(root, width), recent=RecentFiles(), settings=AppSettings())
    frame.pack(fill="both", expand=True)
    frame._show_ribbon_tab(tab)
    for viewport in (width, 1024, width):
        root.geometry(f"{viewport}x768+0+0")
        settle(root)
        controls = [w for w in descendants(frame.ribbon_body) if isinstance(w, (tk.Button, tk.Menubutton, tk.Checkbutton, tk.Label, ttk.Combobox))]
        assert controls
        for control in controls:
            assert_inside(control, frame.ribbon_body)
            assert_inside(control, control.master)
        for control in [frame.file_button, *frame.tab_buttons.values()]:
            assert_inside(control, frame.tab_strip)
        assert frame.canvas.winfo_height() >= 150
        if viewport == 1920:
            assert len({w.winfo_y() for w in frame.ribbon_body.winfo_children()}) == 1


@pytest.mark.parametrize("width", [1024, 1365, 1920])
def test_draw_all_toolbar_commands_wrap_and_tools_still_select(root, width):
    frame = DrawFrame(shell(root, width), recent=RecentFiles())
    frame.pack(fill="both", expand=True)
    ribbon = frame.winfo_children()[0]
    for viewport in (width, 1024, width):
        root.geometry(f"{viewport}x768+0+0")
        settle(root)
        controls = [w for w in ribbon.winfo_children() if isinstance(w, (ttk.Button, ttk.Radiobutton))]
        assert len(controls) == 18
        for control in controls:
            assert_inside(control, ribbon)
            assert_inside(control, root)
            if isinstance(control, ttk.Radiobutton):
                control.invoke()
                assert frame.tool.get() == str(control.cget("value"))
        assert frame.canvas.winfo_height() >= 350
