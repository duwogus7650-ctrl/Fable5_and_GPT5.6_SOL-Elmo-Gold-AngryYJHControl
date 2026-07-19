# Supervised field validation session · 2026-07-19

## Scope and authority

This session started the current-revision field-validation sequence with a
read-only, no-motion baseline. It did not authorize or execute motor enable,
current command, tuning, commutation, PTP/Jog/Homing/Sine motion, parameter
assignment, Apply, Save, or `SV`.

- repository revision: `f03453aead75d8cb098e4fc91f6f98feeb7ea322`
- branch: `codex/quick-single-axis-handoff`
- host time: 2026-07-19 23:08–23:17 KST
- operator request: begin supervised field verification

## AngryYJH read-only baseline

Connection:

- `ONLINE · READ ONLY`, Direct Access USB, COM3
- firmware: `Twitter 01.01.16.00 08Mar2020B01G`
- PAL: `90`
- boot: `DSP Boot 1.0.1.6 12Feb2014G`
- target class: `Gold Drive`

Observed drive state:

- `MOTOR DISABLED`
- raw `PX=-2038379934 cnt`
- velocity `0 cnt/s`
- position error `0 cnt`
- active current `0 A`
- Axis snapshot: `MO=0`, `SO=0`, `MF=0`, amplifier code `0x0`,
  `SR4=0`, `SR14=1`, `SR15=1`, `SR13=0`, `SR27=0`

Explicit bounded reads:

| Read | Result |
|---|---|
| Position/Velocity references | `CURRENT`, acquisition `54.6 ms`, VX=0 |
| Drive Mode | `UM=5 Position`, acquisition `2.0 ms` |
| Current | TC/IQ/ID=0 A, CL=21.2132 A, PL=70.7107 A, LC=OFF, MC=140 A |
| Digital Inputs | Inputs 1–6 active, GP, active-high/non-sticky, 0 ms; acquisition `27.7 ms` |
| Digital Outputs | Outputs 1–4 inactive, GP, active-high; acquisition `20.4 ms` |

The application was normally disconnected before EAS was connected.

## Same-session EAS comparison

EAS III was connected alone to the same target and then normally disconnected.

Identity:

- target `Drive01`
- hardware `GCON Revision E`
- target version `Twitter 01.01.16.00 08Mar2020B01G`
- PAL `90.1 (V1)`
- target type `Gold Drive`
- target serial `22033647`
- Direct Access USB, COM3

Single Axis observations:

- Drive Mode `Position [UM=5]`
- Digital Inputs 1–6 green/active and GP
- Digital Outputs 1–4 unchecked/inactive
- drive-reported STO1/STO2 indicators green and ERR indicator off
- terminal retained/read `PX=-2038379934`
- Position profile: AC/DC/StopDec=`1E+6`, Speed=`4444444`
- Current Commands 1–5=`0`; all five Set buttons disabled with motor off

Quick Tuning observations:

- Axis: Single Axis, Rotary Motor/Rotary Load, no transmission, Single
  Feedback, Position UM=5, brake/vertical-axis unchecked
- Motor database: Not in Use
- Peak Current=`50 Arms`, Continuous Stall Current=`15 Arms`,
  Maximal Motor Speed=`3600 rpm`, Pole Pairs=`16`
- configured phase-to-phase `R=0.136 ohm`, `L=0.0395 mH`, `Ke=0`
- Feedback on Motor: Serial Absolute EnDat 2.2 designation 22
- rotary, Position + Velocity + Commutation, no digital Halls
- Direction=Non Invert, Clock Frequency=5.000 MHz,
  Input Glitch Filter=120 ns, Serial Data Polling=Every TS,
  Error Bitwise Mask=0x0

`Run Automatic Tuning`, Enable, Set Current, Apply, Revert, Save, and all
motion controls were not executed.

## Gate to the first energized step

The first write-capable action is only a `SUPERVISED` connection. It does not
by itself enable or move the motor, but it remains blocked until the on-site
operator confirms for this run:

1. operator present, axis area clear, and load restrained;
2. independent E-stop/STO tested and immediately available;
3. positive direction and the allowed travel envelope physically verified.

After that confirmation, each energized action still needs exact command
bounds, duration, live abort conditions, and verified `ST -> MO=0` closeout.

## Current verdict

- procedure through no-motion baseline: `GREEN`
- telemetry freshness and identity: `GREEN` for the bounded observed reads
- independent protection: `NEED-DATA`
- motion/current command bounds: `NEED-DATA`
- final state at the end of the read-only comparison: `GREEN` — AngryYJH and
  EAS were both normally disconnected; no motor action or setting change
  occurred

## Supervised admission · 23:25–23:27 KST

The operator then reported that the on-site presence, clear/restrained axis
area, independent E-stop/STO availability/test, direction, and allowed travel
conditions were all checked for this run. The application was admitted as
`ONLINE · SUPERVISED` on COM3. Connection admission alone did not enable the
motor or issue a motion/current command.

