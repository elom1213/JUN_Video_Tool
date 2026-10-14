# JUN_Video_Tool — 구현 계획서 (v01)

- **Author**: Ji Hun Park (Junny / `Dnable_JunnyPark`)
- **작성일**: 2026-10-14
- **상태**: 설계 확정본 → **v0.1.0 구현 완료 (2026-10-14)**. P0~P9 전 단계 구현. 유닛 테스트 35개 통과,
  합성 영상으로 헤드리스 end-to-end(프로브 → 썸네일 → 샘플 추정 → 병렬 변환 → 목표 용량 재시도) 검증 완료.
  Windows 10 실기 체크리스트(12.3)는 미수행 — Win10 머신이 생기면 수행한다.
- **대상 환경**: **Windows 10 (21H2 이상) 과 Windows 11 양쪽**, Python 3.11, PySide6 6.x (개발 PC 는 Win11 + 6.11.1), ffmpeg (별도 확보 — 4장). 호환 규칙은 12장

---

## 0. 한 줄 요약

영상 파일(mp4 · mov 등)을 여러 개 리스트업하고, 체크한 파일을 **GIF 로 벌크 변환**하는
PySide6 데스크톱 툴. 출력 크기(종횡비 락) · 압축률 · 프레임 구간을 조절할 수 있고,
변환기(Converter) 를 플러그인처럼 등록하는 구조로 만들어 **나중에 WebP · MP4 · 이미지 시퀀스 등
다른 포맷을 추가**할 수 있게 한다.

---

## 1. 요구사항

### 1.1 우선순위 1 (이번 구현 범위)

| # | 요구 | 구현 결정 |
|---|------|-----------|
| R1 | 여러 영상 파일을 선택해 리스트업 | 파일 다이얼로그(다중 선택) + 폴더 추가 + 드래그&드롭. 중복 경로는 1회만 등록 |
| R2 | 항목마다 체크박스 | 리스트 모델의 `Qt.CheckStateRole`. 체크된 항목만 변환 대상 |
| R3 | 전체 체크 / 전체 해제 | 툴바 버튼 `Check All` / `Uncheck All` / `Invert` |
| R4 | 파일명 보기 ↔ 썸네일 보기 전환 | 같은 모델에 두 개의 뷰 모드(`List` / `Thumbnails`). 썸네일은 백그라운드로 추출·캐시 |
| R5 | GIF 가로·세로 픽셀 + 종횡비 락 토글 | 폭/높이 스핀박스 + 락 토글 버튼. 락 ON 이면 마지막으로 편집한 축이 기준(anchor) 이 되고 나머지 축은 **항목별 원본 비율**로 산출 |
| R6 | 압축률로 출력 파일 크기 조절 | `Quality` 슬라이더(1~100) → fps 상한 · 팔레트 색 수 · 디더링 매핑. 선택적으로 `Target size (MB)` 지정 시 반복 재인코딩으로 크기 맞춤 |
| R7 | 변환 구간을 **프레임 단위**로 지정 | 항목별 `FrameRange(start_frame, end_frame)`. 범위 슬라이더(듀얼 핸들) + 스핀박스 + 시작/끝 프레임 미리보기. "체크된 모든 항목에 적용" 버튼 |
| R8 | 지금은 GIF 만, 나중에 다른 포맷 | `BaseConverter` 추상 클래스 + `ConverterRegistry`. UI 는 레지스트리에서 포맷 콤보를 채우고, 포맷별 옵션 패널을 팩토리로 생성 |
| R9 | 출력 GIF 의 fps 를 사용자가 지정 | `FPS` 모드 콤보 `Auto (from quality)` / `Source` / `Custom`. Custom 이면 QDoubleSpinBox(1~60) 값을 사용. 어떤 모드든 원본 fps 를 넘지 않게 상한 적용 |
| R10 | 변환 전에 **각 파일의 예상 출력 파일 용량(MB)** 을 본다 | 픽셀 크기가 아니라 **바이트 수**를 추정해 MB 로 표시. 리스트에 `Est. file size` 열. 1단계 휴리스틱(즉시, `~2.4 MB`) → 2단계 샘플 인코딩(백그라운드, `≈2.1 MB`). 옵션·구간이 바뀌면 자동 재계산. 체크 항목 합계를 Convert 버튼 위에 표시. 상세는 5.8 |
| R11 | 필요한 라이브러리 · 외부 바이너리를 **한 번에 설치** | `setup.bat` 더블클릭 → 표준 라이브러리만 쓰는 `bootstrap.py` 가 pip 패키지 설치 + ffmpeg/ffprobe 다운로드·검증을 수행. 앱 안에서도 `Help > Check Dependencies…` 로 상태 확인과 누락분 설치. 상세는 13장 |

### 1.2 비기능 요구

- UI 가 멈추지 않을 것 — 프로브 · 썸네일 · 변환은 모두 워커 스레드/프로세스에서.
- 변환 중 **취소** 가능. 항목별 진행률 + 전체 진행률 표시.
- 실패한 항목은 건너뛰고 나머지 계속. 실패 이유를 로그 패널과 항목 상태에 남긴다.
- 마지막 사용 폴더 · 옵션 · 보기 모드를 `QSettings` 로 기억.
- **Windows 10 에서도 동작**해야 한다. Windows 11 전용 API · 폰트 · 셸 기능을 쓰지 않는다 (12장).
- **UI 문자열은 전부 영어**, 주석·독스트링은 한국어 (전역 규칙 6장).

### 1.3 범위 밖 (이번에 하지 않음)

- 영상 재생(플레이어) UI. 미리보기는 정지 프레임 썸네일로만.
- 자르기(crop) · 회전 · 자막 · 오디오 처리.
- exe 패키징 (구조만 PyInstaller 가능하게 유지, 빌드 스크립트는 후속).

---

## 2. 기술 선택

| 항목 | 선택 | 이유 |
|------|------|------|
| GUI | **PySide6** | 이 PC 에 6.11.1 설치됨. `A00080` 계열과 동일 |
| 미디어 처리 | **ffmpeg / ffprobe 외부 프로세스** | GIF 팔레트 2패스(`palettegen`/`paletteuse`) 품질이 가장 좋고, 포맷 확장 시 명령만 추가하면 됨. OpenCV 등 바인딩 의존 제거 |
| 썸네일 | ffmpeg `image2pipe` → PNG bytes → `QImage.fromData` | 임시 파일 없이 메모리로 |
| 메타데이터 | ffprobe JSON, 없으면 `ffmpeg -i` stderr 정규식 파싱 | `imageio-ffmpeg` 로 ffmpeg 만 있고 ffprobe 가 없는 경우 대비 |
| 스레딩 | 썸네일·프로브: `QThreadPool` + `QRunnable` / 변환: 전용 `QThread` 1개가 큐를 관리하며 **ffmpeg 프로세스를 N개 동시 실행**(기본 2, 설정 1~4) | 벌크 변환 처리량 확보. 아래 2.2 |
| 설정 | `QSettings("JUN", "JUN_Video_Tool")` | 레지스트리 저장, 의존성 없음 |
| 테스트 | `pytest` (명령 생성·수치 변환 등 순수 로직만) | ffmpeg 없이도 도는 테스트로 한정 |

### 2.1 GUI 프레임워크 검토 — PySide6 를 유지하는 이유

사용자가 "PySide6 가 필수는 아니다" 라고 했으므로 대안을 비교했다. **변환 속도는 GUI 와 무관**하다 — 시간의 거의 전부를
ffmpeg 프로세스가 쓰고, GUI 는 명령을 만들고 진행률을 그릴 뿐이다. 따라서 선택 기준은 편의성(개발·유지보수)과 UI 요구(썸네일 격자, 듀얼 슬라이더, 드래그&드롭)다.

| 후보 | 장점 | 단점 | 판정 |
|------|------|------|------|
| **PySide6 (Qt)** | 모델/뷰·델리게이트로 썸네일 격자와 체크박스 리스트를 정석으로 구현. 드래그&드롭·스레드풀 내장. 기존 `A00080` 계열과 같은 스택이라 코드·경험 재사용 | exe 크기 큼(100MB+), 듀얼 슬라이더는 직접 그려야 함 | **채택** |
| Tkinter / customtkinter | 표준 라이브러리, 가벼움 | 썸네일 격자·가상화 리스트가 약함, 드래그&드롭 외부 패키지 필요, 디자인 자유도 낮음 | 보류 |
| Flet / Dear PyGui | 선언적, 보기 좋음 | 커스텀 위젯(범위 슬라이더) 제약, 파일 드롭·네이티브 다이얼로그 지원이 불완전 | 보류 |
| Electron / Tauri + 웹 UI | 가장 자유로운 UI | Python 코어와 IPC 계층이 추가되고 빌드가 두 배. 혼자 유지보수하기엔 과함 | 보류 |
| C# WPF / WinUI 3 | 네이티브, 빠른 시작 | 기존 Python 자산과 단절, Maya 파이프라인 재사용 불가 | 보류 |

→ **GUI 는 PySide6**, 처리는 **ffmpeg 외부 프로세스**로 확정. 속도는 2.2 의 전략으로 확보한다.
GUI 를 바꿔야 할 사유가 생기면 `app/core` 는 Qt 비의존이므로 UI 레이어만 교체하면 된다 (3장 레이어 규칙).

### 2.2 변환 속도 전략

| 전략 | 내용 | 효과 |
|------|------|------|
| **병렬 변환** | `JobRunner` 가 동시에 N개 ffmpeg 프로세스를 돌린다 (`concurrency` 설정 1~4, 기본 2). `palettegen`/`paletteuse` 는 단일 스레드 비중이 커서 코어가 남으므로 2~3 병렬이 벌크에서 1.5~2.5배 | 벌크 처리량 |
| **하드웨어 디코드** | 옵션 `hwaccel: "auto" | "none"` (기본 `auto`) → `-hwaccel auto` 를 입력 옵션에 추가. H.264/HEVC 디코드를 GPU 로. 실패 시(ffmpeg 가 자동으로 CPU 폴백하지 않는 환경) 재시도 1회는 `none` 으로 | 고해상도 원본 디코드 |
| **입력 측 seek** | `-ss` 를 `-i` 앞에 두어 구간 바깥을 디코드하지 않음 (이미 5.6 에 반영) | 구간 변환 |
| **스케일 선행** | 필터 체인에서 `fps` → `scale` → `palettegen` 순. 축소 후 팔레트를 만들어 팔레트 분석 비용 절감 | 모든 변환 |
| **썸네일 저해상도** | 썸네일 추출 `-ss` 입력 seek + `scale=320:-2` + 가능하면 `-skip_frame nokey` 는 쓰지 않음(정확도) | UI 반응성 |
| **gifski 엔진 (후속)** | `BaseConverter` 를 그대로 두고 `GifConverter.engine: "ffmpeg" | "gifski"` 를 추가. gifski 는 ffmpeg 로 PNG 프레임을 파이프로 뽑아 넘기며, 같은 용량에서 화질이 눈에 띄게 좋다. 속도는 ffmpeg 보다 느리므로 "품질 우선" 선택지로 제공 | 화질(선택) |

- `concurrency` 와 `hwaccel` 은 `AppSettings` 에 저장하고 `Settings…` 다이얼로그(메뉴 `Edit > Settings…`)에서 바꾼다. 이번 범위(P7/P8)에 포함.
- 병렬 실행 시 로그 줄은 `[clip_a.mp4]` 접두로 어느 작업의 메시지인지 구분한다.

---

## 3. 디렉터리 구조

