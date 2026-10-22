# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-22
"""트랜스포트 바 (PLAN_DRAW_TAB 5.5, 13.1, 17장, 18장): 버튼 · 타임라인(그림 마커 · 캐시 구간 핸들 · 확대) · 프레임 스핀 ·
타임코드 · 음량.

타임라인 확대(set_zoom): 슬라이더의 범위가 영상 전체가 아니라 [lo, hi] 가 된다. 재생 위치가 그 밖이면 핸들은 가장자리에 붙고,
프레임 스핀 · 타임코드는 실제 프레임을 보여 준다. 마커 · 캐시 줄 · 구간 핸들은 보이는 범위만 그린다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPolygonF
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSlider, QSpinBox, QStyle, QStyleOptionSlider, QToolButton,
                               QWidget)

from ....config import constants as C
from ....core.utils import frame_timecode
from ...icons import icon
from .playback_controller import PlaybackController


class _MarkerSlider(QSlider):
    """타임라인. 위에서 아래로: 캐시 구간 띠 + 양 끝 핸들(드래그) → 전체 캐시된 구간 녹색 줄 → 그루브 → 그림 마커 점.

    캐시 구간 핸들은 위쪽 띠(RANGE_STRIP_H px)에서만 잡힌다. 그 아래는 평소의 재생 위치 슬라이더다.
    """
    cache_range_changed = Signal(int, int)     # start, end (드래그 중에도 보낸다)

    RANGE_STRIP_H = 11      # 캐시 구간 띠 높이 (px). 이 안에서 누르면 핸들 드래그다
    HANDLE_W = 9            # 핸들 삼각형 폭
    GRAB_PX = 7             # 핸들 중심에서 이만큼 안이면 잡힌다

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._markers: list[int] = []
        self._cached: list[tuple[int, int]] = []
        self._range: tuple[int, int] | None = None     # 캐시 구간 (None = 안 보임)
        self._drag: str | None = None                  # "start" | "end"
        self._hover: str | None = None
        self.setMinimumHeight(34)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ API
    def set_markers(self, frames: list[int]) -> None:
        self._markers = list(frames)
        self.update()

    def set_cached_ranges(self, ranges: list[tuple[int, int]]) -> None:
        if ranges != self._cached:
            self._cached = list(ranges)
            self.update()

    def cache_range(self) -> tuple[int, int] | None:
        return self._range

    def set_cache_range(self, rng: tuple[int, int] | None) -> None:
        """신호 없이 띠만 옮긴다 (스핀박스 · 영상 전환에서 맞출 때)."""
        if rng is not None:
            rng = (int(rng[0]), int(rng[1]))
        if rng != self._range:
            self._range = rng
            self.update()

    # ------------------------------------------------------------------ 좌표
    def _geom(self) -> tuple[int, int, int, float]:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                             QStyle.SubControl.SC_SliderHandle, self)
        return self.minimum(), self.maximum(), self.width() - handle.width(), handle.width() / 2

    def _xpos(self, f: int) -> float:
        lo, hi, span, half = self._geom()
        return QStyle.sliderPositionFromValue(lo, hi, f, span) + half

    def _frame_at(self, x: float) -> int:
        lo, hi, span, half = self._geom()
        return QStyle.sliderValueFromPosition(lo, hi, int(round(x - half)), span)

    def _visible(self, f: int) -> bool:
        """확대된 범위 안에 있어 그려지는 프레임인가."""
        return self.minimum() <= f <= self.maximum()

    def _handle_hit(self, pos: QPointF) -> str | None:
        """위쪽 띠 안의 좌표가 어느 핸들 위인지. 둘이 겹쳐 있으면 마우스가 있는 쪽을 고른다. 범위 밖 핸들은 안 잡힌다."""
        if self._range is None or pos.y() > self.RANGE_STRIP_H or self.maximum() <= self.minimum():
            return None
        a, b = self._range
        xa, xb = self._xpos(a), self._xpos(b)
        da = abs(pos.x() - xa) if self._visible(a) else float("inf")
        db = abs(pos.x() - xb) if self._visible(b) else float("inf")
        if min(da, db) > self.GRAB_PX:
            return None
        if da == db:
            return "start" if pos.x() < xa else "end"
        return "start" if da < db else "end"

    # ------------------------------------------------------------------ 마우스
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton and self._range is not None and pos.y() <= self.RANGE_STRIP_H:
            # 띠 안에서 누르면 재생 위치는 안 움직인다 (핸들을 놓쳐도 시크되지 않게)
            self._drag = self._handle_hit(pos)
            if self._drag is not None:
                self._drag_to(pos.x())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        if self._drag is not None:
            self._drag_to(pos.x())
            event.accept()
            return
        hover = self._handle_hit(pos)
        if hover != self._hover:
            self._hover = hover
            self.setCursor(Qt.CursorShape.SplitHCursor if hover else Qt.CursorShape.ArrowCursor)
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._hover is not None:
            self._hover = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.update()
        super().leaveEvent(event)

    def _drag_to(self, x: float) -> None:
        assert self._range is not None and self._drag is not None
        f = max(self.minimum(), min(self.maximum(), self._frame_at(x)))
        a, b = self._range
        if self._drag == "start":
            a = min(f, b)                   # 끝을 넘어가지 않는다
        else:
            b = max(f, a)
        if (a, b) != self._range:
            self._range = (a, b)
            self.update()
            self.cache_range_changed.emit(a, b)

    # ------------------------------------------------------------------ 페인트
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if not (self._markers or self._cached or self._range is not None) or self.maximum() <= self.minimum():
            return
        lo, hi = self.minimum(), self.maximum()
        p = QPainter(self)
        p.setPen(Qt.PenStyle.NoPen)
        strip = self.RANGE_STRIP_H
        if self._range is not None:
            a, b = self._range
            ca, cb = max(a, lo), min(b, hi)         # 보이는 부분만 (확대 중이면 잘린다)
            if ca <= cb:
                x0, x1 = self._xpos(ca), self._xpos(cb)
                band = QColor(C.Colors.ACCENT)
                band.setAlpha(70)
                p.setBrush(band)
                p.drawRect(int(x0), 3, max(1, int(x1 - x0) + 1), strip - 5)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            hw = self.HANDLE_W / 2
            for key, f in (("start", a), ("end", b)):
                if not self._visible(f):
                    continue                        # 범위 밖 핸들은 그리지 않는다 (가장자리에 붙이면 자리가 거짓이 된다)
                x = self._xpos(f)
                active = self._drag == key or (self._drag is None and self._hover == key)
                p.setBrush(QColor(C.Colors.TEXT if active else C.Colors.ACCENT))
                # 아래를 향한 삼각형: 꼭짓점이 그 프레임 자리
                p.drawPolygon(QPolygonF([QPointF(x - hw, 0.0), QPointF(x + hw, 0.0), QPointF(x, strip - 1.0)]))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        if self._cached:
            p.setBrush(QColor(C.Colors.OK))
            for a, b in self._cached:
                a, b = max(a, lo), min(b, hi)
                if a > b:
                    continue
                x0, x1 = int(self._xpos(a)), int(self._xpos(b))
                p.drawRect(x0, strip + 1, max(1, x1 - x0 + 1), 2)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setBrush(QColor(C.Colors.ACCENT))
        y = self.height() - 3
        for f in self._markers:
            if self._visible(f):
                p.drawEllipse(int(self._xpos(f)) - 2, y - 2, 4, 4)
        p.end()


def _tool_button(name: str, tip: str) -> QToolButton:
    b = QToolButton()
    b.setIcon(icon(name))
    b.setIconSize(QSize(18, 18))
    b.setToolTip(tip)
    b.setAutoRaise(True)
    # Space 가 포커스된 버튼을 누르지 않게 한다 (5.8)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


class TransportBar(QWidget):
    volume_changed = Signal(int)       # 0 ~ 100
    muted_changed = Signal(bool)
    prev_drawn_clicked = Signal()      # 그림이 있는 이전 프레임으로
    next_drawn_clicked = Signal()      # 그림이 있는 다음 프레임으로
    cache_range_changed = Signal(int, int)   # 타임라인 핸들로 캐시 구간을 바꿈 (start, end)

    def __init__(self, controller: PlaybackController, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._updating = False
        self._resume_after_drag = False

        self.btn_first = _tool_button("first_frame", "First Frame (Home)")
        self.btn_prev = _tool_button("prev_frame", "Previous Frame (Left)")
        self.btn_play = _tool_button("play", "Play / Pause (Space)")
        self.btn_next = _tool_button("next_frame", "Next Frame (Right)")
        self.btn_last = _tool_button("last_frame", "Last Frame (End)")
        self.btn_prev_drawn = _tool_button("prev_drawn", "Previous Drawn Frame (Ctrl+Left)")
        self.btn_next_drawn = _tool_button("next_drawn", "Next Drawn Frame (Ctrl+Right)")
        self.slider = _MarkerSlider()
        self.slider.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        # 타임라인 양 끝 프레임 번호. 확대 중이면 주황으로 눈에 띈다
        self.zoom_lo_label = QLabel("0")
        self.zoom_hi_label = QLabel("0")
        for lb in (self.zoom_lo_label, self.zoom_hi_label):
            lb.setObjectName("HintLabel")
            lb.setToolTip("Frame at this end of the timeline (Timeline Zoom)")
        self.zoom_lo_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._last = 0
        self._zoom = (0, 0)
        self.spin = QSpinBox()
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumWidth(70)
        self.total_label = QLabel("/ 0")
        self.tc_label = QLabel("00:00:00:00")
        self.tc_label.setMinimumWidth(84)
        self.btn_mute = _tool_button("volume", "Mute")
        self.btn_mute.setCheckable(True)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(C.DRAW_VOLUME_DEFAULT)
        self.volume.setFixedWidth(90)
        self.volume.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.volume.setToolTip("Volume")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        for b in (self.btn_first, self.btn_prev, self.btn_play, self.btn_next, self.btn_last):
            lay.addWidget(b)
        lay.addSpacing(6)
        lay.addWidget(self.btn_prev_drawn)
        lay.addWidget(self.btn_next_drawn)
        lay.addWidget(self.zoom_lo_label)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.zoom_hi_label)
        lay.addWidget(QLabel("Frame"))
        lay.addWidget(self.spin)
        lay.addWidget(self.total_label)
        lay.addSpacing(8)
        lay.addWidget(self.tc_label)
        lay.addSpacing(8)
        lay.addWidget(self.btn_mute)
        lay.addWidget(self.volume)

        c = controller
        self.btn_first.clicked.connect(c.first)
        self.btn_prev.clicked.connect(lambda: c.step(-1))
        self.btn_play.clicked.connect(c.toggle)
        self.btn_next.clicked.connect(lambda: c.step(1))
        self.btn_last.clicked.connect(c.last)
        self.btn_prev_drawn.clicked.connect(self.prev_drawn_clicked)
        self.btn_next_drawn.clicked.connect(self.next_drawn_clicked)
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderMoved.connect(self._slider_moved)
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.valueChanged.connect(self._slider_value)
        self.slider.cache_range_changed.connect(self.cache_range_changed)
        self.spin.valueChanged.connect(self._spin_value)
        self.btn_mute.toggled.connect(self._mute_toggled)
        self.volume.valueChanged.connect(self.volume_changed)
        c.frame_changed.connect(self.set_frame)
        c.playing_changed.connect(self._playing_changed)
        c.range_changed.connect(self.set_range)
        self.set_range(0)
        self.setEnabled(False)

    # ------------------------------------------------------------------ API
    def set_range(self, last_frame: int) -> None:
        """영상 길이. 확대는 전체로 되돌아간다 (DrawTab 이 필요하면 set_zoom 으로 다시 맞춘다)."""
        self._last = max(0, int(last_frame))
        self._updating = True
        self.spin.setRange(0, self._last)
        self.total_label.setText(f"/ {last_frame}")
        self._updating = False
        self.set_zoom(0, self._last)

    def zoom(self) -> tuple[int, int]:
        return self._zoom

    def set_zoom(self, lo: int, hi: int) -> None:
        """타임라인 양 끝에 보일 프레임 (신호 없음). 범위 밖의 재생 위치는 가장자리에 붙는다."""
        lo, hi = max(0, min(int(lo), self._last)), max(0, min(int(hi), self._last))
        if hi < lo:
            lo, hi = hi, lo
        self._zoom = (lo, hi)
        self._updating = True
        self.slider.setRange(lo, hi)
        self.slider.setValue(self.spin.value())
        self._updating = False
        zoomed = not (lo == 0 and hi >= self._last)
        color = C.Colors.ACCENT if zoomed else C.Colors.TEXT_DIM
        for lb, v in ((self.zoom_lo_label, lo), (self.zoom_hi_label, hi)):
            lb.setText(str(v))
            lb.setStyleSheet(f"color: {color};")

    def set_markers(self, frames: list[int]) -> None:
        self.slider.set_markers(frames)

    def set_cached_ranges(self, ranges: list[tuple[int, int]]) -> None:
        self.slider.set_cached_ranges(ranges)

    def set_cache_range(self, rng: tuple[int, int] | None) -> None:
        """캐시 구간 띠를 맞춘다 (신호 없음). None = 영상 없음."""
        self.slider.set_cache_range(rng)

    def set_frame(self, frame: int) -> None:
        self._updating = True
        if not self.slider.isSliderDown():
            self.slider.setValue(frame)
        self.spin.setValue(frame)
        self.tc_label.setText(frame_timecode(frame, self.controller.fps()))
        self._updating = False

    def set_snap_enabled(self, prev: bool, nxt: bool) -> None:
        self.btn_prev_drawn.setEnabled(prev)
        self.btn_next_drawn.setEnabled(nxt)

    def set_audio_state(self, volume: int, muted: bool) -> None:
        self.volume.setValue(volume)
        self.btn_mute.setChecked(muted)
        self._mute_icon(muted)

    def set_has_audio(self, has_audio: bool) -> None:
        self.btn_mute.setEnabled(has_audio)
        self.volume.setEnabled(has_audio)
        self.btn_mute.setToolTip("Mute" if has_audio else "This video has no audio")

    # ------------------------------------------------------------------ 내부
    def _playing_changed(self, playing: bool) -> None:
        self.btn_play.setIcon(icon("pause" if playing else "play"))

    def _slider_pressed(self) -> None:
        self._resume_after_drag = self.controller.is_playing()
        if self._resume_after_drag:
            self.controller.pause()

    def _slider_moved(self, v: int) -> None:
        self.controller.seek(v)

    def _slider_released(self) -> None:
        self.controller.seek(self.slider.value())
        if self._resume_after_drag:
            self._resume_after_drag = False
            self.controller.play()

    def _slider_value(self, v: int) -> None:
        # 홈 클릭 · 키보드 이동처럼 드래그가 아닌 변경
        if not self._updating and not self.slider.isSliderDown():
            self.controller.seek(v)

    def _spin_value(self, v: int) -> None:
        if not self._updating:
            self.controller.seek(v)

    def _mute_toggled(self, muted: bool) -> None:
        self._mute_icon(muted)
        self.muted_changed.emit(muted)

    def _mute_icon(self, muted: bool) -> None:
        self.btn_mute.setIcon(icon("volume_mute" if muted else "volume"))
        self.btn_mute.setToolTip("Unmute" if muted else "Mute")
