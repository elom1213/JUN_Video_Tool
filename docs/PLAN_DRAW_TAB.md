# JUN_Video_Tool — Convert / Draw 탭 분리 계획서 (v0.3.0)

- **Author**: Ji Hun Park (Junny / `Dnable_JunnyPark`)
- **작성일**: 2026-10-14
- **상태**: 설계 확정본. **2026-10-16 사용자 답변 · 추가 요청을 13장에 반영 — 13장이 앞 장과 충돌하면 13장이 우선한다.**
- **선행 문서**: [`PLAN.md`](PLAN.md) (v0.1.0 ~ v0.2.0 설계). 이 문서는 PLAN.md 의 **3장(디렉터리) · 6장(UI) 을 덧쓰는 증분 계획**이다.
  PLAN.md 의 코어(변환기 · 추정 · 러너)와 컨벤션(9장) · Win10 규칙(12장)은 그대로 유효하다.
- **대상 환경**: PLAN.md 와 동일 — Windows 10 (21H2+) / 11, Python 3.11, PySide6 6.x (개발 PC 6.11.1), `bin/ffmpeg.exe`.
- **이 문서의 목표**: 이 문서만 읽고 코드를 열어 바로 작업을 시작할 수 있어야 한다. 클래스 · 시그널 · 파일 · 상수 · 단축키 ·
  JSON 스키마 · 구현 순서 · 완료 기준이 전부 여기에 있다. 결정이 필요한 지점은 **결정과 이유**를 같이 적었다.

---

## 0. 한 줄 요약

기존 변환 기능 전부를 **`Convert` 탭**으로 옮기고, **`Draw` 탭**을 신설한다. Draw 탭은 영상을 리스트업해 고르고,
**프레임 단위로 재생 · 정지 · 좌우 이동**(화살표 키, 화면 드래그)하면서 **멈춘 프레임 위에 마우스로 선을 그리고**,
앞뒤 프레임의 선을 **반투명 고스트(Ghosting)** 로 겹쳐 보고, 그린 내용을 **프레임별 JSON 으로 저장 · 불러오기**해서
재생 화면 위에 함께 보는 애니메이션 리뷰(드로오버) 기능이다.

---

## 1. 요구사항

### 1.1 사용자 요청 → 구현 결정

| # | 요청 | 구현 결정 |
|---|------|-----------|
| D0 | 기존 영상 변환 기능 전부를 `Convert` 탭으로 이식 | `MainWindow` 의 변환 관련 본문을 `ConvertTab(QWidget)` 으로 그대로 옮긴다. 동작 · 단축키 · 설정 키는 바꾸지 않는다 (3장) |
| D1 | Convert 처럼 영상을 리스트업하고 골라서 재생 · 정지 | Draw 탭에 **별도의** `VideoListModel` + `VideoListView` (체크박스 없음, 단일 선택). 선택한 항목을 `VideoCanvas` 에 표시, `Space` 로 재생/정지. 프레임 디코딩은 **ffmpeg rawvideo 파이프**(4.1) — QtMultimedia 를 쓰지 않는 이유는 2.1 |
| D1b | Draw 탭에 리스트업된 파일도 **썸네일로 볼 수 있어야** 한다 (2026-10-14 추가 요청) | Convert 와 같은 `VideoItemDelegate` 두 모드(`List` / `Thumbnails`)를 그대로 쓴다. Draw 툴바에 `View: (● List ○ Thumbs)` 토글, `View` 메뉴 `Ctrl+1`/`Ctrl+2` 는 활성 탭의 리스트에 적용. 썸네일은 `MainWindow` 가 만든 **공유 `ThumbnailLoader`** 로 뽑아 두 탭이 캐시를 함께 쓴다 (같은 파일을 양쪽에 넣어도 1회 추출). 썸네일 모드 선택도 리스트 모드와 동일하게 `currentChanged` 로 캔버스에 영상이 올라간다. 설정 키 `draw/view_mode` 로 모드를 기억 |
| D2 | `←`/`→` 키와 화면 위 좌우 드래그로 한 프레임씩 이동 | `←`/`→` = ±1 프레임, `Shift+←/→` = ±10, `Home`/`End` = 첫/끝. 캔버스 스크럽은 **가운데 버튼 드래그만** (13.1 — Scrub 툴 모드 없음). 기본 감도 8 px/프레임 (5.3) |
| D3 | 멈춘 화면 위 드래그로 선 그리기. 두께 · 색 변경 | **Draw 모드**에서 좌드래그 = 스트로크 1개. `BrushPanel` 에서 색(스와치 8개 + `QColorDialog`) · 두께(1~64, 소스 픽셀 단위) 변경. 재생 중 드래그하면 먼저 정지하고 그린다. Undo/Redo, Clear Frame 포함 (5.4) |
| D4 | Ghosting — 그린 선이 앞뒤 프레임에서 반투명으로 보임. 범위는 사용자 선택 | `GhostPanel`: On/Off, `Before`(0~30), `After`(0~30), `Opacity`(5~100 %). 거리 d 의 투명도 = `opacity × (1 − (d−1)/N)` (7장). 재생 중에도 적용 |
| D5 | 프레임별 그림 정보를 따로 저장 · 불러오기, 재생 화면과 같이 보기 | `DrawingDocument` → **영상 옆 사이드카** `<영상이름>.draw.json` (6장 스키마). `Save`(`Ctrl+S`) / `Save As…` / `Load…`(`Ctrl+L`). 영상을 선택할 때 사이드카가 있으면 **자동 로드**. 로드된 선은 정지 · 재생 · 스크럽 모두에서 캔버스 위에 그려진다 |

### 1.2 비기능 요구

- Draw 탭의 프레임 이동은 **프레임 정확(frame-accurate)** 해야 한다. 29.97 fps 에서도 `→` 를 N 번 누르면 정확히 N 프레임 뒤다.
- 캐시된 프레임으로의 이동은 즉시(< 16 ms 페인트), 캐시 밖 이동은 1080p 기준 0.3 s 이내 목표.
- 메모리 상한: 디코드 캐시 **512 MB** (`DRAW_CACHE_BUDGET_MB`). 초과 시 LRU 로 버린다.
- 두 탭은 서로 독립 — Convert 변환 중에도 Draw 탭은 동작한다. 단 프로세스 풀(`QThreadPool`)과 썸네일 캐시는 공유한다.
- 모든 UI 문자열은 영어 (전역 규칙). 주석 · 독스트링은 한국어.

### 1.3 범위 밖 (이번에 하지 않음)

- ~~오디오 재생~~ → 13.1 로 범위에 들어옴.
- 캔버스 줌 · 팬 (항상 Fit). 도형 · 텍스트 · 레이어. 스트로크 선택 · 이동. (~~지우개~~ → 13.3)
- ~~그림이 입힌 영상의 내보내기(burn-in)~~ → 13.4 로 범위에 들어옴.
- VFR(가변 프레임률) 영상의 정확한 프레임 매핑 — `avg_frame_rate` 를 CFR 로 간주한다 (9장 리스크).
- Convert 와 Draw 리스트의 동기화(한쪽에 넣으면 다른 쪽에도 보이기). 리스트는 탭별로 독립이다.

---

## 2. 기술 결정

### 2.1 재생 엔진: ffmpeg rawvideo 파이프 (QtMultimedia 미사용)

| 후보 | 장점 | 단점 | 판단 |
|------|------|------|------|
| **ffmpeg 서브프로세스 → rawvideo 파이프** | 이미 쓰는 바이너리, 코덱 의존 없음(Win10 N 에디션 포함), `-ss` 입력 시크가 정확(디코드 후 버림), 모든 프레임을 우리가 인덱싱 | 재생 루프 · 캐시 · 스레드를 직접 짠다. 오디오 없음 | **채택** |
| `QMediaPlayer` + `QVideoSink` | 재생 · 오디오가 공짜 | Windows WMF 백엔드는 `setPosition()` 이 키프레임 단위로 틀어질 수 있어 프레임 단위 이동이 보장되지 않음. 시스템 코덱 의존. 프레임 번호를 ms 에서 역산해야 해 29.97 에서 1 프레임 오차 발생 | 기각 |
| PyAV (`av`) | 인프로세스 디코드, 빠름 | 새 pip 의존(약 40 MB, ffmpeg 바이너리 중복) | 보류. 9장 리스크의 폴백 |

### 2.2 프레임 ↔ 시간 매핑

- 프레임 `i` 의 시각 `t(i) = i / fps` (`utils.frame_to_sec`). fps 는 `MediaInfo.fps`(= `avg_frame_rate`).
- **시크 시각은 `t(i) − 0.25/fps`** 로 준다. ffmpeg 의 입력 `-ss` 는 "pts ≥ ss 인 첫 프레임"을 내보내므로,
  부동소수 오차로 `i/fps` 가 실제 pts 보다 아주 조금 커져 `i+1` 이 먼저 나오는 일을 막는다. 0.25 프레임 여유는 1 프레임보다
  작으므로 `i−1` 이 나오지는 않는다. `clamp_time` 은 쓰지 않는다 (마지막 프레임을 못 뽑는 건 EOF 로 처리).
- 출력 프레임 수를 세는 쪽(`-fps_mode passthrough`, 구 `-vsync 0`)으로 중복 · 드롭을 금지해 "읽은 순서 = 프레임 인덱스" 를 보장한다.

### 2.3 좌표계

- 스트로크 점과 두께는 **소스 영상 픽셀 단위**(float) 로 저장한다. 디코드 폭(`≤1280`)이나 창 크기와 무관하게 재현된다.
- 캔버스는 `video_rect`(레터박스 적용 fit 사각형) 하나로 양방향 변환한다 (5.2).

