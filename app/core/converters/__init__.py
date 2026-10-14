# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""변환기 레지스트리. 새 포맷은 여기서 register 한 줄만 추가한다."""
from __future__ import annotations

from .base import BaseConverter, ConverterRegistry
from .common import VideoOptions
from .gif_converter import GifConverter, GifOptions, resolve_fps
from .mp4_converter import Mp4Converter, Mp4Options, crf_for_quality, resolve_fps_mp4

registry = ConverterRegistry()
registry.register(GifConverter())
registry.register(Mp4Converter())


def get_converter(format_id: str) -> BaseConverter:
    return registry.get(format_id)


__all__ = ["BaseConverter", "ConverterRegistry", "VideoOptions", "GifConverter", "GifOptions",
           "Mp4Converter", "Mp4Options", "registry", "get_converter", "resolve_fps", "resolve_fps_mp4",
           "crf_for_quality"]
