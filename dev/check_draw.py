# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""Draw 탭 통합 검증 (PLAN_DRAW_TAB 9.2, 12장, 13.8). 오프스크린 Qt 로 실제 위젯을 돌린다.

    python dev/check_draw.py [--keep]

1. 합성 영상(testsrc 1280x720 29.97 fps 300 프레임, H.264 B-프레임 + 사인파 오디오)을 만든다.
2. 0번부터 순차 디코드한 각 프레임의 해시 = 정답. 시크 디코드(FrameStream start=i)가 같은 해시인지 본다 (프레임 정확성).
3. MainWindow 의 Draw 탭에 영상을 넣고 → 키 30번 = 프레임 30 (해시 · 타임코드 00:00:01:00), 재생 · 정지, 가운데 드래그 스크럽,
   선 그리기 · 지우개 · Undo, 사이드카 저장 → 새 창에서 자동 로드, MP4 · GIF 내보내기의 그림 위치(프레임 30) 픽셀 검증.
설정은 별도 범위(JUN_VIDEO_TOOL_SETTINGS_SCOPE)를 써서 사용자 설정을 건드리지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["JUN_VIDEO_TOOL_SETTINGS_SCOPE"] = "JUN_Video_Tool_check_draw"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.drawing import sidecar_path  # noqa: E402
from app.core.ffmpeg_locator import find_ffmpeg  # noqa: E402
from app.core.frame_decoder import FrameStream, make_decode_spec  # noqa: E402
from app.core.media_probe import probe  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  ok   " if cond else "  FAIL ") + label)
    if not cond:
        FAILS.append(label)


def pump(app: QApplication, sec: float, cond=lambda: False) -> bool:
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    app.processEvents()
    return cond()


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def qimage_bytes(img) -> bytes:
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    raw = bytes(img.constBits())
    return b"".join(raw[y * bpl: y * bpl + w * 3] for y in range(h))


def make_source(ff: Path, out: Path) -> None:
    subprocess.run([str(ff), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30000/1001",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-frames:v", "300", "-shortest", "-c:v", "libx264", "-bf", "3", "-g", "60",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)], check=True)


def sequential_hashes(ff: Path, path: Path, hwaccel: str = "none") -> list[str]:
    spec = make_decode_spec(probe(path))
    fs = FrameStream(ff, path, spec, 0, hwaccel)
    out = []
    while (got := fs.read_frame()) is not None:
        out.append(md5(got[1]))
    fs.close()
    return out


def read_frames(ff: Path, path: Path, frames: list[int]) -> dict[int, tuple[bytes, int, int]]:
    info = probe(path)
    spec = make_decode_spec(info, max_width=info.width)
    fs = FrameStream(ff, path, spec, 0, "none")
    want = set(frames)
    out = {}
    while (got := fs.read_frame()) is not None and want:
        if got[0] in want:
            out[got[0]] = (got[1], spec.out_w, spec.out_h)
            want.discard(got[0])
    fs.close()
    return out


