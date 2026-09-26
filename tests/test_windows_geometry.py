"""Work-area regressions; arithmetic tests are not packaged Windows DPI proof."""
import os

import pytest

from leandesk import windows_geometry as geometry


@pytest.mark.parametrize("width,height", [(1024, 768), (1365, 768), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize("percent", [100, 125, 150, 175, 200])
@pytest.mark.parametrize("taskbar", ["bottom", "top", "left", "right"])
def test_outer_frame_fits_resolution_scale_and_taskbar(width, height, percent, taskbar):
    bar = round(48 * percent / 100)
    work = {"bottom": (0, 0, width, height - bar),
            "top": (0, bar, width, height),
            "left": (bar, 0, width, height),
            "right": (0, 0, width - bar, height)}[taskbar]
    requested = (24, 80, 24 + round(1580 * percent / 100),
                 80 + round(940 * percent / 100) + round(40 * percent / 100))
    fitted = geometry.clamp_outer_bounds(requested, work)
    assert work[0] <= fitted[0] < fitted[2] <= work[2]
    assert work[1] <= fitted[1] < fitted[3] <= work[3]
    assert geometry.clamp_outer_bounds(fitted, work) == fitted


def test_negative_monitor_coordinates_and_existing_valid_bounds():
    work = (-1920, -200, 0, 840)
    assert geometry.clamp_outer_bounds((-1800, -100, -400, 700), work) == (-1800, -100, -400, 700)
    assert geometry.clamp_outer_bounds((-2000, -300, 100, 1000), work) == work


@pytest.mark.parametrize("bounds,work", [((0, 0, 0, 2), (0, 0, 10, 10)),
                                         ((0, 0, 2, 2), (10, 0, 0, 10))])
def test_invalid_bounds_are_not_accepted(bounds, work):
    with pytest.raises(ValueError):
        geometry.clamp_outer_bounds(bounds, work)


class FakeRoot:
    minimum = (640, 360)

    def state(self): return "normal"
    def minsize(self, *value):
        if value: self.minimum = value
        return self.minimum
    def update_idletasks(self): pass
    def winfo_id(self): return 123
    def winfo_width(self): return 500
    def winfo_height(self): return 300


def test_tk_minimum_is_bounded_by_the_fitted_client(monkeypatch):
    monkeypatch.setattr(geometry.os, "name", "nt")
    root = FakeRoot()
    def fit(hwnd):
        assert hwnd == 123 and root.minimum == (1, 1)
        return {"status": "FITTED"}
    monkeypatch.setattr(geometry, "_fit_native_window", fit)
    assert geometry.fit_startup_window(root)["status"] == "FITTED"
    assert root.minimum == (500, 300)


def test_native_failure_restores_minimum_and_is_not_reported_as_fitted(monkeypatch):
    monkeypatch.setattr(geometry.os, "name", "nt")
    root = FakeRoot()
    def fail(hwnd): raise OSError("native probe failed")
    monkeypatch.setattr(geometry, "_fit_native_window", fail)
    result = geometry.fit_startup_window(root)
    assert result == {"status": "ERROR", "error": "native probe failed"}
    assert root.minimum == (640, 360)


@pytest.mark.skipif(os.name != "nt", reason="Requires a real Windows native window")
def test_actual_windows_outer_frame_is_inside_actual_monitor_work_area():
    import tkinter as tk
    root = tk.Tk()
    root.title("LeanDesk isolated startup bounds regression")
    root.geometry("3000x2000+0+0")
    root.minsize(3000, 2000)
    try:
        result = geometry.fit_startup_window(root)
        assert result["status"] == "FITTED", result
        assert geometry.clamp_outer_bounds(result["after"], result["work_area"]) == result["after"]
        assert root.minsize()[0] <= root.winfo_width()
        assert root.minsize()[1] <= root.winfo_height()
    finally:
        root.destroy()
