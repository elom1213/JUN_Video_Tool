# -*- coding: utf-8 -*-
"""Draw 탭 디코더 순수 함수 (PLAN_DRAW_TAB 4.1, 7장, 13.1)."""
from pathlib import Path

import pytest

from app.core.frame_decoder import build_audio_command, build_stream_command, make_decode_spec, seek_time
from app.core.models import MediaInfo

FF = Path("C:/tools/ffmpeg.exe")
SRC = Path("C:/v/clip.mp4")


def _info(w, h, fps=30.0):
    return MediaInfo(width=w, height=h, fps=fps, duration=10, frame_count=int(10 * fps), codec="h264",
                     size_bytes=1)


def test_seek_time():
    assert seek_time(0, 30) == 0.0
    assert seek_time(90, 29.97) == pytest.approx(89.75 / 29.97)
    assert seek_time(5, 0) == 0.0


@pytest.mark.parametrize("src,out", [((1920, 1080), (1280, 720)), ((1280, 720), (1280, 720)),
                                     ((640, 480), (640, 480)), ((1921, 1081), (1280, 720))])
def test_make_decode_spec(src, out):
    spec = make_decode_spec(_info(*src))
    assert (spec.out_w, spec.out_h) == out
    assert spec.frame_bytes == out[0] * out[1] * 3


def test_frame_bytes_720p():
    assert make_decode_spec(_info(1280, 720)).frame_bytes == 2_764_800


def test_build_stream_command():
    spec = make_decode_spec(_info(1920, 1080))
    cmd = build_stream_command(FF, SRC, spec, 30, "auto")
    assert cmd[0] == str(FF)
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-hwaccel") + 1] == "auto"
    assert "-an" in cmd
    assert cmd[cmd.index("-fps_mode") + 1] == "passthrough"
    assert "scale=1280:720" in cmd[cmd.index("-vf") + 1]
    assert cmd[cmd.index("-f") + 1] == "rawvideo"
    assert cmd[-1] == "-"


def test_build_stream_command_variants():
    spec = make_decode_spec(_info(640, 360))
    cmd = build_stream_command(FF, SRC, spec, 0, "none", legacy_vsync=True)
    assert "-hwaccel" not in cmd
    assert "-ss" not in cmd
    assert cmd[cmd.index("-vsync") + 1] == "0"
    assert "-fps_mode" not in cmd


def test_build_audio_command():
    cmd = build_audio_command(FF, SRC, 2.5)
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "2.500000"
    assert "-vn" in cmd
    assert cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[cmd.index("-ar") + 1] == "48000"
    assert cmd[cmd.index("-f") + 1] == "s16le"
    assert cmd[-1] == "-"
    assert "-ss" not in build_audio_command(FF, SRC, 0.0)
