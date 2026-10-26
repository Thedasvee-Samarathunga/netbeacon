"""Add / edit a check. The right-hand side teaches while you fill in the form."""
from __future__ import annotations

import copy
from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from .. import config_writer, knowledge, netutil
from ..checks import CHECKS, CheckType, Field, checks_by_category
from ..store import MonitorDef, clean_name
from . import theme
from .context import AppContext
from .widgets import HelpText, Task, label, make_button

INTERVALS = [(0, "Every round (the global interval)"), (60, "Every minute"), (300, "Every 5 minutes"),
             (900, "Every 15 minutes"), (3600, "Every hour"), (86400, "Once a day")]


class PickerDialog(QDialog):
    """Pick one row from a list (used for 'choose a service / program')."""

    def __init__(self, parent, title: str, headers: list[str], rows: list[list[str]], key_col: int = 0) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 520)
        self.rows, self.key_col, self.chosen = rows, key_col, ""
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type to filter...")
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        self.table = QTableWidget(len(rows), len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for r, row in enumerate(rows):
            for c, v in enumerate(row):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.table.resizeColumnsToContents()
        self.table.doubleClicked.connect(self.accept)
        lay.addWidget(self.table)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _filter(self, text: str) -> None:
        t = text.lower()
        for r, row in enumerate(self.rows):
            self.table.setRowHidden(r, bool(t) and not any(t in v.lower() for v in row))

    def accept(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.chosen = self.rows[r][self.key_col]
        super().accept()


class MonitorDialog(QDialog):
    def __init__(self, ctx: AppContext, parent=None, *, kind: Optional[str] = None, params: Optional[dict] = None,
                 name: Optional[str] = None, edit: Optional[MonitorDef] = None, duplicate_of: Optional[MonitorDef] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.store = ctx.store
        self.edit = edit
        self.setWindowTitle("Edit check" if edit else "Add a check")
        self.setMinimumSize(900, 600)
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen().availableGeometry() if QGuiApplication.primaryScreen() else None
        self.resize(1100, min(860, (scr.height() - 80) if scr else 860))
        self._getters: dict[str, Callable[[], Any]] = {}
        self._setters: dict[str, Callable[[Any], None]] = {}
        self._kind: str = ""
        self._test_task: Optional[Task] = None
        self._initial = {"kind": kind, "params": params or {}, "name": name}
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._update_preview)

        root = QHBoxLayout(self)
        split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(split)

        # ---- left: type list
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.addWidget(label("1. What do you want to check?", "h2"))
        self.type_list = QListWidget()
        self.type_list.setMinimumWidth(270)
        self.type_list.setMaximumWidth(330)
        self.type_list.setSpacing(1)
        for cat, items in checks_by_category():
            head = QListWidgetItem(cat.upper())
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            f = QFont()
            f.setBold(True)
            f.setPointSizeF(8.5)
            head.setFont(f)
            head.setForeground(QColor(theme.palette()["muted"]))
            self.type_list.addItem(head)
            for ct in items:
                it = QListWidgetItem("   " + ct.title)
                it.setData(Qt.ItemDataRole.UserRole, ct.key)
                self.type_list.addItem(it)
        self.type_list.currentItemChanged.connect(self._on_type_selected)
        ll.addWidget(self.type_list, 1)
        split.addWidget(left)

        # ---- right: scrollable form
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 0, 0, 0)
        self.title = label("", "h2")
        self.summary = label("", "muted", wrap=True)
        rl.addWidget(self.title)
        rl.addWidget(self.summary)

        self.learn = QTabWidget()
        self.learn.setMaximumHeight(170)
        self.what_view, self.why_view, self.how_view = QTextBrowser(), QTextBrowser(), QTextBrowser()
        for v in (self.what_view, self.why_view, self.how_view):
            v.setOpenExternalLinks(True)
            v.document().setDefaultStyleSheet(theme.html_css(theme._current))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 9))
        self.preview.setMaximumHeight(90)
        how_tab = QWidget()
        hl = QVBoxLayout(how_tab)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.how_view, 1)
        hl.addWidget(label("What NetBeacon hands to SimpleMonitor (monitors.ini):", "muted"))
        hl.addWidget(self.preview)
        self.learn.addTab(self.what_view, "What is this?")
        self.learn.addTab(self.why_view, "Why use it?")
        self.learn.addTab(how_tab, "Under the hood")
        rl.addWidget(self.learn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_host = QWidget()
        self.form_layout = QVBoxLayout(form_host)
        self.form_layout.setContentsMargins(0, 4, 8, 4)
        self.form_layout.setSpacing(10)
        scroll.setWidget(form_host)
        rl.addWidget(scroll, 1)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("A friendly name, e.g. Office router")
        self.name_edit.textEdited.connect(self._mark_touched)
        self.name_edit.textChanged.connect(self._schedule_preview)
        self.fields_box = QWidget()
        self.fields_layout = QFormLayout(self.fields_box)
        self.fields_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.fields_layout.setContentsMargins(0, 0, 0, 0)
        self.fields_layout.setVerticalSpacing(8)
        self.form_layout.addWidget(label("2. Fill in the details", "h2"))
        self.form_layout.addWidget(self.fields_box)

        self.adv_toggle = make_button("Show advanced options: tolerance, dependencies, groups, notes...", "link")
        self.adv_toggle.clicked.connect(self._toggle_adv)
        self.form_layout.addWidget(self.adv_toggle)
        self.adv_box = QWidget()
        self._build_advanced(self.adv_box)
        self.adv_box.setVisible(False)
        self.form_layout.addWidget(self.adv_box)
        self.form_layout.addStretch(1)

        # test + buttons
        test_row = QHBoxLayout()
        self.test_btn = make_button("Test this check now")
        self.test_btn.clicked.connect(self._test_now)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        self.test_result.setTextFormat(Qt.TextFormat.RichText)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)
        rl.addLayout(test_row)
        self.problem_label = QLabel("")
        self.problem_label.setStyleSheet("color:#dc2626;")
        self.problem_label.setWordWrap(True)
        rl.addWidget(self.problem_label)
        bb = QDialogButtonBox()
        self.save_btn = bb.addButton("Save check", QDialogButtonBox.ButtonRole.AcceptRole)
        self.save_btn.setProperty("kind", "primary")
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        rl.addWidget(bb)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([290, 780])

        # ---- initial state
        if edit:
            self._select_kind(edit.kind)
            self.type_list.setEnabled(False)
            self._fill_from(edit)
        elif duplicate_of:
            self._select_kind(duplicate_of.kind)
            self._fill_from(duplicate_of)
            self.name_edit.setText(self.store.unique_name(duplicate_of.name + " copy"))
        else:
            self._select_kind(kind or "ping")
            if params:
                self._set_params(params)
            if name:
                self._name_touched = True
                self.name_edit.setText(name)
        self._update_preview()

    # ------------------------------------------------------------------ advanced
    def _build_advanced(self, host: QWidget) -> None:
        lay = QFormLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setVerticalSpacing(8)
        self.interval_combo = QComboBox()
        for secs, text in INTERVALS:
            self.interval_combo.addItem(text, secs)
        lay.addRow("Check this", self._with_help(self.interval_combo, knowledge.TERM_HELP["interval"]))

        self.tol_spin = QSpinBox()
        self.tol_spin.setRange(0, 50)
        self.tol_spin.setSuffix(" extra failed checks")
        self.tol_note = HelpText("")
        self.tol_spin.valueChanged.connect(self._tol_changed)
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(2)
        wl.addWidget(self.tol_spin)
        wl.addWidget(HelpText(knowledge.TERM_HELP["tolerance"]))
        wl.addWidget(self.tol_note)
        lay.addRow("Forgive", w)

        self.dep_list = QListWidget()
        self.dep_list.setMaximumHeight(120)
        lay.addRow("Depends on", self._with_help(self.dep_list, knowledge.TERM_HELP["depends"]))

        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.group_combo.addItems(sorted({"General", "Internet", "Office", "Servers", "Websites", *self.store.groups()}, key=str.lower))
        lay.addRow("Group", self._with_help(self.group_combo, knowledge.TERM_HELP["group"]))

        self.notify_chk = QCheckBox("Send alerts for this check")
        self.notify_chk.setChecked(True)
        self.urgent_chk = QCheckBox("Urgent (use every alert channel)")
        self.urgent_chk.setChecked(True)
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.addWidget(self.notify_chk)
        bl.addWidget(self.urgent_chk)
        bl.addWidget(HelpText(knowledge.TERM_HELP["urgent"]))
        lay.addRow("Alerts", box)

        self.remind_spin = QSpinBox()
        self.remind_spin.setRange(0, 10080)
        self.remind_spin.setSuffix(" minutes (0 = never)")
        lay.addRow("Remind me every", self._with_help(self.remind_spin, knowledge.TERM_HELP["remind"]))

        self.doc_edit = QPlainTextEdit()
        self.doc_edit.setMaximumHeight(70)
        self.doc_edit.setPlaceholderText("e.g. Restart the switch in the comms cupboard, then call Sam on 555-0100.")
        lay.addRow("What to do if this fails", self._with_help(self.doc_edit, knowledge.TERM_HELP["failure_doc"]))

        self.recover_edit = QLineEdit()
        self.recover_edit.setPlaceholderText("e.g. net start Spooler   (advanced)")
        lay.addRow("Self-healing command", self._with_help(self.recover_edit, knowledge.TERM_HELP["recover"]))

        self.enabled_chk = QCheckBox("This check is switched on")
        self.enabled_chk.setChecked(True)
        lay.addRow("", self.enabled_chk)

        self.interval_combo.currentIndexChanged.connect(self._schedule_preview)
        self.tol_spin.valueChanged.connect(self._schedule_preview)
        self.group_combo.editTextChanged.connect(self._schedule_preview)
        self.dep_list.itemChanged.connect(self._schedule_preview)

    @staticmethod
    def _with_help(widget: QWidget, text: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(widget)
        if text:
            lay.addWidget(HelpText(text))
        return w

    def _toggle_adv(self) -> None:
        show = not self.adv_box.isVisible()
        self.adv_box.setVisible(show)
        self.adv_toggle.setText("Hide advanced options" if show else "Show advanced options: tolerance, dependencies, groups, notes...")

    def _tol_changed(self) -> None:
        interval = max(5, int(self.store.get("interval", 30)))
        n = self.tol_spin.value()
        if n == 0:
            self.tol_note.setText(f"Right now: the first failed check turns this red (within about {interval} seconds).")
        else:
            self.tol_note.setText(f"Right now: it must fail {n + 1} times in a row - about {(n + 1) * interval} seconds - before it turns red and alerts you. "
                                  "Until then it shows amber 'Retrying'.")

    # ------------------------------------------------------------------ type + fields
    def _select_kind(self, kind: str) -> None:
        for i in range(self.type_list.count()):
            it = self.type_list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == kind:
                self.type_list.setCurrentItem(it)
                return

    def _on_type_selected(self, current: Optional[QListWidgetItem], _prev) -> None:
        if current is None or current.data(Qt.ItemDataRole.UserRole) is None:
            return
        self._build_fields(current.data(Qt.ItemDataRole.UserRole))

    def _build_fields(self, kind: str) -> None:
        keep_name = self.name_edit.text()
        old_kind = self._kind
        self._kind = kind
        ct = CHECKS[kind]
        self.name_edit.setParent(None)          # removeRow() deletes child widgets - keep the name box alive
        while self.fields_layout.rowCount():
            self.fields_layout.removeRow(0)
        self._getters.clear()
        self._setters.clear()
        self.title.setText(ct.title)
        self.summary.setText(ct.summary + ("   (Windows only)" if ct.windows_only else ""))
        css = theme.html_css(theme._current)
        self.what_view.setHtml(f"<style>{css}</style>{ct.what}")
        tips = "".join(f"<li>{t}</li>" for t in ct.tips)
        self.why_view.setHtml(f"<style>{css}</style>{ct.why}" + (f"<p><b>Tips</b></p><ul>{tips}</ul>" if tips else ""))
        self.how_view.setHtml(f"<style>{css}</style>{ct.how}")

        self.name_edit.setText(keep_name)
        self.fields_layout.addRow("Name", self._with_help(self.name_edit, "How this check is called in the dashboard and in alerts."))
        for f in ct.fields:
            self._add_field(ct, f)
        # dependency list (everything except me)
        self._refresh_dep_lists(ct)
        self.test_btn.setEnabled(kind not in ("compound", "practice"))
        self.test_result.setText("")
        if not self.edit and not getattr(self, "_name_touched", False):
            self._maybe_autoname()
        self._tol_changed()
        self._schedule_preview()

    def _current_params(self, kind: str) -> dict:
        try:
            return {k: g() for k, g in self._getters.items()}
        except Exception:
            return {}

    def _maybe_autoname(self) -> None:
        if self.edit:
            return
        ct = CHECKS[self._kind]
        if not getattr(self, "_name_touched", False):
            self.name_edit.blockSignals(True)
            self.name_edit.setText(ct.default_name(self._current_params(self._kind)))
            self.name_edit.blockSignals(False)

    def _refresh_dep_lists(self, ct: CheckType) -> None:
        self.dep_list.clear()
        selected = set(self.edit.depends) if self.edit else set()
        for m in self.store.monitors:
            if self.edit and m.id == self.edit.id:
                continue
            it = QListWidgetItem(m.name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if m.id in selected else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, m.id)
            self.dep_list.addItem(it)

    def _add_field(self, ct: CheckType, f: Field) -> None:
        w: QWidget
        trigger = None
        if ct.key == "compound" and f.key == "monitors":
            lst = QListWidget()
            lst.setMaximumHeight(150)
            current = set(str(self.edit.params.get("monitors", "")).split(",")) if self.edit else set()
            for m in self.store.monitors:
                if self.edit and m.id == self.edit.id:
                    continue
                it = QListWidgetItem(m.name)
                it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Checked if m.id in current else Qt.CheckState.Unchecked)
                it.setData(Qt.ItemDataRole.UserRole, m.id)
                lst.addItem(it)
            lst.itemChanged.connect(self._schedule_preview)
            self._getters[f.key] = lambda l=lst: ",".join(l.item(i).data(Qt.ItemDataRole.UserRole) for i in range(l.count())
                                                          if l.item(i).checkState() == Qt.CheckState.Checked)

            def set_list(v, l=lst):
                ids = set(str(v).split(","))
                for i in range(l.count()):
                    l.item(i).setCheckState(Qt.CheckState.Checked if l.item(i).data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)

            self._setters[f.key] = set_list
            self.fields_layout.addRow(f.label, self._with_help(lst, f.help))
            return
        if f.kind == "int":
            sp = QSpinBox()
            sp.setRange(int(f.minimum if f.minimum is not None else 0), int(f.maximum if f.maximum is not None else 1_000_000))
            sp.setValue(int(f.default or 0))
            if f.suffix:
                sp.setSuffix(" " + f.suffix)
            sp.valueChanged.connect(self._schedule_preview)
            self._getters[f.key] = sp.value
            self._setters[f.key] = lambda v, s=sp: s.setValue(int(float(v)))
            trigger = sp.valueChanged
            w = sp
        elif f.kind == "float":
            ds = QDoubleSpinBox()
            ds.setDecimals(1)
            ds.setRange(float(f.minimum if f.minimum is not None else 0), float(f.maximum if f.maximum is not None else 1_000_000))
            ds.setValue(float(f.default or 0))
            if f.suffix:
                ds.setSuffix(" " + f.suffix)
            ds.valueChanged.connect(self._schedule_preview)
            self._getters[f.key] = ds.value
            self._setters[f.key] = lambda v, s=ds: s.setValue(float(v))
            w = ds
        elif f.kind == "choice":
            cb = QComboBox()
            for val, text in (f.choices or []):
                cb.addItem(text, val)
            idx = cb.findData(f.default)
            cb.setCurrentIndex(max(0, idx))
            cb.currentIndexChanged.connect(self._schedule_preview)
            self._getters[f.key] = lambda c=cb: c.currentData()
            self._setters[f.key] = lambda v, c=cb: c.setCurrentIndex(max(0, c.findData(v)))
            w = cb
        elif f.kind == "bool":
            ck = QCheckBox(f.label)
            ck.setChecked(bool(f.default))
            ck.toggled.connect(self._schedule_preview)
            self._getters[f.key] = ck.isChecked
            self._setters[f.key] = lambda v, c=ck: c.setChecked(v in (True, "1", 1, "true", "True"))
            self.fields_layout.addRow("", self._with_help(ck, f.help))
            return
        else:
            le = QLineEdit(str(f.default or ""))
            le.setPlaceholderText(f.placeholder)
            if f.kind == "password":
                le.setEchoMode(QLineEdit.EchoMode.Password)
            le.textChanged.connect(self._schedule_preview)
            self._getters[f.key] = lambda e=le: e.text().strip()
            self._setters[f.key] = lambda v, e=le: e.setText(str(v))
            trigger = le.textChanged
            w = le
            extra: Optional[QPushButton] = None
            if f.kind == "path":
                extra = make_button("Browse...")
                extra.clicked.connect(lambda _=False, e=le, k=ct.key: self._browse(e, k))
            elif ct.key == "service" and f.key == "service":
                extra = make_button("Pick from list...")
                extra.clicked.connect(self._pick_service)
            elif ct.key == "process" and f.key == "process_name":
                extra = make_button("Pick from list...")
                extra.clicked.connect(self._pick_process)
            if extra is not None:
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.addWidget(le, 1)
                rl.addWidget(extra)
                w = row
        if trigger is not None and f.key in ("host", "url", "record", "service", "process_name", "path", "pattern", "command", "port"):
            trigger.connect(self._maybe_autoname_if_untouched)
        self.fields_layout.addRow(f.label, self._with_help(w, f.help))

    def _maybe_autoname_if_untouched(self) -> None:
        if not self.edit and not getattr(self, "_name_touched", False):
            self._maybe_autoname()

    def _browse(self, edit: QLineEdit, kind: str) -> None:
        if kind == "disk":
            p = QFileDialog.getExistingDirectory(self, "Choose a drive or folder", edit.text() or "C:\\")
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choose a file", edit.text())
        if p:
            edit.setText(p)

    def _pick_service(self) -> None:
        rows = netutil.list_windows_services()
        if not rows:
            QMessageBox.information(self, "Windows services", "Windows services can only be listed when NetBeacon runs on Windows.")
            return
        dlg = PickerDialog(self, "Pick a Windows service", ["Name", "Display name", "Status"],
                           [[r["name"], r["display_name"], r["status"]] for r in sorted(rows, key=lambda r: r["display_name"].lower())])
        if dlg.exec() and dlg.chosen:
            self._setters["service"](dlg.chosen)

    def _pick_process(self) -> None:
        rows = netutil.list_processes()
        dlg = PickerDialog(self, "Pick a running program", ["Program", "Copies", "Memory (MB)"],
                           [[r["name"], str(r["count"]), f"{r['memory'] / 1024 ** 2:.0f}"] for r in rows])
        if dlg.exec() and dlg.chosen:
            self._setters["process_name"](dlg.chosen)

    # ------------------------------------------------------------------ data in/out
    def _set_params(self, params: dict) -> None:
        for k, v in params.items():
            if k in self._setters:
                self._setters[k](v)

    def _fill_from(self, m: MonitorDef) -> None:
        self._name_touched = True
        self.name_edit.setText(m.name)
        self._set_params(m.params)
        i = self.interval_combo.findData(m.interval)
        if i < 0:
            self.interval_combo.addItem(f"Every {m.interval} seconds", m.interval)
            i = self.interval_combo.count() - 1
        self.interval_combo.setCurrentIndex(i)
        self.tol_spin.setValue(m.tolerance)
        self.group_combo.setCurrentText(m.group)
        self.notify_chk.setChecked(m.notify)
        self.urgent_chk.setChecked(m.urgent)
        self.remind_spin.setValue(m.remind)
        self.doc_edit.setPlainText(m.failure_doc)
        self.recover_edit.setText(m.recover_command)
        self.enabled_chk.setChecked(m.enabled)
        self._tol_changed()
        if m.tolerance or m.depends or m.failure_doc or m.remind or m.recover_command or m.interval:
            self._toggle_adv()

    def _build_def(self) -> MonitorDef:
        params = {k: g() for k, g in self._getters.items()}
        base = self.edit
        m = MonitorDef(id=base.id if base else MonitorDef.new(self._kind, "x", {}).id, name=clean_name(self.name_edit.text()),
                       kind=self._kind, params=params)
        if base:
            m.created = base.created
        m.enabled = self.enabled_chk.isChecked()
        m.group = self.group_combo.currentText().strip() or "General"
        m.interval = int(self.interval_combo.currentData() or 0)
        m.tolerance = self.tol_spin.value()
        m.depends = [self.dep_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.dep_list.count())
                     if self.dep_list.item(i).checkState() == Qt.CheckState.Checked]
        m.urgent = self.urgent_chk.isChecked()
        m.notify = self.notify_chk.isChecked()
        m.remind = self.remind_spin.value()
        m.failure_doc = self.doc_edit.toPlainText().strip()
        m.recover_command = self.recover_edit.text().strip()
        return m

    def _problems(self, m: MonitorDef) -> list[str]:
        out: list[str] = []
        if not m.name:
            out.append("Please give the check a name.")
        out.extend(CHECKS[m.kind].validate(m.params))
        if m.kind == "compound" and len([i for i in str(m.params.get("monitors", "")).split(",") if i]) < 2:
            out.append("Pick at least two checks to combine.")
        if m.depends and self.store.would_cycle(m.id, m.depends):
            out.append("These dependencies would create a loop (A waits for B, B waits for A).")
        return out

    # ------------------------------------------------------------------ preview + test
    def _schedule_preview(self, *_a) -> None:
        self._preview_timer.start()

    def _update_preview(self) -> None:
        if not self._kind:
            return
        try:
            m = self._build_def()
            if not m.name:
                m.name = "Unnamed"
            self.preview.setPlainText(self.ctx.preview(m))
        except Exception as exc:  # pragma: no cover
            self.preview.setPlainText(f"; {exc}")

    def _test_now(self) -> None:
        m = self._build_def()
        problems = self._problems(m)
        if problems:
            self.test_result.setText(f"<span style='color:#dc2626'>{problems[0]}</span>")
            return
        ids = {x.id: x.name for x in self.store.monitors}
        ids[m.id] = m.name
        self.test_btn.setEnabled(False)
        self.test_result.setText("Testing...")

        def work(_task: Task):
            typ, opts = config_writer.monitor_options(m, ids)
            from simplemonitor.Monitors.monitor import get_class
            mon = get_class(typ)(m.name, dict(opts))
            mon.run_test()
            return mon.error_count == 0, mon.get_result(), getattr(mon, "response_ms", None)

        self._test_task = Task(work, self)
        self._test_task.result.connect(self._test_done)
        self._test_task.failed.connect(self._test_failed)
        self._test_task.start()

    def _test_done(self, res) -> None:
        ok, msg, ms = res
        self.test_btn.setEnabled(True)
        color = "#16a34a" if ok else "#dc2626"
        word = "Works" if ok else "Failed"
        self.test_result.setText(f"<b style='color:{color}'>{word}.</b> {msg or ''}")

    def _test_failed(self, msg: str) -> None:
        self.test_btn.setEnabled(True)
        self.test_result.setText(f"<span style='color:#dc2626'>Could not run the test: {msg}</span>")

    # ------------------------------------------------------------------ save
    def _save(self) -> None:
        m = self._build_def()
        problems = self._problems(m)
        if problems:
            self.problem_label.setText(problems[0])
            return
        self.problem_label.setText("")
        if self.edit:
            old_name = self.edit.name
            self.store.update(m)
            if old_name != m.name:
                self.ctx.history.rename_monitor(old_name, m.name)
        else:
            self.store.add(m)
        self.ctx.apply_changes()
        self.ctx.toast(f"Saved check '{m.name}'.", "ok")
        self.accept()

    def done(self, r: int) -> None:
        if self._test_task and self._test_task.isRunning():
            self._test_task.wait(3000)
        super().done(r)

    def _mark_touched(self, _t: str) -> None:
        self._name_touched = True
