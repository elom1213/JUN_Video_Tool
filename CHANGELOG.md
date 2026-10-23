# Changelog

## 0.4.7 — 2026-10-23

- **Draw 탭이 영상별 보기 상태를 기억한다**: 다른 영상으로 바꾸면 떠나는 영상의 **정지 프레임 · 타임라인 확대 구간 · 캐시 구간 ·
  캔버스 보기 배율 과 위치**를 적어 두고, 그 영상을 다시 고르면 그 상태 그대로 열린다 (전에는 늘 0 프레임 · 전체 타임라인으로 돌아갔다).
  재생 중에 바꾸면 그 순간의 프레임에서 정지한 채로 이어 본다. 처음 여는 영상은 전처럼 0 프레임 · 전체 구간.
  - 로그에 `Resumed where you left off: frame 123, timeline 50-70, cache range 10-200, view 156%.` 한 줄 (기본값인 항목은 생략).
  - 리스트에서 지우거나 `Clear List` 하면 잊는다. 세션 안에서만 기억하고 설정 파일에는 쓰지 않는다.
  - 영상 길이가 EOF 로 짧게 밝혀진 뒤에도 구간은 잘라서 맞춘다 (`normalize_zoom` · `normalize_cache_range`).
- `DrawTab._ViewState` · `_remember_view` · `_restore_view`, `VideoCanvas.set_view`. `dev/check_draw.py` [15]. PLAN_DRAW_TAB 20.

## 0.4.6 — 2026-10-22

- **Draw 탭 캔버스 보기 확대 · 이동**: 영상 위에서 **마우스 휠**을 굴리면 커서 아래 자리를 고정한 채 1.25 배씩 확대 · 축소된다
  (25 % ~ 1600 %, 맞춤 = 100 %). **우버튼 드래그**로 보이는 위치를 옮긴다. 영상이 캔버스보다 크면 가장자리 안쪽에 빈 공간이
  생기지 않는 범위까지만, 작으면 가운데에 고정이라 영상을 화면 밖으로 잃어버릴 수 없다. **우버튼 더블클릭** 또는
  `Draw > Reset View Zoom`(`F`) 으로 맞춤으로 되돌린다. 확대 중엔 캔버스 오른쪽 위에 배율(`250%`, 반전과 함께면 `Flipped H · 250%`).
  - 보기만 바뀐다: 확대 상태에서 그려도 선은 원본 픽셀 좌표로 들어가고, 저장 파일 · 내보내기 · 고스트 · 지우개 · 툴 크기 원이 모두 같이 따라온다.
  - 그리는 중 · 스크럽 중에는 휠을 무시한다. 해상도를 바꿔 다시 열어도 남고, 다른 크기의 영상을 열거나 영상을 비우면 맞춤으로.
- `geometry.view_rect` · `clamp_pan` · `zoom_about` · `zoom_label`, `VideoCanvas.set_view_zoom` · `set_view_pan` · `reset_view` · `view_changed`,
  상수 `DRAW_VIEW_ZOOM_STEP` · `DRAW_VIEW_ZOOM_MIN/MAX`. `tests/test_draw_geometry.py` 5개, `dev/check_draw.py` [14].

## 0.4.5 — 2026-10-22

- **`Get Zoom` 버튼** (`Resolution & Cache` 패널 `Range` 행, `All` 옆): 누르면 지금 타임라인에 펼쳐진 확대 구간
  (`Timeline Zoom` 의 `Show` 시작 · 끝) 이 캐시 구간의 시작 · 끝에 들어간다. `Zoom to Cache Range` 의 반대 방향.
  스핀박스 · 타임라인 핸들 · 버튼 문구(`Cache Range`)가 같이 바뀐다.
- `CachePanel.get_zoom_clicked`, `DrawTab.cache_range_from_zoom`. `dev/check_draw.py` [13].

## 0.4.4 — 2026-10-22

