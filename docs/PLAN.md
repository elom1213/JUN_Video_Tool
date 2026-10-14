# JUN_Video_Tool — 구현 계획서 (v01)

- **Author**: Ji Hun Park (Junny / `Dnable_JunnyPark`)
- **작성일**: 2026-10-14
- **상태**: 코드 작성 전 설계 확정본. 이 문서만 보고 코드를 작성할 수 있는 수준을 목표로 한다.
- **대상 환경**: Windows 11, Python 3.11, PySide6 6.x (이 PC 에 6.11.1 설치 확인됨), ffmpeg (별도 확보 — 4장)

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

### 1.2 비기능 요구

- UI 가 멈추지 않을 것 — 프로브 · 썸네일 · 변환은 모두 워커 스레드/프로세스에서.
- 변환 중 **취소** 가능. 항목별 진행률 + 전체 진행률 표시.
- 실패한 항목은 건너뛰고 나머지 계속. 실패 이유를 로그 패널과 항목 상태에 남긴다.
- 마지막 사용 폴더 · 옵션 · 보기 모드를 `QSettings` 로 기억.
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
| 스레딩 | 썸네일·프로브: `QThreadPool` + `QRunnable` / 변환: 전용 `QThread` 1개가 큐를 순차 처리 | ffmpeg 자체가 멀티스레드이므로 동시 변환은 1 |
| 설정 | `QSettings("JUN", "JUN_Video_Tool")` | 레지스트리 저장, 의존성 없음 |
| 테스트 | `pytest` (명령 생성·수치 변환 등 순수 로직만) | ffmpeg 없이도 도는 테스트로 한정 |

---

## 3. 디렉터리 구조

```
JUN_Video_Tool/
├── launch.py                      # 진입점. run() → QApplication → MainWindow.show()
├── requirements.txt               # PySide6>=6.6 ; imageio-ffmpeg (선택, ffmpeg 폴백) ; pytest (개발)
├── README.md
├── CHANGELOG.md
├── .gitignore                     # __pycache__/ *.pyc bin/ .venv/ dist/ build/ *.spec
├── bin/                           # (선택) ffmpeg.exe / ffprobe.exe 를 여기에 두면 최우선 사용. git 제외
├── docs/
│   └── PLAN.md                    # 이 문서
├── tests/
│   ├── test_utils.py              # 프레임↔초, 크기 계산, 품질 매핑, 출력 경로
│   ├── test_gif_converter.py      # build_command() 가 만든 인자 리스트 검증
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
    │   ├── media_probe.py         # MediaInfo 생성: probe(path)
    │   ├── thumbnail.py           # extract_frame_png(path, time_sec, max_width) -> bytes
    │   ├── models.py              # VideoItem, FrameRange, ItemStatus, MediaInfo, ConvertOptions, ConvertJob, ConvertResult
    │   ├── utils.py               # frame_to_sec, sec_to_frame, fit_size, make_output_path, format_timecode, subprocess_flags
    │   ├── job_runner.py          # JobRunner(QThread): 큐 순차 실행, 진행률 파싱, 취소
    │   └── converters/
    │       ├── __init__.py        # registry 생성 + GifConverter 등록
    │       ├── base.py            # BaseConverter(ABC), ConverterRegistry
    │       └── gif_converter.py   # GifOptions, GifConverter
    └── ui/
        ├── __init__.py
        ├── main_window.py         # MainWindow(QMainWindow)
        ├── styles/
        │   └── dark.qss
        └── widgets/
            ├── __init__.py
            ├── video_list_model.py    # VideoListModel(QAbstractListModel)
            ├── video_item_delegate.py # VideoItemDelegate: list / thumbs 두 모드 그리기
            ├── video_list_view.py     # VideoListView(QListView): 드래그&드롭, 뷰 모드 전환, 컨텍스트 메뉴
            ├── loaders.py             # ProbeLoader, ThumbnailLoader (QThreadPool 비동기 + 캐시)
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
- `requirements.txt` 의 `imageio-ffmpeg` 는 **선택 의존**이지만 기본 포함해, `pip install -r requirements.txt` 만으로 변환이 되게 한다.

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
    fps_override: float | None = None   # None → quality 매핑으로 fps 결정
    loop: int = 0                       # 0 = 무한 반복
    target_size_mb: float | None = None # None → 비활성
    max_attempts: int = 5

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

- `fps_override` 가 있으면 fps 공식만 대체한다 (`min(src_fps, fps_override)`).

**명령 생성** (`build_command`)

```
ffmpeg -hide_banner -y -nostats -progress pipe:1
       [-ss {start_sec:.3f} -t {dur_sec:.3f}]  -i <src>
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
  - 매 시도 `quality = max(5, quality - 15)`.
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
                 jobs: list[tuple[int, ConvertJob]], parent=None)
    def run(self) -> None:          # for row, job in jobs: if self._cancel: emit canceled result; else _run_one
    def cancel(self) -> None:       # self._cancel = True ; 현재 Popen 이 있으면 terminate()
    def _run_one(self, row: int, job: ConvertJob) -> ConvertResult:
        # attempt 루프 (타깃 크기 지원 시 최대 max_attempts):
        #   cmd = converter.build_command(ffmpeg, job.item, opts, job.output_path)
        #   self._proc = Popen(cmd, stdout=PIPE, stderr=PIPE, text=True, encoding="utf-8", errors="replace",
        #                      creationflags=subprocess_flags())
        #   stdout 을 줄 단위로 읽어 "out_time_us=" / "out_time_ms=" 값으로 percent 계산 (dur_sec 기준), "progress=end" 로 종료 감지
        #   stderr 는 별도 스레드(threading.Thread) 로 흘려 받아 마지막 20줄 보관 (파이프 데드락 방지)
        #   returncode != 0 → ok=False, error=tail_lines(stderr)
        #   취소 플래그 → 출력 파일 삭제 후 canceled=True
        #   ok 이고 타깃 크기 초과 → degrade_for_retry → 반복
