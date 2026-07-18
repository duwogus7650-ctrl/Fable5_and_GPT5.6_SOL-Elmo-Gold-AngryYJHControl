<!-- scope_progress: 87 -->
<!-- offline_progress: 82 -->
<!-- field_progress: 5 -->
<!-- progress_basis: scope/offline/field are planning indicators, not safety scores; field 5 records host-observed read-only admission only, not energization or motion validation -->

# Gold Twitter · Quick + Single Axis + Expert Candidate Lab v1

상태: **IN PROGRESS · CONTROL APP OFFLINE · EAS UI MAPPED / UNCONNECTED · READ-ONLY FIELD SESSION CLOSED**<br>
업데이트: **2026-07-18 15:53 KST**

## 현재 기준

- 브랜치: `codex/quick-single-axis-handoff`
- 작업 시작 기준 HEAD: `1c12808e2d035ae202ee83013f397d52a420eae2`
- GitHub 게시 HEAD: `9a596265afb31044d43d24015914f35de28d5706`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2)
- 현재 작업 대상: 게시 HEAD 위의 Single Axis Safety Snapshot v1
- 제어창: 최신 source를 Python 3.14로 다시 실행했고 **OFFLINE · READ ONLY 기본값**.
  1366×820, page-scroll reset, Quick/Expert 공통 제어와 Expert offline/locked 표시를
  실제 실행창에서 재확인
- EAS: 설치본을 실행해 **drive 미연결** 상태에서 Quick Automatic Tuning,
  Expert Tuning tree, Motion - Single Axis 화면 구조를 직접 관찰. Connect/Enable/Run/Apply/Save는
  누르지 않았고 직접 장비 식별자는 문서에서 제외
- 사용자 현장 복귀: 실기 준비는 가능하지만, 현재 working tree로 모터 동작은 아직 실행하지 않음
- Read Only 입장: 펌웨어/PAL/boot/target-class 표시와 `MO=0`, `SO=0`, `MF=0`,
  `VX=0`, active current `0 A`, position error `0`을 현재 세션에서 관찰

## 검증 상태

- `OBSERVED` 최신 전체 오프라인 suite: **1371 passed, 0 failed in 303.22s**
- `OBSERVED` Single Axis snapshot·connection generation·session log·motion 집중 회귀:
  **346 passed, 0 failed in 127.18s**
- `OBSERVED` 집중 연결·텔레메트리·모니터·테마 회귀: **204 passed**
- `OBSERVED` 1366×820 세 테마 레이아웃 회귀: **33 passed**
- `OBSERVED` 독립 리뷰의 access-mode 증거 누락·복구 잠금·자기서명 경로 3건:
  RED 재현 후 수정, 음성 대조 **3 passed**
- `OBSERVED` 실패 이력: 강화된 access-mode 계약 직후 **1285 passed / 44 failed**였고,
  생산 경계를 완화하지 않은 채 기존 test double에 의도 모드를 명시하여 위 전체 GREEN으로 복구
- `OBSERVED` `git diff --check`: exit 0. 출력은 기존 LF→CRLF 변환 경고뿐
- `OBSERVED` 현재 working tree Read Only 최종 세션 로그: **12 events · 0 dropped**,
  마지막 이벤트 `connection.closed · worker stopped`,
  `evidence_class=HOST_OBSERVED_NOT_DRIVE_HISTORY`,
  SHA-256 `C8E818BBF8690A14DC88503E3A2838EE448D3B336A18FE57E7C8E3BC8025CF7A`
- `OBSERVED` 위 세션에서 telemetry authority가 비활성 상태로 잠시 해제된 뒤 복구됨.
  당시 `energizing=false`; 복구 후 `motor_enabled=false`
- `OBSERVED/DERIVED` sequence 690–694는 host-source age가
  `1514.2 / 1295.3 / 1077.4 / 859.9 / 639.8 ms`로 모두 0.5 s source-age gate를
  초과해 fail-closed 거부됨. 약 1.5 s UI queue backlog의 직접 유발 동작은 `UNVERIFIED`
- `OBSERVED` 페이지 전환 뒤 공용 스크롤 값 `923` 잔류를 RED로 재현하고,
  실제 페이지가 바뀔 때만 새 페이지 원점으로 초기화. 집중 회귀 **67 passed**
- `OBSERVED` Disconnect/창 닫기 즉시 authority를 폐기하고 late
  telemetry/connected/failed에도 `DISCONNECTING`과 선택기 잠금을 유지하도록 수정.
  직접 영향 **169 passed**, 추가 UI/safety **182 passed**, 독립 재검토 **102 passed**
- `OBSERVED` 최신 runtime smoke: System 하단에서 Status로 전환했을 때
  `FAULT / STATUS / SESSION LOG` 상단이 즉시 보였고, Expert Candidate Lab은
  `OFFLINE MODEL · NO DRIVE I/O`, Apply/Save `LOCKED`; hardware Run/Verify는 OFFLINE disabled
