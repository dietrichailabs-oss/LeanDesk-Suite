from __future__ import annotations

import tkinter as tk
from tkinter import ttk

COLORS = {
    "bg": "#111827",
    "panel": "#172033",
    "panel2": "#202b40",
    "panel3": "#263246",
    "line": "#31405a",
    "text": "#f4f1ea",
    "muted": "#aeb8ca",
    "cobalt": "#5f8dff",
    "copper": "#e18a4b",
    "jade": "#55d6b0",
    "amber": "#f3c35c",
    "orchid": "#c78af0",
    "coral": "#f07e89",
    "danger": "#f15b72",
    "paper": "#fdfcf8",
    "paper_text": "#202124",
}


def configure_suite_styles(root: tk.Misc) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 10))
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Panel.TFrame", background=COLORS["panel"])
    style.configure("Card.TFrame", background=COLORS["panel2"])
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Panel.TLabel", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("Card.TLabel", background=COLORS["panel2"], foreground=COLORS["text"])
    style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI Semibold", 27))
    style.configure("Subtitle.TLabel", background=COLORS["bg"], foreground=COLORS["copper"], font=("Segoe UI", 10))
    style.configure("Sidebar.TButton", background=COLORS["panel"], foreground=COLORS["text"], anchor="w", padding=(16, 12), borderwidth=0)
    style.map("Sidebar.TButton", background=[("active", COLORS["panel2"])])
    style.configure("Primary.TButton", background=COLORS["cobalt"], foreground="#ffffff", padding=(13, 8), font=("Segoe UI Semibold", 9))
    style.map("Primary.TButton", background=[("active", "#7da3ff")])
    style.configure("TButton", background=COLORS["panel2"], foreground=COLORS["text"], padding=(10, 7), bordercolor=COLORS["line"])
    style.map("TButton", background=[("active", COLORS["panel3"])], foreground=[("disabled", "#6f7a90")])
    style.configure("TEntry", fieldbackground="#101827", foreground=COLORS["text"], insertcolor=COLORS["text"], bordercolor=COLORS["line"])
    style.configure("TCombobox", fieldbackground="#101827", background="#101827", foreground=COLORS["text"], arrowcolor=COLORS["cobalt"], bordercolor=COLORS["line"])
    style.map("TCombobox", fieldbackground=[("readonly", "#101827")], foreground=[("readonly", COLORS["text"])])
    style.configure("Treeview", background="#101827", fieldbackground="#101827", foreground=COLORS["text"], rowheight=29, bordercolor=COLORS["line"])
    style.configure("Treeview.Heading", background=COLORS["panel2"], foreground=COLORS["text"], font=("Segoe UI Semibold", 9))
    style.map("Treeview", background=[("selected", "#354b82")])
    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=COLORS["panel2"], foreground=COLORS["muted"], padding=(13, 7))
    style.map("TNotebook.Tab", background=[("selected", COLORS["cobalt"])], foreground=[("selected", "#ffffff")])
    style.configure("TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("TRadiobutton", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("Horizontal.TScale", background=COLORS["panel"], troughcolor=COLORS["panel3"])


def ribbon_button(parent: tk.Misc, text: str, command, *, width: int | None = None, accent: bool = False, font=None) -> tk.Button:
    kwargs = {
        "text": text,
        "command": command,
        "bg": COLORS["panel2"] if not accent else COLORS["cobalt"],
        "fg": COLORS["text"] if not accent else "#ffffff",
        "activebackground": COLORS["panel3"] if not accent else "#7da3ff",
        "activeforeground": "#ffffff",
        "relief": "flat",
        "bd": 0,
        "padx": 9,
        "pady": 6,
        "cursor": "hand2",
        "font": font or ("Segoe UI", 9),
    }
    if width is not None:
        kwargs["width"] = width
    return tk.Button(parent, **kwargs)


class RibbonGroup(tk.Frame):
    def __init__(self, parent: tk.Misc, title: str, **kwargs):
        super().__init__(parent, bg=COLORS["panel"], **kwargs)
        self.body = tk.Frame(self, bg=COLORS["panel"])
        self.body.pack(fill="both", expand=True, padx=7, pady=(8, 1))
        tk.Label(self, text=title, bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="bottom", pady=(0, 4))


class StatusBar(tk.Frame):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, bg=COLORS["bg"], height=30)
        self.pack_propagate(False)

    def add_left(self, variable: tk.StringVar, *, muted: bool = False) -> tk.Label:
        label = tk.Label(self, textvariable=variable, bg=COLORS["bg"], fg=COLORS["muted"] if muted else COLORS["text"], font=("Segoe UI", 9))
        label.pack(side="left", padx=10)
        return label

    def add_right(self, variable: tk.StringVar, *, muted: bool = False) -> tk.Label:
        label = tk.Label(self, textvariable=variable, bg=COLORS["bg"], fg=COLORS["muted"] if muted else COLORS["text"], font=("Segoe UI", 9))
        label.pack(side="right", padx=10)
        return label
