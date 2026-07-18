<!-- scope_progress: 91 -->
<!-- offline_progress: 87 -->
<!-- field_progress: 5 -->
<!-- progress_basis: scope/offline/field are planning indicators, not safety scores; field 5 records host-observed read-only admission only, not energization or motion validation -->

# Gold Twitter · Quick + Single Axis + Expert v2 + Filter/Scheduling Evidence

상태: **FILTER/SCHEDULING INSPECTOR OFFLINE VERIFIED · CONTROL APP OPEN · PUBLISH NEXT · MOTOR ACTION NOT RUN**<br>
업데이트: **2026-07-18 18:22 KST**

## 현재 기준

- 브랜치: `codex/quick-single-axis-handoff`
- 작업 시작 기준 HEAD: `1c12808e2d035ae202ee83013f397d52a420eae2`
- Single Axis 구현 HEAD: `6f1250ffbdd558e65499e4193d69a1872269c729`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2에 포함)
- Expert v2 검증·게시 HEAD: `dfda7fef1a63ab05a26691c5b793a6bf62cb3cd2`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2에 포함)
- 현재 작업 대상: Expert filter/scheduling 읽기 전용 evidence inspector의
  private Draft PR 게시
- 제어창: 최신 source를 Python 3.14로 다시 실행했고 **OFFLINE · READ ONLY 기본값**.
  1366×820, page-scroll reset, Quick/Expert 공통 제어, Expert offline/locked와
  Single Axis Snapshot `UNKNOWN`/zero-new-I/O 고지를 실제 실행창에서 재확인
- Expert runtime smoke: P1은 `fc=430.129 Hz · PM=55.69 deg`, P2는
  `K_a=5.794e6 cnt/s²/A_peak · B=1e-7 A_peak/(cnt/s)`에서
  `MODEL GATE PASS · D=0.5794 1/s · bandwidth=457.500 rad/s`.
  입력을 `5.8e6`으로 바꿨을 때 `STALE` 전환을 관찰한 뒤 기준값으로 복원·재계산
- EAS: 설치본을 실행해 **drive 미연결** 상태에서 Quick Automatic Tuning,
  Expert Tuning tree, Motion - Single Axis 화면 구조를 직접 관찰. Connect/Enable/Run/Apply/Save는
  누르지 않았고 직접 장비 식별자는 문서에서 제외
- 사용자 현장 복귀: 실기 준비는 가능하지만, 현재 working tree로 모터 동작은 아직 실행하지 않음
- Read Only 입장: 펌웨어/PAL/boot/target-class 표시와 `MO=0`, `SO=0`, `MF=0`,
  `VX=0`, active current `0 A`, position error `0`을 현재 세션에서 관찰

## 검증 상태

- `OBSERVED` 최신 전체 오프라인 suite:
  **1434 passed, 0 failed in 249.01s**
- `OBSERVED` filter/scheduling evidence·Expert UI·operation catalog 집중 회귀:
  **98 passed, 0 failed in 53.01s**
- `OBSERVED` MAN-G-CR 1.406에서 filter type `0..6`, KV controller slots,
  KG table blocks와 `GS[2]=0..66` category만 immutable topology evidence로 고정
- `OBSERVED` KG `1..504/1..945`, scheduled position `KV[45]/KV[50]`,
  KV `1..90/KV[91..95]`, position boundary `GS[18,20]/GS[19],GS[20]`,
  speed scheduling `GS[1,6,8,10]`/`GS[6],GS[7],GS[8] Reserved`
  문서 충돌 5건을 정규화하지 않는 음성 대조가 GREEN
- `OBSERVED` inspector는 DriveWorker/ElmoLink/job/command를 만들지 않고,
  P1/P2 candidate·installed readback·Verify/Apply/Save·dispatch authority를 바꾸지 않음
- `OBSERVED` 최신 source runtime smoke:
  `OFFLINE · READ ONLY`, filter type `4 · Notch`, `Scheduled position filter`,
  `GS[2]=64 · SPEED`, 다섯 문서 충돌과 `NO MODEL · NO EMULATION · NO WRITE ·
  NO DRIVE I/O`; Apply/Save는 계속 `LOCKED`
- `OBSERVED` Expert v2 수치 모델·UI·operation catalog·palette 격리 집중 회귀:
  **74 passed, 0 failed in 44.40s**