### 2.4 탭 구조

- `QTabWidget` 두 탭: `Convert` · `Draw`. 각 탭은 **자기 툴바를 탭 안에** 가진다 (`QToolBar` 를 레이아웃에 넣음).
  메인 윈도우 툴바는 없앤다. 각 탭이 자기 하단 영역(Convert: 진행 바 + 로그, Draw: 트랜스포트 바 + 상태 줄)을 가진다.
- 메뉴바는 메인 윈도우 하나. `Convert` 메뉴와 `Draw` 메뉴를 **항상 둘 다** 두고, 비활성 탭의 액션은 `setEnabled(False)` (5.8).
- 프레임 이동 등 Draw 전용 단축키는 `QAction.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)` 후
  `draw_tab.addAction(act)` 으로 **Draw 탭 안에 포커스가 있을 때만** 작동한다. 같은 액션을 메뉴에도 넣어 단축키 글자가 보이게 한다.
  스핀박스 · 라인에디트는 `ShortcutOverride` 로 좌우 키를 먼저 가져가므로 숫자 편집과 충돌하지 않는다.

---

## 3. Convert 탭 이식 (D0) — 무엇을 어디로

### 3.1 파일

```
app/ui/
├── main_window.py          # 얇아진다: 탭 · 메뉴 · 설정 · 시작 점검 · 종료 (5.8)
├── convert_tab.py          # 신설. 기존 MainWindow 본문 이식 → ConvertTab(QWidget)
├── draw_tab.py             # 신설. DrawTab(QWidget) (5.1)
└── widgets/
    ├── (기존 전부 유지)
    └── draw/               # Draw 전용 위젯 (5장)
```

### 3.2 `MainWindow` → `ConvertTab` 이동 표

| 현재 `MainWindow` 멤버 | 이동 후 | 비고 |
|------------------------|---------|------|
| `model, view, probe_loader, estimator, runner, _thumb_keys, _options_panel, _converter, _total_jobs, _done_jobs, _est_timer` | `ConvertTab` 속성 | 그대로 |
| `thumb_loader` | **`MainWindow` 가 만들어 두 탭에 주입** | 썸네일 캐시 공유. 생성자 인자 `ConvertTab(settings, thumb_loader, parent)` |
| `settings` | `MainWindow` 소유, 탭에 주입 | `AppSettings` 인스턴스 1개 |
| `_build_ui` 의 툴바 · 좌우 스플리터 · 하단(진행 · 로그) | `ConvertTab._build_ui` | 툴바는 `QToolBar` 를 탭 `QVBoxLayout` 맨 위에 `addWidget`. `setMovable(False)` 유지 |
| `act_add_files … act_view_thumbs, act_refresh_est` | `ConvertTab` 속성 (QAction 은 탭이 소유) | 메뉴 등록은 `MainWindow` 가 `convert_tab.menu_actions()` 로 받아서 한다 |
| `act_settings, act_deps, act_ffmpeg_info, act_about` | `MainWindow` 유지 | 전역 |
| `_build_menus` | `MainWindow._build_menus` 로 재작성 (5.8) | 단축키 값은 그대로 |
| `_connect, _restore_settings(스플리터 · 뷰모드 · 포맷 · 출력), _save_settings(같은 것)` | `ConvertTab.restore_settings()`, `ConvertTab.save_settings()` | `ui/geometry` 만 `MainWindow` 가 저장. 스플리터 키 `ui/splitter_h`, `ui/splitter_v` 는 그대로 Convert 소유 |
| `_startup_checks, _set_ffmpeg_available, _dependencies_changed` | `MainWindow._startup_checks` 가 판정 → `tab.set_ffmpeg_available(ok)` 를 두 탭에 호출. 재프로브 루프는 `ConvertTab.reprobe_missing()` · `DrawTab.reprobe_missing()` | ffmpeg 가 없으면 Draw 탭도 Add 가 막힌다 |
| 파일 추가 · 제거 · 프로브 · 썸네일 · 선택 · 구간 · 추정 · 변환 · 러너 콜백 전부 | `ConvertTab` 메서드, 이름 유지 | 로직 변경 없음 |
| `open_settings` | `MainWindow.open_settings` → `convert_tab.on_settings_changed()` 호출 (hwaccel 패널 반영 + 추정 재예약 + 로그) | |
| `closeEvent` | `MainWindow.closeEvent` 가 `convert_tab.request_close()` → `bool`, `draw_tab.request_close()` → `bool` 순으로 묻고, 둘 다 True 면 `shutdown()` 호출 후 저장 | Convert: 변환 중 질문. Draw: 미저장 그림 질문 (5.7) |
| `show_about` 문구 | `"Bulk video converter (GIF / MP4) and frame draw-over tool."` | 버전 0.3.0 |

### 3.3 탭 공통 인터페이스 (덕 타이핑, 베이스 클래스 불필요)

두 탭 모두 다음 메서드를 가진다. `MainWindow` 는 이것만 부른다.

```python
def add_files(self) -> None            # File > Add Files…  (활성 탭으로 전달)
def add_folder(self) -> None           # File > Add Folder…
def set_view_mode(self, mode: str)     # View > List / Thumbnails ("list" | "thumbs")
def view_mode(self) -> str
def set_ffmpeg_available(self, ok: bool) -> None
def reprobe_missing(self) -> None
def menu_actions(self) -> list[QAction | None]   # 탭 메뉴에 넣을 액션. None = 구분선
def request_close(self) -> bool        # False 면 종료 취소
def shutdown(self) -> None             # 스레드 · 프로세스 정리
def restore_settings(self) -> None
def save_settings(self) -> None
def log_panel(self) -> LogPanel        # MainWindow 가 ffmpeg 버전 등 공통 로그를 남길 곳 (Draw 탭도 자기 LogPanel 을 가진다)
```

### 3.4 `VideoListModel` · 델리게이트 확장 (Draw 리스트용)

- `VideoListModel(parent=None, *, checkable: bool = True, show_status: bool = True)`.
  - `checkable=False`: `flags()` 에서 `ItemIsUserCheckable` 제외, `data(CheckStateRole)` 은 `None`, `setData` 는 `False`.
    `checked_rows()` 는 빈 리스트 — Draw 탭은 쓰지 않는다.
  - `show_status=False`: `StatusRole`/`ProgressRole`/`EstimateTextRole` 이 `None` 을 돌려준다. 툴팁에서도 상태 · 추정 줄을 뺀다.
- `VideoItemDelegate._paint_list/_paint_thumb`: `CheckStateRole` 이 `None` 이면 체크박스 영역을 그리지 않고 텍스트를 왼쪽으로 당긴다.
  `StatusRole` 이 `None` 이면 오른쪽 상태 · 추정 · 진행 바 영역을 생략한다. `_check_rect` 는 `editorEvent` 에서만 쓰므로 그대로.
- `VideoListView(parent=None, *, context_actions: str = "convert")`: `"draw"` 면 컨텍스트 메뉴에 `Reset Frame Range` 대신
  `Load Drawing…` / `Show Drawing File` 을 넣는다 (시그널 `load_drawing_requested(int)`, `show_drawing_file_requested(int)`).
  기존 `files_dropped, open_folder_requested, remove_requested` 는 공통.

---

## 4. 코어 (UI 비의존, `app/core/`)

### 4.1 `frame_decoder.py` — `FrameStream`

ffmpeg 한 프로세스가 **시작 프레임부터 순차로** RGB24 raw 프레임을 뿜고, 우리는 `w*h*3` 바이트씩 읽는다.

```python
@dataclass(frozen=True)
class DecodeSpec:
    src_w: int; src_h: int; fps: float
    out_w: int; out_h: int            # 짝수, out_w = min(src_w, DRAW_DECODE_MAX_WIDTH)
    @property
    def frame_bytes(self) -> int: return self.out_w * self.out_h * 3

def make_decode_spec(info: MediaInfo, max_width: int = C.DRAW_DECODE_MAX_WIDTH) -> DecodeSpec
    # out_w = min(src_w, max_width) 를 짝수로, out_h = resolve_dimensions(src_w, src_h, out_w, None)[1]

def seek_time(frame: int, fps: float) -> float
    # max(0.0, (frame - 0.25) / fps)   (2.2)

def build_stream_command(ffmpeg: Path, path: Path, spec: DecodeSpec, start_frame: int, hwaccel: str) -> list[str]
    # [ffmpeg, -hide_banner, -loglevel error, -nostdin,
    #  (-hwaccel auto  if hwaccel == "auto"),
    #  -ss f"{seek_time:.6f}", -i path, -an, -sn,
    #  -fps_mode passthrough,
    #  -vf f"scale={out_w}:{out_h}:flags=bilinear,format=rgb24",
    #  -f rawvideo, -]
    # 순수 함수 → tests/test_frame_decoder.py 에서 검증

class FrameStream:
    """Popen 래퍼. read_frame() 는 (frame_index, bytes) 를 돌려주고 EOF 면 None."""
    def __init__(self, ffmpeg: Path, path: Path, spec: DecodeSpec, start_frame: int, hwaccel: str) -> None
        # Popen(cmd, stdout=PIPE, stderr=PIPE, bufsize=0, creationflags=subprocess_flags())
        # self.next_index = start_frame
    def read_frame(self) -> tuple[int, bytes] | None
        # stdout 에서 frame_bytes 가 될 때까지 반복 read. 짧게 끝나면 EOF → None.
        # 반환 뒤 next_index += 1
    def close(self) -> None     # kill → wait(1s). stderr 마지막 줄을 .last_error 에 보관
    def stderr_tail(self) -> str
```

