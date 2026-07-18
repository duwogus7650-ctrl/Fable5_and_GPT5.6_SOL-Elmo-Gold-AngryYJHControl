# Expert Verification – Time · Documented Map v0.1

## 범위와 판정

이 기능은 설치된 EAS III 도움말에 나타난 Expert Tuning의
`Current Verification - Time`과 `Velocity / Position Verification - Time`
화면을 읽기 전용 정적 카탈로그로 정리한다. 실제 EAS 화면 상태, 드라이브
상태, Recorder 상태 또는 시험 결과를 읽는 기능이 아니다.

- model id: `expert_time_verification_documented_map_v0_1`
- authority: `DOCUMENTED_TIME_VERIFICATION_MAP_ONLY`
- model status: `PARTIAL_NEED_DATA`
- fidelity: `DOCUMENTED_STATIC_REFERENCE`
- canonical shape: **3 sections × 8 rows = 24 rows**
- inspect operation:
  `tuning.expert.time_verification.evidence.inspect`
  (`LOCAL_UI / PARTIAL`)
- Current 실제 실행 gap:
  `tuning.expert.time_verification.current.execute`
  (`ENERGIZING / NEED_DATA`)
- Velocity/Position 실제 실행 gap:
  `tuning.expert.time_verification.velocity_position.execute`
  (`MOTION / NEED_DATA`)

실제 실행 operation 두 개는 menu-disabled이며 실행 gate 계약도 아직 없다.
이는 실행 허가가 아니라 실행에 필요한 계약 자체가 미완성이라는 뜻이다.
따라서 actual execution 판정은 모두 **NEED-DATA / NO-GO**다.

## 고정 zero-I/O 경계

고정 boundary는 다음과 같다.

`STATIC DOCUMENT MAP ONLY · DOCUMENTED TIME VERIFICATION MAP ·
PARTIAL / NEED-DATA · NOT EAS VERIFICATION RESULT ·
NOT CURRENT DRIVE STATE · NOT RECORDER STATE ·
NOT MODEL/MEASUREMENT PARITY · NOT A SAFETY ASSESSMENT ·
NO DRIVE READ · NO RECORDER CONFIGURATION · NO ACQUISITION ·
NO EVALUATION · NO VERIFY · NO ENABLE/PTP/JOG/SINE/STEP ·
NO COMMAND/WRITE/APPLY/SV · NO RECORDING ·
NO ENERGIZATION/MOTION · UI STOP IS NOT STO/E-STOP · NO DRIVE I/O`

`can_inspect`만 `True`다. 다음 capability는 모두 `False`다.

- drive/current/Recorder 상태 관찰
- validation, evaluation, acquisition, Recorder 구성
- command 생성, write, Apply, Revert, persist
- Verify, Enable/Disable, energization, injection, motion, recording
- hardware stop, pass 판정, safety 판정

모델 import, snapshot 생성, section lookup과 UI section 전환은 파일,
process, network, worker, Recorder 또는 drive I/O를 만들지 않아야 한다.

## 3 × 8 고정 문서맵

모든 행의 access는
`document: inspect-only · app: inspect-only`다. 값, 상태, waveform,
Recorder 결과 또는 현재 드라이브 설정은 샘플링하지 않는다.

### 1. Current Verification - Time · EAS III §8.2.8.3

| Key | Documented control | Evidence status |
|---|---|---|
| `controller_fine_tuning` | Controller Gain `KP[1]` / Controller Integral `KI[1]` | `DOCUMENT_CONFLICT` |
| `experiment_type` | Auto / Single | `NEED_DATA` |
| `excitation_type` | Sine / Step | `DOCUMENTED_HIGH_RISK_INPUT` |
| `test_phases` | A / B / C phases | `DOCUMENTED_HIGH_RISK_INPUT` |
| `unbalanced_vertical_axis` | Unbalanced / Vertical Axis | `DOCUMENTED_HIGH_RISK_INPUT` |
| `verify` | Verify | `DOCUMENTED_HIGH_RISK_ACTION` |
| `advanced_current_frequency` | Minimum / Maximum Current + Frequency | `NEED_DATA` |
| `advanced_limits_voltage` | `XP[6]`, `XP[5]`, `US[1]`, `US[2]`, Show Phase Voltage | `DOCUMENT_CONFLICT` |

