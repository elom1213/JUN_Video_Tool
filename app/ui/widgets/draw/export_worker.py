# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""그림 입힌 영상 내보내기 워커 (PLAN_DRAW_TAB 13.4).

ffmpeg 한 프로세스가 원본 디코드 · 스케일 · 합성 · 인코딩을 하고, 이 스레드는 출력 크기의 RGBA 오버레이를
프레임 0..N-1 순서로 stdin 에 쓴다. 그림이 없는 프레임은 미리 만든 투명 바이트를 재사용한다.
목표 용량 재시도(degrade_for_retry)와 hwaccel 폴백은 job_runner 와 같은 규칙이다.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage, QPainter

from ....core.burnin import build_burnin_command, overlay_size
from ....core.converters.base import BaseConverter
from ....core.drawing import DrawingDocument, ghost_frames
from ....core.job_runner import _HWACCEL_FAIL_MARKERS
from ....core.models import ConvertOptions, VideoItem
from ....core.utils import human_size, subprocess_flags
from .stroke_painter import paint_frame


class ExportWorker(QThread):
    progress = Signal(int)                         # 0 ~ 100
    log = Signal(str)
    finished_ok = Signal(object, int, float)       # path, size, elapsed
    failed = Signal(str)

    def __init__(self, ffmpeg: Path, item: VideoItem, converter: BaseConverter, options: ConvertOptions,
                 out_path: Path, doc: DrawingDocument, ghost: tuple[bool, int, int, float] | None,
                 parent=None) -> None:
        super().__init__(parent)
        self._ffmpeg = ffmpeg
        self._item = item
        self._conv = converter
        self._opts = options
        self._out = Path(out_path)
        self._doc = doc
        self._ghost = ghost if ghost and ghost[0] else None
        self._cancel = False
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel = True
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    self._proc.kill()
                except OSError:
                    pass

    # ------------------------------------------------------------------ 오버레이
    def _has_drawing(self, frame: int) -> bool:
        if self._doc.strokes_at(frame):
            return True
        if self._ghost is not None:
            _on, before, after, _op = self._ghost
            return any(self._doc.strokes_at(i) for i, _d in ghost_frames(frame, before, after, frame + after))
        return False

    def _overlay(self, frame: int, w: int, h: int, scale: float) -> bytes:
        img = QImage(w, h, QImage.Format.Format_RGBA8888)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        paint_frame(p, self._doc, frame, scale, ghost=self._ghost)
        p.end()
        return bytes(img.constBits())[: w * h * 4]

    # ------------------------------------------------------------------ 실행
    def run(self) -> None:
        info = self._item.info
        if info is None:
            self.failed.emit("No media info.")
            return
        t0 = time.time()
        opts = self._opts
        target = self._conv.target_size_bytes(opts) if self._conv.supports_target_size() else None
        attempt = 0
        hw_retry_done = False
        name = self._out.name
        while True:
            attempt += 1
            rc, err = self._run_once(opts)
            if self._cancel:
                self._remove()
                self.failed.emit("Canceled.")
                return
            if rc != 0:
                if (getattr(opts, "hwaccel", "none") == "auto" and not hw_retry_done
                        and any(m.lower() in err.lower() for m in _HWACCEL_FAIL_MARKERS)):
                    hw_retry_done = True
                    opts = replace(opts, hwaccel="none")
                    self.log.emit(f"[{name}] Hardware decode failed, retrying with software decode.")
                    attempt -= 1
                    continue
                self._remove()
                self.failed.emit(err.splitlines()[-1] if err else f"ffmpeg exited with code {rc}.")
                return
            try:
                size = self._out.stat().st_size
            except OSError:
                self.failed.emit("Output file was not created.")
                return
            if target is not None and size > target:
                new_opts = self._conv.degrade_for_retry(opts, attempt, size, target, info.width, info.fps)
                if new_opts is not None:
                    self.log.emit(f"[{name}] {human_size(size)} > target {human_size(target)}, retrying "
                                  f"({attempt + 1}/{getattr(opts, 'max_attempts', '?')}).")
                    opts = new_opts
                    continue
                self.log.emit(f"[{name}] Target size not reached ({human_size(size)} > {human_size(target)}).")
            self.progress.emit(100)
            self.finished_ok.emit(self._out, size, time.time() - t0)
            return

    def _run_once(self, opts: ConvertOptions) -> tuple[int, str]:
        info = self._item.info
        assert info is not None
        w, h = overlay_size(self._item, self._conv, opts)
        scale = h / info.height if info.height else 1.0
        cmd = build_burnin_command(self._ffmpeg, self._item, self._conv, opts, self._out)
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    creationflags=subprocess_flags())
        except OSError as exc:
            return 1, f"Failed to start ffmpeg: {exc}"
        with self._lock:
            self._proc = proc
        err_tail: deque[str] = deque(maxlen=40)
        dur = info.duration if info.duration > 0 else info.frame_count / max(info.fps, 1e-6)

        def drain_err() -> None:
            assert proc.stderr is not None
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    err_tail.append(line)

        def read_progress() -> None:
            assert proc.stdout is not None
            last = -1
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("out_time_us=") and dur > 0:
                    try:
                        pct = int(max(0, min(99, int(line.split("=", 1)[1]) / 1e6 / dur * 100)))
                    except ValueError:
                        continue
                    if pct != last:
                        last = pct
                        self.progress.emit(pct)

        threads = [threading.Thread(target=drain_err, daemon=True), threading.Thread(target=read_progress, daemon=True)]
        for t in threads:
            t.start()
        blank = bytes(w * h * 4)
        stdin = proc.stdin
        assert stdin is not None
        try:
            for f in range(max(1, info.frame_count)):
                if self._cancel:
                    break
                data = self._overlay(f, w, h, scale) if self._has_drawing(f) else blank
                stdin.write(data)
        except (BrokenPipeError, OSError):
            pass    # ffmpeg 가 먼저 끝났거나 죽음 → 종료 코드로 판정
        finally:
            try:
                stdin.close()
            except OSError:
                pass
        rc = proc.wait()
        for t in threads:
            t.join(timeout=5)
        with self._lock:
            self._proc = None
        return rc, "\n".join(err_tail)

    def _remove(self) -> None:
        try:
            if self._out.exists():
                os.remove(self._out)
        except OSError:
            pass
