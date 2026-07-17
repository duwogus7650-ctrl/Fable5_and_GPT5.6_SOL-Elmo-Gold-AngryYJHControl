<!-- scope_progress: 100 -->
<!-- offline_progress: 95 -->
<!-- field_progress: 0 -->
<!-- progress_basis: scope=frozen; offline=full-suite and independent review green for the current dirty tree, with commit/runtime/hardware admission separate; field=NEED-DATA because this revision has no supervised hardware run; percentages are not safety scores -->

# Gold Twitter Quick Tuning + 제한형 단일축 모니터

상세 인계: [`../docs/current-scope-handoff.md`](../docs/current-scope-handoff.md)<br>
상태: **OFFLINE HARDENED CANDIDATE · HARDWARE USE BLOCKED · PRIVATE DRAFT**<br>
업데이트: 2026-07-17 KST

## 현재 기준점

- 브랜치: `codex/quick-single-axis-handoff`
- 기준 HEAD: `d572e4b964f61c7ba2a9f951cd7acbac81e61a5d`
- 상태: 소스·테스트·문서가 수정된 **uncommitted working tree**. commit/push는 하지 않았다.
- 이번 작업에서 DLL, drive 연결, 통전, 모션, `SV`, visible main GUI smoke를 실행하지 않았다.
- 읽기 전용 진행 모니터 PID 16324는 한글 Markdown 표시 수정 코드를 로드한 별도 프로세스로 유지한다.
  PID는 재실행 때 달라질 수 있다.
- 제어창은 사용자가 넘겨주면 화면/상태부터 읽는다. 명시적 승인 전에는 연결 변경이나 motor command를
  보내지 않는다.

## 현재 production 권한

- P1 전류 식별·설계 후보와 P2 속도/위치 식별·설계 후보를 계산하는 코드가 있다. 이 경로는
  통전/회전을 포함하므로 최신 리비전의 감독 실기 전에는 실행하지 않는다.
- `Verify Installed P2 on Motor`는 현재 설치 게인만 판정한다. current-generation commutation
  signature와 durable `P2_LIMITS` transaction을 요구하며 Apply/Save 권한을 만들지 않는다.
- Motor profile은 first-assignment WAL → RAM apply/readback → rollback 또는 단일 `SV`의 bounded
  transaction을 가진다. 최신 흐름은 아직 감독 실기 전이다.
- `FINITE_PTP_LIVE_ENABLED=False`: 제한형 finite PTP는 backend/test만 있고 production live 실행은 잠겨 있다.

## 명시적으로 잠긴 기능

- **P1/P2 gain Apply/Save:** durable pre-assignment gain-trial WAL이 없어 UI/domain/worker 경계에서
  drive I/O 전에 거부한다. trial state machine은 exact `SYNTHETIC_NO_HARDWARE` 회귀 전용이다.
- **P1 Save:** 위 WAL 외에도 real session-bound on-motor verifier가 없다.
- **Feedback direct save:** versioned write/type/range/side-effect/rollback registry 전까지 잠긴다.
- **finite PTP live:** site motion envelope, limit, 정지거리, 독립 E-stop/STO evidence 전까지 잠긴다.

## 닫은 소프트웨어 finding

1. P2 Verify는 current-generation commutation signature token을 UI/worker/algorithm payload까지 결속한다.
2. P1 임시 구성은 첫 assignment 전에 durable `P1_CONFIG` WAL을 만들고, bounds/type/exact restore를
   검증한다. forward와 원본 rollback 권한은 `MO/SO/VX=0` link proof 뒤의 단방향 transition으로
   분리되며, restore 불확실성은 `UNKNOWN`으로 남긴다. 원시 snapshot은 `Decimal`로 먼저 판정해
   sub-ULP 반올림값이 WAL 원본이 되는 것을 막는다.
3. P2 `SD/HL[2]/LL[2]/ER[2]`는 첫 assignment 전 durable `P2_LIMITS` WAL, full-set exact readback,
   enable 전 proof, proof 뒤 limit 동결, safe-state 뒤 단방향 original rollback, full restore 또는
   `UNKNOWN` 계약을 가진다. limit 명령·snapshot·되읽기는 binary float 변환 전에 exact
   integer/signed-32 계약을 검증한다.
