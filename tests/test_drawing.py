# -*- coding: utf-8 -*-
"""Draw 탭 데이터 모델: JSON 왕복 · undo · 고스트 · 리스케일 · 지우개 (PLAN_DRAW_TAB 7장, 13.3)."""
import json
from pathlib import Path

import pytest

from app.core.drawing import (DrawingDocument, DrawingFormatError, Stroke, densify, erase_strokes, ghost_alpha,
                              ghost_frames, legacy_sidecar_path, sidecar_path)


def _doc():
    return DrawingDocument("clip.mp4", "C:/a/clip.mp4", 1920, 1080, 29.97, 360)


def _s(*pts, color="#e8734a", width=4.0):
    return Stroke(color, width, list(pts))


def test_json_roundtrip_and_rounding():
    d = _doc()
    d.add_stroke(12, _s((412.123, 388.0), (418.2, 392.666)))
    d.add_stroke(3, _s((1, 2), width=2.555))
    text = d.to_json()
    data = json.loads(text)
    assert data["format"] == "jun-video-tool-drawing" and data["version"] == 1
    assert list(data["frames"]) == ["3", "12"]
    assert data["frames"]["12"][0]["points"] == [[412.12, 388.0], [418.2, 392.67]]
    assert "opacity" not in data["frames"]["12"][0]
    back = DrawingDocument.from_json(text)
    assert back.frames_with_strokes() == [3, 12]
    assert back.strokes_at(3)[0].width == pytest.approx(2.56)
    assert back.width == 1920 and back.fps == pytest.approx(29.97) and not back.dirty


def test_version_and_format_rejected():
    with pytest.raises(DrawingFormatError):
        DrawingDocument.from_json(json.dumps({"format": "other", "version": 1}))
    with pytest.raises(DrawingFormatError):
        DrawingDocument.from_json(json.dumps({"format": "jun-video-tool-drawing", "version": 2}))
    with pytest.raises(DrawingFormatError):
        DrawingDocument.from_json("not json")


def test_broken_strokes_skipped():
    data = {"format": "jun-video-tool-drawing", "version": 1,
            "video": {"name": "a.mp4", "width": 10, "height": 10, "fps": 30, "frame_count": 5},
            "frames": {"1": [{"color": "#ffffff", "width": 2, "points": [[1, 1]]},
                             {"color": "red", "width": 2, "points": [[1, 1]]},
                             {"color": "#000000", "width": 2, "points": []}],
                       "2": []}}
    d = DrawingDocument.from_json(json.dumps(data))
    assert d.load_warnings == 2
    assert d.frames_with_strokes() == [1]
    assert len(d.strokes_at(1)) == 1


def test_undo_redo_clear_scenario():
    d = _doc()
    A, B, C = _s((0, 0)), _s((1, 1)), _s((2, 2))
    d.add_stroke(5, A)
    d.add_stroke(5, B)
    assert d.undo(5) and d.strokes_at(5) == [A]
    assert d.redo(5) and d.strokes_at(5) == [A, B]
    d.add_stroke(5, C)
    assert d.redo(5) is False
    assert d.clear_frame(5) == 3 and d.strokes_at(5) == []
    assert d.undo(5) and d.strokes_at(5) == [A, B, C]
    assert d.undo(1) is False
    assert d.dirty


def test_clear_all_undo_per_frame():
    d = _doc()
    d.add_stroke(1, _s((0, 0)))
    d.add_stroke(2, _s((0, 0)))
    d.add_stroke(2, _s((1, 1)))
    assert d.clear_all() == 3
    assert d.is_empty()
    assert d.undo(2) and len(d.strokes_at(2)) == 2
    assert d.frames_with_strokes() == [2]


def test_ghost_alpha():
    assert ghost_alpha(1, 2, 0.35) == pytest.approx(0.35)
    assert ghost_alpha(2, 2, 0.35) == pytest.approx(0.175)
    assert ghost_alpha(1, 1, 0.5) == pytest.approx(0.5)