def pixel(frame: tuple[bytes, int, int], x: int, y: int) -> tuple[int, int, int]:
    data, w, _h = frame
    i = (y * w + x) * 3
    return data[i], data[i + 1], data[i + 2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep the temp folder")
    args = ap.parse_args()
    ff = find_ffmpeg()
    if ff is None:
        print("ffmpeg not found")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="jun_check_draw_"))
    src = tmp / "testsrc.mp4"
    QSettings("JUN", "JUN_Video_Tool_check_draw").clear()
    app = QApplication([])
    try:
        print("[1] synthetic source")
        make_source(ff, src)
        info = probe(src)
        check(info.frame_count == 300 and info.has_audio, f"probe: {info.frame_count} frames, audio={info.has_audio}")

        print("[2] seek accuracy (FrameStream)")
        seq = sequential_hashes(ff, src)
        check(len(seq) == 300, f"sequential decode: {len(seq)} frames")
        spec = make_decode_spec(info)
        picks = sorted({0, 1, 2, 29, 30, 31, 59, 60, 61, 89, 90, 150, 238, 299} | set(random.sample(range(300), 12)))
        bad = []
        for i in picks:
            fs = FrameStream(ff, src, spec, i, "none")
            got = fs.read_frame()
            fs.close()
            if got is None or md5(got[1]) != seq[i]:
                near = [j for j in range(max(0, i - 3), min(300, i + 4)) if got and md5(got[1]) == seq[j]]
                bad.append((i, near))
        check(not bad, f"seek start frame == sequential frame for {len(picks)} picks" + (f" (bad: {bad})" if bad else ""))

        print("[3] Draw tab")
        from app.ui.main_window import MainWindow
        from app.ui.styles import load_stylesheet
        app.setStyleSheet(load_stylesheet("dark"))
        w = MainWindow()
        w.resize(1280, 760)
        w.show()
        pump(app, 0.3)
        w.tabs.setCurrentIndex(1)
        dt = w.draw_tab
        c = dt.controller
        check(w.m_draw.isEnabled() and not w.m_convert.isEnabled(), "Draw menu active, Convert menu disabled")
        dt.add_paths([src])
        check(pump(app, 10, lambda: c.item() is not None and dt.canvas._image is not None), "video selected, frame 0 shown")
        check(dt.model.data(dt.model.index(0), Qt.ItemDataRole.CheckStateRole) is None, "draw list has no checkbox")
        dt.canvas.setFocus()
        pump(app, 0.5, lambda: dt.provider.cached(24) is not None)
        t0 = time.time()
        for _ in range(30):
            QTest.keyClick(dt.canvas, Qt.Key.Key_Right)
            pump(app, 2, lambda: dt.provider.cached(c.frame()) is not None)
        check(c.frame() == 30, f"Right x30 -> frame {c.frame()} ({time.time() - t0:.2f} s)")
        # 하드웨어 디코드는 픽셀이 소프트웨어와 다르므로 앱과 같은 모드로 만든 정답과 비교한다
        hw = dt.provider._hwaccel
        ref = seq if hw == "none" else sequential_hashes(ff, src, hw)
        img = dt.provider.cached(30)
        got = md5(qimage_bytes(img)) if img is not None else ""
        idx = ref.index(got) if got in ref else None
        check(idx == 30, f"frame 30 image == sequential frame 30 (hwaccel={hw}, matched {idx})")
        check(dt.transport.tc_label.text() == "00:00:01:00", f"timecode {dt.transport.tc_label.text()}")
        QTest.keyClick(dt.canvas, Qt.Key.Key_Left, Qt.KeyboardModifier.ShiftModifier)
        pump(app, 0.2)
        check(c.frame() == 20, f"Shift+Left -> frame {c.frame()}")
        QTest.keyClick(dt.canvas, Qt.Key.Key_End)
        check(pump(app, 5, lambda: dt.canvas._image_frame == 299), f"End -> frame {c.frame()} shown")
        miss = 0
        for _ in range(12):
            before_hit = dt.provider.cached(c.frame() - 1) is not None
            miss += 0 if before_hit else 1
            QTest.keyClick(dt.canvas, Qt.Key.Key_Left)
            pump(app, 2, lambda: dt.provider.cached(c.frame()) is not None)
        check(miss <= 1 and c.frame() == 287, f"Left x12 from end -> frame {c.frame()}, cache misses {miss}")
        QTest.keyClick(dt.canvas, Qt.Key.Key_Home)
        pump(app, 3, lambda: dt.canvas._image_frame == 0)

        print("[4] playback")
        seen: list[int] = []
        c.frame_changed.connect(seen.append)
        QTest.keyClick(dt.canvas, Qt.Key.Key_Space)
        check(c.is_playing(), "Space -> playing")
        pump(app, 2.0)
        QTest.keyClick(dt.canvas, Qt.Key.Key_Space)
        c.frame_changed.disconnect(seen.append)
        gaps = [b - a for a, b in zip(seen, seen[1:]) if b - a != 1]
        check(not c.is_playing() and len(seen) >= 30, f"played {len(seen)} frames in 2 s (expect ~60)")
        check(not gaps, "no skipped frames during playback" + (f" (gaps {gaps[:5]})" if gaps else ""))
        stop_frame = c.frame()
        pump(app, 0.3)
        check(c.frame() == stop_frame, "paused stays on frame")

        print("[5] middle-drag scrub")
        c.seek(100)
        pump(app, 3, lambda: dt.canvas._image_frame == 100)
        cv = dt.canvas
        r = cv.video_rect()
        y = int(r.center().y())
        x0 = int(r.center().x())
        QTest.mousePress(cv, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, QPoint(x0, y))
        for dx in (8, 16, 24, 40):
            QTest.mouseMove(cv, QPoint(x0 + dx, y))
            pump(app, 0.05)
        QTest.mouseRelease(cv, Qt.MouseButton.MiddleButton, Qt.KeyboardModifier.NoModifier, QPoint(x0 + 40, y))
        check(c.frame() == 105, f"middle drag +40 px at 8 px/frame -> frame {c.frame()}")
        doc = dt.doc
        check(doc is not None and doc.is_empty(), "middle drag does not draw")

        print("[6] draw / erase / undo")
        c.seek(30)
        pump(app, 3, lambda: dt.canvas._image_frame == 30)
        dt.brush_panel.set_state("#ff0000", 16, 64)
        p1, p2 = cv.screen_point(200, 360), cv.screen_point(1000, 360)
        QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1.toPoint())
        steps = 20
        for k in range(1, steps + 1):
            QTest.mouseMove(cv, QPoint(int(p1.x() + (p2.x() - p1.x()) * k / steps), int(p1.y())))
        QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p2.toPoint())
        pump(app, 0.1)
        s30 = doc.strokes_at(30) if doc else []
        check(len(s30) == 1 and len(s30[0].points) >= 10, f"stroke on frame 30 ({len(s30[0].points) if s30 else 0} points)")
        check(abs(s30[0].points[0][0] - 200) < 3 and abs(s30[0].points[-1][0] - 1000) < 3 if s30 else False,
              "stroke stored in source pixels")
        check(dt.transport.slider._markers == [30], f"timeline markers {dt.transport.slider._markers}")
        check(w.windowTitle().endswith("testsrc.mp4*"), f"title shows dirty: {w.windowTitle()}")
        # Erase 툴로 가운데를 세로로 긁는다 → 둘로 갈라짐
        QTest.keyClick(cv, Qt.Key.Key_E)
        check(dt.act_tool_erase.isChecked(), "E -> Erase tool")
        e1, e2 = cv.screen_point(600, 250), cv.screen_point(600, 470)
        QTest.mousePress(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, e1.toPoint())
        QTest.mouseMove(cv, e2.toPoint())
        QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, e2.toPoint())
        pump(app, 0.1)
        check(len(doc.strokes_at(30)) == 2, f"erase splits stroke into {len(doc.strokes_at(30))}")
        QTest.keyClick(cv, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        pump(app, 0.1)
        check(len(doc.strokes_at(30)) == 1 and len(doc.strokes_at(30)[0].points) == len(s30[0].points), "Ctrl+Z restores")
        QTest.keyClick(cv, Qt.Key.Key_D)
        check(dt.act_tool_draw.isChecked(), "D -> Draw tool")
        # 고스트 범위 안 프레임에서 앞 프레임 선이 보이는지 (렌더 결과로 확인)
        dt.ghost_panel.set_state(True, 2, 2, 1.0)
        c.seek(31)
        pump(app, 3, lambda: dt.canvas._image_frame == 31)
        grab = cv.grab().toImage()
        gp = cv.screen_point(600, 360).toPoint()
        col = grab.pixelColor(gp)
        check(col.red() > 200 and col.green() < 80, f"ghost of frame 30 visible on 31 ({col.name()})")
        dt.ghost_panel.set_state(False, 2, 2, 1.0)
        grab = cv.grab().toImage()
        col2 = grab.pixelColor(gp)
        check(col2.name() != col.name(), "ghost off hides it")

        print("[7] save -> reopen -> auto-load")
        check(dt.save(), "Ctrl+S save")
        side = sidecar_path(src)
        check(side.is_file(), f"sidecar {side.name} written")
        check(not doc.dirty and not w.windowTitle().endswith("*"), "dirty cleared")
        w.close()
        pump(app, 0.5)
        w2 = MainWindow()
        w2.show()
        pump(app, 0.3)
        check(w2.tabs.currentIndex() == 1, "Draw tab restored as current tab")
        d2 = w2.draw_tab
        check(d2.brush_panel.color() == "#ff0000" and d2.brush_panel.brush_width() == 16, "brush settings restored")
        d2.add_paths([src])
        check(pump(app, 10, lambda: d2.doc is not None), "video selected in new window")
        check(d2.doc is not None and len(d2.doc.strokes_at(30)) == 1, "drawing auto-loaded from sidecar")
        log = d2.log.toPlainText()
        check("Loaded drawing: testsrc.mp4.draw.json (1 frame, 1 stroke)" in log, "load log line")

        print("[8] export with drawing")
        from app.core.converters import GifConverter, GifOptions, Mp4Converter, Mp4Options
        from app.ui.widgets.draw.export_worker import ExportWorker
        item = d2.controller.item()
        results = {}
        for conv, opts, name in ((Mp4Converter(), Mp4Options(quality=90, audio="aac", hwaccel="none"), "out_draw.mp4"),
                                 (GifConverter(), GifOptions(width=640, quality=90, fps_mode="source", hwaccel="none"),
                                  "out_draw.gif")):
            out = tmp / name
            wk = ExportWorker(ff, item, conv, opts, out, d2.doc, None)
            res: dict = {}
            wk.finished_ok.connect(lambda p, size, sec, r=res: r.update(ok=(p, size, sec)))
            wk.failed.connect(lambda m, r=res: r.update(err=m))
            wk.start()
            pump(app, 120, lambda: wk.isFinished())
            pump(app, 0.2)
            check("ok" in res, f"{name}: {res.get('err') or 'exported %.1f KB in %.1f s' % (res['ok'][1] / 1024, res['ok'][2])}")
            results[name] = out
        frames_src = read_frames(ff, src, [29, 30, 31])
        for name, out in results.items():
            if not out.is_file():
                continue
            oi = probe(out)
            sx = oi.width / 1280
            fr = read_frames(ff, out, [29, 30, 31])
            check(oi.frame_count == 300 or name.endswith(".gif"), f"{name}: {oi.width}x{oi.height}, {oi.frame_count} frames")
            px, py = int(600 * sx), int(360 * sx)
            on = pixel(fr[30], px, py) if 30 in fr else (0, 0, 0)
            check(on[0] > 180 and on[1] < 90 and on[2] < 90, f"{name}: frame 30 has the red stroke {on}")
            for f in (29, 31):
                if f not in fr:
                    continue
                o = pixel(fr[f], px, py)
                srcp = pixel(frames_src[f], 600, 360)
                check(not (o[0] > 180 and o[1] < 90 and o[2] < 90 and not (srcp[0] > 180 and srcp[1] < 90)),
                      f"{name}: frame {f} has no stroke {o}")
        w2.close()
        pump(app, 0.5)
    finally:
        QSettings("JUN", "JUN_Video_Tool_check_draw").clear()
        if args.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
