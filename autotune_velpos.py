"""Phase 2 autotune — commutation verification + velocity/position loops.

SPEC: docs/autotune-velpos-spec.md (fable-physics 2026-07-13).  Architecture
(_Ctx / snapshot I1 / abort chain / _resolve_signals / RED-never-raise /
sleep_fn·progress_fn·cancel_fn injection) is carried over from Phase 1
(autotune_current.py — untouched).  Transport = elmo_link.ElmoLink command()
+ record_start()/record_fetch() (the split lets us keep sending TC/JV and
polling VX/MF/LC while the recorder free-runs).

Method (SPEC §0..§3):
  - K_a = dv/dt per ampere = Kt*CA[18]/(2*pi*J_tot) [cnt/s^2/A] — identified
    open-loop (UM=5 torque mode) with a +/- torque pulse pair; matched
    same-speed windows cancel friction exactly:
        K_a = (a_plus - a_minus) / (I_plus + |I_minus|)
    (window slopes by least squares — never point differences; the recorded
    ACTUAL current is the denominator).
  - Global regression  a(t) = K_a*I - D*v - C*sgn(v)  cross-checks K_a and
    yields B = D/K_a, I_c = C/K_a (gate G1a); position second-order fits and
    the integral(v)dt-vs-dPos identity guard the time base (G1c/G1d).
  - Friction (final): closed-loop JV steady states at +-300/+-900 rpm,
    I_ss = B*v + I_c*sgn(v) per-direction fit (method B; doubles as the
    rotating commutation check §1-2).
  - Gains (EAS single-point reverse engineering, honesty note in SPEC §3):
        wcv   = 0.04575 / TS_s        (calibration; Phase-1 0.2010 sibling)
        KP[2] = wcv / K_a_meas        (the ONLY measurement-dependent gain)
        KI[2] = wcv / (2*pi*6.805)    (TS=100us -> 10.700 Hz, deterministic)
        KP[3] = wcv / 5.369           (TS=100us -> 85.20,     deterministic)
        FF[1]_advisory = 1/K_a_meas   (report only — NEVER written)
  - Margin gate G4 (numeric, probe-verified model): L_v = C_v*H_ci*P_m*
    e^(-1.5*TS*s) with H_ci from the CURRENT drive KP[1]/KI[1] + R_pp/L_pp,
    P_m = K_a/(s+D); L_p = KP[3]*T_v/s.  At the EAS gains + K_a* this model
    reproduces vel 73.9 Hz / PM 67.7 / GM 15.0 dB and pos 15 Hz / PM 81.7
    (T4).  Gate: PM_v>=50, GM>=8 dB, wcv*TS<=0.07, PM_p>=70, w_ci/w_cv>=3,
    w_cv/KP[3]>=4; PM shortfall -> wcv*0.8 up to 3x (beta/delta kept).

Safety (SPEC §4): default limits are NOT trusted — SD/HL[2]/LL[2]/ER[2] are
set (write+readback, refusal -> warnings) and restored; SW guard polls VX
every 30 ms against a 1200 rpm ceiling; segment timebox 5 s / total 120 s;
abort chains are segment-specific (TC: TC=0 -> MO=0 coast; JV: JV=0 -> ST ->
wait |VX|<30 rpm -> MO=0) and NEVER rely on ST alone (U-P6).  Motion commands
(MO=1/TC/JV/ST) go out with allow_motion=True only — the caller must have
passed the operator gate (free rotation / load detached / expected revs).

Judgment note (probe-grounded deviation from the SPEC-B1 letter): the probe
K_a uses the on/off TWO-slope difference  K_a = (a_on - a_off)/I  from the
same recording (same +- cancellation principle).  The literal a_on/I is
friction-biased low by (B*v+I_c)/I — with the T3 truth values (I_c=0.2 A vs
probe 0.25 A) it underestimates K_a 5x, oversizes Tp to the 0.3 s clip and
drives the main pulse through the 1200 rpm guard.  The two-slope probe sizes
Tp correctly (~0.07 s, ~725 rpm peak).

Hardware-pending (SPEC §8 — honest, never guessed): U-P1 FF[1]=1/K_a (A1,
checked +-30% as gate G3), U-P2 vel-PI zero=2*pi*KI (F2), U-P3 KP[3] unit
(F2), U-P4 HL[2]/LL[2] writability (readback; SW guard covers refusal),
U-P5 record dt (absorbed by G1d), U-P6 ST behavior in UM=5 TC mode (aborts
do not depend on it), U-P7 velocity-channel internal filter (slope-invariant;
F2 final say).  F1 apply / F2 verification run are separate operator actions
(F2 = honest stub, Phase-1 E4 pattern).

All failures return a RED result (never raise) after the segment-appropriate
abort chain whenever the drive state was touched.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np

__all__ = ["AutotuneVPParams", "AutotuneVPResult", "run_velpos_autotune",
           "apply_gains_vp", "verify_run_vp", "vel_pos_margins",
           "design_vp_gains", "window_slope", "GREEN", "YELLOW", "RED"]

GREEN, YELLOW, RED = "GREEN", "YELLOW", "RED"

# --- calibration constants (SPEC §3 — single-point, this drive; honesty note) ---------
WCV_TS_CAL = 0.04575      # wcv*TS (EAS reverse-engineered; Phase-1 0.2010 sibling)
BETA_VEL = 6.805          # wcv / (2*pi*KI[2])
DELTA_POS = 5.369         # wcv / KP[3]
VEL_DELAY_MULT = 1.5      # extra vel-loop delay (probe-locked: 73.9Hz/PM67.7/GM15.0)
CUR_DELAY_MULT = 1.5      # Phase-1 current-loop delay model

# --- gate thresholds (SPEC §3/§5) ------------------------------------------------------
PM_VEL_MIN = 50.0
GM_MIN_DB = 8.0
WCV_TS_MAX = 0.07
PM_POS_MIN = 70.0
RATIO_CI_CV_MIN = 3.0
RATIO_CV_KP3_MIN = 4.0
MAX_WCV_REDUCTIONS = 3
KA_RANGE = (3e5, 3e8)     # G2 physicality [cnt/s^2/A]
FRICTION_RATIO_MAX = 0.5  # G2: (B*v_peak + I_c)/I0
G1A_TOL, G1B_TOL, G1C_TOL, G1D_TOL, G1F_TOL = 0.15, 0.10, 0.10, 0.05, 0.30
G1E_R2_MIN = 0.98
G3_KA_TOL, G3_KP2_TOL, G3_CFG_TOL = 0.30, 0.30, 0.02

# --- B1.5 UNIT-DIAG (SPEC §9 — hard gate BEFORE the main pulses) ------------------------
UNITDIAG_I_A = 0.5        # diagnostic pulse current [A] (K_a 3x high -> 636rpm < 1200)
UNITDIAG_T_S = 0.08       # host-timed pulse duration (dt discriminant reference)
UNITDIAG_REC_S = 0.4      # TR=1 recording (dt = TS, the Phase-1-verified base)
UNITDIAG_MIN_DPOS = 200.0 # cnt: |dPos| below this = PHYSICS anomaly branch (units
                          # fine — Position is the ground-truth channel, PX-adjacent)
UNITDIAG_S_TOL = 0.05     # hard gate: |s-1| after correction
UNITDIAG_G_TOL = 0.10     # hard gate: |g-1| after correction
UNITDIAG_KA_TOL = 0.10    # hard gate: Position-fit accel vs corrected velocity slope
PULSE_BAND = (0.30, 0.70) # §9: matched windows at [30%,70%] of the MEASURED v_pk
MOTION_MIN_RPM = 30.0     # v_pk below this -> 모션부족 (adaptive I0 x2 once <=0.4*CL[1])

# --- safety / timing (SPEC §2.5/§4) ----------------------------------------------------
PROBE_T_S = 0.05          # B1 probe pulse
PRE_ROLL_S = 0.05         # quiet pre-roll in each recording
TP_MIN_S, TP_MAX_S = 0.05, 0.30
GUARD_PERIOD_S = 0.03     # MF/LC/VX poll while MO=1
GUARD_RPM = 1200.0        # |VX| ceiling (cnt/s via CA[18])
SEG_TIMEBOX_S = 5.0
TOTAL_BUDGET_S = 120.0
JV_SETTLE_S = 0.8
JV_RECORD_S = 0.5
JV_STOP_RPM = 30.0
JV_STOP_TIMEOUT_S = 2.0
DECEL_TAIL_S = 0.25       # post-pulse coast captured for the regression
# explicit limit set (SPEC §4 — default limits are not trusted)
LIMIT_WRITES = (("SD", 4e6), ("HL[2]", 1.97e6), ("LL[2]", -1.97e6),
                ("ER[2]", 3.3e5))


# ======================================================================================
# dataclasses
# ======================================================================================
def _noop_progress(code: str, detail: str) -> None:
    """Default progress hook: do nothing."""


def _never_cancel() -> bool:
    return False


@dataclass
class AutotuneVPParams:
    probe_i_a: float = 0.25             # B1 probe current [A amplitude]
    i_pulse_frac: float = 0.10          # I0 = frac*CL[1] (hard cap 0.2*CL[1])
    tp_target_rpm: float = 800.0        # Tp sizing target speed
    jv_speeds_rpm: Sequence[float] = (300.0, 900.0)
    rec_dt_s: float = 400e-6            # recorder sample time (tres = rec_dt/TS)
    wcv_override_hz: Optional[float] = None
    expected_ca17: int = 5              # commutation config guard (G0)
    expected_ca7: Optional[float] = 438.0   # None = skip the CA[7] value check
    # --- injection points (headless tests replace sleep_fn with the sim clock) -------
    sleep_fn: Callable[[float], None] = time.sleep
    snapshot_dir: str = os.path.join(".omc", "state")
    poll_s: float = 0.01
    progress_fn: Callable[[str, str], None] = _noop_progress
    cancel_fn: Callable[[], bool] = _never_cancel
    # H_ci model inputs for the G4 margin gate (live-confirmed Phase-1 values)
    r_pp_ohm: float = 0.139
    l_pp_h: float = 41.6e-6


@dataclass
class AutotuneVPResult:
    status: str
    reason: str = ""
    kp_vel: Optional[float] = None          # KP[2] [A/(cnt/s)]
    ki_vel_hz: Optional[float] = None       # KI[2] [Hz]
    kp_pos: Optional[float] = None          # KP[3] [1/s]
    ff1_advisory: Optional[float] = None    # 1/K_a — report only, never written
    k_a: Optional[float] = None             # [cnt/s^2/A]
    b_visc: Optional[float] = None          # [A/(cnt/s)]
    i_c: Optional[float] = None             # [A]
    d_inv_s: Optional[float] = None         # D = K_a*B [1/s]
    wcv_rad_s: Optional[float] = None
    pm_vel_deg: Optional[float] = None
    gm_db: Optional[float] = None
    pm_pos_deg: Optional[float] = None
    ts_us: Optional[int] = None
    evidence: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class PreflightError(Exception):
    """Failure BEFORE any drive write: RED without the abort chain."""


class AbortError(Exception):
    """Failure after drive state may have been touched: run the abort chain."""


# ======================================================================================
# pure analysis helpers (unit-testable without a link)
# ======================================================================================
def _to_num(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return s
    t = str(s).strip().rstrip(";").strip()
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def window_slope(t: np.ndarray, y: np.ndarray):
    """Least-squares line fit -> (slope, intercept, R^2).  SPEC §2.2: window
    slopes only — point differences are forbidden (quantization noise)."""
    t = np.asarray(t, float)
    y = np.asarray(y, float)
    n = len(t)
    if n < 3:
        return 0.0, float(y.mean()) if n else 0.0, 0.0
    tm, ym = t.mean(), y.mean()
    stt = float(np.sum((t - tm) ** 2))
    if stt <= 0:
        return 0.0, ym, 0.0
    slope = float(np.sum((t - tm) * (y - ym)) / stt)
    resid = y - (ym + slope * (t - tm))
    ss_tot = float(np.sum((y - ym) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else 1.0
    return slope, float(ym - slope * tm), r2


def _margins_of(G: np.ndarray, w: np.ndarray):
    """(crossover rad/s, PM deg, GM dB or None) from a complex response grid."""
    mag = np.abs(G)
    ph = np.unwrap(np.angle(G))
    ic = int(np.argmin(np.abs(mag - 1.0)))
    pm = 180.0 + math.degrees(ph[ic])
    gm = None
    tgt = -math.pi
    for i in range(len(w) - 1):
        if (ph[i] - tgt) * (ph[i + 1] - tgt) <= 0 and ph[i] != ph[i + 1]:
            tt = (tgt - ph[i]) / (ph[i + 1] - ph[i])
            m = mag[i] + tt * (mag[i + 1] - mag[i])
            if m > 0:
                gm = -20.0 * math.log10(m)
            break
    return float(w[ic]), float(pm), gm


def vel_pos_margins(kp2: float, ki2_hz: float, kp3: float, k_a: float,
                    d_visc: float, kp1: float, ki1_hz: float,
                    r_pp: float, l_pp: float, ts_s: float) -> dict:
    """Numeric margins of the FULL velocity/position loops (SPEC §3 model,
    probe-locked: EAS gains + K_a* -> vel 73.9 Hz PM 67.7 GM 15.0 dB, pos
    15 Hz PM 81.7):
      H_ci = G_i/(1+G_i),  G_i = KP1(s+2piKI1)/s * 1/(L s+R) * e^(-1.5 TS s)
      L_v  = KP2(s+2piKI2)/s * H_ci * K_a/(s+D) * e^(-1.5 TS s)
      L_p  = KP3 * (L_v/(1+L_v)) / s
    """
    w = np.logspace(0, 4.5, 200000)
    gi = (kp1 * (1j * w + 2 * np.pi * ki1_hz) / (1j * w)
          / (l_pp * 1j * w + r_pp) * np.exp(-1j * w * CUR_DELAY_MULT * ts_s))
    wci, pmi, _ = _margins_of(gi, w)
    hci = gi / (1 + gi)
    lv = (kp2 * (1j * w + 2 * np.pi * ki2_hz) / (1j * w) * hci
          * (k_a / (1j * w + d_visc)) * np.exp(-1j * w * VEL_DELAY_MULT * ts_s))
    wcv_x, pm_v, gm_v = _margins_of(lv, w)
    tv = lv / (1 + lv)
    lp = kp3 * tv / (1j * w)
    wcp_x, pm_p, _ = _margins_of(lp, w)
    return {"w_ci": wci, "pm_i": pmi,
            "w_cv": wcv_x, "pm_vel": pm_v, "gm_db": gm_v,
            "w_cp": wcp_x, "pm_pos": pm_p}


def design_vp_gains(k_a: float, d_visc: float, ts_s: float,
                    params: AutotuneVPParams, kp1: float, ki1_hz: float) -> dict:
    """SPEC §3 design + G4 margin gate with up to 3 wcv reductions (the beta
    and delta RATIOS are kept, so KI[2]/KP[3] rescale with wcv).
    kp1/ki1_hz = the drive's CURRENT-loop gains as read at P1 (H_ci model).
    Returns {ok, kp2, ki2, kp3, wcv, margins, iters}."""
    if params.wcv_override_hz:
        wcv = 2 * math.pi * float(params.wcv_override_hz)
    else:
        wcv = WCV_TS_CAL / ts_s
    iters = []
    out = None
    for _ in range(1 + MAX_WCV_REDUCTIONS):
        kp2 = wcv / k_a
        ki2 = wcv / (2 * math.pi * BETA_VEL)
        kp3 = wcv / DELTA_POS
        m = vel_pos_margins(kp2, ki2, kp3, k_a, d_visc, kp1, ki1_hz,
                            params.r_pp_ohm, params.l_pp_h, ts_s)
        ok = (m["pm_vel"] >= PM_VEL_MIN
              and (m["gm_db"] is None or m["gm_db"] >= GM_MIN_DB)
              and wcv * ts_s <= WCV_TS_MAX
              and m["pm_pos"] >= PM_POS_MIN
              and m["w_ci"] / wcv >= RATIO_CI_CV_MIN
              and wcv / kp3 >= RATIO_CV_KP3_MIN)
        iters.append({"wcv_rad_s": wcv, "kp2": kp2, "ki2_hz": ki2, "kp3": kp3,
                      "pm_vel": m["pm_vel"], "gm_db": m["gm_db"],
                      "pm_pos": m["pm_pos"], "wcv_ts": wcv * ts_s, "pass": ok})
        out = {"ok": ok, "kp2": kp2, "ki2": ki2, "kp3": kp3, "wcv": wcv,
               "margins": m, "iters": iters}
        if ok:
            return out
        wcv *= 0.8
    return out


# ======================================================================================
# pipeline context + transport helpers (Phase-1 pattern)
# ======================================================================================
class _Ctx:
    def __init__(self, link, params: AutotuneVPParams):
        self.link = link
        self.params = params
        self.readings: dict = {}
        self.evidence: dict = {}
        self.warnings: list = []
        self.snapshot: dict = {}
        self.snapshot_path: Optional[str] = None
        self.dirty: list = []
        self.motor_on = False
        self.aborted = False
        self.segment = "idle"           # idle | tc | jv  (abort chain selector)
        self.ts_s: float = 0.0
        self.cl1: float = 0.0
        self.ca18: float = 65536.0
        self.guard_due_s = 0.0
        self.elapsed_s = 0.0            # total in-motion budget (120 s)
        self.seg_deadline_s: Optional[float] = None
        self.cancel_err_logged = False
        self.sig: dict = {}
        self.vx_guard_cnt = 1.31e6      # recomputed from CA[18] at P2
        # unit corrections established by B1.5 UNIT-DIAG (SPEC §9); applied to
        # every subsequent _record_fetch (v *= s_scale, dt *= g_dt)
        self.s_scale = 1.0              # velocity-channel scale (true = rec * s)
        self.g_dt = 1.0                 # recording dt factor (true = g * assumed)


def _cmd(ctx: _Ctx, cmd: str, allow_motion: bool = False, retries: int = 2):
    """command() with the I5 retry policy and the NaN entrance gate."""
    last = None
    for _ in range(retries + 1):
        try:
            resp = ctx.link.command(cmd, timeout_ms=1000, allow_motion=allow_motion)
            val = _to_num(resp)
            if isinstance(val, float) and math.isnan(val):
                raise AbortError("NaN 응답 (%s) — 즉시 중단" % cmd)
            return val
        except (AbortError, PermissionError):
            raise
        except Exception as e:
            last = e
    raise AbortError("통신 실패 %r: %s" % (cmd, last))


def _write(ctx: _Ctx, cmd: str, value, allow_motion: bool = False):
    ctx.dirty.append(cmd)
    return _cmd(ctx, "%s=%s" % (cmd, _fmt(value)), allow_motion=allow_motion)


def _fmt(v):
    return ("%.9g" % v) if isinstance(v, float) else str(v)


def _emit(ctx: _Ctx, code: str, detail: str):
    try:
        ctx.params.progress_fn(code, detail)
    except Exception as e:
        errs = ctx.evidence.setdefault("progress_errors", [])
        if len(errs) < 8:
            errs.append("%s: %r" % (code, e))


def _check_cancel(ctx: _Ctx):
    try:
        want = bool(ctx.params.cancel_fn())
    except Exception as e:
        if not ctx.cancel_err_logged:
            ctx.cancel_err_logged = True
            ctx.warnings.append("cancel_fn 예외 — 취소로 간주하지 않고 계속: %r" % (e,))
        return
    if want:
        raise AbortError("작업자 중단 요청")


def _guard(ctx: _Ctx):
    """30 ms in-motion guard (SPEC §4): MF!=0, LC==1, |VX|>1200rpm, segment
    timebox, total budget -> abort."""
    mf = _cmd(ctx, "MF")
    if isinstance(mf, (int, float)) and mf != 0:
        raise AbortError("모터 폴트 MF=0x%X" % int(mf))
    lc = _cmd(ctx, "LC")
    if lc == 1:
        raise AbortError("전류 리미터 포화 LC=1")
    vx = _cmd(ctx, "VX")
    if isinstance(vx, (int, float)) and abs(vx) > ctx.vx_guard_cnt:
        raise AbortError("과속 가드 |VX|=%.0f cnt/s > %.0f (1200rpm)"
                         % (abs(vx), ctx.vx_guard_cnt))
    if ctx.seg_deadline_s is not None and ctx.elapsed_s > ctx.seg_deadline_s:
        raise AbortError("세그먼트 타임박스(%.0fs) 초과" % SEG_TIMEBOX_S)
    if ctx.elapsed_s > TOTAL_BUDGET_S:
        raise AbortError("전체 시간예산(%.0fs) 초과" % TOTAL_BUDGET_S)


def _sleep(ctx: _Ctx, dur_s: float):
    """Sleep in <=30 ms chunks; cancel poll every chunk; guard while MO=1."""
    remaining = float(dur_s)
    while remaining > 1e-12:
        chunk = min(remaining, GUARD_PERIOD_S - ctx.guard_due_s
                    if ctx.motor_on else remaining)
        chunk = max(chunk, 1e-6)
        ctx.params.sleep_fn(chunk)
        remaining -= chunk
        ctx.elapsed_s += chunk
        _check_cancel(ctx)
        if ctx.motor_on:
            ctx.guard_due_s += chunk
            if ctx.guard_due_s >= GUARD_PERIOD_S - 1e-9:
                ctx.guard_due_s = 0.0
                _guard(ctx)


def _seg(ctx: _Ctx, name: str):
    """Enter a motion segment: select the abort chain + arm the 5 s timebox."""
    ctx.segment = name
    ctx.seg_deadline_s = ctx.elapsed_s + SEG_TIMEBOX_S if name != "idle" else None


# ======================================================================================
# recording (record_start / record_fetch split — SPEC §6 infra)
# ======================================================================================
def _resolve_signals(ctx: _Ctx):
    """SPEC P4 regexes: Velocity(^velocity(?!.*command)), Active Current,
    Position(^position(?!.*(command|error))), Velocity Command.  RED+dump."""
    lister = getattr(ctx.link, "recorder_signals", None)
    names = None
    if callable(lister):
        try:
            nm = lister()
            names = list(nm) if nm else None
        except Exception:
            names = None
    if not names:
        err = getattr(ctx.link, "_last_recorder_error", None)
        raise PreflightError("레코더 신호목록 확보 실패%s"
                             % (" — %s" % err if err else ""))
    ctx.evidence["recorder_signals"] = list(names)

    def pick(pattern, label):
        m = [n for n in names if re.match(pattern, n, re.I)]
        if not m:
            raise PreflightError("레코더 신호 '%s' 없음 — 신호목록 덤프 참조" % label)
        return m[0]

    vel = pick(r"^velocity(?!.*command)", "Velocity")
    pos = pick(r"^position(?!.*(command|error))", "Position")
    cur = ([n for n in names if n == "Active Current [A]"]
           or [n for n in names if re.search(r"active\s*current", n, re.I)
               and not re.search(r"reactive", n, re.I)])
    if not cur:
        raise PreflightError("레코더 신호 'Active Current' 없음 — 덤프 참조")
    # Current Command — §9: recorded in EVERY capture (torque-path witness)
    icmd = ([n for n in names if n == "Current Command [A]"]
            or [n for n in names if n == "Total Current Command [A]"]
            or [n for n in names if re.search(r"current\s*command", n, re.I)
                and not re.search(r"position|velocity", n, re.I)])
    if not icmd:
        raise PreflightError("레코더 신호 'Current Command' 없음 — 덤프 참조 (§9)")
    vcmd = [n for n in names if re.match(r"^velocity.*command", n, re.I)]
    ctx.sig = {"vel": vel, "pos": pos, "cur": cur[0], "icmd": icmd[0],
               "vcmd": vcmd[0] if vcmd else None}
    ctx.evidence["signal_map"] = dict(ctx.sig)
    return ctx.sig


def _rec_names(ctx: _Ctx):
    return [ctx.sig["vel"], ctx.sig["pos"], ctx.sig["cur"], ctx.sig["icmd"]]


def _record_start(ctx: _Ctx, duration_s: float, tres_override: Optional[int] = None):
    """Arm the free-running recorder for `duration_s` (tres from rec_dt; the
    UNIT-DIAG passes tres_override=1 for the Phase-1-verified dt=TS base)."""
    if tres_override is not None:
        tres = int(tres_override)
    else:
        tres = max(1, int(round(ctx.params.rec_dt_s / ctx.ts_s)))
    length = int(math.ceil(duration_s / (tres * ctx.ts_s)))
    if length > 16384 // 4:                     # per-signal cap -> coarser dt
        tres *= 2                               # SPEC §6 edge: tres fallback
        length = int(math.ceil(duration_s / (tres * ctx.ts_s)))
    fn = getattr(ctx.link, "record_start", None)
    if not callable(fn):
        raise AbortError("링크에 record_start() 없음 — 레코더 분리 래퍼 필요")
    try:
        fn(_rec_names(ctx), length, time_resolution=tres)
    except Exception as e:
        raise AbortError("레코딩 시작 실패: %s" % e)
    return tres * ctx.ts_s


def _record_fetch(ctx: _Ctx) -> dict:
    fn = getattr(ctx.link, "record_fetch", None)
    if not callable(fn):
        raise AbortError("링크에 record_fetch() 없음")
    try:
        out = fn(timeout_s=10.0)
    except Exception as e:
        raise AbortError("레코딩 업로드 실패: %s" % e)
    try:
        v = np.asarray(out[ctx.sig["vel"]], float)
        p = np.asarray(out[ctx.sig["pos"]], float)
        i = np.asarray(out[ctx.sig["cur"]], float)
        icmd = np.asarray(out[ctx.sig["icmd"]], float)
    except KeyError as e:
        raise AbortError("레코딩 채널 누락: %s" % e)
    if len(v) == 0 or len(p) != len(v) or len(i) != len(v) or len(icmd) != len(v):
        raise AbortError("레코딩 길이 이상 (v=%d p=%d i=%d ic=%d)"
                         % (len(v), len(p), len(i), len(icmd)))
    if np.isnan(v).any() or np.isnan(i).any() or np.isnan(p).any():
        raise AbortError("레코딩 데이터 NaN — 즉시 중단")
    dt = out.get("dt")
    if not isinstance(dt, (int, float)) or dt <= 0:
        dt = ctx.params.rec_dt_s
        ctx.warnings.append("레코딩 dt 미보고 — rec_dt=%.3gs 잠정 적용 (U-P5)" % dt)
    # apply the UNIT-DIAG-confirmed unit corrections (§9: 이후 K_a측정은 확정된
    # s·dt 보정 적용).  Both stay 1.0 until B1.5 establishes them.
    return {"v": v * ctx.s_scale, "v_raw": v, "p": p, "i": i, "icmd": icmd,
            "dt": float(dt) * ctx.g_dt}


# ======================================================================================
# abort chains (SPEC §4 — segment-specific, fixed order)
# ======================================================================================
def _restore_limits(ctx: _Ctx):
    restored, failed = [], []
    for cmd, _v in LIMIT_WRITES:
        if cmd not in set(ctx.dirty) or cmd not in ctx.snapshot:
            continue
        try:
            _cmd(ctx, "%s=%s" % (cmd, _fmt(ctx.snapshot[cmd])), retries=1)
            restored.append(cmd)
        except Exception as e:
            failed.append("%s(%s)" % (cmd, e))
    if failed:
        ctx.warnings.append("리밋 복원 실패 %s — 전원 재투입 시 스냅숏(%s) 참조"
                            % (", ".join(failed), ctx.snapshot_path))
    ctx.evidence["restored_limits"] = restored


def _do_abort(ctx: _Ctx, reason: str):
    if ctx.aborted:
        return
    ctx.aborted = True
    steps = []

    def _try(label, fn):
        try:
            fn()
            steps.append(label)
        except Exception as e:
            ctx.warnings.append("abort %s 실패: %s" % (label, e))

    if ctx.segment == "jv":
        _try("A1 JV=0", lambda: ctx.link.command("JV=0", timeout_ms=1000,
                                                 allow_motion=True))
        _try("A1b ST", lambda: ctx.link.command("ST", timeout_ms=1000,
                                                allow_motion=True))
        stop_cnt = ctx.ca18 * JV_STOP_RPM / 60.0

        def _wait_stop():
            waited = 0.0
            while waited < JV_STOP_TIMEOUT_S:
                vx = _to_num(ctx.link.command("VX", timeout_ms=1000))
                if isinstance(vx, (int, float)) and abs(vx) < stop_cnt:
                    return
                ctx.params.sleep_fn(0.05)
                waited += 0.05
            raise TimeoutError("JV 정지 대기 실패 — 즉시 MO=0")
        _try("A2 wait |VX|<30rpm", _wait_stop)
    elif ctx.segment == "tc":
        _try("A1 TC=0", lambda: ctx.link.command("TC=0", timeout_ms=1000,
                                                 allow_motion=True))
    _try("A_mo MO=0", lambda: ctx.link.command("MO=0", timeout_ms=1000))
    ctx.motor_on = False
    _try("A_lim restore", lambda: _restore_limits(ctx))
    ctx.evidence["abort"] = {"reason": reason, "segment": ctx.segment,
                             "steps_done": steps}


def _red(ctx: _Ctx, reason: str) -> AutotuneVPResult:
    ctx.evidence.setdefault("readings", ctx.readings)
    return AutotuneVPResult(status=RED, reason=reason,
                            ts_us=ctx.readings.get("TS"),
                            evidence=ctx.evidence, warnings=ctx.warnings)


# ======================================================================================
# identification analysis (SPEC §2)
# ======================================================================================
def _grid_points(rec: dict, win_s: float = 0.010):
    """Non-overlapping ~10 ms windows -> (a=dv/dt slope, Ibar, vbar, sgn, R2)
    per window.  Slopes by least squares (SPEC: point differences forbidden)."""
    dt = rec["dt"]
    n_w = max(4, int(round(win_s / dt)))
    pts = []
    for k0 in range(0, len(rec["v"]) - n_w, n_w):
        sl = slice(k0, k0 + n_w)
        t = np.arange(n_w) * dt
        a, _b, r2 = window_slope(t, rec["v"][sl])
        pts.append({"a": a, "i": float(np.mean(rec["i"][sl])),
                    "v": float(np.mean(rec["v"][sl])),
                    "s": float(np.sign(np.mean(rec["v"][sl]))), "r2": r2,
                    "k0": k0, "n": n_w})
    return pts


def _band_window(rec: dict, mask: np.ndarray, lo: float, hi: float, sign: float):
    """Indices inside `mask` where sign*v is within [lo, hi] (same-speed band)."""
    v = rec["v"] * sign
    sel = mask & (v >= lo) & (v <= hi)
    return np.flatnonzero(sel)


def _analyze_pulse_run(ctx: _Ctx, rec: dict, i0: float, first_sign: float) -> dict:
    """SPEC §2.2: matched same-speed-band windows on the +/- pulse pair ->
    K_a_diff (friction cancels exactly); global regression a=[I,-v,-sgn] ->
    K_a,D,C; position second-order cross-check (G1c); integral(v)dt vs dPos
    time-base identity (G1d)."""
    v, p, i, dt = rec["v"], rec["p"], rec["i"], rec["dt"]
    t = np.arange(len(v)) * dt
    m1 = (i * first_sign) > 0.5 * i0                 # first pulse samples
    m2 = (i * first_sign) < -0.5 * i0                # second pulse samples
    if not m1.any() or not m2.any():
        raise AbortError("펄스 구간 미검출 (기록에 전류 펄스 없음)")
    vpk = float(np.max(v * first_sign))
    if vpk <= 0:
        raise AbortError("펄스 방향 속도 미상승 — sign(v̇)≠sign(TC) (§1-3)")
    band = (PULSE_BAND[0] * vpk, PULSE_BAND[1] * vpk)   # §9: 실측 v_pk 상대구간
    i1x = _band_window(rec, m1, band[0], band[1], first_sign)
    i2x = _band_window(rec, m2, band[0], band[1], first_sign)
    if len(i1x) < 4 or len(i2x) < 4:
        raise AbortError("속도대 매칭 창 부족 (n1=%d n2=%d)" % (len(i1x), len(i2x)))
    a1, _o1, r2_1 = window_slope(t[i1x], v[i1x])
    a2, _o2, r2_2 = window_slope(t[i2x], v[i2x])
    ib1 = float(np.mean(i[i1x]))
    ib2 = float(np.mean(i[i2x]))
    denom = abs(ib1) + abs(ib2)
    if denom < 0.2 * i0:
        raise AbortError("펄스 기록전류 이상 (|I1|+|I2|=%.3fA)" % denom)
    k_a_diff = abs(a1 - a2) / denom
    k_a_naive = abs(a1 / ib1) if ib1 else float("nan")   # regression tooth (biased)
    # global regression over all moving windows (both pulses + coast tail)
    pts = [q for q in _grid_points(rec)
           if abs(q["v"]) > 0.02 * vpk or abs(q["i"]) > 0.5 * i0]
    A = np.array([[q["i"], -q["v"], -q["s"]] for q in pts])
    y = np.array([q["a"] for q in pts])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    k_a_reg, d_reg, c_reg = float(coef[0]), float(coef[1]), float(coef[2])
    # position 2nd-order in the matched window: 2*a2_coef == dv/dt (G1c)
    tt = t[i1x] - t[i1x][0]
    qc = np.polyfit(tt, p[i1x], 2)
    a_pos = 2.0 * float(qc[0])
    # time-base identity: integral(v dt) vs dPos over the whole record (G1d)
    int_v = float(np.trapezoid(v, dx=dt))
    d_pos = float(p[-1] - p[0])
    return {"k_a_diff": k_a_diff, "k_a_naive": k_a_naive,
            "k_a_reg": k_a_reg, "d_reg": d_reg, "c_reg": c_reg,
            "b_reg": d_reg / k_a_reg if k_a_reg else float("nan"),
            "i_c_reg": c_reg / k_a_reg if k_a_reg else float("nan"),
            "slope_plus": a1, "slope_minus": a2,
            "i_plus": ib1, "i_minus": ib2, "r2": min(r2_1, r2_2),
            "a_pos_2nd": a_pos, "slope_for_pos": a1,
            "int_v": int_v, "d_pos": d_pos, "v_peak": vpk * first_sign,
            "band": list(band),
            # §9: raw arrays are MANDATORY evidence (no summary-only results)
            "raw": {"pos": _decimate(p), "vel": _decimate(v),
                    "i_act": _decimate(i), "i_cmd": _decimate(rec["icmd"])}}


def _probe_ka(ctx: _Ctx, rec: dict, i_probe: float):
    """B1 probe: on/off TWO-slope K_a (friction-corrected — module docstring
    judgment note).  Returns (k_a_probe, v_peak, on_slope, moved).
    `moved` compares the peak against the PRE-ROLL noise floor: a bare 500
    cnt/s constant is below the velocity-quantization noise (sigma~1e3 ->
    max|noise|~3.3 sigma) and mistakes noise for motion (found by the T3 sim:
    stiction case sailed into the pulses on a fake K_a)."""
    v, i, dt = rec["v"], rec["i"], rec["dt"]
    t = np.arange(len(v)) * dt
    m_on = i > 0.5 * i_probe
    if not m_on.any():
        raise AbortError("프로브 전류 미기록")
    a_on, _o, _r = window_slope(t[m_on], v[m_on])
    vpk = float(np.max(np.abs(v)))
    n_pre = max(4, int(PRE_ROLL_S / dt) - 2)
    noise_sd = float(np.std(v[:n_pre])) if len(v) > n_pre else 0.0
    moved = vpk > max(500.0, 8.0 * noise_sd)
    if moved and a_on < 0:                           # §1-3 sign gate (40 ms window)
        raise AbortError("커뮤 부호 이상: sign(v̇)≠sign(TC) — 즉시 중단")
    k_last = int(np.flatnonzero(m_on)[-1])
    # CONTIGUOUS coast segment only: a threshold mask alone lets post-stiction
    # noise samples (|noise| > threshold, scattered far in time) leverage the
    # fit and flatten the slope to ~0 (found by the T3 sim: probe K_a 5x low
    # -> Tp clipped long -> overspeed guard)
    idx = k_last + 2
    seg = []
    while idx < len(v) and abs(v[idx]) > 0.15 * vpk:
        seg.append(idx)
        idx += 1
    if len(seg) >= 4:
        seg = np.asarray(seg)
        a_off, _o2, _r2 = window_slope(t[seg], v[seg])
    else:
        a_off = 0.0
    ib = float(np.mean(i[m_on]))
    k_a_probe = (a_on - a_off) / ib if ib else 0.0
    return k_a_probe, vpk, a_on, moved


def _decimate(a, max_n: int = 512):
    """Raw-array evidence helper (§9: 원배열 의무, 8:1급 데시메이션 허용)."""
    a = np.asarray(a, float)
    step = max(1, int(math.ceil(len(a) / max_n)))
    return [round(float(x), 3) for x in a[::step]]


def _unit_diag(ctx: _Ctx):
    """B1.5 UNIT-DIAG (SPEC §9) — hard gate before any main pulse.

    One +0.5 A / 80 ms torque pulse recorded at TR=1 (dt = TS, the ONLY
    Phase-1-verified time base) with all four channels + a 30 ms VX poll log.
    Three discriminants:
      (1) g  = T_host / (N_pulse * dt_assumed)        [dt factor, current mask]
      (2) s  = dPosition / sum(v * g * dt_assumed)    [velocity-channel scale];
          second path s2 = median(VX_poll / v_rec) at matched instants
      (3) K_a(channel-agnostic) from a POSITION-only 2nd-order fit over the
          late pulse window t in [24, 80] ms — the final judge (no Velocity).
    Decision (§9): big dPos & s off -> velocity scale (adopt s); big dPos &
    g~1/4 -> dt (adopt g); dPos itself tiny -> units are fine, PHYSICS anomaly
    (I_act << I_cmd = torque not applied -> RED with MO/SR/MF/LC log;
    I_act ~ I_cmd -> mechanical constraint/stiction RED).
    Hard gate: post-correction |s-1|<=5% AND |g-1|<=10% AND the corrected
    velocity slope matches the Position-fit accel within 10%; only then the
    main pulses run, and every later capture gets the s/dt corrections."""
    p = ctx.params
    _seg(ctx, "tc")
    _record_start(ctx, UNITDIAG_REC_S, tres_override=1)
    vx_log = []
    t0 = ctx.elapsed_s

    def poll_sleep(dur):
        remaining = float(dur)
        while remaining > 1e-9:
            step = min(0.03, remaining)
            _sleep(ctx, step)
            remaining -= step
            vx = _cmd(ctx, "VX")
            if isinstance(vx, (int, float)):
                vx_log.append((ctx.elapsed_s - t0, float(vx)))

    poll_sleep(PRE_ROLL_S)
    _write(ctx, "TC", UNITDIAG_I_A, allow_motion=True)
    poll_sleep(UNITDIAG_T_S)
    _write(ctx, "TC", 0.0, allow_motion=True)
    poll_sleep(UNITDIAG_REC_S - PRE_ROLL_S - UNITDIAG_T_S + 0.02)
    rec = _record_fetch(ctx)                    # corrections still 1.0 -> raw
    _seg(ctx, "idle")
    v, pos, i_act, icmd, dt = rec["v"], rec["p"], rec["i"], rec["icmd"], rec["dt"]
    d_pos = float(pos[-1] - pos[0])
    cmd_mask = icmd > 0.5 * UNITDIAG_I_A
    act_mask = i_act > 0.5 * UNITDIAG_I_A
    mean_icmd = float(np.mean(icmd[cmd_mask])) if cmd_mask.any() else 0.0
    mean_iact = float(np.mean(i_act[cmd_mask])) if cmd_mask.any() else 0.0
    ev = {"d_pos_cnt": d_pos, "dt_assumed_s": dt,
          "mean_i_cmd": mean_icmd, "mean_i_act": mean_iact,
          "vx_poll": [(round(t, 4), round(x, 1)) for t, x in vx_log],
          "raw": {"pos": _decimate(pos), "vel": _decimate(v),
                  "i_act": _decimate(i_act), "i_cmd": _decimate(icmd)},
          "notes": "U-P9=Velocity 단위, U-P10=UM=5 TC 실효 — 이 진단이 실기 판별 경로"}
    ctx.evidence["unit_diag"] = ev

    # ---- physics-anomaly branch first (Position = ground truth) -----------------------
    if abs(d_pos) < UNITDIAG_MIN_DPOS:
        logs = {k: _cmd(ctx, k) for k in ("MO", "SR", "MF", "LC")}
        ev["drive_logs"] = logs
        if mean_icmd > 0 and mean_iact < 0.5 * mean_icmd:
            raise AbortError(
                "UNIT-DIAG: 토크미인가 — I_active=%.2fA ≪ I_cmd=%.2fA, ΔPos=%.0fcnt"
                " (UM=5 TC경로 확인 필요, U-P10; 로그 %s)"
                % (mean_iact, mean_icmd, d_pos, logs))
        raise AbortError(
            "UNIT-DIAG: 기계구속/정지마찰 의심 — I_active 정상(%.2fA)인데 ΔPos=%.0fcnt"
            % (mean_iact, d_pos))

    # ---- (1) g: dt factor --------------------------------------------------------------
    n_pulse = int(act_mask.sum())
    g = UNITDIAG_T_S / (n_pulse * dt) if n_pulse else float("inf")
    # ---- (2) s: velocity-channel scale (true = rec * s) --------------------------------
    sum_v = float(np.sum(v)) * g * dt
    s = d_pos / sum_v if sum_v else float("inf")
    ratios = []
    v_ref = float(np.max(np.abs(v)))
    for t_rel, vx in vx_log:
        k = int(round(t_rel / (g * dt)))
        if 0 <= k < len(v) and abs(v[k]) > 0.05 * v_ref:
            ratios.append(vx / v[k])
    s2 = float(np.median(ratios)) if ratios else None
    # ---- (3) channel-agnostic accel: POSITION-only late-window 2nd-order fit ----------
    t_true = np.arange(len(v)) * g * dt
    k_on = np.flatnonzero(act_mask)
    t_p0 = float(t_true[k_on[0]])
    w = (t_true >= t_p0 + 0.024) & (t_true <= t_p0 + UNITDIAG_T_S) & act_mask
    if w.sum() < 8:
        raise AbortError("UNIT-DIAG: 후반창 표본 부족 (n=%d)" % int(w.sum()))
    tt = t_true[w] - t_true[w][0]
    qc = np.polyfit(tt, pos[w], 2)
    a_pos = 2.0 * float(qc[0])
    i_w = float(np.mean(i_act[w]))
    ka_pos = a_pos / i_w if i_w else float("nan")

    # ---- adopt corrections (§9 decision table, sequential (1)->(2)) --------------------
    verdicts = []
    if abs(g - 1.0) > UNITDIAG_G_TOL and math.isfinite(g):
        ctx.g_dt = g
        verdicts.append("dt계수 g=%.4g 채택 (dt_true=g·dt)" % g)
    if abs(s - 1.0) > UNITDIAG_S_TOL and math.isfinite(s):
        ctx.s_scale = s
        verdicts.append("속도스케일 s=%.4g 채택 (v_true=s·v_rec)" % s)
        ctx.warnings.append("Velocity 채널 스케일 %.4g 보정 적용 — U-P9 실기확정 대상"
                            % s)
    # ---- hard gate: post-correction self-consistency ------------------------------------
    g_corr = UNITDIAG_T_S / (n_pulse * dt * ctx.g_dt)
    s_corr = d_pos / (float(np.sum(v)) * ctx.s_scale * ctx.g_dt * dt) \
        if np.sum(v) else float("inf")
    t_corr = np.arange(len(v)) * ctx.g_dt * dt
    slope_v, _o, _r2 = window_slope(t_corr[w], v[w] * ctx.s_scale)
    ka_vel = slope_v / i_w if i_w else float("nan")
    ka_dev = abs(ka_vel / ka_pos - 1.0) if ka_pos else float("inf")
    gate_pass = (abs(s_corr - 1.0) <= UNITDIAG_S_TOL
                 and abs(g_corr - 1.0) <= UNITDIAG_G_TOL
                 and ka_dev <= UNITDIAG_KA_TOL)
    ev.update({"g": g, "s": s, "s2_vx": s2, "ka_pos": ka_pos, "ka_vel_corr": ka_vel,
               "ka_dev": ka_dev, "s_corr": s_corr, "g_corr": g_corr,
               "s_scale_adopted": ctx.s_scale, "g_dt_adopted": ctx.g_dt,
               "verdicts": verdicts, "gate_pass": bool(gate_pass)})
    if not gate_pass:
        raise AbortError(
            "UNIT-DIAG 하드게이트 실패 — 보정후 s=%.3f g=%.3f, Position-교차 K_a 편차"
            " %.0f%% (>10%%): 단위 미확정, 본펄스 진행 금지" %
            (s_corr, g_corr, 100 * ka_dev))


# ======================================================================================
# the pipeline (SPEC §6 P0..E2)
# ======================================================================================
_P1_READS = (["TS", "UM", "MF", "SR", "GS[0]", "GS[1]", "GS[2]",
              "KP[1]", "KP[2]", "KP[3]", "KI[1]", "KI[2]",
              "CA[7]", "CA[17]", "CA[18]", "CA[41]", "CA[42]", "CA[43]", "CA[44]",
              "CL[1]", "PL[1]", "MC", "VH[2]", "VH[3]", "VL[3]",
              "ER[2]", "ER[3]", "HL[2]", "HL[3]", "LL[2]", "LL[3]",
              "AC", "DC", "SD", "SP", "FF[1]", "FF[2]", "VX", "PX", "BV",
              "WS[28]", "WS[55]"])


def run_velpos_autotune(link, params: Optional[AutotuneVPParams] = None
                        ) -> AutotuneVPResult:
    """Phase 2 measurement pipeline (P0..E2).  Gain application (F1) and the
    verification run (F2) are separate calls: apply_gains_vp / verify_run_vp.

    SAFETY: sends MO=1/TC/JV/ST with allow_motion=True — the caller must have
    passed the operator gate (free rotation, load detached, expected revs
    shown) BEFORE calling this.  Never raises: failures return RED after the
    segment-appropriate abort chain."""
    params = params or AutotuneVPParams()
    ctx = _Ctx(link, params)
    try:
        return _pipeline(ctx)
    except PreflightError as e:
        return _red(ctx, str(e))
    except AbortError as e:
        _do_abort(ctx, str(e))
        return _red(ctx, str(e))
    except Exception as e:
        _do_abort(ctx, "내부 예외: %r" % (e,))
        return _red(ctx, "내부 예외: %r" % (e,))


def _pipeline(ctx: _Ctx) -> AutotuneVPResult:
    p = ctx.params

    # ---- P0 ---------------------------------------------------------------------------
    if not getattr(ctx.link, "is_connected", False):
        raise PreflightError("드라이브 미연결")
    if _cmd(ctx, "MO") == 1:
        raise PreflightError("모터 ON(MO=1) — STOP 후 재시도 (자동 disable 금지)")
    _emit(ctx, "P0", "연결 확인, MO=0 게이트 통과")

    # ---- P1 ---------------------------------------------------------------------------
    for c in _P1_READS:
        ctx.readings[c] = _cmd(ctx, c)
    ctx.evidence["readings"] = dict(ctx.readings)

    # ---- P2 / G0 (pre-power, SPEC §5) --------------------------------------------------
    r = ctx.readings
    ts = r["TS"]
    if not isinstance(ts, (int, float)) or not (40 <= ts <= 200):
        raise PreflightError("TS=%r 비정상" % (ts,))
    ctx.ts_s = ts * 1e-6
    if r.get("GS[2]") not in (0, 0.0):
        raise PreflightError("게인 스케줄링 활성(GS[2]=%r) — KP/KI 비실효, 중단"
                             % (r.get("GS[2]"),))
    if r.get("UM") != 5:
        raise PreflightError("UM=%r (5 필요 — TC토크/JV속도 겸용 모드)" % (r.get("UM"),))
    if not isinstance(r.get("MF"), (int, float)) or r["MF"] != 0:
        raise PreflightError("모터 폴트 MF=%r" % (r.get("MF"),))
    if r.get("CA[17]") != p.expected_ca17:
        raise PreflightError("커뮤 변경감지: CA[17]=%r (기대 %d) — CS/CA[7] 쓰기 금지,"
                             " 수동 확인 필요" % (r.get("CA[17]"), p.expected_ca17))
    if p.expected_ca7 is not None and r.get("CA[7]") != p.expected_ca7:
        raise PreflightError("커뮤 변경감지: CA[7]=%r (기대 %s)"
                             % (r.get("CA[7]"), p.expected_ca7))
    for wsk in ("WS[28]", "WS[55]"):
        if isinstance(r.get(wsk), (int, float)) and r[wsk] != ts:
            raise PreflightError("%s=%r ≠ TS=%r — 루프주기 불일치" % (wsk, r[wsk], ts))
    cl1 = r.get("CL[1]")
    if not isinstance(cl1, (int, float)) or cl1 <= 0:
        raise PreflightError("CL[1]=%r 비정상" % (cl1,))
    ctx.cl1 = float(cl1)
    ca18 = r.get("CA[18]")
    ctx.ca18 = float(ca18) if isinstance(ca18, (int, float)) and ca18 > 0 else 65536.0
    ctx.vx_guard_cnt = ctx.ca18 * GUARD_RPM / 60.0
    kp1 = r.get("KP[1]") if isinstance(r.get("KP[1]"), (int, float)) else 0.07177
    ki1 = r.get("KI[1]") if isinstance(r.get("KI[1]"), (int, float)) else 812.939
    _emit(ctx, "VALIDATE", "G0 통과: TS=%dµs UM=5 GS[2]=0 CA[17]=%d, CL[1]=%.2fA"
          % (int(ts), p.expected_ca17, ctx.cl1))

    # ---- P4 (read-only) then P3 snapshot -----------------------------------------------
    _resolve_signals(ctx)
    ctx.snapshot = dict(ctx.readings)
    os.makedirs(p.snapshot_dir, exist_ok=True)
    ctx.snapshot_path = os.path.join(
        p.snapshot_dir, "autotune_vp_snapshot_%d.json" % int(time.time() * 1000))
    with open(ctx.snapshot_path, "w", encoding="utf-8") as fj:
        json.dump({"t": time.time(), "readings": ctx.snapshot}, fj,
                  ensure_ascii=False, indent=1)
    ctx.evidence["snapshot_path"] = ctx.snapshot_path
    _emit(ctx, "SNAPSHOT", "스냅숏 저장: %s" % ctx.snapshot_path)

    # ---- P5 explicit limits (write + readback; refusal -> warnings only, U-P4) --------
    limit_rb = {}
    for cmd, val in LIMIT_WRITES:
        try:
            _write(ctx, cmd, val)
            rb = _cmd(ctx, cmd)
            limit_rb[cmd] = rb
            if isinstance(rb, (int, float)) and abs(rb - val) > abs(val) * 1e-6 + 1e-9:
                ctx.warnings.append("리밋 %s 리드백 불일치(%r≠%r) — SW가드로 보완(U-P4)"
                                    % (cmd, rb, val))
        except Exception as e:
            ctx.warnings.append("리밋 %s 쓰기 거부(%s) — SW가드로 보완(U-P4)" % (cmd, e))
    ctx.evidence["limits"] = limit_rb

    # ---- B0 enable (operator gate is the CALLER's) -------------------------------------
    _cmd(ctx, "MO=1", allow_motion=True)
    ctx.motor_on = True
    waited = 0.0
    while _cmd(ctx, "SO") != 1:
        if waited >= 2.0:
            raise AbortError("SO!=1 (2s) — 서보온 실패")
        _sleep(ctx, p.poll_s)
        waited += p.poll_s
    _emit(ctx, "ENABLE", "MO=1 통전(UM=5), 서보온 확인 — 단위 진단(B1.5) 시작")

    # ---- B1.5 UNIT-DIAG (§9 hard gate — the probe B1 moved AFTER this) ----------------
    _emit(ctx, "UNIT_DIAG", "단위 진단: +%.1fA/%.0fms 펄스, TR=1, dt·속도스케일·토크경로 판별"
          % (UNITDIAG_I_A, UNITDIAG_T_S * 1e3))
    _unit_diag(ctx)
    ud = ctx.evidence["unit_diag"]
    _emit(ctx, "UNIT_DIAG", "단위 확정: s=%.4g g=%.4g (K_a③=%.3g, 편차 %.1f%%) — 게이트 통과"
          % (ud["s"], ud["g"], ud["ka_pos"], 100 * ud["ka_dev"]))

    # ---- B1 probe (uses the UNIT-DIAG-confirmed s/dt corrections) ----------------------
    i_probe = p.probe_i_a
    k_a_probe = None
    for attempt in (0, 1):
        _seg(ctx, "tc")
        rec_dt = _record_start(ctx, 0.4)
        _sleep(ctx, PRE_ROLL_S)
        _write(ctx, "TC", i_probe, allow_motion=True)
        _sleep(ctx, PROBE_T_S)
        _write(ctx, "TC", 0.0, allow_motion=True)
        _sleep(ctx, 0.4 - PRE_ROLL_S - PROBE_T_S + 0.02)
        rec = _record_fetch(ctx)
        _seg(ctx, "idle")
        k_a_probe, vpk, a_on, moved = _probe_ka(ctx, rec, i_probe)
        ctx.evidence.setdefault("probe", []).append(
            {"i_a": i_probe, "k_a_probe": k_a_probe, "v_peak": vpk,
             "slope_on": a_on, "moved": moved, "dt": rec_dt})
        if moved and k_a_probe > 0:
            break
        if attempt == 0:
            i_probe = min(2.0 * i_probe, 0.2 * ctx.cl1)
            ctx.warnings.append("프로브 v̇≈0 — 전류 ×2 재시도 (%.2fA)" % i_probe)
            continue
        raise AbortError("정지마찰 과대 — 프로브 무이동 (I=%.2fA)" % i_probe)
    _emit(ctx, "PROBE", "프로브 K_a=%.3g cnt/s²/A (on/off 2기울기, 마찰보정)" % k_a_probe)

    # ---- B2 pulse sizing ----------------------------------------------------------------
    i0 = min(p.i_pulse_frac * ctx.cl1, 0.2 * ctx.cl1)
    target_cnt = ctx.ca18 * p.tp_target_rpm / 60.0
    tp = min(max(target_cnt / (k_a_probe * i0), TP_MIN_S), TP_MAX_S)
    rev_est = (k_a_probe * i0) * tp * tp / ctx.ca18   # ~both pulses combined
    ctx.evidence["sizing"] = {"i0_a": i0, "tp_s": tp, "rev_est": rev_est,
                              "k_a_probe": k_a_probe}
    _emit(ctx, "SIZING", "본펄스 I0=%.2fA Tp=%.0fms, 예상회전≈%.2f rev/런"
          % (i0, tp * 1e3, rev_est))

    # ---- C1/C2 pulse-pair runs (G2 friction-ratio retry: once) -------------------------
    runs = None
    for sizing_try in (0, 1):
        runs = []
        for first_sign in (+1.0, -1.0):
            for m_try in (0, 1):                 # §9: 모션부족 적응 재시도 1회
                _seg(ctx, "tc")
                dur = 2 * tp + 0.4
                _record_start(ctx, dur)
                _sleep(ctx, PRE_ROLL_S)
                _write(ctx, "TC", first_sign * i0, allow_motion=True)
                _sleep(ctx, tp)
                _write(ctx, "TC", -first_sign * i0, allow_motion=True)
                _sleep(ctx, tp)
                _write(ctx, "TC", 0.0, allow_motion=True)
                _sleep(ctx, dur - PRE_ROLL_S - 2 * tp + 0.02)
                rec = _record_fetch(ctx)
                _seg(ctx, "idle")
                vpk_run = float(np.max(np.abs(rec["v"])))
                if vpk_run < ctx.ca18 * MOTION_MIN_RPM / 60.0:
                    if m_try == 0:
                        i0 = min(2.0 * i0, 0.4 * ctx.cl1)
                        ctx.warnings.append("모션부족(v_pk=%.0f<%.0frpm) — I0 ×2"
                                            " 재시도(%.2fA)" % (vpk_run,
                                                               MOTION_MIN_RPM, i0))
                        continue
                    raise AbortError("모션부족 — I0=%.2fA에도 v_pk=%.0f cnt/s <"
                                     " %.0frpm (관성/마찰 과대 의심)"
                                     % (i0, vpk_run, MOTION_MIN_RPM))
                runs.append(_analyze_pulse_run(ctx, rec, i0, first_sign))
                break
        fr_num = runs[0]["b_reg"] * abs(runs[0]["v_peak"]) + runs[0]["i_c_reg"]
        friction_ratio = fr_num / i0 if i0 else float("inf")
        if friction_ratio <= FRICTION_RATIO_MAX or sizing_try == 1:
            break
        i0 = min(1.5 * i0, 0.2 * ctx.cl1)
        ctx.warnings.append("마찰비 %.2f>%.1f — I0 증액 재시도(%.2fA)"
                            % (friction_ratio, FRICTION_RATIO_MAX, i0))
    ctx.evidence["pulse_runs"] = runs
    k_a = 0.5 * (runs[0]["k_a_diff"] + runs[1]["k_a_diff"])
    _emit(ctx, "IDENT_KA", "K_a=%.4g cnt/s²/A (±펄스 차분, 런2회 평균)" % k_a)

    # ---- D1 JV steady states (method B friction + rotating commutation check) ---------
    jv_pts = []
    stop_cnt = ctx.ca18 * JV_STOP_RPM / 60.0
    for rpm in list(p.jv_speeds_rpm) + [-x for x in p.jv_speeds_rpm]:
        jv = ctx.ca18 * rpm / 60.0
        _seg(ctx, "jv")
        _write(ctx, "JV", jv, allow_motion=True)
        _sleep(ctx, JV_SETTLE_S)
        _seg(ctx, "jv")                              # re-arm timebox per point
        _record_start(ctx, JV_RECORD_S)
        _sleep(ctx, JV_RECORD_S + 0.02)
        rec = _record_fetch(ctx)
        i_ss = float(np.mean(rec["i"]))
        v_ss = float(np.mean(rec["v"]))
        jv_pts.append({"rpm": rpm, "jv_cnt_s": jv, "v_ss": v_ss, "i_ss": i_ss})
        if v_ss * jv <= 0:
            raise AbortError("JV 커뮤검증 실패: sign(v) ≠ sign(JV) @%.0frpm" % rpm)
        if abs(i_ss) > 0.10 * ctx.cl1:
            raise AbortError("JV 무부하전류 과대 |I_ss|=%.2fA > %.2fA @%.0frpm"
                             % (abs(i_ss), 0.10 * ctx.cl1, rpm))
    _write(ctx, "JV", 0.0, allow_motion=True)
    _cmd(ctx, "ST", allow_motion=True)
    waited = 0.0
    while True:
        vx = _cmd(ctx, "VX")
        if isinstance(vx, (int, float)) and abs(vx) < stop_cnt:
            break
        if waited >= JV_STOP_TIMEOUT_S:
            raise AbortError("JV 정지 대기 실패 (|VX|=%.0f)" % abs(vx))
        _sleep(ctx, 0.05)
        waited += 0.05
    _seg(ctx, "idle")
    for k in range(len(p.jv_speeds_rpm)):            # +-same-speed asymmetry <= x2
        ip = abs(jv_pts[k]["i_ss"])
        im = abs(jv_pts[k + len(p.jv_speeds_rpm)]["i_ss"])
        lo, hi = min(ip, im), max(ip, im)
        if lo > 1e-3 and hi / lo > 2.0:
            raise AbortError("JV 전류 비대칭 ×%.1f (>2) @±%.0frpm — 커뮤/기구 확인"
                             % (hi / lo, p.jv_speeds_rpm[k]))
    A = np.array([[q["v_ss"], float(np.sign(q["v_ss"]))] for q in jv_pts])
    y = np.array([q["i_ss"] for q in jv_pts])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    b_jv, i_c_jv = float(coef[0]), float(coef[1])
    ctx.evidence["jv"] = {"points": jv_pts, "b_jv": b_jv, "i_c_jv": i_c_jv}
    _emit(ctx, "IDENT_FRICTION", "B=%.3g A/(cnt/s), I_c=%.3fA (JV 정상상태 피팅)"
          % (b_jv, i_c_jv))

    # ---- E1 de-energize + restore limits ------------------------------------------------
    _cmd(ctx, "MO=0")
    ctx.motor_on = False
    _restore_limits(ctx)

    # ---- E2 design + gates G1..G4 -------------------------------------------------------
    b_final, i_c_final = b_jv, i_c_jv               # method B = adopted friction
    d_visc = k_a * b_final
    des = design_vp_gains(k_a, d_visc, ctx.ts_s, p, kp1, ki1)
    ctx.evidence["design"] = {"iters": des["iters"], "wcv_ts_cal": WCV_TS_CAL,
                              "beta": BETA_VEL, "delta": DELTA_POS,
                              "calibration_note":
                                  "0.04575/6.805/5.369는 이 드라이브 EAS 단일점"
                                  " 캘리브레이션(SPEC §3 정직표기) — KI[2]/KP[3]"
                                  " 오라클일치는 구성상 자동(증거 아님)"}

    gates = {}
    ka_reg_mean = 0.5 * (runs[0]["k_a_reg"] + runs[1]["k_a_reg"])
    g1a = abs(ka_reg_mean / k_a - 1.0) if k_a else float("inf")
    gates["G1a_diff_vs_reg"] = {"dev": g1a, "tol": G1A_TOL, "pass": g1a <= G1A_TOL}
    g1b = abs(runs[0]["k_a_diff"] / runs[1]["k_a_diff"] - 1.0) \
        if runs[1]["k_a_diff"] else float("inf")
    gates["G1b_run_repeat"] = {"dev": g1b, "tol": G1B_TOL, "pass": g1b <= G1B_TOL}
    g1c = max(abs(q["a_pos_2nd"] / q["slope_for_pos"] - 1.0)
              if q["slope_for_pos"] else float("inf") for q in runs)
    gates["G1c_pos_2nd"] = {"dev": g1c, "tol": G1C_TOL, "pass": g1c <= G1C_TOL}
    g1d = max(abs(q["int_v"] / q["d_pos"] - 1.0) if q["d_pos"] else float("inf")
              for q in runs)
    gates["G1d_intv_dpos"] = {"dev": g1d, "tol": G1D_TOL, "pass": g1d <= G1D_TOL}
    r2min = min(q["r2"] for q in runs)
    gates["G1e_window_r2"] = {"r2": r2min, "min": G1E_R2_MIN,
                              "pass": r2min >= G1E_R2_MIN}
    ic_reg_mean = 0.5 * (runs[0]["i_c_reg"] + runs[1]["i_c_reg"])
    g1f = abs(ic_reg_mean / i_c_jv - 1.0) if i_c_jv else float("inf")
    gates["G1f_frictionAB"] = {"dev": g1f, "tol": G1F_TOL, "pass": g1f <= G1F_TOL}

    fr_ratio = (b_final * abs(runs[0]["v_peak"]) + i_c_final) / i0
    g2_hard = (KA_RANGE[0] <= k_a <= KA_RANGE[1] and b_final >= 0
               and i_c_final >= 0)
    gates["G2_physical"] = {"k_a": k_a, "range": list(KA_RANGE), "b": b_final,
                            "i_c": i_c_final, "friction_ratio": fr_ratio,
                            "pass": bool(g2_hard
                                         and fr_ratio <= FRICTION_RATIO_MAX)}

    ff1 = ctx.readings.get("FF[1]")
    g3_ka = (abs(k_a * ff1 - 1.0)
             if isinstance(ff1, (int, float)) and ff1 > 0 else None)
    kp2_rd = ctx.readings.get("KP[2]")
    g3_kp2 = (abs(des["kp2"] / kp2_rd - 1.0)
              if isinstance(kp2_rd, (int, float)) and kp2_rd > 0 else None)
    g3_cfg = []
    for key, val in (("KI[2]", des["ki2"]), ("KP[3]", des["kp3"])):
        rd = ctx.readings.get(key)
        if isinstance(rd, (int, float)) and rd > 0:
            g3_cfg.append(abs(val / rd - 1.0))
    g3_ok = ((g3_ka is None or g3_ka <= G3_KA_TOL)
             and (g3_kp2 is None or g3_kp2 <= G3_KP2_TOL)
             and all(x <= G3_CFG_TOL for x in g3_cfg))
    gates["G3_oracle"] = {"ka_vs_1_over_ff1": g3_ka, "kp2_vs_drive": g3_kp2,
                          "cfg_devs": g3_cfg, "pass": bool(g3_ok),
                          "note": "실패=FF[1] 가정 반증 또는 관성 변경 (U-P1/A1)"}
    gates["G4_margins"] = {"margins": des["margins"], "pass": bool(des["ok"])}
    ctx.evidence["gates"] = gates
    ctx.evidence["g5_note"] = ("G5 검증런(F2)은 실기 사용자 액션 — 미실시,"
                               " 정직 스텁 (Phase-1 E4 패턴)")

    red_msgs = []                                    # RED gates (SPEC §5)
    if not gates["G1a_diff_vs_reg"]["pass"]:
        red_msgs.append("G1a 차분vs회귀 K_a %.0f%%>15%%" % (100 * g1a))
    if not gates["G1b_run_repeat"]["pass"]:
        red_msgs.append("G1b 런반복 %.0f%%>10%%" % (100 * g1b))
    if not gates["G1d_intv_dpos"]["pass"]:
        red_msgs.append("G1d ∫v vs ΔPos %.1f%%>5%% (dt 신뢰불가)" % (100 * g1d))
    if not g2_hard:
        red_msgs.append("G2 물리성 위반 (K_a/B/I_c 범위·부호)")
    if not des["ok"]:
        red_msgs.append("G4 안정도 게이트 실패 (wcv 3회 감축 후)")
    if red_msgs:
        res = _red(ctx, "; ".join(red_msgs))
        res.k_a, res.b_visc, res.i_c = k_a, b_final, i_c_final
        return res
    if not gates["G1c_pos_2nd"]["pass"]:             # YELLOW gates
        ctx.warnings.append("G1c 위치2차 vs 속도기울기 %.0f%%>10%%" % (100 * g1c))
    if not gates["G1e_window_r2"]["pass"]:
        ctx.warnings.append("G1e 창 피팅 R²=%.3f<0.98" % r2min)
    if not gates["G1f_frictionAB"]["pass"]:
        ctx.warnings.append("G1f A-B 마찰 %.0f%%>30%%" % (100 * g1f))
    if fr_ratio > FRICTION_RATIO_MAX:
        ctx.warnings.append("G2 마찰비 %.2f>%.1f (증액 후에도)"
                            % (fr_ratio, FRICTION_RATIO_MAX))
    if not g3_ok:
        ctx.warnings.append("G3 오라클 이탈 — FF[1] 가정 반증 또는 관성 변경")

    status = YELLOW if ctx.warnings else GREEN
    m = des["margins"]
    _emit(ctx, "DESIGN", "KP[2]=%.4g KI[2]=%.3fHz KP[3]=%.2f | 속도 PM=%.1f° GM=%.1fdB"
          % (des["kp2"], des["ki2"], des["kp3"], m["pm_vel"], m["gm_db"] or -1))
    _emit(ctx, "DONE", "Phase2 측정 완료 — %s (적용은 별도 F1, 검증런 F2)" % status)
    return AutotuneVPResult(
        status=status,
        reason="" if status == GREEN else "; ".join(ctx.warnings),
        kp_vel=des["kp2"], ki_vel_hz=des["ki2"], kp_pos=des["kp3"],
        ff1_advisory=1.0 / k_a if k_a else None,
        k_a=k_a, b_visc=b_final, i_c=i_c_final, d_inv_s=d_visc,
        wcv_rad_s=des["wcv"], pm_vel_deg=m["pm_vel"], gm_db=m["gm_db"],
        pm_pos_deg=m["pm_pos"], ts_us=int(ts),
        evidence=ctx.evidence, warnings=ctx.warnings)


# ======================================================================================
# F1 / F2 — separate operator actions
# ======================================================================================
def apply_gains_vp(link, result: AutotuneVPResult, persist: bool = False):
    """F1: write KP[2]/KI[2]/KP[3] from a GREEN/YELLOW result (MO must be 0).
    FF[1] is NEVER written (advisory only).  SV only on explicit persist."""
    if result is None or result.status not in (GREEN, YELLOW) \
            or result.kp_vel is None:
        return False, "적용 불가: 결과 상태 %s" % (result.status if result else None)
    try:
        if _to_num(link.command("MO")) == 1:
            return False, "모터 ON(MO=1) — STOP 후 적용"
        link.command("KP[2]=%.9g" % result.kp_vel)
        link.command("KI[2]=%.9g" % result.ki_vel_hz)
        link.command("KP[3]=%.9g" % result.kp_pos)
        if persist:
            link.command("SV")
        return True, "KP[2]=%.4g KI[2]=%.4g KP[3]=%.4g 적용%s (FF[1] 미변경)" % (
            result.kp_vel, result.ki_vel_hz, result.kp_pos,
            " + SV" if persist else "")
    except Exception as e:
        return False, "적용 실패: %s" % e


def verify_run_vp(link):
    """F2 stub: JV-step verification (overshoot<=15%, settle<=60 ms, no ring,
    idx8 tracking — SPEC G5).  NOT implemented headless — requires live
    hardware; returns an honest RED placeholder (Phase-1 E4 pattern)."""
    return AutotuneVPResult(
        status=RED,
        reason="F2 검증런 미구현 — 실기 사용자 액션 대기 (SPEC §6 F2/G5)",
        evidence={"todo": "B0 재통과 + JV스텝 cnt(300rpm) 기록 + G5 판정"})
