# Codex Token Monitor

Windows에서 Codex 데스크톱 앱의 **로컬 JSONL 사용량 로그만 읽어** KST 날짜 × 모델별 토큰 사용량을 집계하는 가벼운 트레이 프로그램입니다. 네트워크 통신을 감청하거나 Codex를 변경하지 않습니다.

## 주요 기능

- Windows 시스템 트레이 상주, 오늘 전체/모델별 합계 빠른 보기
- 파일 변경 알림(`watchdog`) + 주기적 전체 재조정 스캔
- 첫 실행 전체 백필, 종료 중 누락분의 다음 실행 자동 복구
- 오늘·최근 7일·이번 달·사용자 지정 기간 대시보드
- 날짜 × 모델 표, 모델별/날짜별 합계, 추세 차트
- 입력·출력·캐시 입력·추론 출력·전체 토큰 분리
- 선택 기간만 UTF-8 BOM CSV로 내보내기
- 로그 자동 탐지, 추가 읽기 전용 경로, 백필 범위, 스캔 간격, 현재 사용자 자동 시작 설정
- 단일 인스턴스와 SQLite WAL/트랜잭션 기반 복구
- Windows Per-Monitor V2 DPI 선언으로 고배율 트레이 메뉴 선명도 유지

`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`를 원래 이름으로 구분합니다. 그 밖의 모델도 이름을 바꾸지 않고 표시하며, 근거가 없는 경우에만 `unknown`으로 집계합니다.

## 개인정보 보호 경계

프로그램은 HTTPS 가로채기, 프록시/루트 인증서 설치, Codex 통신 변조, 프로세스 메모리 읽기, 쿠키·로그인·인증정보 접근, 관리자 권한, 외부 전송을 전혀 사용하지 않습니다. 원본 로그를 수정하거나 삭제하지 않습니다.

SQLite에는 모델명, 토큰 숫자, 이벤트 시각/KST 날짜, 세션·턴의 SHA-256 기반 비가역 해시, 이벤트 중복 키, 파일 체크포인트, 스키마 버전, 짧은 진단 코드와 설정만 저장합니다. 대화 본문, 프롬프트, 모델 응답, 시스템/개발자 지침, 도구 입력·출력, 쿠키, API 키, 원본 JSON/payload는 SQLite·CSV·화면·진단 로그에 저장하거나 표시하지 않습니다. CSV에는 날짜, 모델, 다섯 토큰 숫자만 들어갑니다.

대시보드는 `127.0.0.1`에만 바인딩되고 외부 리소스를 불러오지 않습니다. POST 동작은 프로세스별 CSRF 토큰을 요구합니다.

## 지원 로그 위치

기본 자동 탐지 경로:

- `%USERPROFILE%\.codex\sessions\**\*.jsonl`
- `%USERPROFILE%\.codex\archived_sessions\**\*.jsonl`

설정에서 다른 디렉터리를 추가할 수 있습니다. 추가 경로도 읽기 전용으로 사용합니다. 경로가 없거나 Codex가 실행 중이 아니어도 트레이, 대시보드와 기존 통계는 정상 동작합니다.

## 설치와 실행

### 완성된 실행 파일

`dist\CodexTokenMonitor.exe`를 실행합니다. 설치 프로그램이나 관리자 권한은 필요하지 않습니다. 데이터베이스는 기본적으로 `%LOCALAPPDATA%\CodexTokenMonitor\monitor.db`에 생성됩니다.

처음 실행하면 트레이에 상주하고 백그라운드 백필을 시작합니다. 트레이 아이콘을 더블 클릭하거나 메뉴의 **대시보드 열기**를 선택합니다. 종료는 트레이 메뉴의 **종료**를 사용합니다.

트레이 아이콘이 작업 표시줄에 바로 보이지 않으면 시계 옆 **숨겨진 아이콘 표시(∧)**를 열어 녹색 원형 아이콘의 **Codex Token Monitor** 툴팁을 확인하십시오. 메뉴에서 **오늘 전체**, **모델별 오늘 합계**, **대시보드 열기**, **즉시 재스캔**, **감시 일시중지/재개**, **설정**, **종료**가 보이면 정상입니다.

### 고DPI 화면

실행 파일에는 `PerMonitorV2, PerMonitor, System` DPI awareness와 구형 Windows용 `true/pm` fallback을 선언합니다. 따라서 Windows 10 1703 이상에서 트레이 우클릭 메뉴는 현재 모니터의 배율에 맞춰 네이티브로 렌더링됩니다. 150% 이상 배율에서 이전 버전이 흐렸다면 `v1.2.0` 이상을 실행한 뒤 트레이 메뉴를 다시 열어 확인하십시오.

