<!-- scope_progress: 100 -->
<!-- offline_progress: 88 -->
<!-- field_progress: 40 -->
<!-- progress_basis: Planning indicators, not safety scores. Scope means the implemented feature inventory is enumerated. Offline means code/tests/documents reviewed. Field means bounded live EAS and read-only drive comparisons only; it excludes motion, protection efficacy, STO/E-stop, write transactions, and Gold-family compatibility. -->

# EAS LIVE PARITY AUDIT · IN PROGRESS

상태: **기존 완료 표시는 잠정 철회 · 처음부터 전 기능 재대조 중**

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
- EAS 터미널 raw `PX=-2038379934`; 우리 앱의 current-drive `PX`도 정확히 동일.
- 같은 순간 EAS Single Axis/Verification-Time 표시 위치는 `-2004825502`.
- 차이 `33554432 = 2^25 counts`; EnDat 2.2 표시 변환/랩 원인은 아직 미확정.

## 현재 판정

- `VALUE_PARITY_OBSERVED`: raw PX, UM=5, 속도/가감속/정지감속,
  Digital Input/Output 논리 상태, Current PI와 Velocity/Position 설계 게인.
- `UI_SEMANTICS_MISMATCH`: 우리 Current Reference readback은 EAS Current 탭의
  5개 Current Command preset UI와 같은 기능이 아님.
- `MISMATCH_NEED_DATA`: EAS raw PX와 EAS Single Axis 표시 위치의 `2^25` 차이.
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
- 수정 제어창을 재시작해 Current UI 의미 분리와 PX `2^25` 경고 표시를 확인함.

## 현재 코드 검증

- audit RED: 누락 기능군과 UI 의미/위치 경고가 의도대로 실패.
- focused GREEN: **57 passed**.
- 영향 범위 GREEN: **204 passed in 269.59s**.
- 전체 repository GREEN: **1873 passed in 852.71s (14:12), exit 0**.
- 전체 출력에 skip/xfail 요약 없음.
- `git diff --check`: exit 0.

## 다음 작업

1. 전 기능 parity ledger를 코드/문서의 현재 구현과 1:1로 고정한다.
2. 우리 앱의 모든 read-only refresh를 현재 연결에서 재실행해 EAS 관찰값과 대조한다.
3. 과장된 “완료/동등” 문구와 혼동되는 Current/Position UI를 수정한다.
4. 회귀시험 뒤 감사 결과를 private branch와 Draft PR에 반영한다.

## 계속 잠긴 기능

- 모든 motor energization/motion: `MO=1`, `BG`, PTP/Jog/Current/Sine/Homing.
- 실제 Quick/Expert tuning과 Commutation/Verification.
- 파라미터 assignment, Apply/Revert, Save/SV, firmware download.
- unrestricted Terminal 및 Digital Output actuation.

이 감사의 live 관찰은 기능 동등성·제어 성능·기계 안전·STO/E-stop·다른 Gold 제품
호환성을 증명하지 않는다.