```
JUN_Video_Tool/
├── launch.py                      # 진입점. 의존성 사전 점검(13.4) → QApplication → MainWindow.show()
├── setup.bat                      # 더블클릭 설치: py -3 bootstrap.py %*  (13장)
├── bootstrap.py                   # 표준 라이브러리만 사용. pip 설치 + ffmpeg 다운로드/검증 + 결과 리포트
├── requirements.txt               # PySide6>=6.8,<7  (런타임 필수)
├── requirements-dev.txt           # pytest  (개발)
├── deps.json                      # 외부 바이너리 목록: 이름, URL(주/대체), sha256 URL, zip 안 경로, 설치 위치
├── README.md
├── CHANGELOG.md
├── .gitignore                     # __pycache__/ *.pyc bin/ .venv/ dist/ build/ *.spec
├── bin/                           # bootstrap 이 ffmpeg.exe / ffprobe.exe / VERSION.txt 를 설치하는 곳. 최우선 탐색. git 제외
├── docs/
│   └── PLAN.md                    # 이 문서
├── tests/
│   ├── test_utils.py              # 프레임↔초, 크기 계산, 품질 매핑, 출력 경로
│   ├── test_gif_converter.py      # build_command() 가 만든 인자 리스트 검증, resolve_fps, degrade_for_retry
│   ├── test_size_estimator.py     # heuristic_size, pick_sample_ranges, scale_sample
│   └── test_probe_parser.py       # ffprobe JSON / ffmpeg stderr 파서
└── app/
    ├── __init__.py
    ├── config/
    │   ├── __init__.py
    │   ├── version.py             # VERSION = "0.1.0", LAST_UPDATE = "2026-10-14"
    │   ├── constants.py           # 지원 확장자, 기본값, 품질 매핑 함수
    │   └── settings.py            # AppSettings: QSettings 래퍼
    ├── core/                      # UI 비의존 로직. job_runner.py 만 PySide6.QtCore 허용
    │   ├── __init__.py
    │   ├── ffmpeg_locator.py      # find_ffmpeg() / find_ffprobe() / ffmpeg_version()
    │   ├── dependency_check.py    # DependencyStatus 목록 생성 (pip 패키지 · ffmpeg · ffprobe). 표준 라이브러리만 사용
    │   ├── media_probe.py         # MediaInfo 생성: probe(path)
    │   ├── thumbnail.py           # extract_frame_png(path, time_sec, max_width) -> bytes
    │   ├── models.py              # VideoItem, FrameRange, ItemStatus, MediaInfo, ConvertOptions, ConvertJob, ConvertResult
    │   ├── utils.py               # frame_to_sec, sec_to_frame, fit_size, make_output_path, format_timecode, subprocess_flags
    │   ├── size_estimator.py      # make_est_key, pick_sample_ranges, scale_sample (순수 함수)
    │   ├── job_runner.py          # JobRunner(QThread): 병렬 N 실행, 진행률 파싱, 취소
    │   └── converters/
    │       ├── __init__.py        # registry 생성 + GifConverter 등록
    │       ├── base.py            # BaseConverter(ABC), ConverterRegistry
    │       └── gif_converter.py   # GifOptions, GifConverter
    └── ui/
        ├── __init__.py
        ├── main_window.py         # MainWindow(QMainWindow)
        ├── settings_dialog.py     # SettingsDialog: concurrency / hwaccel / estimate on-off
        ├── dependency_dialog.py   # DependencyDialog: 상태 표 + Install Missing (bootstrap.py 를 QProcess 로 실행, 로그 스트리밍)
        ├── styles/
        │   └── dark.qss
        └── widgets/
            ├── __init__.py
            ├── video_list_model.py    # VideoListModel(QAbstractListModel)
            ├── video_item_delegate.py # VideoItemDelegate: list / thumbs 두 모드 그리기
            ├── video_list_view.py     # VideoListView(QListView): 드래그&드롭, 뷰 모드 전환, 컨텍스트 메뉴
            ├── loaders.py             # ProbeLoader, ThumbnailLoader, SizeEstimator (QThreadPool 비동기 + 캐시)
            ├── range_slider.py        # RangeSlider(QWidget): 듀얼 핸들 정수 슬라이더
            ├── frame_range_panel.py   # FrameRangePanel: 구간 편집 + 시작/끝 미리보기
            ├── options_panel_base.py  # BaseOptionsPanel + OptionsPanelFactory
            ├── gif_options_panel.py   # GifOptionsPanel(BaseOptionsPanel)
            ├── output_panel.py        # OutputPanel: 출력 폴더 · 접미사 · 덮어쓰기
            └── log_panel.py           # LogPanel(QPlainTextEdit)
```

**레이어 규칙**
- `app/core` 는 `PySide6` 를 import 하지 않는다. 유일한 예외는 `job_runner.py` (`QThread`, `Signal`).
  순수 로직(`converters/`, `media_probe`, `thumbnail`, `utils`)은 Qt 없이 pytest 로 돌릴 수 있어야 한다.
- `app/ui` 는 `app/core` 를 import 하되, 반대 방향은 없다.

---

## 4. ffmpeg 확보 전략 (`app/core/ffmpeg_locator.py`)

이 PC 의 PATH 에는 ffmpeg 가 없다. 아래 순서로 찾고, 전부 실패하면 시작 시 다이얼로그로 안내한다.

```python
def find_ffmpeg() -> Path | None:
    """탐색 순서: 1) <tool_root>/bin/ffmpeg.exe  2) PATH (shutil.which)  3) imageio_ffmpeg.get_ffmpeg_exe()"""

def find_ffprobe() -> Path | None:
    """탐색 순서: 1) <tool_root>/bin/ffprobe.exe  2) ffmpeg 와 같은 폴더의 ffprobe.exe  3) PATH.
    imageio-ffmpeg 는 ffprobe 를 제공하지 않으므로 None 이 정상 상황일 수 있다."""

def ffmpeg_version(exe: Path) -> str:
    """`ffmpeg -version` 첫 줄. 시작 시 로그 패널에 출력."""
```

- 결과는 모듈 레벨에서 1회 캐시 (`_FFMPEG`, `_FFPROBE`). `tool_root = Path(__file__).resolve().parents[2]`.
- ffprobe 가 없으면 `media_probe` 가 ffmpeg stderr 파싱 폴백을 사용한다 (5.2).
- 모든 서브프로세스는 `creationflags=utils.subprocess_flags()` 로 실행 — Windows 면 `subprocess.CREATE_NO_WINDOW`, 그 외 0.
- 정상 경로는 **`setup.bat` 이 `bin/` 에 ffmpeg 를 설치**하는 것이다 (13장). `imageio-ffmpeg` 는 `requirements.txt` 에 넣지 않고,
  bootstrap 이 ffmpeg 다운로드에 실패했을 때만 폴백으로 설치한다 (3단계 탐색은 그대로 유효).

---

## 5. 코어 모델과 로직

### 5.1 `models.py`

```python
class ItemStatus(Enum):
    IDLE = "Idle"; QUEUED = "Queued"; RUNNING = "Running"
    DONE = "Done"; FAILED = "Failed"; CANCELED = "Canceled"; SKIPPED = "Skipped"

@dataclass
class MediaInfo:
    width: int
    height: int
    fps: float            # avg_frame_rate 분수 평가 (예: "30000/1001" → 29.97). 0 이면 r_frame_rate
    duration: float       # 초. format.duration 우선, 없으면 stream.duration
    frame_count: int      # nb_frames 가 있으면 그 값, 없으면 round(duration * fps)
    codec: str            # codec_name
    size_bytes: int

    @property
    def aspect(self) -> float: return self.width / self.height
    @property
    def last_frame(self) -> int: return max(0, self.frame_count - 1)

@dataclass
class FrameRange:
    start_frame: int      # 0-based, inclusive
    end_frame: int        # 0-based, inclusive

    @property
    def frame_count(self) -> int: return self.end_frame - self.start_frame + 1
    def clamp(self, info: MediaInfo) -> "FrameRange":
        """0 ≤ start ≤ end ≤ info.last_frame 로 잘라서 새 객체 반환"""
    def to_seconds(self, fps: float) -> tuple[float, float]:
        """(start_sec, duration_sec). start = start_frame / fps, duration = frame_count / fps"""
    def is_full(self, info: MediaInfo) -> bool
    @classmethod
    def full(cls, info: MediaInfo) -> "FrameRange": return cls(0, info.last_frame)

@dataclass
class VideoItem:
    path: Path
    info: MediaInfo | None = None            # probe 완료 전 None
    probe_error: str | None = None
    checked: bool = True
    frame_range: FrameRange | None = None    # None = 전체 구간
    status: ItemStatus = ItemStatus.IDLE
    progress: int = 0                         # 0~100
    message: str = ""                         # 실패 사유 / 결과 요약 ("1.8 MB")
    output_path: Path | None = None
    est_size: int | None = None               # 예상 출력 크기(bytes). None = 미계산
    est_level: str = "none"                   # "none" | "heuristic" | "sampled" | "failed"
    est_key: str = ""                         # 추정에 쓴 (옵션+구간) 해시. 불일치면 stale 로 간주

    def effective_range(self) -> FrameRange:  # frame_range or FrameRange.full(info)

@dataclass
class ConvertOptions:        # 모든 포맷 옵션의 베이스
    format_id: str
    output_dir: Path | None = None    # None → 원본과 같은 폴더
    suffix: str = ""                  # 예: "_gif" → name_gif.gif
    overwrite: bool = False

@dataclass
class ConvertJob:
    item: VideoItem
    options: ConvertOptions
    output_path: Path

@dataclass
class ConvertResult:
    job: ConvertJob
    ok: bool
    output_size: int = 0
    elapsed: float = 0.0
    error: str = ""
    attempts: int = 1                 # 타깃 크기 맞춤으로 재시도한 횟수
    canceled: bool = False
```

### 5.2 `media_probe.py`

```python
class ProbeError(Exception): ...

def probe(path: Path) -> MediaInfo:
    """ffprobe 가 있으면 _probe_ffprobe, 없으면 _probe_ffmpeg_stderr. 실패 시 ProbeError(영어 메시지)."""

def _probe_ffprobe(ffprobe: Path, path: Path) -> MediaInfo:
    # ffprobe -v error -select_streams v:0
    #   -show_entries stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,codec_name,duration
    #   -show_entries format=duration,size -of json <path>
    # → parse_ffprobe_json(stdout_text, size_fallback)

def parse_ffprobe_json(text: str, size_fallback: int) -> MediaInfo      # 테스트 대상 (순수 함수)

def _probe_ffmpeg_stderr(ffmpeg: Path, path: Path) -> MediaInfo:
    # ffmpeg -hide_banner -i <path>   (출력 없음 → exit code 1 이 정상, stderr 를 파싱)
    # → parse_ffmpeg_stderr(stderr_text, size_bytes)

def parse_ffmpeg_stderr(text: str, size_bytes: int) -> MediaInfo        # 테스트 대상 (순수 함수)
    # 정규식:
    #   DURATION_RE = r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)"
    #   VIDEO_RE    = r"Stream #\d+:\d+.*?Video:\s*(\w+).*?,\s*(\d{2,5})x(\d{2,5})"
    #   FPS_RE      = r"(\d+(?:\.\d+)?)\s*fps"
    # frame_count = round(duration * fps)

def eval_fraction(text: str) -> float   # "30000/1001" → 29.97 ; "0/0" / "" → 0.0 ; "30" → 30.0

SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".wmv",
                        ".mpg", ".mpeg", ".flv", ".ts", ".mts"}     # constants.py 에 정의, 여기서 import
```

