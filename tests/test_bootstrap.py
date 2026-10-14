# -*- coding: utf-8 -*-
"""bootstrap / dependency_check 테스트 (네트워크 없음)."""
import json
import zipfile
from pathlib import Path

import bootstrap
from app.core.dependency_check import parse_requirements, satisfies, version_tuple


def test_version_tuple_and_satisfies():
    assert version_tuple("6.11.1") == (6, 11, 1)
    assert version_tuple("7.0.0rc1") == (7, 0, 0)
    assert satisfies("6.11.1", ">=6.8,<7")
    assert not satisfies("7.0.0", ">=6.8,<7")
    assert not satisfies("6.7.9", ">=6.8,<7")
    assert satisfies("6.8", "==6.*")
    assert satisfies("1.2.3", "")
    assert satisfies("6.9.0", "~=6.8")


def test_parse_requirements(tmp_path: Path):
    f = tmp_path / "req.txt"
    f.write_text("# comment\nPySide6>=6.8,<7\n\npytest>=7  # dev\n-r other.txt\n", encoding="utf-8")
    assert parse_requirements(f) == [("PySide6", ">=6.8,<7"), ("pytest", ">=7")]


def test_match_member_and_safe_basename():
    assert bootstrap.match_member("ffmpeg-7.1-essentials_build/bin/ffmpeg.exe", "*/bin/ffmpeg.exe")
    assert bootstrap.match_member("x\\bin\\FFMPEG.EXE", "*/bin/ffmpeg.exe")
    assert not bootstrap.match_member("ffmpeg-7.1/doc/ffmpeg.exe", "*/bin/ffmpeg.exe")
    assert bootstrap.safe_basename("../../bin/ffmpeg.exe") == "ffmpeg.exe"
    assert bootstrap.safe_basename("a\\b\\ffprobe.exe") == "ffprobe.exe"


def test_extract_members(tmp_path: Path):
    z = tmp_path / "ff.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("ffmpeg-7.1-essentials_build/bin/ffmpeg.exe", b"MZ-ffmpeg")
        zf.writestr("ffmpeg-7.1-essentials_build/bin/ffprobe.exe", b"MZ-ffprobe")
        zf.writestr("ffmpeg-7.1-essentials_build/doc/ffmpeg.exe", b"not this")
    out = tmp_path / "bin"
    missing = bootstrap.extract_members(z, ["ffmpeg.exe", "ffprobe.exe", "ffplay.exe"], "*/bin/{name}", out)
    assert missing == ["ffplay.exe"]
    assert (out / "ffmpeg.exe").read_bytes() == b"MZ-ffmpeg"
    assert (out / "ffprobe.exe").read_bytes() == b"MZ-ffprobe"


def test_deps_json_schema():
    deps = json.loads((bootstrap.ROOT / "deps.json").read_text(encoding="utf-8"))
    assert deps["python"]["min"] == "3.11"
    ff = deps["binaries"][0]
    assert ff["name"] == "ffmpeg"
    assert set(ff["files"]) == {"ffmpeg.exe", "ffprobe.exe"}
    assert all("members_glob" in s and "url" in s for s in ff["sources"])


def test_report_json_keys():
    deps = bootstrap.load_deps()
    items = bootstrap.build_report(deps)
    assert items, "report must not be empty"
    for it in items:
        assert set(it) == {"name", "kind", "required", "found", "status", "location"}
    assert items[0]["name"] == "Python"
