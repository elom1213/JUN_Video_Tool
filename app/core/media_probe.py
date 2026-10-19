# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""영상 · 음성 메타데이터 프로브 (PLAN 5.2). ffprobe JSON 우선, 없으면 ffmpeg stderr 파싱.

비디오 스트림이 없고 오디오만 있으면 음성 전용 MediaInfo (audio_only, 1 프레임 = 1 ms) 를 돌려준다.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from ..config import constants as C
from .ffmpeg_locator import find_ffmpeg, find_ffprobe
from .models import MediaInfo
from .utils import subprocess_flags

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?Video:\s*(\w+).*?,\s*(\d{2,5})x(\d{2,5})")
FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
TBR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*tbr")
AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?Audio:")
AUDIO_DETAIL_RE = re.compile(r"Stream #\d+:\d+.*?Audio:\s*(\w+)[^\n]*?,\s*(\d+)\s*Hz,\s*([^,\n]+)")
_LAYOUT_CHANNELS = {"mono": 1, "stereo": 2, "2.1": 3, "quad": 4, "4.0": 4, "5.0": 5, "5.1": 6, "5.1(side)": 6,
                    "6.1": 7, "7.1": 8}


def layout_channels(text: str) -> int:
    """ffmpeg 채널 레이아웃 표기 → 채널 수 ("stereo" → 2, "3 channels" → 3, 모르면 0)."""
    t = text.strip().lower()
    m = re.match(r"(\d+)\s*channels?", t)
    if m:
        return int(m.group(1))
    return _LAYOUT_CHANNELS.get(t, 0)


def audio_only_info(duration: float, codec: str, size_bytes: int, sample_rate: int, channels: int) -> MediaInfo:
    """음성 전용 파일의 MediaInfo. 구간 · 진행률 계산이 그대로 돌도록 1 ms 를 한 프레임으로 둔다."""
    if duration <= 0:
        raise ProbeError("Could not determine duration.")
    fps = C.AUDIO_TIMELINE_FPS
    return MediaInfo(width=0, height=0, fps=fps, duration=duration,
                     frame_count=max(1, int(round(duration * fps))), codec=codec or "unknown",
                     size_bytes=size_bytes, has_audio=True, audio_only=True,
                     sample_rate=int(sample_rate), channels=int(channels))


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start: end if end != -1 else len(text)]


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


class ProbeError(Exception):
    pass


def eval_fraction(text: str | None) -> float:
    """"30000/1001" → 29.97 ; "0/0" / "" / None → 0.0 ; "30" → 30.0"""
    if not text:
        return 0.0
    text = str(text).strip()
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return 0.0
            return float(num) / den_f
        return float(text)
    except (ValueError, ZeroDivisionError):
        return 0.0


