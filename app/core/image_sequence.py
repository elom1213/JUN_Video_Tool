# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-26
"""이미지 시퀀스 (img.001.jpg, img.002.jpg …) 를 영상 한 개처럼 다룬다. PySide6 비의존.

표현: VideoItem.path 는 시퀀스의 **첫 프레임 파일** 이다 (실제 파일이라 is_file · stat · 사이드카 경로가 그대로 돈다).
그 파일부터 번호가 끊기지 않고 이어지는 파일들이 시퀀스다 — ffmpeg image2 가 첫 빈 번호에서 멈추는 것과 같은 규칙.
번호 자리 수는 첫 프레임의 숫자 글자 수 (`img.001.jpg` → `%03d`, `img.1.jpg` → `%01d`) 이고 ffmpeg 도 같은 sprintf 로
파일 이름을 만들므로 여기서 센 프레임 수와 ffmpeg 가 읽는 프레임 수가 일치한다.

이미지에는 fps 가 없으므로 sequence_fps() (설정 `sequence/fps`) 로 시간축을 만든다.
ffmpeg 입력 인자는 input_args() 한 곳에서 만든다 — 영상이면 `-i <path>`, 시퀀스면 image2 패턴 입력.
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ..config import constants as C

_NUM_RE = re.compile(r"^(.*?)(\d+)$")
_fps = C.SEQUENCE_FPS_DEFAULT
_lock = threading.Lock()
_cache: dict[tuple[str, int], "ImageSequence"] = {}   # (normcase 첫 프레임, 폴더 mtime_ns) → 시퀀스


@dataclass(frozen=True)
class ImageSequence:
    folder: Path
    prefix: str          # 숫자 앞 (img.)
    width: int           # 숫자 자리 수 (0 패딩 폭)
    suffix: str          # 숫자 뒤 확장자 (.jpg) — 첫 프레임 표기 그대로
    start: int           # 첫 프레임 번호
    count: int           # 이어지는 프레임 수 (번호 없는 단일 이미지는 1)
    numbered: bool = True

    def frame_name(self, n: int) -> str:
        return f"{self.prefix}{n:0{self.width}d}{self.suffix}"

    def frame_path(self, index: int) -> Path:
        """0-based 프레임 index 의 파일 (범위 밖은 양 끝으로)."""
        if not self.numbered:
            return self.folder / f"{self.prefix}{self.suffix}"
        i = max(0, min(int(index), self.count - 1))
        return self.folder / self.frame_name(self.start + i)

    @property
    def end(self) -> int:
        return self.start + self.count - 1

    @property
    def pattern(self) -> str:
        """ffmpeg image2 패턴 (이름의 % 는 %% 로)."""
        esc = lambda s: s.replace("%", "%%")   # noqa: E731
        return str(self.folder / f"{esc(self.prefix)}%0{self.width}d{esc(self.suffix)}")

    def display_name(self) -> str:
        """img.[001-120].jpg (단일 이미지는 파일 이름 그대로)."""
        if not self.numbered:
            return f"{self.prefix}{self.suffix}"
        if self.count == 1:
            return self.frame_name(self.start)
        return f"{self.prefix}[{self.start:0{self.width}d}-{self.end:0{self.width}d}]{self.suffix}"

    def stem(self) -> str:
        """출력 파일 이름용 — 번호와 그 앞 구분자를 뗀다 (img.001 → img, 0001 → 폴더 이름)."""
        if not self.numbered:
            return self.prefix
        s = self.prefix.rstrip("._- ")
        return s or self.folder.name or "sequence"

    def total_bytes(self) -> int:
        n = 0
        for i in range(self.count):
            try:
                n += self.frame_path(i).stat().st_size
            except OSError:
                pass
        return n


# ---------------------------------------------------------------------------
def sequence_fps() -> float:
    return _fps


def set_sequence_fps(fps: float) -> None:
    """시퀀스의 시간축 fps (설정 `sequence/fps`). 이미 목록에 있는 항목은 프로브할 때의 fps 를 그대로 쓴다."""
    global _fps
    try:
        v = float(fps)
    except (TypeError, ValueError):
        return
    if C.SEQUENCE_FPS_MIN <= v <= C.SEQUENCE_FPS_MAX:
        _fps = v


def is_image(path: Path | str) -> bool:
    return Path(path).suffix.lower() in C.IMAGE_EXTENSIONS


def _split(name: str) -> tuple[str, str, str] | None:
    """img.001.jpg → ("img.", "001", ".jpg"). 숫자로 끝나지 않는 이름은 None."""
    stem, ext = os.path.splitext(name)
    m = _NUM_RE.match(stem)
    if not m:
        return None
    return m.group(1), m.group(2), ext


def _names(folder: Path) -> set[str]:
    try:
        return {os.path.normcase(e.name) for e in os.scandir(folder) if e.is_file()}
    except OSError:
        return set()


def _run(names: set[str], prefix: str, suffix: str, n: int, width: int, down: bool) -> tuple[int, int]:
    """번호 n 에서 이어지는 구간 (lo, hi). down=False 면 아래로는 넓히지 않는다."""
    def has(k: int) -> bool:
        return k >= 0 and os.path.normcase(f"{prefix}{k:0{width}d}{suffix}") in names
    lo = hi = n
    if down:
        while has(lo - 1):
            lo -= 1
    while has(hi + 1):
        hi += 1
    return lo, hi


def _locate(path: Path, down: bool) -> ImageSequence | None:
    path = Path(path)
    if not is_image(path):
        return None
    parts = _split(path.name)
    if parts is None:
        stem, ext = os.path.splitext(path.name)
        return ImageSequence(path.parent, stem, 0, ext, 0, 1, numbered=False)
    prefix, digits, suffix = parts
    n = int(digits)
    names = _names(path.parent)
    names.add(os.path.normcase(path.name))
    best: tuple[int, int, int] | None = None   # (width, lo, hi)
    # 0 으로 시작하지 않는 번호(img.100.jpg)는 패딩 폭인지 패딩 없음인지 모른다 → 더 길게 이어지는 쪽
    for width in ([len(digits)] if digits.startswith("0") or len(digits) == 1 else [len(digits), 1]):
        lo, hi = _run(names, prefix, suffix, n, width, down)
        if best is None or hi - lo > best[2] - best[1]:
            best = (width, lo, hi)
    assert best is not None
    width, lo, hi = best
    return ImageSequence(path.parent, prefix, width, suffix, lo, hi - lo + 1)


def sequence_of(path: Path | str) -> ImageSequence | None:
    """첫 프레임 파일 → 그 파일부터 이어지는 시퀀스. 이미지가 아니면 None. 폴더가 안 바뀌면 캐시."""
    path = Path(path)
    if not is_image(path):
        return None
    try:
        mtime = path.parent.stat().st_mtime_ns
    except OSError:
        mtime = 0
    key = (os.path.normcase(str(path)), mtime)
    with _lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    seq = _locate(path, down=False)
    if seq is not None:
        with _lock:
            if len(_cache) > 256:
                _cache.clear()
            _cache[key] = seq
    return seq


def first_frame(path: Path | str) -> Path:
    """이미지면 그 파일이 속한 시퀀스의 첫 프레임 (아래로 이어지는 번호까지), 아니면 그대로."""
    seq = _locate(Path(path), down=True)
    return Path(path) if seq is None else seq.frame_path(0)


def collapse(paths: Iterable[Path | str]) -> list[Path]:
    """드롭 · 추가한 경로 목록에서 같은 시퀀스의 프레임들을 첫 프레임 하나로 모은다 (순서는 처음 나온 자리).

    img.001 ~ img.120 을 모두 끌어놓든 그중 한 장만 놓든 결과는 img.001.jpg 하나 (= 시퀀스 전체).
    """
    out: list[Path] = []
    seen: set[str] = set()
    folder_names: dict[str, set[str]] = {}
    for p in paths:
        p = Path(p)
        if is_image(p):
            # 같은 폴더의 프레임 수천 장을 하나씩 _locate 하면 느리다 → 이미 모은 시퀀스에 든 이름은 건너뛴다
            names = folder_names.get(os.path.normcase(str(p.parent)))
            if names is not None and os.path.normcase(p.name) in names:
                continue
            seq = _locate(p, down=True)
            if seq is not None:
                bucket = folder_names.setdefault(os.path.normcase(str(p.parent)), set())
                if seq.numbered:
                    bucket.update(os.path.normcase(seq.frame_name(seq.start + i)) for i in range(seq.count))
                p = seq.frame_path(0)
        key = os.path.normcase(str(p))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def display_name(path: Path | str) -> str:
    """리스트 · 로그에 보일 이름 (시퀀스는 img.[001-120].jpg)."""
    seq = sequence_of(path)
    return Path(path).name if seq is None else seq.display_name()


def media_stem(path: Path | str) -> str:
    """출력 파일 이름의 바탕 (시퀀스는 번호를 뗀 이름)."""
    seq = sequence_of(path)
    return Path(path).stem if seq is None else seq.stem()


def input_args(path: Path | str, fps: float | None = None) -> list[str]:
    """ffmpeg 입력 인자. 영상은 `-i <path>`, 시퀀스는 image2 패턴 입력 (fps 없으면 sequence_fps()).

    -ss / -t 는 이 앞에 붙인다 (image2 는 프레임 번호로 정확히 시크한다).
    """
    seq = sequence_of(path)
    if seq is None:
        return ["-i", str(path)]
    rate = f"{float(fps if fps and fps > 0 else _fps):.6g}"
    if not seq.numbered:
        return ["-f", "image2", "-pattern_type", "none", "-framerate", rate, "-i", str(path)]
    return ["-f", "image2", "-pattern_type", "sequence", "-framerate", rate,
            "-start_number", str(seq.start), "-i", seq.pattern]
