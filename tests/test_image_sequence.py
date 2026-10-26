# -*- coding: utf-8 -*-
"""이미지 시퀀스 묶기 · ffmpeg 입력 인자 · 출력 이름 (core/image_sequence.py)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import constants as C
from app.core import image_sequence as seq
from app.core.media_probe import sequence_info
from app.core.models import MediaInfo
from app.core.utils import make_output_path


def _touch(folder: Path, *names: str) -> None:
    for n in names:
        (folder / n).write_bytes(b"x" * 10)


@pytest.fixture(autouse=True)
def _reset_fps():
    seq.set_sequence_fps(C.SEQUENCE_FPS_DEFAULT)
    yield
    seq.set_sequence_fps(C.SEQUENCE_FPS_DEFAULT)


def test_padded_sequence(tmp_path: Path) -> None:
    _touch(tmp_path, *(f"img.{i:03d}.jpg" for i in range(1, 121)))
    s = seq.sequence_of(tmp_path / "img.001.jpg")
    assert s is not None and s.numbered
    assert (s.prefix, s.width, s.suffix, s.start, s.count) == ("img.", 3, ".jpg", 1, 120)
    assert s.display_name() == "img.[001-120].jpg"
    assert s.stem() == "img"
    assert s.frame_path(9).name == "img.010.jpg"
    assert s.frame_path(999).name == "img.120.jpg"
    assert s.total_bytes() == 1200


def test_collapse_many_frames_to_first(tmp_path: Path) -> None:
    _touch(tmp_path, *(f"img.{i:03d}.jpg" for i in range(1, 11)), "other.mp4")
    dropped = [tmp_path / f"img.{i:03d}.jpg" for i in (5, 1, 2, 3)] + [tmp_path / "other.mp4"]
    assert seq.collapse(dropped) == [tmp_path / "img.001.jpg", tmp_path / "other.mp4"]
    # 한 장만 놓아도 시퀀스 전체 (첫 프레임으로)
    assert seq.collapse([tmp_path / "img.007.jpg"]) == [tmp_path / "img.001.jpg"]


def test_gap_splits_sequence(tmp_path: Path) -> None:
    # ffmpeg image2 는 첫 빈 번호에서 멈춘다 → 끊긴 곳에서 두 시퀀스
    _touch(tmp_path, *(f"a_{i:04d}.png" for i in (1, 2, 3, 7, 8)))
    out = seq.collapse(sorted(tmp_path.iterdir()))
    assert [p.name for p in out] == ["a_0001.png", "a_0007.png"]
    assert seq.sequence_of(out[0]).count == 3
    assert seq.sequence_of(out[1]).count == 2
    assert seq.display_name(out[1]) == "a_[0007-0008].png"
    assert seq.media_stem(out[0]) == "a"


def test_sequence_of_starts_at_given_file(tmp_path: Path) -> None:
    _touch(tmp_path, *(f"f{i:02d}.tif" for i in range(0, 10)))
    s = seq.sequence_of(tmp_path / "f04.tif")
    assert (s.start, s.count) == (4, 6)
    assert seq.first_frame(tmp_path / "f04.tif") == tmp_path / "f00.tif"


def test_unpadded_numbers(tmp_path: Path) -> None:
    _touch(tmp_path, *(f"shot{i}.png" for i in range(8, 13)))
    s = seq.sequence_of(seq.first_frame(tmp_path / "shot10.png"))
    assert (s.width, s.start, s.count) == (1, 8, 5)
    assert s.pattern.endswith("shot%01d.png")


def test_single_image_without_number(tmp_path: Path) -> None:
    _touch(tmp_path, "photo.jpg")
    s = seq.sequence_of(tmp_path / "photo.jpg")
    assert s is not None and not s.numbered and s.count == 1
    assert seq.display_name(tmp_path / "photo.jpg") == "photo.jpg"
    args = seq.input_args(tmp_path / "photo.jpg", 30)
    assert args[:4] == ["-f", "image2", "-pattern_type", "none"] and args[-1] == str(tmp_path / "photo.jpg")


def test_input_args(tmp_path: Path) -> None:
    _touch(tmp_path, *(f"100%_v.{i:03d}.jpg" for i in range(5, 9)), "clip.mp4")
    first = tmp_path / "100%_v.005.jpg"
    args = seq.input_args(first, 25)
    assert args == ["-f", "image2", "-pattern_type", "sequence", "-framerate", "25", "-start_number", "5",
                    "-i", str(tmp_path / "100%%_v.%03d.jpg")]
    seq.set_sequence_fps(12.5)
    assert seq.input_args(first)[5] == "12.5"
    assert seq.input_args(tmp_path / "clip.mp4") == ["-i", str(tmp_path / "clip.mp4")]


def test_sequence_fps_bounds() -> None:
    seq.set_sequence_fps(500)
    assert seq.sequence_fps() == C.SEQUENCE_FPS_DEFAULT
    seq.set_sequence_fps(30)
    assert seq.sequence_fps() == 30.0


def test_sequence_info() -> None:
    still = MediaInfo(width=1921, height=1081, fps=0.0, duration=0.0, frame_count=1, codec="mjpeg", size_bytes=0)
    info = sequence_info(still, 48, 24.0, 1234)
    assert info.sequence and not info.has_audio
    assert (info.frame_count, info.duration, info.fps, info.width) == (48, 2.0, 24.0, 1921)
    assert info.last_frame == 47


def test_output_name_drops_frame_number(tmp_path: Path) -> None:
    _touch(tmp_path, *(f"img.{i:03d}.jpg" for i in range(1, 4)))
    out = make_output_path(tmp_path / "img.001.jpg", None, "_gif", ".gif", False)
    assert out == tmp_path / "img_gif.gif"
    _touch(tmp_path, "0001.png", "0002.png")
    assert make_output_path(tmp_path / "0001.png", None, "", ".mp4", False).name == f"{tmp_path.name}.mp4"
