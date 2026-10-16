# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""메인 윈도우 (PLAN_DRAW_TAB 5.8): 탭 · 메뉴 · 전역 설정 · 시작 점검 · 종료만 담당한다.

변환 기능은 `ConvertTab`, 드로오버 기능은 `DrawTab` 이 가진다. 두 탭은 같은 메서드 이름(3.3)을 가지므로
여기서는 활성 탭에 전달만 한다.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenu, QMessageBox, QTabWidget

from ..config.settings import AppSettings
from ..config.version import APP_NAME, VERSION
from ..core import ffmpeg_locator
from .convert_tab import ConvertTab
from .dependency_dialog import DependencyDialog
from .draw_tab import DrawTab
from .icons import app_icon, icon
from .settings_dialog import SettingsDialog
from .widgets.loaders import ThumbnailLoader
from .widgets.video_list_view import dropped_paths, has_local_files

_TAB_KEYS = ("convert", "draw")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowIcon(app_icon())
        self.resize(1280, 760)
        self.setMinimumSize(1000, 600)

        self.settings = AppSettings()
        # 썸네일 캐시는 두 탭이 공유한다 (같은 파일을 양쪽에 넣어도 1회 추출)
        self.thumb_loader = ThumbnailLoader(self)
        self._dep_dialog: DependencyDialog | None = None

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.convert_tab = ConvertTab(self.settings, self.thumb_loader)
        self.draw_tab = DrawTab(self.settings, self.thumb_loader)
        self.tabs.addTab(self.convert_tab, icon("convert"), "Convert")
        self.tabs.addTab(self.draw_tab, icon("brush"), "Draw")
        self.setCentralWidget(self.tabs)
        # 창 어디에 드롭해도 활성 탭에 추가된다 (리스트 뷰는 자기 드롭을 직접 처리)
        self.setAcceptDrops(True)

        self._build_menus()
        self._restore()
        self.tabs.currentChanged.connect(lambda _i: self._sync_menus())
        for tab in self._all_tabs():
            tab.view_mode_changed.connect(lambda _m: self._sync_menus())
            tab.title_changed.connect(self._update_title)
        self._sync_menus()
        QTimer.singleShot(0, self._startup_checks)

    # ================================================================== 탭
    def _all_tabs(self) -> tuple[ConvertTab, DrawTab]:
        return self.convert_tab, self.draw_tab

    def current_tab(self) -> ConvertTab | DrawTab:
        return self.draw_tab if self.tabs.currentWidget() is self.draw_tab else self.convert_tab

    def _sync_menus(self) -> None:
        cur = self.current_tab()
        for tab in self._all_tabs():
            tab.set_active(tab is cur)
        self.m_convert.setEnabled(cur is self.convert_tab)
        self.m_draw.setEnabled(cur is self.draw_tab)
        (self.act_view_thumbs if cur.view_mode() == "thumbs" else self.act_view_list).setChecked(True)
        self._update_title()

    def _update_title(self) -> None:
        suffix = self.current_tab().title_suffix()
        self.setWindowTitle(f"{APP_NAME} v{VERSION}" + (f" — {suffix}" if suffix else ""))

    # ================================================================== 드래그&드롭
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if has_local_files(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if not has_local_files(event.mimeData()):
            event.ignore()
            return
        # 탭 제목 위로 끌고 가면 그 탭으로 전환한다 → 원하는 탭에 놓을 수 있다
        bar = self.tabs.tabBar()
        idx = bar.tabAt(bar.mapFrom(self, event.position().toPoint()))
        if idx >= 0 and idx != self.tabs.currentIndex():
            self.tabs.setCurrentIndex(idx)
        event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if not has_local_files(event.mimeData()):
            event.ignore()
            return
        event.acceptProposedAction()
        paths = dropped_paths(event.mimeData())
        if paths:
            self.current_tab().add_paths(paths)

    # ================================================================== 메뉴
    def _build_menus(self) -> None:
        mb = self.menuBar()
        m_file = mb.addMenu("File")
        act_add_files = QAction(icon("add_files"), "Add Files…", self)
        act_add_files.setShortcut(QKeySequence("Ctrl+O"))
        act_add_files.triggered.connect(lambda: self.current_tab().add_files())
        act_add_folder = QAction(icon("add_folder"), "Add Folder…", self)
        act_add_folder.setShortcut(QKeySequence("Ctrl+Shift+O"))
        act_add_folder.triggered.connect(lambda: self.current_tab().add_folder())
        m_file.addAction(act_add_files)
        m_file.addAction(act_add_folder)
        m_file.addSeparator()
        act_exit = QAction(icon("cancel"), "Exit", self)
        act_exit.triggered.connect(self.close)
        m_file.addAction(act_exit)

        m_edit = mb.addMenu("Edit")
        self.act_settings = QAction(icon("settings"), "Settings…", self)
        self.act_settings.triggered.connect(self.open_settings)
        m_edit.addAction(self.act_settings)

        m_view = mb.addMenu("View")
        self.act_view_list = QAction(icon("view_list"), "List", self)
        self.act_view_thumbs = QAction(icon("view_thumbs"), "Thumbnails", self)
        self.act_view_list.setShortcut(QKeySequence("Ctrl+1"))
        self.act_view_thumbs.setShortcut(QKeySequence("Ctrl+2"))
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for a, mode in ((self.act_view_list, "list"), (self.act_view_thumbs, "thumbs")):
            a.setCheckable(True)
            grp.addAction(a)
            a.triggered.connect(lambda _c=False, m=mode: self.current_tab().set_view_mode(m))
            m_view.addAction(a)
        m_view.addSeparator()
        for i, (name, key) in enumerate((("Convert Tab", "Alt+1"), ("Draw Tab", "Alt+2"))):
            a = QAction(name, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _c=False, idx=i: self.tabs.setCurrentIndex(idx))
            m_view.addAction(a)

        self.m_convert = mb.addMenu("Convert")
        self._fill_menu(self.m_convert, self.convert_tab.menu_actions())
        self.m_draw = mb.addMenu("Draw")
        self._fill_menu(self.m_draw, self.draw_tab.menu_actions())

        m_help = mb.addMenu("Help")
        act_deps = QAction(icon("download"), "Check Dependencies…", self)
        act_deps.triggered.connect(lambda: self.open_dependencies(False))
        act_ffmpeg_info = QAction(icon("info"), "Show ffmpeg Info", self)
        act_ffmpeg_info.triggered.connect(self.show_ffmpeg_info)
        act_about = QAction(app_icon(), "About", self)
        act_about.triggered.connect(self.show_about)
        m_help.addAction(act_deps)
        m_help.addAction(act_ffmpeg_info)
        m_help.addSeparator()
        m_help.addAction(act_about)

    @staticmethod
    def _fill_menu(menu: QMenu, actions: list[QAction | None]) -> None:
        for a in actions:
            if a is None:
                menu.addSeparator()
            else:
                menu.addAction(a)

    # ================================================================== 설정
    def _restore(self) -> None:
        geo = self.settings.get("ui/geometry")
        if isinstance(geo, QByteArray) and not geo.isEmpty():
            self.restoreGeometry(geo)
        for tab in self._all_tabs():
            tab.restore_settings()
        key = str(self.settings.get("ui/current_tab", "convert", str))
        self.tabs.setCurrentIndex(_TAB_KEYS.index(key) if key in _TAB_KEYS else 0)

    def _save(self) -> None:
        s = self.settings
        s.set("ui/geometry", self.saveGeometry())
        s.set("ui/current_tab", _TAB_KEYS[max(0, self.tabs.currentIndex())])
        for tab in self._all_tabs():
            tab.save_settings()
        s.sync()

    # ================================================================== 시작 점검
    def _log_all(self, msg: str, kind: str = "info") -> None:
        for tab in self._all_tabs():
            log = tab.log_panel()
            {"info": log.append, "ok": log.append_ok, "error": log.append_error}[kind](msg)

    def _set_ffmpeg_available(self, ok: bool) -> None:
        for tab in self._all_tabs():
            tab.set_ffmpeg_available(ok)

    def _startup_checks(self) -> None:
        ff = ffmpeg_locator.find_ffmpeg()
        if ff is None:
            self._log_all("ffmpeg was not found.", "error")
            self._set_ffmpeg_available(False)
            ans = QMessageBox.question(
                self, "ffmpeg not found",
                f"ffmpeg was not found.\nInstall it now? (downloads about 90 MB into {ffmpeg_locator.bin_dir()})",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                self.open_dependencies(auto_install=True)
            return
        self._set_ffmpeg_available(True)
        self._log_all(f"{ffmpeg_locator.ffmpeg_version(ff) or 'ffmpeg'} — {ff}")
        if ffmpeg_locator.find_ffprobe() is None:
            self._log_all("ffprobe not found; falling back to ffmpeg output parsing for media info.")

    def _dependencies_changed(self) -> None:
        ffmpeg_locator.reset_cache()
        ff = ffmpeg_locator.find_ffmpeg()
        if ff is not None:
            self._set_ffmpeg_available(True)
            self._log_all(f"ffmpeg is now available: {ff}", "ok")
            for tab in self._all_tabs():
                tab.reprobe_missing()
        else:
            self._log_all("ffmpeg is still missing.", "error")

    # ================================================================== 다이얼로그
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            self.convert_tab.on_settings_changed()

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
                          f"{APP_NAME} v{VERSION}\n\nBulk video converter (GIF / MP4) and frame draw-over tool.\n"
                          "Python + PySide6 + ffmpeg.\n\nAuthor: Ji Hun Park")

    # ================================================================== 종료
    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        for tab in self._all_tabs():
            if not tab.request_close():
                event.ignore()
                return
        for tab in self._all_tabs():
            tab.shutdown()
        self.thumb_loader.cancel_all()
        self._save()
        super().closeEvent(event)
