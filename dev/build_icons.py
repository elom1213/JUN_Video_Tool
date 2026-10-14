# -*- coding: utf-8 -*-
# Python Script by Ji Hun Park
# last Update date : 2026-10-14
"""app.svg → app.png (256px) + app.ico (16~256 다중 크기) 생성. 툴바 SVG 미리보기 시트도 만든다.

    python dev/build_icons.py            # app/ui/icons/app.png, app.ico 갱신
    python dev/build_icons.py --sheet out.png   # 모든 SVG 를 한 장에 렌더해 확인
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ICON_DIR = ROOT / "app" / "ui" / "icons"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_svg(svg: Path, size: int) -> QImage:
    r = QSvgRenderer(str(svg))
    if not r.isValid():
        raise SystemExit(f"Invalid SVG: {svg}")
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    r.render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def build_app_icon() -> None:
    svg = ICON_DIR / "app.svg"
    png = ICON_DIR / "app.png"
    ico = ICON_DIR / "app.ico"
    big = render_svg(svg, 256)
    if not big.save(str(png), "PNG"):
        raise SystemExit("Failed to write app.png")
    print(f"wrote {png}")
    # Qt 의 ico 플러그인은 한 파일에 한 이미지만 쓰므로, 다중 크기 ICO 는 직접 조립한다 (PNG 압축 엔트리)
    _write_multi_ico(ico, [render_svg(svg, s) for s in ICO_SIZES])
    print(f"wrote {ico} ({', '.join(str(s) for s in ICO_SIZES)})")


def _write_multi_ico(path: Path, images: list[QImage]) -> None:
    """ICO 컨테이너를 수동 작성. 각 엔트리는 PNG 데이터 (Vista+ 지원, Windows 10/11 OK)."""
    import struct
    from PySide6.QtCore import QBuffer, QIODevice

    entries: list[tuple[int, int, bytes]] = []
    for img in images:
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        entries.append((img.width(), img.height(), bytes(buf.data())))
        buf.close()
    header = struct.pack("<HHH", 0, 1, len(entries))
    dir_size = 16 * len(entries)
    offset = 6 + dir_size
    directory = b""
    blobs = b""
    for w, h, data in entries:
        directory += struct.pack("<BBBBHHII", 0 if w >= 256 else w, 0 if h >= 256 else h, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    path.write_bytes(header + directory + blobs)


def build_sheet(out: Path, cell: int = 48) -> None:
    svgs = sorted(p for p in ICON_DIR.glob("*.svg") if p.stem != "app")
    cols = 6
    rows = (len(svgs) + cols - 1) // cols
    img = QImage(cols * cell * 2, rows * cell * 2, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor("#2b2b2b"))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for i, svg in enumerate(svgs):
        x, y = (i % cols) * cell * 2, (i // cols) * cell * 2
        # 왼쪽: 어두운 배경, 오른쪽: 코랄(체크 상태) 배경
        p.fillRect(x + cell, y, cell, cell, QColor("#e8734a"))
        ic = render_svg(svg, cell - 16)
        p.drawImage(x + 8, y + 8, ic)
        p.drawImage(x + cell + 8, y + 8, ic)
        p.setPen(QColor("#9a9a9a"))
        p.drawText(QRectF(x, y + cell, cell * 2, cell), Qt.AlignmentFlag.AlignCenter, svg.stem)
    p.end()
    img.save(str(out), "PNG")
    print(f"wrote {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", type=str, default=None, help="render all toolbar icons into one PNG")
    args = ap.parse_args()
    app = QGuiApplication([])
    app.setApplicationName("build_icons")
    build_app_icon()
    if args.sheet:
        build_sheet(Path(args.sheet))
    return 0


if __name__ == "__main__":
    sys.exit(main())
