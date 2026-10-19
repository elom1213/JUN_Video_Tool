# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""WAV 옵션 패널 — 출력 규격(44.1 kHz · 16-bit · 모노)은 JUN_JALI 고정이라 채널 선택 · 길이 상한 · 검사만 고른다."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QLabel

from ...config import constants as C
from ...core.converters.wav_converter import WavOptions
from ...core.models import ConvertOptions, MediaInfo
from .options_panel_base import BaseOptionsPanel, OptionsPanelFactory

_CHANNELS = (("Mix all channels (recommended)", "mix"), ("Left channel only", "left"),
             ("Right channel only", "right"))


class WavOptionsPanel(BaseOptionsPanel):
    def __init__(self, parent=None) -> None:
        super().__init__("WAV Options (JUN_JALI)", parent)
        self._updating = False
        spec = QLabel(f"Output: {C.JALI_SAMPLE_RATE} Hz · 16-bit PCM · mono\n"
                      "The input format JUN_JALI (VisemeNet Converter) requires. "
                      "Works as a sound node in Maya as is.")
        spec.setObjectName("HintLabel")
        spec.setWordWrap(True)
        self.channels_combo = QComboBox()
        for text, mode in _CHANNELS:
            self.channels_combo.addItem(text, mode)
        self.channels_combo.setToolTip("VisemeNet reads one channel. Mixing keeps a centered voice; pick Left or "
                                       "Right when the voice is recorded on one side only.")
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(1.0, 3600.0)
        self.max_spin.setDecimals(0)
        self.max_spin.setSuffix(" s")
        self.max_spin.setValue(C.JALI_MAX_SECONDS)
        self.max_spin.setToolTip("Same as Max length in JUN_JALI (default 120 s). Longer results are flagged; "
                                 "trim the range or split the file.")
        self.check_box = QCheckBox("Check the output against JUN_JALI rules")
        self.check_box.setChecked(True)
        self.check_box.setToolTip("Re-reads each WAV after conversion: 44.1 kHz, 16-bit, length, silence, clipping.")
        self.source_label = QLabel()
        self.source_label.setObjectName("HintLabel")
        self.source_label.setWordWrap(True)

        g = QGridLayout(self)
        g.setContentsMargins(8, 12, 8, 8)
        g.addWidget(spec, 0, 0, 1, 2)
        g.addWidget(QLabel("Channels"), 1, 0)
        g.addWidget(self.channels_combo, 1, 1)
        g.addWidget(QLabel("Max length"), 2, 0)
        g.addWidget(self.max_spin, 2, 1)
        g.addWidget(self.check_box, 3, 0, 1, 2)
        g.addWidget(self.source_label, 4, 0, 1, 2)
        g.setColumnStretch(1, 1)

        self.channels_combo.currentIndexChanged.connect(lambda _i: self._emit())
        self.max_spin.valueChanged.connect(lambda _v: self._emit())
        self.check_box.toggled.connect(lambda _b: self._emit())
        for w in (self.channels_combo, self.max_spin):
            w.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.set_reference_info(None)

    def _emit(self) -> None:
        if not self._updating:
            self.options_changed.emit()

    def get_options(self) -> WavOptions:
        return WavOptions(channels=str(self.channels_combo.currentData()), max_seconds=float(self.max_spin.value()),
                          check_jali=self.check_box.isChecked())

    def set_options(self, options: ConvertOptions) -> None:
        if not isinstance(options, WavOptions):
            return
        self._updating = True
        self.channels_combo.setCurrentIndex(max(0, self.channels_combo.findData(options.channels)))
        self.max_spin.setValue(float(options.max_seconds))
        self.check_box.setChecked(bool(options.check_jali))
        self._updating = False

    def set_reference_info(self, info: MediaInfo | None) -> None:
        if info is None:
            self.source_label.setText("")
            self.source_label.hide()
            return
        if not info.has_audio:
            self.source_label.setText("Selected file has no audio stream - it will be skipped.")
        else:
            ch = {1: "mono", 2: "stereo"}.get(info.channels, f"{info.channels} ch" if info.channels else "? ch")
            rate = f"{info.sample_rate / 1000:g} kHz" if info.sample_rate else "? kHz"
            self.source_label.setText(f"Selected source audio: {rate} · {ch}")
        self.source_label.show()


OptionsPanelFactory.register("wav", WavOptionsPanel)
