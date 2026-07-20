# Expert Limits / Protections · Documented Parameter Map v0.1

## 목적과 판정

이 기능은 EAS III Expert Tuning의 `Current Limits`, `Motion Limits and
Modulo`, `Protections`에 등장하는 문서화된 명령·단위·접근 조건·충돌을
한 화면에서 읽는 순수 로컬 정적 카탈로그다.

- 로컬 카탈로그 판정: **GREEN**
- authority: `DOCUMENTED_PARAMETER_MAP_ONLY`
- model status: `PARTIAL_NEED_DATA`
- Expert 단계: `6 · LIMITS / PROTECT`
- operation id: `tuning.expert.limits_protections.evidence.inspect`
- operation risk/status: `LOCAL_UI / PARTIAL`
- 고정 경계:
  `STATIC DOCUMENT MAP ONLY · DOCUMENTED PARAMETER MAP · PARTIAL / NEED-DATA ·
  NOT CURRENT DRIVE CONFIG · NOT ACTIVE PROTECTION STATE ·
  NOT A SAFETY ASSESSMENT · NO DRIVE READ · NO VALIDATION / EVALUATION ·
  NO COMMAND · NO WRITE · NO APPLY/SV · NO UNIT PROPAGATION · NO DRIVE I/O`

여기서 GREEN은 immutable catalog를 정해진 순서로 열람하고 문서 충돌을
그대로 표시하는 **로컬 기능에만** 적용된다. 다음 항목은 모두
`NEED-DATA / NO-GO`다.

- 현재 drive 설정값과 active protection 상태
- EAS III 화면·조건부 visibility·transaction의 수치/동작 parity
- 특정 값의 유효성, motor/drive 적합성 또는 권장값
- 보호 기능의 실제 작동·차단 성능
- read/write, Apply/Revert, SV, import/export와 단위 전파
- motion safety, STO/E-stop, 정지거리 또는 현장 사용 승인

## 고정된 문서 파라미터

표의 unit/access는 문서에 적힌 표현을 보존한 것이다. 현재 drive 값이나
현재 firmware에서의 사용 가능 여부를 뜻하지 않는다.

### Current Limits · NetHelp §8.2.6.1

| 명령 | 문서상 의미 | 문서상 단위 / access | 고정 경계 |
|---|---|---|---|
| `MC` | drive maximum current rating | A / read-only | 제품 의존, generic range 없음 |
| `BV` | drive maximum bus voltage rating | V / read-only | 제품 의존 |
| `PL[1]` | peak sine-current amplitude limit | A / R/W | drive·motor rating 필요 |
| `CL[1]` | continuous sine-current amplitude limit | A / R/W | R/non-R 제품 authority와 문서 교차참조 충돌 |
| `PL[2]` | peak-current duration | s / R/W | 제품별 range/default와 종료 후 제한 대상 문구 충돌 |
| `US[1]` | PWM duty-cycle limit | % max PWM / R/W | 현재 firmware 적용성 미확인 |
| `US[2]` | current-controller integral contribution limit | % max PWM / version-dependent | NetHelp/firmware와 MAN-G-CR Reserved 표기가 충돌 |

### Motion Limits and Modulo · NetHelp §8.2.6.2

| 명령 | 문서상 의미 | 문서상 단위 / access | 고정 경계 |
|---|---|---|---|
| `SD` | emergency-stop deceleration와 documented acceleration ceiling | FC-based acceleration / R/W | 현재 FC/display unit 없음 |
| `VH[2]` | maximum reference velocity | FC-based velocity / R/W | rotary mode에서 DS-402 `0x6080`도 관련 |
| `VL[3]` | lower software feedback position limit | FC-based position / R/W | `VH[3] > VL[3]` 관계 필요 |
| `VH[3]` | upper software feedback position limit | FC-based position / R/W | `VH[3] > VL[3]` 관계 필요 |
| `XM[1]` | absolute/modulo range lower boundary | FC-based position | EAS read-only 표현과 command reference R/W가 충돌 |
| `XM[2]` | absolute/modulo range exclusive upper boundary | FC-based position | motor-off·`HM[1]=0` 제한, EAS mapping 미확인 |
| `MODULO MODE` | non-modulo/modulo/cyclic-limit behavior | documented mode | EAS dropdown-to-command mapping `NEED-DATA` |
| `XA[4]:1` | acceleration limiting bypass | bit / dangerous, version-dependent | 정적 danger row만; toggle/value preview 없음 |
| `XA[4]:2` | cyclic/IP에서 HW/SW position limit 무시 | bit / dangerous, version-dependent | 정적 danger row만; toggle/value preview 없음 |