- `OBSERVED` EAS 미연결 UI baseline:
  Quick 6단계, Expert의 Limits/Protections·Current·Commutation·Velocity/Position·Scheduling,
  Single Axis의 I/O·STO·UM·Current/Stepper/Sine·PTP·Terminal·Recorder 구조를 직접 매핑

## 구현된 범위

- **Read Only 기본 연결**
  - link 생명주기 단방향 observe-only latch
  - allowlisted query + software safe-shutdown만 허용
  - `MO=SO=VX=MF=0`, `PS=-2/-1` 정지상태 2회 일치 입장
  - requested / transport / returned access mode 3방향 일치
- **Supervised Control 연결**
  - 연결별 1회 확인, 기본값 Cancel
  - 연결 자체는 Enable·모션·커뮤테이션·튜닝·`PX=0`·쓰기·`SV` 승인이 아님
  - mutation UI는 fresh telemetry + supervised mode + `MO=0` 필요
- **Quick Tuning**
  - P1 / commutation signature / P2 / Verify / Abort가 Quick과 Expert에서 공통 표시
  - Apply/Save는 계속 `NEED-DATA` 잠금
- **Single Axis**
  - finite-PTP 오프라인 backend는 MODEL 검증
  - 기존 Axis Summary의 `MO/SO/MF/PS/SR/MS`만 소비하는
    `DRIVE-REPORTED · MODEL · NOT STO TEST EVIDENCE` safety snapshot 구현
  - 누락·NaN/Inf·bool·비정수·초대형 정수·reserved SR bit·문서 밖 amplifier/profiler code는
    전체 model authority `UNKNOWN`
  - SO/SR4 또는 PS/SR12 불일치는 `INCONSISTENT · AUTHORITY UNKNOWN`
  - 신규 query/job/link 호출 없이 current worker generation만 처리하고 disconnect 즉시 blank
  - telemetry authority 상실·energizing 중에는 snapshot만 blank하되 current-worker
    `motion_config_unknown` fail-safe latch는 계속 수용
  - live PTP는 기계 envelope·limit·정지거리·독립 E-stop/STO 근거 전까지 `NEED-DATA`
- **Expert Candidate Lab v1**
  - 전류루프 후보 계산과 read-only Bode 미리보기는 LOCAL MODEL
  - EAS Expert 전체 패리티, P2·필터·스케줄링은 미구현/잔여
- **UI lifecycle 안전 보완**
  - 탭 전환 시 공용 workspace 스크롤을 새 페이지 원점으로 복귀
  - shutdown-pending 동안 연결·텔레메트리·access-mode authority 폐기
  - 현재 worker의 `stopped` 뒤에만 `OFFLINE`과 연결 선택기 복구
- **EAS 미연결 UI inventory**
  - Quick 6단계 명칭/순서가 현재 guided flow와 일치
  - Expert의 User Units·limits/protection·I/O·settling·scheduling·time verification·Summary는 잔여
  - Single Axis의 STO drive-reported snapshot은 부분 구현
  - Digital I/O·mode별 수동 구동·Terminal·docked Recorder parity는 잔여 `NEED-DATA`
- **Elmo 자료 인벤토리**
  - 신규 폴더 59개 파일과 SHA-256 기록
  - `Version 1.1.16.0 B01 for customers.zip` 안의 `NGDrive 01.01.16.00 08Mar2020B01G.gabs` 파일명 일치 확인
  - B01/B01G 의미와 flashing 적합성은 `NEED-DATA`; flashing 승인 아님

## 남은 예상 시간

| 작업 | 남은 예상 |
|---|---:|
| 최신 앱 OFFLINE smoke 후 문서 closeout | **0.25–0.5시간** |
| EAS 미연결 매핑 정리 + 잔여 무구동 세부 페이지 비교 | **1.5–3시간** |
| Expert vNext P2·필터·스케줄링 오프라인 구현 | **7–12시간** |
| 통합 문서·독립 재검토 | **2–3시간** |

**실기 검증 제외 잔여:** 약 **11–19 집중시간 / 2–3 작업일**.<br>
전체 EAS 패리티나 vendor 비공개 알고리즘의 동일 복제는 별도 범위이며 현재 신뢰 가능한 ETA를 제시하지 않음.

## 다음 자동 진행

1. Expert vNext P2·filter·scheduling을 순수 OFFLINE candidate 단계부터 구현
2. EAS 미연결 세부 화면과 operation catalog의 구현/잠금 상태를 항목별 대조
3. 현장 gate가 충족된 개별 동작만 별도 확인 후 제한 실기

## 현장 안전 규칙

1. 우리 앱과 EAS를 동시에 같은 드라이브에 연결하지 않음
2. 연결은 모터 동작 승인이 아님
3. 실제 Enable·커뮤테이션·튜닝·영점·PTP·쓰기·저장은 해당 단계 직전의 별도 확인 필요
4. software STOP은 독립 STO/E-stop이 아니며 현장 E-stop/STO가 즉시 사용 가능해야 함
5. field 결과는 exact revision·identity·조건·raw transcript가 있을 때만 계산
