from __future__ import annotations

import os
import queue
import sys
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .backup_integrity import BackupIntegrityError
from .backup_service import BackupRestoreStateError, create_backup, restore_backup
from .core import APP_NAME, APP_VERSION, DATA_ROOT, AppSettings, RecentFiles, RecoveryStore
from .draw import DrawFrame
from .notes import NotesFrame
from .organizer import CalendarFrame, ContactsFrame, TasksFrame
from .sheets import SheetsFrame
from .slides import SlidesFrame
from .themes import get_theme
from .ui import COLORS, apply_suite_theme, configure_suite_styles, theme_names
from .writer import WriterFrame
from .compatibility import cleanup_stale_conversion_roots, module_for_suffix
from .update_checker import MANIFEST_URL, UpdateResult, check_async, set_enabled

PUBLISHER = "Dietrich AI Labs"


def resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / name


class LeanDeskApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings.load()
        startup_theme = get_theme(self.settings.theme)
        self.settings.theme = startup_theme.name
        configure_suite_styles(self, startup_theme.name)
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("1580x940")
        self.minsize(1180, 720)
        self.configure(bg=COLORS["bg"])
        icon = resource_path("lean_desk_suite.ico")
        if os.name == "nt" and icon.is_file():
            try:
                self.iconbitmap(default=str(icon))
            except tk.TclError:
                pass
        try:
            cleanup_stale_conversion_roots()
        except Exception:
            # Conversion residue cleanup is non-critical and must never block launch.
            pass
        self.recent = RecentFiles()
        self.recovery = RecoveryStore()
        self._update_results: queue.Queue[UpdateResult] = queue.Queue()
        self._update_check_inflight = False
        self._notified_update_versions: set[str] = set()
        try:
            set_enabled(self.settings.auto_check_updates)
        except Exception:
            pass
        self.frames: dict[str, ttk.Frame] = {}
        self.home_frame: ttk.Frame | None = None
        self.recent_tree: ttk.Treeview | None = None
        self.active_module = "Home"
        self.sidebar_buttons: dict[str, ttk.Button] = {}
        self._build_menu()
        self._build_shell()
        self.show_home()
        self.after(350, self._offer_recovery)
        self.after(1500, self._schedule_automatic_update_check)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Home", command=self.show_home)
        file_menu.add_separator()
        file_menu.add_command(label="New Writer Document", command=lambda: self.show_module("Writer", new=True))
        file_menu.add_command(label="New Workbook", command=lambda: self.show_module("Sheets", new=True))
        file_menu.add_command(label="New Presentation", command=lambda: self.show_module("Slides", new=True))
        file_menu.add_command(label="New Drawing", command=lambda: self.show_module("Draw", new=True))
        file_menu.add_separator()
        file_menu.add_command(label="Create Profile Backup...", command=self.create_profile_backup)
        file_menu.add_command(label="Restore Profile Backup...", command=self.restore_profile_backup)
        file_menu.add_command(label="Open Data Folder", command=self.open_data_folder)
        file_menu.add_command(label="Exit", command=self.on_close)
        menu.add_cascade(label="File", menu=file_menu)

        modules = tk.Menu(menu, tearoff=False)
        for name in ("Writer", "Sheets", "Slides", "Notes", "Draw", "Tasks", "Calendar", "Contacts"):
            modules.add_command(label=name, command=lambda value=name: self.show_module(value))
        menu.add_cascade(label="Modules", menu=modules)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Check for Updates", command=self.check_for_updates_now)
        help_menu.add_separator()
        help_menu.add_command(label="Open README", command=self.open_readme)
        help_menu.add_command(label="About", command=self.about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menu)

    def _build_shell(self) -> None:
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        sidebar = ttk.Frame(shell, style="Panel.TFrame", width=196)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.sidebar = sidebar

        brand = ttk.Frame(sidebar, style="Panel.TFrame")
        brand.pack(fill="x", padx=16, pady=(18, 20))
        ttk.Label(brand, text="LEANDESK", style="Panel.TLabel", font=("Segoe UI Bold", 18), foreground=COLORS["text"]).pack(anchor="w")
        ttk.Label(brand, text=f"SUITE {APP_VERSION}", style="Panel.TLabel", foreground=COLORS["copper"], font=("Segoe UI Semibold", 9)).pack(anchor="w")

        modules = (
            ("Home", "⌂"),
            ("Writer", "▤"),
            ("Sheets", "▦"),
            ("Slides", "▣"),
            ("Notes", "≡"),
            ("Draw", "◇"),
            ("Tasks", "☑"),
            ("Calendar", "▧"),
            ("Contacts", "○"),
        )
        for name, icon_text in modules:
            button = ttk.Button(
                sidebar,
                text=f"{icon_text}   {name}",
                command=self.show_home if name == "Home" else lambda value=name: self.show_module(value),
                style="Sidebar.TButton",
            )
            button.pack(fill="x", padx=8, pady=2)
            self.sidebar_buttons[name] = button

        ttk.Separator(sidebar).pack(fill="x", padx=14, pady=14)
        ttk.Button(sidebar, text="⚙   Settings", command=self.show_settings, style="Sidebar.TButton").pack(fill="x", padx=8, pady=2)
        ttk.Button(sidebar, text="?   Help", command=self.open_readme, style="Sidebar.TButton").pack(fill="x", padx=8, pady=2)
        ttk.Label(sidebar, text="Local-first productivity", style="Panel.TLabel", foreground=COLORS["muted"], font=("Segoe UI", 8)).pack(side="bottom", anchor="w", padx=18, pady=16)

        self.content = ttk.Frame(shell)
        self.content.pack(side="left", fill="both", expand=True)
        callbacks = dict(on_recent_changed=self.refresh_home_recent, on_title_changed=self._update_window_title)
        self.frames["Writer"] = WriterFrame(self.content, recent=self.recent, settings=self.settings, **callbacks)
        self.frames["Sheets"] = SheetsFrame(self.content, recent=self.recent, **callbacks)
        self.frames["Slides"] = SlidesFrame(self.content, recent=self.recent, **callbacks)
        self.frames["Notes"] = NotesFrame(self.content, recent=self.recent, on_title_changed=self._update_window_title)
        self.frames["Draw"] = DrawFrame(self.content, recent=self.recent, **callbacks)
        self.frames["Tasks"] = TasksFrame(self.content, on_title_changed=self._update_window_title)
        self.frames["Calendar"] = CalendarFrame(self.content, on_title_changed=self._update_window_title)
        self.frames["Contacts"] = ContactsFrame(self.content, on_title_changed=self._update_window_title)

    def _update_window_title(self, document_title: str, dirty: bool) -> None:
        marker = "* " if dirty else ""
        self.title(f"{marker}{document_title} — LeanDesk Suite")

    def _clear_view(self) -> None:
        for child in self.content.winfo_children():
            child.pack_forget()

    def _set_active(self, name: str) -> None:
        self.active_module = name
        for module, button in self.sidebar_buttons.items():
            if module == name:
                button.state(["pressed"])
            else:
                button.state(["!pressed"])

    def show_module(self, name: str, new: bool = False) -> None:
        frame = self.frames[name]
        self._clear_view()
        frame.pack(fill="both", expand=True)
        self._set_active(name)
        if new:
            methods = {
                "Writer": "new_document",
                "Sheets": "new_workbook",
                "Slides": "new_deck",
                "Draw": "new_drawing",
                "Notes": "new_note",
                "Tasks": "new_task",
                "Contacts": "new_contact",
            }
            method = methods.get(name)
            if method:
                getattr(frame, method)()
        self.title(f"LeanDesk {name} — LeanDesk Suite")

    def show_home(self) -> None:
        self._clear_view()
        self._set_active("Home")
        if self.home_frame:
            self.home_frame.destroy()
        home = ttk.Frame(self.content)
        self.home_frame = home
        home.pack(fill="both", expand=True, padx=28, pady=24)
        header = ttk.Frame(home)
        header.pack(fill="x")
        ttk.Label(header, text="Lean tools. Fast work.", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="A focused local productivity suite with documents, spreadsheets, presentations, notes, drawings, and personal organization.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 16))

        cards = ttk.Frame(home)
        cards.pack(fill="x")
        modules = [
            ("Writer", "Documents, offline spell checking, DOCX and PDF", COLORS["cobalt"]),
            ("Sheets", "Formulas, multiple sheets, CSV and XLSX", COLORS["jade"]),
            ("Slides", "Themes, presenter mode, images and PPTX", COLORS["amber"]),
            ("Notes", "Markdown notes, notebooks, tags and preview", COLORS["orchid"]),
            ("Draw", "Shapes, arrows, text, SVG and PNG export", COLORS["coral"]),
            ("Organizer", "Tasks, calendar events and contacts", COLORS["copper"]),
        ]
        for index, (name, description, color) in enumerate(modules):
            card = ttk.Frame(cards, style="Card.TFrame")
            card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=6, pady=6)
            cards.columnconfigure(index % 3, weight=1)
            ttk.Label(card, text=name.upper(), style="Card.TLabel", foreground=color, font=("Segoe UI Bold", 17)).pack(anchor="w", padx=16, pady=(15, 4))
            ttk.Label(card, text=description, style="Card.TLabel", foreground=COLORS["muted"], wraplength=310, justify="left").pack(anchor="w", padx=16, pady=(0, 12))
            target = "Tasks" if name == "Organizer" else name
            ttk.Button(card, text="OPEN", command=lambda value=target: self.show_module(value)).pack(anchor="w", padx=16, pady=(0, 15))
            ttk.Label(card, text="READY FOR TESTING", style="Card.TLabel", foreground=color, font=("Segoe UI Semibold", 8)).place(relx=1.0, x=-15, y=17, anchor="ne")

        recent_panel = ttk.Frame(home, style="Panel.TFrame")
        recent_panel.pack(fill="both", expand=True, pady=(18, 0))
        top = ttk.Frame(recent_panel, style="Panel.TFrame")
        top.pack(fill="x", padx=16, pady=(14, 8))
        ttk.Label(top, text="RECENT FILES", style="Panel.TLabel", foreground=COLORS["copper"], font=("Segoe UI Semibold", 11)).pack(side="left")
        ttk.Button(top, text="Clean Missing", command=self.clean_missing).pack(side="right")
        self.recent_tree = ttk.Treeview(recent_panel, columns=("module", "name", "path", "opened"), show="headings", selectmode="browse")
        for column, title, width in (("module", "Module", 90), ("name", "File", 200), ("path", "Location", 570), ("opened", "Last Opened", 165)):
            self.recent_tree.heading(column, text=title)
            self.recent_tree.column(column, width=width)
        self.recent_tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.recent_tree.bind("<Double-1>", self.open_selected_recent)
        self.refresh_home_recent()
        self.title(f"{APP_NAME} {APP_VERSION}")

    def refresh_home_recent(self) -> None:
        if self.recent_tree is None or not self.recent_tree.winfo_exists():
            return
        self.recent.load()
        self.recent_tree.delete(*self.recent_tree.get_children())
        for index, entry in enumerate(self.recent.entries):
            self.recent_tree.insert("", "end", iid=f"recent-{index}", values=(entry.module, entry.display_name or Path(entry.path).name, entry.path, entry.opened_at.replace("T", " ")))

    def clean_missing(self) -> None:
        removed = self.recent.remove_missing()
        self.refresh_home_recent()
        messagebox.showinfo(APP_NAME, f"Removed {removed} missing recent-file entr{'y' if removed == 1 else 'ies'}.")

    def open_selected_recent(self, _event=None) -> None:
        if self.recent_tree is None:
            return
        selection = self.recent_tree.selection()
        if not selection:
            return
        index = int(selection[0].split("-")[-1])
        if not 0 <= index < len(self.recent.entries):
            return
        entry = self.recent.entries[index]
        path = Path(entry.path)
        if not path.exists():
            messagebox.showwarning(APP_NAME, "That file no longer exists.")
            return
        module = entry.module if entry.module in self.frames else self.module_for_path(path)
        self.show_module(module)
        frame = self.frames[module]
        open_method = {
            "Writer": "open_document",
            "Sheets": "open_workbook",
            "Slides": "open_deck",
            "Draw": "open_drawing",
        }.get(module)
        if open_method:
            getattr(frame, open_method)(path)

    def open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showerror(APP_NAME, f"File not found:\n{path}")
            return
        module = self.module_for_path(path)
        self.show_module(module)
        method = {
            "Writer": "open_document",
            "Sheets": "open_workbook",
            "Slides": "open_deck",
            "Draw": "open_drawing",
        }.get(module)
        if method:
            getattr(self.frames[module], method)(path)

    @staticmethod
    def module_for_path(path: Path) -> str:
        return module_for_suffix(path.suffix)

    def show_settings(self) -> None:
        self._clear_view()
        self._set_active("Settings")
        page = ttk.Frame(self.content)
        page.pack(fill="both", expand=True, padx=45, pady=36)
        ttk.Label(page, text="Suite Settings", style="Title.TLabel").pack(anchor="w")
        ttk.Label(page, text="Shared local settings for every LeanDesk module.", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 18))

        card = ttk.Frame(page, style="Panel.TFrame")
        card.pack(fill="x")
        live_var = tk.BooleanVar(value=self.settings.live_spellcheck)
        update_var = tk.BooleanVar(value=self.settings.auto_check_updates)
        theme_var = tk.StringVar(value=self.settings.theme)
        theme_description = tk.StringVar(value=get_theme(theme_var.get()).description)
        ttk.Label(card, text="APPEARANCE", style="Panel.TLabel", foreground=COLORS["copper"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=18, pady=(18, 5))
        ttk.Label(card, text="Suite theme", style="Panel.TLabel", foreground=COLORS["muted"]).pack(anchor="w", padx=18)
        theme_picker = ttk.Combobox(card, textvariable=theme_var, values=theme_names(), state="readonly", width=28)
        theme_picker.pack(anchor="w", padx=18, pady=(3, 5))
        ttk.Label(card, textvariable=theme_description, style="Panel.TLabel", foreground=COLORS["muted"], wraplength=720).pack(anchor="w", padx=18, pady=(0, 10))

        def preview_theme(_event=None) -> None:
            theme = apply_suite_theme(self, theme_var.get())
            theme_var.set(theme.name)
            theme_description.set(theme.description)

        theme_picker.bind("<<ComboboxSelected>>", preview_theme)
        ttk.Separator(card).pack(fill="x", padx=18, pady=8)
        ttk.Checkbutton(card, text="Enable live Writer spell checking", variable=live_var).pack(anchor="w", padx=18, pady=(18, 8))
        ttk.Label(card, text="Autosave recovery interval (seconds)", style="Panel.TLabel", foreground=COLORS["muted"]).pack(anchor="w", padx=18)
        autosave = tk.StringVar(value=str(self.settings.autosave_seconds))
        ttk.Entry(card, textvariable=autosave, width=12).pack(anchor="w", padx=18, pady=(3, 12))

        ttk.Separator(card).pack(fill="x", padx=18, pady=8)
        ttk.Label(card, text="UPDATES", style="Panel.TLabel", foreground=COLORS["copper"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=18, pady=(4, 5))
        ttk.Checkbutton(
            card,
            text="Automatically check for LeanDesk updates once a week",
            variable=update_var,
        ).pack(anchor="w", padx=18, pady=(0, 7))
        ttk.Label(
            card,
            text=f"Official update metadata: {MANIFEST_URL}",
            style="Panel.TLabel",
            foreground=COLORS["muted"],
        ).pack(anchor="w", padx=18, pady=(0, 8))
        ttk.Button(card, text="Check for Updates Now", command=self.check_for_updates_now).pack(anchor="w", padx=18, pady=(0, 12))

        ttk.Separator(card).pack(fill="x", padx=18, pady=8)
        ttk.Label(card, text="LOCAL PROFILE BACKUP", style="Panel.TLabel", foreground=COLORS["cobalt"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=18, pady=(4, 5))
        backup_row = ttk.Frame(card, style="Panel.TFrame")
        backup_row.pack(fill="x", padx=18, pady=(0, 8))
        ttk.Button(backup_row, text="Create Backup...", command=self.create_profile_backup).pack(side="left", padx=(0, 8))
        ttk.Button(backup_row, text="Restore Backup...", command=self.restore_profile_backup).pack(side="left")
        ttk.Label(
            card,
            text="Restore validates into staging before replacing the local profile and then closes LeanDesk.",
            style="Panel.TLabel",
            foreground=COLORS["muted"],
        ).pack(anchor="w", padx=18, pady=(0, 12))
        ttk.Label(card, text=f"Local data: {DATA_ROOT}", style="Panel.TLabel", foreground=COLORS["muted"]).pack(anchor="w", padx=18, pady=(0, 12))

        def save_settings() -> None:
            self.settings.theme = get_theme(theme_var.get()).name
            self.settings.live_spellcheck = live_var.get()
            self.settings.auto_check_updates = update_var.get()
            try:
                self.settings.autosave_seconds = max(10, min(3600, int(autosave.get())))
            except ValueError:
                self.settings.autosave_seconds = 30
            if not self.settings.save():
                messagebox.showwarning(
                    APP_NAME,
                    "These settings are read-only because the stored settings need a newer LeanDesk build or repair. The original file was preserved.",
                    parent=self,
                )
                return
            try:
                set_enabled(self.settings.auto_check_updates)
            except Exception:
                messagebox.showwarning(
                    APP_NAME,
                    "The preference was saved, but LeanDesk could not update its non-critical update-check state right now.",
                    parent=self,
                )
            writer = self.frames["Writer"]
            writer.live_spell_var.set(self.settings.live_spellcheck)
            writer.toggle_live_spellcheck()
            messagebox.showinfo(APP_NAME, "Settings saved locally.", parent=self)

        ttk.Button(card, text="SAVE SETTINGS", command=save_settings, style="Primary.TButton").pack(anchor="w", padx=18, pady=(0, 18))
        self.title("Settings — LeanDesk Suite")

    def _offer_recovery(self) -> None:
        records = self.recovery.list()
        for record in records:
            frame = self.frames.get(record.module)
            recover = getattr(frame, "recover_record", None) if frame is not None else None
            if not callable(recover):
                continue
            choice = messagebox.askyesnocancel(
                APP_NAME,
                f"An unsaved {record.module} recovery copy from {record.saved_at.replace('T', ' ')} was found.\n\n"
                "Yes: recover it now\nNo: discard this recovery copy\nCancel: keep it for later",
                parent=self,
            )
            if choice is None:
                break
            if choice is False:
                try:
                    self.recovery.delete(record.recovery_id)
                except Exception:
                    messagebox.showwarning(APP_NAME, "The recovery copy could not be discarded safely.", parent=self)
                continue
            try:
                self.show_module(record.module)
                recover(record)
            except Exception:
                messagebox.showwarning(
                    APP_NAME,
                    f"LeanDesk could not recover this {record.module} copy. It has been kept for later review.",
                    parent=self,
                )

    def _schedule_automatic_update_check(self) -> None:
        if self.settings.auto_check_updates:
            self._start_update_check(manual=False)

    def check_for_updates_now(self) -> None:
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool) -> None:
        if self._update_check_inflight:
            if manual:
                messagebox.showinfo(APP_NAME, "LeanDesk is already checking for updates.", parent=self)
            return
        self._update_check_inflight = True
        check_async(APP_VERSION, self._update_results.put, force=manual)
        self.after(100, lambda: self._poll_update_result(manual=manual))

    def _poll_update_result(self, *, manual: bool) -> None:
        try:
            result = self._update_results.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(100, lambda: self._poll_update_result(manual=manual))
            return
        self._update_check_inflight = False
        self._handle_update_result(result, manual=manual)

    def _handle_update_result(self, result: UpdateResult, *, manual: bool) -> None:
        if result.status == "update_available" and result.latest_version:
            if not manual and result.latest_version in self._notified_update_versions:
                return
            self._notified_update_versions.add(result.latest_version)
            self._show_update_available(result)
        elif result.status == "current" and manual:
            messagebox.showinfo(APP_NAME, "LeanDesk Suite is up to date.", parent=self)
        elif result.status in {"error"} and manual:
            diagnostic = result.error or "The official update service could not be reached."
            messagebox.showinfo(
                APP_NAME,
                f"LeanDesk couldn't check for updates right now.\n\n{diagnostic}\n\n"
                f"Diagnostic category: {result.error_category or 'unknown'}\n\n"
                "You can continue using the application normally.",
                parent=self,
            )
        # disabled and not_due are intentionally quiet for automatic checks.

    def _show_update_available(self, result: UpdateResult) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Update Available")
        dialog.transient(self)
        dialog.resizable(False, False)
        dialog.configure(bg=COLORS["panel"])
        frame = ttk.Frame(dialog, style="Panel.TFrame", padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Update Available", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            frame,
            text=f"LeanDesk Suite {result.latest_version} is now available.",
            style="Panel.TLabel",
            font=("Segoe UI Semibold", 11),
        ).pack(anchor="w", pady=(8, 5))
        if result.message:
            ttk.Label(frame, text=result.message, style="Panel.TLabel", foreground=COLORS["muted"], wraplength=500).pack(anchor="w", pady=(0, 5))
        if result.sha256:
            ttk.Label(
                frame,
                text=f"Published SHA-256: {result.sha256}",
                style="Panel.TLabel",
                foreground=COLORS["muted"],
                wraplength=500,
            ).pack(anchor="w", pady=(4, 8))
        row = ttk.Frame(frame, style="Panel.TFrame")
        row.pack(fill="x", pady=(14, 0))

        def view_update() -> None:
            url = result.release_url or result.download_url
            dialog.destroy()
            if url:
                webbrowser.open(url, new=2)

        ttk.Button(row, text="View Update", command=view_update, style="Primary.TButton").pack(side="left")
        ttk.Button(row, text="Remind Me Later", command=dialog.destroy).pack(side="left", padx=(8, 0))
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.grab_set()

    def create_profile_backup(self) -> None:
        value = filedialog.asksaveasfilename(
            parent=self,
            title="Create LeanDesk Profile Backup",
            defaultextension=".ldbackup",
            filetypes=(("LeanDesk backup", "*.ldbackup"), ("ZIP archive", "*.zip")),
        )
        if not value:
            return
        try:
            try:
                self.frames["Notes"].save_now()
            except Exception:
                pass
            result = create_backup(value)
        except BackupIntegrityError:
            messagebox.showerror(
                APP_NAME,
                "LeanDesk could not create a verified backup. The existing profile was not changed.",
                parent=self,
            )
            return
        detail = f"Verified backup created.\n\nFiles: {result['files']}\nSHA-256: {result['sha256']}"
        warning = str(result.get("durability_warning", "")).strip()
        if warning:
            detail += "\n\nImportant: " + warning
        messagebox.showinfo(APP_NAME, detail, parent=self)

    def restore_profile_backup(self) -> None:
        value = filedialog.askopenfilename(
            parent=self,
            title="Restore LeanDesk Profile Backup",
            filetypes=(("LeanDesk backup", "*.ldbackup *.zip"), ("All files", "*.*")),
        )
        if not value:
            return
        if not messagebox.askyesno(
            APP_NAME,
            "LeanDesk will fully validate this backup in a staging directory before replacing the local profile.\n\n"
            "After a successful restore, LeanDesk will close so the restored data cannot be overwritten by the current session. Continue?",
            parent=self,
        ):
            return
        try:
            result = restore_backup(value)
        except BackupRestoreStateError as exc:
            state = getattr(exc, "profile_state", "unknown")
            rollback_path = getattr(exc, "rollback_path", None)
            if state in {"previous_profile_active", "profile_unchanged"}:
                detail = "The previous LeanDesk profile is active and was not replaced."
            elif state == "previous_profile_retained":
                detail = "The previous LeanDesk profile is preserved in a recovery directory and was not deleted."
                if rollback_path:
                    detail += f"\n\nRecovery location: {rollback_path}"
            elif state == "no_previous_profile":
                detail = "No new profile was committed."
            else:
                detail = "LeanDesk preserved all recoverable restore data for manual review."
            messagebox.showerror(
                APP_NAME,
                "The backup was rejected or could not be restored safely.\n\n" + detail,
                parent=self,
            )
            return
        except BackupIntegrityError:
            messagebox.showerror(
                APP_NAME,
                "The backup was rejected before the local LeanDesk profile was changed.",
                parent=self,
            )
            return
        cleanup = result.get("cleanup_warning", "")
        message = f"Backup restored and verified.\n\nFiles: {result['files']}\nLeanDesk will now close."
        if cleanup:
            message += (
                "\n\nThe restore succeeded, but LeanDesk retained a safety copy or "
                "cleanup item:\n" + cleanup
            )
        messagebox.showinfo(APP_NAME, message, parent=self)
        self.destroy()

    def open_data_folder(self) -> None:
        DATA_ROOT.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(DATA_ROOT)
        else:
            webbrowser.open(DATA_ROOT.as_uri())

    def open_readme(self) -> None:
        path = resource_path("README.md")
        if path.is_file():
            if os.name == "nt":
                os.startfile(path)
            else:
                webbrowser.open(path.as_uri())
        else:
            messagebox.showinfo(APP_NAME, "README.md was not found.")

    def about(self) -> None:
        messagebox.showinfo(
            APP_NAME,
            f"{APP_NAME} {APP_VERSION}\n\n"
            "Functional multi-module preview: Writer, Sheets, Slides, Notes, Draw, Tasks, Calendar, and Contacts.\n\n"
            "Publisher: Dietrich AI Labs\n"
            "Local-first. No account, cloud service, telemetry, or subscription.",
        )

    def on_close(self) -> None:
        checks = (
            ("Writer", "confirm_discard_or_save"),
            ("Sheets", "confirm_discard"),
            ("Slides", "confirm_discard"),
            ("Draw", "confirm_discard"),
        )
        for name, method in checks:
            if not getattr(self.frames[name], method)():
                return
        try:
            self.frames["Notes"].save_now()
        except Exception:
            pass
        self.settings.default_zoom = self.frames["Writer"].zoom
        self.settings.save()
        self.destroy()


def main() -> int:
    app = LeanDeskApp()
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1]).expanduser()
        app.after(300, lambda path=candidate: app.open_path(path))
    app.mainloop()
    return 0
