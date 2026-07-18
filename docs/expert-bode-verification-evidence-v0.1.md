# Expert Hidden Verification – Bode · Documented Map v0.1

## 목적과 판정

이 기능은 EAS III에서 기본적으로 숨겨진 두 Bode 검증 페이지와 이를
표시하는 Tuner 설정을 한 화면에서 읽는 순수 로컬 정적 카탈로그다.

- 로컬 catalog/UI 판정: **GREEN**
- authority: `DOCUMENTED_HIDDEN_BODE_MAP_ONLY`
- model status: `PARTIAL_NEED_DATA`
- fidelity: `DOCUMENTED_STATIC_REFERENCE`
- Expert 단계: `8 · BODE DOC MAP`
- inspect operation:
  `tuning.expert.bode_verification.evidence.inspect`
- 실제 실행 gap:
  `tuning.expert.bode_verification.execute`

고정 boundary는 다음과 같다.

`STATIC DOCUMENT MAP ONLY · DOCUMENTED BODE VERIFICATION MAP ·
PARTIAL / NEED-DATA · NOT EAS VERIFICATION RESULT ·
NOT CURRENT DRIVE STATE · NOT EAS SETTING STATE ·
NOT MODEL/MEASUREMENT PARITY · NOT A SAFETY ASSESSMENT ·
NO DRIVE READ · NO EXPERIMENT · NO ACQUISITION · NO EVALUATION ·
NO VERIFY · NO EAS SETTINGS CHANGE ·
NO COMMAND/WRITE/APPLY/REVERT/SV · NO RECORDING ·
NO ENERGIZATION/MOTION · NO DRIVE I/O`

여기서 GREEN은 24개의 immutable documentation row를 정해진 순서로
열람하고 문서의 충돌·위험·누락을 그대로 표시하는 로컬 기능에만
적용된다. 실제 EAS Verify, 측정값, 튜닝 성능 또는 현장 안전의 GREEN이
아니다.

## 왜 별도 화면인가

기존 첫 번째 Expert 단계의 `ExpertBodeWidget`은 사용자가 입력한
phase-to-phase `R/L/TS`와 계산된 P1 후보로 그리는 **OFFLINE MODEL**이다.
이번 화면은 EAS가 실제 드라이브에 폐루프 자극을 인가해 얻는
frequency-domain 검증 페이지의 **문서 지도**다.

두 기능은 다음처럼 분리한다.

| 항목 | 기존 P1 Bode preview | 이번 Hidden Verification – Bode |
|---|---|---|
| authority | OFFLINE MODEL | DOCUMENTED STATIC REFERENCE |
| 입력 | 명시적 R/L/TS와 P1 후보 | frozen 문서 row |
| 측정 | 없음 | 없음 |
| EAS Verify | 없음 | 설명만, 실행 불가 |
| 결과 판정 | model gate | 판정 없음 |
| drive I/O | 없음 | 없음 |

`Show Design` overlay나 화면 모양의 유사성은 model/measurement parity,
안정성 또는 pass/fail 근거가 아니다.

## 고정된 문서 구조

canonical shape는 **3 sections / 24 rows = 8 / 8 / 8**이다. 모든 행의
access는 `document: inspect-only · app: inspect-only`이며 현재 값은
`not sampled`, action은 `unavailable · not executable`이다.

### Tuner Verification Settings · EAS III §13.1.5.6

| Control | 문서상 단위 | 문서상 역할 | 고정 경계 |
|---|---|---|---|
| Velocity Slope Time | sec | verification slope setting | min/max/default/current value `NEED-DATA` |
| Minimum Amplitude Reduction Factor | no units | automatic amplitude reduction ratio | exact law·clamp·rounding `NEED-DATA` |
| Min Frequency Resolution | Hz | frequency-resolution setting | sample grid interaction `NEED-DATA` |
| Min Quality Factor Threshold | no units | quality-factor threshold setting | 계산식·acceptance 의미 `NEED-DATA` |
| Auto Save Experiment Recordings | Boolean | experiment recording auto-save | 파일 identity·signal·sampling·completion 미확정 |
| View Verification – Bode Pages | Boolean | Current와 V/P Bode page 표시 | visibility는 권한·준비·안전 아님 |
| Initial Chart Limits | dB / deg | magnitude min/max, phase min/max | exact range/default/current value `NEED-DATA` |
| Reset to Factory Defaults | action | EAS-local setting reset | 앱에서는 실행 불가, scope·rollback 미확정 |

`View Verification – Bode Pages`는 두 advanced page를 보이게 할 뿐이다.
체크되어 있다는 사실은 드라이브 연결, 실험 승인, 안전 상태 또는 실행
준비가 완료됐다는 뜻이 아니다.

