from __future__ import annotations

import io
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from typing import Any

from .core import RecentFiles, RecoveryRecord, RecoveryStore, atomic_write_json, atomic_write_text
from .data_boundary import DataCorruptionError, UnsupportedSchemaVersion, merge_known_and_extra, read_bounded, strict_json_load_bytes
from .save_policy import SavePolicyError, mark_save_boundary, validate_destination, write_atomically
from .ui import COLORS, StatusBar


@dataclass
class Shape:
    shape_id: str
    kind: str
    x1: float
    y1: float
    x2: float
    y2: float
    fill: str = "#5f8dff"
    outline: str = "#f4f1ea"
    width: int = 2
    text: str = ""
    rotation: float = 0.0
    group_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Shape":
        if not isinstance(payload, dict):
            raise DataCorruptionError("Drawing shape is not an object.")
        known = {"shape_id", "kind", "x1", "y1", "x2", "y2", "fill", "outline", "width", "text", "rotation", "group_id", "extra"}
        kind = payload.get("kind", "")
        if not isinstance(kind, str) or kind not in {"rectangle", "ellipse", "line", "arrow", "text"}:
            raise DataCorruptionError(f"Unsupported drawing shape kind: {kind!r}")
        shape_id = payload.get("shape_id", "")
        if not isinstance(shape_id, str) or not shape_id or len(shape_id) > 256 or any(ord(ch) < 32 for ch in shape_id):
            raise DataCorruptionError("Drawing shape identifier is invalid.")
        coord_values = [payload.get(name, 0.0) for name in ("x1", "y1", "x2", "y2")]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in coord_values):
            raise DataCorruptionError("Drawing shape coordinates are invalid.")
        coords = [float(value) for value in coord_values]
        width = payload.get("width", 2)
        if isinstance(width, bool) or not isinstance(width, int):
            raise DataCorruptionError("Drawing line width is invalid.")
        if not all(math.isfinite(value) and abs(value) <= 1_000_000 for value in coords):
            raise DataCorruptionError("Drawing shape coordinates exceed safe limits.")
        if not 1 <= width <= 128:
            raise DataCorruptionError("Drawing line width is invalid.")
        fill = payload.get("fill", "#5f8dff")
        outline = payload.get("outline", "#f4f1ea")
        text = payload.get("text", "")
        rotation = payload.get("rotation", 0.0)
        group_id = payload.get("group_id", "")
        explicit_extra = payload.get("extra", {})
        if not isinstance(fill, str) or len(fill) > 128 or not isinstance(outline, str) or len(outline) > 128:
            raise DataCorruptionError("Drawing shape colors are invalid.")
        if not isinstance(text, str) or len(text) > 1_000_000:
            raise DataCorruptionError("Drawing shape text is invalid or too large.")
        if isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or not math.isfinite(rotation):
            raise DataCorruptionError("Drawing shape rotation is invalid.")
        if not isinstance(group_id, str) or len(group_id) > 256:
            raise DataCorruptionError("Drawing group identifier is invalid.")
        if not isinstance(explicit_extra, dict):
            raise DataCorruptionError("Drawing shape extension data is invalid.")
        return cls(
            shape_id, kind, *coords,
            fill=fill,
            outline=outline,
            width=width,
            text=text,
            rotation=float(rotation) % 360,
            group_id=group_id,
            extra=dict(explicit_extra) | {key: value for key, value in payload.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return merge_known_and_extra({
            "shape_id": self.shape_id,
            "kind": self.kind,
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "fill": self.fill,
            "outline": self.outline,
            "width": self.width,
            "text": self.text,
            "rotation": self.rotation,
            "group_id": self.group_id,
        }, self.extra)


@dataclass
class Drawing:
    title: str = "Untitled Drawing"
    width: int = 1200
    height: int = 760
    background: str = "#fdfcf8"
    shapes: list[Shape] = field(default_factory=list)
    format_version: int = 1
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Drawing":
        if not isinstance(payload, dict):
            raise DataCorruptionError("Drawing payload is not an object.")
        version = payload.get("format_version", payload.get("schema_version", 1))
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise DataCorruptionError("Drawing format version is invalid.")
        if version > 1:
            raise UnsupportedSchemaVersion(version, 1)
        width = payload.get("width", 1200)
        height = payload.get("height", 760)
        if isinstance(width, bool) or not isinstance(width, int) or isinstance(height, bool) or not isinstance(height, int):
            raise DataCorruptionError("Drawing dimensions are invalid.")
        if not (64 <= width <= 20_000 and 64 <= height <= 20_000):
            raise DataCorruptionError("Drawing dimensions exceed safe limits.")
        title = payload.get("title", "Untitled Drawing")
        background = payload.get("background", "#fdfcf8")
        rows = payload.get("shapes", [])
        explicit_extra = payload.get("extra", {})
        if not isinstance(title, str) or len(title) > 4096:
            raise DataCorruptionError("Drawing title is invalid.")
        if not isinstance(background, str) or len(background) > 128:
            raise DataCorruptionError("Drawing background is invalid.")
        if not isinstance(rows, list) or len(rows) > 20_000:
            raise DataCorruptionError("Drawing shape collection is invalid or too large.")
        if not isinstance(explicit_extra, dict):
            raise DataCorruptionError("Drawing extension data is invalid.")
        known = {"format_version", "schema_version", "title", "width", "height", "background", "shapes", "extra"}
        return cls(
            title=title,
            width=width,
            height=height,
            background=background,
            shapes=[Shape.from_dict(row) for row in rows],
            format_version=version,
            extra=dict(explicit_extra) | {key: value for key, value in payload.items() if key not in known},
        )

    def to_dict(self) -> dict[str, Any]:
        return merge_known_and_extra({
            "format_version": 1,
            "title": self.title,
            "width": self.width,
            "height": self.height,
            "background": self.background,
            "shapes": [shape.to_dict() for shape in self.shapes],
        }, self.extra)


class DrawFrame(ttk.Frame):
    def __init__(self, master, *, recent: RecentFiles, on_recent_changed=None, on_title_changed=None):
        super().__init__(master)
        self.recent = recent
        self.on_recent_changed = on_recent_changed
        self.on_title_changed = on_title_changed
        self.drawing = Drawing()
        self.current_path: Path | None = None
        self.imported_source_path: Path | None = None
        self.recovery = RecoveryStore()
        self.recovery_id = str(uuid.uuid4())
        self.dirty = False
        self.tool = tk.StringVar(value="select")
        self.fill_color = "#5f8dff"
        self.outline_color = "#283044"
        self.selected_id: str | None = None
        self.selected_ids: list[str] = []
        self._clipboard_shapes: list[Shape] = []
        self._undo_stack: list[list[dict[str, Any]]] = []
        self._redo_stack: list[list[dict[str, Any]]] = []
        self.start_x = self.start_y = 0.0
        self.preview_item: int | None = None
        self.drag_last: tuple[float, float] | None = None
        self.status_var = tk.StringVar(value="Select a tool and draw on the canvas")
        self.zoom_var = tk.StringVar(value="100%")
        self._build_ui()
        self.render()

    def _build_ui(self) -> None:
        ribbon = tk.Frame(self, bg=COLORS["panel"], height=90, highlightbackground=COLORS["line"], highlightthickness=1)
        ribbon.pack(fill="x")
        ribbon.pack_propagate(False)
        for label, command in (("New", self.new_drawing), ("Open", self.open_drawing), ("Save", self.save), ("Save As", self.save_as), ("Export PNG", self.export_png), ("Export SVG", self.export_svg)):
            ttk.Button(ribbon, text=label, command=command).pack(side="left", padx=3, pady=17)
        tk.Frame(ribbon, bg=COLORS["line"], width=1).pack(side="left", fill="y", padx=8, pady=12)
        for label, value in (("Select", "select"), ("Rectangle", "rectangle"), ("Ellipse", "ellipse"), ("Line", "line"), ("Arrow", "arrow"), ("Text", "text")):
            ttk.Radiobutton(ribbon, text=label, variable=self.tool, value=value).pack(side="left", padx=3, pady=18)
        ttk.Button(ribbon, text="Fill Color", command=self.choose_fill).pack(side="left", padx=3, pady=17)
        ttk.Button(ribbon, text="Line Color", command=self.choose_outline).pack(side="left", padx=3, pady=17)
        ttk.Button(ribbon, text="Delete", command=self.delete_selected).pack(side="left", padx=3, pady=17)
        ttk.Button(ribbon, text="Group", command=self.group_selected).pack(side="left", padx=3, pady=17)
        ttk.Button(ribbon, text="Front", command=self.bring_to_front).pack(side="left", padx=3, pady=17)
        ttk.Button(ribbon, text="Undo", command=self.undo).pack(side="left", padx=3, pady=17)
        tk.Label(ribbon, text="DRAW", bg=COLORS["panel"], fg=COLORS["coral"], font=("Segoe UI Bold", 14)).pack(side="right", padx=16)

        shell = tk.Frame(self, bg=COLORS["workspace"])
        shell.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(shell, bg=COLORS["workspace"], highlightthickness=0, scrollregion=(0, 0, self.drawing.width + 120, self.drawing.height + 120))
        xscroll = ttk.Scrollbar(shell, orient="horizontal", command=self.canvas.xview)
        yscroll = ttk.Scrollbar(shell, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        self.canvas.bind("<ButtonPress-1>", self.pointer_down)
        self.canvas.bind("<B1-Motion>", self.pointer_move)
        self.canvas.bind("<ButtonRelease-1>", self.pointer_up)
        self.canvas.bind("<Delete>", lambda _e: self.delete_selected())
        self.canvas.bind("<BackSpace>", lambda _e: self.delete_selected())
        status = StatusBar(self)
        status.pack(fill="x")
        status.add_left(self.status_var)
        status.add_right(self.zoom_var, muted=True)

    def canvas_point(self, event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def render(self) -> None:
        self.canvas.delete("all")
        margin = 60
        self.canvas.create_rectangle(margin, margin, margin + self.drawing.width, margin + self.drawing.height, fill=self.drawing.background, outline="#6d7480", tags=("page",))
        for shape in self.drawing.shapes:
            self.draw_shape(shape, margin)
        self.canvas.configure(scrollregion=(0, 0, self.drawing.width + 120, self.drawing.height + 120))
        self.highlight_selected()

    def draw_shape(self, shape: Shape, margin: int = 60) -> int:
        coords = (shape.x1 + margin, shape.y1 + margin, shape.x2 + margin, shape.y2 + margin)
        tags = ("shape", shape.shape_id)
        if shape.kind == "rectangle":
            return self.canvas.create_rectangle(*coords, fill=shape.fill, outline=shape.outline, width=shape.width, tags=tags)
        if shape.kind == "ellipse":
            return self.canvas.create_oval(*coords, fill=shape.fill, outline=shape.outline, width=shape.width, tags=tags)
        if shape.kind == "arrow":
            return self.canvas.create_line(*coords, fill=shape.outline, width=shape.width, arrow="last", tags=tags)
        if shape.kind == "line":
            return self.canvas.create_line(*coords, fill=shape.outline, width=shape.width, tags=tags)
        return self.canvas.create_text(shape.x1 + margin, shape.y1 + margin, text=shape.text, fill=shape.outline, anchor="nw", font=("Segoe UI", max(8, int(shape.width * 6))), width=max(50, abs(shape.x2 - shape.x1)), tags=tags)

    def shape_by_id(self, shape_id: str | None) -> Shape | None:
        return next((shape for shape in self.drawing.shapes if shape.shape_id == shape_id), None)

    def _snapshot(self) -> None:
        self._undo_stack.append([shape.to_dict() for shape in self.drawing.shapes])
        self._redo_stack.clear()

    def select_shapes(self, shape_ids: list[str]) -> None:
        self.selected_ids = [shape_id for shape_id in shape_ids if self.shape_by_id(shape_id)]
        self.selected_id = self.selected_ids[-1] if self.selected_ids else None
        self.highlight_selected()

    def group_selected(self) -> None:
        if len(self.selected_ids) < 2:
            return
        self._snapshot()
        group_id = uuid.uuid4().hex
        for shape_id in self.selected_ids:
            self.shape_by_id(shape_id).group_id = group_id
        self.mark_dirty()

    def ungroup_selected(self) -> None:
        self._snapshot()
        for shape_id in self.selected_ids:
            self.shape_by_id(shape_id).group_id = ""
        self.mark_dirty()

    def resize_selected(self, scale_x: float, scale_y: float) -> None:
        if not self.selected_ids:
            return
        self._snapshot()
        for shape_id in self.selected_ids:
            shape = self.shape_by_id(shape_id)
            shape.x2 = shape.x1 + (shape.x2 - shape.x1) * scale_x
            shape.y2 = shape.y1 + (shape.y2 - shape.y1) * scale_y
        self.mark_dirty(); self.render()

    def rotate_selected(self, degrees: float) -> None:
        if not self.selected_ids:
            return
        self._snapshot()
        for shape_id in self.selected_ids:
            shape = self.shape_by_id(shape_id)
            shape.rotation = (shape.rotation + degrees) % 360
        self.mark_dirty(); self.render()

    def bring_to_front(self) -> None:
        selected = [shape for shape in self.drawing.shapes if shape.shape_id in self.selected_ids]
        if not selected:
            return
        self._snapshot()
        self.drawing.shapes = [shape for shape in self.drawing.shapes if shape.shape_id not in self.selected_ids] + selected
        self.mark_dirty(); self.render()

    def send_to_back(self) -> None:
        selected = [shape for shape in self.drawing.shapes if shape.shape_id in self.selected_ids]
        if not selected:
            return
        self._snapshot()
        self.drawing.shapes = selected + [shape for shape in self.drawing.shapes if shape.shape_id not in self.selected_ids]
        self.mark_dirty(); self.render()

    def copy_selected(self) -> None:
        self._clipboard_shapes = [Shape.from_dict(self.shape_by_id(shape_id).to_dict()) for shape_id in self.selected_ids]

    def paste_shapes(self) -> None:
        if not self._clipboard_shapes:
            return
        self._snapshot()
        pasted = []
        for source in self._clipboard_shapes:
            shape = Shape.from_dict(source.to_dict())
            shape.shape_id = uuid.uuid4().hex
            shape.x1 += 20; shape.x2 += 20; shape.y1 += 20; shape.y2 += 20
            self.drawing.shapes.append(shape); pasted.append(shape.shape_id)
        self.select_shapes(pasted); self.mark_dirty(); self.render()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append([shape.to_dict() for shape in self.drawing.shapes])
        self.drawing.shapes = [Shape.from_dict(row) for row in self._undo_stack.pop()]
        self.select_shapes([]); self.mark_dirty(); self.render()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append([shape.to_dict() for shape in self.drawing.shapes])
        self.drawing.shapes = [Shape.from_dict(row) for row in self._redo_stack.pop()]
        self.select_shapes([]); self.mark_dirty(); self.render()

    def pointer_down(self, event) -> None:
        self.canvas.focus_set()
        x, y = self.canvas_point(event)
        margin = 60
        x -= margin
        y -= margin
        if self.tool.get() == "select":
            items = self.canvas.find_overlapping(event.x - 2, event.y - 2, event.x + 2, event.y + 2)
            selected = None
            for item in reversed(items):
                tags = self.canvas.gettags(item)
                for tag in tags:
                    if self.shape_by_id(tag):
                        selected = tag
                        break
                if selected:
                    break
            self.selected_id = selected
            self.selected_ids = [selected] if selected else []
            self.drag_last = (x, y) if selected else None
            self.highlight_selected()
            return
        self.start_x, self.start_y = x, y
        self.preview_item = None
        if self.tool.get() == "text":
            text = simpledialog.askstring("Text", "Text to insert:", parent=self)
            if text:
                shape = Shape(str(uuid.uuid4()), "text", x, y, x + 240, y + 60, fill="", outline=self.outline_color, width=2, text=text)
                self.drawing.shapes.append(shape)
                self.selected_id = shape.shape_id
                self.selected_ids = [shape.shape_id]
                self.mark_dirty()
                self.render()

    def pointer_move(self, event) -> None:
        x, y = self.canvas_point(event)
        margin = 60
        x -= margin
        y -= margin
        if self.tool.get() == "select" and self.selected_id and self.drag_last:
            dx, dy = x - self.drag_last[0], y - self.drag_last[1]
            shape = self.shape_by_id(self.selected_id)
            if shape:
                shape.x1 += dx; shape.x2 += dx; shape.y1 += dy; shape.y2 += dy
                self.drag_last = (x, y)
                self.mark_dirty()
                self.render()
            return
        if self.tool.get() in {"rectangle", "ellipse", "line", "arrow"}:
            if self.preview_item:
                self.canvas.delete(self.preview_item)
            coords = (self.start_x + margin, self.start_y + margin, x + margin, y + margin)
            if self.tool.get() == "rectangle":
                self.preview_item = self.canvas.create_rectangle(*coords, outline=self.outline_color, fill=self.fill_color, stipple="gray50")
            elif self.tool.get() == "ellipse":
                self.preview_item = self.canvas.create_oval(*coords, outline=self.outline_color, fill=self.fill_color, stipple="gray50")
            else:
                self.preview_item = self.canvas.create_line(*coords, fill=self.outline_color, width=2, arrow="last" if self.tool.get() == "arrow" else "none")

    def pointer_up(self, event) -> None:
        if self.tool.get() == "select":
            self.drag_last = None
            return
        if self.tool.get() not in {"rectangle", "ellipse", "line", "arrow"}:
            return
        x, y = self.canvas_point(event)
        x -= 60; y -= 60
        if abs(x - self.start_x) < 3 and abs(y - self.start_y) < 3:
            if self.preview_item:
                self.canvas.delete(self.preview_item)
            return
        shape = Shape(str(uuid.uuid4()), self.tool.get(), self.start_x, self.start_y, x, y, self.fill_color, self.outline_color, 2)
        self.drawing.shapes.append(shape)
        self.selected_id = shape.shape_id
        self.selected_ids = [shape.shape_id]
        self.preview_item = None
        self.mark_dirty()
        self.render()

    def highlight_selected(self) -> None:
        self.canvas.delete("selection")
        for shape_id in self.selected_ids or ([self.selected_id] if self.selected_id else []):
            shape = self.shape_by_id(shape_id)
            if not shape: continue
            margin = 60
            x1, y1, x2, y2 = shape.x1 + margin, shape.y1 + margin, shape.x2 + margin, shape.y2 + margin
            if shape.kind == "text": x2 = x1 + max(80, abs(shape.x2 - shape.x1)); y2 = y1 + 45
            self.canvas.create_rectangle(min(x1, x2) - 5, min(y1, y2) - 5, max(x1, x2) + 5, max(y1, y2) + 5, outline=COLORS["cobalt"], dash=(4, 3), tags=("selection",))

    def choose_fill(self) -> None:
        color = colorchooser.askcolor(initialcolor=self.fill_color, parent=self)[1]
        if color:
            self.fill_color = color
            shape = self.shape_by_id(self.selected_id)
            if shape and shape.kind in {"rectangle", "ellipse"}:
                shape.fill = color
                self.mark_dirty(); self.render()

    def choose_outline(self) -> None:
        color = colorchooser.askcolor(initialcolor=self.outline_color, parent=self)[1]
        if color:
            self.outline_color = color
            shape = self.shape_by_id(self.selected_id)
            if shape:
                shape.outline = color
                self.mark_dirty(); self.render()

    def delete_selected(self) -> None:
        if self.selected_ids or self.selected_id:
            self._snapshot()
            selected = set(self.selected_ids or [self.selected_id])
            self.drawing.shapes = [shape for shape in self.drawing.shapes if shape.shape_id not in selected]
            self.selected_id = None
            self.selected_ids = []
            self.mark_dirty(); self.render()

    def mark_dirty(self) -> None:
        self.dirty = True
        self._update_title()
        self.status_var.set(f"{len(self.drawing.shapes)} objects")
        try:
            self.recovery.save(
                RecoveryRecord(
                    self.recovery_id,
                    "Draw",
                    self.drawing.title,
                    str(self.current_path or ""),
                    datetime.now().isoformat(timespec="seconds"),
                    self.drawing.to_dict(),
                )
            )
        except Exception:
            self.status_var.set("Recovery copy could not be updated")

    def _update_title(self) -> None:
        name = self.current_path.name if self.current_path else self.drawing.title
        if self.on_title_changed:
            self.on_title_changed(f"Draw — {name}", self.dirty)

    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("LeanDesk Draw", "Save drawing changes?", parent=self)
        if answer is None:
            return False
        return self.save() if answer else True

    def new_drawing(self) -> bool:
        if not self.confirm_discard():
            return False
        self.recovery.delete(self.recovery_id)
        self.recovery_id = str(uuid.uuid4())
        self.drawing = Drawing()
        self.current_path = None
        self.imported_source_path = None
        self.dirty = False
        self.selected_id = None
        self.render()
        self._update_title()
        return True

    def open_drawing(self, path: Path | None = None) -> bool:
        if not self.confirm_discard(): return False
        if path is None:
            value = filedialog.askopenfilename(parent=self, filetypes=(("LeanDesk drawing", "*.ldraw"), ("All files", "*.*")))
            if not value: return False
            path = Path(value)
        try:
            payload = strict_json_load_bytes(read_bounded(Path(path), limit=128 * 1024 * 1024))
            self.drawing = Drawing.from_dict(payload)
        except Exception as exc:
            messagebox.showerror("LeanDesk Draw", f"Could not open drawing.\n\n{exc}", parent=self)
            return False
        self.recovery.delete(self.recovery_id)
        self.recovery_id = str(uuid.uuid4())
        self.current_path = Path(path)
        self.imported_source_path = None
        self.dirty = False
        self.selected_id = None
        self.render()
        self.recent.add(path, "Draw")
        if self.on_recent_changed: self.on_recent_changed()
        self._update_title(); return True

    @mark_save_boundary
    def save(self) -> bool:
        return self.save_as() if self.current_path is None else self._write(self.current_path)

    @mark_save_boundary
    def save_as(self) -> bool:
        value = filedialog.asksaveasfilename(parent=self, defaultextension=".ldraw", filetypes=(("LeanDesk drawing", "*.ldraw"),))
        return self._write(Path(value)) if value else False

    @mark_save_boundary
    def _write(self, path: Path) -> bool:
        try:
            destination = validate_destination("Draw", path, imported_source=self.imported_source_path)
            write_atomically(destination, lambda temporary: atomic_write_json(temporary, self.drawing.to_dict()))
        except SavePolicyError as exc:
            messagebox.showwarning("LeanDesk Draw", str(exc), parent=self)
            return False
        except Exception as exc:
            messagebox.showerror("LeanDesk Draw", f"Could not save drawing.\n\n{exc}", parent=self)
            return False
        self.current_path = destination
        self.imported_source_path = None
        self.dirty = False
        self.recovery.delete(self.recovery_id)
        self.recent.add(destination, "Draw")
        if self.on_recent_changed:
            self.on_recent_changed()
        self._update_title()
        self.status_var.set(f"Saved {destination.name}")
        return True

    def export_svg(self) -> None:
        value = filedialog.asksaveasfilename(parent=self, defaultextension=".svg", filetypes=(("SVG", "*.svg"),))
        if not value:
            return
        try:
            destination = validate_destination("Draw", value, allow_export_only=True)
            write_atomically(destination, lambda temporary: atomic_write_text(temporary, self.to_svg()))
            self.status_var.set(f"Exported {destination.name}")
        except Exception as exc:
            messagebox.showerror("LeanDesk Draw", f"SVG export failed.\n\n{exc}", parent=self)

    def to_svg(self) -> str:
        rows = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.drawing.width}" height="{self.drawing.height}" viewBox="0 0 {self.drawing.width} {self.drawing.height}">', f'<rect width="100%" height="100%" fill="{self.drawing.background}"/>']
        for shape in self.drawing.shapes:
            x, y = min(shape.x1, shape.x2), min(shape.y1, shape.y2)
            w, h = abs(shape.x2 - shape.x1), abs(shape.y2 - shape.y1)
            if shape.kind == "rectangle": rows.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{shape.fill}" stroke="{shape.outline}" stroke-width="{shape.width}"/>')
            elif shape.kind == "ellipse": rows.append(f'<ellipse cx="{x + w/2}" cy="{y + h/2}" rx="{w/2}" ry="{h/2}" fill="{shape.fill}" stroke="{shape.outline}" stroke-width="{shape.width}"/>')
            elif shape.kind in {"line", "arrow"}: rows.append(f'<line x1="{shape.x1}" y1="{shape.y1}" x2="{shape.x2}" y2="{shape.y2}" stroke="{shape.outline}" stroke-width="{shape.width}"/>')
            else:
                import html
                rows.append(f'<text x="{shape.x1}" y="{shape.y1 + 20}" fill="{shape.outline}" font-family="Segoe UI" font-size="16">{html.escape(shape.text)}</text>')
        rows.append("</svg>")
        return "\n".join(rows)

    def recover_record(self, record: RecoveryRecord) -> None:
        if record.module != "Draw" or not self.confirm_discard():
            return
        self.drawing = Drawing.from_dict(record.payload)
        self.current_path = Path(record.original_path) if record.original_path else None
        self.imported_source_path = None
        self.recovery_id = record.recovery_id
        self.dirty = True
        self.selected_id = None
        self.render()
        self._update_title()
        self.status_var.set("Recovered unsaved drawing")

    def export_png(self) -> None:
        value = filedialog.asksaveasfilename(parent=self, defaultextension=".png", filetypes=(("PNG", "*.png"),))
        if not value:
            return
        try:
            from PIL import Image, ImageDraw
            destination = validate_destination("Draw", value, allow_export_only=True)

            def produce(temporary: Path) -> None:
                image = Image.new("RGB", (self.drawing.width, self.drawing.height), self.drawing.background)
                draw = ImageDraw.Draw(image)
                for shape in self.drawing.shapes:
                    box = (shape.x1, shape.y1, shape.x2, shape.y2)
                    if shape.kind == "rectangle":
                        draw.rectangle(box, fill=shape.fill, outline=shape.outline, width=shape.width)
                    elif shape.kind == "ellipse":
                        draw.ellipse(box, fill=shape.fill, outline=shape.outline, width=shape.width)
                    elif shape.kind in {"line", "arrow"}:
                        draw.line(box, fill=shape.outline, width=shape.width)
                    else:
                        draw.text((shape.x1, shape.y1), shape.text, fill=shape.outline)
                image.save(temporary, format="PNG")

            write_atomically(destination, produce)
            self.status_var.set(f"Exported {destination.name}")
        except Exception as exc:
            messagebox.showerror("LeanDesk Draw", f"PNG export failed.\n\n{exc}", parent=self)
