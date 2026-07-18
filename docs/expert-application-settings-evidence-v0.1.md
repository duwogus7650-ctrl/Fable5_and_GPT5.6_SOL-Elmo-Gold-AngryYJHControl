# Expert Application Settings · Documented Map v0.1

## 목적과 판정

이 기능은 EAS III Expert Tuning의 `Application Settings` 아래에 있는
`Brake`, `Settling Window`, `Inputs and Outputs` 문서 내용을 한 화면에서
읽는 순수 로컬 정적 카탈로그다.

- 로컬 카탈로그 판정: **GREEN**
- authority: `DOCUMENTED_APPLICATION_SETTINGS_MAP_ONLY`
- model status: `PARTIAL_NEED_DATA`
- fidelity: `DOCUMENTED_STATIC_REFERENCE`
- Expert 단계: `7 · APP SETTINGS`
- inspect operation id:
  `tuning.expert.application_settings.evidence.inspect`
- transaction gap operation id:
  `tuning.expert.application_settings.transaction`
- inspect operation risk/status: `LOCAL_UI / PARTIAL`
- transaction status: `NEED_DATA`
- 고정 경계:
  `STATIC DOCUMENT MAP ONLY · DOCUMENTED APPLICATION SETTINGS MAP ·
  PARTIAL / NEED-DATA · NOT CURRENT DRIVE CONFIG · NOT CURRENT I/O STATE ·
  NOT BRAKE OR SAFETY EVIDENCE · NO DRIVE READ · NO VALIDATION/EVALUATION ·
  NO COMMAND · NO WRITE · NO APPLY/REVERT/SV · NO OUTPUT ACTUATION ·
  NO MOTION · NO DRIVE I/O`

여기서 GREEN은 immutable catalog를 정해진 순서로 열람하고 문서의 충돌과
누락을 그대로 표시하는 **로컬 UI 기능에만** 적용된다. 다음 항목은 모두
`NEED-DATA / NO-GO`다.

- 현재 drive 설정, 현재 input/output state와 실제 EAS 조건부 visibility
- brake 출력의 전기 정격·배선·코일 구동 능력과 부하 유지 성능
- 현재 값·factory default·B01G default 판정, 값 유효성·추천
- read/write, Apply/Revert, SV, readback, rollback과 import/export
- output actuation, motor enable, motion 또는 field behavior
- mechanical/dynamic brake, STO/E-stop, 정지거리와 현장 안전 판정

## 고정된 문서 파라미터

모든 행의 access는 `document: … · app: inspect-only`다. 문서가 R/W로
설명한 명령도 이 앱에서는 쓰기 권한이 아니다. 문서상 reference/default는
현재 값이나 현재 Gold Twitter B01G의 factory default가 아니다.

### Brake · EAS III §8.2.7.1

| 명령 | 문서상 의미 | 문서상 단위 / access | 고정 경계 |
|---|---|---|---|
| `OL[N]` | Brake output assignment; 4 active-low, 5 active-high | none / R/W, non-volatile | `Using Brake` 선택 때만 EAS에 보임; 실제 output과 전기 능력은 hardware-dependent |
| `BP[1]` | brake engage time | ms / R/W, non-volatile | 0..1000, 문서 reference 0; 다음 motor-off에 적용, 현재 값 아님 |
| `BP[2]` | brake release time | ms / R/W, non-volatile | 0..1000, 문서 reference 0; 다음 motor-on에 적용, 현재 값 아님 |
| `VH[1]` | dynamic-brake speed threshold | counts/sec / R/W, non-volatile | 0은 dynamic braking disable; index metadata 충돌, current/default 아님 |

Brake logical output, mechanical brake와 dynamic braking은 서로 같은 기능이
아니며, 어느 것도 독립 STO/E-stop 증거나 안전 판정으로 사용하지 않는다.

### Settling Window · EAS III §8.2.7.2

| 명령 | 문서상 의미 | 문서상 단위 / access | 고정 경계 |
|---|---|---|---|
| `TR[1]` | target position window | counts / R/W, non-volatile | `-1` inactive 또는 0..2^31-1; 문서 reference 100, 현재 값 아님 |
| `TR[2]` | target position window time | ms / R/W, non-volatile | range 미기재, 문서 reference 20, 현재 값 아님 |
| `TR[3]` | target velocity window | counts/sec / R/W, non-volatile | range 미기재, 문서 reference 100, 현재 값 아님 |
| `TR[4]` | target velocity window time | ms / R/W, non-volatile | range 미기재, 문서 reference 20, 현재 값 아님 |

