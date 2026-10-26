# JUN_Video_Tool

영상 파일(mp4 · mov · gif 등)을 여러 개 골라 **GIF 또는 MP4(H.264) 로 벌크 변환**하고, 영상 · 음성 파일의 소리를
**JUN_JALI 용 WAV** 로 뽑고(`Convert` 탭),
영상을 프레임 단위로 넘기며 **그 위에 선을 그려 리뷰**하는(`Draw` 탭) Windows 데스크톱 툴.
PySide6 + ffmpeg. Windows 10 (21H2+) / 11.

- 설계 문서: [`docs/PLAN.md`](docs/PLAN.md) (v0.1 ~ v0.2), [`docs/PLAN_DRAW_TAB.md`](docs/PLAN_DRAW_TAB.md) (v0.3 탭 분리 · Draw 탭)
- 변경 이력: [`CHANGELOG.md`](CHANGELOG.md)

## 설치 (3단계)

1. **Python 3.11 ~ 3.14** (64-bit, 표준 빌드) 를 설치한다 (python.org, "Add to PATH" 체크). free-threaded(3.14t) 빌드는 지원하지 않는다.
2. **`setup.bat`** 을 더블클릭한다. PySide6 를 pip 로 설치하고, ffmpeg/ffprobe 를 `bin/` 에 내려받아 검증한다 (약 90 MB).
3. **`run.bat`** 을 더블클릭해 실행한다.

앱 안에서도 `Help > Check Dependencies…` 로 상태를 보고 누락분을 설치할 수 있다.

### 시작 메뉴 · 작업표시줄 아이콘

- `File > Add to Start Menu`: 시작 메뉴(모든 앱 · 검색)에 `JUN Video Tool` 바로가기를 만들고 시작 화면 고정을 요청한다.
  콘솔 창 없이(`pythonw.exe`) 실행되며 앱 아이콘을 쓴다. 툴 폴더를 옮겼으면 다시 누르면 경로가 갱신된다.
- `File > Pin to Taskbar`: 바로가기를 만든 뒤 작업표시줄 고정을 시도한다. **Windows 10 (1809+) / 11 은 프로그램이 스스로
  작업표시줄에 고정하는 것을 막아 두었으므로**, 그때는 안내에 따라 실행 중인 툴의 작업표시줄 버튼을 우클릭 → `작업 표시줄에 고정`
  한 번만 누르면 된다. 툴이 창에 실행 정보를 넣어 두므로 고정된 버튼은 python 이 아니라 이 툴을 바로 실행한다.

### 오프라인 · 프록시 환경

```
python bootstrap.py --ffmpeg-zip C:\path\to\ffmpeg-release-essentials.zip
python bootstrap.py --pip-index-url https://<mirror>/simple
python bootstrap.py --check          # 상태만 확인
python bootstrap.py --venv           # .venv 에 격리 설치 (run.bat 이 자동 인식)
```

여러 Python 이 설치돼 있으면 `setup.bat` 은 가장 최신 3.x 를 쓴다. 특정 버전을 쓰려면 `py -3.11 bootstrap.py` 처럼 직접 실행하거나
`set PY_PYTHON=3.11` 을 둔다.

ffmpeg 를 직접 구했다면 `ffmpeg.exe` 와 `ffprobe.exe` 를 `bin/` 에 넣기만 해도 된다.
백신이 `bin\ffmpeg.exe` 를 격리하면 그 폴더를 예외로 추가한다. 관리자 권한으로 실행하면 탐색기 드래그&드롭이 막히므로 일반 권한으로 실행한다.

## 사용 — Convert 탭

1. `Add Files` / `Add Folder` 또는 파일 · 폴더를 창에 드래그&드롭 (어디에 놓든 현재 탭에 추가된다.
   끌고 가는 중에 탭 제목 `Convert` / `Draw` 위에 올리면 그 탭으로 바뀐다).
2. 변환할 항목을 체크 (`Check All` / `Uncheck All` / `Invert`).
3. `Output format` 에서 GIF 또는 MP4 를 고르고 옵션 조절: 크기(종횡비 `Lock`/`Free`), `Quality`, `FPS`, `Target size`.
   GIF 는 `Loop`, MP4 는 x264 `Preset` 과 `Audio`(AAC / 원본 복사 / 제거) 가 추가된다.
