# JUN_Video_Tool — Python 3.14 지원 계획서 (v0.2.1)

- **Author**: Ji Hun Park (Junny / `Dnable_JunnyPark`)
- **작성일**: 2026-10-16
- **상태**: 설계 확정본. 구현 전.
- **선행 문서**: [`PLAN.md`](PLAN.md) 12장(Win10 호환 규칙) · 13장(의존성 일괄 설치). 이 문서는 13장의 **Python 버전 게이트**를
  고치는 증분 계획이다. 코어 · UI · 변환 로직은 건드리지 않는다.
- **이 문서의 목표**: 이 문서만 읽고 바로 작업을 시작할 수 있어야 한다. 바뀌는 파일 · 함수 시그니처 · 문자열 · 테스트 · 검증 절차 ·
  완료 기준이 전부 여기에 있다.

---

## 0. 한 줄 요약

**툴 코드는 이미 Python 3.14 에서 돌 수 있다.** 막고 있는 것은 `deps.json` 의 `"max_exclusive": "3.14"` 와
`dependency_check.check_all()` 에 하드코딩된 `< (3, 14)` 두 곳뿐이다. 유일한 바이너리 의존성인 PySide6 는 **6.10.1 부터
Python 3.14 를 공식 지원**하고, 현재 `requirements.txt` 의 `PySide6>=6.8,<7` 은 3.14 에서 pip 가 자동으로 6.12.0 을 고른다.

따라서 작업은 ① 게이트를 `<3.15` 로 올리고 ② 하드코딩을 없애 `deps.json` 을 단일 소스로 만들고 ③ PySide6 휠이 없는
**free-threaded 빌드(3.14t)** 를 명시적으로 거부하고 ④ 문서 · 테스트 · 버전을 갱신하는 것이다. 코드 변경은 5개 파일, 50줄 안팎.

---

## 1. 조사 결과 (2026-10-16, 이 PC 에서 확인)

### 1.1 왜 지금 3.14 가 막히는가

사용자 보고 메시지 `Python 3.14.0 is not supported. Install Python 3.11 (below 3.14).` 는 `bootstrap.py` `main()` 의
Python 게이트가 내는 것이다. 게이트는 두 군데에 **따로** 있다.

| 위치 | 현재 코드 | 성격 |
|------|-----------|------|
| `deps.json` 2행 | `"python": {"min": "3.11", "max_exclusive": "3.14"}` | `bootstrap.python_ok()` · `build_report()` 가 읽는 설정값 |
| `app/core/dependency_check.py` 160~162행 `check_all()` | `">=3.11,<3.14"` 문자열과 `(3, 11) <= sys.version_info[:2] < (3, 14)` | 앱 안 `Help > Check Dependencies…` 의 Python 행. **deps.json 과 무관한 중복** |
| `bootstrap.py` 390행 | `f"Python {cur} is not supported. Install Python {min} (below {max_exclusive})."` | 안내 문구 |

`"3.14"` 는 2026-10-14 설계 시점에 PySide6 6.9.x 의 PyPI 메타데이터(`Requires-Python <3.14`)를 그대로 옮긴 값이다.
그 뒤 PySide6 가 3.14 지원을 추가했으므로 **값만 낡은 상태**다.

### 1.2 PySide6 의 Python 3.14 지원 (PyPI 메타데이터 `https://pypi.org/pypi/PySide6/json`)

| PySide6 | `Requires-Python` | 휠 태그 (win_amd64) | 3.14 에서 pip 선택 가능 |
|---------|-------------------|---------------------|-------------------------|
| 6.9.0 ~ 6.10.0 | `>=3.9,<3.14` | `cp39-abi3` | ✗ (메타데이터에서 제외) |
| 6.10.3 | `>=3.9,<3.15` | `cp39-abi3` | ○ |
| 6.11.0 ~ 6.11.2 | `>=3.10,<3.15` | `cp310-abi3` | ○ |
| **6.12.0 (최신)** | `>=3.10,<3.16` | `cp310-abi3` | ○ |

