# Single Axis Drive Mode · Read-Only Snapshot v0.1

## Outcome

Motion 화면에 현재 Gold drive의 `UM`을 한 번만 조회하는 명시적
`DRIVE MODE (UM) · READ-ONLY SNAPSHOT v0.1` 카드를 추가했다.

- `OBSERVED` 2026-07-19 11:51 KST, COM3 `ONLINE · READ ONLY`
- drive report: `UM=5 · Position`
- acquisition: `2.1 ms`
- 동시에 표시된 host telemetry: motor `DISABLED`, velocity `0`, active current `0`
- 실행하지 않음: `UM=` assignment, Enable/Disable, `TC/JV/PA/PR/BG`,
  reference 변경, energization, motion, `SV`

이 결과는 현재 identity-bound session의 drive-reported `UM` 값만 증명한다.
EAS same-moment parity, control-loop performance, 저장 상태, 안전성 또는 다른
Gold 제품 호환성을 증명하지 않는다.

게시 후 closeout에서 exact implementation commit `d84d7b8`의 Python 3.14
제어창을 재시작해 같은 Read Only 상태와 `UM=5 · Position`을 다시 관찰했다.
두 번째 acquisition은 `2.3 ms`였다.

## Frozen installed source

| Source | Location | SHA-256 |
|---|---|---|
| Gold `UM – Unit Mode` | `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\Gold Line Command Reference\UM Unit Mode.htm` | `8E50AC03CD82F119EEAB3A2BC8C311086EF4CB9F03C06F597084EC79BB3277F8` |

설치 문서에서 직접 확인한 계약:

- type: Long, Read/Write
- restriction: motor must be off
- range: 1–6, excluding 4
- default: 3
- non-volatile: Yes
- `UM=1`: Torque, `TC`
- `UM=2`: Speed, `JV` 후 `BG`; `TC`가 torque loop를 강제할 수 있음
- `UM=3`: Stepper, current loop 외 폐루프 없음; `PA/PR/JV/TC`
- `UM=4`: Reserved
- `UM=5`: Position, single/dual; `PA/PR`; `JV` 또는 `TC`가 하위 loop를
  강제할 수 있음
- `UM=6`: Stepper open/closed loop; `HT[]/FF[]`; closed loop는 sensor ID 34 필요

## Exact reader boundary

[`single_axis_drive_mode.py`](../single_axis_drive_mode.py)는 다음만 수행한다.

1. 현재 transport session identity를 얻는다.
2. `UM` 한 건을 `150 ms` timeout으로 조회한다.
3. session identity가 바뀌지 않았는지 확인한다.
4. acquisition이 `0..0.5 s`인지 확인한다.
5. exact integer `1,2,3,5,6`만 immutable documented map으로 해석한다.

missing, bool, NaN/Inf, non-integral, reserved `4`, 미지원 값, timeout/read error,
session 교체, stale duration은 전체 snapshot을 `UNKNOWN`으로 blank한다.

## Change contract

`axis.drive_mode.refresh`와 `axis.drive_mode.change`는 서로 다른 operation이다.

- refresh: `DRIVE_READ · PARTIAL`, exact `UM` query only
- change: `NEED_DATA`, UI control·worker job·assignment 없음

향후 `UM=` 변경을 열기 위한 최소 조건:

- verified identity와 current connection generation
- fresh `MO=0`, `SO=0`, `VX=0` 및 disabled/stationary 재확인
- 현재 UM과 target UM의 정확한 capability/firmware/personality 적합성
- 비휘발성 mutation 전 durable recovery record
- exact assignment/readback 및 timeout/disconnect/fault 판정
- 이전 UM 복구와 rollback authority
- mode 전환이 reference/loop/state에 미치는 영향의 현장 closeout

문서의 “control loops can be freely switched without disabling the motor” 문장은
`UM` assignment 자체의 “motor must be off” 제한과 구분한다. 이 프로그램은
이를 UM live-change 권한으로 해석하지 않는다.

## Verification

- pure UM contract: `24 passed`
- decoder/worker/catalog/UI/transport/safety integration slice:
  `261 passed in 88.22s`
- Motion UI 3-skin geometry/readability: `32 passed in 57.09s`
- latest focused split: Single Axis motion `53 passed in 0.49s`;
  remaining UM integration `287 passed in 130.75s`
- full repository: `1717 passed in 1012.58s`, numeric exit `0`
- installed source SHA-256: `1/1` match
- current-target runtime: `UM=5 · Position`, `2.1 ms`
