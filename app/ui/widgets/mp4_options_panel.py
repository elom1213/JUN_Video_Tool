# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""MP4 옵션 패널 — 공통 패널 + Preset · Audio."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QGridLayout, QLabel

from ...core.converters.common import VideoOptions
from ...core.converters.mp4_converter import PRESETS, Mp4Options, crf_for_quality, resolve_fps_mp4
from .common_options_panel import CommonOptionsPanel
from .options_panel_base import OptionsPanelFactory

_AUDIO = (("AAC 128 kbps (re-encode)", "aac"), ("Copy original", "copy"), ("No audio", "none"))


class Mp4OptionsPanel(CommonOptionsPanel):
    title = "MP4 Options (H.264)"
    options_cls = Mp4Options
    fps_auto_label = "Auto (keep source)"
    fps_custom_default = 30.0

    def _add_extra_rows(self, g: QGridLayout, row: int) -> int:
        self.preset_combo = QComboBox()
        for p in PRESETS:
            self.preset_combo.addItem(p, p)
        self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData("medium")))
        self.preset_combo.setToolTip("Slower presets give smaller files at the same quality.")
        self.audio_combo = QComboBox()
        for text, _id in _AUDIO:
            self.audio_combo.addItem(text, _id)
        g.addWidget(QLabel("Preset"), row, 0)
        g.addWidget(self.preset_combo, row, 1, 1, 2)
        g.addWidget(QLabel("Audio"), row + 1, 0)
        g.addWidget(self.audio_combo, row + 1, 1, 1, 2)
        self.preset_combo.currentIndexChanged.connect(lambda _: self._emit())
        self.audio_combo.currentIndexChanged.connect(lambda _: self._emit())
        return row + 2

    def _hint_text(self, opts: VideoOptions, fps: float) -> str:
        return f"CRF {crf_for_quality(opts.quality)} · x264 {getattr(opts, 'preset', 'medium')}"

    def _resolve_fps(self, opts: VideoOptions, src_fps: float) -> float:
        return resolve_fps_mp4(opts, src_fps)

    def _extra_kwargs(self) -> dict:
        return {"preset": str(self.preset_combo.currentData()), "audio": str(self.audio_combo.currentData())}

    def _apply_extra(self, options: VideoOptions) -> None:
        if isinstance(options, Mp4Options):
            self.preset_combo.setCurrentIndex(max(0, self.preset_combo.findData(options.preset)))
            self.audio_combo.setCurrentIndex(max(0, self.audio_combo.findData(options.audio)))


OptionsPanelFactory.register("mp4", Mp4OptionsPanel)
