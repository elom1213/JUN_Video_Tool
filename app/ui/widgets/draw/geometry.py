# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""캔버스 좌표 변환 (PLAN_DRAW_TAB 2.3, 5.2). Qt 비의존 — tests/test_draw_geometry.py 에서 검증."""
from __future__ import annotations

Rect = tuple[float, float, float, float]   # (x, y, w, h)


def fit_rect(widget_w: float, widget_h: float, src_w: float, src_h: float) -> Rect:
    """소스 비율을 유지해 위젯 안에 가운데 맞춤한 사각형 (레터박스)."""
    if widget_w <= 0 or widget_h <= 0 or src_w <= 0 or src_h <= 0:
        return 0.0, 0.0, 0.0, 0.0
    scale = min(widget_w / src_w, widget_h / src_h)
    w, h = src_w * scale, src_h * scale
    return (widget_w - w) / 2.0, (widget_h - h) / 2.0, w, h


def to_video(px: float, py: float, rect: Rect, src_w: float, src_h: float) -> tuple[float, float]:
    """화면 좌표 → 소스 픽셀 좌표. [0, src_w] × [0, src_h] 로 클램프."""
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return 0.0, 0.0
    vx = (px - x) / w * src_w
    vy = (py - y) / h * src_h
    return min(max(vx, 0.0), float(src_w)), min(max(vy, 0.0), float(src_h))


def to_screen(vx: float, vy: float, rect: Rect, src_w: float, src_h: float) -> tuple[float, float]:
    """소스 픽셀 좌표 → 화면 좌표."""
    x, y, w, h = rect
    if src_w <= 0 or src_h <= 0:
        return x, y
    return x + vx / src_w * w, y + vy / src_h * h


def scrub_delta(x: float, x0: float, px_per_frame: int) -> int:
    """가운데 드래그 이동량 → 프레임 오프셋 (0 방향 절삭, 7장)."""
    return int((x - x0) / max(1, int(px_per_frame)))
