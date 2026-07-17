# EAS III Full Parity Plan

> **DEFERRED BACKLOG — 2026-07-17:** 이 문서는 장기 EAS inventory/parity 참고 계획이다. 현재 활성
> 구현 범위와 완료율을 나타내지 않는다. Quick Tuning + 제한형 Single Axis의 현재 계획은
> [`current-scope-handoff.md`](current-scope-handoff.md), 상태값은 [`../tasks/status.md`](../tasks/status.md)를
> 우선한다. 아래의 기존 24/12 전체-EAS 진행 anchor는 폐기된 historical snapshot이다.

상태: 실행 기준선 v1.2<br>
작성일: 2026-07-16 KST<br>
대상 설치본: Elmo Application Studio III 3.0.0.26<br>
연동 체크리스트: tasks/eas-execution-checklist.md

## 1. 관찰 가능한 최종 상태

이 계획의 목표는 EAS 화면을 닮게 만드는 데 그치지 않는다. 선택한 범위의 각 기능에 대해 다음 상태가
모두 증거로 남을 때만 parity를 완료로 판정한다.

1. 실제 EAS UI에서 기능명, 입력, 출력, 상태 전이, 오류와 복구 경로를 관찰한다.
2. 설치 NetHelp, 공개 매뉴얼, 실제 3.0.0.26 리소스 또는 공식 Drive .NET API에서 공개 근거를 연결한다.
3. LOCAL, READ, DRIVE_STATE, RAM, ENERGY, MOTION, SV, RESET-FLASH, SAFETY_STOP, NEED-DATA 중 위험을 분류한다.
4. 순수 로컬 모델과 가짜 링크에서 정상, 경계, 음성 대조군, 실패 주입, 취소 경로를 통과한다.
5. READ 기능은 정확한 target identity와 fresh telemetry가 있는 실제 드라이브에서 조회 전용으로 검증한다.
6. 변경 기능은 해당 실행 직전의 명시 승인과 안전 gate를 통과한 뒤 최소 범위로 한 번 실행한다. 단,
   SAFETY_STOP과 disconnect cleanup은 fresh approval이나 fresh telemetry를 기다리느라 차단하지 않는다.
7. 변경 전 snapshot, 종료 readback, rollback 또는 복구 절차와 durable evidence를 남긴다.
8. 사용자 문서가 기능의 효과, 단위, 위험, 권한, 비호환 범위를 정확히 설명한다.

완료 판정은 기능별이며, 한 기능의 성공을 같은 메뉴에 있는 다른 기능으로 확장하지 않는다.

## 2. 범위

### Scope A — Gold Twitter 단축 드라이브

현재 Gold Twitter 한 축에서 공개적으로 확인 가능한 EAS 기능을 안전한 자체 UI와 backend로 구현한다.

- USB/serial target 연결, identity, telemetry, 상태, zero-new-drive-I/O System Configuration
  Inspector v0.1, host-observed Session Log v0.1과 HOST-OBSERVED Status Monitor v0.1
- Quick Tuning과 Expert Tuning의 Gold 적용 부분
- Axis, Motor, Feedback, limits/protections, application settings
- Current, commutation, velocity/position identification, design, verification
- Single Axis Motion과 Gold 적용 Application Tools
- Recorder, View Design, Status Monitor, Parameters Explorer/Comparison
- Gold parameter upload/download, 제한된 RAM trial, restore, SV의 장기 목표. 현재 production gain
  trial/Save는 durable pre-assignment trial WAL 전까지 잠금
- Gold firmware/PAL/reset/load는 Scope A의 마지막 조건부 단계로만 계획한다

Scope A는 EAS native 파일 형식이나 Elmo 내부 알고리즘과 byte-identical임을 기본 목표로 삼지 않는다.
같은 입력, 단위, drive side effect, postcondition, 취소와 복구 의미가 확인된 기능적 parity가 목표다.

### Scope B — 네트워크, Programming, 다축

Scope A의 단일 축 안전 계약이 먼저 통과한 뒤 별도 capability로 추가한다.

- CAN 및 EtherCAT configuration, PDO/FMMU/SM/DC/mailbox/init/EEPROM
- Multi Axis Motion, Group Motion, synchronized recorder
- Drive Script Manager, Command Macros, Terminal
- Drive Programming project, compile, build, download, run, debug
- EAS native workspace/parameter/recording 파일 호환
- multi-target Fault/Event aggregation과 target별 event evidence

Scope B는 연결 일부 실패, target 혼선, clock skew, command fan-out, partial rollback을 단일 축과 별도로 다룬다.

### Scope C — Maestro/Platinum 조건부

해당 하드웨어, firmware, license, 공개 문서와 시험 장비가 준비된 경우에만 활성화한다.

- Maestro Configurator, Maestro Script Manager, cyclic/profile/interpolated motion
- Modbus, EtherCAT Diagnostics, Maestro Parameters Explorer
- Maestro ECAM, Move & Settle, PVT/Splines, Path, Status Viewer, G-Code
- Maestro SIL, Blockly, Python, Browser, Event Logger
- Platinum Functional Safety, Safety I/O, Safety sign/report/validation/acceptance
- Platinum Sensor Memory Access, stopping options, BBH/SCU-1-EC, Drive SIL
- Kinematic/Sensory Memory Access
- 리소스에서만 확인된 Non-Linear Current FF는 target 노출 조건 확인 후 판단

