# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""영상 계열 변환기(GIF · MP4 …)가 공유하는 옵션 필드와 헬퍼."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...config import constants as C
from ..models import ConvertOptions, VideoItem
from ..utils import fit_size, resolve_dimensions


@dataclass
class VideoOptions(ConvertOptions):
    """크기 · 품질 · fps · 목표 용량 · 하드웨어 디코드 — 모든 영상 출력 포맷의 공통 옵션."""
    width: int | None = None
    height: int | None = None
    lock_aspect: bool = True
    anchor: str = "width"
    quality: int = 70                   # 1~100
    fps_mode: str = "auto"              # "auto" | "source" | "custom"
    fps_custom: float = 15.0
    target_size_mb: float | None = None
    max_attempts: int = 5
    hwaccel: str = C.DEFAULT_HWACCEL    # "auto" | "none"


def validate_common(o: VideoOptions) -> list[str]:
    problems: list[str] = []
    for name, val in (("Width", o.width), ("Height", o.height)):
        if val is not None and not (1 <= val <= 8192):
            problems.append(f"{name} must be between 1 and 8192.")
    if not (1 <= o.quality <= 100):
        problems.append("Quality must be between 1 and 100.")
    if o.fps_mode == "custom" and not (1 <= o.fps_custom <= 60):
        problems.append("Custom FPS must be between 1 and 60.")
    if o.target_size_mb is not None and o.target_size_mb <= 0:
        problems.append("Target size must be greater than 0 MB.")
    if o.output_dir is not None and not Path(o.output_dir).is_dir():
        problems.append(f"Output folder does not exist: {o.output_dir}")
    return problems


def scale_args(item: VideoItem, o: VideoOptions) -> tuple[int | None, int | None]:
    if item.info is None:
        return o.width, o.height
    return fit_size(item.info.width, item.info.height, o.width, o.height, o.lock_aspect, o.anchor)


def output_dimensions(item: VideoItem, o: VideoOptions) -> tuple[int, int]:
    if item.info is None:
        return 0, 0
    w, h = scale_args(item, o)
    return resolve_dimensions(item.info.width, item.info.height, w, h)


def input_args(item: VideoItem, o: VideoOptions) -> list[str]:
    """[-hwaccel auto] [-ss -t] -i <src>  — 구간이 전체면 seek 생략."""
    assert item.info is not None
    args: list[str] = []
    if o.hwaccel == "auto":
        args += ["-hwaccel", "auto"]
    rng = item.effective_range()
    if not rng.is_full(item.info):
        start_sec, dur_sec = rng.to_seconds(item.info.fps)
        args += ["-ss", f"{start_sec:.3f}", "-t", f"{dur_sec:.3f}"]
    args += ["-i", str(item.path)]
    return args


def fmt_fps(fps: float) -> str:
    if abs(fps - round(fps)) < 1e-6:
        return str(int(round(fps)))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


def even(n: int) -> int:
    """yuv420p 계열 코덱은 짝수 크기가 필요하다."""
    return max(2, n - (n % 2))
