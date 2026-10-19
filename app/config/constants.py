# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-19
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
    ".mpg", ".mpeg", ".flv", ".ts", ".mts", ".gif",
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
    CANVAS_BG = "#1a1a1a"
    GHOST_BEFORE = "#e05555"    # 예약 (고스트 틴트, PLAN_DRAW_TAB 11장)
    GHOST_AFTER = "#4aa3e8"


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

# ---------------------------------------------------------------------------
# Draw 탭 (PLAN_DRAW_TAB 4.3, 13.6)
# ---------------------------------------------------------------------------
DRAW_DECODE_SCALES = (100, 75, 50, 25)   # 디코드 해상도 = 원본의 이 % (Draw 탭 Resolution)
DRAW_DECODE_SCALE_DEFAULT = 100
DRAW_PIPE_BUFFER_BYTES = 1 << 20  # 디코더 stdout 파이프 버퍼 (Windows 기본 4 KB 는 4K 에서 4 배 느리다)
DRAW_CACHE_BUDGET_MB = 2048       # 일반(LRU) 프레임 캐시 메모리 상한. 전체 캐시는 따로 잡는다
# 전체 캐시 (Cache Whole Video): 시스템에 남겨 둘 여유 메모리 = max(최소 GB, 전체 RAM x 비율)
DRAW_FULL_CACHE_RESERVE_MIN_GB = 4.0
DRAW_FULL_CACHE_RESERVE_RATIO = 0.15
DRAW_FULL_CACHE_MEM_CHECK_EVERY = 32   # 이 프레임 수마다 남은 메모리를 다시 확인 (다른 앱이 먹으면 멈춘다)
DRAW_FULL_CACHE_PROGRESS_MS = 200      # 진행 신호 최소 간격
DRAW_PREFETCH_FORWARD = 24        # 시크 뒤 앞으로 미리 디코드할 프레임 수
DRAW_PREFETCH_BACKWARD = 48       # 뒤로 갈 때 이만큼 앞에서 시작해 디코드 (어차피 키프레임부터 디코드하므로 넉넉히)
DRAW_PLAY_AHEAD = 48              # 재생 중 디코더가 표시 프레임보다 앞서 가도 되는 최대 프레임 수
DRAW_SCRUB_PX_PER_FRAME = 8       # 가운데 드래그 스크럽 감도
DRAW_SCRUB_PX_MIN, DRAW_SCRUB_PX_MAX = 2, 40
DRAW_WIDTH_DEFAULT = 4.0          # 브러시 두께 (소스 px)
DRAW_WIDTH_MIN, DRAW_WIDTH_MAX = 1.0, 64.0
DRAW_COLOR_DEFAULT = "#e8734a"
DRAW_SWATCHES = ("#e8734a", "#ffffff", "#000000", "#e05555", "#e0b955", "#6cc070", "#4aa3e8", "#c06ce0")
DRAW_MIN_POINT_DIST_PX = 1.5      # 화면 px. 이보다 가까운 점은 버린다
DRAW_ERASER_DEFAULT = 32.0        # 지우개 지름 (소스 px)
DRAW_ERASER_MIN, DRAW_ERASER_MAX = 4.0, 256.0
GHOST_BEFORE_DEFAULT = 2
GHOST_AFTER_DEFAULT = 2
GHOST_SPAN_MAX = 30
GHOST_OPACITY_DEFAULT = 0.35      # 0.05 ~ 1.0
DRAW_FILE_SUFFIX = ".draw.json"
DRAW_DIR_NAME = ".draw"             # 드로잉 파일을 모아 두는 하위 폴더 (영상 폴더 안)
DRAW_FORMAT_NAME = "jun-video-tool-drawing"
DRAW_FORMAT_VERSION = 1

# 오디오 (PLAN_DRAW_TAB 13.1)
AUDIO_RATE = 48000
AUDIO_CHANNELS = 2
AUDIO_PUSH_INTERVAL_MS = 10
DRAW_VOLUME_DEFAULT = 80

# 그림 입힌 영상 내보내기 (PLAN_DRAW_TAB 13.4)
EXPORT_SUFFIX = "_draw"
