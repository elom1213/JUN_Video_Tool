# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""JUN_JALI (VisemeNet Converter) 입력 규격 검사 — 표준 라이브러리 wave 만 쓴다 (PySide6 · numpy 비의존).

규칙은 JUN_JALI/tools/VisemeNet_Converter/app/core/wav_check.py 의 check_wav() 와 같다 (코드 E02 ~ E08, W01 ~ W02).
WAV 변환 뒤 출력 파일을 이걸로 다시 읽어, JUN_JALI 가 그대로 받아 마야용 데이터로 바꿀 수 있는지 확인한다.
"""
from __future__ import annotations

import sys
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path

from ..config import constants as C

_CHUNK_FRAMES = 1 << 16


class JaliWavError(Exception):
    """JUN_JALI 가 거부하는 문제. code 는 JUN_JALI 와 같은 E02 ~ E08."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code} {message}")
        self.code = code
        self.message = message


@dataclass
class JaliWavInfo:
    sample_rate: int
    channels: int
    seconds: float
    peak: int
    warnings: list[tuple[str, str]] = field(default_factory=list)   # [(code, message)]

    def summary(self) -> str:
        return f"{self.sample_rate} Hz · int16 · {self.channels} ch · {self.seconds:.2f} s"


def check_jali_wav(path: Path, max_seconds: float | None = C.JALI_MAX_SECONDS) -> JaliWavInfo:
    """wav 하나를 JUN_JALI 규칙으로 검사한다. 통과하면 JaliWavInfo (경고 포함), 아니면 JaliWavError."""
    try:
        with wave.open(str(path), "rb") as w:
            rate, channels, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
            if rate != C.JALI_SAMPLE_RATE:
                raise JaliWavError("E03", f"sample rate {rate} Hz - VisemeNet needs {C.JALI_SAMPLE_RATE} Hz")
            if width != 2:
                raise JaliWavError("E04", f"sample format {width * 8}-bit - need 16-bit integer PCM")
            if channels > 2:
                raise JaliWavError("E05", f"{channels} channels - need mono or stereo")
            seconds = n / float(rate)
            if seconds < C.JALI_MIN_SECONDS:
                raise JaliWavError("E06", f"too short ({seconds:.2f} s, minimum {C.JALI_MIN_SECONDS:g} s)")
            if max_seconds and seconds > max_seconds:
                raise JaliWavError("E07", f"too long ({seconds:.1f} s > {max_seconds:g} s) - split the file")
            # 모델은 왼쪽(첫) 채널만 쓴다 — 무음 · 클리핑도 그 채널로 본다
            peak = 0
            clipped = 0
            total = 0
            while True:
                raw = w.readframes(_CHUNK_FRAMES)
                if not raw:
                    break
                a = array("h")
                a.frombytes(raw[: len(raw) - len(raw) % (2 * channels)])
                if sys.byteorder == "big":
                    a.byteswap()
                if channels == 2:
                    a = a[0::2]
                if not a:
                    continue
                total += len(a)
                lo, hi = min(a), max(a)
                peak = max(peak, hi, -lo)
                if hi >= C.JALI_CLIP_LEVEL or lo <= -C.JALI_CLIP_LEVEL:
                    clipped += sum(1 for s in a if s >= C.JALI_CLIP_LEVEL or s <= -C.JALI_CLIP_LEVEL)
    except JaliWavError:
        raise
    except (wave.Error, EOFError, OSError) as exc:
        # wave 는 PCM(포맷 1) 만 읽는다 — float · 압축 wav 는 여기서 걸린다 (JUN_JALI 도 E02 / E04)
        raise JaliWavError("E02", f"cannot read as PCM WAV: {str(exc).strip() or type(exc).__name__}") from exc
    if peak == 0:
        raise JaliWavError("E08", "silent audio")
    found: list[tuple[str, str]] = []
    if channels == 2:
        found.append(("W01", "stereo - only the left channel is used"))
    if total and clipped / total > C.JALI_CLIP_RATIO_WARN:
        found.append(("W02", f"clipping detected ({clipped / total * 100.0:.1f} % of samples)"))
    return JaliWavInfo(rate, channels, seconds, peak, found)