`TR[1..4]`는 Target Reached 판정 window/time 문서 의미일 뿐 positioning
accuracy, closed-loop stability, stopping 성능 또는 safety를 증명하지 않는다.
연결된 CANopen object의 user-unit 표현과 command의 raw counts/counts/sec
사이를 이 inspector가 변환하거나 다른 화면에 전파하지 않는다.

### Inputs and Outputs · EAS III §8.2.7.3

| 명령 | 문서상 의미 | 문서상 단위 / access | 고정 경계 |
|---|---|---|---|
| `IL[N]` | digital input function/polarity | bit field / R/W, non-volatile | index 1..16 문서; hardware/personality와 default 문서가 충돌 |
| `IF[N]` | digital input filter | ms / access Type 미기재, non-volatile | 0.0..500.0, reference 0; index scope·quantization·hardware-capture 경계 충돌 |
| `IP + IB[N]` | digital input status semantics | Boolean/bit field / live semantics | **unavailable · not sampled**; 현재 bulb/port/bit 값 없음 |
| `OL[N]` | digital output function/polarity | bit field / R/W, non-volatile | General/AOK/Brake/Motor Enable/Fault/Target Reached mapping 문서; range 충돌 |
| `GO[N] + OP` | output routing/status semantics | none/bit field / R/W + port state | **unavailable · not sampled**; 현재 output state가 아니며 Port C는 coupled/hardware-dependent |

따라서 총 행 수는 **3 sections / 13 rows = 4 / 4 / 5**다. 전체 목록의
**11번 `IP + IB[N]`와 13번 `GO[N] + OP`**는 live data가 빠진 명확한
`unavailable · not sampled` 행이다. 전체 13개 모두 documentation rows이며
현재 값을 읽었다는 뜻이 아니다.

## 정규화하지 않은 문서 충돌

구현은 다음 **9개** 충돌을 어느 한쪽의 “정답”으로 합치지 않는다.

1. `VH[N]` attributes index는 2,3인데 같은 command page가 `VH[1]`을 정의한다.
2. `IF[N]` index 범위가 attributes의 1..16과 Indices 표의 1..6으로 갈린다.
3. `OL[N]` range 0..9와 Target Reached 값 10/11이 충돌한다.
4. `GO[14]..GO[15]` range 문구와 `GO[14]..GO[16]` index/behavior가 충돌한다.
5. EAS Port C의 Gantry/Daisy Chain과 MAN-G-CR의 reserved/absolute-sensor
   routing 사이에 exact dropdown-to-command mapping이 없다.
6. EAS output 설명이 command `IL`을 적지만 실제 row는 `OL[N]`/`GO[N]`이다.
7. Home/Auxiliary Home input 범위와 RevC/RevE `IL`/`GI` 설명이 일치하지
   않으며 exact B01G hardware revision이 없다.
8. `IL` default 설명이 input 7을 누락하고 firmware notes의 `IL[6]`/`IL[7]`
   default 변경과도 충돌한다.
9. 2013 workspace MAN-G-CR v1.406과 설치된 2024 MAN-G-CR v2.001의
   `GO`/`IL` capability가 다르다. legacy source는 비교용일 뿐이다.

## 항상 표시하는 경고와 누락

카탈로그는 **16개** persistent warning을 고정한다. 핵심은 다음과 같다.

- 문서 맵은 current configuration, factory default, live I/O,
  protection state 또는 safety assessment가 아니다.
- page open/section change는 connect/query/dispatch/read/write/apply/save,
  command generation, output actuation 또는 motion을 만들지 않는다.
- exact B01G output count·rating·brake-current capability·polarity·relay/
  flyback·wiring·coil data와 fail-safe behavior가 없다.
- brake/dynamic-brake는 STO나 E-stop이 아니다.
- `VH[1]=0`의 disable 의미, BP transition timing, `TR[1..4]`의 Target
  Reached 전용 의미를 safety/accuracy로 확대하지 않는다.
- IL mapping은 motion·reference·stop/freewheel을 포함할 수 있고,
  IF는 firmware quantization과 hardware-capture 비적용 경계가 있다.
- GO/OL과 Port C routing은 hardware-dependent이며 `GO[N]=7`은 STO
  indication이지 STO actuation이 아니다.
- 설치된 2024 Gold-line 문서와 B01 release note만으로 reported
  `08Mar2020B01G` behavior를 확정하지 않는다.

missing-evidence는 **6개**다. exact SKU/variant/hardware/personality/B01G
delta, product-specific I/O installation guide, brake/coil/load data, 의도적으로
읽지 않은 current command/I/O values, 현재 mode/sensor/XA/WS/state/page
availability, field brake/Target Reached/I/O/STO/fault 검증이 필요하다.

