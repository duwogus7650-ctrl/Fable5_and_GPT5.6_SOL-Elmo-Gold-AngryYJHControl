# Quick Tuning + Single Axis + Expert Candidate Lab v2 + Page Status 작업 인계서

상태: **PAGE STATUS INSPECTOR OFFLINE VERIFIED · PRIVATE DRAFT UPDATE PENDING · CONTROL APP OPEN · MOTOR ACTION NOT RUN**<br>
기준 시각: **2026-07-18 18:59 KST**<br>
활성 상태판: [`../tasks/status.md`](../tasks/status.md)<br>
후속 장비/센서 매트릭스: [`drive-feedback-validation-matrix.md`](drive-feedback-validation-matrix.md)

## 1. 저장소와 runtime 기준점

- 작업 브랜치: `codex/quick-single-axis-handoff`
- 작업 시작 기준 HEAD: `1c12808e2d035ae202ee83013f397d52a420eae2`
- Single Axis 구현 HEAD:
  `6f1250ffbdd558e65499e4193d69a1872269c729`
- Expert v2 검증·게시 HEAD:
  `dfda7fef1a63ab05a26691c5b793a6bf62cb3cd2`
- Filter/Scheduling evidence inspector 검증·구현 HEAD:
  `540877ea2b65866bb45aeaad4fc88cd836258e0a`
- 새 저장소 `origin`:
  `duwogus7650-ctrl/Fable5_and_GPT5.6_SOL-Elmo-Gold-AngryYJHControl`
- 원본 저장소 `source`:
  `duwogus7650-ctrl/Fable5-Elmo-Gold-AngryYJHControl`
- Quick/Single Axis/Expert·Filter/Scheduling evidence·안전 경계 변경은 새 비공개
  `origin`의 기존 Draft PR #2에 위 구현 HEAD까지 게시했다. 공개 원본 `source`에는
  push하지 않았다.
- 기존 사용자 `media/smoke_main.png` 변경은 working tree에 보존하고 게시에서 제외했다.
- 최신 working tree의 앱으로 Read Only field admission을 수행했고,
  host-observed 세션 증거를 보존했다.
- 후속 source 변경 뒤 Python 3.14로 다시 실행해 1366×820 OFFLINE/READ ONLY,
  page-scroll reset, Quick/Expert 공통 제어, Expert offline/locked와
  Single Axis Snapshot `UNKNOWN`/zero-new-I/O 고지를 재확인했다.
- 같은 최신 실행창에서 P1 `fc=430.129 Hz · PM=55.69 deg`와
  P2 `K_a=5.794e6 cnt/s²/A_peak · B=1e-7 A_peak/(cnt/s)`의
  `MODEL GATE PASS · D=0.5794 1/s · bandwidth=457.500 rad/s`를 관찰했다.
  K_a 편집 뒤 `STALE` 전환과 기준값 복원·재계산 PASS도 관찰했다.
- filter/scheduling inspector를 포함한 최신 source를 다시 실행해
  `OFFLINE · READ ONLY`, filter type `4 · Notch`,
  `Scheduled position filter`, `GS[2]=64 · SPEED`를 관찰했다.
  다섯 문서 충돌과 `NO MODEL · NO EMULATION · NO WRITE · NO DRIVE I/O`가
  동시에 표시되고 Apply/Save가 계속 잠긴 상태를 확인했다.
- Page Status inspector를 포함한 최신 source를 다시 실행해 네 번째
  `STATUS / ERRORS` 단계에서 `OVERALL PARTIAL · LOCAL STATUS ONLY`,
  P1 `MISSING`, P2 `BLOCKED`, Evidence `DOCUMENTED PARTIAL · 5 unresolved
  document conflicts`를 관찰했다. `NOT EAS ENTER/APPLY STATE · NOT INSTALLED ·
  NO DRIVE I/O`와 Apply/Save `LOCKED`가 동시에 유지됐다.
- 이 admission에서는 motor enable, commutation, tuning, PTP 또는 setting write를
  실행했다는 증거가 없으며, 그런 동작을 검증한 것으로 간주하지 않는다.
