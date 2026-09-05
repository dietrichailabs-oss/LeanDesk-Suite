from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .themes import SUITE_THEMES, SuiteTheme, get_theme

CURRENT_THEME_NAME = "Dark"
COLORS: dict[str, str] = dict(get_theme(CURRENT_THEME_NAME).colors)

_LEGACY_COLOR_ROLES = {
    "#111827": "bg", "#121a29": "ribbon", "#172033": "panel",
    "#202b40": "panel2", "#263246": "panel3", "#2a3140": "workspace",
    "#263044": "workspace", "#0f1724": "workspace", "#101827": "field",
    "#161d2c": "field", "#0d1420": "field", "#31405a": "line",
    "#2f3c53": "line", "#2b3a52": "line", "#40506d": "line",
    "#f4f1ea": "text", "#dbe3f0": "text", "#aeb8ca": "muted",
    "#8f9db3": "muted", "#7f8ca3": "muted", "#5f8dff": "cobalt",
    "#e18a4b": "copper", "#55d6b0": "jade", "#f3c35c": "amber",
    "#c78af0": "orchid", "#f07e89": "coral", "#f15b72": "danger",
    "#314a73": "selection", "#354b82": "selection", "#5a3e73": "selection",
    "#75492d": "selection", "#3c5476": "button_hover", "#354765": "button_hover",
    "#3a5d87": "button_hover", "#1a263a": "button_pressed",
    "#294d7b": "button_pressed", "#fdfcf8": "paper_alt",
    "#202124": "paper_text", "#9dc9ff": "grid",
}


def set_suite_theme(name: str) -> SuiteTheme:
    global CURRENT_THEME_NAME
    theme = get_theme(name)
    CURRENT_THEME_NAME = theme.name
    COLORS.clear()
    COLORS.update(theme.colors)
    return theme


def theme_names() -> tuple[str, ...]:
    return tuple(SUITE_THEMES)


def configure_suite_styles(root: tk.Misc, theme_name: str | None = None) -> None:
    if theme_name is not None:
        set_suite_theme(theme_name)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    for pattern, value in {
        "*Menu.background": COLORS["menu_bg"],
        "*Menu.foreground": COLORS["menu_text"],
        "*Menu.activeBackground": COLORS["menu_active_bg"],
        "*Menu.activeForeground": COLORS["menu_active_text"],
        "*Menu.disabledForeground": COLORS["disabled_text"],
        "*Listbox.background": COLORS["field"],
        "*Listbox.foreground": COLORS["field_text"],
        "*Listbox.selectBackground": COLORS["selection"],
        "*Listbox.selectForeground": COLORS["button_active_text"],
    }.items():
        try:
            root.option_add(pattern, value, 80)
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
    button_state_text = [
        ("disabled", COLORS["disabled_text"]),
        ("pressed", COLORS["button_active_text"]),
        ("active", COLORS["button_active_text"]),
    ]
    style.map("Sidebar.TButton", background=[("pressed", COLORS["selection"]), ("active", COLORS["panel2"])], foreground=button_state_text)
    style.configure("Primary.TButton", background=COLORS["accent_bg"], foreground=COLORS["accent_text"], padding=(13, 8), font=("Segoe UI Semibold", 9))
    style.map("Primary.TButton", background=[("pressed", COLORS["button_pressed"]), ("active", COLORS["accent_hover"])], foreground=button_state_text)
    style.configure("TButton", background=COLORS["button_bg"], foreground=COLORS["button_text"], padding=(10, 7), bordercolor=COLORS["line"])
    style.map("TButton", background=[("pressed", COLORS["button_pressed"]), ("active", COLORS["button_hover"])], foreground=button_state_text)
    style.configure("TEntry", fieldbackground=COLORS["field"], foreground=COLORS["field_text"], insertcolor=COLORS["field_text"], bordercolor=COLORS["line"])
    style.configure("TCombobox", fieldbackground=COLORS["field"], background=COLORS["field"], foreground=COLORS["field_text"], arrowcolor=COLORS["cobalt"], bordercolor=COLORS["line"])
    style.map("TCombobox", fieldbackground=[("readonly", COLORS["field"])], foreground=[("readonly", COLORS["field_text"])])
    style.configure("Treeview", background=COLORS["field"], fieldbackground=COLORS["field"], foreground=COLORS["field_text"], rowheight=29, bordercolor=COLORS["line"], borderwidth=1)
    style.configure("Treeview.Heading", background=COLORS["panel2"], foreground=COLORS["text"], font=("Segoe UI Semibold", 9))
    style.map("Treeview", background=[("selected", COLORS["selection"])], foreground=[("selected", COLORS["button_active_text"])])
    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background=COLORS["tab_bg"], foreground=COLORS["muted"], padding=(13, 7))
    style.map("TNotebook.Tab", background=[("selected", COLORS["tab_selected_bg"]), ("active", COLORS["tab_hover"])], foreground=[("disabled", COLORS["disabled_text"]), ("selected", COLORS["tab_selected_text"]), ("active", COLORS["button_active_text"])])
    style.configure("TCheckbutton", background=COLORS["panel"], foreground=COLORS["text"])
    style.configure("TRadiobutton", background=COLORS["panel"], foreground=COLORS["text"])
    # Clam supplies its own active colors. Override both sides of the label
    # pair rather than inheriting a platform hover foreground/background.
    for name in ("TCheckbutton", "TRadiobutton"):
        style.map(name, background=[("pressed", COLORS["button_pressed"]), ("active", COLORS["button_hover"])], foreground=button_state_text)
    style.configure("Horizontal.TScale", background=COLORS["panel"], troughcolor=COLORS["panel3"])
    style.configure("TSeparator", background=COLORS["line"])
    for orientation in ("Vertical", "Horizontal"):
        name = f"{orientation}.TScrollbar"
        style.configure(name, background=COLORS["scrollbar_thumb"], troughcolor=COLORS["scrollbar_track"], bordercolor=COLORS["line"], arrowcolor=COLORS["muted"])
        style.map(name, background=[("pressed", COLORS["scrollbar_pressed"]), ("active", COLORS["scrollbar_hover"])])