4. P1 Save는 UI/worker/domain/transport에서 잠겼고, P1/P2 새 hardware gain trial 자체도 pre-I/O 잠겼다.
5. STOP/Abort cancellation token이 queue pop 뒤에도 telemetry·handler·algorithm까지 유지되어 stale 작업이
   새 세대를 오염시키지 않는다.
6. Motor `UNKNOWN`의 `phase=MOTOR`, `record_id`, ledger 상태가 worker 시작 시 보존되어 query-only audit가
   영구적으로 막히지 않는다.

독립 안전 검토는 위 변경 뒤 **Critical/Important 잔여 안전 finding 없음**으로 판정했다. 최신 문서와
전체 suite를 대상으로 한 독립 integration review도 **blocking finding 없음**으로 종료됐다.

## 최신 오프라인 증거

- 전체 최신 suite: **1206 passed, 1 skipped in 79.24s**
- 독립 reviewer 전체 재실행: **1185 passed, 1 skipped in 83.09s**
- 핵심 8-file 회귀: **629 passed, 1 skipped in 45.79s**
  - P1/P2 domain, persistence audit/lifecycle, worker/UI, energy shutdown/cancellation, operation catalog
- progress monitor 한글 Markdown 회귀: 수정 전 **1 failed** 재현 → 수정 뒤 **26 passed**,
  actual-status smoke **100/95/0 · Korean text preserved**
- P1_CONFIG/P2_LIMITS forward/rollback 권한 분리와 exact audit 회귀: **536 passed, 1 skipped**
- sub-ULP/underflow 명령·snapshot·readback 경계 회귀: **23 passed**
- skip 1건은 CLR/vendor DLL이 없는 오프라인 환경의 명시적 분기다.
- Motor startup recovery 재현은 수정 전 worker/UI 모두 실패했고, 수정 뒤 **2 passed**다.
- gain catalog 계약은 수정 전 `IMPLEMENTED`로 실패했고, `NEED_DATA` + installed-signature gate 수정 뒤
  **3 passed**다.
- 내장 P1 smoke는 수정 전 stale Apply 기대에서 exit 1을 재현했고, media-free 회귀 추가 뒤 **1 passed**다.
- 변경 Python compile/AST와 `git diff --check`는 성공했다. diff check 출력은 기존 LF→CRLF 경고뿐이다.
- 이 결과는 mock/simulation/offscreen 경로만 증명한다. hardware safety·성능·실제 정지거리를 증명하지 않는다.

## 오프라인 closeout

- 문서/UI 계약, compile/AST, diff integrity, 전체 suite, 독립 안전·통합 review를 최신 dirty tree에서
  완료했다.
- commit/push/PR은 하지 않았다. 사용자가 명시적으로 요청할 때만 수행한다.
- 제어 프로그램 runtime 통합과 hardware admission은 아래 현장 gate에 속하며 offline GREEN에 포함하지 않는다.

## 현장 검증 게이트 — `NEED-DATA`

- exact model/part number, firmware/PAL, target identity와 connection generation
- 물리 이동 범위, 출력축 환산, 안전한 +/− 방향
- FLS/RLS/STOP 배선·극성·drive mapping과 양방향 작동 증거
- 최악 통신/샘플 지연을 포함한 정지거리와 여유거리
- 독립 E-stop/STO, 부하 낙하/브레이크/구속 조건
- 저에너지 감독 P1/commutation/P2 transcript와 abort/comms-loss/reconnect/냉간 audit

위 항목 전에는 `field_progress`를 올리지 않고 hardware use/live motion 잠금을 해제하지 않는다.

## 지표 해석

- **범위 100:** 이번 목표가 Quick Tuning + 제한형 Single Axis로 고정됐다는 뜻이다.
- **오프라인 95:** 현재 dirty tree의 fail-closed 변경, 전체 suite와 독립 검토가 끝났다는 표시다.
  commit 여부, hardware 안전 확률이나 전체 EAS 구현률이 아니다.
- **실기 0 / NEED-DATA:** 최신 dirty tree를 hardware에서 실행하지 않았다는 뜻이다.
