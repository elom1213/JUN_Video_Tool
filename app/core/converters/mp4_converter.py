# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""MP4 (H.264) 변환기 (PLAN 5.9): 재인코딩 · 리사이즈 · 구간 자르기 · fps 변경 · 오디오 처리."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ...config.constants import round_half_up
from ..models import ConvertOptions, VideoItem
from .base import BaseConverter
from .common import VideoOptions, even, fmt_fps, input_args, output_dimensions, scale_args, validate_common

PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
AUDIO_MODES = ("aac", "copy", "none")
AUDIO_BITRATE_KBPS = 128


@dataclass
class Mp4Options(VideoOptions):
    format_id: str = "mp4"
    fps_custom: float = 30.0
    preset: str = "medium"          # x264 preset
    audio: str = "aac"              # "aac" (128 kbps 재인코딩) | "copy" | "none"


def crf_for_quality(q: int) -> int:
    """품질 1~100 → x264 CRF. q=100→16, q=70→22, q=50→26, q=10→34 (낮을수록 고화질·대용량)."""
    q = max(1, min(100, int(q)))
    return max(14, min(40, round_half_up(36 - q * 0.2)))


def resolve_fps_mp4(options: VideoOptions, src_fps: float) -> float:
    """auto = 원본 fps 유지. custom 은 원본 상한."""
    if options.fps_mode == "custom":
        f = float(options.fps_custom)
        return float(min(src_fps, f)) if src_fps > 0 else f
    return float(src_fps)


class Mp4Converter(BaseConverter):
    format_id = "mp4"
    display_name = "MP4 (H.264)"
    extension = ".mp4"
    options_cls = Mp4Options

    # ------------------------------------------------------------------ 옵션
    def default_options(self) -> Mp4Options:
        return Mp4Options()

    def validate(self, options: ConvertOptions) -> list[str]:
        o = self._opts(options)
        problems = validate_common(o)
        if o.preset not in PRESETS:
            problems.append(f"Unknown preset: {o.preset}")
        if o.audio not in AUDIO_MODES:
            problems.append(f"Unknown audio mode: {o.audio}")
        return problems

    # ------------------------------------------------------------------ 파생 값
    def crf(self, options: ConvertOptions) -> int:
        return crf_for_quality(self._opts(options).quality)

    def output_fps(self, item: VideoItem, options: ConvertOptions) -> float:
        src_fps = item.info.fps if item.info else 30.0
        return resolve_fps_mp4(self._opts(options), src_fps)

    def output_dimensions(self, item: VideoItem, options: ConvertOptions) -> tuple[int, int]:
        w, h = output_dimensions(item, self._opts(options))
        return even(w), even(h)

    # ------------------------------------------------------------------ 명령
    def build_command(self, ffmpeg: Path, item: VideoItem, options: ConvertOptions,
                      output_path: Path) -> list[str]:
        o = self._opts(options)
        if item.info is None:
            raise ValueError("Item has no media info.")
        info = item.info
        cmd: list[str] = [str(ffmpeg), "-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
        cmd += input_args(item, o)

        filters: list[str] = []
        fps = resolve_fps_mp4(o, info.fps)
        if o.fps_mode == "custom" and abs(fps - info.fps) > 1e-3:
            filters.append(f"fps={fmt_fps(fps)}")
        w, h = scale_args(item, o)
        if w is not None or h is not None:
            # 락 해제로 정확한 값을 줄 때도 짝수로 보정 (yuv420p). -2 는 ffmpeg 가 알아서 짝수로 맞춘다
            ws = str(even(w)) if (w is not None and w > 0) else str(w)
            hs = str(even(h)) if (h is not None and h > 0) else str(h)
            filters.append(f"scale={ws}:{hs}:flags=lanczos")
        if filters:
            cmd += ["-vf", ",".join(filters)]

        cmd += ["-c:v", "libx264", "-crf", str(self.crf(o)), "-preset", o.preset,
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if o.audio == "none":
            cmd += ["-an"]
        elif o.audio == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", f"{AUDIO_BITRATE_KBPS}k"]
        cmd += [str(output_path)]
        return cmd

    # ------------------------------------------------------------------ 타깃 크기
    def supports_target_size(self) -> bool:
        return True

    def target_size_bytes(self, options: ConvertOptions) -> int | None:
        o = self._opts(options)
        if o.target_size_mb is None:
            return None
        return int(round(o.target_size_mb * 1024 * 1024))

    def degrade_for_retry(self, options: ConvertOptions, attempt: int,
                          last_size: int, target: int, src_w: int = 0, src_fps: float = 30.0) -> Mp4Options | None:
        """quality -20 (CRF +4) 씩, 2차부터는 폭도 85% 로."""
        o = self._opts(options)
        if attempt >= o.max_attempts:
            return None
        new = replace(o, quality=max(1, o.quality - 20))
        if attempt >= 2:
            base_w = o.width if o.width else (src_w or None)
            if base_w:
                new = replace(new, width=max(16, int(round(base_w * 0.85))))
                if not o.lock_aspect and o.height:
                    new = replace(new, height=max(16, int(round(o.height * 0.85))))
                else:
                    new = replace(new, anchor="width", height=None if o.lock_aspect else new.height)
        return new

    # ------------------------------------------------------------------ 추정
    def heuristic_size(self, item: VideoItem, options: ConvertOptions) -> int | None:
        """x264 경험식: CRF 23 에서 0.10 bit/pixel/frame, CRF 6 차이마다 2배. 오디오는 128 kbps."""
        if item.info is None:
            return None
        o = self._opts(options)
        _, dur = item.effective_range().to_seconds(item.info.fps)
        fps = resolve_fps_mp4(o, item.info.fps)
        w, h = self.output_dimensions(item, o)
        bpp = 0.10 * 2 ** ((23 - self.crf(o)) / 6)
        video = w * h * fps * dur * bpp / 8
        audio = (AUDIO_BITRATE_KBPS * 1000 / 8) * dur if o.audio != "none" else 0
        return int(2048 + video + audio)

    # ------------------------------------------------------------------ 내부
    @staticmethod
    def _opts(options: ConvertOptions) -> Mp4Options:
        if isinstance(options, Mp4Options):
            return options
        raise TypeError(f"Mp4Converter expects Mp4Options, got {type(options).__name__}")
