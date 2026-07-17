# Quick Tuning + 제한형 단일축 작업 인계서

상태: **OFFLINE HARDENED CANDIDATE · HARDWARE USE BLOCKED · PRIVATE DRAFT**<br>
기준 시각: 2026-07-17 KST<br>
활성 상태판: [`../tasks/status.md`](../tasks/status.md)<br>
후속 장비/센서 매트릭스: [`drive-feedback-validation-matrix.md`](drive-feedback-validation-matrix.md)

## 1. 저장소와 runtime 기준점

- 작업 브랜치: `codex/quick-single-axis-handoff`
- 기준 HEAD: `d572e4b964f61c7ba2a9f951cd7acbac81e61a5d`
- 원격: `duwogus7650-ctrl/Fable5_and_GPT5.6_SOL-Elmo-Gold-AngryYJHControl`
- 현재 인계 대상은 위 HEAD 위의 **uncommitted dirty working tree**다. commit/push/PR 변경은 하지 않았다.
- 기존 사용자 변경과 로컬 산출물을 임의로 정리하거나 삭제하지 않았다.
- 이번 작업은 DLL과 drive를 열지 않았고, 통전·모션·영점 변경·`SV`·visible main GUI smoke를 실행하지 않았다.
- 읽기 전용 progress monitor PID 16324가 한글 Markdown 표시 수정 코드를 로드한 채 응답 중이다.
  PID는 일회성 정보다.
- 제어 프로그램은 새 코드를 로드했다고 가정하지 않는다. 사용자가 제어창을 넘기면 우선 화면과 상태만
  관찰하고, 명시적 승인 전에는 연결 변경 또는 motor command를 보내지 않는다.

## 2. 현재 활성 범위

이번 목표는 다음 두 축으로 한정한다.

1. 현재 Gold Twitter + EnDat 2.2 한 축의 Quick Tuning 기반 기능
   - P1 제한 에너지 R/L 식별과 전류 PI 후보 설계
   - 별도 제한 전류 commutation signature
   - P2 속도/위치 plant 식별과 게인 후보 설계
   - 현재 설치 P2 게인의 bounded on-motor Verify
2. `UM=5` finite PTP만 허용하는 제한형 Single Axis Motion backend

현재 범위에 EAS 전체 패리티, vendor 비공개 알고리즘의 동일 복제, 다축, CAN/EtherCAT, firmware
update, 일반 Jog/Homing/Current/Sine, Gold 계열 전체 자동 호환은 포함하지 않는다.

## 3. production 권한과 잠금

### 3.1 열려 있는 소프트웨어 경로

- P1/P2 식별·설계는 후보를 산출한다. 실제 실행은 통전/회전을 포함하므로 현 리비전의 감독 실기와
  fresh 현장 승인이 없으면 사용하지 않는다.
- `Verify Installed P2 on Motor`는 현재 설치 게인을 대상으로 한다. current-generation commutation
  signature, fresh telemetry, identity/session gate와 durable `P2_LIMITS` transaction을 요구한다.
  GREEN/RED는 verdict일 뿐 새 gain Apply/Save capability가 아니다.
- Motor profile 저장은 first-assignment durable WAL, exact readback, rollback/full readback 또는
  `UNKNOWN`, request-bound 단일 `SV` authority 순서를 가진다.

### 3.2 fail-closed 잠금

- `Apply P1 → RAM`, `Apply P2 → RAM`, `Save P1 → SV`, `Save P2 → SV`는 production에서 잠겨 있다.
  이유는 새 gain assignment 전에 살아남는 durable pre-assignment gain-trial WAL이 없고, 현재 단일
  active-record ledger가 P2 Verify의 `P2_LIMITS` WAL과 중첩 trial을 안전하게 표현하지 못하기 때문이다.
- hardware-capable link의 P1/P2 begin과 legacy P1 `apply_gains()`는 persistence query·snapshot·assignment
  전 typed failure를 반환한다. exact `SYNTHETIC_NO_HARDWARE` marker만 trial 회귀를 연다.
- P1은 별도로 real session-bound on-motor verifier도 없으므로 Save가 transport까지 잠겨 있다.
- Feedback direct save는 versioned registry 전까지 잠겨 있다.
- `FINITE_PTP_LIVE_ENABLED=False`이며 환경변수 우회가 없다.

