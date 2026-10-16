# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""Draw 탭 프레임 디코더 (PLAN_DRAW_TAB 4.1, 13.1).

ffmpeg 한 프로세스가 시작 프레임부터 순차로 RGB24 raw 프레임을 내보내고, 우리는 w*h*3 바이트씩 읽는다.
오디오 재생용 s16le 파이프 명령도 여기서 만든다. PySide6 비의존.
"""
from __future__ import annotations

import subprocess
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from ..config import constants as C
from .models import MediaInfo
from .utils import resolve_dimensions, subprocess_flags


@dataclass(frozen=True)
class DecodeSpec:
    src_w: int
    src_h: int
    fps: float
    out_w: int
    out_h: int

    @property
    def frame_bytes(self) -> int:
        return self.out_w * self.out_h * 3


def make_decode_spec(info: MediaInfo, max_width: int = C.DRAW_DECODE_MAX_WIDTH) -> DecodeSpec:
    out_w = min(int(info.width), int(max_width))
    out_w = max(2, out_w - (out_w % 2))
    out_h = resolve_dimensions(info.width, info.height, out_w, None)[1]
    out_h = max(2, out_h - (out_h % 2))
    return DecodeSpec(int(info.width), int(info.height), float(info.fps), out_w, out_h)


def seek_time(frame: int, fps: float) -> float:
    """프레임 i 의 입력 시크 시각. 0.25 프레임 여유로 i+1 이 먼저 나오는 일을 막는다 (2.2)."""
    if fps <= 0:
        return 0.0
    return max(0.0, (frame - 0.25) / fps)


def build_stream_command(ffmpeg: Path, path: Path, spec: DecodeSpec, start_frame: int, hwaccel: str,
                         legacy_vsync: bool = False) -> list[str]:
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if hwaccel == "auto":
        cmd += ["-hwaccel", "auto"]
    if start_frame > 0:
        cmd += ["-ss", f"{seek_time(start_frame, spec.fps):.6f}"]
    cmd += ["-i", str(path), "-an", "-sn"]
    cmd += ["-vsync", "0"] if legacy_vsync else ["-fps_mode", "passthrough"]
    cmd += ["-vf", f"scale={spec.out_w}:{spec.out_h}:flags=bilinear,format=rgb24",
            "-f", "rawvideo", "-"]
    return cmd


def build_audio_command(ffmpeg: Path, path: Path, start_sec: float,
                        rate: int = C.AUDIO_RATE, channels: int = C.AUDIO_CHANNELS) -> list[str]:
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start_sec > 0:
        cmd += ["-ss", f"{start_sec:.6f}"]
    cmd += ["-i", str(path), "-vn", "-sn", "-ac", str(int(channels)), "-ar", str(int(rate)),
            "-f", "s16le", "-"]
    return cmd


class FrameStream:
    """Popen 래퍼. read_frame() 는 (frame_index, bytes) 를 돌려주고 EOF 면 None."""

    def __init__(self, ffmpeg: Path, path: Path, spec: DecodeSpec, start_frame: int, hwaccel: str,
                 legacy_vsync: bool = False) -> None:
        self.spec = spec
        self.next_index = int(start_frame)
        self.last_error = ""
        self._err: deque[str] = deque(maxlen=20)
        cmd = build_stream_command(ffmpeg, path, spec, start_frame, hwaccel, legacy_vsync)
        self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, bufsize=0, creationflags=subprocess_flags())
        # stderr 를 비우지 않으면 파이프가 차서 ffmpeg 가 멈출 수 있다
        self._err_thread = threading.Thread(target=self._drain_err, daemon=True)
        self._err_thread.start()

    def _drain_err(self) -> None:
        stream = self._proc.stderr
        if stream is None:
            return
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._err.append(line)
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def read_frame(self) -> tuple[int, bytes] | None:
        out = self._proc.stdout
        if out is None:
            return None
        need = self.spec.frame_bytes
        buf = bytearray()
        try:
            while len(buf) < need:
                chunk = out.read(need - len(buf))
                if not chunk:
                    return None
                buf += chunk
        except (OSError, ValueError):
            return None
        idx = self.next_index
        self.next_index += 1
        return idx, bytes(buf)

    def returncode(self) -> int | None:
        return self._proc.poll()

    def stderr_tail(self) -> str:
        return "\n".join(self._err)

    def close(self) -> None:
        try:
            if self._proc.poll() is None:
                self._proc.kill()
            self._proc.wait(timeout=1.0)
        except Exception:
            pass
        for s in (self._proc.stdout,):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass
        self._err_thread.join(timeout=1.0)
        self.last_error = self._err[-1] if self._err else ""
