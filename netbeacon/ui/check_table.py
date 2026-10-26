"""The table of checks used on the Dashboard and the Checks page."""
from __future__ import annotations

import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from .. import netutil
from . import theme
from .widgets import ROLE_BARS, ROLE_SORT, ROLE_STATUS, BarsDelegate, StatusDelegate

PRIORITY = {"down": 0, "error": 1, "retry": 2, "skipped": 3, "pending": 4, "up": 5, "paused": 6}

ALL_COLUMNS = {
    "status": "Status", "name": "Check", "type": "Type", "group": "Group", "target": "Target", "result": "Latest result",
    "response": "Response", "avail": "24 h", "bars": "Recent results", "since": "Up for", "last": "Last check",
}


class CheckModel(QAbstractTableModel):
    def __init__(self, columns: list[str]) -> None:
        super().__init__()
        self.columns = columns
        self.rows: list[dict] = []

    def set_rows(self, rows: list[dict]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return ALL_COLUMNS[self.columns[section]]
        return None

    def row_at(self, row: int) -> dict:
        return self.rows[row]

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        r = self.rows[index.row()]
        col = self.columns[index.column()]
        status = r["status"]
        if role == ROLE_STATUS:
            return status
        if role == ROLE_BARS:
            return r.get("bars", [])
        if role == ROLE_SORT:
            if col == "status":
                return PRIORITY.get(status, 9)
            if col == "response":
                return r["response_ms"] if r["response_ms"] is not None else 1e12
            if col == "avail":
                return r["avail"] if r.get("avail") is not None else -1
            if col == "last":
                return r["last_check"] or 0
            if col == "since":
                return r["since"] or 0
            return str(self._text(r, col)).lower()
        if role == Qt.ItemDataRole.DisplayRole:
            return "" if col in ("status", "bars") else self._text(r, col)
        if role == Qt.ItemDataRole.ToolTipRole:
            parts = [f"<b>{r['name']}</b>"]
            if r.get("description"):
                parts.append(r["description"])
            if r["message"]:
                parts.append(f"Latest: {r['message']}")
            if status == "retry":
                parts.append(f"Failing, but within the tolerance of {r['tolerance']} - not yet called down.")
            return "<br>".join(parts)
        if role == Qt.ItemDataRole.ForegroundRole:
            if status == "paused":
                return QColor(theme.palette()["muted"])
            if col == "result" and status in ("down", "error"):
                return QColor(theme.STATUS_COLORS[status])
        if role == Qt.ItemDataRole.TextAlignmentRole and col in ("response", "avail", "since", "last"):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    @staticmethod
    def _text(r: dict, col: str) -> str:
        if col == "name":
            return r["name"]
        if col == "type":
            return r["title"]
        if col == "group":
            return r["group"]
        if col == "target":
            return r["target"]
        if col == "result":
            return r["message"] or ("" if r["status"] != "paused" else "Paused")
        if col == "response":
            return f"{r['response_ms']:.0f} ms" if r["response_ms"] is not None else "-"
        if col == "avail":
            a = r.get("avail")
            return f"{a:.2f}%" if a is not None else "-"
        if col == "since":
            return netutil.format_duration(r["since"]) if r["since"] else "-"
        if col == "last":
            if not r["last_check"]:
                return "-"
            ago = time.time() - r["last_check"]
            return "just now" if ago < 5 else f"{netutil.format_duration(ago)} ago"
        return ""


class CheckProxy(QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.setSortRole(ROLE_SORT)
        self.text = ""
        self.group = ""
        self.status = ""

    def set_filters(self, text: str = "", group: str = "", status: str = "") -> None:
        self.text, self.group, self.status = text.lower().strip(), group, status
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent) -> bool:
        r = self.sourceModel().rows[row]
        if self.group and r["group"] != self.group:
            return False
        if self.status:
            if self.status == "problem" and r["status"] not in ("down", "error", "retry"):
                return False
            if self.status not in ("problem",) and r["status"] != self.status:
                return False
        if self.text and self.text not in f"{r['name']} {r['target']} {r['title']} {r['group']} {r['message']}".lower():
            return False
        return True


def make_table(columns: list[str]) -> tuple[QTableView, CheckModel, CheckProxy]:
    model = CheckModel(columns)
    proxy = CheckProxy()
    proxy.setSourceModel(model)
    view = QTableView()
    view.setModel(proxy)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSortingEnabled(True)
    view.setShowGrid(False)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(38)
    view.setWordWrap(False)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    h = view.horizontalHeader()
    h.setStretchLastSection(False)
    h.setSortIndicatorShown(False)
    h.setHighlightSections(False)
    for i, c in enumerate(columns):
        if c == "status":
            view.setItemDelegateForColumn(i, StatusDelegate(view))
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            view.setColumnWidth(i, 118)
        elif c == "bars":
            view.setItemDelegateForColumn(i, BarsDelegate(view))
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            view.setColumnWidth(i, 200)
        elif c == "result":
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        elif c in ("name", "target"):
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            view.setColumnWidth(i, 190 if c == "name" else 150)
        else:
            h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
            view.setColumnWidth(i, 85 if c in ("response", "avail", "since", "last", "group") else 150)
    h.setMinimumSectionSize(60)
    view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    return view, model, proxy