- progress monitor는 `tasks/status.md`를 읽어 갱신 중이다.
- 세션 증거는 EAS 또는 다른 master의 동시 연결 여부를 기록하지 않는다.
- Read Only 세션을 정상 종료한 뒤 EAS 설치본을 실행했고, drive에 연결하지 않은 상태에서
  Quick Automatic Tuning, Expert Tuning tree, Motion - Single Axis UI를 직접 매핑했다.
  Connect/Enable/Run/Apply/Save는 누르지 않았고 직접 장비 식별자는 기록하지 않았다.

## 2. 현재 범위와 경계

### 2.1 Quick Tuning guided flow

- P1 제한 에너지 R/L 식별과 전류 PI 후보 설계
- 별도 제한 전류 commutation signature
- P2 속도/위치 plant 식별과 게인 후보 설계
- 현재 설치 P2 게인의 bounded on-motor Verify
- P1 / commutation / P2 / Verify / Abort는 Quick과 Expert 화면에서 공통 표시

실제 P1/P2/commutation/Verify는 모터 통전 또는 회전을 포함한다.
오프라인 구현 완료가 현장 실행 승인이나 안전성 판정을 뜻하지 않는다.

### 2.2 Single Axis

- `UM=5` finite-PTP 오프라인 backend와 제한·판정 kernel은 MODEL 검증됨
- `Single Axis Safety Snapshot v1`은 기존 Axis Summary가 이미 읽은
  `MO/SO/MF/PS/SR/MS`만 소비하는 pure zero-new-I/O projection
- UI에는 `DRIVE-REPORTED · MODEL DECODE · NOT STO TEST EVIDENCE`를 고정 표시
- `SR[3:0]`, `SR4`, `SR12`, `SR13`, `SR14`, `SR15`, `SR[11:8]`을
  2013 Gold command reference 기반 MODEL로만 해석
- 누락·NaN/Inf·bool·비정수·초대형 정수·범위 위반은 전체 semantic projection `UNKNOWN`
- 2013 reference에서 reserved인 SR bit, amplifier code와 profiler code 11–15도
  `UNKNOWN`; 현재 firmware에서 의미를 추정하지 않음
- `SO↔SR4`, `PS↔SR12` 불일치는 raw 값은 보존하되 authority를
  `INCONSISTENT · AUTHORITY UNKNOWN`으로 폐기
- current worker가 아닌 signal과 shutdown-pending/disconnect 뒤 signal은 표시를 복구하지 못함
- telemetry authority 상실·energizing 중에는 safety projection만 blank하고,
  current worker가 보내는 `motion_config_unknown`/energy-closeout latch는 계속 수용
- 이 projection은 STO 배선·반응시간·torque isolation·독립 E-stop 시험의 증거가 아님
- `FINITE_PTP_LIVE_ENABLED=False`
- live PTP catalog 상태는 `NEED-DATA`
- 기계 travel, 방향, output ratio, limit 입력, 정지거리, 독립 E-stop/STO 근거 전에는
  live gate를 열지 않는다.

### 2.3 Expert Candidate Lab v2

- Current P1 후보 계산은 pure no-I/O LOCAL MODEL
- P1은 R/L, sampling period, target bandwidth, KI rule을 명시 입력
- P2는 완전한 passing P1 MODEL과 `K_a [cnt/s²/A_peak]`,
  `B [A_peak/(cnt/s)]`를 명시 입력
- P1 candidate KP/KI와 bounded read-only Bode preview,
  P2 candidate KP[2]/KI[2]/KP[3]과 modeled margins 제공
- 새 P1 성공 시 종속 offline P2를 폐기하고, invalid 입력은 이전 완전한 결과를 보존
- candidate와 설치 drive readback을 별도 authority로 표시
- 계산은 worker/link/job/drive command를 만들지 않고 Apply/Save/Verify 권한을 바꾸지 않음
- 결과는 현재 Gold Twitter/motor/TS 단일점 교정 `MODEL`; 다른 motor/feedback/
  firmware/Gold 제품 일반화 또는 EAS 내부 알고리즘 동등성을 주장하지 않음
