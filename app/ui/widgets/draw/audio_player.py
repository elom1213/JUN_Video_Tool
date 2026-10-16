# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""Draw 탭 오디오 재생 (PLAN_DRAW_TAB 13.1).

ffmpeg `-f s16le` 파이프를 리더 스레드가 읽어 deque 에 쌓고, UI 스레드 타이머가 QAudioSink(push 모드)에
bytesFree() 만큼 쓴다. 비디오 클럭이 주인이고, 오디오는 play/seek 때 그 시각에서 새로 시작한다.
"""
from __future__ import annotations

import subprocess
import threading
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ....config import constants as C
from ....core import ffmpeg_locator
from ....core.frame_decoder import build_audio_command
from ....core.utils import subprocess_flags

try:  # QtMultimedia 가 빠진 환경에서도 앱은 떠야 한다 (무음 동작)
    from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink, QMediaDevices
    _HAS_MM = True
except ImportError:  # pragma: no cover
    _HAS_MM = False

_BYTES_PER_FRAME = 2 * C.AUDIO_CHANNELS      # Int16 × 채널
_MAX_BUFFER = C.AUDIO_RATE * _BYTES_PER_FRAME * 2   # 리더가 2 초 이상 앞서 쌓지 않는다


class AudioPlayer(QObject):
    log = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sink = None
        self._dev = None
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._buf: deque[bytes] = deque()
        self._buf_bytes = 0
        self._lock = threading.Lock()
        self._space = threading.Condition(self._lock)
        self._gen = 0
        self._pending = b""
        self._volume = C.DRAW_VOLUME_DEFAULT / 100.0
        self._muted = False
        self._available: bool | None = None
        self._timer = QTimer(self)
        self._timer.setInterval(C.AUDIO_PUSH_INTERVAL_MS)
        self._timer.timeout.connect(self._push)

    # ------------------------------------------------------------------ 장치
    def _ensure_sink(self) -> bool:
        if self._available is not None:
            return self._available
        self._available = False
        if not _HAS_MM:
            self.log.emit("No audio output device; playback is silent.")
            return False
        dev = QMediaDevices.defaultAudioOutput()
        fmt = QAudioFormat()
        fmt.setSampleRate(C.AUDIO_RATE)
        fmt.setChannelCount(C.AUDIO_CHANNELS)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if dev.isNull() or not dev.isFormatSupported(fmt):
            self.log.emit("No audio output device; playback is silent.")
            return False
        self._sink = QAudioSink(dev, fmt, self)
        self._sink.setBufferSize(C.AUDIO_RATE * _BYTES_PER_FRAME // 5)    # 200 ms
        self._apply_volume()
        self._available = True
        return True

    def _apply_volume(self) -> None:
        if self._sink is not None:
            self._sink.setVolume(0.0 if self._muted else self._volume)

    def set_volume(self, percent: int) -> None:
        self._volume = max(0, min(100, int(percent))) / 100.0
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        self._apply_volume()

    # ------------------------------------------------------------------ 재생
    def start(self, path: Path, start_sec: float) -> None:
        """start_sec 위치에서 새로 재생한다 (이전 재생은 버린다)."""
        self.stop()
        ffmpeg = ffmpeg_locator.find_ffmpeg()
        if ffmpeg is None or not self._ensure_sink():
            return
        cmd = build_audio_command(ffmpeg, Path(path), max(0.0, start_sec))
        try:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, bufsize=0, creationflags=subprocess_flags())
        except OSError as exc:
            self.log.emit(f"Audio playback failed: {exc}")
            self._proc = None
            return
        with self._lock:
            self._gen += 1
            gen = self._gen
        self._reader = threading.Thread(target=self._read, args=(self._proc, gen), daemon=True)
        self._reader.start()
        assert self._sink is not None
        self._dev = self._sink.start()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        with self._lock:
            self._gen += 1
            self._buf.clear()
            self._buf_bytes = 0
            self._space.notify_all()
        self._pending = b""
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
            except Exception:
                pass
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except OSError:
                pass
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        if self._sink is not None:
            self._sink.stop()
        self._dev = None

    def suspend(self) -> None:
        """비디오가 디코드를 기다리는 동안 소리가 앞서 나가지 않게 멈춘다."""
        if self._sink is not None and self._dev is not None:
            self._sink.suspend()
            self._timer.stop()

    def resume(self) -> None:
        if self._sink is not None and self._dev is not None:
            self._sink.resume()
            self._timer.start()

    def shutdown(self) -> None:
        self.stop()

    # ------------------------------------------------------------------ 내부
    def _read(self, proc: subprocess.Popen, gen: int) -> None:
        out = proc.stdout
        if out is None:
            return
        try:
            while True:
                chunk = out.read(16384)
                if not chunk:
                    return
                with self._lock:
                    while self._gen == gen and self._buf_bytes > _MAX_BUFFER:
                        self._space.wait(0.05)
                    if self._gen != gen:
                        return
                    self._buf.append(chunk)
                    self._buf_bytes += len(chunk)
        except (OSError, ValueError):
            return

    def _push(self) -> None:
        if self._sink is None or self._dev is None:
            return
        if self._sink.state() == QAudio.State.SuspendedState:
            return
        free = self._sink.bytesFree()
        if free <= 0:
            return
        data = self._pending
        with self._lock:
            while self._buf and len(data) < free:
                chunk = self._buf.popleft()
                self._buf_bytes -= len(chunk)
                data += chunk
            self._space.notify_all()
        if not data:
            return
        n = min(len(data), free)
        n -= n % _BYTES_PER_FRAME
        if n <= 0:
            self._pending = data
            return
        written = self._dev.write(data[:n])
        written = max(0, int(written))
        self._pending = data[written:]
