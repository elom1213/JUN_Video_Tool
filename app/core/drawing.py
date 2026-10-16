# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""Draw 탭 데이터 모델 · 고스트 계산 · 지우개 · JSON (PLAN_DRAW_TAB 4.2, 6, 7, 13.3). PySide6 비의존."""
from __future__ import annotations

import bisect
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import constants as C

_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class DrawingFormatError(Exception):
    pass


@dataclass
class Stroke:
    color: str                                  # "#rrggbb"
    width: float                                # 소스 픽셀
    points: list[tuple[float, float]]           # 소스 픽셀 좌표, 길이 ≥ 1 (1 이면 점)
    opacity: float = 1.0                        # 예비. 이번 UI 는 항상 1.0

    def copy(self) -> "Stroke":
        return Stroke(self.color, self.width, list(self.points), self.opacity)

    def to_dict(self) -> dict:
        d: dict = {"color": self.color, "width": round(float(self.width), 2),
                   "points": [[round(float(x), 2), round(float(y), 2)] for x, y in self.points]}
        if abs(self.opacity - 1.0) > 1e-9:
            d["opacity"] = round(float(self.opacity), 3)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Stroke":
        """형식 오류면 ValueError (호출자가 그 스트로크만 건너뛴다)."""
        color = str(d.get("color", ""))
        if not _COLOR_RE.match(color):
            raise ValueError(f"bad color: {color!r}")
        width = float(d.get("width", C.DRAW_WIDTH_DEFAULT))
        if not (width > 0):
            raise ValueError("bad width")
        pts = [(float(p[0]), float(p[1])) for p in (d.get("points") or [])]
        if not pts:
            raise ValueError("no points")
        return cls(color=color.lower(), width=width, points=pts, opacity=float(d.get("opacity", 1.0)))


