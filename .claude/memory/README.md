# Claude Code 메모리 (PC 간 공유)

이 폴더는 **`JUN_Video_Tool` 저장소의** 프로젝트 메모리 원본이다. git 으로 추적해서 여러 PC 가 같은 기억을 공유한다.

- `MEMORY.md` — 세션마다 컨텍스트에 로드되는 인덱스 (한 메모리당 한 줄)
- `*.md` — 메모리 1개 = 파일 1개 (frontmatter 의 `type`: `user` / `feedback` / `project` / `reference`)

## 동작 방식

Claude Code 는 메모리를 `~/.claude/projects/<경로슬러그>/memory/` 에서 읽고 쓴다. 그 경로를 이 폴더로
**디렉터리 정크션(junction)** 걸어 두면 Claude 가 메모리를 저장하는 순간 곧바로 이 repo 의 변경으로 잡힌다.

```
~/.claude/projects/C--Users-USER-Desktop-JP-0110-JUN-Video-Tool/memory  ──junction──▶  <repo>/.claude/memory
```

## 새 PC 셋업

이 저장소는 `JUN_Claude` 의 형제 폴더가 아니므로 `setup.ps1` 에 경로를 직접 알려 준다:

```powershell
cd <JUN_Claude 경로>
.\setup.ps1 -ExtraRepo "<이 저장소의 절대 경로>"
```

수동으로 걸 때 (PowerShell):

```powershell
$slug = (Resolve-Path .).Path -replace '[:\\/_.]', '-'
$link = "$env:USERPROFILE\.claude\projects\$slug\memory"
if (Test-Path $link) { Remove-Item $link -Force }     # 빈 실폴더면 지운다
New-Item -ItemType Junction -Path $link -Target (Resolve-Path .claude\memory)
```

`~/.claude/projects/<슬러그>/` 의 `*.jsonl` 세션 로그는 공유 대상이 아니다. `memory/` 만 저장소에 담는다.
