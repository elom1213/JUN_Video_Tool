# -*- coding: utf-8 -*-
"""Mp4Converter: 명령 생성 · CRF 매핑 · fps · 검증 · 재시도."""
from pathlib import Path

from app.core.converters import Mp4Converter, Mp4Options, crf_for_quality, registry, resolve_fps_mp4
from app.core.models import FrameRange, MediaInfo, VideoItem

FFMPEG = Path("C:/tools/ffmpeg.exe")


def _item(frames=300, fps=30.0, rng=None, w=1920, h=1080):
    info = MediaInfo(width=w, height=h, fps=fps, duration=frames / fps, frame_count=frames,
                     codec="h264", size_bytes=1000)
    return VideoItem(path=Path("C:/videos/clip.mov"), info=info, frame_range=rng)


def _after(cmd, flag):
    return cmd[cmd.index(flag) + 1]


def test_registry_order():
    assert registry.ids() == ["gif", "mp4", "wav"]
    assert isinstance(registry.get("mp4"), Mp4Converter)


def test_crf_mapping():
    assert crf_for_quality(100) == 16
    assert crf_for_quality(70) == 22
    assert crf_for_quality(50) == 26
    assert crf_for_quality(10) == 34
    assert crf_for_quality(1) == 36


def test_resolve_fps_mp4():
    assert resolve_fps_mp4(Mp4Options(fps_mode="auto"), 29.97) == 29.97
    assert resolve_fps_mp4(Mp4Options(fps_mode="source"), 24) == 24
    assert resolve_fps_mp4(Mp4Options(fps_mode="custom", fps_custom=15), 30) == 15
    assert resolve_fps_mp4(Mp4Options(fps_mode="custom", fps_custom=60), 24) == 24


def test_build_command_defaults_full_range():
    conv = Mp4Converter()
    cmd = conv.build_command(FFMPEG, _item(), Mp4Options(hwaccel="none"), Path("o.mp4"))
    assert cmd[-1] == "o.mp4"
    assert "-ss" not in cmd and "-vf" not in cmd and "-hwaccel" not in cmd
    assert _after(cmd, "-c:v") == "libx264"
    assert _after(cmd, "-crf") == "22"
    assert _after(cmd, "-preset") == "medium"
    assert _after(cmd, "-pix_fmt") == "yuv420p"
    assert _after(cmd, "-movflags") == "+faststart"
    assert _after(cmd, "-c:a") == "aac" and _after(cmd, "-b:a") == "128k"


def test_build_command_range_scale_fps_audio():
    conv = Mp4Converter()
    opts = Mp4Options(width=641, height=361, lock_aspect=False, quality=50, fps_mode="custom", fps_custom=15,
                      preset="fast", audio="none", hwaccel="auto")
    cmd = conv.build_command(FFMPEG, _item(rng=FrameRange(30, 89)), opts, Path("o.mp4"))
    assert _after(cmd, "-hwaccel") == "auto"
    assert _after(cmd, "-ss") == "1.000" and _after(cmd, "-t") == "2.000"
    assert _after(cmd, "-vf") == "fps=15,scale=640:360:flags=lanczos"   # 홀수 → 짝수 보정
    assert _after(cmd, "-crf") == "26" and _after(cmd, "-preset") == "fast"
    assert "-an" in cmd and "-c:a" not in cmd


def test_build_command_locked_width_and_copy_audio():
    conv = Mp4Converter()
    cmd = conv.build_command(FFMPEG, _item(), Mp4Options(width=720, audio="copy"), Path("o.mp4"))
    assert _after(cmd, "-vf") == "scale=720:-2:flags=lanczos"
    assert _after(cmd, "-c:a") == "copy"


def test_validate_and_degrade():
    conv = Mp4Converter()
    assert conv.validate(Mp4Options()) == []
    assert len(conv.validate(Mp4Options(preset="nope", audio="mp3", quality=0))) == 3
    o1 = conv.degrade_for_retry(Mp4Options(quality=70, width=1280), 1, 10, 5, src_w=1920)
    assert o1.quality == 50 and o1.width == 1280
    o2 = conv.degrade_for_retry(o1, 2, 10, 5, src_w=1920)
    assert o2.quality == 30 and o2.width == 1088
    assert conv.degrade_for_retry(Mp4Options(max_attempts=2), 2, 10, 5) is None


def test_output_dimensions_even_and_heuristic():
    conv = Mp4Converter()
    item = _item(w=1919, h=1079)
    assert conv.output_dimensions(item, Mp4Options()) == (1918, 1078)
    size = conv.heuristic_size(_item(frames=300), Mp4Options(width=640, audio="none"))
    # 640x360, 30 fps, 10 s, crf 22 → bpp 0.1*2^(1/6)
    expected = int(2048 + 640 * 360 * 30 * 10 * (0.10 * 2 ** (1 / 6)) / 8)
    assert size == expected
    assert conv.estimate_warning(item, Mp4Options()) is None
