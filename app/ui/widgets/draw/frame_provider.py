# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-19
"""디코더 스레드 + LRU 프레임 캐시 (PLAN_DRAW_TAB 5.3) + 전체 캐시 (Cache Whole Video).

UI 스레드는 request_frame / start_stream / stop_stream / set_display_frame 만 부른다.
요청마다 request_gen 이 올라가므로 진행 중 디코드는 즉시 끊기고 최신 요청 하나만 좇는다 (스크럽 대응).
단, 이미 돌고 있는 앞쪽 prefetch 가 곧 닿을 프레임이면 끊지 않고 목표만 늘린다 — 끊으면 ffmpeg 를 다시 띄워
키프레임부터 다시 디코드해야 해서, 한 프레임씩 넘길 때 화면이 잠깐 멈추는 원인이 된다.

전체 캐시는 영상별 저장소(_Pinned)에 담기고, 영상을 바꿔도 남는다 (free_all_cache 로만 비운다).
채우기는 별도 스레드 · 별도 ffmpeg 가 하므로 그 동안에도 프레임 이동 · 그리기가 된다.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from ....config import constants as C
from ....core import ffmpeg_locator
from ....core.frame_decoder import DecodeSpec, FrameStream, make_decode_spec
from ....core.memory_info import format_gib, system_memory
from ....core.models import MediaInfo

_HW_HINTS = ("hwaccel", "d3d11", "dxva", "cuda", "qsv", "nvdec", "vulkan", "device")


def _image_alloc(spec: DecodeSpec) -> Callable[[], tuple[QImage, memoryview]] | None:
    """파이프에서 QImage 메모리로 바로 읽는 할당자. 행 끝에 패딩이 생기는 폭(w*3 이 4 의 배수가 아님)이면 None."""
    w, h = spec.out_w, spec.out_h
    if (w * 3) % 4:
        return None

    def alloc() -> tuple[QImage, memoryview]:
        img = QImage(w, h, QImage.Format.Format_RGB888)
        return img, memoryview(img.bits())
    return alloc


def to_image(data, spec: DecodeSpec) -> QImage:
    """read_frame 결과 → QImage (할당자를 썼으면 이미 QImage)."""
    if isinstance(data, QImage):
        return data
    w, h = spec.out_w, spec.out_h
    return QImage(data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


def open_stream(ffmpeg: Path, path: Path, spec: DecodeSpec, start: int, hwaccel: str, legacy_vsync: bool,
                alive: Callable[[], bool], on_info: Callable[[str], None]
                ) -> tuple[FrameStream | None, tuple[int, QImage | bytes] | None, str, bool, str]:
    """스트림을 열고 첫 프레임까지 읽는다. hwaccel · -fps_mode 실패 시 한 번씩 폴백 (4.1).

    (stream, 첫 프레임, 폴백 뒤 hwaccel, 폴백 뒤 legacy_vsync, 오류 메시지) 를 돌려준다.
    stream 이 None 이고 오류가 "" 이면 정상 EOF (끝을 넘는 요청). 프레임 데이터는 to_image 로 QImage 로 만든다.
    """
    alloc = _image_alloc(spec)
    for _attempt in range(3):
        stream = FrameStream(ffmpeg, path, spec, start, hwaccel, legacy_vsync, alloc)
        got = stream.read_frame()
        if got is not None or not alive():
            return stream, got, hwaccel, legacy_vsync, ""
        stream.close()
        code = stream.returncode()
        err = stream.stderr_tail()
        if code in (0, None):
            return None, None, hwaccel, legacy_vsync, ""
        if "fps_mode" in err and not legacy_vsync:
            legacy_vsync = True
            on_info("ffmpeg does not support -fps_mode; retrying with -vsync 0.")
            continue
        if hwaccel == "auto":
            hwaccel = "none"
            low = err.lower()
            hint = "hardware decode failed" if any(h in low for h in _HW_HINTS) else "decode failed"
            on_info(f"{hint.capitalize()}; retrying without hardware acceleration.")
            continue
        return None, None, hwaccel, legacy_vsync, err.splitlines()[-1] if err else f"ffmpeg exited with code {code}."
    return None, None, hwaccel, legacy_vsync, ""


class _Pinned:
    """전체 캐시 한 영상분. frames 는 provider 의 _cv 아래에서만 고친다."""

    def __init__(self, name: str, frame_bytes: int) -> None:
        self.name = name
        self.frame_bytes = frame_bytes
        self.frames: dict[int, QImage] = {}
        self.complete = False          # 0 번부터 영상 끝까지 빈틈없이 올라가 있다

    @property
    def nbytes(self) -> int:
        return len(self.frames) * self.frame_bytes


class FrameProvider(QThread):
    frame_ready = Signal(int, int, QImage)     # video_gen, frame_index, image
    stream_ended = Signal(int)                 # video_gen (재생 스트림이 끝까지 디코드됨)
    eof_reached = Signal(int, int)             # video_gen, EOF 직전까지 읽은 프레임 수 (= 실제 frame_count 상한)
    decode_error = Signal(int, str)            # video_gen, message
    info = Signal(int, str)                    # video_gen, 로그용 안내 (hwaccel 폴백 등)
    fill_progress = Signal(str, int, int)      # 영상 이름, 범위 안에서 캐시된 프레임 수, 범위 프레임 수
    fill_finished = Signal(str, bool, str)     # 영상 이름, 범위를 다 채웠나, 로그 메시지
    fill_log = Signal(str)                     # 채우기 중 안내 (폴백 등)
    cache_changed = Signal()                   # 전체 캐시 메모리가 바뀜 (채우는 중엔 진행 간격으로)

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
        # 진행 중인 seek prefetch (끊지 않고 늘리기 위해 run 스레드가 갱신)
        self._job_gen = -1
        self._job_next = 0
        self._job_end = 0
        self._stream_next = -1                     # 재생 스트림이 다음에 낼 프레임 (재생 중이 아니면 -1)
        # 전체 캐시
        self._key: tuple | None = None
        self._pinned: dict[tuple, _Pinned] = {}
        self._pin: _Pinned | None = None           # 지금 영상의 전체 캐시 (없으면 None)
        self._fill_token = 0
        self._fill_name: str | None = None         # 채우는 중인 영상 이름 (없으면 None)
        self._fill_thread: threading.Thread | None = None

    # ================================================================== UI 스레드 API
    @property
    def spec(self) -> DecodeSpec | None:
        return self._spec

    def cache_capacity(self) -> int:
        spec = self._spec
        return self._budget // spec.frame_bytes if spec and spec.frame_bytes else 0

    def set_video(self, path: Path | None, info: MediaInfo | None, hwaccel: str,
                  scale: int = C.DRAW_DECODE_SCALE_DEFAULT) -> int:
        """scale: 디코드 해상도 (원본의 %). 전체 캐시는 (경로, 디코드 크기) 별이라 해상도마다 따로다."""
        with self._cv:
            self._video_gen += 1
            self._req_gen += 1
            self._req = None
            self._cache.clear()
            self._cache_bytes = 0
            self._display_frame = 0
            if path is None or info is None:
                self._path, self._spec, self._key = None, None, None
            else:
                self._path = Path(path)
                self._spec = make_decode_spec(info, scale)
                self._hwaccel = hwaccel
                self._key = (str(self._path), self._spec.out_w, self._spec.out_h)
            # 전체 캐시는 영상을 바꿔도 남는다 — 돌아오면 바로 쓴다
            self._pin = self._pinned.get(self._key) if self._key is not None else None
            self._cv.notify_all()
            return self._video_gen

    def cached(self, frame: int) -> QImage | None:
        with self._cv:
            pin = self._pin
            if pin is not None:
                img = pin.frames.get(frame)
                if img is not None:
                    return img
            img = self._cache.get(frame)
            if img is not None:
                self._cache.move_to_end(frame)
            return img

    def request_frame(self, frame: int) -> None:
        with self._cv:
            self._display_frame = frame    # LRU 가 지금 보는 자리 앞쪽을 밀어내지 않게
        img = self.cached(frame)
        if img is not None:
            self.frame_ready.emit(self._video_gen, frame, img)
            # 캐시 히트여도 앞쪽 prefetch 가 비었으면 채워 둔다 (→ 연타 대응)
            if self._range_cached(frame, frame + C.DRAW_PREFETCH_FORWARD // 2):
                return
        if self._extend_job(frame, img is not None):
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
            self._fill_token += 1
            self._fill_name = None
            self._cv.notify_all()
            th = self._fill_thread
        self.wait(2000)
        if th is not None:
            th.join(2.0)

    # ------------------------------------------------------------------ 전체 캐시 (UI 스레드)
    def pinned_frames(self) -> int:
        """지금 영상의 전체 캐시 프레임 수."""
        with self._cv:
            return len(self._pin.frames) if self._pin is not None else 0

    def pinned_complete(self) -> bool:
        with self._cv:
            return self._pin is not None and self._pin.complete

    def pinned_total(self) -> tuple[int, int]:
        """(모든 영상의 전체 캐시 bytes, 영상 수)."""
        with self._cv:
            stores = [p for p in self._pinned.values() if p.frames]
            return sum(p.nbytes for p in stores), len(stores)

    def pinned_ranges(self) -> list[tuple[int, int]]:
        """지금 영상에서 전체 캐시된 연속 구간들 [(a, b), ...] (b 포함)."""
        with self._cv:
            keys = sorted(self._pin.frames) if self._pin is not None else []
        out: list[tuple[int, int]] = []
        for k in keys:
            if out and k == out[-1][1] + 1:
                out[-1] = (out[-1][0], k)
            else:
                out.append((k, k))
        return out

    def filling_name(self) -> str | None:
        with self._cv:
            return self._fill_name

    def start_full_cache(self, start: int, end: int, reserve: int, whole: bool) -> bool:
        """지금 영상의 [start, end] 를 전체 캐시로 채우기 시작한다. 다른 채우기가 돌고 있으면 그것은 멈춘다.

        whole: [start, end] 가 영상 전체(0 ~ 마지막 프레임)다. 채우는 동안 남은 메모리가 reserve 아래로 내려가면 멈춘다.
        """
        self.cancel_full_cache()
        with self._cv:
            if self._path is None or self._spec is None or self._key is None or end < start:
                return False
            pin = self._pinned.get(self._key)
            if pin is None:
                pin = self._pinned[self._key] = _Pinned(self._path.name, self._spec.frame_bytes)
            self._pin = pin
            self._fill_token += 1
            token = self._fill_token
            self._fill_name = pin.name
            args = (token, pin, self._path, self._spec, int(start), int(end), self._hwaccel, self._legacy_vsync,
                    int(reserve), bool(whole), self._key)
            th = self._fill_thread = threading.Thread(target=self._fill, args=args, daemon=True)
        th.start()
        return True

    def cancel_full_cache(self) -> None:
        """채우기를 멈춘다. 이미 올라간 프레임은 남는다."""
        with self._cv:
            self._fill_token += 1
            name, self._fill_name = self._fill_name, None
        if name is not None:
            self.fill_finished.emit(name, False, f"Stopped caching {name}.")
            self.cache_changed.emit()

    def free_all_cache(self) -> int:
        """전체 캐시(모든 영상) + LRU 캐시를 비운다. 해제한 bytes 를 돌려준다."""
        self.cancel_full_cache()
        with self._cv:
            freed = sum(p.nbytes for p in self._pinned.values()) + self._cache_bytes
            self._pinned.clear()
            self._pin = None
            self._cache.clear()
            self._cache_bytes = 0
            # 진행 중 디코드(재생 스트림 포함)는 끊지 않는다 — LRU 는 다시 채워져도 상한이 있다
        self.cache_changed.emit()
        return freed

    # ================================================================== 내부
    def _post(self, req: tuple[str, int]) -> None:
        with self._cv:
            self._req = req
            self._req_gen += 1
            self._stream_next = -1     # 돌던 스트림은 끊긴다 (새 스트림이면 첫 프레임에서 다시 정해진다)
            self._cv.notify_all()

    def _has(self, f: int) -> bool:
        """_cv 를 잡은 채로 부른다."""
        return f in self._cache or (self._pin is not None and f in self._pin.frames)

    def _range_cached(self, a: int, b: int) -> bool:
        with self._cv:
            return all(self._has(f) for f in range(max(0, a), b + 1))

    def _extend_job(self, frame: int, have_frame: bool) -> bool:
        """돌고 있는 seek prefetch 가 곧 닿을 자리면 끊지 않고 목표만 늘린다. 늘렸으면 True."""
        with self._cv:
            if self._job_gen != self._req_gen or self._req is not None:
                return False
            need = frame
            if have_frame:
                while need <= frame + C.DRAW_PREFETCH_FORWARD and self._has(need):
                    need += 1
            if not (self._job_next <= need <= self._job_next + C.DRAW_PREFETCH_FORWARD):
                return False
            self._job_end = max(self._job_end, frame + C.DRAW_PREFETCH_FORWARD)
            self._cv.notify_all()      # 세워 둔 스트림을 깨운다
            return True

    def _put(self, idx: int, img: QImage, frame_bytes: int) -> None:
        with self._cv:
            if self._pin is not None and idx in self._pin.frames:
                return
            if idx in self._cache:
                self._cache.move_to_end(idx)
                return
            self._cache[idx] = img
            self._cache_bytes += frame_bytes
            # 재생 창 [표시 프레임, 표시 + play_ahead] 은 밀어내지 않는다. 큰 프레임(4K 원본)은 LRU 에 몇십 장만
            # 들어가서, 그냥 오래된 순으로 빼면 곧 보여줄 프레임이 지워지고 재생이 그 자리에서 멈춘다
            lo = self._display_frame
            hi = lo + self._play_ahead() + 1
            while self._cache_bytes > self._budget and len(self._cache) > 1:
                victim = next((k for k in self._cache if not lo <= k <= hi), None)
                if victim is None:
                    self._cache.popitem(last=False)
                else:
                    del self._cache[victim]
                self._cache_bytes -= frame_bytes

    def _play_ahead(self) -> int:
        """재생 중 디코더가 앞서 가도 되는 프레임 수. 캐시 용량의 1/3 을 넘지 않는다 (큰 프레임 대비)."""
        return max(4, min(C.DRAW_PLAY_AHEAD, self.cache_capacity() // 3))

    def stream_passed(self, frame: int) -> bool:
        """재생 스트림이 frame 을 이미 지나갔는데 캐시에 없다 (다시 걸어야 한다)."""
        with self._cv:
            return self._stream_next > frame and not self._has(frame)

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
                while start < frame + self._play_ahead() and self.cached(start) is not None:
                    start += 1

            self._decode(ffmpeg, path, spec, kind, frame, start, gen, vgen)

    def _decode(self, ffmpeg: Path, path: Path, spec: DecodeSpec, kind: str, frame: int, start: int, gen: int,
                vgen: int) -> None:
        # hwaccel 폴백은 이후 이 영상 내내 유지된다 (set_video 에서 다시 정해진다)
        stream, got, self._hwaccel, self._legacy_vsync, err = open_stream(
            ffmpeg, path, spec, start, self._hwaccel, self._legacy_vsync, lambda: self._alive(gen),
            lambda msg: self.info.emit(vgen, msg))
        if stream is None:
            if err:
                self.decode_error.emit(vgen, err)
            elif self._alive(gen):
                self.eof_reached.emit(vgen, start)
                if kind == "stream":
                    self.stream_ended.emit(vgen)
            return
        if kind == "seek":
            with self._cv:
                self._job_gen, self._job_next, self._job_end = gen, start, frame + C.DRAW_PREFETCH_FORWARD
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
                img = self.cached(idx)
                if img is None:
                    img = to_image(data, spec)
                    self._put(idx, img, spec.frame_bytes)
                self.frame_ready.emit(vgen, idx, img)
                if kind == "seek":
                    with self._cv:
                        self._job_next = idx + 1
                        # 목표까지 채웠으면 닫지 않고 세워 둔다 (ffmpeg 는 파이프가 차서 멈춘다). 앞으로 넘기면
                        # _extend_job 이 목표를 늘려 그대로 이어 읽는다 — 다시 열면 키프레임부터 다시 디코드해야 한다
                        while self._alive(gen) and (idx >= self._job_end
                                                    or all(self._has(f) for f in range(idx + 1, self._job_end + 1))):
                            self._cv.wait(0.5)
                if kind == "stream":
                    # 표시 프레임보다 너무 앞서가지 않는다 (캐시가 재생 중 프레임을 밀어내지 않게)
                    ahead = self._play_ahead()
                    with self._cv:
                        self._stream_next = stream.next_index
                        while self._alive(gen) and stream.next_index - self._display_frame > ahead:
                            self._cv.wait(0.05)
                got = stream.read_frame()
        finally:
            with self._cv:
                if kind == "seek" and self._job_gen == gen:
                    self._job_gen = -1
                if kind == "stream" and self._req_gen == gen:
                    self._stream_next = -1
            stream.close()

    # ================================================================== 전체 캐시 채우기 (별도 스레드)
    def _fill(self, token: int, pin: _Pinned, path: Path, spec: DecodeSpec, a: int, b: int, hwaccel: str,
              legacy: bool, reserve: int, whole: bool, key: tuple) -> None:  # noqa: C901
        def alive() -> bool:
            return not self._quit and self._fill_token == token

        def finish(ok: bool, msg: str) -> None:
            with self._cv:
                if self._fill_token != token or self._fill_name is None:
                    return              # 이미 취소됨 (취소한 쪽이 알렸다)
                self._fill_name = None
                if ok and pin.complete and self._key == key:
                    # 이 영상은 전부 전체 캐시에 있다 → LRU 는 중복이므로 비운다
                    self._cache.clear()
                    self._cache_bytes = 0
            self.cache_changed.emit()
            self.fill_finished.emit(pin.name, ok, msg)

        ffmpeg = ffmpeg_locator.find_ffmpeg()
        if ffmpeg is None:
            finish(False, "ffmpeg is not available.")
            return
        total = b - a + 1
        t0 = time.monotonic()
        last_emit = 0.0
        with self._cv:
            done = sum(1 for fr in range(a, b + 1) if fr in pin.frames)
        f = a
        eof_at: int | None = None
        while alive():
            with self._cv:
                while f <= b and f in pin.frames:
                    f += 1
            if f > b:
                break
            stream, got, hwaccel, legacy, err = open_stream(
                ffmpeg, path, spec, f, hwaccel, legacy, alive, lambda msg: self.fill_log.emit(f"[{pin.name}] {msg}"))
            if stream is None:
                if err:
                    finish(False, f"Caching {pin.name} failed: {err}")
                    return
                eof_at = f
                break
            n = 0
            try:
                while alive() and got is not None:
                    idx, data = got
                    if idx > b:
                        break
                    with self._cv:
                        have = idx in pin.frames
                    if not have:
                        img = to_image(data, spec)
                        with self._cv:
                            if idx not in pin.frames:
                                pin.frames[idx] = img
                                done += 1
                    n += 1
                    f = idx + 1
                    if n % C.DRAW_FULL_CACHE_MEM_CHECK_EVERY == 0:
                        mem = system_memory()
                        if mem is not None and mem.available < reserve:
                            finish(False, f"Stopped caching {pin.name}: system memory is low "
                                          f"({format_gib(mem.available)} free). {done} of {total} frames cached.")
                            return
                    now = time.monotonic()
                    if now - last_emit >= C.DRAW_FULL_CACHE_PROGRESS_MS / 1000.0:
                        last_emit = now
                        self.fill_progress.emit(pin.name, done, total)
                        self.cache_changed.emit()
                    got = stream.read_frame()
                if alive() and got is None:
                    code = stream.returncode()
                    if code not in (0, None):
                        tail = stream.stderr_tail()
                        msg = tail.splitlines()[-1] if tail else f"ffmpeg exited with code {code}."
                        finish(False, f"Caching {pin.name} failed: {msg}")
                        return
                    eof_at = stream.next_index
            finally:
                stream.close()
            if eof_at is not None:
                break
        if not alive():
            return
        end = eof_at if eof_at is not None else b + 1
        with self._cv:
            # 영상 전체를 요청했고 0 번부터 끝까지 빈틈이 없어야 complete
            pin.complete = (whole or eof_at is not None) and a == 0 and all(fr in pin.frames for fr in range(end))
            total = min(total, end - a)
        self.fill_progress.emit(pin.name, done, total)
        finish(True, f"Cached {pin.name}: {done} frames, {format_gib(pin.nbytes)} in memory "
                     f"({time.monotonic() - t0:.1f} s).")
