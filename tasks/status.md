<!-- scope_progress: 96 -->
<!-- offline_progress: 94 -->
<!-- field_progress: 5 -->
<!-- progress_basis: scope/offline/field are planning indicators, not safety scores; field 5 records host-observed read-only admission only, not energization or motion validation -->

# Gold Twitter · Quick + Single Axis + Expert v2 + Evidence + Page Status + User Units + Limits/Protections + Application Settings + Hidden Bode Map

상태: **HIDDEN BODE MAP PUBLISHED · LOCAL CATALOG/UI ONLY GREEN · MOTOR ACTION NOT RUN**<br>
업데이트: **2026-07-19 01:03 KST**

## 현재 기준

- 브랜치: `codex/quick-single-axis-handoff`
- 작업 시작 기준 HEAD: `1c12808e2d035ae202ee83013f397d52a420eae2`
- Single Axis 구현 HEAD: `6f1250ffbdd558e65499e4193d69a1872269c729`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2에 포함)
- Expert v2 검증·게시 HEAD: `dfda7fef1a63ab05a26691c5b793a6bf62cb3cd2`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2에 포함)
- Filter/Scheduling evidence inspector 검증·구현 HEAD:
  `540877ea2b65866bb45aeaad4fc88cd836258e0a`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2에 포함)
- Expert Local Page Status / Errors v0.1 검증·구현 HEAD:
  `a20e19a0d28bc66b91572ad93d4cd2da4f032672`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2에 포함)
