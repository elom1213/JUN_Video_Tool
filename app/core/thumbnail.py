# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""정지 프레임 추출 (PLAN 5.3). ffmpeg image2pipe → PNG bytes."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .ffmpeg_locator import find_ffmpeg
from .models import MediaInfo
from .utils import subprocess_flags


class ThumbnailError(Exception):
    pass


def representative_time(info: MediaInfo) -> float:
    """대표 썸네일 시각 = min(1.0, duration * 0.1)."""
    return max(0.0, min(1.0, info.duration * 0.1))


def clamp_time(time_sec: float, info: MediaInfo) -> float:
    """마지막 프레임 근처에서 빈 출력이 나지 않게 보정."""
    if info.fps > 0:
        limit = max(0.0, info.duration - 1.0 / info.fps)
    else:
        limit = max(0.0, info.duration - 0.05)
    return max(0.0, min(time_sec, limit))


def extract_frame_png(path: Path, time_sec: float, max_width: int = 320, timeout: float = 15.0) -> bytes:
    """time_sec 의 프레임을 PNG bytes 로."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise ThumbnailError("ffmpeg not found.")
    cmd = [
        str(ffmpeg), "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, time_sec):.3f}", "-i", str(path),
        "-frames:v", "1", "-vf", f"scale='min({int(max_width)},iw)':-2",
        "-f", "image2pipe", "-vcodec", "png", "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=subprocess_flags())
    except subprocess.TimeoutExpired as exc:
        raise ThumbnailError("Thumbnail extraction timed out.") from exc
    if out.returncode != 0 or not out.stdout:
        err = (out.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        raise ThumbnailError(err[-1] if err else "No frame produced.")
    return out.stdout