### 5.3 `thumbnail.py`

```python
class ThumbnailError(Exception): ...

def extract_frame_png(path: Path, time_sec: float, max_width: int = 320, timeout: float = 15.0) -> bytes:
    """ffmpeg -hide_banner -loglevel error -ss {time_sec:.3f} -i <path>
       -frames:v 1 -vf "scale='min({max_width},iw)':-2" -f image2pipe -vcodec png -
       stdout 전체(PNG bytes)를 반환. 빈 출력 / 비정상 종료 / 타임아웃 → ThumbnailError."""

def representative_time(info: MediaInfo) -> float:
    """대표 썸네일 시각 = min(1.0, duration * 0.1). 맨 앞 검은 프레임 회피."""
```
- 구간 미리보기는 `frame_to_sec(frame, fps)` 로 시각을 계산해 호출한다.
- 마지막 프레임 근처는 `-ss` 가 범위를 넘어 빈 출력이 될 수 있으므로 `time_sec = min(time_sec, duration - 1/fps)` 로 보정.

### 5.4 `utils.py`

```python
def frame_to_sec(frame: int, fps: float) -> float                 # frame / fps
def sec_to_frame(sec: float, fps: float) -> int                   # floor(sec * fps + 1e-6)
def format_timecode(sec: float, fps: float) -> str                # "HH:MM:SS:FF"
def fit_size(src_w: int, src_h: int, width: int | None, height: int | None,
             lock: bool, anchor: str) -> tuple[int | None, int | None]:
    """ffmpeg scale 필터에 넘길 (w, h).
       - width/height 둘 다 None → (None, None): scale 필터 생략
       - lock=True : anchor("width"|"height") 축 값은 그대로, 다른 축은 -2 (ffmpeg 가 비율 유지 + 짝수 보정)
       - lock=False: 주어진 값 그대로, None 인 축은 원본 값"""
def make_output_path(src: Path, out_dir: Path | None, suffix: str, ext: str, overwrite: bool) -> Path:
    """<out_dir or src.parent>/<src.stem><suffix><ext>.
       overwrite=False 이고 파일이 있으면 _001, _002 … 를 붙여 비어 있는 이름을 찾는다."""
def human_size(n_bytes: int) -> str                                # "1.8 MB"
def subprocess_flags() -> int
def tail_lines(text: str, n: int = 20) -> str
```

### 5.5 변환기 추상화 (`converters/base.py`)

```python
class BaseConverter(ABC):
    format_id: str          # "gif"
    display_name: str       # "GIF"
    extension: str          # ".gif"
    options_cls: type[ConvertOptions]

    @abstractmethod
    def default_options(self) -> ConvertOptions: ...
    @abstractmethod
    def validate(self, options: ConvertOptions) -> list[str]:
        """문제 목록(영어 문장). 비어 있으면 OK."""
    @abstractmethod
    def build_command(self, ffmpeg: Path, item: VideoItem, options: ConvertOptions,
                      output_path: Path) -> list[str]:
        """실행할 ffmpeg argv (shell=False 용 리스트). 마지막 원소는 output_path 문자열."""
    def supports_target_size(self) -> bool: return False
    def target_size_bytes(self, options: ConvertOptions) -> int | None: return None
    def degrade_for_retry(self, options: ConvertOptions, attempt: int,
                          last_size: int, target: int) -> ConvertOptions | None:
        """타깃 크기 초과 시 다음 시도용 옵션(새 객체). None 이면 포기."""
    def estimate_warning(self, item: VideoItem, options: ConvertOptions) -> str | None:
        """변환 전 경고 문구(예: 너무 큰 출력). None 이면 경고 없음."""
    def heuristic_size(self, item: VideoItem, options: ConvertOptions) -> int | None:
        """즉시 계산되는 대략적 출력 크기(bytes). 포맷이 지원하지 않으면 None."""
    def build_sample_command(self, ffmpeg: Path, item: VideoItem, options: ConvertOptions,
                             sample_range: FrameRange, output_path: Path) -> list[str] | None:
        """sample_range 구간만 같은 옵션으로 인코딩하는 argv. None 이면 샘플 추정 미지원.
        기본 구현: item 을 복사해 frame_range 만 바꿔 build_command 를 호출."""

class ConverterRegistry:
    def register(self, conv: BaseConverter) -> None       # format_id 중복 시 ValueError
    def get(self, format_id: str) -> BaseConverter
    def all(self) -> list[BaseConverter]                  # 등록 순서 = 콤보박스 순서

registry = ConverterRegistry()    # converters/__init__.py 에서 생성 후 registry.register(GifConverter())
```

**다른 포맷을 추가하는 절차 (미래)**
1. `converters/<fmt>_converter.py` 에 `XOptions(ConvertOptions)` 와 `XConverter(BaseConverter)` 작성.
2. `converters/__init__.py` 에서 `registry.register(XConverter())`.
3. `ui/widgets/<fmt>_options_panel.py` 에 `XOptionsPanel(BaseOptionsPanel)` 작성 후
   `OptionsPanelFactory.register("x", XOptionsPanel)`.
4. `MainWindow` 는 수정하지 않는다 — 포맷 콤보와 옵션 패널 교체가 레지스트리/팩토리로 자동 처리된다.

### 5.6 GIF 변환기 (`converters/gif_converter.py`)

```python
@dataclass
class GifOptions(ConvertOptions):
    format_id: str = "gif"
    width: int | None = None            # None → 원본
    height: int | None = None
    lock_aspect: bool = True
    anchor: str = "width"               # lock 시 기준 축. UI 가 마지막 편집 축을 기록
    quality: int = 70                   # 1~100
    fps_mode: str = "auto"              # "auto" (quality 매핑) | "source" (원본 fps) | "custom"
    fps_custom: float = 15.0            # fps_mode == "custom" 일 때 사용 (1~60)
    loop: int = 0                       # 0 = 무한 반복
    target_size_mb: float | None = None # None → 비활성
    max_attempts: int = 5
    hwaccel: str = "auto"               # "auto" → `-hwaccel auto` 입력 옵션 추가 | "none" → 생략 (2.2)

@dataclass
class GifParams:                        # 품질 매핑 결과
    fps: float
    max_colors: int
    dither: str
    stats_mode: str
```

**품질 → 인코딩 파라미터 매핑** (`constants.gif_params_for_quality(q: int, src_fps: float) -> GifParams`)

| 파라미터 | 공식 | q=10 | q=50 | q=100 |
|----------|------|------|------|-------|
| `fps` | `min(src_fps, 5 + round(q * 0.25))` | 8 | 18 | 30 (소스 fps 상한) |
| `max_colors` | `min(256, 32 + round(q * 2.24))` | 54 | 144 | 256 |
| `dither` | q<40 → `none` ; 40~75 → `bayer:bayer_scale=3` ; >75 → `sierra2_4a` | none | bayer | sierra2_4a |
| `stats_mode` | q>75 → `diff` ; 그 외 `full` | full | full | diff |

**출력 fps 결정** (`gif_converter.resolve_fps(options: GifOptions, src_fps: float) -> float`)

| `fps_mode` | 결과 |
|------------|------|
| `"auto"` | 위 표의 품질 매핑 값 `min(src_fps, 5 + round(q * 0.25))` |
| `"source"` | `src_fps` 그대로 (원본 프레임 전부 유지) |
| `"custom"` | `min(src_fps, fps_custom)` — 원본보다 높게 지정해도 프레임을 만들어 내지 않는다 |

- `gif_params_for_quality` 는 fps 를 계산해 돌려주지만, `build_command` 는 최종 fps 를 항상 `resolve_fps` 로 받는다 (매핑 함수의 fps 는 `auto` 모드에서만 쓰임).
- fps 가 소스보다 낮으면 ffmpeg `fps` 필터가 프레임을 드롭한다. 구간 길이(초)는 그대로이므로 출력 GIF 프레임 수는 `round(dur_sec * fps)` 가 된다. 이 값을 옵션 패널 힌트와 Frame Range 패널의 `"→ N GIF frames"` 표기로 보여 준다.
- `validate`: `fps_mode == "custom"` 이고 `fps_custom` 이 1~60 범위 밖이면 `"Custom FPS must be between 1 and 60."`.

**명령 생성** (`build_command`)

```
ffmpeg -hide_banner -y -nostats -progress pipe:1
       [-hwaccel auto] [-ss {start_sec:.3f} -t {dur_sec:.3f}]  -i <src>
       -filter_complex "[0:v]fps={fps}[,scale={w}:{h}:flags=lanczos],split[a][b];[a]palettegen=max_colors={mc}:stats_mode={stats}[p];[b][p]paletteuse=dither={dither}"
       -loop {loop}  <out.gif>
```
- `-ss` 를 **입력 옵션**(`-i` 앞)으로 두면 ffmpeg 기본 `accurate_seek` 로 앞 키프레임부터 디코드해 정확한 시각까지 버리므로
  프레임 정확도와 속도를 함께 얻는다. `start_sec, dur_sec = item.effective_range().to_seconds(info.fps)`.
  전체 구간(`is_full`)이면 `-ss`/`-t` 를 생략한다.
- `scale` 절은 `fit_size()` 결과가 `(None, None)` 이면 생략. lock 상태에서 비기준 축은 `-2` 로 넘겨 ffmpeg 가 **항목별 비율**로 계산한다.
- `-y` 는 `make_output_path` 가 이미 충돌을 해결했으므로 항상 붙인다 (재시도 덮어쓰기에도 필요).
- `validate`: `width`/`height` 가 1~8192 범위 밖, `quality` 범위 밖, `target_size_mb <= 0`, `output_dir` 가 존재하지 않는 경로 → 문구 반환.
- `estimate_warning`: `range.frame_count * out_w * out_h > 400_000_000` 이면
  `"Output may be very large (N frames at WxH). Continue?"` 반환. (`out_w/out_h` 는 `-2` 축을 원본 비율로 환산해 추정)

**타깃 크기 맞춤** (`supports_target_size() = True`, `target_size_bytes = round(target_size_mb * 1024 * 1024)`)
- 1차 결과 크기 > target → `degrade_for_retry(opts, attempt, last_size, target)`:
  - 매 시도 `quality = max(5, quality - 15)`. `fps_mode` 가 `"source"`/`"custom"` 이면 품질 하향으로 fps 가 내려가지 않으므로,
    `attempt >= 1` 부터 `fps_mode = "custom"`, `fps_custom = max(5, round(current_fps * 0.75))` 로 fps 도 함께 낮춘다 (사용자 지정 fps 는 1차 시도에서만 그대로 존중).
  - `attempt >= 2` 부터는 `width = round(width * 0.85)` 도 함께 축소(width 가 None 이면 원본 폭에서 시작). lock 이 꺼져 있으면 height 도 같은 비율로.
  - `attempt >= max_attempts - 1` 이면 None (포기).
- 포기 시 마지막 결과 파일은 남기고 `ConvertResult.ok = True`, `message = "Target size not reached (2.3 MB > 2.0 MB)"`.
- 재시도 사이 중간 파일은 같은 경로에 덮어쓴다.

### 5.7 작업 실행기 (`job_runner.py`)

