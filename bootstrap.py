# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""의존성 일괄 설치 (PLAN 13.3). 표준 라이브러리만 사용한다.

    python bootstrap.py [--check] [--venv] [--dev] [--no-pip] [--no-binaries]
                        [--ffmpeg-zip PATH] [--pip-index-url URL] [--yes] [--json]

--json 모드 프로토콜 (DependencyDialog 가 파싱):
    PROGRESS <0-100>
    REPORT_JSON {"ok": bool, "items": [{name, kind, required, found, status, location}, ...]}
"""
from __future__ import annotations

import argparse
import atexit
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import dependency_check as dc  # noqa: E402  (stdlib only)

_JSON = False
_TMP_FILES: list[Path] = []


# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
def say(msg: str = "") -> None:
    print(msg, flush=True)


def progress(pct: float) -> None:
    if _JSON:
        print(f"PROGRESS {int(max(0, min(100, pct)))}", flush=True)


def _cleanup_tmp() -> None:
    for p in _TMP_FILES:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
        except OSError:
            pass


atexit.register(_cleanup_tmp)


# ---------------------------------------------------------------------------
# deps.json
# ---------------------------------------------------------------------------
def load_deps() -> dict:
    with open(ROOT / "deps.json", encoding="utf-8") as f:
        return json.load(f)


def match_member(member_name: str, pattern: str) -> bool:
    """zip 멤버 이름이 members_glob 에 맞는지. 경로 구분자는 / 로 정규화."""
    name = member_name.replace("\\", "/")
    return fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name.lower(), pattern.lower())


def safe_basename(member_name: str) -> str:
    """경로 탈출 방지: 정규화 후 basename 만."""
    name = member_name.replace("\\", "/")
    return os.path.basename(name.rstrip("/"))


def python_ok(spec: dict) -> tuple[bool, str]:
    cur = ".".join(str(x) for x in sys.version_info[:3])
    lo = dc.version_tuple(spec.get("min", "3.11"))
    hi = dc.version_tuple(spec.get("max_exclusive", "4.0"))
    v = sys.version_info[:3]
    ok = lo <= v[: len(lo)] and v[: len(hi)] < hi
    return ok, cur


# ---------------------------------------------------------------------------
# 다운로드 · 검증 · 추출
# ---------------------------------------------------------------------------
def download(url: str, dest: Path, base_pct: float = 0.0, span_pct: float = 60.0) -> None:
    say(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "JUN-Video-Tool-bootstrap"})
    with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        last_shown = -1
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if total:
                pct = got / total * 100
                shown = int(pct // 5) * 5
                if shown != last_shown:
                    last_shown = shown
                    if not _JSON:
                        print(f"\r  {got / 1048576:6.1f} / {total / 1048576:6.1f} MB ({pct:3.0f}%)", end="", flush=True)
                    progress(base_pct + span_pct * pct / 100)
    if not _JSON:
        print()
    say(f"  Saved {dest.stat().st_size / 1048576:.1f} MB")


def fetch_sha256(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "JUN-Video-Tool-bootstrap"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read(4096).decode("utf-8", "replace")
    except Exception as exc:
        say(f"  Could not fetch checksum: {exc}")
        return None
    for tok in text.replace("\n", " ").split():
        tok = tok.strip().lower()
        if len(tok) == 64 and all(c in "0123456789abcdef" for c in tok):
            return tok
    return None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_members(zip_path: Path, files: list[str], members_glob: str, install_dir: Path) -> list[str]:
    """files 각각에 맞는 멤버를 install_dir 로 추출. 누락된 파일 이름 목록 반환."""
    install_dir.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for fname in files:
            pattern = members_glob.replace("{name}", fname)
            member = next((n for n in names if match_member(n, pattern)), None)
            if member is None:
                missing.append(fname)
                continue
            target = install_dir / safe_basename(member)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            say(f"  Extracted {target.name}")
    return missing


def verify_binary(install_dir: Path, verify_cmd: list[str]) -> str | None:
    exe = install_dir / verify_cmd[0]
    if not exe.is_file():
        return None
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0
        out = subprocess.run([str(exe), *verify_cmd[1:]], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=20, creationflags=flags)
        if out.returncode != 0:
            return None
        lines = (out.stdout or out.stderr or "").splitlines()
        if not lines:
            return "ok"
        first = lines[0].strip()
        # "ffmpeg version 9.0.2-essentials_build-www.gyan.dev Copyright ..." → "9.0.2-essentials_build-www.gyan.dev"
        toks = first.split()
        if len(toks) >= 3 and toks[1] == "version":
            return toks[2]
        return first[:60]
    except Exception:
        return None


def binary_installed(entry: dict) -> str | None:
    install_dir = ROOT / entry["install_dir"]
    if not all((install_dir / f).is_file() for f in entry["files"]):
        return None
    return verify_binary(install_dir, entry["verify_cmd"])


def install_binary(entry: dict, local_zip: Path | None, yes: bool, base_pct: float, span_pct: float) -> tuple[bool, str]:
    """(성공, 메시지)."""
    install_dir = ROOT / entry["install_dir"]
    files = list(entry["files"])
    sources = list(entry.get("sources") or [])
    if local_zip is not None:
        sources = [{"url": None, "sha256_url": None, "members_glob": sources[0]["members_glob"] if sources else "*/bin/{name}",
                    "local": str(local_zip)}]
    if not sources:
        return False, "No download sources configured."

    tmp_dir = Path(tempfile.mkdtemp(prefix="jun_bootstrap_"))
    _TMP_FILES.append(tmp_dir)
    per_source = span_pct / max(1, len(sources))

    for i, src in enumerate(sources):
        start_pct = base_pct + per_source * i
        try:
            if src.get("local"):
                zip_path = Path(src["local"])
                say(f"Using local archive {zip_path}")
                if not zip_path.is_file():
                    say("  File not found.")
                    continue
            else:
                url = src["url"]
                if not yes:
                    ans = input(f"Download {entry['name']} from {url} ? [Y/n] ").strip().lower()
                    if ans not in ("", "y", "yes"):
                        return False, "Download declined by user."
                zip_path = tmp_dir / f"{entry['name']}_{i}.zip"
                download(url, zip_path, start_pct, per_source * 0.7)
                sha_url = src.get("sha256_url")
                if sha_url:
                    expected = fetch_sha256(sha_url)
                    if expected:
                        actual = sha256_of(zip_path)
                        if actual != expected:
                            say(f"  Checksum mismatch (expected {expected[:12]}…, got {actual[:12]}…). Discarding.")
                            zip_path.unlink(missing_ok=True)
                            continue
                        say("  Checksum OK")
                    else:
                        say("  Checksum unavailable; continuing without verification.")
            missing = extract_members(zip_path, files, src.get("members_glob", "*/bin/{name}"), install_dir)
            if missing:
                say(f"  Archive is missing: {', '.join(missing)}")
                continue
            ver = verify_binary(install_dir, entry["verify_cmd"])
            if not ver:
                say("  Verification failed; removing extracted files.")
                for f in files:
                    (install_dir / f).unlink(missing_ok=True)
                continue
            (install_dir / "VERSION.txt").write_text(ver + "\n", encoding="utf-8")
            progress(base_pct + span_pct)
            return True, ver
        except Exception as exc:
            say(f"  Source failed: {exc}")
            continue
    return False, "All download sources failed."


# ---------------------------------------------------------------------------
# pip
# ---------------------------------------------------------------------------
def pip_install(req_file: Path, index_url: str | None, extra: list[str] | None = None) -> tuple[bool, str]:
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    if req_file.is_file():
        cmd += ["-r", str(req_file)]
    if extra:
        cmd += extra
    if index_url:
        cmd += ["--index-url", index_url]
    say(f"Running: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        assert proc.stdout is not None
        tail: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            tail.append(line)
            if len(tail) > 30:
                del tail[0]
            say("  " + line)
        rc = proc.wait()
        return rc == 0, "\n".join(tail[-5:]) if rc != 0 else "ok"
    except OSError as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# venv
# ---------------------------------------------------------------------------
def in_venv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)


def ensure_venv_and_reexec(argv: list[str]) -> None:
    venv_dir = ROOT / ".venv"
    py = venv_dir / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
    if not py.is_file():
        say(f"Creating virtual environment at {venv_dir}")
        import venv

        venv.create(venv_dir, with_pip=True, clear=False)
    args = [a for a in argv if a != "--venv"]
    say(f"Re-running inside {py}")
    rc = subprocess.call([str(py), str(ROOT / "bootstrap.py"), *args])
    sys.exit(rc)


# ---------------------------------------------------------------------------
# 리포트
# ---------------------------------------------------------------------------
def build_report(deps: dict, extra_status: dict[str, dict] | None = None) -> list[dict]:
    items: list[dict] = []
    ok, cur = python_ok(deps.get("python", {}))
    items.append({"name": "Python", "kind": "python",
                  "required": f">={deps.get('python', {}).get('min', '3.11')},<{deps.get('python', {}).get('max_exclusive', '3.14')}",
                  "found": cur, "status": "OK" if ok else "Outdated", "location": sys.executable})
    for d in dc.check_pip(ROOT / deps.get("pip", {}).get("requirements", "requirements.txt")):
        items.append(d.to_dict())
    for entry in deps.get("binaries", []):
        install_dir = ROOT / entry["install_dir"]
        ver = binary_installed(entry)
        for fname in entry["files"]:
            exe = install_dir / fname
            short = Path(fname).stem
            if exe.is_file() and ver:
                items.append({"name": short, "kind": "binary", "required": "any", "found": ver if short == Path(entry["files"][0]).stem else "found",
                              "status": "OK", "location": str(exe)})
            else:
                # bin/ 에 없으면 PATH / imageio 폴백도 인정
                found = shutil.which(short)
                if found is None and short == "ffmpeg":
                    try:
                        import imageio_ffmpeg  # type: ignore

                        found = imageio_ffmpeg.get_ffmpeg_exe()
                    except Exception:
                        found = None
                if found:
                    items.append({"name": short, "kind": "binary", "required": "any", "found": "found (outside bin)",
                                  "status": "OK", "location": str(found)})
                else:
                    required = "optional" if short == "ffprobe" else "any"
                    items.append({"name": short, "kind": "binary", "required": required, "found": "-",
                                  "status": "Missing", "location": str(install_dir)})
    if extra_status:
        for it in items:
            if it["name"] in extra_status:
                it.update(extra_status[it["name"]])
    return items


def print_report(items: list[dict]) -> None:
    say()
    widths = [max(len(str(it[k])) for it in items + [{"name": "Name", "required": "Required", "found": "Found",
                                                       "status": "Status", "location": "Location"}])
              for k in ("name", "required", "found", "status", "location")]
    header = ("Name", "Required", "Found", "Status", "Location")
    say("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    say("  ".join("-" * w for w in widths))
    for it in items:
        say("  ".join(str(it[k]).ljust(w) for k, w in zip(("name", "required", "found", "status", "location"), widths)))
    say()


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    global _JSON
    ap = argparse.ArgumentParser(description="Install JUN Video Tool dependencies.")
    ap.add_argument("--check", action="store_true", help="only report status, install nothing")
    ap.add_argument("--venv", action="store_true", help="create .venv and install there")
    ap.add_argument("--dev", action="store_true", help="also install requirements-dev.txt")
    ap.add_argument("--no-pip", action="store_true")
    ap.add_argument("--no-binaries", action="store_true")
    ap.add_argument("--ffmpeg-zip", type=str, default=None, help="use a local ffmpeg zip instead of downloading")
    ap.add_argument("--pip-index-url", type=str, default=None)
    ap.add_argument("--yes", "-y", action="store_true", help="do not ask before downloading")
    ap.add_argument("--json", action="store_true", help="machine-readable progress and report")
    args = ap.parse_args(argv)
    _JSON = args.json

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

    deps = load_deps()

    ok_py, cur = python_ok(deps.get("python", {}))
    if not ok_py:
        say(f"Python {cur} is not supported. Install Python {deps.get('python', {}).get('min', '3.11')} "
            f"(below {deps.get('python', {}).get('max_exclusive', '3.14')}).")
        items = build_report(deps)
        if _JSON:
            print("REPORT_JSON " + json.dumps({"ok": False, "items": items}), flush=True)
        return 2

    if args.venv and not in_venv() and not args.check:
        ensure_venv_and_reexec(sys.argv[1:])

    if args.check:
        items = build_report(deps)
        print_report(items)
        if _JSON:
            print("REPORT_JSON " + json.dumps({"ok": all(i["status"] == "OK" or i["required"] == "optional" for i in items),
                                               "items": items}), flush=True)
        return 0

    failures: list[str] = []
    extra: dict[str, dict] = {}
    progress(0)

    # --- pip ---
    if not args.no_pip:
        req = ROOT / deps.get("pip", {}).get("requirements", "requirements.txt")
        need = [d for d in dc.check_pip(req) if d.status != "OK"]
        if need:
            say(f"Installing pip packages: {', '.join(d.name for d in need)}")
            ok, msg = pip_install(req, args.pip_index_url)
            if not ok:
                failures.append(f"pip install failed:\n{msg}")
        else:
            say("pip packages already satisfied.")
        if args.dev:
            dev = ROOT / deps.get("pip", {}).get("dev_requirements", "requirements-dev.txt")
            if dev.is_file():
                ok, msg = pip_install(dev, args.pip_index_url)
                if not ok:
                    failures.append(f"dev pip install failed:\n{msg}")
    progress(20)

    # --- binaries ---
    if not args.no_binaries:
        bins = deps.get("binaries", [])
        span = 75.0 / max(1, len(bins))
        for i, entry in enumerate(bins):
            base = 20 + span * i
            ver = binary_installed(entry)
            if ver:
                say(f"{entry['name']} already installed: {ver}")
                progress(base + span)
                continue
            local = Path(args.ffmpeg_zip) if (args.ffmpeg_zip and entry["name"] == "ffmpeg") else None
            ok, msg = install_binary(entry, local, args.yes, base, span)
            if ok:
                say(f"{entry['name']} installed: {msg}")
                for f in entry["files"]:
                    extra[Path(f).stem] = {"status": "Installed"}
            else:
                say(f"{entry['name']} install failed: {msg}")
                fb = entry.get("pip_fallback")
                if fb:
                    say(f"Trying pip fallback: {fb}")
                    ok2, msg2 = pip_install(Path("__none__"), args.pip_index_url, extra=[fb])
                    if ok2:
                        say(f"Installed {fb}. ffmpeg will be located through it (ffprobe is not included).")
                    else:
                        failures.append(f"{entry['name']}: {msg}\npip fallback failed: {msg2}")
                else:
                    failures.append(f"{entry['name']}: {msg}")
    progress(95)

    items = build_report(deps, extra)
    print_report(items)
    if failures:
        say("Some steps FAILED:")
        for f in failures:
            say("  - " + f.replace("\n", "\n    "))
        say()
        say("Manual steps:")
        say("  1) Download an ffmpeg Windows build (e.g. https://www.gyan.dev/ffmpeg/builds/).")
        say("  2) Copy ffmpeg.exe and ffprobe.exe into: " + str(ROOT / "bin"))
        say("  3) Or run:  python bootstrap.py --ffmpeg-zip <downloaded zip>")
        say("  If an antivirus quarantined ffmpeg.exe, add an exception for the bin folder.")
    progress(100)
    if _JSON:
        print("REPORT_JSON " + json.dumps({"ok": not failures, "items": items}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
