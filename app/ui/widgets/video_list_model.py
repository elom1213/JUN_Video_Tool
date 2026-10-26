# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-26
"""영상 목록 모델 (PLAN 6.2)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, Signal, QPersistentModelIndex
from PySide6.QtGui import QPixmap

from ...config import constants as C
from ...core import image_sequence
from ...core.models import ItemStatus, MediaInfo, VideoItem
from ...core.utils import format_duration, human_size, normcase_path


def _fps_text(fps: float) -> str:
    if abs(fps - round(fps)) < 1e-3:
        return str(int(round(fps)))
    return f"{fps:.2f}"


def _audio_text(info: MediaInfo) -> str:
    rate = f"{info.sample_rate / 1000:g} kHz" if info.sample_rate else "? kHz"
    ch = {1: "mono", 2: "stereo"}.get(info.channels, f"{info.channels} ch" if info.channels else "? ch")
    return f"{rate} {ch}"


def info_text(info: MediaInfo | None, error: str | None = None) -> str:
    if info is None:
        return error or "Probing…"
    if info.audio_only:
        return (f"Audio {info.codec} · {_audio_text(info)} · "
                f"{format_duration(info.duration)} · {human_size(info.size_bytes)}")
    if info.sequence:
        return (f"Image sequence · {info.frame_count} frames · {info.width}x{info.height} · {_fps_text(info.fps)} fps · "
                f"{format_duration(info.duration)} · {human_size(info.size_bytes)}")
    return (f"{info.width}x{info.height} · {_fps_text(info.fps)} fps · "
            f"{format_duration(info.duration)} · {human_size(info.size_bytes)}")


class VideoListModel(QAbstractListModel):
    ItemRole = Qt.ItemDataRole.UserRole + 1
    InfoTextRole = Qt.ItemDataRole.UserRole + 2
    StatusRole = Qt.ItemDataRole.UserRole + 3
    ProgressRole = Qt.ItemDataRole.UserRole + 4
    MessageRole = Qt.ItemDataRole.UserRole + 5
    EstimateTextRole = Qt.ItemDataRole.UserRole + 6
    EstimateOverTargetRole = Qt.ItemDataRole.UserRole + 7

    rows_added = Signal(list)       # list[int]
    check_changed = Signal()

    def __init__(self, parent=None, *, checkable: bool = True, show_status: bool = True,
                 extensions: frozenset[str] = C.SUPPORTED_EXTENSIONS) -> None:
        super().__init__(parent)
        self._extensions = extensions      # 받는 확장자 (Draw 탭은 영상만)
        # Draw 탭 리스트는 체크박스 · 상태 · 추정 열이 없다 (PLAN_DRAW_TAB 3.4)
        self._checkable = checkable
        self._show_status = show_status
        self._items: list[VideoItem] = []
        self._pixmaps: dict[str, QPixmap] = {}
        self._keys: set[str] = set()
        self._locked = False
        self._target_bytes: int | None = None

    # ------------------------------------------------------------------ Qt 모델 API
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
        if self._checkable and not self._locked:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        it = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return image_sequence.display_name(it.path)
        if role == Qt.ItemDataRole.CheckStateRole:
            if not self._checkable:
                return None
            return Qt.CheckState.Checked if it.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DecorationRole:
            return self._pixmaps.get(normcase_path(it.path))
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [str(it.path), info_text(it.info, it.probe_error)]
            if not self._show_status:
                return "\n".join(lines)
            lines.append(f"Status: {it.status.value}")
            if it.message:
                lines.append(it.message)
            est = self.estimate_text(it)
            if est:
                lines.append(f"Estimated output: {est}")
                if it.est_level == "sampled":
                    lines.append("Estimate from sample encodes. Actual size may differ.")
                elif it.est_level == "heuristic":
                    lines.append("Rough estimate. Actual size may differ.")
            return "\n".join(lines)
        if role == self.ItemRole:
            return it
        if role == self.InfoTextRole:
            return info_text(it.info, it.probe_error)
        if not self._show_status and role in (self.StatusRole, self.ProgressRole, self.EstimateTextRole,
                                              self.EstimateOverTargetRole):
            return None
        if role == self.StatusRole:
            return it.status
        if role == self.ProgressRole:
            return it.progress
        if role == self.MessageRole:
            return it.message
        if role == self.EstimateTextRole:
            return self.estimate_text(it)
        if role == self.EstimateOverTargetRole:
            return (self._target_bytes is not None and it.est_size is not None
                    and it.est_size > self._target_bytes and it.status not in (ItemStatus.DONE,))
        return None

    def setData(self, index: QModelIndex | QPersistentModelIndex, value: Any,  # noqa: N802
                role: int = Qt.ItemDataRole.EditRole) -> bool:
        if (not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or self._locked
                or not self._checkable):
            return False
        it = self._items[index.row()]
        new = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value, True)
        if it.checked == new:
            return True
        it.checked = new
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.check_changed.emit()
        return True

    # ------------------------------------------------------------------ 표시 보조
    @staticmethod
    def estimate_text(it: VideoItem) -> str:
        if it.status == ItemStatus.DONE:
            return ""
        if it.est_level == "pending":
            return "…"
        if it.est_level == "failed":
            return "?"
        if it.est_size is None:
            return ""
        size = human_size(it.est_size)
        if it.est_level == "heuristic":
            return f"~{size}"
        if it.est_level == "sampled":
            return f"≈{size}"
        return size

    def set_target_bytes(self, target: int | None) -> None:
        self._target_bytes = target
        self._emit_all()

    # ------------------------------------------------------------------ 편집
    def add_paths(self, paths: Iterable[Path]) -> tuple[int, int]:
        added_rows: list[int] = []
        new_items: list[VideoItem] = []
        paths = [Path(p) for p in paths]
        supported = [p for p in paths if p.suffix.lower() in self._extensions]
        skipped = len(paths) - len(supported)
        # 같은 시퀀스의 프레임들(img.001 ~ img.120)은 첫 프레임 한 항목으로 모은다 (모인 프레임은 건너뜀으로 세지 않는다)
        for p in image_sequence.collapse(supported):
            if not p.is_file():
                skipped += 1
                continue
            key = normcase_path(p)
            if key in self._keys:
                skipped += 1
                continue
            self._keys.add(key)
            new_items.append(VideoItem(path=p))
        if new_items:
            first = len(self._items)
            self.beginInsertRows(QModelIndex(), first, first + len(new_items) - 1)
            self._items.extend(new_items)
            self.endInsertRows()
            added_rows = list(range(first, first + len(new_items)))
            self.rows_added.emit(added_rows)
            self.check_changed.emit()
        return len(added_rows), skipped

    def remove_rows(self, rows: list[int]) -> None:
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self._items):
                self.beginRemoveRows(QModelIndex(), row, row)
                it = self._items.pop(row)
                key = normcase_path(it.path)
                self._keys.discard(key)
                self._pixmaps.pop(key, None)
                self.endRemoveRows()
        self.check_changed.emit()

    def clear(self) -> None:
        self.beginResetModel()
        self._items.clear()
        self._keys.clear()
        self._pixmaps.clear()
        self.endResetModel()
        self.check_changed.emit()

    def set_all_checked(self, checked: bool) -> None:
        if self._locked:
            return
        for it in self._items:
            it.checked = checked
        self._emit_all([Qt.ItemDataRole.CheckStateRole])
        self.check_changed.emit()

    def invert_checked(self) -> None:
        if self._locked:
            return
        for it in self._items:
            it.checked = not it.checked
        self._emit_all([Qt.ItemDataRole.CheckStateRole])
        self.check_changed.emit()

    def checked_rows(self) -> list[int]:
        if not self._checkable:
            return []
        return [i for i, it in enumerate(self._items) if it.checked]

    def item(self, row: int) -> VideoItem:
        return self._items[row]

    def items(self) -> list[VideoItem]:
        return list(self._items)

    def row_of(self, path: Path) -> int:
        key = normcase_path(path)
        for i, it in enumerate(self._items):
            if normcase_path(it.path) == key:
                return i
        return -1

    def update_item(self, row: int, **fields: Any) -> None:
        if not (0 <= row < len(self._items)):
            return
        it = self._items[row]
        for k, v in fields.items():
            setattr(it, k, v)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx)

    def set_info(self, row: int, info: MediaInfo | None, error: str | None = None) -> None:
        self.update_item(row, info=info, probe_error=error)

    def set_thumbnail(self, row: int, pixmap: QPixmap) -> None:
        if not (0 <= row < len(self._items)):
            return
        self._pixmaps[normcase_path(self._items[row].path)] = pixmap
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])

    def set_estimate(self, row: int, est_key: str, size: int | None, level: str) -> None:
        """모델의 est_key 와 일치할 때만 반영 (늦게 온 결과 무시)."""
        if not (0 <= row < len(self._items)):
            return
        it = self._items[row]
        if est_key and it.est_key and est_key != it.est_key:
            return
        it.est_size = size
        it.est_level = level
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [self.EstimateTextRole])

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self._emit_all()

    def is_locked(self) -> bool:
        return self._locked

    def _emit_all(self, roles: list[int] | None = None) -> None:
        if not self._items:
            return
        top, bottom = self.index(0), self.index(len(self._items) - 1)
        if roles:
            self.dataChanged.emit(top, bottom, roles)
        else:
            self.dataChanged.emit(top, bottom)