- Qt for Python 6.10.1 changelog: `[PYSIDE-3147] Python 3.14 is now supported.`
- 휠은 전부 **abi3(안정 ABI)** 이므로 3.14 전용 `cp314` 태그가 없어도 설치된다. 단, abi3 는 **free-threaded 빌드(`3.14t`)와 호환되지 않는다** → 2.3 에서 거부.
- 실측: 이 PC(3.11.9) 에서 3.14 를 대상으로 해석시킨 결과 현재 `requirements.txt` 그대로 6.12.0 이 선택됐다.
  ```
  py -3.11 -m pip download --no-deps --only-binary=:all: --python-version 3.14 --platform win_amd64 --implementation cp -d dl "PySide6>=6.8,<7"
  → pyside6-6.12.0-cp310-abi3-win_amd64.whl  (shiboken6 · PySide6_Essentials 6.12.0 도 동일하게 해석됨)
  ```

### 1.3 툴 코드의 3.14 호환성

`app/`, `launch.py`, `bootstrap.py`, `dev/` 의 import 전수 확인 결과 3.13/3.14 에서 제거된 모듈(`cgi` `imghdr` `telnetlib`
`pipes` `pkgutil.get_loader` `asyncio` 정책 API 등)은 쓰지 않는다. 쓰는 표준 라이브러리는 `argparse atexit collections
concurrent.futures ctypes dataclasses datetime enum fnmatch hashlib html importlib.metadata json math os pathlib re shutil
subprocess sys tempfile threading time tkinter typing urllib.request venv zipfile` 로 전부 3.14 에 그대로 있다.
`from __future__ import annotations` 는 PEP 649(지연 평가 어노테이션) 아래서도 유효하다. **코어 · UI 코드 변경은 없다.**

### 1.4 Python 3.14 의 Windows 배포 방식 변경 (설치 안내에 영향)

3.14 부터 python.org 는 기존 전체 설치 프로그램 대신 **Python install manager**(`pymanager`) 를 기본으로 안내한다
(`docs.python.org/3.14/using/windows.html`). 이 툴의 `.bat` 에 관련된 사실:

| 항목 | 사실 | 이 툴에 미치는 영향 |
|------|------|---------------------|
| 제공 명령 | `python` `py` `pymanager` + 창 없는 `pythonw` `pyw` `pywmanager` | `setup.bat` 의 `py -3`, `run.bat` 의 `pyw -3` / `pythonw` 모두 그대로 동작 |
| 버전 선택 | `py -V:3.11`, 공식 릴리스는 `V:` 생략 가능(`py -3.11`) | 변경 없음 |
| 기본 인터프리터 | "최신 안정 릴리스" (`PYTHON_MANAGER_DEFAULT` 로 변경 가능) | 3.11 과 3.14 가 같이 있으면 `py -3` 은 **3.14** 를 고른다 → 이 계획으로 3.14 가 통과해야 함 |
| free-threaded | `py install 3.14t` 로 별도 설치. 기존 런처는 `py -3` 이 **t 빌드를 우선**할 수 있다고 경고 | PySide6 설치가 실패하므로 bootstrap 이 먼저 알아채고 영어 메시지로 거부해야 함 (2.3) |
| tkinter | install manager 배포본에 포함 여부가 문서에 없음 | `launch._ask_yes_no()` 가 이미 콘솔 `input()` 으로 폴백한다. 변경 없음 |

### 1.5 이 PC 상태

`py --list` → **3.11.9 만 설치**, 3.14 없음. 따라서 3.14 검증(5장)은 3.14 설치부터 시작한다.
현재 `python -m pytest -q` → 43 passed.

---

## 2. 결정

### 2.1 지원 범위 상한: `max_exclusive = "3.15"`

