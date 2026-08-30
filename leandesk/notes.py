from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .core import NOTES_FILE, RecentFiles, RecoveryRecord, RecoveryStore, atomic_write_json, atomic_write_text
from .data_boundary import DataCorruptionError, UnsupportedSchemaVersion, load_json_or_default, merge_known_and_extra, read_bounded
from .ui import COLORS, StatusBar

NOTES_SCHEMA_VERSION = 1


@dataclass
class Note:
    note_id: str
    title: str
    body: str = ""
    notebook: str = "General"
    tags: str = ""
    created_at: str = ""
    updated_at: str = ""
    pinned: bool = False
    extra: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def new(cls, title: str = "New Note") -> "Note":
        now = datetime.now().isoformat(timespec="seconds")
        return cls(str(uuid.uuid4()), title, created_at=now, updated_at=now)

    @classmethod
    def from_dict(cls, payload: dict) -> "Note":
        if not isinstance(payload, dict):
            raise DataCorruptionError("Invalid note row.")
        known = {"note_id", "title", "body", "notebook", "tags", "created_at", "updated_at", "pinned"}
        note_id = payload.get("note_id", "")
        text_fields = ("note_id", "title", "body", "notebook", "tags", "created_at", "updated_at")
        if any(not isinstance(payload.get(name, ""), str) for name in text_fields):
            raise DataCorruptionError("Note contains an invalid text field.")
        if not isinstance(payload.get("pinned", False), bool):
            raise DataCorruptionError("Note pinned state must be true or false.")
        try:
            uuid.UUID(note_id)
        except (ValueError, AttributeError) as exc:
            raise DataCorruptionError("Invalid note identifier.") from exc
        return cls(
            note_id=note_id,
            title=payload.get("title", "Untitled Note"),
            body=payload.get("body", ""),
            notebook=payload.get("notebook", "General"),
            tags=payload.get("tags", ""),
            created_at=payload.get("created_at", ""),
            updated_at=payload.get("updated_at", ""),
            pinned=payload.get("pinned", False),
            extra={k: v for k, v in payload.items() if k not in known},
        )

    def to_dict(self) -> dict:
        return merge_known_and_extra(
            {
                "note_id": self.note_id,
                "title": self.title,
                "body": self.body,
                "notebook": self.notebook,
                "tags": self.tags,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "pinned": bool(self.pinned),
            },
            self.extra,
        )