### Current Verification – Bode · EAS III §8.2.8.4

| Control | 문서상 단위 | 문서상 역할 | 고정 경계 |
|---|---|---|---|
| A / B / C Phases | phase selection | 실험 phase 선택 | topology·balance·current path 미검증 |
| Current Level | `% of PL` / `% of CL` 충돌 | 문서 표 default 40% | current/safe value 아님, basis 미확정 |
| Fixed / Automatic by Frequency | mode | 고정 또는 주파수별 감소 | exact law·bounds·clamp 미확정 |
| Experiment Frequencies | Hz / point count | start/end/Number of Points | `position points` 표현 충돌, grid/timing 미확정 |
| Current Offset | prose 단위 없음 / screenshot `% of CL` | current bias | unit·range·phase interaction 미확정 |
| Show Design | Boolean | design overlay 표시 | quantitative acceptance 아님 |
| Unbalanced / Vertical Axis | Boolean options | screenshot에만 보이는 옵션 | prose field 설명 없음 |
| Verify | action | 실제 current Bode experiment | **ENERGIZES**, 앱에서는 실행 불가 |

실제 EAS Current Verify는 선택 phase와 frequency에서 폐루프 current
experiment를 수행한다. 문서는 motor가 움직이거나 hum/click할 수 있음을
경고한다. 이 static map은 current를 인가하지 않는다.

### Velocity / Position Verification – Bode · EAS III §8.2.13.5

| Control | 문서상 단위 | 문서상 역할 | 고정 경계 |
|---|---|---|---|
| Loop Mode | mode | Position 또는 Velocity Closed Loop Bode | 현재 mode/gain/feedback 미확인 |
| Velocity Amplitude | cnt/sec | velocity excitation amplitude | position-mode 의미·travel demand 미확정 |
| Fixed / Automatic by Frequency | mode | 고정 또는 주파수별 current level | exact law·bounds·clamp 미확정 |
| Current Limit | `% of CL` | 문서 default 100% | current/safe value 아님 |
| Experiment Frequencies | Hz / point count | start/end/Number of Points | `position points` 표현 충돌, grid/timing 미확정 |
| Velocity Offset | cnt/sec | velocity mode의 한 방향 bias | direction·travel·stopping distance 미확정 |
| Show Design | Boolean | design overlay 표시 | quantitative acceptance 아님 |
| Verify | action | 실제 closed-loop Bode experiment | **MOTION**, 앱에서는 실행 불가 |

실제 EAS V/P Verify는 축을 움직일 수 있다. 특히 Velocity Offset은 한
방향의 이동을 의도적으로 만든다. 이 static map은 loop를 선택하거나
자극을 인가하지 않는다.

## 정규화하지 않은 문서 충돌

구현은 다음 **4개** 충돌을 어느 한쪽의 정답으로 합치지 않는다.

1. Current Level 표는 `% of PL`과 default 40%를 쓰지만 같은 절의 실행
   절차와 screenshot은 `% of CL`을 쓴다.
2. Current Offset prose에는 단위가 없지만 screenshot에는 `% of CL`이
   표시된다.
3. Current screenshot에는 `Unbalanced`와 `Vertical Axis`가 있지만 해당
   field table은 두 control의 의미를 설명하지 않는다.
4. 두 frequency sweep의 `Number of Points` 설명이 `position points`라고
   쓰여 있으며 swept-frequency sample과의 mapping이 없다.

## 항상 표시하는 위험과 누락

고정 persistent warning은 **12개**다.

- static 문서 map은 current EAS/drive state, measured plant, verification
  result 또는 safety assessment가 아니다.
- hidden-page visibility는 실행 authority가 아니다.
- import/build/lookup/page change는 file/process/network/worker/link/drive
  I/O를 만들지 않는다.
- Current Bode 실제 실행은 energization 위험, V/P Bode 실제 실행은
  motion 위험이 있다.
- offline Bode MODEL과 EAS field measurement는 서로 다른 authority다.
- `Show Design`과 chart 갱신은 pass/fail oracle이 아니다.
- automatic amplitude law와 offset 안전 범위가 미확정이다.
- auto-save recording은 provenance 자체가 아니다.
- EAS setting mutation과 factory reset은 이 inspector의 비범위다.

missing-evidence는 **8개**다.

1. exact Gold Twitter SKU/revision/personality와 B01G/EAS 문서 parity
2. 현재 EAS setting/visibility/workspace/loop/phase/drive state
3. Tuner setting의 exact min/max/factory value
4. automatic-by-frequency equation·rounding·clamping
5. 승인된 current/motion/travel/thermal/STO/E-stop envelope
6. raw recording signal·sample·unit·identity·completion provenance
7. magnitude/phase/margin/resonance의 quantitative acceptance oracle
8. abort/timeout/disconnect/fault/over-travel/recovery/restore contract