| 후보 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **`"3.15"`** (3.11 ~ 3.14) | PySide6 가 공식 지원하고 실측 가능한 범위만 연다. 3.15 가 나오면 PySide6 메타데이터 확인 후 값만 올리면 됨 | 3.15 출시(2026-10 예정) 뒤 같은 보고가 한 번 더 올 수 있음 | **채택** |
| `"4.0"` (사실상 무제한) | 재발 없음 | PySide6 휠이 없는 버전에서 Python 행은 `OK` 인데 pip 설치만 실패해 원인 파악이 어려움. 6.12.0 메타데이터도 `<3.16` 으로 닫혀 있어 어차피 3.16 은 설치 불가 | 보류 |
| `"3.14"` 유지 + 메시지만 개선 | 변경 최소 | 사용자 요구를 못 채움 | 기각 |

### 2.2 `deps.json` 을 단일 소스로 — `dependency_check` 의 하드코딩 제거

`check_all()` 의 `">=3.11,<3.14"` 와 `(3, 14)` 를 지우고, `dependency_check` 가 `deps.json` 을 읽는 `python_spec()` 을 두어
`bootstrap.python_ok()` 와 `check_all()` 이 **같은 함수**를 쓰게 한다. `dependency_check` 는 PySide6 없이 import 돼야 하는
표준 라이브러리 전용 모듈인데 `json` 은 표준이므로 조건을 지킨다.

### 2.3 free-threaded 빌드는 명시적으로 거부

판정 기준: `sysconfig.get_config_var("Py_GIL_DISABLED") == 1` (3.13+ 에서 free-threaded 빌드면 1, 일반 빌드면 0/None).
`sys._is_gil_enabled()` 는 런타임 상태(`-X gil=1` 로 바뀔 수 있음)라 쓰지 않는다. 상태 문자열은 새 값 **`"Unsupported"`**
(기존 `"Outdated"` 는 "버전이 낮다" 는 뜻이라 혼동). `DependencyDialog` 의 색 분기에 `"Unsupported"` 를 추가한다.

### 2.4 `requirements.txt` 는 그대로 `PySide6>=6.8,<7`

3.14 에서는 pip 가 메타데이터로 6.9.x 이하를 스스로 제외하므로(1.2) 하한을 올릴 필요가 없다. 환경 마커
(`; python_version >= "3.14"`) 는 자체 파서 `parse_requirements()` 가 마커를 모르기 때문에 넣지 않는다.
3.11 PC 에 이미 깔린 6.9.x · 6.11.1 도 계속 `OK` 다.

### 2.5 `.bat` 는 변경하지 않는다

`py -3` 이 3.14 를 고르는 것이 이번 작업의 목적과 일치한다. 3.14t 가 잡히는 경우는 bootstrap 메시지로 안내한다(2.3).
3.11 을 강제로 쓰고 싶은 사용자는 README 에 적는 `py -3.11 bootstrap.py` / `set PY_PYTHON=3.11` 로 해결한다.

### 2.6 버전: `0.2.1`, 문서 · CHANGELOG 동반 갱신

---

## 3. 파일별 변경 (이 순서대로 작업)

### 3.1 `deps.json`

```json
"python": {"min": "3.11", "max_exclusive": "3.15"},
```
나머지는 그대로.

### 3.2 `app/core/dependency_check.py`

상단 import 에 `import json`, `import sys`, `import sysconfig` 추가(기존 `check_all()` 안의 지역 `import sys` 는 제거).
`check_all()` 바로 위에 다음 세 함수를 추가한다.

