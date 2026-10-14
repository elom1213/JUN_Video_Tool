# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""GIF 변환기 (PLAN 5.6). palettegen / paletteuse 2패스를 filter_complex 한 번으로."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from ...config import constants as C
from ...config.constants import GifParams, gif_params_for_quality
from ..models import ConvertOptions, VideoItem
from ..size_estimator import heuristic_gif_size, output_frames
from ..utils import fit_size, resolve_dimensions
from .base import BaseConverter


@dataclass
class GifOptions(ConvertOptions):
    format_id: str = "gif"
    width: int | None = None
    height: int | None = None
    lock_aspect: bool = True
    anchor: str = "width"
    quality: int = 70
    fps_mode: str = "auto"          # "auto" | "source" | "custom"
    fps_custom: float = 15.0
    loop: int = 0
    target_size_mb: float | None = None
    max_attempts: int = 5
    hwaccel: str = C.DEFAULT_HWACCEL  # "auto" | "none"


def resolve_fps(options: GifOptions, src_fps: float) -> float:
    """PLAN 5.6 '출력 fps 결정' 표."""
    if options.fps_mode == "source":
        return float(src_fps)
    if options.fps_mode == "custom":
        f = float(options.fps_custom)
        return float(min(src_fps, f)) if src_fps > 0 else f
    return gif_params_for_quality(options.quality, src_fps).fps


def _fmt_fps(fps: float) -> str:
    """필터 문자열용 fps 표기 (정수면 정수로)."""
    if abs(fps - round(fps)) < 1e-6:
        return str(int(round(fps)))
    return f"{fps:.3f}".rstrip("0").rstrip(".")


class GifConverter(BaseConverter):
    format_id = "gif"
    display_name = "GIF"
    extension = ".gif"
    options_cls = GifOptions

    # ------------------------------------------------------------------ 옵션
    def default_options(self) -> GifOptions:
        return GifOptions()

    def validate(self, options: ConvertOptions) -> list[str]:
        o = self._opts(options)
        problems: list[str] = []
        for name, val in (("Width", o.width), ("Height", o.height)):
            if val is not None and not (1 <= val <= 8192):
                problems.append(f"{name} must be between 1 and 8192.")
        if not (1 <= o.quality <= 100):
            problems.append("Quality must be between 1 and 100.")
        if o.fps_mode == "custom" and not (1 <= o.fps_custom <= 60):
            problems.append("Custom FPS must be between 1 and 60.")
        if o.target_size_mb is not None and o.target_size_mb <= 0:
            problems.append("Target size must be greater than 0 MB.")
        if o.output_dir is not None and not Path(o.output_dir).is_dir():
            problems.append(f"Output folder does not exist: {o.output_dir}")
        if o.loop < 0:
            problems.append("Loop count cannot be negative.")
        return problems

    # ------------------------------------------------------------------ 파생 값
    def params(self, item: VideoItem, options: ConvertOptions) -> GifParams:
        o = self._opts(options)
        src_fps = item.info.fps if item.info else 30.0
        base = gif_params_for_quality(o.quality, src_fps)
        return GifParams(fps=resolve_fps(o, src_fps), max_colors=base.max_colors,
                         dither=base.dither, stats_mode=base.stats_mode)

    def output_fps(self, item: VideoItem, options: ConvertOptions) -> float:
        src_fps = item.info.fps if item.info else 30.0
        return resolve_fps(self._opts(options), src_fps)

    def scale_args(self, item: VideoItem, options: ConvertOptions) -> tuple[int | None, int | None]:
        o = self._opts(options)
        if item.info is None:
            return o.width, o.height
        return fit_size(item.info.width, item.info.height, o.width, o.height, o.lock_aspect, o.anchor)

    def output_dimensions(self, item: VideoItem, options: ConvertOptions) -> tuple[int, int]:
        if item.info is None:
            return 0, 0
        w, h = self.scale_args(item, options)
        return resolve_dimensions(item.info.width, item.info.height, w, h)

    # ------------------------------------------------------------------ 명령
    def build_command(self, ffmpeg: Path, item: VideoItem, options: ConvertOptions,
                      output_path: Path) -> list[str]:
        o = self._opts(options)
        if item.info is None:
            raise ValueError("Item has no media info.")
        info = item.info
        p = self.params(item, o)
        rng = item.effective_range()

        cmd: list[str] = [str(ffmpeg), "-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
        if o.hwaccel == "auto":
            cmd += ["-hwaccel", "auto"]
        if not rng.is_full(info):
            start_sec, dur_sec = rng.to_seconds(info.fps)
            cmd += ["-ss", f"{start_sec:.3f}", "-t", f"{dur_sec:.3f}"]
        cmd += ["-i", str(item.path)]

        chain = [f"fps={_fmt_fps(p.fps)}"]
        w, h = self.scale_args(item, o)
        if w is not None or h is not None:
            chain.append(f"scale={w}:{h}:flags=lanczos")
        filter_complex = (
            f"[0:v]{','.join(chain)},split[a][b];"
            f"[a]palettegen=max_colors={p.max_colors}:stats_mode={p.stats_mode}[p];"
            f"[b][p]paletteuse=dither={p.dither}"
        )
        cmd += ["-filter_complex", filter_complex, "-loop", str(int(o.loop)), str(output_path)]
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
                          last_size: int, target: int, src_w: int = 0, src_fps: float = 30.0) -> GifOptions | None:
        """attempt: 지금까지 실패한 시도 수(1부터). PLAN 5.6."""
        o = self._opts(options)
        if attempt >= o.max_attempts:
            return None
        new = replace(o, quality=max(5, o.quality - 15))
        if o.fps_mode in ("source", "custom"):
            current_fps = resolve_fps(o, src_fps)
            new = replace(new, fps_mode="custom", fps_custom=max(5.0, float(round(current_fps * 0.75))))
        if attempt >= 2:
            base_w = o.width if o.width else (src_w or None)
            if base_w:
                new_w = max(16, int(round(base_w * 0.85)))
                new = replace(new, width=new_w)
                if not o.lock_aspect and o.height:
                    new = replace(new, height=max(16, int(round(o.height * 0.85))))
                else:
                    new = replace(new, anchor="width", height=None if o.lock_aspect else new.height)
        return new

    # ------------------------------------------------------------------ 추정 · 경고
    def heuristic_size(self, item: VideoItem, options: ConvertOptions) -> int | None:
        if item.info is None:
            return None
        o = self._opts(options)
        p = self.params(item, o)
        rng = item.effective_range()
        _, dur = rng.to_seconds(item.info.fps)
        frames = output_frames(dur, p.fps)
        w, h = self.output_dimensions(item, o)
        return heuristic_gif_size(frames, w, h, p.max_colors, p.dither_family)

    def estimate_warning(self, item: VideoItem, options: ConvertOptions) -> str | None:
        if item.info is None:
            return None
        p = self.params(item, options)
        rng = item.effective_range()
        _, dur = rng.to_seconds(item.info.fps)
        frames = output_frames(dur, p.fps)
        w, h = self.output_dimensions(item, options)
        if frames * w * h > C.LARGE_OUTPUT_PIXELS:
            return f"Output may be very large ({frames} frames at {w}x{h})."
        return None

    # ------------------------------------------------------------------ 내부
    @staticmethod
    def _opts(options: ConvertOptions) -> GifOptions:
        if isinstance(options, GifOptions):
            return options
        raise TypeError(f"GifConverter expects GifOptions, got {type(options).__name__}")
