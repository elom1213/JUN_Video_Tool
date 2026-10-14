# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""듀얼 핸들 정수 범위 슬라이더 (PLAN 6.6)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QSize
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QWheelEvent
from PySide6.QtWidgets import QWidget

from ...config import constants as C

_HANDLE_D = 14
_TRACK_H = 4


class RangeSlider(QWidget):
    valuesChanged = Signal(int, int)   # noqa: N815
    sliderReleased = Signal()          # noqa: N815

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._min = 0
        self._max = 100
        self._low = 0
        self._high = 100
        self._active: str | None = None   # "low" | "high"
        self._pressed = False
        self.setFixedHeight(24)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ API
    def setRange(self, lo: int, hi: int) -> None:  # noqa: N802
        self._min = int(lo)
        self._max = max(int(lo), int(hi))
        self._low = max(self._min, min(self._low, self._max))
        self._high = max(self._low, min(self._high, self._max))
        self.update()

    def setValues(self, low: int, high: int, emit: bool = False) -> None:  # noqa: N802
        low = max(self._min, min(int(low), self._max))
        high = max(self._min, min(int(high), self._max))
        if low > high:
            low, high = high, low
        changed = (low, high) != (self._low, self._high)
        self._low, self._high = low, high
        self.update()
        if changed and emit:
            self.valuesChanged.emit(self._low, self._high)

    def values(self) -> tuple[int, int]:
        return self._low, self._high

    def minimum(self) -> int:
        return self._min

    def maximum(self) -> int:
        return self._max

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 24)

    # ------------------------------------------------------------------ 좌표 변환
    def _track_rect(self) -> QRectF:
        m = _HANDLE_D / 2 + 1
        return QRectF(m, self.height() / 2 - _TRACK_H / 2, self.width() - 2 * m, _TRACK_H)

    def _val_to_x(self, v: int) -> float:
        tr = self._track_rect()
        span = max(1, self._max - self._min)
        return tr.left() + (v - self._min) / span * tr.width()

    def _x_to_val(self, x: float) -> int:
        tr = self._track_rect()
        if tr.width() <= 0:
            return self._min
        t = (x - tr.left()) / tr.width()
        t = max(0.0, min(1.0, t))
        return int(round(self._min + t * (self._max - self._min)))

    # ------------------------------------------------------------------ 그리기
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tr = self._track_rect()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.Colors.TRACK))
        p.drawRoundedRect(tr, 2, 2)
        x1, x2 = self._val_to_x(self._low), self._val_to_x(self._high)
        p.setBrush(QColor(C.Colors.ACCENT))
        p.drawRoundedRect(QRectF(x1, tr.top(), max(0.0, x2 - x1), tr.height()), 2, 2)
        cy = self.height() / 2
        for name, x in (("low", x1), ("high", x2)):
            active = self._active == name and self.hasFocus()
            p.setBrush(QColor(C.Colors.TEXT if active else "#d0d0d0"))
            p.setPen(QColor(C.Colors.ACCENT) if active else QColor(C.Colors.BORDER))
            p.drawEllipse(QPointF(x, cy), _HANDLE_D / 2, _HANDLE_D / 2)
        if not self.isEnabled():
            p.fillRect(self.rect(), QColor(0, 0, 0, 110))

    # ------------------------------------------------------------------ 마우스
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        d_low = abs(x - self._val_to_x(self._low))
        d_high = abs(x - self._val_to_x(self._high))
        if d_low == d_high:
            self._active = "low" if x < self._val_to_x(self._low) else "high"
        else:
            self._active = "low" if d_low < d_high else "high"
        self._pressed = True
        self.setFocus()
        self._move_active(self._x_to_val(x))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pressed and self._active:
            self._move_active(self._x_to_val(event.position().x()))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pressed:
            self._pressed = False
            self.sliderReleased.emit()

    def _move_active(self, v: int) -> None:
        low, high = self._low, self._high
        if self._active == "low":
            low = min(v, high)
        else:
            high = max(v, low)
        self.setValues(low, high, emit=True)

    # ------------------------------------------------------------------ 키보드 · 휠
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if self._active is None:
            self._active = "low"
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        cur = self._low if self._active == "low" else self._high
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._move_active(cur - step)
        elif key == Qt.Key.Key_Right:
            self._move_active(cur + step)
        elif key == Qt.Key.Key_Home:
            self._move_active(self._min)
        elif key == Qt.Key.Key_End:
            self._move_active(self._max)
        elif key == Qt.Key.Key_Tab:
            self._active = "high" if self._active == "low" else "low"
            self.update()
        else:
            return super().keyPressEvent(event)
        self.sliderReleased.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._active is None:
            self._active = "high"
        delta = 1 if event.angleDelta().y() > 0 else -1
        cur = self._low if self._active == "low" else self._high
        self._move_active(cur + delta)
        self.sliderReleased.emit()
        event.accept()