```python
_DEFAULT_PY_SPEC = {"min": "3.11", "max_exclusive": "3.15"}


def python_spec() -> dict:
    """deps.json 의 "python" 항목. 파일이 없거나 깨졌으면 기본값. (bootstrap 과 앱이 같은 소스를 본다)"""
    try:
        with open(tool_root() / "deps.json", encoding="utf-8") as f:
            spec = json.load(f).get("python") or {}
    except (OSError, ValueError):
        spec = {}
    return {**_DEFAULT_PY_SPEC, **spec}


def is_free_threaded() -> bool:
    """free-threaded(GIL 없는) 빌드면 True. PySide6 abi3 휠은 이 빌드에 설치되지 않는다."""
    return sysconfig.get_config_var("Py_GIL_DISABLED") == 1


def python_status(spec: dict | None = None,
                  version: tuple[int, ...] | None = None,
                  free_threaded: bool | None = None) -> DependencyStatus:
    """현재 인터프리터가 지원 범위인지. 인자는 테스트용 — 생략하면 실행 중인 인터프리터를 본다."""
    spec = spec or python_spec()
    v = tuple(version if version is not None else sys.version_info[:3])
    ft = is_free_threaded() if free_threaded is None else free_threaded
    lo = version_tuple(spec["min"])
    hi = version_tuple(spec["max_exclusive"])
    required = f">={spec['min']},<{spec['max_exclusive']}"
    found = ".".join(str(x) for x in v) + ("t (free-threaded)" if ft else "")
    if ft:
        status = "Unsupported"
    elif _cmp(v[: len(lo)], lo) < 0:
        status = "Outdated"
    elif _cmp(v[: len(hi)], hi) >= 0:
        status = "Unsupported"
    else:
        status = "OK"
    return DependencyStatus("Python", "python", required, found, status, sys.executable)
```

`check_all()` 은 다음으로 바뀐다.

```python
def check_all() -> list[DependencyStatus]:
    return [python_status()] + check_pip() + check_binaries()
```

`DependencyStatus.status` 주석을 `"OK" | "Missing" | "Outdated" | "Unsupported" | "Unknown"` 으로 갱신한다.

### 3.3 `bootstrap.py`

- `python_ok()` 를 `dependency_check.python_status()` 의 얇은 래퍼로 바꾼다 (시그니처 유지 — `tests/test_bootstrap.py` 와 `build_report()` 가 쓴다).
  ```python
  def python_ok(spec: dict) -> tuple[bool, str]:
      st = dc.python_status(spec)
      return st.status == "OK", st.found
  ```
- `build_report()` 의 Python 행은 `dc.python_status(deps.get("python")).to_dict()` 한 줄로 교체한다 (`required` · `found` · `status` · `location` 이 같은 키로 나온다).
- `main()` 의 거부 메시지(390~391행)를 다음으로 교체한다. 변수는 `spec = deps.get("python", {})`, `st = dc.python_status(spec)`.
  ```python
  if st.status != "OK":
      hi = dc.version_tuple(spec.get("max_exclusive", "3.15"))
      newest = f"{hi[0]}.{hi[1] - 1}" if len(hi) >= 2 and hi[1] > 0 else spec.get("min", "3.11")
      if dc.is_free_threaded():
          say(f"Python {st.found} is a free-threaded build, which PySide6 does not support. "
              f"Install the standard (non free-threaded) Python {spec.get('min', '3.11')}-{newest} 64-bit.")
      else:
          say(f"Python {st.found} is not supported. Install Python {spec.get('min', '3.11')}-{newest} 64-bit "
              f"(supported range {st.required}).")
      items = build_report(deps)
      if _JSON:
          print("REPORT_JSON " + json.dumps({"ok": False, "items": items}), flush=True)
      return 2
  ```
  예시 출력: `Python 3.15.0 is not supported. Install Python 3.11-3.14 64-bit (supported range >=3.11,<3.15).`
- 모듈 독스트링의 `--json` 프로토콜 설명에 `status` 값으로 `Unsupported` 가 올 수 있음을 한 줄 추가.
- `# last Update date : 2026-10-16`.

### 3.4 `app/ui/dependency_dialog.py`

