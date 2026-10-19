# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""변환 작업 실행기 (PLAN 5.7). core 에서 유일하게 PySide6.QtCore 를 쓴다."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .converters.base import BaseConverter
from .models import ConvertJob, ConvertResult
from .utils import subprocess_flags, tail_lines, human_size

_HWACCEL_FAIL_MARKERS = ("hwaccel", "Failed to initialise", "Failed to initialize", "No device available",
                         "Device creation failed", "hardware")


class JobRunner(QThread):
    job_started = Signal(int)                 # row
    job_progress = Signal(int, int)           # row, percent
    job_finished = Signal(int, object)        # row, ConvertResult
    all_finished = Signal(int, int, int)      # ok, failed, canceled
    log = Signal(str)

    def __init__(self, ffmpeg: Path, converter: BaseConverter,
                 jobs: list[tuple[int, ConvertJob]], concurrency: int = 2, parent=None) -> None:
        super().__init__(parent)
        self._ffmpeg = ffmpeg
        self._conv = converter
        self._jobs = jobs
        self._concurrency = max(1, int(concurrency))
        self._cancel = False
        self._procs: dict[int, subprocess.Popen] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 제어
    def cancel(self) -> None:
        self._cancel = True
        with self._lock:
            procs = list(self._procs.values())
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass

    # ------------------------------------------------------------------ 실행
    def run(self) -> None:
        ok = failed = canceled = 0
        futures: dict[Future, int] = {}
        with ThreadPoolExecutor(max_workers=self._concurrency) as pool:
            for row, job in self._jobs:
                fut = pool.submit(self._run_guarded, row, job)
                futures[fut] = row
            for fut in futures:
                res: ConvertResult = fut.result()
                if res.canceled:
                    canceled += 1
                elif res.ok:
                    ok += 1
                else:
                    failed += 1
        self.all_finished.emit(ok, failed, canceled)

    def _run_guarded(self, row: int, job: ConvertJob) -> ConvertResult:
        if self._cancel:
            res = ConvertResult(job=job, ok=False, canceled=True, message="Canceled")
            self.job_finished.emit(row, res)
            return res
        self.job_started.emit(row)
        try:
            res = self._run_one(row, job)
        except Exception as exc:  # 방어: 워커 예외가 전체를 멈추지 않게
            res = ConvertResult(job=job, ok=False, error=str(exc), message="Failed")
        self.job_finished.emit(row, res)
        return res

    def _run_one(self, row: int, job: ConvertJob) -> ConvertResult:
        name = job.item.path.name
        info = job.item.info
        assert info is not None
        opts = job.options
        target = self._conv.target_size_bytes(opts) if self._conv.supports_target_size() else None
        attempt = 0
        t0 = time.time()
        hw_retry_done = False
        last_size = 0
        while True:
            attempt += 1
            rng = job.item.effective_range()
            _, dur_sec = rng.to_seconds(info.fps)
            cmd = self._conv.build_command(self._ffmpeg, job.item, opts, job.output_path)
            rc, stderr_tail = self._exec(row, cmd, dur_sec)

            if self._cancel:
                self._remove(job.output_path)
                return ConvertResult(job=job, ok=False, canceled=True, attempts=attempt, message="Canceled",
                                     elapsed=time.time() - t0)

            if rc != 0:
                hw = getattr(opts, "hwaccel", "none")
                if hw == "auto" and not hw_retry_done and any(m.lower() in stderr_tail.lower() for m in _HWACCEL_FAIL_MARKERS):
                    hw_retry_done = True
                    opts = replace(opts, hwaccel="none")
                    self.log.emit(f"[{name}] Hardware decode failed, retrying with software decode.")
                    attempt -= 1
                    continue
                self._remove(job.output_path)
                return ConvertResult(job=job, ok=False, error=stderr_tail or f"ffmpeg exited with code {rc}",
                                     attempts=attempt, message="Failed", elapsed=time.time() - t0)

            try:
                last_size = job.output_path.stat().st_size
            except OSError:
                return ConvertResult(job=job, ok=False, error="Output file was not created.",
                                     attempts=attempt, message="Failed", elapsed=time.time() - t0)

            if target is not None and last_size > target:
                src_w = info.width
                new_opts = self._conv.degrade_for_retry(opts, attempt, last_size, target, src_w, info.fps)  # type: ignore[call-arg]
                if new_opts is not None:
                    self.log.emit(f"[{name}] {human_size(last_size)} > target {human_size(target)}, "
                                  f"retrying ({attempt + 1}/{getattr(opts, 'max_attempts', '?')}).")
                    opts = new_opts
                    continue
                msg = f"Target size not reached ({human_size(last_size)} > {human_size(target)})"
                return ConvertResult(job=job, ok=True, output_size=last_size, attempts=attempt,
                                     message=msg, elapsed=time.time() - t0)

            res = ConvertResult(job=job, ok=True, output_size=last_size, attempts=attempt,
                                message=human_size(last_size), elapsed=time.time() - t0)
            # 출력 검사 (WAV: JUN_JALI 규칙). error 면 실패로 표시하되 파일은 남긴다 — 무엇이 문제인지 볼 수 있게
            try:
                res.check_level, res.check_message = self._conv.post_check(job.output_path, job.item, opts)
            except Exception as exc:
                res.check_level, res.check_message = "error", f"Output check failed: {exc}"
            if res.check_level == "error":
                res.ok = False
                res.error = res.check_message
                res.message = "Failed"
            return res

    # ------------------------------------------------------------------ 프로세스
    def _exec(self, row: int, cmd: list[str], dur_sec: float) -> tuple[int, str]:
        """ffmpeg 실행. (returncode, stderr tail)."""
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                encoding="utf-8", errors="replace", creationflags=subprocess_flags(),
            )
        except OSError as exc:
            return 1, f"Failed to start ffmpeg: {exc}"
        with self._lock:
            self._procs[row] = proc

        stderr_buf: list[str] = []

        def _drain() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_buf.append(line.rstrip("\n"))
                if len(stderr_buf) > 200:
                    del stderr_buf[:100]

        t = threading.Thread(target=_drain, daemon=True)
        t.start()

        last_pct = -1
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    us = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if dur_sec > 0:
                    pct = int(max(0, min(100, us / 1_000_000 / dur_sec * 100)))
                    if pct != last_pct:
                        last_pct = pct
                        self.job_progress.emit(row, pct)
            elif line == "progress=end":
                self.job_progress.emit(row, 100)
        rc = proc.wait()
        t.join(timeout=5)
        with self._lock:
            self._procs.pop(row, None)
        return rc, tail_lines("\n".join(stderr_buf), 20)

    @staticmethod
    def _remove(path: Path) -> None:
        try:
            if path.exists():
                os.remove(path)
        except OSError:
            pass
