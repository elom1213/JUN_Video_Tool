# -*- coding: utf-8 -*-
"""WAV 변환기 (JUN_JALI 규격) · JUN_JALI 규칙 검사 · 음성 전용 probe (ffmpeg 불필요)."""
import json
import math
import struct
import wave
from pathlib import Path

import pytest

from app.config import constants as C
from app.core.converters import GifConverter, Mp4Converter, WavConverter, WavOptions
from app.core.converters.wav_converter import channel_filter
from app.core.jali_wav import JaliWavError, check_jali_wav
from app.core.media_probe import layout_channels, parse_ffmpeg_stderr, parse_ffprobe_json
from app.core.models import FrameRange, MediaInfo, VideoItem

FF = Path("C:/tools/ffmpeg.exe")


def _audio_info(dur=10.0, rate=48000, ch=2):
    return MediaInfo(width=0, height=0, fps=C.AUDIO_TIMELINE_FPS, duration=dur, frame_count=int(dur * 1000),
                     codec="mp3", size_bytes=1, has_audio=True, audio_only=True, sample_rate=rate, channels=ch)


def _video_info(has_audio=True, ch=2):
    return MediaInfo(width=1920, height=1080, fps=30.0, duration=10.0, frame_count=300, codec="h264",
                     size_bytes=1, has_audio=has_audio, sample_rate=48000 if has_audio else 0,
                     channels=ch if has_audio else 0)


# ---------------------------------------------------------------------- 명령
@pytest.mark.parametrize("mode,ch,expect", [
    ("mix", 2, "pan=mono|c0=0.5*c0+0.5*c1"), ("mix", 1, "pan=mono|c0=c0"), ("mix", 0, "pan=mono|c0=c0"),
    ("left", 2, "pan=mono|c0=c0"), ("right", 2, "pan=mono|c0=c1"), ("right", 1, "pan=mono|c0=c0"),
    ("mix", 6, "pan=mono|c0=" + "+".join(f"0.166667*c{i}" for i in range(6)))])
def test_channel_filter(mode, ch, expect):
    assert channel_filter(mode, ch) == expect


def test_build_command_full_audio_file():
    item = VideoItem(path=Path("C:/a/voice.mp3"), info=_audio_info())
    cmd = WavConverter().build_command(FF, item, WavOptions(), Path("C:/a/voice_wav.wav"))
    assert "-ss" not in cmd
    assert cmd[cmd.index("-map") + 1] == "0:a:0"
    assert cmd[cmd.index("-ar") + 1] == "44100"
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-c:a") + 1] == "pcm_s16le"
    assert cmd[cmd.index("-f") + 1] == "wav"
    assert "+bitexact" in cmd and "-vn" in cmd and cmd[cmd.index("-map_metadata") + 1] == "-1"
    assert cmd[cmd.index("-af") + 1] == "pan=mono|c0=0.5*c0+0.5*c1,aresample=44100"
    assert cmd[-1] == str(Path("C:/a/voice_wav.wav"))


def test_build_command_range_in_milliseconds():
    # 음성 파일은 1 프레임 = 1 ms → 1500 ~ 3999 = 1.5 s 부터 2.5 s
    item = VideoItem(path=Path("C:/a/voice.mp3"), info=_audio_info(), frame_range=FrameRange(1500, 3999))
    cmd = WavConverter().build_command(FF, item, WavOptions(channels="left"), Path("C:/a/o.wav"))
    assert cmd[cmd.index("-ss") + 1] == "1.500"
    assert cmd[cmd.index("-t") + 1] == "3.000"          # 넉넉히 읽고
    assert cmd.index("-ss") < cmd.index("-i")
    # 리샘플 뒤 정확히 2.5 s x 44100 샘플로 자른다
    assert cmd[cmd.index("-af") + 1] == "pan=mono|c0=c0,aresample=44100,atrim=end_sample=110250"


def test_build_command_video_range_uses_video_fps():
    item = VideoItem(path=Path("C:/a/clip.mp4"), info=_video_info(), frame_range=FrameRange(30, 89))
    cmd = WavConverter().build_command(FF, item, WavOptions(), Path("C:/a/o.wav"))
    assert cmd[cmd.index("-ss") + 1] == "1.000"
    assert cmd[cmd.index("-af") + 1].endswith("atrim=end_sample=88200")
    assert "-hwaccel" not in cmd


def test_exact_size_and_no_output_fps():
    conv = WavConverter()
    item = VideoItem(path=Path("C:/a/voice.mp3"), info=_audio_info(dur=2.0))
    assert conv.heuristic_size(item, WavOptions()) == 44 + 2 * 44100 * 2
    assert conv.heuristic_level() == "exact"
    assert conv.output_fps(item, WavOptions()) == 0.0
    assert not conv.supports_sample_estimate()


def test_skip_reasons():
    audio = VideoItem(path=Path("a.mp3"), info=_audio_info())
    silent_video = VideoItem(path=Path("b.mp4"), info=_video_info(has_audio=False))
    video = VideoItem(path=Path("c.mp4"), info=_video_info())
    assert "audio file" in GifConverter().skip_reason(audio)
    assert "audio file" in Mp4Converter().skip_reason(audio)
    assert Mp4Converter().skip_reason(video) is None
    assert WavConverter().skip_reason(audio) is None
    assert WavConverter().skip_reason(video) is None
    assert WavConverter().skip_reason(silent_video) == "no audio stream"