- filter는 `NEED-DATA`, gain scheduling은 `GS[2]=0 ONLY`; KV/GS/KG emulation/write 없음
- 상세 계약: [`expert-tuning-offline-v2.md`](expert-tuning-offline-v2.md)

### 2.4 Expert Filter / Scheduling Contract Inspector v0.1

- 세 번째 Expert 단계에서 MAN-G-CR 1.406의 filter type, controller KV slot,
  `GS[2]` mode category와 KG table topology를 순수 로컬로 탐색
- `DOCUMENTED TOPOLOGY ONLY · NO MODEL · NO EMULATION · NO WRITE`
- KG `1..504/1..945`, scheduled position `KV[45]/KV[50]`, KV
  `1..90/KV[91..95]`, position boundary `GS[18,20]/GS[19],GS[20]`,
  speed scheduling `GS[1,6,8,10]`/`GS[6],GS[7],GS[8] Reserved`
  문서 충돌을 어느 한쪽으로 정규화하지 않고 그대로 표시
- 누락된 SimplIQ §15.4, B01G parity, exact filter 식·discretization·range와
  scheduling interpolation/boundary는 `NEED-DATA`
- inspector 조작은 worker/link/command를 만들지 않고 P1/P2 candidate, installed
  readback, Verify/Apply/Save, dispatch authority를 바꾸지 않음
- 상세 계약:
  [`expert-filter-scheduling-evidence-v0.1.md`](expert-filter-scheduling-evidence-v0.1.md)

### 2.5 Expert Local Page Status / Errors v0.1

- 네 번째 Expert 단계에서 현재 프로세스의 P1/P2/evidence immutable 상태만 분류
- 상태는 `MISSING / BLOCKED / STALE / INVALID / CURRENT LOCAL MODEL /
  DOCUMENTED PARTIAL`; 전체 verdict는 항상 `PARTIAL`
- P1 수치 coherence, 정확한 P1↔P2 object binding과 P2 재계산,
  canonical filter/scheduling snapshot 전체 동등성을 fail-closed로 확인
- 입력 편집 중 숨겨진 Status page는 dirty만 기록하고 page 진입 시 한 번 재분류
- page 열기와 `Open` 이동은 candidate, installed readback, `_vp_result`, dispatch,
  Verify/Apply/Save authority를 바꾸지 않고 worker/link/command/file/drive I/O를 만들지 않음
- EAS idle/changed/warning/error icon parity, Enter/Apply/Revert, saved-last-page,
  Summary recommendation과 installed-drive 판정은 구현하지 않음
- 상세 계약: [`expert-page-status-v0.1.md`](expert-page-status-v0.1.md)

현재 범위에는 다축, CAN/EtherCAT, firmware update, 일반 Jog/Homing/Current/Sine,
Gold 계열 전체 자동 호환 또는 EAS 전체 패리티가 포함되지 않는다.

## 3. 연결 access-mode 계약

### 3.1 Read Only — 기본값

- UI 기본 선택은 `READ ONLY`
- `ElmoLink` 생명주기에서 observe-only latch는 단방향이며 되돌릴 수 없음
- bare query allowlist와 software safe-shutdown만 허용
- admission 전에 `MO/SO/VX/PS/MF`를 두 번 읽어 완전히 일치해야 함
- 입장 조건은 `MO=0`, `SO=0`, `VX=0`, `MF=0`, `PS=-2/-1`
- requested mode, transport의 명시적 `access_mode`, worker가 반환한 mode가 모두 일치해야 함
- transport mode 속성 누락·예외·중간 변경은 요청값으로 대체하지 않고 연결을 거부

### 3.2 Supervised Control — 연결별 1회 권한

- 선택 후 기본 Cancel인 확인창을 통과해야 worker를 구성
- 연결 종료·실패 후 자동으로 Read Only로 복귀
- 연결 자체는 Enable, 모션, commutation, tuning, `PX=0`, 파라미터 쓰기,
  `SV`를 승인하거나 자동 실행하지 않음
- ordinary mutation UI는 admitted connection + fresh telemetry +
  `SUPERVISED_CONTROL` + `MO=0`을 모두 요구
- worker mode 불일치나 구성 실패 뒤 Port/Connection Type/Access Mode 선택기를 복구

