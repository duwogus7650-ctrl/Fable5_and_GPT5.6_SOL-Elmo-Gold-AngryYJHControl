# Single Axis Enable / Disable contract v0.1

## Scope

This slice adds a zero-new-I/O projection of the Single Axis enable lifecycle.
It reuses the existing admitted `MO/SO/MF/PS/SR/MS` Axis Summary snapshot.

Implemented:

- distinct drive-reported states for `MO/SO = 0/0`, `1/0`, `1/1`, and
  `0/1`
- fault precedence from `MF`, the SR amplifier code, and SR bit 6
- a permanently disabled `Enable - LOCKED / NEED-DATA (MO=1)` control
- an explicit pointer to the existing `drive.stop` escape path:
  `ST -> MO=0 -> terminal readback`
- fail-closed reset on missing, stale, inconsistent, disconnected, late, or
  structurally forged evidence

Not implemented:

- an `MO=1` worker job, handler, dispatch path, or transport request
- automatic enable retry
- reference commands while `SO=0`
- independent STO/E-stop testing or torque-isolation proof
- a commissioned current/energy envelope, operator gate, telemetry abort
  envelope, or field closeout for standalone Enable

## Installed Gold source identities

1. `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\Gold Line Command Reference\MO SO Motor On Servo On.htm`
   - SHA-256:
     `363632520E982C5B42BAF683ECCDBAA1E59623DC4EEE512B7291DA611C671E37`
2. `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\Gold Line Command Reference\SO Servo Enabled.htm`
   - SHA-256:
     `02B70DB68865AA92534E41F3B77976F3E228E39B63EA19F4F28E756F563EA931`
3. `C:\Program Files\Elmo Motion Control\Elmo Application Studio III\NetHelp\Content\Gold Line Command Reference\SR Status Register.htm`
   - SHA-256:
     `7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF`

`OBSERVED` from the installed documentation:

- `MO` is Long R/W, range `0/1`, default `0`, and non-volatile `No`.
- `MO=1` is the operative state and can drive the motor.
- the `MO=1` interpreter call returns before the servo is necessarily ready.
- the application must wait until `SO=1` before a profiler/reference can
  command motion.
- commutation search or brake release can leave `MO=1, SO=0` for a bounded
  or configuration-dependent time.
- `MO=0` disables the power stage, but a configured brake can temporarily
  leave `MO=0, SO=1` while the brake is applied.
- a captured motor fault disables the servo; automatically retrying enable is
  not justified while the fault condition remains.
- mixing interpreter `MO` control with the DS-402 state machine is not
  recommended.

## Projection states

| Raw admitted evidence | UI state | Meaning and boundary |
|---|---|---|
| invalid, stale, missing, inconsistent, or forged | `UNKNOWN - ENABLE LOCKED` | no current state authority |
| fault evidence present | `FAULT REPORTED - NO AUTO-RETRY` | use STOP/Disable and inspect `MF/CD/EE`; no automatic retry |
| `MO=0, SO=0` | `DISABLED REPORTED - ENABLE LOCKED` | drive-reported idle only; not independent torque isolation |
| `MO=1, SO=0` | `ENABLE REQUESTED - SO=0 / REFERENCES BLOCKED` | enable completion is pending; references remain blocked |
| `MO=1, SO=1` | `ENABLED REPORTED - ENERGIZED` | drive reports servo ready; STOP remains available |
| `MO=0, SO=1` | `DISABLING / BRAKE HOLD - SO=1` | documented brake-application state; closeout not yet verified |

Fault evidence takes precedence over the four normal `MO/SO` combinations.

## Operation boundaries

- `motor.enable`
  - risk: `ENERGIZING`
  - status: `NEED_DATA`
  - UI: visible but disabled
  - executable dispatch: none
- `drive.stop`
  - risk: `SAFETY_STOP`
  - status: existing implemented escape path
  - sequence: `ST -> MO=0 -> terminal readback`
  - boundary: software STOP is not independent STO/E-stop

## Acceptance gates

- pure state projection has deterministic truth, boundary, negative, and
  forged-evidence tests
- UI issues no worker call and never enables the `motor.enable` control
- stale/disconnected/late evidence resets the state to `UNKNOWN`
- the existing STOP control remains available on a connected transport
- the three skins fit at 1366x820 with no horizontal workspace scroll
- no live `MO=1`, reference, motion, or setting write occurs in this slice

Field verdict remains `NEED-DATA`.

## Verification closeout — 2026-07-19 KST

`OBSERVED` local evidence:

- pure contract + operation catalog: `47 passed`
- affected safety/UI/shutdown/motion regression:
  `450 passed in 274.33s`, numeric exit `0`
- full repository:
  `1741 passed in 1613.99s (0:26:53)`, numeric exit `0`
- Python compile checks: exit `0`
- `git diff --check`: exit `0` with line-ending warnings only
- installed source identity: `3/3` SHA-256 matches
- three-skin 1366x820 layout: no horizontal workspace scroll; contract and
  detail labels are not clipped
- added diff contains no worker job, `command(...)`, or executable `MO=1`
  path; the only added `MO=1` occurrences are locked labels/tooltips/docs

`OBSERVED` current-target read-only runtime after launching the changed source:

- connection: `COM3`, `ONLINE - READ ONLY`
- displayed motor state: `MOTOR DISABLED`
- displayed velocity/current: `0 / 0`
- admitted Axis Summary state: `MO=0, SO=0`
- enable panel: `DISABLED REPORTED - ENABLE LOCKED`
- `Enable - LOCKED / NEED-DATA (MO=1)`: disabled
- no Enable click, `MO=1`, reference, motion, parameter write, or persistence
  action was executed

This read-only observation does not validate independent STO/E-stop response,
torque isolation, brake timing, fault recovery, or standalone Enable.