class NotesFrame(ttk.Frame):
    def __init__(self, master, *, recent: RecentFiles | None = None, on_title_changed=None):
        super().__init__(master)
        self.recent = recent
        self.on_title_changed = on_title_changed
        self.notes: list[Note] = []
        self.current_id: str | None = None
        self.read_only = False
        self.load_error: str | None = None
        self.recovery = RecoveryStore()
        self.recovery_id = str(uuid.uuid4())
        self.search_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.notebook_var = tk.StringVar(value="General")
        self.tags_var = tk.StringVar()
        self.pinned_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.count_var = tk.StringVar(value="0 notes")
        self.preview_visible = tk.BooleanVar(value=True)
        self._save_job = None
        self._build_ui()
        self.load()

    def _build_ui(self) -> None:
        ribbon = tk.Frame(self, bg=COLORS["panel"], height=80, highlightbackground=COLORS["line"], highlightthickness=1)
        ribbon.pack(fill="x")
        ribbon.pack_propagate(False)
        for label, command in (
            ("New Note", self.new_note), ("Delete", self.delete_note), ("Duplicate", self.duplicate_note),
            ("Import Markdown", self.import_markdown), ("Export Markdown", self.export_markdown),
            ("Toggle Preview", self.toggle_preview), ("Save Now", self.save_now),
        ):
            ttk.Button(ribbon, text=label, command=command).pack(side="left", padx=4, pady=14)
        tk.Label(ribbon, text="NOTES", bg=COLORS["panel"], fg=COLORS["orchid"], font=("Segoe UI Bold", 14)).pack(side="right", padx=16)

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Panel.TFrame", width=270)
        editor = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(editor, weight=7)

        tk.Label(left, text="SEARCH", bg=COLORS["panel"], fg=COLORS["orchid"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=12, pady=(12, 5))
        search = ttk.Entry(left, textvariable=self.search_var)
        search.pack(fill="x", padx=12, pady=(0, 8))
        search.bind("<KeyRelease>", lambda _e: self.refresh_list())
        self.note_list = tk.Listbox(left, bg="#101827", fg=COLORS["text"], selectbackground="#5a3e73", selectforeground="#ffffff", relief="flat", bd=0, activestyle="none", font=("Segoe UI", 10))
        self.note_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.note_list.bind("<<ListboxSelect>>", self.on_select)

        meta = tk.Frame(editor, bg=COLORS["panel2"], height=72)
        meta.pack(fill="x")
        meta.pack_propagate(False)
        ttk.Entry(meta, textvariable=self.title_var, font=("Segoe UI Semibold", 14)).pack(side="left", fill="x", expand=True, padx=(10, 6), pady=14)
        ttk.Entry(meta, textvariable=self.notebook_var, width=16).pack(side="left", padx=4, pady=14)
        ttk.Entry(meta, textvariable=self.tags_var, width=24).pack(side="left", padx=4, pady=14)
        ttk.Checkbutton(meta, text="Pinned", variable=self.pinned_var, command=self.editor_changed).pack(side="left", padx=(8, 12))
        self.title_var.trace_add("write", lambda *_: self.editor_changed())
        self.notebook_var.trace_add("write", lambda *_: self.editor_changed())
        self.tags_var.trace_add("write", lambda *_: self.editor_changed())

        split = ttk.Panedwindow(editor, orient="horizontal")
        split.pack(fill="both", expand=True)
        edit_frame = ttk.Frame(split)
        preview_frame = ttk.Frame(split, style="Panel.TFrame")
        split.add(edit_frame, weight=1)
        split.add(preview_frame, weight=1)
        self.split = split
        self.preview_frame = preview_frame
        self.editor_text = tk.Text(edit_frame, wrap="word", undo=True, bg="#fdfcf8", fg="#202124", insertbackground="#202124", selectbackground="#9dc9ff", relief="flat", padx=30, pady=24, font=("Segoe UI", 11), spacing3=3)
        self.editor_text.pack(fill="both", expand=True)
        self.editor_text.bind("<KeyRelease>", self.editor_changed)
        self.preview_text = tk.Text(preview_frame, wrap="word", bg="#161d2c", fg=COLORS["text"], relief="flat", padx=28, pady=24, state="disabled", font=("Segoe UI", 11), spacing3=4)
        self.preview_text.pack(fill="both", expand=True)
        self.preview_text.tag_configure("h1", font=("Segoe UI Semibold", 22), foreground=COLORS["orchid"], spacing1=8, spacing3=10)
        self.preview_text.tag_configure("h2", font=("Segoe UI Semibold", 17), foreground=COLORS["cobalt"], spacing1=7, spacing3=7)
        self.preview_text.tag_configure("h3", font=("Segoe UI Semibold", 14), foreground=COLORS["jade"], spacing1=6, spacing3=5)
        self.preview_text.tag_configure("bullet", lmargin1=20, lmargin2=38)
        self.preview_text.tag_configure("code", font=("Consolas", 10), background="#0d1420", foreground="#f4c47e")
        self.preview_text.tag_configure("quote", lmargin1=18, foreground=COLORS["muted"], font=("Segoe UI Italic", 11))

        status = StatusBar(self)
        status.pack(fill="x")
        status.add_left(self.status_var)
        status.add_right(self.count_var, muted=True)

    def load(self) -> None:
        target = Path(NOTES_FILE)
        existed = target.exists()
        result = load_json_or_default(target, dict, expected_type=(dict, list), limit=64 * 1024 * 1024)
        payload = result.value
        self.read_only = result.read_only
        self.load_error = result.error
        rows = payload if isinstance(payload, list) else payload.get("notes", []) if isinstance(payload, dict) else []
        if isinstance(payload, dict):
            version = payload.get("schema_version", NOTES_SCHEMA_VERSION)
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                self.read_only = True
                self.load_error = "Invalid Notes schema version; original data is preserved."
                rows = []
            elif version > NOTES_SCHEMA_VERSION:
                self.read_only = True
                self.load_error = f"Notes schema {version} is newer than this build; data is read-only."
        self.notes = []
        try:
            if not isinstance(rows, list):
                raise DataCorruptionError("Notes collection is not a list.")
            self.notes = [Note.from_dict(row) for row in rows]
        except (DataCorruptionError, TypeError, ValueError) as exc:
            self.read_only = True
            self.load_error = str(exc)
            self.notes = []
        if not self.notes and not existed and not self.read_only:
            self.notes = [Note.new("Welcome to LeanDesk Notes")]
            self.notes[0].body = "# LeanDesk Notes\n\nFast local Markdown notes with notebooks, tags, search, pinning, preview, and automatic saving."
            self.save_now()
        if self.notes:
            self.refresh_list(select_id=self.notes[0].note_id)
        else:
            self.current_id = None
            self.note_list.delete(0, "end")
            self.editor_text.delete("1.0", "end")
            self.count_var.set("0 notes")
            self.status_var.set("Notes data could not be loaded; the original file was preserved")

    def _payload(self) -> dict:
        return {"schema_version": NOTES_SCHEMA_VERSION, "notes": [note.to_dict() for note in self.notes]}

    def save_now(self) -> bool:
        if self.read_only:
            self.status_var.set("Notes are read-only because the stored data needs a newer build or repair")
            return False
        self.commit_current()
        payload = self._payload()
        try:
            self.recovery.save(
                RecoveryRecord(
                    self.recovery_id,
                    "Notes",
                    "LeanDesk Notes",
                    str(NOTES_FILE),
                    datetime.now().isoformat(timespec="seconds"),
                    payload,
                )
            )
            atomic_write_json(Path(NOTES_FILE), payload)
            self.recovery.delete(self.recovery_id)
        except Exception as exc:
            self.status_var.set(f"Notes were not saved: {type(exc).__name__}")
            return False
        self.status_var.set("Notes saved locally")
        return True

    def schedule_save(self) -> None:
        if self.read_only:
            return
        if self._save_job:
            try:
                self.after_cancel(self._save_job)
            except Exception:
                pass
        self._save_job = self.after(750, self.save_now)

    def filtered(self) -> list[Note]:
        needle = self.search_var.get().strip().lower()
        rows = self.notes
        if needle:
            rows = [note for note in rows if needle in "\n".join((note.title, note.body, note.notebook, note.tags)).lower()]
        return sorted(rows, key=lambda note: (not note.pinned, note.updated_at), reverse=False)

    def refresh_list(self, select_id: str | None = None) -> None:
        rows = self.filtered()
        self.visible_ids = [note.note_id for note in rows]
        self.note_list.delete(0, "end")
        selected_index = None
        for index, note in enumerate(rows):
            pin = "★ " if note.pinned else ""
            self.note_list.insert("end", f"{pin}{note.title or 'Untitled'}\n   {note.notebook}  {note.tags}"[:70])
            if note.note_id == (select_id or self.current_id):
                selected_index = index
        if selected_index is not None:
            self.note_list.selection_set(selected_index)
            self.note_list.activate(selected_index)
            self.load_note(self.visible_ids[selected_index])
        self.count_var.set(f"{len(self.notes)} note{'s' if len(self.notes) != 1 else ''}")

    def get_note(self, note_id: str | None) -> Note | None:
        return next((note for note in self.notes if note.note_id == note_id), None)

    def on_select(self, _event=None) -> None:
        selection = self.note_list.curselection()
        if not selection:
            return
        self.commit_current()
        self.load_note(self.visible_ids[selection[0]])

    def load_note(self, note_id: str) -> None:
        note = self.get_note(note_id)
        if not note:
            return
        self.current_id = note_id
        self.title_var.set(note.title)
        self.notebook_var.set(note.notebook)
        self.tags_var.set(note.tags)
        self.pinned_var.set(note.pinned)
        self.editor_text.delete("1.0", "end")
        self.editor_text.insert("1.0", note.body)
        self.render_preview()
        self.status_var.set(f"Editing {note.title}")
        if self.on_title_changed:
            self.on_title_changed(f"Notes — {note.title}", False)

    def commit_current(self) -> None:
        note = self.get_note(self.current_id)
        if not note:
            return
        note.title = self.title_var.get().strip() or "Untitled Note"
        note.notebook = self.notebook_var.get().strip() or "General"
        note.tags = self.tags_var.get().strip()
        note.pinned = self.pinned_var.get()
        note.body = self.editor_text.get("1.0", "end-1c")
        note.updated_at = datetime.now().isoformat(timespec="seconds")

    def editor_changed(self, _event=None) -> None:
        if not self.current_id:
            return
        self.render_preview()
        self.schedule_save()
        if self.on_title_changed:
            self.on_title_changed(f"Notes — {self.title_var.get().strip() or 'Untitled Note'}", True)

    def render_preview(self) -> None:
        source = self.editor_text.get("1.0", "end-1c")
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        in_code = False
        for line in source.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.preview_text.insert("end", line + "\n", "code")
            elif line.startswith("### "):
                self.preview_text.insert("end", line[4:] + "\n", "h3")
            elif line.startswith("## "):
                self.preview_text.insert("end", line[3:] + "\n", "h2")
            elif line.startswith("# "):
                self.preview_text.insert("end", line[2:] + "\n", "h1")
            elif re.match(r"^\s*[-*+]\s+", line):
                self.preview_text.insert("end", "• " + re.sub(r"^\s*[-*+]\s+", "", line) + "\n", "bullet")
            elif line.startswith("> "):
                self.preview_text.insert("end", line[2:] + "\n", "quote")
            else:
                clean = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
                clean = re.sub(r"`([^`]+)`", r"\1", clean)
                self.preview_text.insert("end", clean + "\n")
        self.preview_text.configure(state="disabled")

    def new_note(self) -> None:
        self.commit_current()
        title = simpledialog.askstring("New note", "Title:", initialvalue="New Note", parent=self) or "New Note"
        note = Note.new(title)
        self.notes.append(note)
        self.current_id = note.note_id
        self.save_now()
        self.refresh_list(select_id=note.note_id)

    def delete_note(self) -> None:
        note = self.get_note(self.current_id)
        if not note:
            return
        if messagebox.askyesno("LeanDesk Notes", f'Delete "{note.title}"?', parent=self):
            self.notes = [row for row in self.notes if row.note_id != note.note_id]
            if not self.notes:
                self.notes.append(Note.new())
            self.current_id = self.notes[0].note_id
            self.save_now()
            self.refresh_list(select_id=self.current_id)

    def duplicate_note(self) -> None:
        note = self.get_note(self.current_id)
        if not note:
            return
        now = datetime.now().isoformat(timespec="seconds")
        copy = Note(str(uuid.uuid4()), f"{note.title} Copy", note.body, note.notebook, note.tags, now, now, note.pinned, dict(note.extra))
        self.notes.append(copy)
        self.save_now()
        self.refresh_list(select_id=copy.note_id)

    def import_markdown(self) -> None:
        value = filedialog.askopenfilename(parent=self, filetypes=(("Markdown and text", "*.md *.txt"),))
        if not value:
            return
        path = Path(value)
        note = Note.new(path.stem)
        note.body = read_bounded(path, limit=64 * 1024 * 1024).decode("utf-8", errors="replace")
        self.notes.append(note)
        self.save_now()
        self.refresh_list(select_id=note.note_id)
        if self.recent:
            self.recent.add(path, "Notes")

    def export_markdown(self) -> None:
        note = self.get_note(self.current_id)
        if not note:
            return
        value = filedialog.asksaveasfilename(parent=self, initialfile=f"{note.title}.md", defaultextension=".md", filetypes=(("Markdown", "*.md"), ("Text", "*.txt")))
        if value:
            atomic_write_text(Path(value), note.body)
            self.status_var.set(f"Exported {Path(value).name}")
            if self.recent:
                self.recent.add(value, "Notes")


    def recover_record(self, record: RecoveryRecord) -> None:
        if record.module != "Notes":
            return
        payload = record.payload
        if not isinstance(payload, dict):
            raise DataCorruptionError("Recovered Notes payload is invalid.")
        version = payload.get("schema_version", NOTES_SCHEMA_VERSION)
        if isinstance(version, bool) or not isinstance(version, int) or version != NOTES_SCHEMA_VERSION:
            raise DataCorruptionError("Recovered Notes schema is incompatible.")
        rows = payload.get("notes")
        if not isinstance(rows, list):
            raise DataCorruptionError("Recovered Notes collection is invalid.")
        self.notes = [Note.from_dict(row) for row in rows]
        self.current_id = self.notes[0].note_id if self.notes else None
        self.read_only = False
        self.load_error = None
        self.recovery_id = record.recovery_id
        if self.notes:
            self.refresh_list(select_id=self.current_id)
        else:
            self.note_list.delete(0, "end")
            self.editor_text.delete("1.0", "end")
            self.count_var.set("0 notes")
        self.status_var.set("Recovered unsaved Notes data")

    def toggle_preview(self) -> None:
        if self.preview_visible.get():
            try:
                self.split.forget(self.preview_frame)
            except tk.TclError:
                pass
            self.preview_visible.set(False)
        else:
            self.split.add(self.preview_frame, weight=1)
            self.preview_visible.set(True)


# RecoveryStore/RecoveryRecord are used for every Notes write boundary.
