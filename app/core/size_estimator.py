# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""출력 파일 용량 추정의 순수 함수 (PLAN 5.8). Qt 쪽 비동기 실행은 ui/widgets/loaders.py."""
from __future__ import annotations

import hashlib
import math
from dataclasses import asdict
from pathlib import Path

from ..config import constants as C
from .models import ConvertOptions, FrameRange


def output_frames(dur_sec: float, out_fps: float) -> int:
    """출력 GIF 프레임 수."""
    return max(1, int(round(dur_sec * out_fps)))


def make_est_key(path: Path, rng: FrameRange, options: ConvertOptions) -> str:
    """(경로 + 옵션 + 구간) 해시. 출력 경로 관련 필드는 용량과 무관하므로 제외."""
    d = asdict(options)
    for k in ("output_dir", "suffix", "overwrite"):
        d.pop(k, None)
    payload = f"{path}|{rng.start_frame}:{rng.end_frame}|{sorted(d.items())!r}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def pick_sample_ranges(rng: FrameRange, src_fps: float, out_fps: float,
                       n: int = C.SAMPLE_SEGMENTS, out_frames_each: int = C.SAMPLE_OUT_FRAMES) -> list[FrameRange]:
    """구간을 n 등분한 각 조각의 중앙에서 out_frames_each 개의 출력 프레임이 나올 만큼 src 프레임을 자른다.

    샘플 합이 전체의 SAMPLE_FULL_THRESHOLD 이상이면 전체 구간 1개 (= 정확 측정).
    """
    total = rng.frame_count
    if src_fps <= 0 or out_fps <= 0 or total <= 0:
        return [rng]
    src_per_sample = int(math.ceil(out_frames_each * src_fps / out_fps))
    src_per_sample = max(1, src_per_sample)
    if n * src_per_sample >= total * C.SAMPLE_FULL_THRESHOLD:
        return [FrameRange(rng.start_frame, rng.end_frame)]
    seg = total / n
    result: list[FrameRange] = []
    for i in range(n):
        center = rng.start_frame + int(seg * i + seg / 2)
        s = center - src_per_sample // 2
        e = s + src_per_sample - 1
        if s < rng.start_frame:
            s, e = rng.start_frame, rng.start_frame + src_per_sample - 1
        if e > rng.end_frame:
            e = rng.end_frame
            s = max(rng.start_frame, e - src_per_sample + 1)
        result.append(FrameRange(s, e))
    return result


def scale_sample(sample_bytes: list[int], sample_out_frames: list[int], total_out_frames: int) -> int:
    """per_frame = sum(bytes) / sum(frames) ; 800 + per_frame * total."""
    frames = sum(sample_out_frames)
    if frames <= 0:
        return C.HEURISTIC_BASE_BYTES
    per_frame = sum(sample_bytes) / frames
    return int(C.HEURISTIC_BASE_BYTES + round(per_frame * total_out_frames))


def heuristic_gif_size(out_frames: int, out_w: int, out_h: int, max_colors: int, dither_family: str) -> int:
    """PLAN 5.8 1단계 공식."""
    bpp = C.HEURISTIC_BPP_MIN + C.HEURISTIC_BPP_RANGE * (max_colors / 256.0)
    mult = C.HEURISTIC_DITHER_MULT.get(dither_family, 1.0)
    return int(C.HEURISTIC_BASE_BYTES + out_frames * out_w * out_h * bpp * mult)