- `-hwaccel auto` 로 열었는데 첫 프레임 전에 프로세스가 죽으면(returncode ≠ 0) 호출자(`FrameProvider`)가 `hwaccel="none"` 으로 **한 번 재시도**한다. 이후 그 영상은 `none` 으로 고정 (`job_runner` 와 같은 정책).
- `-fps_mode` 는 ffmpeg 5.1+. `deps.json` 이 받는 빌드(release-essentials, 7.x) 는 지원. 구 버전이면 `-vsync 0` 으로 폴백할 수 있게
  `build_stream_command(..., legacy_vsync: bool = False)` 인자를 둔다. 폴백 조건: stderr 에 `Unrecognized option 'fps_mode'`.

### 4.2 `drawing.py` — 데이터 모델 · 고스트 계산 · JSON

```python
@dataclass
class Stroke:
    color: str                 # "#rrggbb"
    width: float               # 소스 픽셀
    points: list[tuple[float, float]]   # 소스 픽셀 좌표, 길이 ≥ 1 (1 이면 점)
    opacity: float = 1.0       # 예비. 이번 UI 는 항상 1.0

@dataclass
class DrawingDocument:
    video_name: str
    video_path: str            # 저장 시점의 절대 경로 (슬래시). 로드 때는 참고용
    width: int; height: int; fps: float; frame_count: int
    frames: dict[int, list[Stroke]] = field(default_factory=dict)
    # ---- 편집 ----
    def add_stroke(self, frame: int, stroke: Stroke) -> None      # redo 스택 비움, dirty=True
    def undo(self, frame: int) -> bool                            # 그 프레임의 마지막 스트로크 → redo 스택
    def redo(self, frame: int) -> bool
    def clear_frame(self, frame: int) -> int                      # 지운 개수. undo 가능하도록 통째로 undo 스택에 넣는다
    def strokes_at(self, frame: int) -> list[Stroke]
    def frames_with_strokes(self) -> list[int]                    # 정렬. 타임라인 마커용
    def is_empty(self) -> bool
    dirty: bool                                                   # 저장 뒤 False
    # ---- 직렬화 ----
    def to_json(self) -> str
    @classmethod
    def from_json(cls, text: str) -> "DrawingDocument"            # 버전 검사. 틀리면 DrawingFormatError
    def rescaled(self, width: int, height: int) -> "DrawingDocument"   # 다른 해상도 영상에 입힐 때 점 · 두께를 비율로 변환

def ghost_alpha(distance: int, span: int, opacity: float) -> float
    # distance ≥ 1, span ≥ distance. opacity * (1 - (distance - 1) / span)   (7장)

def ghost_frames(frame: int, before: int, after: int, last_frame: int) -> list[tuple[int, int]]
    # [(frame_index, distance), …] — frame 자신은 제외, 0 ≤ idx ≤ last_frame

def sidecar_path(video: Path) -> Path
    # video.with_name(video.name + C.DRAW_FILE_SUFFIX)  → "clip.mp4.draw.json"
    # (확장자 교체가 아니라 덧붙임: clip.mp4 와 clip.mov 가 같은 폴더에 있어도 충돌하지 않는다)
```

Undo 스택 구조: `_undo: dict[int, list[list[Stroke]]]`, `_redo: dict[int, list[list[Stroke]]]` — 항목 하나가 "한 번의 편집으로 추가된 스트로크 묶음".
`add_stroke` 는 `[stroke]` 하나를, `clear_frame` 은 지운 전체 리스트를 넣는다. undo 는 그 묶음을 `frames[frame]` 에서 제거하고 redo 로 옮긴다
(clear 의 undo 는 묶음을 다시 붙인다). 영상을 바꾸면 문서 자체가 바뀌므로 스택도 함께 사라진다.

### 4.3 `constants.py` 추가 상수

```python
# Draw 탭
DRAW_DECODE_MAX_WIDTH = 1280      # 디코드 폭 상한 (px). 소스가 더 작으면 소스 폭
DRAW_CACHE_BUDGET_MB = 512        # 프레임 캐시 메모리 상한
DRAW_PREFETCH_FORWARD = 24        # 시크 뒤 앞으로 미리 디코드할 프레임 수
DRAW_PREFETCH_BACKWARD = 12       # 뒤로 갈 때 이만큼 앞에서 시작해 디코드
DRAW_PLAY_AHEAD = 48              # 재생 중 디코더가 표시 프레임보다 앞서 가도 되는 최대 프레임 수
DRAW_SCRUB_PX_PER_FRAME = 8       # 드래그 스크럽 감도
DRAW_SCRUB_PX_MIN, DRAW_SCRUB_PX_MAX = 2, 40
DRAW_WIDTH_DEFAULT = 4.0          # 브러시 두께 (소스 px)
DRAW_WIDTH_MIN, DRAW_WIDTH_MAX = 1.0, 64.0
DRAW_COLOR_DEFAULT = "#e8734a"
DRAW_SWATCHES = ("#e8734a", "#ffffff", "#000000", "#e05555", "#e0b955", "#6cc070", "#4aa3e8", "#c06ce0")
DRAW_MIN_POINT_DIST_PX = 1.5      # 화면 px. 이보다 가까운 점은 버린다
GHOST_BEFORE_DEFAULT = 2
GHOST_AFTER_DEFAULT = 2
GHOST_SPAN_MAX = 30
GHOST_OPACITY_DEFAULT = 0.35      # 0.05 ~ 1.0
DRAW_FILE_SUFFIX = ".draw.json"
DRAW_FORMAT_NAME = "jun-video-tool-drawing"
DRAW_FORMAT_VERSION = 1
```

`Colors` 에 `GHOST_BEFORE = "#e05555"`, `GHOST_AFTER = "#4aa3e8"` 를 넣어 두지만 **이번 구현은 고스트에 원래 선 색을 쓴다**
(틴트 옵션은 10장). 상수만 예약.

---

## 5. UI (`app/ui/draw_tab.py`, `app/ui/widgets/draw/`)

### 5.1 `DrawTab` 레이아웃 (기본 1280×760 안에서)

```
┌ Draw 툴바 ───────────────────────────────────────────────────────────────────────────────────────┐
│ [Add Files] [Add Folder] [Remove] [Clear] │ View: (● List ○ Thumbs) │ Tool: (○ Scrub ● Draw) │ [Save] [Save As…] [Load…] │
├───────────────────────────┬──────────────────────────────────────────────────┬────────────────────┤
│ VideoListView (단일 선택)  │ VideoCanvas                                       │ ┌ Brush ─────────┐ │
│  clip_a.mp4  1920x1080 …  │   ┌────────────────────────────────────────────┐   │ │ Color [■][■][■]│ │
│  clip_b.mov  …            │   │                                            │   │ │  [■][■][■][■][■]│ │
│                           │   │          (fit, 레터박스, 검정 배경)          │   │ │  [ Custom… ]   │ │
│                           │   │                                            │   │ │ Width ──●── 4  │ │
│                           │   └────────────────────────────────────────────┘   │ └────────────────┘ │
│                           │                                                  │ ┌ Ghosting ──────┐ │
│                           │                                                  │ │ ☑ Enable        │ │
│                           │                                                  │ │ Before [ 2 ]    │ │
│                           │                                                  │ │ After  [ 2 ]    │ │
│                           │                                                  │ │ Opacity ──●─ 35%│ │
│                           │                                                  │ └────────────────┘ │
│                           │                                                  │ ┌ Scrub ─────────┐ │
│                           │                                                  │ │ Sensitivity [8]│ │
│                           │                                                  │ │  px / frame     │ │
│                           │                                                  │ └────────────────┘ │
│                           │                                                  │ [Undo] [Redo]      │
│                           │                                                  │ [Clear Frame]      │
├───────────────────────────┴──────────────────────────────────────────────────┴────────────────────┤
│ [|◀] [◀] [▶/❚❚] [▶|] [▶|]  ●━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  Frame [  12 ] / 359  00:00:00:12 │
│       (타임라인 아래 그림 있는 프레임에 코랄 점 마커)                                                                   │
│ Log: [12:01:03] clip_a.mp4 — 1920x1080, 29.97 fps, 360 frames. Decoding at 1280x720.                                   │
│      [12:01:05] Loaded drawing: clip_a.mp4.draw.json (14 frames, 37 strokes)                                           │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- 좌 : 중 : 우 = `QSplitter` 수평 `[list | canvas | side]`, 초기 `[260, 760, 260]`, 설정 키 `draw/splitter_h`.
  side 는 `QScrollArea` 안의 `QVBoxLayout` (Convert 와 동일 패턴), 최소 폭 230.
- 위 : 아래 = `QSplitter` 수직 `[상단 | 트랜스포트+로그]`, 초기 `[600, 140]`, 키 `draw/splitter_v`. 트랜스포트 바는 로그와 같은 하단 위젯에 고정 높이로.
- 트랜스포트 아이콘은 SVG 추가: `first_frame prev_frame play pause next_frame last_frame brush scrub undo redo clear_frame save save_as`
  (PLAN.md 6.14 규격: 24 viewBox, stroke `#e6e6e6` 1.8 px). `dev/build_icons.py` 의 시트 출력에도 포함.

### 5.2 `VideoCanvas(QWidget)` — `widgets/draw/video_canvas.py`

