# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""스트로크 렌더 (PLAN_DRAW_TAB 5.2, 13.4). 캔버스와 내보내기가 같은 함수를 써서 결과가 같다."""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from ....core.drawing import DrawingDocument, Stroke, ghost_alpha, ghost_frames


def paint_strokes(painter: QPainter, strokes: Iterable[Stroke], scale: float, ox: float = 0.0, oy: float = 0.0,
                  opacity: float = 1.0) -> None:
    """소스 좌표 스트로크를 (ox, oy) + p * scale 위치에 그린다."""
    if opacity <= 0:
        return
    painter.save()
    painter.setOpacity(opacity)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for s in strokes:
        if not s.points:
            continue
        color = QColor(s.color)
        if s.opacity < 1.0:
            color.setAlphaF(max(0.0, min(1.0, s.opacity)))
        pen = QPen(color, max(0.5, s.width * scale), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        pts = [QPointF(ox + x * scale, oy + y * scale) for x, y in s.points]
        if len(pts) == 1:
            # 길이 0 선분 + RoundCap = 원
            painter.drawLine(pts[0], pts[0])
            continue
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        painter.drawPath(path)
    painter.restore()


def paint_frame(painter: QPainter, doc: DrawingDocument, frame: int, scale: float, ox: float = 0.0, oy: float = 0.0,
                ghost: tuple[bool, int, int, float] | None = None, current: list[Stroke] | None = None) -> None:
    """한 프레임의 고스트(앞뒤) + 현재 스트로크. current 를 주면 문서 대신 그 리스트(지우개 미리보기)."""
    if ghost is not None and ghost[0]:
        _on, before, after, opacity = ghost
        last = max(0, doc.frame_count - 1)
        for idx, d in ghost_frames(frame, before, after, max(last, frame)):
            strokes = doc.strokes_at(idx)
            if strokes:
                span = before if idx < frame else after
                paint_strokes(painter, strokes, scale, ox, oy, ghost_alpha(d, span, opacity))
    paint_strokes(painter, current if current is not None else doc.strokes_at(frame), scale, ox, oy)
