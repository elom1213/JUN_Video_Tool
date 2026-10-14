# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""전역 상수 · 품질 매핑 · 휴리스틱 계수.

PySide6 를 import 하지 않는다 (core 와 테스트에서 공유).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# 지원 확장자
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv",
    ".mpg", ".mpeg", ".flv", ".ts", ".mts",
})

# ---------------------------------------------------------------------------
# UI 치수 · 색상 (델리게이트가 qss 와 같은 색을 쓰기 위해 여기에 둔다)
# ---------------------------------------------------------------------------
THUMB_WIDTH = 320          # 리스트 썸네일 추출 폭 (px)
PREVIEW_WIDTH = 160        # 구간 시작/끝 미리보기 폭 (px)
THUMB_CELL_W = 180
THUMB_CELL_H = 150
THUMB_IMG_W = 160
THUMB_IMG_H = 90
LIST_ROW_H = 28


class Colors:
    BG = "#2b2b2b"
    PANEL = "#353535"
    BORDER = "#444444"
    TEXT = "#e6e6e6"
    TEXT_DIM = "#9a9a9a"
    ACCENT = "#e8734a"
    OK = "#6cc070"
    FAIL = "#e05555"
    WARN = "#e0b955"
    TRACK = "#555555"
    SELECTION = "#4a3a34"


# ---------------------------------------------------------------------------
# GIF 품질 매핑 (PLAN 5.6)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GifParams:
    """품질 슬라이더 값에서 유도된 ffmpeg 인코딩 파라미터."""
    fps: float
    max_colors: int
    dither: str          # "none" | "bayer:bayer_scale=3" | "sierra2_4a"
    stats_mode: str      # "full" | "diff"

    @property
    def dither_family(self) -> str:
        """휴리스틱 계수 조회용 디더링 종류 이름."""
        if self.dither.startswith("bayer"):
            return "bayer"
        return self.dither


def round_half_up(x: float) -> int:
    """Python round() 는 은행가 반올림(12.5→12)이므로 표의 공식에는 반올림(.5 올림)을 쓴다."""
    return int(math.floor(x + 0.5))


def quality_fps(q: int, src_fps: float) -> float:
    """품질 → 자동 fps. 소스 fps 를 넘지 않는다."""
    q = max(1, min(100, int(q)))
    auto = 5 + round_half_up(q * 0.25)
    return float(min(src_fps, auto)) if src_fps > 0 else float(auto)


def gif_params_for_quality(q: int, src_fps: float) -> GifParams:
    """PLAN 5.6 표의 공식 그대로."""
    q = max(1, min(100, int(q)))
    fps = quality_fps(q, src_fps)
    max_colors = min(256, 32 + round_half_up(q * 2.24))
    if q < 40:
        dither = "none"
    elif q <= 75:
        dither = "bayer:bayer_scale=3"
    else:
        dither = "sierra2_4a"
    stats_mode = "diff" if q > 75 else "full"
    return GifParams(fps=fps, max_colors=max_colors, dither=dither, stats_mode=stats_mode)


# ---------------------------------------------------------------------------
# 출력 파일 용량 휴리스틱 (PLAN 5.8)
# ---------------------------------------------------------------------------
HEURISTIC_BASE_BYTES = 800
HEURISTIC_BPP_MIN = 0.08
HEURISTIC_BPP_RANGE = 0.42
HEURISTIC_DITHER_MULT = {"none": 0.80, "bayer": 1.00, "sierra2_4a": 1.35}

# 샘플 추정
SAMPLE_SEGMENTS = 2
SAMPLE_OUT_FRAMES = 24
SAMPLE_FULL_THRESHOLD = 0.70

# 변환 전 경고 임계 (출력 프레임 수 × 폭 × 높이)
LARGE_OUTPUT_PIXELS = 400_000_000

# 출력 경로 길이 경고 (Windows MAX_PATH 대비)
MAX_OUTPUT_PATH_LEN = 240

# 기본 설정
DEFAULT_CONCURRENCY = 2
MAX_CONCURRENCY = 4
DEFAULT_HWACCEL = "auto"
ESTIMATE_DEBOUNCE_MS = 500
PREVIEW_DEBOUNCE_MS = 200
THUMB_POOL_THREADS = 4
THUMB_CACHE_SIZE = 500