173행 `elif status in ("Missing", "Outdated", "FAILED"):` → `elif status in ("Missing", "Outdated", "Unsupported", "FAILED"):`.
`Unsupported` 는 `Outdated` 와 같이 노란색이고, `required != "optional"` 이므로 `Install Missing` 버튼이 켜진다 — 단 Python 은
bootstrap 이 코드 2 로 즉시 끝나며 위 메시지를 로그 패널에 남기므로 사용자는 무엇을 설치해야 하는지 바로 본다. 추가 분기는 두지 않는다.

### 3.5 `app/config/version.py` · `CHANGELOG.md`

- `VERSION = "0.2.1"`, `LAST_UPDATE = "2026-10-16"`.
- CHANGELOG 맨 위:
  ```
  ## 0.2.1 — 2026-10-16

  - **Python 3.14 지원**: 지원 범위를 3.11 ~ 3.14 로 확장 (`deps.json` `max_exclusive` 3.15). PySide6 는 6.10.1 부터 3.14 를
    지원하며 기존 `PySide6>=6.8,<7` 그대로 3.14 에서는 6.12.0 이 설치된다.
  - Python 버전 판정을 `dependency_check.python_status()` 로 통합. 앱 안 `Check Dependencies…` 와 `bootstrap.py` 가 같은
    `deps.json` 값을 본다 (이전에는 앱 쪽에 3.14 미만이 하드코딩돼 있었다).
  - free-threaded 빌드(3.13t / 3.14t) 는 PySide6 휠이 없으므로 `Unsupported` 로 표시하고 표준 빌드 설치를 안내한다.
  - 지원 범위 밖 Python 안내 문구에 설치할 버전 범위(`3.11-3.14`)를 직접 적는다.
  ```

### 3.6 `README.md` · `docs/PLAN.md`

- README 설치 1단계: `1. **Python 3.11 ~ 3.14** (64-bit, 표준 빌드) 를 설치한다 (python.org, "Add to PATH" 체크). free-threaded(3.14t) 빌드는 지원하지 않는다.`
- README "오프라인 · 프록시 환경" 코드 블록 아래 한 줄 추가:
  `여러 Python 이 설치돼 있으면 setup.bat 은 가장 최신 3.x 를 쓴다. 특정 버전을 쓰려면 \`py -3.11 bootstrap.py\` 처럼 직접 실행하거나 \`set PY_PYTHON=3.11\` 을 둔다.`
- PLAN.md 8행 · 12.1 표 Python 행 · 13.1 · 13.2 JSON · 13.6 README 요약의 `Python 3.11` 을 `Python 3.11 ~ 3.14` / `"max_exclusive": "3.15"` 로 맞춘다.
  12.1 VC 런타임 행의 "Python 3.11 은 UCRT 사용" 은 3.12~3.14 도 동일하므로 "Python 3.11+ 는 UCRT 사용" 으로.

### 3.7 `tests/test_bootstrap.py`

기존 `test_deps_json_schema` 에 `assert deps["python"]["max_exclusive"] == "3.15"` 추가. 새 테스트:

```python
from app.core.dependency_check import python_status

_SPEC = {"min": "3.11", "max_exclusive": "3.15"}


def test_python_status_range():
    assert python_status(_SPEC, (3, 11, 9), False).status == "OK"
    assert python_status(_SPEC, (3, 14, 0), False).status == "OK"
    assert python_status(_SPEC, (3, 10, 11), False).status == "Outdated"
    assert python_status(_SPEC, (3, 15, 0), False).status == "Unsupported"
    assert python_status(_SPEC, (3, 14, 0), True).status == "Unsupported"


def test_python_status_fields():
    st = python_status(_SPEC, (3, 14, 0), True)
    assert st.required == ">=3.11,<3.15"
    assert st.found == "3.14.0t (free-threaded)"
    assert st.kind == "python" and st.name == "Python"


def test_python_ok_matches_running_interpreter():
    ok, cur = bootstrap.python_ok(_SPEC)
    assert cur.startswith(".".join(str(x) for x in sys.version_info[:3]))
    assert ok == (python_status(_SPEC).status == "OK")
```

