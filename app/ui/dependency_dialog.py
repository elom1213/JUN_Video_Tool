# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""의존성 상태 · 설치 다이얼로그 (PLAN 13.5). bootstrap.py 를 QProcess 로 실행한다."""
from __future__ import annotations

import json
import sys

from PySide6.QtCore import QProcess, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.utils import tool_root
from ..core.ffmpeg_locator import bin_dir
from .icons import app_icon, icon

_COLS = ("Name", "Required", "Found", "Status", "Location")


class DependencyDialog(QDialog):
    dependencies_changed = Signal()

    def __init__(self, parent=None, auto_install: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dependencies")
        self.setWindowIcon(app_icon())
        self.resize(760, 520)
        self._proc: QProcess | None = None
        self._installing = False
        self._auto_install = auto_install

        self.table = QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(list(_COLS))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(len(_COLS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("LogPanel")
        self.log.setMaximumBlockCount(3000)

        self.install_btn = QPushButton(icon("download"), "Install Missing")
        self.recheck_btn = QPushButton(icon("refresh"), "Re-check")
        self.open_bin_btn = QPushButton(icon("folder"), "Open bin Folder")
        self.close_btn = QPushButton("Close")
        self.status_label = QLabel("")
        self.status_label.setObjectName("HintLabel")

        btns = QHBoxLayout()
        btns.addWidget(self.install_btn)
        btns.addWidget(self.recheck_btn)
        btns.addWidget(self.open_bin_btn)
        btns.addStretch(1)
        btns.addWidget(self.close_btn)

        v = QVBoxLayout(self)
        v.addWidget(self.table, 2)
        v.addWidget(self.status_label)
        v.addWidget(self.progress)
        v.addWidget(self.log, 1)
        v.addLayout(btns)

        self.install_btn.clicked.connect(self.install_missing)
        self.recheck_btn.clicked.connect(self.recheck)
        self.open_bin_btn.clicked.connect(self._open_bin)
        self.close_btn.clicked.connect(self.close)

        self.recheck()

    # ------------------------------------------------------------------ 실행
    def _bootstrap_cmd(self, *args: str) -> tuple[str, list[str]]:
        return sys.executable, [str(tool_root() / "bootstrap.py"), *args]

    def _start(self, args: list[str], installing: bool) -> None:
        if self._proc is not None:
            return
        self._installing = installing
        self._set_busy(True)
        self.progress.setValue(0)
        self.log.clear()
        self.status_label.setText("Installing…" if installing else "Checking…")
        prog, argv = self._bootstrap_cmd(*args)
        self._proc = QProcess(self)
        self._proc.setWorkingDirectory(str(tool_root()))
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._read)
        self._proc.finished.connect(self._finished)
        self._proc.errorOccurred.connect(self._error)
        self._proc.start(prog, argv)

    def recheck(self) -> None:
        self._start(["--check", "--json"], installing=False)

    def install_missing(self) -> None:
        self._start(["--yes", "--json"], installing=True)

    def _read(self) -> None:
        if self._proc is None:
            return
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            if line.startswith("PROGRESS "):
                try:
                    self.progress.setValue(int(float(line.split()[1])))
                except (ValueError, IndexError):
                    pass
                continue
            if line.startswith("REPORT_JSON "):
                try:
                    report = json.loads(line[len("REPORT_JSON "):])
                except json.JSONDecodeError:
                    report = None
                if report:
                    self._fill_table(report)
                continue
            if line.strip():
                self.log.appendPlainText(line)

    def _finished(self, code: int, _status) -> None:
        self._proc = None
        self._set_busy(False)
        was_installing = self._installing
        self._installing = False
        if was_installing:
            self.progress.setValue(100)
            self.status_label.setText("Install finished." if code == 0 else f"Install finished with errors (exit {code}).")
            self.dependencies_changed.emit()
            if self._auto_install:
                self._auto_install = False
        else:
            self.status_label.setText("Check complete.")
            if self._auto_install and self.install_btn.isEnabled():
                self._auto_install = False
                self.install_missing()

    def _error(self, _err) -> None:
        if self._proc is not None:
            self.log.appendPlainText(f"Failed to run bootstrap.py: {self._proc.errorString()}")
        self._proc = None
        self._set_busy(False)
        self.status_label.setText("Could not run bootstrap.py.")

    def _set_busy(self, busy: bool) -> None:
        self.recheck_btn.setEnabled(not busy)
        self.install_btn.setEnabled(not busy and self.install_btn.property("hasMissing") is True)
        self.close_btn.setEnabled(True)

    # ------------------------------------------------------------------ 표
    def _fill_table(self, report: dict) -> None:
        items = report.get("items") or []
        self.table.setRowCount(0)
        has_missing = False
        for it in items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            vals = (it.get("name", ""), it.get("required", ""), it.get("found", ""),
                    it.get("status", ""), it.get("location", ""))
            for col, val in enumerate(vals):
                cell = QTableWidgetItem(str(val))
                if col == 3:
                    status = str(val)
                    if status == "OK":
                        cell.setForeground(Qt.GlobalColor.green)
                    elif status in ("Missing", "Outdated", "Unsupported", "FAILED"):
                        cell.setForeground(Qt.GlobalColor.yellow if status != "FAILED" else Qt.GlobalColor.red)
                        if it.get("required") != "optional":
                            has_missing = True
                self.table.setItem(row, col, cell)
        self.install_btn.setProperty("hasMissing", has_missing)
        self.install_btn.setEnabled(has_missing and self._proc is None)
        if not has_missing:
            self.status_label.setText("All required dependencies are installed.")

    def _open_bin(self) -> None:
        d = bin_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    # ------------------------------------------------------------------ 닫기
    def closeEvent(self, event) -> None:  # noqa: N802
        if self._proc is not None and self._installing:
            ans = QMessageBox.question(self, "Installing", "Installation is running. Stop it and close?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._proc.kill()
            self._proc.waitForFinished(3000)
            self._proc = None
        super().closeEvent(event)
