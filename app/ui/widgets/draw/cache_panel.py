# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-22
"""해상도 · 프레임 캐시 패널: 디코드 해상도(원본 / 75 / 50 / 25 %), 캐시 구간(시작 · 끝 프레임 정수 입력),
지금 영상의 구간을 메모리에 올리기, 모든 캐시 해제, 메모리 현황.

표시만 한다. 계산과 실행은 DrawTab 이 provider 를 불러서 한다. 캐시 구간은 타임라인 핸들과 같은 값을 보여 주며
(DrawTab 이 양쪽을 맞춘다), 스핀박스를 고치면 range_changed 로 알린다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QSpinBox,
                               QVBoxLayout)

from ....config import constants as C
from ....core.frame_decoder import decode_size
from ....core.memory_info import format_gib


def _scale_name(scale: int) -> str:
    return "Original" if scale == 100 else f"{scale}%"


class CachePanel(QGroupBox):
    cache_clicked = Signal()     # 지금 영상의 캐시 구간을 캐시 (채우는 중이면 멈춤)
    free_clicked = Signal()      # 모든 영상의 캐시 해제
    scale_changed = Signal(int)  # 디코드 해상도 (원본의 %)
    range_changed = Signal(int, int)   # 스핀박스로 캐시 구간을 바꿈 (start, end)
    get_zoom_clicked = Signal()        # 캐시 구간 = 지금 타임라인 확대 구간 (Timeline Zoom 의 Show)

    def __init__(self, parent=None) -> None:
        super().__init__("Resolution && Cache", parent)
        self.res_combo = QComboBox()
        for s in C.DRAW_DECODE_SCALES:
            self.res_combo.addItem(_scale_name(s), s)
        self.res_combo.setToolTip("Resolution frames are decoded at. Drawings always use source pixels.\n"
                                  "Higher resolution uses more memory per frame and decodes slower.")
        # 포커스를 받으면 ← → 가 콤보 값을 바꿔 버린다 (프레임 이동 단축키)
        self.res_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.res_info = QLabel()
        self.res_info.setObjectName("HintLabel")
        # 캐시 구간 (프레임 번호, 끝 포함). 타임라인의 핸들과 같은 값
        self.start_spin = QSpinBox()
        self.end_spin = QSpinBox()
        for sp, tip in ((self.start_spin, "First frame to cache. Drag the left handle above the timeline to change it."),
                        (self.end_spin, "Last frame to cache (inclusive). Drag the right handle above the timeline.")):
            sp.setKeyboardTracking(False)
            sp.setMinimumWidth(64)
            sp.setToolTip(tip)
        self.all_btn = QPushButton("All")
        self.all_btn.setToolTip("Cache range = whole video")
        self.get_zoom_btn = QPushButton("Get Zoom")
        self.get_zoom_btn.setToolTip("Cache range = the frames shown on the timeline (Timeline Zoom > Show)")
        for b in (self.all_btn, self.get_zoom_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.range_info = QLabel()
        self.range_info.setObjectName("HintLabel")
        self.video_label = QLabel()
        self.video_label.setWordWrap(True)
        self.need_label = QLabel()
        self.need_label.setWordWrap(True)
        self.need_label.setObjectName("HintLabel")
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setFixedHeight(16)
        self.bar.hide()
        self.total_label = QLabel()
        self.total_label.setWordWrap(True)
        self.cache_btn = QPushButton("Cache Whole Video")
        self.cache_btn.setToolTip("Decode every frame of this video into memory so stepping never waits.\n"
                                  "Cached videos stay in memory when you switch videos.")
        self.free_btn = QPushButton("Free All")
        self.free_btn.setToolTip("Release the memory used by cached frames of all videos.")
        for b in (self.cache_btn, self.free_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(4)
        res_row = QHBoxLayout()
        res_row.addWidget(QLabel("Resolution"))
        res_row.addWidget(self.res_combo, 1)
        lay.addLayout(res_row)
        lay.addWidget(self.res_info)
        rng_row = QHBoxLayout()
        rng_row.setSpacing(4)
        rng_row.addWidget(QLabel("Range"))
        rng_row.addWidget(self.start_spin, 1)
        rng_row.addWidget(QLabel("–"))
        rng_row.addWidget(self.end_spin, 1)
        rng_row.addWidget(self.all_btn)
        rng_row.addWidget(self.get_zoom_btn)
        lay.addLayout(rng_row)
        lay.addWidget(self.range_info)
        lay.addWidget(self.video_label)
        lay.addWidget(self.need_label)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.cache_btn, 3)
        row.addWidget(self.free_btn, 2)
        lay.addLayout(row)
        lay.addWidget(self.total_label)

        self.cache_btn.clicked.connect(self.cache_clicked)
        self.free_btn.clicked.connect(self.free_clicked)
        self.res_combo.currentIndexChanged.connect(lambda _i: self.scale_changed.emit(self.scale()))
        self.start_spin.valueChanged.connect(self._spin_changed)
        self.end_spin.valueChanged.connect(self._spin_changed)
        self.all_btn.clicked.connect(lambda: self.range_changed.emit(0, self.end_spin.maximum()))
        self.get_zoom_btn.clicked.connect(self.get_zoom_clicked)
        self._last = -1
        self.set_source_size(0, 0)
        self.set_range_bounds(-1)
        self.set_state(None, 0, 0, False, None, 0, 0, None)

    # ------------------------------------------------------------------ 캐시 구간
    def set_range_bounds(self, last: int) -> None:
        """영상 길이 (마지막 프레임 번호). -1 = 영상 없음 → 비활성."""
        self._last = int(last)
        has = last >= 0
        for sp in (self.start_spin, self.end_spin):
            sp.blockSignals(True)
            sp.setRange(0, max(0, last))
            sp.setEnabled(has)
            sp.blockSignals(False)
        self.all_btn.setEnabled(has)
        self.get_zoom_btn.setEnabled(has)
        if not has:
            self.set_cache_range(0, 0)

    def cache_range(self) -> tuple[int, int]:
        return self.start_spin.value(), self.end_spin.value()

    def set_cache_range(self, start: int, end: int) -> None:
        """신호 없이 스핀박스만 맞춘다 (타임라인 핸들 · 영상 전환에서)."""
        for sp, v in ((self.start_spin, start), (self.end_spin, end)):
            sp.blockSignals(True)
            sp.setValue(int(v))
            sp.blockSignals(False)
        self._update_range_info()

    def _spin_changed(self, _v: int) -> None:
        a, b = self.start_spin.value(), self.end_spin.value()
        if self.sender() is self.start_spin and a > b:
            b = a                    # 시작을 끝 너머로 올리면 끝도 따라간다
        elif self.sender() is self.end_spin and b < a:
            a = b
        self.set_cache_range(a, b)
        self.range_changed.emit(a, b)

    def _update_range_info(self) -> None:
        if self._last < 0:
            self.range_info.setText("")
            self.range_info.hide()
            return
        a, b = self.cache_range()
        n = b - a + 1
        whole = a == 0 and b == self._last
        w, h = getattr(self, "_src", (0, 0))
        text = f"{n} frame{'s' if n != 1 else ''}" + (" (whole video)" if whole else "")
        if w > 0 and h > 0:
            dw, dh = decode_size(w, h, self.scale())
            text += f" · {format_gib(n * dw * dh * 3)}"
        self.range_info.setText(text)
        self.range_info.show()

    # ------------------------------------------------------------------ 해상도
    def scale(self) -> int:
        return int(self.res_combo.currentData())

    def set_scale(self, scale: int) -> None:
        """신호 없이 콤보만 맞춘다 (설정 복원 · 취소 되돌리기)."""
        i = self.res_combo.findData(int(scale))
        if i >= 0:
            self.res_combo.blockSignals(True)
            self.res_combo.setCurrentIndex(i)
            self.res_combo.blockSignals(False)
        self._update_res_info()

    def set_source_size(self, w: int, h: int) -> None:
        """영상 크기를 받아 항목마다 디코드 크기를 붙인다 (0 이면 영상 없음)."""
        self._src = (int(w), int(h))
        for i, s in enumerate(C.DRAW_DECODE_SCALES):
            text = _scale_name(s)
            if w > 0 and h > 0:
                dw, dh = decode_size(w, h, s)
                text += f" ({dw}x{dh})"
            self.res_combo.setItemText(i, text)
        self._update_res_info()

    def _update_res_info(self) -> None:
        w, h = getattr(self, "_src", (0, 0))
        if w <= 0 or h <= 0:
            self.res_info.setText("")
            self.res_info.hide()
            return
        dw, dh = decode_size(w, h, self.scale())
        self.res_info.setText(f"{dw * dh * 3 / 2 ** 20:.1f} MB per frame")
        self.res_info.show()
        self._update_range_info()

    def set_state(self, video: str | None, cached: int, frames: int, complete: bool, filling: str | None,
                  total_bytes: int, videos: int, need_text: str | None, whole: bool = True) -> None:
        """video: 지금 영상 이름 (없으면 None). filling: 채우는 중인 영상 이름 (없으면 None).

        cached / frames / complete 는 캐시 구간 기준이다. whole: 구간이 영상 전체다 (버튼 문구가 바뀐다).
        """
        filling_this = filling is not None and filling == video
        what = "This video" if whole else "This range"
        if video is None:
            self.video_label.setText("No video.")
        elif complete:
            self.video_label.setText(f"{what}: all {cached} frames cached.")
        elif cached:
            self.video_label.setText(f"{what}: {cached} of {frames} frames cached.")
        else:
            self.video_label.setText(f"{what}: not cached.")
        self.need_label.setText(need_text or "")
        self.need_label.setVisible(bool(need_text))
        self.bar.setVisible(filling is not None)
        if filling is not None and not filling_this:
            self.bar.setFormat(f"{filling}  %p%")
        else:
            self.bar.setFormat("%p%")
        self.cache_btn.setText("Stop Caching" if filling_this else ("Cache Whole Video" if whole else "Cache Range"))
        self.cache_btn.setEnabled(video is not None and (filling_this or not complete))
        self.free_btn.setEnabled(total_bytes > 0 or filling is not None)
        if total_bytes > 0:
            self.total_label.setText(f"In memory: {format_gib(total_bytes)} ({videos} video{'s' if videos != 1 else ''})")
        else:
            self.total_label.setText("In memory: none")

    def set_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(min(done, max(1, total)))