```python
class JobRunner(QThread):
    job_started  = Signal(int)              # row
    job_progress = Signal(int, int)         # row, percent 0~100
    job_finished = Signal(int, object)      # row, ConvertResult
    all_finished = Signal(int, int, int)    # ok_count, failed_count, canceled_count
    log          = Signal(str)

    def __init__(self, ffmpeg: Path, converter: BaseConverter,
                 jobs: list[tuple[int, ConvertJob]], concurrency: int = 2, parent=None)
    def run(self) -> None:
        # concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) 에 (row, job) 을 제출.
        # 각 워커가 _run_one 을 실행하고 결과를 job_finished 로 emit (Signal 은 스레드 안전, 큐드 커넥션).
        # 모두 끝나면 all_finished. 취소 시 아직 시작하지 않은 future 는 cancel() 하고 CANCELED 결과를 emit.
    def cancel(self) -> None:       # self._cancel = True ; 실행 중인 모든 Popen 을 terminate() (self._procs: dict[int, Popen], Lock 보호)
    def _run_one(self, row: int, job: ConvertJob) -> ConvertResult:
        # attempt 루프 (타깃 크기 지원 시 최대 max_attempts):
        #   cmd = converter.build_command(ffmpeg, job.item, opts, job.output_path)
        #   proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True, encoding="utf-8", errors="replace",
        #                creationflags=subprocess_flags()) ; self._procs[row] = proc
        #   stdout 을 줄 단위로 읽어 "out_time_us=" / "out_time_ms=" 값으로 percent 계산 (dur_sec 기준), "progress=end" 로 종료 감지
        #   stderr 는 별도 스레드(threading.Thread) 로 흘려 받아 마지막 20줄 보관 (파이프 데드락 방지)
        #   returncode != 0 이고 hwaccel 이 "auto" 였고 stderr 에 "hwaccel"/"Failed to initialise" 가 있으면 hwaccel="none" 으로 1회 재시도
        #   returncode != 0 → ok=False, error=tail_lines(stderr)
        #   취소 플래그 → 출력 파일 삭제 후 canceled=True
        #   ok 이고 타깃 크기 초과 → degrade_for_retry → 반복
```
- `MainWindow` 가 `ConvertJob` 목록을 만든다: 체크된 항목 중 `info` 가 있는 것만. `info` 없는 체크 항목은 `SKIPPED` 로 표시하고 로그.
- 러너는 한 번에 하나만 존재. 실행 중에는 `Convert Checked` 비활성, `Cancel` 활성, 리스트 편집(추가·삭제) 비활성.
- `concurrency` 는 `AppSettings` 의 `run/concurrency` (1~4, 기본 2). 전체 진행 바는 완료 작업 수 기준이고, 항목별 진행률은 리스트에서 동시에 여러 개가 움직인다.

### 5.8 출력 파일 용량(MB) 추정 (`core/size_estimator.py`) — R10

GIF 용량은 팔레트·디더링·프레임 간 변화량에 좌우되어 수식으로 정확히 구할 수 없다. 그래서 **2단계**로 보여 준다.

**1단계 — 휴리스틱 (즉시, UI 스레드)**  `GifConverter.heuristic_size()`

```
out_frames  = round(dur_sec * fps)
out_w,out_h = 출력 크기 (-2 축은 원본 비율로 환산)
bpp         = 0.08 + 0.42 * (max_colors / 256)          # 프레임당 픽셀 1개가 차지하는 평균 바이트. 색 많을수록 LZW 압축률 저하
dither_mul  = {"none": 0.80, "bayer": 1.00, "sierra2_4a": 1.35}[dither 종류]
size        = 800 + out_frames * out_w * out_h * bpp * dither_mul
```
- 계수는 경험값이며 `constants.py` 에 모아 두고, 샘플 추정이 끝나면 **그 파일의 실측/휴리스틱 비율**을 로그에 남겨 추후 보정에 쓴다.
- 표시는 `~2.4 MB` (물결표 = 대략).

**2단계 — 샘플 인코딩 (백그라운드, `QThreadPool`)**  `SizeEstimator`

```python
class SizeEstimator(QObject):          # ui/widgets/loaders.py 의 다른 로더와 같은 풀 사용
    estimate_ready  = Signal(int, str, int)     # row, est_key, bytes
    estimate_failed = Signal(int, str, str)     # row, est_key, error
    def request(self, row: int, item: VideoItem, converter: BaseConverter, options: ConvertOptions) -> str   # est_key 반환
    def cancel_all(self) -> None

def make_est_key(path: Path, rng: FrameRange, options: ConvertOptions) -> str   # sha1(str(path) + asdict(options) + rng)  (core, 순수 함수)
def pick_sample_ranges(rng: FrameRange, src_fps: float, out_fps: float, n: int = 2, out_frames_each: int = 24) -> list[FrameRange]
    # 구간을 n 등분한 각 조각의 중앙에서 out_frames_each 개의 출력 프레임이 나오도록 src 프레임 수 = ceil(out_frames_each * src_fps / out_fps) 를 자른다.
    # 구간이 짧아 샘플 합이 전체의 70% 이상이면 → 전체 구간 1개를 샘플로 (= 정확값).
def scale_sample(sample_bytes: list[int], sample_out_frames: list[int], total_out_frames: int) -> int
    # per_frame = sum(bytes) / sum(frames) ; return round(800 + per_frame * total_out_frames)
```
- 샘플은 `build_sample_command()` 로 **실제 변환과 동일한 필터 체인**을 임시 파일(`%TEMP%/JUN_Video_Tool/est_<key>.gif`)에 쓰고 크기를 읽은 뒤 삭제한다.
  기본 2구간 × 24프레임 → 파일당 ffmpeg 2회, 보통 0.3~1.5 초. 풀 동시 4 → 20개 파일도 수 초.
- 표시는 `≈2.1 MB` (근사 등호 = 샘플 기반). 샘플이 전체 구간을 덮었으면 `2.1 MB` (정확).
- **재계산 트리거**: 옵션 변경(`options_changed`), 구간 변경(`range_changed`), 파일 추가(프로브 완료 직후). 500ms 디바운스 후 체크된 항목 전부 + 현재 선택 항목.
  요청 전 `est_key` 를 계산해 모델에 저장하고, 결과가 도착했을 때 모델의 `est_key` 와 같을 때만 반영 (늦게 온 결과 무시). 새 요청이 들어오면 큐에 남은 이전 작업은 `cancel_all`.
- 트리거 사이에는 휴리스틱을 즉시 써서 열이 비지 않게 하고, 샘플 결과가 오면 덮어쓴다.
- 변환이 끝난 항목은 실제 크기를 `Done · 1.8 MB` 로 보이므로 추정 열은 비운다.
- `Target size` 가 켜져 있으면 추정값 > 타깃인 항목을 노란색으로 표시해 재시도가 일어날 것임을 미리 알린다.
- 체크 항목 합계는 `Estimated total: ≈14.2 MB (5 files, 2 pending)` 로 Convert 버튼 위 라벨에. 아직 샘플이 안 끝난 항목은 휴리스틱으로 합산하고 `pending` 수를 표기.
- 추정은 **변환 결과 재사용은 하지 않는다** (샘플은 일부 구간이므로). 변환 중에는 추정 요청을 보내지 않는다 (ffmpeg 자원 경쟁).

---

## 6. UI 설계

### 6.1 전체 레이아웃 (`MainWindow`, 기본 1280×760, 최소 1000×600)

```
┌ JUN Video Tool v0.1.0 ───────────────────────────────────────────────────────────────────────┐
│ [Add Files] [Add Folder] [Remove] [Clear] │ [Check All] [Uncheck All] [Invert] │ View: (● List ○ Thumbnails) │
├────────────────────────────────────────────────────┬─────────────────────────────────────────┤
│ VideoListView   (QSplitter 좌:우 = 6:4)             │ Output format: [ GIF              ▼ ]   │
│  ☑ clip_a.mp4   1920x1080 · 29.97 fps · 00:12          Done · 1.8 MB │ ┌ GIF Options ─────────────────┐ │
│  ☑ clip_b.mov   1280x720  · 30 fps    · 01:03  ≈6.3 MB  ▓▓▓▓░░ 62 % │ │ Width [ 640 ] [Lock] Height [ 360 ] │
│  ☐ clip_c.mp4   ...                            ~2.4 MB        Idle  │ │ [Reset to Source Size]        │ │
│                                                         │ │ Quality ───────●──── 70              │ │
│  (Thumbnails 모드: 160x90 썸네일 격자 + 파일명)          │ │   18 fps · 144 colors · bayer       │ │
│                                                         │ │ FPS [ Custom ▼ ] [ 15.0 ]  src 29.97 │ │
│                                                         │ │ ☐ Target size  [ 2.0 ] MB            │ │
│                                                         │ │ Loop [ 0 ]  (0 = infinite)           │ │
│                                                         │ └─────────────────────────────────────┘ │
│                                                         │ ┌ Frame Range (selected item) ───────┐ │
│                                                         │ │ [start thumb 160x90] [end thumb]    │ │
│                                                         │ │ Start [   0 ] ●──────────● [ 359 ] End │
│                                                         │ │ 00:00:00:00            00:00:11:29  │ │
│                                                         │ │ Frames: 360 / 360 (12.0 s)          │ │
│                                                         │ │ [Full Range]  [Apply to Checked]    │ │
│                                                         │ └─────────────────────────────────────┘ │
│                                                         │ ┌ Output ────────────────────────────┐ │
│                                                         │ │ (●) Same folder as source           │ │
│                                                         │ │ ( ) Folder [ C:\...        ] [...]  │ │
│                                                         │ │ Suffix [ _gif ]   ☐ Overwrite       │ │
│                                                         │ └─────────────────────────────────────┘ │
│                                                         │   Estimated total: ≈14.2 MB (5 files)   │
│                                                         │   [      Convert Checked      ]         │
│                                                         │   [           Cancel          ]         │
├────────────────────────────────────────────────────┴─────────────────────────────────────────┤
│ Overall ████████░░░░░░░░░░ 2 / 5                                                              │
│ Log: [12:01:03] ffmpeg version 7.1 — C:\...\bin\ffmpeg.exe                                     │
│      [12:01:10] Added 5 files (1 skipped: unsupported extension)                              │
│      [12:02:00] clip_a.mp4 -> clip_a_gif.gif  (1.8 MB, 4.2 s)                                 │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 `VideoListModel(QAbstractListModel)`

- 내부 `self._items: list[VideoItem]`, 썸네일 `self._pixmaps: dict[Path, QPixmap]`.
- 커스텀 롤: `ItemRole = UserRole + 1`(VideoItem), `InfoTextRole`("1920x1080 · 29.97 fps · 00:12 · 12.3 MB"), `StatusRole`(ItemStatus), `ProgressRole`(int), `MessageRole`(str),
  `EstimateTextRole`(str: `"~2.4 MB"` / `"≈2.1 MB"` / `"2.1 MB"` / `"…"`(계산 중) / `""`), `EstimateOverTargetRole`(bool).
- `set_estimate(row, est_key, size, level)`: 모델의 `est_key` 와 일치할 때만 반영.
- `data(index, role)`:
  - `DisplayRole` → 파일명 (`path.name`)
  - `CheckStateRole` → `Qt.Checked / Qt.Unchecked`
  - `DecorationRole` → `QPixmap` (없으면 None → 델리게이트가 플레이스홀더 그림)
  - `ToolTipRole` → 전체 경로 + info 텍스트 + 상태 + 메시지 (probe_error 가 있으면 그것)
- `setData(index, value, CheckStateRole)` → `checked` 토글 후 `dataChanged`. `flags` = `ItemIsUserCheckable | ItemIsSelectable | ItemIsEnabled`.
- 공개 메서드
  - `add_paths(paths: Iterable[Path]) -> tuple[int, int]` : (추가 수, 걸러진 수). 확장자 필터 + 중복(resolve 후 비교) 제거. 추가된 행 번호는 `rows_added = Signal(list)` 로 발행.
  - `remove_rows(rows: list[int])`, `clear()`
  - `set_all_checked(bool)`, `invert_checked()`, `checked_rows() -> list[int]`
  - `item(row) -> VideoItem`, `row_of(path) -> int`
  - `update_item(row, **fields)` : dataclass 필드 갱신 + `dataChanged(index, index)`
  - `set_info(row, info: MediaInfo | None, error: str | None)`, `set_thumbnail(row, QPixmap)`
  - `set_locked(bool)` : 변환 중 체크/편집 금지 (flags 에서 `ItemIsUserCheckable` 제거)

### 6.3 `VideoItemDelegate(QStyledItemDelegate)`

- `mode: str = "list" | "thumbs"` (`set_mode`).
- **list** 모드 — 행 높이 28px. 좌→우: `[체크박스 16px] 파일명(elide middle, 폭의 40%) │ info 텍스트(회색) │ 예상 크기 90px(우측 정렬, 타깃 초과면 노란색) │ 우측 140px 상태 영역`.
  상태 영역: `RUNNING` → 미니 진행 바 + `"62 %"`, `DONE` → 녹색 `"Done · 1.8 MB"`, `FAILED` → 빨간 `"Failed"`, 그 외 상태명.
- **thumbs** 모드 — 셀 180×150. 상단 160×90 썸네일(레터박스 중앙 정렬, 없으면 어두운 사각형 + `"…"`), 좌상단 체크박스, 하단 파일명(elide middle) + info 텍스트 1줄(작게). 진행 중이면 썸네일 아래 3px 진행 바. `DONE/FAILED` 는 우상단 작은 색 점.
- 체크박스 클릭은 `editorEvent` 에서 체크 영역 히트테스트(`_check_rect(option)`)로만 처리. 더블클릭은 무시.
- `sizeHint` 는 모드에 따라 `(0, 28)` 또는 `(180, 150)`.

### 6.4 `VideoListView(QListView)`

- 시그널: `files_dropped = Signal(list)` (Path 리스트), `open_folder_requested = Signal(int)`, `reset_range_requested = Signal(list)`.
- `set_view_mode("list"|"thumbs")`:
  - list → `ListMode`, `setUniformItemSizes(True)`, `setSpacing(0)`, `setWrapping(False)`
  - thumbs → `IconMode`, `setResizeMode(Adjust)`, `setGridSize(QSize(180,150))`, `setSpacing(6)`, `setMovement(Static)`, `setWrapping(True)`
- `setAcceptDrops(True)`; `dragEnterEvent/dragMoveEvent` 에서 URL 이면 수락, `dropEvent` 에서 파일은 그대로, 폴더는 **1단계(비재귀)** 스캔해 `files_dropped` 발행.
- `setSelectionMode(ExtendedSelection)`. `Delete` 키 → 메인 윈도우 `remove_selected`.
- 컨텍스트 메뉴: `Open Containing Folder`, `Remove Selected`, `Reset Frame Range`.

### 6.5 `loaders.py` — `ProbeLoader`, `ThumbnailLoader`

```python
class ProbeLoader(QObject):
    probe_ready  = Signal(object, object)    # Path, MediaInfo
    probe_failed = Signal(object, str)       # Path, error
    def request(self, path: Path) -> None    # 이미 대기 중이면 무시
    def cancel_all(self) -> None

