# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""영상 목록 뷰 (PLAN 6.4): 드래그&드롭, 보기 모드 전환, 컨텍스트 메뉴."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, QPoint
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeyEvent, QAction
from PySide6.QtWidgets import QAbstractItemView, QListView, QMenu

from ...config import constants as C
from .video_item_delegate import VideoItemDelegate


class VideoListView(QListView):
    files_dropped = Signal(list)              # list[Path]
    open_folder_requested = Signal(int)       # row
    remove_requested = Signal(list)           # rows
    reset_range_requested = Signal(list)      # rows

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._delegate = VideoItemDelegate(self)
        self.setItemDelegate(self._delegate)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.set_view_mode("list")

    # ------------------------------------------------------------------ 모드
    def set_view_mode(self, mode: str) -> None:
        self._delegate.set_mode(mode)
        if mode == "thumbs":
            self.setViewMode(QListView.ViewMode.IconMode)
            self.setResizeMode(QListView.ResizeMode.Adjust)
            self.setMovement(QListView.Movement.Static)
            self.setWrapping(True)
            self.setGridSize(QSize(C.THUMB_CELL_W + 6, C.THUMB_CELL_H + 6))
            self.setSpacing(6)
            self.setUniformItemSizes(True)
            self.setFlow(QListView.Flow.LeftToRight)
        else:
            self.setViewMode(QListView.ViewMode.ListMode)
            self.setResizeMode(QListView.ResizeMode.Adjust)
            self.setMovement(QListView.Movement.Static)
            self.setWrapping(False)
            self.setGridSize(QSize())
            self.setSpacing(0)
            self.setUniformItemSizes(True)
            self.setFlow(QListView.Flow.TopToBottom)
        self.doItemsLayout()
        self.viewport().update()

    def view_mode(self) -> str:
        return self._delegate.mode()

    # ------------------------------------------------------------------ 드래그&드롭
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if not event.mimeData().hasUrls():
            return super().dropEvent(event)
        paths: list[Path] = []
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            p = Path(url.toLocalFile())
            if p.is_dir():
                paths.extend(sorted(c for c in p.iterdir() if c.is_file()))
            else:
                paths.append(p)
        event.acceptProposedAction()
        if paths:
            self.files_dropped.emit(paths)

    # ------------------------------------------------------------------ 키 · 메뉴
    def selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.selectionModel().selectedIndexes()})

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Delete:
            rows = self.selected_rows()
            if rows:
                self.remove_requested.emit(rows)
            return
        super().keyPressEvent(event)

    def _context_menu(self, pos: QPoint) -> None:
        idx = self.indexAt(pos)
        rows = self.selected_rows()
        if idx.isValid() and idx.row() not in rows:
            rows = [idx.row()]
        menu = QMenu(self)
        act_open = QAction("Open Containing Folder", menu)
        act_open.setEnabled(idx.isValid())
        act_open.triggered.connect(lambda: self.open_folder_requested.emit(idx.row()))
        act_remove = QAction("Remove Selected", menu)
        act_remove.setEnabled(bool(rows))
        act_remove.triggered.connect(lambda: self.remove_requested.emit(rows))
        act_reset = QAction("Reset Frame Range", menu)
        act_reset.setEnabled(bool(rows))
        act_reset.triggered.connect(lambda: self.reset_range_requested.emit(rows))
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(act_reset)
        menu.addAction(act_remove)
        menu.exec(self.viewport().mapToGlobal(pos))
