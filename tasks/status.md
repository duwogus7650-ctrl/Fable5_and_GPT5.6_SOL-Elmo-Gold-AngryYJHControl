<!-- scope_progress: 100 -->
<!-- offline_progress: 92 -->
<!-- field_progress: 40 -->
<!-- progress_basis: Planning indicators, not safety scores. Scope means the implemented feature inventory is enumerated. Offline means code/tests/documents reviewed. Field means bounded live EAS and read-only drive comparisons only; it excludes motion, protection efficacy, STO/E-stop, write transactions, and Gold-family compatibility. -->

# EAS LIVE PARITY AUDIT · PX/PU + CURRENT DRAFT IMPLEMENTED

상태: **전 범위 감사 완료 · 두 핵심 불일치 수정 · 전체 회귀 GREEN**

업데이트: **2026-07-19 KST**

## 감사 범위

- Quick Tuning: Axis Configuration, Motor, Feedback, 6단계 Automatic Tuning.
- Expert Tuning: User Units, Limits/Protections, Application Settings,
  Current, Commutation, Velocity/Position, Scheduling, Verification, Summary.
- Single Axis: 상태, Position/Velocity/Current/Sine/Homing, Digital I/O,
  Drive Mode, Terminal, Recorder docking.
- Recorder: ribbon, acquisition modes, signal/trigger, chart/view/export 범위.
- 공통 셸: 메뉴, System Configuration, Status/Monitor, persistence/authority 표시.

## 이번 live EAS 관찰

- EAS 3.0.0.26을 현재 Gold Twitter에 COM3 단독 연결해 Motor Disabled,
  Velocity 0, Active Current 0 상태에서 읽기/화면 관찰만 수행.
- Enable, Run Tuning, Verify, PTP/Jog/Current/Sine/Homing, Apply, Save/SV는 실행하지 않음.
- EAS 터미널 raw `PX=-2038379934`, `PU=-2004825502`; EAS Single
  Axis/Verification-Time 표시는 정확히 `PU`.
- `PU-PX=33554432=2^25`, XM=0, FC=1, CA[45]=1. firmware-internal
  좌표 원점은 아직 미확정이며 앱은 자동 보정하지 않음.
- EAS Current는 `Current Command 1..5`, 모두 같은 `[TC]`, 초기 0 A,
  motor-off에서 Set disabled.

## 현재 판정

- `VALUE_PARITY_OBSERVED`: raw PX, EAS display PU, UM=5, 속도/가감속/정지감속,
  Digital Input/Output 논리 상태, Current PI와 Velocity/Position 설계 게인.
- `PARTIAL_LIVE_OBSERVED / OUTPUT LOCKED`: Current readback과 별도로 EAS형
  5개 local draft 구현; 모든 Set TC는 항상 잠김.
- `NEED-DATA`: `PU-PX=2^25`의 firmware-internal 좌표 원점.
- `DOC_ONLY`: User Units, Limits/Protections, Application Settings,
  hidden Bode, Verification-Time, Summary의 기존 로컬 inspector 대부분.
- `NOT_EXECUTED_NEED_DATA`: 실제 Automatic/Expert tuning, Commutation,
  Verification, Recorder acquisition, motion, Apply/SV.

## AngryYJH same-session 재조회

- `UM=5 Position`.
- `PX=-2038379934`, `VX=0`.
- `SP=4444444`, `AC=DC=SD=1000000`.
- `CL[1]=21.2132`, `PL[1]=70.7107`, `MC=140`, `TC=IQ=ID=0`.
- Digital Inputs 1..6: active/GP; Digital Outputs 1..4: inactive/GP.
- installed gains: `KP1=0.0857`, `KI1=782.5188`, `KP2=0.0002`,
  `KI2=10.7000`, `KP3=85.2114`.
- 수정 제어창은 raw `PX`, EAS `PU`, delta/socket/modulo/scale을 분리하고
  상단 위치를 `RAW POSITION · PX`로 명시함.

## 현재 코드 검증

- TDD RED: Current preset module 누락, old PX-only ledger가 의도대로 실패.
- PX/PU + Current preset 집중 GREEN: **142 passed in 34.79s**.
- EAS parity ledger GREEN: **5 passed**.
- 전체 repository 회귀: **1956 passed in 692.83s, exit 0**.
- 전체 출력에 skip/xfail 요약 없음.
- `git diff --check`: exit 0.

## 다음 작업

1. private Draft PR #2를 이번 PX/PU + Current preset revision으로 갱신한다.
2. `PU-PX=2^25` firmware-internal 좌표 원점을 독립적으로 규명한다.
3. `DOC_ONLY`와 `NOT_EXECUTED_NEED_DATA` 항목을 EAS 기능 단위로 하나씩
   구현·검증한다.
4. Current 출력은 현장 current/thermal/torque envelope와 독립 stop evidence가
   생길 때까지 계속 잠근다.

## 계속 잠긴 기능

- 모든 motor energization/motion: `MO=1`, `BG`, PTP/Jog/Current/Sine/Homing.
- 실제 Quick/Expert tuning과 Commutation/Verification.
- 파라미터 assignment, Apply/Revert, Save/SV, firmware download.
- unrestricted Terminal 및 Digital Output actuation.

이 감사의 live 관찰은 기능 동등성·제어 성능·기계 안전·STO/E-stop·다른 Gold 제품
호환성을 증명하지 않는다.
