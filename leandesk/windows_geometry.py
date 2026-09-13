"""Keep the initial native window inside the current monitor's work area."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import tkinter as tk


Rect = tuple[int, int, int, int]


def clamp_outer_bounds(bounds: Rect, work_area: Rect) -> Rect:
    left, top, right, bottom = work_area
    if right <= left or bottom <= top:
        raise ValueError("Invalid monitor work area")
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    if width <= 0 or height <= 0:
        raise ValueError("Invalid outer window bounds")
    width, height = min(width, right - left), min(height, bottom - top)
    x = min(max(bounds[0], left), right - width)
    y = min(max(bounds[1], top), bottom - height)
    return x, y, x + width, y + height


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _rect(value: wintypes.RECT) -> Rect:
    return value.left, value.top, value.right, value.bottom


def _fit_native_window(tk_hwnd: int) -> dict:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    signatures = {
        "GetAncestor": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
        "MonitorFromWindow": ([wintypes.HWND, wintypes.DWORD], wintypes.HANDLE),
        "GetMonitorInfoW": ([wintypes.HANDLE, ctypes.POINTER(_MonitorInfo)], wintypes.BOOL),
        "GetWindowRect": ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        "SetWindowPos": ([wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                          ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        "SetThreadDpiAwarenessContext": ([ctypes.c_void_p], ctypes.c_void_p),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(user32, name)
        function.argtypes, function.restype = arguments, result

    # Use one physical-pixel context for measurement AND positioning. Restore
    # it before returning to Tk; never change process/window DPI awareness.
    previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        hwnd = user32.GetAncestor(tk_hwnd, 2)  # GA_ROOT: Tk's native frame.
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        monitor = user32.MonitorFromWindow(hwnd, 2)  # Nearest monitor.
        info = _MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        rectangle = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
            raise ctypes.WinError(ctypes.get_last_error())
        before, work_area = _rect(rectangle), _rect(info.rcWork)
        target = clamp_outer_bounds(before, work_area)
        if target != before:
            x, y, right, bottom = target
            if not user32.SetWindowPos(hwnd, None, x, y, right - x, bottom - y, 0x0014):
                raise ctypes.WinError(ctypes.get_last_error())
        if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
            raise ctypes.WinError(ctypes.get_last_error())
        after = _rect(rectangle)
        if clamp_outer_bounds(after, work_area) != after:
            raise OSError("Native startup window still exceeds monitor work area")
        return {"status": "FITTED", "before": before, "work_area": work_area,
                "after": after}
    finally:
        if not user32.SetThreadDpiAwarenessContext(previous):
            raise OSError("Could not restore the thread DPI awareness context")


def fit_startup_window(root) -> dict:
    if os.name != "nt":
        return {"status": "NOT_APPLICABLE"}
    if root.state() != "normal":
        return {"status": "NOT_NORMAL"}
    minimum = root.minsize()
    try:
        # A DPI-scaled minimum must not prevent fitting a small work area.
        root.minsize(1, 1)
        root.update_idletasks()
        result = _fit_native_window(root.winfo_id())
        root.update_idletasks()
        root.minsize(min(minimum[0], root.winfo_width()),
                     min(minimum[1], root.winfo_height()))
        return result
    except (OSError, AttributeError, ValueError, tk.TclError) as error:
        root.minsize(*minimum)
        logging.getLogger(__name__).warning("Startup work-area fitting failed: %s", error)
        return {"status": "ERROR", "error": str(error)}