- `OBSERVED` P2 동결 기준점, 대수 관계, malformed delegate mutation,
  invalid-input atomic preservation, worker/link/job 0개, installed readback/Verify/Apply/Save
  authority 불변, qdd/amber/angrybirds 1366×820 무수평스크롤을 고정
- `OBSERVED` 독립 리뷰 HIGH 1건(P1 plant provenance/delegate self-pass)과
  MEDIUM 1건(input edit 뒤 stale PASS)을 RED 5건으로 재현한 뒤 수정; 해당 5건 GREEN
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
- `OBSERVED` 최신 runtime smoke: Expert Candidate Lab v2에서 P1과 P2를 순서대로
  계산했고 위 기준점에서 각각 PASS. K_a 편집 시 기존 immutable 결과는 보존되지만
  상태가 `STALE · recalculation required`로 바뀌었고, 기준값 복원·재계산 뒤 PASS.
  전체 과정은 `OFFLINE MODEL · NO DRIVE / WORKER / COMMAND I/O`,
  Apply/Save `LOCKED`; hardware Run/Verify는 OFFLINE disabled
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
- **Expert Candidate Lab v2**
  - 두 단계 Current P1 → Velocity/Position P2 immutable LOCAL MODEL
  - explicit phase-to-phase R/L/TS, count/s·peak-A `K_a/B` basis
  - P1 성공 시 종속 P2 폐기, invalid 입력 시 이전 완전한 모델 보존
  - P2 KP[2]/KI[2]/KP[3]와 modeled PM/GM 표시; `I_c`는 선형 모델에서 제외
  - candidate/installed readback/`_vp_result` 권한 분리, drive/worker/command I/O 0
  - `MODEL GATE`, `SINGLE-POINT`, `GS[2]=0 ONLY`, `FILTER NEED-DATA`를 UI에 고정
  - EAS 전체 패리티·filter·gain scheduling·vendor 비공개 알고리즘 복제는 잔여
- **Expert Filter / Scheduling Evidence v0.1**
  - Expert 세 번째 단계에서 공개 문서의 filter type·KV location·KG block·
    `GS[2]` mode category를 읽기 전용으로 탐색
  - `DOCUMENTED TOPOLOGY ONLY · LOCAL INSPECTOR · NO MODEL · NO EMULATION ·
    NO WRITE · NO DRIVE I/O`
  - 공개 command reference의 충돌 5건과 누락 근거를 그대로 표시
  - exact transfer/discretization/range/cascade/quantization/saturation/
    anti-windup/interpolation/boundary는 `NEED-DATA`
  - filter response·coefficient synthesis·KV/KG/GS write는 구현하지 않음
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
| Expert v2 로컬 구현·전체 회귀·독립 재검토·runtime smoke | **완료** |
| Expert v2 private Draft PR 게시 | **완료 · `dfda7fe`** |
| Filter/Scheduling 문서 topology inspector | **구현·집중/전체 회귀·독립 게이트·runtime smoke 완료 · 게시 진행 중** |
| EAS 미연결 매핑 정리 + 잔여 무구동 세부 페이지 비교 | **1.5–3시간** |
| Exact filter·gain scheduling evaluator/emulator | **NEED-DATA · 신뢰 가능한 ETA 없음** |

문서 topology inspector 게시 뒤 확정된 무구동 잔여는 EAS 세부 화면 비교
**1.5–3시간**이다. Exact evaluator와 전체 EAS 패리티, vendor 비공개 알고리즘의
동일 복제는 근거 부족으로 현재 신뢰 가능한 ETA를 제시하지 않는다.

## 다음 자동 진행

1. Filter/scheduling inspector 전체 suite·독립 검토·runtime smoke 완료
2. 최신 제어창/모니터창을 OFFLINE으로 재실행하고 private Draft PR 갱신
3. EAS 미연결 세부 화면과 operation catalog의 구현/잠금 상태를 항목별 대조
4. Exact 식·단위·range·interpolation 근거 전까지 evaluator/emulator/write는 `NEED-DATA`

## 현장 안전 규칙

1. 우리 앱과 EAS를 동시에 같은 드라이브에 연결하지 않음
2. 연결은 모터 동작 승인이 아님
3. 실제 Enable·커뮤테이션·튜닝·영점·PTP·쓰기·저장은 해당 단계 직전의 별도 확인 필요
4. software STOP은 독립 STO/E-stop이 아니며 현장 E-stop/STO가 즉시 사용 가능해야 함
5. field 결과는 exact revision·identity·조건·raw transcript가 있을 때만 계산