@dataclass
class DrawingDocument:
    video_name: str
    video_path: str
    width: int
    height: int
    fps: float
    frame_count: int
    frames: dict[int, list[Stroke]] = field(default_factory=dict)
    dirty: bool = False
    load_warnings: int = 0                      # from_json 이 버린 깨진 스트로크 수

    def __post_init__(self) -> None:
        # 프레임별 스냅숏 스택 (13.3): 항목 = 그 프레임의 스트로크 리스트 전체 사본
        self._undo: dict[int, list[list[Stroke]]] = {}
        self._redo: dict[int, list[list[Stroke]]] = {}

    # ------------------------------------------------------------------ 편집
    def _snapshot(self, frame: int) -> list[Stroke]:
        return [s.copy() for s in self.frames.get(frame, [])]

    def _set_frame(self, frame: int, strokes: list[Stroke]) -> None:
        if strokes:
            self.frames[frame] = strokes
        else:
            self.frames.pop(frame, None)

    def _push_undo(self, frame: int) -> None:
        self._undo.setdefault(frame, []).append(self._snapshot(frame))
        self._redo.pop(frame, None)
        self.dirty = True

    def add_stroke(self, frame: int, stroke: Stroke) -> None:
        self._push_undo(frame)
        self.frames.setdefault(frame, []).append(stroke)

    def replace_frame(self, frame: int, strokes: list[Stroke]) -> None:
        """지우개 결과 등으로 그 프레임 전체를 바꾼다 (undo 1단계)."""
        self._push_undo(frame)
        self._set_frame(frame, [s.copy() for s in strokes])

    def undo(self, frame: int) -> bool:
        stack = self._undo.get(frame)
        if not stack:
            return False
        self._redo.setdefault(frame, []).append(self._snapshot(frame))
        self._set_frame(frame, stack.pop())
        self.dirty = True
        return True

    def redo(self, frame: int) -> bool:
        stack = self._redo.get(frame)
        if not stack:
            return False
        self._undo.setdefault(frame, []).append(self._snapshot(frame))
        self._set_frame(frame, stack.pop())
        self.dirty = True
        return True

    def can_undo(self, frame: int) -> bool:
        return bool(self._undo.get(frame))

    def can_redo(self, frame: int) -> bool:
        return bool(self._redo.get(frame))

    def clear_frame(self, frame: int) -> int:
        n = len(self.frames.get(frame, []))
        if n:
            self._push_undo(frame)
            self.frames.pop(frame, None)
        return n

    def clear_all(self) -> int:
        """모든 프레임을 비운다. 프레임마다 undo 스냅숏을 남긴다. 반환 = 지운 스트로크 수."""
        total = 0
        for f in list(self.frames):
            total += self.clear_frame(f)
        return total

    def strokes_at(self, frame: int) -> list[Stroke]:
        return self.frames.get(frame, [])

    def frames_with_strokes(self) -> list[int]:
        return sorted(f for f, s in self.frames.items() if s)

    def prev_drawn_frame(self, frame: int) -> int | None:
        """frame 보다 앞에서 그림이 있는 가장 가까운 프레임. 없으면 None."""
        frames = self.frames_with_strokes()
        i = bisect.bisect_left(frames, frame)
        return frames[i - 1] if i > 0 else None

    def next_drawn_frame(self, frame: int) -> int | None:
        """frame 보다 뒤에서 그림이 있는 가장 가까운 프레임. 없으면 None."""
        frames = self.frames_with_strokes()
        i = bisect.bisect_right(frames, frame)
        return frames[i] if i < len(frames) else None

    def stroke_count(self) -> int:
        return sum(len(s) for s in self.frames.values())

    def is_empty(self) -> bool:
        return not any(self.frames.values())

    # ------------------------------------------------------------------ 직렬화
    def to_json(self) -> str:
        data = {
            "format": C.DRAW_FORMAT_NAME,
            "version": C.DRAW_FORMAT_VERSION,
            "video": {"name": self.video_name, "path": self.video_path.replace("\\", "/"),
                      "width": int(self.width), "height": int(self.height),
                      "fps": round(float(self.fps), 6), "frame_count": int(self.frame_count)},
            "frames": {str(f): [s.to_dict() for s in self.frames[f]] for f in self.frames_with_strokes()},
        }
        return json.dumps(data, ensure_ascii=False, indent=None)

    @classmethod
    def from_json(cls, text: str) -> "DrawingDocument":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DrawingFormatError(f"Invalid JSON: {exc}") from exc
        if not isinstance(data, dict) or data.get("format") != C.DRAW_FORMAT_NAME:
            raise DrawingFormatError("Unsupported drawing file.")
        try:
            version = int(data.get("version", 0))
        except (TypeError, ValueError):
            version = 0
        if version < 1 or version > C.DRAW_FORMAT_VERSION:
            raise DrawingFormatError("Unsupported drawing file.")
        v = data.get("video") or {}
        try:
            doc = cls(video_name=str(v.get("name", "")), video_path=str(v.get("path", "")),
                      width=int(v.get("width", 0)), height=int(v.get("height", 0)),
                      fps=float(v.get("fps", 0.0)), frame_count=int(v.get("frame_count", 0)))
        except (TypeError, ValueError) as exc:
            raise DrawingFormatError("Unsupported drawing file.") from exc
        bad = 0
        for key, strokes in (data.get("frames") or {}).items():
            try:
                f = int(key)
            except (TypeError, ValueError):
                bad += len(strokes or [])
                continue
            if f < 0:
                bad += len(strokes or [])
                continue
            out: list[Stroke] = []
            for sd in strokes or []:
                try:
                    out.append(Stroke.from_dict(sd))
                except (TypeError, ValueError, IndexError, AttributeError):
                    bad += 1
            if out:
                doc.frames[f] = out
        doc.load_warnings = bad
        doc.dirty = False
        return doc

    def rescaled(self, width: int, height: int) -> "DrawingDocument":
        """다른 해상도 영상에 입힐 때 점 · 두께를 비율로 변환 (두께는 높이 비율)."""
        sx = width / self.width if self.width else 1.0
        sy = height / self.height if self.height else 1.0
        doc = DrawingDocument(self.video_name, self.video_path, width, height, self.fps, self.frame_count)
        for f, strokes in self.frames.items():
            doc.frames[f] = [Stroke(s.color, s.width * sy, [(x * sx, y * sy) for x, y in s.points], s.opacity)
                             for s in strokes]
        doc.dirty = True
        return doc


