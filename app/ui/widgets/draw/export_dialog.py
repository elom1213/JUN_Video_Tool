# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""그림 입힌 영상 내보내기 다이얼로그 (PLAN_DRAW_TAB 13.4).

포맷별 옵션 패널은 Convert 탭과 같은 클래스를 쓰되, 설정은 `export/<format_id>/options_json` 에 따로 둔다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ....config import constants as C
from ....config.settings import AppSettings
from ....core import ffmpeg_locator
from ....core.converters import registry
from ....core.converters.base import BaseConverter
from ....core.drawing import DrawingDocument
from ....core.models import ConvertOptions, VideoItem
from ....core.utils import human_size, make_output_path, normcase_path
from .. import gif_options_panel, mp4_options_panel  # noqa: F401  (팩토리 등록)
from ..options_panel_base import BaseOptionsPanel, OptionsPanelFactory
from .export_worker import ExportWorker

_PREFIX = "export/"


class ExportDialog(QDialog):
    exported = Signal(object, int, float)     # path, size, elapsed
    log = Signal(str)

    def __init__(self, settings: AppSettings, item: VideoItem, doc: DrawingDocument,
                 ghost: tuple[bool, int, int, float], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Export with Drawing — {item.path.name}")
        self.setMinimumWidth(480)
        self.resize(520, 640)
        self.settings = settings
        self.item = item
        self.doc = doc
        self.ghost = ghost
        self.worker: ExportWorker | None = None
        self._panel: BaseOptionsPanel | None = None
        self._converter: BaseConverter = registry.all()[0]
        self._out_edited = False

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        for conv in registry.all():
            self.format_combo.addItem(conv.display_name, conv.format_id)
        row.addWidget(self.format_combo, 1)
        lay.addLayout(row)

        body = QWidget()
        self._slot = QVBoxLayout(body)
        self._slot.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        self.ghost_check = QCheckBox("Include ghosting (uses the current Ghosting settings)")
        self.ghost_check.setChecked(bool(settings.get("export/include_ghost", False, bool)))
        lay.addWidget(self.ghost_check)

        orow = QHBoxLayout()
        orow.addWidget(QLabel("Output:"))
        self.out_edit = QLineEdit()
        self.out_edit.textEdited.connect(lambda _t: setattr(self, "_out_edited", True))
        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.clicked.connect(self._browse)
        orow.addWidget(self.out_edit, 1)
        orow.addWidget(self.browse_btn)
        lay.addLayout(orow)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        lay.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setObjectName("HintLabel")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

        brow = QHBoxLayout()
        brow.addStretch(1)
        self.export_btn = QPushButton("Export")
        self.export_btn.setObjectName("ConvertButton")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.close_btn = QPushButton("Close")
        for b in (self.export_btn, self.cancel_btn, self.close_btn):
            brow.addWidget(b)
        lay.addLayout(brow)

        self.export_btn.clicked.connect(self._export)
        self.cancel_btn.clicked.connect(self._cancel)
        self.close_btn.clicked.connect(self.close)
        self.format_combo.currentIndexChanged.connect(lambda _i: self._set_format(self.format_combo.currentData()))

        fmt = str(settings.get("export/format", "mp4", str))
        idx = self.format_combo.findData(fmt)
        if idx >= 0 and idx != self.format_combo.currentIndex():
            self.format_combo.setCurrentIndex(idx)    # → _set_format
        else:
            self._set_format(self.format_combo.currentData())

    # ------------------------------------------------------------------ 포맷
    def _set_format(self, format_id: str) -> None:
        if not format_id or not OptionsPanelFactory.has(format_id):
            return
        if self._panel is not None:
            self.settings.save_options(self._panel.get_options(), _PREFIX)
            self._slot.removeWidget(self._panel)
            self._panel.deleteLater()
        self._converter = registry.get(format_id)
        panel = OptionsPanelFactory.create(format_id)
        if hasattr(panel, "set_hwaccel"):
            panel.set_hwaccel(self.settings.hwaccel)  # type: ignore[attr-defined]
        panel.set_options(self.settings.load_options(self._converter, _PREFIX))
        panel.set_reference_info(self.item.info)
        self._slot.addWidget(panel)
        self._panel = panel
        if not self._out_edited or not self.out_edit.text():
            self.out_edit.setText(str(self._default_output()))
        else:
            # 사용자가 고친 경로라도 확장자는 포맷에 맞춘다
            p = Path(self.out_edit.text())
            self.out_edit.setText(str(p.with_suffix(self._converter.extension)))

    def _default_output(self) -> Path:
        return make_output_path(self.item.path, None, C.EXPORT_SUFFIX, self._converter.extension, False)

    def _options(self) -> ConvertOptions:
        assert self._panel is not None
        opts = self._panel.get_options()
        if hasattr(opts, "hwaccel"):
            opts.hwaccel = self.settings.hwaccel  # type: ignore[attr-defined]
        return opts

    def _browse(self) -> None:
        ext = self._converter.extension
        path, _ = QFileDialog.getSaveFileName(self, "Export with Drawing", self.out_edit.text(),
                                              f"{self._converter.display_name} (*{ext})")
        if path:
            p = Path(path)
            if p.suffix.lower() != ext:
                p = p.with_name(p.name + ext)
            self.out_edit.setText(str(p))
            self._out_edited = True

    # ------------------------------------------------------------------ 실행
    def _export(self) -> None:
        if self.worker is not None or self._panel is None:
            return
        ffmpeg = ffmpeg_locator.find_ffmpeg()
        if ffmpeg is None:
            QMessageBox.critical(self, "ffmpeg not found", "ffmpeg is not available. Use Help > Check Dependencies.")
            return
        opts = self._options()
        problems = self._converter.validate(opts)
        if problems:
            QMessageBox.warning(self, "Invalid options", "\n".join(problems))
            return
        text = self.out_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "No output", "Choose an output file.")
            return
        out = Path(text)
        if out.suffix.lower() != self._converter.extension:
            out = out.with_name(out.name + self._converter.extension)
        if normcase_path(out) == normcase_path(self.item.path):
            QMessageBox.warning(self, "Invalid output", "The output file cannot be the source video.")
            return
        if not out.parent.is_dir():
            QMessageBox.warning(self, "Invalid output", f"Folder does not exist:\n{out.parent}")
            return
        if out.exists():
            ans = QMessageBox.question(self, "Overwrite?", f"'{out.name}' already exists. Overwrite it?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        if self.doc.is_empty():
            ans = QMessageBox.question(self, "No drawings", "This video has no drawings. Export anyway?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        self._save_settings()
        ghost = self.ghost if self.ghost_check.isChecked() else None
        self.worker = ExportWorker(ffmpeg, self.item, self._converter, opts, out, self.doc, ghost, self)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.log.connect(self._log)
        self.worker.finished_ok.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._worker_finished)
        self._set_running(True)
        self.bar.setValue(0)
        self.status.setText(f"Exporting to {out.name}…")
        self.log.emit(f"Exporting {self.item.path.name} -> {out.name} ({self._converter.display_name}"
                      f"{', with ghosting' if ghost else ''}).")
        self.worker.start()

    def _cancel(self) -> None:
        if self.worker is not None:
            self.status.setText("Canceling…")
            self.worker.cancel()

    def _log(self, msg: str) -> None:
        self.status.setText(msg)
        self.log.emit(msg)

    def _done(self, path: Path, size: int, elapsed: float) -> None:
        self.status.setText(f"Exported: {Path(path).name} ({human_size(size)}, {elapsed:.1f} s)")
        self.exported.emit(path, size, elapsed)
        # 다음 내보내기가 같은 파일을 덮지 않게 기본 경로를 다시 계산한다
        if not self._out_edited:
            self.out_edit.setText(str(self._default_output()))

    def _failed(self, msg: str) -> None:
        self.status.setText(f"Export failed: {msg}" if msg != "Canceled." else "Export canceled.")
        self.log.emit(f"Export failed: {msg}" if msg != "Canceled." else "Export canceled.")

    def _worker_finished(self) -> None:
        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.export_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(running)
        self.close_btn.setEnabled(not running)
        self.format_combo.setEnabled(not running)
        if self._panel is not None:
            self._panel.setEnabled(not running)
        self.ghost_check.setEnabled(not running)
        self.out_edit.setEnabled(not running)
        self.browse_btn.setEnabled(not running)

    def _save_settings(self) -> None:
        self.settings.set("export/format", self._converter.format_id)
        self.settings.set("export/include_ghost", self.ghost_check.isChecked())
        if self._panel is not None:
            self.settings.save_options(self._panel.get_options(), _PREFIX)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.worker is not None:
            event.ignore()
            return
        self._save_settings()
        super().closeEvent(event)

    def reject(self) -> None:
        # Esc 로 닫을 때도 실행 중이면 막는다
        if self.worker is None:
            self._save_settings()
            super().reject()
