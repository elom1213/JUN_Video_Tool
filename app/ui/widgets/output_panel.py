# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""출력 폴더 · 접미사 · 덮어쓰기 패널 (PLAN 6.9)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLineEdit,
                               QPushButton, QRadioButton, QLabel)

from ...core.models import ConvertOptions


class OutputPanel(QGroupBox):
    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("Output", parent)
        self._auto_suffix = "_gif"

        self.rb_source = QRadioButton("Same folder as source")
        self.rb_folder = QRadioButton("Folder")
        self.rb_source.setChecked(True)
        self.dir_edit = QLineEdit()
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setPlaceholderText("Choose an output folder…")
        self.browse_btn = QPushButton("Browse…")
        self.suffix_edit = QLineEdit(self._auto_suffix)
        self.suffix_edit.setPlaceholderText("Suffix")
        self.overwrite_check = QCheckBox("Overwrite")

        g = QGridLayout(self)
        g.setContentsMargins(8, 8, 8, 8)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(4)
        g.addWidget(self.rb_source, 0, 0, 1, 3)
        g.addWidget(self.rb_folder, 1, 0)
        g.addWidget(self.dir_edit, 1, 1)
        g.addWidget(self.browse_btn, 1, 2)
        row = QHBoxLayout()
        row.addWidget(QLabel("Suffix"))
        row.addWidget(self.suffix_edit, 1)
        row.addSpacing(8)
        row.addWidget(self.overwrite_check)
        g.addLayout(row, 2, 0, 1, 3)

        self.rb_source.toggled.connect(self._mode_changed)
        self.browse_btn.clicked.connect(self._browse)
        self.suffix_edit.textChanged.connect(lambda _: self.changed.emit())
        self.overwrite_check.toggled.connect(lambda _: self.changed.emit())
        self._mode_changed()

    # ------------------------------------------------------------------ 동작
    def _mode_changed(self) -> None:
        use_folder = self.rb_folder.isChecked()
        self.dir_edit.setEnabled(use_folder)
        self.browse_btn.setEnabled(use_folder)
        self.changed.emit()

    def _browse(self) -> None:
        start = self.dir_edit.text() or str(Path.home())
        d = QFileDialog.getExistingDirectory(self, "Select output folder", start)
        if d:
            self.dir_edit.setText(d)
            self.rb_folder.setChecked(True)
            self.changed.emit()

    def suggest_suffix(self, format_id: str) -> None:
        """포맷 변경 시, 비어 있거나 이전 자동값이면 새 자동값으로."""
        new = f"_{format_id}"
        cur = self.suffix_edit.text()
        if cur in ("", self._auto_suffix):
            self.suffix_edit.setText(new)
        self._auto_suffix = new

    # ------------------------------------------------------------------ 값
    def output_dir(self) -> Path | None:
        if self.rb_folder.isChecked() and self.dir_edit.text().strip():
            return Path(self.dir_edit.text().strip())
        return None

    def apply_to(self, options: ConvertOptions) -> ConvertOptions:
        return replace(options, output_dir=self.output_dir(), suffix=self.suffix_edit.text(),
                       overwrite=self.overwrite_check.isChecked())

    def state(self) -> dict:
        return {"mode": "folder" if self.rb_folder.isChecked() else "source",
                "dir": self.dir_edit.text(), "suffix": self.suffix_edit.text(),
                "overwrite": self.overwrite_check.isChecked()}

    def restore(self, mode: str, directory: str, suffix: str, overwrite: bool) -> None:
        self.dir_edit.setText(directory or "")
        (self.rb_folder if mode == "folder" and directory else self.rb_source).setChecked(True)
        if suffix:
            self.suffix_edit.setText(suffix)
        self.overwrite_check.setChecked(bool(overwrite))
