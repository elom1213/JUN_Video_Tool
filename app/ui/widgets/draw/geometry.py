# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-22
"""캔버스 좌표 변환 (PLAN_DRAW_TAB 2.3, 5.2, 16장). Qt 비의존 — tests/test_draw_geometry.py 에서 검증.

flip_h / flip_v 는 보기 반전이다. 화면에서는 영상이 거울상으로 보이지만 문서의 스트로크 좌표는 늘 원본 픽셀이라,
화면 ↔ 소스 변환에서만 축을 뒤집는다 (저장 · 내보내기는 영향 없음).
"""
from __future__ import annotations

Rect = tuple[float, float, float, float]   # (x, y, w, h)


def fit_rect(widget_w: float, widget_h: float, src_w: float, src_h: float) -> Rect:
    """소스 비율을 유지해 위젯 안에 가운데 맞춤한 사각형 (레터박스)."""
    if widget_w <= 0 or widget_h <= 0 or src_w <= 0 or src_h <= 0:
        return 0.0, 0.0, 0.0, 0.0
    scale = min(widget_w / src_w, widget_h / src_h)
    w, h = src_w * scale, src_h * scale
    return (widget_w - w) / 2.0, (widget_h - h) / 2.0, w, h


def to_video(px: float, py: float, rect: Rect, src_w: float, src_h: float,
             flip_h: bool = False, flip_v: bool = False) -> tuple[float, float]:
    """화면 좌표 → 소스 픽셀 좌표. [0, src_w] × [0, src_h] 로 클램프. flip 이면 그 축을 거울상으로 되돌린다."""
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return 0.0, 0.0
    vx = (px - x) / w * src_w
    vy = (py - y) / h * src_h
    if flip_h:
        vx = src_w - vx
    if flip_v:
        vy = src_h - vy
    return min(max(vx, 0.0), float(src_w)), min(max(vy, 0.0), float(src_h))


def to_screen(vx: float, vy: float, rect: Rect, src_w: float, src_h: float,
              flip_h: bool = False, flip_v: bool = False) -> tuple[float, float]:
    """소스 픽셀 좌표 → 화면 좌표 (to_video 의 역)."""
    x, y, w, h = rect
    if src_w <= 0 or src_h <= 0:
        return x, y
    if flip_h:
        vx = src_w - vx
    if flip_v:
        vy = src_h - vy
    return x + vx / src_w * w, y + vy / src_h * h


def normalize_zoom(lo: int, hi: int, last: int) -> tuple[int, int]:
    """타임라인 확대 구간 [lo, hi] 를 0 ~ last 로 클램프하고 hi > lo (프레임 둘 이상) 를 보장한다 (18장).

    last < 1 이면 확대할 것이 없으므로 (0, max(0, last)).
    """
    last = int(last)
    if last < 1:
        return 0, max(0, last)
    lo = max(0, min(int(lo), last))
    hi = max(0, min(int(hi), last))
    if lo > hi:
        lo, hi = hi, lo
    if hi == lo:
        if hi < last:
            hi += 1
        else:
            lo -= 1
    return lo, hi


def flip_label(flip_h: bool, flip_v: bool) -> str:
    """캔버스 구석 배지 문구. 반전이 없으면 ""."""
    if flip_h and flip_v:
        return "Flipped H+V"
    if flip_h:
        return "Flipped H"
    if flip_v:
        return "Flipped V"
    return ""


def scrub_delta(x: float, x0: float, px_per_frame: int) -> int:
    """가운데 드래그 이동량 → 프레임 오프셋 (0 방향 절삭, 7장)."""
    return int((x - x0) / max(1, int(px_per_frame)))
