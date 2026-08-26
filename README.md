# Codex Token Monitor

Windows용 로컬 Codex 토큰 사용량 모니터입니다. Codex의 로컬 JSONL 로그를 읽어 모델별 사용량을 집계하고, 시스템 트레이와 웹 대시보드에서 보여줍니다.

## 주요 기능

- 오늘, 이번 주, 이번 달, 분기, 반기, 1년 사용량 조회
- `sol`, `terra`, `luna` 등 모델별 추세와 전체 합계 표시
- 입력·출력·캐시 입력·추론 출력·전체 토큰 집계
- 날짜별 사용량 표와 CSV 내보내기
- 백그라운드 로그 감시, 누락 기록 백필 및 중복 제거
- Windows 자동 시작 지원

## 개인정보 보호

- 원본 로그를 읽기 전용으로 처리합니다.
- 프롬프트, 응답, 도구 내용, 쿠키와 인증정보를 저장하거나 전송하지 않습니다.
- 대시보드는 `127.0.0.1`에서만 실행됩니다.
- 모델명, 토큰 수치, 이벤트 시각과 비가역 해시 등 집계에 필요한 최소 정보만 SQLite에 저장합니다.

기본 로그 탐지 경로:

```text
%USERPROFILE%\.codex\sessions\**\*.jsonl
%USERPROFILE%\.codex\archived_sessions\**\*.jsonl
```

## 설치 및 실행

[Releases](https://github.com/Primskal/Codex-token-counter/releases)에서 최신 Windows 실행 파일을 내려받아 실행합니다. 설치 프로그램이나 관리자 권한은 필요하지 않습니다.

데이터베이스는 `%LOCALAPPDATA%\CodexTokenMonitor\monitor.db`에 생성됩니다. 트레이 아이콘을 더블 클릭하거나 메뉴에서 **대시보드 열기**를 선택하면 통계를 확인할 수 있습니다.

> 실행 파일은 현재 코드 서명이 되어 있지 않아 Windows에서 경고가 표시될 수 있습니다.

## 개발

Python 3.12 이상이 필요합니다.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m codex_token_monitor
```

배포 실행 파일 빌드:

```powershell
.\build.ps1
```

## 참고

- 통계는 로컬 로그에 기록된 이벤트 기준이며 서버 측 청구량이나 구독 한도와 다를 수 있습니다.
- Codex 로그 형식이 변경되면 일부 이벤트가 집계되지 않을 수 있습니다.
- 현재 라이선스가 명시되지 않았으므로 재배포나 수정 사용 전에 저장소 소유자에게 문의하세요.
