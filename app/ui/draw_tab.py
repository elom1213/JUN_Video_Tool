# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""Draw 탭 (PLAN_DRAW_TAB 5장, 13장).

영상을 리스트업해 고르고, 프레임 단위로 재생 · 정지 · 이동하면서 멈춘 프레임 위에 선을 그린다.
앞뒤 프레임의 선은 고스트로 겹쳐 보이고, 그림은 영상 옆 사이드카 `<영상이름>.draw.json` 으로 저장 · 자동 로드된다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QItemSelectionModel, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QIcon, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox, QSplitter, QToolBar, QVBoxLayout,
                               QWidget)

from ..config import constants as C
from ..config.settings import AppSettings
from ..core.drawing import DrawingDocument, DrawingFormatError, Stroke, legacy_sidecar_path, sidecar_path
from ..core.frame_decoder import normalize_scale
from ..core.memory_info import format_gib, full_cache_budget, plan_cache_range, reserve_bytes, system_memory
from ..core.models import MediaInfo, VideoItem
from ..core.thumbnail import representative_time
from ..core.utils import human_size
from .convert_tab import VIDEO_FILTER
from .icons import icon
from .widgets.draw.audio_player import AudioPlayer
from .widgets.draw.brush_panel import BrushPanel
from .widgets.draw.cache_panel import CachePanel
from .widgets.draw.export_dialog import ExportDialog
from .widgets.draw.frame_provider import FrameProvider
from .widgets.draw.ghost_panel import GhostPanel
from .widgets.draw.playback_controller import PlaybackController
from .widgets.draw.transport_bar import TransportBar
from .widgets.draw.video_canvas import VideoCanvas
from .widgets.loaders import ProbeLoader, ThumbnailLoader
from .widgets.log_panel import LogPanel
from .widgets.video_list_model import VideoListModel
from .widgets.video_list_view import VideoListView

_DRAWING_FILTER = f"Drawing (*{C.DRAW_FILE_SUFFIX});;JSON (*.json);;All files (*.*)"


def _doc_summary(doc: DrawingDocument) -> str:
    n_frames = len(doc.frames_with_strokes())
    n = doc.stroke_count()
    return f"{n_frames} frame{'s' if n_frames != 1 else ''}, {n} stroke{'s' if n != 1 else ''}"


