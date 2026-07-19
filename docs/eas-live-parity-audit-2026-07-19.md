# EAS III Live Parity Audit · 2026-07-19

상태: **IN PROGRESS · READ-ONLY/UI OBSERVATION ONLY · FULL PARITY NOT CLAIMED**

이 문서는 지금까지 구현한 AngryYJH 기능을 실제 EAS III 3.0.0.26과
처음부터 다시 대조한 원장이다. 기계 안전성, 제어 성능, 다른 Gold 제품 호환성,
독립 STO/E-stop 또는 생산 사용 적합성 판정이 아니다.

## 세션 경계

- 관찰 시각: 2026-07-19 19:08–19:35 KST.
- 대상: 현재 Gold Twitter `Drive01`, firmware
  `Twitter 01.01.16.00 08Mar2020B01G`.
- EAS executable:
  `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\ElmoMotionControl.View.Main.exe`,
  version 3.0.0.26, SHA-256
  `C8A023EA6DCEF8BC39E3E86E0AF929269AB47BB5B8791EB99FB9A62080F719ED`.
- repository baseline: branch `codex/quick-single-axis-handoff`, audit 시작 HEAD
  `995b5969b8858711c8083e6b7d2c4471b3e38d35`.
- 연결: COM3를 EAS와 AngryYJH가 번갈아 단독 소유했다. 두 프로그램을 동시에
  연결하지 않았다.
- 상태: Motor Disabled, Velocity 0, Active Current 0.
- 실행한 drive 명령: EAS Terminal의 assignment 없는 정확한 read-only query
  `PX`, `PU`, `XM[1]`, `XM[2]`, `FC[1]`, `FC[2]`, `FC[5]`, `FC[6]`,
  `FC[7]`, `FC[8]`, `CA[45]`, `CA[91]`, `OV[9]`, `OV[39]`, `HM[2]`,
  `FP[1]`과 AngryYJH의 기존 bounded read-only refresh.
- 실행하지 않은 것: Enable, tuning/identification/commutation/Verify,
  PTP/Jog/Current/Sine/Homing, Recorder acquisition, assignment, Apply/Revert,
  Save/SV, upload/download, firmware/PAL 변경.
- target serial은 이 문서에 기록하지 않는다.

판정은 `eas_live_parity.py`의 immutable ledger와
`tests/test_eas_live_parity.py`가 고정한다.

## 결정적 발견

### 1. EAS 표시 위치는 raw `PX`가 아니라 `PU`다

| 관찰점 | 값 |
|---|---:|
| EAS Terminal raw `PX` | `-2038379934 cnt` |
| EAS Terminal `PU` (`DS402 0x6064`) | `-2004825502 user units` |
| AngryYJH bounded raw `PX` | `-2038379934 cnt` |
| EAS Single Axis / V/P Verification-Time 표시 | `-2004825502 cnt` |
| `PU-PX` | `33554432 = 2^25` |
| `XM[1]`, `XM[2]` | `0`, `0` |
| `FC[1,2,5,6,7,8]` | 모두 `1` |
| `CA[45]` | `1` |

EAS Single Axis 표시는 정확히 `PU`와 일치한다. 따라서 “EAS가 raw PX를
화면에서 임의 변환한다”는 이전 설명은 폐기한다. `PX`는 raw main-position
socket counts, `PU`는 EAS/DS402 user-position 좌표로 별도 authority다.
다만 현재 `FC=1`, `XM=0`, `CA[45]=1`, `CA[91]=0`, `OV[9]=0`,
`OV[39]=0`, `HM[2]=0`인데도 `PU-PX=2^25`인 firmware-internal 좌표 원점은
아직 규명되지 않았다. 앱은 둘을 모두 표시하고 그 차이를 자동 보정값으로
사용하지 않는다.

### 2. Current 화면은 기능 의미가 다름

EAS Single Axis Current 탭은 `Current Command 1..5`의 편집 가능한 5개
host preset과 Set 버튼이다. 각 row tooltip에서 동일한 `[TC]` target을
관찰했고, motor disabled 상태에서는 모든 Set이 비활성화됐다. AngryYJH는
기존 `TC/IQ/ID/CL[1]/PL[1]/LC/MC` query-only readback과 별도로 동일한
5개 로컬 draft를 구현했다. 현재 Set은 항상 잠겨 있고 signal/worker job/drive
I/O가 없으므로 판정은 `PARTIAL_LIVE_OBSERVED / OUTPUT LOCKED`다.