def test_ghost_frames():
    assert ghost_frames(10, 2, 3, 359) == [(8, 2), (9, 1), (11, 1), (12, 2), (13, 3)]
    assert ghost_frames(0, 2, 1, 359) == [(1, 1)]
    assert ghost_frames(359, 1, 5, 359) == [(358, 1)]
    assert ghost_frames(5, 0, 0, 359) == []


def test_rescaled():
    d = _doc()
    d.add_stroke(0, _s((960, 540), (300, 150), width=6))
    r = d.rescaled(1280, 720)
    s = r.strokes_at(0)[0]
    assert s.points[0] == pytest.approx((640, 360))
    assert s.points[1] == pytest.approx((200, 100))
    assert s.width == pytest.approx(4)
    assert d.strokes_at(0)[0].points[0] == (960, 540)


def test_sidecar_path():
    assert sidecar_path(Path("C:/a/clip.mp4")) == Path("C:/a/.draw/clip.mp4.draw.json")
    assert legacy_sidecar_path(Path("C:/a/clip.mp4")) == Path("C:/a/clip.mp4.draw.json")


def test_prev_next_drawn_frame():
    doc = DrawingDocument("v.mp4", "C:/v.mp4", 100, 100, 30.0, 100)
    for f in (5, 20, 40):
        doc.add_stroke(f, Stroke("#ffffff", 2.0, [(1.0, 1.0)]))
    doc.add_stroke(60, Stroke("#ffffff", 2.0, [(1.0, 1.0)]))
    doc.clear_frame(60)                          # 빈 프레임은 건너뛴다
    assert doc.next_drawn_frame(0) == 5
    assert doc.next_drawn_frame(5) == 20
    assert doc.next_drawn_frame(39) == 40
    assert doc.next_drawn_frame(40) is None
    assert doc.prev_drawn_frame(40) == 20
    assert doc.prev_drawn_frame(21) == 20
    assert doc.prev_drawn_frame(5) is None
    assert doc.prev_drawn_frame(99) == 40


def test_frames_with_strokes_sorted():
    d = _doc()
    for f in (30, 2, 15):
        d.add_stroke(f, _s((0, 0)))
    d.clear_frame(15)
    assert d.frames_with_strokes() == [2, 30]


def test_densify():
    pts = densify([(0, 0), (10, 0)], 2.5)
    assert pts[0] == (0, 0) and pts[-1] == (10, 0)
    assert all(abs(b[0] - a[0]) <= 2.5 + 1e-9 for a, b in zip(pts, pts[1:]))


def test_erase_splits_stroke():
    line = _s((0, 0), (100, 0), width=2)
    out, changed = erase_strokes([line], [(50, -20), (50, 20)], radius=5)
    assert changed
    assert len(out) == 2
    left, right = out
    assert left.points[0] == (0, 0) and max(p[0] for p in left.points) < 50 - 5
    assert right.points[-1] == (100, 0) and min(p[0] for p in right.points) > 50 + 5
    assert line.points == [(0, 0), (100, 0)]          # 원본은 그대로


def test_erase_removes_whole_and_keeps_far():
    dot = _s((10, 10), width=4)
    far = _s((500, 500), (510, 500))
    out, changed = erase_strokes([dot, far], [(11, 11)], radius=3)
    assert changed and out == [far]
    out2, changed2 = erase_strokes([far], [(0, 0)], radius=3)
    assert not changed2 and out2 == [far]


def test_replace_frame_undo():
    d = _doc()
    d.add_stroke(4, _s((0, 0), (100, 0)))
    new, _ = erase_strokes(d.strokes_at(4), [(50, 0)], radius=5)
    d.replace_frame(4, new)
    assert len(d.strokes_at(4)) == 2
    assert d.undo(4) and len(d.strokes_at(4)) == 1
    d.replace_frame(4, [])
    assert d.frames_with_strokes() == []