## 구현과 현재 검증

- 순수 모델: `expert_application_settings_evidence.py`
- UI: 별도 일곱 번째 page에서 세 section, boundary, 9 conflicts,
  16 warnings, 6 missing-evidence와 24 source identity만 표시
- capability: `can_inspect=True`; read-drive, validate, evaluate,
  command-generate, write, apply, revert, persist, output-actuate, move,
  claim-safety는 모두 `False`
- canonical snapshot/section/parameter는 frozen이며 lookup은 strict canonical
  string만 허용
- focused 회귀 결과: **85 passed**
- 전체 repository 회귀: **1529 passed in 476.14s**, 직접 실행 종료코드 **0**
- focused 검증 범위:
  - canonical identity, exact 3/13/4-4-5 shape와 immutable/deterministic snapshot
  - conflict/warning/missing digest와 24개 source SHA-256
  - import/build/lookup의 file/process/network poison
  - non-None poison worker에서 page open/section change zero-call
  - 기존 P1/P2/Evidence/Page Status/User Units/Limits/installed/dispatch/
    connection/safety/Run/Verify/Apply/Restore/Save authority 불변
  - late Axis Summary 값이 표에 흘러들지 않음
  - page 내부 editable line/button 없음, section combo noneditable
  - 세 테마 1366×820 geometry, text fit와 table contrast
  - inspect `LOCAL_UI / PARTIAL`, transaction `NEED_DATA`

- 독립 closeout:
  - HIGH/MEDIUM/LOW 지적 없음
  - 독립 재계산한 24개 source SHA-256 전부 동결값과 일치
  - 미검증 Gold Twitter 설치/하드웨어 PDF는 source 집합에 포함되지 않음
- runtime GUI smoke:
  - Python 3.14, 1366×820, `OFFLINE · READ ONLY`
  - Brake 4 / Settling Window 4 / Inputs and Outputs 5개 행 확인
  - `COMMAND`, `ROLE / REF`, `UNIT / ACCESS`, `STATUS / NOTE` 헤더와
    24개 source identity 표시 확인
  - Connect, drive/worker/command/output/motion I/O를 실행하지 않음

이 검증은 **로컬 model/UI/catalog의 좁은 경계만** 지지한다. current
drive/I/O/brake behavior 또는 field safety로 확장하지 않는다.

## 근거 identity

canonical evidence는 설치 EAS NetHelp, command reference, EAS screenshot
3개, firmware release notes, legacy comparison source와 administrative
manual stub을 포함한 **24개 exact location/SHA-256** 집합이다.

| 대표 근거 | SHA-256 |
|---|---|
| 설치 NetHelp `Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| Brake image `_72.png` | `1F9AC24B682B666B19A184618CCB9EB2B43B5A7D7BEB3DFD423464DA07D4CC45` |
| Settling image `_73.png` | `FE90AC9D8A3CD3416DDEE6A59083D0A4B7C0EE0933B569CE25AB7B83B092C4D6` |
| I/O image `_74.png` | `8DD5E4F1232A607EECE43612543F72FE2763C14D84C0500722A3124B523ECD8F` |
| `BP Brake Parameters.htm` | `590F4D17B6C03F944E34EE2C60FB30BCF335315785409003D942F8AB084D6C7F` |
| `TR Target Radius.htm` | `E67F57644C8B1A80E387066101F79CCA1EC0A44531C71A65A905F431664C0907` |
| `IL Digital Input Logic.htm` | `F5C058B8A2CE435411A8114D7BB30ADD4E640D5BBA8B14737702096BF60F99C2` |
| `OL Output Logic.htm` | `F6A33CF4609B61AA31EB36F3B811387537A8208B495ACCA81CFB9A7B93331291` |
| `GO Digital Output Source.htm` | `4D4E7CBCE1EADBA8ED820224B441AFC370D5E264676A4AD22CC399361CE247BE` |

전체 24개 location/hash의 canonical 집합은
`expert_application_settings_evidence.py`의 frozen `SOURCES`다.

## 다음 gate

read/write 또는 live 기능을 설계하려면 exact Gold Twitter SKU·interface·
hardware revision·personality·B01G delta, product-specific output electrical
data, brake/coil/load/fail-safe data, current mode/sensor/XA/WS/I/O state,
EAS transaction·readback·rollback·Revert/SV semantics와 독립 STO/E-stop
현장 근거가 필요하다.

이 근거가 갖춰지기 전에는 static catalog를 current-value reader,
validator, recommendation engine, brake controller, I/O actuator 또는
motion path로 승격하지 않는다.