`KP[1]`과 `KI[1]`은 화면 구조를 설명할 뿐 installed gain이나 추천값이
아니다. Auto/Single의 반복·종료 의미와 Sine/Step의 amplitude, offset,
rise time, duration, phase order는 확정되지 않았다.

### 2. Velocity / Position Recording Setup · EAS III §8.2.13.4

| Key | Documented control | Evidence status |
|---|---|---|
| `signals` | Signals | `DOCUMENTED_UNAVAILABLE_ACTION` |
| `chart_assignment` | Chart Signal Assignment | `DOCUMENTED_OVERLAP_NOT_EXECUTABLE` |
| `trigger` | Trigger | `DOCUMENTED_UNAVAILABLE_ACTION` |
| `slope` | Trigger Slope | `NEED_DATA` |
| `source` | Trigger Source | `NEED_DATA` |
| `delay` | Trigger Delay | `NEED_DATA` |
| `start_recording` | Start Recording | `DOCUMENTED_HIGH_RISK_ACTION` |
| `start_ignore_trigger` | Start Ignore Trigger | `DOCUMENTED_HIGH_RISK_ACTION` |

이 section은 EAS Recorder 절차의 문서상 구조만 보존한다. 기존 애플리케이션
Recorder를 열거나 구성하지 않으며, signal identity, unit, sampling,
trigger timing, target identity, completion과 raw-data provenance를
생성하지 않는다. Recorder Start/Stop은 데이터 수집 제어이지 motor stop이
아니다.

### 3. Velocity / Position Verification - Time · EAS III §8.2.13.4.1–3

| Key | Documented control | Evidence status |
|---|---|---|
| `indicators_current` | Position / Velocity / editable Current input | `DOCUMENTED_HIGH_RISK_INPUT_NOT_CURRENT` |
| `enable_status` | Enable / Disable + Status | `DOCUMENTED_HIGH_RISK_ACTION` |
| `ptp_absolute_relative` | PTP Absolute / Relative | `DOCUMENTED_HIGH_RISK_OVERLAP` |
| `jogging_run_held` | Jogging + Run Held | `DOCUMENTED_HIGH_RISK_OVERLAP` |
| `motion_profile` | Acc / Dec / Stop Dec / Smooth / Speed / Dwell | `DOCUMENTED_OVERLAP_NOT_EXECUTABLE` |
| `sine_step_injection` | Sine / Step Injection | `DOCUMENTED_HIGH_RISK_ACTION` |
| `injection_run_held_start_stop` | Injection Run Held + Start / Stop | `DOCUMENTED_HIGH_RISK_ACTION` |
| `control_parameters` | Scheduling / gains / filters / compensation | `DOCUMENTED_HIGH_RISK_OVERLAP_NOT_EXECUTABLE` |

`Current`는 단순 telemetry indicator로만 취급할 수 없다. EAS 문서는 PTP나
Jog 중 on-the-fly로 바꿀 수 있는 editable motion-current input으로도
설명한다. 이 카탈로그는 해당 값을 읽거나 쓰지 않으며, `CL`을 안전한
current envelope로 간주하지 않는다.

Control Parameters에는 gain, feedforward, advanced filter, phase advance뿐
아니라 **field weakening과 friction compensation**이 포함된다. 이 설정은
current, torque와 motion에 영향을 줄 수 있으므로 기존 P2 MODEL이나
filter/scheduling evidence와 동등한 기능이 아니며 편집 기능도 제공하지
않는다.

## 실제 실행 위험

### Current Verification - Time

실제 EAS Verify는 motor-on 상태에서 선택 phase에 Sine/Step
current-response excitation을 가한다. 설치 도움말의
`Drive Setup and Motion Activities_77.jpg`에는
`Motor is about to move` 경고가 표시된다. 따라서 motor가 움직이거나
twitch할 수 있다.

필요하지만 없는 계약은 다음과 같다.

- exact phase/current path와 waveform
- 승인된 current·thermal·brake·vertical-axis envelope
- Recorder signal/sample/unit/identity provenance
- timeout, abort, fault, disconnect와 terminal closeout
- repeatability 및 독립적인 quantitative acceptance oracle