software STOP은 독립 STO/E-stop이 아니며, vendor call이 진행 중이면 즉시성이 보장되지 않는다.

## 4. production 잠금과 recovery

- `Apply P1 → RAM`, `Apply P2 → RAM`, `Save P1 → SV`, `Save P2 → SV`는
  현재 production에서 `NEED-DATA` 잠금
- P1 임시 설정은 첫 assignment 전에 durable `P1_CONFIG` WAL을 요구
- installed P2 Verify의 limit 변경은 첫 assignment 전에 durable `P2_LIMITS` WAL을 요구
- 원시 수치 판정, exact readback, 단방향 rollback, full original-profile closeout을
  증명하지 못하면 `UNKNOWN`을 유지
- current-generation commutation signature token을 UI → worker → algorithm까지 결속
- STOP/Abort는 monotonic generation에 결속되어 stale queued tuning을 실행하지 않음
- query-only persistence audit은 `SV`, `LD`, `RS`, assignment, enable, motion을 보내지 않음
- Feedback direct save는 versioned registry가 완성될 때까지 잠금

## 5. 2026-07-18 UI와 독립 안전 리뷰

### 5.1 1366×820 레이아웃

별도 Access Mode form row가 테마별 최소 높이를 43–62px 올리는 회귀를 만들었다.
모드 선택기를 `CONNECTION` 제목 행에 항상 보이는 compact selector로 옮기고,
긴 설명은 tooltip과 Connect 버튼 상태에 유지했다.

### 5.2 독립 리뷰에서 발견·수정한 경계

1. transport `access_mode`가 없을 때 requested mode로 대체하던 fallback 제거
2. worker mode 불일치 뒤 Port/Connection Type 선택기가 잠기는 복구 결함 수정
3. 비-DriveWorker test double이 emitted info만으로 mode를 자기서명하던 분기 제거

생산 경계를 느슨하게 하지 않고 기존 test double이 의도한 모드를 명시하도록 정비했다.

### 5.3 현장 관찰 뒤 추가한 UI lifecycle 경계

- 공용 `workspace_scroll`이 이전 페이지의 scroll value `923`을 유지해
  Status가 흰 화면처럼 보이는 현상을 RED로 재현했다.
- 실제 페이지가 바뀔 때만 수평·수직 스크롤을 새 페이지 원점으로 초기화하고,
  같은 페이지 재선택은 현재 위치를 보존한다.
- Disconnect/창 닫기 요청 직후 fresh queued telemetry가 도착하면 worker의
  `stopped` 전에도 authority가 다시 보일 수 있던 종료 경계를 RED로 재현했다.
- `shutdown-pending` latch에서 connection admission, telemetry, access-mode authority를
  즉시 폐기하고, late telemetry/connected/failed에도 `DISCONNECTING`,
  energy `UNKNOWN`, Connect/port/type/access-mode 잠금을 유지한다.
- 현재 worker의 sender-bound `stopped` 뒤에만 latch를 해제하고 `OFFLINE`과
  연결 선택기를 복구한다.

### 5.4 EAS 미연결 Quick/Expert/Single Axis 기준선

- Quick Automatic Tuning의
  `Initialization → Current Identification → Current Design → Commutation →
  Velocity & Position Identification → Velocity & Position Design` 6단계를 확인했다.
- Expert tree에서 User Units, Limits/Protections, Application Settings,
  Current Identification/Design/Verification-Time, Commutation,
  Velocity/Position Identification/Design/Scheduling/Verification-Time, Summary를 확인했다.
- Single Axis에서 motion status, digital I/O, `STO1/STO2/ERR`, UM mode,
  Enable, Current/Stepper/Sine Reference, PTP absolute/relative, Terminal과
  2-chart Recorder 구성을 확인했다.
- target는 EAS에서 `Disconnected`였고 모든 실행·다운로드·저장 동작은 수행하지 않았다.
- 세부 표와 현재 구현 차이는
  [`eas-feature-matrix.md`](eas-feature-matrix.md)의
  `2026-07-18 EAS 미연결 UI 관찰 기준선`에 기록했다.

