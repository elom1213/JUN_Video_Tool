# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-19
"""프레임 캐시 패널: 지금 영상 전체를 메모리에 올리기 · 모든 캐시 해제 · 메모리 현황.

표시만 한다. 계산과 실행은 DrawTab 이 provider 를 불러서 한다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout

from ....core.memory_info import format_gib


class CachePanel(QGroupBox):
    cache_clicked = Signal()     # 지금 영상 전체 캐시 (채우는 중이면 멈춤)
    free_clicked = Signal()      # 모든 영상의 캐시 해제

    def __init__(self, parent=None) -> None:
        super().__init__("Frame Cache", parent)
        self.video_label = QLabel()
        self.video_label.setWordWrap(True)
        self.need_label = QLabel()
        self.need_label.setWordWrap(True)
        self.need_label.setObjectName("HintLabel")
        self.bar = QProgressBar()
        self.bar.setTextVisible(True)
        self.bar.setFixedHeight(16)
        self.bar.hide()
        self.total_label = QLabel()
        self.total_label.setWordWrap(True)
        self.cache_btn = QPushButton("Cache Whole Video")
        self.cache_btn.setToolTip("Decode every frame of this video into memory so stepping never waits.\n"
                                  "Cached videos stay in memory when you switch videos.")
        self.free_btn = QPushButton("Free All")
        self.free_btn.setToolTip("Release the memory used by cached frames of all videos.")
        for b in (self.cache_btn, self.free_btn):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 8)
        lay.setSpacing(4)
        lay.addWidget(self.video_label)
        lay.addWidget(self.need_label)
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(self.cache_btn, 3)
        row.addWidget(self.free_btn, 2)
        lay.addLayout(row)
        lay.addWidget(self.total_label)

        self.cache_btn.clicked.connect(self.cache_clicked)
        self.free_btn.clicked.connect(self.free_clicked)
        self.set_state(None, 0, 0, False, None, 0, 0, None)

    def set_state(self, video: str | None, cached: int, frames: int, complete: bool, filling: str | None,
                  total_bytes: int, videos: int, need_text: str | None) -> None:
        """video: 지금 영상 이름 (없으면 None). filling: 채우는 중인 영상 이름 (없으면 None)."""
        filling_this = filling is not None and filling == video
        if video is None:
            self.video_label.setText("No video.")
        elif complete:
            self.video_label.setText(f"This video: all {cached} frames cached.")
        elif cached:
            self.video_label.setText(f"This video: {cached} of {frames} frames cached.")
        else:
            self.video_label.setText("This video: not cached.")
        self.need_label.setText(need_text or "")
        self.need_label.setVisible(bool(need_text))
        self.bar.setVisible(filling is not None)
        if filling is not None and not filling_this:
            self.bar.setFormat(f"{filling}  %p%")
        else:
            self.bar.setFormat("%p%")
        self.cache_btn.setText("Stop Caching" if filling_this else "Cache Whole Video")
        self.cache_btn.setEnabled(video is not None and (filling_this or not complete))
        self.free_btn.setEnabled(total_bytes > 0 or filling is not None)
        if total_bytes > 0:
            self.total_label.setText(f"In memory: {format_gib(total_bytes)} ({videos} video{'s' if videos != 1 else ''})")
        else:
            self.total_label.setText("In memory: none")

    def set_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(min(done, max(1, total)))