```
- `MainWindow` 가 `ConvertJob` 목록을 만든다: 체크된 항목 중 `info` 가 있는 것만. `info` 없는 체크 항목은 `SKIPPED` 로 표시하고 로그.
- 러너는 한 번에 하나만 존재. 실행 중에는 `Convert Checked` 비활성, `Cancel` 활성, 리스트 편집(추가·삭제) 비활성.

---

## 6. UI 설계

### 6.1 전체 레이아웃 (`MainWindow`, 기본 1280×760, 최소 1000×600)

```
┌ JUN Video Tool v0.1.0 ───────────────────────────────────────────────────────────────────────┐
│ [Add Files] [Add Folder] [Remove] [Clear] │ [Check All] [Uncheck All] [Invert] │ View: (● List ○ Thumbnails) │
├────────────────────────────────────────────────────┬─────────────────────────────────────────┤
│ VideoListView   (QSplitter 좌:우 = 6:4)             │ Output format: [ GIF              ▼ ]   │
│  ☑ clip_a.mp4     1920x1080 · 29.97 fps · 00:12  Done · 1.8 MB │ ┌ GIF Options ───────────────────────┐ │
│  ☑ clip_b.mov     1280x720  · 30 fps    · 01:03  ▓▓▓▓░░ 62 %  │ │ Width [ 640 ] [Lock] Height [ 360 ] │ │
│  ☐ clip_c.mp4     ...                                  Idle   │ │ [Reset to Source Size]             │ │
│                                                         │ │ Quality ───────●──── 70              │ │
│  (Thumbnails 모드: 160x90 썸네일 격자 + 파일명)          │ │   18 fps · 144 colors · bayer       │ │
│                                                         │ │ ☐ FPS override [ 15.0 ]              │ │
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
- 커스텀 롤: `ItemRole = UserRole + 1`(VideoItem), `InfoTextRole`("1920x1080 · 29.97 fps · 00:12 · 12.3 MB"), `StatusRole`(ItemStatus), `ProgressRole`(int), `MessageRole`(str).
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
- **list** 모드 — 행 높이 28px. 좌→우: `[체크박스 16px] 파일명(elide middle, 폭의 45%) │ info 텍스트(회색) │ 우측 140px 상태 영역`.
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
  `frames_label`(`"Frames: 120 / 360 (4.0 s)"`), 시작/끝 미리보기 `QLabel` 160×90, 버튼 `Full Range`, `Apply to Checked`.
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