4. 항목을 선택해 `Frame Range` 에서 구간을 프레임 단위로 조절. `Apply to Checked` 로 일괄 적용.
5. 리스트의 `Est. file size` 와 `Estimated total` 로 예상 용량 확인 (`~` 대략, `≈` 샘플 기반).
6. `Convert Checked`.

`Edit > Settings…` 에서 병렬 변환 수, 하드웨어 디코드, 샘플 추정 on/off, 이미지 시퀀스 fps 를 바꿀 수 있다.
GIF 도 입력으로 받으므로, 큰 GIF 를 넣어 품질 · 크기 · 목표 용량을 낮춰 더 작은 GIF 로 다시 만들 수 있다
(같은 폴더 · 빈 접미사여도 원본은 덮어쓰지 않고 `_001` 을 붙인다).

### WAV (JUN_JALI 립싱크용)

`Output format` 을 **`WAV (JUN_JALI 44.1 kHz 16-bit mono)`** 로 고르면 영상(mp4 · mov …)과 음성 파일
(mp3 · m4a · aac · flac · ogg · opus · wma · aiff · 규격 밖 wav 등)의 소리를 **JUN_JALI(VisemeNet Converter) 가
그대로 받는 wav** 로 만든다. 그 wav 를 JUN_JALI 에 넣어 변환하면 마야(A00540 JALI LipSync)에서 쓸 수 있다.

- 출력 규격은 고정: **44100 Hz · 16-bit PCM · 모노**, 메타데이터 청크 없는 44 바이트 헤더. JUN_JALI 는 리샘플을 하지
  않아서 48 kHz · float 등 다른 규격은 에러 없이 틀린 립싱크가 나온다 — 이 포맷이 그걸 맞춰 준다.
- `Channels`: 모델은 한 채널만 쓰므로 모노로 만든다. 기본 `Mix all channels`(평균, 클리핑 없음).
  한쪽 채널에만 목소리가 녹음됐으면 `Left` / `Right channel only`.
- `Max length`: JUN_JALI 의 Max length (기본 120 초). 넘으면 시작 전에 경고하고 결과에 `E07` 을 표시한다 —
  `Frame Range` 로 잘라 여러 번 변환하거나 JUN_JALI 쪽 값을 늘린다. 0.5 초보다 짧으면 JUN_JALI 가 거부한다.
- 음성 파일의 `Frame Range` 는 **밀리초 단위**다 (구간은 샘플 수까지 정확히 자른다).
- `Check the output against JUN_JALI rules`(기본 켬): 변환이 끝난 wav 를 JUN_JALI 와 같은 규칙(E03 ~ E08 · W01 ~ W02)
  으로 다시 읽어, 통과하면 로그에 `JUN_JALI ready (44100 Hz · int16 · 1 ch · …)`, 무음(`E08`) · 너무 짧음(`E06`) 은
  실패로 표시한다 (파일은 남는다).
- 소리가 없는 영상은 건너뛰고, GIF · MP4 포맷에서는 음성 파일을 건너뛴다. Draw 탭은 영상만 받는다.
- 이름이 겹치는 원본(`voice.mp3` · `voice.ogg`)은 `voice_wav.wav` · `voice_wav_001.wav` 로 따로 쓴다.

### 이미지 시퀀스 (img.001.jpg, img.002.jpg …)

번호가 이어지는 이미지 파일(jpg · png · tif · tga · exr · dpx · bmp · webp)은 **영상 한 개**로 들어간다 — 두 탭 모두.
프레임을 전부 끌어놓든 한 장만 놓든 폴더째 놓든 리스트에는 `img.[001-120].jpg` 한 줄이 생기고,
GIF · MP4 변환 · 구간 자르기 · Draw 탭 재생 · 그리기 · 내보내기가 일반 영상과 똑같이 된다.

