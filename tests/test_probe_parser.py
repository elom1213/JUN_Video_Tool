# -*- coding: utf-8 -*-
"""ffprobe JSON / ffmpeg stderr 파서 테스트 (ffmpeg 불필요)."""
import json

import pytest

from app.core.media_probe import ProbeError, eval_fraction, parse_ffmpeg_stderr, parse_ffprobe_json

SAMPLE_STDERR = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Metadata:
    major_brand     : isom
  Duration: 00:00:12.34, start: 0.000000, bitrate: 2560 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], 2430 kb/s, 29.97 fps, 29.97 tbr, 30k tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 128 kb/s (default)
At least one output file must be specified
"""


def test_eval_fraction():
    assert eval_fraction("30000/1001") == pytest.approx(29.97, abs=0.01)
    assert eval_fraction("0/0") == 0.0
    assert eval_fraction("") == 0.0
    assert eval_fraction(None) == 0.0
    assert eval_fraction("30") == 30.0


def test_parse_ffprobe_json():
    payload = {
        "streams": [{"width": 1280, "height": 720, "codec_name": "h264", "r_frame_rate": "30/1",
                     "avg_frame_rate": "30000/1001", "nb_frames": "300", "duration": "10.01"}],
        "format": {"duration": "10.010000", "size": "4567890"},
    }
    info = parse_ffprobe_json(json.dumps(payload), 1)
    assert (info.width, info.height) == (1280, 720)
    assert info.fps == pytest.approx(29.97, abs=0.01)
    assert info.frame_count == 300
    assert info.duration == pytest.approx(10.01)
    assert info.size_bytes == 4567890
    assert info.codec == "h264"


def test_parse_ffprobe_json_without_nb_frames():
    payload = {"streams": [{"width": 640, "height": 360, "codec_name": "vp9", "r_frame_rate": "24/1",
                            "avg_frame_rate": "0/0"}], "format": {"duration": "5.0"}}
    info = parse_ffprobe_json(json.dumps(payload), 777)
    assert info.fps == 24
    assert info.frame_count == 120
    assert info.size_bytes == 777


def test_parse_ffprobe_json_errors():
    with pytest.raises(ProbeError):
        parse_ffprobe_json("not json", 0)
    with pytest.raises(ProbeError):
        parse_ffprobe_json(json.dumps({"streams": []}), 0)


def test_parse_ffmpeg_stderr():
    info = parse_ffmpeg_stderr(SAMPLE_STDERR, 1234)
    assert (info.width, info.height) == (1920, 1080)
    assert info.fps == pytest.approx(29.97)
    assert info.duration == pytest.approx(12.34)
    assert info.codec == "h264"
    assert info.size_bytes == 1234
    assert info.frame_count == round(12.34 * 29.97)


def test_parse_ffmpeg_stderr_no_video():
    with pytest.raises(ProbeError):
        parse_ffmpeg_stderr("Duration: 00:00:01.00\n Stream #0:0: Audio: aac", 0)


def test_parse_ffprobe_json_picks_video_and_audio_flag():
    payload = {"streams": [{"codec_type": "audio", "codec_name": "aac"},
                           {"codec_type": "video", "width": 320, "height": 240, "codec_name": "h264",
                            "avg_frame_rate": "10/1", "nb_frames": "20"}],
               "format": {"duration": "2.0", "size": "100"}}
    info = parse_ffprobe_json(json.dumps(payload), 1)
    assert (info.width, info.codec, info.has_audio) == (320, "h264", True)
    gif = {"streams": [{"codec_type": "video", "width": 320, "height": 240, "codec_name": "gif",
                        "avg_frame_rate": "10/1", "nb_frames": "20"}], "format": {"duration": "2.0"}}
    info = parse_ffprobe_json(json.dumps(gif), 1)
    assert info.has_audio is False and info.frame_count == 20
    with pytest.raises(ProbeError):
        parse_ffprobe_json(json.dumps({"streams": [{"codec_type": "audio"}], "format": {}}), 0)


def test_parse_ffmpeg_stderr_audio_flag():
    assert parse_ffmpeg_stderr(SAMPLE_STDERR, 1).has_audio is True
    no_audio = "\n".join(ln for ln in SAMPLE_STDERR.splitlines() if "Audio:" not in ln)
    assert parse_ffmpeg_stderr(no_audio, 1).has_audio is False
