from __future__ import annotations

import calendar
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from .core import CALENDAR_FILE, CONTACTS_FILE, TASKS_FILE, RecoveryRecord, RecoveryStore, atomic_write_json
from .data_boundary import DataCorruptionError, load_json_or_default
from .ui import COLORS, StatusBar

ORGANIZER_SCHEMA_VERSION = 1


def _validated_item(cls, row: dict, *, collection: str):
    if not isinstance(row, dict):
        raise DataCorruptionError(f"Invalid {collection} row.")
    known = {field.name for field in fields(cls)}
    values = {name: row[name] for name in known if name in row}
    for name, value in values.items():
        if not isinstance(value, str):
            raise DataCorruptionError(f"Invalid {collection} field: {name}.")
    item = cls(**values)
    identifier_name = next((name for name in known if name.endswith("_id")), None)
    if identifier_name:
        try:
            uuid.UUID(getattr(item, identifier_name))
        except (ValueError, AttributeError, TypeError) as exc:
            raise DataCorruptionError(f"Invalid {collection} identifier.") from exc
    item._extra = {name: value for name, value in row.items() if name not in known}
    return item


def _load_collection(path: Path, key: str, cls):
    result = load_json_or_default(Path(path), dict, expected_type=(dict, list), limit=64 * 1024 * 1024)
    payload = result.value
    read_only = result.read_only
    error = result.error
    extra = {}
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        version = payload.get("schema_version", ORGANIZER_SCHEMA_VERSION)
        if isinstance(version, bool) or not isinstance(version, int) or version < 1 or version > ORGANIZER_SCHEMA_VERSION:
            return [], True, f"Unsupported or invalid {key} schema version.", {
                k: v for k, v in payload.items() if k not in {"schema_version", key}
            }
        rows = payload.get(key, [])
        extra = {k: v for k, v in payload.items() if k not in {"schema_version", key}}
    else:
        rows = []
    if not isinstance(rows, list):
        return [], True, f"Stored {key} collection is invalid.", extra
    items = []
    try:
        for row in rows:
            items.append(_validated_item(cls, row, collection=key))
    except (TypeError, ValueError, DataCorruptionError) as exc:
        return [], True, str(exc), extra
    return items, read_only, error, extra


def _item_dict(item) -> dict:
    row = asdict(item)
    row.update(getattr(item, "_extra", {}))
    return row


def _save_collection(frame, path: Path, key: str, module: str, items) -> bool:
    if getattr(frame, "read_only", False):
        if hasattr(frame, "status_var"):
            frame.status_var.set(f"{module} data is read-only; the original store was preserved")
        return False
    payload = dict(getattr(frame, "_store_extra", {}))
    payload.update({"schema_version": ORGANIZER_SCHEMA_VERSION, key: [_item_dict(item) for item in items]})
    try:
        frame.recovery.save(
            RecoveryRecord(
                frame.recovery_id,
                module,
                f"LeanDesk {module}",
                str(path),
                datetime.now().isoformat(timespec="seconds"),
                payload,
            )
        )
        atomic_write_json(Path(path), payload)
        frame.recovery.delete(frame.recovery_id)
        return True
    except Exception as exc:
        if hasattr(frame, "status_var"):
            frame.status_var.set(f"{module} data was not saved: {type(exc).__name__}")
        return False


def _recover_collection(frame, record: RecoveryRecord, key: str, module: str, cls) -> bool:
    if record.module != module or not isinstance(record.payload, dict):
        return False
    payload = record.payload
    version = payload.get("schema_version", ORGANIZER_SCHEMA_VERSION)
    rows = payload.get(key)
    if isinstance(version, bool) or not isinstance(version, int) or version != ORGANIZER_SCHEMA_VERSION:
        raise DataCorruptionError(f"Recovered {module} schema is incompatible.")
    if not isinstance(rows, list):
        raise DataCorruptionError(f"Recovered {module} collection is invalid.")
    items = []
    for row in rows:
        items.append(_validated_item(cls, row, collection=f"recovered {module}"))
    setattr(frame, key, items)
    frame._store_extra = {name: value for name, value in payload.items() if name not in {"schema_version", key}}
    frame.read_only = False
    frame.recovery_id = record.recovery_id
    return True