Scope C의 안전 기능은 일반 UI parity가 인증 parity를 의미하지 않는다. 인증서, SRA, acceptance evidence가
없으면 기능 구현 상태와 관계없이 safety verdict는 NEED-DATA다.

## 3. 비목표

- Elmo firmware, license, 인증, 암호화 또는 비공개 service 인터페이스 우회
- 문서나 리소스에 없는 숨겨진 기능 추측
- EAS 화면을 자동 클릭한 사실만으로 동등성 선언
- software STOP을 독립 STO, contactor 또는 E-stop과 동일시
- 실제 하드웨어에서 기능을 연속 실행해 알아내는 탐색
- 사용자별 승인 없이 MO, TC, JV, BG, PX assignment, SV, LD, RS, download 실행
- EAS native 파일이라고 입증되지 않은 로컬 JSON을 EAS 호환으로 표시

## 4. 증거 기준선

| 근거 | OBSERVED 내용 | 사용 | 제한 |
|---|---|---|---|
| Windows 설치 정보 | EAS III 3.0.0.26 | 실제 설치 build identity | 매뉴얼보다 신버전 |
| Gold/SimplIQ NetHelp | MAN-SG-EASIII_UM Ver. 4.003, Nov 2024, 본문상 EASIII 3.0.0.0 | 공개 기능 목차와 절차 | 3.0.0.26와 차이 가능 |
| Settings and Configuration.htm §13.3 | Tool Organizer의 Activities/Tools, add/remove/reorder/reset과 세션 간 기억 동작 | A-003 공개 기능 계약 | 실제 3.0.0.26 화면·저장 schema 관찰이 아님 |
| Supporting Tools.htm §12.3 | Status Monitor의 one-or-more target, arbitrary variable/array, 0.5 s visible-only update, units/gauge/line/file 도구 | A-129~A-130 공개 기능 계약 | 실제 3.0.0.26 dialog 관찰이 아니며 `.smc`/`.sac` 설명이 모순됨 |
| Floating Tools.htm §11.5 | compact Status Monitor, Quick Watch, always-visible/top과 Unpin | A-134 공개 기능 계약 | modeless라는 용어·runtime ownership·display parity를 직접 입증하지 않음 |
| Platinum NetHelp | Drive Setup and Motion, safety/SIL/Platinum 기능 | Scope C catalog | 현재 Gold에서 실행 불가 |
| Ribbons.View.dll | 3.0.0.26의 메뉴, ribbon, tool 문자열 | 설치 build 교차 확인 | 문자열만으로 접근성이나 side effect를 확정하지 않음 |
| 162개 ElmoMotionControl DLL 이름 | 기능별 module 존재 | 문서 기능의 build 포함 여부 확인 | type 이름만으로 숨겨진 기능을 추측하지 않음 |
| operation_catalog.py | 현재 앱의 공통 위험 분류와 gate | 현재 구현 범위 | EAS 전체 catalog는 아님 |
| 기존 tests | 2026-07-16 전체 실행 898 passed in 237.51s | 구현 경로의 offline 기준선 | test count는 EAS 기능 수나 live parity 완료율이 아님 |
| 현재 repo 문서 | tuning, feedback, recorder, persistence 문서 | 기존 계약 재사용 | 일부 문서 encoding과 범위 정리 필요 |

증거 추적성 주의: 위 표와 연동 체크리스트의 `[x]`/`[~]`는 현재 inventory 표기다. 정확한 artifact 경로,
revision, SHA-256, 관찰/실행 시각, target identity와 connection epoch, 생성 명령 또는 live transcript가
연결되지 않은 표기는 감사 가능한 완료 증거가 아니며 `UNVERIFIED`로 취급한다. 대표 설치 파일 hash는 아래에
기록하지만, 각 기능 행의 증거 identity를 대신하지 않는다.

설치 증거의 대표 SHA-256:

- ElmoMotionControl.View.Main.exe:
  C8A023EA6DCEF8BC39E3E86E0AF929269AB47BB5B8791EB99FB9A62080F719ED
- Gold Drive Setup and Motion Activities.htm:
  BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE
- Platinum Drive Setup and Motion Activities.htm:
  6E76DAF7DB2E181BA2492730D8D15AA8CAA939E0C6DCB66233248690B53EE14F
- ElmoMotionControl.Ribbons.View.dll:
  1A42269899FA44AC776329F3E74EA6F8E5330CA523451FF8267793756D830A05
- NetHelp/Default.mcwebhelp:
  51F5FB6AC2C33B149F3AC0565B002B7D93B1D2C5D226852D229C29522EA72BBF
- EAS_II_SimplIQ_Gold_UM/Settings and Configuration.htm:
  E5BF9FDEE568B2FB8C58D06F9D0C2F9261A6973A5E081581038F5CFB3843F881
- EAS_II_SimplIQ_Gold_UM/Supporting Tools.htm:
  300B980C11BF37A5AE20803AA3038C178A2E6CD0785959791124EFA6739AAEC4
- EAS_II_SimplIQ_Gold_UM/Floating Tools.htm:
  32936D4B12A469CC950B592268D4E56A0E7BD12465C1CFA6AC88549D0B2E7E85

## 5. 알려진 사실, 미확정 사항, 가정, 사용자 결정

### 알려진 사실

