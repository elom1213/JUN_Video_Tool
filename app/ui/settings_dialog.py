# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-26
"""설정 다이얼로그 (PLAN 6.12): 동시 변환 수 · 하드웨어 디코드 · 추정 on/off · 이미지 시퀀스 fps."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
                               QSpinBox, QVBoxLayout)

from ..config import constants as C
from ..config.settings import AppSettings
from .icons import app_icon


class SettingsDialog(QDialog):
    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setWindowIcon(app_icon())
        self._settings = settings

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, C.MAX_CONCURRENCY)
        self.concurrency_spin.setValue(settings.concurrency)
        self.concurrency_spin.setToolTip("Number of ffmpeg processes to run at the same time.")

        self.hwaccel_combo = QComboBox()
        self.hwaccel_combo.addItem("Auto (GPU decode if available)", "auto")
        self.hwaccel_combo.addItem("None (software decode)", "none")
        self.hwaccel_combo.setCurrentIndex(max(0, self.hwaccel_combo.findData(settings.hwaccel)))

        self.estimate_check = QCheckBox("Estimate output size with sample encodes")
        self.estimate_check.setChecked(settings.estimate_enabled)
        self.estimate_check.setToolTip("When off, only the quick rough estimate is shown.")

        self.sequence_fps_spin = QDoubleSpinBox()
        self.sequence_fps_spin.setRange(C.SEQUENCE_FPS_MIN, C.SEQUENCE_FPS_MAX)
        self.sequence_fps_spin.setDecimals(3)
        self.sequence_fps_spin.setSuffix(" fps")
        self.sequence_fps_spin.setValue(settings.sequence_fps)
        self.sequence_fps_spin.setToolTip("Frame rate for image sequences (img.001.jpg, img.002.jpg, ...).\n"
                                          "Applies to sequences added after the change; re-add a sequence to update it.")

        form = QFormLayout()
        form.addRow("Parallel conversions", self.concurrency_spin)
        form.addRow("Hardware decode", self.hwaccel_combo)
        form.addRow("", self.estimate_check)
        form.addRow("Image sequence FPS", self.sequence_fps_spin)

        note = QLabel("Changes apply to the next conversion.")
        note.setObjectName("HintLabel")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addLayout(form)
        v.addWidget(note)
        v.addWidget(buttons)

    def accept(self) -> None:
        self._settings.concurrency = self.concurrency_spin.value()
        self._settings.hwaccel = str(self.hwaccel_combo.currentData())
        self._settings.estimate_enabled = self.estimate_check.isChecked()
        self._settings.sequence_fps = self.sequence_fps_spin.value()
        self._settings.sync()
        super().accept()
