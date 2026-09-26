"""Bounded Office-style spreadsheet features shared by the Sheets UI and tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
import re
from typing import Any, Callable, Iterable


_CELL_RE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")
_TABLE_REF_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]$")
_CRITERION_RE = re.compile(r"^(<=|>=|<>|=|<|>)?(.*)$", re.DOTALL)
MAX_FEATURE_ITEMS = 10_000


def _is_excel_cell_reference(value: str) -> bool:
    match = _CELL_RE.fullmatch(value.upper())
    return bool(match and column_number(match.group(1)) <= 16_384 and int(match.group(2)) <= 1_048_576)


def column_number(label: str) -> int:
    value = 0
    for char in label.upper():
        if not "A" <= char <= "Z":
            raise ValueError("Invalid column label")
        value = value * 26 + ord(char) - 64
    return value


def column_label(number: int) -> str:
    if number < 1:
        raise ValueError("Column number must be positive")
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def parse_cell(address: str) -> tuple[int, int]:
    match = _CELL_RE.fullmatch(address.upper())
    if not match:
        raise ValueError(f"Invalid cell address: {address}")
    return int(match.group(2)), column_number(match.group(1))


def parse_range(reference: str) -> tuple[int, int, int, int]:
    parts = reference.upper().split(":")
    if len(parts) == 1:
        parts.append(parts[0])
    if len(parts) != 2:
        raise ValueError("Invalid range")
    row1, col1 = parse_cell(parts[0])
    row2, col2 = parse_cell(parts[1])
    top, bottom = sorted((row1, row2))
    left, right = sorted((col1, col2))
    if (bottom - top + 1) * (right - left + 1) > MAX_FEATURE_ITEMS:
        raise ValueError("Range exceeds the bounded feature limit")
    return top, left, bottom, right


def iter_range(reference: str) -> Iterable[str]:
    top, left, bottom, right = parse_range(reference)
    for row in range(top, bottom + 1):
        for col in range(left, right + 1):
            yield f"{column_label(col)}{row}"


def _raw(sheet: Any, address: str) -> Any:
    if hasattr(sheet, "get_raw"):
        return sheet.get_raw(address)
    cell = getattr(sheet, "cells", {}).get(address)
    if cell is None:
        return ""
    for attribute in ("raw", "value", "text"):
        if hasattr(cell, attribute):
            return getattr(cell, attribute)
    return cell


def _write(sheet: Any, address: str, value: Any) -> None:
    if hasattr(sheet, "set_cell"):
        sheet.set_cell(address, value)
        return
    cells = getattr(sheet, "cells", None)
    if cells is None:
        raise TypeError("Sheet does not expose writable cells")
    existing = cells.get(address)
    if existing is not None:
        for attribute in ("raw", "value", "text"):
            if hasattr(existing, attribute):
                setattr(existing, attribute, value)
                return
    cells[address] = value


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass
class StructuredTable:
    name: str
    range_ref: str
    headers: list[str]
    style: str = "Medium2"
    banded_rows: bool = True
    banded_columns: bool = False
    show_totals: bool = False
    totals: dict[str, str] = field(default_factory=dict)
    filters: dict[str, list[str]] = field(default_factory=dict)

    def validate(self) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", self.name) or _is_excel_cell_reference(self.name):
            raise ValueError("Table name must be a valid identifier")
        top, left, bottom, right = parse_range(self.range_ref)
        if bottom <= top:
            raise ValueError("A table requires a header and at least one data row")
        if len(self.headers) != right - left + 1:
            raise ValueError("Header count does not match table width")
        if len(set(self.headers)) != len(self.headers) or any(not str(item).strip() for item in self.headers):
            raise ValueError("Table headers must be non-empty and unique")


@dataclass
class ConditionalRule:
    range_ref: str
    kind: str
    operand: Any = None
    foreground: str = "#9C0006"
    background: str = "#FFC7CE"

    def matches(self, value: Any, peers: Iterable[Any] = ()) -> bool:
        kind = self.kind.lower()
        if kind in {"greater_than", "less_than", "equal"}:
            left = _number(value)
            right = _number(self.operand)
            if left is None or right is None:
                return kind == "equal" and str(value) == str(self.operand)
            return {"greater_than": left > right, "less_than": left < right, "equal": left == right}[kind]
        if kind == "text_contains":
            return str(self.operand).casefold() in str(value).casefold()
        if kind == "duplicate":
            values = [str(item) for item in peers]
            return values.count(str(value)) > 1
        raise ValueError("Unsupported conditional-format rule")


@dataclass
class ChartSpec:
    name: str
    kind: str
    source_range: str
    title: str = ""
    legend: bool = True
    x: int = 40
    y: int = 40
    width: int = 480
    height: int = 280

    def validate(self) -> None:
        if self.kind not in {"column", "bar", "line", "pie"}:
            raise ValueError("Unsupported chart type")
        parse_range(self.source_range)
        if min(self.width, self.height) < 40 or max(self.width, self.height) > 4096:
            raise ValueError("Chart dimensions are outside supported bounds")


@dataclass
class SpreadsheetFeatureStore:
    tables: dict[str, StructuredTable] = field(default_factory=dict)
    named_ranges: dict[str, str] = field(default_factory=dict)
    conditional_rules: list[ConditionalRule] = field(default_factory=list)
    charts: list[ChartSpec] = field(default_factory=list)
    merged_ranges: list[str] = field(default_factory=list)
    hidden_rows: set[int] = field(default_factory=set)
    hidden_columns: set[int] = field(default_factory=set)
    filters: dict[str, list[str]] = field(default_factory=dict)

    def create_table(self, sheet: Any, range_ref: str, name: str | None = None, has_headers: bool = True) -> StructuredTable:
        top, left, bottom, right = parse_range(range_ref)
        if bottom <= top:
            raise ValueError("A table needs at least two rows")
        table_name = name or self._next_table_name()
        if table_name.casefold() in {item.casefold() for item in self.tables}:
            raise ValueError("Table name already exists")
        headers: list[str] = []
        for offset, col in enumerate(range(left, right + 1), 1):
            address = f"{column_label(col)}{top}"
            header = str(_raw(sheet, address)).strip() if has_headers else f"Column{offset}"
            header = header or f"Column{offset}"
            candidate = header
            suffix = 2
            while candidate in headers:
                candidate = f"{header}{suffix}"
                suffix += 1
            headers.append(candidate)
            if not has_headers:
                _write(sheet, address, candidate)
        table = StructuredTable(table_name, f"{column_label(left)}{top}:{column_label(right)}{bottom}", headers)
        table.validate()
        self.tables[table.name] = table
        return table

    def _next_table_name(self) -> str:
        index = 1
        while f"Table{index}" in self.tables:
            index += 1
        return f"Table{index}"

    def rename_table(self, old_name: str, new_name: str) -> None:
        table = self.tables.pop(old_name)
        if new_name in self.tables:
            self.tables[old_name] = table
            raise ValueError("Table name already exists")
        previous = table.name
        table.name = new_name
        try:
            table.validate()
        except Exception:
            table.name = previous
            self.tables[old_name] = table
            raise
        self.tables[new_name] = table

    def resize_table(self, name: str, range_ref: str) -> None:
        table = self.tables[name]
        old = table.range_ref
        table.range_ref = range_ref.upper()
        try:
            table.validate()
        except Exception:
            table.range_ref = old
            raise

    def column_values(self, sheet: Any, table_name: str, header: str, include_header: bool = False) -> list[Any]:
        table = self.tables[table_name]
        if header not in table.headers:
            raise KeyError(header)
        top, left, bottom, _ = parse_range(table.range_ref)
        col = left + table.headers.index(header)
        start = top if include_header else top + 1
        return [_raw(sheet, f"{column_label(col)}{row}") for row in range(start, bottom + 1)]

    def apply_table_filter(self, sheet: Any, table_name: str, header: str, allowed: Iterable[Any]) -> list[int]:
        table = self.tables[table_name]
        accepted = {str(value) for value in allowed}
        table.filters[header] = sorted(accepted)
        top, _, bottom, _ = parse_range(table.range_ref)
        values = self.column_values(sheet, table_name, header)
        return [row for row, value in zip(range(top + 1, bottom + 1), values) if str(value) in accepted]

    def clear_table_filter(self, table_name: str, header: str | None = None) -> None:
        table = self.tables[table_name]
        if header is None:
            table.filters.clear()
        else:
            table.filters.pop(header, None)

    def sort_table(self, sheet: Any, table_name: str, header: str, descending: bool = False) -> None:
        table = self.tables[table_name]
        top, left, bottom, right = parse_range(table.range_ref)
        key_col = left + table.headers.index(header)
        rows = [[_raw(sheet, f"{column_label(col)}{row}") for col in range(left, right + 1)] for row in range(top + 1, bottom + 1)]
        def key(row: list[Any]) -> tuple[int, Any]:
            value = row[key_col - left]
            numeric = _number(value)
            return (0, numeric) if numeric is not None else (1, str(value).casefold())
        rows.sort(key=key, reverse=descending)
        for row_number, values in zip(range(top + 1, bottom + 1), rows):
            for col, value in zip(range(left, right + 1), values):
                _write(sheet, f"{column_label(col)}{row_number}", value)

    def table_total(self, sheet: Any, table_name: str, header: str, operation: str) -> float:
        values = self.column_values(sheet, table_name, header)
        numbers = [number for value in values if (number := _number(value)) is not None]
        operation = operation.upper()
        if operation == "SUM": return sum(numbers)
        if operation == "AVERAGE": return sum(numbers) / len(numbers) if numbers else 0.0
        if operation == "COUNT": return float(len(numbers))
        if operation == "MIN": return min(numbers) if numbers else 0.0
        if operation == "MAX": return max(numbers) if numbers else 0.0
        raise ValueError("Unsupported total operation")

    def define_name(self, name: str, range_ref: str) -> None:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,63}", name) or _is_excel_cell_reference(name):
            raise ValueError("Invalid named range")
        parse_range(range_ref)
        self.named_ranges[name] = range_ref.upper()

    def resolve_reference(self, sheet: Any, reference: str) -> list[Any]:
        table_match = _TABLE_REF_RE.fullmatch(reference)
        if table_match:
            return self.column_values(sheet, table_match.group(1), table_match.group(2))
        if reference in self.named_ranges:
            reference = self.named_ranges[reference]
        return [_raw(sheet, address) for address in iter_range(reference)]

    def fill(self, sheet: Any, source_ref: str, target_ref: str) -> None:
        source = list(iter_range(source_ref))
        target = list(iter_range(target_ref))
        if not source or not target:
            return
        values = [_raw(sheet, address) for address in source]
        numeric = [_number(value) for value in values]
        step = numeric[1] - numeric[0] if len(numeric) >= 2 and all(item is not None for item in numeric[:2]) else None
        date_values: list[date] = []
        for value in values[:2]:
            try: date_values.append(date.fromisoformat(str(value)))
            except ValueError: break
        for index, address in enumerate(target):
            if step is not None:
                value = numeric[0] + step * index
                _write(sheet, address, int(value) if value.is_integer() else value)
            elif len(date_values) == 2:
                delta = date_values[1] - date_values[0]
                _write(sheet, address, (date_values[0] + delta * index).isoformat())
            else:
                _write(sheet, address, values[index % len(values)])

    def merge(self, sheet: Any, range_ref: str) -> None:
        addresses = list(iter_range(range_ref))
        populated = [address for address in addresses if str(_raw(sheet, address)) not in {"", "None"}]
        if len(populated) > 1:
            raise ValueError("Merge refused because it would discard populated cells")
        normalized = f"{addresses[0]}:{addresses[-1]}"
        if normalized not in self.merged_ranges:
            self.merged_ranges.append(normalized)

    def unmerge(self, range_ref: str) -> None:
        addresses = list(iter_range(range_ref))
        normalized = f"{addresses[0]}:{addresses[-1]}"
        if normalized in self.merged_ranges:
            self.merged_ranges.remove(normalized)

    def add_chart(self, chart: ChartSpec) -> None:
        chart.validate()
        if any(item.name == chart.name for item in self.charts):
            raise ValueError("Chart name already exists")
        self.charts.append(chart)

    def chart_data(self, sheet: Any, name: str) -> list[list[Any]]:
        chart = next(item for item in self.charts if item.name == name)
        top, left, bottom, right = parse_range(chart.source_range)
        return [[_raw(sheet, f"{column_label(col)}{row}") for col in range(left, right + 1)] for row in range(top, bottom + 1)]

    def evaluate_function(self, name: str, args: list[Any]) -> Any:
        function = name.upper()
        flattened = list(_flatten(args))
        if function in {"SUMIF", "COUNTIF", "AVERAGEIF"}:
            if len(args) < 2:
                raise ValueError(f"{function} requires a range and criterion")
            candidates = list(_flatten([args[0]]))
            matches = [index for index, value in enumerate(candidates) if _criterion(value, args[1])]
            if function == "COUNTIF": return len(matches)
            sum_values = list(_flatten([args[2]])) if len(args) > 2 else candidates
            numbers = [_number(sum_values[index]) for index in matches if index < len(sum_values)]
            valid = [value for value in numbers if value is not None]
            if function == "SUMIF": return sum(valid)
            return sum(valid) / len(valid) if valid else 0
        if function == "IF": return args[1] if bool(args[0]) else (args[2] if len(args) > 2 else False)
        if function == "AND": return all(bool(value) for value in flattened)
        if function == "OR": return any(bool(value) for value in flattened)
        if function == "NOT": return not bool(flattened[0])
        text = str(flattened[0]) if flattened else ""
        if function == "LEFT": return text[: int(flattened[1]) if len(flattened) > 1 else 1]
        if function == "RIGHT": return text[-(int(flattened[1]) if len(flattened) > 1 else 1):]
        if function == "MID": return text[max(0, int(flattened[1]) - 1):][: int(flattened[2])]
        if function == "LEN": return len(text)
        if function in {"CONCAT", "CONCATENATE"}: return "".join(str(value) for value in flattened)
        if function == "UPPER": return text.upper()
        if function == "LOWER": return text.lower()
        if function == "TODAY": return date.today().isoformat()
        if function == "NOW": return datetime.now().replace(microsecond=0).isoformat(sep=" ")
        if function == "DATE": return date(int(flattened[0]), int(flattened[1]), int(flattened[2])).isoformat()
        parsed = date.fromisoformat(text)
        if function == "YEAR": return parsed.year
        if function == "MONTH": return parsed.month
        if function == "DAY": return parsed.day
        raise ValueError("Unsupported spreadsheet function")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "tables": {name: asdict(table) for name, table in sorted(self.tables.items())},
            "named_ranges": dict(sorted(self.named_ranges.items())),
            "conditional_rules": [asdict(rule) for rule in self.conditional_rules],
            "charts": [asdict(chart) for chart in self.charts],
            "merged_ranges": list(self.merged_ranges),
            "hidden_rows": sorted(self.hidden_rows),
            "hidden_columns": sorted(self.hidden_columns),
            "filters": {name: list(values) for name, values in sorted(self.filters.items())},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SpreadsheetFeatureStore":
        if not isinstance(payload, dict) or payload.get("schema", 1) != 1:
            raise ValueError("Unsupported spreadsheet feature schema")
        store = cls()
        for name, value in payload.get("tables", {}).items():
            table = StructuredTable(**value)
            table.validate()
            if name != table.name:
                raise ValueError("Table identity mismatch")
            store.tables[name] = table
        store.named_ranges = {str(name): str(value) for name, value in payload.get("named_ranges", {}).items()}
        store.conditional_rules = [ConditionalRule(**value) for value in payload.get("conditional_rules", [])]
        store.charts = [ChartSpec(**value) for value in payload.get("charts", [])]
        for chart in store.charts: chart.validate()
        store.merged_ranges = [str(value) for value in payload.get("merged_ranges", [])]
        store.hidden_rows = {int(value) for value in payload.get("hidden_rows", [])}
        store.hidden_columns = {int(value) for value in payload.get("hidden_columns", [])}
        store.filters = {str(name): [str(item) for item in values] for name, values in payload.get("filters", {}).items()}
        return store


def _flatten(values: Iterable[Any]) -> Iterable[Any]:
    for value in values:
        if isinstance(value, (list, tuple)):
            yield from _flatten(value)
        else:
            yield value


def _criterion(value: Any, criterion: Any) -> bool:
    match = _CRITERION_RE.fullmatch(str(criterion))
    operator, operand = match.groups() if match else ("=", str(criterion))
    operator = operator or "="
    left_number, right_number = _number(value), _number(operand)
    left: Any = left_number if left_number is not None and right_number is not None else str(value)
    right: Any = right_number if left_number is not None and right_number is not None else operand
    return {"=": left == right, "<>": left != right, "<": left < right, ">": left > right, "<=": left <= right, ">=": left >= right}[operator]


def install_workbook_feature_support(workbook_class: type) -> None:
    """Attach backward-compatible feature persistence to the native Workbook."""
    if getattr(workbook_class, "_office_features_installed", False):
        return

    def sheet_items(workbook: Any) -> list[tuple[str, Any]]:
        sheets = getattr(workbook, "sheets", {})
        if isinstance(sheets, dict):
            return [(str(name), sheet) for name, sheet in sheets.items()]
        return [(str(getattr(sheet, "name", index)), sheet) for index, sheet in enumerate(sheets)]

    def feature_store_for(workbook: Any, sheet: Any | None = None) -> SpreadsheetFeatureStore:
        if sheet is None:
            sheet = getattr(workbook, "current_sheet", None) or getattr(workbook, "active_sheet", None)
            if sheet is None:
                items = sheet_items(workbook)
                if not items:
                    raise ValueError("Workbook has no sheets")
                sheet = items[0][1]
        store = getattr(sheet, "_office_feature_store", None)
        if store is None:
            store = SpreadsheetFeatureStore()
            setattr(sheet, "_office_feature_store", store)
        return store

    original_to_dict = getattr(workbook_class, "to_dict", None)
    original_from_dict = getattr(workbook_class, "from_dict", None)
    if callable(original_to_dict):
        def to_dict(workbook: Any) -> dict[str, Any]:
            payload = original_to_dict(workbook)
            stores = {
                name: store.to_dict()
                for name, sheet in sheet_items(workbook)
                if (store := getattr(sheet, "_office_feature_store", None)) is not None
            }
            if stores:
                payload["office_features"] = stores
            return payload
        workbook_class.to_dict = to_dict

    if callable(original_from_dict):
        @classmethod
        def from_dict(cls: type, payload: dict[str, Any]) -> Any:
            base_payload = dict(payload)
            extension = base_payload.pop("office_features", {})
            workbook = original_from_dict(base_payload)
            lookup = dict(sheet_items(workbook))
            for name, value in extension.items():
                if name in lookup:
                    setattr(lookup[name], "_office_feature_store", SpreadsheetFeatureStore.from_dict(value))
            return workbook
        workbook_class.from_dict = from_dict

    workbook_class.office_features_for = feature_store_for
    workbook_class._office_features_installed = True


def install_sheets_frame_feature_ui(frame_class: type) -> None:
    """Add discoverable structured-table and chart commands to SheetsFrame."""
    if getattr(frame_class, "_office_feature_ui_installed", False):
        return
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk

    original_init = frame_class.__init__

    def active_grid(frame: Any) -> Any:
        index = int(frame.notebook.index("current"))
        return frame.grids[index]

    def selected_range(frame: Any) -> str:
        selection = active_grid(frame).selection
        top, left, bottom, right = parse_range(f"{selection.anchor}:{selection.active}")
        return f"{column_label(left)}{top}:{column_label(right)}{bottom}"

    def create_table_from_selection(frame: Any, name: str | None = None, has_headers: bool = True) -> StructuredTable | None:
        grid = active_grid(frame)
        try:
            table = frame.workbook.office_features_for(grid.model).create_table(grid.model, selected_range(frame), name=name, has_headers=has_headers)
        except (KeyError, TypeError, ValueError) as exc:
            frame.status_var.set(f"Table not created: {exc}")
            return None
        top, left, _, right = parse_range(table.range_ref)
        formats = getattr(grid.model, "cell_formats", None)
        if isinstance(formats, dict):
            for col in range(left, right + 1):
                formats.setdefault(f"{column_label(col)}{top}", {})["bold"] = True
        if hasattr(grid, "refresh"):
            grid.refresh()
        frame.dirty = True
        frame.status_var.set(f"Created {table.name} ({table.range_ref})")
        return table

    def prompt_create_table(frame: Any) -> None:
        name = simpledialog.askstring("Create Table", "Table name (leave blank for automatic):", parent=frame)
        if name is None:
            return
        has_headers = messagebox.askyesno("Create Table", "Does the selected range already contain headers?", parent=frame)
        create_table_from_selection(frame, name.strip() or None, has_headers)

    def create_chart_from_selection(frame: Any, name: str | None = None, kind: str = "column") -> ChartSpec | None:
        grid = active_grid(frame)
        store = frame.workbook.office_features_for(grid.model)
        chart_name = name or f"Chart{len(store.charts) + 1}"
        try:
            chart = ChartSpec(chart_name, kind, selected_range(frame), title=chart_name)
            store.add_chart(chart)
        except (TypeError, ValueError) as exc:
            frame.status_var.set(f"Chart not created: {exc}")
            return None
        frame.dirty = True
        frame.status_var.set(f"Created {chart.name} ({chart.kind})")
        return chart

    def prompt_create_chart(frame: Any) -> None:
        kind = simpledialog.askstring("Insert Chart", "Chart type: column, bar, line, or pie", initialvalue="column", parent=frame)
        if kind is None:
            return
        create_chart_from_selection(frame, kind=kind.strip().lower())

    def init(frame: Any, *args: Any, **kwargs: Any) -> None:
        original_init(frame, *args, **kwargs)
        children = frame.winfo_children()
        if children:
            toolbar = children[0]
            ttk.Button(toolbar, text="Create Table", command=lambda: prompt_create_table(frame)).pack(side=tk.LEFT, padx=3, pady=5)
            ttk.Button(toolbar, text="Insert Chart", command=lambda: prompt_create_chart(frame)).pack(side=tk.LEFT, padx=3, pady=5)
        frame.bind_all("<Control-t>", lambda _event: prompt_create_table(frame), add="+")

    frame_class.__init__ = init
    frame_class.create_table_from_selection = create_table_from_selection
    frame_class.create_chart_from_selection = create_chart_from_selection
    frame_class.selected_office_range = selected_range
    frame_class._office_feature_ui_installed = True