- 이미지에는 fps 가 없으므로 `Edit > Settings… > Image sequence FPS` (기본 24) 로 시간축을 만든다.
  바꾼 값은 그 뒤에 넣는 시퀀스부터 적용된다 (이미 리스트에 있는 건 지우고 다시 넣는다).
- 번호가 비는 곳에서 시퀀스가 나뉜다 (1-50, 52-100 → 두 항목). ffmpeg 가 첫 빈 번호에서 멈추는 것과 같은 규칙.
- 출력 이름은 번호를 뗀 이름 (`img.001.jpg` → `img_gif.gif`). 오디오는 없다 (WAV 변환은 건너뛴다).

## 사용 — Draw 탭

1. `Add Files` / `Add Folder` / 드래그&드롭(캔버스 위에 놓아도 된다)으로 영상을 넣고 리스트에서 하나를 고른다 (`List` / `Thumbnails` 보기).
   다른 영상으로 바꾸면 보던 **프레임 · 타임라인 확대 · 캐시 구간 · 보기 배율**을 영상별로 기억해 두고, 다시 고르면 거기서 이어 본다
   (리스트에서 지우거나 툴을 끄면 잊는다).
2. 프레임 이동: `Space` 재생/정지, `←` `→` 한 프레임, `Shift+←/→` 10 프레임, `Home` / `End`, 타임라인 · 프레임 칸.
   `Ctrl+←` / `Ctrl+→` (또는 트랜스포트 바의 스냅 버튼) = 그림이 있는 이전 · 다음 프레임으로 이동.
   캔버스 위 **가운데 버튼 드래그** = 좌우 스크럽 (감도 `Middle-drag sensitivity`).
   **마우스 휠** = 커서 자리를 고정한 채 영상 보기 확대 · 축소 (25 % ~ 1600 %), **우버튼 드래그** = 보이는 위치 이동,
   **우버튼 더블클릭** 또는 `F`(`Draw > Reset View Zoom`) = 맞춤으로. 보기만 바뀌며 그림 · 저장 · 내보내기는 원본 픽셀 그대로다
   (확대 중엔 캔버스 구석에 `250%` 표시). 영상이 캔버스보다 크면 빈 공간이 생기지 않는 범위까지만 움직인다.
3. **좌버튼 드래그** = 현재 툴로 그리기(`D`) 또는 지우기(`E`, 선의 닿은 부분만 지움). 재생 중에 누르면 먼저 멈춘다.
   색 · 두께 · 지우개 크기는 오른쪽 `Brush` 패널이며, 영상 위 마우스 위치에 그 크기의 원이 보인다. `Ctrl+Z` / `Ctrl+Y`, `Clear Frame`(`Shift+Del`), `Draw > Clear All Drawings`.
4. `Ghosting`: 앞(`Before`) · 뒤(`After`) 프레임의 선을 반투명으로 겹쳐 본다 (`G` 로 켜고 끄기). 재생 중에도 보인다.
   **보기 반전**: 툴바 `Flip H` / `Flip V` (또는 `Draw > Flip Horizontal` `H` · `Flip Vertical` `V`, 둘 다 켜면 상하좌우).
   영상과 선이 거울상으로 보이고 그 상태에서 그려도 된다. 보기만 바뀌며 저장 파일 · 내보내기는 원본 방향이다 (캔버스 구석에 `Flipped H` 표시).
5. `Save`(`Ctrl+S`) 는 영상 폴더 안 `.draw` 폴더에 `<영상이름>.draw.json` 을 쓴다. 다음에 그 영상을 고르면 자동으로 불러온다.
   (0.3.0 처럼 영상 바로 옆에 있는 파일도 읽는다.)
   `Save As…` / `Load…`(`Ctrl+L`) 로 다른 파일도 쓸 수 있다. `Auto-save on switch` 를 켜면 영상 전환 · 종료 시 묻지 않고 저장한다.
6. `Export…`(`Ctrl+E`): 그림을 입힌 MP4 / GIF 를 만든다. 옵션은 Convert 탭과 같고 설정은 따로 기억한다.
   `Include ghosting` 을 켜면 현재 고스트 설정까지 굽는다.