### 3. 설정값과 식별값을 섞으면 안 됨

EAS Motor Settings의 configured `R=0.1316 Ω`, `L=0.0395 mH`와 이전 AngryYJH
P1 식별 candidate 약 `0.139 Ω`, `0.0416 mH`는 서로 다른 authority다.
configured motor DB 값과 실기 identification 결과를 “같은 값의 parity”로
합치지 않는다.

## Quick Tuning

| 기능 | EAS live 관찰 | AngryYJH 현재 동작 | 판정 |
|---|---|---|---|
| Axis Configuration | Single Axis, rotary motor/load, single feedback, Position UM=5 | 같은 guided 축 구성을 설명/선택 | `PARTIAL_LIVE_OBSERVED` |
| Motor Settings | current/speed/poles/R/L/Ke configured fields | profile readback + 별도 P1 measurement | `PARTIAL_LIVE_OBSERVED` |
| Feedback Settings | Serial Absolute EnDat 2.2, Port A, Position+Velocity+Commutation | EnDat panels + 별도 Encoder Maintenance | `PARTIAL_LIVE_OBSERVED` |
| Automatic Tuning flow | Initialization→Current ID→Current Design→Commutation→V/P ID→V/P Design | 같은 6단계 guided flow | `LIVE_UI_OBSERVED`; 실행 안 함 |
| Start phase / Full Log | 실제 control 관찰 | 일부 local/gated workflow | `NOT_EXECUTED_NEED_DATA` |

## Expert Tuning

| 기능 | EAS live 관찰 | AngryYJH 현재 동작 | 판정 |
|---|---|---|---|
| Tree/page status | 실제 page tree, Current Limits red invalid warning | local model status inspector | `UI_SEMANTICS_MISMATCH` |
| User Units | No Conversion, factor 1, on motor | explicit-input DS-402 formula | `DOC_ONLY` |
| Current Limits | MC 140, BV 100, PL1 70.7107, CL1 21.2132, PL2 3, US 100/100 | static parameter map | `DOC_ONLY` |
| Motion Limits/Modulo | SD 1e6, VH2 3932160, No Modulo, position limits ignored | static parameter map | `DOC_ONLY`; live motion lock 근거 |
| Protections | ER/CL motor-stuck fields | static parameter map | `DOC_ONLY` |
| Settling Window | position/velocity 100, time 20 ms | static map | `DOC_ONLY` |
| Inputs/Outputs | Inputs 1..6 active GP, outputs 1..4 inactive GP | bounded read-only snapshots | `VALUE_PARITY_OBSERVED` |
| Current Identification | phases A/B/C, 60% PL, R/L configured | P1 identification + local model | UI 관찰만; 실행 안 함 |
| Current Design | 5 kHz, 59°, KP 0.086, KI 782.52 | KP 0.0857, KI 782.5188 | 반올림 `VALUE_PARITY_OBSERVED` |
| Current Verification-Time | KP 0.0857, KI 782.5188 | installed-gain readback | exact `VALUE_PARITY_OBSERVED`; Verify 안 함 |
| Commutation | Absolute Serial, 100% CL, 1.4 el.cycles | bounded 1.30 A signature | `UI_SEMANTICS_MISMATCH`; EAS run 안 함 |
| V/P Identification | Fast, open loop, 100% CL | 별도 low-current Phase 2 | `UI_SEMANTICS_MISMATCH`; 실행 안 함 |
| V/P Design | KP2≈0.000196, KI2 10.7, KP3 85.2114, FF/filter | 0.0002, 10.7000, 85.2114 + doc filter map | gain `VALUE_PARITY_OBSERVED`; filter는 `DOC_ONLY` |
| Scheduling | Off, PIP/filter tabs | documented topology | `DOC_ONLY` |
| V/P Verification-Time | motion controls, gains, filters, Recorder | static Time map | `DOC_ONLY`; motion/Verify 안 함 |
| Hidden Bode | 현재 tree에 표시되지 않음 | static hidden-page map | `DOC_ONLY`; 실제 visibility/Verify 미확인 |
| Summary | SV/upload/design export/DB import choices | static authority map | `DOC_ONLY`; Save 안 함 |

