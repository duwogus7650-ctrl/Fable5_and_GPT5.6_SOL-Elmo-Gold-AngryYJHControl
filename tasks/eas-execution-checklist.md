# EAS III Execution Checklist

> **DEFERRED BACKLOG — 2026-07-17:** 전체 EAS checklist 실행은 중단했다. 현재 활성 범위는
> [`../docs/current-scope-handoff.md`](../docs/current-scope-handoff.md)의 Quick Tuning + 제한형
> Single Axis이며, 이 표의 `[x]/[~]`를 현재 완료율로 사용하지 않는다.

기준 설치본: EAS III 3.0.0.26<br>
계획: docs/eas-full-parity-plan.md<br>
갱신일: 2026-07-16 KST

## 사용법

- [x] = 현재 식별 가능한 증거로 완료
- [~] = 일부 target, 일부 field, stand-in 또는 과거 evidence만 있음
- [ ] = 미실행/미구현/미검증
- — = 해당 기능에 본질적으로 적용되지 않음
- EAS 관찰은 실제 EAS 화면/영상 관찰이다. NetHelp나 DLL 문자열 확인은 공개 근거 열에만 기록한다.
- Read-only live 표기는 `LAST OBSERVED` 이력이다. 행에 exact sample timestamp, source와 connection epoch가
  연결되지 않았으면 현재 상태로 재사용하지 않고 `STALE/UNVERIFIED`로 취급한다.
- 위험 분류의 canonical 집합은 `LOCAL / READ / DRIVE_STATE / RAM / ENERGY / MOTION / SV /
  RESET-FLASH / SAFETY_STOP / NEED-DATA`다. `SAFETY_STOP`은 일반 위험 승격 순서 밖의 cleanup 경로다.
- Offline check는 기존 row-specific test evidence를 표시한다. 최신 전체 suite는 2026-07-16에
  898 passed in 237.51s였지만,
  그 결과를 모든 행의 Offline test 완료로 확장하지 않는다.
- 승인 Mutation 열은 매번 fresh approval이 필요하므로 과거 승인 이력을 재사용하지 않는다. 예외적으로
  SAFETY_STOP과 disconnect cleanup은 fresh approval이나 fresh telemetry를 기다리지 않고 비차단 attempt해야 한다.
- Rollback은 단순 예외 처리나 software STOP이 아니라 original state의 exact readback 또는 공식 recovery를 뜻한다.
- 한 행의 완료는 docs/eas-full-parity-plan.md의 공통 gate와 기능군 DoD도 충족해야 한다.
- `[x]`/`[~]`만으로는 감사 가능한 완료 증거가 아니다. artifact 경로/URL, repo revision, SHA-256,
  관찰·실행 시각, target identity/connection epoch와 transcript 중 적용 가능한 identity가 연결되지 않은 셀은
  `UNVERIFIED`다. 그런 행과 아래 grouped coverage는 진행률 산식에서 제외한다.

근거 코드:

- G2 = Gold EASIII Quick Start Guide
- G3 = Gold EASIII Infrastructure
- G5 = EtherCAT Configurator Tool
- G6 = System Configuration Activities
- G7 = Maestro and Drive Administration
- G8 = Gold Drive Setup and Motion Activities
- G9 = Drive Programming Activities
- G10 = Maestro Setup and Motion Activities
- G11 = Floating Tools
- G12 = Supporting Tools
- G13 = Settings and Configuration
- P9 = Platinum Drive Setup and Motion Activities
- RIB = ElmoMotionControl.Ribbons.View.dll 3.0.0.26 resource
- MOD = 해당 ElmoMotionControl module DLL

Tool Organizer 공개 근거 identity: 설치된 `EAS_II_SimplIQ_Gold_UM/Settings and Configuration.htm`
§13.3, SHA-256 `E5BF9FDEE568B2FB8C58D06F9D0C2F9261A6973A5E081581038F5CFB3843F881`;
help manifest `NetHelp/Default.mcwebhelp`, SHA-256
`51F5FB6AC2C33B149F3AC0565B002B7D93B1D2C5D226852D229C29522EA72BBF`. 이는 공개 문서 근거이며
실제 EAS 3.0.0.26 Tool Organizer 화면/native persistence/display/hardware 검증이 아니다.

Status Monitor 공개 근거 identity: 설치된 `EAS_II_SimplIQ_Gold_UM/Supporting Tools.htm` §12.3,
SHA-256 `300B980C11BF37A5AE20803AA3038C178A2E6CD0785959791124EFA6739AAEC4`;
`EAS_II_SimplIQ_Gold_UM/Floating Tools.htm` §11.5, SHA-256
`32936D4B12A469CC950B592268D4E56A0E7BD12465C1CFA6AC88549D0B2E7E85`;
help manifest `NetHelp/Default.mcwebhelp`, SHA-256
`51F5FB6AC2C33B149F3AC0565B002B7D93B1D2C5D226852D229C29522EA72BBF`; 설치 executable
`ElmoMotionControl.View.Main.exe` 3.0.0.26, SHA-256
`C8A023EA6DCEF8BC39E3E86E0AF929269AB47BB5B8791EB99FB9A62080F719ED`. 이는 static public help/build
identity이며 실제 EAS dialog, native file round-trip, hardware 또는 display validation이 아니다.