Fresh post-admission readback:

- `MO=0`, `SO=0`, `MF=0`
- amplifier code `0x0`
- `SR4=0`
- drive-reported `SR14=1`, `SR15=1`
- `PS=2`, `SR12=0`, `SR13=0`
- `MS=3`, `SR[11:8]=0`

The application correctly invalidated the prior connection's commutation
authority and reported `Commutation Signature required this connection`.
The proposed first energized action is the dedicated standalone signature:
`+TC 0 -> at most 1.30 A`, at most `2.0 s`, with no Phase-2 continuation and
mandatory final readback `TC=0`, `MO=0`, plus restoration of all temporary
limits.

No signature, `MO=1`, tuning, parameter assignment, motion, Apply, Save, or
`SV` had been executed when this entry was recorded.

At 23:30 KST the on-site operator supplied and approved the remaining
action-specific gate:

- DC-link: `48 V`
- external supply current limit: `5 A`
- approved action: standalone commutation signature, `+TC 0 -> at most
  1.30 A`, at most `2.0 s`

This approval does not include Phase 1/2, PTP/Jog/Homing/Sine motion,
parameter Apply/Save, `SV`, automatic retry, or any higher current/duration.

## Standalone commutation-signature attempt · 23:33 KST

The approved standalone signature was started once. It did not produce a
commutation signature and was not retried.

Preflight artifact:

- `TS=100 us`, `UM=5`
- initial `MF=0`, `VX=0`, `PX=-2038379934`
- `CA[17]=5`, `CA[18]=65536`, `CA[19]=16`
- `CL[1]=21.2132 A`, `PL[1]=70.7107 A`, `MC=140 A`
- `BV=100 V` is the drive's maximum bus-voltage rating; the operator-reported
  actual DC-link for this run remained `48 V`

Observed result:

- result: `RED`
- reason: `MF=0x80`
- commutation breakaway current: not detected
- direction: not established
- Phase 2: not entered and remained locked
- UI closeout: `MO=0`, `TC=0`

The Gold Line command reference defines `MF=128 (0x80)` as a speed-tracking
error: the absolute difference between the speed command and feedback exceeded
`ER[2]`. The raw result contains no `breakaway` or `signature_gate` evidence
and records `abort.segment="idle"`. This is consistent with a fault at or near
motor enable, before the breakaway/signature measurement was reached; it does
not establish that the approved 1.30 A ramp was delivered.

Temporary RAM limits were treated transactionally and restored:

| Parameter | Before | Temporary | Restored |
|---|---:|---:|---:|
| `SD` | 1,000,000 | 4,000,000 | 1,000,000 |
| `HL[2]` | 0 | 1,970,000 | 0 |
| `LL[2]` | 0 | -1,970,000 | 0 |
| `ER[2]` | 100,000,000 | 330,000 | 100,000,000 |

Both forward and reverse closeout readbacks matched. The result artifact
reported `configuration_state=RESTORED`, `final_state.pass=true`,
`MO=0`, `TC=0`, and `worker_safe_closeout.disabled_verified=true`.

Independent post-result UI observations:

- Axis: `MO=0`, `SO=0`, `MF=128`, `SR4=0`, `SR14=1`, `SR15=1`
- the drive-reported enable-limit fault indication was active (`SR8=1`)
- Motion: `MOTOR DISABLED`, `VX=0`, active current `0 A`
- `PX=-2038379934`, unchanged from the pre-test baseline

The operator pressed Escape and requested a stop after these observations.
Computer control was stopped immediately. The last captured application state
was still `ONLINE · SUPERVISED`, but motor-disabled with zero velocity and
zero active current; a normal UI disconnect was therefore not performed by
the automation.

Preserved raw evidence:

- [`commutation-signature-result-20260719T233309+0900.json`](evidence/field-2026-07-19/commutation-signature-result-20260719T233309+0900.json),
  SHA-256 `FB2C935BADDC814C338C58957FB7440DAE00278ED1D9EC41EED1E823FB549434`
- [`commutation-signature-snapshot-20260719T233309+0900.json`](evidence/field-2026-07-19/commutation-signature-snapshot-20260719T233309+0900.json),
  SHA-256 `3D7455F042BB3E420E12311F0F628A43169A4CE8B25CD5AE98BC03B76AC54B06`

Current field verdicts for this bounded attempt:

- procedure and fail-closed abort: `GREEN`
- operator-reported independent protection: `YELLOW` (not independently
  instrumented by the application)
- telemetry and evidence integrity: `GREEN`
- commutation-signature result: `RED`
- final torque/current state: `GREEN`
- normal application disconnect: `NOT COMPLETED` because the user stopped UI
  control

No fault clear, motor re-enable, signature retry, tuning, motion, parameter
Apply/Save, or `SV` is authorized. Before any future energized step, diagnose
the enable-time `VE/ER[2]` path and capture the pre-enable speed command
(`DV[2]`) and velocity error.
