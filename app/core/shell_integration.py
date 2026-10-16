# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-16
"""Windows 셸 통합: 시작 메뉴 바로가기 · 작업표시줄 고정 · 창 재실행 정보. PySide6 비의존.

- 시작 메뉴: `%APPDATA%/Microsoft/Windows/Start Menu/Programs/JUN Video Tool.lnk` 를 만든다. 대상은 pythonw.exe +
  `launch.py`(콘솔 창 없음), 아이콘은 app.ico, 그리고 AppUserModelID 를 바로가기에 넣어 실행 중인 창과 같은 작업표시줄
  버튼으로 묶이게 한다. .lnk 의 AppUserModelID 는 WScript.Shell 로는 못 쓰므로 PowerShell 의 Add-Type(C#) 으로
  IShellLinkW + IPropertyStore 를 직접 호출한다 (pywin32 의존 없음).
- 작업표시줄: Windows 10 1809+ / 11 은 프로그램이 스스로 고정하는 공식 API 가 없다. 셸 동사("Pin to taskbar")가 보이는
  환경에서만 자동 고정을 시도하고, 아니면 사용자가 작업표시줄 버튼을 우클릭 → 고정하도록 안내한다. 그때 고정된 아이콘이
  python.exe 가 아니라 이 툴을 실행하도록 창에 Relaunch 속성(set_window_relaunch)을 미리 넣어 둔다.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config.version import APP_NAME, APP_USER_MODEL_ID
from .utils import subprocess_flags, tool_root

SHORTCUT_NAME = f"{APP_NAME}.lnk"
_PKEY_APPUSERMODEL = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"   # System.AppUserModel.* fmtid
_PID_RELAUNCH_COMMAND = 2
_PID_RELAUNCH_ICON = 3
_PID_RELAUNCH_NAME = 4
_PID_ID = 5


class ShellIntegrationError(Exception):
    pass


def is_supported() -> bool:
    return sys.platform.startswith("win")


@dataclass(frozen=True)
class LaunchSpec:
    target: Path          # pythonw.exe
    arguments: str        # "\"<root>\\launch.py\""
    workdir: Path
    icon: Path

    @property
    def command_line(self) -> str:
        return f'"{self.target}" {self.arguments}'


def launch_spec(executable: Path | None = None, root: Path | None = None) -> LaunchSpec:
    """지금 돌고 있는 Python 의 pythonw.exe 로 launch.py 를 실행하는 명령 (콘솔 창이 뜨지 않게)."""
    exe = Path(executable or sys.executable)
    root = Path(root or tool_root())
    if exe.name.lower() == "python.exe":
        w = exe.with_name("pythonw.exe")
        if w.is_file():
            exe = w
    return LaunchSpec(target=exe, arguments=f'"{root / "launch.py"}"', workdir=root,
                      icon=root / "app" / "ui" / "icons" / "app.ico")


def start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def start_menu_shortcut() -> Path:
    return start_menu_dir() / SHORTCUT_NAME


def taskbar_pinned_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"


# ---------------------------------------------------------------------------
# PowerShell 실행 (C# 은 PowerShell 5.1 의 Add-Type 이 컴파일한다 — Windows 10/11 기본 탑재)
# ---------------------------------------------------------------------------
_CSHARP = r'''
using System;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
namespace JunShell {
  [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder f, int c, IntPtr fd, uint fl);
    void GetIDList(out IntPtr p);
    void SetIDList(IntPtr p);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string s);
    void GetHotkey(out short h);
    void SetHotkey(short h);
    void GetShowCmd(out int c);
    void SetShowCmd(int c);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder s, int c, out int i);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string s, int i);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string s, uint r);
    void Resolve(IntPtr h, uint f);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string s);
  }
  [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IPropertyStore {
    void GetCount(out uint c);
    void GetAt(uint i, out PropertyKey k);
    void GetValue(ref PropertyKey k, out PropVariant v);
    void SetValue(ref PropertyKey k, ref PropVariant v);
    void Commit();
  }
  [StructLayout(LayoutKind.Sequential, Pack = 4)]
  struct PropertyKey { public Guid fmtid; public uint pid; }
  [StructLayout(LayoutKind.Explicit, Size = 24)]
  struct PropVariant { [FieldOffset(0)] public ushort vt; [FieldOffset(8)] public IntPtr p; }
  [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
  class CShellLink {}
  public static class Lnk {
    static readonly Guid AUM = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
    public static void Create(string lnk, string target, string args, string wd, string icon, string aumid, string desc) {
      var link = (IShellLinkW)new CShellLink();
      link.SetPath(target);
      link.SetArguments(args);
      link.SetWorkingDirectory(wd);
      link.SetIconLocation(icon, 0);
      link.SetDescription(desc);
      var store = (IPropertyStore)link;
      var key = new PropertyKey { fmtid = AUM, pid = 5 };
      var pv = new PropVariant { vt = 31, p = Marshal.StringToCoTaskMemUni(aumid) };
      try { store.SetValue(ref key, ref pv); store.Commit(); }
      finally { Marshal.FreeCoTaskMem(pv.p); }
      ((IPersistFile)link).Save(lnk, true);
    }
    public static string ReadAumid(string lnk) {
      var link = (IShellLinkW)new CShellLink();
      ((IPersistFile)link).Load(lnk, 0);
      var key = new PropertyKey { fmtid = AUM, pid = 5 };
      PropVariant pv;
      ((IPropertyStore)link).GetValue(ref key, out pv);
      return pv.vt == 31 ? Marshal.PtrToStringUni(pv.p) : "";
    }
  }
}
'''

_PS_CREATE = r'''
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition (Get-Content -Raw -LiteralPath $env:JUN_CS)
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $env:JUN_LNK) | Out-Null
[JunShell.Lnk]::Create($env:JUN_LNK, $env:JUN_TARGET, $env:JUN_ARGS, $env:JUN_WD, $env:JUN_ICON, $env:JUN_AUMID, $env:JUN_DESC)
'OK:' + [JunShell.Lnk]::ReadAumid($env:JUN_LNK)
'''

_PS_READ_AUMID = r'''
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition (Get-Content -Raw -LiteralPath $env:JUN_CS)
foreach ($f in (Get-ChildItem -LiteralPath $env:JUN_DIR -Filter *.lnk -ErrorAction SilentlyContinue)) {
  try { 'LNK:' + $f.Name + '|' + [JunShell.Lnk]::ReadAumid($f.FullName) } catch { }
}
'''

_PS_PIN = r'''
$ErrorActionPreference = 'Continue'   # 열거 중 비종료 오류로 멈추지 않게 (결과는 출력으로 판정)
$shell = New-Object -ComObject Shell.Application
$item = $shell.Namespace((Split-Path -Parent $env:JUN_LNK)).ParseName((Split-Path -Leaf $env:JUN_LNK))
$names = @($item.Verbs() | ForEach-Object { $_.Name.Replace('&', '') })
if ($names | Where-Object { $_ -match $env:JUN_UNPIN }) { 'ALREADY'; exit 0 }
$verb = $item.Verbs() | Where-Object { $_.Name.Replace('&', '') -match $env:JUN_PIN } | Select-Object -First 1
if ($verb) { $verb.DoIt(); 'PINNED' } else { 'UNAVAILABLE' }
'''


def _run_ps(script: str, env_extra: dict[str, str], timeout: float = 60.0) -> str:
    if not is_supported():
        raise ShellIntegrationError("Shortcuts are only supported on Windows.")
    with tempfile.TemporaryDirectory(prefix="jun_shell_") as td:
        cs = Path(td) / "lnk.cs"
        ps = Path(td) / "run.ps1"
        cs.write_text(_CSHARP, encoding="utf-8")
        # PowerShell 5.1 은 BOM 없는 UTF-8 스크립트를 ANSI 로 읽으므로 BOM 을 붙인다 (한글 동사 이름)
        ps.write_text(script, encoding="utf-8-sig")
        env = dict(os.environ)
        env.update(env_extra)
        env["JUN_CS"] = str(cs)
        try:
            proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                   "-File", str(ps)], capture_output=True, env=env, timeout=timeout,
                                  creationflags=subprocess_flags())
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ShellIntegrationError(f"PowerShell failed: {exc}") from exc
    out = proc.stdout.decode("utf-8", "replace") if proc.stdout else ""
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines() if proc.stderr else []
        raise ShellIntegrationError(err[0] if err else f"PowerShell exited with code {proc.returncode}.")
    return out


def create_shortcut(lnk: Path, spec: LaunchSpec | None = None, aumid: str = APP_USER_MODEL_ID) -> Path:
    """바로가기를 만들거나 덮어쓴다 (툴 폴더를 옮긴 뒤 다시 누르면 경로가 갱신된다)."""
    spec = spec or launch_spec()
    out = _run_ps(_PS_CREATE, {
        "JUN_LNK": str(lnk), "JUN_TARGET": str(spec.target), "JUN_ARGS": spec.arguments,
        "JUN_WD": str(spec.workdir), "JUN_ICON": str(spec.icon), "JUN_AUMID": aumid,
        "JUN_DESC": f"{APP_NAME} — video converter and frame draw-over tool",
    })
    if f"OK:{aumid}" not in out:
        raise ShellIntegrationError("Shortcut was written but its app ID could not be verified.")
    return lnk


def add_to_start_menu() -> Path:
    return create_shortcut(start_menu_shortcut())


def find_pinned_taskbar_shortcut(aumid: str = APP_USER_MODEL_ID) -> Path | None:
    """작업표시줄에 이미 고정된 이 툴의 바로가기 (AppUserModelID 또는 이름으로 찾는다)."""
    d = taskbar_pinned_dir()
    if not d.is_dir():
        return None
    try:
        out = _run_ps(_PS_READ_AUMID, {"JUN_DIR": str(d)})
    except ShellIntegrationError:
        out = ""
    for line in out.splitlines():
        if not line.startswith("LNK:"):
            continue
        name, _, ident = line[4:].partition("|")
        if ident.strip() == aumid:
            return d / name
    named = d / SHORTCUT_NAME
    return named if named.is_file() else None


_VERBS = {
    "start": ("Pin to Start|시작 화면에 고정", "Unpin from Start|시작 화면에서 고정 해제"),
    "taskbar": ("Pin to taskbar|작업 표시줄에 고정", "Unpin from taskbar|작업 표시줄에서 고정 해제"),
}


def pin_shortcut(lnk: Path, where: str) -> str:
    """셸 동사로 시작 화면("start") / 작업표시줄("taskbar")에 고정한다.

    반환: "pinned" | "already" | "unavailable". 작업표시줄 동사는 Windows 10 1809+ / 11 에서 보통 없다
    (프로그램이 스스로 고정하는 것을 Windows 가 막았다).
    """
    pin, unpin = _VERBS[where]
    try:
        out = _run_ps(_PS_PIN, {"JUN_LNK": str(lnk), "JUN_PIN": pin, "JUN_UNPIN": unpin})
    except ShellIntegrationError:
        return "unavailable"
    if "ALREADY" in out:
        return "already"
    return "pinned" if "PINNED" in out else "unavailable"


# ---------------------------------------------------------------------------
# 창 재실행 속성 (작업표시줄 버튼 우클릭 → 고정 시 이 툴을 실행하게)
# ---------------------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("p", ctypes.c_void_p), ("p2", ctypes.c_void_p)]


def _guid(text: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


def set_window_relaunch(hwnd: int, spec: LaunchSpec | None = None, aumid: str = APP_USER_MODEL_ID) -> bool:
    """창에 AppUserModel.ID / RelaunchCommand / RelaunchIconResource / RelaunchDisplayNameResource 를 넣는다."""
    if not is_supported() or not hwnd:
        return False
    spec = spec or launch_spec()
    try:
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        store = ctypes.c_void_p()
        iid = _guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
        hr = shell32.SHGetPropertyStoreForWindow(ctypes.c_void_p(hwnd), ctypes.byref(iid), ctypes.byref(store))
        if hr != 0 or not store:
            return False
        vtbl = ctypes.cast(ctypes.cast(store, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        proto_set = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_PROPERTYKEY),
                                       ctypes.POINTER(_PROPVARIANT))
        proto_unary = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
        set_value = proto_set(vtbl[6])
        commit = proto_unary(vtbl[7])
        release = proto_unary(vtbl[2])
        fmtid = _guid(_PKEY_APPUSERMODEL)
        ok = True
        try:
            # ID 를 마지막에 넣는다 (MS 문서: Relaunch 속성은 ID 와 함께 있어야 쓰인다)
            for pid, value in ((_PID_RELAUNCH_COMMAND, spec.command_line),
                               (_PID_RELAUNCH_ICON, f"{spec.icon},0"),
                               (_PID_RELAUNCH_NAME, APP_NAME),
                               (_PID_ID, aumid)):
                buf = ctypes.create_unicode_buffer(value)
                pv = _PROPVARIANT(vt=31, p=ctypes.cast(buf, ctypes.c_void_p))
                key = _PROPERTYKEY(fmtid, pid)
                ok = set_value(store, ctypes.byref(key), ctypes.byref(pv)) == 0 and ok
            commit(store)
        finally:
            release(store)
        return ok
    except (OSError, AttributeError, ValueError):
        return False