## Scope A — Gold Twitter

| ID | EAS 기능 | EAS 관찰 | 공개 근거 | 위험 분류 | Offline test | Read-only live | 승인 Mutation | Rollback | Docs | 메모 |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---|
| A-001 | Main window, Workspace Tree, Navigation, File/Core/Context ribbons | [x] 상단 일부 | [x] G3/RIB | [x] LOCAL | [x] | — | — | — | [~] | 현재 앱은 EAS-style 메뉴와 8 fixed pages; session-only Tool Organizer, Status / Log와 System Inspector 포함 |
| A-002 | EAS Settings: General/Logger/Workspace/Drive/Tuner/Recorder | [ ] | [x] G13/RIB | [x] LOCAL→DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | 설정별 위험 재분류 필요 |
| A-003 | Tool Organizer v0.1과 tool visibility | [ ] | [x] G13 §13.3/RIB | [x] LOCAL | [x] 8-page model/UI | — | — | [x] local UI rollback | [x] | [~] session-only show/hide/reorder/reset; modeless; safety shell·active workflow lock; no persistence/native EAS config/drive I/O; full native persistence·capability 조건 NEED-DATA |
| A-004 | Gold hardware recognition과 COM target discovery | [~] | [x] Introduction/G3 | [x] READ | [x] | [x] | — | — | [x] | Inspector v0.1은 admission된 단일 Direct USB target만 host projection; 별도 discovery/read 없음 |
| A-005 | Connect/disconnect/reconnect lifecycle | [~] | [x] G3/RIB | [x] DRIVE_STATE | [x] | [x] | [ ] | [x] | [~] | vendor disconnect 오류 집계 구현; disconnect cleanup은 fresh approval 비대상 |
| A-006 | System Configuration: drive/device/group 추가 | [ ] | [x] G6/RIB | [x] LOCAL→DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | Inspector와 분리; Add/Remove/Edit/Group full management 잠금·NEED-DATA |
| A-007 | I/O device와 virtual axis 추가 | [ ] | [x] G6/RIB | [x] LOCAL→DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | I/O/Virtual Axis 잠금·NEED-DATA |
| A-008 | Personality upload와 signal discovery | [~] | [x] G7/MOD | [x] READ | [x] | [~] | — | — | [x] | 현재 target 일부 live |
| A-009 | Textual parameter upload | [ ] | [x] G7 | [x] READ | [ ] | [ ] | — | — | [ ] | |
| A-010 | Binary parameter upload | [ ] | [x] G7 | [x] READ | [ ] | [ ] | — | — | [ ] | |
| A-011 | Textual parameter download | [ ] | [x] G7 | [x] RAM→SV | [ ] | [ ] | [ ] | [ ] | [ ] | generic file download 없음 |
| A-012 | Binary parameter download | [ ] | [x] G7 | [x] RAM→SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-013 | Workspace Parameters upload/download | [ ] | [x] G7 | [x] READ→RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-014 | Workspace Files Download wizard | [ ] | [x] G7/RIB | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | firmware/config/program fan-out |
| A-015 | Drive Load: flash에서 RAM으로 복원 | [ ] | [x] G8/G13/RIB | [x] RAM/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | 현재 generic LD 차단 |
| A-016 | Drive Save: RAM을 flash에 저장 | [~] | [x] G8/G13/RIB | [x] SV | [x] 제한 profile | [~] | [ ] | [x] 제한 profile | [x] | 범용 EAS Save 아님 |
| A-017 | Factory Reset/Drive Restart | [ ] | [x] G8/RIB | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | 현재 RS 차단 |
| A-018 | Gold firmware download via USB/RS232 | [ ] | [x] G7 | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [~] | official recovery 필요 |
| A-019 | Gold firmware download via FoE | [ ] | [x] G7 | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [~] | Scope B EtherCAT 의존 |
| A-020 | Gold PAL download via USB/RS232 | [ ] | [x] G7 | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [~] | |
| A-021 | Gold PAL download via FoE | [ ] | [x] G7 | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [~] | |
| A-022 | Quick Tuning: Axis Configurations | [ ] | [x] G2 §2.3.2 | [x] RAM | [~] | [~] | [ ] | [~] | [~] | current Axis Summary는 read-only |
| A-023 | Quick Tuning: Motor Settings | [ ] | [x] G2 §2.3.3 | [x] RAM/SV | [x] 제한 profile | [~] | [ ] | [x] | [x] | EAS page 전체 parity 아님 |
| A-024 | Quick Tuning: Feedback Settings | [~] 영상 | [x] G2 §2.3.3.2 | [x] RAM/SV | [x] preview | [~] EnDat | [ ] | [ ] | [x] | 23 sensor preview, write registry 미완 |
| A-025 | Quick Tuning: Initialization | [ ] | [x] G2 §2.3.4 | [x] DRIVE_STATE/RAM | [~] | [~] | [ ] | [~] | [~] | |
| A-026 | Quick Tuning: Current Identification | [ ] | [x] G2 §2.3.4 | [x] ENERGY | [x] | [~] | [ ] | [x] | [x] | Phase 1 구현 |
| A-027 | Quick Tuning: Current Design | [ ] | [x] G2 §2.3.4 | [x] RAM | [x] | [~] | [ ] | [x] | [x] | |
| A-028 | Quick Tuning: Commutation | [ ] | [x] G2 §2.3.4 | [x] ENERGY/MOTION/RAM | [x] signature | [~] | [ ] | [~] | [x] | EAS auto-phasing 전체 아님 |
| A-029 | Quick Tuning: Velocity/Position Identification | [ ] | [x] G2 §2.3.4 | [x] MOTION | [x] | [~] | [ ] | [x] | [x] | Phase 2 |
| A-030 | Quick Tuning: Velocity/Position Design | [ ] | [x] G2 §2.3.4 | [x] RAM | [x] | [~] | [ ] | [x] | [x] | |
| A-031 | Quick Tuning: Summary recommendation/apply | [ ] | [x] G2 §2.3.4 | [x] RAM/SV | [~] | [ ] | [ ] | [~] | [~] | 추천 action 정확한 의미 미확정 |
| A-032 | Expert Tuning tree와 page status/error | [ ] | [x] G8 §8.2 | [x] LOCAL/READ | [~] | [ ] | — | — | [~] | 현재 Quick/Expert 보기 분리만 |
| A-033 | Expert Apply/Revert current page | [ ] | [x] G8 §8.2.1 | [x] RAM | [x] P1/P2 | [~] | [ ] | [x] | [x] | page 범위 제한 |
| A-034 | Expert Apply All/Revert All | [ ] | [x] G8 §8.2.1/RIB | [x] RAM | [~] | [ ] | [ ] | [~] | [~] | aggregate transaction 필요 |
| A-035 | Expert Drive Load/Drive Save/Reset | [ ] | [x] G8 §8.2.1~2 | [x] RAM/SV/RESET-FLASH | [~] 제한 SV | [ ] | [ ] | [~] | [~] | generic path 없음 |
| A-036 | Expert Axis Configurations | [ ] | [x] G8 §8.2.3 | [x] RAM/SV | [~] read model | [~] | [ ] | [ ] | [~] | |
| A-037 | Expert Motor Settings 전체 | [ ] | [x] G8 §8.2.4.1 | [x] RAM/SV | [x] 제한 profile | [~] | [ ] | [x] | [x] | |
| A-038 | Expert Feedback Settings/Advanced 전체 | [~] 영상 | [x] G8 §8.2.4.2~3 | [x] RAM/SV | [x] preview | [~] EnDat | [ ] | [ ] | [x] | |
| A-039 | Drive/Display User Units | [ ] | [x] G8 §8.2.5 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-040 | Current Limits | [ ] | [x] G8 §8.2.6.1 | [x] RAM/SV | [~] motor profile 일부 | [~] | [ ] | [~] | [~] | |
| A-041 | Motion Limits and Modulo | [ ] | [x] G8 §8.2.6.2 | [x] RAM/SV | [~] PTP envelope model | [ ] | [ ] | [ ] | [~] | |
| A-042 | Protections | [ ] | [x] G8 §8.2.6.3 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-043 | Brake | [ ] | [x] G8 §8.2.7.1 | [x] DRIVE_STATE/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-044 | Settling Window | [ ] | [x] G8 §8.2.7.2 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-045 | Inputs and Outputs settings | [ ] | [x] G8 §8.2.7.3 | [x] DRIVE_STATE/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-046 | Current Identification | [ ] | [x] G8 §8.2.8.1 | [x] ENERGY | [x] | [~] | [ ] | [x] closeout | [x] | |
| A-047 | Current Design | [ ] | [x] G8 §8.2.8.2 | [x] RAM | [x] | [~] | [ ] | [x] | [x] | |
| A-048 | Current Verification - Time | [ ] | [x] G8 §8.2.8.3 | [x] ENERGY | [~] | [~] | [ ] | [~] | [~] | EAS exact waveform gate 미확정 |
| A-049 | Current Verification - Bode | [ ] | [x] G8 §8.2.8.4 | [x] ENERGY | [~] | [ ] | [ ] | [~] | [~] | |
| A-050 | Analog Sensor Calibration | [ ] | [x] G8 §8.2.9 | [x] ENERGY/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-051 | Analog Sensor Calibration Advanced | [ ] | [x] G8 §8.2.9.1 | [x] ENERGY/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-052 | Sensorless tuning/verification | [ ] | [x] G8 §8.2.10 | [x] ENERGY/MOTION/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-053 | Sensorless manual tuning | [ ] | [x] G8 §8.2.10.2 | [x] ENERGY/MOTION/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-054 | Commutation and Sensor Selection | [ ] | [x] G8 §8.2.11.1 | [x] RAM | [~] | [~] | [ ] | [~] | [x] | |
| A-055 | Incremental Sensor + Digital Halls phasing | [ ] | [x] G8 §8.2.11.2 | [x] ENERGY/MOTION/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | current target는 EnDat 2.2 |
| A-056 | Incremental Sensor without Halls phasing | [ ] | [x] G8 §8.2.11.3 | [x] ENERGY/MOTION/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-057 | Absolute Sensor alternate phasing method | [ ] | [x] G8 §8.2.11.4 | [x] ENERGY/MOTION/RAM | [~] signature | [~] | [ ] | [~] | [~] | |
| A-058 | Running Commutation | [ ] | [x] G8 §8.2.11.5 | [x] ENERGY/MOTION | [x] bounded signature | [~] | [ ] | [x] closeout | [x] | EAS 전체 procedure parity 미완 |
| A-059 | Stepper Closed Loop | [ ] | [x] G8 §8.2.12 | [x] ENERGY/MOTION/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-060 | Velocity/Position Identification | [ ] | [x] G8 §8.2.13.1 | [x] MOTION | [x] | [~] | [ ] | [x] | [x] | |
| A-061 | Velocity/Position Design | [ ] | [x] G8 §8.2.13.2 | [x] RAM | [x] | [~] | [ ] | [x] | [x] | |
| A-062 | Velocity/Position Scheduling | [ ] | [x] G8 §8.2.13.3 | [x] RAM | [~] | [ ] | [ ] | [~] | [~] | |
| A-063 | Velocity/Position Verification - Time | [ ] | [x] G8 §8.2.13.4 | [x] MOTION | [~] | [~] | [ ] | [~] | [~] | |
| A-064 | Velocity/Position Verification - Bode | [ ] | [x] G8 §8.2.13.5 | [x] MOTION | [~] | [ ] | [ ] | [~] | [~] | |
| A-065 | Error Mapping Settings | [ ] | [x] G8 §8.3.1 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-066 | Error Mapping Experiment | [ ] | [x] G8 §8.3.2 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-067 | Error Mapping Verification | [ ] | [x] G8 §8.3.3 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-068 | 2-D/3-D Error Correction | [ ] | [x] G8 §8.3.4 | [x] MOTION/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | Maestro 연동은 Scope C |
| A-069 | Gantry Slave/Master tuning | [ ] | [x] G8 §8.4.2~3 | [x] MOTION/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | 다축 gate 필요 |
| A-070 | Gantry Homing/Yaw/Center | [ ] | [x] G8 §8.4.4 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-071 | Drive ECAM configuration | [ ] | [x] G8 §8.5 | [x] RAM/MOTION/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-072 | Drive ECAM Table Editor | [ ] | [x] G8 §8.6/MOD | [x] LOCAL→RAM/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-073 | ECAM table activation/deactivation | [ ] | [x] G8 §8.6.2 | [x] MOTION/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-074 | Automated ID process/experiment settings | [ ] | [x] G8 §8.7.1~3 | [x] LOCAL/RAM | [~] | [ ] | [ ] | [ ] | [~] | |
| A-075 | Automated Sine Sweep Identification | [ ] | [x] G8 §8.7.4 | [x] ENERGY/MOTION | [~] | [ ] | [ ] | [~] | [~] | |
| A-076 | Automated Fast Identification | [ ] | [x] G8 §8.7.5 | [x] ENERGY/MOTION | [~] | [ ] | [ ] | [~] | [~] | |
| A-077 | Automated Closed Loop Bode Verification | [ ] | [x] G8 §8.7.6 | [x] ENERGY/MOTION | [~] | [ ] | [ ] | [~] | [~] | |
| A-078 | Motion Single Axis: Position Loop | [ ] | [x] G8 §8.9.3.1 | [x] MOTION | [x] kernel | [ ] | [ ] | [x] offline | [x] | live NEED-DATA |
| A-079 | Motion Single Axis: Velocity Loop | [ ] | [x] G8 §8.9.3.2 | [x] MOTION | [~] STOP model | [ ] | [ ] | [~] | [~] | |
| A-080 | Motion Single Axis: Current Loop | [ ] | [x] G8 §8.9.3.3 | [x] ENERGY/MOTION | [~] STOP model | [ ] | [ ] | [~] | [~] | |
| A-081 | Motion Single Axis: Stepper UM=3 | [ ] | [x] G8 §8.9.3.4 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-082 | Motion Single Axis: Stepper UM=6 | [ ] | [x] G8 §8.9.3.5 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-083 | Single Axis I/O Status | [ ] | [x] G8 §8.9.4 | [x] READ | [~] telemetry | [~] | — | — | [~] | |
| A-084 | Single Axis Motion Status | [ ] | [x] G8 §8.9.5 | [x] READ | [x] telemetry state | [x] | — | — | [x] | |
| A-085 | Set Session Zero / PX=0 | [ ] | [x] G8/RIB Reset Ref Position | [x] RAM | [x] | [~] pre-read | [ ] | [~] coordinate latch | [x] | fresh approval 필요 |
| A-086 | Motor Enable without profile | [ ] | [x] Gold command/risk catalog | [x] ENERGY | [x] gate | [~] MO read | [ ] | [x] disable closeout | [x] | |
| A-087 | Software DRIVE STOP: ST→MO=0 | [ ] | [x] G8/RIB | [x] SAFETY_STOP | [x] | [~] | — 비차단 | — | [x] | fresh approval/telemetry를 기다리지 않음; independent STO 아님 |
| A-088 | Drive Emulation | [ ] | [x] G8 §8.12.2 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-089 | Application Tool Inputs and Outputs | [ ] | [x] G8 §8.12.3 | [x] DRIVE_STATE/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-090 | Application Tool Verification - Time | [ ] | [x] G8 §8.12.4 | [x] ENERGY/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-091 | Application Tool ECAM/Follower | [ ] | [x] G8 §8.12.5 | [x] RAM/MOTION/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-092 | Direct Reference Command | [ ] | [x] G8 §8.12.6 | [x] ENERGY/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-093 | Cogging Compensation table/sine | [ ] | [x] G8 §8.12.7 | [x] MOTION/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-094 | Drive Output Compare | [ ] | [x] G8 §8.12.8 | [x] DRIVE_STATE/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-095 | Position/Event Capture | [ ] | [x] G8 §8.12.9 | [x] DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | Recorder와 별도 |
| A-096 | Torque Speed Calculator/Motor DB | [ ] | [x] G8 §8.12.10/MOD | [x] LOCAL/READ | [ ] | [ ] | — | — | [ ] | |
| A-097 | Drive Profile Conditioning | [ ] | [x] G8 §8.12.11 | [x] MOTION/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-098 | Halls Correction ID/Verification | [ ] | [x] G8 §8.12.12 | [x] ENERGY/MOTION/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-099 | Constant Identification | [ ] | [x] G8 §8.12.13 | [x] ENERGY/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-100 | Hot Plugging Verification | [ ] | [x] G8 §8.12.14 | [x] DRIVE_STATE/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | 제조사 현장 절차 필요 |
| A-101 | Drive Parameters Explorer read/tree/table | [ ] | [x] G8 §8.14 | [x] READ | [x] Axis Summary | [x] 제한 | — | — | [~] | |
| A-102 | Drive Parameters Explorer typed edit | [ ] | [x] G8 §8.14.1.1 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-103 | Drive Parameters Explorer Online/Offline mode | [ ] | [x] G8 §8.14.4 | [x] LOCAL/READ/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-104 | Parameters Comparison | [ ] | [x] G8 §8.14.5/G12 | [x] LOCAL/READ | [~] transaction diff | [~] | — | — | [~] | |
| A-105 | Feedback 23 sensor panels read/preview | [~] 영상 | [x] G8/Sensor Definitions | [x] READ | [x] | [~] EnDat only | — | — | [x] | 모든 sensor live 검증 아님 |
| A-106 | Feedback assignment write registry | [ ] | [x] G8/Gold CR | [x] RAM/SV | [~] preview reject | [~] baseline | [ ] | [ ] | [~] | exact registry 미완 |
| A-107 | EnDat Encoder Maintenance | [~] EAS dialog 근거 | [x] G8/Gold CR | [x] SV/NVM | [x] | [~] pre/post read | [ ] | [ ] | [x] | deterministic rollback 없음 |
| A-108 | Recorder Target/Filter/Lock Target | [x] screenshot | [x] G12/RIB | [x] READ/DRIVE_STATE | [~] | [~] | — | — | [x] | 단일 target만 |
| A-109 | Recorder Signals editor | [x] screenshot | [x] G12/RIB | [x] DRIVE_STATE | [x] | [~] discovery | [ ] | [x] stop cleanup | [x] | |
| A-110 | Recorder Trigger editor | [x] screenshot | [x] G12/RIB | [x] DRIVE_STATE | [~] | [ ] | [ ] | [~] | [~] | |
| A-111 | Recorder Resolution/Buffer/Record Time | [x] screenshot | [x] G12/RIB | [x] DRIVE_STATE | [x] | [~] | [ ] | [x] | [x] | |
| A-112 | Recorder Single mode | [x] screenshot | [x] RIB | [x] DRIVE_STATE | [x] | [~] | [ ] | [x] | [x] | Immediate finite |
| A-113 | Recorder Rollover mode | [x] screenshot | [x] RIB | [x] DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [~] | |
| A-114 | Recorder Normal mode | [x] screenshot | [x] RIB | [x] DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [~] | |
| A-115 | Recorder Auto mode | [x] screenshot | [x] RIB | [x] DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [~] | |
| A-116 | Recorder Interval mode | [x] screenshot | [x] RIB | [x] DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [~] | |
| A-117 | Recorder Start/Immediate | [x] screenshot | [x] G12/RIB | [x] DRIVE_STATE | [x] | [~] | [ ] | [x] | [x] | |
| A-118 | Recorder Upload Buffer | [x] screenshot | [x] G12/RIB | [x] DRIVE_STATE | [x] | [~] | [ ] | [x] | [x] | |
| A-119 | Recorder Stop | [x] screenshot | [x] G12/RIB | [x] DRIVE_STATE | [x] | [~] | [ ] | [x] | [x] | motion STOP과 분리 |
| A-120 | Recorder preset Load/Save/Manage | [x] screenshot | [x] RIB/ProgramData | [x] LOCAL→DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [~] | EAS native preset 미지원 |
| A-121 | Recorder View Design/chart layout | [x] screenshot | [x] G12/RIB | [x] LOCAL | [x] | — | — | — | [x] | local-only |
| A-122 | Recorder Cursor/Rider/A-B selection | [x] screenshot 일부 | [x] G12/RIB | [x] LOCAL | [x] | — | — | — | [x] | exact EAS glyph parity 미완 |
| A-123 | Recorder Chart Editor | [ ] | [x] G12 §12.1.10 | [x] LOCAL | [~] local layout | — | — | — | [~] | |
| A-124 | Recorder Recording File Editor/Import/Organize | [ ] | [x] G12 §12.1.11 | [x] LOCAL | [ ] | — | — | — | [ ] | EAS native format 필요 |
| A-125 | Recorder Analysis Calculator offline | [ ] | [x] G12 §12.1.12 | [x] LOCAL | [x] FFT/statistics | — | — | — | [x] | STAND-IN 범위 명시 |
| A-126 | Recorder Analysis Calculator online | [ ] | [x] G12 §12.1.12 | [x] READ/DRIVE_STATE | [~] local only | [ ] | [ ] | [ ] | [~] | |
| A-127 | Recorder standalone Viewer | [ ] | [x] G12 §12.1.14/MOD | [x] LOCAL | [~] 자체 viewer | — | — | — | [~] | EAS recording 호환 아님 |
| A-128 | Recorder CSV와 provenance export | [ ] | [x] G12 + local contract | [x] LOCAL | [x] | — | — | — | [x] | EAS Save As parity 아님 |
| A-129 | Status Monitor configurable lines | [ ] | [x] G12 §12.3 | [x] LOCAL(v0.1)→READ(full) | [x] fixed allowlist model/UI | [~] existing core telemetry only | — | [x] full blank fail-closed | [x] v0.1 boundary | session-only PX/VX/PE/IQ/MO; local 16-line cap은 EAS 최대값이 아님; EAS 0.5 s arbitrary variables/arrays/multi-target/user units/gauge는 NEED-DATA |
| A-130 | Status Monitor save/load configuration | [ ] | [x] G12 §12.3.1.3~4 | [x] LOCAL_FILE/NEED-DATA | [ ] | — | — | — | [x] boundary | 미구현·잠금; Save/Replace `.smc`, Append 설명 `.sac`→`.smc` 모순; fixture/schema/round-trip 필요 |
| A-131 | Fault/Status/Log Manager | [ ] | [x] G12/RIB 일부 | [x] LOCAL(v0.1)→READ/DRIVE_STATE(full); full NEED-DATA | [x] host model/UI zero-I/O/export | [~] raw status; drive history 아님 | [ ] | [ ] | [x] v0.1 boundary | host-observed viewer only; Full EAS history/taxonomy/Ack/Clear/Reset는 NEED-DATA/disabled |
| A-132 | Floating Control Parameters | [ ] | [x] G11 §11.2 | [x] READ/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-133 | Floating Single Axis Motion | [ ] | [x] G11 §11.3 | [x] MOTION | [~] page backend | [ ] | [ ] | [~] | [ ] | actual floating UI 없음 |
| A-134 | Floating Status Monitor | [ ] | [x] G11 §11.5 | [x] LOCAL(v0.1)→READ(full) | [x] modeless host UI | [~] existing core telemetry only | — | [x] display blank | [x] v0.1 boundary | modeless only; EAS Quick Watch/topmost/compact display와 full polling은 NEED-DATA |
| A-135 | Floating Application Tools | [ ] | [x] G11 §11.6 | [x] 포함 도구별 | [ ] | [ ] | [ ] | [ ] | [ ] | |
| A-136 | Floating Recorder | [ ] | [x] G11 §11.8 | [x] DRIVE_STATE | [~] page recorder | [~] | [ ] | [~] | [ ] | |
| A-137 | File Backstage: New/Open/Save/Save As workspace lifecycle | [x] menu label | [x] G3/RIB | [x] LOCAL | [~] local recorder workspace | — | — | [~] local file | [~] | EAS native schema/round-trip 미확정 |
| A-138 | Help/About/Release Notes | [x] backstage | [x] RIB/installed release notes | [x] LOCAL | [ ] | — | — | — | [~] | exact evidence path/hash 연결 필요 |
| A-139 | Share/external export integration | [x] menu label | [~] RIB | [x] NEED-DATA | [ ] | [ ] | [ ] | [ ] | [ ] | destination, network/external side effect 미확정; scoring disabled |
| A-140 | Drive Vector parameter upload | [x] ribbon label | [x] G7/RIB | [x] READ | [ ] | [ ] | — | — | [ ] | typed/vector schema 미확정 |
| A-141 | Drive Vector parameter download | [x] ribbon label | [x] G7/RIB | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | dry-run diff와 target binding 필요 |
| A-142 | Workspace Files Configure selection | [x] ribbon label | [x] G7/RIB | [x] LOCAL | [ ] | — | — | [ ] | [ ] | 실제 download side effect는 A-014에서 검증 |