## 4. 이번 working tree의 핵심 보강

### 4.1 P1_CONFIG durable rollback

- P1의 모든 fallible admission을 첫 write 앞으로 옮겼다.
- 임시 `KP[1]/KI[1]/UM/SC[8]/CA[42..44]/CA[70]/SE[1..7]` 변경은 첫 assignment 전에 durable
  `P1_CONFIG` WAL을 만든다.
- WAL 원본은 drive의 원시 응답을 `Decimal`로 먼저 판정한다. discrete register는 exact integer,
  연속 register는 float 변환이 값을 바꾸지 않는 경우만 동결하며, sub-ULP 소수는 WAL/write 전에 RED다.
- prepared applied values는 register별 mutation bounds와 type/range를 만족해야 한다. frozen profile과
  같다는 이유로 bounds를 우회할 수 없다.
- forward authority는 bounded/applied 값만 허용한다. link가 `MO/SO/VX=0`을 직접 확인한 뒤의 단방향
  rollback transition만 frozen original 값을 허용하며, 전환 뒤 forward authority는 되살아나지 않는다.
- same-session closeout은 원 profile을 되읽고, post-reset audit은 original profile exact match에서만
  temporary-config lock을 해제한다. drift/mixed/불안정 read는 `UNKNOWN`을 유지한다.
- P1 Save는 verifier와 gain-trial WAL이 없어 잠긴다.

### 4.2 P2_LIMITS와 installed-gain Verify

- standalone Verify도 current-generation commutation signature token을 UI → worker → algorithm까지
  전달하고, stale/foreign token은 drive I/O 전에 거부한다.
- `SD/HL[2]/LL[2]/ER[2]`는 첫 assignment 전 durable `P2_LIMITS` WAL을 만들고 전 항목 exact
  apply/readback proof 뒤에만 enable을 허용한다.
- 네 limit의 원시 응답은 binary float 변환 전에 finite·integral·signed-32를 검사한다. 반올림되어
  정수처럼 보이는 소수 literal/readback은 profile authority나 applied proof를 만들지 못한다.
- applied proof 뒤에는 limit assignment를 동결한다. link가 `MO/SO/VX=0`을 직접 확인한 단방향
  rollback transition 뒤에만 signed-32-bit exact original profile 복원을 허용한다.
- register 거부, silent mismatch, timeout, partial restore, session change는 성공으로 승격되지 않는다.
  full original readback을 증명하지 못하면 durable `UNKNOWN`으로 잠긴다.
- installed-gain Verify는 gain을 바꾸지 않고 verdict만 반환한다.

### 4.3 STOP/Abort generation 결속

- tuning token이 worker queue pop 뒤에도 fresh telemetry 전후, handler, algorithm `cancel_fn`과
  `_EnergyAwareLink`까지 유지된다.
- Abort는 해당 generation을 취소하고, 이미 취소된 queued 작업이 새 generation을 오염시키지 않는다.
- STOP은 계속 sticky safety request이며, closeout은 전류/enable 제거를 확인하지만 기계적 정지나 독립
  STO를 증명한다고 주장하지 않는다.

### 4.4 persistence와 Motor recovery

- active production 원장 scope는 P1_CONFIG, P2_LIMITS, Motor다. legacy/offline P2 gain record 판정
  엔진은 기존 ambiguous-SV incident를 위해 호환 유지하지만 새 production gain trial을 만들지 않는다.
- Motor `UNKNOWN` status의 `phase=MOTOR`, `record_id`, `ledger_error`가 worker startup/status publisher/UI
  validator를 통과한다. 따라서 안전 잠금은 유지하면서 유일한 query-only post-reset audit 버튼도 남는다.
- query-only audit은 `SV`, `LD`, `RS`, assignment, enable, motion을 보내지 않는다.

### 4.5 operation catalog와 UI

- P1/P2 Apply/Save는 위험 분류를 유지한 채 `OperationStatus.NEED_DATA`로 표시한다.
- installed P2 Verify는 `trial_capability`가 아니라 `commutation_signature` + `P2_LIMITS` gate로 설명한다.
- Quick/Expert 모두 gain Apply/Save가 잠겼음을 표시하며 결과 수신으로 버튼이 다시 열리지 않는다.

## 5. 오프라인 검증 증거

