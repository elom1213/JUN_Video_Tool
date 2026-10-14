# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""백그라운드 로더 (PLAN 6.5, 5.8): ProbeLoader, ThumbnailLoader, SizeEstimator.

공용 QThreadPool 하나를 쓰고, 결과는 QObject 시그널로 메인 스레드에 전달한다.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QImage

from ...config import constants as C
from ...core import media_probe, thumbnail as thumb
from ...core.converters.base import BaseConverter
from ...core.models import ConvertOptions, VideoItem
from ...core.size_estimator import make_est_key, output_frames, pick_sample_ranges, scale_sample
from ...core.utils import subprocess_flags

_pool: QThreadPool | None = None


def shared_pool() -> QThreadPool:
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(C.THUMB_POOL_THREADS)
    return _pool


class _Task(QRunnable):
    """함수 하나를 풀에서 실행하는 단순 러너."""

    def __init__(self, fn: Callable[[], None]) -> None:
        super().__init__()
        self._fn = fn
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            self._fn()
        except Exception:
            pass


# ---------------------------------------------------------------------------
class ProbeLoader(QObject):
    probe_ready = Signal(object, object)    # Path, MediaInfo
    probe_failed = Signal(object, str)      # Path, error

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._pending: set[str] = set()
        self._gen = 0
        self._lock = threading.Lock()

    def request(self, path: Path) -> None:
        key = str(path)
        with self._lock:
            if key in self._pending:
                return
            self._pending.add(key)
            gen = self._gen

        def work() -> None:
            try:
                info = media_probe.probe(path)
                if gen == self._gen:
                    self.probe_ready.emit(path, info)
            except Exception as exc:
                if gen == self._gen:
                    self.probe_failed.emit(path, str(exc))
            finally:
                with self._lock:
                    self._pending.discard(key)

        shared_pool().start(_Task(work))

    def cancel_all(self) -> None:
        with self._lock:
            self._gen += 1
            self._pending.clear()


# ---------------------------------------------------------------------------
class ThumbnailLoader(QObject):
    thumbnail_ready = Signal(str, QImage)   # key, image
    thumbnail_failed = Signal(str, str)     # key, error

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: OrderedDict[str, QImage] = OrderedDict()
        self._pending: set[str] = set()
        self._lock = threading.Lock()
        self._gen = 0

    @staticmethod
    def make_key(path: Path, time_sec: float, max_width: int) -> str:
        return f"{path}|{time_sec:.3f}|{max_width}"

    def cached(self, key: str) -> QImage | None:
        with self._lock:
            img = self._cache.get(key)
            if img is not None:
                self._cache.move_to_end(key)
            return img

    def request(self, path: Path, time_sec: float, max_width: int = C.THUMB_WIDTH) -> str:
        key = self.make_key(path, time_sec, max_width)
        img = self.cached(key)
        if img is not None:
            QTimer.singleShot(0, lambda: self.thumbnail_ready.emit(key, img))
            return key
        with self._lock:
            if key in self._pending:
                return key
            self._pending.add(key)
            gen = self._gen

        def work() -> None:
            try:
                if gen != self._gen:
                    return
                data = thumb.extract_frame_png(path, time_sec, max_width)
                image = QImage.fromData(data, "PNG")
                if image.isNull():
                    raise thumb.ThumbnailError("Decoded image is empty.")
                with self._lock:
                    self._cache[key] = image
                    while len(self._cache) > C.THUMB_CACHE_SIZE:
                        self._cache.popitem(last=False)
                if gen == self._gen:
                    self.thumbnail_ready.emit(key, image)
            except Exception as exc:
                if gen == self._gen:
                    self.thumbnail_failed.emit(key, str(exc))
            finally:
                with self._lock:
                    self._pending.discard(key)

        shared_pool().start(_Task(work))
        return key

    def cancel_all(self) -> None:
        with self._lock:
            self._gen += 1
            self._pending.clear()


