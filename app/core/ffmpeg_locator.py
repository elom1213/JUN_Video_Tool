# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""ffmpeg / ffprobe 실행 파일 탐색 (PLAN 4장).

탐색 순서
  ffmpeg : 1) <tool>/bin/ffmpeg.exe  2) PATH  3) imageio_ffmpeg
  ffprobe: 1) <tool>/bin/ffprobe.exe 2) ffmpeg 와 같은 폴더  3) PATH
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .utils import subprocess_flags, tool_root

_FFMPEG: Path | None = None
_FFPROBE: Path | None = None
_SEARCHED = False

_EXE = ".exe" if sys.platform.startswith("win") else ""


def bin_dir() -> Path:
    return tool_root() / "bin"


def reset_cache() -> None:
    """설치 후 다시 탐색하도록 캐시를 비운다."""
    global _FFMPEG, _FFPROBE, _SEARCHED
    _FFMPEG = None
    _FFPROBE = None
    _SEARCHED = False


def _search() -> None:
    global _FFMPEG, _FFPROBE, _SEARCHED
    if _SEARCHED:
        return
    _SEARCHED = True

    # --- ffmpeg ---
    cand = bin_dir() / f"ffmpeg{_EXE}"
    if cand.is_file():
        _FFMPEG = cand
    else:
        which = shutil.which("ffmpeg")
        if which:
            _FFMPEG = Path(which)
        else:
            try:
                import imageio_ffmpeg  # type: ignore

                exe = imageio_ffmpeg.get_ffmpeg_exe()
                if exe and Path(exe).is_file():
                    _FFMPEG = Path(exe)
            except Exception:
                _FFMPEG = None

    # --- ffprobe ---
    cand = bin_dir() / f"ffprobe{_EXE}"
    if cand.is_file():
        _FFPROBE = cand
    elif _FFMPEG is not None and (_FFMPEG.parent / f"ffprobe{_EXE}").is_file():
        _FFPROBE = _FFMPEG.parent / f"ffprobe{_EXE}"
    else:
        which = shutil.which("ffprobe")
        _FFPROBE = Path(which) if which else None


def find_ffmpeg() -> Path | None:
    _search()
    return _FFMPEG


def find_ffprobe() -> Path | None:
    _search()
    return _FFPROBE


def ffmpeg_version(exe: Path | None = None) -> str:
    """`ffmpeg -version` 첫 줄. 실패 시 빈 문자열."""
    exe = exe or find_ffmpeg()
    if exe is None:
        return ""
    try:
        out = subprocess.run(
            [str(exe), "-version"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=10, creationflags=subprocess_flags(),
        )
        first = (out.stdout or out.stderr or "").splitlines()
        return first[0].strip() if first else ""
    except Exception:
        return ""