- `LAST OBSERVED` target은 Gold Drive, PAL 90, Twitter 01.01.16.00 계열이다. 관찰일은
  2026-07-16 KST이고 source는 앱 UI/COM3 조회 전용 telemetry였으나, exact sample timestamp와
  connection epoch가 이 문서에 보존되지 않았다. 따라서 현재 상태 근거로는 `STALE/UNVERIFIED`다.
- 현재 앱은 identity-bound telemetry, software STOP, Session Zero, 좁은 Motor/P1/P2 transaction,
  Encoder Maintenance, Recorder Immediate, local View Design과 bounded PTP kernel을 갖고 있다.
- host-observed Session Log v0.1은 이미 UI에 전달된 이벤트만 bounded buffer로 소비하고
  비식별화 JSON/CSV를 로컬 저장한다. 열기·렌더·export는 drive I/O를 만들지 않는다.
- Tool Organizer v0.1은 modeless `LOCAL_UI`로 고정된 8개 page의 세션 내 표시/숨김·재정렬·Reset만
  수행한다. safety shell과 active Tuning/Recorder/Motion recovery page는 숨길 수 없고, persistence와
  drive I/O는 없다.
- HOST-OBSERVED Status Monitor v0.1은 modeless local dialog에서 이미 core-admitted된 PX/VX/PE/IQ/MO만
  표시한다. 별도 polling/timer/drive I/O는 없고 line 추가/삭제/재정렬/Reset은 session-only다. positive
  generation, canonical hashed identity, increasing sequence, explicit freshness, complete finite 다섯 신호와
  `MO∈{0,1}`이 모두 맞지 않으면 일부 값을 유지하지 않고 snapshot 전체를 blank 처리한다.
- Single Axis live motion은 site motion envelope가 없어서 잠겨 있다.
- Quick Tuning은 EAS 문서상 Current Identification/Design, Commutation, Velocity/Position
  Identification/Design을 연속 수행한다.
- Expert Tuning은 Apply/Revert 외에 Factory Reset, Drive Load, Drive Save까지 포함한다.
- Recorder의 Normal, Auto, Interval, Rollover, Multi Drive와 EAS native file parity는 미완이다.
- 일반 Terminal, Macros, Programs는 고정 위험이 아니라 내부 명령에 따라 전체 위험 범위를 가진다.

### 미확정 사항

- EAS 3.0.0.26 native workspace, parameter, recording, preset 파일 schema와 atomic recovery 의미
- EAS Tool Organizer의 실제 3.0.0.26 activity/capability 조건, 저장 위치·schema·version·손상 복구
- EAS Status Monitor의 실제 3.0.0.26 visible-only 0.5 s polling ownership/정확한 timing, arbitrary
  variables/arrays, multi-target, user units, color/gauge/warning, Quick Watch/topmost 상태 전이
- Status Monitor native configuration의 `.smc`/`.sac` extension 모순, schema/version, append/replace,
  unknown-field 보존, corruption 및 unavailable-target recovery
- 각 EAS 화면이 현 Gold firmware에서 실제 발행하는 정확한 명령, 순서, timeout, retry
- 현재 기계의 허용 이동 범위, 방향, 속도, 가속도, jerk, stop distance
- 독립 STO/E-stop 반응과 transport loss 시 실제 stop latency
- CAN/EtherCAT/Maestro/Platinum 시험 장비와 license, firmware 조합
- firmware/PAL 실패 시 공식 field recovery 절차와 복구 image
- 리소스에서만 확인된 기능의 target/license 노출 조건
- drive-origin fault history/source timestamp와 EC/SR/MF taxonomy
- Ack/Clear/Reset의 정확한 side effect, 권한, 실패·재연결·복구 계약

### 계획 가정

- 공식 NetHelp, 공개 매뉴얼, 공개 API와 사용자 소유 하드웨어만 사용한다.
- 한 명의 senior Python/control engineer가 주 담당이고, controls/test 지원이 0.3~0.5 FTE 제공된다.
- 실제 bench 사용은 주 1~2일이며 안전 담당자가 ENERGY 이상 실행에 참석한다.
- 기능적 parity를 우선하고, byte-identical proprietary algorithm은 요구하지 않는다.
- 각 live mutation 승인은 실행 직전에 기능, 범위, 최대치, 종료 조건을 다시 명시한다.

### 사용자 결정이 필요한 경계

- Scope B와 C를 실제 납품 목표로 포함할지
- EAS native file round-trip을 요구할지, 자체 format을 명확히 분리할지
- certified safety 기능을 단순 monitor로 둘지, 공식 safety workflow에 포함할지
- firmware/PAL/reset/load를 이 앱에 넣을지, EAS 전용 운영 절차로 유지할지
- Scope A motion envelope와 독립 STO/E-stop 시험 계획

## 6. 위험 순서와 공통 admission gate

일반 구현과 검증 순서는 반드시 다음을 따른다. `SAFETY_STOP`은 이 승격 순서 밖의 비차단 cleanup 경로이며,
`NEED-DATA`는 위험이나 side effect를 판정할 근거가 없어서 해당 branch를 잠그는 상태다.

LOCAL → READ → DRIVE_STATE → RAM → ENERGY → MOTION → SV → RESET-FLASH

