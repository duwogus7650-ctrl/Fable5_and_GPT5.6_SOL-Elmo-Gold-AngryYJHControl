# Single Axis Position / Velocity References · Read-Only Snapshot v0.1

> **2026-07-19 EAS live audit correction:** AngryYJH raw
> `PX=-2038379934`는 EAS Terminal raw `PX`와 정확히 일치했지만, 같은 순간
> EAS Single Axis/Verification-Time 표시 위치는 `-2004825502`였다.
> 차이는 `33554432 = 2^25 counts`이며 원인은 아직 `MISMATCH_NEED_DATA`다.
> raw PX 일치를 EAS 화면 좌표 parity로 확대하지 않는다.

## Outcome

`Motion` page에 position/velocity 관련 drive parameter와 live feedback을
한 번에 읽는 별도 panel을 추가했다. 이 panel은 다음을 엄격히 구분한다.

- `PA[1]`, `PR[1]`, `JV`: configured 또는 queued reference readback.
- `SP[1]`, `AC[1]`, `DC`, `SD`: main profiler 설정과 stop-deceleration cap.
- `PX`, `VX`: 조회 시점의 live main-feedback position/velocity.
- 어느 값도 active command 또는 실제 motion의 증거로 해석하지 않는다.

명령 실행은 구현하지 않았다. `PA/PR/JV` assignment, `BG`, `MO=1`,
mode 변경, enable, energization, motion은 이 기능에서 발생하지 않는다.

## Frozen query contract

`single_axis_position_velocity_reference.READ_STEPS`는 다음 18개 query만
150 ms/query, 1.5 s/snapshot 한도로 실행한다.

```text
MO, SO, MF, SR,
UM,
PA[1], PR[1], JV, SP[1], AC[1], DC, SD, PX, VX,
MO, SO, MF, SR
```

모든 query는 동일 `transaction_session_identity`에 묶인다. 시작/종료
session identity가 다르거나, 안전 관련 pre/post 상태가 달라지거나,
값·단위 범위·acquisition 시간이 유효하지 않으면 전체 snapshot을
`UNKNOWN`으로 blank한다.

Transport에서는 `JV`, `PA[1]`, `PR[1]`, `SP[1]`, `AC[1]`의 exact query만
추가 허용했다. 다음은 vendor I/O 전에 계속 차단된다.

```text
PA, PR, PA[2], PR[2], SP[2], AC[2], JV[1]
PA[1]=..., PR[1]=..., JV=..., SP[1]=..., AC[1]=...
BG, MO=1
```

## Decoder invariants

- `MO`, `SO`, `MF`는 pre/post가 같아야 한다.
- `SR`의 Motor On/Servo Enabled bit는 `MO/SO`와 일치해야 한다.
- safety/motion 관련 `SR` mask는 acquisition 동안 안정적이어야 한다.
- `UM`은 설치 Gold 문서의 `1/2/3/5/6`만 해석한다.
- `PA[1]`, `PR[1]`, `JV`, `PX`는 signed 32-bit integer다.
- `SP[1]`은 `0..2^31-1`, `AC[1]`, `DC`, `SD`는
  `1..2^31-1` 범위다.
- `VX`는 finite `-2e9..2e9 cnt/s`다.
- main profiler의 effective acceleration/deceleration은 각각
  `min(AC[1], SD)`, `min(DC, SD)`로 표시한다. 설정값이 SD보다 크더라도
  snapshot을 거부하지 않고 `LIMITED BY SD`로 명시한다.

## UI and authority

- 표는 9개 행이며 모든 행은 read-only다.
- action은 `Refresh Position / Velocity References - READ ONLY` 하나뿐이다.
- spin box, combo box, check box, line edit, slider가 없다.
- snapshot은 canonical re-decode와 현재 worker/session authority를 통과해야
  표시된다.
- disconnect, telemetry authority 상실, energizing transition, forged/late
  snapshot에서 즉시 `UNKNOWN`으로 blank한다.
- command operation은 별도
  `axis.position_velocity_reference.command`로
  `MOTION / NEED_DATA`에 잠겨 있다.

실제 1366×820 확인에서 최초 table 높이 360 px가 마지막 `VX` 행을
가리는 문제가 관찰됐다. 410 px 이상 계약을 RED로 추가하고 420 px로
수정해 `VX = 0.000 cnt/s`까지 표시되는 것을 재검증했다.

## Installed source identity