```python
class VideoCanvas(QWidget):
    stroke_finished = Signal(object)        # Stroke (소스 픽셀 좌표)
    scrub_started = Signal()
    scrub_delta = Signal(int)               # 누적 프레임 오프셋 (시작 프레임 기준)
    scrub_finished = Signal()
    draw_pressed_while_playing = Signal()   # 컨트롤러가 pause() 한다

    def set_frame(self, index: int, image: QImage | None) -> None   # None = "로딩 중" (이전 그림 유지 + 희미하게)
    def set_source_size(self, w: int, h: int) -> None               # 좌표 변환 기준. 영상 바뀔 때
    def set_document(self, doc: DrawingDocument | None) -> None
    def set_ghost(self, enabled: bool, before: int, after: int, opacity: float) -> None
    def set_tool(self, tool: str) -> None                           # "scrub" | "draw"
    def set_brush(self, color: str, width: float) -> None
    def set_scrub_sensitivity(self, px_per_frame: int) -> None
    def video_rect(self) -> QRectF                                  # 테스트 · 디버그용
```

**페인트 순서** (`paintEvent`, `Antialiasing | SmoothPixmapTransform`):
1. 배경 `#1a1a1a` 전체.
2. `video_rect` = 소스 비율로 위젯 안에 fit(가운데). 이미지가 있으면 `drawImage(video_rect, image)`. 없으면 사각형만 `#000`.
3. 고스트: `ghost_frames(cur, before, after, last)` 각각에 대해 `painter.setOpacity(ghost_alpha(d, span, opacity))` 후 스트로크 그리기.
   `span` 은 그 방향의 값(before 쪽은 `before`, after 쪽은 `after`).
4. 현재 프레임 스트로크 (opacity 1).
5. 진행 중 스트로크(`_live_points`, 화면 좌표 그대로).
6. 로딩 중이면 우하단 작은 텍스트 `Loading…` (`Colors.TEXT_DIM`).

**스트로크 그리기**: `QPen(QColor(color), width * scale, SolidLine, RoundCap, RoundJoin)`, `scale = video_rect.height() / src_h`.
점 1개면 `drawPoint` 대신 길이 0 의 `drawLine(p, p)` (RoundCap 으로 원이 된다). 점 2개 이상은 `QPainterPath` `moveTo/lineTo` 로 한 번에.

**좌표 변환**: `to_video(QPointF) -> (x, y)` = `((px - r.x()) / r.width() * src_w, (py - r.y()) / r.height() * src_h)`,
결과를 `[0, src_w] × [0, src_h]` 로 클램프. `to_screen` 은 역변환.

**마우스**:
- `mousePressEvent` 좌버튼:
  - 재생 중 → `draw_pressed_while_playing.emit()` (컨트롤러가 정지) 후 아래로 계속.
  - tool == "draw" → 스트로크 시작. `_live_points = [pos]`.
  - tool == "scrub" → 스크럽 시작 (`_scrub_x0 = pos.x()`, `scrub_started.emit()`).
- `mousePressEvent` **가운데 버튼** → 모드 무관 스크럽 시작.
- `mouseMoveEvent`: 드로잉 중이면 마지막 점과 거리 ≥ `DRAW_MIN_POINT_DIST_PX` 일 때만 추가 후 `update()`.
  스크럽 중이면 `delta = int((x - x0) / px_per_frame)`; 이전 delta 와 다를 때만 `scrub_delta.emit(delta)`.
- `mouseReleaseEvent`: 드로잉 → `Stroke(color, width, [to_video(p) …])` 만들어 `stroke_finished.emit`, `_live_points` 비움.
  스크럽 → `scrub_finished.emit()`.
- `enterEvent` → `setFocus()` (마우스를 올리면 키가 캔버스로 감. `setFocusPolicy(StrongFocus)`). 커서: draw = `CrossCursor`, scrub = `SizeHorCursor`.
- 영상이 없거나 이미지가 없으면 모든 입력 무시.

### 5.3 `FrameProvider(QThread)` — `widgets/draw/frame_provider.py`

디코더 스레드 + LRU 캐시. UI 스레드는 `request_frame` / `start_stream` / `stop_stream` 만 부른다.

```python
class FrameProvider(QThread):
    frame_ready = Signal(int, int, QImage)     # video_gen, frame_index, image
    stream_ended = Signal(int)                 # video_gen (마지막 프레임까지 디코드 완료)
    decode_error = Signal(int, str)            # video_gen, message

    def set_video(self, path: Path | None, info: MediaInfo | None, hwaccel: str) -> int
        # 캐시 비움, 스트림 닫음, video_gen += 1, DecodeSpec 계산. 반환 = 새 video_gen
    def cached(self, frame: int) -> QImage | None
    def request_frame(self, frame: int) -> None
        # 캐시 있으면 즉시 frame_ready 를 emit 하고 끝.
        # 없으면 요청 큐에 Seek(frame) 를 넣는다 (이전 미처리 요청은 교체 — 최신 요청만 의미 있다)
    def start_stream(self, from_frame: int) -> None   # 재생용 연속 디코드
    def stop_stream(self) -> None                     # 재생 정지 → 현재 프레임 주변 prefetch 로 전환
    def set_display_frame(self, frame: int) -> None   # 재생 중 UI 가 표시한 프레임 (앞서가기 제한용, 원자적 int)
    def shutdown(self) -> None                        # 종료. 스레드 join(2s)
```

**워커 루프 (`run`)**:
```
while not quit:
    req = wait_for_request()                       # Condition. Seek(frame) | Stream(frame) | Stop
    gen = request_gen
    start = plan_start(req)                        # Seek: frame 이 (frame-1) 캐시됨 → frame, 아니면 max(0, frame - PREFETCH_BACKWARD)
                                                   # Stream: frame
    stream = open FrameStream(start)               # hwaccel 실패 시 none 으로 1회 재시도 (4.1)
    decoded = 0
    while request_gen == gen and not quit:
        if req is Stream and (stream.next_index - display_frame) > DRAW_PLAY_AHEAD: sleep 5ms; continue
        got = stream.read_frame()
        if got is None: emit stream_ended(video_gen) if Stream; break
        idx, data = got
        img = QImage(data, w, h, w*3, Format_RGB888).copy()    # 바이트 소유권을 QImage 로
        cache.put(idx, img)                                    # LRU, 바이트 예산 초과 시 가장 오래된 것 pop
        emit frame_ready(video_gen, idx, img)
        decoded += 1
        if req is Seek and idx >= req.frame + DRAW_PREFETCH_FORWARD: break
        if req is Seek and all frames req.frame..req.frame+FORWARD cached: break
    stream.close()
```
- 캐시: `OrderedDict[int, QImage]`, 바이트 합계를 추적. 예산 `DRAW_CACHE_BUDGET_MB * 2**20`. `frame_bytes` 로 수용 프레임 수를 로그에 남긴다
  (`Cache holds about 180 frames at 1280x720.`).
- `request_gen` 은 `request_frame/start_stream/stop_stream` 마다 +1 → 진행 중 디코드가 즉시 끊기고 최신 요청으로 넘어간다. 스크럽처럼
  초당 수십 번 요청이 와도 프로세스는 최신 목표 하나만 좇는다.
- 재생 중 요청된 `Seek` (타임라인 클릭) 은 `Stream` 을 끊고 `Seek` 로 간다. 컨트롤러가 재생 상태면 뒤이어 `start_stream(frame)` 을 다시 부른다.
- 프로세스 생성 비용(약 50~100 ms) 때문에 `Seek` 는 항상 `FORWARD` 만큼 더 읽어 둔다 — `→` 연타가 즉시 반응하는 이유.

### 5.4 `PlaybackController(QObject)` — `widgets/draw/playback_controller.py`

프레임 번호 · 재생 상태 · 타이머의 단일 진실.

```python
class PlaybackController(QObject):
    frame_changed = Signal(int)            # 표시할 프레임 번호가 바뀜 (이미지 준비 여부와 무관)
    image_ready = Signal(int, QImage)      # 현재 프레임의 이미지가 도착
    playing_changed = Signal(bool)
    video_changed = Signal(object)         # VideoItem | None

    def set_video(self, item: VideoItem | None, hwaccel: str) -> None   # 정지 → provider.set_video → frame 0 요청
    def play(self), pause(self), toggle(self)
    def seek(self, frame: int) -> None     # clamp [0, last]. 같은 프레임이면 무시
    def step(self, delta: int) -> None
    def first(self), last(self)
    def frame(self) -> int ; def is_playing(self) -> bool ; def last_frame(self) -> int
```

- **재생 클럭**: `QTimer` 간격 `max(1, round(1000 / fps))`, `QElapsedTimer` 로 시작 시각 기준 `target = start_frame + floor(elapsed * fps)`.
  tick 마다 `target` 이 캐시에 있으면 표시하고 `provider.set_display_frame`; 없으면 **클럭을 멈추고 기다린다**(`_waiting = True`,
  `frame_ready` 가 target 을 가져오면 `elapsed` 기준점을 다시 잡아 재개). 프레임을 건너뛰지 않으므로 그림 · 고스트가 매 프레임 보인다.
  마지막 프레임에 도달하면 `pause()` (루프 없음. 토글 옵션은 10장).
- `seek` 중 재생이면 `provider.start_stream(frame)` 으로 스트림을 다시 건다.
- `frame_ready(gen, idx, img)` 수신: `gen` 이 현재 영상이 아니면 버림. `idx == frame` 이면 `image_ready.emit`.
- `set_video(None)` 은 캔버스를 비우고 트랜스포트를 비활성한다.

### 5.5 `TransportBar(QWidget)` — `widgets/draw/transport_bar.py`

