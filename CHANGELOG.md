# Changelog

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