## Source identity

| Source | SHA-256 |
|---|---|
| `Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| `Drive Setup and Motion Activities_87.png` | `35007B311F9D912975E5B72666E42C5DE20A0F7CC4B942E03DBD16FA69501663` |
| `Drive Setup and Motion Activities_77.jpg` | `FC85BAE479514E6B5D5048594968DE0CF149351ABBAEBEE318918F1F86947F91` |
| `Drive Setup and Motion Activities_145.png` | `3208706439F318FDBA319E4F883DEE59693155ECD5C6F82ED740136F360D40C6` |
| `Drive Setup and Motion Activities_125.jpg` | `A2DB9446BF57D19A7C1D20473EBB3BF32C0C91C58C16F4D892EB5D24BC5B2E2A` |
| `Settings and Configuration.htm` | `E5BF9FDEE568B2FB8C58D06F9D0C2F9261A6973A5E081581038F5CFB3843F881` |
| `Settings and Configuration_11.jpg` | `40CCACC87EA197A46FB6010F129F2F538250CED5217B4BE4A14125FB60CCA6AE` |

`Settings and Configuration_11.png`은 다른 Application Tools 그림이므로
source 집합에 포함하지 않는다. 위 7개 hash는 구현 뒤 설치 파일에서 다시
계산해 frozen 값과 모두 일치했다.

## 구현과 검증

- pure model: `expert_bode_verification_evidence.py`
- UI: 별도 여덟 번째 page, noneditable section selector, 4-column
  read-only table
- action/edit widgets: `QLineEdit`, `QPushButton`, `QCheckBox`, `QSlider`,
  plot 모두 **0**
- capability: `can_inspect=True`; drive read/current-state observation,
  validation/evaluation/acquisition, command/write/Apply/Revert/SV,
  EAS-setting change, recording, Verify, energization, motion, hardware stop,
  pass/safety claim은 모두 `False`
- model contract: **14 passed**
- Expert 영향 범위 회귀: **211 passed in 65.06s**
- 전체 repository 회귀: **1547 passed in 503.66s**, 숫자 종료코드 **0**
- UI contract: PoisonWorker/DriveWorker/ElmoLink/dispatch 0회,
  Axis Summary와 기존 P1 Bode MODEL 비전파, Page Status/authority 불변
- display contract: qdd/amber/angrybirds, 1366×820, horizontal scroll 0,
  8개 step button text-fit/non-overlap, table contrast `>=4.5`
- Python 3.14 runtime: `OFFLINE`, stack index 7, 3 sections의
  8/8/8 rows, 7 frozen identities, action/edit widget 0,
  minimum size hint 1197×706, horizontal scroll 0
- 독립 read-only 검토: HIGH/MEDIUM 없음. LOW 표현 개선으로 실제 실행처럼
  읽힐 수 있던 `VERIFY BODE`를 `BODE DOC MAP`으로, 화면의
  `MODEL STATUS`를 `EVIDENCE STATUS`로 변경한 뒤 영향범위와 전체 회귀를
  현재 트리에서 다시 통과

첫 전체 실행은 65% 지점의 기존 Status Monitor GUI 테스트에서 Qt native
access violation으로 비정상 종료했다. 같은 시각 오후부터 남아 있던 별도
pytest process가 관찰됐지만 직접 원인인지는 `UNVERIFIED`다. 그 기존
process를 종료한 뒤 문제의 단일 테스트는 **1 passed**, 새 전체 실행은
위 **1547 passed / exit 0**으로 완료됐다. 실패 이력은 삭제하지 않고
환경 간섭 가능성과 함께 보존한다.

## 실제 실행으로 가는 다음 gate

실제 Verify는 현재 문서 map의 자연스러운 다음 버튼이 아니다. 별도
hardware workflow로 분리해야 한다.

1. Current와 V/P 실행을 각각 ENERGY와 MOTION operation으로 분리
2. exact target identity·firmware·feedback·gain·mode snapshot
3. amplitude/frequency/current/offset/travel/thermal envelope
4. recorder signal·sample·unit·completion·hash provenance
5. timeout/fault/disconnect/abort와 독립 stop/closeout
6. measured-vs-design quantitative acceptance와 repeatability
7. fresh 현장 안전 확인과 해당 실험 직전의 명시적 실행 승인

이 근거가 없으면 actual Verify는 계속 `NEED-DATA / NO-GO`다.
