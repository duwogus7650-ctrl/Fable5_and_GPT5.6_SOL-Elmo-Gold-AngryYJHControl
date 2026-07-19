# Single Axis Current Reference + EAS Preset Drafts · v0.2

> **2026-07-19 EAS live audit correction:** 기존
> `TC/IQ/ID/CL/PL/LC/MC` panel은 current-drive readback이다. 별도 panel로
> EAS Single Axis의 `Current Command 1..5` host preset shape를 구현했지만,
> 모든 Set은 항상 잠겨 있고 drive I/O가 없다.

## 판정

이 기능은 현재 Gold Twitter에서 `TC`, `IQ`, `ID`, `CL[1]`, `PL[1]`,
`LC`, `MC`를 한 번의 identity-bound 조회 묶음으로 표시하는
**CURRENT DRIVE READ ONLY** 기능이다.

- `OBSERVED`: 2026-07-19 KST의 COM3 Read Only 세션에서 아래 스냅샷을
  정상 취득했다.
- `OBSERVED`: 명시적 조회 시간은 **32.2 ms**였다.
- `OBSERVED`: 조회 전후 `MO/SO/MF/SR`와 `LC`의 상태 비트 교차검증이
  통과했다.
- `OBSERVED`: 모터는 `DISABLED REPORTED`, mode는 `UM=5 · Position`이었다.
- `NEED-DATA`: `TC=` 전류 지령, motor enable, loop 변경, 통전, 토크 발생,
  모션, EAS same-moment parity 및 물리 전류 계측은 이 기능이 증명하지 않는다.

Software `DRIVE STOP`은 독립 STO/E-stop이 아니며, 이 readback을 hardware
safety 또는 torque-isolation 증거로 사용하면 안 된다.

## EAS Current preset local draft

EAS III live UI에서 다음을 관찰했다.

- `Current Command 1..5 [Amp.]`의 다섯 editable host preset.
- 초기값은 모두 `0`.
- 각 row tooltip은 동일한 `[TC]` target.
- motor disabled 상태에서 다섯 Set 버튼 모두 disabled.

앱은 이를 `single_axis_current_presets.py`의 pure local model과 별도 UI
frame으로 구현했다.

- 값 편집은 local draft만 변경한다.
- 정확히 다섯 값, finite number, 관찰된 `CL[1]/PL[1]/MC` limit band를
  검증한다.
- 각 preview는 같은 `TC` register를 가리킨다.
- `Set TC · LOCKED` 버튼은 다섯 개 모두 disabled이며 signal connection,
  worker job, transport call이 없다.
- Current Reference snapshot이 있으면 local warning만 갱신하며 command
  authority로 승격하지 않는다.

따라서 UI shape/mapping 판정은 `PARTIAL_LIVE_OBSERVED`, 출력 판정은
`OUTPUT LOCKED / NEED-DATA`다. 실제 EAS Set behavior와 TC assignment parity는
실행하지 않았다.

## 동결된 조회 절차

`single_axis_current_reference.READ_STEPS`는 다음 16개 query만 허용한다.
각 query timeout은 150 ms이고 전체 snapshot은 1.5 s를 넘으면 폐기한다.

```text
MO, SO, MF, SR,
UM, TC, IQ, ID, CL[1], PL[1], LC, MC,
MO, SO, MF, SR
```

모든 명령은 assignment가 없는 bare query다. 시작과 끝의 connection-session
identity가 같아야 하며 다음 조건 중 하나라도 어기면 전체 값을 blank하고
`UNKNOWN`으로 강등한다.

- `MO/SO/MF`가 acquisition 중 변하지 않음
- `SR`의 motor-on, servo-enabled, current-limit 비트가 `MO/SO/LC`와 일치
- 안전·fault·current 관련 `SR` mask가 acquisition 중 변하지 않음
- `UM`이 설치 문서의 `1/2/3/5/6` 중 하나
- 모든 수치가 finite
- `0 <= CL[1] <= MC`, `0 <= PL[1] <= MC`
- `-PL[1] <= TC <= PL[1]`
- `-MC <= IQ, ID <= MC`
- `MO=0`이면 문서 계약에 따라 `IQ=ID=0`

## 현재 target 관찰값

관찰 환경:

- host app: Python 3.14 `AngryYJH Control`
- access: `ONLINE · READ ONLY`
- firmware: `Twitter 01.01.16.00 08Mar2020B01G`
- PAL: `90`
- boot: `DSP Boot 1.0.1.6 12Feb2014G`
- application target class: `Gold Drive`
- motor state: `DISABLED REPORTED`
- drive mode: `UM=5 · Position`

