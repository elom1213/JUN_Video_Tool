# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""아이콘 로더 (PLAN 6.14).

- SVG 라인 아이콘은 이 폴더에 두고 `icon("name")` 으로 QIcon 을 얻는다 (qsvgicon 플러그인이 렌더).
- 앱 아이콘은 `dev/build_icons.py` 가 app.svg 에서 만든 app.ico / app.png 를 우선 쓴다.
- 이모지·심볼 폰트에 의존하지 않으므로 Windows 10/11 에서 같은 모양이 나온다 (PLAN 12.2).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon, QPixmap

ICON_DIR = Path(__file__).resolve().parent
_cache: dict[str, QIcon] = {}


def icon_path(name: str) -> Path:
    return ICON_DIR / f"{name}.svg"


def icon(name: str) -> QIcon:
    """SVG 이름 → QIcon. 파일이 없으면 빈 QIcon (텍스트만 보임)."""
    ic = _cache.get(name)
    if ic is None:
        p = icon_path(name)
        ic = QIcon(str(p)) if p.is_file() else QIcon()
        _cache[name] = ic
    return ic


def pixmap(name: str, size: int = 16) -> QPixmap:
    return icon(name).pixmap(QSize(size, size))


def app_icon() -> QIcon:
    """app.ico (다중 크기) → app.png → app.svg 순."""
    for fname in ("app.ico", "app.png", "app.svg"):
        p = ICON_DIR / fname
        if p.is_file():
            ic = QIcon(str(p))
            if not ic.isNull():
                return ic
    return QIcon()
