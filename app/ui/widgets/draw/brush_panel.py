# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""브러시 패널 (PLAN_DRAW_TAB 5.6, 13.3): 색 스와치 · Custom 색 · 두께 · 지우개 크기."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QColorDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QToolButton, QVBoxLayout)

from ....config import constants as C


class BrushPanel(QGroupBox):
    brush_changed = Signal(str, float)   # color, width (소스 px)
    eraser_changed = Signal(float)       # 지름 (소스 px)

    def __init__(self, parent=None) -> None:
        super().__init__("Brush", parent)
        self._color = C.DRAW_COLOR_DEFAULT

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(6)
        lay.addWidget(QLabel("Color"))
        grid = QGridLayout()
        grid.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._swatches: list[QToolButton] = []
        for i, c in enumerate(C.DRAW_SWATCHES):
            b = QToolButton()
            b.setObjectName("Swatch")
            b.setCheckable(True)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(c)
            b.setStyleSheet(f"QToolButton#Swatch {{ background-color: {c}; }}")
            b.clicked.connect(lambda _c=False, col=c: self._pick(col))
            self._group.addButton(b)
            self._swatches.append(b)
            grid.addWidget(b, i // 4, i % 4)
        lay.addLayout(grid)
        row = QHBoxLayout()
        self.custom_btn = QPushButton("Custom…")
        self.custom_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.custom_btn.clicked.connect(self._custom)
        self.current = QLabel()
        self.current.setFixedSize(22, 22)
        self.current.setToolTip("Current color")
        row.addWidget(self.custom_btn, 1)
        row.addWidget(self.current)
        lay.addLayout(row)

        self.width_slider, self.width_label = self._slider_row(lay, "Width", int(C.DRAW_WIDTH_MIN),
                                                               int(C.DRAW_WIDTH_MAX), int(C.DRAW_WIDTH_DEFAULT))
        self.eraser_slider, self.eraser_label = self._slider_row(lay, "Eraser", int(C.DRAW_ERASER_MIN),
                                                                 int(C.DRAW_ERASER_MAX), int(C.DRAW_ERASER_DEFAULT))
        self.width_slider.valueChanged.connect(self._width_changed)
        self.eraser_slider.valueChanged.connect(self._eraser_changed)
        self._sync_color()

    @staticmethod
    def _slider_row(lay: QVBoxLayout, name: str, lo: int, hi: int, val: int) -> tuple[QSlider, QLabel]:
        row = QHBoxLayout()
        row.addWidget(QLabel(name))
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        s.setToolTip(f"{name} in source pixels")
        lab = QLabel(str(val))
        lab.setMinimumWidth(28)
        lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(s, 1)
        row.addWidget(lab)
        lay.addLayout(row)
        return s, lab

    # ------------------------------------------------------------------ API
    def color(self) -> str:
        return self._color

    def brush_width(self) -> float:
        return float(self.width_slider.value())

    def eraser_size(self) -> float:
        return float(self.eraser_slider.value())

    def set_state(self, color: str, width: float, eraser: float) -> None:
        if QColor(color).isValid():
            self._color = QColor(color).name()
        self.width_slider.setValue(int(round(width)))
        self.eraser_slider.setValue(int(round(eraser)))
        self._sync_color()
        self.brush_changed.emit(self._color, self.brush_width())
        self.eraser_changed.emit(self.eraser_size())

    # ------------------------------------------------------------------ 내부
    def _pick(self, color: str) -> None:
        self._color = color
        self._sync_color()
        self.brush_changed.emit(self._color, self.brush_width())

    def _custom(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, "Brush Color")
        if c.isValid():
            self._pick(c.name())

    def _sync_color(self) -> None:
        for b, c in zip(self._swatches, C.DRAW_SWATCHES):
            b.setChecked(c.lower() == self._color.lower())
        if not any(b.isChecked() for b in self._swatches):
            # 스와치에 없는 색 (Custom) → 그룹 선택 해제
            self._group.setExclusive(False)
            for b in self._swatches:
                b.setChecked(False)
            self._group.setExclusive(True)
        self.current.setStyleSheet(f"background-color: {self._color}; border: 1px solid #888888; border-radius: 3px;")

    def _width_changed(self, v: int) -> None:
        self.width_label.setText(str(v))
        self.brush_changed.emit(self._color, float(v))

    def _eraser_changed(self, v: int) -> None:
        self.eraser_label.setText(str(v))
        self.eraser_changed.emit(float(v))