| Drive item | 관찰값 | 의미/경계 |
|---|---:|---|
| `TC` | `0.0000 A` | torque/current command query; assignment 아님 |
| `IQ` | `0.0000 A` | torque-producing active current component |
| `ID` | `0.0000 A` | reactive current component |
| `CL[1]` | `21.2132 A` | continuous motor phase-current limit parameter |
| `PL[1]` | `70.7107 A` | peak current limit parameter |
| `LC` | `0 · OFF` | current-limit flag |
| `MC` | `140.0000 A` | factory maximum phase-current rating |

`CL[1] <= PL[1] <= MC`와 motor-off `IQ=ID=0`이 통과했다. 이 값은 drive
parameter/readback이며 독립 전류 센서 측정, RMS 환산 결과, 실제 motor phase
current 또는 토크 검증이 아니다.

## 전송 가드와 실패 이력

첫 field refresh는 vendor I/O 전에
`observe-only session blocked command ... 'TC'`로 안전하게 실패했다.
원인은 transport의 exact query allowlist에 bare `TC`와 `LC`가 빠져 있었고,
bare `TC`도 assignment와 같이 motion prefix로 분류된 것이었다.

수정 계약:

- exact `TC`와 `LC`만 scalar query allowlist에 추가
- exact bare `TC`만 non-motion query로 분류
- `TC=0.1`, `LC=1`, `TC[1]`과 알 수 없는 명령은 계속 vendor I/O 전에 차단
- 기존 `TC=0` software de-energizing escape는 변경하지 않음
- `TC=` nonzero assignment와 power/motion 명령은 계속 별도
  `allow_motion` 및 상위 transaction authority가 필요

테스트 우선 증거:

- RED: `TC`, `LC`, composed Current Reference read가 정확히 3건 실패
- GREEN: transport/telemetry safety **64 passed**
- GREEN: Current Reference·UI·catalog·main safety·transport 영향 범위
  **286 passed**
- GREEN: 전체 repository **1781 passed in 1269.31s / exit 0**
- 최신 PX/PU + EAS preset draft revision 전체 repository:
  **1956 passed in 692.83s / exit 0**

## 설치 문서 identity

모든 source는 설치된 EAS III Gold Line Command Reference의 로컬 HTML이다.

| Source | SHA-256 |
|---|---|
| `TC Torque Command.htm` | `E9152A936F2717C747A0382B215D5463966A56B36F7D203D126251C068856CA9` |
| `CL Current Limit Parameters.htm` | `A881FE3E645E42D417E6E598EE3A8016AA04910277B935DD92AC02999598F48C` |
| `PL N Peak Limit.htm` | `5A65892FA038EEE704A23F232EC4A901F4A29584345AC02BD7E502A07F5C37D2` |
| `LC Current Limit Flag.htm` | `08848BA17A1253660849BCAC3DD5966FB8C2628DD46AC0381E2CC66AAE3A1079` |
| `MC Maximum Current.htm` | `26EBD384B34F4616454A41BECD66DBD193A4093AE5BEC73941D1B7E05C112205` |
| `ID IQ Active Reactive Current.htm` | `2D1E639F7F4C0374E91793CD8085D6ABA85B9E6F3C4F1A04B7C205E5041DB4C2` |
| `UM Unit Mode.htm` | `8E50AC03CD82F119EEAB3A2BC8C311086EF4CB9F03C06F597084EC79BB3277F8` |
| `MO SO Motor On Servo On.htm` | `363632520E982C5B42BAF683ECCDBAA1E59623DC4EEE512B7291DA611C671E37` |
| `SR Status Register.htm` | `7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF` |

## 명령 기능의 별도 잠금

기존 `axis.current_reference.command`는 operation catalog에
`ENERGIZING / NEED_DATA`로만 존재한다. 새 다섯 button의 operationId는
`axis.current_command_preset.N.locked` 표시 metadata일 뿐 catalog dispatch나
실행 handler가 없다. 향후 `TC=` 기능을 열려면 최소한 다음 근거가 별도로
필요하다.

- current/thermal/torque envelope와 unit convention
- restrained load와 의도하지 않은 motion/twitch 대책
- independent E-stop/STO 및 현장 operator gate
- `MO=1` 뒤 `SO=1` readback
- telemetry watchdog와 stale/comms-loss abort
- `PL[1]/CL[1]/MC`에 종속된 command bounds
- 모든 종료 경로의 `ST -> MO=0`과 terminal readback
- fault, timeout, disconnect, reconnect, cold-start 복구 검증

이 근거가 없으면 Current Reference의 **읽기 완료**를 current-command
실행 권한으로 승격하지 않는다.
