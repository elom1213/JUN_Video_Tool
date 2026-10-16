# -*- coding: utf-8 -*-
"""시작 메뉴 · 작업표시줄 통합의 순수 부분 (명령 · 경로)."""
from pathlib import Path

import pytest

from app.core import shell_integration as si


def test_launch_spec_prefers_pythonw(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"")
    (tmp_path / "pythonw.exe").write_bytes(b"")
    root = tmp_path / "tool"
    spec = si.launch_spec(exe, root)
    assert spec.target == tmp_path / "pythonw.exe"
    assert spec.arguments == f'"{root / "launch.py"}"'
    assert spec.workdir == root
    assert spec.icon == root / "app" / "ui" / "icons" / "app.ico"
    assert spec.command_line == f'"{tmp_path / "pythonw.exe"}" "{root / "launch.py"}"'


def test_launch_spec_keeps_python_without_pythonw(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"")
    assert si.launch_spec(exe, tmp_path).target == exe


def test_shortcut_paths(monkeypatch):
    monkeypatch.setenv("APPDATA", r"C:\Users\x\AppData\Roaming")
    assert si.start_menu_shortcut() == Path(r"C:\Users\x\AppData\Roaming\Microsoft\Windows\Start Menu\Programs"
                                            r"\JUN Video Tool.lnk")
    assert si.taskbar_pinned_dir() == Path(r"C:\Users\x\AppData\Roaming\Microsoft\Internet Explorer\Quick Launch"
                                           r"\User Pinned\TaskBar")


@pytest.mark.skipif(not si.is_supported(), reason="Windows only")
def test_create_shortcut_writes_app_id(tmp_path):
    lnk = tmp_path / "sub" / "JUN Video Tool.lnk"
    si.create_shortcut(lnk)                     # 앱 ID 를 다시 읽어 확인하지 못하면 예외
    assert lnk.is_file() and lnk.stat().st_size > 0