class ThumbnailLoader(QObject):
    thumbnail_ready  = Signal(str, QImage)   # key, image
    thumbnail_failed = Signal(str, str)      # key, error
    @staticmethod
    def make_key(path: Path, time_sec: float, max_width: int) -> str   # f"{path}|{time_sec:.3f}|{max_width}"
    def request(self, path: Path, time_sec: float, max_width: int = 320) -> str
        # 캐시 히트면 즉시 emit(QTimer.singleShot(0, …) 으로 비동기 보장) 후 key 반환
    def cancel_all(self) -> None
```
- 공용 `QThreadPool` 1개(`setMaxThreadCount(4)`), 작업은 `QRunnable` 서브클래스. 결과는 `QObject` 시그널로 메인 스레드에 전달.
- 썸네일 캐시: `OrderedDict[str, QImage]` LRU, 최대 500. 모델에는 메인 스레드에서 `QPixmap.fromImage` 로 변환해 저장.
- 파일 추가 → `ProbeLoader.request` → `probe_ready` → `model.set_info` → `ThumbnailLoader.request(path, representative_time(info), 320)` → `model.set_thumbnail`.
  (파일 하나당 프로브 1회 + 대표 썸네일 1회. 보기 모드와 무관하게 미리 받아 두어 전환이 즉시 되게 한다.)

### 6.6 `RangeSlider(QWidget)`

- 두 핸들을 가진 정수 범위 슬라이더. PySide6 표준 위젯에 없어 직접 구현.
- API: `setRange(lo, hi)`, `setValues(low, high)`, `values() -> tuple[int, int]`,
  시그널 `valuesChanged(int, int)`(드래그 중 연속), `sliderReleased()`(마우스 뗄 때 1회).
- 그리기: 트랙 4px 회색, 선택 구간 강조색, 핸들 2개 지름 14px. 고정 높이 24px.
- 조작: `mousePressEvent` 에서 가까운 핸들을 활성화(같은 위치면 이동 방향으로 결정), `mouseMoveEvent` 로 이동, 교차 금지(`low <= high`).
  키보드 ←/→ 활성 핸들 1프레임, Shift+←/→ 10프레임, Home/End 끝으로. `wheelEvent` 는 1프레임.
- 미리보기 썸네일 요청은 `sliderReleased` 와 스핀박스 `editingFinished` 에서만 발생시키고, 추가로 `FrameRangePanel` 이 200ms 디바운스 타이머를 둔다 (ffmpeg 호출 폭주 방지).

### 6.7 `FrameRangePanel(QGroupBox)`

- `set_item(row: int, item: VideoItem | None)`: `item is None or item.info is None` → 전체 비활성 + 라벨 `"Select a probed video to edit its range."`.
  있으면 `slider.setRange(0, info.last_frame)`, 스핀박스 범위 동기화, 값 = `item.effective_range()`.
- 위젯: `start_spin`, `end_spin`(QSpinBox; 서로 `start ≤ end` 제약), `RangeSlider`, 좌/우 타임코드 라벨(`format_timecode`),
  `frames_label`(`"Frames: 120 / 360 (4.0 s) → 60 GIF frames @ 15 fps"`; 메인 윈도우가 `set_output_fps(fps)` 로 현재 출력 fps 를 넘겨 주고, 옵션 변경 시마다 갱신),
  시작/끝 미리보기 `QLabel` 160×90, 버튼 `Full Range`, `Apply to Checked`.
- 값 변경 → `range_changed = Signal(int, object)` (row, `FrameRange | None`; 전체 구간이면 None). 메인 윈도우가 모델에 반영.
- `Apply to Checked` → `apply_to_checked = Signal(object)` (FrameRange). 메인 윈도우가 체크된 모든 항목에 `clamp` 하여 적용하고, 잘린 항목 수를 로그.
- 미리보기: `ThumbnailLoader.request(path, frame_to_sec(start), 160)` / end 도 동일. `thumbnail_ready` 의 key 와 자신이 기다리는 key 가 일치할 때만 라벨 갱신(지연 도착 무시).

### 6.8 옵션 패널 (`options_panel_base.py`, `gif_options_panel.py`)

```python
class BaseOptionsPanel(QGroupBox):
    options_changed = Signal()
    def get_options(self) -> ConvertOptions          # 베이스 필드(output_dir/suffix/overwrite)는 비워 두고 OutputPanel 이 채움
    def set_options(self, options: ConvertOptions) -> None
    def set_reference_info(self, info: MediaInfo | None) -> None   # 선택 항목 원본 크기 → 락 계산 / Reset 에 사용

class OptionsPanelFactory:
    _panels: dict[str, type[BaseOptionsPanel]] = {}
    @classmethod
    def register(cls, format_id: str, panel_cls: type[BaseOptionsPanel]) -> None
    @classmethod
    def create(cls, format_id: str, parent=None) -> BaseOptionsPanel
```

`CommonOptionsPanel` 동작 세부 (GIF · MP4 공통, v0.2.0 부터)
- `width_spin`, `height_spin`: QSpinBox 0~8192, `specialValueText("Source")` 로 0 = 원본. **`setKeyboardTracking(False)`** —
  한 글자씩 칠 때마다 반대 축이 바뀌지 않고, Enter · 포커스 이동 · 화살표 버튼으로 **입력이 확정된 뒤에만** 반대 축을 계산한다 (사용자 요청 2026-10-14).
  배치는 `Width [ ] Height [ ] [Lock]` — 락 버튼은 Height 오른쪽.
  `lock_btn`: checkable QToolButton, 텍스트 `"Lock"`(ON) / `"Free"`(OFF) + 자물쇠 아이콘. `reset_btn`: `"Reset to Source Size"` → 두 스핀을 0 으로.
- **락 ON**: `width_spin.valueChanged` → `anchor = "width"`, `height = round(width / ref_aspect)` 를 `blockSignals(True)` 상태로 반영. 반대도 동일.
  `ref_aspect` 는 `set_reference_info` 로 받은 선택 항목 비율, 없으면 16:9. 0(Source) 입력 시 다른 축도 0.
  변환 시에는 anchor 축 값만 전달되고 다른 축은 `-2` (5.6) → **항목별 비율 유지**가 보장된다. UI 의 다른 축 값은 "선택 항목 기준 예시" 임을 툴팁으로 안내.
- **락 OFF**: 두 값을 그대로 모든 항목에 적용 (비율 왜곡 허용).
- `quality_slider`(QSlider 1~100) + 값 라벨 + 매핑 힌트 라벨(`"18 fps · 144 colors · bayer"`, `ref_info.fps` 기준, 없으면 30 가정).
- **FPS 행**: `fps_mode_combo`(`"Auto (from quality)"` / `"Source"` / `"Custom"`) + `fps_spin`(QDoubleSpinBox 1~60, 소수 1자리, 기본 15.0; Custom 모드에서만 활성)
  + 결과 라벨(`"→ 15 fps"`; Source 모드면 선택 항목의 fps, 없으면 `"→ source fps"`). 모드가 Auto 면 Quality 슬라이더 변화에 따라 결과 라벨이 갱신되고,
  Custom/Source 모드면 Quality 힌트 라벨의 fps 부분이 사라진다 (`"144 colors · bayer"`). `fps_custom` 이 선택 항목 fps 보다 크면 라벨을 노란색으로 `"→ 29.97 fps (capped to source)"`.
- `target_check` + `target_spin`(QDoubleSpinBox 0.1~500 MB), `loop_spin`(0~100, 0 툴팁 `"0 = infinite"`).
- `get_options()` 는 `GifOptions(width=None if 0 else w, …)`. `set_options()` 는 역변환.

### 6.9 `OutputPanel(QGroupBox)`

- 라디오 `Same folder as source` / `Folder` + `QLineEdit`(읽기 전용) + `Browse…`(QFileDialog.getExistingDirectory).
- `suffix_edit`(기본 `"_gif"`; 포맷 변경 시 비어 있거나 이전 자동값이면 `f"_{format_id}"` 로 갱신), `overwrite_check`.
- `apply_to(options: ConvertOptions) -> ConvertOptions` : `output_dir/suffix/overwrite` 를 채워 반환.

### 6.10 `LogPanel(QPlainTextEdit)`

- 읽기 전용, 최대 2000줄(`setMaximumBlockCount`). `append(msg: str)` 이 `[HH:MM:SS] ` 접두를 붙인다. `append_error(msg)` 는 빨간 색.

### 6.11 `MainWindow` 흐름

```
Add Files / Add Folder / Drop ─▶ model.add_paths ─▶ rows_added ─▶ ProbeLoader.request(path) (각 행)
    └▶ probe_ready ─▶ model.set_info ─▶ ThumbnailLoader.request(path, representative_time) ─▶ thumbnail_ready ─▶ model.set_thumbnail
    └▶ probe_failed ─▶ model.set_info(None, error) + log.append_error