# ---------------------------------------------------------------------------
# 고스트 (7장)
# ---------------------------------------------------------------------------
def ghost_alpha(distance: int, span: int, opacity: float) -> float:
    """opacity × (1 − (d−1)/N). distance ≥ 1, span ≥ distance."""
    if span <= 0 or distance < 1:
        return 0.0
    return max(0.0, float(opacity) * (1.0 - (distance - 1) / span))


def ghost_frames(frame: int, before: int, after: int, last_frame: int) -> list[tuple[int, int]]:
    """[(frame_index, distance), …] — 자기 자신 제외, 0 ≤ idx ≤ last_frame, 프레임 오름차순."""
    out: list[tuple[int, int]] = []
    for d in range(max(0, before), 0, -1):
        idx = frame - d
        if 0 <= idx <= last_frame:
            out.append((idx, d))
    for d in range(1, max(0, after) + 1):
        idx = frame + d
        if 0 <= idx <= last_frame:
            out.append((idx, d))
    return out


# ---------------------------------------------------------------------------
# 지우개 (13.3)
# ---------------------------------------------------------------------------
def densify(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """연속 점 사이 거리가 step 을 넘으면 중간 점을 끼워 넣는다."""
    if len(points) < 2 or step <= 0:
        return list(points)
    out = [points[0]]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        n = int(d // step)
        for k in range(1, n + 1):
            t = k * step / d
            if t < 1.0:
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        out.append((x1, y1))
    return out


def _dist_point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _near_path(px: float, py: float, path: list[tuple[float, float]], limit: float) -> bool:
    if len(path) == 1:
        return math.hypot(px - path[0][0], py - path[0][1]) <= limit
    for (ax, ay), (bx, by) in zip(path, path[1:]):
        if _dist_point_segment(px, py, ax, ay, bx, by) <= limit:
            return True
    return False


def erase_strokes(strokes: list[Stroke], path: list[tuple[float, float]],
                  radius: float) -> tuple[list[Stroke], bool]:
    """지우개 경로(소스 좌표)에 닿는 점을 지우고 남은 연속 구간을 새 스트로크로 분할한다.

    점이 지워지는 조건: 지우개 경로(선분 열)까지 거리 ≤ radius + stroke.width / 2.
    반환 = (새 스트로크 리스트, 바뀜 여부). 입력 리스트는 건드리지 않는다.
    """
    if not path or radius <= 0:
        return list(strokes), False
    xs = [p[0] for p in path]
    ys = [p[1] for p in path]
    changed = False
    out: list[Stroke] = []
    for s in strokes:
        limit = radius + s.width / 2.0
        # 바운딩 박스로 빠르게 거른다
        sx = [p[0] for p in s.points]
        sy = [p[1] for p in s.points]
        if (min(sx) > max(xs) + limit or max(sx) < min(xs) - limit
                or min(sy) > max(ys) + limit or max(sy) < min(ys) - limit):
            out.append(s)
            continue
        pts = densify(s.points, max(1.0, s.width / 2.0))
        keep = [not _near_path(x, y, path, limit) for x, y in pts]
        if all(keep):
            out.append(s)
            continue
        changed = True
        seg: list[tuple[float, float]] = []
        for p, k in zip(pts, keep):
            if k:
                seg.append(p)
            elif seg:
                out.append(Stroke(s.color, s.width, seg, s.opacity))
                seg = []
        if seg:
            out.append(Stroke(s.color, s.width, seg, s.opacity))
    return out, changed


def sidecar_path(video: Path) -> Path:
    """C:/a/clip.mp4 → C:/a/.draw/clip.mp4.draw.json.

    영상 폴더 안의 `.draw` 하위 폴더에 모은다 (영상 옆을 어지럽히지 않게). 확장자 교체가 아니라 덧붙임이라
    clip.mp4 와 clip.mov 가 같은 폴더에 있어도 충돌하지 않는다. 폴더는 저장할 때 만든다.
    """
    video = Path(video)
    return video.parent / C.DRAW_DIR_NAME / (video.name + C.DRAW_FILE_SUFFIX)


def legacy_sidecar_path(video: Path) -> Path:
    """v0.3.0 초기 위치 (영상 바로 옆). 새 위치에 파일이 없을 때 읽기 전용 폴백."""
    video = Path(video)
    return video.with_name(video.name + C.DRAW_FILE_SUFFIX)