## 6. Elmo 로컬 자료 증분 감사

- 로컬 Elmo root: **59 files / 5,691,086,215 bytes**
- 전체 파일 SHA-256과 ZIP/RAR member 목록을 추출 없이 기록
- `Version 1.1.16.0 B01 for customers.zip`
  - SHA-256:
    `6A79E0C2956EA643916FFF5526450BEB66D47BAE6C8DB1C7E92A993CF8B4C74F`
  - member:
    `NGDrive 01.01.16.00 08Mar2020B01G.gabs`
- 위 member 이름은 현재 personality 문자열과 파일명 수준에서 일치하지만,
  B01/B01G 의미·board 적합성·flashing 안전성을 증명하지 않는다.
- firmware flashing은 이번 작업의 승인 범위가 아니다.

세부 목록은 [`local-elmo-artifact-audit.md`](local-elmo-artifact-audit.md)에 있다.

## 7. 최신 오프라인 증거

| 증거 | 결과 | 주장 범위 |
|---|---:|---|
| 전체 repository suite | **1448 passed, 0 failed in 277.69s** | Expert v2, filter/scheduling evidence와 Page Status inspector를 포함한 최신 working tree의 Python/mock/offscreen 경로 |
| Expert P1/P2·Evidence·Page Status·UI·catalog 집중 회귀 | **112 passed, 0 failed in 74.68s** | immutable local models/evidence, exact binding/coherence, strict inputs, 문서 충돌 5건, zero-I/O·authority isolation, hidden-page dirty refresh, 세 스킨 1366×820 |
| Page Status pure projection | **10 passed** | missing/blocked/current/stale/invalid, forged evidence, mutated P2, I/O poison |
| Page Status 독립 리뷰 | RED 5건 수정 뒤 **잔여 HIGH/MEDIUM/LOW 없음** | coherence-before-stale, canonical evidence, P2 MISSING, hidden-page one-shot refresh |
| Page Status 최신 runtime smoke | **P1 MISSING · P2 BLOCKED · Evidence DOCUMENTED PARTIAL** | Python 3.14, 1366×820, OFFLINE/READ ONLY; LOCAL STATUS ONLY, NOT EAS ENTER/APPLY, NOT INSTALLED, Apply/Save LOCKED |
| Filter/scheduling 최신 runtime smoke | **Notch · Scheduled position · GS[2]=64 SPEED** | Python 3.14, 1366×820, OFFLINE/READ ONLY; 다섯 문서 충돌, NO MODEL/EMULATION/WRITE/DRIVE I/O와 Apply/Save LOCKED 확인 |
| Expert v2 수치·UI·catalog 집중 회귀 | **74 passed, 0 failed in 44.40s** | P1→P2 MODEL, provenance·mutation/음성 대조, zero-I/O, stale authority, 세 스킨 1366×820와 palette 격리 |
| Expert v2 독립 리뷰 | HIGH 1 + MEDIUM 1 RED 재현 후 **5 passed** | 다른 plant의 P1 자기서명·모순 delegate PASS·입력 편집 뒤 stale PASS 차단 |
| Expert v2 최신 runtime smoke | **P1 PASS · P2 PASS · edit→STALE→recalculate PASS** | Python 3.14, 1366×820, OFFLINE/READ ONLY; drive/worker/command I/O 없음 |
| Single Axis snapshot 집중 회귀 | **346 passed, 0 failed in 127.18s** | decoder·UI·catalog·generation·telemetry·shutdown·session log·motion |
| 연결·텔레메트리·모니터·테마 집중 회귀 | **204 passed** | access-mode와 UI lifecycle |
| 1366×820 세 테마 회귀 | **33 passed** | qdd/amber/angrybirds geometry |
| 독립 리뷰 3개 음성 대조 | RED 재현 후 **3 passed** | mode 누락·복구·자기서명 |
| 페이지 전환 스크롤 집중 회귀 | RED `923 != 0`, 수정 후 **67 passed** | 새 페이지 원점·같은 페이지 위치 보존 |
| 종료 중 authority 집중 회귀 | **169 passed** | fresh/stale queued signal과 shutdown latch |
| 추가 UI/motor-safety 회귀 | **182 passed** | persistence/status/system 포함 |
| 종료 경계 독립 재검토 | **102 passed** | prior P1 해소, 잔여 finding 없음 |
| `git diff --check` | **exit 0** | whitespace error 없음; LF→CRLF 경고만 존재 |

