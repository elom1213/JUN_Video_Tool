# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""의존성 상태 점검 (PLAN 13장). 표준 라이브러리만 사용 — PySide6 가 없을 때도 import 가능해야 한다."""
from __future__ import annotations

import json
import re
import sys
import sysconfig
from dataclasses import dataclass, asdict
from importlib import metadata
from pathlib import Path

from .ffmpeg_locator import find_ffmpeg, find_ffprobe, ffmpeg_version, bin_dir
from .utils import tool_root

_REQ_RE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(.*?)\s*(?:#.*)?$")
_SPEC_RE = re.compile(r"(===|==|!=|~=|>=|<=|>|<)\s*([0-9][0-9A-Za-z.\-+*]*)")


@dataclass
class DependencyStatus:
    name: str
    kind: str              # "python" | "pip" | "binary"
    required: str
    found: str
    status: str            # "OK" | "Missing" | "Outdated" | "Unsupported" | "Unknown"
    location: str

    def to_dict(self) -> dict:
        return asdict(self)


def version_tuple(v: str) -> tuple[int, ...]:
    """"6.11.1" → (6, 11, 1). 숫자가 아닌 접미(rc1 등)는 버린다."""
    parts: list[int] = []
    for piece in v.split("."):
        m = re.match(r"\d+", piece)
        if not m:
            break
        parts.append(int(m.group(0)))
    return tuple(parts) or (0,)


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    a2 = a + (0,) * (n - len(a))
    b2 = b + (0,) * (n - len(b))
    return (a2 > b2) - (a2 < b2)


def satisfies(version: str, spec: str) -> bool:
    """`packaging` 없이 간단한 PEP 440 비교. 와일드카드(==6.*)는 접두 비교."""
    spec = (spec or "").strip()
    if not spec:
        return True
    v = version_tuple(version)
    for op, target in _SPEC_RE.findall(spec):
        if target.endswith(".*"):
            t = version_tuple(target[:-2])
            prefix_ok = v[: len(t)] == t
            if op in ("==", "===") and not prefix_ok:
                return False
            if op == "!=" and prefix_ok:
                return False
            continue
        t = version_tuple(target)
        c = _cmp(v, t)
        if op in ("==", "==="):
            ok = c == 0
        elif op == "!=":
            ok = c != 0
        elif op == ">=":
            ok = c >= 0
        elif op == "<=":
            ok = c <= 0
        elif op == ">":
            ok = c > 0
        elif op == "<":
            ok = c < 0
        elif op == "~=":
            # ~=6.8 → >=6.8, ==6.*
            ok = c >= 0 and v[: max(1, len(t) - 1)] == t[: max(1, len(t) - 1)]
        else:
            ok = True
        if not ok:
            return False
    return True


def parse_requirements(path: Path) -> list[tuple[str, str]]:
    """requirements.txt → [(패키지명, 스펙문자열)]."""
    result: list[tuple[str, str]] = []
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        m = _REQ_RE.match(line)
        if not m:
            continue
        name, spec = m.group(1), m.group(2).strip()
        result.append((name, spec))
    return result


def installed_version(dist_name: str) -> str | None:
    try:
        return metadata.version(dist_name)
    except metadata.PackageNotFoundError:
        return None


def _dist_location(dist_name: str) -> str:
    try:
        dist = metadata.distribution(dist_name)
        files = dist.files or []
        if files:
            return str(Path(str(dist.locate_file(files[0]))).parent)
    except Exception:
        pass
    return ""


def check_pip(requirements: Path | None = None) -> list[DependencyStatus]:
    req_path = requirements or (tool_root() / "requirements.txt")
    out: list[DependencyStatus] = []
    for name, spec in parse_requirements(req_path):
        ver = installed_version(name)
        if ver is None:
            out.append(DependencyStatus(name, "pip", spec or "any", "-", "Missing", ""))
        elif satisfies(ver, spec):
            out.append(DependencyStatus(name, "pip", spec or "any", ver, "OK", _dist_location(name)))
        else:
            out.append(DependencyStatus(name, "pip", spec or "any", ver, "Outdated", _dist_location(name)))
    return out


def check_binaries() -> list[DependencyStatus]:
    out: list[DependencyStatus] = []
    ff = find_ffmpeg()
    if ff is None:
        out.append(DependencyStatus("ffmpeg", "binary", "any", "-", "Missing", str(bin_dir())))
    else:
        out.append(DependencyStatus("ffmpeg", "binary", "any", ffmpeg_version(ff) or "found", "OK", str(ff)))
    fp = find_ffprobe()
    if fp is None:
        out.append(DependencyStatus("ffprobe", "binary", "optional", "-", "Missing", str(bin_dir())))
    else:
        out.append(DependencyStatus("ffprobe", "binary", "optional", "found", "OK", str(fp)))
    return out


def missing_pip_packages() -> list[str]:
    return [d.name for d in check_pip() if d.status != "OK"]


_DEFAULT_PY_SPEC = {"min": "3.11", "max_exclusive": "3.15"}


def python_spec() -> dict:
    """deps.json 의 "python" 항목. 파일이 없거나 깨졌으면 기본값. (bootstrap 과 앱이 같은 소스를 본다)"""
    try:
        with open(tool_root() / "deps.json", encoding="utf-8") as f:
            spec = json.load(f).get("python") or {}
    except (OSError, ValueError):
        spec = {}
    return {**_DEFAULT_PY_SPEC, **spec}


def is_free_threaded() -> bool:
    """free-threaded(GIL 없는) 빌드면 True. PySide6 abi3 휠은 이 빌드에 설치되지 않는다."""
    return sysconfig.get_config_var("Py_GIL_DISABLED") == 1


def python_status(spec: dict | None = None,
                  version: tuple[int, ...] | None = None,
                  free_threaded: bool | None = None) -> DependencyStatus:
    """현재 인터프리터가 지원 범위인지. 인자는 테스트용 — 생략하면 실행 중인 인터프리터를 본다."""
    spec = {**_DEFAULT_PY_SPEC, **(spec or python_spec())}
    v = tuple(version if version is not None else sys.version_info[:3])
    ft = is_free_threaded() if free_threaded is None else free_threaded
    lo = version_tuple(spec["min"])
    hi = version_tuple(spec["max_exclusive"])
    required = f">={spec['min']},<{spec['max_exclusive']}"
    found = ".".join(str(x) for x in v) + ("t (free-threaded)" if ft else "")
    if ft:
        status = "Unsupported"
    elif _cmp(v[: len(lo)], lo) < 0:
        status = "Outdated"
    elif _cmp(v[: len(hi)], hi) >= 0:
        status = "Unsupported"
    else:
        status = "OK"
    return DependencyStatus("Python", "python", required, found, status, sys.executable)


def check_all() -> list[DependencyStatus]:
    return [python_status()] + check_pip() + check_binaries()
