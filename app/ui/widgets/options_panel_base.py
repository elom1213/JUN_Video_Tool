# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""포맷별 옵션 패널 베이스 + 팩토리 (PLAN 6.8)."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QWidget

from ...core.models import ConvertOptions, MediaInfo


class BaseOptionsPanel(QGroupBox):
    options_changed = Signal()

    def get_options(self) -> ConvertOptions:
        raise NotImplementedError

    def set_options(self, options: ConvertOptions) -> None:
        raise NotImplementedError

    def set_reference_info(self, info: MediaInfo | None) -> None:
        """선택 항목의 원본 정보 (락 계산 · 힌트용)."""


class OptionsPanelFactory:
    _panels: dict[str, type[BaseOptionsPanel]] = {}

    @classmethod
    def register(cls, format_id: str, panel_cls: type[BaseOptionsPanel]) -> None:
        cls._panels[format_id] = panel_cls

    @classmethod
    def create(cls, format_id: str, parent: QWidget | None = None) -> BaseOptionsPanel:
        panel_cls = cls._panels[format_id]
        return panel_cls(parent)

    @classmethod
    def has(cls, format_id: str) -> bool:
        return format_id in cls._panels