Brake page는 `Using Brake=false`인 현재 EAS tree에서 별도 page로 나타나지 않았다.
따라서 기존 Brake inspector는 현재 target parity가 아니라 문서 map이다.

## Single Axis

| 기능 | EAS live 관찰 | AngryYJH current read | 판정 |
|---|---|---|---|
| Motion status | Disabled, velocity/current 0 | 같은 disabled/zero 상태 | `PARTIAL_LIVE_OBSERVED` |
| raw PX | Terminal `-2038379934` | `-2038379934` | `VALUE_PARITY_OBSERVED` |
| Position display | `PU=-2004825502` | raw `PX`와 `PU`를 분리 표시 | 표시값 `VALUE_PARITY_OBSERVED`; 좌표 원점 `NEED-DATA` |
| Position profile | AC/DC/SD 1e6, SP 4444444, PA/PR 0 | 같은 query 결과 | `VALUE_PARITY_OBSERVED`; motion 안 함 |
| Velocity | Jog/profile controls | JV/SP/VX readback | 값 parity; Jog 안 함 |
| Current | five host presets, each `[TC]`; Set disabled with motor off | 별도 5 local drafts + current/limit readback; Set always locked | `PARTIAL_LIVE_OBSERVED / OUTPUT LOCKED` |
| Sine/Step | amplitude/frequency/offset/injection controls | documented authority row | `NOT_EXECUTED_NEED_DATA` |
| Homing | Method 1, Main Position Socket, offset 0, speeds 1000 | documented authority row | `NOT_EXECUTED_NEED_DATA` |
| Digital Inputs | 1..6 active, GP | 1..6 active, GP, active-high, 0 ms | logical `VALUE_PARITY_OBSERVED` |
| Digital Outputs | 1..4 inactive, GP | 1..4 inactive, GP, active-high | logical `VALUE_PARITY_OBSERVED` |
| Drive Mode | Position UM=5 | UM=5 Position | `VALUE_PARITY_OBSERVED` |
| Enable/Stop | controls 관찰 | Enable locked, bounded Stop+Disable | 실행 안 함 |
| Terminal | unrestricted EAS terminal | unrestricted terminal 없음 | exact PX query만 관찰 |
| Recorder docking | Terminal + two charts | Recorder separate page | `UI_SEMANTICS_MISMATCH` |
| Encoder Maintenance | EnDat Feedback page의 Open entry | bounded TW maintenance surface | entry만 `PARTIAL`; write 안 함 |

EAS의 STO1/STO2 green indicators는 화면 관찰일 뿐 독립 STO 배선/torque isolation
시험 증거가 아니다.

## Recorder

| 기능 | EAS live 관찰 | AngryYJH 현재 동작 | 판정 |
|---|---|---|---|
| Ribbon | target/filter/lock, resolution, 8 s buffer, duration, modes | 유사 ribbon과 명시적 locks | `PARTIAL_LIVE_OBSERVED` |
| Trigger/Signals | native dialogs/buttons | Personality signal discovery; trigger 일부 placeholder | `PARTIAL` |
| Single/Rollover/Normal/Auto/Interval | 실제 options 관찰 | Immediate finite subset | 나머지 `NOT_EXECUTED_NEED_DATA` |
| Start/Immediate/Upload/Stop | 실제 controls 관찰 | Immediate backend | EAS acquisition 미실행 |
| Preset/Manage/Multi Drive | 실제 controls 관찰 | local JSON/disabled placeholders | `STAND_IN`/`NEED_DATA` |
| Two charts/View Design | native charts | local time/FFT/A:B/statistics | `STAND_IN`; native interaction/file parity 아님 |

## 공통 셸과 persistence

| 기능 | 결과 |
|---|---|
| System Configuration | target/board/firmware/PAL/COM route `VALUE_PARITY_OBSERVED` |
| Top menus/ribbons | inventory `PARTIAL_LIVE_OBSERVED`; 개별 command behavior 미실행 |
| Tool Organizer / Status Monitor / Log | local stand-in; native EAS persistence/polling parity 아님 |
| Apply/Revert/Apply All | 미실행, `NEED_DATA` |
| Save/SV/upload/export/DB | 미실행, 서로 다른 authority로 계속 분리 |
| Firmware/PAL download | 범위 밖 고위험 기능, 실행 안 함 |

## 과거 구현 전수 재분류