| 위험 | admission gate | 필수 종료 증거 | 다음 단계 차단 조건 |
|---|---|---|---|
| LOCAL | hardware I/O가 없는 순수 model, versioned schema | deterministic output, malformed input reject | 불명확한 EAS format |
| READ | verified identity, connection epoch, fresh complete telemetry | source timestamp, sequence, exact target | stale/partial/replayed telemetry |
| DRIVE_STATE | READ + exclusive ownership + MO=0/SO=0/VX=0 | state closeout와 terminal readback | Recorder/IO ownership UNKNOWN |
| RAM | DRIVE_STATE + frozen snapshot + allowlist/range + rollback set | exact postcondition 또는 exact restore | write/readback mismatch |
| ENERGY | RAM + 현장 안전 + current limit + explicit run scope | ST, TC=0, MO=0, SO/MS/ID/IQ/VX readback | closeout UNKNOWN |
| MOTION | ENERGY + site envelope + direction/limit/stop distance + independent stop | final position, zero velocity/current, disabled | envelope 또는 STO/E-stop evidence 없음 |
| SV | RAM + durable authority/ledger + full profile verification | SV response, full readback, power-cycle audit | identity/profile ambiguity |
| RESET-FLASH | exact HW/FW/PAL/boot, official recovery, uninterrupted power, 별도 승인 | reboot identity, version, parameter and safety audit | recovery path 또는 image 없음 |
| SAFETY_STOP | connected transport가 있으면 fresh approval/telemetry 없이 즉시 attempt; 일반 mutation queue 우회 | ST→MO=0 terminal readback 또는 확인 불가 시 UNKNOWN latch | STOP 경로가 approval, telemetry refresh 또는 일반 worker에 의해 대기함 |
| NEED-DATA | side effect, target 적용성 또는 복구 의미가 미확정 | 공개 근거와 operation-specific contract | 추측 또는 일반화로 실행하려 함 |

SAFETY_STOP과 disconnect cleanup은 일반 작업 queue와 fresh-approval admission을 우회해 비차단으로
attempt한다. 성공을 주장하려면 terminal readback이 필요하며, 확인하지 못하면 UNKNOWN으로 남긴다. Recorder
Stop은 recorder ownership만 정리하는 `DRIVE_STATE` cleanup이고 motor SAFETY_STOP이 아니다. software STOP은
stale telemetry에서도 실행 가능해야 하지만 independent STO, contactor 또는 E-stop으로 표기하지 않는다.

## 7. 실행 단계

### Phase 0 — Catalog와 관찰 기준선 고정

- 입력: 설치 NetHelp, 3.0.0.26 resources/DLL, 사용자 제공 화면과 영상, 현재 repo
- 작업: checklist 각 행에 EAS 관찰과 공개 근거를 분리하여 기록
- 출력: 기능 ID, target applicability, 위험, 단위, side effect, unknown 목록
- 허용 범위: LOCAL, read-only file inspection
- 검증: 같은 기능이 메뉴/도구/module 세 근거 중 둘 이상에서 교차 확인되거나 단일 근거로 명시
- checkpoint: 문서와 실제 EAS UI가 다르면 구현 전에 version-specific contract로 분기

### Phase 1 — LOCAL parity

- workspace/navigation, settings, tool organizer, local editors, plot, comparison, calculators부터 구현한다.
- EAS native format은 schema와 round-trip oracle이 확보될 때까지 local-only extension을 사용한다.
- 모든 local parser는 malformed, oversized, truncated, version mismatch 입력을 거부한다.
- host-observed Session Log v0.1의 bounded viewer와 redacted atomic JSON/CSV는 구현됐다. 이는
  drive fault history나 Full EAS Fault Manager 완료를 뜻하지 않는다.
- Tool Organizer v0.1의 8-page session layout은 구현됐다. modeless dialog에서 표시/숨김·순서·Reset을
  staging/apply하며 safety shell과 active recovery page를 보호한다. native EAS persistence나 full
  activity/Favorites parity는 포함하지 않는다.
- HOST-OBSERVED Status Monitor v0.1의 fixed five-signal, modeless session view는 구현됐다. line config는
  session-only이고 현재 core telemetry를 projection할 뿐 새 polling이나 drive I/O를 만들지 않는다.
  full-blank authority gate를 포함하지만 EAS arbitrary signal/array, multi-target, user units, gauge,
  Quick Watch와 native `.smc`/`.sac` configuration parity는 포함하지 않는다.
- checkpoint: hardware import 없이 전체 local suite가 통과하고 UI가 mutation backend를 생성하지 않는다.

### Phase 2 — READ parity

- target discovery, identity, telemetry, status/fault, personality, parameter upload, signal discovery를 확장한다.
- 조회 결과에는 target identity, epoch, source time, receive time, sequence와 provenance를 결합한다.
- read-only live 검증은 write transcript가 비어 있음을 별도 oracle로 확인한다.
- 실제 fault/status 확장은 drive source timestamp, raw taxonomy와 target-bound ordering을 확보한 뒤 진행한다.
- checkpoint: COM 재연결, stale sample, target swap, partial read에서 UI가 UNKNOWN으로 잠긴다.

### Phase 3 — DRIVE_STATE parity

- Recorder lifecycle, status polling, I/O read/status, fault/event log를 우선한다.
- full EAS Status Monitor polling은 verified identity, fresh telemetry, bounded read allowlist, poll ownership와
  rate limit이 확보된 뒤 별도 READ/DRIVE_STATE 경로로 추가한다. v0.1 local observer가 이 gate를 충족했다고
  간주하지 않는다.
