# Field evidence · 2026-07-19

This directory preserves the exact application-generated artifacts from the
single supervised standalone commutation-signature attempt at 23:33 KST.

## Identity and approved envelope

- repository revision at execution: `f03453aead75d8cb098e4fc91f6f98feeb7ea322`
- branch: `codex/quick-single-axis-handoff`
- target: Gold Twitter, firmware
  `Twitter 01.01.16.00 08Mar2020B01G`, PAL 90
- communication: Direct Access USB, COM3
- operator-reported DC-link: `48 V`
- operator-reported supply current limit: `5 A`
- approved command envelope: standalone `+TC 0 -> at most 1.30 A`,
  at most `2.0 s`

## Exact artifacts

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `commutation-signature-result-20260719T233309+0900.json` | 10,732 | `FB2C935BADDC814C338C58957FB7440DAE00278ED1D9EC41EED1E823FB549434` |
| `commutation-signature-snapshot-20260719T233309+0900.json` | 907 | `3D7455F042BB3E420E12311F0F628A43169A4CE8B25CD5AE98BC03B76AC54B06` |

The tracked files are byte-identical copies of the ignored runtime files:

- `.omc/state/autotune_vp_result_1784471589991.json`
- `.omc/state/autotune_vp_snapshot_1784471589505.json`

## Outcome

- result: `RED`
- reason: motor fault `MF=0x80`
- no breakaway/signature measurement was produced
- temporary limits restored with matching forward/reverse readbacks
- final artifact state: `MO=0`, `TC=0`, restore `pass=true`
- independent UI observation: motor disabled, velocity 0, active current 0 A,
  position unchanged

`MF=0x80` maps to a speed-tracking error in the Gold Line command reference.
No automatic retry or fault clear was performed.
