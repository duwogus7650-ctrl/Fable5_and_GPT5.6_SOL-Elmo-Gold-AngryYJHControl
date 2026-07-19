# Single Axis SR live diagnostic · 2026-07-19

## Scope and authority

This note records a bounded read-only diagnostic on the current Gold Twitter
target. It does not authorize or prove motor enable, energization, motion,
tuning, parameter assignment, persistence, STO performance, or independent
E-stop operation.

- repository base before this correction:
  `4afdbf34b41488e7bf5c0bba82aad3495f6bea36`
- branch: `codex/quick-single-axis-handoff`
- host time: 2026-07-19 KST
- application: Python 3.14 `AngryYJH Control`
- connection: `Direct Access USB`, `COM3`, `ONLINE · READ ONLY`
- firmware: `Twitter 01.01.16.00 08Mar2020B01G`
- PAL: `90`
- boot: `DSP Boot 1.0.1.6 12Feb2014G`
- application target class: `Gold Drive`
- observed motor state: `MOTOR DISABLED`

No `MO=1`, assignment, `BG`, `TC=`, tuning, write, Apply, `SV`, or motion
command was issued in this diagnostic.

## Trigger

The first current-revision 28-query Position/Velocity refresh failed closed
with:

```text
SR safety/motion state changed during acquisition
```

That build discarded the raw `SR_PRE/SR_POST` pair when returning `UNKNOWN`.
Therefore the exact bit that changed in that first acquisition is
`UNVERIFIED`; it must not be retroactively claimed as bit 23 or any safety
bit.

The decoder was changed to keep fail-closed behavior while including:

```text
SR_PRE=0x........; SR_POST=0x........; changed bits=...
```

The labels distinguish bit 23 `movement/standstill` from bit 27
`STO diagnostics error`. No stability bit was removed from the mask.

## Installed source reconciliation

Installed source:

```text
C:\Program Files\Elmo Motion Control\Elmo Application Studio III\
NetHelp\Content\Gold Line Command Reference\SR Status Register.htm
SHA-256 7DA74A9E02133827EF962D73673FC34FF7F5B25259AFD38C459A07F8681BE1AF
```

The installed page defines, among the earlier SR fields:

| Bit | Installed-page role |
|---:|---|
| 21 | shunt indication |
| 22 | Motor On (`MO`) |
| 23 | movement/standstill indication |
| 24..26 | Hall A/B/C |
| 27 | STO diagnostics error; cleared only at power-up |
| 28 | profiler stopped due to a switch |
| 30 | PTP buffer full |

The local firmware release notes separately describe bit 23 as a speed-zero
indication and mention a motor-off correction. Because the installed page and
the older target firmware do not provide one unambiguous cross-version
Boolean naming contract, the application uses the neutral label
`movement/standstill indication` and keeps its interpretation source-bound.
It does not infer physical movement from bit 23 alone.

Bit 27 is not neutralized: when set, it is projected as an STO diagnostics
error and the Enable projection becomes
`FAULT REPORTED - NO AUTO-RETRY`.

## Live observations

### Position / Velocity

After restarting the application with exact-change diagnostics, one explicit
28-query read-only refresh completed in **59.1 ms**.

| Item | Observed |
|---|---:|
| state | `CURRENT · DRIVE READ ONLY` |
| motor/mode | `DISABLED REPORTED · UM=5 Position` |
| `PA[1]`, `PR[1]`, `JV` | `0`, `0`, `0` |
| `SP[1]` | `4,444,444 cnt/s` |
| `AC[1]`, `DC`, `SD` | `1,000,000 cnt/s²` each |
| `PX` | `-2,038,379,934 cnt` |
| `PU` | `-2,004,825,502 user units` |
| `PU-PX` | `+33,554,432 = 2^25` |
| `XM[1]`, `XM[2]` | `0`, `0` |
| `FC[1,2,5,6,7,8]` | all `1` |
| `CA[45]` | `1` |
| `VX` | `0 cnt/s` |

The coordinate result remains `DIVERGED / NEED-DATA`; the delta is not used
as an automatic correction.

### Current readback and EAS-shaped local drafts

One explicit 16-query read-only refresh completed in **37.4 ms**.

| Item | Observed |
|---|---:|
| `TC`, `IQ`, `ID` | `0.0000 A` each |
| `CL[1]` | `21.2132 A` |
| `PL[1]` | `70.7107 A` |
| `LC` | `0 · OFF` |
| `MC` | `140.0000 A` |

`CL[1] <= PL[1] <= MC` passed. All five EAS-shaped Current drafts remained
`0 A`, were labeled `WITHIN OBSERVED LIMITS`, and all five
`Set TC · LOCKED` buttons remained disabled with no drive I/O route.

### Axis status

The running pre-fix status projection displayed:

```text
SR has reserved bits set: 0x00800000
```

This directly identifies live bit 23 as set in the admitted Axis Summary and
proves that the old `_SR_DEFINED_MASK` was stale for this installed source and
target observation. It does **not** identify the bit that changed in the
earlier failed 28-query acquisition.

The correction:

- admits installed documented bits 21, 22, 23, 27, and 30;
- cross-checks `MO` against SR22, in addition to `SO/SR4` and `PS/SR12`;
- preserves bit 23 as a source-bound indication rather than a motion verdict;
- treats SR27 as an Enable-blocking fault;
- keeps reserved/unknown bits fail-closed.

## Offline EAS functional comparison

After the bounded live reads, both applications were disconnected and compared
without further drive I/O:

- EAS exposed `Connect` and disabled `Disconnect`, confirming its disconnected
  state, but its Single Axis Position and Current pages retained the prior or
  project values: AC/DC/StopDec `1000000`, Speed `4444444`, five Current
  Commands at `0`, and the terminal's prior `PX=-2038379934`.
- AngryYJH was restarted from the current source in `OFFLINE` state. It showed
  `MOTOR STATE UNKNOWN`, `UNKNOWN-ENABLE LOCKED`, disabled both bounded refresh
  paths, and kept all five `Set TC` controls disabled.
- The retained EAS values therefore are not fresh live evidence. AngryYJH
  intentionally separates value/shape parity from freshness authority and
  blanks live authority when disconnected.

This is an intentional fail-closed semantic difference, not a claim of missing
EAS visual parity.

## Verdict

- `OBSERVED`: current target exposes SR bit 23 and the old status decoder
  falsely rejected it as reserved.
- `OBSERVED`: current-revision Position/Velocity and Current bounded reads
  completed while the drive reported disabled and zero velocity/current.
- `UNVERIFIED`: the exact bit transition that caused the first 28-query
  failure.
- `NEED-DATA`: physical meaning of the persistent `PU-PX=2^25` origin and
  cross-version bit-23 polarity semantics.
- `NO-GO`: using any of this software evidence as proof of STO/E-stop,
  torque isolation, safe motion, or Gold-family compatibility.

## Software verification

- SR/PX-PU/Current + safety/catalog affected scope: `504 passed`.
- Single Axis Qt integration: `56 passed in 118.13s`.
- full repository: `1964 passed in 636.67s`, exit 0.
- full output contained no skip/xfail summary.
