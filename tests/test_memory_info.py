# -*- coding: utf-8 -*-
"""전체 프레임 캐시 예산 · 범위 계산 (memory_info)."""
from app.core.memory_info import GIB, MemoryStatus, full_cache_budget, plan_cache_range, reserve_bytes, system_memory


def test_reserve_bytes():
    assert reserve_bytes(16 * GIB) == 4 * GIB             # 최소 4 GB
    assert reserve_bytes(32 * GIB) == int(32 * GIB * 0.15)
    assert reserve_bytes(96 * GIB) == int(96 * GIB * 0.15)


def test_full_cache_budget():
    assert full_cache_budget(MemoryStatus(32 * GIB, 20 * GIB)) == 20 * GIB - int(32 * GIB * 0.15)
    assert full_cache_budget(MemoryStatus(32 * GIB, 2 * GIB)) == 0


def test_plan_whole_fits():
    assert plan_cache_range(300, 10, 150, 3000) == (0, 299)
    assert plan_cache_range(300, 10, 150, 10 ** 9) == (0, 299)


def test_plan_window_centered():
    a, b = plan_cache_range(1000, 10, 500, 1000)          # 100 프레임만 들어감
    assert (a, b) == (450, 549)


def test_plan_window_clamped_to_edges():
    assert plan_cache_range(1000, 10, 5, 1000) == (0, 99)
    assert plan_cache_range(1000, 10, 995, 1000) == (900, 999)


def test_plan_counts_already_cached():
    # 예산은 50 프레임뿐이지만 이미 260 프레임이 올라가 있으면 300 전체를 다시 채울 수 있다
    assert plan_cache_range(300, 10, 0, 500, already_cached=260) == (0, 299)


def test_plan_nothing_fits():
    a, b = plan_cache_range(1000, 10, 40, 5)
    assert b < a
    assert plan_cache_range(0, 10, 0, 1000) == (0, -1)


def test_system_memory_reads():
    mem = system_memory()
    assert mem is not None
    assert mem.total > 0 and 0 < mem.available <= mem.total
