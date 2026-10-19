# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-19
"""시스템 메모리 조회 + 전체 프레임 캐시 예산 계산. PySide6 비의존 (psutil 없이 ctypes).

Draw 탭의 "Cache Whole Video" 가 쓴다. 영상 전 구간을 RGB24 로 메모리에 올리므로,
시작 전에 남은 물리 메모리에서 여유분(reserve)을 뺀 만큼만 쓰고, 채우는 동안에도 주기적으로 다시 본다.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass

from ..config import constants as C

GIB = 2 ** 30


@dataclass(frozen=True)
class MemoryStatus:
    total: int        # 물리 메모리 전체 (bytes)
    available: int    # 지금 바로 쓸 수 있는 물리 메모리 (bytes)


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def system_memory() -> MemoryStatus | None:
    """물리 메모리 상태. 알 수 없으면 None."""
    try:
        if sys.platform == "win32":
            st = _MemoryStatusEx()
            st.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
                return None
            return MemoryStatus(int(st.ullTotalPhys), int(st.ullAvailPhys))
        page = os.sysconf("SC_PAGE_SIZE")
        return MemoryStatus(int(os.sysconf("SC_PHYS_PAGES") * page), int(os.sysconf("SC_AVPHYS_PAGES") * page))
    except (AttributeError, OSError, ValueError):
        return None


def reserve_bytes(total: int) -> int:
    """캐시를 채우는 동안에도 시스템에 남겨 둘 물리 메모리."""
    return int(max(C.DRAW_FULL_CACHE_RESERVE_MIN_GB * GIB, total * C.DRAW_FULL_CACHE_RESERVE_RATIO))


def full_cache_budget(mem: MemoryStatus) -> int:
    """지금 전체 캐시에 새로 쓸 수 있는 bytes (남은 메모리 - 여유분)."""
    return max(0, mem.available - reserve_bytes(mem.total))


def plan_cache_range(frame_count: int, frame_bytes: int, current: int, budget: int,
                     already_cached: int = 0) -> tuple[int, int]:
    """캐시할 [start, end] (end 포함). 영상 전체가 예산에 들어가면 0 ~ 끝, 아니면 현재 프레임을 가운데로 한 창.

    already_cached 는 이 영상에서 이미 올라가 있는 프레임 수 — 다시 채울 때 그만큼은 새로 안 든다.
    예산이 한 프레임도 안 되면 (current, current - 1) 처럼 빈 범위를 돌려준다.
    """
    frame_count = max(0, int(frame_count))
    if frame_count == 0 or frame_bytes <= 0:
        return 0, -1
    fit = budget // frame_bytes + max(0, int(already_cached))
    if fit >= frame_count:
        return 0, frame_count - 1
    if fit <= 0:
        return current, current - 1
    current = max(0, min(int(current), frame_count - 1))
    start = max(0, current - fit // 2)
    end = start + fit - 1
    if end > frame_count - 1:
        end = frame_count - 1
        start = end - fit + 1
    return start, end


def format_gib(n: int) -> str:
    return f"{n / GIB:.1f} GB"
