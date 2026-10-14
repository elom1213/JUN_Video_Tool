# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""변환기 추상화 (PLAN 5.5). 새 포맷은 이 클래스를 구현해 registry 에 등록한다."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
from pathlib import Path

from ..models import ConvertOptions, FrameRange, VideoItem


class BaseConverter(ABC):
    format_id: str = ""
    display_name: str = ""
    extension: str = ""
    options_cls: type[ConvertOptions] = ConvertOptions

    # ----- 필수 -----
    @abstractmethod
    def default_options(self) -> ConvertOptions: ...

    @abstractmethod
    def validate(self, options: ConvertOptions) -> list[str]:
        """문제 목록(영어 문장). 비어 있으면 OK."""

    @abstractmethod
    def build_command(self, ffmpeg: Path, item: VideoItem, options: ConvertOptions,
                      output_path: Path) -> list[str]:
        """실행할 ffmpeg argv. 마지막 원소는 output_path 문자열."""

    # ----- 선택 -----
    def output_fps(self, item: VideoItem, options: ConvertOptions) -> float:
        """출력 프레임레이트 (UI 표기·추정용). 기본은 원본 fps."""
        return item.info.fps if item.info else 0.0

    def output_dimensions(self, item: VideoItem, options: ConvertOptions) -> tuple[int, int]:
        """실제 출력 픽셀 치수 (추정·경고용). 기본은 원본."""
        if item.info is None:
            return 0, 0
        return item.info.width, item.info.height

    def supports_target_size(self) -> bool:
        return False

    def target_size_bytes(self, options: ConvertOptions) -> int | None:
        return None

    def degrade_for_retry(self, options: ConvertOptions, attempt: int,
                          last_size: int, target: int,
                          src_w: int = 0, src_fps: float = 30.0) -> ConvertOptions | None:
        """타깃 크기 초과 시 다음 시도용 옵션(새 객체). None 이면 포기."""
        return None

    def estimate_warning(self, item: VideoItem, options: ConvertOptions) -> str | None:
        return None

    def heuristic_size(self, item: VideoItem, options: ConvertOptions) -> int | None:
        return None

    def supports_sample_estimate(self) -> bool:
        return True

    def build_sample_command(self, ffmpeg: Path, item: VideoItem, options: ConvertOptions,
                             sample_range: FrameRange, output_path: Path) -> list[str] | None:
        """sample_range 만 같은 옵션으로 인코딩하는 argv. 기본: item 복사 후 frame_range 교체."""
        if not self.supports_sample_estimate():
            return None
        sample_item = replace(item, frame_range=sample_range)
        return self.build_command(ffmpeg, sample_item, options, output_path)


class ConverterRegistry:
    def __init__(self) -> None:
        self._items: dict[str, BaseConverter] = {}

    def register(self, conv: BaseConverter) -> None:
        if conv.format_id in self._items:
            raise ValueError(f"Converter already registered: {conv.format_id}")
        self._items[conv.format_id] = conv

    def get(self, format_id: str) -> BaseConverter:
        return self._items[format_id]

    def all(self) -> list[BaseConverter]:
        return list(self._items.values())

    def ids(self) -> list[str]:
        return list(self._items.keys())
