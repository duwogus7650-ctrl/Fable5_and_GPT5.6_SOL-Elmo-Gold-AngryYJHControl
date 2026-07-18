# Single Axis Controls · Documented Authority Map v0.1

## 목적과 판정

`Motion - Single Axis` 화면에 보이는 기능 이름과 실제 실행 권한을 분리한다.
설치된 EAS III Gold 도움말의 §8.9와 두 화면 이미지를 동결해
`Status & I/O`, `Mode & Reference`, `Activation & Tools`의 3개 section,
12개 grouped row로 표시한다.

- `OBSERVED`: 설치 도움말에는 Motion Status, Digital I/O, STO 표시,
  Drive Mode, Position/Velocity/Current/Sine/Homing/Stepper, Enable/Stop,
  Terminal/Command Reference, Recorder가 있다.
- `DERIVED`: Digital Output checkbox는 단순 표시가 아니라 drive write이며,
  Enable/Current는 통전, PTP/Jog/Homing/Sine/Stepper는 구동 또는 통전을
  포함할 수 있다.
- 현재 판정:
  `DOCUMENTED_SINGLE_AXIS_AUTHORITY_MAP_ONLY · PARTIAL_NEED_DATA`.
- `GREEN` 범위: frozen local catalog, strict lookup, fail-closed capability와
  읽기 전용 UI 렌더링만.
- `NEED-DATA / NO-GO` 범위: live drive state, Digital Output 변경, UM 변경,
  Enable/Disable, PTP/Jog/Current/Sine/Homing/Stepper, Terminal command,
  Recorder config/acquisition와 EAS 동등성.

이 페이지는 모터나 드라이브를 제어하지 않는다. 실제 Single Axis 기능이
구현됐거나 안전하다는 판정도 아니다.

## UI 구조

Motion page의 기존 STOP, Session Zero, finite PTP controls 아래에 별도
`SINGLE AXIS CONTROLS - DOCUMENTED AUTHORITY MAP` frame을 둔다.

| Section | 4개 row |
|---|---|
| `Status & I/O` | Motion Status; Digital Inputs; Digital Outputs; Safety / STO Status |
| `Mode & Reference` | Drive Mode (UM); Position / Velocity; Current Reference; Sine / Homing / Stepper |
| `Activation & Tools` | Enable / Disable; Stop Controls; Terminal / Command Reference; Recorder |

각 row는 `EAS AREA / CONTROL`, `DOCUMENTED ROLE`, `RISK / ACCESS`,
`STATUS / BOUNDARY`를 보여준다. selector는 section 표시만 바꾸며 frame 안에는
`QPushButton`, editable `QLineEdit`, `QCheckBox`, `QSlider`가 없다.

## 권한 경계

모델의 유일한 `True` capability는 `can_inspect`다. 다음은 모두 `False`다.

- drive read와 live status observation
- Digital Output toggle과 UM 변경
- Enable/Disable
- Position/Velocity, Current, Sine/Homing/Stepper command
- Terminal command send
- Recorder config/acquisition
- command generation, write, Apply, SV
- energization, motion
- live-state, safety, EAS parity claim

고정 boundary 문구는 다음을 포함한다.

`STATIC DOCUMENT MAP ONLY · PARTIAL / NEED-DATA · NOT CURRENT EAS SINGLE
AXIS STATE · NOT CURRENT DRIVE STATE · NOT STO TEST EVIDENCE · NO DRIVE READ ·
NO DIGITAL OUTPUT WRITE · NO MODE CHANGE · NO ENABLE/DISABLE ·
NO PTP/JOG/CURRENT/SINE/HOMING/STEPPER · NO TERMINAL/COMMAND SEND ·
NO RECORDER CONFIG/ACQUISITION · NO ENERGIZATION/MOTION · NO DRIVE I/O`.

기존 실제 operation은 합치지 않는다.

- `eas.single_axis.digital_io`: `NEED_DATA`
- `eas.single_axis.manual_references`: `NEED_DATA`
- `eas.single_axis.terminal`: `NEED_DATA`
- `motion.ptp.run`: `MOTION / NEED_DATA`
- `motor.enable`: `ENERGIZING`
- `recorder.*`: 별도 identity/freshness/ownership gate
- 새 `eas.single_axis.authority.evidence.inspect`만
  `LOCAL_UI / PARTIAL`

