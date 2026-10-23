# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-23
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

from PySide6.QtCore import QPoint, QPointF, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core.drawing import legacy_sidecar_path, sidecar_path  # noqa: E402
from app.core.ffmpeg_locator import find_ffmpeg  # noqa: E402
from app.core.frame_decoder import FrameStream, make_decode_spec  # noqa: E402
from app.core.media_probe import probe  # noqa: E402
from app.ui.widgets.draw.geometry import to_video  # noqa: E402

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
    spec = make_decode_spec(info)
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
        # 툴 크기 원: 브러시 16 px, 지우개 64 px (소스) × 화면 배율
        sc = cv.video_rect().height() / 720
        mid = cv.screen_point(640, 360).toPoint()
        QTest.mouseMove(cv, mid)
        pump(app, 0.05)
        check(abs(cv.tool_outline_radius() - 8 * sc) < 1e-6, f"brush outline radius {cv.tool_outline_radius():.2f} px")
        check(cv.cursor().shape() == Qt.CursorShape.BlankCursor, "system cursor hidden over video (outline is the cursor)")
        ring_pt = QPoint(mid.x() + round(8 * sc), mid.y())
        ring = cv.grab().toImage().pixelColor(ring_pt)
        cv.leaveEvent(None)
        bare = cv.grab().toImage().pixelColor(ring_pt)
        QTest.mouseMove(cv, mid)
        check(ring.name() != bare.name(), f"outline ring drawn at radius ({bare.name()} -> {ring.name()})")
        QTest.keyClick(cv, Qt.Key.Key_E)
        QTest.mouseMove(cv, mid)
        check(abs(cv.tool_outline_radius() - 32 * sc) < 1e-6, f"eraser outline radius {cv.tool_outline_radius():.2f} px")
        QTest.keyClick(cv, Qt.Key.Key_D)
        # 그린 프레임으로 스냅 (Ctrl+←/→, 트랜스포트 버튼)
        doc.add_stroke(80, doc.strokes_at(30)[0].copy())
        dt._doc_changed()
        c.seek(0)
        pump(app, 3, lambda: dt.canvas._image_frame == 0)
        check(dt.transport.btn_next_drawn.isEnabled() and not dt.transport.btn_prev_drawn.isEnabled(),
              "snap buttons: next on, prev off at frame 0")
        QTest.keyClick(cv, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
        check(c.frame() == 30, f"Ctrl+Right -> drawn frame {c.frame()}")
        dt.transport.btn_next_drawn.click()
        check(c.frame() == 80, f"next-drawn button -> frame {c.frame()}")
        check(not dt.act_next_drawn.isEnabled(), "no drawn frame after 80 -> next disabled")
        c.seek(150)
        pump(app, 0.1)
        QTest.keyClick(cv, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
        check(c.frame() == 80, f"Ctrl+Left from 150 -> frame {c.frame()}")
        dt.transport.btn_prev_drawn.click()
        check(c.frame() == 30, f"prev-drawn button -> frame {c.frame()}")
        doc.undo(80)
        dt._doc_changed()
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
        check(side.is_file() and side.parent == src.parent / ".draw", f"sidecar written to {side.parent.name}/{side.name}")
        check(not legacy_sidecar_path(src).exists(), "nothing written next to the video")
        # 옛 위치(영상 옆) 파일도 읽히는지: 옮겨 두고 새 창에서 연다
        side.replace(legacy_sidecar_path(src))
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
        check("Loaded drawing: testsrc.mp4.draw.json (1 frame, 1 stroke)" in log, "legacy location loaded + log line")
        check("old location" in log, "old location notice")
        d2.doc.dirty = True
        check(d2.save() and side.is_file(), "next save goes to .draw folder")
        log = d2.log.toPlainText()
        check("Saved drawing: .draw/testsrc.mp4.draw.json" in log, "save log shows .draw path")

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

        print("[9] frame cache (Cache Whole Video / Free All Cache)")
        pv, cp = d2.provider, d2.cache_panel
        cp.cache_btn.click()
        check(pv.filling_name() == "testsrc.mp4" and cp.cache_btn.text() == "Stop Caching", "caching started")
        check(pump(app, 60, lambda: pv.filling_name() is None), "caching finished")
        pump(app, 0.2)
        check(pv.pinned_complete() and pv.pinned_frames() == 300, f"all frames pinned ({pv.pinned_frames()})")
        check(all(pv.cached(f) is not None for f in range(300)), "every frame is a cache hit")
        check("all 300 frames cached" in cp.video_label.text(), f"panel: {cp.video_label.text()}")
        check(d2.transport.slider._cached == [(0, 299)], f"timeline cached range {d2.transport.slider._cached[:3]}")
        check("Cached testsrc.mp4: 300 frames" in d2.log.toPlainText(), "cache log line")
        img = pv.cached(30)
        check(img is not None and md5(qimage_bytes(img)) == ref[30], "pinned frame 30 == sequential frame 30")
        d2.controller.set_video(item, "none")
        check(pv.pinned_complete(), "pinned cache survives reloading the video")
        nbytes, nvid = pv.pinned_total()
        cp.free_btn.click()
        pump(app, 0.2)
        check(pv.pinned_total() == (0, 0) and pv.pinned_frames() == 0, f"free all cache ({nbytes >> 20} MB, {nvid} video)")
        check(cp.total_label.text() == "In memory: none" and d2.transport.slider._cached == [], "panel cleared")
        cp.cache_btn.click()
        cp.cache_btn.click()
        pump(app, 0.3)
        check(pv.filling_name() is None and "Stopped caching testsrc.mp4." in d2.log.toPlainText(), "stop caching")
        cp.free_btn.click()

        print("[10] decode resolution (Original / 75 / 50 / 25 %)")
        from PySide6.QtWidgets import QMessageBox
        cv2 = d2.canvas
        d2.controller.seek(30)
        pump(app, 5, lambda: cv2._image_frame == 30)
        texts = [cp.res_combo.itemText(i) for i in range(cp.res_combo.count())]
        check(texts == ["Original (1280x720)", "75% (960x540)", "50% (640x360)", "25% (320x180)"], f"combo {texts}")
        check(pv.spec.out_w == 1280 and cv2._image.width() == 1280, "default decodes at original size")
        cp.res_combo.setCurrentIndex(cp.res_combo.findData(50))
        check((pv.spec.out_w, pv.spec.out_h) == (640, 360), f"50% -> decode {pv.spec.out_w}x{pv.spec.out_h}")
        check(pump(app, 5, lambda: cv2._image is not None and cv2._image_frame == 30 and cv2._image.width() == 640),
              "frame 30 shown at 640x360")
        check(d2.controller.frame() == 30 and len(d2.doc.strokes_at(30)) == 1, "stays on frame 30, drawing kept")
        check(d2.settings.get("draw/decode_scale", 0, int) == 50, "resolution saved to settings")
        # 전체 캐시가 있으면 물어본다: No → 그대로, Yes → 해제 후 변경
        cp.cache_btn.click()
        pump(app, 30, lambda: pv.filling_name() is None)
        orig_q = QMessageBox.question
        try:
            QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
            cp.res_combo.setCurrentIndex(cp.res_combo.findData(25))
            check(cp.scale() == 50 and pv.spec.out_w == 640 and pv.pinned_complete(), "No keeps 50% and the cache")
            QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
            cp.res_combo.setCurrentIndex(cp.res_combo.findData(25))
            check(pv.spec.out_w == 320 and pv.pinned_total() == (0, 0), "Yes frees cache and switches to 25%")
        finally:
            QMessageBox.question = orig_q
        check(pump(app, 5, lambda: cv2._image is not None and cv2._image.width() == 320), "frame shown at 320x180")
        cp.res_combo.setCurrentIndex(cp.res_combo.findData(100))
        check(pump(app, 5, lambda: cv2._image is not None and cv2._image.width() == 1280), "back to original")

        print("[11] view flip (H / V / both)")
        d2.controller.seek(30)
        pump(app, 5, lambda: cv2._image_frame == 30)
        d2.ghost_panel.set_state(False, 2, 2, 1.0)
        d2.doc.clear_frame(30)
        d2._doc_changed()
        cv2.setFocus()
        cv2.leaveEvent(None)
        frame30 = pv.cached(30)

        def close(a, b, tol=24):
            return all(abs(x - y) <= tol for x, y in zip((a.red(), a.green(), a.blue()), (b.red(), b.green(), b.blue())))

        def is_red(c):
            return c.red() > 200 and c.green() < 80

        def find_pair(cands):
            """소스 픽셀 쌍 중 색이 확실히 다른 첫 쌍 (반전 전후 비교용)."""
            for (ax, ay), (bx, by) in cands:
                if not close(frame30.pixelColor(ax, ay), frame30.pixelColor(bx, by), 60):
                    return (ax, ay), (bx, by)
            return None

        def sp(x, y):
            return cv2.screen_point(x, y).toPoint()

        # --- 좌우: 소스 (x, y) 와 거울상 (1280 - x, y) 의 색이 다른 자리를 고른다 (testsrc 윗부분 색 막대)
        pair = find_pair([((x, y), (1280 - x, y)) for y in (100, 60, 200) for x in (100, 60, 200, 300)])
        check(pair is not None, f"found a left/right probe pair {pair}")
        (lx, ly), (rx, ry) = pair or ((100, 100), (1180, 100))
        pL, pR = sp(lx, ly), sp(rx, ry)
        plain = cv2.grab().toImage()
        cL, cR = plain.pixelColor(pL), plain.pixelColor(pR)
        QTest.keyClick(cv2, Qt.Key.Key_H)
        pump(app, 0.1)
        check(cv2.flip() == (True, False) and d2.act_flip_h.isChecked(), "H -> flip horizontal")
        flipped = cv2.grab().toImage()
        check(close(flipped.pixelColor(pL), cR) and close(flipped.pixelColor(pR), cL),
              f"image mirrored left<->right ({cL.name()}/{cR.name()} -> "
              f"{flipped.pixelColor(pL).name()}/{flipped.pixelColor(pR).name()})")
        check(sp(lx, ly) == pR and sp(rx, ry) == pL, "screen_point follows the flip")
        # 반전 중 소스 1080 → 280 자리(= 반전 전 화면의 200 → 1000 자리)에 긋는다: 문서에는 1080 → 280, 화면에는 마우스 자리
        q1, q2 = cv2.screen_point(1080, 360), cv2.screen_point(280, 360)
        QTest.mousePress(cv2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q1.toPoint())
        for k in range(1, 21):
            QTest.mouseMove(cv2, QPoint(int(q1.x() + (q2.x() - q1.x()) * k / 20), int(q1.y())))
        QTest.mouseRelease(cv2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q2.toPoint())
        pump(app, 0.1)
        st = d2.doc.strokes_at(30)
        check(len(st) == 1 and abs(st[0].points[0][0] - 1080) < 3 and abs(st[0].points[-1][0] - 280) < 3
              and abs(st[0].points[0][1] - 360) < 3,
              f"stroke stored mirrored in source pixels ({st[0].points[0] if st else None} -> "
              f"{st[0].points[-1] if st else None})")
        cv2.leaveEvent(None)
        near_q1 = QPoint(int(q1.x() + (q2.x() - q1.x()) * 0.1), int(q1.y()))     # 소스 1000 (반전 중 화면에선 q1 쪽)
        check(is_red(cv2.grab().toImage().pixelColor(near_q1)),
              f"stroke drawn under the mouse while flipped ({cv2.grab().toImage().pixelColor(near_q1).name()})")
        # 반전을 끄면 스트로크는 소스 자리(280 ~ 1080)로 간다: 화면의 q1 쪽(소스 200)은 비고, 소스 1000 자리는 빨갛다
        QTest.keyClick(cv2, Qt.Key.Key_H)
        pump(app, 0.1)
        check(cv2.flip() == (False, False), "H again -> flip off")
        off = cv2.grab().toImage()
        check(is_red(off.pixelColor(sp(1000, 360))) and is_red(off.pixelColor(sp(300, 360))),
              f"unflipped: stroke at source x=300..1000 ({off.pixelColor(sp(1000, 360)).name()})")
        old_spot = QPoint(int(q1.x() + (q2.x() - q1.x()) * 0.04), int(q1.y()))   # 반전 전 소스 232 (선 끝 280 밖)
        check(not is_red(off.pixelColor(sp(200, 360))) and not is_red(off.pixelColor(old_spot)),
              f"unflipped: nothing at source x=200 / old screen spot ({off.pixelColor(old_spot).name()})")
        # --- 상하
        pair = find_pair([((x, y), (x, 720 - y)) for x in (100, 640, 1000, 300) for y in (60, 100, 150, 250)])
        check(pair is not None, f"found a top/bottom probe pair {pair}")
        (tx, ty), (bx, by) = pair or ((640, 60), (640, 660))
        pT, pB = sp(tx, ty), sp(bx, by)
        plain = cv2.grab().toImage()
        cT, cB = plain.pixelColor(pT), plain.pixelColor(pB)
        QTest.keyClick(cv2, Qt.Key.Key_V)
        pump(app, 0.1)
        check(cv2.flip() == (False, True), "V -> flip vertical")
        flipped = cv2.grab().toImage()
        check(close(flipped.pixelColor(pT), cB) and close(flipped.pixelColor(pB), cT),
              f"image mirrored top<->bottom ({cT.name()}/{cB.name()} -> "
              f"{flipped.pixelColor(pT).name()}/{flipped.pixelColor(pB).name()})")
        # --- 둘 다 (메뉴 액션으로 H 추가): 소스 (x, y) 자리에 (1280 - x, 720 - y) 가 보인다
        pair = find_pair([((x, y), (1280 - x, 720 - y)) for x in (100, 300, 200) for y in (60, 100, 150, 250)])
        check(pair is not None, f"found a diagonal probe pair {pair}")
        (ax, ay), (dx, dy) = pair or ((100, 100), (1180, 620))
        d2.set_flip(False, False)
        pump(app, 0.1)
        pA, pD = sp(ax, ay), sp(dx, dy)          # 반전 없는 화면 자리
        plain = cv2.grab().toImage()
        cA, cD = plain.pixelColor(pA), plain.pixelColor(pD)
        d2.act_flip_v.trigger()
        d2.act_flip_h.trigger()
        pump(app, 0.1)
        check(cv2.flip() == (True, True) and d2.act_flip_h.isChecked() and d2.act_flip_v.isChecked(),
              "menu actions -> both axes")
        both = cv2.grab().toImage()
        check(close(both.pixelColor(pA), cD) and close(both.pixelColor(pD), cA),
              f"image mirrored on both axes ({cA.name()}/{cD.name()} -> "
              f"{both.pixelColor(pA).name()}/{both.pixelColor(pD).name()})")
        check(sp(ax, ay) == pD, "screen_point follows both flips")
        check("flipped horizontally and vertically" in d2.log.toPlainText(), "log line for both axes")
        d2.save_settings()
        check(d2.settings.get("draw/flip_h", False, bool) and d2.settings.get("draw/flip_v", False, bool),
              "flip saved to settings")
        d2.set_flip(False, False)
        pump(app, 0.1)
        check(cv2.flip() == (False, False) and "View flip off." in d2.log.toPlainText(), "set_flip(False, False)")
        d2.doc.clear_frame(30)
        d2._doc_changed()
        d2.doc.dirty = False          # 안 그러면 close 가 저장 여부를 묻는 모달에서 멈춘다

        print("[12] cache range (timeline handles <-> spin boxes)")
        sl = d2.transport.slider
        check(d2.cache_range() == (0, 299) and sl.cache_range() == (0, 299) and cp.cache_range() == (0, 299),
              "new video: range = whole video")
        check(cp.cache_btn.text() == "Cache Whole Video" and "whole video" in cp.range_info.text(),
              f"panel: {cp.cache_btn.text()} / {cp.range_info.text()}")
        # 스핀박스 → 타임라인
        cp.start_spin.setValue(100)
        cp.end_spin.setValue(150)
        pump(app, 0.1)
        check(d2.cache_range() == (100, 150) and sl.cache_range() == (100, 150),
              f"spin boxes 100-150 -> timeline {sl.cache_range()}")
        check(cp.cache_btn.text() == "Cache Range" and d2.act_cache_whole.text() == "Cache Range"
              and cp.range_info.text().startswith("51 frames"), f"panel: {cp.cache_btn.text()} / {cp.range_info.text()}")
        # 타임라인 끝 핸들 드래그 → 스핀박스
        playhead = d2.controller.frame()
        x_end, x_to = int(sl._xpos(150)), int(sl._xpos(200))
        QTest.mousePress(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x_end, 5))
        QTest.mouseMove(sl, QPoint(x_to, 5))
        QTest.mouseRelease(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x_to, 5))
        pump(app, 0.1)
        check(abs(sl.cache_range()[1] - 200) <= 1 and sl.cache_range()[0] == 100, f"drag end handle -> {sl.cache_range()}")
        check(cp.cache_range() == d2.cache_range() == sl.cache_range(), f"spin boxes follow {cp.cache_range()}")
        check(d2.controller.frame() == playhead, "dragging a range handle does not seek")
        a, b = d2.cache_range()
        # 시작 핸들을 끝 너머로 끌면 끝에서 멈춘다
        QTest.mousePress(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(sl._xpos(a)), 5))
        QTest.mouseMove(sl, QPoint(int(sl._xpos(290)), 5))
        QTest.mouseRelease(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(sl._xpos(290)), 5))
        pump(app, 0.1)
        check(d2.cache_range() == (b, b) and cp.cache_range() == (b, b), f"start handle stops at the end ({d2.cache_range()})")
        d2.set_cache_range(100, b)
        pump(app, 0.1)
        check(cp.cache_range() == (100, b) and sl.cache_range() == (100, b), "set_cache_range updates both")
        # 구간만 캐시
        cp.cache_btn.click()
        check(pump(app, 60, lambda: pv.filling_name() is None), "range caching finished")
        pump(app, 0.2)
        check(pv.pinned_ranges() == [(100, b)] and not pv.pinned_complete(), f"pinned {pv.pinned_ranges()}")
        check(cp.video_label.text() == f"This range: all {b - 100 + 1} frames cached.", f"panel: {cp.video_label.text()}")
        check(not cp.cache_btn.isEnabled() and "frames 100-" in d2.log.toPlainText(), "button off when range is cached")
        # 스핀박스 시작을 끝 너머로 → 끝이 따라온다
        cp.start_spin.setValue(250)
        pump(app, 0.1)
        check(d2.cache_range() == (250, 250) and sl.cache_range() == (250, 250), f"start spin 250 -> {d2.cache_range()}")
        check(cp.video_label.text() == "This range: not cached." and cp.cache_btn.isEnabled(), "new range not cached")
        cp.all_btn.click()
        pump(app, 0.1)
        check(d2.cache_range() == (0, 299) and cp.cache_btn.text() == "Cache Whole Video", "All -> whole video")
        check(f"This video: {b - 100 + 1} of 300 frames cached." == cp.video_label.text(), f"panel: {cp.video_label.text()}")
        cp.free_btn.click()
        pump(app, 0.2)

        print("[13] timeline zoom")
        zp, tr = d2.zoom_panel, d2.transport
        check(d2.timeline_zoom() == (0, 299) and (sl.minimum(), sl.maximum()) == (0, 299), "new video: whole timeline")
        check(tr.zoom_lo_label.text() == "0" and tr.zoom_hi_label.text() == "299" and zp.info.text() == "Whole video",
              f"labels {tr.zoom_lo_label.text()} / {tr.zoom_hi_label.text()} / {zp.info.text()}")
        check(not d2.act_zoom_reset.isEnabled() and not zp.reset_btn.isEnabled(), "reset disabled when whole")
        d2.controller.seek(60)
        pump(app, 3, lambda: cv2._image_frame == 60)
        # 패널 스핀박스 → 타임라인 양 끝
        zp.start_spin.setValue(50)
        zp.end_spin.setValue(70)
        pump(app, 0.1)
        check(d2.timeline_zoom() == (50, 70) and (sl.minimum(), sl.maximum()) == (50, 70),
              f"spin boxes 50-70 -> timeline ends {(sl.minimum(), sl.maximum())}")
        check(tr.zoom_lo_label.text() == "50" and tr.zoom_hi_label.text() == "70" and zp.info.text() == "21 of 300 frames",
              f"labels {tr.zoom_lo_label.text()} / {tr.zoom_hi_label.text()} / {zp.info.text()}")
        check(sl.value() == 60 and tr.spin.value() == 60, "playhead at 60 inside the zoom")
        check("Timeline zoomed to frames 50-70." in d2.log.toPlainText(), "log line")
        # 확대된 타임라인에서 핸들 드래그 = 그 범위 안의 프레임으로 시크 (그루브 클릭은 QSlider 기본대로 페이지 이동)
        ym = sl.height() // 2 + 2
        x60, x55 = int(sl._xpos(60)), int(sl._xpos(55))
        QTest.mousePress(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x60, ym))
        QTest.mouseMove(sl, QPoint(x55, ym))
        QTest.mouseRelease(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x55, ym))
        pump(app, 0.3)
        check(abs(d2.controller.frame() - 55) <= 1, f"drag playhead on zoomed timeline -> frame {d2.controller.frame()}")
        # 범위 밖 프레임: 핸들은 가장자리, 스핀 · 타임코드는 실제 프레임
        d2.controller.seek(20)
        pump(app, 3, lambda: cv2._image_frame == 20)
        check(d2.controller.frame() == 20 and tr.spin.value() == 20 and sl.value() == 50,
              f"frame 20 outside zoom: spin {tr.spin.value()}, slider handle at {sl.value()}")
        QTest.keyClick(cv2, Qt.Key.Key_Right)
        pump(app, 1, lambda: d2.controller.frame() == 21)
        check(d2.controller.frame() == 21, "stepping outside the zoom still works")
        # 시작을 끝까지 올리면 끝이 따라간다 / 끝을 시작 아래로 내리면 시작이 따라간다
        zp.start_spin.setValue(70)
        pump(app, 0.1)
        check(d2.timeline_zoom() == (70, 71), f"start spin 70 -> {d2.timeline_zoom()}")
        zp.end_spin.setValue(30)
        pump(app, 0.1)
        check(d2.timeline_zoom() == (29, 30), f"end spin 30 -> {d2.timeline_zoom()}")
        # 캐시 구간 핸들: 범위 밖이면 안 그려지고 안 잡힌다, 범위 안이면 끌 수 있다
        d2.set_cache_range(10, 200)
        d2.set_timeline_zoom(50, 70)
        pump(app, 0.1)
        check(sl._handle_hit(QPointF(sl._xpos(50), 5)) is None and sl._handle_hit(QPointF(sl._xpos(70), 5)) is None,
              "cache handles outside the zoom are not grabbable at the edges")
        d2.set_cache_range(55, 65)
        pump(app, 0.1)
        check(sl._handle_hit(QPointF(sl._xpos(65), 5)) == "end", "cache handle inside the zoom is grabbable")
        x65, x68 = int(sl._xpos(65)), int(sl._xpos(68))
        QTest.mousePress(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x65, 5))
        QTest.mouseMove(sl, QPoint(x68, 5))
        QTest.mouseRelease(sl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x68, 5))
        pump(app, 0.1)
        check(d2.cache_range()[0] == 55 and abs(d2.cache_range()[1] - 68) <= 1 and cp.cache_range() == d2.cache_range(),
              f"drag cache handle while zoomed -> {d2.cache_range()}")
        # Zoom to Cache Range (Z) / Reset (Shift+Z)
        d2.set_cache_range(100, 150)
        check(d2.act_zoom_cache.isEnabled() and zp.fit_btn.isEnabled(), "zoom-to-cache enabled when it differs")
        cv2.setFocus()
        QTest.keyClick(cv2, Qt.Key.Key_Z)
        pump(app, 0.1)
        check(d2.timeline_zoom() == (100, 150) and zp.zoom() == (100, 150) and (sl.minimum(), sl.maximum()) == (100, 150),
              f"Z -> zoom to cache range {d2.timeline_zoom()}")
        check(not d2.act_zoom_cache.isEnabled() and d2.act_zoom_reset.isEnabled(), "actions: fit off, reset on")
        QTest.keyClick(cv2, Qt.Key.Key_Z, Qt.KeyboardModifier.ShiftModifier)
        pump(app, 0.1)
        check(d2.timeline_zoom() == (0, 299) and zp.zoom() == (0, 299) and tr.zoom_hi_label.text() == "299",
              f"Shift+Z -> whole {d2.timeline_zoom()}")
        zp.fit_btn.click()
        pump(app, 0.1)
        check(d2.timeline_zoom() == (100, 150), "panel button -> zoom to cache range")
        zp.reset_btn.click()
        pump(app, 0.1)
        check(d2.timeline_zoom() == (0, 299), "panel Reset -> whole")
        # Get Zoom: 캐시 구간 = 확대 구간 (Zoom to Cache Range 의 반대)
        d2.set_timeline_zoom(120, 180)
        pump(app, 0.1)
        check(d2.cache_range() == (100, 150), f"cache range before Get Zoom {d2.cache_range()}")
        cp.get_zoom_btn.click()
        pump(app, 0.1)
        check(d2.cache_range() == (120, 180) and cp.cache_range() == (120, 180) and sl.cache_range() == (120, 180),
              f"Get Zoom -> cache range {d2.cache_range()}, spins {cp.cache_range()}, handles {sl.cache_range()}")
        check(not d2.act_zoom_cache.isEnabled() and not zp.fit_btn.isEnabled(), "zoom-to-cache off: already equal")
        check(cp.cache_btn.text() == "Cache Range" and cp.range_info.text().startswith("61 frames"),
              f"panel: {cp.cache_btn.text()} / {cp.range_info.text()}")
        # 범위 슬라이더 (타임라인 아래): 그립 드래그 = 크기, 가운데 드래그 = 이동, 더블클릭 = 전체. 패널 스핀이 따라온다
        rs = tr.range_slider
        d2.set_timeline_zoom(50, 70)
        pump(app, 0.1)
        check(rs.zoom() == (50, 70), f"range slider shows the zoom {rs.zoom()}")
        ym = rs.height() // 2
        x70, x100 = int(rs._xpos(70)), int(rs._xpos(100))
        QTest.mousePress(rs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x70, ym))
        QTest.mouseMove(rs, QPoint(x100, ym))
        QTest.mouseRelease(rs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x100, ym))
        pump(app, 0.1)
        lo, hi = d2.timeline_zoom()
        check(lo == 50 and abs(hi - 100) <= 1 and zp.zoom() == (lo, hi) and (sl.minimum(), sl.maximum()) == (lo, hi),
              f"drag right grip -> zoom {d2.timeline_zoom()}, panel {zp.zoom()}")
        # 가운데 드래그 (오프스크린은 슬라이더가 좁아 창을 넉넉히 잡는다: 50 ~ 200, +50 이동)
        d2.set_timeline_zoom(50, 200)
        pump(app, 0.1)
        lo, hi = d2.timeline_zoom()
        width = hi - lo
        xm, xm2 = int((rs._xpos(lo) + rs._xpos(hi)) / 2), int((rs._xpos(lo + 50) + rs._xpos(hi + 50)) / 2)
        QTest.mousePress(rs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(xm, ym))
        QTest.mouseMove(rs, QPoint(xm2, ym))
        QTest.mouseRelease(rs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(xm2, ym))
        pump(app, 0.1)
        lo2, hi2 = d2.timeline_zoom()
        tol = int(300 / max(1.0, rs._span()[1])) + 1          # 1 px 이 몇 프레임인지 (오프스크린은 슬라이더가 좁다)
        check(hi2 - lo2 == width and abs(lo2 - (lo + 50)) <= tol and zp.zoom() == (lo2, hi2),
              f"drag middle -> moved window {d2.timeline_zoom()} (width kept, tol {tol})")
        QTest.mousePress(rs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(rs._xpos(lo2)), ym))
        QTest.mouseMove(rs, QPoint(int(rs._xpos(299)), ym))
        QTest.mouseRelease(rs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(rs._xpos(299)), ym))
        pump(app, 0.1)
        check(d2.timeline_zoom() == (hi2 - 1, hi2), f"left grip past the right one -> two frames {d2.timeline_zoom()}")
        QTest.mouseDClick(rs, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(rs._xpos(150)), ym))
        pump(app, 0.1)
        check(d2.timeline_zoom() == (0, 299) and zp.zoom() == (0, 299), "double-click -> whole video")
        # 해상도를 바꿔 다시 열어도 확대는 남는다
        d2.set_timeline_zoom(50, 70)
        cp.res_combo.setCurrentIndex(cp.res_combo.findData(50))
        pump(app, 3, lambda: cv2._image is not None and cv2._image.width() == 640)
        check(d2.timeline_zoom() == (50, 70) and (sl.minimum(), sl.maximum()) == (50, 70), "zoom survives resolution change")
        cp.res_combo.setCurrentIndex(cp.res_combo.findData(100))
        pump(app, 3, lambda: cv2._image is not None and cv2._image.width() == 1280)
        d2.reset_timeline_zoom()
        d2.set_cache_range(0, 299)

        print("[14] view zoom (wheel) and pan (right-drag)")
        f = d2.controller.frame()
        pump(app, 3, lambda: cv2._image_frame == f)
        cv2.setFocus()
        fit = cv2.video_rect()
        check(cv2.view_zoom() == 1.0 and cv2.is_view_default() and not d2.act_view_reset.isEnabled(),
              f"starts fitted: zoom {cv2.view_zoom()}, rect {fit.getRect()}")

        def wheel(pos: QPointF, steps: int) -> None:
            ev = QWheelEvent(pos, cv2.mapToGlobal(pos), QPoint(), QPoint(0, 120 * steps), Qt.MouseButton.NoButton,
                             Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
            app.sendEvent(cv2, ev)
            pump(app, 0.05)

        def near(a: QPointF, b: QPointF, tol: float = 1.0) -> bool:
            return abs(a.x() - b.x()) <= tol and abs(a.y() - b.y()) <= tol

        # 휠 한 칸: 1.25배, 커서 아래 영상 자리(소스 1/4 지점)는 그대로
        anchor = cv2.screen_point(320, 180)
        wheel(anchor, 1)
        check(abs(cv2.view_zoom() - 1.25) < 1e-9 and d2.act_view_reset.isEnabled(), f"wheel up -> zoom {cv2.view_zoom()}")
        vr = cv2.video_rect()
        check(abs(vr.width() - fit.width() * 1.25) < 1e-6 and abs(vr.height() - fit.height() * 1.25) < 1e-6,
              f"video rect scaled {vr.getRect()}")
        # 가로는 영상이 캔버스보다 넓어져 커서 자리가 지켜지고, 세로는 아직 캔버스보다 낮아 가운데 고정이다 (빈 공간 금지)
        sp1 = cv2.screen_point(320, 180)
        check(abs(sp1.x() - anchor.x()) <= 1.0 and abs(vr.center().y() - cv2.height() / 2) < 1e-6,
              f"x under the cursor stays put ({sp1.x():.1f} vs {anchor.x():.1f}); y centered while shorter than the canvas")
        img = cv2.grab().toImage()
        # 배지: 오른쪽 위 어딘가에 밝은 글자 (정확한 문구는 paintEvent 의 zoom_label)
        check(cv2._zoom == 1.25 and img.width() == cv2.width(), "badge paints (no crash while zoomed)")
        wheel(anchor, 3)
        check(abs(cv2.view_zoom() - 1.25 ** 4) < 1e-9, f"three more -> {cv2.view_zoom():.4f}")
        # 양축 모두 캔버스보다 커진 뒤에는 커서 아래 자리가 그대로다
        vr = cv2.video_rect()
        check(vr.width() > cv2.width() and vr.height() > cv2.height(), "video larger than the canvas on both axes")
        anchor2 = QPointF(cv2.width() * 0.6, cv2.height() * 0.4)
        src = to_video(anchor2.x(), anchor2.y(), (vr.x(), vr.y(), vr.width(), vr.height()), 1280, 720)
        wheel(anchor2, 1)
        sp2 = cv2.screen_point(*src)
        check(abs(cv2.view_zoom() - 1.25 ** 5) < 1e-9 and near(sp2, anchor2),
              f"zoom around the cursor keeps the source point under it ({sp2.x():.1f},{sp2.y():.1f} vs "
              f"{anchor2.x():.1f},{anchor2.y():.1f})")
        wheel(anchor2, -1)
        # 확대 상태에서 그은 선은 소스 좌표로 들어간다 (화면 배율만 다르다)
        d2.doc.clear_frame(f)
        d2._doc_changed()
        q1, q2 = cv2.screen_point(400, 300), cv2.screen_point(600, 300)
        QTest.mousePress(cv2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q1.toPoint())
        for k in range(1, 21):
            QTest.mouseMove(cv2, QPoint(int(q1.x() + (q2.x() - q1.x()) * k / 20), int(q1.y())))
        QTest.mouseRelease(cv2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q2.toPoint())
        pump(app, 0.1)
        st = d2.doc.strokes_at(f)
        (x0, y0), (x1, y1) = (st[-1].points[0], st[-1].points[-1]) if st else ((0, 0), (0, 0))
        check(len(st) == 1 and abs(x0 - 400) <= 2 and abs(y0 - 300) <= 2 and abs(x1 - 600) <= 2 and abs(y1 - 300) <= 2,
              f"stroke drawn while zoomed lands in source pixels ({x0:.0f},{y0:.0f}) -> ({x1:.0f},{y1:.0f})")
        # 우드래그 = 이동 (왼쪽으로 40 px, 위로 30 px)
        before = cv2.video_rect()
        p0 = QPoint(cv2.width() // 2, cv2.height() // 2)
        QTest.mousePress(cv2, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, p0)
        check(cv2.is_busy() and cv2._panning, "right press starts panning")
        QTest.mouseMove(cv2, p0 + QPoint(-20, -15))
        QTest.mouseMove(cv2, p0 + QPoint(-40, -30))
        QTest.mouseRelease(cv2, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, p0 + QPoint(-40, -30))
        pump(app, 0.1)
        after = cv2.video_rect()
        check(not cv2._panning and abs(after.x() - (before.x() - 40)) < 1e-6 and abs(after.y() - (before.y() - 30)) < 1e-6,
              f"right-drag pans by (-40, -30): {before.x():.1f},{before.y():.1f} -> {after.x():.1f},{after.y():.1f}")
        check(len(d2.doc.strokes_at(f)) == 1, "right-drag draws nothing")
        # 이동은 영상 가장자리가 위젯 안쪽으로 들어오지 않는 범위까지만
        QTest.mousePress(cv2, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, p0)
        QTest.mouseMove(cv2, p0 + QPoint(5000, 5000))
        QTest.mouseRelease(cv2, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, p0 + QPoint(5000, 5000))
        pump(app, 0.1)
        vr = cv2.video_rect()
        check(vr.x() == 0.0 and vr.y() == 0.0, f"pan clamps at the top-left edge {vr.getRect()}")
        QTest.mousePress(cv2, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, p0)
        QTest.mouseMove(cv2, p0 + QPoint(-5000, -5000))
        QTest.mouseRelease(cv2, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, p0 + QPoint(-5000, -5000))
        pump(app, 0.1)
        vr = cv2.video_rect()
        check(abs(vr.right() - cv2.width()) < 1e-6 and abs(vr.bottom() - cv2.height()) < 1e-6,
              f"pan clamps at the bottom-right edge {vr.getRect()} in {cv2.width()}x{cv2.height()}")
        # 우버튼 더블클릭 → 되돌림
        QTest.mouseDClick(cv2, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, p0)
        pump(app, 0.1)
        check(cv2.is_view_default() and cv2.video_rect() == fit and not d2.act_view_reset.isEnabled(),
              f"right double-click -> fit {cv2.video_rect().getRect()}")
        # 축소 (맞춤보다 작게) → 가운데, 그리고 F 로 되돌림
        wheel(QPointF(10, 10), -1)
        vr = cv2.video_rect()
        check(abs(cv2.view_zoom() - 0.8) < 1e-9 and abs(vr.center().x() - cv2.width() / 2) < 1e-6
              and abs(vr.center().y() - cv2.height() / 2) < 1e-6, f"wheel down below fit -> 80 %, centered {vr.getRect()}")
        QTest.keyClick(cv2, Qt.Key.Key_F)
        pump(app, 0.1)
        check(cv2.is_view_default() and cv2.video_rect() == fit, "F -> fit")
        # 휠은 2 칸 올리고 2 칸 내리면 정확히 1.0 (부동소수 찌꺼기 없음), 범위 밖은 잘린다
        wheel(anchor, 2)
        wheel(anchor, -2)
        check(cv2.view_zoom() == 1.0 and cv2.is_view_default(), f"up 2 / down 2 -> exactly 1.0 ({cv2.view_zoom()})")
        wheel(anchor, 40)
        check(cv2.view_zoom() == 16.0, f"zoom clamps at max {cv2.view_zoom()}")
        wheel(anchor, -80)
        check(cv2.view_zoom() == 0.25, f"zoom clamps at min {cv2.view_zoom()}")
        # 그리는 중에는 휠을 무시한다
        d2.reset_view()
        QTest.mousePress(cv2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q1.toPoint())
        wheel(anchor, 1)
        check(cv2.view_zoom() == 1.0, "wheel ignored while drawing")
        QTest.mouseRelease(cv2, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, q1.toPoint())
        pump(app, 0.1)
        # 해상도를 바꿔 다시 열어도(같은 소스 크기) 보기는 남고, 캔버스를 비우면 되돌아간다
        wheel(anchor, 2)
        cp.res_combo.setCurrentIndex(cp.res_combo.findData(50))
        pump(app, 3, lambda: cv2._image is not None and cv2._image.width() == 640)
        check(abs(cv2.view_zoom() - 1.25 ** 2) < 1e-9, f"view zoom survives resolution change ({cv2.view_zoom()})")
        cp.res_combo.setCurrentIndex(cp.res_combo.findData(100))
        pump(app, 3, lambda: cv2._image is not None and cv2._image.width() == 1280)
        d2.doc.clear_frame(f)
        d2._doc_changed()
        cv2.clear("x")
        check(cv2.is_view_default(), "clear() resets the view")
        d2._load_video(d2._row)
        pump(app, 3, lambda: cv2._image is not None)

        print("[15] per-video view state survives switching videos")
        src_a = tmp / "testsrc.mp4"          # [14] 가 src 를 좌표로 덮었다
        src2 = tmp / "testsrc_b.mp4"
        shutil.copy(src_a, src2)
        d2.add_paths([src2])
        pump(app, 10, lambda: d2.model.rowCount() == 2 and d2.model.item(1).info is not None)
        check(d2.controller.item() is not None and d2.controller.item().path == src_a,
              "first video stays selected after adding a second")
        d2.doc.dirty = False
        d2.controller.seek(123)
        pump(app, 3, lambda: cv2._image_frame == 123)
        d2.set_timeline_zoom(50, 70)
        d2.set_cache_range(10, 200)
        d2.reset_view()
        wheel(anchor, 2)
        zoom0, pan0 = cv2.view_zoom(), cv2.view_pan()
        check(abs(zoom0 - 1.25 ** 2) < 1e-9 and pan0 != (0.0, 0.0), f"first video: view {zoom0:.4f}, pan {pan0}")
        d2.view.setCurrentIndex(d2.model.index(1))
        check(pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src2
                   and cv2._image is not None), "second video opens")
        check(d2.controller.frame() == 0 and d2.timeline_zoom() == (0, 299) and d2.cache_range() == (0, 299),
              f"first visit starts fresh: frame {d2.controller.frame()}, zoom {d2.timeline_zoom()}, cache {d2.cache_range()}")
        d2.controller.seek(40)
        pump(app, 3, lambda: cv2._image_frame == 40)
        d2.set_timeline_zoom(100, 150)
        d2.reset_view()
        d2.view.setCurrentIndex(d2.model.index(0))
        check(pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src_a
                   and cv2._image_frame == 123), f"back to the first video at frame {d2.controller.frame()}")
        check(d2.timeline_zoom() == (50, 70) and zp.zoom() == (50, 70) and (sl.minimum(), sl.maximum()) == (50, 70),
              f"timeline zoom restored {d2.timeline_zoom()}")
        check(d2.cache_range() == (10, 200) and cp.cache_range() == (10, 200) and sl.cache_range() == (10, 200),
              f"cache range restored {d2.cache_range()}")
        check(abs(cv2.view_zoom() - zoom0) < 1e-9 and near(QPointF(*cv2.view_pan()), QPointF(*pan0), 1e-6)
              and d2.act_view_reset.isEnabled(), f"view zoom and pan restored {cv2.view_zoom():.4f} {cv2.view_pan()}")
        check("Resumed where you left off: frame 123, timeline 50-70, cache range 10-200, view 156%." in d2.log.toPlainText(),
              "log line")
        d2.view.setCurrentIndex(d2.model.index(1))
        check(pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src2
                   and cv2._image_frame == 40), f"second video resumes at frame {d2.controller.frame()}")
        check(d2.timeline_zoom() == (100, 150) and d2.cache_range() == (0, 299) and cv2.is_view_default(),
              f"second video keeps its own state: zoom {d2.timeline_zoom()}, cache {d2.cache_range()}, fit view")
        # 재생 중에 바꾸면 그 순간의 프레임을 기억한다
        d2.controller.play()
        pump(app, 1.0, lambda: d2.controller.frame() >= 45)
        d2.view.setCurrentIndex(d2.model.index(0))
        pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src_a and cv2._image_frame == 123)
        check(not d2.controller.is_playing(), "switching pauses")
        d2.view.setCurrentIndex(d2.model.index(1))
        pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src2 and cv2._image is not None)
        check(45 <= d2.controller.frame() < 299 and not d2.controller.is_playing(),
              f"resumes paused at the frame where playback was when leaving ({d2.controller.frame()})")
        # 리스트에서 지우면 잊는다 — 다시 넣으면 처음부터
        d2.remove_rows([1])
        pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src_a and cv2._image_frame == 123)
        check(d2.model.rowCount() == 1 and d2.timeline_zoom() == (50, 70), "removing the second video falls back to the first, restored")
        d2.add_paths([src2])
        pump(app, 10, lambda: d2.model.rowCount() == 2 and d2.model.item(1).info is not None)
        d2.view.setCurrentIndex(d2.model.index(1))
        pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src2 and cv2._image is not None)
        check(d2.controller.frame() == 0 and d2.timeline_zoom() == (0, 299), "re-added video starts fresh (state forgotten on remove)")
        d2.view.setCurrentIndex(d2.model.index(0))
        pump(app, 10, lambda: d2.controller.item() is not None and d2.controller.item().path == src_a and cv2._image_frame == 123)
        d2.clear_list()
        pump(app, 0.3)
        check(d2.controller.item() is None and not d2._view_states, "Clear List forgets every state")
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