## Scope B — Network, Programming, Multi-axis

| ID | EAS 기능 | EAS 관찰 | 공개 근거 | 위험 분류 | Offline test | Read-only live | 승인 Mutation | Rollback | Docs | 메모 |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---|
| B-001 | CAN Maestro Configuration | [ ] | [x] G6/MOD/RIB | [x] DRIVE_STATE/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-002 | EtherCAT Master Settings/Quick Settings | [ ] | [x] G5 §5.2 | [x] DRIVE_STATE/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-003 | EtherCAT master state/diagnostics/system/process image/cyclic | [ ] | [x] G5 §5.2.3~6 | [x] READ/DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-004 | EtherCAT Distributed Clocks/Aliasing/Hot Connect/S2S/Safety Master | [ ] | [x] G5 §5.2.7~10 | [x] RAM/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-005 | EtherCAT Slave State/Diagnostics/FMMU/SM/PDO | [ ] | [x] G5 §5.3.1~4 | [x] READ/RAM | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-006 | EtherCAT Mailbox/Init/DC/Memory/EEPROM | [ ] | [x] G5 §5.3.6~10 | [x] RAM/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-007 | EtherCAT Bridge automatic/manual configuration | [ ] | [x] G5 §5.3.11 | [x] DRIVE_STATE/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-008 | Motion Multiple Axes | [ ] | [x] G8 §8.10/RIB | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | operation catalog NEED-DATA |
| B-009 | Group Motion | [ ] | [x] G8 §8.8/RIB | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-010 | Multi Drive Recording/Manage Drives | [x] screenshot | [x] RIB | [x] 다축 DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [~] | |
| B-011 | Floating Multi Axis Motion | [ ] | [x] G11 §11.4 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-012 | Drive Script Manager editor/state machine/truth table | [ ] | [x] G8 §8.11/RIB | [x] LOCAL→RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | command-level classifier 필요 |
| B-013 | Drive Script Manager motion/debug | [ ] | [x] G8 §8.11 | [x] ENERGY/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-014 | Command Macros create/load/run | [ ] | [x] G8 §8.13/G12 | [x] READ→RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-015 | Floating Terminal/Smart Terminal | [ ] | [x] G11/G12/MOD | [x] READ→RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | unrestricted terminal 금지 |
| B-016 | Drive Programming project/program/editor | [ ] | [x] G9 §9.1~2.6 | [x] LOCAL | [ ] | — | — | — | [ ] | |
| B-017 | Drive Programming compile/build | [ ] | [x] G9 §9.2.4~5/MOD | [x] LOCAL | [ ] | — | — | — | [ ] | exact target compiler 필요 |
| B-018 | Drive program download/link | [ ] | [x] G9 §9.2.5~8 | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-019 | Drive program run/debug/breakpoint/watch/thread | [ ] | [x] G9 §9.2.9~14 | [x] ENERGY/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-020 | EAS native workspace import/export | [ ] | [x] G3/G7 | [x] LOCAL→RESET-FLASH | [ ] | — | [ ] | [ ] | [ ] | schema NEED-DATA |
| B-021 | EAS native parameter file round-trip | [ ] | [x] G7/G8 | [x] LOCAL→RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-022 | EAS native recording/preset file round-trip | [ ] | [x] G12/RIB | [x] LOCAL/DRIVE_STATE | [ ] | — | [ ] | [ ] | [ ] | |
| B-023 | Multi-target Fault/Event Logger | [ ] | [x] G12/RIB | [x] READ/DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | |
| B-024 | Floating EtherCAT Diagnostics | [x] ribbon label | [x] G11/MOD/RIB | [x] READ/DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | master/slave target applicability 미검증 |

