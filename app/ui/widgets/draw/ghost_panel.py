# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""고스팅 패널 (PLAN_DRAW_TAB 5.6, 7장): 켜기 · 앞/뒤 범위 · 투명도."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSlider, QSpinBox, QWidget

from ....config import constants as C


class GhostPanel(QGroupBox):
    ghost_changed = Signal(bool, int, int, float)   # enabled, before, after, opacity (0.05 ~ 1.0)

    def __init__(self, parent=None) -> None:
        super().__init__("Ghosting", parent)
        self.enable = QCheckBox("Enable")
        self.enable.setChecked(True)
        self.enable.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.before = QSpinBox()
        self.after = QSpinBox()
        for sp, v, tip in ((self.before, C.GHOST_BEFORE_DEFAULT, "Previous frames shown as ghosts"),
                           (self.after, C.GHOST_AFTER_DEFAULT, "Next frames shown as ghosts")):
            sp.setRange(0, C.GHOST_SPAN_MAX)
            sp.setValue(v)
            sp.setToolTip(tip)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.setValue(int(round(C.GHOST_OPACITY_DEFAULT * 100)))
        self.opacity.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.opacity_label = QLabel()
        self.opacity_label.setMinimumWidth(36)
        self.opacity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        orow = QWidget()
        oh = QHBoxLayout(orow)
        oh.setContentsMargins(0, 0, 0, 0)
        oh.addWidget(self.opacity, 1)
        oh.addWidget(self.opacity_label)

        form = QFormLayout(self)
        form.setContentsMargins(8, 12, 8, 8)
        form.addRow(self.enable)
        form.addRow("Before", self.before)
        form.addRow("After", self.after)
        form.addRow("Opacity", orow)

        self.enable.toggled.connect(self._emit)
        self.before.valueChanged.connect(self._emit)
        self.after.valueChanged.connect(self._emit)
        self.opacity.valueChanged.connect(self._emit)
        self._sync_label()

    def state(self) -> tuple[bool, int, int, float]:
        return self.enable.isChecked(), self.before.value(), self.after.value(), self.opacity.value() / 100.0

    def set_state(self, enabled: bool, before: int, after: int, opacity: float) -> None:
        for w in (self.enable, self.before, self.after, self.opacity):
            w.blockSignals(True)
        self.enable.setChecked(bool(enabled))
        self.before.setValue(int(before))
        self.after.setValue(int(after))
        self.opacity.setValue(int(round(max(0.05, min(1.0, opacity)) * 100)))
        for w in (self.enable, self.before, self.after, self.opacity):
            w.blockSignals(False)
        self._emit()

    def toggle(self) -> None:
        self.enable.setChecked(not self.enable.isChecked())

    def _sync_label(self) -> None:
        self.opacity_label.setText(f"{self.opacity.value()}%")
        on = self.enable.isChecked()
        for w in (self.before, self.after, self.opacity):
            w.setEnabled(on)

    def _emit(self, *_args) -> None:
        self._sync_label()
        self.ghost_changed.emit(*self.state())