- Recorder Start/Stop/Upload는 motion STOP과 소유권을 분리하고 disconnect recovery ledger를 유지한다.
- Ack/Clear/Reset과 drive-origin fault/event lifecycle은 별도 권한·closeout·복구 계약 전까지 잠근다.
- Normal/Auto/Interval/Rollover/Multi Drive는 각각 독립 state machine과 실패 주입을 갖는다.
- checkpoint: start/upload/stop/disconnect 경쟁에서 stale completion이 새 session 권한을 열지 않는다.

### Phase 4 — RAM parity

- Axis, Motor, Feedback, user units, limits, protections, brake, settling, I/O와 parameter explorer를
  versioned command registry에 추가한다.
- 모든 변경은 Preview → frozen snapshot → bounded write → readback → restore를 기본으로 한다.
- 서로 연결된 motor/feedback/tuning parameter는 한 transaction aggregate로 취급한다.
- checkpoint: 각 assignment 직전 실패와 readback mismatch mutation을 harness가 잡아야 한다.

### Phase 5 — ENERGY parity

- Current Identification/Design/Verification, commutation, analog calibration, Halls/constant identification을
  한 기능씩 독립 승인하여 실행한다.
- current/time/displacement 한계와 abort chain을 UI에서 숨기지 않는다.
- closeout을 확인할 수 없으면 worker 전체를 UNKNOWN latch로 잠근다.
- checkpoint: 최대 허용 current의 낮은 단계부터 계단식으로 올리고 stop latency와 current trace를 보존한다.

### Phase 6 — MOTION parity

- Single Axis position → velocity → 다른 mode 순으로 진행한다.
- 그 뒤 Velocity/Position ID, verification, error mapping, cogging/profile conditioning으로 확장한다.
- Multi Axis, Group, Gantry, ECAM은 Scope B의 clock/partial failure contract 이후에만 연다.
- checkpoint: 방향 반전, limit 근접, communication loss, stale feedback, stop-distance 경계를 통과한다.

### Phase 7 — SV parity

- RAM trial이 독립적으로 복구 가능함을 먼저 입증한 기능만 비휘발 저장을 허용한다.
- request-bound durable ledger, process lock, fsync, full profile readback, power-cycle audit를 사용한다.
- Encoder Maintenance처럼 명령 자체가 datum/NVM을 변경하는 기능은 일반 SV와 별도 registry로 관리한다.
- checkpoint: crash-before-SV, crash-after-SV-response, ambiguous readback에서 재시도가 차단된다.

### Phase 8 — RESET-FLASH parity

- Factory Reset, Drive Load, program/config download, firmware/PAL은 기능별 복구 runbook이 있어야 한다.
- firmware/PAL은 app 구현보다 공식 EAS 운영 절차 유지가 더 안전할 수 있으며 사용자 결정 사항이다.
- bench spare와 recovery image가 없는 production target에서는 실행하지 않는다.
- checkpoint: 의도적인 interrupted-download 시험을 production drive가 아닌 복구 가능한 fixture에서 완료한다.

## 8. 기능군별 Definition of Done