def test_length_warnings():
    conv = WavConverter()
    short = VideoItem(path=Path("a.mp3"), info=_audio_info(dur=0.3))
    long_ = VideoItem(path=Path("a.mp3"), info=_audio_info(dur=150.0))
    ok = VideoItem(path=Path("a.mp3"), info=_audio_info(dur=30.0))
    assert "at least 0.5 s" in conv.estimate_warning(short, WavOptions())
    assert "longer than 120 s" in conv.estimate_warning(long_, WavOptions())
    assert conv.estimate_warning(long_, WavOptions(max_seconds=200)) is None
    assert conv.estimate_warning(ok, WavOptions()) is None


def test_validate():
    assert WavConverter().validate(WavOptions()) == []
    assert WavConverter().validate(WavOptions(channels="center"))
    assert WavConverter().validate(WavOptions(max_seconds=0))


# ---------------------------------------------------------------------- probe
def test_probe_audio_only_json():
    payload = {"streams": [{"codec_type": "audio", "codec_name": "mp3", "sample_rate": "48000", "channels": 2,
                            "duration": "12.5"}], "format": {"duration": "12.500000", "size": "200000"}}
    info = parse_ffprobe_json(json.dumps(payload), 1)
    assert info.audio_only and info.has_audio
    assert (info.width, info.height, info.fps) == (0, 0, C.AUDIO_TIMELINE_FPS)
    assert info.frame_count == 12500 and info.last_frame == 12499
    assert (info.sample_rate, info.channels, info.codec) == (48000, 2, "mp3")


def test_probe_cover_art_is_not_video():
    payload = {"streams": [{"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100", "channels": 1},
                           {"codec_type": "video", "codec_name": "mjpeg", "width": 500, "height": 500,
                            "r_frame_rate": "90000/1", "avg_frame_rate": "0/0", "disposition": {"attached_pic": 1}}],
               "format": {"duration": "3.0"}}
    info = parse_ffprobe_json(json.dumps(payload), 1)
    assert info.audio_only and info.channels == 1


def test_probe_video_keeps_audio_details():
    payload = {"streams": [{"codec_type": "video", "codec_name": "h264", "width": 1280, "height": 720,
                            "r_frame_rate": "30/1", "avg_frame_rate": "30/1", "nb_frames": "90",
                            "disposition": {"attached_pic": 0}},
                           {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2}],
               "format": {"duration": "3.0"}}
    info = parse_ffprobe_json(json.dumps(payload), 1)
    assert not info.audio_only and info.has_audio and (info.sample_rate, info.channels) == (44100, 2)


def test_probe_stderr_audio_only_and_cover():
    text = """Input #0, mp3, from 'voice.mp3':
  Duration: 00:00:04.20, start: 0.025057, bitrate: 128 kb/s
  Stream #0:0: Audio: mp3 (mp3float), 44100 Hz, stereo, fltp, 128 kb/s
  Stream #0:1: Video: mjpeg (Baseline), yuvj420p(pc), 500x500 [SAR 1:1 DAR 1:1], 90k tbr, 90k tbn (attached pic)
"""
    info = parse_ffmpeg_stderr(text, 99)
    assert info.audio_only and (info.sample_rate, info.channels) == (44100, 2)
    assert info.duration == pytest.approx(4.2)


@pytest.mark.parametrize("text,n", [("mono", 1), ("stereo", 2), ("5.1", 6), ("5.1(side)", 6), ("3 channels", 3),
                                    ("weird", 0)])
def test_layout_channels(text, n):
    assert layout_channels(text) == n


# ---------------------------------------------------------------------- JUN_JALI 규칙
def _write_wav(path, rate=44100, ch=1, width=2, seconds=1.0, amp=0.3, clip=False):
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(n):
            v = 1.0 if clip else amp * math.sin(2 * math.pi * 220 * i / rate)
            for _c in range(ch):
                if width == 2:
                    frames += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
                else:
                    frames += struct.pack("<B", int(128 + v * 127))
        w.writeframes(bytes(frames))
    return path


def test_jali_ok(tmp_path):
    info = check_jali_wav(_write_wav(tmp_path / "ok.wav"))
    assert (info.sample_rate, info.channels) == (44100, 1)
    assert info.seconds == pytest.approx(1.0) and info.warnings == []
    assert info.summary() == "44100 Hz · int16 · 1 ch · 1.00 s"


@pytest.mark.parametrize("kw,code", [({"rate": 48000}, "E03"), ({"width": 1}, "E04"), ({"ch": 3}, "E05"),
                                     ({"seconds": 0.3}, "E06"), ({"amp": 0.0}, "E08")])
def test_jali_errors(tmp_path, kw, code):
    with pytest.raises(JaliWavError) as e:
        check_jali_wav(_write_wav(tmp_path / "bad.wav", **kw))
    assert e.value.code == code


def test_jali_too_long(tmp_path):
    p = _write_wav(tmp_path / "long.wav", rate=44100, seconds=3.0)
    with pytest.raises(JaliWavError) as e:
        check_jali_wav(p, max_seconds=2.0)
    assert e.value.code == "E07"
    assert check_jali_wav(p, max_seconds=None).seconds == pytest.approx(3.0)


def test_jali_warnings(tmp_path):
    st = check_jali_wav(_write_wav(tmp_path / "st.wav", ch=2))
    assert [c for c, _ in st.warnings] == ["W01"]
    cl = check_jali_wav(_write_wav(tmp_path / "cl.wav", clip=True))
    assert [c for c, _ in cl.warnings] == ["W02"]


def test_jali_not_pcm(tmp_path):
    bad = tmp_path / "fake.wav"
    bad.write_bytes(b"ID3" + b"\0" * 100)       # mp3 를 이름만 바꾼 파일
    with pytest.raises(JaliWavError) as e:
        check_jali_wav(bad)
    assert e.value.code == "E02"