def set_theme_roles(widget: tk.Misc, **roles: str) -> tk.Misc:
    widget._leandesk_theme_roles = dict(roles)  # type: ignore[attr-defined]
    return widget


def _semantic_role(widget: tk.Misc, option: str, value: object, old_colors: dict[str, str]) -> str | None:
    # ttk can return a Tcl color object rather than a Python str.
    value = str(value)
    if not value.startswith("#"):
        return None
    normalized = value.lower()
    fixed_by_option = {
        "activeforeground": "button_active_text",
        "selectforeground": "button_active_text",
        "selectbackground": "selection",
        "insertbackground": "field_text",
        "troughcolor": "scrollbar_track",
    }
    if option in fixed_by_option:
        return fixed_by_option[option]
    matches = [role for role, old_value in old_colors.items() if normalized == old_value.lower()]
    if option == "background" and isinstance(widget, (tk.Text, tk.Listbox, tk.Entry)):
        if normalized == old_colors.get("paper_alt", "").lower():
            return "paper_alt"
        if normalized == old_colors.get("paper", "").lower():
            return "paper"
        return "field"
    if option == "foreground" and isinstance(widget, (tk.Text, tk.Listbox, tk.Entry)):
        if normalized == old_colors.get("paper_text", "").lower():
            return "paper_text"
        return "field_text"
    if option in {"highlightbackground", "highlightcolor"} and "line" in matches:
        return "line"
    if matches:
        return matches[0]
    return _LEGACY_COLOR_ROLES.get(normalized)


def _refresh_menu(menu: tk.Menu) -> None:
    try:
        menu.configure(
            background=COLORS["menu_bg"], foreground=COLORS["menu_text"],
            activebackground=COLORS["menu_active_bg"], activeforeground=COLORS["menu_active_text"],
            disabledforeground=COLORS["disabled_text"],
        )
        end = menu.index("end")
    except tk.TclError:
        return
    if end is None:
        return
    for index in range(end + 1):
        try:
            menu.entryconfigure(
                index, background=COLORS["menu_bg"], foreground=COLORS["menu_text"],
                activebackground=COLORS["menu_active_bg"], activeforeground=COLORS["menu_active_text"],
            )
            child = menu.nametowidget(menu.entrycget(index, "menu"))
            if isinstance(child, tk.Menu):
                _refresh_menu(child)
        except (tk.TclError, KeyError):
            pass


