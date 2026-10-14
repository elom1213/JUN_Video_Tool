# JUN_Video_Tool

영상 파일(mp4 · mov 등)을 여러 개 골라 **GIF 또는 MP4(H.264) 로 벌크 변환**하는 Windows 데스크톱 툴.
PySide6 + ffmpeg. Windows 10 (21H2+) / 11.

- 설계 문서: [`docs/PLAN.md`](docs/PLAN.md)
- 변경 이력: [`CHANGELOG.md`](CHANGELOG.md)

## 설치 (3단계)

1. **Python 3.11** 을 설치한다 (python.org, "Add to PATH" 체크).
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

ffmpeg 를 직접 구했다면 `ffmpeg.exe` 와 `ffprobe.exe` 를 `bin/` 에 넣기만 해도 된다.
백신이 `bin\ffmpeg.exe` 를 격리하면 그 폴더를 예외로 추가한다. 관리자 권한으로 실행하면 탐색기 드래그&드롭이 막히므로 일반 권한으로 실행한다.

## 사용

1. `Add Files` / `Add Folder` 또는 리스트에 파일을 드래그&드롭.
2. 변환할 항목을 체크 (`Check All` / `Uncheck All` / `Invert`).
3. `Output format` 에서 GIF 또는 MP4 를 고르고 옵션 조절: 크기(종횡비 `Lock`/`Free`), `Quality`, `FPS`, `Target size`.
   GIF 는 `Loop`, MP4 는 x264 `Preset` 과 `Audio`(AAC / 원본 복사 / 제거) 가 추가된다.
4. 항목을 선택해 `Frame Range` 에서 구간을 프레임 단위로 조절. `Apply to Checked` 로 일괄 적용.
5. 리스트의 `Est. file size` 와 `Estimated total` 로 예상 용량 확인 (`~` 대략, `≈` 샘플 기반).
6. `Convert Checked`.

`Edit > Settings…` 에서 병렬 변환 수, 하드웨어 디코드, 샘플 추정 on/off 를 바꿀 수 있다.

## 개발

```
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python launch.py
```

구조는 `app/core`(UI 비의존 로직) 와 `app/ui`(PySide6) 로 나뉜다. 새 출력 포맷은
`app/core/converters/` 에 `BaseConverter` 구현을 추가하고 `app/ui/widgets/` 에 옵션 패널을 등록하면 된다 (`docs/PLAN.md` 5.5).
