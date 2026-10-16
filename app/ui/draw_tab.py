# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""Draw 탭 (PLAN_DRAW_TAB 5장). P1 단계: 탭 공통 인터페이스만 가진 자리."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..config.settings import AppSettings
from .widgets.loaders import ThumbnailLoader
from .widgets.log_panel import LogPanel


class DrawTab(QWidget):
    view_mode_changed = Signal(str)
    title_changed = Signal()

    def __init__(self, settings: AppSettings, thumb_loader: ThumbnailLoader, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.thumb_loader = thumb_loader
        self._view_mode = "list"
        self.log = LogPanel()
        lay = QVBoxLayout(self)
        label = QLabel("Draw tab — coming soon")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(label, 1)
        lay.addWidget(self.log)

    def add_files(self) -> None:
        pass

    def add_folder(self) -> None:
        pass

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = mode

    def view_mode(self) -> str:
        return self._view_mode

    def set_ffmpeg_available(self, ok: bool) -> None:
        pass

    def reprobe_missing(self) -> None:
        pass

    def menu_actions(self) -> list[QAction | None]:
        return []

    def set_active(self, active: bool) -> None:
        pass

    def title_suffix(self) -> str:
        return ""

    def request_close(self) -> bool:
        return True

    def shutdown(self) -> None:
        pass

    def restore_settings(self) -> None:
        pass

    def save_settings(self) -> None:
        pass

    def log_panel(self) -> LogPanel:
        return self.log