- **타임라인 확대를 끌어서 설정** (마야 Range Slider 꼴): 타임라인 바로 아래에 영상 전체를 나타내는 띠가 생기고, 그 위의 주황 창이
  타임라인에 펼쳐진 구간이다. 창의 양 끝 그립을 끌면 크기가, 창 가운데를 끌면 폭을 유지한 채 위치가 바뀌고, 더블클릭하면 전체로 돌아간다.
  재생 위치는 작은 눈금으로 보인다. `Timeline Zoom` 패널의 숫자 · 타임라인 양 끝 숫자가 끄는 동안 같이 바뀐다 (반대도 같다).
  창은 최소 두 프레임, 영상 밖으로는 못 나간다. 위 타임라인과 같은 여백을 써서 두 줄의 프레임 자리가 일치한다.
- `_RangeSlider`(`transport_bar.py`), `TransportBar.zoom_changed` · `zoom_reset_requested`. `dev/check_draw.py` [13] 에 그립 · 이동 · 더블클릭.

## 0.4.3 — 2026-10-22

- **Draw 탭 타임라인 확대**: 타임라인 양 끝을 영상의 처음 · 끝이 아니라 원하는 프레임 `[lo, hi]` 로 둘 수 있다
  (1000 프레임 영상에서 50 ~ 70 만 타임라인 전체에 펼쳐 보기).
  - 사이드 패널 `Timeline Zoom`: `Show` 시작 · 끝 프레임 스핀박스(정수), `Zoom to Cache Range`, `Reset`.
    시작을 끝까지 올리면 끝이 한 칸 따라가고 반대도 같다 (최소 두 프레임).
  - `Draw > Zoom Timeline to Cache Range`(`Z`) · `Reset Timeline Zoom`(`Shift+Z`).
  - 타임라인 양 옆에 끝 프레임 번호가 보이고, 확대 중이면 주황색. 그림 마커 · 캐시 녹색 줄 · 캐시 구간 핸들은 보이는 범위만 그린다
    (범위 밖 캐시 핸들은 그리지도 잡히지도 않는다 — 가장자리에 붙이면 자리가 거짓이 된다).
  - 확대는 보기만 바꾼다: 재생 · 프레임 이동 · `Home` / `End` 는 영상 전체 기준 그대로이고, 재생 위치가 범위 밖이면
    핸들은 가장자리에 붙고 프레임 칸 · 타임코드는 실제 프레임을 보여 준다. 해상도를 바꿔도 남고, 영상을 새로 열면 전체로.
- `geometry.normalize_zoom`, `widgets/draw/zoom_panel.py`, `TransportBar.set_zoom`. `tests/test_draw_geometry.py` 1개, `dev/check_draw.py` [13].

## 0.4.2 — 2026-10-22

- **Draw 탭 캐시 구간**: 영상 전체가 아니라 원하는 프레임 구간만 메모리에 올릴 수 있다.
  - 타임라인 위쪽 띠에 주황 구간 띠와 양 끝 삼각 핸들. 핸들을 끌면 시작 · 끝 프레임이 바뀐다 (재생 위치는 움직이지 않는다).
    시작은 끝을, 끝은 시작을 넘지 못한다.
  - `Resolution & Cache` 패널 `Range` 행의 시작 · 끝 스핀박스(정수 입력) + `All`(전체 구간). 시작을 끝 너머로 올리면 끝이 따라오고 반대도 같다.
  - 두 UI 는 항상 같은 값이다: 핸들을 끌면 스핀박스가, 스핀박스를 고치면 핸들이 따라 움직인다 (`DrawTab.set_cache_range` 한 곳으로 모은다).
  - 구간 아래에 프레임 수 · 필요 메모리. 버튼 · 메뉴는 구간이 전체면 `Cache Whole Video`, 아니면 `Cache Range`.
    패널의 캐시 현황(`This range: k of n frames cached`)과 `Needs` 도 구간 기준. 메모리가 모자라면 구간 안에서 현재 프레임 주변만.
  - 영상을 열면 전체 구간으로 되돌아간다.
