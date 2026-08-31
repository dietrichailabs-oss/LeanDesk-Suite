from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import tkinter as tk

import pytest

from leandesk.core import AppSettings
from leandesk.app import LeanDeskApp
from leandesk.sheets import SheetGrid, SheetModel
from leandesk.themes import SUITE_THEMES, get_theme
from leandesk.ui import COLORS, apply_suite_theme, configure_suite_styles
from leandesk.updates.update_checker import check_for_updates
from leandesk.updates.update_manifest import ManifestError, parse_manifest


EXPECTED_THEMES = (
    "Dark",
    "Light",
    "Midnight Copper",
    "Slate Blue",
    "Forest Slate",
    "Burgundy Office",
    "Desert Sand",
    "Ocean Mist",
    "Graphite Teal",
    "Lavender Office",
)


def _manifest(**changes) -> bytes:
    payload = {
        "product": "leandesk-suite",
        "latest_version": "0.8.0",
        "release_name": "LeanDesk Suite 0.8.0",
        "published_at": "2026-08-26T23:04:22Z",
        "release_url": "https://www.dietrichailabs.com/leandesk.html",
        "download_url": "https://downloads.dietrichailabs.com/LeanDesk_Suite_0.8.0.zip",
        "sha256": "A" * 64,
        "message": "LeanDesk Suite 0.8.0 is now available.",
    }
    payload.update(changes)
    return json.dumps(payload).encode("utf-8")


class FakeResponse:
    status = 200
    headers = {"Content-Length": "500"}

    def __init__(self, body: bytes, final_url: str = "https://www.dietrichailabs.com/updates/leandesk.json"):
        self.body = body
        self.final_url = final_url

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self):
        return self.final_url

    def read(self, _limit: int):
        return self.body


def test_exact_historical_ten_theme_registry_and_palette_markers() -> None:
    assert tuple(SUITE_THEMES) == EXPECTED_THEMES
    assert get_theme("Midnight Copper").colors["bg"] == "#17181f"
    assert get_theme("Slate Blue").colors["cobalt"] == "#68a5ff"
    assert get_theme("Forest Slate").colors["panel"] == "#1d302a"
    assert get_theme("Burgundy Office").colors["selection"] == "#704052"
    assert get_theme("Desert Sand").colors["field"] == "#fffdf9"
    assert get_theme("Ocean Mist").colors["workspace"] == "#cedce1"
    assert get_theme("Graphite Teal").colors["jade"] == "#4cc5b0"
    assert get_theme("Lavender Office").colors["selection"] == "#d6cdf3"


@pytest.mark.parametrize("theme_name", EXPECTED_THEMES)
def test_theme_settings_round_trip(tmp_path: Path, theme_name: str) -> None:
    path = tmp_path / "settings.json"
    settings = AppSettings(theme=theme_name)
    assert settings.save(path)
    assert AppSettings.load(path).theme == theme_name


def test_all_live_themes_reach_classic_widgets_and_preserve_paper() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        configure_suite_styles(root, "Dark")
        frame = tk.Frame(root, bg=COLORS["panel"])
        label = tk.Label(frame, bg=COLORS["panel"], fg=COLORS["text"])
        editor = tk.Text(frame, bg=COLORS["paper_alt"], fg=COLORS["paper_text"])
        frame.pack()
        label.pack()
        editor.pack()
        for theme_name in EXPECTED_THEMES:
            theme = apply_suite_theme(root, theme_name)
            assert frame.cget("background") == theme.colors["panel"]
            assert label.cget("foreground") == theme.colors["text"]
            assert editor.cget("background") == "#fdfcf8"
            assert editor.cget("foreground") == "#202124"
    finally:
        root.destroy()


THEME_COLOR_OPTIONS = (
    "background", "foreground", "activebackground", "activeforeground",
    "highlightbackground", "highlightcolor", "selectbackground",
    "selectforeground", "insertbackground", "troughcolor", "selectcolor",
)
THEME_CANVAS_OPTIONS = (
    "fill", "outline", "activefill", "activeoutline", "disabledfill", "disabledoutline",
)


def _cancel_scheduled_callbacks(root: tk.Misc) -> None:
    callback_ids = root.tk.call("after", "info")
    if isinstance(callback_ids, str):
        callback_ids = (callback_ids,) if callback_ids else ()
    for callback_id in callback_ids:
        try:
            root.tk.call("after", "cancel", callback_id)
        except tk.TclError:
            pass


def _whole_app_theme_snapshot(widget: tk.Misc, output: dict[str, object]) -> None:
    record: dict[str, object] = {"class": widget.winfo_class()}
    for option in THEME_COLOR_OPTIONS:
        try:
            value = widget.cget(option)
        except tk.TclError:
            continue
        if value not in ("", None):
            record[option] = str(value).lower()
    if isinstance(widget, tk.Canvas):
        items: list[dict[str, str]] = []
        for item_id in widget.find_all():
            item = {"type": widget.type(item_id)}
            for option in THEME_CANVAS_OPTIONS:
                try:
                    value = widget.itemcget(item_id, option)
                except tk.TclError:
                    continue
                if value not in ("", None):
                    item[option] = str(value).lower()
            items.append(item)
        record["canvas_items"] = items
    output[str(widget)] = record
    for child in widget.winfo_children():
        _whole_app_theme_snapshot(child, output)