유용한 실패 이력:

- 강화된 access-mode 계약 직후 전체 suite는 **1285 passed / 44 failed**였다.
- 원인은 정상 admission을 흉내 내던 기존 fake link/worker가 transport 또는 requested mode를
  명시하지 않은 것이었다.
- production fallback을 복원하지 않고 fixture 계약을 명시해 전체 GREEN으로 회복했다.

이 증거는 실제 드라이브 응답, 전류 인가, commutation, 성능, 정지거리,
whole-drive durability 또는 field safety를 증명하지 않는다.

### 7.1 Read Only field admission 증거

증거 파일:
[`field-read-only-admission-20260718-1418-closed.aysession.json`](field-read-only-admission-20260718-1418-closed.aysession.json)

- SHA-256:
  `C8E818BBF8690A14DC88503E3A2838EE448D3B336A18FE57E7C8E3BC8025CF7A`
- `schema_version=1`, `evidence_class=HOST_OBSERVED_NOT_DRIVE_HISTORY`
- export 시각: `2026-07-18T05:25:04.794496Z`
  = **2026-07-18 14:25:04.794496 KST**
- 선언/실제 이벤트 수: **12 / 12**, `dropped_count=0`, `capacity=512`
- connection event 시각:
  `2026-07-18T05:16:58.435305Z`
  = **2026-07-18 14:16:58.435305 KST**
- host가 기록한 firmware:
  `Twitter 01.01.16.00 08Mar2020B01G`
- host가 기록한 boot:
  `DSP Boot 1.0.1.6 12Feb2014G`
- host가 기록한 PAL: `90`
- `Gold Drive`는 **application classification이며 board readback이 아니다**.
- 최초 fresh telemetry는 `MO=0`, `vel=0`, `iq=0`이었다.
- 이어진 raw-axis status는 `MO=0`, `SO=0`, `MF=0`이었다.
- 마지막 event는 `connection.closed`, reason은 `worker stopped`이며,
  `2026-07-18T05:24:27.882689Z`
  = **2026-07-18 14:24:27.882689 KST**에 기록됐다.
- 이 close event는 host worker/connection lifecycle의 정상 종결을 증명하지만,
  종료 직전 drive-state readback이나 물리적 energy isolation을 증명하지 않는다.
- 직접 serial/port/device identity는 기록하지 않고 익명 target label만 유지한다.

선행 파일
[`field-read-only-admission-20260718-1418.aysession.json`](field-read-only-admission-20260718-1418.aysession.json)은
close 전의 **pre-close snapshot**이며 주 증거가 아니다.

- SHA-256:
  `145534764C3E521FAA808D34E0E95A24E96619A374E9031ED3D60938447223B1`
- **11 / 11 events**, `dropped_count=0`
- final closed log의 event 1–11은 payload와 event identity가 같고,
  lifecycle 종결에 따라 scope만 `CURRENT`/`REJECTED`에서 `HISTORICAL`로 재분류됐다.
- final closed log가 완결된 주 증거이고, pre-close snapshot은 시간순 계보를 보존하는 보조 증거다.

텔레메트리 authority에는 짧은 이탈이 있었다.

- **2026-07-18 14:19:32.364886–14:19:32.378222 KST**에
  sequence `690`–`694`의 5개 sample이 `UI_REJECTED`로 기록됐다.
- authority-lost event는
  **2026-07-18 14:19:32.368249 KST**에 발생했고,
  `energizing=false`였다.
- sequence `695`에서
  **2026-07-18 14:19:32.383226 KST**에 authority가 복구됐다.
  lost→restored host-event 간격은 약 **14.98 ms**다.
- rejected sample 자체의 payload는 `telemetry_valid=true`, `MO=0`, `vel=0`, `iq=0`이지만,
  freshness가 `UI_REJECTED`이므로 current-state authority로 사용하지 않는다.
