# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""GIF 옵션 패널 (PLAN 6.8)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QSpinBox, QToolButton, QWidget)

from ...config import constants as C
from ...config.constants import gif_params_for_quality
from ...core.converters.gif_converter import GifOptions, resolve_fps
from ...core.models import ConvertOptions, MediaInfo
from .options_panel_base import BaseOptionsPanel, OptionsPanelFactory

_FPS_MODES = (("Auto (from quality)", "auto"), ("Source", "source"), ("Custom", "custom"))


class GifOptionsPanel(BaseOptionsPanel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("GIF Options", parent)
        self._ref_aspect = 16 / 9
        self._ref_fps = 30.0
        self._anchor = "width"
        self._updating = False
        self._hwaccel = C.DEFAULT_HWACCEL

        # --- 크기 ---
        self.width_spin = QSpinBox()
        self.height_spin = QSpinBox()
        for sp in (self.width_spin, self.height_spin):
            sp.setRange(0, 8192)
            sp.setSpecialValueText("Source")
            sp.setValue(0)
            sp.setAccelerated(True)
        self.lock_btn = QToolButton()
        self.lock_btn.setCheckable(True)
        self.lock_btn.setChecked(True)
        self.lock_btn.setToolTip("Lock aspect ratio. The other axis follows each video's own ratio.")
        self.reset_btn = QPushButton("Reset to Source Size")

        # --- 품질 ---
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(1, 100)
        self.quality_slider.setValue(70)
        self.quality_label = QLabel("70")
        self.quality_label.setMinimumWidth(28)
        self.hint_label = QLabel()
        self.hint_label.setObjectName("HintLabel")
        self.hint_label.setWordWrap(True)

        # --- FPS ---
        self.fps_mode_combo = QComboBox()
        for text, _id in _FPS_MODES:
            self.fps_mode_combo.addItem(text, _id)
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1.0, 60.0)
        self.fps_spin.setDecimals(1)
        self.fps_spin.setSingleStep(1.0)
        self.fps_spin.setValue(15.0)
        self.fps_result_label = QLabel()
        self.fps_result_label.setObjectName("HintLabel")
        self.fps_result_label.setWordWrap(True)

        # --- 타깃 · 루프 ---
        self.target_check = QCheckBox("Target size")
        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0.1, 500.0)
        self.target_spin.setDecimals(1)
        self.target_spin.setValue(2.0)
        self.target_spin.setSuffix(" MB")
        self.target_spin.setEnabled(False)
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(0, 100)
        self.loop_spin.setToolTip("0 = infinite")

        # --- 레이아웃 ---
        g = QGridLayout(self)
        g.setContentsMargins(8, 8, 8, 8)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Width"))
        size_row.addWidget(self.width_spin, 1)
        size_row.addWidget(self.lock_btn)
        size_row.addWidget(QLabel("Height"))
        size_row.addWidget(self.height_spin, 1)
        g.addLayout(size_row, 0, 0, 1, 3)
        g.addWidget(self.reset_btn, 1, 0, 1, 3)

        g.addWidget(QLabel("Quality"), 2, 0)
        g.addWidget(self.quality_slider, 2, 1)
        g.addWidget(self.quality_label, 2, 2)
        g.addWidget(self.hint_label, 3, 1, 1, 2)

        fps_row = QHBoxLayout()
        fps_row.addWidget(self.fps_mode_combo, 1)
        fps_row.addWidget(self.fps_spin)
        g.addWidget(QLabel("FPS"), 4, 0)
        g.addLayout(fps_row, 4, 1, 1, 2)
        g.addWidget(self.fps_result_label, 5, 1, 1, 2)

        g.addWidget(self.target_check, 6, 0)
        g.addWidget(self.target_spin, 6, 1, 1, 2)
        g.addWidget(QLabel("Loop"), 7, 0)
        loop_row = QHBoxLayout()
        loop_row.addWidget(self.loop_spin)
        loop_row.addWidget(QLabel("(0 = infinite)"))
        loop_row.addStretch(1)
        g.addLayout(loop_row, 7, 1, 1, 2)

        # --- 시그널 ---
        self.width_spin.valueChanged.connect(self._width_changed)
        self.height_spin.valueChanged.connect(self._height_changed)
        self.lock_btn.toggled.connect(self._lock_toggled)
        self.reset_btn.clicked.connect(self._reset_size)
        self.quality_slider.valueChanged.connect(self._quality_changed)
        self.fps_mode_combo.currentIndexChanged.connect(self._fps_mode_changed)
        self.fps_spin.valueChanged.connect(lambda _: self._emit())
        self.target_check.toggled.connect(self._target_toggled)
        self.target_spin.valueChanged.connect(lambda _: self._emit())
        self.loop_spin.valueChanged.connect(lambda _: self._emit())

        self._lock_toggled(True)
        self._fps_mode_changed()
        self._update_hints()

    # ------------------------------------------------------------------ 내부 핸들러
    def _emit(self) -> None:
        if not self._updating:
            self._update_hints()
            self.options_changed.emit()

    def _width_changed(self, v: int) -> None:
        if self._updating:
            return
        self._anchor = "width"
        if self.lock_btn.isChecked():
            self._updating = True
            self.height_spin.setValue(0 if v == 0 else max(1, int(round(v / self._ref_aspect))))
            self._updating = False
        self._emit()

    def _height_changed(self, v: int) -> None:
        if self._updating:
            return
        self._anchor = "height"
        if self.lock_btn.isChecked():
            self._updating = True
            self.width_spin.setValue(0 if v == 0 else max(1, int(round(v * self._ref_aspect))))
            self._updating = False
        self._emit()

    def _lock_toggled(self, on: bool) -> None:
        self.lock_btn.setText("Lock" if on else "Free")
        if on:
            self._sync_locked_axis()
        self._emit()

    def _sync_locked_axis(self) -> None:
        self._updating = True
        if self._anchor == "width":
            w = self.width_spin.value()
            self.height_spin.setValue(0 if w == 0 else max(1, int(round(w / self._ref_aspect))))
        else:
            h = self.height_spin.value()
            self.width_spin.setValue(0 if h == 0 else max(1, int(round(h * self._ref_aspect))))
        self._updating = False

    def _reset_size(self) -> None:
        self._updating = True
        self.width_spin.setValue(0)
        self.height_spin.setValue(0)
        self._updating = False
        self._emit()

    def _quality_changed(self, v: int) -> None:
        self.quality_label.setText(str(v))
        self._emit()

    def _fps_mode_changed(self) -> None:
        mode = self.fps_mode_combo.currentData()
        self.fps_spin.setEnabled(mode == "custom")
        self._emit()

    def _target_toggled(self, on: bool) -> None:
        self.target_spin.setEnabled(on)
        self._emit()

    def _update_hints(self) -> None:
        opts = self.get_options()
        p = gif_params_for_quality(opts.quality, self._ref_fps)
        fps = resolve_fps(opts, self._ref_fps)
        fps_txt = f"{fps:g}"
        if opts.fps_mode == "auto":
            self.hint_label.setText(f"{fps_txt} fps · {p.max_colors} colors · {p.dither_family}")
        else:
            self.hint_label.setText(f"{p.max_colors} colors · {p.dither_family}")
        capped = opts.fps_mode == "custom" and opts.fps_custom > self._ref_fps + 1e-6
        if opts.fps_mode == "source":
            self.fps_result_label.setText(f"→ {fps_txt} fps (source)")
        elif capped:
            self.fps_result_label.setText(f"→ {fps_txt} fps (capped to source)")
        else:
            self.fps_result_label.setText(f"→ {fps_txt} fps")
        self.fps_result_label.setStyleSheet(f"color: {C.Colors.WARN};" if capped else "")

    # ------------------------------------------------------------------ 공개 API
    def set_hwaccel(self, value: str) -> None:
        self._hwaccel = value if value in ("auto", "none") else C.DEFAULT_HWACCEL

    def get_options(self) -> GifOptions:
        w = self.width_spin.value() or None
        h = self.height_spin.value() or None
        return GifOptions(
            width=w, height=h, lock_aspect=self.lock_btn.isChecked(), anchor=self._anchor,
            quality=self.quality_slider.value(),
            fps_mode=str(self.fps_mode_combo.currentData()), fps_custom=float(self.fps_spin.value()),
            loop=self.loop_spin.value(),
            target_size_mb=float(self.target_spin.value()) if self.target_check.isChecked() else None,
            hwaccel=self._hwaccel,
        )

    def set_options(self, options: ConvertOptions) -> None:
        if not isinstance(options, GifOptions):
            return
        self._updating = True
        try:
            self._anchor = options.anchor if options.anchor in ("width", "height") else "width"
            self.lock_btn.setChecked(bool(options.lock_aspect))
            self.lock_btn.setText("Lock" if options.lock_aspect else "Free")
            self.width_spin.setValue(int(options.width or 0))
            self.height_spin.setValue(int(options.height or 0))
            self.quality_slider.setValue(max(1, min(100, int(options.quality))))
            self.quality_label.setText(str(self.quality_slider.value()))
            idx = max(0, self.fps_mode_combo.findData(options.fps_mode))
            self.fps_mode_combo.setCurrentIndex(idx)
            self.fps_spin.setEnabled(options.fps_mode == "custom")
            self.fps_spin.setValue(float(options.fps_custom))
            self.target_check.setChecked(options.target_size_mb is not None)
            self.target_spin.setEnabled(options.target_size_mb is not None)
            if options.target_size_mb is not None:
                self.target_spin.setValue(float(options.target_size_mb))
            self.loop_spin.setValue(int(options.loop))
            self._hwaccel = options.hwaccel
        finally:
            self._updating = False
        self._update_hints()
        self.options_changed.emit()

    def set_reference_info(self, info: MediaInfo | None) -> None:
        self._ref_aspect = info.aspect if info else 16 / 9
        self._ref_fps = info.fps if info else 30.0
        if self.lock_btn.isChecked():
            self._sync_locked_axis()
        self._update_hints()


OptionsPanelFactory.register("gif", GifOptionsPanel)
