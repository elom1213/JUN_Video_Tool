# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""qss 로더. `@ICONS@` 토큰을 아이콘 폴더 절대 경로(슬래시)로 치환한다."""
from __future__ import annotations

from pathlib import Path

STYLE_DIR = Path(__file__).resolve().parent
ICON_DIR = STYLE_DIR.parent / "icons"


def load_stylesheet(name: str = "dark") -> str:
    path = STYLE_DIR / f"{name}.qss"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    return text.replace("@ICONS@", ICON_DIR.as_posix())
