# -*- coding: utf-8 -*-
"""GifConverter.build_command / resolve_fps / degrade_for_retry (PLAN 7장)."""
from pathlib import Path

import pytest

from app.core.converters import GifConverter, GifOptions, registry, resolve_fps
from app.core.models import FrameRange, MediaInfo, VideoItem

FFMPEG = Path("C:/tools/ffmpeg.exe")


def _item(frames=360, fps=30.0, rng=None):
    info = MediaInfo(width=1920, height=1080, fps=fps, duration=frames / fps, frame_count=frames,
                     codec="h264", size_bytes=1000)
    return VideoItem(path=Path("C:/videos/clip a.mp4"), info=info, frame_range=rng)


def _filter(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_registry_has_gif():
    assert registry.ids()[0] == "gif"
    assert isinstance(registry.get("gif"), GifConverter)


def test_resolve_fps():
    assert resolve_fps(GifOptions(fps_mode="auto", quality=50), 29.97) == 18
    assert resolve_fps(GifOptions(fps_mode="source"), 29.97) == pytest.approx(29.97)
    assert resolve_fps(GifOptions(fps_mode="custom", fps_custom=12), 29.97) == 12.0
    assert resolve_fps(GifOptions(fps_mode="custom", fps_custom=60), 24) == 24.0


def test_build_command_with_range_and_lock():
    conv = GifConverter()
    opts = GifOptions(width=640, height=None, lock_aspect=True, anchor="width", quality=50, hwaccel="none")
    item = _item(rng=FrameRange(30, 59))
    out = Path("C:/videos/clip a_gif.gif")
    cmd = conv.build_command(FFMPEG, item, opts, out)
    assert cmd[0] == str(FFMPEG)
    assert cmd[-1] == str(out)
    assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "1.000"
    assert "-t" in cmd and cmd[cmd.index("-t") + 1] == "1.000"
    assert "-hwaccel" not in cmd
    f = _filter(cmd)
    assert "fps=18" in f
    assert "scale=640:-2:flags=lanczos" in f
    assert "max_colors=144" in f
    assert "dither=bayer:bayer_scale=3" in f
    assert "stats_mode=full" in f
    assert cmd[cmd.index("-loop") + 1] == "0"


def test_build_command_full_range_no_seek_and_hwaccel():
    conv = GifConverter()
    opts = GifOptions(quality=90, hwaccel="auto")
    cmd = conv.build_command(FFMPEG, _item(), opts, Path("o.gif"))
    assert "-ss" not in cmd and "-t" not in cmd
    assert cmd[cmd.index("-hwaccel") + 1] == "auto"
    f = _filter(cmd)
    assert "scale=" not in f  # 원본 크기
    assert "dither=sierra2_4a" in f and "stats_mode=diff" in f


def test_build_command_custom_fps_and_free_size():
    conv = GifConverter()
    opts = GifOptions(width=640, height=480, lock_aspect=False, fps_mode="custom", fps_custom=12)
    f = _filter(conv.build_command(FFMPEG, _item(), opts, Path("o.gif")))
    assert "fps=12" in f
    assert "scale=640:480:flags=lanczos" in f


def test_validate():
    conv = GifConverter()
    assert conv.validate(GifOptions()) == []
    problems = conv.validate(GifOptions(width=9000, quality=0, fps_mode="custom", fps_custom=0.5,
                                        target_size_mb=0, output_dir=Path("Z:/__nope__")))
    assert len(problems) == 5


def test_degrade_for_retry():
    conv = GifConverter()
    o0 = GifOptions(quality=70, width=640, lock_aspect=True, anchor="width")
    o1 = conv.degrade_for_retry(o0, 1, 5_000_000, 2_000_000, src_w=1920, src_fps=30)
    assert o1.quality == 55 and o1.width == 640
    o2 = conv.degrade_for_retry(o1, 2, 4_000_000, 2_000_000, src_w=1920, src_fps=30)
    assert o2.quality == 40 and o2.width == 544
    # 사용자 지정 fps 는 2차부터 75% 로
    oc = GifOptions(quality=70, fps_mode="custom", fps_custom=20)
    oc1 = conv.degrade_for_retry(oc, 1, 3, 2, src_w=1920, src_fps=30)
    assert oc1.fps_mode == "custom" and oc1.fps_custom == 15
    # max_attempts 소진
    assert conv.degrade_for_retry(GifOptions(max_attempts=3), 3, 3, 2) is None


def test_heuristic_and_warning():
    conv = GifConverter()
    item = _item(frames=300)
    opts = GifOptions(width=640, quality=50, fps_mode="source")
    size = conv.heuristic_size(item, opts)
    assert size == int(800 + 300 * 640 * 360 * (0.08 + 0.42 * 144 / 256) * 1.0)
    assert conv.estimate_warning(item, opts) is None
    big = _item(frames=30 * 60 * 5)  # 5분
    assert conv.estimate_warning(big, GifOptions(fps_mode="source")) is not None
