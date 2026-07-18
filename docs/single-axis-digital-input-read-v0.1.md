# Single Axis Digital Inputs · Read-Only Snapshot v0.1

## 목적과 현재 판정

EAS III `Motion - Single Axis`의 I/O Status Area 중 Digital Input 1–6만
명시적 새로고침으로 읽는다. 화면이 비슷해도 Digital Output checkbox는 실제
출력 변경이므로 포함하지 않는다.

- `OBSERVED`: 설치 Gold 도움말은 `IP`의 bit 16–21을 Digital Input 1–6의
  logical pin state로 정의하고, `IL[N]`은 function/polarity/sticky,
  `IF[N]`은 software filter time을 제공한다.
- `DERIVED`: 한 snapshot은 `IL[1]..IL[6]`, `IF[1]..IF[6]`, 마지막 `IP`
  순서로 읽으며 동일 connection session과 bounded duration이 유지돼야 한다.
- 현재 판정:
  `CURRENT DRIVE READ ONLY · PARTIAL`.
- `OBSERVED`: 2026-07-19 05:28 KST의 Read Only session에서 현재 Gold Twitter가
  6개 입력 모두 `ACTIVE · DRIVE LOGICAL`, `General purpose`,
  `ACTIVE_HIGH · non-sticky`, `0.000 ms`를 반환했고 bounded acquisition은
  25.9 ms였다.
- 아직 `UNVERIFIED`: 배선과 raw pin 전압, 물리 입력 응답, EAS same-moment
  표시 parity와 polarity/filter/sticky의 실제 timing.

이 기능은 입력을 바꾸거나 모터를 구동하지 않는다. 표시값은 drive가 해석한
logical state이며 독립 STO/E-stop 시험이나 물리 전압 측정이 아니다.

## 읽기 계약

명시적 `Refresh Digital Inputs · READ ONLY` 한 번에 다음 query만 허용한다.

```text
IL[1] ... IL[6]
IF[1] ... IF[6]
IP
```

- 각 query timeout: 최대 150 ms
- 전체 snapshot duration: 최대 2.0 s
- 시작/종료의 `transaction_session_identity()`는 같은 object여야 한다.
- 입력 하나라도 missing, bool, non-integral, non-finite, 범위 밖,
  reserved `IL` bit 또는 session/timing 오류이면 전체를 `UNKNOWN`으로 blank한다.
- worker, connection, telemetry authority가 바뀌거나 energizing/shutdown 상태면
  UI가 snapshot을 거부하고 즉시 blank한다.
- `IP`는 마지막에 한 번만 읽어 6개 state를 같은 sample로 해석한다.

UI의 6개 row는 다음을 표시한다.

| 열 | 근거 |
|---|---|
| Input | 1–6 고정 |
| Drive Logical State | `IP` bit 16–21 |
| IL Function | `IL` bits 1–4의 code 0–15 |
| Polarity / Sticky | `IL` bit 0과 bit 8 |
| IF Filter | `IF[N]`, ms |

`IL` function label은 command reference의 0–15 code를 그대로 분리한다.
label이 `stop`, `limit`, `home`, `abort`를 포함해도 현재 배선·안전 동작 또는
기능 유효성을 보증하지 않는다.

## 명시적으로 제외한 쓰기와 동작

다음은 query allowlist 밖이며 이 feature와 버튼에서 실행할 수 없다.

- `IB[17..32]` write를 통한 sticky-bit clear
- `IL[N]=...` function/polarity/sticky 설정
- `IF[N]=...` filter 설정
- Digital Output read/write와 checkbox actuation
- UM 변경, Enable/Disable, PTP/Jog/Homing/Current/Sine/Stepper
- Terminal command, Recorder config/acquisition
- Apply, Revert, `SV`, energization, motion

특히 command reference의 `IB[17..32]`는 읽기처럼 보이는 이름이라도
write 1로 sticky bit를 clear할 수 있어 사용하지 않는다.

## 해석 제한

- `active low/high`는 drive의 `IL` polarity 설정과 logical state 해석이다.
  raw electrical level이나 wiring polarity의 독립 증거가 아니다.
- `IF`는 firmware의 내부 sample period에 맞게 quantize될 수 있다.
  hardware capture는 software filter를 우회할 수 있다.
- `IF` 문서에는 index 범위가 1–16으로 보이는 대목과 1–6 표가 함께 있다.
  현재 target과 EAS 화면의 6개 입력 범위만 구현한다.
