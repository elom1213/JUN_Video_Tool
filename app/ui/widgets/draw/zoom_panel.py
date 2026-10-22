# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-22
"""타임라인 확대 패널 (PLAN_DRAW_TAB 18장): 타임라인 양 끝에 보일 시작 · 끝 프레임 정수 입력,
캐시 구간으로 맞추기, 전체로 되돌리기.

표시만 한다. 확대 값의 주인은 DrawTab (set_timeline_zoom) 이고, 여기서 고치면 zoom_changed 로 알린다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout

from .geometry import normalize_zoom


class ZoomPanel(QGroupBox):
    zoom_changed = Signal(int, int)    # 스핀박스로 확대 구간을 바꿈 (lo, hi)
    fit_cache_clicked = Signal()       # 캐시 구간으로 확대
    reset_clicked = Signal()           # 전체로

    def __init__(self, parent=None) -> None:
        super().__init__("Timeline Zoom", parent)
        self._last = -1
        self.start_spin = QSpinBox()
        self.end_spin = QSpinBox()
        for sp, tip in ((self.start_spin, "Frame shown at the left end of the timeline"),
                        (self.end_spin, "Frame shown at the right end of the timeline")):
            sp.setKeyboardTracking(False)
            sp.setMinimumWidth(64)
            sp.setToolTip(tip)
        self.info = QLabel()
        self.info.setObjectName("HintLabel")
        self.fit_btn = QPushButton("Zoom to Cache Range")
        self.fit_btn.setToolTip("Show only the cache range on the timeline (Z)")
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Show the whole video on the timeline (Shift+Z)")
        for b in (self.fit_btn, self.reset_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(QLabel("Show"))
        row.addWidget(self.start_spin, 1)
        row.addWidget(QLabel("–"))
        row.addWidget(self.end_spin, 1)
        lay.addLayout(row)
        lay.addWidget(self.info)
        brow = QHBoxLayout()
        brow.setSpacing(4)
        brow.addWidget(self.fit_btn, 3)
        brow.addWidget(self.reset_btn, 2)
        lay.addLayout(brow)

        self.start_spin.valueChanged.connect(self._spin_changed)
        self.end_spin.valueChanged.connect(self._spin_changed)
        self.fit_btn.clicked.connect(self.fit_cache_clicked)
        self.reset_btn.clicked.connect(self.reset_clicked)
        self.set_bounds(-1)

    # ------------------------------------------------------------------ API
    def set_bounds(self, last: int) -> None:
        """영상 길이 (마지막 프레임 번호). -1 = 영상 없음 → 비활성."""
        self._last = int(last)
        has = last >= 1          # 프레임이 둘은 있어야 확대할 것이 있다
        for sp in (self.start_spin, self.end_spin):
            sp.blockSignals(True)
            sp.setRange(0, max(0, last))
            sp.setEnabled(has)
            sp.blockSignals(False)
        self.fit_btn.setEnabled(has)
        self.reset_btn.setEnabled(has)
        self.set_zoom(0, max(0, last))

    def zoom(self) -> tuple[int, int]:
        return self.start_spin.value(), self.end_spin.value()

    def set_zoom(self, lo: int, hi: int) -> None:
        """신호 없이 스핀박스만 맞춘다."""
        for sp, v in ((self.start_spin, lo), (self.end_spin, hi)):
            sp.blockSignals(True)
            sp.setValue(int(v))
            sp.blockSignals(False)
        self._update_info()

    def set_fit_enabled(self, enabled: bool) -> None:
        self.fit_btn.setEnabled(bool(enabled) and self._last >= 1)

    # ------------------------------------------------------------------ 내부
    def _spin_changed(self, _v: int) -> None:
        lo, hi = self.start_spin.value(), self.end_spin.value()
        if self.sender() is self.start_spin and lo >= hi:
            hi = lo + 1                  # 시작을 끝까지 올리면 끝이 한 칸 따라간다 (끝에 닿으면 normalize 가 시작을 물린다)
        elif self.sender() is self.end_spin and hi <= lo:
            lo = hi - 1
        lo, hi = normalize_zoom(lo, hi, self._last)
        self.set_zoom(lo, hi)
        self.zoom_changed.emit(lo, hi)

    def _update_info(self) -> None:
        if self._last < 1:
            self.info.setText("")
            self.info.hide()
            return
        lo, hi = self.zoom()
        if lo == 0 and hi >= self._last:
            self.info.setText("Whole video")
        else:
            self.info.setText(f"{hi - lo + 1} of {self._last + 1} frames")
        self.info.show()
        self.reset_btn.setEnabled(not (lo == 0 and hi >= self._last))