- 버튼 `first / prev / play-pause(토글, 아이콘 교체) / next / last`, `QSlider(Horizontal)` 0..last, `QSpinBox` 프레임, 라벨 `/ 359`, 타임코드 라벨(`format_timecode`).
- 슬라이더 `sliderPressed` → 재생 중이었으면 기억하고 `pause`; `sliderMoved(v)` → `controller.seek(v)`; `sliderReleased` → 기억했으면 `play`.
- 스핀박스 `editingFinished` → `seek`. `controller.frame_changed` → 슬라이더 · 스핀 · 타임코드 갱신 (`_updating` 가드).
- **마커**: `QSlider` 를 상속한 `_MarkerSlider` 가 `paintEvent` 뒤에 `frames_with_strokes()` 위치마다 아래쪽에 3 px 코랄 점을 찍는다.
  `set_markers(list[int])`. 그루브 좌표는 `QStyle.sliderPositionFromValue`.

### 5.6 사이드 패널 — `widgets/draw/brush_panel.py`, `ghost_panel.py`

- `BrushPanel(QGroupBox "Brush")`: 스와치 8개(`QToolButton`, 체크 가능, 배경색 = 스와치, 선택은 2 px 흰 테두리), `Custom…`(`QColorDialog`, 결과를
  첫 스와치 자리에 임시 반영하지 않고 현재 색으로만), `Width` `QSlider`(1~64) + 숫자 라벨. 시그널 `brush_changed(str color, float width)`.
  설정 키 `draw/color`, `draw/width`.
- `GhostPanel(QGroupBox "Ghosting")`: `Enable` 체크, `Before`/`After` `QSpinBox`(0~30), `Opacity` 슬라이더(5~100 %). 시그널
  `ghost_changed(bool, int, int, float)`. 설정 키 `draw/ghost_enabled`, `draw/ghost_before`, `draw/ghost_after`, `draw/ghost_opacity`.
- `Scrub` 그룹은 `DrawTab` 안에서 직접 만든다 (`QSpinBox` 2~40, 키 `draw/scrub_px`).
- `Undo` `Redo` `Clear Frame` 버튼은 `DrawTab` 의 액션에 연결 (아래).

### 5.7 `DrawTab` 흐름

```
Add Files / Add Folder / Drop ─▶ model.add_paths ─▶ rows_added ─▶ ProbeLoader.request (Convert 와 동일 코드, 썸네일도 동일)
List currentChanged ─▶ _select_video(row)
    ├▶ 현재 문서 dirty ─▶ autosave 켜져 있으면 저장, 아니면 QMessageBox.question Save / Discard / Cancel  (Cancel 이면 선택 되돌림)
    ├▶ controller.set_video(item, settings.hwaccel) ; canvas.set_source_size(info.w, info.h)
    ├▶ sidecar_path(item.path) 가 있으면 DrawingDocument.from_json → 해상도 다르면 rescaled() + 로그 경고 ─▶ canvas.set_document
    │   없으면 빈 DrawingDocument(video 정보로) ─▶ canvas.set_document
    └▶ transport.set_range(last_frame) ; transport.set_markers(doc.frames_with_strokes()) ; log "<name> — WxH, fps, N frames. Decoding at WxH."
item.info 가 아직 없으면(프로브 중) 선택은 받되 캔버스는 "Probing…" 표시, probe_ready 가 오면 _select_video 를 다시 탄다
controller.frame_changed(f) ─▶ canvas.set_frame(f, provider.cached(f)) ; transport 갱신
controller.image_ready(f, img) ─▶ canvas.set_frame(f, img)
canvas.stroke_finished(stroke) ─▶ doc.add_stroke(controller.frame(), stroke) ─▶ canvas.update() ; markers 갱신 ; _update_title()  (dirty '*')
canvas.scrub_started ─▶ _scrub_base = controller.frame() ; 재생 중이면 pause
canvas.scrub_delta(d) ─▶ controller.seek(_scrub_base + d)
canvas.draw_pressed_while_playing ─▶ controller.pause()
brush_panel.brush_changed ─▶ canvas.set_brush ; ghost_panel.ghost_changed ─▶ canvas.set_ghost ; scrub spin ─▶ canvas.set_scrub_sensitivity
act_undo / act_redo ─▶ doc.undo/redo(controller.frame()) ─▶ canvas.update() ; markers
act_clear_frame ─▶ doc.clear_frame(frame) ─▶ 〃 ; log "Cleared N stroke(s) on frame F."
act_save ─▶ _save_to(doc_path or sidecar_path) ; act_save_as ─▶ QFileDialog.getSaveFileName(filter "Drawing (*.draw.json)") ; act_load ─▶ getOpenFileName
    ─▶ 로드한 문서의 video_name 이 현재 영상과 다르면 question "This drawing was made for '<name>'. Load it anyway?" ; 해상도 다르면 rescaled
remove_rows / clear_list ─▶ 현재 영상이 포함되면 _select_video(-1) (dirty 처리 포함)
request_close ─▶ dirty 면 Save / Discard / Cancel ; shutdown ─▶ controller.pause() ; provider.shutdown() ; probe_loader.cancel_all()
```

- 창 제목은 `MainWindow` 가 `tab.title_suffix()` 를 모아 `"JUN Video Tool v0.3.0 — clip_a.mp4*"` 처럼 만든다 (Draw 탭 활성 시만, `*` = dirty).
- 저장 성공 로그: `Saved drawing: clip_a.mp4.draw.json (14 frames, 37 strokes)`. JSON 은 `indent=None`, `ensure_ascii=False`, UTF-8.
- `Auto-save on switch` 체크박스(툴바 끝, 키 `draw/autosave`, 기본 OFF): 켜져 있으면 영상 전환 · 종료 시 묻지 않고 사이드카에 저장.

### 5.8 `MainWindow` (얇아진 버전)

```python
class MainWindow(QMainWindow):
    def __init__(self):
        self.settings = AppSettings(); self.thumb_loader = ThumbnailLoader(self)
        self.tabs = QTabWidget(); self.tabs.setDocumentMode(True)
        self.convert_tab = ConvertTab(self.settings, self.thumb_loader)
        self.draw_tab = DrawTab(self.settings, self.thumb_loader)
        self.tabs.addTab(self.convert_tab, icon("convert"), "Convert")
        self.tabs.addTab(self.draw_tab, icon("brush"), "Draw")
        self.setCentralWidget(self.tabs)
        self._build_menus(); self._restore(); QTimer.singleShot(0, self._startup_checks)
```

메뉴:

| 메뉴 | 항목 (단축키) | 대상 |
|------|---------------|------|
| File | Add Files… (`Ctrl+O`), Add Folder… (`Ctrl+Shift+O`), ─, Exit | `current_tab().add_files()` 등 |
| Edit | Settings… | 전역 |
| View | List (`Ctrl+1`), Thumbnails (`Ctrl+2`), ─, Convert Tab (`Alt+1`), Draw Tab (`Alt+2`) | 리스트 모드는 활성 탭에 적용. 탭 전환 시 체크 상태를 활성 탭의 `view_mode()` 로 맞춘다 |
| Convert | `convert_tab.menu_actions()`: Check All (`Ctrl+A`), Uncheck All (`Ctrl+Shift+A`), Invert Check (`Ctrl+I`), ─, Remove Selected (`Del`), Clear List, ─, Refresh Estimates (`F5`) | Convert 탭이 활성일 때만 enabled |
| Draw | `draw_tab.menu_actions()`: Play/Pause (`Space`), Previous Frame (`Left`), Next Frame (`Right`), Back 10 (`Shift+Left`), Forward 10 (`Shift+Right`), First Frame (`Home`), Last Frame (`End`), ─, Scrub Tool (`S`), Draw Tool (`D`), Toggle Ghosting (`G`), ─, Undo (`Ctrl+Z`), Redo (`Ctrl+Y`), Clear Frame (`Shift+Del`), ─, Save Drawing (`Ctrl+S`), Save Drawing As… (`Ctrl+Shift+S`), Load Drawing… (`Ctrl+L`), ─, Remove Selected (`Del`), Clear List | Draw 탭이 활성일 때만 enabled |
| Help | Check Dependencies…, Show ffmpeg Info, ─, About | 전역 |

- Convert 액션은 기존처럼 `WindowShortcut` 컨텍스트 + `setEnabled` 토글로 충분하다 (`Del` 은 두 탭 모두에 있으므로 각 탭 액션에
  `WidgetWithChildrenShortcut` 을 준다 — 충돌 방지).
- Draw 액션은 전부 `WidgetWithChildrenShortcut` + `draw_tab.addAction(act)` (2.4). `Space` 가 포커스된 `QPushButton` 을 누르는 문제: 캔버스 · 리스트 ·
  슬라이더에 포커스가 있을 때만 재생 토글이 되면 충분하다. 버튼들은 `setFocusPolicy(NoFocus)` 로 둔다 (Convert 쪽은 건드리지 않는다).
- `tabs.currentChanged` → `_sync_menus()`: Convert/Draw 메뉴 enabled 토글, View 체크 동기화, 창 제목 갱신.
- 설정: `ui/geometry`, `ui/current_tab`("convert"|"draw") 만 `MainWindow` 가 저장. 나머지는 각 탭.
- `_startup_checks`: 기존 로직 → 결과를 `convert_tab.set_ffmpeg_available(ok)`, `draw_tab.set_ffmpeg_available(ok)` 에 전달.
  ffmpeg 버전 로그는 두 탭 로그 패널 모두에 남긴다.

### 5.9 `dark.qss` 추가

