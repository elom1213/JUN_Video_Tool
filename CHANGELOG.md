# Changelog

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