## Scope C — Maestro/Platinum Conditional

| ID | EAS 기능 | EAS 관찰 | 공개 근거 | 위험 분류 | Offline test | Read-only live | 승인 Mutation | Rollback | Docs | 메모 |
|---|---|---:|---|---|---:|---:|---:|---:|---:|---|
| C-001 | Maestro Configurator Global/Error/Gearing | [ ] | [x] G10 §10.2.1 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | target 없음 |
| C-002 | Maestro I/O/Touch Probe/Packages/Extended/Analog I/O | [ ] | [x] G10 §10.2.1.4~8 | [x] DRIVE_STATE/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-003 | Maestro Time Capture/Encoders/Emulation/Output Compare | [ ] | [x] G10 §10.2.1.9~14 | [x] DRIVE_STATE/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-004 | Maestro Single Axis Config/User Units/Limits/Settling | [ ] | [x] G10 §10.2.2 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-005 | Maestro Group Axis/Kinematic configuration | [ ] | [x] G10 §10.2.3 | [x] RAM/MOTION/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-006 | Maestro Script Manager | [ ] | [x] G10 §10.3 | [x] LOCAL→RESET-FLASH/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-007 | Maestro Axis Motion cyclic position/velocity/torque | [ ] | [x] G10 §10.4.2.1~4 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-008 | Maestro Profile/Interpolated Position/Homing | [ ] | [x] G10 §10.4.2.5~9 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-009 | Modbus Configuration | [ ] | [x] G10 §10.5/MOD | [x] DRIVE_STATE/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-010 | Maestro EtherCAT Diagnostics | [ ] | [x] G10 §10.6/MOD | [x] READ/DRIVE_STATE | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-011 | Maestro Parameters Explorer | [ ] | [x] G10 §10.7 | [x] READ/RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-012 | Maestro ECAM/Table Editor | [ ] | [x] G10 §10.8~9 | [x] RAM/MOTION/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-013 | Move & Settle | [ ] | [x] G10 §10.10/MOD | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-014 | PVT/PT/P/Splines Table Editor | [ ] | [x] G10 §10.11/MOD | [x] LOCAL→MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-015 | Path Editor | [ ] | [x] G10 §10.12/MOD | [x] LOCAL→MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-016 | Maestro Status Viewer | [ ] | [x] G10 §10.13/MOD | [x] READ | [ ] | [ ] | — | — | [ ] | |
| C-017 | Maestro Group Motion/MCS/PCS/Homing | [ ] | [x] G10 §10.14 | [x] MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-018 | G-Code Editor/runtime | [ ] | [x] G10 §10.15/MOD | [x] LOCAL→MOTION/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-019 | Maestro SIL setup/model/identification | [ ] | [x] G10 §10.16/MOD | [x] LOCAL→ENERGY/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-020 | Blockly Editor/upload/debug | [ ] | [x] G10 §10.17/MOD | [x] LOCAL→RESET-FLASH/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-021 | Python Programming/packages/download/debug | [ ] | [x] G10 §10.18/MOD | [x] LOCAL→RESET-FLASH/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-022 | Maestro Browser/file transfer | [ ] | [x] G11 §11.16/MOD | [x] LOCAL→SV/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-023 | Maestro Event Logger | [ ] | [x] G12 §12.7/MOD | [x] READ | [ ] | [ ] | — | — | [ ] | |
| C-024 | Platinum Functional Safety configuration | [ ] | [x] P9 §9.2.5 | [x] RAM/SV/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | certification 별도 |
| C-025 | Platinum Safety I/O Configuration | [ ] | [x] P9 §9.2.6 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-026 | Platinum Sensor Memory Access | [ ] | [x] P9 §9.2.7.4 | [x] SV/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-027 | Platinum Stopping Options | [ ] | [x] P9 §9.2.9.4 | [x] RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | safety decision |
| C-028 | Safety Function/IO/Enable/Sign & Report | [ ] | [x] P9 §9.2.15.1~4 | [x] RAM/SV/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-029 | Safety Monitoring/Validation/Acceptance | [ ] | [x] P9 §9.2.15.5~7/MOD | [x] READ→RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | UI parity는 인증 아님 |
| C-030 | BBH/SCU-1-EC Configuration | [ ] | [x] P9 §9.3 | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-031 | Drive SIL Dashboard/Model/Identification | [ ] | [x] P9 §9.10/MOD | [x] LOCAL→ENERGY/MOTION | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-032 | Platinum Kinematic Editor | [ ] | [x] P9 §9.14.17 | [x] RAM/MOTION/SV | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-033 | Platinum Sensory Memory Access | [ ] | [x] P9 §9.14.18 | [x] SV/RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | |
| C-034 | Non-Linear Current FF | [ ] | [~] RIB/MOD only | [x] RAM/ENERGY/SV | [ ] | [ ] | [ ] | [ ] | [ ] | target/menu applicability UNVERIFIED |
| C-035 | Maestro User File upload/download administration | [x] ribbon label | [x] G7/RIB/MOD | [x] READ→RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | target/package/recovery contract 필요 |
| C-036 | Maestro Parameters upload/download | [x] ribbon label | [x] G7/G10/RIB | [x] READ→RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | Maestro target 없음 |
| C-037 | Safety Textual Parameters upload/download | [x] ribbon label | [x] P9/RIB | [x] READ→RAM/SV | [ ] | [ ] | [ ] | [ ] | [ ] | certification evidence와 별도 |
| C-038 | Drive SIL administration/download | [x] ribbon label | [x] P9/G7/RIB/MOD | [x] RESET-FLASH | [ ] | [ ] | [ ] | [ ] | [ ] | exact package/target/recovery 미확정 |