```css
QTabWidget::pane { border: 1px solid #444444; top: -1px; }
QTabBar::tab { background: #2b2b2b; color: #9a9a9a; padding: 6px 18px; border: 1px solid #444444; border-bottom: none; }
QTabBar::tab:selected { background: #353535; color: #e6e6e6; border-top: 2px solid #e8734a; }
QTabBar::tab:hover:!selected { color: #e6e6e6; }
#VideoCanvas { background: #1a1a1a; }
QToolButton#Swatch { border: 1px solid #444444; border-radius: 3px; min-width: 22px; min-height: 22px; }
QToolButton#Swatch:checked { border: 2px solid #ffffff; }
```

---

## 6. 드로잉 파일 포맷 (`*.draw.json`, version 1)

```json
{
  "format": "jun-video-tool-drawing",
  "version": 1,
  "video": {
    "name": "clip_a.mp4",
    "path": "C:/work/clip_a.mp4",
    "width": 1920, "height": 1080,
    "fps": 29.97, "frame_count": 360
  },
  "frames": {
    "12": [
      {"color": "#e8734a", "width": 4.0, "opacity": 1.0,
       "points": [[412.5, 388.0], [418.2, 392.6], [430.0, 401.1]]}
    ],
    "13": []
  }
}
```

- 키는 프레임 번호 문자열(JSON 객체 키 제약). 빈 리스트인 프레임은 저장하지 않는다 (`"13": []` 는 로드 시 허용하되 쓰지 않음).
- 점 좌표 · 두께는 **소스 픽셀**, 소수 2자리로 반올림해 저장. `opacity` 는 생략 가능(기본 1.0).
- `from_json` 검증: `format` 불일치 또는 `version > 1` → `DrawingFormatError("Unsupported drawing file.")`. 점이 없는 스트로크 · 색 형식 오류는 그 스트로크만 버리고 개수를 경고 로그.
- `video.path` 는 참고용. 로드 판정은 `name` 과 `width/height` 로만 한다 (5.7).

---

## 7. 핵심 계산 규칙 (테스트 대상)

| 규칙 | 식 · 예 |
|------|---------|
| 시크 시각 | `seek_time(i, fps) = max(0, (i − 0.25) / fps)`. `seek_time(0, 30) = 0.0`, `seek_time(90, 29.97) = 2.99466…` |
| 디코드 크기 | `make_decode_spec(1920×1080) → 1280×720`, `(1280×720) → 1280×720`, `(640×480) → 640×480`, `(1921×1081) → 1280×720`(짝수 보정) |
| 프레임 바이트 | `out_w * out_h * 3` → 1280×720 = 2,764,800 B. 512 MB 예산 ≈ 194 프레임 |
| 고스트 알파 | `ghost_alpha(d, N, o) = o × (1 − (d−1)/N)`. N=2, o=0.35 → d1: 0.35, d2: 0.175. N=1 → d1: o. `d > N` 는 호출하지 않는다 |
| 고스트 프레임 | `ghost_frames(10, 2, 3, 359) = [(8,2),(9,1),(11,1),(12,2),(13,3)]`; `ghost_frames(0, 2, 1, 359) = [(1,1)]`; `ghost_frames(359, 1, 5, 359) = [(358,1)]` |
| 스크럽 | `delta = int((x − x0) / px_per_frame)` → 8 px/frame, 이동 −23 px → −2 프레임 (0 방향 절삭) |
| 좌표 변환 | video_rect (100, 50, 640, 360), 소스 1920×1080: 화면 (420, 230) → 소스 (960.0, 540.0). 역변환은 동일 점 복원 |
| 리스케일 | 1920×1080 문서를 1280×720 영상에 `rescaled` → 점 ×(2/3), 두께 ×(2/3) (두께는 높이 비율) |
| 사이드카 | `sidecar_path("C:/a/clip.mp4") = "C:/a/clip.mp4.draw.json"` |
| Undo | add A, add B, undo → [A]; redo → [A,B]; add C 뒤 redo → 무효(False); clear_frame → [] , undo → [A,B,C] |

---

## 8. 구현 순서 (각 단계 끝에 앱이 뜨고 pytest 가 통과해야 한다)

| 단계 | 내용 | 완료 기준 |
|------|------|-----------|
| **P0** | `version.py` 0.3.0, `constants.py` 4.3 상수, `drawing.py`, `frame_decoder.py` (순수 부분), `tests/test_drawing.py`, `tests/test_frame_decoder.py` | 7장 규칙 전부 테스트 통과. 콘솔에서 `FrameStream` 으로 합성 영상 10 프레임을 읽어 인덱스 · 바이트 수 확인 |
| **P1** | `ConvertTab` 추출 (3.2 표), `MainWindow` 재작성 (5.8, Draw 탭은 빈 `QLabel("Draw tab — coming soon")` 자리), 메뉴 재구성, qss 탭 스타일 | 기존 변환 기능이 **동일하게** 동작. 설정(스플리터 · 포맷 · 출력 · 뷰모드)이 이전 값으로 복원된다. 기존 테스트 35+개 통과 |
| **P2** | `VideoListModel/Delegate/View` 확장 (3.4), `DrawTab` 골격: 툴바(Add/Remove/Clear/View), 리스트, 빈 캔버스, 로그 | Draw 탭에서 영상 리스트업 · 선택, `View: List / Thumbs` 전환으로 썸네일 격자 보기(D1b). 체크박스 · 상태 열은 보이지 않음 |
| **P3** | `FrameProvider`, `PlaybackController`, `VideoCanvas` 이미지 표시, `TransportBar`(마커 제외) | 선택한 영상 첫 프레임 표시, `Space` 재생/정지, `←/→/Home/End`, 슬라이더 · 스핀 이동. 29.97 fps 영상에서 `→` 30번 = 프레임 30 (타임코드 `00:00:01:00`) |
| **P4** | 스크럽(좌드래그 Scrub 모드 · 가운데 드래그), Tool 토글, 감도 스핀 | 드래그로 프레임 왕복. 재생 중 드래그하면 정지 |
| **P5** | 드로잉: `BrushPanel`, 스트로크 입력 · 렌더, `DrawingDocument` 연결, Undo/Redo/Clear Frame, 타임라인 마커 | 정지 프레임에 선. 프레임을 옮기면 그 프레임의 선만 보임. Undo 동작 |
| **P6** | `GhostPanel` + 고스트 렌더 (재생 중 포함) | Before/After/Opacity 변경이 즉시 반영. 범위 0 이면 고스트 없음 |
| **P7** | Save / Save As / Load, 사이드카 자동 로드, dirty 처리(전환 · 종료 질문, 제목 `*`), Auto-save 체크, 리스트 컨텍스트 메뉴, 해상도 리스케일 · 이름 불일치 질문 | 저장 → 앱 재시작 → 영상 선택 시 그림이 그대로 재생 위에 보임 |
| **P8** | SVG 아이콘 14개 + 시트, 설정 저장/복원(`draw/*`), hwaccel 폴백 · `-fps_mode` 폴백, 캐시 예산 로그, README · CHANGELOG, Win10 체크(12장) | v0.3.0. PLAN.md 상태 줄 갱신 ("v0.3.0 은 PLAN_DRAW_TAB.md") |

각 단계의 커밋 메시지 접두: `refactor(ui): …` (P1), `feat(draw): …` (P2~P7), `chore: …` (P8). 로컬 커밋만, 푸시는 요청 시.

---

## 9. 테스트 계획

### 9.1 유닛 (`pytest`, Qt 불필요)

- `tests/test_drawing.py`: `Stroke`/`DrawingDocument` JSON 왕복(소수 반올림 포함), 버전 거부, 깨진 스트로크 건너뛰기, `undo/redo/clear_frame` 시나리오(7장), `ghost_alpha`, `ghost_frames` 경계(0, last), `rescaled`, `sidecar_path`, `frames_with_strokes` 정렬 · 빈 프레임 제외.
- `tests/test_frame_decoder.py`: `seek_time`, `make_decode_spec` 4 케이스, `build_stream_command` 인자 순서(`-ss` 가 `-i` 앞, `-an`, `-fps_mode passthrough`, `scale=1280:720`, `-f rawvideo`, 마지막 `-`), `hwaccel="none"` 이면 `-hwaccel` 없음, `legacy_vsync=True` 면 `-vsync 0`.
- 캔버스 좌표 변환은 순수 함수 `widgets/draw/geometry.py` 의 `fit_rect(widget_w, widget_h, src_w, src_h) -> (x, y, w, h)`, `to_video`, `to_screen` 으로 빼서 Qt 없이 테스트한다.

### 9.2 통합 (수동 또는 `QT_QPA_PLATFORM=offscreen` 스크립트, `dev/check_draw.py`)

- 합성 영상(`ffmpeg -f lavfi -i testsrc=size=1280x720:rate=29.97 -frames:v 300`) 으로: 프레임 0 → `→` ×30 → 표시 프레임의 testsrc 프레임 카운터가 `30` 인지 픽셀로 읽어 확인 (testsrc 는 프레임 번호를 화면에 찍는다 — 이게 프레임 정확성의 결정적 검증).
- 1080p 실영상: `End` 이동 시간, `←` 연타 12회 반응(모두 캐시 히트여야 함), 재생 30 초 메모리(작업 관리자) ≤ 예산 + 150 MB.
- Convert 변환 중에 Draw 탭 재생이 되는지 (`QThreadPool` 4 스레드 공유 — 프로브 · 썸네일 큐가 밀려도 Draw 디코더는 전용 `QThread` 라 영향 없음).

### 9.3 Win10 체크 (PLAN.md 12.3 에 추가)

- 125 % DPI 에서 캔버스 선 두께와 스와치 테두리. `QTabBar` 글자 잘림 없음. 가운데 버튼 드래그(일부 노트북 터치패드는 가운데 버튼이 없다 → Scrub 모드가 대안이라고 README 에 적는다).

