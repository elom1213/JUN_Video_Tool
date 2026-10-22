# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-22
"""영상 프레임 + 그림 캔버스 (PLAN_DRAW_TAB 5.2, 13.2, 13.3, 16장).

마우스: 좌드래그 = 현재 툴(draw: 스트로크 / erase: 지우기), 가운데 드래그 = 스크럽, 우버튼 = 없음.
스트로크 좌표 · 두께는 소스 픽셀 단위로 문서에 들어가고, 화면 변환은 video_rect 하나로 한다.
보기 반전(set_flip)은 영상과 저장된 스트로크를 같은 거울 변환으로 그리고, 마우스 → 소스 변환에서 축을 되돌린다.
문서 · 저장 파일 · 내보내기는 반전과 무관하게 원본 픽셀 그대로다.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen, QTransform
from PySide6.QtWidgets import QSizePolicy, QWidget

from ....config import constants as C
from ....core.drawing import DrawingDocument, Stroke, erase_strokes
from .geometry import fit_rect, flip_label, scrub_delta, to_screen, to_video
from .stroke_painter import paint_frame


class VideoCanvas(QWidget):
    stroke_finished = Signal(object)        # Stroke (소스 픽셀 좌표)
    erase_finished = Signal(object)         # list[Stroke] — 지우개 적용 뒤 그 프레임 전체
    scrub_started = Signal()
    scrub_delta = Signal(int)               # 누적 프레임 오프셋 (시작 프레임 기준)
    scrub_finished = Signal()
    draw_pressed_while_playing = Signal()   # 컨트롤러가 pause() 한다

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("VideoCanvas")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._image: QImage | None = None
        self._image_frame = -1
        self._frame = 0
        self._loading = False
        self._src_w = 0
        self._src_h = 0
        self._doc: DrawingDocument | None = None
        self._ghost = (True, C.GHOST_BEFORE_DEFAULT, C.GHOST_AFTER_DEFAULT, C.GHOST_OPACITY_DEFAULT)
        self._tool = "draw"
        self._color = C.DRAW_COLOR_DEFAULT
        self._width = C.DRAW_WIDTH_DEFAULT
        self._eraser = C.DRAW_ERASER_DEFAULT
        self._scrub_px = C.DRAW_SCRUB_PX_PER_FRAME
        self._playing = False
        self._message = ""
        self._flip_h = False
        self._flip_v = False
        # 입력 상태
        self._live_points: list[QPointF] = []
        self._erase_preview: list[Stroke] | None = None
        self._erase_last: tuple[float, float] | None = None
        self._erase_changed = False
        self._scrubbing = False
        self._scrub_x0 = 0.0
        self._scrub_last = 0
        self._mouse: QPointF | None = None

    # ================================================================== 설정 API
    def set_frame(self, index: int, image: QImage | None) -> None:
        """image None = 로딩 중 (이전 그림 유지 + 희미하게)."""
        if index != self._frame:
            # 프레임이 바뀌면 그리던 선 · 지우개는 버린다 (스크럽은 프레임을 바꾸는 입력이므로 유지)
            self._live_points = []
            self._erase_preview = None
            self._erase_last = None
        self._frame = index
        if image is not None:
            self._image = image
            self._image_frame = index
            self._loading = False
        else:
            self._loading = self._image is None or self._image_frame != index
        self.update()

    def set_loading(self, loading: bool) -> None:
        self._loading = loading and self._image_frame != self._frame
        self.update()

    def clear(self, message: str = "") -> None:
        self._cancel_input()
        self._image = None
        self._image_frame = -1
        self._loading = False
        self._src_w = self._src_h = 0
        self._message = message
        self.update()

    def set_message(self, message: str) -> None:
        self._message = message
        self.update()

    def set_source_size(self, w: int, h: int) -> None:
        self._src_w, self._src_h = int(w), int(h)
        self._message = ""
        self.update()

    def set_document(self, doc: DrawingDocument | None) -> None:
        self._cancel_input()
        self._doc = doc
        self.update()

    def set_ghost(self, enabled: bool, before: int, after: int, opacity: float) -> None:
        self._ghost = (bool(enabled), int(before), int(after), float(opacity))
        self.update()

    def set_tool(self, tool: str) -> None:
        self._cancel_input()
        self._tool = "erase" if tool == "erase" else "draw"
        self._update_cursor()
        self.update()

    def set_brush(self, color: str, width: float) -> None:
        self._color, self._width = color, float(width)
        self.update()

    def set_eraser_size(self, size: float) -> None:
        self._eraser = float(size)
        self.update()

    def set_scrub_sensitivity(self, px_per_frame: int) -> None:
        self._scrub_px = max(1, int(px_per_frame))

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)

    def set_flip(self, flip_h: bool, flip_v: bool) -> None:
        """보기 반전 (좌우 · 상하). 그리던 입력은 버린다 — 축이 바뀌면 점들이 엉뚱한 자리로 간다."""
        flip_h, flip_v = bool(flip_h), bool(flip_v)
        if (flip_h, flip_v) == (self._flip_h, self._flip_v):
            return
        self._cancel_input()
        self._flip_h, self._flip_v = flip_h, flip_v
        self.update()

    def flip(self) -> tuple[bool, bool]:
        return self._flip_h, self._flip_v

    def video_rect(self) -> QRectF:
        return QRectF(*self._rect())

    def is_busy(self) -> bool:
        """그리기 · 지우기 · 스크럽 중."""
        return bool(self._live_points) or self._erase_preview is not None or self._scrubbing

    # ================================================================== 좌표
    def _rect(self) -> tuple[float, float, float, float]:
        return fit_rect(self.width(), self.height(), self._src_w, self._src_h)

    def _scale(self) -> float:
        r = self._rect()
        return r[3] / self._src_h if self._src_h else 1.0

    def _to_video(self, p: QPointF) -> tuple[float, float]:
        return to_video(p.x(), p.y(), self._rect(), self._src_w, self._src_h, self._flip_h, self._flip_v)

    def _flip_transform(self, vr: QRectF) -> QTransform:
        """영상 사각형을 제자리에서 거울상으로 뒤집는 변환 (반전이 없으면 항등)."""
        t = QTransform()
        if self._flip_h or self._flip_v:
            t.translate(vr.x() * 2 + vr.width() if self._flip_h else 0.0,
                        vr.y() * 2 + vr.height() if self._flip_v else 0.0)
            t.scale(-1.0 if self._flip_h else 1.0, -1.0 if self._flip_v else 1.0)
        return t

    def _has_input(self) -> bool:
        return self._src_w > 0 and self._src_h > 0 and self._image is not None and self._doc is not None

    # ================================================================== 페인트
    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.fillRect(self.rect(), QColor(C.Colors.CANVAS_BG))
        if self._src_w <= 0 or self._src_h <= 0:
            if self._message:
                p.setPen(QColor(C.Colors.TEXT_DIM))
                p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            p.end()
            return
        x, y, w, h = self._rect()
        vr = QRectF(x, y, w, h)
        # 영상과 저장된 스트로크는 같은 거울 변환 아래 그린다 (보기 반전). 그 뒤는 화면 좌표 그대로
        p.save()
        p.setTransform(self._flip_transform(vr))
        if self._image is not None:
            if self._loading:
                p.setOpacity(0.45)
            p.drawImage(vr, self._image)
            p.setOpacity(1.0)
        else:
            p.fillRect(vr, QColor("#000000"))

        scale = self._scale()
        if self._doc is not None:
            p.save()
            p.setClipRect(vr)
            paint_frame(p, self._doc, self._frame, scale, x, y, ghost=self._ghost, current=self._erase_preview)
            p.restore()
        p.restore()

        # 진행 중 스트로크 (화면 좌표 그대로)
        if self._live_points:
            pen = QPen(QColor(self._color), max(0.5, self._width * scale), Qt.PenStyle.SolidLine,
                       Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            if len(self._live_points) == 1:
                p.drawLine(self._live_points[0], self._live_points[0])
            else:
                path = QPainterPath(self._live_points[0])
                for pt in self._live_points[1:]:
                    path.lineTo(pt)
                p.drawPath(path)

        # 툴 크기 원 (브러시 두께 / 지우개 지름). 영상 위에서는 시스템 커서 대신 이 원이 커서다
        if self._show_tool_outline(vr):
            self._paint_tool_outline(p, scale)

        if self._loading:
            p.setPen(QColor(C.Colors.TEXT_DIM))
            p.drawText(self.rect().adjusted(0, 0, -10, -8), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                       "Loading…")
        badge = flip_label(self._flip_h, self._flip_v)
        if badge:
            # 거울상으로 보고 있다는 표시 (저장 · 내보내기는 원본 방향이다)
            p.setPen(QColor(C.Colors.TEXT_DIM))
            p.drawText(self.rect().adjusted(0, 6, -10, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                       badge)
        p.end()

    # ================================================================== 마우스
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not self._has_input() or self.is_busy():
            return
        pos = event.position()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._scrubbing = True
            self._scrub_x0 = pos.x()
            self._scrub_last = 0
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            self.scrub_started.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._playing:
            self.draw_pressed_while_playing.emit()
        if self._tool == "erase":
            assert self._doc is not None
            self._erase_preview = [s.copy() for s in self._doc.strokes_at(self._frame)]
            self._erase_changed = False
            self._erase_last = self._to_video(pos)
            self._erase_at([self._erase_last])
        else:
            self._live_points = [pos]
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = event.position()
        self._mouse = pos
        if self._scrubbing:
            d = scrub_delta(pos.x(), self._scrub_x0, self._scrub_px)
            if d != self._scrub_last:
                self._scrub_last = d
                self.scrub_delta.emit(d)
            return
        if self._live_points:
            last = self._live_points[-1]
            if math.hypot(pos.x() - last.x(), pos.y() - last.y()) >= C.DRAW_MIN_POINT_DIST_PX:
                self._live_points.append(pos)
                self.update()
            return
        if self._erase_preview is not None:
            cur = self._to_video(pos)
            seg = [self._erase_last, cur] if self._erase_last is not None else [cur]
            self._erase_last = cur
            self._erase_at(seg)
        self._update_cursor()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton and self._scrubbing:
            self._scrubbing = False
            self._update_cursor()
            self.scrub_finished.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._live_points:
            pts = [self._to_video(p) for p in self._live_points]
            self._live_points = []
            self.stroke_finished.emit(Stroke(self._color, self._width, pts))
            self.update()
        elif self._erase_preview is not None:
            result, changed = self._erase_preview, self._erase_changed
            self._erase_preview = None
            self._erase_last = None
            if changed:
                self.erase_finished.emit(result)
            self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._mouse = None
        self.update()

    def tool_outline_radius(self) -> float:
        """현재 툴 크기 원의 화면 반지름 (px). 브러시 = 두께/2, 지우개 = 지름/2 (소스 px × 화면 배율)."""
        size = self._eraser if self._tool == "erase" else self._width
        return size / 2.0 * self._scale()

    def _show_tool_outline(self, vr: QRectF) -> bool:
        return (self._mouse is not None and not self._scrubbing and self._has_input()
                and vr.contains(self._mouse))

    def _paint_tool_outline(self, p: QPainter, scale: float) -> None:
        assert self._mouse is not None
        r = max(1.5, self.tool_outline_radius())
        p.save()
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 어두운 테두리 + 밝은 선 두 겹이라 어떤 배경에서도 보인다
        p.setPen(QPen(QColor(0, 0, 0, 170), 3))
        p.drawEllipse(self._mouse, r, r)
        light = QColor("#ffffff") if self._tool == "erase" else QColor(self._color).lighter(115)
        p.setPen(QPen(light, 1))
        p.drawEllipse(self._mouse, r, r)
        # 중심점 (작은 브러시에서도 위치가 보이게)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawEllipse(self._mouse, 2.0, 2.0)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(self._mouse, 1.0, 1.0)
        p.restore()

    def enterEvent(self, _event) -> None:  # noqa: N802
        # 마우스를 올리면 키(←/→/Space)가 캔버스로 가게 한다 (5.2)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._update_cursor()

    # ================================================================== 내부
    def _erase_at(self, path: list[tuple[float, float]]) -> None:
        if self._erase_preview is None:
            return
        out, changed = erase_strokes(self._erase_preview, path, self._eraser / 2.0)
        if changed:
            self._erase_preview = out
            self._erase_changed = True
        self.update()

    def _cancel_input(self) -> None:
        self._live_points = []
        self._erase_preview = None
        self._erase_last = None
        if self._scrubbing:
            self._scrubbing = False
            self._update_cursor()

    def _update_cursor(self) -> None:
        if self._scrubbing:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif self._show_tool_outline(self.video_rect()):
            # 영상 위: 툴 크기 원이 커서를 대신한다
            self.setCursor(Qt.CursorShape.BlankCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def screen_point(self, vx: float, vy: float) -> QPointF:
        """테스트 · 디버그용: 소스 좌표 → 화면 좌표."""
        sx, sy = to_screen(vx, vy, self._rect(), self._src_w, self._src_h, self._flip_h, self._flip_v)
        return QPointF(sx, sy)
