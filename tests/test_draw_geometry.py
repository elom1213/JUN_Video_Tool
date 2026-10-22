# -*- coding: utf-8 -*-
"""캔버스 좌표 변환 · 스크럽 · 보기 배율 (PLAN_DRAW_TAB 7장, 19장)."""
from app.ui.widgets.draw.geometry import (clamp_pan, fit_rect, flip_label, normalize_zoom, scrub_delta, to_screen,
                                          to_video, view_rect, zoom_about, zoom_label)


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


# ---------------------------------------------------------------- 보기 배율 · 이동 (19장). 위젯 800x600, 소스 1920x1080 → 맞춤 (0, 75, 800, 450)
def test_view_rect_identity_at_fit():
    assert view_rect(800, 600, 1920, 1080) == fit_rect(800, 600, 1920, 1080)
    assert view_rect(800, 600, 1920, 1080, 1.0, 500, 500) == fit_rect(800, 600, 1920, 1080)   # 맞춤이면 이동 없음
    assert view_rect(0, 600, 1920, 1080, 2.0) == (0.0, 0.0, 0.0, 0.0)
    assert view_rect(800, 600, 1920, 1080, 0.0) == (0.0, 0.0, 0.0, 0.0)


def test_view_rect_zoom_centers_and_clamps():
    # 2배: 1600x900, 가운데 → (-400, -150)
    assert view_rect(800, 600, 1920, 1080, 2.0) == (-400.0, -150.0, 1600.0, 900.0)
    # 이동은 빈 공간이 안 생기는 범위까지만: x ∈ [-800, 0], y ∈ [-300, 0]
    assert view_rect(800, 600, 1920, 1080, 2.0, 1000, 1000)[:2] == (0.0, 0.0)
    assert view_rect(800, 600, 1920, 1080, 2.0, -1000, -1000)[:2] == (-800.0, -300.0)
    assert view_rect(800, 600, 1920, 1080, 2.0, -100, 50)[:2] == (-500.0, -100.0)
    # 1.2배: 960x540 — 세로는 위젯보다 작으니 가운데 고정, 가로만 움직인다
    x, y, w, h = view_rect(800, 600, 1920, 1080, 1.2, -500, -500)
    assert (x, w) == (-160.0, 960.0) and abs(y - 30.0) < 1e-9 and abs(h - 540.0) < 1e-9
    # 축소: 가운데
    assert view_rect(800, 600, 1920, 1080, 0.5, 300, 300) == (200.0, 187.5, 400.0, 225.0)


def test_clamp_pan_returns_effective_pan():
    assert clamp_pan(800, 600, 1920, 1080, 2.0, 1000, 1000) == (400.0, 150.0)   # y: -150 → 0 이 한계
    assert clamp_pan(800, 600, 1920, 1080, 2.0, -100, 50) == (-100.0, 50.0)
    assert clamp_pan(800, 600, 1920, 1080, 1.0, 123, 456) == (0.0, 0.0)
    assert clamp_pan(800, 600, 1920, 1080, 1.2, -500, -500) == (-80.0, 0.0)
    assert clamp_pan(0, 0, 1920, 1080, 2.0, 1, 1) == (0.0, 0.0)


def test_zoom_about_keeps_anchor_fixed():
    W, H, SW, SH = 800, 600, 1920, 1080
    cases = [(1.0, 0.0, 0.0, 2.0, 400, 300), (1.0, 0.0, 0.0, 2.0, 200, 300), (2.0, 0.0, 0.0, 4.0, 100, 100),
             (2.0, -100.0, 50.0, 1.5, 700, 200), (4.0, 300.0, 200.0, 2.0, 400, 300), (1.0, 0.0, 0.0, 0.5, 400, 300)]
    for zoom, px, py, new_zoom, ax, ay in cases:
        before = to_video(ax, ay, view_rect(W, H, SW, SH, zoom, px, py), SW, SH)
        npx, npy = zoom_about(W, H, SW, SH, zoom, px, py, new_zoom, ax, ay)
        after = to_video(ax, ay, view_rect(W, H, SW, SH, new_zoom, npx, npy), SW, SH)
        # 새 배율에서 클램프에 안 걸리는 경우만 자리가 그대로다 (위 케이스는 모두 범위 안)
        assert abs(after[0] - before[0]) < 1e-6 and abs(after[1] - before[1]) < 1e-6, (zoom, new_zoom, ax, ay)
    # 가운데를 기준으로 하면 이동은 그대로 0
    assert zoom_about(W, H, SW, SH, 1.0, 0.0, 0.0, 3.0, 400, 300) == (0.0, 0.0)
    # 레터박스 가장자리 근처를 기준으로 키우면 그 자리를 지키려다 위에 빈 공간이 생긴다 → view_rect 가 가장자리에 붙인다
    npx, npy = zoom_about(W, H, SW, SH, 1.0, 0.0, 0.0, 2.0, 100, 100)
    assert npy > 0 and view_rect(W, H, SW, SH, 2.0, npx, npy)[1] == 0.0
    assert zoom_about(W, H, SW, SH, 0.0, 0.0, 0.0, 2.0, 100, 100) == (0.0, 0.0)


def test_zoom_label():
    assert zoom_label(1.0) == ""
    assert zoom_label(1.0 + 1e-9) == ""
    assert zoom_label(2.0) == "200%"
    assert zoom_label(1.25) == "125%"
    assert zoom_label(0.5) == "50%"