| 기능군 / checklist ID | 추가 DoD |
|---|---|
| Core UI, Workspace, Backstage / A-001~A-003, A-137~A-139 | menu와 tool visibility가 target capability를 따르고, 화면 열기만으로 I/O가 없어야 하며 외부 Share destination은 별도 contract 전까지 잠겨야 한다 |
| Connection/System Config / A-004~A-007 | 정확한 target identity, epoch, disconnect cleanup, target swap 차단이 확인되어야 한다 |
| Parameter Upload/Download/Admin / A-008~A-021, A-140~A-142 | 파일 version/hash/target, dry-run diff, atomicity, partial-failure와 recovery가 확인되어야 한다 |
| Quick Tuning / A-022~A-031 | EAS 단계 순서, 입력 단위, stage result, abort/continue 의미와 최종 RAM diff가 일치해야 한다 |
| Expert configuration / A-032~A-045 | 각 page의 Enter/Apply/Revert/Apply All과 Drive Load/Save/Reset 효과를 분리해 재현해야 한다 |
| Current loop / A-046~A-049 | R/L 단위·phase convention, excitation 한계, independent calculation, time/Bode acceptance가 있어야 한다 |
| Analog calibration / A-050~A-051 | sensor range/direction, sample provenance, bounded excitation, repeatability와 exact restore가 있어야 한다 |
| Sensorless / A-052~A-053 | startup/fault/low-speed boundary와 loss-of-feedback recovery가 있어야 한다 |
| Commutation / A-054~A-058 | sensor direction, electrical angle convention, bounded current/motion, repeatability와 closeout가 있어야 한다 |
| Stepper / A-059 | UM/feedback 조건, current/motion limit, stall/fault와 disable closeout가 있어야 한다 |
| Velocity/Position / A-060~A-064 | position/velocity units, plant provenance, scheduling range, saturation/anti-windup, time/Bode gates가 있어야 한다 |
| Error Mapping / A-065~A-068 | coordinate frame, 2D/3D dataset, repeatability, correction disable/restore가 있어야 한다 |
| Gantry / A-069~A-070 | master/slave identity, yaw/center convention, one-axis fault fan-out와 coordinated stop가 있어야 한다 |
| ECAM / A-071~A-073 | table schema, modulo, master/follower identity, activation/deactivation와 safe stop가 있어야 한다 |
| Automated Identification / A-074~A-077 | excitation file, sample timing, fit quality, holdout verification, failed-stage continuation이 있어야 한다 |
| Single Axis Motion, status, zero, enable/STOP / A-078~A-087 | site envelope, direction, limit, stop distance, independent stop, coordinate authority, bounded closeout와 SAFETY_STOP 분리가 있어야 한다 |
| Application Tools / A-088~A-100 | 각 도구의 입력/출력 파일, drive writes, activation/deactivation, restore를 독립적으로 증명해야 한다 |
| Parameters Explorer/Comparison / A-101~A-104 | online/offline 값 출처, typed edit, diff, apply/revert/save와 forbidden commands가 분리되어야 한다 |
| Feedback/Encoder / A-105~A-107 | sensor ID별 command registry, unit conversion, reconnect latch, datum/NVM 의미가 확인되어야 한다 |
| Recorder / A-108~A-128 | target lock, timing, trigger, lifecycle, immutable data, export provenance, mode별 cancel/recovery가 있어야 한다 |
| Status/Fault/Log / A-129~A-131 | fault taxonomy, source timestamp, stale handling, reset 권한과 raw evidence export가 있어야 한다 |
| Floating Tools / A-132~A-136 | floating view와 canonical backend가 같은 ownership/risk contract를 공유하고 중복 실행을 차단해야 한다 |
| CAN configuration / B-001 | topology/target identity, state transition, link loss, download rollback이 있어야 한다 |
| EtherCAT configuration/diagnostics / B-002~B-007, B-024 | master/slave identity, PDO/FMMU/SM/DC/mailbox/init, state transition, link loss와 partial download rollback이 있어야 한다 |
| Multi/Group Motion/Recording / B-008~B-011 | synchronized clock, axis ownership, one-axis fault fan-out, coordinated stop와 partial restore가 있어야 한다 |
| Script/Macro/Terminal / B-012~B-015 | command-level risk classifier, allowlist, review, watchdog, kill과 execution transcript가 있어야 한다 |
| Drive Programming / B-016~B-019 | compiler/toolchain identity, source/build hash, download provenance, runtime watchdog와 recovery가 있어야 한다 |
| EAS native files / B-020~B-022 | EAS open-save-open round trip, schema version, unknown-field preservation, corrupted-file recovery가 있어야 한다 |
| Multi-target Fault/Event / B-023 | target/epoch별 event ordering, clock provenance, partial disconnect와 raw export가 있어야 한다 |
| Maestro configuration/parameters/admin / C-001~C-005, C-009~C-011, C-035~C-036 | 실제 Maestro identity와 firmware별 public API, typed parameter/file contract와 restore가 있어야 한다 |
| Maestro motion/application tools / C-007~C-008, C-012~C-017 | axis/group ownership, coordinate frame, synchronized stop, limit/fault fan-out와 recovery가 있어야 한다 |
| Maestro script/programming/files / C-006, C-018, C-020~C-022 | command classifier, source/package provenance, watchdog, transfer rollback과 target-bound debug가 있어야 한다 |
| Maestro SIL/Event evidence / C-019, C-023 | simulation과 field evidence를 분리하고 timestamp/target provenance 및 MODEL/STAND-IN 표기가 있어야 한다 |
| Platinum safety/admin / C-024~C-031, C-037~C-038 | hardware/license applicability와 공식 safety/recovery evidence가 있어야 하며 UI parity만으로 완료할 수 없다 |
| Platinum extensions / C-032~C-034 | target 노출 조건, coordinate/memory semantics와 공개 side-effect contract가 없으면 NEED-DATA로 유지해야 한다 |

각 checklist 행은 위 공통/기능군 DoD에 더해 자체 EAS 관찰, offline, live, mutation, rollback, docs 칸을
모두 충족해야 완료다.

`HOST-OBSERVED Status Monitor v0.1`은 A-129의 fixed PX/VX/PE/IQ/MO session layout과 A-134의 modeless
host view 하위 항목만 충족한다. 기존 core-admitted telemetry만 소비하고 strict
generation/hashed-identity/sequence/freshness gate 실패 시 전체 blank 처리하지만, EAS 0.5 s polling,
arbitrary variables/arrays, multi-target, user units, gauge, Quick Watch/topmost와 native `.smc`/`.sac`는
`NEED-DATA`다. 따라서 A-129, A-130, A-134 전체 DoD나 hardware/display parity를 충족하지 않는다.

`Status / Session Log v0.1`은 A-131의 local viewer/export 하위 항목만 충족한다. drive-origin history,
taxonomy, Ack/Clear/Reset이 없으므로 A-131 전체 DoD는 아직 충족하지 않는다.

`System Configuration Inspector v0.1`은 A-001/A-004의 local current-target 표시 하위 항목만
충족한다. 이미 admission된 단일 Gold/Direct Access USB target을 새 drive I/O 없이 투영하며,
board type은 `UNOBSERVED/NEED-DATA`다. Add/Remove/Edit/Group/I/O/Virtual Axis와 full management가
잠겨 있으므로 A-006/A-007 및 Connection/System Config 전체 DoD는 아직 충족하지 않는다.

`Tool Organizer v0.1`은 A-003의 8개 고정 page에 대한 session-only 표시/숨김·재정렬·Reset 하위
항목만 충족한다. modeless local dialog는 safety shell을 layout 대상에 넣지 않고 active
Tuning/Recorder/Motion recovery page 숨김을 거부하며 drive I/O를 만들지 않는다. EAS의 전체
activity/Favorites, target capability 조건과 세션 간 native persistence는 `NEED-DATA`이므로 A-003
전체 parity와 Core UI/Workspace/Backstage 전체 DoD는 아직 충족하지 않는다.