최신 핵심 회귀:

| 집합 | 결과 | 의미 |
|---|---:|---|
| 전체 repository suite | **1206 passed, 1 skipped in 79.24s** | 최신 dirty tree의 root 재실행 |
| 독립 reviewer 전체 재실행 | **1185 passed, 1 skipped in 83.09s** | 구현자와 분리된 재검증 |
| P1/P2 domain + persistence audit/lifecycle + worker/UI + energy shutdown + catalog | **629 passed, 1 skipped in 45.79s** | mock/simulation/offscreen, no hardware I/O |
| progress monitor 한글 Markdown 회귀 | 수정 전 **1 failed** → 수정 뒤 **26 passed**, actual smoke **100/95/0** | Qt raw `<br>` 정규화, 한글 887자 보존 |
| P1_CONFIG/P2_LIMITS 권한 분리와 exact audit | **536 passed, 1 skipped in 41.82s** | Decimal 원시 판정, forward/rollback 단방향 전환, no hardware I/O |
| Motor startup `MOTOR` record propagation | 수정 전 2 failed → 수정 뒤 **2 passed** | record ID와 audit availability 보존 |
| gain operation catalog 계약 | 수정 전 1 failed → 수정 뒤 **3 passed** | Apply/Save NEED_DATA, installed Verify signature gate |
| built-in P1 smoke 계약 | stale Apply 기대에서 exit 1 → media-free 회귀 **1 passed** | production Apply lock과 smoke 일치 |
| 독립 안전 검토 | Critical/Important 잔여 없음 | production gain lock 전 drive mutation 0 확인 |
| 독립 integration review | blocking finding 없음 | worker bypass, UI/catalog/docs, full suite 재검토 |

skip 1건은 CLR/vendor DLL unavailable 오프라인 분기다. 변경 Python compile/AST와
`git diff --check`도 성공했으며 diff 출력은 기존 LF→CRLF 경고뿐이다. 위 수치는 hardware safety,
실제 응답, 성능, 정지거리 또는 whole-drive durability를 증명하지 않는다.

## 6. 오프라인 closeout

1. 최신 문서/UI 문자열, compile/AST, diff integrity, 전체 suite와 독립 review를 완료했다.
2. exact base HEAD와 dirty-tree 수치를 이 문서와 상태판에 기록했다.
3. commit/push/PR은 사용자 지시가 있을 때만 수행한다.
4. 제어창/runtime 확인과 hardware admission은 아래 현장 `NEED-DATA`의 별도 단계다.

## 7. 현장 `NEED-DATA`

- exact drive model/part number, firmware/PAL, hashed identity와 connection generation
- 물리 travel, output ratio, 안전한 +/− 방향
- FLS/RLS/STOP 배선·극성·drive mapping과 양방향 작동 증거
- 최악 통신/샘플 지연을 포함한 정지거리·여유거리
- 독립 E-stop/STO, 부하 낙하/브레이크/구속 조건
- 다른 master의 배타적 제어권
- 저에너지 P1/commutation/P2, abort/comms loss/reconnect/cold audit의 supervised transcript

이 자료 전에는 hardware 사용, production gain mutation, finite PTP live gate를 열지 않는다.

## 8. 안전한 재개 순서

1. 오프라인 전체 suite와 최종 review를 마친다.
2. 사용자가 명시적으로 넘긴 제어창은 화면과 runtime identity부터 read-only로 확인한다.
3. 드라이브가 disabled·정지·무전류이고 현장 gate가 갖춰졌을 때만 통제된 앱 재시작을 별도 승인받는다.
4. query-only identity/firmware/PAL/active persistence status를 확인한다.
5. hardware 단계는 각 단계마다 새 승인을 받아 P1 식별 → commutation signature → P2 식별 →
   installed-gain Verify 순으로 진행한다. Production gain Apply/Save는 계속 제외한다.
6. finite PTP는 site envelope와 독립 stop evidence가 완성된 별도 승인 작업으로 남긴다.

## 9. 완료 의미

오프라인 GREEN은 exercised code path와 fail-closed 음성 대조군이 통과했다는 뜻이다. 최신 리비전의
supervised hardware transcript, closeout, recovery, cold audit와 motion envelope가 없으면 `hardware
safe`, `field complete`, `Gold-compatible`을 선언하지 않는다.