### Protections · NetHelp §8.2.6.3

| 명령 | 문서상 의미 | 문서상 단위 / access | 고정 경계 |
|---|---|---|---|
| `ER[3]` | maximum position tracking error | count / R/W | 설정값·보호 효능을 읽지 않음 |
| `ER[2]` | maximum velocity tracking error | count/s / R/W | EAS table/body unit 문구 충돌 |
| `ER[5]` | conditional yaw/stepper tracking error | count / EAS read-only vs array R/W | visibility/access 충돌, 0은 문서상 disable |
| `CL[2]` | motor-stuck current threshold | % `CL[1]` / R/W | `< 2`이면 문서상 motor-stuck protection disable |
| `CL[3]` | motor-stuck velocity threshold | count/s / R/W | 다른 manual table과 index semantics 충돌 |
| `CL[4]` | motor-stuck duration | ms in EAS/index; s in remarks / R/W | 변환·stuck verdict 없음 |
| `XP[1]` | overvoltage threshold | V / R/W | 제품 `WI[35]`와 installation guide 의존 |
| `XP[13]` | undervoltage threshold | V / R/W | generic numeric range `NEED-DATA` |
| `LL[3]` | minimum feedback position | FC-based position / R/W, motor off | lower-bound sign 문구 충돌 |
| `HL[3]` | maximum feedback position | FC-based position / R/W, motor off | NetHelp maximum row가 `See LL[3]`로 표기 |
| `HL[2]` | maximum feedback speed | FC-based velocity / R/W, motor off | 0은 문서상 overspeed protection disable |

## 정규화하지 않은 문서 충돌

구현은 아래 충돌을 어느 한쪽의 “정답”으로 합치지 않는다.

1. `US[2]`가 설치 NetHelp/firmware notes에서는 current-integral saturation
   limit이지만 MAN-G-CR 1.406은 `US[2]`, `US[3]`을 Reserved로 표시한다.
2. EAS는 `ER[5]`를 조건부로 노출하지만 ER index/access 설명은
   read-only와 R/W에서 일치하지 않는다.
3. 상세 설명의 motor-stuck 의미는 `CL[2]=current`, `CL[3]=velocity`,
   `CL[4]=duration`이지만 다른 표는 `CL[2]`/`CL[3]`을 바꿔 적고,
   `CL[4]`는 ms·s·고정 3 seconds 문구가 공존한다.
4. Gold NetHelp/EAS는 `XA[4]` bit 1/2 bypass를 노출하지만 다른 설치
   reference는 `XA[4] Reserved`와 `XA[]` 수정 금지를 적는다.
5. Current Limits의 `CL[1]` 설명은 `PL[1]`을 참조하고, peak duration 뒤의
   제한 대상도 `PL[1]`과 `CL[1]`로 갈린다.
6. Maximum `HL[3]` row는 `See LL[3]`라고 적고, `LL[3]` lower-bound sign
   문구는 표시 interval과 충돌한다.
7. `XM[1]/XM[2]`는 EAS page에서 read-only로 보이지만 command reference는
   motor-off R/W로 설명한다.
8. `XA[4]` default는 zero 암시와 factory-set bit 2 설명이 충돌한다.
9. EAS의 count/count-per-second 표기와 FC user scaling을 따르는 command
   page 단위 설명이 충돌한다.

## 항상 표시하는 위험 경고

- `CL[2] < 2`는 문서상 motor-stuck protection을 비활성화한다.
- `XA[4]` bypass bit는 acceleration 또는 HW/SW position-limit enforcement를
  제거할 수 있다. 이 inspector는 toggle이나 encoded value를 제공하지 않는다.
- all-zero `XM/VH/VL` 조합은 문서상 no-limits mode가 될 수 있다.
- `LL[3]=HL[3]=0`은 문서상 feedback position-range protection,
  `HL[2]=0`은 overspeed protection을 비활성화한다.