- `OBSERVED`: sequence `690`–`694`의 host-source age는 각각
  **1514.2 / 1295.3 / 1077.4 / 859.9 / 639.8 ms**였다.
- `DERIVED`: 다섯 sample 모두 **0.5 s source-age gate**를 초과했고,
  sequence `690`은 **1.5 s UI-age gate**도 약 14 ms 초과했으므로
  현재-state authority에서 제외된 경로가 재현된다.
- `INFERRED`: 약 220–223 ms 간격으로 생성된 sample이 UI에서 약 3 ms 간격으로
  몰려 처리된 패턴은 약 1.5 s UI event-loop backlog와 일치한다.
  어떤 UI/OS 동작이 직접 backlog를 유발했는지는 **UNVERIFIED**다.
- 이 event 묶음은 transport 또는 motor fault의 증거가 아니며,
  `MO=0`, `energizing=false`, 복구 시 `motor_enabled=false`였다.

이 자료가 증명하는 범위는 **host가 해당 시각에 연결·정지/비활성 telemetry·raw status를
관찰했고, stale/replayed 의심 sample을 current state에서 제외한 사실**이다.
`HOST_OBSERVED_NOT_DRIVE_HISTORY`이므로 다음을 증명하지 않는다.

- transport가 실제로 query만 보냈다는 원시 명령 이력
- Read Only access-mode의 end-to-end enforcement 또는 쓰기 명령 부재
- admission의 두 번 일치 sweep 전체와 `VX/PS` 값
- 독립 E-stop/STO, 다른 master 부재, setting 불변, motor safety
- enable, commutation, tuning, PTP, 정지거리 또는 field performance

따라서 좁은 host-observed admission은 **OBSERVED**지만,
telemetry integrity는 원인 미확정 blip 때문에 **YELLOW**,
motor action과 hardware-safety 판정은 계속 **NEED-DATA**다.

## 8. 현장 상태와 `NEED-DATA`

사용자가 현장에 복귀했고 Read Only admission까지는 수행했다. 상태판의 field 5%는
이 host-observed admission/close 증거만 가리키는 계획 지표다. 현재 working tree로
motor action은 아직 실행하지 않았으므로 **motor-action field validation은 0%**다.

다음 자료는 live PTP와 넓은 실기 판정 전에 필요하다.

- exact drive model/part number, firmware/PAL, hashed identity, connection generation
- motor/encoder 구성과 pole-pair, current convention, counts/rev
- 물리 travel, output ratio, 안전한 +/− 방향
- FLS/RLS/STOP 배선·극성·drive mapping과 양방향 작동 증거
- 최악 통신/샘플 지연을 포함한 정지거리·여유거리
- 독립 E-stop/STO, 부하 낙하/브레이크/구속 조건
- 다른 master의 배타적 제어권
- 저에너지 P1/commutation/P2, abort/comms loss/reconnect/cold audit의 raw transcript

## 9. 안전한 재개 순서

1. 최신 source로 제어창을 OFFLINE 재시작해 page-scroll과 shutdown UI를 smoke
2. EAS를 **미연결 상태**에서 캡처하고 Quick/Single/Expert 화면·상태부터 매핑
3. EAS와 우리 앱의 동시 drive 연결이 없음을 확인
4. Read Only 재연결이 필요하면 mutation controls disabled와 freshness를 확인하고
   admission sweep의 `MO/SO/VX/PS/MF` 원시 transcript를 보존
5. 실기 조건과 exact 제한값을 고정한 개별 동작만 별도 확인 후 실행
6. P1 → commutation signature → P2 → installed-gain Verify 순서로 raw transcript 보존
7. Production gain Apply/Save와 finite PTP live는 별도 gate로 유지

## 10. 완료 의미

현재 `READ ONLY FIELD ADMISSION OBSERVED`는 host-observed 연결과 정지/비활성 readback을
보존했다는 뜻이다. 최신 리비전의 supervised hardware transcript, closeout, recovery,
cold audit와 motion envelope가 없으면 `hardware safe`, `field complete`, `EAS parity`,
`Gold-compatible`을 선언하지 않는다.