7. 재생 시 소리도 나온다. 트랜스포트 바 오른쪽에서 음소거 · 음량 조절.
8. `Resolution & Cache` 패널의 `Resolution`: 디코드 해상도를 원본(`Original`) / 75 % / 50 % / 25 % 중에서 고른다
   (기본 원본, 설정에 기억). 그림은 항상 원본 픽셀 좌표라 해상도를 바꿔도 그대로다. 바꾸면 같은 프레임에서 다시 열고,
   전체 캐시가 있으면 새 해상도에서 못 쓰므로 물어본 뒤 해제한다.
   프레임당 메모리: 1080p 원본 5.9 MB · 4K 원본 23.7 MB · 4K 75 % 13.3 MB · 4K 50 % 5.9 MB.
9. `Cache Whole Video` / `Free All` (`Draw > Cache Whole Video` / `Free All Frame Cache`):
   `Cache Whole Video` 는 지금 영상의 모든 프레임을 메모리에 올려, 어느 방향으로 얼마나 넘겨도 기다림이 없게 한다
   (30 fps 1분 = 1080p 원본 약 10.4 GB, 4K 원본 약 42 GB). 다 올라간 구간은 타임라인 위 녹색 줄로 보인다.
   채우는 동안에도 이동 · 그리기가 되고, 다시 누르면 멈춘다. 캐시는 영상을 바꿔도 남으므로 여러 영상을 번갈아 볼 수 있고,
   `Free All` 은 모든 영상의 캐시 메모리를 한 번에 해제한다.
   남은 물리 메모리에서 여유분 `max(4 GB, 전체 RAM의 15 %)` 을 뺀 만큼만 쓰며, 영상 전체가 안 들어가면 현재 프레임 주변만 채운다.
   **캐시 구간**: 타임라인 위쪽의 주황 띠 양 끝 삼각 핸들을 끌거나, 패널 `Range` 의 시작 · 끝 프레임 칸에 숫자를 넣으면
   그 구간만 캐시한다 (둘은 항상 같은 값을 보여 준다, `All` = 전체, `Get Zoom` = 지금 타임라인에 펼쳐진 확대 구간).
   구간이 전체가 아니면 버튼이 `Cache Range` 로 바뀐다.
10. 타임라인 확대: 타임라인 **바로 아래의 띠**가 영상 전체이고 그 위의 주황 창이 타임라인에 펼쳐진 구간이다 (마야 Range Slider 와 같다).
    창의 양 끝을 끌면 크기, 가운데를 끌면 이동, 더블클릭하면 전체. 같은 값을 `Timeline Zoom` 패널의 `Show` 시작 · 끝 칸에 숫자로
    넣어도 된다 (예: 50 ~ 70) — 둘은 항상 같이 움직인다. `Zoom to Cache Range`(`Z`) 는 캐시 구간으로, `Reset`(`Shift+Z`) 은 영상 전체로.
    타임라인 양 옆의 숫자가 지금 끝 프레임이며 확대 중엔 주황색이다. 재생 · 프레임 이동은 영향받지 않는다 (범위 밖으로 가면 핸들만 가장자리에 붙는다).
   채우는 중에 다른 프로그램이 메모리를 써서 여유분 아래로 내려가면 거기서 멈춘다.

노트북 터치패드처럼 가운데 버튼이 없으면 타임라인 드래그나 `←` `→` 로 이동한다.
프레임 번호는 `avg_frame_rate` 기준이라 가변 프레임률(VFR) 영상(스마트폰 녹화 등)은 근사치일 수 있다.

## 개발

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python dev/check_draw.py        # Draw 탭 통합 검증 (오프스크린, 합성 영상)
python dev/check_wav.py         # WAV(JUN_JALI) 변환 통합 검증 (--jali-python <numpy·scipy 있는 python> 로 JUN_JALI 실제 검사)
python launch.py
```

구조는 `app/core`(UI 비의존 로직) 와 `app/ui`(PySide6) 로 나뉜다. 새 출력 포맷은
`app/core/converters/` 에 `BaseConverter` 구현을 추가하고 `app/ui/widgets/` 에 옵션 패널을 등록하면 된다 (`docs/PLAN.md` 5.5).