| Key | Installed Gold page | SHA-256 |
|---|---|---|
| PA | `PA N Position Absolute.htm` | `40F8B55DDCED8C0BE6A3ACB88BD0E15A8E35C4CD12C22C5BF0047E4BBE4978F9` |
| PR | `PR N Position Relative.htm` | `245BBA0F05357FAE5D3AE98A67734D5C36D8BB0B7371F0F620F1C70DCBDD3B4D` |
| JV | `JV Jog Velocity.htm` | `9C0C536586335AF2FFB1CDEA2EFC63937476C2401E5655F81A8DD48AF92BDBEA` |
| SP | `SP N PTP Profiler Speed.htm` | `3CB54282817987E3B752A810D04B7B52CE4CF191D5650AF8E70FBF04F39CD8D5` |
| AC | `AC N Set Acceleration.htm` | `B9AA59CFD00F017A6CFE6D10D5DB1BC1D7093BD47CDB1D5E3F397CA7481120F7` |
| DC | `DC Set Deceleration.htm` | `75C1C5452D495BA796D99FD868F46A3029A9A2E008EE93F07A18550ECAF39554` |
| SD | `SD Stop Deceleration.htm` | `785E2AEDF1CB90A71DF41349742DD2ED207BCAD6FDCF1226D38C3EC38D24E935` |
| PX | `PX Main Position in Counts.htm` | `AF2BE7117C4816FB815D16C7F05CE5B44098D5A8B28B7BE2A1666EAD5F93E363` |
| VX | `VX Main Feedback Velocity.htm` | `A6D910DFCB93AD746B57EE8D12A6EC807BCB573FE05ACF4F1A2D3FDE0D74CD7A` |
| UM | `UM Unit Mode.htm` | `8E50AC03CD82F119EEAB3A2BC8C311086EF4CB9F03C06F597084EC79BB3277F8` |
| MO/SO | `MO SO Motor On Servo On.htm` | `363632520E982C5B42BAF683ECCDBAA1E59623DC4EEE512B7291DA611C671E37` |
| MF | `MF Drive Fault.htm` | `2145352F50DA457DF5EEDA45F4D8B505C4E9EF5D7B911F7DE7C437F864A36307` |
| SR | `SR Status Register.htm` | `7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF` |

2026-07-19 재해시 결과는 13/13 byte identity 일치다.

## Current-target observation

Python 3.14 앱을 새 코드로 재시작하고 COM3를 `Read Only`로 연결했다.
모터는 `DISABLED REPORTED`, `UM=5 Position`이었다.

| Item | Observed readback |
|---|---:|
| PA[1] | `0 cnt` |
| PR[1] | `0 cnt` |
| JV | `0 cnt/s` |
| SP[1] | `4,444,444 cnt/s` |
| AC[1] | `1,000,000 cnt/s²` |
| DC | `1,000,000 cnt/s²` |
| SD | `1,000,000 cnt/s²` |
| PX | `-2,038,379,934 cnt` |
| VX | `0.000 cnt/s` |
| Acquisition | `35.6 ms` |

`AC[1]/DC WITHIN SD`였다. 조회 전후 `MO/SO/MF/SR`가 안정적으로
일치해 `CURRENT - DRIVE READ ONLY`로 표시됐다. `PX=0`을 포함한 write,
enable, `BG`, energization, motion은 실행하지 않았다.

## Verification evidence

- pure decoder/reader: `56 passed`.
- transport + pure: `144 passed`.
- authority/UI/catalog/transport 직접 영향 범위: `244 passed`.
- closeout 영향 범위(모니터 포함): `270 passed in 104.51s`.
- UI clipping negative control: 360 px에서 RED, 420 px에서 GREEN.
- 전체 repository 회귀: `1868 passed in 735.79s (12:15)`.
- `git diff --check`: exit 0.

이 증거는 exact current-target readback과 앱의 fail-closed 동작만 지지한다.
EAS same-moment parity, encoder coordinate validity, physical motion capability,
safe travel/stopping envelope, independent STO/E-stop, 다른 Gold 제품/firmware
호환성은 `NEED-DATA / NO-GO`다.

## Command boundary

향후 PA/PR/JV + BG 실행에는 최소한 다음이 필요하다.

- exact user-unit/count scaling과 direction convention.
- target-specific travel, speed, acceleration, stop distance envelope.
- position/velocity/current limit와 external limit input 확인.
- restrained load, operator presence, independent E-stop/STO.
- stale telemetry/watchdog/timeout/fault/disconnect abort.
- terminal readback과 `ST -> MO=0` verified closeout.

이 gate가 없으면 readback panel을 command surface로 확장하지 않는다.
