# JUN_Video_Tool

영상 파일(mp4 · mov · gif 등)을 여러 개 골라 **GIF 또는 MP4(H.264) 로 벌크 변환**하고(`Convert` 탭),
영상을 프레임 단위로 넘기며 **그 위에 선을 그려 리뷰**하는(`Draw` 탭) Windows 데스크톱 툴.
PySide6 + ffmpeg. Windows 10 (21H2+) / 11.

- 설계 문서: [`docs/PLAN.md`](docs/PLAN.md) (v0.1 ~ v0.2), [`docs/PLAN_DRAW_TAB.md`](docs/PLAN_DRAW_TAB.md) (v0.3 탭 분리 · Draw 탭)
- 변경 이력: [`CHANGELOG.md`](CHANGELOG.md)

## 설치 (3단계)

1. **Python 3.11 ~ 3.14** (64-bit, 표준 빌드) 를 설치한다 (python.org, "Add to PATH" 체크). free-threaded(3.14t) 빌드는 지원하지 않는다.
2. **`setup.bat`** 을 더블클릭한다. PySide6 를 pip 로 설치하고, ffmpeg/ffprobe 를 `bin/` 에 내려받아 검증한다 (약 90 MB).
3. **`run.bat`** 을 더블클릭해 실행한다.

앱 안에서도 `Help > Check Dependencies…` 로 상태를 보고 누락분을 설치할 수 있다.

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

1. `Add Files` / `Add Folder` 또는 리스트에 파일을 드래그&드롭.
2. 변환할 항목을 체크 (`Check All` / `Uncheck All` / `Invert`).
3. `Output format` 에서 GIF 또는 MP4 를 고르고 옵션 조절: 크기(종횡비 `Lock`/`Free`), `Quality`, `FPS`, `Target size`.
   GIF 는 `Loop`, MP4 는 x264 `Preset` 과 `Audio`(AAC / 원본 복사 / 제거) 가 추가된다.
4. 항목을 선택해 `Frame Range` 에서 구간을 프레임 단위로 조절. `Apply to Checked` 로 일괄 적용.
5. 리스트의 `Est. file size` 와 `Estimated total` 로 예상 용량 확인 (`~` 대략, `≈` 샘플 기반).
6. `Convert Checked`.

`Edit > Settings…` 에서 병렬 변환 수, 하드웨어 디코드, 샘플 추정 on/off 를 바꿀 수 있다.
GIF 도 입력으로 받으므로, 큰 GIF 를 넣어 품질 · 크기 · 목표 용량을 낮춰 더 작은 GIF 로 다시 만들 수 있다
(같은 폴더 · 빈 접미사여도 원본은 덮어쓰지 않고 `_001` 을 붙인다).

## 사용 — Draw 탭

1. `Add Files` / `Add Folder` / 드래그&드롭으로 영상을 넣고 리스트에서 하나를 고른다 (`List` / `Thumbnails` 보기).
2. 프레임 이동: `Space` 재생/정지, `←` `→` 한 프레임, `Shift+←/→` 10 프레임, `Home` / `End`, 타임라인 · 프레임 칸.
   `Ctrl+←` / `Ctrl+→` (또는 트랜스포트 바의 스냅 버튼) = 그림이 있는 이전 · 다음 프레임으로 이동.
   캔버스 위 **가운데 버튼 드래그** = 좌우 스크럽 (감도 `Middle-drag sensitivity`).
3. **좌버튼 드래그** = 현재 툴로 그리기(`D`) 또는 지우기(`E`, 선의 닿은 부분만 지움). 재생 중에 누르면 먼저 멈춘다.
   색 · 두께 · 지우개 크기는 오른쪽 `Brush` 패널이며, 영상 위 마우스 위치에 그 크기의 원이 보인다. `Ctrl+Z` / `Ctrl+Y`, `Clear Frame`(`Shift+Del`), `Draw > Clear All Drawings`.
4. `Ghosting`: 앞(`Before`) · 뒤(`After`) 프레임의 선을 반투명으로 겹쳐 본다 (`G` 로 켜고 끄기). 재생 중에도 보인다.
5. `Save`(`Ctrl+S`) 는 영상 폴더 안 `.draw` 폴더에 `<영상이름>.draw.json` 을 쓴다. 다음에 그 영상을 고르면 자동으로 불러온다.
   (0.3.0 처럼 영상 바로 옆에 있는 파일도 읽는다.)
   `Save As…` / `Load…`(`Ctrl+L`) 로 다른 파일도 쓸 수 있다. `Auto-save on switch` 를 켜면 영상 전환 · 종료 시 묻지 않고 저장한다.
6. `Export…`(`Ctrl+E`): 그림을 입힌 MP4 / GIF 를 만든다. 옵션은 Convert 탭과 같고 설정은 따로 기억한다.
   `Include ghosting` 을 켜면 현재 고스트 설정까지 굽는다.
7. 재생 시 소리도 나온다. 트랜스포트 바 오른쪽에서 음소거 · 음량 조절.

노트북 터치패드처럼 가운데 버튼이 없으면 타임라인 드래그나 `←` `→` 로 이동한다.
프레임 번호는 `avg_frame_rate` 기준이라 가변 프레임률(VFR) 영상(스마트폰 녹화 등)은 근사치일 수 있다.

## 개발

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python dev/check_draw.py        # Draw 탭 통합 검증 (오프스크린, 합성 영상)
python launch.py
```

구조는 `app/core`(UI 비의존 로직) 와 `app/ui`(PySide6) 로 나뉜다. 새 출력 포맷은
`app/core/converters/` 에 `BaseConverter` 구현을 추가하고 `app/ui/widgets/` 에 옵션 패널을 등록하면 된다 (`docs/PLAN.md` 5.5).