@dataclass
class Task:
    task_id: str
    title: str
    due: str = ""
    priority: str = "Normal"
    status: str = "Open"
    project: str = ""
    notes: str = ""


class TasksFrame(ttk.Frame):
    def __init__(self, master, *, on_title_changed=None):
        super().__init__(master)
        self.on_title_changed = on_title_changed
        self.tasks: list[Task] = []
        self.current_id: str | None = None
        self.read_only = False
        self._store_extra = {}
        self.recovery = RecoveryStore()
        self.recovery_id = str(uuid.uuid4())
        self.search_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.due_var = tk.StringVar()
        self.priority_var = tk.StringVar(value="Normal")
        self.status_edit_var = tk.StringVar(value="Open")
        self.project_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")
        self.count_var = tk.StringVar(value="0 tasks")
        self._build_ui(); self.load()

    def _build_ui(self):
        ribbon = tk.Frame(self, bg=COLORS["panel"], height=72, highlightbackground=COLORS["line"], highlightthickness=1)
        ribbon.pack(fill="x"); ribbon.pack_propagate(False)
        for label, command in (("New Task", self.new_task), ("Save", self.save_current), ("Complete / Reopen", self.toggle_complete), ("Delete", self.delete_task)):
            ttk.Button(ribbon, text=label, command=command).pack(side="left", padx=4, pady=12)
        tk.Label(ribbon, text="TASKS", bg=COLORS["panel"], fg=COLORS["cobalt"], font=("Segoe UI Bold", 14)).pack(side="right", padx=16)
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True)
        left = ttk.Frame(body, style="Panel.TFrame"); right = ttk.Frame(body, style="Panel.TFrame", width=340)
        body.add(left, weight=5); body.add(right, weight=2)
        search = ttk.Entry(left, textvariable=self.search_var); search.pack(fill="x", padx=12, pady=12); search.bind("<KeyRelease>", lambda _e: self.refresh())
        self.tree = ttk.Treeview(left, columns=("due", "priority", "status", "project", "title"), show="headings", selectmode="browse")
        for col, title, width in (("due", "Due", 95), ("priority", "Priority", 80), ("status", "Status", 90), ("project", "Project", 130), ("title", "Task", 360)):
            self.tree.heading(col, text=title); self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 12)); self.tree.bind("<<TreeviewSelect>>", self.on_select)
        tk.Label(right, text="TASK DETAILS", bg=COLORS["panel"], fg=COLORS["cobalt"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=12, pady=(12, 5))
        for label, var, values in (("Title", self.title_var, None), ("Due YYYY-MM-DD", self.due_var, None), ("Priority", self.priority_var, ("Low", "Normal", "High", "Critical")), ("Status", self.status_edit_var, ("Open", "In Progress", "Waiting", "Completed")), ("Project", self.project_var, None)):
            tk.Label(right, text=label, bg=COLORS["panel"], fg=COLORS["muted"]).pack(anchor="w", padx=12, pady=(7, 2))
            widget = ttk.Combobox(right, textvariable=var, values=values, state="readonly") if values else ttk.Entry(right, textvariable=var)
            widget.pack(fill="x", padx=12)
        tk.Label(right, text="Notes", bg=COLORS["panel"], fg=COLORS["muted"]).pack(anchor="w", padx=12, pady=(7, 2))
        self.notes_text = tk.Text(right, height=12, wrap="word", bg="#101827", fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", padx=8, pady=8)
        self.notes_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        status = StatusBar(self); status.pack(fill="x"); status.add_left(self.status_var); status.add_right(self.count_var, muted=True)

    def load(self):
        self.tasks, self.read_only, error, self._store_extra = _load_collection(Path(TASKS_FILE), "tasks", Task)
        if error:
            self.status_var.set("Tasks data could not be loaded; the original file was preserved")
        self.refresh()

    def save_all(self): return _save_collection(self, Path(TASKS_FILE), "tasks", "Tasks", self.tasks)
    def get(self, task_id): return next((item for item in self.tasks if item.task_id == task_id), None)

    def refresh(self, select_id=None):
        needle = self.search_var.get().strip().lower(); rows = self.tasks
        if needle: rows = [item for item in rows if needle in "\n".join((item.title, item.project, item.notes, item.status)).lower()]
        rank = {"Critical": 0, "High": 1, "Normal": 2, "Low": 3}
        rows = sorted(rows, key=lambda item: (item.status == "Completed", item.due or "9999", rank.get(item.priority, 9), item.title.lower()))
        self.visible_ids = [item.task_id for item in rows]; self.tree.delete(*self.tree.get_children()); selected = None
        for index, item in enumerate(rows):
            iid = f"task-{index}"; self.tree.insert("", "end", iid=iid, values=(item.due or "-", item.priority, item.status, item.project or "-", item.title))
            if item.task_id == (select_id or self.current_id): selected = iid
        if selected: self.tree.selection_set(selected); self.tree.focus(selected)
        self.count_var.set(f"{len(self.tasks)} task{'s' if len(self.tasks) != 1 else ''}")

    def on_select(self, _event=None):
        selection = self.tree.selection()
        if not selection: return
        index = int(selection[0].split("-")[-1]); task = self.get(self.visible_ids[index])
        if not task: return
        self.current_id = task.task_id; self.title_var.set(task.title); self.due_var.set(task.due); self.priority_var.set(task.priority); self.status_edit_var.set(task.status); self.project_var.set(task.project)
        self.notes_text.delete("1.0", "end"); self.notes_text.insert("1.0", task.notes)
        if self.on_title_changed: self.on_title_changed(f"Tasks — {task.title}", False)

    def new_task(self):
        item = Task(str(uuid.uuid4()), "New Task", due=date.today().isoformat()); self.tasks.append(item); self.current_id = item.task_id; self.save_all(); self.refresh(item.task_id); self._load_direct(item)
    def _load_direct(self, task):
        self.title_var.set(task.title); self.due_var.set(task.due); self.priority_var.set(task.priority); self.status_edit_var.set(task.status); self.project_var.set(task.project); self.notes_text.delete("1.0", "end"); self.notes_text.insert("1.0", task.notes)
    def save_current(self):
        task = self.get(self.current_id)
        if not task: self.new_task(); task = self.get(self.current_id)
        task.title = self.title_var.get().strip() or "Untitled Task"; task.due = self.due_var.get().strip(); task.priority = self.priority_var.get(); task.status = self.status_edit_var.get(); task.project = self.project_var.get().strip(); task.notes = self.notes_text.get("1.0", "end-1c").strip(); self.save_all(); self.refresh(task.task_id); self.status_var.set(f"Saved {task.title}")
    def toggle_complete(self):
        task = self.get(self.current_id)
        if task: task.status = "Open" if task.status == "Completed" else "Completed"; self.status_edit_var.set(task.status); self.save_all(); self.refresh(task.task_id)
    def delete_task(self):
        task = self.get(self.current_id)
        if task and messagebox.askyesno("LeanDesk Tasks", f'Delete "{task.title}"?', parent=self): self.tasks = [item for item in self.tasks if item.task_id != task.task_id]; self.current_id = None; self.save_all(); self.refresh()

    def recover_record(self, record: RecoveryRecord) -> None:
        if _recover_collection(self, record, "tasks", "Tasks", Task):
            self.current_id = self.tasks[0].task_id if self.tasks else None
            self.refresh(self.current_id)
            self.status_var.set("Recovered unsaved Tasks data")


@dataclass
class CalendarEvent:
    event_id: str
    date: str
    title: str
    time: str = ""
    notes: str = ""


class CalendarFrame(ttk.Frame):
    def __init__(self, master, *, on_title_changed=None):
        super().__init__(master); self.on_title_changed = on_title_changed; today = date.today(); self.year = today.year; self.month = today.month; self.selected_date = today
        self.events: list[CalendarEvent] = []; self.read_only = False; self._store_extra = {}; self.recovery = RecoveryStore(); self.recovery_id = str(uuid.uuid4()); self.month_var = tk.StringVar(); self.status_var = tk.StringVar(value="Ready"); self._build_ui(); self.load(); self.render_month()
    def _build_ui(self):
        ribbon = tk.Frame(self, bg=COLORS["panel"], height=72, highlightbackground=COLORS["line"], highlightthickness=1); ribbon.pack(fill="x"); ribbon.pack_propagate(False)
        ttk.Button(ribbon, text="Previous", command=lambda: self.shift_month(-1)).pack(side="left", padx=4, pady=12); ttk.Button(ribbon, text="Today", command=self.go_today).pack(side="left", padx=4, pady=12); ttk.Button(ribbon, text="Next", command=lambda: self.shift_month(1)).pack(side="left", padx=4, pady=12); ttk.Button(ribbon, text="Add Event", command=self.add_event).pack(side="left", padx=12, pady=12); ttk.Button(ribbon, text="Delete Event", command=self.delete_event).pack(side="left", padx=4, pady=12)
        tk.Label(ribbon, textvariable=self.month_var, bg=COLORS["panel"], fg=COLORS["copper"], font=("Segoe UI Bold", 16)).pack(side="right", padx=16)
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True); self.grid_frame = ttk.Frame(body, style="Panel.TFrame"); side = ttk.Frame(body, style="Panel.TFrame", width=330); body.add(self.grid_frame, weight=5); body.add(side, weight=2)
        tk.Label(side, text="EVENTS", bg=COLORS["panel"], fg=COLORS["copper"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=12, pady=(12, 5)); self.event_list = tk.Listbox(side, bg="#101827", fg=COLORS["text"], selectbackground="#75492d", relief="flat", bd=0, activestyle="none"); self.event_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        status = StatusBar(self); status.pack(fill="x"); status.add_left(self.status_var)
    def load(self):
        self.events, self.read_only, error, self._store_extra = _load_collection(Path(CALENDAR_FILE), "events", CalendarEvent)
        if error: self.status_var.set("Calendar data could not be loaded; the original file was preserved")
    def save(self): return _save_collection(self, Path(CALENDAR_FILE), "events", "Calendar", self.events)
    def render_month(self):
        for child in self.grid_frame.winfo_children(): child.destroy()
        self.month_var.set(f"{calendar.month_name[self.month]} {self.year}")
        for col, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
            tk.Label(self.grid_frame, text=name, bg=COLORS["panel2"], fg=COLORS["muted"], font=("Segoe UI Semibold", 9)).grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
            self.grid_frame.columnconfigure(col, weight=1)
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        for row_index, week in enumerate(weeks, 1):
            self.grid_frame.rowconfigure(row_index, weight=1)
            for col, day in enumerate(week):
                if not day:
                    tk.Frame(self.grid_frame, bg="#121a29").grid(row=row_index, column=col, sticky="nsew", padx=1, pady=1); continue
                current = date(self.year, self.month, day); count = sum(item.date == current.isoformat() for item in self.events); text = f"{day}\n{count} event{'s' if count != 1 else ''}" if count else str(day)
                bg = "#314a73" if current == self.selected_date else COLORS["panel2"]
                button = tk.Button(self.grid_frame, text=text, command=lambda value=current: self.select_date(value), bg=bg, fg=COLORS["text"], activebackground="#3c5476", activeforeground="#ffffff", relief="flat", bd=0, anchor="nw", justify="left", padx=8, pady=7, font=("Segoe UI", 10)); button.grid(row=row_index, column=col, sticky="nsew", padx=1, pady=1)
        self.refresh_events()
        if self.on_title_changed: self.on_title_changed(f"Calendar — {calendar.month_name[self.month]} {self.year}", False)
    def select_date(self, value): self.selected_date = value; self.render_month(); self.status_var.set(value.strftime("%A, %B %d, %Y"))
    def refresh_events(self):
        self.event_list.delete(0, "end"); self.visible_events = [item for item in sorted(self.events, key=lambda row: (row.date, row.time, row.title)) if item.date == self.selected_date.isoformat()]
        for item in self.visible_events: self.event_list.insert("end", f"{item.time or 'All day'}  {item.title}\n  {item.notes}"[:100])
    def shift_month(self, delta):
        value = self.month - 1 + delta; self.year += value // 12; self.month = value % 12 + 1; self.selected_date = date(self.year, self.month, 1); self.render_month()
    def go_today(self): today = date.today(); self.year, self.month, self.selected_date = today.year, today.month, today; self.render_month()
    def add_event(self):
        title = simpledialog.askstring("Add event", f"Event for {self.selected_date.isoformat()}:", parent=self)
        if not title: return
        time_value = simpledialog.askstring("Event time", "Time (optional, e.g. 2:30 PM):", parent=self) or ""; notes = simpledialog.askstring("Event notes", "Notes (optional):", parent=self) or ""
        self.events.append(CalendarEvent(str(uuid.uuid4()), self.selected_date.isoformat(), title.strip(), time_value.strip(), notes.strip())); self.save(); self.render_month()
    def delete_event(self):
        selection = self.event_list.curselection()
        if not selection: return
        event = self.visible_events[selection[0]]
        if messagebox.askyesno("LeanDesk Calendar", f'Delete "{event.title}"?', parent=self): self.events = [item for item in self.events if item.event_id != event.event_id]; self.save(); self.render_month()

    def recover_record(self, record: RecoveryRecord) -> None:
        if _recover_collection(self, record, "events", "Calendar", CalendarEvent):
            self.render_month()
            self.status_var.set("Recovered unsaved Calendar data")


@dataclass
class Contact:
    contact_id: str
    name: str
    company: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    notes: str = ""


class ContactsFrame(ttk.Frame):
    def __init__(self, master, *, on_title_changed=None):
        super().__init__(master); self.on_title_changed = on_title_changed; self.contacts: list[Contact] = []; self.current_id = None; self.read_only = False; self._store_extra = {}; self.recovery = RecoveryStore(); self.recovery_id = str(uuid.uuid4()); self.search_var = tk.StringVar(); self.name_var = tk.StringVar(); self.company_var = tk.StringVar(); self.email_var = tk.StringVar(); self.phone_var = tk.StringVar(); self.address_var = tk.StringVar(); self.status_var = tk.StringVar(value="Ready"); self.count_var = tk.StringVar(value="0 contacts"); self._build_ui(); self.load()
    def _build_ui(self):
        ribbon = tk.Frame(self, bg=COLORS["panel"], height=72, highlightbackground=COLORS["line"], highlightthickness=1); ribbon.pack(fill="x"); ribbon.pack_propagate(False)
        for label, command in (("New Contact", self.new_contact), ("Save", self.save_current), ("Delete", self.delete_contact), ("Copy Email", self.copy_email)):
            ttk.Button(ribbon, text=label, command=command).pack(side="left", padx=4, pady=12)
        tk.Label(ribbon, text="CONTACTS", bg=COLORS["panel"], fg=COLORS["jade"], font=("Segoe UI Bold", 14)).pack(side="right", padx=16)
        body = ttk.Panedwindow(self, orient="horizontal"); body.pack(fill="both", expand=True); left = ttk.Frame(body, style="Panel.TFrame"); right = ttk.Frame(body, style="Panel.TFrame", width=390); body.add(left, weight=4); body.add(right, weight=3)
        search = ttk.Entry(left, textvariable=self.search_var); search.pack(fill="x", padx=12, pady=12); search.bind("<KeyRelease>", lambda _e: self.refresh())
        self.tree = ttk.Treeview(left, columns=("name", "company", "email", "phone"), show="headings", selectmode="browse")
        for col, title, width in (("name", "Name", 190), ("company", "Company", 180), ("email", "Email", 240), ("phone", "Phone", 130)): self.tree.heading(col, text=title); self.tree.column(col, width=width)
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 12)); self.tree.bind("<<TreeviewSelect>>", self.on_select)
        tk.Label(right, text="CONTACT DETAILS", bg=COLORS["panel"], fg=COLORS["jade"], font=("Segoe UI Semibold", 10)).pack(anchor="w", padx=12, pady=(12, 5))
        for label, var in (("Name", self.name_var), ("Company", self.company_var), ("Email", self.email_var), ("Phone", self.phone_var), ("Address", self.address_var)):
            tk.Label(right, text=label, bg=COLORS["panel"], fg=COLORS["muted"]).pack(anchor="w", padx=12, pady=(7, 2)); ttk.Entry(right, textvariable=var).pack(fill="x", padx=12)
        tk.Label(right, text="Notes", bg=COLORS["panel"], fg=COLORS["muted"]).pack(anchor="w", padx=12, pady=(7, 2)); self.notes_text = tk.Text(right, height=12, wrap="word", bg="#101827", fg=COLORS["text"], insertbackground=COLORS["text"], relief="flat", padx=8, pady=8); self.notes_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        status = StatusBar(self); status.pack(fill="x"); status.add_left(self.status_var); status.add_right(self.count_var, muted=True)
    def load(self):
        self.contacts, self.read_only, error, self._store_extra = _load_collection(Path(CONTACTS_FILE), "contacts", Contact)
        if error: self.status_var.set("Contacts data could not be loaded; the original file was preserved")
        self.refresh()
    def save_all(self): return _save_collection(self, Path(CONTACTS_FILE), "contacts", "Contacts", self.contacts)
    def get(self, cid): return next((item for item in self.contacts if item.contact_id == cid), None)
    def refresh(self, select_id=None):
        needle = self.search_var.get().strip().lower(); rows = self.contacts
        if needle: rows = [item for item in rows if needle in "\n".join((item.name, item.company, item.email, item.phone, item.notes)).lower()]
        rows = sorted(rows, key=lambda item: item.name.lower()); self.visible_ids = [item.contact_id for item in rows]; self.tree.delete(*self.tree.get_children()); selected = None
        for index, item in enumerate(rows): iid=f"contact-{index}"; self.tree.insert("", "end", iid=iid, values=(item.name, item.company, item.email, item.phone)); selected = iid if item.contact_id == (select_id or self.current_id) else selected
        if selected: self.tree.selection_set(selected); self.tree.focus(selected)
        self.count_var.set(f"{len(self.contacts)} contact{'s' if len(self.contacts) != 1 else ''}")
    def on_select(self, _event=None):
        selection=self.tree.selection()
        if not selection:return
        index=int(selection[0].split("-")[-1]); item=self.get(self.visible_ids[index])
        if not item:return
        self.current_id=item.contact_id; self.name_var.set(item.name); self.company_var.set(item.company); self.email_var.set(item.email); self.phone_var.set(item.phone); self.address_var.set(item.address); self.notes_text.delete("1.0","end"); self.notes_text.insert("1.0",item.notes)
        if self.on_title_changed:self.on_title_changed(f"Contacts — {item.name}",False)
    def new_contact(self): item=Contact(str(uuid.uuid4()),"New Contact");self.contacts.append(item);self.current_id=item.contact_id;self.save_all();self.refresh(item.contact_id);self.name_var.set(item.name);self.company_var.set("");self.email_var.set("");self.phone_var.set("");self.address_var.set("");self.notes_text.delete("1.0","end")
    def save_current(self):
        item=self.get(self.current_id)
        if not item:self.new_contact();item=self.get(self.current_id)
        item.name=self.name_var.get().strip() or "Unnamed Contact";item.company=self.company_var.get().strip();item.email=self.email_var.get().strip();item.phone=self.phone_var.get().strip();item.address=self.address_var.get().strip();item.notes=self.notes_text.get("1.0","end-1c").strip();self.save_all();self.refresh(item.contact_id);self.status_var.set(f"Saved {item.name}")
    def delete_contact(self):
        item=self.get(self.current_id)
        if item and messagebox.askyesno("LeanDesk Contacts",f'Delete "{item.name}"?',parent=self):self.contacts=[row for row in self.contacts if row.contact_id!=item.contact_id];self.current_id=None;self.save_all();self.refresh()
    def copy_email(self):
        email=self.email_var.get().strip()
        if email:self.clipboard_clear();self.clipboard_append(email);self.status_var.set("Email copied")

    def recover_record(self, record: RecoveryRecord) -> None:
        if _recover_collection(self, record, "contacts", "Contacts", Contact):
            self.current_id = self.contacts[0].contact_id if self.contacts else None
            self.refresh(self.current_id)
            self.status_var.set("Recovered unsaved Contacts data")

