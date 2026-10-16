# -*- coding: utf-8 -*-
"""캔버스 좌표 변환 · 스크럽 (PLAN_DRAW_TAB 7장)."""
from app.ui.widgets.draw.geometry import fit_rect, scrub_delta, to_screen, to_video


def test_fit_rect_letterbox():
    x, y, w, h = fit_rect(800, 600, 1920, 1080)
    assert (x, w) == (0.0, 800.0)
    assert abs(h - 450.0) < 1e-9 and abs(y - 75.0) < 1e-9
    x, y, w, h = fit_rect(1000, 360, 1920, 1080)
    assert (y, h) == (0.0, 360.0) and abs(w - 640.0) < 1e-9 and abs(x - 180.0) < 1e-9


def test_fit_rect_degenerate():
    assert fit_rect(0, 100, 1920, 1080) == (0.0, 0.0, 0.0, 0.0)
    assert fit_rect(100, 100, 0, 0) == (0.0, 0.0, 0.0, 0.0)


def test_to_video_and_back():
    r = (100.0, 50.0, 640.0, 360.0)
    assert to_video(420, 230, r, 1920, 1080) == (960.0, 540.0)
    assert to_screen(960.0, 540.0, r, 1920, 1080) == (420.0, 230.0)


def test_to_video_clamps():
    r = (100.0, 50.0, 640.0, 360.0)
    assert to_video(0, 0, r, 1920, 1080) == (0.0, 0.0)
    assert to_video(5000, 5000, r, 1920, 1080) == (1920.0, 1080.0)


def test_scrub_delta_truncates_toward_zero():
    assert scrub_delta(-23, 0, 8) == -2
    assert scrub_delta(23, 0, 8) == 2
    assert scrub_delta(7, 0, 8) == 0
    assert scrub_delta(10, 0, 0) == 10   # 감도 0 은 1 로 취급