# ---------------------------------------------------------------------------
class SizeEstimator(QObject):
    """샘플 인코딩 기반 출력 용량 추정 (PLAN 5.8 2단계)."""

    estimate_ready = Signal(int, str, int, str)    # row, est_key, bytes, level ("sampled"|"exact")
    estimate_failed = Signal(int, str, str)        # row, est_key, error

    def __init__(self, ffmpeg_getter: Callable[[], Path | None], parent=None) -> None:
        super().__init__(parent)
        self._ffmpeg_getter = ffmpeg_getter
        self._gen = 0
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._procs: dict[str, subprocess.Popen] = {}
        self._tmp_dir = Path(tempfile.gettempdir()) / "JUN_Video_Tool"

    def temp_dir(self) -> Path:
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        return self._tmp_dir

    def request(self, row: int, item: VideoItem, converter: BaseConverter, options: ConvertOptions) -> str:
        if item.info is None:
            return ""
        rng = item.effective_range()
        key = make_est_key(item.path, rng, options)
        with self._lock:
            if key in self._active:
                return key
            self._active.add(key)
            gen = self._gen

        info = item.info
        ffmpeg = self._ffmpeg_getter()

        def work() -> None:
            try:
                if gen != self._gen or ffmpeg is None:
                    return
                out_fps = converter.output_fps(item, options)
                samples = pick_sample_ranges(rng, info.fps, out_fps)
                _, total_dur = rng.to_seconds(info.fps)
                total_frames = output_frames(total_dur, out_fps)
                sizes: list[int] = []
                frames: list[int] = []
                for i, s in enumerate(samples):
                    if gen != self._gen:
                        return
                    out_path = self.temp_dir() / f"est_{key[:16]}_{i}.gif"
                    cmd = converter.build_sample_command(ffmpeg, item, options, s, out_path)
                    if cmd is None:
                        return
                    size = self._run(key, cmd, out_path)
                    _, d = s.to_seconds(info.fps)
                    sizes.append(size)
                    frames.append(output_frames(d, out_fps))
                if gen != self._gen:
                    return
                if len(samples) == 1 and samples[0].frame_count >= rng.frame_count:
                    self.estimate_ready.emit(row, key, sizes[0], "exact")
                else:
                    self.estimate_ready.emit(row, key, scale_sample(sizes, frames, total_frames), "sampled")
            except Exception as exc:
                if gen == self._gen:
                    self.estimate_failed.emit(row, key, str(exc))
            finally:
                with self._lock:
                    self._active.discard(key)

        shared_pool().start(_Task(work))
        return key

    def _run(self, key: str, cmd: list[str], out_path: Path) -> int:
        # 진행률 출력은 필요 없으므로 -progress pipe:1 을 제거해 stdout 을 비운다
        cleaned: list[str] = []
        skip = False
        for a in cmd:
            if skip:
                skip = False
                continue
            if a == "-progress":
                skip = True
                continue
            cleaned.append(a)
        proc = subprocess.Popen(cleaned, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                creationflags=subprocess_flags())
        with self._lock:
            self._procs[key] = proc
        try:
            _, err = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise RuntimeError("Sample encode timed out.")
        finally:
            with self._lock:
                self._procs.pop(key, None)
        try:
            if proc.returncode != 0:
                tail = (err or b"").decode("utf-8", "replace").strip().splitlines()
                raise RuntimeError(tail[-1] if tail else "Sample encode failed.")
            return out_path.stat().st_size
        finally:
            try:
                if out_path.exists():
                    os.remove(out_path)
            except OSError:
                pass

    def cancel_all(self) -> None:
        with self._lock:
            self._gen += 1
            self._active.clear()
            procs = list(self._procs.values())
        for p in procs:
            try:
                p.kill()
            except Exception:
                pass

    def cleanup(self) -> None:
        self.cancel_all()
        try:
            if self._tmp_dir.exists():
                for f in self._tmp_dir.glob("est_*.gif"):
                    try:
                        f.unlink()
                    except OSError:
                        pass
        except OSError:
            pass
