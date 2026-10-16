# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""코어 데이터 모델 (PLAN 5.1). PySide6 비의존."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ItemStatus(Enum):
    IDLE = "Idle"
    QUEUED = "Queued"
    RUNNING = "Running"
    DONE = "Done"
    FAILED = "Failed"
    CANCELED = "Canceled"
    SKIPPED = "Skipped"


@dataclass
class MediaInfo:
    width: int
    height: int
    fps: float
    duration: float
    frame_count: int
    codec: str
    size_bytes: int
    has_audio: bool = False      # 오디오 스트림 존재 (Draw 탭 재생 · 내보내기)

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 16 / 9

    @property
    def last_frame(self) -> int:
        return max(0, self.frame_count - 1)


@dataclass
class FrameRange:
    start_frame: int
    end_frame: int

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame + 1

    def clamp(self, info: MediaInfo) -> "FrameRange":
        last = info.last_frame
        s = max(0, min(self.start_frame, last))
        e = max(s, min(self.end_frame, last))
        return FrameRange(s, e)

    def to_seconds(self, fps: float) -> tuple[float, float]:
        """(start_sec, duration_sec)."""
        if fps <= 0:
            return 0.0, 0.0
        return self.start_frame / fps, self.frame_count / fps

    def is_full(self, info: MediaInfo) -> bool:
        return self.start_frame <= 0 and self.end_frame >= info.last_frame

    @classmethod
    def full(cls, info: MediaInfo) -> "FrameRange":
        return cls(0, info.last_frame)


@dataclass
class VideoItem:
    path: Path
    info: MediaInfo | None = None
    probe_error: str | None = None
    checked: bool = True
    frame_range: FrameRange | None = None
    status: ItemStatus = ItemStatus.IDLE
    progress: int = 0
    message: str = ""
    output_path: Path | None = None
    est_size: int | None = None
    est_level: str = "none"      # "none" | "heuristic" | "sampled" | "exact" | "failed"
    est_key: str = ""

    def effective_range(self) -> FrameRange:
        if self.info is None:
            return FrameRange(0, 0)
        if self.frame_range is None:
            return FrameRange.full(self.info)
        return self.frame_range.clamp(self.info)


@dataclass
class ConvertOptions:
    """모든 포맷 옵션의 베이스."""
    format_id: str = ""
    output_dir: Path | None = None
    suffix: str = ""
    overwrite: bool = False


@dataclass
class ConvertJob:
    item: VideoItem
    options: ConvertOptions
    output_path: Path


@dataclass
class ConvertResult:
    job: ConvertJob
    ok: bool
    output_size: int = 0
    elapsed: float = 0.0
    error: str = ""
    attempts: int = 1
    canceled: bool = False
    message: str = ""
    log_lines: list[str] = field(default_factory=list)