- sticky flag가 보이더라도 언제/어떤 edge가 발생했는지와 source timestamp를
  제공하지 않는다.
- snapshot은 해당 session과 fresh telemetry authority에서만 CURRENT다.
  재연결 뒤에는 자동 복원하지 않고 다시 명시적으로 읽어야 한다.
- Gold Twitter 이외의 Gold 제품, 다른 firmware, 다른 I/O count로 일반화하지 않는다.

## 동결한 source identity

| Key | 설치 경로 | SHA-256 |
|---|---|---|
| `single_axis_html` | `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities.htm` | `BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE` |
| `ip_command_html` | `...\Gold Line Command Reference\IP Input Port.htm` | `0594BD5A9A1B8DCC0128985747E0ED86861A917A87CB292528180B186A413336` |
| `il_command_html` | `...\Gold Line Command Reference\IL Digital Input Logic.htm` | `F5C058B8A2CE435411A8114D7BB30ADD4E640D5BBA8B14737702096BF60F99C2` |
| `if_command_html` | `...\Gold Line Command Reference\IF Digital Input Filter.htm` | `1803C3A188B45B4E0945D161211FDD04887B12727F209977C52871F4292260BA` |

설치 경로와 파일명만으로 authority를 얻지 않는다. decoder와 tests는 위 네
byte identity, 문서의 bit/range 정의와 현재 6-input 범위에 결합된다.

## 검증 계약

`tests/test_single_axis_digital_inputs.py`와 연동 tests는 다음을 고정한다.

- 16개 exact function code와 IP bit 16–21 decode
- invalid/missing/reserved/non-finite/out-of-range 전체 fail-closed
- exact query order와 `IB`/assignment/output query 0
- connection-session 변경, read error, duration 초과의 전체 blank
- observe-only allowlist가 `IP`, `IL/IF[1..6]`만 허용
- worker queue/emission과 current-worker/current-authority UI gate
- disconnect/stale/energizing 때 blank, fresh explicit refresh만 복구
- frame 안 action은 refresh button 하나이며 editable/output control 0
- 세 skin의 table contrast ≥ 4.5:1과 horizontal scroll 0
- 설치 source SHA-256 4/4 exact identity

최신 직접 영향 범위는 **133 passed in 96.03s**, 숫자 종료코드 **0**이다.
이 수치는 decoder/transport/worker/UI/catalog의 offline contract 증거이며
physical I/O validation 점수가 아니다.

확대 영향범위는 **489 passed in 370.16s**, stderr 0이었다. 다만 이 실행 뒤
실제 Read Only refresh에서 transport query allowlist는 통과하지만 worker의
observer job allowlist가 `axis_digital_inputs_read`를 거부하는 통합 누락을
관찰했다. 같은 job을 query-only guard test의 허용 case로 추가해 RED를 재현한
뒤 observer allowlist에 이 읽기 job 하나만 추가했고 관련 gate **6 passed**를
확인했다. 최신 수정 전체 회귀 결과는 closeout에서 이 과거 489개 결과와
분리해 기록한다.

수정된 새 Python 3.14 제어창에서 같은 target에 다시 Read Only 연결 후 명시적
refresh를 실행해 `CURRENT · DRIVE READ ONLY`, 입력 1–6의 위 값을 확인했다.
Motor Enable, output, `IB`, assignment, mapping/filter change, PTP/Jog/Current/
Sine/Homing/Stepper, Terminal, Recorder, Apply/SV는 실행하지 않았다. 모든
입력이 ACTIVE였다는 관찰은 배선 정상, safe state 또는 물리 입력 전압의
증거가 아니다.

최신 전체 repository stdout은 **1639 passed in 827.24s**, 100%, stderr
**0 bytes**다. 별도 numeric-exit watcher가 빈 파일을 남겼으므로 전체 suite의
숫자 exit code만 `UNVERIFIED`로 남기고 `exit 0`이라고 주장하지 않는다.
focused suite의 exit 0, 전체 pass count/100% summary와 stderr 0은 직접 관찰했다.

## 다음 gate

1. EAS I/O Status Area와 같은 순간의 값 비교
2. 비통전 상태에서 known inactive/active 입력을 하나씩 독립 계측
3. polarity/filter/sticky와 source timestamp 의미 검증
4. 다른 feedback motor가 아니라 I/O count가 다른 Gold target에서 재발견
5. Digital Output은 별도 safe-state/부하/rollback/권한 설계 전까지 잠금

현장 검증 전에는 이 snapshot을 safety interlock의 유일한 입력으로 사용하지 않는다.