def parse_ffprobe_json(text: str, size_fallback: int) -> MediaInfo:
    """ffprobe -of json 출력 → MediaInfo."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProbeError(f"ffprobe returned invalid JSON: {exc}") from exc
    streams = data.get("streams") or []
    # codec_type 이 있으면 첫 video 스트림을 고르고, 없으면(옛 출력 · -select_streams v:0) 첫 스트림을 비디오로 본다
    # mp3 · m4a 의 앨범 아트는 attached_pic 비디오 스트림으로 보인다 → 영상으로 치지 않는다
    videos = [s for s in streams if s.get("codec_type", "video") == "video"
              and not _int((s.get("disposition") or {}).get("attached_pic"))]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    has_audio = bool(audios)
    fmt = data.get("format") or {}
    size_fallback_bytes = _int(fmt.get("size")) or size_fallback
    a0 = audios[0] if audios else {}
    if not videos:
        if not audios:
            raise ProbeError("No video or audio stream found.")
        dur = 0.0
        for src in (fmt.get("duration"), a0.get("duration")):
            try:
                dur = float(src)  # type: ignore[arg-type]
                if dur > 0:
                    break
            except (TypeError, ValueError):
                continue
        return audio_only_info(dur, str(a0.get("codec_name") or ""), size_fallback_bytes,
                               _int(a0.get("sample_rate")), _int(a0.get("channels")))
    st = videos[0]

    width = int(st.get("width") or 0)
    height = int(st.get("height") or 0)
    if width <= 0 or height <= 0:
        raise ProbeError("Video stream has no valid dimensions.")

    fps = eval_fraction(st.get("avg_frame_rate"))
    if fps <= 0:
        fps = eval_fraction(st.get("r_frame_rate"))
    if fps <= 0:
        raise ProbeError("Could not determine frame rate.")

    duration = 0.0
    for src in (fmt.get("duration"), st.get("duration")):
        try:
            duration = float(src)  # type: ignore[arg-type]
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue
    if duration <= 0:
        raise ProbeError("Could not determine duration.")

    nb_frames = 0
    try:
        nb_frames = int(st.get("nb_frames") or 0)
    except (TypeError, ValueError):
        nb_frames = 0
    frame_count = nb_frames if nb_frames > 0 else max(1, int(round(duration * fps)))

    try:
        size_bytes = int(fmt.get("size") or size_fallback)
    except (TypeError, ValueError):
        size_bytes = size_fallback

    return MediaInfo(
        width=width, height=height, fps=fps, duration=duration,
        frame_count=frame_count, codec=str(st.get("codec_name") or "unknown"),
        size_bytes=size_bytes, has_audio=has_audio,
        sample_rate=_int(a0.get("sample_rate")), channels=_int(a0.get("channels")),
    )


def parse_ffmpeg_stderr(text: str, size_bytes: int) -> MediaInfo:
    """`ffmpeg -i` 의 stderr → MediaInfo (ffprobe 폴백)."""
    m = DURATION_RE.search(text)
    if not m:
        raise ProbeError("Could not parse duration from ffmpeg output.")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    am = AUDIO_DETAIL_RE.search(text)
    rate, channels = (int(am.group(2)), layout_channels(am.group(3))) if am else (0, 0)

    vm = next((v for v in VIDEO_RE.finditer(text) if "attached pic" not in _line_at(text, v.start())), None)
    if not vm:
        if am:
            return audio_only_info(duration, am.group(1), size_bytes, rate, channels)
        raise ProbeError("No video or audio stream found.")
    codec = vm.group(1)
    width, height = int(vm.group(2)), int(vm.group(3))

    # fps 는 비디오 스트림 줄에서 찾는다 (없으면 tbr)
    line_start = text.rfind("\n", 0, vm.start()) + 1
    line_end = text.find("\n", vm.end())
    line = text[line_start: line_end if line_end != -1 else len(text)]
    fm = FPS_RE.search(line) or TBR_RE.search(line)
    fps = float(fm.group(1)) if fm else 0.0
    if fps <= 0:
        raise ProbeError("Could not determine frame rate.")
    if duration <= 0:
        raise ProbeError("Could not determine duration.")

    return MediaInfo(
        width=width, height=height, fps=fps, duration=duration,
        frame_count=max(1, int(round(duration * fps))), codec=codec, size_bytes=size_bytes,
        has_audio=bool(AUDIO_RE.search(text)), sample_rate=rate, channels=channels,
    )


def _probe_ffprobe(ffprobe: Path, path: Path) -> MediaInfo:
    cmd = [
        str(ffprobe), "-v", "error",
        "-show_entries", "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,nb_frames,codec_name,duration,"
                         "sample_rate,channels",
        "-show_entries", "stream_disposition=attached_pic",
        "-show_entries", "format=duration,size",
        "-of", "json", str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=60, creationflags=subprocess_flags())
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffprobe timed out.") from exc
    if out.returncode != 0:
        raise ProbeError((out.stderr or "ffprobe failed.").strip().splitlines()[-1])
    size = path.stat().st_size if path.exists() else 0
    return parse_ffprobe_json(out.stdout, size)


def _probe_ffmpeg_stderr(ffmpeg: Path, path: Path) -> MediaInfo:
    cmd = [str(ffmpeg), "-hide_banner", "-i", str(path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=60, creationflags=subprocess_flags())
    except subprocess.TimeoutExpired as exc:
        raise ProbeError("ffmpeg timed out.") from exc
    size = path.stat().st_size if path.exists() else 0
    return parse_ffmpeg_stderr(out.stderr or "", size)


def probe(path: Path) -> MediaInfo:
    """경로의 영상 메타데이터. 실패 시 ProbeError."""
    path = Path(path)
    if not path.is_file():
        raise ProbeError("File not found.")
    ffprobe = find_ffprobe()
    if ffprobe is not None:
        return _probe_ffprobe(ffprobe, path)
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise ProbeError("ffmpeg/ffprobe not found.")
    return _probe_ffmpeg_stderr(ffmpeg, path)