(`import sys` 를 테스트 파일 상단에 추가.) 실행 중인 인터프리터가 3.11.9 이므로 `test_report_json_keys` 는 그대로 통과한다.

---

## 4. 핵심 규칙 (입력 → 기대값)

| `version` | `free_threaded` | spec `min`/`max_exclusive` | `status` | `found` |
|-----------|-----------------|----------------------------|----------|---------|
| (3, 11, 9) | False | 3.11 / 3.15 | `OK` | `3.11.9` |
| (3, 14, 0) | False | 3.11 / 3.15 | `OK` | `3.14.0` |
| (3, 14, 2) | False | 3.11 / 3.15 | `OK` | `3.14.2` |
| (3, 10, 11) | False | 3.11 / 3.15 | `Outdated` | `3.10.11` |
| (3, 15, 0) | False | 3.11 / 3.15 | `Unsupported` | `3.15.0` |
| (3, 14, 0) | True | 3.11 / 3.15 | `Unsupported` | `3.14.0t (free-threaded)` |
| (3, 13, 1) | False | 3.11 / 3.15 | `OK` | `3.13.1` |

비교는 `min` · `max_exclusive` 의 자릿수만큼만 본다 (`(3,14,0)[:2] = (3,14) < (3,15)`). `bootstrap.main()` 종료 코드는
`OK` 면 계속, 아니면 **2** (기존과 동일).

---

## 5. 검증 절차 (이 PC 에 3.14 가 없으므로 설치부터)

| 단계 | 명령 · 행위 | 완료 기준 |
|------|-------------|-----------|
| V0 | 3.1~3.7 구현 후 `py -3.11 -m pytest -q` | 43 + 3 = **46 passed** |
| V1 | 3.14 설치: python.org 의 Python install manager 설치 후 `py install 3.14` (또는 기존 전체 설치 프로그램 3.14.x, free-threaded 체크 해제). `py --list` 에 `3.14` 표시 | `py -3.14 --version` → `Python 3.14.x` |
| V2 | 격리 환경: `py -3.14 -m venv .venv314` → `.venv314\Scripts\python bootstrap.py --check --json` | 첫 행 `Python … "status": "OK"`, PySide6 행 `Missing`, 종료 코드 0 (더 이상 코드 2 로 거부하지 않음) |
| V3 | `.venv314\Scripts\python bootstrap.py --no-binaries -y` (ffmpeg 는 `bin/` 에 이미 있음) | `pip install` 이 PySide6 **6.12.0**(또는 그 이상 6.x) 을 설치. 리포트 전 행 `OK` |
| V4 | `.venv314\Scripts\python -m pytest -q` | 46 passed (3.14 인터프리터로) |
| V5 | `.venv314\Scripts\python launch.py` → `Help > Check Dependencies…` | 창이 뜨고 Python 행 `3.14.x` `OK` 초록. 콘솔에 Deprecation 경고가 있으면 기록 |
| V6 | 스모크: 영상 2개 추가 → 썸네일 보기 → 구간 편집 → GIF 1개 + MP4 1개 변환 → `Open Containing Folder` | 변환 성공, 예상 용량 표시, 로그에 Traceback 없음 |
| V7 | free-threaded 거부: `py install 3.14t` → `py -V:3.14t bootstrap.py --check` | 메시지 `Python 3.14.xt (free-threaded) is a free-threaded build, which PySide6 does not support. …`, 종료 코드 2 |
| V8 | 회귀: 3.11 로 `py -3.11 bootstrap.py --check` 와 `run.bat` | 기존과 동일하게 `OK` · 기동 |
| V9 | 정리: `.venv314` 삭제(`.gitignore` 의 `.venv*` 패턴에 걸리는지 확인, 아니면 추가), 필요 없으면 `py uninstall 3.14t` | `git status` 에 임시 폴더 없음 |