| AngryYJH 구현 | 대응 EAS 기능 | 현재 판정 |
|---|---|---|
| Motor profile | Quick/Expert Motor Settings | current page/value 일부만 live 관찰; full field/write parity 아님 |
| Motor durable transaction | Apply/Revert/Save/SV | offline fault-injection 증거만; EAS transaction 미실행 |
| 23 sensor panels | Feedback Settings | EnDat 2.2만 live 관찰; 나머지 sensor field parity 미검증 |
| Feedback preview/reject | EAS validation/Apply | local fail-closed stand-in; native validation/write parity 아님 |
| Axis Summary | 여러 EAS Axis/Feedback/User Unit page | UM/EnDat 일부 일치; one-page parity oracle 없음 |
| Phase 1 | Current ID/Design/Verify | design/installed value parity, EAS experiment 미실행 |
| Phase 2 | V/P ID/Design/Verify | installed gain parity, identification procedure mismatch |
| Installed-gain Verify | EAS Time/Bode Verify | contract만 구현; 실제 Verify 미실행 |
| Session Zero | Zero Position | control 존재; 이번 감사에서 PX=0 미실행 |
| finite PTP | PTP Absolute/Relative | backend 존재·live lock; 양쪽 모두 motion 미실행 |
| Recorder CSV/provenance | EAS Save/Save As | local stand-in; EAS file 호환성 미검증 |
| Recorder FFT/A:B statistics | EAS View Design/statistics | local/static-IL stand-in; native interaction parity 미검증 |
| Status/Session Log | EAS status/fault manager | host-observed log; drive fault history가 아님 |
| Tool Organizer | EAS tool activity/Favorites | session-only stand-in; native persistence 미검증 |
| Host Status Monitor | EAS Status Monitor/Quick Watch | fixed-signal projection; native polling/config parity 아님 |
| Persistence Audit | EAS page/apply/save state | app-local safety ledger; EAS transaction 결과가 아님 |
| DRIVE STOP | EAS global/page Stop | ST→MO=0 software escape; 이번 감사 미실행, STO 아님 |

## 현재 결론

- raw drive 값과 일부 설계값의 대조는 강해졌다.
- 화면 구조가 비슷하다는 사실은 기능 parity가 아니다.
- 현재 구현 중 EAS와 실제 값 parity가 관찰된 것은 raw PX, PU display, UM, motion profile
  query, Digital I/O logical state, installed P1/P2 gains의 제한된 범위다.
- Current preset의 UI shape와 `[TC]` mapping은 대조했지만 실제 Set/enable은
  실행하지 않았다. commutation, V/P identification, Recorder native workflow는
  여전히 의미나 절차가 다르다.
- User Units, Limits/Protections, Application Settings, Bode/Time, Summary의
  대부분은 문서 inspector이며 실제 EAS 기능 구현으로 부르면 안 된다.
- motion/energization/write/save 경로는 이 감사에서 검증하지 않았다.

## 소프트웨어 검증

- TDD RED:
  - EAS Current 5-preset UI와 app current readback의 의미 분리.
  - EAS display=`PU`, raw=`PX`, `PU-PX=2^25`의 이중 좌표 계약 고정.
  - Motor/Feedback/Axis/Session Zero/PTP/Tool Organizer/Status/Recorder export
    등 과거 구현 누락을 audit ledger에서 검출.
- 신규 PX/PU + Current preset 집중: `142 passed in 34.79s`.
- 직접 영향 범위: `284 passed in 133.72s`.
- 전체 repository: `1956 passed in 692.83s (11:32)`, exit 0,
  skip/xfail summary 없음.
- 위 시험은 코드 계약을 검증하며 EAS field behavior나 hardware safety를
  대신하지 않는다.

## 다음 게이트

1. 완료: UI에서 Current readback과 EAS Current local drafts를 분리하고
   출력은 잠갔다.
2. 완료/잔여: raw PX와 EAS `PU`를 이중 authority로 표시했다. 남은 일은
   `PU-PX=2^25` firmware-internal 좌표 원점을 vendor 문서/공식 API/통제된
   관찰로 규명하는 것이다.
3. 모든 read-only value page는 same-session EAS observation과 앱 snapshot을
   timestamp/identity-bound artifact로 남긴다.
4. energizing/motion/write 기능은 별도 승인과 현장 safety gate 없이는 parity
   실행 대상으로 올리지 않는다.