- `memory_info.normalize_cache_range` · `plan_cache_window`, `FrameProvider.pinned_in`. `tests/test_memory_info.py` 3개, `dev/check_draw.py` [12].

## 0.4.1 — 2026-10-22

- **Draw 탭 보기 반전**: 툴바 `Flip H` / `Flip V` 버튼, `Draw > Flip Horizontal`(`H`) · `Flip Vertical`(`V`).
  둘 다 켜면 상하좌우 모두 반전. 영상과 그 위의 선이 함께 거울상으로 보이고, 반전 상태에서 그은 선도 마우스 자리에 그려진다.
  **보기 전용**이다 — 문서의 스트로크 좌표 · `.draw.json` · `Export…` 결과는 원본 방향 그대로 (좌표 변환에서만 축을 되돌린다).
  캔버스 오른쪽 위에 `Flipped H` / `Flipped V` / `Flipped H+V` 표시. 설정에 저장된다 (`draw/flip_h`, `draw/flip_v`).
- `geometry.to_video` / `to_screen` 에 `flip_h` · `flip_v`, `flip_label`. `tests/test_draw_geometry.py` 4개, `dev/check_draw.py` [11].

## 0.4.0 — 2026-10-20

- **WAV 출력 (JUN_JALI 용)**: Convert 탭 `Output format` 에 `WAV (JUN_JALI 44.1 kHz 16-bit mono)` 추가.
  영상 · 음성 파일의 첫 오디오 스트림을 44100 Hz · 16-bit PCM · 모노 wav (메타데이터 없는 44 바이트 헤더) 로 뽑는다 —
  JUN_JALI VisemeNet Converter 의 입력 규격(`wav_check.py`)이며 마야 sound 노드도 그대로 읽는다.
  채널: 평균 섞기(기본) / 왼쪽 / 오른쪽. 구간은 리샘플 뒤 샘플 수로 정확히 자른다. 용량은 정확히 계산된다.
- **변환 뒤 JUN_JALI 규칙 검사** (`app/core/jali_wav.py`, 표준 라이브러리만): E03 샘플레이트 · E04 형식 · E05 채널 ·
  E06 너무 짧음 · E07 너무 김 · E08 무음 · W01 스테레오 · W02 클리핑. 통과하면 `JUN_JALI ready`, E06 · E08 은 실패로 표시.
  JUN_JALI 실제 `check_wav()` 로도 검증 (`dev/check_wav.py --jali-python`).
- **음성 파일 입력**: Convert 탭이 mp3 · m4a · aac · flac · ogg · oga · opus · wma · aif · aiff · ac3 · amr · caf · mka · 3gp · wav 를 받는다.
  probe 가 비디오 없는 파일을 음성 전용(`MediaInfo.audio_only`, 1 프레임 = 1 ms)으로 읽고, mp3 · m4a 의 앨범 아트
  (`attached_pic`)는 영상으로 치지 않는다. 리스트에 `Audio <코덱> · 48 kHz stereo …`, 썸네일 자리에 스피커 아이콘,
  `Frame Range` 는 ms 단위. GIF · MP4 는 음성 파일을, WAV 는 소리 없는 영상을 건너뛴다 (`BaseConverter.skip_reason`).
  Draw 탭은 영상만 받는다.
- **출력 이름 충돌 수정**: 같은 배치에서 출력 이름이 겹치면(`voice.m4a` · `voice.ogg` → `voice_wav.wav`) 서로 덮어쓰던 문제.
  배치 안의 다른 원본도 덮어쓰지 않는다 (`make_output_path(..., taken)`). GIF · MP4 에도 적용된다.
- `BaseConverter`: `needs_video` · `needs_audio` · `skip_reason()` · `heuristic_level()` · `post_check()`.
- `dev/check_wav.py`, `tests/test_wav_converter.py`.

## 0.3.3 — 2026-10-19

