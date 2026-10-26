# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-26
"""Draw 탭 프레임 디코더 (PLAN_DRAW_TAB 4.1, 13.1).

ffmpeg 한 프로세스가 시작 프레임부터 순차로 RGB24 raw 프레임을 내보내고, 우리는 w*h*3 바이트씩 읽는다.
디코드 해상도는 원본의 100 / 75 / 50 / 25 % 중 하나 (DRAW_DECODE_SCALES).
오디오 재생용 s16le 파이프 명령도 여기서 만든다. PySide6 비의존.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..config import constants as C
from . import image_sequence
from .models import MediaInfo
from .utils import subprocess_flags

# 프레임 버퍼 할당자: (돌려줄 객체, 그 객체 메모리에 쓰는 memoryview). Draw 탭은 QImage 를 바로 채운다
FrameAlloc = Callable[[], "tuple[Any, memoryview]"]


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


def normalize_scale(scale: Any) -> int:
    """설정값 → DRAW_DECODE_SCALES 중 하나 (모르는 값은 기본값)."""
    try:
        v = int(scale)
    except (TypeError, ValueError):
        return C.DRAW_DECODE_SCALE_DEFAULT
    return v if v in C.DRAW_DECODE_SCALES else C.DRAW_DECODE_SCALE_DEFAULT


def decode_size(width: int, height: int, scale: int = 100) -> tuple[int, int]:
    """원본 크기 x scale % 를 짝수로 내린 디코드 크기 (최소 2)."""
    s = max(1, min(100, int(scale))) / 100.0
    w = max(2, int(round(int(width) * s)) // 2 * 2)
    h = max(2, int(round(int(height) * s)) // 2 * 2)
    return w, h


def make_decode_spec(info: MediaInfo, scale: int = 100) -> DecodeSpec:
    out_w, out_h = decode_size(info.width, info.height, scale)
    return DecodeSpec(int(info.width), int(info.height), float(info.fps), out_w, out_h)


def _big_pipe() -> tuple[int, int] | None:
    """Windows: 버퍼가 큰 익명 파이프 (read_fd, write_fd). 기본 파이프(4 KB)는 4K 프레임에서 읽기가 4 배 느리다."""
    if sys.platform != "win32":
        return None
    try:
        import _winapi
        import msvcrt
        r, w = _winapi.CreatePipe(None, C.DRAW_PIPE_BUFFER_BYTES)
        return msvcrt.open_osfhandle(r, os.O_RDONLY), msvcrt.open_osfhandle(w, 0)
    except (ImportError, OSError):
        return None


def seek_time(frame: int, fps: float) -> float:
    """프레임 i 의 입력 시크 시각. 0.25 프레임 여유로 i+1 이 먼저 나오는 일을 막는다 (2.2)."""
    if fps <= 0:
        return 0.0
    return max(0.0, (frame - 0.25) / fps)


def build_stream_command(ffmpeg: Path, path: Path, spec: DecodeSpec, start_frame: int, hwaccel: str,
                         legacy_vsync: bool = False) -> list[str]:
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-nostdin"]
    seq = image_sequence.is_image(path)
    if hwaccel == "auto" and not seq:
        cmd += ["-hwaccel", "auto"]
    if start_frame > 0:
        cmd += ["-ss", f"{seek_time(start_frame, spec.fps):.6f}"]
    cmd += image_sequence.input_args(path, spec.fps) + ["-an", "-sn"]
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
    """Popen 래퍼. read_frame() 는 (frame_index, 프레임 데이터) 를 돌려주고 EOF 면 None.

    alloc 을 주면 프레임마다 그것이 준 버퍼에 바로 읽어 넣고 그 객체를 돌려준다 (복사 없음). 없으면 bytes.
    """

    def __init__(self, ffmpeg: Path, path: Path, spec: DecodeSpec, start_frame: int, hwaccel: str,
                 legacy_vsync: bool = False, alloc: FrameAlloc | None = None) -> None:
        self.spec = spec
        self.next_index = int(start_frame)
        self.last_error = ""
        self._alloc = alloc
        self._err: deque[str] = deque(maxlen=20)
        cmd = build_stream_command(ffmpeg, path, spec, start_frame, hwaccel, legacy_vsync)
        pipe = _big_pipe()
        if pipe is None:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE, bufsize=0, creationflags=subprocess_flags())
            self._out = self._proc.stdout
        else:
            rfd, wfd = pipe
            try:
                self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=wfd, stderr=subprocess.PIPE,
                                              bufsize=0, creationflags=subprocess_flags())
            except BaseException:
                os.close(rfd)
                raise
            finally:
                os.close(wfd)   # 쓰기 끝은 자식만 갖는다 (부모가 쥐고 있으면 EOF 가 오지 않는다)
            self._out = os.fdopen(rfd, "rb", buffering=0)
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

    def read_frame(self) -> tuple[int, Any] | None:
        out = self._out
        if out is None:
            return None
        need = self.spec.frame_bytes
        if self._alloc is not None:
            obj, view = self._alloc()
        else:
            obj = bytearray(need)
            view = memoryview(obj)
        # readinto 로 미리 잡은 버퍼에 바로 받는다. read(n) 은 파이프가 몇 KB 씩만 돌려줘도 매번 n 바이트를
        # 새로 할당하므로 (프레임당 수백 번 x 2.7 MB) 디코드보다 읽기가 5 배 느려진다
        got = 0
        try:
            while got < need:
                k = out.readinto(view[got:need])
                if not k:
                    return None
                got += k
        except (OSError, ValueError):
            return None
        finally:
            view.release()
        idx = self.next_index
        self.next_index += 1
        return idx, (bytes(obj) if self._alloc is None else obj)

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
        for s in (self._out,):
            try:
                if s is not None:
                    s.close()
            except OSError:
                pass
        self._err_thread.join(timeout=1.0)
        self.last_error = self._err[-1] if self._err else ""
