# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""메인 윈도우 (PLAN 6.1, 6.11)."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDesktopServices, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSplitter, QToolBar, QVBoxLayout, QWidget)

from ..config import constants as C
from ..config.settings import AppSettings
from ..config.version import APP_NAME, VERSION
from ..core import ffmpeg_locator
from ..core.converters import registry
from ..core.converters.base import BaseConverter
from ..core.job_runner import JobRunner
from ..core.models import ConvertJob, ConvertOptions, ConvertResult, FrameRange, ItemStatus, MediaInfo
from ..core.size_estimator import make_est_key
from ..core.thumbnail import representative_time
from ..core.utils import human_size, make_output_path
from .dependency_dialog import DependencyDialog
from .icons import app_icon, icon
from .settings_dialog import SettingsDialog
from .widgets import gif_options_panel  # noqa: F401  (팩토리 등록)
from .widgets.frame_range_panel import FrameRangePanel
from .widgets.loaders import ProbeLoader, SizeEstimator, ThumbnailLoader
from .widgets.log_panel import LogPanel
from .widgets.options_panel_base import BaseOptionsPanel, OptionsPanelFactory
from .widgets.output_panel import OutputPanel
from .widgets.video_list_model import VideoListModel
from .widgets.video_list_view import VideoListView

_VIDEO_FILTER = "Video files (" + " ".join(f"*{e}" for e in sorted(C.SUPPORTED_EXTENSIONS)) + ");;All files (*.*)"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1280, 760)
        self.setMinimumSize(1000, 600)

        self.settings = AppSettings()
        self.model = VideoListModel(self)
        self.probe_loader = ProbeLoader(self)
        self.thumb_loader = ThumbnailLoader(self)
        self.estimator = SizeEstimator(ffmpeg_locator.find_ffmpeg, self)
        self.runner: JobRunner | None = None
        self._thumb_keys: dict[str, Path] = {}
        self._options_panel: BaseOptionsPanel | None = None
        self._converter: BaseConverter = registry.all()[0]
        self._total_jobs = 0
        self._done_jobs = 0
        self._dep_dialog: DependencyDialog | None = None
        self._ffmpeg_ok = False
        # _build_ui 중에도 _schedule_estimates 가 호출될 수 있으므로 타이머는 가장 먼저 만든다
        self._est_timer = QTimer(self)
        self._est_timer.setSingleShot(True)
        self._est_timer.setInterval(C.ESTIMATE_DEBOUNCE_MS)
        self._est_timer.timeout.connect(self._run_estimates)

        self._build_ui()
        self._build_menus()
        self._connect()
        self._restore_settings()
        QTimer.singleShot(0, self._startup_checks)

    # ================================================================== UI 구성
    def _build_ui(self) -> None:
        # --- 툴바 ---
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.act_add_files = QAction(icon("add_files"), "Add Files", self)
        self.act_add_folder = QAction(icon("add_folder"), "Add Folder", self)
        self.act_remove = QAction(icon("remove"), "Remove", self)
        self.act_clear = QAction(icon("clear"), "Clear", self)
        self.act_check_all = QAction(icon("check_all"), "Check All", self)
        self.act_uncheck_all = QAction(icon("uncheck_all"), "Uncheck All", self)
        self.act_invert = QAction(icon("invert"), "Invert", self)
        self.act_view_list = QAction(icon("view_list"), "List", self)
        self.act_view_thumbs = QAction(icon("view_thumbs"), "Thumbnails", self)
        for a in (self.act_view_list, self.act_view_thumbs):
            a.setCheckable(True)
        self.act_view_list.setChecked(True)
        grp = QActionGroup(self)
        grp.setExclusive(True)
        grp.addAction(self.act_view_list)
        grp.addAction(self.act_view_thumbs)
        for a in (self.act_add_files, self.act_add_folder, self.act_remove, self.act_clear):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_check_all, self.act_uncheck_all, self.act_invert):
            tb.addAction(a)
        tb.addSeparator()
        view_label = QLabel("View: ")
        tb.addWidget(view_label)
        tb.addAction(self.act_view_list)
        tb.addAction(self.act_view_thumbs)

        # --- 좌: 리스트 ---
        self.view = VideoListView()
        self.view.setModel(self.model)

        # --- 우: 옵션 ---
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(6, 6, 6, 6)
        rv.setSpacing(6)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Output format:"))
        self.format_combo = QComboBox()
        for conv in registry.all():
            self.format_combo.addItem(conv.display_name, conv.format_id)
        fmt_row.addWidget(self.format_combo, 1)
        rv.addLayout(fmt_row)

        self._options_slot = QVBoxLayout()
        rv.addLayout(self._options_slot)
        self.range_panel = FrameRangePanel(self.thumb_loader)
        rv.addWidget(self.range_panel)
        self.output_panel = OutputPanel()
        rv.addWidget(self.output_panel)
        rv.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(right)
        right.setMinimumWidth(0)

        # 합계 라벨과 변환/취소 버튼은 스크롤 밖 하단에 고정해 항상 보이게 한다
        self.total_label = QLabel("Estimated total: —")
        self.total_label.setObjectName("TotalLabel")
        self.total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_label.setWordWrap(True)
        self.convert_btn = QPushButton(icon("convert"), "Convert Checked")
        self.convert_btn.setObjectName("ConvertButton")
        self.convert_btn.setIconSize(QSize(20, 20))
        self.cancel_btn = QPushButton(icon("cancel"), "Cancel")
        self.cancel_btn.setEnabled(False)
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(4)
        sv.addWidget(scroll, 1)
        sv.addWidget(self.total_label)
        sv.addWidget(self.convert_btn)
        sv.addWidget(self.cancel_btn)
        side.setMinimumWidth(400)

        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.h_splitter.addWidget(self.view)
        self.h_splitter.addWidget(side)
        self.h_splitter.setStretchFactor(0, 6)
        self.h_splitter.setStretchFactor(1, 4)
        self.h_splitter.setSizes([760, 500])

        # --- 하단: 진행 · 로그 ---
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(6, 4, 6, 6)
        bv.setSpacing(4)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Overall"))
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 1)
        self.overall_bar.setValue(0)
        self.overall_bar.setFormat("%v / %m")
        prow.addWidget(self.overall_bar, 1)
        bv.addLayout(prow)
        self.log = LogPanel()
        bv.addWidget(self.log, 1)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.addWidget(self.h_splitter)
        self.v_splitter.addWidget(bottom)
        self.v_splitter.setStretchFactor(0, 5)
        self.v_splitter.setStretchFactor(1, 1)
        self.v_splitter.setSizes([560, 160])
        self.setCentralWidget(self.v_splitter)

        self._set_format(self.format_combo.currentData())

    def _build_menus(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("File")
        self.act_add_files.setShortcut(QKeySequence("Ctrl+O"))
        self.act_add_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        m_file.addAction(self.act_add_files)
        m_file.addAction(self.act_add_folder)
        m_file.addSeparator()
        act_exit = QAction(icon("cancel"), "Exit", self)
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        m_edit = mb.addMenu("Edit")
        self.act_check_all.setShortcut(QKeySequence("Ctrl+A"))
        self.act_uncheck_all.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.act_invert.setShortcut(QKeySequence("Ctrl+I"))
        self.act_remove.setShortcut(QKeySequence("Del"))
        for a in (self.act_check_all, self.act_uncheck_all, self.act_invert):
            m_edit.addAction(a)
        m_edit.addSeparator()
        m_edit.addAction(self.act_remove)
        m_edit.addAction(self.act_clear)
        m_edit.addSeparator()
        self.act_refresh_est = QAction(icon("refresh"), "Refresh Estimates", self)
        self.act_refresh_est.setShortcut(QKeySequence("F5"))
        m_edit.addAction(self.act_refresh_est)
        self.act_settings = QAction(icon("settings"), "Settings…", self)
        m_edit.addAction(self.act_settings)

        m_view = mb.addMenu("View")
        self.act_view_list.setShortcut(QKeySequence("Ctrl+1"))
        self.act_view_thumbs.setShortcut(QKeySequence("Ctrl+2"))
        m_view.addAction(self.act_view_list)
        m_view.addAction(self.act_view_thumbs)

        m_help = mb.addMenu("Help")
        self.act_deps = QAction(icon("download"), "Check Dependencies…", self)
        self.act_ffmpeg_info = QAction(icon("info"), "Show ffmpeg Info", self)
        self.act_about = QAction(app_icon(), "About", self)
        m_help.addAction(self.act_deps)
        m_help.addAction(self.act_ffmpeg_info)
        m_help.addSeparator()
        m_help.addAction(self.act_about)

    def _connect(self) -> None:
        self.act_add_files.triggered.connect(self.add_files)
        self.act_add_folder.triggered.connect(self.add_folder)
        self.act_remove.triggered.connect(lambda: self.remove_rows(self.view.selected_rows()))
        self.act_clear.triggered.connect(self.clear_list)
        self.act_check_all.triggered.connect(lambda: self.model.set_all_checked(True))
        self.act_uncheck_all.triggered.connect(lambda: self.model.set_all_checked(False))
        self.act_invert.triggered.connect(self.model.invert_checked)
        self.act_view_list.triggered.connect(lambda: self._set_view_mode("list"))
        self.act_view_thumbs.triggered.connect(lambda: self._set_view_mode("thumbs"))
        self.act_refresh_est.triggered.connect(self._run_estimates)
        self.act_settings.triggered.connect(self.open_settings)
        self.act_deps.triggered.connect(lambda: self.open_dependencies(False))
        self.act_ffmpeg_info.triggered.connect(self.show_ffmpeg_info)
        self.act_about.triggered.connect(self.show_about)

        self.view.files_dropped.connect(self.add_paths)
        self.view.remove_requested.connect(self.remove_rows)
        self.view.open_folder_requested.connect(self.open_containing_folder)
        self.view.reset_range_requested.connect(self.reset_ranges)
        self.view.selectionModel().currentChanged.connect(lambda cur, _prev: self._current_changed(cur.row()))

        self.model.rows_added.connect(self._rows_added)
        self.model.check_changed.connect(self._schedule_estimates)
        self.probe_loader.probe_ready.connect(self._probe_ready)
        self.probe_loader.probe_failed.connect(self._probe_failed)
        self.thumb_loader.thumbnail_ready.connect(self._thumb_ready)
        self.estimator.estimate_ready.connect(self._estimate_ready)
        self.estimator.estimate_failed.connect(self._estimate_failed)

        self.format_combo.currentIndexChanged.connect(lambda _: self._set_format(self.format_combo.currentData()))
        self.range_panel.range_changed.connect(self._range_changed)
        self.range_panel.apply_to_checked.connect(self._apply_range_to_checked)
        self.output_panel.changed.connect(self._schedule_estimates)
        self.convert_btn.clicked.connect(self.convert_checked)
        self.cancel_btn.clicked.connect(self.cancel_conversion)

    # ================================================================== 설정 복원 · 저장
    def _restore_settings(self) -> None:
        geo = self.settings.get("ui/geometry")
        if isinstance(geo, QByteArray) and not geo.isEmpty():
            self.restoreGeometry(geo)
        for key, sp in (("ui/splitter_h", self.h_splitter), ("ui/splitter_v", self.v_splitter)):
            st = self.settings.get(key)
            if isinstance(st, QByteArray) and not st.isEmpty():
                sp.restoreState(st)
        mode = str(self.settings.get("ui/view_mode", "list", str))
        (self.act_view_thumbs if mode == "thumbs" else self.act_view_list).setChecked(True)
        self._set_view_mode(mode)
        fmt = str(self.settings.get("format/current", "gif", str))
        idx = self.format_combo.findData(fmt)
        if idx >= 0:
            self.format_combo.setCurrentIndex(idx)
        self.output_panel.restore(
            str(self.settings.get("io/output_mode", "source", str)),
            self.settings.last_output_dir,
            str(self.settings.get("io/suffix", "", str)),
            bool(self.settings.get("io/overwrite", False, bool)),
        )
        if self._converter.format_id == "gif" and self._options_panel is not None:
            self._options_panel.set_options(self.settings.load_gif_options())

    def _save_settings(self) -> None:
        s = self.settings
        s.set("ui/geometry", self.saveGeometry())
        s.set("ui/splitter_h", self.h_splitter.saveState())
        s.set("ui/splitter_v", self.v_splitter.saveState())
        s.set("ui/view_mode", self.view.view_mode())
        s.set("format/current", self._converter.format_id)
        st = self.output_panel.state()
        s.set("io/output_mode", st["mode"])
        s.last_output_dir = st["dir"]
        s.set("io/suffix", st["suffix"])
        s.set("io/overwrite", st["overwrite"])
        if self._converter.format_id == "gif" and self._options_panel is not None:
            opts = self._options_panel.get_options()
            s.save_gif_options(opts)  # type: ignore[arg-type]
        s.sync()

    # ================================================================== 시작 점검
    def _startup_checks(self) -> None:
        ff = ffmpeg_locator.find_ffmpeg()
        if ff is None:
            self.log.append_error("ffmpeg was not found.")
            self._set_ffmpeg_available(False)
            ans = QMessageBox.question(
                self, "ffmpeg not found",
                f"ffmpeg was not found.\nInstall it now? (downloads about 90 MB into {ffmpeg_locator.bin_dir()})",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                self.open_dependencies(auto_install=True)
            return
        self._set_ffmpeg_available(True)
        self.log.append(f"{ffmpeg_locator.ffmpeg_version(ff) or 'ffmpeg'} — {ff}")
        if ffmpeg_locator.find_ffprobe() is None:
            self.log.append("ffprobe not found; falling back to ffmpeg output parsing for media info.")

    def _set_ffmpeg_available(self, ok: bool) -> None:
        self._ffmpeg_ok = ok
        self.convert_btn.setEnabled(ok)
        self.act_add_files.setEnabled(ok)
        self.act_add_folder.setEnabled(ok)
        self.view.setAcceptDrops(ok)

    def _dependencies_changed(self) -> None:
        ffmpeg_locator.reset_cache()
        ff = ffmpeg_locator.find_ffmpeg()
        if ff is not None:
            self._set_ffmpeg_available(True)
            self.log.append_ok(f"ffmpeg is now available: {ff}")
            # 미프로브 항목 재프로브
            for row, it in enumerate(self.model.items()):
                if it.info is None:
                    self.probe_loader.request(it.path)
        else:
            self.log.append_error("ffmpeg is still missing.")

    # ================================================================== 포맷 · 옵션 패널
    def _set_format(self, format_id: str) -> None:
        if not format_id or not OptionsPanelFactory.has(format_id):
            return
        self._converter = registry.get(format_id)
        if self._options_panel is not None:
            self._options_slot.removeWidget(self._options_panel)
            self._options_panel.deleteLater()
        panel = OptionsPanelFactory.create(format_id)
        self._options_slot.addWidget(panel)
        self._options_panel = panel
        if hasattr(panel, "set_hwaccel"):
            panel.set_hwaccel(self.settings.hwaccel)  # type: ignore[attr-defined]
        panel.options_changed.connect(self._options_changed)
        self.output_panel.suggest_suffix(format_id)
        self._current_changed(self.view.currentIndex().row())
        self._options_changed()

    def _current_options(self) -> ConvertOptions:
        assert self._options_panel is not None
        opts = self._options_panel.get_options()
        if hasattr(opts, "hwaccel"):
            opts.hwaccel = self.settings.hwaccel  # type: ignore[attr-defined]
        return self.output_panel.apply_to(opts)

    def _options_changed(self) -> None:
        row = self.view.currentIndex().row()
        if 0 <= row < self.model.rowCount():
            item = self.model.item(row)
            if item.info is not None:
                self.range_panel.set_output_fps(self._converter.output_fps(item, self._current_options()))
        target = self._converter.target_size_bytes(self._current_options()) if self._converter.supports_target_size() else None
        self.model.set_target_bytes(target)
        self._schedule_estimates()

    # ================================================================== 파일 추가 · 제거
    def add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Add video files", self.settings.last_input_dir, _VIDEO_FILTER)
        if files:
            self.settings.last_input_dir = str(Path(files[0]).parent)
            self.add_paths([Path(f) for f in files])

    def add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Add all videos in folder", self.settings.last_input_dir)
        if d:
            self.settings.last_input_dir = d
            self.add_paths(sorted(p for p in Path(d).iterdir() if p.is_file()))

    def add_paths(self, paths: list[Path]) -> None:
        if not getattr(self, "_ffmpeg_ok", False):
            self.log.append_error("Cannot add files: ffmpeg is not available.")
            return
        if self.runner is not None:
            self.log.append_error("Cannot add files while a conversion is running.")
            return
        added, skipped = self.model.add_paths(paths)
        msg = f"Added {added} file{'s' if added != 1 else ''}"
        if skipped:
            msg += f" ({skipped} skipped: unsupported or duplicate)"
        self.log.append(msg + ".")

    def _rows_added(self, rows: list[int]) -> None:
        for r in rows:
            self.probe_loader.request(self.model.item(r).path)
        if self.view.currentIndex().row() < 0 and rows:
            self.view.setCurrentIndex(self.model.index(rows[0]))

    def remove_rows(self, rows: list[int]) -> None:
        if self.runner is not None:
            self.log.append_error("Cannot remove files while a conversion is running.")
            return
        if rows:
            self.model.remove_rows(rows)
            self._current_changed(self.view.currentIndex().row())

    def clear_list(self) -> None:
        if self.runner is not None:
            self.log.append_error("Cannot clear the list while a conversion is running.")
            return
        self.probe_loader.cancel_all()
        self.estimator.cancel_all()
        self.model.clear()
        self.range_panel.set_item(-1, None)
        self._update_total_label()

    def open_containing_folder(self, row: int) -> None:
        if 0 <= row < self.model.rowCount():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.item(row).path.parent)))

    def reset_ranges(self, rows: list[int]) -> None:
        for r in rows:
            if 0 <= r < self.model.rowCount():
                self.model.update_item(r, frame_range=None, est_key="", est_size=None, est_level="none")
                self.range_panel.refresh_item(r, self.model.item(r))
        self._schedule_estimates()

    # ================================================================== 프로브 · 썸네일
    def _probe_ready(self, path: Path, info: MediaInfo) -> None:
        row = self.model.row_of(path)
        if row < 0:
            return
        self.model.set_info(row, info, None)
        key = self.thumb_loader.request(path, representative_time(info), C.THUMB_WIDTH)
        self._thumb_keys[key] = path
        if self.view.currentIndex().row() == row:
            self._current_changed(row)
        self._schedule_estimates()

    def _probe_failed(self, path: Path, error: str) -> None:
        row = self.model.row_of(path)
        if row < 0:
            return
        self.model.set_info(row, None, error)
        self.log.append_error(f"[{path.name}] Probe failed: {error}")
        if self.view.currentIndex().row() == row:
            self._current_changed(row)

    def _thumb_ready(self, key: str, img: QImage) -> None:
        path = self._thumb_keys.pop(key, None)
        if path is None:
            return
        row = self.model.row_of(path)
        if row >= 0:
            self.model.set_thumbnail(row, QPixmap.fromImage(img))

    def _set_view_mode(self, mode: str) -> None:
        self.view.set_view_mode(mode)

    # ================================================================== 선택 · 구간
    def _current_changed(self, row: int) -> None:
        item = self.model.item(row) if 0 <= row < self.model.rowCount() else None
        self.range_panel.set_item(row, item)
        if self._options_panel is not None:
            self._options_panel.set_reference_info(item.info if item else None)
        if item is not None and item.info is not None:
            self.range_panel.set_output_fps(self._converter.output_fps(item, self._current_options()))
        self._schedule_estimates()

    def _range_changed(self, row: int, rng: FrameRange | None) -> None:
        if 0 <= row < self.model.rowCount():
            self.model.update_item(row, frame_range=rng)
            self._schedule_estimates()

    def _apply_range_to_checked(self, rng: FrameRange) -> None:
        clipped = 0
        applied = 0
        for r in self.model.checked_rows():
            it = self.model.item(r)
            if it.info is None:
                continue
            c = rng.clamp(it.info)
            if c.end_frame != rng.end_frame or c.start_frame != rng.start_frame:
                clipped += 1
            self.model.update_item(r, frame_range=None if c.is_full(it.info) else c)
            applied += 1
        msg = f"Applied range {rng.start_frame}-{rng.end_frame} to {applied} checked item(s)."
        if clipped:
            msg += f" {clipped} shorter video(s) were clipped to their last frame."
        self.log.append(msg)
        self._schedule_estimates()

    # ================================================================== 용량 추정
    def _schedule_estimates(self) -> None:
        if self.runner is None:
            self._est_timer.start()

    def _run_estimates(self) -> None:
        if self.runner is not None or self._options_panel is None:
            return
        options = self._current_options()
        rows = set(self.model.checked_rows())
        cur = self.view.currentIndex().row()
        if cur >= 0:
            rows.add(cur)
        self.estimator.cancel_all()
        use_samples = self.settings.estimate_enabled and ffmpeg_locator.find_ffmpeg() is not None
        for r in sorted(rows):
            it = self.model.item(r)
            if it.info is None or it.status in (ItemStatus.RUNNING, ItemStatus.QUEUED):
                continue
            key = make_est_key(it.path, it.effective_range(), options)
            if it.est_key == key and it.est_level in ("sampled", "exact"):
                continue
            heuristic = self._converter.heuristic_size(it, options)
            self.model.update_item(r, est_key=key)
            self.model.set_estimate(r, key, heuristic, "heuristic" if heuristic is not None else "none")
            if use_samples and heuristic is not None:
                self.estimator.request(r, it, self._converter, options)
        self._update_total_label()

    def _estimate_ready(self, row: int, key: str, size: int, level: str) -> None:
        r = self._row_for_key(row, key)
        if r is not None:
            self.model.set_estimate(r, key, size, level)
            self._update_total_label()

    def _estimate_failed(self, row: int, key: str, error: str) -> None:
        r = self._row_for_key(row, key)
        if r is not None:
            it = self.model.item(r)
            self.log.append(f"[{it.path.name}] Size estimate failed: {error}")

    def _row_for_key(self, row: int, key: str) -> int | None:
        if 0 <= row < self.model.rowCount() and self.model.item(row).est_key == key:
            return row
        for r, it in enumerate(self.model.items()):
            if it.est_key == key:
                return r
        return None

    def _update_total_label(self) -> None:
        total = 0
        files = 0
        pending = 0
        for r in self.model.checked_rows():
            it = self.model.item(r)
            if it.info is None or it.status == ItemStatus.DONE:
                continue
            files += 1
            if it.est_size is not None:
                total += it.est_size
                if it.est_level == "heuristic" and self.settings.estimate_enabled:
                    pending += 1
            else:
                pending += 1
        if files == 0:
            self.total_label.setText("Estimated total: —")
            return
        prefix = "≈" if pending == 0 else "~"
        txt = f"Estimated total: {prefix}{human_size(total)} ({files} file{'s' if files != 1 else ''}"
        if pending:
            txt += f", {pending} pending"
        self.total_label.setText(txt + ")")

    # ================================================================== 변환
    def convert_checked(self) -> None:
        if self.runner is not None or self._options_panel is None:
            return
        ffmpeg = ffmpeg_locator.find_ffmpeg()
        if ffmpeg is None:
            QMessageBox.critical(self, "ffmpeg not found", "ffmpeg is not available. Use Help > Check Dependencies.")
            return
        options = self._current_options()
        problems = self._converter.validate(options)
        if options.output_dir is None:
            pass
        if problems:
            QMessageBox.warning(self, "Invalid options", "\n".join(problems))
            return
        rows = self.model.checked_rows()
        if not rows:
            QMessageBox.information(self, "Nothing to convert", "Check at least one video.")
            return

        jobs: list[tuple[int, ConvertJob]] = []
        warnings: list[str] = []
        for r in rows:
            it = self.model.item(r)
            if it.info is None:
                self.model.update_item(r, status=ItemStatus.SKIPPED, message=it.probe_error or "No media info")
                self.log.append(f"[{it.path.name}] Skipped: {it.probe_error or 'not probed yet'}")
                continue
            out = make_output_path(it.path, options.output_dir, options.suffix, self._converter.extension,
                                   options.overwrite)
            if len(str(out)) > C.MAX_OUTPUT_PATH_LEN:
                warnings.append(f"{it.path.name}: output path is too long for Windows (>{C.MAX_OUTPUT_PATH_LEN} chars).")
            w = self._converter.estimate_warning(it, options)
            if w:
                warnings.append(f"{it.path.name}: {w}")
            jobs.append((r, ConvertJob(item=it, options=options, output_path=out)))
        if not jobs:
            self.log.append_error("No convertible items (all skipped).")
            return
        if warnings:
            shown = "\n".join(warnings[:8]) + ("\n…" if len(warnings) > 8 else "")
            ans = QMessageBox.question(self, "Continue?", shown + "\n\nContinue anyway?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return

        self.estimator.cancel_all()
        self._est_timer.stop()
        for r, _job in jobs:
            self.model.update_item(r, status=ItemStatus.QUEUED, progress=0, message="", output_path=None)
        self._total_jobs = len(jobs)
        self._done_jobs = 0
        self.overall_bar.setRange(0, self._total_jobs)
        self.overall_bar.setValue(0)
        self.model.set_locked(True)
        self._set_running_ui(True)
        self._save_settings()

        self.runner = JobRunner(ffmpeg, self._converter, jobs, concurrency=self.settings.concurrency, parent=self)
        self.runner.job_started.connect(self._job_started)
        self.runner.job_progress.connect(self._job_progress)
        self.runner.job_finished.connect(self._job_finished)
        self.runner.all_finished.connect(self._all_finished)
        self.runner.log.connect(self.log.append)
        self.log.append(f"Starting {len(jobs)} conversion(s) with {self.settings.concurrency} parallel process(es).")
        self.runner.start()

    def cancel_conversion(self) -> None:
        if self.runner is not None:
            self.log.append("Canceling…")
            self.runner.cancel()
            self.cancel_btn.setEnabled(False)

    def _set_running_ui(self, running: bool) -> None:
        self.convert_btn.setEnabled(not running and getattr(self, "_ffmpeg_ok", False))
        self.cancel_btn.setEnabled(running)
        for a in (self.act_add_files, self.act_add_folder, self.act_remove, self.act_clear,
                  self.act_check_all, self.act_uncheck_all, self.act_invert):
            a.setEnabled(not running and getattr(self, "_ffmpeg_ok", False) if a in (self.act_add_files, self.act_add_folder) else not running)
        self.format_combo.setEnabled(not running)
        if self._options_panel is not None:
            self._options_panel.setEnabled(not running)
        self.range_panel.setEnabled(not running)
        self.output_panel.setEnabled(not running)

    def _job_started(self, row: int) -> None:
        self.model.update_item(row, status=ItemStatus.RUNNING, progress=0)

    def _job_progress(self, row: int, pct: int) -> None:
        self.model.update_item(row, progress=pct)

    def _job_finished(self, row: int, res: ConvertResult) -> None:
        name = res.job.item.path.name
        if res.canceled:
            self.model.update_item(row, status=ItemStatus.CANCELED, message="Canceled", progress=0)
            self.log.append(f"[{name}] Canceled.")
        elif res.ok:
            self.model.update_item(row, status=ItemStatus.DONE, progress=100,
                                   message=human_size(res.output_size), output_path=res.job.output_path)
            est = res.job.item.est_size
            extra = ""
            if est:
                diff = (res.output_size - est) / est * 100.0
                extra = f", estimate was {human_size(est)} ({diff:+.0f}%)"
            note = f" — {res.message}" if res.message and res.message != human_size(res.output_size) else ""
            self.log.append_ok(f"[{name}] -> {res.job.output_path.name} ({human_size(res.output_size)}, "
                               f"{res.elapsed:.1f} s, {res.attempts} attempt{'s' if res.attempts != 1 else ''}{extra}){note}")
        else:
            self.model.update_item(row, status=ItemStatus.FAILED, message=res.error or "Failed", progress=0)
            self.log.append_error(f"[{name}] Failed: {res.error.splitlines()[-1] if res.error else 'unknown error'}")
        self._done_jobs += 1
        self.overall_bar.setValue(self._done_jobs)

    def _all_finished(self, ok: int, failed: int, canceled: int) -> None:
        self.log.append(f"Finished: {ok} ok, {failed} failed, {canceled} canceled.")
        if self.runner is not None:
            self.runner.wait(2000)
            self.runner.deleteLater()
            self.runner = None
        self.model.set_locked(False)
        self._set_running_ui(False)
        self._update_total_label()

    # ================================================================== 다이얼로그
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            if self._options_panel is not None and hasattr(self._options_panel, "set_hwaccel"):
                self._options_panel.set_hwaccel(self.settings.hwaccel)  # type: ignore[attr-defined]
            self.log.append(f"Settings saved: {self.settings.concurrency} parallel, hwaccel={self.settings.hwaccel}, "
                            f"sample estimates {'on' if self.settings.estimate_enabled else 'off'}.")
            self._schedule_estimates()

    def open_dependencies(self, auto_install: bool = False) -> None:
        if self._dep_dialog is None:
            self._dep_dialog = DependencyDialog(self, auto_install=auto_install)
            self._dep_dialog.dependencies_changed.connect(self._dependencies_changed)
            self._dep_dialog.finished.connect(self._dep_dialog_closed)
        self._dep_dialog.show()
        self._dep_dialog.raise_()
        self._dep_dialog.activateWindow()

    def _dep_dialog_closed(self, _result: int) -> None:
        if self._dep_dialog is not None:
            self._dep_dialog.deleteLater()
            self._dep_dialog = None

    def show_ffmpeg_info(self) -> None:
        ff = ffmpeg_locator.find_ffmpeg()
        fp = ffmpeg_locator.find_ffprobe()
        text = (f"ffmpeg: {ff or 'not found'}\n{ffmpeg_locator.ffmpeg_version(ff) if ff else ''}\n\n"
                f"ffprobe: {fp or 'not found'}\n\nbin folder: {ffmpeg_locator.bin_dir()}")
        QMessageBox.information(self, "ffmpeg Info", text)

    def show_about(self) -> None:
        QMessageBox.about(self, "About",
                          f"{APP_NAME} v{VERSION}\n\nBulk video to GIF converter.\nPython + PySide6 + ffmpeg.\n\n"
                          "Author: Ji Hun Park")

    # ================================================================== 종료
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.runner is not None:
            ans = QMessageBox.question(self, "Conversion running", "Conversion is running. Cancel and exit?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.runner.cancel()
            self.runner.wait(5000)
        self.probe_loader.cancel_all()
        self.thumb_loader.cancel_all()
        self.estimator.cleanup()
        self._save_settings()
        super().closeEvent(event)