- **Draw 탭 디코드 해상도 선택**: `Resolution & Cache` 패널에서 원본 / 75 / 50 / 25 % (기본 원본, 설정에 저장).
  기존 1280 px 폭 상한을 없앴다. 항목마다 디코드 크기, 아래에 프레임당 MB 를 보여 준다. 바꾸면 같은 프레임에서 다시 열고,
  이전 해상도의 전체 캐시는 확인 후 해제한다. 그림 좌표는 원본 픽셀이라 영향이 없다.
- **고해상도 디코드 경로 개선** (4K 원본도 실시간 재생):
  - 디코더 stdout 을 1 MB 버퍼 파이프로 (Windows 기본 4 KB): 4K 파이프 읽기 20 → 84 fps.
  - 파이프에서 QImage 메모리로 바로 읽는다 (프레임당 `bytes` · `QImage.copy` 두 번의 복사 제거).
  - LRU 가 재생 창(표시 프레임 ~ 앞서 가는 범위)을 밀어내지 않게 했다. 4K 원본은 LRU 에 86 장만 들어가서
    곧 보여줄 프레임이 지워지고 재생이 그 자리에서 멈추던 문제 (17 fps → 29.8 fps).
    재생 중 앞서 가는 양도 캐시 용량의 1/3 이하로 맞추고, 그래도 놓치면 그 자리에서 스트림을 다시 건다.
  - 시크 prefetch 가 목표에 닿으면 ffmpeg 를 닫지 않고 세워 둔다. 앞으로 넘기면 그대로 이어 읽으므로
    키프레임부터 다시 디코드하지 않는다 (1080p +1 스텝 멈춤 2/60 → 0/60).
- `make_decode_spec(info, scale)` · `decode_size` · `normalize_scale`. `DRAW_DECODE_MAX_WIDTH` 제거.
- `dev/check_draw.py` [10] 해상도 검증.

## 0.3.2 — 2026-10-19

- **Cache Whole Video / Free All** (Draw 탭 `Frame Cache` 패널 · `Draw` 메뉴): 지금 영상의 모든 프레임을 메모리에 올려
  프레임 이동 대기를 없앤다. 별도 스레드 · 별도 ffmpeg 가 채우므로 그 동안에도 이동 · 그리기가 된다 (다시 누르면 멈춤).
  캐시는 영상별로 남고(영상 전환 후 돌아와도 그대로), `Free All` 이 모든 영상의 캐시를 해제한다 (메모리가 OS 로 돌아가는 것 확인).
  예산 = 남은 물리 메모리 - `max(4 GB, RAM x 15 %)`. 다 안 들어가면 현재 프레임 주변 창만 채우고,
  채우는 중 남은 메모리가 여유분 아래로 떨어지면 멈춘다. 캐시된 구간은 타임라인 위 녹색 줄.
- **프레임 이동이 잠깐 멈추던 문제 완화**:
  - `FrameStream.read_frame` 을 `readinto` 로 바꿨다. 기존 `read(n)` 은 파이프가 몇 KB 씩 줄 때마다 2.7 MB 버퍼를 새로 잡아
    파이프 읽기가 61 fps 에 묶여 있었다 → 320 fps (1080p 소스, 1280x720 디코드). 시크 · 재생 · 전체 캐시 모두 빨라진다.
  - 한 프레임씩 넘길 때 돌고 있는 prefetch 를 끊고 ffmpeg 를 다시 띄우던 것을, 곧 닿을 자리면 끊지 않고 목표만 늘리게 했다.
    (1080p, 키프레임 간격 250 기준 +1 스텝 멈춤 36/60 → 2/60)
  - 뒤로 갈 때 prefetch 12 → 48 프레임 (어차피 키프레임부터 디코드하므로 비용은 거의 같고 멈춤 횟수는 1/4).
  - LRU 캐시 512 MB → 2 GB.
- `dev/check_draw.py` [9] 프레임 캐시 검증, `tests/test_memory_info.py`.

## 0.3.1 — 2026-10-16

