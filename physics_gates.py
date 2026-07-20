"""Motor-agnostic physics gates for tuning validation (P3).

Replaces EAS-gain / FF[1] comparison with physics gates derived from the
connected motor's MotorProfile.  Pure functions only — NO drive I/O, NO file
I/O.  Every threshold is derived in docs/physics-gates-spec.md; the "magic"
field constants (UM3 drag 6.0 A, GUARD 1200 rpm, verify 900 rpm, signature
band 0.50-1.30 A) are all reproduced by these motor-agnostic formulas.

Verdict semantics:
  GREEN      physics plausible + consistent
  YELLOW     boundary / needs field confirmation
  RED        physics violation
  NEED_DATA  cannot evaluate (missing baseline/input) -> run refusal, NOT a fail
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence, Mapping

SQRT2 = math.sqrt(2.0)

# ---- drive-family design-rule constants (TS-bound, motor-agnostic) ----------
# ω_cv = 0.04575/TS is the rated velocity-loop crossover; the cascade separation
# ratio ω_ci/ω_cv >= 3 and the velocity loop's 3-step ×0.8 reduction budget give
# the Phase-1 ω_c·TS band below.  See spec §1.2.
_WCV_TS = 0.04575
_WC_TS_GREEN_LO = 3.0 * _WCV_TS               # 0.13725
_WC_TS_YELLOW_LO = 3.0 * _WCV_TS * (0.8 ** 3)  # 0.070272
_WC_TS_MAX = 0.25                              # Nyquist margin (21.5deg lag)

# ---- gate thresholds --------------------------------------------------------
PM_GREEN_DEG = 45.0
PM_RED_DEG = 40.0

RHO_GREEN = 0.15
RHO_YELLOW = 0.30

KAPPA_R_GREEN = (0.005, 0.35)
KAPPA_R_YELLOW = (0.001, 0.7)
R_ABS_OHM = (1e-3, 10.0)          # phase-to-phase absolute backstop
L_ABS_H = (1e-6, 10e-3)
L_OBSERVABILITY_MIN = 0.2         # ω2·L/R
CTRL_EFFORT_GREEN = 0.6           # KP·CL/Vbus
CTRL_EFFORT_YELLOW = 1.5

SIG_GREEN = (0.5, 1.5)            # × i_ba_ref
SIG_YELLOW_LO = 0.3
SIG_RED_HI = 2.0
SIG_FLOOR_FRAC = 0.02            # × CL[1]  (near-zero-torque)

KA_DROP_RED = 0.5                # × ka_baseline
KA_DROP_YELLOW = 0.7

UM3_FOLLOW = 0.9                 # >= -> follows (bad commutation)
UM3_SLIP = 0.5                   # <= -> slips (healthy)
DRAG_ROUTE_FRAC = 0.25 * SQRT2   # i_cap >= 0.354·CL[1] to route drag discrimination

G1D_GREEN = 0.05
G1D_YELLOW = 0.10

GUARD_RPM_FRAC = 1.0 / 3.0
GUARD_RPM_CLIP = (150.0, 3000.0)
VERIFY_V1_FRAC = 0.10
VERIFY_V2_FRAC = 0.25
# NOTE: spec §4.2-4 said "each <= 0.6·GUARD", but v2 = 0.25·rated and
# GUARD = rated/3 make v2 == 0.75·GUARD by construction, so a 0.6 cap would
# ALWAYS bind and reduce the frozen field verify speed (900 rpm @ GUARD 1200)
# to 720 — contradicting the validated field value.  The cap is only meant as a
# backstop for the clipped-GUARD edge (large motors where rated/3 clips at 3000).
# Use 0.8 so the 0.75 field value passes while the clip edge stays protected.
VERIFY_GUARD_FRAC = 0.8


@dataclass(frozen=True)
class GateVerdict:
    status: str                      # GREEN | YELLOW | RED | NEED_DATA
    code: str
    detail: dict = field(default_factory=dict)
    advisory: bool = False


# ---- helpers ----------------------------------------------------------------
def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _get(profile, name):
    return getattr(profile, name, None) if profile is not None else None


# ---- §1 current loop (Phase 1) ----------------------------------------------
def p1_pm(pm_deg) -> GateVerdict:
    pm = _num(pm_deg)
    if pm is None:
        return GateVerdict("NEED_DATA", "P1_PM", {"pm_deg": pm_deg})
    if pm >= PM_GREEN_DEG:
        st = "GREEN"
    elif pm >= PM_RED_DEG:
        st = "YELLOW"
    else:
        st = "RED"
    return GateVerdict(st, "P1_PM", {"pm_deg": pm, "green_ge": PM_GREEN_DEG, "red_lt": PM_RED_DEG})


def p1_wc_band(wc_rad_s, ts_s) -> GateVerdict:
    wc, ts = _num(wc_rad_s), _num(ts_s)
    if wc is None or ts is None or ts <= 0:
        return GateVerdict("NEED_DATA", "P1_WC_BAND", {"wc_rad_s": wc_rad_s, "ts_s": ts_s})
    wcts = wc * ts
    if wcts > _WC_TS_MAX:
        st = "RED"          # discretization margin blown
    elif wcts >= _WC_TS_GREEN_LO:
        st = "GREEN"
    elif wcts >= _WC_TS_YELLOW_LO:
        st = "YELLOW"       # velocity-loop reduction can recover separation
    else:
        st = "RED"          # cascade separation impossible
    return GateVerdict(st, "P1_WC_BAND", {
        "wc_ts": wcts, "green_lo": _WC_TS_GREEN_LO,
        "yellow_lo": _WC_TS_YELLOW_LO, "max": _WC_TS_MAX})


def p1_rho(rows: Sequence[Mapping]) -> GateVerdict:
    devs = []
    for r in rows or ():
        meas, pred = _num(r.get("rho_meas")), _num(r.get("rho_pred"))
        if meas is None or pred is None or pred == 0:
            continue
        devs.append(abs(meas / pred - 1.0))
    if not devs:
        return GateVerdict("NEED_DATA", "P1_RHO", {"n_rows": len(rows or ())})
    m = max(devs)
    if m <= RHO_GREEN:
        st = "GREEN"
    elif m <= RHO_YELLOW:
        st = "YELLOW"
    else:
        st = "RED"
    return GateVerdict(st, "P1_RHO", {"max_dev": m, "green_le": RHO_GREEN, "yellow_le": RHO_YELLOW})


def p1_r_relative(r_pp_ohm, cl1_a, vbus_v) -> GateVerdict:
    r, cl, vb = _num(r_pp_ohm), _num(cl1_a), _num(vbus_v)
    if r is None or cl is None or vb is None or vb <= 0:
        return GateVerdict("NEED_DATA", "P1_R_REL", {"r_pp_ohm": r_pp_ohm, "cl1_a": cl1_a, "vbus_v": vbus_v})
    if not (R_ABS_OHM[0] <= r <= R_ABS_OHM[1]):
        return GateVerdict("RED", "P1_R_REL", {"r_pp_ohm": r, "abs_backstop_ohm": R_ABS_OHM})
    kappa = r * cl / vb
    if KAPPA_R_GREEN[0] <= kappa <= KAPPA_R_GREEN[1]:
        st = "GREEN"
    elif KAPPA_R_YELLOW[0] <= kappa <= KAPPA_R_YELLOW[1]:
        st = "YELLOW"
    else:
        st = "RED"
    return GateVerdict(st, "P1_R_REL", {"kappa_r": kappa, "green": KAPPA_R_GREEN, "yellow": KAPPA_R_YELLOW})


def p1_l_relative(l_pp_h, r_pp_ohm, wc_rad_s, f2_hz, cl1_a, vbus_v) -> GateVerdict:
    l, r, wc, f2, cl, vb = (_num(l_pp_h), _num(r_pp_ohm), _num(wc_rad_s),
                            _num(f2_hz), _num(cl1_a), _num(vbus_v))
    if None in (l, r, wc, f2, cl, vb) or r <= 0 or vb <= 0:
        return GateVerdict("NEED_DATA", "P1_L_REL",
                           {"l_pp_h": l_pp_h, "r_pp_ohm": r_pp_ohm, "wc_rad_s": wc_rad_s,
                            "f2_hz": f2_hz, "cl1_a": cl1_a, "vbus_v": vbus_v})
    if not (L_ABS_H[0] <= l <= L_ABS_H[1]):
        return GateVerdict("RED", "P1_L_REL", {"l_pp_h": l, "abs_backstop_h": L_ABS_H})
    observ = (2.0 * math.pi * f2) * l / r          # ω2·L/R
    effort = wc * l * cl / vb                       # KP·CL/Vbus
    detail = {"observability": observ, "observ_min": L_OBSERVABILITY_MIN,
              "ctrl_effort": effort, "effort_green_le": CTRL_EFFORT_GREEN,
              "effort_yellow_le": CTRL_EFFORT_YELLOW}
    if effort > CTRL_EFFORT_YELLOW:
        st = "RED"
    elif effort > CTRL_EFFORT_GREEN or observ < L_OBSERVABILITY_MIN:
        st = "YELLOW"
    else:
        st = "GREEN"
    return GateVerdict(st, "P1_L_REL", detail)


# ---- §2 signature gate (commutation health) --------------------------------
def sig_band(i_ba_a, profile) -> GateVerdict:
    iba = _num(i_ba_a)
    band = _get(profile, "signature_band") or {}
    ref = _num(band.get("i_ba_ref_a")) if isinstance(band, Mapping) else None
    cl = _num(_get(profile, "cont_current_a"))
    if iba is None:
        return GateVerdict("NEED_DATA", "SIG_BAND", {"i_ba_a": i_ba_a})
    # absolute floor first (baseline-independent backstop)
    if cl is not None and iba < SIG_FLOOR_FRAC * cl:
        return GateVerdict("YELLOW", "SIG_BAND",
                           {"i_ba_a": iba, "floor_a": SIG_FLOOR_FRAC * cl,
                            "note": "near-zero-torque move"})
    if ref is None or ref <= 0:
        return GateVerdict("NEED_DATA", "SIG_BAND",
                           {"i_ba_a": iba, "note": "no baseline -> first-run path"})
    ratio = iba / ref
    if SIG_GREEN[0] <= ratio <= SIG_GREEN[1]:
        st = "GREEN"
    elif SIG_YELLOW_LO <= ratio < SIG_GREEN[0] or SIG_GREEN[1] < ratio <= SIG_RED_HI:
        st = "YELLOW"
    else:
        st = "RED"
    return GateVerdict(st, "SIG_BAND",
                       {"i_ba_a": iba, "i_ba_ref_a": ref, "ratio": ratio,
                        "green": SIG_GREEN, "yellow_lo": SIG_YELLOW_LO, "red_hi": SIG_RED_HI})


def sig_first_run(direction_ok, um3_follow_ratio, ka_ok) -> GateVerdict:
    fr = _num(um3_follow_ratio)
    if fr is None:
        return GateVerdict("NEED_DATA", "SIG_FIRST", {"um3_follow_ratio": um3_follow_ratio})
    if not direction_ok:
        return GateVerdict("RED", "SIG_FIRST", {"direction_ok": False})
    if fr >= UM3_FOLLOW:
        return GateVerdict("RED", "SIG_FIRST",
                           {"follow_ratio": fr, "note": "UM3 follows i_ba/sqrt2 -> delta>=45deg"})
    if fr > UM3_SLIP:
        return GateVerdict("YELLOW", "SIG_FIRST",
                           {"follow_ratio": fr, "note": "indeterminate (backlash contamination possible)"})
    # slips -> healthy commutation; provisional GREEN also needs ka_ok
    st = "GREEN" if ka_ok else "YELLOW"
    return GateVerdict(st, "SIG_FIRST", {"follow_ratio": fr, "ka_ok": bool(ka_ok), "slip": True})


def ka_drop(k_a, profile) -> GateVerdict:
    ka = _num(k_a)
    base = _num(_get(profile, "ka_baseline"))
    if ka is None:
        return GateVerdict("NEED_DATA", "KA_DROP", {"k_a": k_a})
    if base is None or base <= 0:
        return GateVerdict("NEED_DATA", "KA_DROP", {"k_a": ka, "note": "no ka_baseline"})
    frac = ka / base
    if frac < KA_DROP_RED:
        st = "RED"
    elif frac < KA_DROP_YELLOW:
        st = "YELLOW"
    else:
        st = "GREEN"
    return GateVerdict(st, "KA_DROP",
                       {"k_a": ka, "ka_baseline": base, "frac": frac,
                        "red_lt": KA_DROP_RED, "yellow_lt": KA_DROP_YELLOW})


# ---- §3 UM3 drag current derivation ----------------------------------------
def derive_drag_current(cl1_a, i_cap_a=None, i_ba_meas_a=None) -> tuple:
    """Return (I_drag_a, detail).  Cap-out mode: i_cap/sqrt2.  First-run
    expect-slip mode: i_ba_meas/sqrt2.  Both give the 45deg discrimination angle.
    """
    cl = _num(cl1_a)
    icap = _num(i_cap_a)
    iba = _num(i_ba_meas_a)
    src = None
    base = None
    if icap is not None:
        base, src = icap, "i_cap"
    elif iba is not None:
        base, src = iba, "i_ba_meas"
    if base is None:
        return None, {"note": "no i_cap or i_ba_meas", "cl1_a": cl}
    i_drag = base / SQRT2
    detail = {"source": src, "base_a": base, "i_drag_a": i_drag,
              "discrimination_deg": 45.0}
    if cl is not None:
        detail["route_floor_a"] = DRAG_ROUTE_FRAC * cl
        detail["route_ok"] = (icap is None) or (icap >= DRAG_ROUTE_FRAC * cl)
    return i_drag, detail


# ---- §4 Phase 2 (velocity/position) ----------------------------------------
def p2_g1d(dev) -> GateVerdict:
    d = _num(dev)
    if d is None:
        return GateVerdict("NEED_DATA", "P2_G1D", {"dev": dev})
    ad = abs(d)
    if ad <= G1D_GREEN:
        st = "GREEN"
    elif ad <= G1D_YELLOW:
        st = "YELLOW"
    else:
        st = "RED"
    return GateVerdict(st, "P2_G1D", {"dev": d, "green_le": G1D_GREEN, "yellow_le": G1D_YELLOW})


def derive_guard_rpm(profile) -> Optional[float]:
    rated = _num(_get(profile, "effective_rated_rpm"))
    if rated is None:
        return None
    return min(max(rated * GUARD_RPM_FRAC, GUARD_RPM_CLIP[0]), GUARD_RPM_CLIP[1])


def derive_verify_speeds(profile, guard_rpm=None) -> Optional[tuple]:
    rated = _num(_get(profile, "effective_rated_rpm"))
    if rated is None:
        return None
    g = _num(guard_rpm) if guard_rpm is not None else derive_guard_rpm(profile)
    v1 = rated * VERIFY_V1_FRAC
    v2 = rated * VERIFY_V2_FRAC
    if g is not None:
        cap = VERIFY_GUARD_FRAC * g
        v1, v2 = min(v1, cap), min(v2, cap)
    return (v1, v2)


# ---- §5 EAS comparison -> advisory only ------------------------------------
def advisory_eas(drive_readings: Mapping, results: Mapping) -> dict:
    """Reference-only deviation of computed gains vs the drive's residual gains.
    NEVER fed into combine().  Untrusted for non-EAS-tuned motors.
    """
    out = {"label": "reference (non-gating) vs drive residual gains; "
                     "untrusted for non-EAS-tuned motors", "deviations": {}}
    dr = drive_readings or {}
    rs = results or {}
    for key, res_key in (("KP[1]", "kp_cur"), ("KI[1]", "ki_cur"),
                         ("KP[2]", "kp_vel"), ("KI[2]", "ki_vel_hz"), ("KP[3]", "kp_pos")):
        drv, comp = _num(dr.get(key)), _num(rs.get(res_key))
        if drv is not None and comp is not None and drv != 0:
            out["deviations"][key] = comp / drv - 1.0
    return out


# ---- combine ----------------------------------------------------------------
def combine(verdicts: Sequence[GateVerdict]) -> str:
    """Worst-of over non-advisory verdicts.  Precedence RED > NEED_DATA >
    YELLOW > GREEN: a physics violation dominates; missing data refuses the run
    but is not itself a failure.
    """
    order = {"GREEN": 0, "YELLOW": 1, "NEED_DATA": 2, "RED": 3}
    worst = "GREEN"
    for v in verdicts or ():
        if v is None or getattr(v, "advisory", False):
            continue
        if order.get(v.status, 0) > order[worst]:
            worst = v.status
    return worst
