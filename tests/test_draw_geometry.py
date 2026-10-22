# -*- coding: utf-8 -*-
"""캔버스 좌표 변환 · 스크럽 (PLAN_DRAW_TAB 7장)."""
from app.ui.widgets.draw.geometry import fit_rect, flip_label, normalize_zoom, scrub_delta, to_screen, to_video


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


def test_flip_mirrors_axes():
    r = (100.0, 50.0, 640.0, 360.0)
    # 화면 왼쪽 위 모서리는 좌우 반전이면 소스 오른쪽 위, 상하 반전이면 소스 왼쪽 아래, 둘 다면 오른쪽 아래
    assert to_video(100, 50, r, 1920, 1080, flip_h=True) == (1920.0, 0.0)
    assert to_video(100, 50, r, 1920, 1080, flip_v=True) == (0.0, 1080.0)
    assert to_video(100, 50, r, 1920, 1080, True, True) == (1920.0, 1080.0)
    # 가운데는 반전해도 가운데
    assert to_video(420, 230, r, 1920, 1080, True, True) == (960.0, 540.0)
    # 화면 x = 100 + 160 (1/4 지점) → 좌우 반전이면 소스 3/4 지점
    assert to_video(260, 50, r, 1920, 1080, flip_h=True) == (1440.0, 0.0)


def test_flip_round_trip():
    r = (100.0, 50.0, 640.0, 360.0)
    for fh, fv in ((False, False), (True, False), (False, True), (True, True)):
        for vx, vy in ((0.0, 0.0), (1920.0, 1080.0), (300.0, 900.0), (960.0, 540.0)):
            sx, sy = to_screen(vx, vy, r, 1920, 1080, fh, fv)
            bx, by = to_video(sx, sy, r, 1920, 1080, fh, fv)
            assert abs(bx - vx) < 1e-9 and abs(by - vy) < 1e-9, (fh, fv, vx, vy)


def test_flip_clamps_after_mirroring():
    r = (100.0, 50.0, 640.0, 360.0)
    assert to_video(5000, 5000, r, 1920, 1080, True, True) == (0.0, 0.0)
    assert to_video(-5000, -5000, r, 1920, 1080, True, True) == (1920.0, 1080.0)


def test_flip_label():
    assert flip_label(False, False) == ""
    assert flip_label(True, False) == "Flipped H"
    assert flip_label(False, True) == "Flipped V"
    assert flip_label(True, True) == "Flipped H+V"


def test_normalize_zoom():
    assert normalize_zoom(50, 70, 999) == (50, 70)
    assert normalize_zoom(70, 50, 999) == (50, 70)            # 뒤집힌 입력
    assert normalize_zoom(-10, 5000, 999) == (0, 999)          # 클램프
    assert normalize_zoom(60, 60, 999) == (60, 61)             # 한 프레임은 못 보여 준다 → 둘
    assert normalize_zoom(999, 999, 999) == (998, 999)         # 끝에서는 시작을 물린다
    assert normalize_zoom(0, 0, 0) == (0, 0)                   # 프레임 하나짜리 영상
    assert normalize_zoom(3, 7, -1) == (0, 0)                  # 영상 없음
