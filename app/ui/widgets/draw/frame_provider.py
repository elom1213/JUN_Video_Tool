# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""디코더 스레드 + LRU 프레임 캐시 (PLAN_DRAW_TAB 5.3).

UI 스레드는 request_frame / start_stream / stop_stream / set_display_frame 만 부른다.
요청마다 request_gen 이 올라가므로 진행 중 디코드는 즉시 끊기고 최신 요청 하나만 좇는다 (스크럽 대응).
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ....config import constants as C
from ....core import ffmpeg_locator
from ....core.frame_decoder import DecodeSpec, FrameStream, make_decode_spec
from ....core.models import MediaInfo

_HW_HINTS = ("hwaccel", "d3d11", "dxva", "cuda", "qsv", "nvdec", "vulkan", "device")


class FrameProvider(QThread):
    frame_ready = Signal(int, int, QImage)     # video_gen, frame_index, image
    stream_ended = Signal(int)                 # video_gen (재생 스트림이 끝까지 디코드됨)
    eof_reached = Signal(int, int)             # video_gen, EOF 직전까지 읽은 프레임 수 (= 실제 frame_count 상한)
    decode_error = Signal(int, str)            # video_gen, message
    info = Signal(int, str)                    # video_gen, 로그용 안내 (hwaccel 폴백 등)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cv = threading.Condition()
        self._quit = False
        self._req: tuple[str, int] | None = None
        self._req_gen = 0
        self._video_gen = 0
        self._path: Path | None = None
        self._spec: DecodeSpec | None = None
        self._hwaccel = "none"
        self._legacy_vsync = False
        self._display_frame = 0
        self._cache: OrderedDict[int, QImage] = OrderedDict()
        self._cache_bytes = 0
        self._budget = C.DRAW_CACHE_BUDGET_MB * 2 ** 20

    # ================================================================== UI 스레드 API
    @property
    def spec(self) -> DecodeSpec | None:
        return self._spec

    def cache_capacity(self) -> int:
        spec = self._spec
        return self._budget // spec.frame_bytes if spec and spec.frame_bytes else 0

    def set_video(self, path: Path | None, info: MediaInfo | None, hwaccel: str) -> int:
        with self._cv:
            self._video_gen += 1
            self._req_gen += 1
            self._req = None
            self._cache.clear()
            self._cache_bytes = 0
            self._display_frame = 0
            if path is None or info is None:
                self._path, self._spec = None, None
            else:
                self._path = Path(path)
                self._spec = make_decode_spec(info)
                self._hwaccel = hwaccel
            self._cv.notify_all()
            return self._video_gen

    def cached(self, frame: int) -> QImage | None:
        with self._cv:
            img = self._cache.get(frame)
            if img is not None:
                self._cache.move_to_end(frame)
            return img

    def request_frame(self, frame: int) -> None:
        img = self.cached(frame)
        if img is not None:
            self.frame_ready.emit(self._video_gen, frame, img)
            # 캐시 히트여도 앞쪽 prefetch 가 비었으면 채워 둔다 (→ 연타 대응)
            if self._range_cached(frame, frame + C.DRAW_PREFETCH_FORWARD // 2):
                return
        self._post(("seek", frame))

    def start_stream(self, from_frame: int) -> None:
        with self._cv:
            self._display_frame = from_frame
        self._post(("stream", from_frame))

    def stop_stream(self) -> None:
        with self._cv:
            frame = self._display_frame
        self._post(("seek", frame))

    def set_display_frame(self, frame: int) -> None:
        with self._cv:
            self._display_frame = frame
            self._cv.notify_all()

    def shutdown(self) -> None:
        with self._cv:
            self._quit = True
            self._req_gen += 1
            self._cv.notify_all()
        self.wait(2000)

    # ================================================================== 내부
    def _post(self, req: tuple[str, int]) -> None:
        with self._cv:
            self._req = req
            self._req_gen += 1
            self._cv.notify_all()

    def _range_cached(self, a: int, b: int) -> bool:
        with self._cv:
            return all(f in self._cache for f in range(max(0, a), b + 1))

    def _put(self, idx: int, img: QImage, frame_bytes: int) -> None:
        with self._cv:
            if idx in self._cache:
                self._cache.move_to_end(idx)
                return
            self._cache[idx] = img
            self._cache_bytes += frame_bytes
            while self._cache_bytes > self._budget and len(self._cache) > 1:
                self._cache.popitem(last=False)
                self._cache_bytes -= frame_bytes

    def _alive(self, gen: int) -> bool:
        return not self._quit and self._req_gen == gen

    def run(self) -> None:  # noqa: C901 — 워커 루프는 한 곳에 모아 둔다
        while True:
            with self._cv:
                while not self._quit and self._req is None:
                    self._cv.wait()
                if self._quit:
                    return
                kind, frame = self._req
                self._req = None
                gen = self._req_gen
                vgen = self._video_gen
                path, spec = self._path, self._spec
            if path is None or spec is None:
                continue
            ffmpeg = ffmpeg_locator.find_ffmpeg()
            if ffmpeg is None:
                self.decode_error.emit(vgen, "ffmpeg is not available.")
                continue

            if kind == "seek":
                if self._range_cached(frame, frame + C.DRAW_PREFETCH_FORWARD):
                    continue
                if self.cached(frame) is not None:
                    # 목표는 이미 있음 → 그 뒤 처음 비어 있는 프레임부터 prefetch
                    start = frame
                    while self.cached(start) is not None:
                        start += 1
                elif frame == 0 or self.cached(frame - 1) is not None:
                    start = frame
                else:
                    start = max(0, frame - C.DRAW_PREFETCH_BACKWARD)
            else:
                # 재생: 이미 캐시된 앞부분은 건너뛰고 처음 비어 있는 프레임부터 연다
                start = frame
                while start < frame + C.DRAW_PLAY_AHEAD and self.cached(start) is not None:
                    start += 1

            self._decode(ffmpeg, path, spec, kind, frame, start, gen, vgen)

    def _open(self, ffmpeg: Path, path: Path, spec: DecodeSpec, start: int, gen: int,
              vgen: int) -> tuple[FrameStream | None, tuple[int, bytes] | None]:
        """스트림을 열고 첫 프레임까지 읽는다. hwaccel · -fps_mode 실패 시 한 번씩 폴백 (4.1)."""
        for _attempt in range(3):
            stream = FrameStream(ffmpeg, path, spec, start, self._hwaccel, self._legacy_vsync)
            got = stream.read_frame()
            if got is not None or not self._alive(gen):
                return stream, got
            stream.close()
            code = stream.returncode()
            err = stream.stderr_tail()
            if code in (0, None):
                return None, None          # 정상 EOF (끝을 넘는 요청)
            if "fps_mode" in err and not self._legacy_vsync:
                self._legacy_vsync = True
                self.info.emit(vgen, "ffmpeg does not support -fps_mode; retrying with -vsync 0.")
                continue
            if self._hwaccel == "auto":
                self._hwaccel = "none"     # 이후 이 영상은 none 으로 고정 (set_video 에서 다시 정해진다)
                low = err.lower()
                hint = "hardware decode failed" if any(h in low for h in _HW_HINTS) else "decode failed"
                self.info.emit(vgen, f"{hint.capitalize()}; retrying without hardware acceleration.")
                continue
            self.decode_error.emit(vgen, err.splitlines()[-1] if err else f"ffmpeg exited with code {code}.")
            return None, None
        return None, None

    def _decode(self, ffmpeg: Path, path: Path, spec: DecodeSpec, kind: str, frame: int, start: int, gen: int,
                vgen: int) -> None:
        stream, got = self._open(ffmpeg, path, spec, start, gen, vgen)
        if stream is None:
            if self._alive(gen):
                self.eof_reached.emit(vgen, start)
                if kind == "stream":
                    self.stream_ended.emit(vgen)
            return
        w, h = spec.out_w, spec.out_h
        try:
            while self._alive(gen):
                if got is None:
                    code = stream.returncode()
                    if code not in (0, None):
                        err = stream.stderr_tail()
                        self.decode_error.emit(vgen, err.splitlines()[-1] if err else f"ffmpeg exited with code {code}.")
                    else:
                        self.eof_reached.emit(vgen, stream.next_index)
                        if kind == "stream":
                            self.stream_ended.emit(vgen)
                    return
                idx, data = got
                img = QImage(data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
                self._put(idx, img, spec.frame_bytes)
                self.frame_ready.emit(vgen, idx, img)
                if kind == "seek" and (idx >= frame + C.DRAW_PREFETCH_FORWARD
                                       or (idx >= frame and self._range_cached(frame, frame + C.DRAW_PREFETCH_FORWARD))):
                    return
                if kind == "stream":
                    # 표시 프레임보다 너무 앞서가지 않는다 (캐시가 재생 중 프레임을 밀어내지 않게)
                    with self._cv:
                        while self._alive(gen) and stream.next_index - self._display_frame > C.DRAW_PLAY_AHEAD:
                            self._cv.wait(0.05)
                got = stream.read_frame()
        finally:
            stream.close()
