# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""프레임 구간 편집 패널 (PLAN 6.7). 음성 파일은 1 ms 단위 구간 (MediaInfo.audio_only)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ...config import constants as C
from ...core.models import FrameRange, VideoItem
from ...core.size_estimator import output_frames
from ...core.thumbnail import clamp_time
from ...core.utils import format_timecode, frame_to_sec
from ..icons import icon
from .loaders import ThumbnailLoader
from .range_slider import RangeSlider


def _clock(sec: float) -> str:
    """초 → "MM:SS.mmm" (음성 구간 표시)."""
    sec = max(0.0, sec)
    m, s = divmod(sec, 60.0)
    return f"{int(m):02d}:{s:06.3f}"


class _PreviewLabel(QLabel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(C.THUMB_IMG_W, C.THUMB_IMG_H)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setObjectName("PreviewLabel")
        self.clear_preview()

    def clear_preview(self) -> None:
        self.setPixmap(QPixmap())
        self.setText("…")

    def set_image(self, img: QImage) -> None:
        pm = QPixmap.fromImage(img).scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        self.setText("")
        self.setPixmap(pm)


class FrameRangePanel(QGroupBox):
    range_changed = Signal(int, object)      # row, FrameRange | None
    apply_to_checked = Signal(object)        # FrameRange

    def __init__(self, thumb_loader: ThumbnailLoader, parent: QWidget | None = None) -> None:
        super().__init__("Frame Range (selected item)", parent)
        self._thumbs = thumb_loader
        self._row = -1
        self._item: VideoItem | None = None
        self._updating = False
        self._output_fps = 0.0
        self._wait_keys: dict[str, str] = {}   # key → "start"|"end"

        self.hint_label = QLabel("Select a probed video to edit its range.")
        self.hint_label.setObjectName("HintLabel")
        self.hint_label.setWordWrap(True)

        self.start_preview = _PreviewLabel()
        self.end_preview = _PreviewLabel()
        self.start_spin = QSpinBox()
        self.end_spin = QSpinBox()
        for sp in (self.start_spin, self.end_spin):
            sp.setAccelerated(True)
            sp.setMinimumWidth(70)
        self.slider = RangeSlider()
        self.start_tc = QLabel("00:00:00:00")
        self.end_tc = QLabel("00:00:00:00")
        self.end_tc.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.frames_label = QLabel()
        self.frames_label.setObjectName("HintLabel")
        self.frames_label.setWordWrap(True)
        self.full_btn = QPushButton(icon("full_range"), "Full Range")
        self.apply_btn = QPushButton(icon("apply"), "Apply to Checked")

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
        v.addWidget(self.hint_label)
        prev = QHBoxLayout()
        prev.addStretch(1)
        prev.addWidget(self.start_preview)
        prev.addSpacing(8)
        prev.addWidget(self.end_preview)
        prev.addStretch(1)
        v.addLayout(prev)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.addWidget(QLabel("Start"), 0, 0)
        g.addWidget(self.start_spin, 0, 1)
        g.addWidget(self.slider, 0, 2)
        g.addWidget(self.end_spin, 0, 3)
        g.addWidget(QLabel("End"), 0, 4)
        g.addWidget(self.start_tc, 1, 0, 1, 2)
        g.addWidget(self.end_tc, 1, 3, 1, 2)
        g.setColumnStretch(2, 1)
        v.addLayout(g)
        v.addWidget(self.frames_label)
        btns = QHBoxLayout()
        btns.addWidget(self.full_btn)
        btns.addWidget(self.apply_btn)
        v.addLayout(btns)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(C.PREVIEW_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._commit)

        self.slider.valuesChanged.connect(self._slider_changed)
        self.slider.sliderReleased.connect(self._debounce.start)
        self.start_spin.valueChanged.connect(self._spin_changed)
        self.end_spin.valueChanged.connect(self._spin_changed)
        self.start_spin.editingFinished.connect(self._debounce.start)
        self.end_spin.editingFinished.connect(self._debounce.start)
        self.full_btn.clicked.connect(self._full_range)
        self.apply_btn.clicked.connect(self._apply_all)
        self._thumbs.thumbnail_ready.connect(self._thumb_ready)
        self._thumbs.thumbnail_failed.connect(self._thumb_failed)

        self._set_enabled(False)

    # ------------------------------------------------------------------ 공개 API
    def set_item(self, row: int, item: VideoItem | None) -> None:
        self._row = row
        self._item = item
        self._wait_keys.clear()
        if item is None or item.info is None:
            self._set_enabled(False)
            self.hint_label.setText("Select a probed video to edit its range." if item is None
                                    else (item.probe_error or "Probing…"))
            self.start_preview.clear_preview()
            self.end_preview.clear_preview()
            self.frames_label.setText("")
            return
        self._set_enabled(True)
        info = item.info
        self.hint_label.setText(item.path.name + ("  (audio - range in milliseconds)" if info.audio_only else ""))
        for sp in (self.start_spin, self.end_spin):
            sp.setSuffix(" ms" if info.audio_only else "")
        rng = item.effective_range()
        self._updating = True
        self.slider.setRange(0, info.last_frame)
        self.start_spin.setRange(0, info.last_frame)
        self.end_spin.setRange(0, info.last_frame)
        self.slider.setValues(rng.start_frame, rng.end_frame)
        self.start_spin.setValue(rng.start_frame)
        self.end_spin.setValue(rng.end_frame)
        self._updating = False
        self._refresh_labels()
        self._request_previews()

    def refresh_item(self, row: int, item: VideoItem) -> None:
        """외부에서 구간이 바뀐 경우(Reset 등) 현재 표시 중이면 갱신."""
        if row == self._row:
            self.set_item(row, item)

    def set_output_fps(self, fps: float) -> None:
        self._output_fps = fps
        self._refresh_labels()

    def current_range(self) -> FrameRange | None:
        if self._item is None or self._item.info is None:
            return None
        lo, hi = self.slider.values()
        return FrameRange(lo, hi)

    # ------------------------------------------------------------------ 내부
    def _set_enabled(self, on: bool) -> None:
        for w in (self.slider, self.start_spin, self.end_spin, self.full_btn, self.apply_btn,
                  self.start_preview, self.end_preview):
            w.setEnabled(on)

    def _slider_changed(self, lo: int, hi: int) -> None:
        if self._updating:
            return
        self._updating = True
        self.start_spin.setValue(lo)
        self.end_spin.setValue(hi)
        self._updating = False
        self._refresh_labels()

    def _spin_changed(self, _v: int) -> None:
        if self._updating:
            return
        lo, hi = self.start_spin.value(), self.end_spin.value()
        if lo > hi:
            if self.sender() is self.start_spin:
                hi = lo
                self._updating = True
                self.end_spin.setValue(hi)
                self._updating = False
            else:
                lo = hi
                self._updating = True
                self.start_spin.setValue(lo)
                self._updating = False
        self._updating = True
        self.slider.setValues(lo, hi)
        self._updating = False
        self._refresh_labels()

    def _refresh_labels(self) -> None:
        if self._item is None or self._item.info is None:
            return
        info = self._item.info
        lo, hi = self.slider.values()
        rng = FrameRange(lo, hi)
        _, dur = rng.to_seconds(info.fps)
        if info.audio_only:
            self.start_tc.setText(_clock(frame_to_sec(lo, info.fps)))
            self.end_tc.setText(_clock(frame_to_sec(hi + 1, info.fps)))
            self.frames_label.setText(f"Length: {dur:.3f} s / {info.duration:.3f} s")
            return
        self.start_tc.setText(format_timecode(frame_to_sec(lo, info.fps), info.fps))
        self.end_tc.setText(format_timecode(frame_to_sec(hi, info.fps), info.fps))
        text = f"Frames: {rng.frame_count} / {info.frame_count} ({dur:.1f} s)"
        if self._output_fps > 0:
            text += f" → {output_frames(dur, self._output_fps)} output frames @ {self._output_fps:g} fps"
        self.frames_label.setText(text)

    def _commit(self) -> None:
        if self._item is None or self._item.info is None:
            return
        lo, hi = self.slider.values()
        rng = FrameRange(lo, hi)
        payload = None if rng.is_full(self._item.info) else rng
        self._item.frame_range = payload
        self.range_changed.emit(self._row, payload)
        self._request_previews()

    def _full_range(self) -> None:
        if self._item is None or self._item.info is None:
            return
        self._updating = True
        self.slider.setValues(0, self._item.info.last_frame)
        self.start_spin.setValue(0)
        self.end_spin.setValue(self._item.info.last_frame)
        self._updating = False
        self._refresh_labels()
        self._commit()

    def _apply_all(self) -> None:
        rng = self.current_range()
        if rng is not None:
            self.apply_to_checked.emit(rng)

    def _request_previews(self) -> None:
        if self._item is None or self._item.info is None:
            return
        info = self._item.info
        lo, hi = self.slider.values()
        self._wait_keys.clear()
        if info.audio_only:
            for prev in (self.start_preview, self.end_preview):
                prev.setPixmap(QPixmap())
                prev.setText("Audio")
            return
        for which, frame in (("start", lo), ("end", hi)):
            t = clamp_time(frame_to_sec(frame, info.fps), info)
            key = self._thumbs.request(self._item.path, t, C.PREVIEW_WIDTH)
            self._wait_keys[key] = which

    def _thumb_ready(self, key: str, img: QImage) -> None:
        which = self._wait_keys.get(key)
        if which == "start":
            self.start_preview.set_image(img)
        elif which == "end":
            self.end_preview.set_image(img)

    def _thumb_failed(self, key: str, _err: str) -> None:
        which = self._wait_keys.get(key)
        if which == "start":
            self.start_preview.setText("N/A")
        elif which == "end":
            self.end_preview.setText("N/A")