class DrawTab(QWidget):
    view_mode_changed = Signal(str)
    title_changed = Signal()

    def __init__(self, settings: AppSettings, thumb_loader: ThumbnailLoader, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.thumb_loader = thumb_loader
        self.model = VideoListModel(self, checkable=False, show_status=False, extensions=C.DRAW_EXTENSIONS)
        self.probe_loader = ProbeLoader(self)
        self.provider = FrameProvider(self)
        self.audio = AudioPlayer(self)
        self.controller = PlaybackController(self.provider, self.audio, self)
        self.doc: DrawingDocument | None = None
        self._doc_path: Path | None = None     # Save As / Load 로 정한 저장 경로 (없으면 사이드카)
        self._row = -1                         # 캔버스에 올라간 행
        self._thumb_keys: dict[str, Path] = {}
        self._ffmpeg_ok = False
        self._active = False
        self._scrub_base = 0
        self._last_error = ""
        self._reverting = False
        self._decode_scale = C.DRAW_DECODE_SCALE_DEFAULT   # 디코드 해상도 (원본의 %)

        self._build_actions()
        self._build_ui()
        self._connect()
        self.provider.start()
        self._update_actions()

    # ================================================================== UI 구성
    def _act(self, icon_name: str | None, text: str, shortcut: str | None = None, slot=None,
             icon_text: str | None = None) -> QAction:
        a = QAction(icon(icon_name) if icon_name else QIcon(), text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        if icon_text:
            a.setIconText(icon_text)
        # Draw 탭 안에 포커스가 있을 때만 단축키가 작동한다 (2.4)
        a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        if slot is not None:
            a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_actions(self) -> None:
        c = self.controller
        self.act_add_files = self._act("add_files", "Add Files", slot=self.add_files)
        self.act_add_folder = self._act("add_folder", "Add Folder", slot=self.add_folder)
        self.act_remove = self._act("remove", "Remove Selected", "Del",
                                    lambda: self.remove_rows(self.view.selected_rows()), icon_text="Remove")
        self.act_clear_list = self._act("clear", "Clear List", slot=self.clear_list, icon_text="Clear")
        self.act_view_list = self._act("view_list", "List", slot=lambda: self._view_action("list"))
        self.act_view_thumbs = self._act("view_thumbs", "Thumbnails", slot=lambda: self._view_action("thumbs"))
        vg = QActionGroup(self)
        for a in (self.act_view_list, self.act_view_thumbs):
            a.setCheckable(True)
            vg.addAction(a)
        self.act_view_list.setChecked(True)

        self.act_play = self._act("play", "Play/Pause", "Space", c.toggle)
        self.act_prev = self._act("prev_frame", "Previous Frame", "Left", lambda: c.step(-1))
        self.act_next = self._act("next_frame", "Next Frame", "Right", lambda: c.step(1))
        self.act_back10 = self._act(None, "Back 10 Frames", "Shift+Left", lambda: c.step(-10))
        self.act_fwd10 = self._act(None, "Forward 10 Frames", "Shift+Right", lambda: c.step(10))
        self.act_first = self._act("first_frame", "First Frame", "Home", c.first)
        self.act_last = self._act("last_frame", "Last Frame", "End", c.last)
        self.act_prev_drawn = self._act("prev_drawn", "Previous Drawn Frame", "Ctrl+Left",
                                        lambda: self.snap_drawn(-1))
        self.act_next_drawn = self._act("next_drawn", "Next Drawn Frame", "Ctrl+Right",
                                        lambda: self.snap_drawn(1))

        self.act_tool_draw = self._act("brush", "Draw Tool", "D", lambda: self._set_tool("draw"), icon_text="Draw")
        self.act_tool_erase = self._act("eraser", "Erase Tool", "E", lambda: self._set_tool("erase"),
                                        icon_text="Erase")
        tg = QActionGroup(self)
        for a in (self.act_tool_draw, self.act_tool_erase):
            a.setCheckable(True)
            tg.addAction(a)
        self.act_tool_draw.setChecked(True)
        self.act_ghost = self._act(None, "Toggle Ghosting", "G", lambda: self.ghost_panel.toggle())

        self.act_undo = self._act("undo", "Undo", "Ctrl+Z", self.undo)
        self.act_redo = self._act("redo", "Redo", "Ctrl+Y", self.redo)
        self.act_clear_frame = self._act("clear_frame", "Clear Frame", "Shift+Del", self.clear_frame)
        self.act_clear_all = self._act(None, "Clear All Drawings", slot=self.clear_all)

        self.act_save = self._act("save", "Save Drawing", "Ctrl+S", self.save, icon_text="Save")
        self.act_save_as = self._act("save_as", "Save Drawing As…", "Ctrl+Shift+S", self.save_as,
                                     icon_text="Save As…")
        self.act_load = self._act("folder", "Load Drawing…", "Ctrl+L", self.load, icon_text="Load…")
        self.act_export = self._act("export", "Export with Drawing…", "Ctrl+E", self.export, icon_text="Export…")
        self.act_cache_whole = self._act(None, "Cache Whole Video", slot=self.cache_whole_video)
        self.act_free_cache = self._act(None, "Free All Frame Cache", slot=self.free_all_cache)

    def _build_ui(self) -> None:
        # --- 툴바 ---
        tb = QToolBar("Draw")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for a in (self.act_add_files, self.act_add_folder, self.act_remove, self.act_clear_list):
            tb.addAction(a)
        tb.addSeparator()
        tb.addWidget(QLabel("View: "))
        tb.addAction(self.act_view_list)
        tb.addAction(self.act_view_thumbs)
        tb.addSeparator()
        tb.addWidget(QLabel("Tool: "))
        tb.addAction(self.act_tool_draw)
        tb.addAction(self.act_tool_erase)
        tb.addSeparator()
        for a in (self.act_save, self.act_save_as, self.act_load):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_export)
        tb.addSeparator()
        self.autosave_check = QCheckBox("Auto-save on switch")
        self.autosave_check.setToolTip("Save the drawing next to the video without asking when switching videos or exiting.")
        self.autosave_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tb.addWidget(self.autosave_check)
        # 1280 px 폭에 툴바가 다 들어가도록 일부는 아이콘만 보인다 (툴팁 · 메뉴에 이름이 있다)
        for a in (self.act_remove, self.act_clear_list, self.act_view_list, self.act_view_thumbs):
            btn = tb.widgetForAction(a)
            if btn is not None:
                btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                btn.setToolTip(a.text())
        for btn in tb.findChildren(QWidget):
            if btn.metaObject().className() == "QToolButton":
                btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # --- 좌: 리스트 ---
        self.view = VideoListView(context_actions="draw")
        self.view.setModel(self.model)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        # --- 중: 캔버스 ---
        self.canvas = VideoCanvas()
        self.canvas.clear("Add videos and select one to start drawing.")

        # --- 우: 사이드 패널 ---
        side_body = QWidget()
        sv = QVBoxLayout(side_body)
        sv.setContentsMargins(6, 6, 6, 6)
        sv.setSpacing(6)
        self.brush_panel = BrushPanel()
        self.ghost_panel = GhostPanel()
        sv.addWidget(self.brush_panel)
        sv.addWidget(self.ghost_panel)
        scrub_box = QGroupBox("Scrub")
        sl = QHBoxLayout(scrub_box)
        sl.setContentsMargins(8, 12, 8, 8)
        sl.addWidget(QLabel("Middle-drag sensitivity"))
        self.scrub_spin = QSpinBox()
        self.scrub_spin.setRange(C.DRAW_SCRUB_PX_MIN, C.DRAW_SCRUB_PX_MAX)
        self.scrub_spin.setValue(C.DRAW_SCRUB_PX_PER_FRAME)
        self.scrub_spin.setSuffix(" px/frame")
        sl.addWidget(self.scrub_spin)
        sv.addWidget(scrub_box)
        self.cache_panel = CachePanel()
        sv.addWidget(self.cache_panel)
        brow = QHBoxLayout()
        self.undo_btn = QPushButton(icon("undo"), "Undo")
        self.redo_btn = QPushButton(icon("redo"), "Redo")
        brow.addWidget(self.undo_btn)
        brow.addWidget(self.redo_btn)
        sv.addLayout(brow)
        self.clear_frame_btn = QPushButton(icon("clear_frame"), "Clear Frame")
        sv.addWidget(self.clear_frame_btn)
        sv.addStretch(1)
        for b in (self.undo_btn, self.redo_btn, self.clear_frame_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        side = QScrollArea()
        side.setWidgetResizable(True)
        side.setFrameShape(QScrollArea.Shape.NoFrame)
        side.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side.setWidget(side_body)
        side.setMinimumWidth(230)

        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.h_splitter.addWidget(self.view)
        self.h_splitter.addWidget(self.canvas)
        self.h_splitter.addWidget(side)
        self.h_splitter.setStretchFactor(0, 0)
        self.h_splitter.setStretchFactor(1, 1)
        self.h_splitter.setStretchFactor(2, 0)
        self.h_splitter.setSizes([260, 760, 260])

        # --- 하단: 트랜스포트 + 로그 ---
        self.transport = TransportBar(self.controller)
        self.log = LogPanel()
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(6, 4, 6, 6)
        bv.setSpacing(4)
        bv.addWidget(self.transport)
        bv.addWidget(self.log, 1)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.addWidget(self.h_splitter)
        self.v_splitter.addWidget(bottom)
        self.v_splitter.setStretchFactor(0, 5)
        self.v_splitter.setStretchFactor(1, 1)
        self.v_splitter.setSizes([600, 140])

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(tb)
        lay.addWidget(self.v_splitter, 1)

    def _connect(self) -> None:
        self.view.files_dropped.connect(self.add_paths)
        self.view.remove_requested.connect(self.remove_rows)
        self.view.open_folder_requested.connect(self._open_folder)
        self.view.load_drawing_requested.connect(self._load_for_row)
        self.view.show_drawing_file_requested.connect(self._show_drawing_file)
        self.view.selectionModel().currentChanged.connect(lambda cur, prev: self._current_changed(cur.row(), prev.row()))
        self.model.rows_added.connect(self._rows_added)
        self.probe_loader.probe_ready.connect(self._probe_ready)
        self.probe_loader.probe_failed.connect(self._probe_failed)
        self.thumb_loader.thumbnail_ready.connect(self._thumb_ready)

        c = self.controller
        c.frame_changed.connect(self._frame_changed)
        c.image_ready.connect(self.canvas.set_frame)
        c.loading_changed.connect(self.canvas.set_loading)
        c.playing_changed.connect(self._playing_changed)
        c.range_changed.connect(self._range_changed)
        self.provider.decode_error.connect(self._decode_error)
        self.provider.info.connect(lambda gen, msg: self.log.append(msg) if gen == c.video_gen() else None)
        self.audio.log.connect(self.log.append)
        p = self.provider
        p.fill_progress.connect(lambda name, done, total: self.cache_panel.set_progress(done, total))
        p.fill_finished.connect(self._fill_finished)
        p.fill_log.connect(self.log.append)
        p.cache_changed.connect(self._refresh_cache_ui)
        self.cache_panel.cache_clicked.connect(self.cache_whole_video)
        self.cache_panel.free_clicked.connect(self.free_all_cache)
        self.cache_panel.scale_changed.connect(self.set_decode_scale)

        cv = self.canvas
        cv.stroke_finished.connect(self._stroke_finished)
        cv.erase_finished.connect(self._erase_finished)
        cv.scrub_started.connect(self._scrub_started)
        cv.scrub_delta.connect(lambda d: c.seek(self._scrub_base + d))
        cv.draw_pressed_while_playing.connect(c.pause)
        self.brush_panel.brush_changed.connect(cv.set_brush)
        self.brush_panel.eraser_changed.connect(cv.set_eraser_size)
        self.ghost_panel.ghost_changed.connect(cv.set_ghost)
        self.scrub_spin.valueChanged.connect(cv.set_scrub_sensitivity)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        self.clear_frame_btn.clicked.connect(self.clear_frame)
        self.transport.volume_changed.connect(self.audio.set_volume)
        self.transport.muted_changed.connect(self.audio.set_muted)
        self.transport.prev_drawn_clicked.connect(lambda: self.snap_drawn(-1))
        self.transport.next_drawn_clicked.connect(lambda: self.snap_drawn(1))

    # ================================================================== 탭 공통 인터페이스 (3.3)
    def menu_actions(self) -> list[QAction | None]:
        return [self.act_play, self.act_prev, self.act_next, self.act_back10, self.act_fwd10, self.act_first,
                self.act_last, self.act_prev_drawn, self.act_next_drawn, None,
                self.act_tool_draw, self.act_tool_erase, self.act_ghost, None,
                self.act_undo, self.act_redo, self.act_clear_frame, self.act_clear_all, None,
                self.act_save, self.act_save_as, self.act_load, self.act_export, None,
                self.act_cache_whole, self.act_free_cache, None,
                self.act_remove, self.act_clear_list]

    def log_panel(self) -> LogPanel:
        return self.log

    def title_suffix(self) -> str:
        item = self.controller.item()
        if item is None:
            return ""
        return item.path.name + ("*" if self.doc is not None and self.doc.dirty else "")

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self.controller.pause()
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

    def request_close(self) -> bool:
        return self._maybe_save()

    def shutdown(self) -> None:
        self.controller.pause()
        self.audio.shutdown()
        self.provider.shutdown()
        self.probe_loader.cancel_all()

    def restore_settings(self) -> None:
        s = self.settings
        for key, sp in (("draw/splitter_h", self.h_splitter), ("draw/splitter_v", self.v_splitter)):
            st = s.get(key)
            if isinstance(st, QByteArray) and not st.isEmpty():
                sp.restoreState(st)
        self.set_view_mode(str(s.get("draw/view_mode", "list", str)))
        self.brush_panel.set_state(str(s.get("draw/color", C.DRAW_COLOR_DEFAULT, str)),
                                   float(s.get("draw/width", C.DRAW_WIDTH_DEFAULT, float)),
                                   float(s.get("draw/eraser_size", C.DRAW_ERASER_DEFAULT, float)))
        self.ghost_panel.set_state(bool(s.get("draw/ghost_enabled", True, bool)),
                                   int(s.get("draw/ghost_before", C.GHOST_BEFORE_DEFAULT, int)),
                                   int(s.get("draw/ghost_after", C.GHOST_AFTER_DEFAULT, int)),
                                   float(s.get("draw/ghost_opacity", C.GHOST_OPACITY_DEFAULT, float)))
        self.scrub_spin.setValue(int(s.get("draw/scrub_px", C.DRAW_SCRUB_PX_PER_FRAME, int)))
        self.canvas.set_scrub_sensitivity(self.scrub_spin.value())
        tool = str(s.get("draw/tool", "draw", str))
        (self.act_tool_erase if tool == "erase" else self.act_tool_draw).setChecked(True)
        self._set_tool(tool)
        volume = int(s.get("draw/volume", C.DRAW_VOLUME_DEFAULT, int))
        muted = bool(s.get("draw/muted", False, bool))
        self.transport.set_audio_state(volume, muted)
        self.audio.set_volume(volume)
        self.audio.set_muted(muted)
        self.autosave_check.setChecked(bool(s.get("draw/autosave", False, bool)))
        # 영상이 아직 안 열렸을 때 불린다 — 이후 여는 영상부터 이 해상도로 디코드한다
        self._decode_scale = normalize_scale(s.get("draw/decode_scale", C.DRAW_DECODE_SCALE_DEFAULT, int))
        self.cache_panel.set_scale(self._decode_scale)

    def save_settings(self) -> None:
        s = self.settings
        s.set("draw/splitter_h", self.h_splitter.saveState())
        s.set("draw/splitter_v", self.v_splitter.saveState())
        s.set("draw/view_mode", self.view.view_mode())
        s.set("draw/color", self.brush_panel.color())
        s.set("draw/width", self.brush_panel.brush_width())
        s.set("draw/eraser_size", self.brush_panel.eraser_size())
        on, before, after, opacity = self.ghost_panel.state()
        s.set("draw/ghost_enabled", on)
        s.set("draw/ghost_before", before)
        s.set("draw/ghost_after", after)
        s.set("draw/ghost_opacity", opacity)
        s.set("draw/scrub_px", self.scrub_spin.value())
        s.set("draw/tool", "erase" if self.act_tool_erase.isChecked() else "draw")
        s.set("draw/volume", self.transport.volume.value())
        s.set("draw/muted", self.transport.btn_mute.isChecked())
        s.set("draw/autosave", self.autosave_check.isChecked())
        s.set("draw/decode_scale", self._decode_scale)

    def _update_actions(self) -> None:
        a = self._active
        has_video = self.controller.item() is not None and self.doc is not None
        frame = self.controller.frame()
        self.act_add_files.setEnabled(a and self._ffmpeg_ok)
        self.act_add_folder.setEnabled(a and self._ffmpeg_ok)
        for act in (self.act_remove, self.act_clear_list, self.act_view_list, self.act_view_thumbs,
                    self.act_tool_draw, self.act_tool_erase, self.act_ghost):
            act.setEnabled(a)
        for act in (self.act_play, self.act_prev, self.act_next, self.act_back10, self.act_fwd10, self.act_first,
                    self.act_last, self.act_save_as, self.act_load, self.act_export):
            act.setEnabled(a and has_video)
        doc = self.doc
        self.act_save.setEnabled(a and has_video)
        self.act_undo.setEnabled(a and has_video and doc is not None and doc.can_undo(frame))
        self.act_redo.setEnabled(a and has_video and doc is not None and doc.can_redo(frame))
        self.act_clear_frame.setEnabled(a and has_video and doc is not None and bool(doc.strokes_at(frame)))
        self.act_clear_all.setEnabled(a and has_video and doc is not None and not doc.is_empty())
        can_prev = has_video and doc is not None and doc.prev_drawn_frame(frame) is not None
        can_next = has_video and doc is not None and doc.next_drawn_frame(frame) is not None
        self.act_prev_drawn.setEnabled(a and can_prev)
        self.act_next_drawn.setEnabled(a and can_next)
        self.transport.set_snap_enabled(can_prev, can_next)
        self.undo_btn.setEnabled(self.act_undo.isEnabled())
        self.redo_btn.setEnabled(self.act_redo.isEnabled())
        self.clear_frame_btn.setEnabled(self.act_clear_frame.isEnabled())
        self.transport.setEnabled(has_video)
        filling = self.provider.filling_name()
        self.act_cache_whole.setEnabled(a and has_video)
        self.act_cache_whole.setText("Stop Caching" if filling is not None and filling == self._video_name()
                                     else "Cache Whole Video")
        self.act_free_cache.setEnabled(a and (self.provider.pinned_total()[0] > 0 or filling is not None))

    # ================================================================== 파일 추가 · 제거
    def add_files(self) -> None:
        if not self.act_add_files.isEnabled():
            return
        files, _ = QFileDialog.getOpenFileNames(self, "Add video files", self.settings.last_input_dir, VIDEO_FILTER)
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
        added, skipped = self.model.add_paths(paths)
        msg = f"Added {added} file{'s' if added != 1 else ''}"
        if skipped:
            msg += f" ({skipped} skipped: not a video or duplicate)"
        self.log.append(msg + ".")

    def _rows_added(self, rows: list[int]) -> None:
        for r in rows:
            self.probe_loader.request(self.model.item(r).path)
        if self.view.currentIndex().row() < 0 and rows:
            self.view.setCurrentIndex(self.model.index(rows[0]))

    def remove_rows(self, rows: list[int]) -> None:
        if not rows:
            return
        if self._row in rows:
            if not self._maybe_save():
                return
            self._unload()
        self.model.remove_rows(rows)
        # 위쪽 행이 지워지면 현재 영상의 행 번호가 바뀐다 (currentChanged 는 오지 않는다)
        item = self.controller.item()
        self._row = self.model.row_of(item.path) if item is not None else -1

    def clear_list(self) -> None:
        if not self._maybe_save():
            return
        self._unload()
        self.probe_loader.cancel_all()
        self.model.clear()

    def _open_folder(self, row: int) -> None:
        if 0 <= row < self.model.rowCount():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.item(row).path.parent)))

    # ================================================================== 프로브 · 썸네일
    def _probe_ready(self, path: Path, info: MediaInfo) -> None:
        row = self.model.row_of(path)
        if row < 0:
            return
        self.model.set_info(row, info, None)
        if not info.audio_only:
            key = self.thumb_loader.request(path, representative_time(info), C.THUMB_WIDTH)
            self._thumb_keys[key] = path
        if self.view.currentIndex().row() == row and self.controller.item() is None:
            self._load_video(row)

    def _probe_failed(self, path: Path, error: str) -> None:
        row = self.model.row_of(path)
        if row < 0:
            return
        self.model.set_info(row, None, error)
        self.log.append_error(f"[{path.name}] Probe failed: {error}")
        if self.view.currentIndex().row() == row:
            self.canvas.clear(f"Cannot open this file: {error}")

    def _thumb_ready(self, key: str, img: QImage) -> None:
        path = self._thumb_keys.pop(key, None)
        if path is None:
            return
        row = self.model.row_of(path)
        if row >= 0:
            self.model.set_thumbnail(row, QPixmap.fromImage(img))

    # ================================================================== 영상 선택
    def _current_changed(self, row: int, prev: int) -> None:
        if self._reverting:
            return
        cur_item = self.controller.item()
        new_item = self.model.item(row) if 0 <= row < self.model.rowCount() else None
        if cur_item is not None and new_item is not None and new_item.path == cur_item.path:
            return
        if not self._maybe_save():
            # Cancel → 선택을 되돌린다
            self._reverting = True
            if 0 <= self._row < self.model.rowCount():
                self.view.selectionModel().setCurrentIndex(self.model.index(self._row),
                                                           QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self._reverting = False
            return
        self._load_video(row)

    def _unload(self) -> None:
        self.controller.set_video(None, self.settings.hwaccel)
        self.doc = None
        self._doc_path = None
        self._row = -1
        self.canvas.set_document(None)
        self.canvas.clear("Select a video to start drawing.")
        self.transport.set_markers([])
        self.transport.set_has_audio(False)
        self.cache_panel.set_source_size(0, 0)
        self._refresh_cache_ui()
        self._update_actions()
        self.title_changed.emit()

    def _load_video(self, row: int) -> None:
        item = self.model.item(row) if 0 <= row < self.model.rowCount() else None
        if item is None or item.info is None:
            self._unload()
            self._row = row if item is not None else -1
            if item is not None:
                self.canvas.clear(item.probe_error and f"Cannot open this file: {item.probe_error}" or "Probing…")
            return
        if item.info.audio_only:
            # 확장자는 영상인데 소리만 든 파일 (.mp4 로 된 음성 등) — 그릴 화면이 없다
            self._unload()
            self._row = row
            self.canvas.clear("This file has no video stream. Convert it to WAV in the Convert tab.")
            return
        info = item.info
        self._row = row
        self._last_error = ""
        self.controller.set_video(item, self.settings.hwaccel, self._decode_scale)
        self.canvas.set_source_size(info.width, info.height)
        self.cache_panel.set_source_size(info.width, info.height)
        self.transport.set_range(self.controller.last_frame())
        self.transport.set_has_audio(info.has_audio)
        self._doc_path = None
        doc = self._read_sidecar(item)
        self._set_document(doc)
        spec = self.provider.spec
        if spec is not None:
            fps = f"{info.fps:.3f}".rstrip("0").rstrip(".")
            self.log.append(f"{item.path.name} — {info.width}x{info.height}, {fps} fps, "
                            f"{info.frame_count} frames. Decoding at {spec.out_w}x{spec.out_h}. "
                            f"Cache holds about {self.provider.cache_capacity()} frames; the whole video needs "
                            f"{format_gib(info.frame_count * spec.frame_bytes)}.")
        self._refresh_cache_ui()
        self.canvas.setFocus()

    # ================================================================== 프레임 캐시
    def _video_name(self) -> str | None:
        item = self.controller.item()
        return item.path.name if item is not None else None

    def _refresh_cache_ui(self) -> None:
        p = self.provider
        name = self._video_name()
        frames = self.controller.last_frame() + 1 if name is not None else 0
        cached = p.pinned_frames() if name is not None else 0
        complete = p.pinned_complete() if name is not None else False
        total, videos = p.pinned_total()
        need_text = None
        spec = p.spec
        if name is not None and spec is not None and not complete:
            need_text = f"Needs {format_gib(max(0, frames - cached) * spec.frame_bytes)}"
            mem = system_memory()
            if mem is not None:
                need_text += f" · {format_gib(full_cache_budget(mem))} usable"
        self.cache_panel.set_state(name, cached, frames, complete, p.filling_name(), total, videos, need_text)
        self.transport.set_cached_ranges(p.pinned_ranges() if name is not None else [])
        self._update_actions()

    def cache_whole_video(self) -> None:
        """지금 영상 전 구간을 메모리에 올린다 (채우는 중이면 멈춘다). 다 안 들어가면 현재 프레임 주변만."""
        item = self.controller.item()
        p = self.provider
        spec = p.spec
        if item is None or spec is None:
            return
        if p.filling_name() == item.path.name:
            p.cancel_full_cache()
            return
        if p.pinned_complete():
            self.log.append(f"{item.path.name} is already fully cached.")
            return
        frames = self.controller.last_frame() + 1
        mem = system_memory()
        if mem is None:
            budget, reserve = frames * spec.frame_bytes, 0     # 메모리를 못 읽으면 검사 없이 전부
        else:
            budget, reserve = full_cache_budget(mem), reserve_bytes(mem.total)
        start, end = plan_cache_range(frames, spec.frame_bytes, self.controller.frame(), budget, p.pinned_frames())
        if end < start:
            free = format_gib(mem.available) if mem is not None else "?"
            self.log.append_error(f"Not enough free memory to cache {item.path.name} ({free} free, "
                                  f"{format_gib(reserve)} is kept for the system). "
                                  f"Free some cache or close other apps.")
            return
        whole = start == 0 and end == frames - 1
        if whole:
            free = f" ({format_gib(mem.available)} free)" if mem is not None else ""
            self.log.append(f"Caching {item.path.name}: {frames} frames, about "
                            f"{format_gib(frames * spec.frame_bytes)}{free}.")
        else:
            self.log.append_error(f"Not enough free memory for the whole video "
                                  f"({format_gib(frames * spec.frame_bytes)} needed, {format_gib(budget)} usable). "
                                  f"Caching frames {start}-{end} around the current frame.")
        if p.start_full_cache(start, end, reserve, whole):
            self.cache_panel.set_progress(0, end - start + 1)
        self._refresh_cache_ui()

    def set_decode_scale(self, scale: int) -> None:
        """디코드 해상도를 바꾸고 지금 영상을 같은 프레임에서 다시 연다.

        이전 해상도로 올려 둔 전체 캐시는 새 해상도에서 못 쓰므로, 있으면 물어보고 해제한다.
        """
        scale = normalize_scale(scale)
        if scale == self._decode_scale:
            return
        p = self.provider
        total, _ = p.pinned_total()
        if total > 0 or p.filling_name() is not None:
            ans = QMessageBox.question(
                self, "Change Resolution",
                f"Cached frames were decoded at the current resolution and cannot be reused.\n"
                f"Changing the resolution frees them ({format_gib(total)}). Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                self.cache_panel.set_scale(self._decode_scale)
                return
            self.free_all_cache()
        self._decode_scale = scale
        self.settings.set("draw/decode_scale", scale)
        self.cache_panel.set_scale(scale)
        item = self.controller.item()
        if item is None or item.info is None:
            self._refresh_cache_ui()
            return
        frame, playing = self.controller.frame(), self.controller.is_playing()
        self.controller.set_video(item, self.settings.hwaccel, scale, frame)
        self.transport.set_range(self.controller.last_frame())
        spec = p.spec
        if spec is not None:
            self.log.append(f"Decoding at {spec.out_w}x{spec.out_h} ({spec.frame_bytes / 2 ** 20:.1f} MB per frame). "
                            f"Cache holds about {p.cache_capacity()} frames; the whole video needs "
                            f"{format_gib(item.info.frame_count * spec.frame_bytes)}.")
        if playing:
            self.controller.play()
        self._refresh_cache_ui()
        self.canvas.setFocus()

    def free_all_cache(self) -> None:
        freed = self.provider.free_all_cache()
        self.log.append(f"Freed {format_gib(freed)} of frame cache.")
        self._refresh_cache_ui()

    def _fill_finished(self, name: str, ok: bool, msg: str) -> None:
        if ok:
            self.log.append_ok(msg)
        elif msg.startswith("Stopped caching") and "memory" not in msg:
            self.log.append(msg)
        else:
            self.log.append_error(msg)
        self._refresh_cache_ui()

    def _new_document(self, item: VideoItem) -> DrawingDocument:
        info = item.info
        assert info is not None
        return DrawingDocument(video_name=item.path.name, video_path=item.path.as_posix(), width=info.width,
                               height=info.height, fps=info.fps, frame_count=info.frame_count)

    def _read_sidecar(self, item: VideoItem) -> DrawingDocument:
        path = sidecar_path(item.path)
        legacy = False
        if not path.is_file():
            # v0.3.0 초기 위치(영상 바로 옆)에 있으면 읽어 오고, 다음 저장은 .draw 폴더로 간다
            path = legacy_sidecar_path(item.path)
            legacy = True
            if not path.is_file():
                return self._new_document(item)
        try:
            doc = self._read_file(path)
        except (OSError, DrawingFormatError) as exc:
            self.log.append_error(f"Could not load {path.name}: {exc}")
            return self._new_document(item)
        doc = self._fit_document(doc, item)
        self.log.append_ok(f"Loaded drawing: {self._rel(path, item)} ({_doc_summary(doc)})")
        if legacy:
            self.log.append(f"This drawing is in the old location; the next save writes "
                            f"{self._rel(sidecar_path(item.path), item)}.")
        return doc

    @staticmethod
    def _rel(path: Path, item: VideoItem) -> str:
        """영상 폴더 기준 상대 경로 (로그용). 다른 폴더면 파일 이름만."""
        try:
            return path.relative_to(item.path.parent).as_posix()
        except ValueError:
            return path.name

    def _read_file(self, path: Path) -> DrawingDocument:
        doc = DrawingDocument.from_json(path.read_text(encoding="utf-8"))
        if doc.load_warnings:
            self.log.append_error(f"{path.name}: skipped {doc.load_warnings} invalid stroke(s).")
        return doc

    def _fit_document(self, doc: DrawingDocument, item: VideoItem) -> DrawingDocument:
        """다른 해상도로 그린 문서는 비율 변환한다. 영상 정보(이름 · fps · 길이)는 현재 영상으로 맞춘다."""
        info = item.info
        assert info is not None
        if doc.width > 0 and doc.height > 0 and (doc.width, doc.height) != (info.width, info.height):
            self.log.append_error(f"Drawing was made at {doc.width}x{doc.height}; rescaled to "
                                  f"{info.width}x{info.height}.")
            doc = doc.rescaled(info.width, info.height)
        dirty = doc.dirty
        doc.video_name = item.path.name
        doc.video_path = item.path.as_posix()
        doc.width, doc.height = info.width, info.height
        doc.fps, doc.frame_count = info.fps, info.frame_count
        doc.dirty = dirty
        return doc

    def _set_document(self, doc: DrawingDocument) -> None:
        self.doc = doc
        self.canvas.set_document(doc)
        self._doc_changed()

    # ================================================================== 재생 · 프레임
    def _frame_changed(self, frame: int) -> None:
        self.canvas.set_frame(frame, self.provider.cached(frame))
        self._update_actions()

    def _playing_changed(self, playing: bool) -> None:
        self.canvas.set_playing(playing)
        self.act_play.setIcon(icon("pause" if playing else "play"))

    def _range_changed(self, last: int) -> None:
        self.transport.set_range(last)
        self.log.append(f"Video has fewer frames than reported; last frame is {last}. "
                        "Variable frame rate videos may show approximate frame numbers.")

    def _decode_error(self, gen: int, msg: str) -> None:
        if gen != self.controller.video_gen() or msg == self._last_error:
            return
        self._last_error = msg
        self.log.append_error(f"Decode error: {msg}")

    def _scrub_started(self) -> None:
        self.controller.pause()
        self._scrub_base = self.controller.frame()

    def snap_drawn(self, direction: int) -> None:
        """그림이 있는 이전(-1) / 다음(+1) 프레임으로 이동한다."""
        if self.doc is None or self.controller.item() is None:
            return
        cur = self.controller.frame()
        target = self.doc.prev_drawn_frame(cur) if direction < 0 else self.doc.next_drawn_frame(cur)
        if target is not None:
            self.controller.step(target - cur)

    def _set_tool(self, tool: str) -> None:
        self.canvas.set_tool(tool)

    # ================================================================== 편집
    def _doc_changed(self) -> None:
        doc = self.doc
        self.transport.set_markers(doc.frames_with_strokes() if doc is not None else [])
        self.canvas.update()
        self._update_actions()
        self.title_changed.emit()

    def _stroke_finished(self, stroke: Stroke) -> None:
        if self.doc is None:
            return
        self.doc.add_stroke(self.controller.frame(), stroke)
        self._doc_changed()

    def _erase_finished(self, strokes: list[Stroke]) -> None:
        if self.doc is None:
            return
        self.doc.replace_frame(self.controller.frame(), strokes)
        self._doc_changed()

    def undo(self) -> None:
        if self.doc is not None and not self.canvas.is_busy() and self.doc.undo(self.controller.frame()):
            self._doc_changed()

    def redo(self) -> None:
        if self.doc is not None and not self.canvas.is_busy() and self.doc.redo(self.controller.frame()):
            self._doc_changed()

    def clear_frame(self) -> None:
        if self.doc is None:
            return
        f = self.controller.frame()
        n = self.doc.clear_frame(f)
        if n:
            self.log.append(f"Cleared {n} stroke(s) on frame {f}.")
            self._doc_changed()

    def clear_all(self) -> None:
        if self.doc is None or self.doc.is_empty():
            return
        ans = QMessageBox.question(self, "Clear All Drawings",
                                   f"Delete all drawings on every frame of '{self.doc.video_name}'?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        frames = len(self.doc.frames_with_strokes())
        n = self.doc.clear_all()
        self.log.append(f"Cleared {n} stroke(s) on {frames} frame(s). Undo restores each frame separately.")
        self._doc_changed()

    # ================================================================== 저장 · 불러오기
    def _maybe_save(self) -> bool:
        """미저장 그림 처리. False 면 호출한 동작(전환 · 종료 · 제거)을 취소한다."""
        doc = self.doc
        if doc is None or not doc.dirty:
            return True
        if self.autosave_check.isChecked():
            return self.save()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Unsaved drawing")
        box.setText(f"Save changes to the drawing for '{doc.video_name}'?")
        box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                               | QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        ans = box.exec()
        if ans == QMessageBox.StandardButton.Save:
            return self.save()
        if ans == QMessageBox.StandardButton.Discard:
            doc.dirty = False
            self.title_changed.emit()
            return True
        return False

    def _target_path(self) -> Path | None:
        item = self.controller.item()
        if item is None:
            return None
        return self._doc_path or sidecar_path(item.path)

    def save(self) -> bool:
        path = self._target_path()
        if path is None or self.doc is None:
            return False
        return self._save_to(path)

    def save_as(self) -> bool:
        start = self._target_path()
        if start is None or self.doc is None:
            return False
        name, _ = QFileDialog.getSaveFileName(self, "Save Drawing As", str(start), _DRAWING_FILTER)
        if not name:
            return False
        path = Path(name)
        if not path.name.lower().endswith(".json"):
            path = path.with_name(path.name + C.DRAW_FILE_SUFFIX)
        return self._save_to(path)

    def _save_to(self, path: Path) -> bool:
        assert self.doc is not None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)     # <영상 폴더>/.draw
            path.write_text(self.doc.to_json(), encoding="utf-8")
        except OSError as exc:
            self.log.append_error(f"Could not save drawing: {exc}")
            ans = QMessageBox.warning(self, "Save failed", f"Could not save the drawing:\n{exc}\n\nChoose another location?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                return self.save_as()
            return False
        self.doc.dirty = False
        item = self.controller.item()
        assert item is not None
        self._doc_path = path if path != sidecar_path(item.path) else None
        self.log.append_ok(f"Saved drawing: {self._rel(path, item)} ({_doc_summary(self.doc)})")
        self._doc_changed()
        return True

    def load(self) -> None:
        item = self.controller.item()
        if item is None:
            return
        name, _ = QFileDialog.getOpenFileName(self, "Load Drawing", str(self._target_path() or item.path.parent),
                                              _DRAWING_FILTER)
        if not name:
            return
        self._load_from(Path(name), item)

    def _load_from(self, path: Path, item: VideoItem) -> None:
        try:
            doc = self._read_file(path)
        except (OSError, DrawingFormatError) as exc:
            QMessageBox.warning(self, "Load failed", f"Could not load {path.name}:\n{exc}")
            self.log.append_error(f"Could not load {path.name}: {exc}")
            return
        if doc.video_name and doc.video_name != item.path.name:
            ans = QMessageBox.question(self, "Different video",
                                       f"This drawing was made for '{doc.video_name}'. Load it anyway?",
                                       QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return
        if not self._maybe_save():
            return
        doc = self._fit_document(doc, item)
        self._doc_path = path if path != sidecar_path(item.path) else None
        self._set_document(doc)
        self.log.append_ok(f"Loaded drawing: {path.name} ({_doc_summary(doc)})")

    def _load_for_row(self, row: int) -> None:
        if not (0 <= row < self.model.rowCount()):
            return
        if row != self._row:
            self.view.setCurrentIndex(self.model.index(row))
            if row != self._row:
                return   # 전환이 취소됐거나 아직 프로브 중
        self.load()

    def _show_drawing_file(self, row: int) -> None:
        if not (0 <= row < self.model.rowCount()):
            return
        item = self.model.item(row)
        path = (self._doc_path if row == self._row and self._doc_path else None) or sidecar_path(item.path)
        if not path.is_file() and legacy_sidecar_path(item.path).is_file():
            path = legacy_sidecar_path(item.path)
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
            self.log.append(f"Drawing file: {path}")
        else:
            self.log.append(f"No drawing file for {item.path.name} (would be {path.name}).")

    # ================================================================== 내보내기
    def export(self) -> None:
        item = self.controller.item()
        if item is None or self.doc is None:
            return
        self.controller.pause()
        dlg = ExportDialog(self.settings, item, self.doc, self.ghost_panel.state(), self)
        dlg.log.connect(self.log.append)
        dlg.exported.connect(lambda p, size, sec: self.log.append_ok(
            f"Exported: {Path(p).name} ({human_size(size)}, {sec:.1f} s)"))
        dlg.exec()
        dlg.deleteLater()
