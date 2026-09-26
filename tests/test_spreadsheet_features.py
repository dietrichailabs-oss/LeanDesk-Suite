from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from leandesk.spreadsheet_features import (
    ChartSpec,
    ConditionalRule,
    SpreadsheetFeatureStore,
    column_label,
    column_number,
    iter_range,
    parse_range,
)
from leandesk.sheets import WorkbookModel


class FakeSheet:
    def __init__(self):
        self.cells = {}

    def get_raw(self, address):
        return self.cells.get(address, "")

    def set_cell(self, address, value):
        self.cells[address] = value


def populated_sheet():
    sheet = FakeSheet()
    rows = [
        ("Name", "Amount", "Group"),
        ("Alpha", 30, "A"),
        ("Beta", 10, "B"),
        ("Gamma", 20, "A"),
    ]
    for row_number, row in enumerate(rows, 1):
        for col_number, value in enumerate(row, 1):
            sheet.set_cell(f"{column_label(col_number)}{row_number}", value)
    return sheet


@pytest.mark.parametrize("label,number", [("A", 1), ("Z", 26), ("AA", 27), ("XFD", 16384)])
def test_column_conversions(label, number):
    assert column_number(label) == number
    assert column_label(number) == label


def test_bounded_range_parser_normalizes_reverse_ranges():
    assert parse_range("C4:A1") == (1, 1, 4, 3)
    assert list(iter_range("A1:B2")) == ["A1", "B1", "A2", "B2"]
    with pytest.raises(ValueError):
        parse_range("A1:Z1000")


def test_create_table_headers_styles_and_unique_names():
    sheet = populated_sheet()
    store = SpreadsheetFeatureStore()
    table = store.create_table(sheet, "A1:C4")
    assert table.name == "Table1"
    assert table.headers == ["Name", "Amount", "Group"]
    assert table.banded_rows and table.style == "Medium2"
    with pytest.raises(ValueError):
        store.create_table(sheet, "A1:C4", name="Table1")


def test_generated_headers_and_rename_resize_validation():
    sheet = populated_sheet()
    store = SpreadsheetFeatureStore()
    table = store.create_table(sheet, "A1:C4", has_headers=False)
    assert sheet.cells["A1"] == "Column1"
    store.rename_table(table.name, "Sales_2026")
    store.resize_table("Sales_2026", "A1:C6")
    assert store.tables["Sales_2026"].range_ref == "A1:C6"
    with pytest.raises(ValueError):
        store.rename_table("Sales_2026", "A1")


def test_table_sort_filter_clear_and_totals():
    sheet = populated_sheet()
    store = SpreadsheetFeatureStore()
    store.create_table(sheet, "A1:C4", name="Sales")
    assert store.apply_table_filter(sheet, "Sales", "Group", ["A"]) == [2, 4]
    store.clear_table_filter("Sales", "Group")
    store.sort_table(sheet, "Sales", "Amount")
    assert [sheet.cells[f"B{row}"] for row in range(2, 5)] == [10, 20, 30]
    assert store.table_total(sheet, "Sales", "Amount", "SUM") == 60
    assert store.table_total(sheet, "Sales", "Amount", "AVERAGE") == 20


def test_named_and_structured_references():
    sheet = populated_sheet()
    store = SpreadsheetFeatureStore()
    store.create_table(sheet, "A1:C4", name="Sales")
    store.define_name("Amounts", "B2:B4")
    assert store.resolve_reference(sheet, "Amounts") == [30, 10, 20]
    assert store.resolve_reference(sheet, "Sales[Amount]") == [30, 10, 20]
    with pytest.raises(ValueError):
        store.define_name("A1", "B2:B4")


def test_fill_number_date_and_repeated_text_series():
    sheet = FakeSheet()
    store = SpreadsheetFeatureStore()
    sheet.cells.update({"A1": 2, "A2": 4})
    store.fill(sheet, "A1:A2", "B1:B5")
    assert [sheet.cells[f"B{row}"] for row in range(1, 6)] == [2, 4, 6, 8, 10]
    sheet.cells.update({"C1": "2026-01-01", "C2": "2026-01-08"})
    store.fill(sheet, "C1:C2", "D1:D3")
    assert sheet.cells["D3"] == "2026-01-15"
    sheet.cells["E1"] = "Ready"
    store.fill(sheet, "E1", "F1:F3")
    assert [sheet.cells[f"F{row}"] for row in range(1, 4)] == ["Ready"] * 3


def test_merge_refuses_data_loss_and_unmerge_is_reversible():
    sheet = FakeSheet()
    store = SpreadsheetFeatureStore()
    sheet.cells.update({"A1": "keep", "B1": "would be lost"})
    with pytest.raises(ValueError):
        store.merge(sheet, "A1:B1")
    sheet.cells["B1"] = ""
    store.merge(sheet, "A1:B1")
    assert store.merged_ranges == ["A1:B1"]
    store.unmerge("A1:B1")
    assert store.merged_ranges == []


@pytest.mark.parametrize(
    "rule,value,peers,expected",
    [
        (ConditionalRule("A1:A3", "greater_than", 5), 7, [], True),
        (ConditionalRule("A1:A3", "less_than", 5), 7, [], False),
        (ConditionalRule("A1:A3", "text_contains", "desk"), "LeanDesk", [], True),
        (ConditionalRule("A1:A3", "duplicate"), "x", ["x", "y", "x"], True),
    ],
)
def test_conditional_format_rules(rule, value, peers, expected):
    assert rule.matches(value, peers) is expected


