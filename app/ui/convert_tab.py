# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-26
"""Convert 탭 (PLAN_DRAW_TAB 3장). v0.2.x 의 MainWindow 본문을 그대로 옮긴 것 — 동작 · 단축키 · 설정 키는 같다."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSplitter, QToolBar, QVBoxLayout, QWidget)

from ..config import constants as C
from ..config.settings import AppSettings
from ..core import ffmpeg_locator, image_sequence
from ..core.converters import registry
from ..core.converters.base import BaseConverter
from ..core.job_runner import JobRunner
from ..core.models import ConvertJob, ConvertOptions, ConvertResult, FrameRange, ItemStatus, MediaInfo
from ..core.size_estimator import make_est_key
from ..core.thumbnail import representative_time
from ..core.utils import human_size, make_output_path, normcase_path
from .icons import icon, pixmap
from .widgets import gif_options_panel, mp4_options_panel, wav_options_panel  # noqa: F401  (팩토리 등록)
from .widgets.frame_range_panel import FrameRangePanel
from .widgets.loaders import ProbeLoader, SizeEstimator, ThumbnailLoader
from .widgets.log_panel import LogPanel
from .widgets.options_panel_base import BaseOptionsPanel, OptionsPanelFactory
from .widgets.output_panel import OutputPanel
from .widgets.video_list_model import VideoListModel
from .widgets.video_list_view import VideoListView

def _filter(label: str, exts: frozenset[str]) -> str:
    return f"{label} (" + " ".join(f"*{e}" for e in sorted(exts)) + ")"


MEDIA_FILTER = ";;".join((_filter("Media files", C.SUPPORTED_EXTENSIONS), _filter("Video files", C.VIDEO_EXTENSIONS),
                          _filter("Audio files", C.AUDIO_EXTENSIONS), _filter("Image sequences", C.IMAGE_EXTENSIONS),
                          "All files (*.*)"))
VIDEO_FILTER = ";;".join((_filter("Video files", C.DRAW_EXTENSIONS), _filter("Image sequences", C.IMAGE_EXTENSIONS),
                          "All files (*.*)"))


class ConvertTab(QWidget):
    view_mode_changed = Signal(str)     # 탭 툴바에서 보기 모드를 바꿨을 때 (MainWindow View 메뉴 동기화)
    title_changed = Signal()

    def __init__(self, settings: AppSettings, thumb_loader: ThumbnailLoader, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.thumb_loader = thumb_loader
        self.model = VideoListModel(self)
        self.probe_loader = ProbeLoader(self)
        self.estimator = SizeEstimator(ffmpeg_locator.find_ffmpeg, self)
        self.runner: JobRunner | None = None
        self._thumb_keys: dict[str, Path] = {}
        self._options_panel: BaseOptionsPanel | None = None
        self._converter: BaseConverter = registry.all()[0]
        self._total_jobs = 0
        self._done_jobs = 0
        self._ffmpeg_ok = False
        self._active = True
        # _build_ui 중에도 _schedule_estimates 가 호출될 수 있으므로 타이머는 가장 먼저 만든다
        self._est_timer = QTimer(self)
        self._est_timer.setSingleShot(True)
        self._est_timer.setInterval(C.ESTIMATE_DEBOUNCE_MS)
        self._est_timer.timeout.connect(self._run_estimates)

        self._build_actions()
        self._build_ui()
        self._connect()
        self._update_actions()

    # ================================================================== UI 구성
    def _build_actions(self) -> None:
        self.act_add_files = QAction(icon("add_files"), "Add Files", self)
        self.act_add_folder = QAction(icon("add_folder"), "Add Folder", self)
        self.act_remove = QAction(icon("remove"), "Remove Selected", self)
        self.act_remove.setIconText("Remove")
        self.act_clear = QAction(icon("clear"), "Clear List", self)
        self.act_clear.setIconText("Clear")
        self.act_check_all = QAction(icon("check_all"), "Check All", self)
        self.act_uncheck_all = QAction(icon("uncheck_all"), "Uncheck All", self)
        self.act_invert = QAction(icon("invert"), "Invert Check", self)
        self.act_invert.setIconText("Invert")
        self.act_view_list = QAction(icon("view_list"), "List", self)
        self.act_view_thumbs = QAction(icon("view_thumbs"), "Thumbnails", self)
        for a in (self.act_view_list, self.act_view_thumbs):
            a.setCheckable(True)
        self.act_view_list.setChecked(True)
        grp = QActionGroup(self)
        grp.setExclusive(True)
        grp.addAction(self.act_view_list)
        grp.addAction(self.act_view_thumbs)
        self.act_refresh_est = QAction(icon("refresh"), "Refresh Estimates", self)

        self.act_check_all.setShortcut(QKeySequence("Ctrl+A"))
        self.act_uncheck_all.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self.act_invert.setShortcut(QKeySequence("Ctrl+I"))
        self.act_refresh_est.setShortcut(QKeySequence("F5"))
        self.act_remove.setShortcut(QKeySequence("Del"))
        # Del 은 Draw 탭에도 있으므로 이 탭 안에 포커스가 있을 때만 작동시킨다 (5.8)
        self.act_remove.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        for a in (self.act_check_all, self.act_uncheck_all, self.act_invert, self.act_refresh_est, self.act_remove):
            self.addAction(a)

    def _build_ui(self) -> None:
        # --- 툴바 (탭 안) ---
        tb = QToolBar("Convert")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for a in (self.act_add_files, self.act_add_folder, self.act_remove, self.act_clear):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_check_all, self.act_uncheck_all, self.act_invert):
            tb.addAction(a)
        tb.addSeparator()
        tb.addWidget(QLabel("View: "))
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

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(tb)
        lay.addWidget(self.v_splitter, 1)

        self._set_format(self.format_combo.currentData())

    def _connect(self) -> None:
        self.act_add_files.triggered.connect(self.add_files)
        self.act_add_folder.triggered.connect(self.add_folder)
        self.act_remove.triggered.connect(lambda: self.remove_rows(self.view.selected_rows()))
        self.act_clear.triggered.connect(self.clear_list)
        self.act_check_all.triggered.connect(lambda: self.model.set_all_checked(True))
        self.act_uncheck_all.triggered.connect(lambda: self.model.set_all_checked(False))
        self.act_invert.triggered.connect(self.model.invert_checked)
        self.act_view_list.triggered.connect(lambda: self._view_action("list"))
        self.act_view_thumbs.triggered.connect(lambda: self._view_action("thumbs"))
        self.act_refresh_est.triggered.connect(self._run_estimates)

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

    # ================================================================== 탭 공통 인터페이스 (3.3)
    def menu_actions(self) -> list[QAction | None]:
        return [self.act_check_all, self.act_uncheck_all, self.act_invert, None,
                self.act_remove, self.act_clear, None, self.act_refresh_est]

    def log_panel(self) -> LogPanel:
        return self.log

    def title_suffix(self) -> str:
        return ""

    def set_active(self, active: bool) -> None:
        """활성 탭일 때만 메뉴 · 단축키가 동작한다 (5.8)."""
        self._active = active
        self._update_actions()

    def view_mode(self) -> str:
        return self.view.view_mode()

    def set_view_mode(self, mode: str) -> None:
        (self.act_view_thumbs if mode == "thumbs" else self.act_view_list).setChecked(True)
        self.view.set_view_mode(mode)

    def _view_action(self, mode: str) -> None:
        self.set_view_mode(mode)
        self.view_mode_changed.emit(mode)

    def set_ffmpeg_available(self, ok: bool) -> None:
        self._ffmpeg_ok = ok
        self.view.setAcceptDrops(ok)
        self._update_actions()

    def reprobe_missing(self) -> None:
        for it in self.model.items():
            if it.info is None:
                self.probe_loader.request(it.path)

    def on_settings_changed(self) -> None:
        if self._options_panel is not None and hasattr(self._options_panel, "set_hwaccel"):
            self._options_panel.set_hwaccel(self.settings.hwaccel)  # type: ignore[attr-defined]
        self.log.append(f"Settings saved: {self.settings.concurrency} parallel, hwaccel={self.settings.hwaccel}, "
                        f"sample estimates {'on' if self.settings.estimate_enabled else 'off'}, "
                        f"image sequences at {self.settings.sequence_fps:g} fps.")
        self._schedule_estimates()

    def request_close(self) -> bool:
        if self.runner is None:
            return True
        ans = QMessageBox.question(self, "Conversion running", "Conversion is running. Cancel and exit?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return ans == QMessageBox.StandardButton.Yes

    def shutdown(self) -> None:
        if self.runner is not None:
            self.runner.cancel()
            self.runner.wait(5000)
        self.probe_loader.cancel_all()
        self.estimator.cleanup()

    def _update_actions(self) -> None:
        running = self.runner is not None
        can_edit = self._active and not running
        self.act_add_files.setEnabled(can_edit and self._ffmpeg_ok)
        self.act_add_folder.setEnabled(can_edit and self._ffmpeg_ok)
        for a in (self.act_remove, self.act_clear, self.act_check_all, self.act_uncheck_all, self.act_invert):
            a.setEnabled(can_edit)
        self.act_refresh_est.setEnabled(self._active)
        self.act_view_list.setEnabled(self._active)
        self.act_view_thumbs.setEnabled(self._active)
        self.convert_btn.setEnabled(not running and self._ffmpeg_ok)
        self.cancel_btn.setEnabled(running)

    # ================================================================== 설정 복원 · 저장
    def restore_settings(self) -> None:
        for key, sp in (("ui/splitter_h", self.h_splitter), ("ui/splitter_v", self.v_splitter)):
            st = self.settings.get(key)
            if isinstance(st, QByteArray) and not st.isEmpty():
                sp.restoreState(st)
        self.set_view_mode(str(self.settings.get("ui/view_mode", "list", str)))
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

    def save_settings(self) -> None:
        s = self.settings
        s.set("ui/splitter_h", self.h_splitter.saveState())
        s.set("ui/splitter_v", self.v_splitter.saveState())
        s.set("ui/view_mode", self.view.view_mode())
        s.set("format/current", self._converter.format_id)
        st = self.output_panel.state()
        s.set("io/output_mode", st["mode"])
        s.last_output_dir = st["dir"]
        s.set("io/suffix", st["suffix"])
        s.set("io/overwrite", st["overwrite"])
        if self._options_panel is not None:
            s.save_options(self._options_panel.get_options())

    # ================================================================== 포맷 · 옵션 패널
    def _set_format(self, format_id: str) -> None:
        if not format_id or not OptionsPanelFactory.has(format_id):
            return
        if self._options_panel is not None:
            # 떠나는 포맷의 옵션은 보관해 두었다가 다시 돌아오면 복원한다
            self.settings.save_options(self._options_panel.get_options())
            self._options_slot.removeWidget(self._options_panel)
            self._options_panel.hide()       # deleteLater 는 이벤트 루프로 돌아가야 지운다 — 그 사이 겹쳐 그려지지 않게
            self._options_panel.deleteLater()
            self._options_panel = None
        self._converter = registry.get(format_id)
        panel = OptionsPanelFactory.create(format_id)
        self._options_slot.addWidget(panel)
        self._options_panel = panel
        if hasattr(panel, "set_hwaccel"):
            panel.set_hwaccel(self.settings.hwaccel)  # type: ignore[attr-defined]
        panel.set_options(self.settings.load_options(self._converter))
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
        if not self.act_add_files.isEnabled():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Add media files", self.settings.last_input_dir, MEDIA_FILTER)
        if files:
            self.settings.last_input_dir = str(Path(files[0]).parent)
            self.add_paths([Path(f) for f in files])

    def add_folder(self) -> None:
        if not self.act_add_folder.isEnabled():
            return
        d = QFileDialog.getExistingDirectory(self, "Add all media files in folder", self.settings.last_input_dir)
        if d:
            self.settings.last_input_dir = d
            self.add_paths(sorted(p for p in Path(d).iterdir() if p.is_file()))

    def add_paths(self, paths: list[Path]) -> None:
        if not self._ffmpeg_ok:
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
        if info.audio_only:
            # 음성 파일은 뽑을 화면이 없다 → 스피커 아이콘
            self.model.set_thumbnail(row, pixmap("volume", 64))
        else:
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
        self.log.append_error(f"[{image_sequence.display_name(path)}] Probe failed: {error}")
        if self.view.currentIndex().row() == row:
            self._current_changed(row)

    def _thumb_ready(self, key: str, img: QImage) -> None:
        # 썸네일 로더는 Draw 탭과 공유하므로 내가 요청한 키만 받는다
        path = self._thumb_keys.pop(key, None)
        if path is None:
            return
        row = self.model.row_of(path)
        if row >= 0:
            self.model.set_thumbnail(row, QPixmap.fromImage(img))

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
            if self._converter.skip_reason(it) is not None:
                # 이 포맷으로는 변환하지 않는 항목 (영상 포맷의 음성 파일 · WAV 의 무음 영상)
                self.model.update_item(r, est_key=key)
                self.model.set_estimate(r, key, None, "none")
                continue
            if it.est_key == key and it.est_level in ("sampled", "exact"):
                continue
            if it.est_key and it.est_key != key and it.status in (ItemStatus.DONE, ItemStatus.FAILED,
                                                                   ItemStatus.CANCELED, ItemStatus.SKIPPED):
                # 변환 뒤 옵션·포맷·구간이 바뀌면 이전 결과 표시를 지우고 새 추정을 보여 준다
                self.model.update_item(r, status=ItemStatus.IDLE, progress=0, message="", output_path=None)
            heuristic = self._converter.heuristic_size(it, options)
            level = self._converter.heuristic_level() if heuristic is not None else "none"
            self.model.update_item(r, est_key=key)
            self.model.set_estimate(r, key, heuristic, level)
            if use_samples and level == "heuristic":
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
            self.log.append(f"[{image_sequence.display_name(it.path)}] Size estimate failed: {error}")

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
            if it.info is None or it.status == ItemStatus.DONE or self._converter.skip_reason(it) is not None:
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
        if problems:
            QMessageBox.warning(self, "Invalid options", "\n".join(problems))
            return
        rows = self.model.checked_rows()
        if not rows:
            QMessageBox.information(self, "Nothing to convert", "Check at least one file.")
            return

        jobs: list[tuple[int, ConvertJob]] = []
        warnings: list[str] = []
        # 이 배치의 원본들과 이미 배정한 출력 — 이름이 겹치는 원본(voice.mp3 · voice.ogg)끼리, 또는 다른 원본
        # (voice.mp3 → voice.wav 가 원본 voice.wav) 을 덮어쓰지 않게 한다
        taken = {normcase_path(self.model.item(r).path) for r in rows}
        for r in rows:
            it = self.model.item(r)
            if it.info is None:
                self.model.update_item(r, status=ItemStatus.SKIPPED, message=it.probe_error or "No media info")
                self.log.append(f"[{image_sequence.display_name(it.path)}] Skipped: {it.probe_error or 'not probed yet'}")
                continue
            reason = self._converter.skip_reason(it)
            if reason is not None:
                self.model.update_item(r, status=ItemStatus.SKIPPED, message=reason[:1].upper() + reason[1:])
                self.log.append(f"[{image_sequence.display_name(it.path)}] Skipped for "
                                f"{self._converter.display_name}: {reason}.")
                continue
            out = make_output_path(it.path, options.output_dir, options.suffix, self._converter.extension,
                                   options.overwrite, taken)
            if len(str(out)) > C.MAX_OUTPUT_PATH_LEN:
                warnings.append(f"{image_sequence.display_name(it.path)}: output path is too long for Windows "
                                f"(>{C.MAX_OUTPUT_PATH_LEN} chars).")
            w = self._converter.estimate_warning(it, options)
            if w:
                warnings.append(f"{image_sequence.display_name(it.path)}: {w}")
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
        self.save_settings()
        self.settings.sync()

        self.runner = JobRunner(ffmpeg, self._converter, jobs, concurrency=self.settings.concurrency, parent=self)
        self.runner.job_started.connect(self._job_started)
        self.runner.job_progress.connect(self._job_progress)
        self.runner.job_finished.connect(self._job_finished)
        self.runner.all_finished.connect(self._all_finished)
        self.runner.log.connect(self.log.append)
        self._set_running_ui(True)
        self.log.append(f"Starting {len(jobs)} conversion(s) with {self.settings.concurrency} parallel process(es).")
        self.runner.start()

    def cancel_conversion(self) -> None:
        if self.runner is not None:
            self.log.append("Canceling…")
            self.runner.cancel()
            self.cancel_btn.setEnabled(False)

    def _set_running_ui(self, running: bool) -> None:
        self._update_actions()
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
        name = image_sequence.display_name(res.job.item.path)
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
            if res.check_message:
                (self.log.append_error if res.check_level == "warn" else self.log.append)(
                    f"[{res.job.output_path.name}] {res.check_message}")
        elif res.check_level == "error":
            # 변환은 됐지만 출력 검사(JUN_JALI 규칙)에 걸림 — 파일은 남긴다
            self.model.update_item(row, status=ItemStatus.FAILED, message=res.check_message, progress=0,
                                   output_path=res.job.output_path)
            self.log.append_error(f"[{name}] -> {res.job.output_path.name} written, but {res.check_message}")
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