List currentChanged ─▶ FrameRangePanel.set_item(row, item) ; OptionsPanel.set_reference_info(item.info)
FrameRangePanel.range_changed ─▶ model.update_item(row, frame_range=…)
OptionsPanel.options_changed ─▶ FrameRangePanel.set_output_fps(resolve_fps(options, item.info.fps))  (GIF 프레임 수 표기 갱신)
options_changed / range_changed / probe_ready ─▶ _schedule_estimates() (500ms 디바운스)
    ─▶ 체크된 행 + 현재 행: model.set_estimate(row, key, heuristic_size, "heuristic") ; SizeEstimator.request(row, …)
    ─▶ estimate_ready ─▶ model.set_estimate(row, key, bytes, "sampled") ─▶ _update_total_label()
Format combo changed ─▶ 옵션 패널 교체(OptionsPanelFactory.create) ; OutputPanel 접미사 제안
Convert Checked ─▶ options = output_panel.apply_to(options_panel.get_options())
    ─▶ converter.validate(options) → 문제 있으면 QMessageBox.warning 후 중단
    ─▶ 체크 행 순회: info 없음 → SKIPPED ; 있음 → ConvertJob(item, options, make_output_path(...))
    ─▶ estimate_warning 이 있는 항목이 하나라도 있으면 QMessageBox.question(Yes/No)
    ─▶ 모든 job 상태 QUEUED ; model.set_locked(True) ; JobRunner.start
    ├▶ job_started ─▶ status RUNNING   ├▶ job_progress ─▶ progress
    ├▶ job_finished ─▶ status DONE/FAILED/CANCELED, message, output_path ; overall bar +1
    └▶ all_finished ─▶ 버튼 복구, set_locked(False), log "Finished: 4 ok, 1 failed, 0 canceled"