def test_chart_data_tracks_live_source_and_geometry_bounds():
    sheet = populated_sheet()
    store = SpreadsheetFeatureStore()
    store.add_chart(ChartSpec("Revenue", "column", "A1:B4", title="Revenue"))
    assert store.chart_data(sheet, "Revenue")[2] == ["Beta", 10]
    sheet.cells["B3"] = 99
    assert store.chart_data(sheet, "Revenue")[2] == ["Beta", 99]
    with pytest.raises(ValueError):
        store.add_chart(ChartSpec("Bad", "radar", "A1:B4"))


@pytest.mark.parametrize(
    "name,args,expected",
    [
        ("SUMIF", [[1, 2, 3], ">1"], 5),
        ("COUNTIF", [["A", "B", "A"], "A"], 2),
        ("AVERAGEIF", [[1, 2, 3], ">1"], 2.5),
        ("IF", [True, "yes", "no"], "yes"),
        ("AND", [True, 1, "x"], True),
        ("OR", [False, 0, "x"], True),
        ("NOT", [False], True),
        ("LEFT", ["LeanDesk", 4], "Lean"),
        ("RIGHT", ["LeanDesk", 4], "Desk"),
        ("MID", ["LeanDesk", 5, 4], "Desk"),
        ("LEN", ["LeanDesk"], 8),
        ("CONCAT", ["Lean", "Desk"], "LeanDesk"),
        ("UPPER", ["LeanDesk"], "LEANDESK"),
        ("LOWER", ["LeanDesk"], "leandesk"),
        ("DATE", [2026, 9, 3], "2026-09-03"),
        ("YEAR", ["2026-09-03"], 2026),
        ("MONTH", ["2026-09-03"], 9),
        ("DAY", ["2026-09-03"], 3),
    ],
)
def test_common_safe_functions(name, args, expected):
    assert SpreadsheetFeatureStore().evaluate_function(name, args) == expected


def test_feature_store_persistence_round_trip():
    sheet = populated_sheet()
    store = SpreadsheetFeatureStore()
    store.create_table(sheet, "A1:C4", name="Sales")
    store.define_name("Amounts", "B2:B4")
    store.conditional_rules.append(ConditionalRule("B2:B4", "greater_than", 15))
    store.add_chart(ChartSpec("Revenue", "line", "A1:B4"))
    store.merged_ranges.append("E1:F1")
    store.hidden_rows.add(8)
    store.hidden_columns.add(5)
    restored = SpreadsheetFeatureStore.from_dict(store.to_dict())
    assert restored.to_dict() == store.to_dict()


def test_native_workbook_persists_office_feature_extension():
    workbook = WorkbookModel()
    sheet = workbook.sheets[0]
    sheet.cells.update({"A1": "Item", "B1": "Amount", "A2": "Desk", "B2": "12"})
    store = workbook.office_features_for(sheet)
    store.create_table(sheet, "A1:B2", name="Inventory")
    store.define_name("Amounts", "B2:B2")
    store.add_chart(ChartSpec("InventoryChart", "column", "A1:B2"))
    payload = workbook.to_dict()
    restored = WorkbookModel.from_dict(payload)
    restored_store = restored.office_features_for(restored.sheets[0])
    assert restored_store.to_dict() == store.to_dict()


def test_large_common_workload_is_bounded_and_deterministic():
    sheet = FakeSheet()
    store = SpreadsheetFeatureStore()
    for row in range(1, 101):
        for col in range(1, 101):
            sheet.cells[f"{column_label(col)}{row}"] = row * col
    assert len(list(iter_range("A1:CV100"))) == 10_000
    assert sum(store.resolve_reference(sheet, "A1:A100")) == 5050


def test_actual_sheets_gui_creates_table_and_chart_from_drag_selection(tmp_path):
    import os
    import tkinter as tk
    from leandesk.core import RecentFiles
    from leandesk.sheets import SelectionRange, SheetsFrame

    if os.name != "nt" and not os.environ.get("DISPLAY"):
        pytest.skip("GUI test requires an active display")
    root = tk.Tk()
    root.withdraw()
    try:
        frame = SheetsFrame(root, recent=RecentFiles(tmp_path / "recent.json"))
        grid = frame.grids[0]
        grid.model.cells.update({"A1": "Item", "B1": "Amount", "A2": "Desk", "B2": "12"})
        grid.selection = SelectionRange("B2", "A1")
        table = frame.create_table_from_selection(name="Inventory")
        chart = frame.create_chart_from_selection(name="InventoryChart", kind="bar")
        assert table.range_ref == "A1:B2"
        assert chart.source_range == "A1:B2"
        assert grid.model.cell_formats["A1"]["bold"] is True
        assert grid.model.cell_formats["B1"]["bold"] is True
        assert frame.dirty is True
        button_texts = [child.cget("text") for child in frame.winfo_children()[0].winfo_children() if "Button" in type(child).__name__]
        assert "Create Table" in button_texts
        assert "Insert Chart" in button_texts
        restored = WorkbookModel.from_dict(frame.workbook.to_dict())
        restored_store = restored.office_features_for(restored.sheets[0])
        assert "Inventory" in restored_store.tables
        assert restored_store.charts[0].name == "InventoryChart"
    finally:
        root.destroy()