`GifOptionsPanel` 동작 세부
- `width_spin`, `height_spin`: QSpinBox 0~8192, `specialValueText("Source")` 로 0 = 원본.
  `lock_btn`: checkable QToolButton, 텍스트 `"Lock"`(ON) / `"Free"`(OFF). `reset_btn`: `"Reset to Source Size"` → 두 스핀을 0 으로.
- **락 ON**: `width_spin.valueChanged` → `anchor = "width"`, `height = round(width / ref_aspect)` 를 `blockSignals(True)` 상태로 반영. 반대도 동일.
  `ref_aspect` 는 `set_reference_info` 로 받은 선택 항목 비율, 없으면 16:9. 0(Source) 입력 시 다른 축도 0.
  변환 시에는 anchor 축 값만 전달되고 다른 축은 `-2` (5.6) → **항목별 비율 유지**가 보장된다. UI 의 다른 축 값은 "선택 항목 기준 예시" 임을 툴팁으로 안내.
- **락 OFF**: 두 값을 그대로 모든 항목에 적용 (비율 왜곡 허용).
- `quality_slider`(QSlider 1~100) + 값 라벨 + 매핑 힌트 라벨(`"18 fps · 144 colors · bayer"`, `ref_info.fps` 기준, 없으면 30 가정).
- `fps_check` + `fps_spin`(QDoubleSpinBox 1~60, 소수 1자리), `target_check` + `target_spin`(QDoubleSpinBox 0.1~500 MB), `loop_spin`(0~100, 0 툴팁 `"0 = infinite"`).
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

- 메뉴바: `File`(Add Files… `Ctrl+O`, Add Folder… `Ctrl+Shift+O`, Exit), `Edit`(Check All `Ctrl+A`, Uncheck All `Ctrl+Shift+A`, Invert Check `Ctrl+I`, Remove Selected `Del`, Clear List),
  `View`(List `Ctrl+1`, Thumbnails `Ctrl+2`), `Help`(About, Show ffmpeg Info).
- 툴바는 6.1 의 버튼. 뷰 모드는 `QActionGroup` 으로 상호 배제.
- 시작 시 ffmpeg 를 못 찾으면 `QMessageBox.critical` 로
  `"ffmpeg was not found. Put ffmpeg.exe (and ffprobe.exe) into:\n<tool>/bin\nor install it on PATH, or run: pip install imageio-ffmpeg"` 를 띄우고,
  `Convert Checked` 와 `Add *` 를 비활성한 채 창은 열어 둔다.
- 창 제목 `f"JUN Video Tool v{VERSION}"`.

### 6.12 `AppSettings` (`config/settings.py`)

- `QSettings("JUN", "JUN_Video_Tool")`.
- 키: `ui/geometry`(bytes), `ui/splitter`(bytes), `ui/view_mode`(str), `io/last_input_dir`, `io/last_output_dir`,
  `io/output_mode`("source"|"folder"), `io/suffix`, `io/overwrite`, `format/current`, `gif/<field>`(GifOptions 각 필드).
- `load_gif_options() -> GifOptions`, `save_gif_options(opts)`, `get(key, default)`, `set(key, value)`.
- 저장 시점: `closeEvent`, 변환 시작 시(옵션).

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
| `make_output_path("a.mp4", None, "_gif", ".gif", overwrite=False)` (a_gif.gif 존재) | `a_gif_001.gif` |
| `make_output_path("a.mp4", Path("out"), "", ".gif", overwrite=True)` | `out/a.gif` |
| `eval_fraction("30000/1001")` | `29.97…` ; `eval_fraction("0/0")` → `0.0` |
| `parse_ffmpeg_stderr(sample, 1234)` | `width=1920, height=1080, fps=29.97, duration=12.34, codec="h264"` |

