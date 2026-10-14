# -*- coding: utf-8 -*-
"""size_estimator 순수 함수 테스트."""
from pathlib import Path

from app.core.converters import GifOptions
from app.core.models import FrameRange
from app.core.size_estimator import (heuristic_gif_size, make_est_key, output_frames, pick_sample_ranges,
                                     scale_sample)


def test_pick_sample_ranges_two_segments():
    rngs = pick_sample_ranges(FrameRange(0, 899), 30, 15, n=2, out_frames_each=24)
    assert len(rngs) == 2
    for r in rngs:
        assert r.frame_count == 48
    assert abs((rngs[0].start_frame + rngs[0].end_frame) // 2 - 225) <= 1
    assert abs((rngs[1].start_frame + rngs[1].end_frame) // 2 - 675) <= 1


def test_pick_sample_ranges_short_clip_is_full():
    assert pick_sample_ranges(FrameRange(0, 59), 30, 15) == [FrameRange(0, 59)]


def test_scale_sample():
    assert scale_sample([40_000, 60_000], [24, 24], 450) == 800 + round(100_000 / 48 * 450)


def test_output_frames():
    assert output_frames(12.0, 15) == 180
    assert output_frames(0.0, 15) == 1


def test_heuristic_formula():
    assert heuristic_gif_size(300, 640, 360, 144, "bayer") == 800 + 21_859_200


def test_est_key_ignores_output_fields():
    p = Path("a.mp4")
    r = FrameRange(0, 10)
    k1 = make_est_key(p, r, GifOptions(quality=50, suffix="_a", overwrite=False))
    k2 = make_est_key(p, r, GifOptions(quality=50, suffix="_b", overwrite=True, output_dir=Path("x")))
    k3 = make_est_key(p, r, GifOptions(quality=51))
    assert k1 == k2
    assert k1 != k3
    assert k1 != make_est_key(p, FrameRange(0, 11), GifOptions(quality=50))
