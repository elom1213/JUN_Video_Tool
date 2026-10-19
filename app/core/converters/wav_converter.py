# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""WAV 변환기 — 영상 · 음성 파일의 소리를 JUN_JALI(VisemeNet Converter) 가 그대로 받는 wav 로 뽑는다.

출력 규격은 고정: 44100 Hz · 16-bit PCM (pcm_s16le) · 모노. JUN_JALI 는 리샘플을 하지 않고 정규화 값이 이 규격
기준이라, 다르면 에러 없이 틀린 립싱크가 나온다. 모델은 왼쪽 채널만 쓰므로 스테레오 대신 모노로 만든다
(기본은 두 채널을 섞는다 — 한쪽에만 목소리가 있는 녹음이면 Left / Right 를 고른다).
메타데이터 청크 없이(bitexact) 44 바이트 헤더의 순수 PCM wav 를 쓴다 — 마야 sound 노드도 바로 읽는다.
변환 뒤 post_check 가 출력 파일을 JUN_JALI 규칙(jali_wav.check_jali_wav)으로 다시 검사한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...config import constants as C
from ..jali_wav import JaliWavError, check_jali_wav
from ..models import ConvertOptions, VideoItem
from .base import BaseConverter

CHANNEL_MODES = ("mix", "left", "right")
WAV_HEADER_BYTES = 44


@dataclass
class WavOptions(ConvertOptions):
    format_id: str = "wav"
    channels: str = "mix"            # "mix" (모든 채널 평균) | "left" | "right"
    check_jali: bool = True          # 변환 뒤 JUN_JALI 규칙으로 검사
    max_seconds: float = C.JALI_MAX_SECONDS   # 이보다 길면 경고 (JUN_JALI 의 Max length)


def channel_filter(mode: str, src_channels: int) -> str:
    """모노 1 채널로 만드는 pan 필터. 원본이 모노(또는 모름)면 오른쪽 채널이 없으므로 첫 채널을 쓴다."""
    if mode == "left" or src_channels == 1:
        return "pan=mono|c0=c0"
    if mode == "right":
        return "pan=mono|c0=c1" if src_channels >= 2 else "pan=mono|c0=c0"
    if src_channels >= 2:
        # 평균 (합이 1 이므로 같은 소리가 두 채널에 꽉 차 있어도 클리핑되지 않는다)
        k = 1.0 / src_channels
        return "pan=mono|c0=" + "+".join(f"{k:.6g}*c{i}" for i in range(src_channels))
    return "pan=mono|c0=c0"


class WavConverter(BaseConverter):
    format_id = "wav"
    display_name = "WAV (JUN_JALI 44.1 kHz 16-bit mono)"
    extension = ".wav"
    options_cls = WavOptions
    needs_video = False
    needs_audio = True

    def default_options(self) -> WavOptions:
        return WavOptions()

    def validate(self, options: ConvertOptions) -> list[str]:
        o = self._opts(options)
        problems: list[str] = []
        if o.channels not in CHANNEL_MODES:
            problems.append(f"Unknown channel mode: {o.channels}")
        if o.max_seconds <= 0:
            problems.append("Max length must be greater than 0 s.")
        if o.output_dir is not None and not Path(o.output_dir).is_dir():
            problems.append(f"Output folder does not exist: {o.output_dir}")
        return problems

    # ------------------------------------------------------------------ 파생 값
    def output_fps(self, item: VideoItem, options: ConvertOptions) -> float:
        return 0.0                   # 프레임 출력이 없다 (구간 패널의 "→ output frames" 표기를 끈다)

    def output_dimensions(self, item: VideoItem, options: ConvertOptions) -> tuple[int, int]:
        return 0, 0

    def duration(self, item: VideoItem) -> float:
        if item.info is None:
            return 0.0
        return item.effective_range().to_seconds(item.info.fps)[1]

    # ------------------------------------------------------------------ 명령
    def build_command(self, ffmpeg: Path, item: VideoItem, options: ConvertOptions,
                      output_path: Path) -> list[str]:
        o = self._opts(options)
        if item.info is None:
            raise ValueError("Item has no media info.")
        info = item.info
        cmd: list[str] = [str(ffmpeg), "-hide_banner", "-y", "-nostats", "-progress", "pipe:1"]
        rng = item.effective_range()
        chain = f"{channel_filter(o.channels, info.channels)},aresample={C.JALI_SAMPLE_RATE}"
        if not rng.is_full(info):
            start_sec, dur_sec = rng.to_seconds(info.fps)
            # 입력 -t 는 AAC · MP3 프레임 경계에 걸려 몇 ms 어긋난다 → 넉넉히 읽고, 리샘플 뒤 샘플 수로 정확히 자른다
            cmd += ["-ss", f"{start_sec:.3f}", "-t", f"{dur_sec + 0.5:.3f}"]
            chain += f",atrim=end_sample={int(round(dur_sec * C.JALI_SAMPLE_RATE))}"
        cmd += ["-i", str(item.path),
                "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
                "-af", chain,
                "-ar", str(C.JALI_SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le",
                "-fflags", "+bitexact", "-flags:a", "+bitexact", "-f", "wav", str(output_path)]
        return cmd

    # ------------------------------------------------------------------ 추정 (정확: 무압축)
    def heuristic_size(self, item: VideoItem, options: ConvertOptions) -> int | None:
        if item.info is None or not item.info.has_audio:
            return None
        return WAV_HEADER_BYTES + int(round(self.duration(item) * C.JALI_SAMPLE_RATE)) * 2

    def heuristic_level(self) -> str:
        return "exact"

    def supports_sample_estimate(self) -> bool:
        return False

    def estimate_warning(self, item: VideoItem, options: ConvertOptions) -> str | None:
        o = self._opts(options)
        dur = self.duration(item)
        if dur < C.JALI_MIN_SECONDS:
            return f"only {dur:.2f} s - JUN_JALI needs at least {C.JALI_MIN_SECONDS:g} s."
        if dur > o.max_seconds:
            return (f"{dur:.1f} s is longer than {o.max_seconds:g} s - JUN_JALI rejects it unless you raise "
                    f"its Max length. Trim the range or split the file.")
        return None

    # ------------------------------------------------------------------ 변환 뒤 검사
    def post_check(self, output_path: Path, item: VideoItem, options: ConvertOptions) -> tuple[str, str]:
        o = self._opts(options)
        if not o.check_jali:
            return "ok", ""
        try:
            info = check_jali_wav(output_path, max_seconds=None)
        except JaliWavError as exc:
            return "error", f"JUN_JALI check failed: {exc.code} {exc.message}"
        notes = [f"{code} {msg}" for code, msg in info.warnings]
        if info.seconds > o.max_seconds:
            notes.append(f"E07 longer than {o.max_seconds:g} s - raise Max length in JUN_JALI or split")
        text = f"JUN_JALI ready ({info.summary()})"
        return ("warn", text + " - " + "; ".join(notes)) if notes else ("ok", text)

    @staticmethod
    def _opts(options: ConvertOptions) -> WavOptions:
        if isinstance(options, WavOptions):
            return options
        raise TypeError(f"WavConverter expects WavOptions, got {type(options).__name__}")