- 모든 row는 documentation fact일 뿐 current value, active protection,
  recommendation 또는 safety assessment가 아니다.

## 구현과 검증

- 순수 모델: `expert_limits_protections_evidence.py`
- UI: 선택 가능한 세 section과 고정 boundary/conflict/warning/missing-evidence/source
  표시만 제공한다.
- capability: `can_inspect=True`; read-drive, validate, evaluate,
  command-generate, write, apply, persist, unit-propagate는 전부 `False`
- canonical snapshot, section과 parameter는 frozen이며 section lookup은
  strict canonical string만 허용한다.
- 집중 회귀 결과: **69 passed**
- 전체 repository 회귀: **1513 passed in 698.16s**
- 독립 closeout: **잔여 HIGH/MEDIUM/LOW 없음**
- 최신 runtime smoke: Python 3.14, 1366×820, `OFFLINE · READ ONLY`,
  7/9/11개 section row와 20개 frozen identity, zero action control 확인
- 확인한 범위:
  - canonical identity, immutable/deterministic snapshot
  - section·command 순서와 비대칭 의미
  - 모든 capability의 fail-closed 상태
  - 문서 충돌·danger warning·missing evidence 보존
  - source SHA-256 고정
  - file/process/network/worker/link/job/query/write poison I/O
  - non-None poison worker에서도 page open/section change가 zero-I/O
  - P1/P2/Evidence/Page Status/User Units/installed/dispatch/connection/safety/
    Apply/Save authority 불변
  - late Axis Summary/telemetry가 catalog를 바꾸지 않음
  - operation catalog `LOCAL_UI / PARTIAL`
  - qdd/amber/angrybirds 1366×820에서 수평 스크롤·단계 버튼 겹침 없음

집중 결과와 전체 repository 결과는 Python/mock/offscreen 또는 로컬 no-I/O
경로의 evidence다. current drive config, active protection state, EAS transaction
parity, protection efficacy 또는 현장 안전으로 확장하지 않는다.

실제 runtime 최초 확인에서는 기본 `QTableWidget` palette가 흰 배경과 밝은 글자를
조합해 표를 읽기 어렵게 만드는 결함을 재현했다. `expertEvidenceTable` 전용 스타일을
세 테마에 고정한 뒤 현재 QDD runtime에서 어두운 고대비 표를 재확인했고,
자동 회귀는 각 테마의 text/base contrast ratio를 `>=4.5`로 강제한다.

## 근거 identity

| 근거 | SHA-256 |
|---|---|
| 설치 NetHelp `Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| Current Limits image `_66.png` | `248D74A6F9CCAF06847481061586AC730D280CA531E427FC03EF289DE4F3D156` |
| Motion Limits image `_68.png` | `C7D1FDB9B1D6C8CA898E7C9B6972B6C9E840EC354F2652FC116940EE94A5BEAE` |
| Protections image `_69.png` | `0840FB3554AD30DB8DE1DC429031C70CA03B2A1C3C772007367D515C445CE223` |
| Disable Feedback Limits image `_71.png` | `8B4CE688DBA5960C7289344B17EEAB2A5D668954918B1F8D94B1DBD0217DCA46` |
| `docs/man-g-cr_GoldLine_CommandReference.pdf` | `89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80` |
| `docs/firmware-release-notes.txt` | `3E70090E7E9E43290A972EE96ED057AF7E4E6D74FDA92780F6AD7D47BD201719` |

명령별 HTML source와 SimplIQ `Alphabetical Listing.htm`을 포함한 **20개**
exact location/hash 전체 집합은
`expert_limits_protections_evidence.py`의 frozen `SOURCES`가 canonical이다.

## 다음 gate

live/read/write 기능을 설계하려면 최소한 exact Gold Twitter SKU·firmware
적용성, FC/UM/DS-402 mode, current parameter readback, motor rating, 기계
envelope, 방향·limit polarity, EAS dropdown mapping, validation/write order,
readback/rollback/Revert/SV, independent E-stop/STO 증거가 필요하다.

이 근거가 갖춰지기 전에는 현재 catalog를 값 검사기, 설정 추천기,
protection validator 또는 write path로 승격하지 않는다.