### 개발 환경

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e . -r requirements-dev.txt
.\.venv\Scripts\python.exe -m codex_token_monitor
```

트레이 없이 대시보드를 확인하려면 다음을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m codex_token_monitor --no-tray
```

읽기 전용 재조정 스캔 1회와 민감하지 않은 건수 요약만 보려면:

```powershell
.\.venv\Scripts\python.exe -m codex_token_monitor --once
```

합성 로그로 격리 검증할 때만 `--log-root <디렉터리>`를 지정하면 기본 자동 탐지 대신 해당 루트만 읽습니다. 지정한 경로에도 쓰지 않습니다.

## 사용법

### CSV 내보내기

대시보드에서 날짜 범위를 선택하고 **CSV 내보내기**를 누릅니다. 파일은 UTF-8 BOM이며 날짜, 모델, 입력, 출력, 캐시 입력, 추론 출력, 전체 토큰 열만 포함합니다.

### 자동 시작 설정/해제

자동 시작은 기본 비활성화입니다. 대시보드 설정에서 사용자가 체크하고 저장한 경우에만 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`의 `CodexTokenMonitor` 값을 등록합니다. 체크를 끄면 DB에 기록된 관리 명령과 현재 레지스트리 값이 정확히 일치할 때만 삭제하므로, 사용자가 바꾼 동명 항목은 제거하지 않습니다. 시스템 전체 설정이나 관리자 권한은 사용하지 않습니다.

## 실제 확인된 Codex 로그 스키마

2026-08-25 이 PC의 활성/아카이브 JSONL을 원문 출력 없이 읽기 전용 표본 검사한 결과는 다음과 같습니다.

- 레코드 공통 시각은 루트 `timestamp`의 UTC `Z` 형식입니다.
- 세션 식별자는 `session_meta.payload.id` 및 `session_meta.payload.session_id`에 있습니다.
- 모델은 `turn_context.payload.model`, 턴 식별자는 `turn_context.payload.turn_id`에 있습니다.
- 사용량 이벤트는 `type == "event_msg"`이며 `payload.type == "token_count"`입니다.
- `payload.info`에는 `last_token_usage`, `total_token_usage`, `model_context_window`가 있습니다.
- 두 usage 객체에는 `input_tokens`, `output_tokens`, `cached_input_tokens`, `reasoning_output_tokens`, `total_tokens`가 있고 현재 로그에는 추가로 `cache_write_input_tokens`도 있었습니다. 추가 필드는 집계하지 않습니다.
- 표본의 토큰 이벤트에는 별도 응답 ID가 없었습니다. 현재 세션/턴 컨텍스트와 수치 스냅샷으로 중복 키를 만듭니다.
- `total_token_usage`는 세션 처리 중 계속 증가했고, 동일한 last/total 스냅샷이 연속 반복되는 사례가 확인되었습니다.
- 한 파일 안의 모델 전환과 `session_meta.source`가 구조화된 서브에이전트 세션이 확인되었습니다. 파서는 각 토큰 이벤트 직전의 유효한 `turn_context` 모델을 사용하고, 새 `session_meta`에서 컨텍스트를 초기화합니다.
- 활성/아카이브 폴더는 같은 레코드 구조와 세션 식별 체계를 사용합니다. 조사 시점에는 동일 세션이 두 폴더에 동시에 남은 표본이 없어 실제 이동 전후 바이트 동일성은 역사적으로 대조할 수 없었습니다. 파일 이동 및 복제 복구는 합성 통합 테스트로 검증했습니다.

## 증분 처리와 복구 설계

### 체크포인트와 부분 라인

파일별로 정규화 경로, 가능한 경우 OS 파일 ID를 해시한 안정 식별자, 크기/수정 시각, 마지막 완전 라인 다음 바이트 위치, 마지막 라인 시작 위치/해시, 민감정보가 제거된 파서 상태, 파서 버전을 저장합니다. 바이트 단위로 읽기 때문에 UTF-8 문자가 읽기 블록 경계에 걸려도 완전한 `\n` 종료 라인만 해석합니다. 마지막 라인이 미완성이면 시작 위치를 체크포인트로 유지하여 다음 스캔에서 다시 읽습니다.

이벤트 삽입·집계 증가·체크포인트 전진은 하나의 `BEGIN IMMEDIATE` 트랜잭션에서 커밋됩니다. 종료가 커밋 전이면 모두 재처리되고, 커밋 후면 전부 이어서 처리되므로 반쪽 상태가 없습니다. 백필 도중 종료해도 같은 방식으로 이어집니다.

### 교체·축소·회전·아카이브

- 현재 크기가 체크포인트보다 작으면 축소로 판단하여 0부터 안전 재스캔합니다.
- 마지막 완전 라인 해시가 달라지면 같은 파일 ID의 덮어쓰기로 보고 재스캔합니다.
- 같은 경로에 새 파일 ID가 나타나면 교체로 기록하고 새 인스턴스로 읽습니다.
- 같은 파일 ID가 다른 경로에 나타나면 이름 변경/아카이브 이동으로 보고 기존 체크포인트를 이어갑니다.
- 복제로 다른 파일 ID가 생겨도 이벤트 고유 제약으로 다시 합산하지 않습니다.
- 파일 감시 이벤트가 유실되어도 기본 15초 재조정 스캔과 다음 실행의 전체 발견 단계가 복구합니다.

일시적 잠금·접근 실패는 짧은 진단 코드만 늘리고 다음 주기에 재시도합니다. 완전 라인의 UTF-8/JSON 오류는 해당 라인만 건너뛰며 원문은 보관하지 않습니다.

### 중복 제거와 계산

실제 스키마에서 항상 확인된 `last_token_usage`를 응답 증가분으로 우선 사용합니다. 고유 키는 세션 해시, 턴 해시, 당시 모델, 누적 구간, usage 종류, last 수치와 total 스냅샷으로 만듭니다. 따라서 동일 응답 스냅샷 반복, 파일 재스캔, 포크된 세션 이력, 아카이브 복제가 한 번만 반영됩니다. ID가 없으면 파일 인스턴스와 이벤트 시각도 해시에 포함합니다. 해시 입력에는 본문이나 인증정보가 없습니다.

`last_token_usage`가 없는 지원 가능한 이벤트에서는 이전 `total_token_usage`와의 비음수 차이만 집계합니다. 최초 스냅샷과 감소/0 초기화 시점은 새 기준선으로만 삼고 음수나 불명확한 기존 사용량을 더하지 않습니다. 이후 증가분부터 집계합니다.

KST 날짜는 이벤트 시각을 `Asia/Seoul`로 변환해 결정합니다. 시각이 없거나 잘못된 경우 파일 수정 시각을 UTC로 해석한 값을 일관되게 쓰고 `timestamp_fallback` 진단 횟수를 표시합니다.

`cached_input_tokens`는 입력의 부분집합, `reasoning_output_tokens`는 출력의 부분집합일 수 있으므로 `total_tokens`에 다시 더하지 않습니다. 저장된 `total_tokens`는 로그 필드 값을 그대로 사용합니다.

## 테스트와 빌드

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\build.ps1
```

