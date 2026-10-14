# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""GIF 옵션 패널 (PLAN 6.8) — 공통 패널 + Loop."""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QSpinBox

from ...config.constants import gif_params_for_quality
from ...core.converters.common import VideoOptions
from ...core.converters.gif_converter import GifOptions, resolve_fps
from .common_options_panel import CommonOptionsPanel
from .options_panel_base import OptionsPanelFactory


class GifOptionsPanel(CommonOptionsPanel):
    title = "GIF Options"
    options_cls = GifOptions
    fps_auto_label = "Auto (from quality)"
    fps_custom_default = 15.0

    def _add_extra_rows(self, g: QGridLayout, row: int) -> int:
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(0, 100)
        self.loop_spin.setToolTip("0 = infinite")
        g.addWidget(QLabel("Loop"), row, 0)
        loop_row = QHBoxLayout()
        loop_row.addWidget(self.loop_spin)
        loop_row.addWidget(QLabel("(0 = infinite)"))
        loop_row.addStretch(1)
        g.addLayout(loop_row, row, 1, 1, 2)
        self.loop_spin.valueChanged.connect(lambda _: self._emit())
        return row + 1

    def _hint_text(self, opts: VideoOptions, fps: float) -> str:
        p = gif_params_for_quality(opts.quality, self._ref_fps)
        if opts.fps_mode == "auto":
            return f"{fps:g} fps · {p.max_colors} colors · {p.dither_family}"
        return f"{p.max_colors} colors · {p.dither_family}"

    def _resolve_fps(self, opts: VideoOptions, src_fps: float) -> float:
        return resolve_fps(opts, src_fps)

    def _extra_kwargs(self) -> dict:
        return {"loop": self.loop_spin.value()}

    def _apply_extra(self, options: VideoOptions) -> None:
        if isinstance(options, GifOptions):
            self.loop_spin.setValue(int(options.loop))


OptionsPanelFactory.register("gif", GifOptionsPanel)
