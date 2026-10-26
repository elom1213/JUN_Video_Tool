# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-26
"""그림 입힌 영상 내보내기(burn-in) 명령 생성 (PLAN_DRAW_TAB 13.4). PySide6 비의존.

원본 디코드 · 스케일 · 인코딩은 ffmpeg 한 프로세스가 하고, 파이썬은 출력 크기의 RGBA 오버레이 프레임만
stdin 으로 보낸다. 두 입력을 `setpts=N/fps/TB` 로 정규화해 "N 번째 디코드 프레임 = Draw 탭 프레임 N" 을 맞춘다.
"""
from __future__ import annotations

from pathlib import Path

from . import image_sequence
from .converters.base import BaseConverter
from .converters.common import fmt_fps
from .converters.gif_converter import GifConverter, GifOptions
from .converters.mp4_converter import AUDIO_BITRATE_KBPS, Mp4Converter, Mp4Options, resolve_fps_mp4
from .models import ConvertOptions, VideoItem


def overlay_size(item: VideoItem, converter: BaseConverter, options: ConvertOptions) -> tuple[int, int]:
    """오버레이(= 출력) 크기. 짝수로 맞춘다 (rgba → yuv420p 경로와 GIF 모두 안전)."""
    w, h = converter.output_dimensions(item, options)
    w = max(2, w - (w % 2))
    h = max(2, h - (h % 2))
    return w, h


def build_burnin_command(ffmpeg: Path, item: VideoItem, converter: BaseConverter, options: ConvertOptions,
                         output_path: Path) -> list[str]:
    if item.info is None:
        raise ValueError("Item has no media info.")
    info = item.info
    w, h = overlay_size(item, converter, options)
    fps = fmt_fps(info.fps)
    cmd: list[str] = [str(ffmpeg), "-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
    if getattr(options, "hwaccel", "none") == "auto" and not info.sequence:
        cmd += ["-hwaccel", "auto"]
    cmd += image_sequence.input_args(item.path, info.fps)
    cmd += ["-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-framerate", fps, "-i", "-"]
    head = (f"[0:v]scale={w}:{h}:flags=lanczos,setsar=1,setpts=N/({fps})/TB[base];"
            f"[1:v]setpts=N/({fps})/TB[ov];"
            f"[base][ov]overlay=0:0:eof_action=pass:format=auto")

    if isinstance(converter, GifConverter):
        if not isinstance(options, GifOptions):
            raise TypeError("GIF export expects GifOptions")
        p = converter.params(item, options)
        fc = (f"{head},fps={fmt_fps(p.fps)},split[a][b];"
              f"[a]palettegen=max_colors={p.max_colors}:stats_mode={p.stats_mode}[p];"
              f"[b][p]paletteuse=dither={p.dither}")
        cmd += ["-filter_complex", fc, "-loop", str(int(options.loop)), str(output_path)]
        return cmd

    if isinstance(converter, Mp4Converter):
        if not isinstance(options, Mp4Options):
            raise TypeError("MP4 export expects Mp4Options")
        out_fps = resolve_fps_mp4(options, info.fps)
        tail = f",fps={fmt_fps(out_fps)}" if options.fps_mode == "custom" and abs(out_fps - info.fps) > 1e-3 else ""
        fc = f"{head},format=yuv420p{tail}[v]"
        cmd += ["-filter_complex", fc, "-map", "[v]"]
        if options.audio != "none":
            cmd += ["-map", "0:a?"]
        cmd += ["-c:v", "libx264", "-crf", str(converter.crf(options)), "-preset", options.preset,
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if options.audio == "none":
            cmd += ["-an"]
        elif options.audio == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", f"{AUDIO_BITRATE_KBPS}k"]
        cmd += [str(output_path)]
        return cmd

    raise ValueError(f"Export is not supported for format: {converter.format_id}")
