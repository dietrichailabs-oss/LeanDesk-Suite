"""Transactional cell editing for native and imported slide tables."""

from copy import deepcopy
import tkinter as tk
from tkinter import messagebox, ttk


def install_table_editor(owner, toolbar):
    def open_editor():
        if not any(item.kind == "table" for item in owner.current_slide().objects):
            messagebox.showinfo("Edit Tables", "Insert a table first.", parent=owner)
            return
        dialog = SlideTableEditor(owner)
        dialog.grab_set()
        owner.wait_window(dialog)

    button = ttk.Button(toolbar, text="Edit Tables...", command=open_editor)
    button.pack(side="left", padx=3, pady=17)
    return button


class SlideTableEditor(tk.Toplevel):
    """Edits drafts until Apply; Cancel never changes the slide model."""

    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.tables = [item for item in owner.current_slide().objects if item.kind == "table"]
        self.drafts = [deepcopy(item.data) for item in self.tables]
        self.active_table = 0
        self.active_cell = (0, 0)
        self.title("Edit Slide Tables")
        self.geometry("660x440")
        self.minsize(420, 300)
        self.transient(owner.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=8)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Table:").grid(row=0, column=0, padx=(0, 8))
        self.selector = ttk.Combobox(top, state="readonly", values=[
            "Table {}".format(i + 1) for i in range(len(self.tables))
        ])
        self.selector.grid(row=0, column=1, sticky="ew")
        self.selector.bind("<<ComboboxSelected>>", self.switch_table)

        grid = ttk.Frame(self, padding=(8, 0))
        grid.grid(row=1, column=0, sticky="nsew")
        grid.columnconfigure(0, weight=1)
        grid.rowconfigure(0, weight=1)
        self.cells = ttk.Treeview(grid, show="tree headings", selectmode="browse")
        self.cells.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(grid, orient="vertical", command=self.cells.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(grid, orient="horizontal", command=self.cells.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.cells.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.cells.bind("<ButtonRelease-1>", self.pick_cell)
        self.cells.bind("<Return>", lambda _event: self.value.focus_set())

        edit = ttk.Frame(self, padding=8)
        edit.grid(row=2, column=0, sticky="ew")
        edit.columnconfigure(0, weight=1)
        self.cell_label = ttk.Label(edit)
        self.cell_label.grid(row=0, column=0, sticky="w")
        self.value = tk.Text(edit, height=3, width=20, wrap="word", undo=True)
        self.value.grid(row=1, column=0, sticky="ew")
        self.value.bind("<Tab>", lambda _event: self.next_cell(1))
        self.value.bind("<Shift-Tab>", lambda _event: self.next_cell(-1))
        ttk.Label(edit, text="Click a cell to edit. Tab: next cell. Enter: new line.").grid(
            row=2, column=0, sticky="w"
        )
        actions = ttk.Frame(self, padding=8)
        actions.grid(row=3, column=0, sticky="ew")
        ttk.Button(actions, text="Apply", command=self.apply).pack(side="right")
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        if self.tables:
            selected = getattr(owner, "selected_object_id", None)
            self.active_table = next((i for i, item in enumerate(self.tables)
                                      if item.object_id == selected), 0)
            self.selector.current(self.active_table)
            self.show_table()

    def matrix(self):
        data = self.drafts[self.active_table]
        values = data.get("values", [])
        rows = max(1, int(data.get("rows", len(values) or 1)))
        cols = max(1, int(data.get("cols", max((len(row) for row in values), default=1))))
        normalized = [[str(values[r][c]) if r < len(values) and c < len(values[r])
                       and values[r][c] is not None else ""
                       for c in range(cols)] for r in range(rows)]
        data["values"] = normalized
        return normalized

    def show_table(self):
        values = self.matrix()
        self.cells.delete(*self.cells.get_children())
        columns = [str(i) for i in range(len(values[0]))]
        self.cells.configure(columns=columns)
        self.cells.heading("#0", text="Row")
        self.cells.column("#0", width=48, stretch=False)
        for i, column in enumerate(columns):
            self.cells.heading(column, text="Column {}".format(i + 1))
            self.cells.column(column, width=140, minwidth=80, stretch=False)
        for r, row in enumerate(values):
            self.cells.insert("", "end", iid=str(r), text=str(r + 1), values=row)
        self.load_cell(0, 0)

    def store_cell(self):
        if not self.tables:
            return
        row, col = self.active_cell
        values = self.matrix()
        values[row][col] = self.value.get("1.0", "end-1c")
        self.cells.item(str(row), values=values[row])

    def load_cell(self, row, col):
        self.active_cell = row, col
        self.value.delete("1.0", "end")
        self.value.insert("1.0", self.matrix()[row][col])
        self.cell_label.configure(text="Row {}, Column {}".format(row + 1, col + 1))
        self.cells.selection_set(str(row))
        self.cells.focus(str(row))
        self.cells.see(str(row))

    def pick_cell(self, event):
        row = self.cells.identify_row(event.y)
        column = self.cells.identify_column(event.x)
        if not row or not column or column == "#0":
            return
        self.store_cell()
        self.load_cell(int(row), int(column[1:]) - 1)
        self.value.focus_set()

    def next_cell(self, direction):
        self.store_cell()
        values = self.matrix()
        rows, cols = len(values), len(values[0])
        index = (self.active_cell[0] * cols + self.active_cell[1] + direction) % (rows * cols)
        self.load_cell(*divmod(index, cols))
        return "break"

    def switch_table(self, _event=None):
        self.store_cell()
        self.active_table = self.selector.current()
        self.show_table()

    def apply(self):
        self.store_cell()
        changed = False
        for item, draft in zip(self.tables, self.drafts):
            if item.data != draft:
                item.data = deepcopy(draft)
                changed = True
        if changed:
            self.owner.selected_object_id = self.tables[self.active_table].object_id
            self.owner.dirty = True
            self.owner.render_slide()
            self.owner._save_recovery()
        self.destroy()