- **시작 메뉴 · 작업표시줄 아이콘** (`File` 메뉴, Windows): `Add to Start Menu` 는 시작 메뉴 바로가기(pythonw + launch.py,
  앱 아이콘, AppUserModelID)를 만들고 시작 화면 고정을 요청한다. `Pin to Taskbar` 는 고정 동사가 있는 환경에선 바로 고정하고,
  없으면(Windows 10 1809+ / 11) 작업표시줄 버튼 우클릭 → 고정을 안내한다. 이미 고정돼 있으면 알려 준다.
  창에 Relaunch 속성을 넣어 두므로 작업표시줄에서 고정한 버튼이 python.exe 가 아니라 이 툴을 실행한다.

- **창 전체 드래그&드롭**: 리스트뿐 아니라 캔버스 · 옵션 패널 · 로그 등 창 어디에 놓아도 현재 탭에 추가된다.
  끌고 가는 중에 탭 제목 위에 올리면 그 탭으로 전환되므로 원하는 탭에 바로 넣을 수 있다. 폴더는 안의 미디어 파일로 펼친다.

- **드로잉 파일 위치 변경**: `<영상 폴더>/.draw/<영상이름>.draw.json` 에 저장한다 (영상 옆에 파일이 늘어나지 않게).
  폴더는 첫 저장 때 만든다. 0.3.0 위치(영상 바로 옆)의 파일도 자동으로 읽고, 다음 저장부터 `.draw` 폴더로 옮겨 쓴다.
- **그린 프레임으로 스냅**: 트랜스포트 바의 두 버튼과 `Ctrl+←` / `Ctrl+→` 로 그림이 있는 이전 · 다음 프레임으로 이동한다
  (`Draw > Previous / Next Drawn Frame`). 더 갈 곳이 없으면 버튼이 꺼진다.
- **툴 크기 원 커서**: 영상 위에서 마우스 위치에 브러시 두께 · 지우개 지름만 한 원을 그린다 (화면 배율 반영, 중심점 포함).
  영상 위에서는 시스템 커서를 숨기고 이 원이 커서 역할을 한다.

## 0.3.0 — 2026-10-16

- **탭 분리**: 기존 변환 기능 전부를 `Convert` 탭으로 옮겼다. 동작 · 단축키 · 설정은 그대로이며 이전 설정이 복원된다.
  `File` · `View` 메뉴는 활성 탭에 적용되고, 탭 전용 메뉴(`Convert` / `Draw`)는 그 탭이 활성일 때만 켜진다.
  썸네일 캐시는 두 탭이 공유한다. 설계는 `docs/PLAN_DRAW_TAB.md`.
- **Draw 탭 신설** — 프레임 단위 드로오버 리뷰:
  - ffmpeg rawvideo 파이프 디코더 + 512 MB LRU 캐시. 프레임 정확 시크(순차 디코드와 비트 단위 일치 검증),
    `←/→` · `Shift+←/→` · `Home/End`, 가운데 버튼 드래그 스크럽, 프레임을 건너뛰지 않는 재생.
  - 오디오 재생(QtMultimedia, 음량 · 음소거). 디코드를 기다리는 동안 소리도 멈춘다.
  - 좌드래그 그리기(색 스와치 8 + Custom, 두께 1~64 소스 px), 부분 지우개, 프레임별 Undo/Redo, Clear Frame / Clear All.
  - Ghosting: 앞뒤 0~30 프레임, 투명도 5~100 %, 거리에 따라 옅어짐. 재생 중 유지.
  - 영상 옆 사이드카 `<영상이름>.draw.json` 저장 · 자동 로드, Save As / Load, 해상도가 다르면 비율 변환, 미저장 확인 · Auto-save.
  - `Export…`: 그림(옵션: 고스트 포함)을 입힌 MP4 / GIF 내보내기. Convert 의 옵션 패널 · 목표 용량 재시도 · hwaccel 폴백 재사용.