`test_gif_converter.py` 는 `GifConverter.build_command` 결과에 대해
`-ss 1.000`, `-t 1.000` 포함, 전체 구간이면 둘 다 미포함, 필터 문자열에 `fps=18`, `scale=640:-2:flags=lanczos`, `max_colors=144`, `dither=bayer:bayer_scale=3` 포함,
`-loop 0` 포함, 마지막 인자가 출력 경로임을 단언한다. `degrade_for_retry` 는 quality 70 → 55 → 40, attempt 2 부터 width 축소를 단언한다.

---

## 8. 구현 순서 (각 단계가 끝나면 실행 가능한 상태 유지)

| 단계 | 내용 | 완료 기준 |
|------|------|-----------|
| **P0** | 뼈대: 디렉터리, `version.py`, `constants.py`, `launch.py`, 빈 `MainWindow`, `dark.qss`, `.gitignore`, `requirements.txt` | `python launch.py` 로 창이 뜬다 |
| **P1** | `models`, `utils`, `ffmpeg_locator`, `media_probe`, `thumbnail` + `tests/test_utils.py`, `test_probe_parser.py` | pytest 통과. 콘솔에서 `probe()` / `extract_frame_png()` 동작 |
| **P2** | `VideoListModel`, `VideoItemDelegate`(list 모드), `VideoListView`, 툴바(추가/제거/체크 3종), 드래그&드롭, `ProbeLoader`, `LogPanel` | 리스트업 + 메타데이터 표시 |
| **P3** | `ThumbnailLoader`, delegate thumbs 모드, View 전환 | 썸네일 격자 보기 |
| **P4** | `converters/base`, `GifOptions`, `GifConverter`, `gif_params_for_quality`, `tests/test_gif_converter.py` | 명령 생성 테스트 통과 |
| **P5** | `BaseOptionsPanel`/`OptionsPanelFactory`, `GifOptionsPanel`(크기·락·품질·fps·loop), `OutputPanel`, 포맷 콤보 | 옵션이 `GifOptions` 로 왕복(get/set) |
| **P6** | `RangeSlider`, `FrameRangePanel`, 시작/끝 미리보기, Apply to Checked, 컨텍스트 메뉴 Reset Range | 항목별 구간 저장·표시 |
| **P7** | `JobRunner`, 진행률, 취소, 항목 상태 표시, 전체 진행 바, 완료 요약, 큰 출력 경고 | 벌크 GIF 변환 end-to-end |
| **P8** | Target size 재시도, `AppSettings` 저장/복원, 단축키, `README.md`(ffmpeg 설치 안내), `CHANGELOG.md` | v0.1.0 |

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
| 중복/대소문자 다른 경로 | `Path.resolve()` 후 비교 (Windows 는 대소문자 무시: `os.path.normcase`) |

---

## 11. 미래 확장 메모 (이번 범위 밖, 구조만 대비)

- `WebPConverter`: `-c:v libwebp -lossless 0 -q:v {q} -loop 0`. 옵션이 GifOptions 와 거의 같아 `AnimatedImageOptions` 베이스로 묶을 수 있다.
- `Mp4Converter`(재인코딩 / 리사이즈 / 구간 자르기): `-c:v libx264 -crf {crf} -preset {preset} -pix_fmt yuv420p`, 오디오 복사/제거 옵션. 짝수 크기 보정은 `-2` 로 이미 해결.
- `ImageSequenceConverter`: `out_%04d.png`. 출력이 폴더가 되므로 `make_output_path` 에 `is_dir` 변형 필요.
- 동시 변환 수 설정, 프리셋 저장/불러오기(JSON), 결과 파일 더블클릭으로 열기, 리스트 정렬.
