# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-20
"""WAV (JUN_JALI) 변환 통합 검증. 오프스크린 Qt 로 실제 Convert 탭을 돌린다.

    python dev/check_wav.py [--keep] [--jali-python <JUN_JALI .venv python.exe>]

1. ffmpeg 로 여러 원본을 만든다: mp3(앨범 아트) · m4a · flac 96 kHz 24-bit · opus · 48 kHz float wav · 소리 있는 mp4 ·
   소리 없는 mp4 · 0.3 초 · 무음 · 130 초 · 양쪽이 같은 꽉 찬 스테레오.
2. probe: 음성 파일은 audio_only, 앨범 아트는 영상으로 치지 않음, 소리 없는 mp4 는 WAV 에서 건너뜀.
3. Convert 탭에서 WAV 로 변환 → 모든 출력이 44100 Hz · 16-bit · mono · 44 바이트 헤더 · 길이 일치 · JUN_JALI 규칙 통과.
   짧은 파일(E06) · 무음(E08) 은 실패로 표시, 130 초는 E07 경고. 구간 지정(500 ~ 2499 ms) 은 정확히 2.000 초.
4. MP4 포맷에서는 음성 파일을 건너뛴다. Draw 탭은 음성 파일을 받지 않는다.
5. --jali-python 을 주면 JUN_JALI 의 실제 check_wav() 로도 출력을 검사한다 (numpy · scipy 가 있는 파이썬).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["JUN_VIDEO_TOOL_SETTINGS_SCOPE"] = "JUN_Video_Tool_check_wav"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.core.ffmpeg_locator import find_ffmpeg  # noqa: E402
from app.core.jali_wav import JaliWavError, check_jali_wav  # noqa: E402
from app.core.models import FrameRange, ItemStatus  # noqa: E402

FAILS: list[str] = []
JALI_ROOT_DEFAULT = ROOT.parent / "0030_maya_python_JUN" / "JUN_JALI"


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


def ff(ffmpeg: Path, *args: str) -> None:
    subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


VOICE = "aevalsrc=0.5*sin(2*PI*220*t):s=44100:d={d}"   # 목소리 대신 사인파 (진폭 0.5)


def make_sources(ffmpeg: Path, d: Path) -> dict[str, Path]:
    src: dict[str, Path] = {}
    cover = d / "cover.jpg"
    ff(ffmpeg, "-f", "lavfi", "-i", "testsrc=size=300x300:d=1", "-frames:v", "1", str(cover))

    def stereo(dur: float) -> list[str]:
        return ["-f", "lavfi", "-i", VOICE.format(d=dur), "-f", "lavfi", "-i", f"aevalsrc=0.5*sin(2*PI*330*t):s=44100:d={dur}",
                "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]", "-map", "[a]"]

    src["mp3"] = d / "voice_cover.mp3"
    ff(ffmpeg, *stereo(4.0)[:4], "-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:a", "libmp3lame", "-ar", "44100",
       "-ac", "2", "-c:v", "mjpeg", "-disposition:v", "attached_pic", str(src["mp3"]))
    src["m4a"] = d / "voice.m4a"
    ff(ffmpeg, *stereo(5.0), "-c:a", "aac", "-ar", "48000", str(src["m4a"]))
    src["flac"] = d / "voice_96k.flac"
    ff(ffmpeg, "-f", "lavfi", "-i", VOICE.format(d=3.0), "-ar", "96000", "-sample_fmt", "s32", "-c:a", "flac",
       str(src["flac"]))
    src["opus"] = d / "voice.ogg"
    ff(ffmpeg, *stereo(3.0), "-c:a", "libopus", "-ar", "48000", str(src["opus"]))
    src["fwav"] = d / "float48k.wav"
    ff(ffmpeg, *stereo(3.0), "-c:a", "pcm_f32le", "-ar", "48000", str(src["fwav"]))
    src["mp4"] = d / "clip_with_audio.mp4"
    ff(ffmpeg, "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:d=6", *stereo(6.0)[:4],
       "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
       "-shortest", str(src["mp4"]))
    src["mute"] = d / "clip_no_audio.mp4"
    ff(ffmpeg, "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
       str(src["mute"]))
    src["short"] = d / "too_short.mp3"
    ff(ffmpeg, "-f", "lavfi", "-i", VOICE.format(d=0.3), "-c:a", "libmp3lame", str(src["short"]))
    src["silent"] = d / "silent.flac"
    ff(ffmpeg, "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "2", "-c:a", "flac", str(src["silent"]))
    src["long"] = d / "long_130s.m4a"
    ff(ffmpeg, "-f", "lavfi", "-i", VOICE.format(d=130.0), "-c:a", "aac", str(src["long"]))
    src["loud"] = d / "loud_same_lr.wav"
    ff(ffmpeg, "-f", "lavfi", "-i", "aevalsrc=0.99*sin(2*PI*200*t):s=44100:d=2", "-af", "pan=stereo|c0=c0|c1=c0",
       "-c:a", "pcm_s16le", "-ar", "44100", str(src["loud"]))
    return src


def wav_header(path: Path) -> tuple[int, int, int, float, int]:
    with wave.open(str(path), "rb") as w:
        return w.getframerate(), w.getsampwidth(), w.getnchannels(), w.getnframes() / w.getframerate(), \
            path.stat().st_size - w.getnframes() * w.getsampwidth() * w.getnchannels()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--jali-python", default="")
    ap.add_argument("--jali-root", default=str(JALI_ROOT_DEFAULT))
    args = ap.parse_args()
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        print("ffmpeg not found")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="jun_check_wav_"))
    app = QApplication.instance() or QApplication(sys.argv)
    orig_question = QMessageBox.question
    asked: list[str] = []
    QMessageBox.question = staticmethod(lambda *a, **k: (asked.append(str(a[2]) if len(a) > 2 else ""),
                                                         QMessageBox.StandardButton.Yes)[1])
    try:
        print("[1] sources")
        src = make_sources(ffmpeg, tmp)
        check(all(p.is_file() for p in src.values()), f"{len(src)} source files made")

        print("[2] Convert tab: add + probe")
        from app.ui.main_window import MainWindow
        w = MainWindow()
        w.resize(1280, 760)
        w.show()
        pump(app, 0.3)
        w.tabs.setCurrentIndex(0)
        ct = w.convert_tab
        check(pump(app, 10, lambda: ct._ffmpeg_ok), "ffmpeg ready")
        ct.add_paths(list(src.values()))
        m = ct.model
        check(m.rowCount() == len(src), f"all {len(src)} files added (audio extensions accepted)")
        check(pump(app, 30, lambda: all(it.info is not None or it.probe_error for it in m.items())), "all probed")

        def item(key):
            return m.item(m.row_of(src[key]))
        for k in ("mp3", "m4a", "flac", "opus", "fwav", "short", "silent", "long", "loud"):
            check(item(k).info is not None and item(k).info.audio_only, f"{src[k].name}: audio_only")
        check(not item("mp4").info.audio_only and item("mp4").info.has_audio, "mp4 with audio: video + audio")
        check(not item("mute").info.has_audio, "mp4 without audio: has_audio False")
        mp3 = item("mp3").info
        check((mp3.sample_rate, mp3.channels) == (44100, 2), f"mp3 with cover art: {mp3.sample_rate} Hz {mp3.channels} ch")
        check(item("flac").info.sample_rate == 96000, "flac 96 kHz probed")
        check("Audio" in m.data(m.index(m.row_of(src["m4a"])), m.InfoTextRole), "list shows audio info")

        print("[3] MP4 format skips audio files")
        ct.format_combo.setCurrentIndex(ct.format_combo.findData("mp4"))
        pump(app, 0.5)
        check(ct._converter.skip_reason(item("m4a")) is not None, "mp4: audio file has a skip reason")
        check(ct._converter.skip_reason(item("mp4")) is None, "mp4: video file converts")

        print("[4] WAV format: options, range, estimate")
        ct.format_combo.setCurrentIndex(ct.format_combo.findData("wav"))
        pump(app, 0.5)
        check(ct._converter.format_id == "wav" and ct._options_panel.title() == "WAV Options (JUN_JALI)", "WAV panel")
        r_m4a = m.row_of(src["m4a"])
        m.update_item(r_m4a, frame_range=FrameRange(500, 2499))
        ct.view.setCurrentIndex(m.index(r_m4a))
        pump(app, 0.5)
        check(ct.range_panel.start_spin.suffix() == " ms" and ct.range_panel.start_preview.text() == "Audio",
              "range panel in ms, no picture preview")
        check("2.000 s" in ct.range_panel.frames_label.text(), f"range label: {ct.range_panel.frames_label.text()}")
        ct._run_estimates()
        pump(app, 0.5)
        it = item("m4a")
        check(it.est_level == "exact" and it.est_size == 44 + 2 * 44100 * 2, f"exact size estimate {it.est_size}")
        check(item("mute").est_size is None, "silent video has no estimate")

        print("[5] convert to WAV")
        ct.convert_btn.click()
        check(pump(app, 180, lambda: ct.runner is None), "conversion finished")
        pump(app, 0.3)
        log = ct.log.toPlainText()
        check(any("too_short.mp3" in a and "0.5 s" in a for a in asked) and any("long_130s" in a for a in asked),
              "warned before start (short / long)")
        check(item("mute").status == ItemStatus.SKIPPED, "video without audio skipped")
        good = ("mp3", "m4a", "flac", "opus", "fwav", "mp4", "loud")
        for k in good:
            it = item(k)
            out = it.output_path
            ok = it.status == ItemStatus.DONE and out is not None and out.is_file()
            check(ok, f"{src[k].name}: done -> {out.name if out else None}")
            if not ok:
                continue
            rate, width, ch, sec, header = wav_header(out)
            check((rate, width, ch, header) == (44100, 2, 1, 44),
                  f"  {out.name}: {rate} Hz, {width * 8}-bit, {ch} ch, header {header} B")
            src_dur = it.effective_range().to_seconds(it.info.fps)[1]
            check(abs(sec - src_dur) < 0.06, f"  length {sec:.3f} s (source {src_dur:.3f} s)")
            try:
                ji = check_jali_wav(out)
                check(not ji.warnings, f"  JUN_JALI rules pass {ji.warnings or ''}")
            except JaliWavError as exc:
                check(False, f"  JUN_JALI rules: {exc}")
        check(abs(wav_header(item("m4a").output_path)[3] - 2.0) < 0.002, "range 500-2499 ms -> 2.000 s")
        check(src["fwav"].is_file() and item("fwav").output_path != src["fwav"], "source wav not overwritten")
        loud = check_jali_wav(item("loud").output_path)
        check(25000 < loud.peak < 32760, f"mixing equal full L/R does not clip (peak {loud.peak})")
        check(item("short").status == ItemStatus.FAILED and "E06" in item("short").message,
              f"0.3 s file flagged: {item('short').message}")
        check(item("silent").status == ItemStatus.FAILED and "E08" in item("silent").message,
              f"silent file flagged: {item('silent').message}")
        check(item("short").output_path is not None and item("short").output_path.is_file(), "flagged file is kept")
        check(item("long").status == ItemStatus.DONE and "E07" in log, "130 s file done with E07 warning")
        check("JUN_JALI ready (44100 Hz · int16 · 1 ch" in log, "log shows JUN_JALI ready")

        print("[6] channel modes (right-only voice)")
        one = tmp / "right_only.wav"
        ff(ffmpeg, "-f", "lavfi", "-i", VOICE.format(d=1.0), "-af", "pan=stereo|c0=0*c0|c1=c0", "-c:a", "pcm_s16le",
           "-ar", "44100", str(one))
        from app.core.converters import WavConverter, WavOptions
        from app.core.media_probe import probe
        from app.core.models import VideoItem
        vi = VideoItem(path=one, info=probe(one))
        peaks = {}
        for mode in ("mix", "left", "right"):
            out = tmp / f"right_only_{mode}.wav"
            subprocess.run(WavConverter().build_command(ffmpeg, vi, WavOptions(channels=mode), out),
                           capture_output=True, check=True)
            try:
                peaks[mode] = check_jali_wav(out).peak
            except JaliWavError as exc:
                peaks[mode] = exc.code
        check(peaks["left"] == "E08" and isinstance(peaks["right"], int) and isinstance(peaks["mix"], int)
              and peaks["right"] > peaks["mix"] * 1.8, f"left silent, right full, mix half: {peaks}")

        print("[7] Draw tab accepts video only")
        dt = w.draw_tab
        w.tabs.setCurrentIndex(1)
        pump(app, 0.2)
        dt.add_paths([src["m4a"], src["mp3"], src["mp4"]])
        check(dt.model.rowCount() == 1, f"Draw list took {dt.model.rowCount()} of 3 (video only)")

        if args.jali_python:
            print("[8] JUN_JALI check_wav() (real)")
            outs = [str(item(k).output_path) for k in good] + [str(item("long").output_path)]
            code = ("import sys; sys.path.insert(0, r'%s')\n"
                    "from app.core.wav_check import check_wav, WavError\n"
                    "for p in sys.argv[1:]:\n"
                    "    try:\n"
                    "        i = check_wav(p, 0)\n"
                    "        print('OK', p, i.summary(), i.warnings)\n"
                    "    except WavError as e:\n"
                    "        print('ERR', p, e)\n") % str(Path(args.jali_root) / "tools" / "VisemeNet_Converter")
            res = subprocess.run([args.jali_python, "-c", code, *outs], capture_output=True, text=True)
            lines = res.stdout.strip().splitlines()
            for ln in lines:
                print("       " + ln)
            check(res.returncode == 0 and len(lines) == len(outs) and all(ln.startswith("OK") and ln.endswith("[]")
                                                                          for ln in lines),
                  f"JUN_JALI check_wav passes all {len(outs)} outputs with no warnings" + (res.stderr[-300:] or ""))
        w.close()
        pump(app, 0.3)
    finally:
        QMessageBox.question = orig_question
        QSettings("JUN", "JUN_Video_Tool_check_wav").clear()
        if args.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