Cancel ─▶ runner.cancel() (남은 QUEUED 항목은 CANCELED)
closeEvent ─▶ 러너 실행 중이면 QMessageBox.question("Conversion is running. Cancel and exit?") ─▶ cancel + wait ─▶ settings 저장
```

- 메뉴바: `File`(Add Files… `Ctrl+O`, Add Folder… `Ctrl+Shift+O`, Exit), `Edit`(Check All `Ctrl+A`, Uncheck All `Ctrl+Shift+A`, Invert Check `Ctrl+I`, Remove Selected `Del`, Clear List, Refresh Estimates `F5`, Settings…),
  `View`(List `Ctrl+1`, Thumbnails `Ctrl+2`), `Help`(Check Dependencies…, Show ffmpeg Info, About).
- 툴바는 6.1 의 버튼. 뷰 모드는 `QActionGroup` 으로 상호 배제.
- 시작 시 ffmpeg 를 못 찾으면 `QMessageBox` (버튼 `Install Now` / `Later`) 로
  `"ffmpeg was not found. Install it now? (downloads ~90 MB into <tool>/bin)"` 를 띄운다.
  `Install Now` → `DependencyDialog` 를 열어 설치 진행(13.5). `Later` → `Convert Checked` 와 `Add *` 를 비활성한 채 창은 열어 둔다.
  설치가 끝나면 `ffmpeg_locator` 캐시를 비우고 다시 탐색해 버튼을 활성화한다 (재시작 불필요).
- 창 제목 `f"JUN Video Tool v{VERSION}"`.

### 6.12 `AppSettings` (`config/settings.py`)

- `QSettings("JUN", "JUN_Video_Tool")`.
- 키: `ui/geometry`(bytes), `ui/splitter`(bytes), `ui/view_mode`(str), `io/last_input_dir`, `io/last_output_dir`,
  `io/output_mode`("source"|"folder"), `io/suffix`, `io/overwrite`, `format/current`, `gif/<field>`(GifOptions 각 필드),
  `run/concurrency`(int 1~4, 기본 2), `run/hwaccel`("auto"|"none"), `estimate/enabled`(bool, 기본 True; 끄면 휴리스틱만).
- `SettingsDialog(QDialog)` (`ui/settings_dialog.py`): 위 `run/*`, `estimate/*` 세 항목만 편집. OK 시 저장 후 메인 윈도우가 즉시 반영.
- `load_gif_options() -> GifOptions`, `save_gif_options(opts)`, `get(key, default)`, `set(key, value)`.
- 저장 시점: `closeEvent`, 변환 시작 시(옵션).

### 6.14 아이콘 (`ui/icons/`)

- **툴바 · 버튼 아이콘은 SVG 라인 아이콘** (24×24 viewBox, stroke `#e6e6e6` 1.8px, round cap/join). 파일명이 곧 이름이고
  `icons.icon("add_files")` 로 `QIcon` 을 얻는다 (PySide6 의 `qsvgicon` 플러그인이 렌더, 추가 의존성 없음).
  목록: `add_files add_folder folder remove clear check_all uncheck_all invert view_list view_thumbs convert cancel settings lock unlock full_range apply reset refresh download info`.
  코랄 배경(체크 상태) 위에서도 읽히도록 밝은 회색 단색을 쓰고, 항상 켜진 상태로 쓰이는 `convert`/`lock` 은 흰색.
- **앱 아이콘** `app.svg` (256 viewBox: 어두운 둥근 타일 + 코랄 필름 스트립 + 흰 재생 삼각형 + "GIF" 배지).
  글자는 폰트가 아니라 **패스로** 그려 어떤 머신에서 렌더해도 같다.
  `dev/build_icons.py` 가 `app.png`(256) 와 **다중 크기 `app.ico`**(16~256, PNG 압축 엔트리) 를 만든다. Qt 의 ico 플러그인은 단일
  이미지만 쓰므로 ICO 컨테이너는 스크립트가 직접 조립한다. `--sheet out.png` 로 전체 아이콘 미리보기 시트를 뽑을 수 있다.
- `launch.py` 가 `app.setWindowIcon(app_icon())` 과 Windows `SetCurrentProcessExplicitAppUserModelID("JUN.VideoTool")` 를 호출해
  작업표시줄에 python 아이콘 대신 앱 아이콘이 뜨게 한다. 다이얼로그도 같은 아이콘을 쓴다.
- 이모지·심볼 폰트는 쓰지 않는다 (12.2). 아이콘을 추가할 때는 SVG 를 폴더에 넣고 이름으로 부르면 된다.

### 6.13 스타일 (`ui/styles/dark.qss`)

- 배경 `#2b2b2b`, 패널 `#353535`, 테두리 `#444`, 글자 `#e6e6e6`, 보조 글자 `#9a9a9a`,
  강조 `#e8734a`(기존 `coral_01` 테마와 통일), 성공 `#6cc070`, 실패 `#e05555`.
- `launch.py` 가 파일을 읽어 `app.setStyleSheet`. 델리게이트는 같은 색 상수를 `constants.py` 의 `Colors` 에서 가져온다.

---

## 7. 핵심 계산 규칙 정리 (테스트 대상)

| 함수 | 입력 → 출력 예 |
|------|----------------|
| `frame_to_sec(90, 29.97)` | `3.003…` |
| `sec_to_frame(3.003, 29.97)` | `90` |
| `format_timecode(71.5, 30)` | `"00:01:11:15"` |
| `FrameRange(0, 359).to_seconds(30)` | `(0.0, 12.0)` |
| `FrameRange(30, 59).to_seconds(30)` | `(1.0, 1.0)` |
| `FrameRange(-5, 999).clamp(info(frame_count=360))` | `FrameRange(0, 359)` |
| `fit_size(1920,1080, 640,None, lock=True, anchor="width")` | `(640, -2)` |
| `fit_size(1920,1080, None,360, lock=True, anchor="height")` | `(-2, 360)` |
| `fit_size(1920,1080, 640,480, lock=False, anchor="width")` | `(640, 480)` |
| `fit_size(1920,1080, 640,None, lock=False, …)` | `(640, 1080)` |
| `fit_size(1920,1080, None,None, …)` | `(None, None)` → scale 필터 생략 |
| `gif_params_for_quality(50, 29.97)` | `fps=18, max_colors=144, dither="bayer:bayer_scale=3", stats_mode="full"` |
| `gif_params_for_quality(100, 24)` | `fps=24` (소스 상한), `max_colors=256`, `dither="sierra2_4a"`, `stats_mode="diff"` |
| `gif_params_for_quality(10, 30)` | `fps=8, max_colors=54, dither="none"` |
| `resolve_fps(GifOptions(fps_mode="auto", quality=50), 29.97)` | `18` |
| `resolve_fps(GifOptions(fps_mode="source"), 29.97)` | `29.97` |
| `resolve_fps(GifOptions(fps_mode="custom", fps_custom=12), 29.97)` | `12.0` |
| `resolve_fps(GifOptions(fps_mode="custom", fps_custom=60), 24)` | `24.0` (소스 상한) |
| `pick_sample_ranges(FrameRange(0, 899), 30, 15, n=2, out_frames_each=24)` | 2개, 각 48 src 프레임, 중심 ≈ 225 / 675 |
| `pick_sample_ranges(FrameRange(0, 59), 30, 15, …)` | `[FrameRange(0, 59)]` (샘플이 70% 넘음 → 전체) |
| `scale_sample([40_000, 60_000], [24, 24], 450)` | `800 + round(100_000/48 * 450)` = `938_300` |
| `heuristic_size` (300 frames, 640x360, 144 colors, bayer) | `800 + 300*640*360*(0.08+0.42*144/256)*1.0` = `21_860_000` (≈ 20.8 MB, `human_size` 는 1024 기준) |
| 반올림 규칙 | 표의 `round` 는 **.5 올림**(`floor(x+0.5)`). Python `round()` 는 은행가 반올림이라 q=50 에서 fps 17 이 나오므로 쓰지 않는다 |
| `make_output_path("a.mp4", None, "_gif", ".gif", overwrite=False)` (a_gif.gif 존재) | `a_gif_001.gif` |
| `make_output_path("a.mp4", Path("out"), "", ".gif", overwrite=True)` | `out/a.gif` |
| `eval_fraction("30000/1001")` | `29.97…` ; `eval_fraction("0/0")` → `0.0` |
| `parse_ffmpeg_stderr(sample, 1234)` | `width=1920, height=1080, fps=29.97, duration=12.34, codec="h264"` |

`test_gif_converter.py` 는 `GifConverter.build_command` 결과에 대해
`-ss 1.000`, `-t 1.000` 포함, 전체 구간이면 둘 다 미포함, 필터 문자열에 `fps=18`(auto) 또는 `fps=12`(custom 12), `scale=640:-2:flags=lanczos`, `max_colors=144`, `dither=bayer:bayer_scale=3` 포함,
`-loop 0` 포함, 마지막 인자가 출력 경로임을 단언한다. `degrade_for_retry` 는 quality 70 → 55 → 40, attempt 2 부터 width 축소를 단언한다.

---

## 8. 구현 순서 (각 단계가 끝나면 실행 가능한 상태 유지)

| 단계 | 내용 | 완료 기준 |
|------|------|-----------|
| **P0** | 뼈대: 디렉터리, `version.py`, `constants.py`, `launch.py`, 빈 `MainWindow`, `dark.qss`, `.gitignore`, `requirements*.txt`, **`deps.json` + `bootstrap.py` + `setup.bat`**, `dependency_check.py` | 빈 PC 에서 `setup.bat` 한 번으로 `python launch.py` 가 뜬다 |
| **P1** | `models`, `utils`, `ffmpeg_locator`, `media_probe`, `thumbnail` + `tests/test_utils.py`, `test_probe_parser.py` | pytest 통과. 콘솔에서 `probe()` / `extract_frame_png()` 동작 |
| **P2** | `VideoListModel`, `VideoItemDelegate`(list 모드), `VideoListView`, 툴바(추가/제거/체크 3종), 드래그&드롭, `ProbeLoader`, `LogPanel` | 리스트업 + 메타데이터 표시 |
| **P3** | `ThumbnailLoader`, delegate thumbs 모드, View 전환 | 썸네일 격자 보기 |
| **P4** | `converters/base`, `GifOptions`, `GifConverter`, `gif_params_for_quality`, `tests/test_gif_converter.py` | 명령 생성 테스트 통과 |
| **P5** | `BaseOptionsPanel`/`OptionsPanelFactory`, `GifOptionsPanel`(크기·락·품질·fps·loop), `OutputPanel`, 포맷 콤보 | 옵션이 `GifOptions` 로 왕복(get/set) |
| **P6** | `RangeSlider`, `FrameRangePanel`, 시작/끝 미리보기, Apply to Checked, 컨텍스트 메뉴 Reset Range | 항목별 구간 저장·표시 |
| **P7** | `JobRunner`(병렬 N, hwaccel 폴백), 진행률, 취소, 항목 상태 표시, 전체 진행 바, 완료 요약, 큰 출력 경고 | 벌크 GIF 변환 end-to-end |
| **P8** | `size_estimator`(휴리스틱 + 샘플), `Est. file size` 열, 합계 라벨, 타깃 초과 표시, 디바운스 재계산 | 변환 전 예상 크기 표시 |
| **P9** | Target size 재시도, `AppSettings` 저장/복원, `Settings…` 다이얼로그(concurrency, hwaccel), **`DependencyDialog`(Help 메뉴 + 시작 시 안내)**, 단축키, `README.md`(설치 안내), `CHANGELOG.md`, **Windows 10 에서 12.3 체크리스트 수행** | v0.1.0 |

---

## 9. 파일 헤더 · 컨벤션

- 모든 `.py` 첫 줄 `# -*- coding: utf-8 -*-`, 이어서 `# Python Script by Ji Hun Park` / `# last Update date : YYYY-MM-DD`.
- `from __future__ import annotations`, 타입 힌트 필수. 경로는 전부 `pathlib.Path`.
- 서브프로세스는 항상 리스트 argv + `shell=False` (한글/공백 경로 안전), `encoding="utf-8", errors="replace"`.
- 영어 UI 문자열은 위젯 생성 지점에 직접 쓴다 (툴 규모가 작음). 상태명은 `ItemStatus.value` 를 그대로 표시.
- 로그 형식 `[HH:MM:SS] <message>`.
- 버전 관리: `app/config/version.py` 와 `CHANGELOG.md` 동시 갱신.

---

## 10. 리스크와 대응

| 리스크 | 대응 |
|--------|------|
| ffmpeg 미설치 | 4장 탐색 순서 + `imageio-ffmpeg` 폴백 + 시작 시 안내. README 에 `bin/` 배치 방법 명시 |
| ffprobe 없음 (imageio-ffmpeg 만 있을 때) | stderr 파싱 폴백. `nb_frames` 가 없어 `frame_count = round(duration*fps)` 로 ±1 프레임 오차 가능 — 구간 끝은 `clamp` 와 썸네일 시각 보정으로 보호 |
| 가변 프레임레이트(VFR) 영상 | `avg_frame_rate` 를 fps 로 사용. 프레임↔초 변환 오차는 GIF 용도에서 허용 |
| 긴 영상 전체를 GIF 로 → 거대 파일 | `estimate_warning` 으로 변환 전 확인 다이얼로그 |
| 썸네일 요청 폭주 | 풀 동시 4 + 디바운스 200ms + 슬라이더는 release 시점에만 요청 + 지연 도착 결과 무시(key 비교) |
| ffmpeg stderr 파이프 가득 차 데드락 | stderr 는 별도 스레드로 소비 |
| 변환 중 창 닫기 | `closeEvent` 확인 → `cancel()` → 프로세스 terminate → 중간 파일 삭제 → `wait()` |
| 예상 크기 오차 | 휴리스틱은 ±50%, 샘플은 보통 ±20% 수준. 표기에 `~`/`≈` 로 신뢰도를 구분하고, 툴팁에 `"Estimate from 2 samples (48 frames). Actual size may differ."` 명시. 변환 후 실측과 비교해 로그에 오차 기록 |
| 샘플 추정이 ffmpeg 자원을 잠식 | 변환 중에는 추정 중단. 추정 풀 동시 수는 썸네일과 공유(4). 디바운스 500ms + 이전 요청 취소 |
| Windows 10 과 11 동작 차이 | 12장 규칙 준수 + Win10 VM 에서 P9 체크리스트 |
| 설치 시 네트워크 차단 · 사내 프록시 | `bootstrap.py --ffmpeg-zip <로컬 zip>` 오프라인 경로, `--pip-index-url` 미러 지정, `HTTPS_PROXY` 환경변수 존중(urllib 기본). 실패 항목은 수동 절차를 리포트에 출력 |
| 다운로드 파일 변조 · 손상 | gyan.dev 가 제공하는 `.sha256` 로 검증. 불일치면 삭제하고 대체 URL(BtbN) 로 1회 재시도. 그래도 실패면 중단 |
| 백신이 ffmpeg.exe 를 격리 | 리포트에 `bin/ffmpeg.exe` 경로와 "백신 예외 추가" 안내. 코드 대응은 없음 |
| 시스템 Python 오염 | 기본은 현재 인터프리터에 설치. `--venv` 옵션이면 `<tool>/.venv` 를 만들고 `setup.bat`/`run.bat` 이 그 인터프리터를 쓴다 |
| 중복/대소문자 다른 경로 | `Path.resolve()` 후 비교 (Windows 는 대소문자 무시: `os.path.normcase`) |

---

### 5.9 MP4 변환기 (`converters/mp4_converter.py`) — v0.2.0 에서 구현

GIF 와 공통인 필드는 `converters/common.py` 의 `VideoOptions`(width/height/lock/anchor/quality/fps_mode/fps_custom/target_size_mb/max_attempts/hwaccel)
로 묶고, `GifOptions`/`Mp4Options` 가 상속한다. UI 도 `CommonOptionsPanel` 을 상속해 포맷 고유 행만 추가한다.

```python
@dataclass
class Mp4Options(VideoOptions):
    format_id = "mp4"; fps_custom = 30.0
    preset: str = "medium"      # x264 preset (ultrafast … veryslow)
    audio: str = "aac"          # "aac"(128 kbps 재인코딩) | "copy" | "none"
```

| 항목 | 규칙 |
|------|------|
| CRF | `crf = clamp(14, 40, round_half_up(36 - q*0.2))` → q100=16, q70=22, q50=26, q10=34 |
| fps | `auto`/`source` = 원본 유지(필터 없음), `custom` = `min(src, custom)` 이고 원본과 다를 때만 `fps=` 필터 |
| 크기 | `scale=W:H:flags=lanczos`. 락 축은 `-2`, 락 해제 정확값은 **짝수 보정**(yuv420p) |
| 명령 | `ffmpeg -y -nostats -progress pipe:1 [-hwaccel auto] [-ss -t] -i src [-vf …] -c:v libx264 -crf N -preset P -pix_fmt yuv420p -movflags +faststart (-an \| -c:a copy \| -c:a aac -b:a 128k) out.mp4` |
| 목표 용량 | 시도마다 `quality -= 20`(CRF +4), 2차부터 폭 85% |
| 휴리스틱 | `2048 + w*h*fps*dur*bpp/8 + 128kbps*dur(오디오 있을 때)`, `bpp = 0.10 * 2^((23-crf)/6)` |
| 샘플 추정 | 공통 경로 그대로 (구간 샘플을 같은 옵션으로 인코딩) |

기본 오디오를 `aac` 재인코딩으로 둔 이유: mov 의 PCM 등 MP4 컨테이너가 담지 못하는 코덱이 흔하고, 구간 자르기와도 안전하다.
`copy` 는 사용자가 코덱 호환을 아는 경우용.

## 11. 미래 확장 메모 (이번 범위 밖, 구조만 대비)

- `WebPConverter`: `-c:v libwebp -lossless 0 -q:v {q} -loop 0`. `VideoOptions` + `CommonOptionsPanel` 을 그대로 상속하면 된다.
- ~~`Mp4Converter`~~ → 5.9 에서 구현 (v0.2.0).
- `ImageSequenceConverter`: `out_%04d.png`. 출력이 폴더가 되므로 `make_output_path` 에 `is_dir` 변형 필요.
- gifski 엔진(2.2), 프리셋 저장/불러오기(JSON), 결과 파일 더블클릭으로 열기, 리스트 정렬, 휴리스틱 계수 자동 보정(실측 누적).

---

## 12. Windows 10 호환 규칙

이 툴은 **Windows 10 과 Windows 11 양쪽**에서 동작해야 한다. 개발 PC 는 Win11 이므로 아래 규칙으로 차이를 미리 막는다.

### 12.1 런타임 요구

| 구성 | 요구 | 비고 |
|------|------|------|
| Windows | **10 버전 21H2 (빌드 19044) 이상**, 11 | Qt 6.9+ 의 최소 지원 버전. 그 이전 Win10 을 지원해야 하면 `PySide6==6.8.*` 로 고정 (Win10 1809+) |
| Python | 3.11.x 64-bit | Win10 지원. `python.org` 설치본 또는 PyInstaller 번들 |
| PySide6 | `>=6.8,<7` 를 `requirements.txt` 에 고정 | 메이저 7 로 자동 승격 금지 |
| ffmpeg | 정적 빌드(gyan.dev / BtbN) 7.x | Win10/11 공통. `bin/` 배치 또는 imageio-ffmpeg |
| VC 런타임 | Python 3.11 은 UCRT 사용 → Win10 에 기본 포함 | 별도 설치 불필요 |

### 12.2 코드 규칙

- **Windows 11 전용 API 금지**: DWM 의 Mica/Acrylic(`DWMWA_SYSTEMBACKDROP_TYPE`), 둥근 모서리 속성, `DWMWA_USE_IMMERSIVE_DARK_MODE`(Win10 20H1 이전 미지원) 를 호출하지 않는다.
  타이틀 바는 OS 기본으로 두고 어두운 테마는 qss 로 클라이언트 영역만 칠한다.
- **폰트**: qss 에 `Segoe UI Variable`(Win11 전용) 을 쓰지 않는다. 폰트 패밀리를 지정하지 않고 시스템 기본(Win10 `Segoe UI`) 을 상속한다.
- **아이콘·이모지 금지**: 🔒 같은 이모지는 Win10 의 `Segoe UI Emoji` 버전에 따라 렌더가 다르다. 텍스트(`Lock`/`Free`) 또는 Qt 표준 아이콘(`QStyle.StandardPixmap`) 만 쓴다 (6.8 에 반영됨).
- **High DPI**: `QApplication` 생성 전 `QGuiApplication.setHighDpiScaleFactorRoundingPolicy(PassThrough)`. 델리게이트의 모든 픽셀 치수는 `option.widget.logicalDpiX()/96` 배율 또는 폰트 메트릭 기반으로 계산해 125%/150% 에서 깨지지 않게 한다 (Win10 노트북 기본 125%).
- **파일 경로**: 260자 초과 경로는 Win10 기본 설정에서 실패할 수 있다. 출력 경로 길이 > 240 이면 `validate` 가 경고 문구 `"Output path is too long for Windows (>240 chars)."` 를 돌려준다. `\\?\` 접두는 쓰지 않는다 (ffmpeg 가 처리하지 못함).
- **서브프로세스**: `CREATE_NO_WINDOW` 는 Win10/11 동일. `subprocess` 에 `shell=False` 리스트 argv (4장).
- **폴더 열기**: `Open Containing Folder` 는 `QDesktopServices.openUrl(QUrl.fromLocalFile(dir))` 로. `explorer /select,` 는 경로에 쉼표가 있으면 Win10 에서 실패 사례가 있어 쓰지 않는다.
- **QSettings**: 레지스트리 `HKCU\Software\JUN\JUN_Video_Tool` — 양쪽 동일.
- **드래그&드롭**: Win10 에서 관리자 권한으로 실행한 앱은 탐색기 드롭을 받지 못한다(UIPI). README 에 "일반 권한으로 실행" 명시. 코드 대응은 없음.
- **임시 폴더**: 샘플 추정 임시 파일은 `tempfile.gettempdir()/JUN_Video_Tool/` 에. 종료 시 폴더 정리.

### 12.3 검증 체크리스트 (P9 에서 Win10 머신 또는 VM 으로 수행)

1. `python launch.py` 기동, 창 테마·폰트·레이아웃이 Win11 과 동일한지 (스크린샷 비교).
2. 125% / 150% DPI 에서 리스트 행 높이·썸네일 격자·범위 슬라이더 핸들이 잘리지 않는지.
3. 탐색기에서 파일 10개 드래그&드롭, 한글·공백 경로 포함.
4. 썸네일 보기 전환, 구간 편집 미리보기 갱신.
5. 변환 2개 병렬 + 취소. ffmpeg 콘솔 창이 뜨지 않는지.
6. `-hwaccel auto` 가 GPU 없는 VM 에서 실패하면 CPU 폴백 재시도가 동작하는지 (로그 확인).
7. 예상 크기 표시 → 변환 후 실측과 비교, 오차 로그 확인.
8. `bin/` 에 ffmpeg 를 두었을 때 / PATH 만 있을 때 / imageio-ffmpeg 만 있을 때 세 경로 모두 기동.
9. 종료 후 재기동 시 창 위치·옵션·보기 모드 복원.
10. **깨끗한 Win10 (Python 만 설치)** 에서 `setup.bat` → `run.bat` 만으로 변환까지 되는지.

---

## 13. 의존성 일괄 설치 (R11) — `bootstrap.py` · `setup.bat` · `DependencyDialog`

### 13.1 목표

새 PC 에 **Python 3.11 만 있으면** `setup.bat` 더블클릭 한 번으로 PySide6 등 pip 패키지와 ffmpeg/ffprobe 바이너리가 설치되고,
앱이 바로 실행된다. 이미 설치된 항목은 건너뛰고(멱등), 결과를 표로 보여 준다.

### 13.2 설치 대상 (`deps.json`)

```json
{
  "python": {"min": "3.11", "max_exclusive": "3.14"},
  "pip": {"requirements": "requirements.txt", "dev_requirements": "requirements-dev.txt"},
  "binaries": [
    {
      "name": "ffmpeg",
      "install_dir": "bin",
      "files": ["ffmpeg.exe", "ffprobe.exe"],
      "verify_cmd": ["ffmpeg.exe", "-version"],
      "sources": [
        {"url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
         "sha256_url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256",
         "members_glob": "*/bin/{name}"},
        {"url": "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-win64-gpl.zip",
         "sha256_url": null,
         "members_glob": "*/bin/{name}"}
      ],
      "pip_fallback": "imageio-ffmpeg"
    }
  ]
}
```
- 소스는 순서대로 시도. 첫 번째(gyan.dev release essentials, 약 90 MB) 는 **안정 릴리스 + sha256 제공**이라 기본. 두 번째(BtbN) 는 대체.
- 모두 실패하면 `pip_fallback` 패키지를 설치해 `ffmpeg_locator` 3단계가 잡을 수 있게 한다 (ffprobe 는 없음 → stderr 파싱 폴백).
- 새 바이너리(예: gifski) 를 추가할 때는 이 JSON 에 항목만 추가한다. `bootstrap.py` 코드는 바뀌지 않는다.
- 라이선스: ffmpeg GPL 빌드를 **사용자 PC 에서 다운로드**하는 방식이므로 저장소에 바이너리를 포함하지 않는다 (`bin/` 은 `.gitignore`).

### 13.3 `bootstrap.py` (표준 라이브러리만: `argparse, json, sys, subprocess, urllib.request, hashlib, zipfile, fnmatch, tempfile, shutil, importlib.metadata`)

```
python bootstrap.py [--check] [--venv] [--dev] [--no-pip] [--no-binaries]
                    [--ffmpeg-zip PATH] [--pip-index-url URL] [--yes] [--json]