@pytest.mark.parametrize("theme_name", EXPECTED_THEMES)
def test_fresh_whole_app_theme_matches_round_trip(
    monkeypatch: pytest.MonkeyPatch, theme_name: str,
) -> None:
    selected_theme = [theme_name]
    monkeypatch.setattr(
        AppSettings,
        "load",
        lambda: AppSettings(theme=selected_theme[0], auto_check_updates=False),
    )
    app = LeanDeskApp()
    app.withdraw()
    try:
        _cancel_scheduled_callbacks(app)
        app.show_settings()
        app.update_idletasks()
        fresh: dict[str, object] = {}
        _whole_app_theme_snapshot(app, fresh)

        intermediate = "Light" if theme_name == "Dark" else "Dark"
        apply_suite_theme(app, intermediate)
        app.update()
        apply_suite_theme(app, theme_name)
        app.update()
        round_trip: dict[str, object] = {}
        _whole_app_theme_snapshot(app, round_trip)

        assert fresh == round_trip
        writer = app.frames["Writer"]
        calendar = app.frames["Calendar"]
        calendar_buttons = [
            child for child in calendar.grid_frame.winfo_children()
            if child.winfo_class() == "Button"
        ]
        palette = get_theme(theme_name).colors
        assert writer.tab_strip.cget("background") == palette["tab_bg"]
        assert writer.status_frame.cget("background") == palette["status_bg"]
        assert {button.cget("activebackground") for button in calendar_buttons} == {palette["button_hover"]}
        assert palette["selection"] in {button.cget("background") for button in calendar_buttons}
    finally:
        app.destroy()


def test_sheet_grid_draws_every_cell_boundary_and_strong_selection_in_dark_and_light() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        configure_suite_styles(root, "Dark")
        model = SheetModel(cells={"A1": "Header", "B2": "=1+1"})
        selected: list[tuple[str, str]] = []
        grid = SheetGrid(root, model, lambda: None, lambda address, raw: selected.append((address, raw)))
        grid.pack()
        for theme_name in ("Dark", "Light", "Midnight Copper"):
            theme = apply_suite_theme(root, theme_name)
            root.update()
            rectangles = [item for item in grid.canvas.find_withtag("grid") if grid.canvas.type(item) == "rectangle"]
            assert len(rectangles) == 1 + grid.COLS + grid.ROWS + grid.ROWS * grid.COLS
            active = [item for item in rectangles if grid.canvas.itemcget(item, "outline") == COLORS["focus"] and float(grid.canvas.itemcget(item, "width")) == 2.0]
            assert len(active) == 1
            unselected_cell = next(
                item for item in rectangles
                if tuple(grid.canvas.coords(item)) == tuple(grid._cell_bounds(2, 2))
            )
            assert grid.canvas.itemcget(unselected_cell, "fill") == theme.colors["field"]
            grid.select_address("B2")
            assert grid.active_address == "B2"
            assert selected[-1] == ("B2", "=1+1")
        grid.destroy()
    finally:
        root.destroy()


def test_sheet_grid_edit_and_column_resize_round_trip() -> None:
    root = tk.Tk()
    root.geometry("900x500+50+50")
    try:
        changes: list[bool] = []
        model = SheetModel()
        grid = SheetGrid(root, model, lambda: changes.append(True), lambda *_args: None)
        grid.pack(fill="both", expand=True)
        root.update()
        grid.begin_edit()
        assert grid.editor is not None
        grid.editor.insert(0, "42")
        grid.commit_edit("A1")
        assert model.raw("A1") == "42"
        original = grid.column_widths[0]
        event = type("Event", (), {"x": grid._x_positions[1], "y": 3})()
        grid._button_press(event)
        move = type("Event", (), {"x": grid._x_positions[1] + 25, "y": 3})()
        grid._resize_motion(move)
        grid._button_release(move)
        assert model.column_widths["A"] == original + 25
        assert changes
    finally:
        root.destroy()


def test_live_manifest_paths_are_accepted_without_weakening_endpoint_rules() -> None:
    parsed = parse_manifest(_manifest())
    assert parsed.release_url == "https://www.dietrichailabs.com/leandesk.html"
    assert parsed.download_url == "https://downloads.dietrichailabs.com/LeanDesk_Suite_0.8.0.zip"
    with pytest.raises(ManifestError):
        parse_manifest(_manifest(release_url="https://www.dietrichailabs.com/leandesk.html.evil"))
    with pytest.raises(ManifestError):
        parse_manifest(_manifest(download_url="https://evil.example/LeanDesk_Suite_0.8.0.zip"))


def test_updater_reports_current_against_live_shape(tmp_path: Path) -> None:
    result = check_for_updates(
        "0.8.1", force=True,
        opener=lambda *_args, **_kwargs: FakeResponse(_manifest()),
        state_path=tmp_path / "update.json",
        now=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert result.status == "current"
    assert result.checked
    assert result.error_category is None


def test_updater_timeout_has_useful_nonfatal_category(tmp_path: Path) -> None:
    def timeout(*_args, **_kwargs):
        raise socket.timeout("offline")

    result = check_for_updates(
        "0.8.1", force=True, opener=timeout,
        state_path=tmp_path / "update.json",
        now=datetime(2026, 8, 30, tzinfo=timezone.utc),
    )
    assert result.status == "error"
    assert result.error_category == "timeout"
    assert "timeout" in (result.error or "").lower()
