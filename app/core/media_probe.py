# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""영상 메타데이터 프로브 (PLAN 5.2). ffprobe JSON 우선, 없으면 ffmpeg stderr 파싱."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .ffmpeg_locator import find_ffmpeg, find_ffprobe
from .models import MediaInfo
from .utils import subprocess_flags

DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?Video:\s*(\w+).*?,\s*(\d{2,5})x(\d{2,5})")
FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
TBR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*tbr")
AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?Audio:")


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
    videos = [s for s in streams if s.get("codec_type", "video") == "video"]
    if not videos:
        raise ProbeError("No video stream found.")
    st = videos[0]
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    fmt = data.get("format") or {}

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
    )


def parse_ffmpeg_stderr(text: str, size_bytes: int) -> MediaInfo:
    """`ffmpeg -i` 의 stderr → MediaInfo (ffprobe 폴백)."""
    m = DURATION_RE.search(text)
    if not m:
        raise ProbeError("Could not parse duration from ffmpeg output.")
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    vm = VIDEO_RE.search(text)
    if not vm:
        raise ProbeError("No video stream found.")
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
        has_audio=bool(AUDIO_RE.search(text)),
    )


def _probe_ffprobe(ffprobe: Path, path: Path) -> MediaInfo:
    cmd = [
        str(ffprobe), "-v", "error",
        "-show_entries", "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,nb_frames,codec_name,duration",
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
