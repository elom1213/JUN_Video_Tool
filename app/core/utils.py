# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""순수 유틸리티: 프레임↔초 변환, 크기 계산, 출력 경로, 서브프로세스 플래그."""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path


def frame_to_sec(frame: int, fps: float) -> float:
    """프레임 번호(0-based) → 초."""
    if fps <= 0:
        return 0.0
    return frame / fps


def sec_to_frame(sec: float, fps: float) -> int:
    """초 → 프레임 번호 (floor, 부동소수 오차 보정)."""
    if fps <= 0:
        return 0
    v = sec * fps
    r = round(v)
    # 29.97 처럼 순환소수 fps 는 90/29.97*29.97 = 89.9999… 가 되므로 정수 근방은 정수로 본다
    if abs(v - r) < 1e-3:
        return int(r)
    return int(math.floor(v))


def format_timecode(sec: float, fps: float) -> str:
    """초 → "HH:MM:SS:FF"."""
    sec = max(0.0, sec)
    total_frames = sec_to_frame(sec, fps) if fps > 0 else 0
    whole = int(sec + 1e-6)
    ff = total_frames - sec_to_frame(float(whole), fps) if fps > 0 else 0
    hh, rem = divmod(whole, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def frame_timecode(frame: int, fps: float) -> str:
    """프레임 번호 → 비드롭 타임코드 "HH:MM:SS:FF" (명목 fps = round(fps)). 29.97 의 프레임 30 → 00:00:01:00."""
    nominal = max(1, int(round(fps))) if fps > 0 else 1
    frame = max(0, int(frame))
    ff = frame % nominal
    total = frame // nominal
    hh, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def format_duration(sec: float) -> str:
    """초 → "MM:SS" 또는 "H:MM:SS" (리스트 info 텍스트용)."""
    sec = max(0, int(round(sec)))
    hh, rem = divmod(sec, 3600)
    mm, ss = divmod(rem, 60)
    if hh:
        return f"{hh}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"


def fit_size(src_w: int, src_h: int, width: int | None, height: int | None,
             lock: bool, anchor: str) -> tuple[int | None, int | None]:
    """ffmpeg scale 필터에 넘길 (w, h).

    - 둘 다 None → (None, None): scale 필터 생략
    - lock=True : anchor 축 값은 그대로, 다른 축은 -2 (비율 유지 + 짝수 보정).
                  anchor 축이 None 이면 값이 있는 축을 anchor 로 간주.
    - lock=False: 주어진 값 그대로, None 인 축은 원본 값
    """
    if width is None and height is None:
        return None, None
    if lock:
        if anchor == "height" and height is not None:
            return -2, int(height)
        if anchor == "width" and width is not None:
            return int(width), -2
        # anchor 축이 비어 있으면 값이 있는 축을 기준으로
        if width is not None:
            return int(width), -2
        return -2, int(height)  # type: ignore[arg-type]
    w = int(width) if width is not None else int(src_w)
    h = int(height) if height is not None else int(src_h)
    return w, h


def resolve_dimensions(src_w: int, src_h: int, w: int | None, h: int | None) -> tuple[int, int]:
    """fit_size 결과(-2 포함)를 실제 픽셀 치수로 환산 (휴리스틱·경고용)."""
    if w is None and h is None:
        return src_w, src_h
    if w is not None and w > 0 and h is not None and h > 0:
        return w, h
    if w is not None and w > 0:
        hh = max(2, int(round(w * src_h / src_w / 2)) * 2) if src_w else src_h
        return w, hh
    if h is not None and h > 0:
        ww = max(2, int(round(h * src_w / src_h / 2)) * 2) if src_h else src_w
        return ww, h
    return src_w, src_h


def make_output_path(src: Path, out_dir: Path | None, suffix: str, ext: str, overwrite: bool) -> Path:
    """<out_dir or src.parent>/<stem><suffix><ext>. overwrite=False 이고 존재하면 _001, _002 … 를 붙인다.

    후보가 원본 파일 자신이면(GIF → GIF, 같은 폴더, 빈 접미사) overwrite 여부와 무관하게 번호를 붙인다.
    """
    src = Path(src)
    base_dir = Path(out_dir) if out_dir else src.parent
    if not ext.startswith("."):
        ext = "." + ext
    src_key = normcase_path(src)
    candidate = base_dir / f"{src.stem}{suffix}{ext}"
    if normcase_path(candidate) != src_key and (overwrite or not candidate.exists()):
        return candidate
    n = 1
    while True:
        candidate = base_dir / f"{src.stem}{suffix}_{n:03d}{ext}"
        if normcase_path(candidate) != src_key and (overwrite or not candidate.exists()):
            return candidate
        n += 1


def human_size(n_bytes: int | float | None) -> str:
    """바이트 → "1.8 MB" (1024 기준). None → ""."""
    if n_bytes is None:
        return ""
    n = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


def subprocess_flags() -> int:
    """Windows 면 콘솔 창 억제 플래그, 그 외 0."""
    if sys.platform.startswith("win"):
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def tail_lines(text: str, n: int = 20) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return "\n".join(lines[-n:])


def normcase_path(p: Path) -> str:
    """중복 비교용 정규화 키 (Windows 대소문자 무시)."""
    try:
        resolved = Path(p).resolve()
    except OSError:
        resolved = Path(p).absolute()
    return os.path.normcase(str(resolved))


def tool_root() -> Path:
    """저장소/툴 루트 (app/ 의 부모)."""
    return Path(__file__).resolve().parents[2]