## 안전 해석

- `STO1/STO2/ERR` 표시는 drive-reported safety-related display이지,
  배선·응답시간·torque isolation 또는 독립 STO 시험 증거가 아니다.
- software Stop/Disable은 독립 E-stop/STO가 아니다.
- General Purpose Digital Output checkbox도 실제 부하를 작동시킬 수 있으므로
  read-only status로 분류하지 않는다.
- UM에 따라 active loop, tab, command와 unit가 달라진다. 화면 label만으로
  command mapping이나 Gold family 호환성을 일반화하지 않는다.
- unrestricted Terminal은 operation catalog와 allowlist를 우회할 수 있어
  계속 잠근다.
- Recorder는 motion/energization과 결합될 수 있으므로 config/acquisition,
  trigger, ownership, upload, stop, provenance를 별도 검증한다.

## 동결한 source identity

| Key | 설치 경로 | SHA-256 |
|---|---|---|
| `drive_setup_html` | `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| `single_axis_overview_image` | `...\Resources\Images\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities_276.png` | `E05313740D16DBF954ED666EA6F56E6359ED4A1AF2D8813BEBF50CF5BEA21F77` |
| `single_axis_areas_image` | `...\Resources\Images\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities_277.png` | `C6DEF3392BBC943CE8337CFEB6D353A160AAB23D123C4D2519B4A8972912BAAA` |

파일명이나 설치본이라는 사실만으로 authority를 얻지 않는다. 현재 model은
이 세 byte identity와 §8.9 문구에만 결합된다.

## 검증 계약

`tests/test_single_axis_authority_evidence.py`는 다음을 고정한다.

- singleton/frozen/정확한 3 section × 4 row와 순서
- 문서 control, risk class와 inspect-only access
- capability fail-closed
- warnings/missing-evidence 범주
- 실행·안전·동등성 success claim 부재
- source SHA-256 3개 exact identity
- fresh import/build/lookup의 file/socket/subprocess poison I/O 0
- noncanonical lookup rejection과 frozen mutation rejection

UI와 operation tests는 section 전환 중 worker call 0, 기존 connection,
telemetry, commutation, Session Zero, PTP/STOP authority 불변, action/edit
widget 0, 세 skin의 1366×820 수평 scroll 0을 고정한다.

현재 구현 단계에서 직접 확인한 결과:

- 핵심 model/UI/catalog: **53 passed in 45.33s**
- 관련 Motion·menu·safety·Recorder·status/system/tool 영향 범위:
  **560 passed**
- 최신 전체 repository: **1604 passed in 478.69s**, 종료코드 **0**,
  stderr **0 bytes**
- Python 3.14, 1366×820 새 창: **OFFLINE · READ ONLY**,
  QDD dark high-contrast table, 3개 section 각각 **4 documented groups**,
  inspector 내부 action/edit widget **0**
- 설치 source SHA-256: **3/3 일치**

runtime에서는 `Status & I/O`, `Activation & Tools`, `Mode & Reference`를
각각 전환해 status와 첫 visible rows를 확인했다. Connect, drive read,
Digital Output toggle, UM change, Enable/Disable, PTP/Jog/Current/Sine/
Homing/Stepper, Terminal command, Recorder config/acquisition, Apply/SV는
실행하지 않았다. 위 수치는 실기 검증이나 EAS parity 점수가 아니다.

## 후속 구현 순서

1. identity-bound live status와 per-field freshness/validity
2. device별 Digital I/O count/function/polarity/filter와 output safe-state
3. UM별 exact command/unit mapping과 disabled-before-change transaction
4. site motion envelope, limit input, stop distance와 independent STO/E-stop
5. bounded Current/Sine/Homing/Stepper watchdog·abort·rollback
6. restricted Terminal grammar/allowlist 또는 계속 미지원
7. Recorder trigger/ownership/upload/provenance와 motion synchronization
8. Gold Twitter 외 Gold family에서 firmware/personality별 반복 검증

이 gate를 통과하기 전에는 문서 map의 row를 실행 control로 바꾸지 않는다.
