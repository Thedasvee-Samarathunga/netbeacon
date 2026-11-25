"""The 'What's wrong?' window: runs the step-by-step diagnosis and explains the result."""
from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .. import config_writer, diagnose
from ..store import MonitorDef
from .widgets import HelpText, Task, label, make_button

COLORS = {diagnose.OK: "#16a34a", diagnose.WARN: "#f59e0b", diagnose.FAIL: "#dc2626", diagnose.SKIP: "#94a3b8"}
WORDS = {diagnose.OK: "OK", diagnose.WARN: "Hmm", diagnose.FAIL: "Broken", diagnose.SKIP: "Skipped"}


def check_runner(store) -> Any:
    """Run one check exactly like the engine would: (ok, message)."""
    def run(m: MonitorDef) -> tuple[bool, str]:
        ids = {x.id: x.name for x in store.monitors}
        typ, opts = config_writer.monitor_options(m, ids)
        from simplemonitor.Monitors.monitor import get_class
        mon = get_class(typ)(m.name, dict(opts))
        mon.run_test()
        return mon.error_count == 0, mon.get_result() or ""
    return run


class StepRow(QFrame):
    def __init__(self, step: diagnose.Step) -> None:
        super().__init__()
        self.setObjectName("card")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        col = COLORS[step.status]
        pill = QLabel(WORDS[step.status])
        pill.setFixedWidth(70)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet(f"color:{col}; border:1px solid {col}; border-radius:10px; padding:2px 0; font-weight:700;")
        lay.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(f"<b>{step.title}</b>", rich=True))
        text.addWidget(label(step.detail, "muted", wrap=True))
        if step.teach:
            text.addWidget(HelpText(step.teach))
        lay.addLayout(text, 1)


class DiagnoseDialog(QDialog):
    def __init__(self, ctx, parent=None, check: Optional[MonitorDef] = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.check = check
        self.result: Optional[diagnose.Diagnosis] = None
        self._task: Optional[Task] = None
        self.setWindowTitle(f"What's wrong with '{check.name}'?" if check else "What's wrong?")
        self.resize(780, 720)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(label(self.windowTitle(), "h1"))
        lay.addWidget(HelpText("NetBeacon checks your connection step by step, from this PC outwards. The <b>first</b> step that breaks is "
                               "almost always the cause - everything after it fails <i>because</i> of it. Bigger tools call this "
                               "<b>root cause analysis</b>."))
        self.verdict = QFrame()
        self.verdict.setObjectName("banner")
        vl = QVBoxLayout(self.verdict)
        vl.setContentsMargins(16, 12, 16, 12)
        self.verdict_text = label("Checking, step by step...", wrap=True, rich=True)
        self.verdict_text.setStyleSheet("font-size:12.5pt; font-weight:650;")
        vl.addWidget(self.verdict_text)
        self.advice = label("", wrap=True, rich=True)
        vl.addWidget(self.advice)
        lay.addWidget(self.verdict)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        self.steps_lay = QVBoxLayout(host)
        self.steps_lay.setContentsMargins(0, 0, 6, 0)
        self.steps_lay.setSpacing(6)
        self.steps_lay.addStretch(1)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)
        row = QHBoxLayout()
        self.again = make_button("Run again")
        self.copy = make_button("Copy report")
        self.close_btn = make_button("Close", "primary")
        row.addWidget(self.again)
        row.addWidget(self.copy)
        row.addStretch(1)
        row.addWidget(self.close_btn)
        lay.addLayout(row)
        self.again.clicked.connect(lambda: self.start())
        self.copy.clicked.connect(lambda: self._copy())
        self.close_btn.clicked.connect(lambda: self.accept())
        self.start()

    def start(self) -> None:
        if self._task and self._task.isRunning():
            return
        while self.steps_lay.count() > 1:
            it = self.steps_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.verdict_text.setText("Checking, step by step...")
        self.verdict_text.setStyleSheet("font-size:12.5pt; font-weight:650;")
        self.advice.setText("")
        self.again.setEnabled(False)
        self.copy.setEnabled(False)
        probes = diagnose.Probes()
        if self.check is not None and self.check.kind not in ("compound", "practice"):
            probes.run_check = check_runner(self.ctx.store)
        check = self.check

        def work(t: Task):
            return diagnose.run(probes, check=check, on_step=t.emit_item, cancel=t.cancel_event)

        self._task = Task(work, self)
        self._task.item.connect(self._add_step)
        self._task.result.connect(self._done)
        self._task.failed.connect(self._failed)
        self._task.start()

    def _add_step(self, step: diagnose.Step) -> None:
        self.steps_lay.insertWidget(self.steps_lay.count() - 1, StepRow(step))

    def _done(self, d: diagnose.Diagnosis) -> None:
        self.result = d
        self.again.setEnabled(True)
        self.copy.setEnabled(True)
        col = COLORS[d.level]
        self.verdict_text.setText(d.verdict)
        self.verdict_text.setStyleSheet(f"font-size:12.5pt; font-weight:650; color:{col};")
        parts = ["<b>What to do</b><ol style='margin-top:2px'>" + "".join(f"<li>{a}</li>" for a in d.advice) + "</ol>"]
        if d.also:
            parts.append("<b>Also noticed</b><ul style='margin-top:2px'>" + "".join(f"<li>{a}</li>" for a in d.also) + "</ul>")
        self.advice.setText("".join(parts))
        router = next((s for s in d.steps if s.key == "router" and s.status == diagnose.OK), None)
        if router:
            self.ctx.store.set("last_gateway", router.detail.split(" ")[0])
        import time
        self.ctx.history.add_event(time.time(), "error" if d.culprit else "info", self.check.name if self.check else None,
                                   f"Diagnosis: {d.verdict}")

    def _failed(self, msg: str) -> None:
        self.again.setEnabled(True)
        self.verdict_text.setText(f"The diagnosis itself failed: {msg}")

    def _copy(self) -> None:
        if self.result:
            QGuiApplication.clipboard().setText(self.result.as_text())
            self.ctx.toast("Diagnosis copied - paste it into an email to your IT person or provider.", "ok")

    def done(self, r: int) -> None:
        if self._task and self._task.isRunning():
            # let it finish quietly in the background instead of freezing the window while a probe times out
            self._task.cancel()
            for sig in (self._task.item, self._task.result, self._task.failed):
                try:
                    sig.disconnect()
                except (RuntimeError, TypeError):
                    pass
            keeper = self.ctx.main_window or self.parent()
            if keeper is not None:
                self._task.setParent(keeper)
            else:
                self._task.wait(20000)
        super().done(r)