def refresh_classic_widget_tree(root: tk.Misc, old_colors: dict[str, str]) -> None:
    color_options = (
        "background", "foreground", "activebackground", "activeforeground",
        "highlightbackground", "highlightcolor", "selectbackground",
        "selectforeground", "insertbackground", "troughcolor", "selectcolor",
    )
    roles = getattr(root, "_leandesk_theme_roles", {})
    updates: dict[str, str] = {}
    for option in color_options:
        role = roles.get(option)
        try:
            current = root.cget(option)
        except tk.TclError:
            continue
        role = role or _semantic_role(root, option, current, old_colors)
        if role in COLORS:
            updates[option] = COLORS[role]
            roles[option] = role
    if roles:
        root._leandesk_theme_roles = roles  # type: ignore[attr-defined]
    if updates:
        try:
            root.configure(**updates)
        except tk.TclError:
            pass
    if isinstance(root, tk.Menu):
        _refresh_menu(root)
    for child in root.winfo_children():
        refresh_classic_widget_tree(child, old_colors)


def configure_combobox_popdowns(root: tk.Misc) -> None:
    for widget in root.winfo_children():
        if isinstance(widget, ttk.Combobox):
            try:
                popdown = widget.tk.call("ttk::combobox::PopdownWindow", str(widget))
                listbox = widget.nametowidget(f"{popdown}.f.l")
                listbox.configure(
                    background=COLORS["field"], foreground=COLORS["field_text"],
                    selectbackground=COLORS["selection"], selectforeground=COLORS["button_active_text"],
                )
            except (tk.TclError, KeyError):
                pass
        configure_combobox_popdowns(widget)


def broadcast_theme_changed(root: tk.Misc) -> None:
    """Notify every existing widget whose custom drawing depends on theme colors."""

    try:
        root.event_generate("<<LeanDeskThemeChanged>>", when="tail")
    except tk.TclError:
        return
    for child in root.winfo_children():
        broadcast_theme_changed(child)


def apply_suite_theme(root: tk.Misc, name: str) -> SuiteTheme:
    old_colors = dict(COLORS)
    theme = set_suite_theme(name)
    configure_suite_styles(root)
    refresh_classic_widget_tree(root, old_colors)
    configure_combobox_popdowns(root)
    try:
        root.configure(background=COLORS["bg"])
        broadcast_theme_changed(root)
    except tk.TclError:
        pass
    return theme


def ribbon_button(parent: tk.Misc, text: str, command, *, width: int | None = None, accent: bool = False, font=None) -> tk.Button:
    kwargs = {
        "text": text,
        "command": command,
        "bg": COLORS["button_bg"] if not accent else COLORS["accent_bg"],
        "fg": COLORS["button_text"] if not accent else COLORS["accent_text"],
        "activebackground": COLORS["button_hover"] if not accent else COLORS["accent_hover"],
        "activeforeground": COLORS["button_active_text"],
        "relief": "flat",
        "bd": 0,
        "padx": 9,
        "pady": 6,
        "cursor": "hand2",
        "font": font or ("Segoe UI", 9),
    }
    if width is not None:
        kwargs["width"] = width
    button = tk.Button(parent, **kwargs)
    set_theme_roles(
        button,
        background="button_bg" if not accent else "accent_bg",
        foreground="button_text" if not accent else "accent_text",
        activebackground="button_hover" if not accent else "accent_hover",
        activeforeground="button_active_text",
    )
    return button


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


class ResponsiveToolbar(tk.Frame):
    """Wrap existing toolbar children without removing or replacing commands."""

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._layout_job = None
        self.bind("<Configure>", self._schedule_layout, add="+")
        self.bind("<<LeanDeskThemeChanged>>", self._schedule_layout, add="+")
        self._schedule_layout()

    def _schedule_layout(self, _event=None):
        if self._layout_job is None:
            self._layout_job = self.after_idle(self._layout)

    def _layout(self):
        self._layout_job = None
        available = max(1, self.winfo_width() - 12)
        x, y, row_height = 6, 6, 0
        for child in self.winfo_children():
            width = min(available, max(1, child.winfo_reqwidth()))
            height = max(28, child.winfo_reqheight())
            if x > 6 and x + width > available + 6:
                x, y, row_height = 6, y + row_height + 6, 0
            if child.winfo_manager() == "pack":
                child.pack_forget()
            child.place(x=x, y=y, width=width, height=height)
            x += width + 6
            row_height = max(row_height, height)
        height = y + row_height + 6
        if int(self.cget("height")) != height:
            self.configure(height=height)


class ResponsivePanedwindow(ttk.Panedwindow):
    """Let pane weights allocate space rather than embedded Text request sizes."""

    def add(self, child, **kwargs):
        child.configure(width=1)
        child.pack_propagate(False)
        return super().add(child, **kwargs)
