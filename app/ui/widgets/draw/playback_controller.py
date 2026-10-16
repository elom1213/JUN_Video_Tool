# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""프레임 번호 · 재생 상태 · 재생 클럭의 단일 진실 (PLAN_DRAW_TAB 5.4, 13.1).

재생 클럭은 QElapsedTimer 기준이다. 다음 프레임이 아직 디코드되지 않았으면 클럭을 멈추고 기다린다 —
프레임을 건너뛰지 않으므로 그림 · 고스트가 매 프레임 보인다. 기다리는 동안 오디오도 suspend 한다.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QElapsedTimer, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage

from ....core.models import VideoItem
from .audio_player import AudioPlayer
from .frame_provider import FrameProvider


class PlaybackController(QObject):
    frame_changed = Signal(int)            # 표시할 프레임 번호가 바뀜 (이미지 준비 여부와 무관)
    image_ready = Signal(int, QImage)      # 현재 프레임의 이미지가 도착
    playing_changed = Signal(bool)
    video_changed = Signal(object)         # VideoItem | None
    range_changed = Signal(int)            # last_frame (EOF 로 실제 길이가 짧게 밝혀졌을 때)
    loading_changed = Signal(bool)         # 현재 프레임 이미지가 없음(True) / 있음(False)

    def __init__(self, provider: FrameProvider, audio: AudioPlayer | None = None, parent=None) -> None:
        super().__init__(parent)
        self.provider = provider
        self.audio = audio
        self._item: VideoItem | None = None
        self._gen = 0
        self._frame = 0
        self._last = 0
        self._fps = 0.0
        self._playing = False
        self._waiting = False
        self._anchor_frame = 0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        provider.frame_ready.connect(self._on_frame_ready)
        provider.stream_ended.connect(self._on_stream_ended)
        provider.eof_reached.connect(self._on_eof)

    # ================================================================== 조회
    def frame(self) -> int:
        return self._frame

    def last_frame(self) -> int:
        return self._last

    def fps(self) -> float:
        return self._fps

    def is_playing(self) -> bool:
        return self._playing

    def item(self) -> VideoItem | None:
        return self._item

    def video_gen(self) -> int:
        return self._gen

    # ================================================================== 영상
    def set_video(self, item: VideoItem | None, hwaccel: str) -> None:
        self.pause()
        info = item.info if item is not None else None
        self._item = item if info is not None else None
        self._gen = self.provider.set_video(item.path if self._item else None, info, hwaccel)
        self._frame = 0
        self._fps = info.fps if info else 0.0
        self._last = info.last_frame if info else 0
        self.video_changed.emit(self._item)
        self.frame_changed.emit(0)
        if self._item is not None:
            self.loading_changed.emit(True)
            self.provider.request_frame(0)

    # ================================================================== 재생
    def play(self) -> None:
        if self._item is None or self._playing:
            return
        if self._frame >= self._last:
            self.seek(0)   # 끝에서 재생을 누르면 처음부터
        self._playing = True
        self._waiting = False
        self._restart_clock(self._frame)
        self.provider.start_stream(self._frame)
        interval = max(4, int(round(1000.0 / self._fps / 2))) if self._fps > 0 else 16
        self._timer.start(interval)
        self._start_audio()
        self.playing_changed.emit(True)

    def pause(self) -> None:
        if not self._playing:
            return
        self._playing = False
        self._waiting = False
        self._timer.stop()
        if self.audio is not None:
            self.audio.stop()
        self.provider.stop_stream()
        self.playing_changed.emit(False)

    def toggle(self) -> None:
        if self._playing:
            self.pause()
        else:
            self.play()

    def seek(self, frame: int) -> None:
        if self._item is None:
            return
        frame = max(0, min(int(frame), self._last))
        if frame == self._frame:
            return
        self._frame = frame
        self.frame_changed.emit(frame)
        img = self.provider.cached(frame)
        self.loading_changed.emit(img is None)
        if self._playing:
            # 재생 중 시크: 스트림을 새 위치에서 다시 걸고 오디오도 거기서 다시 시작
            self.provider.start_stream(frame)
            self._restart_clock(frame)
            self._waiting = False
            self._start_audio()
            if img is not None:
                self.image_ready.emit(frame, img)
        else:
            self.provider.request_frame(frame)

    def step(self, delta: int) -> None:
        if self._playing:
            self.pause()
        self.seek(self._frame + int(delta))

    def first(self) -> None:
        self.step(-self._frame)

    def last(self) -> None:
        self.step(self._last - self._frame)

    # ================================================================== 내부
    def _restart_clock(self, frame: int) -> None:
        self._anchor_frame = frame
        self._clock.restart()

    def _start_audio(self) -> None:
        if self.audio is None or self._item is None or self._item.info is None or not self._item.info.has_audio:
            return
        self.audio.start(self._item.path, self._frame / self._fps if self._fps > 0 else 0.0)

    def _tick(self) -> None:
        if not self._playing or self._waiting:
            return
        due = self._anchor_frame + int(math.floor(self._clock.elapsed() / 1000.0 * self._fps))
        if due <= self._frame:
            return
        if self._frame >= self._last:
            self.pause()
            return
        nxt = self._frame + 1
        img = self.provider.cached(nxt)
        if img is None:
            # 다음 프레임이 아직 없다 → 클럭과 소리를 멈추고 frame_ready 를 기다린다
            self._waiting = True
            if self.audio is not None:
                self.audio.suspend()
            self.loading_changed.emit(True)
            return
        self._show(nxt, img)
        if due > nxt:
            # UI 가 늦어 밀렸으면 건너뛰지 않고 기준점을 다시 잡는다
            self._restart_clock(nxt)

    def _show(self, frame: int, img: QImage) -> None:
        self._frame = frame
        self.provider.set_display_frame(frame)
        self.frame_changed.emit(frame)
        self.image_ready.emit(frame, img)
        self.loading_changed.emit(False)
        if self._playing and frame >= self._last:
            self.pause()

    def _on_frame_ready(self, gen: int, idx: int, img: QImage) -> None:
        if gen != self._gen or self._item is None:
            return
        if self._playing and self._waiting and idx == self._frame + 1:
            self._waiting = False
            self._show(idx, img)
            self._restart_clock(idx)
            if self.audio is not None:
                self.audio.resume()
            return
        if idx == self._frame:
            self.image_ready.emit(idx, img)
            self.loading_changed.emit(False)

    def _on_stream_ended(self, gen: int) -> None:
        if gen == self._gen and self._playing and self._waiting:
            self.pause()

    def _on_eof(self, gen: int, count: int) -> None:
        """ffprobe 의 frame_count 보다 실제 프레임이 적으면 마지막 프레임을 줄인다."""
        if gen != self._gen or count <= 0 or count - 1 >= self._last:
            return
        self._last = count - 1
        self.range_changed.emit(self._last)
        if self._frame > self._last:
            if self._playing:
                self.pause()
            self._frame = self._last
            self.frame_changed.emit(self._frame)
            self.provider.request_frame(self._frame)
