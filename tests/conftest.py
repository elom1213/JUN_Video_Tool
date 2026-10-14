# -*- coding: utf-8 -*-
"""pytest 공용 설정: 저장소 루트를 sys.path 에 추가."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