- **GIF 입력**: Convert · Draw 두 탭 모두 `.gif` 를 받는다. GIF → GIF 재압축 시 출력 경로가 원본과 같으면 `_001` 을 붙여 덮어쓰지 않는다.
- `MediaInfo.has_audio` (ffprobe `codec_type` · ffmpeg stderr).
- `dev/check_draw.py`: Draw 탭 오프스크린 통합 검증 (시크 정확성 · 키 이동 · 재생 · 스크럽 · 그리기/지우개 · 저장/로드 · 내보내기 프레임 위치).
- 아이콘 16개 추가 (트랜스포트 · 브러시 · 지우개 · 저장 · 음량 · 내보내기).

## 0.2.1 — 2026-10-16

- **Python 3.14 지원**: 지원 범위를 3.11 ~ 3.14 로 확장 (`deps.json` `max_exclusive` 3.15). PySide6 는 6.10.1 부터 3.14 를
  지원하며 기존 `PySide6>=6.8,<7` 그대로 3.14 에서는 6.12.0 이 설치된다. 설계 · 검증 절차는 `docs/PLAN_PY314.md`.
- Python 버전 판정을 `dependency_check.python_status()` 로 통합. 앱 안 `Check Dependencies…` 와 `bootstrap.py` 가 같은
  `deps.json` 값을 본다 (이전에는 앱 쪽에 3.14 미만이 하드코딩돼 있었다).
- free-threaded 빌드(3.13t / 3.14t) 는 PySide6 휠이 없으므로 `Unsupported` 로 표시하고 표준 빌드 설치를 안내한다.
- 지원 범위 밖 Python 안내 문구에 설치할 버전 범위(`3.11-3.14`)를 직접 적는다.

## 0.2.0 — 2026-10-14

- **MP4 (H.264) 출력 추가**: 크기(종횡비 락) · 품질(CRF 매핑) · FPS(원본 유지 / Custom) · x264 preset ·
  오디오(AAC 재인코딩 / 원본 복사 / 제거) · 목표 용량 재시도 · 구간 자르기. `Output format` 콤보에서 선택.
- GIF 와 MP4 가 공유하는 옵션(크기 · 품질 · FPS · 목표 용량 · 하드웨어 디코드)을 `VideoOptions` /
  `CommonOptionsPanel` 로 공통화. 새 포맷은 변환기 1개 + 패널 1개만 추가하면 된다.
- 포맷별 옵션을 각각 기억하고, 포맷을 바꿔도 이전 값이 보존된다 (`<format>/options_json`).
- UI: `Lock` 버튼을 Height 오른쪽으로 이동. Width/Height 는 입력을 마친 뒤(Enter · 포커스 이동)에만
  반대 축을 계산한다 (한 글자마다 바뀌지 않음).
- UI: 체크박스 · 라디오 버튼의 체크 상태를 주황색으로 채워 표시 (리스트의 체크박스 포함).
- 변환 뒤 옵션 · 포맷 · 구간을 바꾸면 이전 결과 표시를 지우고 새 예상 용량을 보여 준다.
- 수정: MP4 샘플 용량 추정이 임시 파일 확장자 때문에 실패하던 문제.

## 0.1.0 — 2026-10-14

첫 릴리스.

- 영상 파일 리스트업 (파일/폴더 추가, 드래그&드롭), 항목별 체크박스, Check All / Uncheck All / Invert
- 리스트 보기 ↔ 썸네일 보기
- GIF 변환: 폭·높이(종횡비 락), 품질(압축률), FPS(Auto / Source / Custom), 루프, 목표 용량(MB) 재시도
- 항목별 프레임 구간 편집 (듀얼 슬라이더 + 스핀박스 + 시작/끝 미리보기), 체크 항목 일괄 적용
- 변환 전 예상 출력 파일 용량 (휴리스틱 → 샘플 인코딩), 체크 항목 합계
- 병렬 ffmpeg 실행, GPU 디코드 자동 폴백, 취소, 항목별 진행률
- `setup.bat` 한 번으로 PySide6 + ffmpeg 설치 (`bootstrap.py`), 앱 내 `Help > Check Dependencies…`
- Windows 10 / 11 지원
- 앱 아이콘(`app.ico`/`app.png`, `dev/build_icons.py` 로 생성) 과 SVG 툴바 · 버튼 아이콘 세트