## Grouped coverage와 scoring hold

- `Drive Tools`, `Floating Tools`, ribbon group, launcher 이름은 그 자체를 별도 기능 완료로 점수화하지 않는다.
  실제 동작은 위의 child 기능 ID에서만 평가한다.
- `Share`의 destination/credential/network 동작, vendor service 전용 administration, 문자열 리소스에만 있는
  target-conditional 항목은 side effect와 공개 contract가 확인될 때까지 A-139/C-034의 grouped
  `NEED-DATA` coverage로 유지하고 진행률 numerator에서 제외한다.
- 새로 분리한 A-137~A-142, B-024, C-035~C-038은 기존 ID를 renumber하지 않는 inventory 보완이다.
  label을 관찰했다는 사실은 해당 기능 실행, 구현 또는 parity를 의미하지 않는다.

## 완료 규칙

1. 공개 근거와 위험 분류만 완료된 행은 구현 진척으로 계산하지 않는다.
2. EAS UI 관찰이 없는 행은 field와 상태 전이 parity를 완료로 선언할 수 없다.
3. Read-only live가 필요한 행은 exact target identity와 빈 write transcript가 있어야 한다.
4. 승인 Mutation은 실행 직전의 새 승인만 유효하며, 이 checklist의 checkbox가 승인을 대신하지 않는다.
   SAFETY_STOP과 disconnect cleanup은 approval/telemetry 대기로 차단하지 않되, 확인되지 않은 closeout은
   UNKNOWN으로 기록한다.
5. ENERGY 이상은 verified closeout가 없으면 Rollback을 완료로 표시하지 않는다.
6. SV와 RESET-FLASH는 power-cycle/reboot 후 full audit 없이는 완료가 아니다.
7. Scope C safety 기능은 official certification evidence가 없으면 최종 verdict를 NEED-DATA로 유지한다.
