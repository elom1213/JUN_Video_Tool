# -*- coding: utf-8 -*-
"""burn-in 내보내기 명령 (PLAN_DRAW_TAB 13.4)."""
from pathlib import Path

import pytest

from app.core.burnin import build_burnin_command, overlay_size
from app.core.converters import GifConverter, GifOptions, Mp4Converter, Mp4Options
from app.core.models import FrameRange, MediaInfo, VideoItem

FF = Path("C:/tools/ffmpeg.exe")
OUT = Path("C:/out/clip_draw.gif")


def _item(w=1920, h=1080, fps=30.0, rng=None):
    info = MediaInfo(width=w, height=h, fps=fps, duration=10, frame_count=int(10 * fps), codec="h264",
                     size_bytes=1, has_audio=True)
    return VideoItem(path=Path("C:/v/clip.mp4"), info=info, frame_range=rng)


def _after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_gif_command():
    item = _item(rng=FrameRange(10, 20))           # 구간은 무시하고 전체 길이
    opts = GifOptions(width=480, quality=70, loop=2, hwaccel="none")
    cmd = build_burnin_command(FF, item, GifConverter(), opts, OUT)
    assert "-ss" not in cmd and "-hwaccel" not in cmd
    assert cmd.count("-i") == 2
    assert _after(cmd, "-pix_fmt") == "rgba"
    assert _after(cmd, "-s") == "480x270"
    assert _after(cmd, "-framerate") == "30"
    assert cmd[cmd.index("-framerate") + 2:cmd.index("-framerate") + 4] == ["-i", "-"]
    fc = _after(cmd, "-filter_complex")
    assert fc.startswith("[0:v]scale=480:270:flags=lanczos")
    assert "setpts=N/(30)/TB[base]" in fc and "[1:v]setpts=N/(30)/TB[ov]" in fc
    assert "overlay=0:0:eof_action=pass" in fc
    assert "palettegen=" in fc and "paletteuse=dither=" in fc
    assert _after(cmd, "-loop") == "2"
    assert cmd[-1] == str(OUT)


def test_mp4_command_audio_modes():
    item = _item(fps=29.97)
    conv = Mp4Converter()
    cmd = build_burnin_command(FF, item, conv, Mp4Options(hwaccel="auto"), OUT.with_suffix(".mp4"))
    assert _after(cmd, "-hwaccel") == "auto"
    assert _after(cmd, "-s") == "1920x1080"
    assert _after(cmd, "-framerate") == "29.97"
    assert "[v]" in _after(cmd, "-filter_complex")
    maps = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-map"]
    assert maps == ["[v]", "0:a?"]
    assert _after(cmd, "-c:v") == "libx264" and _after(cmd, "-c:a") == "aac"
    cmd2 = build_burnin_command(FF, item, conv, Mp4Options(audio="none", hwaccel="none"), OUT)
    assert "-an" in cmd2 and "0:a?" not in cmd2


def test_mp4_custom_fps_and_even_size():
    item = _item(w=1001, h=601)
    opts = Mp4Options(fps_mode="custom", fps_custom=15, hwaccel="none")
    cmd = build_burnin_command(FF, item, Mp4Converter(), opts, OUT)
    w, h = overlay_size(item, Mp4Converter(), opts)
    assert w % 2 == 0 and h % 2 == 0
    assert ",fps=15[v]" in _after(cmd, "-filter_complex")


def test_wrong_options_type():
    with pytest.raises(TypeError):
        build_burnin_command(FF, _item(), GifConverter(), Mp4Options(), OUT)