---

## 10. 리스크와 대응

| 리스크 | 대응 |
|--------|------|
| `-ss` 정확 시크가 코덕 · 컨테이너에 따라 1 프레임 어긋남 (B-프레임 많은 H.264, 오픈 GOP) | 9.2 testsrc 검증 + 실영상 2종(H.264 mp4, ProRes mov). 어긋나면 `seek_time` 여유를 `0.25 → 0.5` 로 조정하고, 그래도 안 되면 `-ss` 를 1 초 앞에 두고 `-vf select='gte(n\,K)'` 대신 **읽은 뒤 버리기**(우리가 프레임 수를 세므로 가능)로 바꾼다 |
| VFR 영상(스마트폰 녹화) 은 `avg_frame_rate` 기반 인덱스가 실제 프레임과 어긋남 | `-fps_mode passthrough` 로 받은 프레임 수가 `frame_count` 와 다르면 로그 경고 `"Variable frame rate detected; frame numbers are approximate."`. 정확 매핑은 범위 밖 |
| 디코드가 재생 속도를 못 따라감 (4K 소스, 느린 PC) | 디코드 폭 상한 1280 + 클럭 대기 방식이라 멈칫하되 프레임은 안 건너뜀. 상한을 `Settings…` 에 노출하는 건 10장 확장 |
| 메모리: 캐시 + QImage 복사 | 바이트 예산 LRU. 영상 전환 시 전부 비움. `QImage.copy()` 1회만 (파이프 버퍼 → QImage) |
| `WidgetWithChildrenShortcut` 과 `QListView` 의 `←/→` 충돌 (리스트가 `ShortcutOverride` 를 가져갈 수 있음) | P3 에서 실측. 가져가면 Draw 리스트 뷰에서 `event()` 를 오버라이드해 `ShortcutOverride` 의 `Left/Right/Space/Home/End` 를 `ignore()` 한다. 최후 수단은 `DrawTab.eventFilter` 로 포커스 위젯이 `QAbstractSpinBox/QLineEdit/QComboBox` 가 아닐 때 가로채기 |
| `Space` 가 포커스된 버튼을 누름 | Draw 탭 버튼 전부 `NoFocus` (5.8) |
| 사이드카 쓰기 권한 없음(읽기 전용 폴더 · 네트워크) | 저장 실패 시 `QMessageBox.warning` + `Save As…` 제안. 자동 로드만 되는 상태 유지 |
| 큰 JSON (수천 스트로크) 로드 지연 | `points` 반올림으로 크기 절감. 수만 점도 ms 단위라 문제 없음. 렌더는 보이는 프레임 ±N 만 |
| ffmpeg 4.x (`-fps_mode` 없음) 를 사용자가 직접 넣음 | stderr 감지 → `-vsync 0` 재시도 (4.1) |

---

## 11. 미래 확장 메모 (구조만 대비)

- 고스트 틴트(before 빨강 · after 파랑, `Colors.GHOST_*` 예약), 루프 재생 토글, 재생 속도(0.5× / 2×), 디코드 폭 설정 노출.
- 그림 burn-in 내보내기: `DrawingDocument` + `FrameStream` 으로 프레임을 받아 `QPainter` 로 합성 → 기존 `MP4Converter` 파이프에 `image2pipe` 입력. Convert 탭의 포맷으로 `MP4 (with drawing)` 을 등록하는 형태가 자연스럽다.
- 지우개(스트로크 단위 히트 테스트), 스트로크 선택 · 이동, 텍스트 주석, 레이어.
- Draw ↔ Convert 리스트 보내기(`Send to Convert` 컨텍스트 메뉴).
- 오디오: PyAV 또는 `QAudioSink` 에 ffmpeg `-f s16le` 파이프. 동기화는 재생 클럭을 오디오 시계로 바꾸는 작업.

---

## 12. 완료 정의 (v0.3.0)

1. Convert 탭에서 v0.2.0 과 똑같이 변환이 되고, 이전 설정이 복원된다.
2. Draw 탭에서 영상을 추가 · 선택 · 재생 · 정지하고, `←/→` · 드래그로 프레임 정확하게 이동한다 (testsrc 검증 통과).
3. 정지 프레임에 색 · 두께를 바꿔 선을 그리고 Undo/Redo/Clear 가 된다.
4. Ghosting 범위 · 투명도를 바꾸면 앞뒤 프레임 선이 반투명으로 겹쳐 보이고 재생 중에도 유지된다.
5. 저장한 `*.draw.json` 이 영상 선택 시 자동으로 올라오고, 다른 PC 의 같은 영상에서도 같은 자리에 그려진다.
6. `pytest -q` 전부 통과, README · CHANGELOG · `version.py` 갱신.

---

## 13. 2026-10-16 사용자 답변 · 추가 요청 (v0.3.0 범위 확장)

이 장은 앞 장보다 우선한다. 앞 장에서 이 장과 충돌하는 내용(무음 재생, Scrub 툴 모드, 지우개 · burn-in 범위 밖)은 무효다.

| # | 요청 (원문 요지) | 결정 |
|---|------------------|------|
| A1 | Draw 탭 재생 시 음성도 재생, 음량 조절 | 13.1 `AudioPlayer` — ffmpeg `s16le` 파이프 → `QAudioSink`. 트랜스포트 바에 음소거 버튼 + 음량 슬라이더 |
| A2 | 좌드래그는 그리기 전용, 스크럽은 가운데 버튼 드래그 | 13.2 — Scrub 툴 모드 삭제. 좌드래그 = 현재 툴(Draw/Erase), 가운데 드래그 = 스크럽 |
| R1 | 그린 그림을 지우는 기능 | 13.3 Erase 툴 (부분 지우개, Undo 가능) + 기존 Clear Frame + 신규 Clear All Drawings |
| R2 | 그림이 입혀진 영상을 MP4 · GIF 로 출력 | 13.4 `Export…` — 원본 + 오버레이 합성(burn-in), Convert 의 GIF/MP4 옵션 패널 재사용 |
| R3 | GIF 도 Convert 탭에 올려서 더 압축된 GIF 로 변환 | 13.5 — `.gif` 를 입력 확장자에 추가, 원본 덮어쓰기 방지 |

### 13.1 오디오 재생 (A1)

- **엔진**: `app/ui/widgets/draw/audio_player.py` `AudioPlayer(QObject)`. 별도 ffmpeg 프로세스
  `ffmpeg -hide_banner -loglevel error -nostdin -ss <t> -i <src> -vn -sn -ac 2 -ar 48000 -f s16le -` 의 stdout 을
  리더 스레드가 읽어 `deque[bytes]` 에 쌓고, UI 스레드 `QTimer`(10 ms) 가 `QAudioSink`(push 모드, `start()` 가 준 `QIODevice`)
  에 `bytesFree()` 만큼 쓴다. 포맷 48000 Hz · 2 ch · Int16 (`AUDIO_RATE`, `AUDIO_CHANNELS`). 기본 출력 장치가 없거나
  포맷 미지원이면 로그 `No audio output device; playback is silent.` 후 무음으로 동작.
- 명령 생성은 순수 함수 `app/core/frame_decoder.py::build_audio_command(ffmpeg, path, start_sec) -> list[str]` (테스트 대상).
- **동기화**: 비디오 클럭(`QElapsedTimer`)이 주인이다. 오디오는 `play` 시 현재 프레임 시각 `frame / fps` 에서 시작하고,
  `pause` · `seek`(재생 중) · 영상 변경 시 프로세스를 죽이고 버퍼를 비운다. 비디오가 디코드를 기다리는 동안(`_waiting`)
  `QAudioSink.suspend()`, 재개 시 `resume()` — 그래서 멈칫해도 소리가 앞서 나가지 않는다. 장시간 드리프트 보정은 범위 밖.
- **오디오 스트림 유무**: `MediaInfo.has_audio: bool = False` 추가. ffprobe 는 `-select_streams v:0` 를 빼고 `stream=codec_type,…`
  를 받아 첫 `video` 스트림을 고르고, `audio` 가 하나라도 있으면 `True`. stderr 폴백은 `Stream #…: Audio:` 정규식.
  `codec_type` 이 없는 옛 JSON(테스트 픽스처)은 `streams[0]` 를 비디오로 본다. `has_audio=False` 면 프로세스를 띄우지 않는다.
- **UI**: `TransportBar` 오른쪽 끝에 음소거 `QToolButton`(체크, 아이콘 `volume` / `volume_mute`) + `QSlider` 0~100(폭 90).
  설정 키 `draw/volume`(기본 80), `draw/muted`(기본 False). 음량은 `QAudioSink.setVolume(v/100)` (선형).
  스크럽 · 프레임 스텝 중에는 소리를 내지 않는다(재생 중일 때만).

### 13.2 마우스 규칙 (A2)

| 입력 | 동작 |
|------|------|
| 좌버튼 드래그 | 툴이 `draw` 면 스트로크, `erase` 면 지우기. 재생 중이면 먼저 정지 |
| 가운데 버튼 드래그 | 스크럽 (감도 `draw/scrub_px`, 2~40 px/frame). 툴과 무관 |
| 우버튼 | 아무것도 안 함 |

- 툴바 `Tool: (● Draw ○ Erase)`, 단축키 `D` / `E`. `S`(Scrub Tool) 는 없다. 설정 키 `draw/tool`.
- 사이드 패널의 `Scrub` 그룹은 남긴다(라벨 `Middle-drag sensitivity`).

### 13.3 지우기 (R1)

