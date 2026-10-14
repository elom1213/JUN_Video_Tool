# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""JUN Video Tool 진입점 (PLAN 13.4).

PySide6 가 없어도 import 에러 없이 안내할 수 있도록, Qt 는 의존성 점검 뒤에 import 한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ask_yes_no(question: str) -> bool:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        ans = messagebox.askyesno("JUN Video Tool", question)
        root.destroy()
        return bool(ans)
    except Exception:
        try:
            return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")
        except EOFError:
            return False


def _precheck() -> bool:
    """필수 pip 패키지가 없으면 setup 실행을 제안한다. True 면 계속 진행."""
    from app.core.dependency_check import missing_pip_packages

    missing = missing_pip_packages()
    if not missing:
        return True
    msg = (f"Missing or outdated packages: {', '.join(missing)}.\n"
           f"Run setup now? (same as double-clicking setup.bat)")
    print(msg)
    if _ask_yes_no(msg):
        subprocess.call([sys.executable, str(ROOT / "bootstrap.py")])
        print("Setup finished. Start the tool again with run.bat or: python launch.py")
    else:
        print("Run setup.bat to install the dependencies, then start the tool again.")
    return False


def run() -> int:
    if not _precheck():
        return 1

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("JUN Video Tool")
    app.setOrganizationName("JUN")

    qss = ROOT / "app" / "ui" / "styles" / "dark.qss"
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))

    from app.ui.main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
