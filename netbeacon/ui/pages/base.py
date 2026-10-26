"""Common page behaviour."""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..context import AppContext


class Page(QWidget):
    key = ""
    title = ""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.setObjectName("page")
        self.ctx = ctx
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 22, 28, 18)
        self.root.setSpacing(14)

    def on_show(self) -> None:
        """Called every time the page becomes visible."""

    def retheme(self) -> None:
        """Called after a theme change."""