## 9. 예상 기간

아래 값은 새로운 구현과 검증을 포함한 `INFERRED` rough-order-of-magnitude(ROM)이며, 단순 UI mockup
기간이 아니다. 요구 범위, fixture availability, vendor API, 안전 담당/인증 일정에 따라 바뀌는 비구속
추정치(non-binding estimate)다.

| 범위 | Engineering effort | 한 명 중심 예상 calendar | 주요 가정 |
|---|---:|---:|---|
| Scope A LOCAL+READ | 8~14 engineer-weeks | 2.5~4개월 | EAS 관찰과 bench read-only 주 1회 |
| Scope A DRIVE_STATE+RAM | 12~22 engineer-weeks | 4~7개월 | command registry와 fault injection 포함 |
| Scope A ENERGY+MOTION | 16~30 engineer-weeks | 6~12개월 | 안전 담당, fixture, motion envelope 확보 |
| Scope A SV+조건부 RESET-FLASH | 9~16 engineer-weeks | 3~6개월 | spare drive와 recovery path 확보 |
| Scope A 전체 | 45~82 engineer-weeks | 12~24개월 | 1 senior + 0.3~0.5 FTE test/controls |
| Scope B 네트워크/Programming/다축 | 45~90 engineer-weeks | 추가 14~28개월 | CAN/EtherCAT 다축 fixture와 compiler/API 확보 |
| Scope C Maestro/Platinum | 70~140+ engineer-weeks | 추가 20~40+개월 | 각 target, license, safety package 확보 |
| A+B+C 전체 | 160~312+ engineer-weeks | 한 명 중심 약 4~8+년 | scope 변경, 대기와 인증 기간에 따라 상한 증가 |

3~5명 팀이 독립 lane을 병렬 수행하고 각 hardware fixture, vendor API와 review owner가 모두 준비된다는
조건에서만 전체 parity의 조건부 ROM은 약 14~30개월이다. Hardware, license, safety certification 또는
serial bench gate가 늦어지면 이 범위는 성립하지 않으며 calendar는 더 길어진다.

## 10. 현재 진행률과 근거

이 절의 `24/12` 값은 2026-07-16 전체-EAS 계획 시점의 historical snapshot이며 현재 모니터에서
사용하지 않는다. 활성 모니터는 범위 확정 100, 두 기능의 오프라인 준비도 70 잠정, 현 리비전 실기
0/NEED-DATA를 서로 분리한다. 해석과 최신 증거는 [`../tasks/status.md`](../tasks/status.md)를 따른다.

| 관점 | 현재 추정 | 근거 | 해석 |
|---|---:|---|---|
| 기능 inventory/위험 routing | 70~85% | Gold/Platinum NetHelp, 3.0.0.26 ribbon/module 대조 | GUI 직접 관찰이 남음 |
| Scope A software 기능 | 20~30% | identity/telemetry, narrow Motor/Feedback, P1/signature/P2, Recorder, host Session Log v0.1, Tool Organizer v0.1, HOST-OBSERVED Status Monitor v0.1, PTP kernel | EAS 전체 page와 application tools는 대부분 없음 |
| Scope A live evidence | 10~15% | COM identity/telemetry와 일부 tuning/encoder 이력 | 최신 code 전체의 단계별 live 재검증 아님 |
| Scope B | 0~5% | 메뉴 placeholder와 문서 inventory | network/programming/multi-axis backend 없음 |
| Scope C | 0~3% | 문서/resource inventory | target hardware 기반 구현 없음 |
| A+B+C 전체 | 8~15% | checklist 기능 분모와 I/P/G/N/O 대조 | 안전 또는 출시 verdict가 아님 |

당시 변경분의 전체 offline suite는 898 passed in 237.51s였지만 최신 working tree보다 오래된 historical
evidence이며 현재 완료 근거가 아니다. 아래 가중치는
향후 evidence identity가 연결된 행을 계산하기 위한 제안일 뿐이다. 현재 24/12 표시는 이 가중치로 재현되는
계산값이 아니며, traceability가 없는 행과 grouped/NEED-DATA coverage는 scoring에서 제외한다.

권장 가중치:

- EAS 직접 관찰 10%
- 공개 근거 10%
- 위험 분류 10%
- offline test 20%
- read-only live 15%
- 승인 mutation 15%
- rollback/recovery 15%
- 사용자 문서 5%

mutation이 본질적으로 없는 LOCAL/READ 기능은 해당 비중을 offline/live/docs에 재분배한다.

## 11. Risk register

