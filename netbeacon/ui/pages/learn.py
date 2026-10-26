"""Lessons, glossary and guided practice."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLineEdit, QListWidget, QListWidgetItem,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ... import knowledge
from ...checks import CHECKS
from ...store import MonitorDef
from .. import theme
from ..widgets import InfoBanner, PageHeader, card_frame, label, make_button
from .base import Page


class LearnPage(Page):
    key = "learn"
    title = "Learn"

    def __init__(self, ctx) -> None:
        super().__init__(ctx)
        self.root.addWidget(PageHeader("Learn", "Network monitoring in plain English."))
        self.root.addWidget(InfoBanner("learn"))
        tabs = QTabWidget()
        self.root.addWidget(tabs, 1)

        # ---- lessons
        split = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setMaximumWidth(330)
        self.list.setMinimumWidth(250)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        read = set(ctx.store.get("lessons_read", []))
        for les in knowledge.LESSONS:
            it = QListWidgetItem(f"{les['title']}\n{les['minutes']} min read")
            it.setData(Qt.ItemDataRole.UserRole, les["id"])
            if les["id"] in read:
                f = it.font()
                it.setForeground(Qt.GlobalColor.gray)
            self.list.addItem(it)
        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        split.addWidget(self.list)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        tabs.addTab(split, "Lessons")
        self.list.currentRowChanged.connect(self._show_lesson)
        self.list.setCurrentRow(0)

        # ---- glossary
        g = QWidget()
        gl = QVBoxLayout(g)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the glossary...")
        self.search.setClearButtonEnabled(True)
        gl.addWidget(self.search)
        self.gtable = QTableWidget(len(knowledge.GLOSSARY), 2)
        self.gtable.setHorizontalHeaderLabels(["Term", "Meaning"])
        self.gtable.setAlternatingRowColors(True)
        self.gtable.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.gtable.verticalHeader().setVisible(False)
        self.gtable.setShowGrid(False)
        self.gtable.setWordWrap(True)
        self.gtable.horizontalHeader().setStretchLastSection(True)
        self.gtable.setColumnWidth(0, 190)
        for r, (k, v) in enumerate(sorted(knowledge.GLOSSARY.items())):
            a = QTableWidgetItem(k)
            f = a.font()
            f.setBold(True)
            a.setFont(f)
            self.gtable.setItem(r, 0, a)
            self.gtable.setItem(r, 1, QTableWidgetItem(v))
        self.gtable.resizeRowsToContents()
        gl.addWidget(self.gtable, 1)
        self.search.textChanged.connect(self._filter_glossary)
        tabs.addTab(g, "Glossary")

        # ---- practice
        p = QWidget()
        pl = QVBoxLayout(p)
        pl.setSpacing(12)
        pl.addWidget(label("Learn by doing - safe experiments", "h2"))
        self._practice_card(pl, "1. See an outage and a recovery",
                            "Creates a <b>practice check</b> that fails a few times and then recovers, all by itself. "
                            "Watch the Dashboard turn amber (retrying), then red (down), then green again; look at the Activity page for the events and the "
                            "Uptime page for the incident it recorded.", "Create the practice check", self._make_practice)
        self._practice_card(pl, "2. The internet trio",
                            "Adds three checks - your router, a public IP (1.1.1.1) and a DNS lookup - and makes the last two depend on the first. "
                            "Then, whenever something breaks, the pattern of red/green tells you <i>where</i>.", "Add the trio", self._make_trio)
        self._practice_card(pl, "3. Who is on my network?",
                            "Scan your network, give your important devices names, and mark everything you recognise as <b>known</b>.", "Open the device scanner",
                            lambda: ctx.goto("devices"))
        self._practice_card(pl, "4. Try a failure-tolerance experiment",
                            "Open any check, open <i>Advanced options</i>, set <b>Forgive</b> to 3, and pull a network cable (or pause Wi-Fi) for a few seconds. "
                            "Notice how it shows amber 'Retrying' and may recover without ever alerting you.", "Open the checks list", lambda: ctx.goto("checks"))
        pl.addStretch(1)
        tabs.addTab(p, "Practice")

    def _practice_card(self, lay: QVBoxLayout, title: str, text: str, btn: str, fn) -> None:
        f, fl = card_frame()
        fl.addWidget(label(title, "h2"))
        fl.addWidget(label(text, "muted", wrap=True, rich=True))
        b = make_button(btn, "primary")
        b.clicked.connect(fn)
        fl.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(f)

    def _show_lesson(self, row: int) -> None:
        if row < 0:
            return
        les = knowledge.LESSONS[row]
        self.view.document().setDefaultStyleSheet(theme.html_css(theme._current))
        self.view.setHtml(les["html"])
        read = list(self.ctx.store.get("lessons_read", []))
        if les["id"] not in read:
            read.append(les["id"])
            self.ctx.store.set("lessons_read", read)
            self.list.item(row).setForeground(Qt.GlobalColor.gray)

    def _filter_glossary(self, text: str) -> None:
        t = text.lower()
        for r in range(self.gtable.rowCount()):
            hay = (self.gtable.item(r, 0).text() + " " + self.gtable.item(r, 1).text()).lower()
            self.gtable.setRowHidden(r, bool(t) and t not in hay)

    def retheme(self) -> None:
        self._show_lesson(self.list.currentRow())

    # ---- practice actions
    def _make_practice(self) -> None:
        m = MonitorDef.new("practice", "Practice outage", {**CHECKS["practice"].defaults(), "interval": 4})
        m.group = "Practice"
        self.ctx.store.add(m)
        self.ctx.apply_changes()
        self.ctx.toast("Practice check created - open the Dashboard and watch!", "ok")
        self.ctx.goto("dashboard")

    def _make_trio(self) -> None:
        from ... import netutil
        gw = netutil.default_gateway() or "192.168.1.1"
        s = self.ctx.store
        router = s.add(MonitorDef.new("ping", "Router", {**CHECKS["ping"].defaults(), "host": gw}))
        router.group = "Internet"
        net = MonitorDef.new("ping", "Internet (1.1.1.1)", {**CHECKS["ping"].defaults(), "host": "1.1.1.1"})
        net.group, net.depends, net.tolerance = "Internet", [router.id], 1
        s.add(net)
        dns = MonitorDef.new("dns", "DNS lookup", {**CHECKS["dns"].defaults(), "record": "example.com"})
        dns.group, dns.depends, dns.tolerance = "Internet", [router.id], 1
        s.add(dns)
        s.update(router)
        self.ctx.apply_changes()
        self.ctx.toast("Added Router, Internet and DNS checks.", "ok")
        self.ctx.goto("dashboard")