문서맵의 Current 실행 경계는 `ENERGIZING / NEED_DATA`이며 실제 실행은
NO-GO다.

### Velocity / Position Verification - Time

실제 화면은 단순 결과 viewer가 아니다. motor Enable, editable Current,
absolute/relative PTP, Jog, Run Held, Sine/Step injection과 control-parameter
변경을 포함한다. 이 동작은 축을 움직일 수 있으며 field weakening과
friction compensation은 current와 torque 동작까지 바꿀 수 있다.

UI Stop은 STO, E-stop, contactor isolation 또는 torque-removal evidence가
아니다. Run Held는 focus loss, release, disconnect, timeout과 stale command
처리가 별도로 검증되지 않았다. travel, velocity, acceleration, limit,
stopping distance, independent stop, fresh telemetry와 restore 계약도 없다.

문서맵의 Velocity/Position 실행 경계는 `MOTION / NEED_DATA`이며 실제
실행은 NO-GO다.

## 보존된 문서 충돌

1. `CONTROLLER_ZERO_INTEGRAL_LABEL_CONFLICT`
   §8.2.8.3 본문은 `KI[1]`을 Controller Zero라고 부르지만 화면은
   Controller Integral이라고 표시한다.
2. `PWM_PMW_LABEL_CONFLICT`
   본문은 `US[1]`을 PMW Output Limit라고 표기하면서 PWM duty-cycle
   제한으로 설명한다.
3. `XP5_UNIT_SYNTAX_CONFLICT`
   `XP[5]` 단위가 `[% of MC/TS]]`처럼 닫는 대괄호가 하나 더 있는
   상태로 문서화되어 있다.

카탈로그는 이 표현을 임의 정규화하거나 하나를 정답으로 선택하지 않는다.

## 지속 경고

모델은 다음 9개 warning category를 항상 보존한다.

1. `DOCUMENTED_MAP_ONLY` — 결과·상태·측정·추천·안전 판정이 아니다.
2. `NO_RUNTIME_IO` — lookup/navigation도 drive 또는 Recorder 작업을
   만들지 않는다.
3. `CURRENT_TIME_ENERGIZATION_RISK` — actual Current 시험은 motor를
   energize하며 move/twitch할 수 있다.
4. `VELOCITY_POSITION_MOTION_RISK` — Enable/PTP/Jog/Sine/Step은 실제
   motion 경로다.
5. `RECORDER_NOT_MOTION_STOP` — recording lifecycle은 motor stop이 아니다.
6. `UI_STOP_NOT_STO` — UI Stop은 독립 안전 정지가 아니다.
7. `RUN_HELD_RISK` — release/focus/disconnect/timeout 계약이 없다.
8. `NO_QUANTITATIVE_PASS_FAIL` — progress 완료나 chart 갱신은 품질·안정성
   pass 근거가 아니다.
9. `OVERLAP_NOT_PARITY` — Recorder, profiler, P2, filter/scheduling 행은
   기존 기능의 실행이나 parity를 의미하지 않는다.

## 누락 증거

1. `TARGET PARITY` — exact Gold Twitter SKU, hardware revision,
   firmware personality와 B01G 문서 일치성
2. `EXCITATION WAVEFORM` — amplitude, offset, frequency, rise time,
   duration, repetition, phase order, saturation과 drive mapping
3. `SAFE ENVELOPE` — current, thermal, travel, velocity, acceleration,
   load, brake, limits, stopping distance, STO/E-stop 조건
4. `RECORDER PROVENANCE` — signals, units, sampling, resolution, buffer,
   trigger, timestamps, target identity, raw data와 hashes
5. `ABORT AND RECOVERY` — timeout, cancel, disconnect, fault, over-travel,
   focus loss, partial capture, closeout와 restore
6. `ACCEPTANCE CRITERIA` — response metrics, tolerances, uncertainty,
   repeatability, model comparison, stability gate와 독립 pass/fail oracle

누락 증거가 채워지기 전에는 실제 시험, measured-vs-model 판정 또는 안전
판정을 할 수 없다.

## Source identity