V5~V6 은 PySide6 6.12.0 이 개발 PC 의 6.11.1 과 다른 버전이라는 점에서 **UI 회귀 확인**을 겸한다. 스타일(`dark.qss`) · 체크 표시(주황) ·
`RangeSlider` 페인트가 달라 보이면 PLAN.md 10장 리스크 항목으로 넘긴다.

---

## 6. 리스크와 대응

| 리스크 | 대응 |
|--------|------|
| 3.14 사용자 PC 에 설치되는 PySide6 가 6.12.0 으로, 개발 PC(6.11.1) 와 다름 | V5~V6 스모크로 확인. 문제가 보이면 `requirements.txt` 를 `PySide6>=6.8,<6.13` 처럼 상한을 좁히는 대신 **문제를 고친다**. 상한은 메이저 7 만 막는다 (PLAN 12.1) |
| `py -3` 이 free-threaded 3.14t 를 고름 (기존 런처의 알려진 동작) | bootstrap 이 `Unsupported` 로 즉시 거부하고 표준 빌드 설치를 안내 (3.3). 메시지에 `-3.11` 우회법까지 넣지 않는다 — README 에 있다 |
| install manager 배포본에 tkinter 가 없을 가능성 | `launch._ask_yes_no()` 가 콘솔 `input()` 으로 폴백하므로 기능 영향 없음. V5 에서 `python -c "import tkinter"` 로 사실만 기록 |
| `deps.json` 을 못 읽는 환경(PyInstaller 번들 등) | `python_spec()` 이 `_DEFAULT_PY_SPEC` 으로 폴백. 기본값은 `deps.json` 과 같은 값으로 유지한다 — 둘을 함께 바꾸는 것을 CHANGELOG 체크 항목으로 |
| 3.15 출시 후 같은 보고 재발 | PySide6 메타데이터(`Requires-Python`)에 3.15 가 열리면 `deps.json` · `_DEFAULT_PY_SPEC` · README 세 곳만 올린다. 이 계획서가 절차다 |
| `Unsupported` 상태를 모르는 옛 `DependencyDialog` 와 새 bootstrap 조합 | 같은 저장소에서 함께 배포되므로 버전 불일치 없음. 3.4 의 한 줄 변경을 빠뜨리면 흰색 글자로만 보이고 기능은 동작한다 |

---

## 7. 범위 밖

- Python 3.15 이상 지원 (PySide6 메타데이터가 열리면 값만 갱신).
- free-threaded 빌드 지원 (PySide6 가 휠을 내기 전까지 불가).
- PyInstaller 패키징, `.bat` 의 버전 고정 옵션.
- PySide6 하한 상향 · `requirements.txt` 환경 마커 도입.

---

## 8. 완료 정의 (v0.2.1)

1. `deps.json` · `dependency_check.python_status()` · `bootstrap.python_ok()` 가 한 값(`>=3.11,<3.15`)을 본다. 앱 안 다이얼로그와 bootstrap 리포트의 Python 행이 같은 문자열을 낸다.
2. 3.14 표준 빌드에서 `bootstrap.py --check` 가 종료 코드 0, 설치 후 `launch.py` 가 뜨고 GIF · MP4 변환이 된다 (V2~V6).
3. 3.14t 에서 종료 코드 2 와 영어 안내 메시지 (V7). 3.11 회귀 없음 (V8).
4. 3.11 · 3.14 양쪽에서 `pytest` 46 passed.
5. `version.py` 0.2.1, CHANGELOG, README, PLAN.md 12 · 13장 갱신. 로컬 커밋 메시지: `feat(deps): support Python 3.12-3.14, unify version gate in deps.json (v0.2.1)`.