| 위험 | 영향 | 현재 상태 | 완화와 gate |
|---|---|---|---|
| EAS 3.0.0.26와 3.0.0.0 문서 차이 | 잘못된 명령/메뉴 parity | OPEN | 실제 EAS 관찰과 resource 교차 확인 |
| EAS native file schema 미확정 | 파일 손상 또는 허위 호환 | OPEN | local extension 유지, round-trip oracle 전까지 NEED-DATA |
| command side effect 미확정 | RAM/NVM/energy 오분류 | OPEN | per-command registry와 exact transcript |
| stale/partial telemetry | 잘못된 enable/mutation admission | 기존 방어 있음 | identity/age/sequence fail-closed 유지 |
| host timestamp를 drive fault history로 오해 | 잘못된 원인·순서·복구 판단 | v0.1 경계 명시 | `HOST_OBSERVED_NOT_DRIVE_HISTORY`; full manager는 NEED-DATA |
| motor/feedback convention 오류 | 역방향 torque/motion | OPEN | phase/line, RMS/peak, pole pair, sign 명시 |
| motion envelope 부재 | 기계 충돌 | BLOCKING | site envelope와 independent stop 전까지 GATED |
| SV ambiguity/crash | 영구 상태 불명 | 일부 방어 있음 | durable ledger, interprocess lock, power-cycle audit |
| firmware/PAL mismatch | drive brick | BLOCKING | spare/recovery image/official workflow 전까지 금지 |
| multi-axis partial failure | 축 간 불일치/충돌 | OPEN | distributed transaction과 coordinated stop |
| Terminal/Program 임의 명령 | 전체 안전 gate 우회 | BLOCKING | unrestricted UI 금지, command-level classifier |
| Recorder blocking vendor call | STOP/cleanup 지연 | 일부 방어 있음 | ownership state, timeout, disconnect recovery |
| SAFETY_STOP이 approval/telemetry에 차단됨 | 비상 cleanup 지연 | 계약 보강 | fresh approval/telemetry 없이 비차단 attempt, terminal readback 실패 시 UNKNOWN |
| software STOP과 독립 STO 혼동 | 잔류 에너지/운동 위험 은폐 | CLOSED BY POLICY | software STOP은 independent safety channel이 아님을 UI/문서에 유지 |
| safety UI와 인증 혼동 | 잘못된 안전 주장 | OPEN | certification evidence 없으면 NEED-DATA |
| 비공개 기능 추측 | 지원 불가/법적 위험 | CLOSED BY POLICY | 공개 근거 없는 기능은 구현하지 않음 |

## 12. Re-plan trigger

다음 중 하나가 발생하면 해당 branch를 중단하고 계획과 checklist를 먼저 갱신한다.

- EAS UI와 NetHelp/resource의 field, 단위, 명령 또는 상태 전이가 다름
- 현재 drive firmware에서 command가 undocumented value 또는 다른 side effect를 보임
- write 후 exact readback이나 rollback이 한 번이라도 불확정
- STOP/disable closeout가 UNKNOWN 또는 latency 한계를 초과
- target identity, connection epoch, recorder ownership이 바뀜
- native EAS file round-trip이 unknown field를 잃거나 corruption을 만듦
- multi-axis 한 축 실패에서 coordinated stop/restore가 불완전
- compiler, firmware, PAL, license 또는 hardware revision이 바뀜
- 같은 safety regression이 반복되거나 test oracle이 구현 code path를 재사용함
- 새 권한, hardware motion, flashing, certification 범위가 필요해짐

## 13. Requirement-to-test matrix

| 요구 | 최소 test/oracle | 완료 증거 |
|---|---|---|
| LOCAL 기능은 I/O 없음 | import/construct transcript가 비어 있음 | deterministic unit/UI test |
| Host Session Log v0.1 | poison worker zero-I/O, stale/replay/old-generation, payload limit, atomic replace failure | bounded redacted JSON/CSV + readback SHA |
| HOST-OBSERVED Status Monitor v0.1 | poison worker zero-I/O, config mutation, stale/replay/old-generation/wrong-identity/incomplete/non-finite/observer-error | exact authority 또는 full blank; session-only fixed allowlist |
| READ는 target-bound | stale/replay/partial/target swap 음성 대조군 | read-only live transcript |
| DRIVE_STATE lifecycle | start/stop/upload/disconnect race와 vendor exception | terminal state + recovery ledger |
| RAM transaction | assignment별 failpoint, mutation, rollback mismatch | exact original/applied/restored readback |
| ENERGY closeout | current limit, cancel timing, transport loss | ST→TC=0→MO=0와 current trace |
| MOTION safety | 방향/limit/stop distance/feedback loss | independent stop와 final state |
| SAFETY_STOP availability | stale telemetry, busy worker, approval 부재, transport loss | 비차단 attempt transcript + terminal readback 또는 UNKNOWN latch |
| SV durability | crash 전후, duplicate request, identity mismatch | power-cycle full profile audit |
| RESET-FLASH recovery | wrong image, interrupted transfer, reboot mismatch | spare fixture recovery run |
| Network atomicity | slave loss, clock skew, partial target success | coordinated stop/rollback |
| Program/Macro safety | forbidden command mutation, infinite loop, kill | command classifier와 watchdog |
| Recorder fidelity | timing, channel count, trigger, rollover, immutable export | raw capture와 independent timing oracle |
| 문서 정확성 | UI label, 위험 badge, 실제 side effect 대조 | checklist docs 승인 |

## 14. 권장 경로

먼저 Scope A의 EAS 직접 관찰을 LOCAL과 READ 기능에 대해 끝내고, 구현된 host-observed v0.1을
기반으로 drive-origin Full Fault/Ack/Clear와 Recorder lifecycle을 별도 완성한다. 그 다음 versioned
RAM command registry를 확장한다. ENERGY와 MOTION은 기능별 작은 승인으로
진행하고, SV는 crash-safe pre-assignment WAL로 복구 가능한 RAM trial 뒤에만 연다. 현재 gain
trial은 이 조건을 만족하지 않아 production에서 잠긴다. Scope B와 C는 UI placeholder와 catalog만 유지하며,
해당 fixture와 공개 API가 준비되기 전에는 backend를 추측해 구현하지 않는다.