```

| 단계 | 동작 | 실패 시 |
|------|------|---------|
| 0 | Python 버전 검사 (`deps.json` 범위). `--venv` 면 `<tool>/.venv` 생성 후 **그 인터프리터로 자기 자신을 재실행** | 범위 밖이면 안내 후 종료(코드 2) |
| 1 | `pip` 상태: `importlib.metadata.version()` 으로 `requirements.txt` 각 항목의 설치 여부·버전 확인 | — |
| 2 | 누락/버전 불일치 패키지만 `python -m pip install -r requirements.txt [--index-url …]` (`--dev` 면 dev 도) | 종료 코드·stderr 를 리포트에 기록, 계속 진행 |
| 3 | 바이너리별: `install_dir` 에 `files` 가 모두 있고 `verify_cmd` 가 성공하면 **건너뜀** | — |
| 4 | 다운로드: `--ffmpeg-zip` 이 있으면 그 파일 사용. 없으면 `sources` 순서로 `urllib.request.urlopen` (타임아웃 30 s, 진행률 콘솔 표시, 임시 폴더에 저장) | 다음 소스 |
| 5 | 검증: `sha256_url` 이 있으면 받아 비교. 불일치 → 삭제 후 다음 소스 | 다음 소스 |
| 6 | 추출: `zipfile` 에서 `members_glob` 에 맞는 멤버만 `install_dir` 로 (경로 탈출 방지: 멤버 이름 정규화 후 basename 만 사용) | 다음 소스 |
| 7 | `verify_cmd` 실행 → 첫 줄을 `bin/VERSION.txt` 에 기록 | 삭제 후 다음 소스 |
| 8 | 모든 소스 실패 → `pip_fallback` 설치 | 리포트에 수동 절차 출력 |
| 9 | **리포트**: 항목 / 상태(`OK · Installed · Skipped · FAILED`) / 버전 / 위치 를 표로 출력. `--json` 이면 JSON 으로(`DependencyDialog` 가 파싱) | 하나라도 FAILED 면 종료 코드 1 |

- `--check` 는 1·3 단계만 수행하고 리포트만 출력한다 (설치 없음). 앱 내 상태 표가 이걸 쓴다.
- `--yes` 가 없으면 다운로드 전에 용량과 URL 을 보여 주고 `[Y/n]` 확인. `setup.bat` 은 `--yes` 없이 호출해 사용자가 확인하게 한다.
- 콘솔 출력은 영어. 종료 시 `setup.bat` 이 `pause` 로 창을 유지한다.

### 13.4 `launch.py` 의 사전 점검 (PySide6 가 없어도 동작해야 함)

```python
def main():
    missing = dependency_check.missing_pip_packages()        # 표준 라이브러리만으로 판단
    if missing:
        msg = "Missing packages: … Run setup.bat to install them."
        _show_fallback_message(msg)                             # tkinter.messagebox 가 가능하면 그것, 아니면 print + input()
        if _ask_yes_no("Run setup now?"): subprocess.call([sys.executable, "bootstrap.py"]); return
        sys.exit(1)
    from app.ui.main_window import MainWindow                   # 여기서 처음 PySide6 import
    …
```
- `python.org` 설치본은 tkinter 를 포함하므로 GUI 안내가 가능하고, 없으면 콘솔로 대체한다.
- ffmpeg 누락은 PySide6 가 있는 상태이므로 `MainWindow` 가 Qt 다이얼로그로 처리한다 (6.11).

### 13.5 `DependencyDialog(QDialog)` (`ui/dependency_dialog.py`)

- 열리면 `bootstrap.py --check --json` 을 `QProcess` 로 실행해 표를 채운다: `Name | Required | Found | Status | Location`.
  행 예: `PySide6 | >=6.8,<7 | 6.11.1 | OK | site-packages`, `ffmpeg | any | — | Missing | bin/`.
- 버튼: `Install Missing`(= `bootstrap.py --yes --json`, 누락이 없으면 비활성), `Re-check`, `Open bin Folder`, `Close`.
- 설치 중에는 하단 `QPlainTextEdit` 에 bootstrap 의 stdout 을 실시간 스트리밍하고(`readyReadStandardOutput`), 진행률 바는 bootstrap 이 출력하는
  `PROGRESS <percent>` 줄을 파싱해 갱신. 끝나면 표를 다시 채우고 `dependencies_changed = Signal()` 발행 → 메인 윈도우가 `ffmpeg_locator` 캐시를 비우고 버튼을 활성화.
- 설치 중 다이얼로그를 닫으려 하면 확인 후 `QProcess.kill()`. 부분 설치된 zip/임시 파일은 bootstrap 이 `atexit` 로 정리.

### 13.6 `setup.bat` · `run.bat`

```bat
@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 bootstrap.py %*) || (python bootstrap.py %*)
pause
```
- `run.bat`: `.venv` 가 있으면 `.venv\Scripts\python.exe launch.py`, 없으면 `py -3 launch.py` (`--venv` 로 설치한 경우 대응).
- README 설치 절차는 세 줄이다: ① Python 3.11 설치 ② `setup.bat` 더블클릭 ③ `run.bat` 더블클릭.

### 13.7 테스트 (`tests/test_bootstrap.py`, 네트워크 없이)

- `deps.json` 스키마 로드와 `members_glob` 매칭: `fnmatch("ffmpeg-7.1-essentials_build/bin/ffmpeg.exe", "*/bin/ffmpeg.exe")` → True, `"../bin/ffmpeg.exe"` 는 경로 정규화 후 basename 만 쓰는지.
- sha256 비교 함수, 버전 범위 비교(`"6.11.1"` 이 `">=6.8,<7"` 을 만족, `"7.0.0"` 은 불만족 — `packaging` 없이 튜플 비교로 구현).
- `--check --json` 출력이 `DependencyDialog` 가 기대하는 키(`name, required, found, status, location`)를 갖는지 (가짜 환경 주입).
