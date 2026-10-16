# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""QSettings 래퍼 (PLAN 6.12). 포맷별 옵션은 `<format_id>/options_json` 한 키에 JSON 으로 저장한다."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

from . import constants as C
from .version import ORG_NAME, SETTINGS_APP
from ..core.converters.base import BaseConverter
from ..core.models import ConvertOptions

_SKIP_FIELDS = ("format_id", "output_dir", "suffix", "overwrite")


class AppSettings:
    def __init__(self) -> None:
        # 테스트·스크립트는 JUN_VIDEO_TOOL_SETTINGS_SCOPE 로 별도 범위를 써서 사용자의 설정을 건드리지 않는다
        scope = os.environ.get("JUN_VIDEO_TOOL_SETTINGS_SCOPE", SETTINGS_APP)
        self._s = QSettings(ORG_NAME, scope)

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

    # ------------------------------------------------------------------ 포맷별 옵션
    def load_options(self, converter: BaseConverter, prefix: str = "") -> ConvertOptions:
        """prefix 가 있으면 `<prefix><format_id>/options_json` (Draw 내보내기: "export/")."""
        opts = converter.default_options()
        raw = str(self.get(f"{prefix}{converter.format_id}/options_json", "", str) or "")
        data: dict = {}
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {}
        elif converter.format_id == "gif" and not prefix:
            data = self._legacy_gif_dict()
        for f in fields(type(opts)):
            if f.name in _SKIP_FIELDS or f.name not in data:
                continue
            val = data[f.name]
            default = getattr(opts, f.name)
            try:
                if val is None:
                    setattr(opts, f.name, None)
                elif isinstance(default, bool):
                    setattr(opts, f.name, bool(val))
                elif isinstance(default, int) and not isinstance(default, bool):
                    setattr(opts, f.name, int(val))
                elif isinstance(default, float):
                    setattr(opts, f.name, float(val))
                elif isinstance(default, str):
                    setattr(opts, f.name, str(val))
                else:  # Optional 필드(default None): 저장된 타입 그대로
                    setattr(opts, f.name, val)
            except (TypeError, ValueError):
                continue
        if hasattr(opts, "hwaccel"):
            opts.hwaccel = self.hwaccel  # type: ignore[attr-defined]
        return opts

    def save_options(self, opts: ConvertOptions, prefix: str = "") -> None:
        d = {k: v for k, v in asdict(opts).items() if k not in _SKIP_FIELDS}
        self.set(f"{prefix}{opts.format_id}/options_json", json.dumps(d, default=str))

    def _legacy_gif_dict(self) -> dict:
        """v0.1.0 의 gif/<field> 키 호환."""
        out: dict = {}
        for key in self._s.allKeys():
            if not key.startswith("gif/") or key == "gif/options_json":
                continue
            name = key[4:]
            raw = self._s.value(key)
            if raw is None or raw == "" or raw == "None":
                out[name] = None
            elif isinstance(raw, str) and raw.lower() in ("true", "false"):
                out[name] = raw.lower() == "true"
            else:
                out[name] = raw
        return out

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
