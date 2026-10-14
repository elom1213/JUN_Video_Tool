# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""로그 패널 (PLAN 6.10)."""
from __future__ import annotations

import html
from datetime import datetime

from PySide6.QtWidgets import QPlainTextEdit

from ...config import constants as C


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setObjectName("LogPanel")

    @staticmethod
    def _stamp() -> str:
        return datetime.now().strftime("[%H:%M:%S] ")

    def append(self, msg: str) -> None:
        self.appendHtml(f'<span style="color:{C.Colors.TEXT_DIM}">{html.escape(self._stamp())}</span>'
                        f'<span style="color:{C.Colors.TEXT}">{html.escape(msg)}</span>')

    def append_error(self, msg: str) -> None:
        self.appendHtml(f'<span style="color:{C.Colors.TEXT_DIM}">{html.escape(self._stamp())}</span>'
                        f'<span style="color:{C.Colors.FAIL}">{html.escape(msg)}</span>')

    def append_ok(self, msg: str) -> None:
        self.appendHtml(f'<span style="color:{C.Colors.TEXT_DIM}">{html.escape(self._stamp())}</span>'
                        f'<span style="color:{C.Colors.OK}">{html.escape(msg)}</span>')
