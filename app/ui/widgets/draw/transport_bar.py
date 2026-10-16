# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""트랜스포트 바 (PLAN_DRAW_TAB 5.5, 13.1): 버튼 · 타임라인(그림 마커) · 프레임 스핀 · 타임코드 · 음량."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSlider, QSpinBox, QStyle, QStyleOptionSlider, QToolButton,
                               QWidget)

from ....config import constants as C
from ....core.utils import frame_timecode
from ...icons import icon
from .playback_controller import PlaybackController


class _MarkerSlider(QSlider):
    """그림이 있는 프레임 위치마다 그루브 아래에 코랄 점을 찍는다."""

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._markers: list[int] = []
        self.setMinimumHeight(22)

    def set_markers(self, frames: list[int]) -> None:
        self._markers = list(frames)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._markers or self.maximum() <= self.minimum():
            return
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        handle = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                             QStyle.SubControl.SC_SliderHandle, self)
        span = self.width() - handle.width()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.Colors.ACCENT))
        y = self.height() - 3
        for f in self._markers:
            x = QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), f, span) + handle.width() / 2
            p.drawEllipse(int(x) - 2, y - 2, 4, 4)
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
        self.slider = _MarkerSlider()
        self.slider.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
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
        lay.addWidget(self.slider, 1)
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
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderMoved.connect(self._slider_moved)
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.valueChanged.connect(self._slider_value)
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
        self._updating = True
        self.slider.setRange(0, max(0, last_frame))
        self.spin.setRange(0, max(0, last_frame))
        self.total_label.setText(f"/ {last_frame}")
        self._updating = False

    def set_markers(self, frames: list[int]) -> None:
        self.slider.set_markers(frames)

    def set_frame(self, frame: int) -> None:
        self._updating = True
        if not self.slider.isSliderDown():
            self.slider.setValue(frame)
        self.spin.setValue(frame)
        self.tc_label.setText(frame_timecode(frame, self.controller.fps()))
        self._updating = False

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