빌드 스크립트는 테스트가 모두 통과해야 PyInstaller one-file/windowed 빌드를 만듭니다. 산출물은 항상 `dist`에 생성되며, 최신 기본 파일 `dist\CodexTokenMonitor.exe`와 동일한 해시의 버전 파일 `dist\CodexTokenMonitor-vX.Y.Z.exe`를 함께 만듭니다. 실행 중인 구버전을 보존하면서 새 버전을 구분하기 위한 방식이며, 별도 `dist-updated` 폴더는 사용하지 않습니다.

`tests/test_windows_dpi_manifest.py`는 생성된 EXE의 PE 매니페스트 리소스를 직접 읽어 Per-Monitor V2 및 구형 DPI fallback 선언이 실제로 내장됐는지 검사합니다.

민감정보 영속화 감사를 재현하려면(내용은 출력하지 않고 건수만 출력):

```powershell
.\.venv\Scripts\python.exe scripts\privacy_audit.py `
  --db runtime-data\real-validation\monitor.db `
  --csv runtime-data\real-validation\validation.csv `
  --log-root "$env:USERPROFILE\.codex\sessions" `
  --log-root "$env:USERPROFILE\.codex\archived_sessions"
```

## 알려진 한계

- 통계는 Codex 로컬 로그에 기록된 이벤트 기준입니다. OpenAI 계정 청구량, 구독 한도 또는 서버 측 측정과 완전히 일치한다고 보장하지 않습니다.
- Codex가 향후 로그 스키마를 바꾸면 지원하지 않는 이벤트는 원문 없이 진단 카운터만 증가시키고 건너뜁니다. `parser_version` 변경 시 기존 이벤트 고유 키로 안전 재스캔할 수 있습니다.
- 별도 응답 ID가 현재 token_count에 없으므로, 같은 세션·턴·모델·누적 구간에서 last와 total의 모든 수치가 완전히 같은 이벤트는 반복으로 취급합니다. 실제 표본에서 이 패턴은 연속 중복이었지만 향후 의미가 달라지면 파서 버전 갱신이 필요합니다.
- 실행 파일은 코드 서명하지 않았습니다. 조직의 Windows 정책에 따라 신뢰 경고가 표시될 수 있습니다.
- 트레이 아이콘 숨김 영역 배치와 브라우저 다운로드 위치는 Windows/브라우저 설정에 따라 달라집니다.
