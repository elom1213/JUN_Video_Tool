# -*- coding: utf-8 -*-
"""PLAN 7장 표의 utils / models 케이스."""
from pathlib import Path

import pytest

from app.config.constants import gif_params_for_quality
from app.core.models import FrameRange, MediaInfo
from app.core.utils import (fit_size, format_timecode, frame_to_sec, human_size, make_output_path,
                            resolve_dimensions, sec_to_frame)


def _info(frames=360, fps=30.0):
    return MediaInfo(width=1920, height=1080, fps=fps, duration=frames / fps, frame_count=frames,
                     codec="h264", size_bytes=1000)


def test_frame_sec_roundtrip():
    assert frame_to_sec(90, 29.97) == pytest.approx(3.003, abs=1e-3)
    assert sec_to_frame(3.003, 29.97) == 90


def test_format_timecode():
    assert format_timecode(71.5, 30) == "00:01:11:15"
    assert format_timecode(0, 30) == "00:00:00:00"


def test_frame_range_seconds():
    assert FrameRange(0, 359).to_seconds(30) == (0.0, 12.0)
    assert FrameRange(30, 59).to_seconds(30) == (1.0, 1.0)


def test_frame_range_clamp_and_full():
    info = _info(360)
    assert FrameRange(-5, 999).clamp(info) == FrameRange(0, 359)
    assert FrameRange.full(info) == FrameRange(0, 359)
    assert FrameRange(0, 359).is_full(info)
    assert not FrameRange(1, 359).is_full(info)


def test_fit_size():
    assert fit_size(1920, 1080, 640, None, True, "width") == (640, -2)
    assert fit_size(1920, 1080, None, 360, True, "height") == (-2, 360)
    assert fit_size(1920, 1080, 640, 480, False, "width") == (640, 480)
    assert fit_size(1920, 1080, 640, None, False, "width") == (640, 1080)
    assert fit_size(1920, 1080, None, None, True, "width") == (None, None)
    # anchor 축이 비어 있으면 값 있는 축이 기준
    assert fit_size(1920, 1080, None, 360, True, "width") == (-2, 360)


def test_resolve_dimensions():
    assert resolve_dimensions(1920, 1080, 640, -2) == (640, 360)
    assert resolve_dimensions(1920, 1080, -2, 360) == (640, 360)
    assert resolve_dimensions(1920, 1080, None, None) == (1920, 1080)


def test_gif_params_for_quality():
    p = gif_params_for_quality(50, 29.97)
    assert p.fps == 18
    assert p.max_colors == 144
    assert p.dither == "bayer:bayer_scale=3"
    assert p.stats_mode == "full"
    p = gif_params_for_quality(100, 24)
    assert p.fps == 24
    assert p.max_colors == 256
    assert p.dither == "sierra2_4a"
    assert p.stats_mode == "diff"
    p = gif_params_for_quality(10, 30)
    assert (p.fps, p.max_colors, p.dither) == (8, 54, "none")


def test_make_output_path(tmp_path: Path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    (tmp_path / "a_gif.gif").write_bytes(b"x")
    assert make_output_path(src, None, "_gif", ".gif", overwrite=False) == tmp_path / "a_gif_001.gif"
    assert make_output_path(src, None, "_gif", ".gif", overwrite=True) == tmp_path / "a_gif.gif"
    out = tmp_path / "out"
    out.mkdir()
    assert make_output_path(src, out, "", ".gif", overwrite=True) == out / "a.gif"


def test_human_size():
    assert human_size(1_887_436) == "1.8 MB"
    assert human_size(512) == "512 B"
    assert human_size(None) == ""


def test_make_output_path_never_returns_source(tmp_path: Path):
    src = tmp_path / "anim.gif"
    src.write_bytes(b"x")
    assert make_output_path(src, None, "", ".gif", overwrite=True) == tmp_path / "anim_001.gif"
    assert make_output_path(src, None, "", ".gif", overwrite=False) == tmp_path / "anim_001.gif"
    assert make_output_path(src, None, "_gif", ".gif", overwrite=True) == tmp_path / "anim_gif.gif"


def test_frame_timecode_non_drop():
    from app.core.utils import frame_timecode
    assert frame_timecode(30, 29.97) == "00:00:01:00"
    assert frame_timecode(29, 29.97) == "00:00:00:29"
    assert frame_timecode(0, 25) == "00:00:00:00"
    assert frame_timecode(25 * 3661 + 3, 25) == "01:01:01:03"
    assert frame_timecode(5, 0) == "00:00:05:00"