- Expert User Units · Documented Formula Preview v0.1 검증·구현 HEAD:
  `0472ee5ae881aabd5a813ea7c176f7c520880d9c`
  (`origin/codex/quick-single-axis-handoff`, Draft PR #2에 포함)
- Expert Limits / Protections · Documented Parameter Map v0.1 검증·구현 HEAD:
  `baa2841bac35ed93cfffd8a9dcbe2dd8bcd83395`
  (`origin/codex/quick-single-axis-handoff`, private Draft PR #2에 포함)
- Expert Application Settings · Documented Map v0.1 검증·구현 HEAD:
  `e577f790f6b15c418f1cd6a8fd9bd55da9a46d1f`
  (`origin/codex/quick-single-axis-handoff`, private Draft PR #2에 포함)
- Expert Hidden Verification – Bode · Documented Map v0.1 검증·구현 HEAD:
  `80731767b0f0b591d4330d6fabd461a1244537bd`
  (`origin/codex/quick-single-axis-handoff`, private Draft PR #2에 포함)
- 현재 작업 대상:
  Hidden Bode 게시 closeout 기록과 다음 no-I/O EAS bounded slice 선정
- Hidden Bode 구현은 private `origin`의 게시 HEAD다. 여덟 번째
  `BODE DOC MAP` page에 Tuner Settings 8 / Current Bode 8 /
  Velocity·Position Bode 8개 immutable documentation row, 7 frozen source
  identity, 4 conflicts, 12 warnings, 8 missing-evidence를 고정했다.
- authority는 `DOCUMENTED_HIDDEN_BODE_MAP_ONLY`, status는
  `PARTIAL_NEED_DATA`; local catalog/UI inspect만 GREEN이다. 실제 Current
  Verify는 ENERGY, V/P Verify는 MOTION이지만 이 page는 drive read/current
  state/acquisition/evaluation/Verify/EAS setting change/recording/command/
  write/Apply/Revert/SV/energization/motion을 제공하지 않는다.
- 독립 검토의 LOW 표현 지적에 따라 실제 실행처럼 읽히던 `VERIFY BODE`를
  `BODE DOC MAP`으로, `MODEL STATUS`를 `EVIDENCE STATUS`로 바꿨다.
- runtime 구조 smoke는 Python 3.14, 1366×820, **OFFLINE**에서 8/8/8개 행,
  action/edit widget 0, 수평 scroll 0을 확인했다. cosmetic label 수정 뒤에는
  해당 권한/UI와 세 테마 geometry 테스트를 현재 트리에서 재통과했다.
  Connect·읽기·쓰기·Verify·설정 변경·통전·구동은 실행하지 않았다.
- Page Status runtime smoke: 네 번째 `STATUS / ERRORS` 단계에서
  `OVERALL PARTIAL · LOCAL STATUS ONLY`, P1 `MISSING`, P2 `BLOCKED`,
  Evidence `DOCUMENTED PARTIAL · 5 unresolved document conflicts`를 관찰.
  `NOT EAS ENTER/APPLY STATE · NOT INSTALLED · NO DRIVE I/O`와
  Apply/Save `LOCKED`가 동시에 유지됨
- User Units runtime smoke: 다섯 번째 `USER UNITS` 단계에서 blank 수동 입력,
  `DOCUMENTED GROUPING MISMATCH · PURPOSE NEED-DATA`, `NO FC/OF WRITE · NO DRIVE I/O`를
  관찰. NetHelp 예제는 정확히 `1/100 = 0.01 µm/count`, `100 count = 1 µm`였고,
  `FC[7]` 편집 뒤 `STALE · previous documented preview retained as historical only`로
  강등되는 것을 확인한 뒤 기준값으로 복원·재계산
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

- `OBSERVED` Hidden Bode immutable model contract:
  **14 passed**. exact 3 sections/24 rows(8/8/8), frozen singleton,
  strict lookup, 7 sources, 4 conflicts, 12 warnings, 8 missing-evidence,
  file/process/network I/O poison과 inspect만 true인 fail-closed capability를 확인했다.
- `OBSERVED` LOW 표현 개선 뒤 Hidden Bode Expert 영향범위 회귀:
  **211 passed in 65.06s**. 기존 P1/P2 MODEL과 다른 Expert inspector,
  operation catalog, late Axis/model 비전파, 8-step UI zero-I/O/authority,
  세 테마 1366×820 geometry/contrast를 재확인했다.
- `OBSERVED` 현재 게시 트리의 최신 전체 repository suite:
  **1547 passed in 503.66s**, 직접 `pytest` 실행의 숫자 종료코드 **0**
- `OBSERVED` Hidden Bode 독립 read-only 검토:
  **HIGH/MEDIUM 없음**. 7개 설치 source SHA-256을 원본에서 독립 재계산해
  전부 동결값과 일치했고, LOW UI 표현 2건은 `BODE DOC MAP`과
  `EVIDENCE STATUS`로 수정한 뒤 영향범위·전체 회귀를 다시 통과했다.
- 이 GREEN은 immutable documentation catalog/UI의 열람 계약에만 적용된다.
  실제 EAS Bode 측정, current/position/velocity 응답, tuning 적합성,
  model/measurement parity, 정량 acceptance와 hardware safety는
  **`NEED-DATA / NO-GO`**다.
- `OBSERVED` 첫 Hidden Bode 전체 실행은 기존 Status Monitor GUI 테스트의
  Qt native access violation으로 비정상 종료했다. 같은 시각 오래 실행 중이던
  별도 pytest process가 관찰됐지만 직접 원인인지는 `UNVERIFIED`다.
  해당 단일 테스트 **1 passed**, 후속 전체 실행 **1547 passed / exit 0**,
  LOW 표현 개선 뒤 최신 전체 재실행도 **1547 passed / exit 0**이었다.
- `OBSERVED` Application Settings 모델·UI·operation catalog·authority focused 회귀:
  **85 passed**. immutable 3 sections/13 rows(4/4/5), 24 source identity,
  9 conflicts, 16 warnings, 6 missing-evidence, strict lookup/digest,
  file/process/network/worker/link/drive I/O poison, 기존 Expert/installed/
  dispatch/connection/safety와 Run/Verify/Apply/Restore/Save authority 불변,
  late Axis Summary 비전파, 세 테마 1366×820 geometry/contrast를 확인했다.
- 이 85-pass 결과에서 **로컬 immutable catalog/UI만 GREEN**이다.
  current drive config/I/O state, exact B01G output electrical/brake capability,
  current/default 판정, transaction/readback/rollback, output actuation,
  brake/safety efficacy와 field behavior는 **`NEED-DATA / NO-GO`**다.
- `OBSERVED` Application Settings를 포함한 최신 전체 repository suite:
  **1529 passed in 476.14s**, 직접 `pytest` 실행의 숫자 종료코드 **0**
- `OBSERVED` Application Settings 독립 closeout:
  **잔여 HIGH/MEDIUM/LOW 없음**. 독립 재계산한 24개 source SHA-256 전부
  동결값과 일치했고 미검증 Gold Twitter 설치/하드웨어 PDF는 제외됨
- `OBSERVED` Application Settings runtime GUI smoke:
  Python 3.14, 1366×820, `OFFLINE · READ ONLY`; 4/4/5개 행, 24개 frozen
  identity, 짧은 표 헤더와 app inspect-only를 확인. Connect,
  drive/worker/command/output/motion I/O 없음
- `OBSERVED` Limits/Protections 모델·UI·operation catalog·authority focused 회귀:
  **69 passed**. canonical frozen snapshot, 27개 command row, 9개 문서 충돌,
  danger warning, strict lookup, 20개 source hash, zero file/process/network/worker/link/job/query/write,
  기존 P1/P2/Evidence/Page Status/User Units/installed/dispatch/connection/safety 권한 불변,
  세 테마 1366×820 geometry를 확인
- 이 69-pass 결과에서 **로컬 immutable documented catalog만 GREEN**이다.
  current drive config, active protection state, firmware/EAS parity, 값 유효성·추천,
  protection efficacy, read/write/Apply/Revert/SV와 field safety는
  **`NEED-DATA / NO-GO`**다.
- `OBSERVED` 직전 Limits/Protections 기준 전체 오프라인 suite:
  **1513 passed in 698.16s**. 출력은 100%와 passed summary까지 완료됐고 stderr는
  비어 있으며, 별도 capture-completeness 검사는 exit 0이다. 백그라운드 launcher가
  원 pytest process의 숫자 exit code를 보존하지 않은 한계는 남긴다.
- `OBSERVED` Limits/Protections 독립 closeout:
  SimplIQ source, mutation digest, documented/app access 구분, fresh-import poison,
  connection/safety authority snapshot과 세 테마 contrast를 재확인해
  **잔여 HIGH/MEDIUM/LOW 없음**. 독립 focused 실행도 **69 passed**
- `OBSERVED` Limits/Protections runtime smoke:
  Python 3.14, 1366×820, `OFFLINE · READ ONLY`; 세 section 7/9/11 row,
  20 frozen identities, dark high-contrast table, action control 없음,
  Apply/Save `LOCKED`; drive/worker/command I/O와 motor action 없음
- `OBSERVED` 최초 runtime table palette 결함:
  흰 배경/밝은 글자를 RED로 재현한 뒤 `expertEvidenceTable` 전용 세 테마 스타일과
  text/base contrast `>=4.5` 회귀로 수정
- `OBSERVED` 직전 게시 기준 전체 오프라인 suite:
  **1498 passed, 0 failed in 275.50s**. Limits/Protections 추가 전 기준선
- `OBSERVED` 직전 게시 기준 Expert P1/P2·filter/scheduling evidence·Page Status·User Units·UI·catalog
  집중 회귀: **162 passed, 0 failed in 59.11s**. 새 Limits/Protections working tree는 포함하지 않음
- `OBSERVED` User Units 모델·UI·catalog·authority 집중 회귀:
  **51 passed, 0 failed in 10.09s**
- `OBSERVED` User Units 독립 검토 3회 결과:
  로컬 `DOCUMENTED_FORMULA_PREVIEW / PARTIAL_SCREENING` 범위에서
  **잔여 HIGH/MEDIUM/LOW 없음**. 현재 drive config, EAS 수치 parity,
  operational suitability와 field safety는 계속 `NO-GO / NEED-DATA`
- `OBSERVED` Page Status 순수 projection 직접 회귀: **10 passed**
- `OBSERVED` 독립 리뷰에서 P2 stale가 변조 candidate를 가리는 경로,
  forged evidence가 `DOCUMENTED PARTIAL`로 보이는 경로, P2 MISSING 직접 대조 누락,
  hidden page text-edit별 고비용 재계산을 발견. RED 5건으로 재현해
  coherence-before-stale, canonical snapshot 전체 동등성, 명시 MISSING,
  hidden-page dirty/visible-page one-shot refresh로 수정; 최종 잔여 HIGH/MEDIUM/LOW 없음
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
- **Expert Local Page Status / Errors v0.1**
  - Expert 네 번째 단계에서 현재 P1/P2/evidence immutable 상태만 분류
  - `MISSING / BLOCKED / STALE / INVALID / CURRENT LOCAL MODEL /
    DOCUMENTED PARTIAL`; 전체는 항상 `PARTIAL`
  - exact P1↔P2 object binding, 재계산 coherence, canonical evidence 전체 동등성 검증
  - hidden page에서는 dirty만 기록하고 실제 page 진입 때 한 번 갱신
  - `LOCAL STATUS ONLY · NOT EAS ENTER/APPLY STATE · NOT INSTALLED ·
    NO CALCULATION · NO WRITE · NO DRIVE I/O`
  - EAS icon/Enter/Apply/Revert/last-page/Summary recommendation은 `NEED-DATA`
- **Expert User Units · Documented Formula Preview v0.1**
  - Expert 다섯 번째 단계에서 명시적 `FC[1], FC[2], FC[5], FC[6], FC[7], FC[8]`
    정수 입력만 받아 NetHelp 위치 식을 exact `Fraction`으로 계산
  - MAN-G-CR의 두 `2^63` product guard는 문서 그대로 별도 적용하고,
    식과 guard의 index 묶음 차이는 `DOCUMENTED GROUPING MISMATCH · PURPOSE NEED-DATA`
    로 항상 표시
  - blank/no-auto-fill, current/stale/invalid historical retention과
    `DOCUMENTED_FORMULA_PREVIEW / PARTIAL_SCREENING` authority를 고정
  - `NOT CURRENT DRIVE CONFIG · NO FC/OF WRITE · NO APPLY/SV · NO DRIVE I/O`
  - Motion/Recorder/Status 단위 전파, drive readback, EAS parity와 안전 적합성은 비범위
- **Expert Limits / Protections · Documented Parameter Map v0.1**
  - Expert 여섯 번째 단계에서 `Current Limits`, `Motion Limits and Modulo`,
    `Protections`의 27개 명령 row를 frozen static catalog로 표시
  - authority `DOCUMENTED_PARAMETER_MAP_ONLY`, status `PARTIAL_NEED_DATA`
  - `US[2]`, `ER[5]`, `CL[2..4]`, `XA[4]`, `CL[1]/PL[1]`, `LL[3]/HL[3]`,
    `XM[1]/XM[2]`, FC-based unit 등 9개 문서 충돌을 임의 정규화하지 않음
  - `CL[2] < 2`, `XA[4]` bypass, all-zero no-limit 조합과
    `LL[3]=HL[3]=0`/`HL[2]=0` disable 경고를 항상 표시
  - 로컬 inspect만 GREEN. current config/active protection/추천/검증/command/write/
    Apply/SV/unit propagation/field safety는 `NEED-DATA / NO-GO`
  - focused 69 passed, 전체 1513 passed, runtime smoke와 독립 closeout 완료;
    private Draft PR #2에 `baa2841`로 게시
- **Expert Application Settings · Documented Map v0.1**
  - Expert 일곱 번째 단계에서 `Brake`, `Settling Window`,
    `Inputs and Outputs`의 4/4/5개 row를 frozen static catalog로 표시
  - authority `DOCUMENTED_APPLICATION_SETTINGS_MAP_ONLY`, status
    `PARTIAL_NEED_DATA`; 24 sources, 9 conflicts, 16 warnings, 6 missing
  - `IP + IB[N]`, `GO[N] + OP`는 live status의 문서상 semantics만 표시하고
    `unavailable · not sampled`를 유지
  - local inspect만 GREEN. current config/I/O/brake/default, validation/
    evaluation/command/write/Apply/Revert/SV/output actuation/motion/safety는
    `NEED-DATA / NO-GO`
  - focused 85 passed, 전체 1529 passed, 독립 closeout과 runtime GUI smoke 완료
  - private Draft PR #2에 구현 commit `e577f79`로 게시
- **Expert Hidden Verification – Bode · Documented Map v0.1**
  - Expert 여덟 번째 `BODE DOC MAP` 단계에서 `Tuner Verification Settings`,
    `Current Verification – Bode`, `Velocity / Position Verification – Bode`를
    각 8개 row의 frozen static catalog로 표시
  - authority `DOCUMENTED_HIDDEN_BODE_MAP_ONLY`, status
    `PARTIAL_NEED_DATA`; 7 sources, 4 conflicts, 12 warnings, 8 missing
  - hidden-page visibility는 authority가 아니며 actual `Verify`,
    EAS settings reset/change와 recording control을 제공하지 않음
  - 기존 P1 Bode preview는 OFFLINE MODEL, 이 page는 field experiment의
    documentation map으로 분리. model/measurement parity와 pass/fail을 주장하지 않음
  - local inspect만 GREEN. actual Current ENERGY와 V/P MOTION verification,
    target parity, envelope, recorder provenance, abort/closeout와 quantitative
    acceptance는 `NEED-DATA / NO-GO`
  - pure 14 passed, 영향범위 211 passed in 65.06s, 전체
    1547 passed in 503.66s / exit 0, 독립 source hash 7/7 일치
  - private Draft PR #2에 구현 commit `8073176`로 게시
- **UI lifecycle 안전 보완**
  - 탭 전환 시 공용 workspace 스크롤을 새 페이지 원점으로 복귀
  - shutdown-pending 동안 연결·텔레메트리·access-mode authority 폐기
  - 현재 worker의 `stopped` 뒤에만 `OFFLINE`과 연결 선택기 복구
- **EAS 미연결 UI inventory**
  - Quick 6단계 명칭/순서가 현재 guided flow와 일치
  - Expert User Units는 documented 위치 식 preview만 부분 구현
  - limits/protection은 static documented map만 부분 구현; 값 read/validation/write와
    protection efficacy는 미구현
  - Application Settings의 Brake/Settling/I/O는 static documented map만
    부분 구현; current readback/write/transaction/actuation은 잔여
  - Hidden Current/V/P Bode는 static documented map만 부분 구현;
    actual Verify와 setting mutation/recording은 잔여 `NEED-DATA`
  - time verification, User Units의 drive readback/write와
    EAS page icon/Enter/Apply·Summary recommendation은 잔여
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
| Filter/Scheduling 문서 topology inspector | **완료 · `540877e` · private Draft PR #2** |
| Expert Local Page Status / Errors v0.1 | **완료 · `a20e19a` · private Draft PR #2** |
| Expert User Units · Documented Formula Preview v0.1 | **완료 · `0472ee5` · private Draft PR #2** |
| Expert Limits / Protections · Documented Parameter Map v0.1 | **완료 · focused 69 / 전체 1513 passed + runtime/독립 closeout · `baa2841` · private Draft PR #2** |
| Expert Application Settings · Documented Map v0.1 | **완료 · focused 85 / 전체 1529 passed + runtime/독립 검토 · `e577f79` · private Draft PR #2** |
| Application Settings private Draft PR 게시 | **완료 · `e577f79`** |
| Expert Hidden Verification – Bode · Documented Map v0.1 | **완료 · pure 14 / 영향범위 211 / 전체 1547 passed + runtime/독립 검토 · `8073176` · private Draft PR #2** |
| 실제 Current Bode / V·P Bode 실행 | **NEED-DATA · ENERGY/MOTION 별도 gate · 신뢰 가능한 ETA 없음** |
| Exact filter·gain scheduling evaluator/emulator | **NEED-DATA · 신뢰 가능한 ETA 없음** |

Hidden Bode static map 로컬 closeout과 private 게시는 완료됐다.
이는 근거가 있는 LOCAL/READ-ONLY 계약의 완료이며 모든 EAS 페이지 구현 완료를 뜻하지 않는다.
Actual Bode Verify, exact evaluator와 전체 EAS 패리티, vendor 비공개 알고리즘의
동일 복제는 근거 부족으로 현재 신뢰 가능한 ETA를 제시하지 않는다.

## 다음 자동 진행

1. 잔여 무구동 EAS 세부 페이지를 evidence-first로 비교해 다음 bounded slice를 선정
2. actual Bode는 exact target/config, excitation·travel·thermal envelope,
   recorder provenance, abort/closeout와 quantitative oracle 전까지 잠금
3. exact current config·EAS transaction·output electrical/brake capability 근거 전까지
   evaluator/recommendation/read/write/Apply/SV/actuation은 `NEED-DATA / NO-GO`

## 현장 안전 규칙

1. 우리 앱과 EAS를 동시에 같은 드라이브에 연결하지 않음
2. 연결은 모터 동작 승인이 아님
3. 실제 Enable·커뮤테이션·튜닝·영점·PTP·쓰기·저장은 해당 단계 직전의 별도 확인 필요
4. software STOP은 독립 STO/E-stop이 아니며 현장 E-stop/STO가 즉시 사용 가능해야 함
5. field 결과는 exact revision·identity·조건·raw transcript가 있을 때만 계산