- **Erase 툴**: 좌드래그 경로(화면 좌표 → 소스 좌표)를 지우개 원(반지름 = `eraser_size / 2`, 소스 px) 으로 쓸어,
  스트로크의 **점 중 지우개 원 안에 드는 점(점-원 거리 ≤ r + stroke.width/2)** 을 제거하고 남은 점들을 연속 구간별로
  **새 스트로크로 분할**한다 (부분 지우기). 점이 하나도 안 남는 스트로크는 사라진다. 순수 함수
  `drawing.erase_strokes(strokes, path_points, radius) -> tuple[list[Stroke], bool]` (bool = 바뀜).
  긴 선분 위를 지우개가 지나가도 지워지도록 지우기 전에 스트로크를 `max(1, width/2)` 소스 px 간격으로 보간(densify)한다.
  드래그 중에는 화면에 즉시 반영(미리보기 = 그 프레임 리스트 사본에 적용), 릴리스 때 문서에 한 번의 편집으로 커밋.
- 지우개 크기: `BrushPanel` 아래 `Eraser` 줄 `QSlider` 4~256 (소스 px, 기본 32, 키 `draw/eraser_size`).
  Erase 툴일 때 캔버스에 지우개 원 외곽선을 마우스 위치에 그린다.
- **Undo 구조 변경**: 4.2 의 "묶음" 스택을 **프레임별 스냅숏 스택**으로 바꾼다. `_undo[frame]` / `_redo[frame]` 의
  항목은 편집 직전/직후의 그 프레임 스트로크 리스트 전체 사본. `add_stroke` · `clear_frame` · `replace_frame`(지우개) 모두
  `_push_undo(frame)` 후 변경 → add/undo/redo/clear 시나리오(7장 표)는 그대로 성립한다.
- `Clear All Drawings`(Draw 메뉴, 확인 질문 `Delete all drawings on every frame of '<name>'?`): 모든 프레임을 비운다.
  프레임별 undo 스택에 각각 스냅숏을 넣으므로 프레임마다 Undo 로 되돌릴 수 있다.

### 13.4 그림 입힌 영상 내보내기 (R2)

- **진입**: Draw 툴바 `Export…` 버튼 / Draw 메뉴 `Export with Drawing…` (`Ctrl+E`). 영상이 선택돼 있어야 한다.
- **다이얼로그** `app/ui/widgets/draw/export_dialog.py` `ExportDialog(QDialog)`:
  `Format` 콤보(GIF / MP4 (H.264) — `registry` 순서), 선택 포맷의 **Convert 옵션 패널을 그대로 생성**
  (`OptionsPanelFactory.create`, 설정 키는 Convert 와 별도로 `export/<format_id>/options_json`), `Include ghosting` 체크
  (기본 OFF, 켜면 현재 Ghosting 설정 그대로 굽는다), 출력 파일 줄(`QLineEdit` + `Browse…`, 기본값
  `<영상 폴더>/<stem>_draw.<ext>`, 존재하면 `make_output_path` 규칙으로 `_001`), 진행 바, `Export` / `Cancel` / `Close`.
  목표 용량(Target size)도 Convert 와 같은 재시도 규칙(`degrade_for_retry`)으로 지원한다.
- **파이프라인** (오버레이만 파이썬이 만든다 — 원본 디코드 · 인코딩은 ffmpeg 한 프로세스):
  ```
  ffmpeg -hide_banner -y -nostats -progress pipe:1 [-hwaccel auto] -i <src>
         -f rawvideo -pix_fmt rgba -s <W>x<H> -framerate <fps> -i -
         -filter_complex "[0:v]scale=W:H:flags=lanczos,setpts=N/(<fps>)/TB[base];
                          [1:v]setpts=N/(<fps>)/TB[ov];[base][ov]overlay=0:0:eof_action=pass:format=auto<tail>"
  ```
  - `W×H` = 변환기의 `output_dimensions(item, options)` (MP4 는 짝수). 오버레이는 **출력 크기로 직접 그린다**
    (스케일 = `H / src_h`) — 소스 해상도 RGBA 를 보내는 것보다 파이프 데이터가 작다.
  - 두 입력 모두 `setpts=N/fps/TB` 로 정규화해 "N 번째 디코드 프레임 = Draw 탭 프레임 N" 을 맞춘다 (2.2 의 프레임 인덱스 규칙과 동일).
  - GIF `<tail>` = `,fps=F,split[a][b];[a]palettegen=…[p];[b][p]paletteuse=dither=…` + `-loop n`.
  - MP4 `<tail>` = `[,fps=F]` → `[v]` 후 `-map [v] -map 0:a? -c:v libx264 -crf … -preset … -pix_fmt yuv420p -movflags +faststart`
    + 오디오(`aac` / `copy` / `-an`, Convert 와 동일).
  - 구간(Frame range)은 없다 — 항상 전체 길이. `-ss/-t` 를 쓰지 않는다.
  - 명령 생성은 순수 함수 `app/core/burnin.py::build_burnin_command(ffmpeg, item, converter, options, out_path) -> list[str]`
    (hwaccel 은 `options.hwaccel`, 테스트 대상). 파이썬 쪽 워커 `app/ui/widgets/draw/export_worker.py` `ExportWorker(QThread)`:
    프레임 0..frame_count-1 마다 투명 `QImage(W, H, Format_RGBA8888)` 에 `paint_strokes`(캔버스와 같은 함수,
    `widgets/draw/stroke_painter.py`) 로 현재 프레임 + (옵션) 고스트를 그려 stdin 에 쓴다. 그림이 없는 프레임은 미리 만든
    투명 바이트를 재사용. stdout(`-progress`) 은 별도 스레드가 읽어 `out_time_us` → 진행률, stderr 는 꼬리 40 줄 보관.
    시그널 `progress(int)`, `log(str)`, `finished_ok(object path, int size, float elapsed)`, `failed(str)`. 취소 시 프로세스 kill + 출력 파일 삭제.
  - `-hwaccel auto` 로 실패(종료 코드 ≠ 0 이고 stderr 에 하드웨어 표지)하면 `none` 으로 1회 재시도 (`job_runner` 와 같은 표지 목록).
- 로그: `Exported: clip_a_draw.mp4 (3.2 MB, 12.4 s)`. 문서가 비어 있으면 질문 `This video has no drawings. Export anyway?`.

### 13.5 GIF 입력 (R3)

- `SUPPORTED_EXTENSIONS` 에 `.gif` 추가 → Convert · Draw 두 탭 모두 GIF 를 받는다. ffprobe 는 GIF 의 `avg_frame_rate` ·
  `nb_frames` · `duration` 을 정상 보고한다 (2026-10-16 실측: 320x240 10 fps 2 s → `10/1`, `20`, `2.000000`).
- 파일 대화상자 필터 이름을 `Media files (…)` 로 바꾼다.
- **원본 덮어쓰기 방지**: GIF → GIF 를 같은 폴더 · 빈 접미사로 내보내면 출력 경로가 원본과 같아진다. `make_output_path` 는
  후보가 **원본 자신과 같은 경로**(`normcase_path` 비교)면 `overwrite` 여부와 무관하게 `_001…` 번호를 붙인다. (테스트 추가)
- GIF 의 가변 프레임 지연은 `avg_frame_rate` CFR 로 간주한다 (10장 VFR 리스크와 동일).
- 압축용 기존 옵션(품질 → 색 수 · 디더, fps, 폭, 목표 용량)이 그대로 GIF 입력에 적용된다. 추가 옵션은 두지 않는다.

### 13.6 상수 · 아이콘 · 설정 추가

```python
# constants.py
SUPPORTED_EXTENSIONS 에 ".gif" 추가
AUDIO_RATE = 48000
AUDIO_CHANNELS = 2
AUDIO_PUSH_INTERVAL_MS = 10
DRAW_VOLUME_DEFAULT = 80
DRAW_ERASER_DEFAULT = 32.0
DRAW_ERASER_MIN, DRAW_ERASER_MAX = 4.0, 256.0
EXPORT_SUFFIX = "_draw"
```
- 아이콘 추가(5.1 목록에서 `scrub` 제거): `eraser volume volume_mute export`.
- 설정 키 추가: `draw/tool`, `draw/volume`, `draw/muted`, `draw/eraser_size`, `export/format`, `export/include_ghost`,
  `export/<format_id>/options_json`.

### 13.7 구현 순서 조정

8장 P0~P8 순서를 유지하되: P4 = 가운데 드래그 스크럽 + Draw/Erase 툴 토글, P5 에 지우개 · Clear All 포함,
**P6b** = 오디오(13.1), **P7b** = Export(13.4), **P1** 에 GIF 입력(13.5) 포함. 테스트 추가:
`test_drawing.py`(지우개 분할 · 스냅숏 undo), `test_frame_decoder.py`(`build_audio_command`), `test_burnin.py`(GIF/MP4 명령),
`test_utils.py`(원본 경로 회피), `test_probe_parser.py`(`has_audio`, `codec_type` 선택).

### 13.8 완료 정의 추가

7. Draw 탭 재생 시 소리가 나고, 음량 · 음소거가 동작한다. 정지 · 시크 시 소리가 멈추거나 새 위치에서 다시 시작한다.
8. 좌드래그는 그리기/지우기만, 가운데 드래그는 스크럽만 한다.
9. Erase 툴로 선 일부를 지우고 Undo 로 되돌린다.
10. `Export…` 로 그림이 입혀진 MP4 · GIF 가 나오고, 그림이 Draw 탭에서 본 프레임과 같은 프레임에 있다 (testsrc 픽셀 검증).
11. Convert 탭에 GIF 를 넣어 더 작은 GIF 로 변환되며, 원본 GIF 는 덮어써지지 않는다.