아래 identity는 모델에 동결된 설치 파일 location 또는 공통 image root
아래의 고유 filename suffix와 SHA-256이다. 첫 HTML 행은 full location을,
image 행의 `...`는
`C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\Resources\Images\EAS_II_SimplIQ_Gold_UM`
location prefix를 뜻한다. runtime에 이 파일을 다시 읽어 상태를 갱신하지
않는다.

| Key | Installed source | SHA-256 |
|---|---|---|
| `drive_setup_html` | `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| `current_time_image` | `...\Drive Setup and Motion Activities_85.png` | `B2A92460D2499285B63DCD55DF0550DFB74278E0EDD935ECAA670AAA6047A5A6` |
| `current_motor_warning_image` | `...\Drive Setup and Motion Activities_77.jpg` | `FC85BAE479514E6B5D5048594968DE0CF149351ABBAEBEE318918F1F86947F91` |
| `current_completion_image` | `...\Drive Setup and Motion Activities_79.jpg` | `D7E261C835B0E9D9EFF3BAC80D8AB358392774C396C06E77999675311CDF1F9D` |
| `velocity_position_time_image` | `...\Drive Setup and Motion Activities_144.png` | `C49250DEB7F13EC586B1238D8702D92DB7598B1BEF084055C7636F1DB6167B7D` |
| `signal_editor_image` | `...\Drive Setup and Motion Activities_175.jpg` | `9F696A8B9C62B40421AA9DFC61C3535BD87FA177B7771079DB0855621CE4B810` |
| `trigger_editor_image` | `...\Drive Setup and Motion Activities_177.jpg` | `9242467B7925CD65E451A56F5542ED270E1A6B68B89A7FE83AA868EE8C87D289` |
| `sine_step_image` | `...\Drive Setup and Motion Activities_182.jpg` | `F17DD9E5D7B38135895AA1468F1D8072BD731846BB7C7479AABF38C04ED46126` |

이미지의 예시 값, chart, completion dialog 또는 motor warning은 현재
드라이브의 값이나 실제 검증 결과가 아니다.

## 현재 검증 범위

현재 기록 가능한 로컬 검증 결과는 다음과 같다.

- 집중 계약: **40 passed in 22.68s**
- Expert 영향범위: **99 passed in 98.84s**
- 전체 repository suite: **1567 passed in 524.64s**, numeric exit **0**
- immutable singleton, exact 3 × 8 row order와 strict section lookup
- 8개 설치 source를 독립 재계산한 SHA-256: **8/8 match**
- conflict/warning/missing category와 fail-closed capability 보존
- import/build/lookup file·socket·subprocess I/O poison
- operation catalog의 LOCAL/ENERGY/MOTION 분리와 UI authority isolation
- 독립 read-only 재검토: **HIGH/MEDIUM/LOW 없음**

새 제어창 runtime smoke는 Python 3.14, 1366×820,
`OFFLINE · READ ONLY`에서 아홉 번째 `TIME DOC MAP` page, selector의
`Current Verification - Time`, `Velocity / Position Recording Setup`,
`Velocity / Position Verification - Time` 세 section, 각 **8 documented
groups**를 확인했다. page 안의 action/edit widget은 **0**이었고
Connect, drive/Recorder read, Verify, Enable, PTP, Jog, Sine/Step,
recording, Apply/SV, 통전 또는 모션은 실행하지 않았다.

이 GREEN은 정적 문서맵 모델·UI·operation catalog의 열람 계약만 지지한다.
EAS parity, field execution, 실제 Verification의 안전성·정확성·실행
가능성은 검증하지 않았으며 계속 `NEED-DATA / NO-GO`다.

## Summary 후속 범위

Expert Summary는 이 모델에 포함하지 않는다. Summary는
`Save Parameters in Drive (SV)`, drive parameter upload, design-plant file,
motor database와 복합 Save/Cancel transaction을 다루며 Time Verification과
다른 authority를 가진다.

따라서 Summary는 별도 후속 slice인
`Summary · Documented Transaction Map`으로 분리해야 한다. 해당 slice도
먼저 zero-I/O static inspector로 구현하고, SV·drive read·local file·DB
mutation의 실제 실행은 각각 독립된 NEED-DATA operation으로 유지해야 한다.
