# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""리스트 / 썸네일 두 모드를 그리는 델리게이트 (PLAN 6.3)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QModelIndex, QRect, QRectF, QSize, Qt, QAbstractItemModel
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from ...config import constants as C
from ...core.models import ItemStatus
from .video_list_model import VideoListModel

_CHECK = 16
_PAD = 6


class VideoItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mode = "list"

    def set_mode(self, mode: str) -> None:
        self._mode = "thumbs" if mode == "thumbs" else "list"

    def mode(self) -> str:
        return self._mode

    # ------------------------------------------------------------------ 크기
    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        if self._mode == "thumbs":
            return QSize(C.THUMB_CELL_W, C.THUMB_CELL_H)
        fm = QFontMetrics(option.font)
        return QSize(0, max(C.LIST_ROW_H, fm.height() + 10))

    # ------------------------------------------------------------------ 그리기
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.fillRect(rect, QColor(C.Colors.SELECTION))
        elif hovered:
            painter.fillRect(rect, QColor(C.Colors.PANEL))

        if self._mode == "thumbs":
            self._paint_thumb(painter, option, index)
        else:
            self._paint_list(painter, option, index)
        painter.restore()

    def _draw_check(self, painter: QPainter, option: QStyleOptionViewItem, rect: QRect, checked: bool,
                    enabled: bool) -> None:
        """qss 의 QCheckBox 표시자와 같은 모양(주황 채움 + 흰 체크)을 직접 그린다."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if checked:
            fill = QColor(C.Colors.ACCENT if enabled else "#6d4a3d")
            painter.setPen(QPen(fill, 1))
            painter.setBrush(fill)
        else:
            painter.setPen(QPen(QColor("#6a6a6a" if enabled else C.Colors.BORDER), 1))
            painter.setBrush(QColor("#262626" if enabled else "#333333"))
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
        if checked:
            pen = QPen(QColor("#ffffff"), 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            w, h = rect.width(), rect.height()
            path = QPainterPath()
            path.moveTo(rect.x() + w * 0.22, rect.y() + h * 0.53)
            path.lineTo(rect.x() + w * 0.42, rect.y() + h * 0.72)
            path.lineTo(rect.x() + w * 0.78, rect.y() + h * 0.32)
            painter.drawPath(path)
        painter.restore()

    def _status_color(self, status: ItemStatus) -> QColor:
        if status == ItemStatus.DONE:
            return QColor(C.Colors.OK)
        if status in (ItemStatus.FAILED,):
            return QColor(C.Colors.FAIL)
        if status in (ItemStatus.CANCELED, ItemStatus.SKIPPED):
            return QColor(C.Colors.WARN)
        return QColor(C.Colors.TEXT_DIM)

    def _paint_progress(self, painter: QPainter, rect: QRect, pct: int) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C.Colors.TRACK))
        painter.drawRoundedRect(rect, 2, 2)
        w = int(rect.width() * max(0, min(100, pct)) / 100)
        if w > 0:
            painter.setBrush(QColor(C.Colors.ACCENT))
            painter.drawRoundedRect(QRect(rect.x(), rect.y(), w, rect.height()), 2, 2)

    def _paint_list(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        r = option.rect
        fm = QFontMetrics(option.font)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        status: ItemStatus = index.data(VideoListModel.StatusRole)
        progress: int = index.data(VideoListModel.ProgressRole) or 0
        message: str = index.data(VideoListModel.MessageRole) or ""
        est_text: str = index.data(VideoListModel.EstimateTextRole) or ""
        over_target: bool = bool(index.data(VideoListModel.EstimateOverTargetRole))

        x = r.x() + _PAD
        cy = r.center().y()
        check_rect = QRect(x, cy - _CHECK // 2, _CHECK, _CHECK)
        self._draw_check(painter, option, check_rect, checked, enabled)
        x += _CHECK + _PAD * 2

        status_w = 140
        est_w = 90
        right = r.right() - _PAD
        status_rect = QRect(right - status_w, r.y(), status_w, r.height())
        est_rect = QRect(status_rect.x() - _PAD - est_w, r.y(), est_w, r.height())
        avail = est_rect.x() - _PAD - x
        name_w = int(avail * 0.40)
        name_rect = QRect(x, r.y(), name_w, r.height())
        info_rect = QRect(x + name_w + _PAD, r.y(), max(0, avail - name_w - _PAD), r.height())

        painter.setPen(QColor(C.Colors.TEXT))
        name = fm.elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideMiddle, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)

        painter.setPen(QColor(C.Colors.TEXT_DIM))
        info = fm.elidedText(index.data(VideoListModel.InfoTextRole) or "", Qt.TextElideMode.ElideRight, info_rect.width())
        painter.drawText(info_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, info)

        if est_text:
            painter.setPen(QColor(C.Colors.WARN if over_target else C.Colors.TEXT_DIM))
            painter.drawText(est_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, est_text)

        if status == ItemStatus.RUNNING:
            bar = QRect(status_rect.x(), cy - 4, status_w - 44, 8)
            self._paint_progress(painter, bar, progress)
            painter.setPen(QColor(C.Colors.TEXT))
            painter.drawText(QRect(bar.right() + 4, r.y(), 40, r.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{progress} %")
        else:
            text = status.value if status else ""
            if status == ItemStatus.DONE and message:
                text = f"Done · {message}"
            elif status in (ItemStatus.FAILED, ItemStatus.SKIPPED) and message:
                text = f"{status.value}"
            elif status == ItemStatus.IDLE:
                text = ""
            painter.setPen(self._status_color(status))
            painter.drawText(status_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             fm.elidedText(text, Qt.TextElideMode.ElideRight, status_w))

    def _paint_thumb(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        r = option.rect
        fm = QFontMetrics(option.font)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        status: ItemStatus = index.data(VideoListModel.StatusRole)
        progress: int = index.data(VideoListModel.ProgressRole) or 0
        est_text: str = index.data(VideoListModel.EstimateTextRole) or ""
        over_target: bool = bool(index.data(VideoListModel.EstimateOverTargetRole))
        pix = index.data(Qt.ItemDataRole.DecorationRole)

        img_rect = QRect(r.x() + (r.width() - C.THUMB_IMG_W) // 2, r.y() + _PAD, C.THUMB_IMG_W, C.THUMB_IMG_H)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#1e1e1e"))
        painter.drawRoundedRect(img_rect, 3, 3)
        if isinstance(pix, QPixmap) and not pix.isNull():
            scaled = pix.scaled(img_rect.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            dx = img_rect.x() + (img_rect.width() - scaled.width()) // 2
            dy = img_rect.y() + (img_rect.height() - scaled.height()) // 2
            painter.drawPixmap(dx, dy, scaled)
        else:
            painter.setPen(QColor(C.Colors.TEXT_DIM))
            painter.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "…")

        # 체크박스 (좌상단)
        check_rect = QRect(img_rect.x() + 4, img_rect.y() + 4, _CHECK, _CHECK)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 140))
        painter.drawRoundedRect(check_rect.adjusted(-2, -2, 2, 2), 3, 3)
        self._draw_check(painter, option, check_rect, checked, enabled)

        # 상태 점 (우상단)
        if status in (ItemStatus.DONE, ItemStatus.FAILED, ItemStatus.CANCELED, ItemStatus.SKIPPED):
            painter.setBrush(self._status_color(status))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(img_rect.right() - 12, img_rect.y() + 4, 8, 8)

        y = img_rect.bottom() + 3
        if status == ItemStatus.RUNNING:
            self._paint_progress(painter, QRect(img_rect.x(), y, img_rect.width(), 3), progress)
        y += 5

        painter.setPen(QColor(C.Colors.TEXT))
        name_rect = QRect(r.x() + _PAD, y, r.width() - _PAD * 2, fm.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(index.data(Qt.ItemDataRole.DisplayRole) or "", Qt.TextElideMode.ElideMiddle, name_rect.width()))
        y += fm.height()
        small_rect = QRect(r.x() + _PAD, y, r.width() - _PAD * 2, fm.height())
        info = index.data(VideoListModel.InfoTextRole) or ""
        if status == ItemStatus.DONE:
            info = f"Done · {index.data(VideoListModel.MessageRole) or ''}"
            painter.setPen(QColor(C.Colors.OK))
        elif status == ItemStatus.FAILED:
            info = "Failed"
            painter.setPen(QColor(C.Colors.FAIL))
        elif est_text:
            info = f"{est_text}"
            painter.setPen(QColor(C.Colors.WARN if over_target else C.Colors.TEXT_DIM))
        else:
            painter.setPen(QColor(C.Colors.TEXT_DIM))
        painter.drawText(small_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                         fm.elidedText(info, Qt.TextElideMode.ElideRight, small_rect.width()))

    # ------------------------------------------------------------------ 체크박스 히트테스트
    def _check_rect(self, option: QStyleOptionViewItem) -> QRect:
        r = option.rect
        if self._mode == "thumbs":
            img_x = r.x() + (r.width() - C.THUMB_IMG_W) // 2
            return QRect(img_x + 4, r.y() + _PAD + 4, _CHECK, _CHECK).adjusted(-4, -4, 4, 4)
        cy = r.center().y()
        return QRect(r.x() + _PAD, cy - _CHECK // 2, _CHECK, _CHECK).adjusted(-4, -4, 4, 4)

    def editorEvent(self, event: QEvent, model: QAbstractItemModel, option: QStyleOptionViewItem,  # noqa: N802
                    index: QModelIndex) -> bool:
        if not (index.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            pos = event.position().toPoint()  # type: ignore[attr-defined]
            if self._check_rect(option).contains(pos):
                cur = index.data(Qt.ItemDataRole.CheckStateRole)
                new = Qt.CheckState.Unchecked if cur == Qt.CheckState.Checked else Qt.CheckState.Checked
                return model.setData(index, new, Qt.ItemDataRole.CheckStateRole)
            return False
        if event.type() == QEvent.Type.MouseButtonPress and self._check_rect(option).contains(
                event.position().toPoint()):  # type: ignore[attr-defined]
            return True  # 선택 변경 억제
        if event.type() == QEvent.Type.MouseButtonDblClick:
            return False
        return False

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: QModelIndex):  # noqa: N802
        return None
