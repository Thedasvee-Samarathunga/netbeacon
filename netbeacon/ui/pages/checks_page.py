"""Manage checks: add, edit, duplicate, pause, delete."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QMenu, QMessageBox

from ..check_table import make_table
from ..widgets import HelpText, InfoBanner, PageHeader, make_button
from .base import Page


class ChecksPage(Page):
    key = "checks"
    title = "Checks"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        head = PageHeader("Checks", "Everything you've asked NetBeacon to watch. Double-click a check to edit it.")
        self.root.addWidget(head)
        self.root.addWidget(InfoBanner("monitors"))

        bar = QHBoxLayout()
        self.add_btn = make_button("+ Add a check", "primary")
        self.edit_btn = make_button("Edit")
        self.dup_btn = make_button("Duplicate")
        self.toggle_btn = make_button("Pause")
        self.del_btn = make_button("Delete", "danger")
        self.now_btn = make_button("Check everything now")
        for b in (self.add_btn, self.edit_btn, self.dup_btn, self.toggle_btn, self.del_btn):
            bar.addWidget(b)
        bar.addSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search...")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(260)
        self.group = QComboBox()
        bar.addWidget(self.search)
        bar.addWidget(self.group)
        bar.addStretch(1)
        bar.addWidget(self.now_btn)
        self.root.addLayout(bar)

        self.view, self.model, self.proxy = make_table(["status", "name", "type", "group", "target", "result", "response", "avail"])
        self.root.addWidget(self.view, 1)
        self.root.addWidget(HelpText("Tip: <b>Pause</b> a check while you do maintenance so it doesn't alarm anyone. "
                                     "Paused checks keep their history. <b>Duplicate</b> is the quickest way to add similar checks."))

        self.add_btn.clicked.connect(lambda: ctx.main_window.open_check_dialog())
        self.edit_btn.clicked.connect(self._edit)
        self.dup_btn.clicked.connect(self._duplicate)
        self.toggle_btn.clicked.connect(self._toggle)
        self.del_btn.clicked.connect(self._delete)
        self.now_btn.clicked.connect(ctx.core.check_now)
        self.view.doubleClicked.connect(self._edit)
        self.view.customContextMenuRequested.connect(self._menu)
        self.view.selectionModel().selectionChanged.connect(self._sel_changed)
        self.search.textChanged.connect(self._filters)
        self.group.currentIndexChanged.connect(self._filters)
        ctx.snapshot_changed.connect(self.on_snapshot)
        self._sel_changed()

    def on_snapshot(self, rows: list[dict]) -> None:
        sel = self._current_id()
        self.model.set_rows(rows)
        cur = self.group.currentData()
        self.group.blockSignals(True)
        self.group.clear()
        self.group.addItem("All groups", "")
        for g in sorted({r["group"] for r in rows}, key=str.lower):
            self.group.addItem(g, g)
        self.group.setCurrentIndex(max(0, self.group.findData(cur)))
        self.group.blockSignals(False)
        if sel:
            for r in range(self.proxy.rowCount()):
                if self.model.row_at(self.proxy.mapToSource(self.proxy.index(r, 0)).row())["id"] == sel:
                    self.view.selectRow(r)
                    break
        self._sel_changed()

    def _filters(self) -> None:
        self.proxy.set_filters(self.search.text(), self.group.currentData() or "")

    def _current(self):
        idx = self.view.currentIndex()
        return self.model.row_at(self.proxy.mapToSource(idx).row()) if idx.isValid() else None

    def _current_id(self) -> str:
        r = self._current()
        return r["id"] if r else ""

    def _sel_changed(self, *_a) -> None:
        r = self._current()
        for b in (self.edit_btn, self.dup_btn, self.toggle_btn, self.del_btn):
            b.setEnabled(r is not None)
        if r:
            self.toggle_btn.setText("Resume" if not r["enabled"] else "Pause")

    def _edit(self, *_a) -> None:
        if r := self._current():
            self.ctx.main_window.edit_check(r["id"])

    def _duplicate(self) -> None:
        if r := self._current():
            m = self.ctx.store.by_id(r["id"])
            if m:
                self.ctx.main_window.open_check_dialog(duplicate_of=m)

    def _toggle(self) -> None:
        if r := self._current():
            m = self.ctx.store.by_id(r["id"])
            if m:
                m.enabled = not m.enabled
                self.ctx.store.update(m)
                self.ctx.apply_changes()

    def _delete(self) -> None:
        r = self._current()
        if not r:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete check")
        box.setText(f"Delete '{r['name']}'?")
        box.setInformativeText("Its history (uptime, incidents) will be deleted too. If you only want to stop it for a while, use Pause instead.")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if box.exec() == QMessageBox.StandardButton.Yes:
            self.ctx.store.remove(r["id"])
            self.ctx.history.delete_monitor_data(r["name"])
            self.ctx.apply_changes()
            self.ctx.toast(f"Deleted '{r['name']}'.", "info")

    def _menu(self, pos) -> None:
        idx = self.view.indexAt(pos)
        if not idx.isValid():
            return
        self.view.selectRow(idx.row())
        r = self._current()
        m = QMenu(self)
        m.addAction("Edit...", self._edit)
        m.addAction("Duplicate...", self._duplicate)
        m.addAction("Resume" if not r["enabled"] else "Pause", self._toggle)
        m.addAction("View uptime and history", lambda: self.ctx.main_window.show_uptime_for(r["name"]))
        m.addAction("What's wrong with this?", lambda: self.ctx.main_window.diagnose(r["id"]))
        m.addSeparator()
        m.addAction("Delete...", self._delete)
        m.exec(self.view.viewport().mapToGlobal(pos))
