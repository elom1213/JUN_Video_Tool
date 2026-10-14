# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""QSettings 래퍼 (PLAN 6.12)."""
from __future__ import annotations

from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

from . import constants as C
from .version import ORG_NAME, SETTINGS_APP
from ..core.converters.gif_converter import GifOptions


class AppSettings:
    def __init__(self) -> None:
        self._s = QSettings(ORG_NAME, SETTINGS_APP)

    # ------------------------------------------------------------------ 범용
    def get(self, key: str, default: Any = None, type_: type | None = None) -> Any:
        if type_ is not None:
            return self._s.value(key, default, type=type_)
        return self._s.value(key, default)

    def set(self, key: str, value: Any) -> None:
        self._s.setValue(key, value)

    def sync(self) -> None:
        self._s.sync()

    # ------------------------------------------------------------------ 실행 옵션
    @property
    def concurrency(self) -> int:
        v = int(self.get("run/concurrency", C.DEFAULT_CONCURRENCY, int))
        return max(1, min(C.MAX_CONCURRENCY, v))

    @concurrency.setter
    def concurrency(self, v: int) -> None:
        self.set("run/concurrency", max(1, min(C.MAX_CONCURRENCY, int(v))))

    @property
    def hwaccel(self) -> str:
        v = str(self.get("run/hwaccel", C.DEFAULT_HWACCEL, str))
        return v if v in ("auto", "none") else C.DEFAULT_HWACCEL

    @hwaccel.setter
    def hwaccel(self, v: str) -> None:
        self.set("run/hwaccel", v if v in ("auto", "none") else C.DEFAULT_HWACCEL)

    @property
    def estimate_enabled(self) -> bool:
        return bool(self.get("estimate/enabled", True, bool))

    @estimate_enabled.setter
    def estimate_enabled(self, v: bool) -> None:
        self.set("estimate/enabled", bool(v))

    # ------------------------------------------------------------------ GIF 옵션
    def load_gif_options(self) -> GifOptions:
        opts = GifOptions()
        for f in fields(GifOptions):
            if f.name in ("format_id", "output_dir", "suffix", "overwrite"):
                continue
            key = f"gif/{f.name}"
            if not self._s.contains(key):
                continue
            raw = self._s.value(key)
            default = getattr(opts, f.name)
            try:
                if raw is None or raw == "":
                    val = None
                elif isinstance(default, bool) or f.name == "lock_aspect":
                    val = str(raw).lower() in ("1", "true", "yes")
                elif f.name in ("width", "height"):
                    val = int(raw) if str(raw) not in ("", "None") else None
                elif f.name == "target_size_mb":
                    val = float(raw) if str(raw) not in ("", "None") else None
                elif isinstance(default, int):
                    val = int(raw)
                elif isinstance(default, float):
                    val = float(raw)
                else:
                    val = str(raw)
                setattr(opts, f.name, val)
            except (TypeError, ValueError):
                continue
        opts.hwaccel = self.hwaccel
        return opts

    def save_gif_options(self, opts: GifOptions) -> None:
        for k, v in asdict(opts).items():
            if k in ("format_id", "output_dir", "suffix", "overwrite"):
                continue
            self.set(f"gif/{k}", "" if v is None else v)

    # ------------------------------------------------------------------ 입출력
    @property
    def last_input_dir(self) -> str:
        return str(self.get("io/last_input_dir", str(Path.home()), str))

    @last_input_dir.setter
    def last_input_dir(self, v: str) -> None:
        self.set("io/last_input_dir", v)

    @property
    def last_output_dir(self) -> str:
        return str(self.get("io/last_output_dir", "", str))

    @last_output_dir.setter
    def last_output_dir(self, v: str) -> None:
        self.set("io/last_output_dir", v)
