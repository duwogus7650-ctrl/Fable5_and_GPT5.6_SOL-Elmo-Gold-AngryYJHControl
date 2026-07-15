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
from dataclasses import dataclass, field, replace as _dc_replace
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
UNITDIAG_I_A = 0.5        # diagnostic pulse current FLOOR [A] — the actual pulse
                          # uses the breakaway-adapted current (up to 0.2*CL[1]);
                          # the old "636rpm<1200" sizing held only for fixed
                          # 0.5 A: overspeed is now owned by the EARLY-STOP below
UNITDIAG_T_S = 0.08       # host-timed pulse duration (dt discriminant reference)
UNITDIAG_EARLYSTOP_RPM = 500.0  # hardening #2: cut the diag pulse when |VX|
                          # crosses this (adaptive i_diag + low RUNNING friction
                          # can reach the 1200 rpm guard within 80 ms); residual
                          # rise ~a*30ms stays under the guard for i<=0.2*CL[1]
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
MAINPULSE_STOP_FRAC = 0.6   # main-pulse motion early-stop at 0.6*guard
                          # (fable-critic MEDIUM: real serial latency makes the
                          # effective poll period ~2x — normal sizing rises
                          # 400..1100 rpm per REAL poll, so the cut->guard band
                          # must be wide; the sizing TARGET is clamped below
                          # the cut so correct pulses are never truncated)
PULSE_TARGET_CAP_FRAC = 0.5  # effective sizing target <= 0.5*cut (=360 rpm):
                          # target must sit UNDER the runtime cut by margin
                          # (fable-physics 2026-07-14: 0.8 let the FAST(+)
                          # direction graze the 720 rpm cut while the slow(-)
                          # direction didn't -> cut asymmetry polluted the +-
                          # difference; 0.5 absorbs the probe's one-direction
                          # sizing optimism so BOTH pulses stay cut-free)
PULSE_CUT_POLL_S = 0.01   # VX-only cut poll during main pulses (10 ms: worst
                          # per-poll rise stays under the cut->guard band)
# --- raised-cap ramp (fable-physics 2026-07-13: live unit shows NO breakaway
# at 0.2*CL=4.24 A -> i_ba>4.24 A confirmed; cap raised to 0.4*CL=8.49 A for
# THIS unit via params.ramp_frac=0.4; the DEFAULT stays 0.2 for bare motors) --
RAMP_FRAC_ABS_MAX = 0.4   # automatic ramp/pulse current ceiling [frac of CL[1]]
RAMP_FRAC_OPERATOR_ONLY = 0.6   # NEVER automatic — operator-approved sessions
                          # may edit this constant deliberately (자동 램프 금지)
RAMP_FAST_POLL_ABOVE_A = 2.0    # above this TC: VX-only polls at 10 ms (the
                          # 30 ms PX+VX pair costs ~60 ms real period; a
                          # high-current snap grows ~2700 rpm in 2 polls)
RAMP_FAST_POLL_S = 0.01
HOLD_INSTANT_GUARD_FRAC = 0.25  # HOLD: |VX| >= 0.25*guard (300 rpm) confirms
                          # in ONE poll (closes the 150 ms window hole where a
                          # high-current breakaway could reach 3300 rpm)
# --- HOLD sustain AND-rule (fable-physics 개정6: live i_ba=1.33 A was FAKE —
# backlash free flight with MONOTONICALLY DECAYING velocity 89k->68k->55k->6k;
# magnitude-only sustain (vx>3k x3) passed a dissipating transit) -------------
HOLD_POLLS_MAX = 15       # extended confirm window (450 ms) — a PROMISING
                          # (non-decaying) slow breakaway may need ~8 polls to
                          # accumulate the travel proof; a transit CANNOT
                          # (its travel is bounded by the free play)
SUSTAIN_VX_END_FRAC = 0.5  # sustain/collapse split: vx_now vs HOLD-max vx
                          # (live retrofit: 6k/89k = 0.07 -> stall, correct)
WINDUP_CNT_PER_A = 60.0   # elastic windup model [cnt/A] (fable-physics)
UNITDIAG_END_V_MIN = 3000.0  # pulse-end POSITION-derived velocity floor
UNITDIAG_TAIL_S = 0.010   # tail-slope window (~10 ms LEAST-SQUARES — a 2-point
                          # 0.8 ms diff turns +-1.5 cnt position noise into
                          # >3000 cnt/s: module discipline "slopes by least
                          # squares, never point differences")
JV_NOLOAD_IBA_FRAC = 1.2  # D1 no-load current gate = max(0.10*CL, 1.2*i_ba):
                          # running friction is bounded above by the STATIC
                          # breakaway current i_ba (with margin for B*v) — the
                          # fixed 0.10*CL predates the i_ba>4.24 A field fact
                          # and would kill a geared run AFTER K_a succeeded
PULSE_FRAC_ABS_MAX = 0.4  # main-pulse i0 ceiling (0.2 cap RETIRED: a geared
                          # unit with i_ba>4.24 A cannot be measured at 2.12 A)
# --- commutation-degradation early detection (fable-physics 2026-07-14) ------
# Live incident: commutation established under CA[25]=1 left an offset error
# delta~75 deg e -> effective Kt x0.27 -> K_a collapsed 1.42e6 -> 3.82e5 and
# every LOCAL gate still passed on the polluted plant; the i0 floor riding up
# to 8.49 A (0.4*CL) was the fingerprint.  Advisories + a baseline drop gate:
HIGH_I0_WARN_FRAC = 0.25  # advisory: main-pulse i0 above this frac of CL[1]
IBA_COMMUT_WARN_A = 4.0   # advisory: breakaway current above this [A]
                          # (healthy S2 run: i_ba=2.03 A; polluted: >4.24 A —
                          # NEVER a hard stop: high i_ba alone is ambiguous)
KA_BASELINE_DROP_FRAC = 0.5     # HARD RED: K_a < 0.5 x last-GREEN baseline
KA_BASELINE_FILE = "autotune_ka_baseline.json"  # in params.snapshot_dir
SYNTHETIC_SUBDIR = "synthetic"  # quarantine for sim/smoke persistence
                                # (2026-07-14 incident x3: --smoke-velpos wrote
                                # its synthetic K_a 5.77e6 into the LIVE
                                # baseline; live healthy K_a=2.77e6 -> ratio
                                # 0.48 < 0.5 = the safety gate would FALSE-RED
                                # a healthy live run.  INVARIANT: only real-
                                # hardware runs may touch the live baseline/
                                # snapshots; a link with is_synthetic=True is
                                # auto-quarantined into this subdir)
NET_FRICTION_FRAC = 0.75  # tp sizing net current: i_net = i0 - 0.75*i_ba
WINDUP_LEVELS_A = (1.0, 2.0, 4.0, 6.0, 8.0)   # windup-curve capture currents
# --- PART B: UM=3 low-speed drag discrimination (commutation-agnostic) -------
UM3_DRAG_I_A = 6.0        # held stator current [A] (torque oracle ~Kt*6=0.72 N*m)
UM3_TICKS_PER_EREV = 512  # PA unit in UM=3: 512 ticks / electrical rev (CR)
UM3_EREV_PER_S = 1.0      # sweep rate ~1 elec rev/s = motor 1.4 rpm (guard-free)
UM3_REVS = 3              # per direction (motor 51 deg = output 1.7 deg)
UM3_STEP_S = 0.03         # PA step period
UM3_FOLLOW_MIN = 0.9      # follow ratio |dPX|/(revs*CA[18]/CA[19]) threshold
UM3_EARLY_CHECK_EREV = 0.5  # HIGH-2: effectiveness check point [elec rev]
UM3_EARLY_MIN_FRAC = 0.2  # PX response must exceed this frac of commanded travel
KT_NOMINAL = 0.12         # N*m/A — message annotation only, not a gate
# --- 2-LAYER COMMUTATION MODEL (fable-physics 확정 2026-07-14 — 오해 금지) ----
# 유효 전기각 δ = "전원 세션" 스코프의 RAM 상태다: 전원 사이클마다 재추첨되고
# (실측: 저장 파라미터 비트단위 동일(CA[7]/CA[25]/CA[54])인데 전원 1회로
# δ 0°→103°, i_ba 0.887→4.05 A·방향 반전), 같은 세션 내 MO 사이클엔 불변.
# CA[7]은 위저드 실행 "기록"일 뿐 커뮤를 결정하지 않는다.  CA[25]=1은 이
# 유닛에서 순기능이 실증된 적 없는 방향수리 잔재이자 전원 복권의 유력 원인
# (확립/복원 경로가 거울반전을 비일관 적용) — 절대 권하지 말 것.  CA[54]도
# 무관(패리티 레버 모델 폐기: 방향 반전은 sign(cos δ)였을 뿐).
DIR_FIX_MSG = ("수리 절차: ① 재커뮤테이션(EAS 위저드) → ② 서명 게이트 확인:"
               " i_ba=0.9±0.4A AND +TC→+dpx → ③ 불합격이면 재커뮤 반복"
               "(healthy 착지 ~17%/회) → ④ 서명 GREEN 전 폐루프(JV/조그/"
               "위치이동) 절대 금지 → ⑤ 전원 사이클하면 δ 재추첨 = ①부터."
               " (묵시적 부호보정 금지 — 반전 상태 게인 적용은 폭주)")
SEG_TIMEBOX_S = 5.0
TOTAL_BUDGET_S = 120.0
JV_SETTLE_S = 0.8
JV_RECORD_S = 0.5
JV_STOP_RPM = 30.0
JV_STOP_TIMEOUT_S = 2.0
DECEL_TAIL_S = 0.25       # post-pulse coast captured for the regression
# --- F2/G5 verification run (JV step-response acceptance, 2026-07-14) -------------------
# Acceptance authority = fable-physics live criteria; the SPEC §6 G5 numbers
# (overshoot<=15%, settle<=60 ms) are TIGHTER and demoted to YELLOW advisories
# with the delta reported (JV steps ride the AC/DC profiler on the real drive,
# so command-to-band settle can legitimately exceed 60 ms without a fault).
VERIFY_SPEEDS_RPM = (300.0, 900.0)   # ladder: next step only after a pass
VERIFY_RECORD_S = 0.6     # per-step capture FLOOR — the actual window is
                          # ADAPTIVE: max(this, t_ramp + VERIFY_SETTLE_TAIL_S)
                          # where t_ramp = |jv|/AC (live artifact 2026-07-14:
                          # AC=1e6 -> 900 rpm ramps 0.983 s > the old fixed
                          # 0.6 s window -> mid-ramp read as steady state,
                          # ramp slope read as sustained oscillation = 3
                          # phantom hard REDs; 300 rpm "settle 0.295 s" was
                          # in fact the profiler ramp 0.328 s, not the loop)
VERIFY_SETTLE_TAIL_S = 0.4    # post-ramp capture margin (steady evidence)
VERIFY_PRE_S = 0.05       # quiet pre-roll before the JV step
VERIFY_OVERSHOOT_MAX = 0.25   # HARD RED (design PM 68.4 deg expects ~5-10%)
VERIFY_OVERSHOOT_SPEC = 0.15  # SPEC §6 figure -> YELLOW advisory band
VERIFY_SETTLE_SPEC_S = 0.060  # SPEC §6 figure -> YELLOW advisory
VERIFY_SETTLE_MAX_S = 0.5     # HARD RED (loop is not doing its job)
VERIFY_BAND_FRAC = 0.05   # +-5% settle band
VERIFY_VSS_TOL = 0.05     # steady-state magnitude tolerance (HARD)
VERIFY_OSC_DECAY = 0.8    # steady-tail 2nd-half RMS must be <= 0.8x 1st half
VERIFY_OSC_FLOOR_FRAC = 0.02  # ...unless below 2% of v_ss (noise floor)
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
    probe_i_a: float = 0.25             # B1 probe current FLOOR/fallback [A amplitude]
    i_pulse_frac: float = 0.10          # I0 = frac*CL[1] (hard cap 0.2*CL[1])
    # --- B1.4 adaptive breakaway ramp (fable-physics 2026-07-13: the live
    # geared unit's stiction sits in (0.5, 2.12] A — fixed 0.5 A diag/probe
    # currents cannot move the rotor -> false '기계구속' RED on a healthy
    # axis.  The ramp finds i_ba = the actual breakaway current and sizes the
    # diag/probe current as clip(breakaway_k*i_ba, probe_i_a, ramp_frac*CL[1]).
    ramp_frac: float = 0.2              # ramp cap = ramp_frac*CL[1] (=4.24 A live)
    ramp_time_s: float = 2.0            # 0 -> cap ramp duration [s] (<= 2 s)
    poll_dt: float = 0.03               # ramp poll period [s]
    detect_dpx: float = 400.0           # |dPX| threshold [cnt] (> compliance windup)
    detect_vx: float = 3000.0           # |VX| threshold [cnt/s] (> velocity noise)
    breakaway_k: float = 1.5            # probe = clip(k*i_ba, probe_i_a, cap)
    # --- HOLD-CONFIRM (fable-physics 2026-07-13: live i_ba=1.01 A was a
    # BACKLASH TRAVERSAL false positive — free-play flight, total 4166 cnt =
    # 0.76 deg output; the true load breakaway is >1.52 A).  Physics
    # invariant: lash traversal is FINITE (<= free play), true breakaway is
    # UNBOUNDED under held torque.
    hold_window_polls: int = 5          # legacy min window (evidence only; the
                                        # AND-rule extends to HOLD_POLLS_MAX)
    sustain_dpx_cnt: float = 13000.0    # sustained-travel FLOOR [cnt] (개정6:
                                        # observed free-play envelope >=8634,
                                        # unit-dependent 2k..9k -> floor 13000;
                                        # effective thr = max(this, 2*lash실측)
    sustain_vx_consec: int = 3          # DEPRECATED (개정6): magnitude-only
                                        # consecutive-vx sustain passed decaying
                                        # transits — replaced by the AND-rule
    tp_target_rpm: float = 800.0        # Tp sizing target speed
    jv_speeds_rpm: Sequence[float] = (300.0, 900.0)
    rec_dt_s: float = 400e-6            # recorder sample time (tres = rec_dt/TS)
    wcv_override_hz: Optional[float] = None
    expected_ca17: int = 5              # commutation config guard (G0)
    # CA[7] is a PER-MOTOR commutation value (multi-motor workflow: the same
    # drive alternates between motors with different pole pairs) — a hardcoded
    # expectation false-alarms on every other motor.  Default None = no value
    # gate: CA[7] is recorded in evidence + emitted informationally only.
    # Commutation-CONFIG validity is owned by the motor-independent CA[17]==5
    # check.  Set a value explicitly to pin one motor (opt-in gate).
    expected_ca7: Optional[float] = None
    # --- injection points (headless tests replace sleep_fn with the sim clock) -------
    sleep_fn: Callable[[float], None] = time.sleep
    snapshot_dir: str = os.path.join(".omc", "state")
    # synthetic-run marker: None = auto-detect from link.is_synthetic (mock
    # drives set it True); True forces quarantine (snapshot_dir/synthetic for
    # ALL persistence); False asserts "this is real hardware" (baseline unit
    # tests use it against tmp dirs).  See SYNTHETIC_SUBDIR.
    synthetic: Optional[bool] = None
    # --- F2/G5 verification run -----------------------------------------------------
    verify_speeds_rpm: Sequence[float] = VERIFY_SPEEDS_RPM
    # unit-specific no-load steady-current window [A] (live: +0.477/+0.524 A);
    # None = generic 0.10*CL[1] hard gate only.  Outside the window = YELLOW
    # (friction drifts with temperature), above the hard gate = RED.
    verify_iss_expect_a: Optional[Sequence[float]] = None
    poll_s: float = 0.01
    progress_fn: Callable[[str, str], None] = _noop_progress
    cancel_fn: Callable[[], bool] = _never_cancel
    # --- host wall clock for the UNIT-DIAG pulse bracket (2026-07-13 fix:
    # poll_sleep serial round-trips stretch the REAL pulse to ~125 ms while
    # the nominal reference stays 80 ms -> the old g=0.08/(N*dt) would read
    # 0.64 and wrongly adopt a dt factor).  Default time.monotonic; sims
    # inject their own time base (lambda: sim.t).  The pulse duration used is
    # max(bracket, nominal): wall time can never be SHORTER than the requested
    # sleeps, so the nominal floor only engages when the clock is not
    # homogeneous with sleep_fn (un-injected sim) — recorded in evidence.
    clock_fn: Callable[[], float] = time.monotonic
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
    if not (isinstance(k_a, (int, float)) and math.isfinite(k_a) and k_a > 0):
        # 보강4 (fable-physics §3): a direction-reversed identification must
        # NEVER be sign-corrected into the gain design (wcv/K_a<0 -> negative
        # KP[2] -> runaway on a healthy drive).  Fix the direction first.
        raise ValueError("design_vp_gains: K_a는 양수여야 함 (방향 반전 식별의"
                         " 부호보정 유입 금지 — 재커뮤+서명 게이트 통과 후"
                         " 재식별): %r" % (k_a,))
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
        self.guard_vx_only = False      # fast windows: skip MF/LC serial reads
                                        # (fable-critic MEDIUM: the 3-read guard
                                        # costs ~45 ms real - VX alone keeps the
                                        # cut/latch latency inside the band)


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
    timebox, total budget -> abort.  guard_vx_only windows (pulse/HOLD/fast
    ramp) skip the MF/LC serial reads - the real latency of the 3-read guard
    (~45 ms) would blow the cut->guard margin; MF/LC coverage resumes at the
    next normal window (fire-safe: HL[2]/limits backstop stays armed)."""
    if not ctx.guard_vx_only:
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


def _size_tp(k_a_probe: float, i0: float, target_cnt: float) -> float:
    """Pulse-length sizing tp = clip(target/(K_a_probe*i0), TP_MIN, TP_MAX).
    MUST be recomputed on EVERY i0 change (HIGH fix 2026-07-13: the motion
    retry doubled i0 while keeping the old tp -> v_pk doubled past the
    1200 rpm guard -> false RED; conservative: true peak = K_a*(i0-I_c)*tp
    < target since the probe K_a is friction-corrected)."""
    return min(max(target_cnt / (k_a_probe * i0), TP_MIN_S), TP_MAX_S)


def _i_net(i0: float, i_ba) -> float:
    """Net accelerating current for tp sizing (fable-physics cap-raise): the
    load friction absorbs ~NET_FRICTION_FRAC*i_ba of the commanded current on
    a geared unit, so the speed prediction must use i_net = i0 - 0.75*i_ba
    (floored at 0.25*i0 so a near-friction i0 sizes to TP_MAX instead of
    diverging).  i_ba unknown -> i0 unchanged (bare-motor behavior)."""
    if isinstance(i_ba, (int, float)) and i_ba > 0:
        return max(i0 - NET_FRICTION_FRAC * float(i_ba), 0.25 * i0)
    return i0


def _pulse_sleep_with_cut(ctx: _Ctx, dur_s: float, vx_cut_cnt: float) -> bool:
    """Sleep dur_s in 30 ms polls; True when |VX| crossed vx_cut_cnt (motion
    early-stop, UNIT-DIAG pattern extended to the MAIN pulses — HIGH fix:
    any mis-sized pulse is cut before the overspeed guard and analyzed from
    the captured window; a correctly sized pulse never reaches the cut)."""
    remaining = float(dur_s)
    prev_mode = ctx.guard_vx_only
    ctx.guard_vx_only = True            # MEDIUM: no MF/LC serial reads inside
    try:                                # the cut window (latency guard band)
        while remaining > 1e-9:
            step = min(PULSE_CUT_POLL_S, remaining)
            _sleep(ctx, step)
            remaining -= step
            vx = _cmd(ctx, "VX")
            if isinstance(vx, (int, float)) and abs(vx) > vx_cut_cnt:
                return True
        return False
    finally:
        ctx.guard_vx_only = prev_mode


def _wait_rest(ctx: _Ctx, timeout_s: float = 5.0):
    """Wait for the rotor to be at TRUE standstill before the next TC stage.

    Companion of the UNIT-DIAG early-stop (hardening #2) and precondition of
    the escalation ladder (2026-07-13 bug fix): STATIC friction only gates a
    pulse that starts from rest — a rotor still creeping at "under 30 rpm"
    rides on RUNNING friction and sails through a stiction level it could
    never break from standstill (false escalation-success class).  Rest is
    therefore confirmed by BOTH witnesses, twice in a row:
      |VX| < 30 rpm  AND  per-poll |dPX| < detect_dpx (position stable).
    The PX witness keeps demanding until the actual speed is well below the
    VX threshold (30 rpm = 32768 cnt/s would still travel 1638 cnt per 50 ms
    poll), after which Coulomb friction sticks the rotor within milliseconds.
    Nominal plants pass after ~3 polls."""
    stop_cnt = ctx.ca18 * JV_STOP_RPM / 60.0
    px_prev = None
    ok = 0
    waited = 0.0
    while waited < timeout_s:
        vx = _cmd(ctx, "VX")
        px = _cmd(ctx, "PX")
        px_f = float(px) if isinstance(px, (int, float)) else None
        vx_ok = not isinstance(vx, (int, float)) or abs(vx) < stop_cnt
        dpx = (abs(px_f - px_prev)
               if px_f is not None and px_prev is not None else None)
        # position evidence required from the 2nd poll on (unless PX is
        # unreadable, in which case VX is the only witness available)
        px_ok = (dpx is not None and dpx < ctx.params.detect_dpx) \
            or (px_f is None)
        px_prev = px_f
        ok = ok + 1 if (vx_ok and px_ok) else 0
        if ok >= 2:
            return
        _sleep(ctx, 0.05)
        waited += 0.05
    raise AbortError("펄스 후 정지 대기 실패 (%.0fs) — 회전 잔존" % timeout_s)


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


def _record_start(ctx: _Ctx, duration_s: float, tres_override: Optional[int] = None,
                  extra_names: Optional[Sequence[str]] = None):
    """Arm the free-running recorder for `duration_s` (tres from rec_dt; the
    UNIT-DIAG passes tres_override=1 for the Phase-1-verified dt=TS base).
    extra_names: optional additional personality channels (windup-curve
    companion capture) — the 16384-total-sample cap scales with the count."""
    names = _rec_names(ctx) + list(extra_names or [])
    if tres_override is not None:
        tres = int(tres_override)
    else:
        tres = max(1, int(round(ctx.params.rec_dt_s / ctx.ts_s)))
    length = int(math.ceil(duration_s / (tres * ctx.ts_s)))
    cap = 16384 // max(4, len(names))           # per-signal cap -> coarser dt
    while length > cap:                         # SPEC §6 edge: tres fallback
        tres *= 2
        length = int(math.ceil(duration_s / (tres * ctx.ts_s)))
    fn = getattr(ctx.link, "record_start", None)
    if not callable(fn):
        raise AbortError("링크에 record_start() 없음 — 레코더 분리 래퍼 필요")
    try:
        fn(names, length, time_resolution=tres)
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
    base = {ctx.sig["vel"], ctx.sig["pos"], ctx.sig["cur"], ctx.sig["icmd"],
            "dt"}
    extras = {k: np.asarray(a, float) for k, a in out.items() if k not in base}
    return {"v": v * ctx.s_scale, "v_raw": v, "p": p, "i": i, "icmd": icmd,
            "dt": float(dt) * ctx.g_dt, "extras": extras}


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
        # CR p175: JV latches on BG — make the zero command effective (decel)
        # BEFORE ST; ST stays the authoritative stop right after (U-P6)
        _try("A1a BG", lambda: ctx.link.command("BG", timeout_ms=1000,
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
    if "UM" in set(ctx.dirty) and "UM" in ctx.snapshot:
        # PART B wrote UM=3 for the drag oracle: ALWAYS restore the snapshot
        # mode (double cover with the drag's own finally-restore)
        _try("A_um UM=%s 복원" % ctx.snapshot["UM"],
             lambda: ctx.link.command("UM=%s" % _fmt(ctx.snapshot["UM"]),
                                      timeout_ms=1000))
    _try("A_lim restore", lambda: _restore_limits(ctx))
    ctx.evidence["abort"] = {"reason": reason, "segment": ctx.segment,
                             "steps_done": steps}


def _red(ctx: _Ctx, reason: str) -> AutotuneVPResult:
    ctx.evidence.setdefault("readings", ctx.readings)
    return AutotuneVPResult(status=RED, reason=reason,
                            ts_us=ctx.readings.get("TS"),
                            evidence=ctx.evidence, warnings=ctx.warnings)


# ======================================================================================
# K_a baseline (commutation-degradation early gate, fable-physics 2026-07-14)
# ======================================================================================
def _ka_baseline_path(ctx: _Ctx) -> str:
    return os.path.join(ctx.params.snapshot_dir, KA_BASELINE_FILE)


def _load_ka_baseline(ctx: _Ctx):
    """Last-GREEN K_a for THIS unit, or None (fail-open: no file / bad file
    just skips the gate — the baseline is an extra tripwire, never a lock)."""
    try:
        with open(_ka_baseline_path(ctx), encoding="utf-8") as f:
            d = json.load(f)
        v = d.get("k_a")
        return float(v) if isinstance(v, (int, float)) and v > 0 else None
    except Exception:
        return None


def _save_ka_baseline(ctx: _Ctx, k_a: float):
    """Persist the K_a fingerprint — called ONLY on a GREEN finish (RED and
    YELLOW runs never re-baseline; oracle discipline)."""
    try:
        os.makedirs(ctx.params.snapshot_dir, exist_ok=True)
        with open(_ka_baseline_path(ctx), "w", encoding="utf-8") as f:
            json.dump({"k_a": k_a, "ts_us": ctx.readings.get("TS"),
                       "t": time.time(),
                       "note": "마지막 GREEN 런의 K_a [cnt/s²/A] — 커뮤 열화"
                               " 조기검출 기준 (RED/YELLOW 런은 갱신 금지)"},
                      f, ensure_ascii=False, indent=1)
        ctx.evidence.setdefault("ka_baseline", {})["saved_path"] = \
            _ka_baseline_path(ctx)
    except Exception as e:
        # post-status: must NOT mutate warnings (status already gated)
        ctx.evidence["ka_baseline_save_error"] = repr(e)


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
        raise AbortError("방향 반전(유효-역방향 커뮤테이션) — sign(v̇)≠sign(TC),"
                         " 즉시 중단. " + DIR_FIX_MSG)
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


def _um3_drag(ctx: _Ctx):
    """PART B (fable-physics §4): UM=3 low-speed drag discrimination — a
    COMMUTATION-AGNOSTIC torque oracle, run only when the raised-cap ramp
    still finds no breakaway with real torque.

    UM=3 (stepper) commands the stator angle directly, bypassing the
    commutation mapping entirely (Phase-1 injected 10.6 A this way), so a
    held TC=6 A guarantees ~Kt*6 = 0.72 N*m at the shaft regardless of CA[7].
    PA is swept in ELECTRICAL ticks (512/elec rev, CR :15742-15745), INTEGER
    values (CR :12471), and each PA is armed with BG (CR :12476 "Effective on
    the next call to BG"; harmless if the write were immediate) — ~1 elec
    rev/s nominal = motor 1.4 rpm (guard-irrelevant), UM3_REVS per direction
    (motor 51 deg = output 1.7 deg).  BG runs the PTP profiler (SP/AC/DC), so
    the 1 rev/s rate is NOT guaranteed — and PA may be clipped by the
    VH[3]/VL[3]/HL[3]/LL[3] soft limits (live probe: all 0!).  Therefore an
    EARLY EFFECTIVENESS CHECK is mandatory (fable-critic HIGH-2): at ~0.5
    elec rev into the FIRST direction the PX response must exceed
    UM3_EARLY_MIN_FRAC of the commanded travel, else pa_effective=False is
    returned and the caller must raise the honest "판별 불가" RED — NEVER a
    mechanical verdict (a dead stator angle and a stuck axis are headless-
    indistinguishable).  follow = |dPX| / (revs * CA[18]/CA[19]), min of both
    directions.  UM is restored in the normal path AND by the abort chain.
    Returns the evidence dict or None when CA[19] is unreadable."""
    ca19 = ctx.readings.get("CA[19]")
    if not isinstance(ca19, (int, float)) or ca19 <= 0:
        ctx.warnings.append("CA[19] 판독불가(%r) — UM3 드래그 판별 생략" % (ca19,))
        return None
    cnt_per_erev = ctx.ca18 / float(ca19)
    _emit(ctx, "BREAKAWAY", "UM3 저속 드래그 판별: TC=%.1fA 고정, PA %d elec rev/방향"
          " (~%.1f rpm, 출력 ≈1.7°) — 커뮤 무관 토크 오라클"
          % (UM3_DRAG_I_A, UM3_REVS, UM3_EREV_PER_S * 60.0 / float(ca19)))
    _cmd(ctx, "MO=0")
    ctx.motor_on = False
    _write(ctx, "UM", 3)
    ev = {"i_drag_a": UM3_DRAG_I_A, "cnt_per_erev": cnt_per_erev,
          "revs_per_dir": UM3_REVS, "threshold": UM3_FOLLOW_MIN,
          "directions": []}
    ctx.evidence["um3_drag"] = ev
    try:
        _cmd(ctx, "MO=1", allow_motion=True)
        ctx.motor_on = True
        _seg(ctx, "tc")
        _write(ctx, "TC", UM3_DRAG_I_A, allow_motion=True)
        _sleep(ctx, 0.3)                # align snap (<= half elec pitch) + settle
        # NOTE: even the PA READ passes the motion-gated prefix filter
        # (prefix "PA") — allow_motion on a pure query is harmless
        pa_rd = _cmd(ctx, "PA", allow_motion=True)
        pa = float(pa_rd) if isinstance(pa_rd, (int, float)) else 0.0
        follows = []
        ev["pa_effective"] = True
        for d_idx, sign in enumerate((+1.0, -1.0)):
            _seg(ctx, "tc")             # re-arm the 5 s timebox per direction
            px_a = _cmd(ctx, "PX")
            px_a_f = float(px_a) if isinstance(px_a, (int, float)) else None
            ticks_total = UM3_REVS * UM3_TICKS_PER_EREV
            n = max(1, int(math.ceil(UM3_REVS / UM3_EREV_PER_S / UM3_STEP_S)))
            k_early = max(1, int(math.ceil(
                n * UM3_EARLY_CHECK_EREV / UM3_REVS)))
            trace = []
            for k in range(1, n + 1):
                pa_t = pa + sign * ticks_total * k / n
                # CR :12471/:12476 — PA is an INTEGER and takes effect on BG
                # (BG is harmless if the drive applied PA immediately)
                _write(ctx, "PA", int(round(pa_t)), allow_motion=True)
                _cmd(ctx, "BG", allow_motion=True)
                _sleep(ctx, UM3_STEP_S)
                if k % 8 == 0:          # 지령각-PX 추종 시계열 (decimated)
                    pxk = _cmd(ctx, "PX")
                    if isinstance(pxk, (int, float)):
                        trace.append((round(pa_t - pa, 1), round(float(pxk), 1)))
                if d_idx == 0 and k == k_early:
                    # EARLY EFFECTIVENESS CHECK (HIGH-2): no PX response by
                    # 0.5 elec rev commanded -> the discrimination premise is
                    # broken (PA/BG not effective? soft-limit clip? OR truly
                    # stuck — indistinguishable) -> abort the sweep honestly
                    pxe = _cmd(ctx, "PX")
                    resp = (abs(float(pxe) - px_a_f)
                            if isinstance(pxe, (int, float))
                            and px_a_f is not None else 0.0)
                    ev["early_px_response_cnt"] = round(resp, 1)
                    ev["early_expected_cnt"] = round(
                        UM3_EARLY_CHECK_EREV * cnt_per_erev, 1)
                    if resp < UM3_EARLY_MIN_FRAC * UM3_EARLY_CHECK_EREV                             * cnt_per_erev:
                        ev["pa_effective"] = False
                        ev["directions"].append(
                            {"sign": sign, "aborted_at_erev":
                             UM3_EARLY_CHECK_EREV, "trace_pa_px": trace})
                        return ev
            pa += sign * ticks_total
            px_b = _cmd(ctx, "PX")
            dpx = (abs(float(px_b) - float(px_a))
                   if isinstance(px_a, (int, float))
                   and isinstance(px_b, (int, float)) else 0.0)
            expected = UM3_REVS * cnt_per_erev
            follow = dpx / expected if expected else 0.0
            follows.append(follow)
            ev["directions"].append({"sign": sign, "dpx_cnt": round(dpx, 1),
                                     "expected_cnt": round(expected, 1),
                                     "follow": round(follow, 3),
                                     "trace_pa_px": trace})
            _sleep(ctx, 0.2)
        ev["follow_ratio"] = round(min(follows), 3)   # both directions must follow
        return ev
    finally:
        _seg(ctx, "idle")
        try:
            ctx.link.command("TC=0", timeout_ms=1000, allow_motion=True)
        except Exception:
            pass
        try:
            ctx.link.command("MO=0", timeout_ms=1000)
            ctx.motor_on = False
            ctx.link.command("UM=%s" % _fmt(ctx.snapshot.get("UM", 5)),
                             timeout_ms=1000)
        except Exception as e:
            ctx.warnings.append("UM3 드래그 종료 복원 실패(%s) — abort 체인이"
                                " UM 복원 재시도" % e)


def _drag_route(ctx: _Ctx, i_cap: float):
    """PART B router (fable-critic HIGH-1/HIGH-2): run the UM=3 drag oracle
    and raise the routed honest RED.

    GATE: only meaningful when i_cap >= UM3_DRAG_I_A — the discrimination
    logic needs cap torque >= drag torque, otherwise the 6 A drag exceeds the
    cap torque and ALWAYS follows, mis-routing healthy mechanical friction to
    a commutation RED.  Gate unmet / CA[19] unreadable / drag exception ->
    returns None (caller raises its own generic verdict, marked 판별 유보).

    Verdicts (전류 증액 금지):
      pa_effective False -> "판별 불가" (a dead stator command and a stuck
        axis are indistinguishable — NEVER claim mechanical);
      follow >= 0.9      -> commutation torque-efficiency RED;
      else               -> mechanical-friction RED, honestly labeled
        "슬립 또는 PA 미실효" (partial follow proved PA works early on,
        but 실기 특성화 still owns the final word)."""
    if i_cap < UM3_DRAG_I_A:
        return None
    drag = None
    try:
        drag = _um3_drag(ctx)
    except (AbortError, PermissionError):
        raise
    except Exception as e:                  # never mask the primary finding
        ctx.warnings.append("UM3 드래그 실험 예외(%r) — 판별 없이 진행" % (e,))
    if not drag:
        return None
    if not drag.get("pa_effective", True):
        raise AbortError(
            "UM3 드래그: PA 지령 실효 미확인 — 초기 %.1f elec rev에 PX 응답"
            " %.0fcnt(<%.0f%%·기대 %.0fcnt): 판별 불가 (기계구속 단정 금지;"
            " PA/BG 실효·VH[3]/HL[3] 소프트리밋=0 실기 특성화 필요)"
            % (UM3_EARLY_CHECK_EREV, drag.get("early_px_response_cnt", 0.0),
               100 * UM3_EARLY_MIN_FRAC, drag.get("early_expected_cnt", 0.0)))
    if drag.get("follow_ratio", 0.0) >= UM3_FOLLOW_MIN:
        raise AbortError(
            "UM3 드래그 추종(%.2f≥%.1f): 기계는 ≤%.2fN·m로 구동됨 — UM=5"
            " %.2fA로 브레이크어웨이 실패 = 커뮤테이션 토크효율<70%% 의심:"
            " 재커뮤테이션 후 서명 게이트(i_ba 0.9±0.4A·방향+) 확인, 불합격시"
            " 재커뮤 반복 (전류 더 올리지 말 것; CA[7]은 위저드 기록일 뿐"
            " 커뮤 결정자 아님)"
            % (drag["follow_ratio"], UM3_FOLLOW_MIN,
               KT_NOMINAL * UM3_DRAG_I_A, i_cap))
    raise AbortError(
        "UM3 드래그 슬립 또는 PA 미실효(%.2f<%.1f, 초기응답은 정상 — 실기"
        " 특성화 필요): 기계 마찰 T_s>%.2fN·m(출력 20+N·m) 우세 — 자유축"
        " 비정상, 기계 점검 (전류 더 올리지 말 것)"
        % (drag["follow_ratio"], UM3_FOLLOW_MIN, KT_NOMINAL * UM3_DRAG_I_A))


def _breakaway_ramp(ctx: _Ctx):
    """B1.4 adaptive breakaway ramp (fable-physics 2026-07-13 — live run #2
    root cause: probe/diag currents below the GEARED stiction never move the
    rotor; the 46,000 'K_a' was low-current noise inside a stiction-locked
    window, and the honest '기계구속' RED fired on a perfectly tunable axis).

    TC ramps 0 -> ramp_frac*CL[1] within ramp_time_s (poll_dt polls).
    Breakaway = (|dPX| > detect_dpx OR |VX| > detect_vx) on TWO consecutive
    polls (rejects compliance windup / velocity-quantization noise); a
    detection is then CONFIRMED by the HOLD phase (TC frozen, sustained
    travel/velocity required — backlash traversal stalls and resumes the
    ramp) before i_ba is latched (upper bound of the static-friction
    current — kept in evidence as a prior for the B/I_c
    identification).  Returns the adaptive probe current
    clip(breakaway_k*i_ba, probe_i_a, ramp_frac*CL[1]), or None when the
    torque path itself is suspect (deferred to the UNIT-DIAG physics branch).

    Cap reached without motion: the IQ witness decides —
      IQ ~ cap  (torque real)   -> honest RED '축 구속(클램프/브레이크?)';
      IQ << cap (torque absent) -> proceed to UNIT-DIAG, whose physics branch
        owns the 토크미인가 diagnosis (full MO/SR/MF/LC log, SPEC §9).
    MF/LC/overspeed guards stay at full strength throughout (30 ms _sleep)."""
    p = ctx.params
    _seg(ctx, "tc")
    i_cap = p.ramp_frac * ctx.cl1
    # best-effort recorder capture across the ramp (windup-curve companion):
    # base 4 channels + optional Reactive Current / Field Angle when the
    # personality exposes them (commutation red-flag evidence)
    extra_names = [n for n in ("Reactive Current [A]", "Field Angle")
                   if n in ctx.evidence.get("recorder_signals", [])]
    ramp_rec_armed = False
    try:
        _record_start(ctx, min(p.ramp_time_s + 0.8, 3.0),
                      extra_names=extra_names)
        ramp_rec_armed = True
    except Exception as e:
        ctx.warnings.append("램프 레코딩 시작 실패(%s) — windup rec 생략" % e)
    px0 = _cmd(ctx, "PX")
    px0 = float(px0) if isinstance(px0, (int, float)) else None
    steps = max(1, int(math.ceil(p.ramp_time_s / p.poll_dt)))
    trace = []
    hits = 0
    i_ba = None
    # hardening #1 (fable-critic MEDIUM): detection is PER-POLL DELTA, not the
    # cumulative |px-px0| — gearbox backlash/compliance windup makes ONE early
    # jump (>detect_dpx) that then SATURATES; a cumulative test would stay
    # true forever, self-satisfy the "2 consecutive" rule, and latch i_ba far
    # below the true breakaway (probe too small -> the exact false-'기계구속'
    # RED this ramp was built to remove — Phase-1 compliance lesson).  True
    # breakaway = CONTINUOUS rotation = consecutive large per-poll deltas.
    #
    # RAMP -> HOLD-CONFIRM state machine (fable-physics 2026-07-13 §2(b)+(c),
    # live field case: i_ba=1.01 A was a BACKLASH TRAVERSAL — free-play flight
    # totalling 4166 cnt = 0.76 deg output — while the true load breakaway is
    # >1.52 A).  Physics invariant: lash traversal is FINITE (<= free play);
    # true load breakaway is UNBOUNDED under held torque.  On RAMP detection
    # the TC is FROZEN (never increased, never cut) for <= hold_window_polls:
    #   SUSTAINED = cumulative travel > max(13000 cnt, 2*lash실측)
    #               AND vx_now >= 0.5*vx_max (개정6 AND-rule — a decaying
    #               transit NEVER sustains; magnitude-only vx passed the live
    #               fake i_ba=1.33 A)  -> i_ba = frozen current, TC=0, done.
    #   STALLED   = 2 consecutive quiet polls (or window exhausted)
    #             -> classified as lash traversal: record the travel in
    #                lash_events and RESUME the ramp from the same point.
    # windup-current curve (fable-physics 추가 evidence): dPX at fixed current
    # levels while (presumably) stuck — elastic windup grows ~linearly with i;
    # IQ rising while windup SATURATES = torque not reaching the mesh
    # (commutation red flag, early capture).  Captured at level crossings.
    levels = [x for x in WINDUP_LEVELS_A if x < i_cap]
    windup_pts = []
    px_prev = px0
    lash_events = []
    tc = 0.0
    ba_direction = 0                    # +1/-1 at the i_ba latch (0 = unknown)
    ba_dir_basis = None                 # signed-motion evidence for the verdict
    for k in range(1, steps + 1):
        tc = i_cap * k / steps
        fast = tc > RAMP_FAST_POLL_ABOVE_A
        _write(ctx, "TC", tc, allow_motion=True)
        # high-current region: VX-only polls at 10 ms (the PX+VX pair costs
        # ~60 ms real period — a breakaway snap grows ~2700 rpm in 2 such
        # polls; PX evidence moves to the HOLD confirm stage).  The in-sleep
        # guard also runs VX-only here (MEDIUM: MF/LC add ~30 ms real).
        ctx.guard_vx_only = fast
        try:
            _sleep(ctx, RAMP_FAST_POLL_S if fast else p.poll_dt)
        finally:
            ctx.guard_vx_only = False
        if fast:
            vx = _cmd(ctx, "VX")
            px_f = None
            dpx_step = 0.0
        else:
            px = _cmd(ctx, "PX")
            vx = _cmd(ctx, "VX")
            px_f = float(px) if isinstance(px, (int, float)) else None
            dpx_step = (abs(px_f - px_prev)
                        if px_f is not None and px_prev is not None else 0.0)
            if px_f is not None:
                px_prev = px_f
        vx_raw = float(vx) if isinstance(vx, (int, float)) else 0.0
        vxa = abs(vx_raw)
        moved = dpx_step > p.detect_dpx or vxa > p.detect_vx
        hits = hits + 1 if moved else 0
        trace.append((round(tc, 4), round(dpx_step, 1), round(vxa, 1),
                      "RAMPF" if fast else "RAMP"))
        while levels and tc >= levels[0] and hits == 0:   # windup point (stuck)
            iq_lv = _cmd(ctx, "IQ")
            px_lv = _cmd(ctx, "PX")
            windup_pts.append({
                "tc_a": round(tc, 3),
                "iq_a": (round(float(iq_lv), 3)
                         if isinstance(iq_lv, (int, float)) else None),
                "dpx_cnt": (round(float(px_lv) - px0, 1)
                            if isinstance(px_lv, (int, float))
                            and px0 is not None else None)})
            levels.pop(0)
        if hits < 2:                # 2 consecutive DELTAS: windup/noise rejected
            continue
        if vxa >= HOLD_INSTANT_GUARD_FRAC * ctx.vx_guard_cnt:
            # MEDIUM: already >=300 rpm AT the detection poll - a lash free
            # flight is over by the 2-consecutive-hits point (the ramp's own
            # invariant), so this IS the load breakaway: latch NOW, skip the
            # HOLD window entirely (real serial latency lets speed grow
            # 400..1100 rpm per poll)
            i_ba = tc
            ba_direction = 1 if vx_raw > 0 else -1     # 보강1: sign at latch
            ba_dir_basis = "signed VX(INSTANT)=%.0f cnt/s" % vx_raw
            trace.append((round(tc, 4), round(dpx_step, 1), round(vxa, 1),
                          "INSTANT"))
            break
        # ---- HOLD-CONFIRM: TC frozen at the detection current ---------------------
        if px_f is None:                # fast region: re-anchor the PX evidence
            pxh = _cmd(ctx, "PX")
            px_f = float(pxh) if isinstance(pxh, (int, float)) else None
            if px_f is not None:
                px_prev = px_f
        px_detect = px_f
        stall = 0
        cum = 0.0
        cum_signed = 0.0
        vx_max = 0.0
        vxa2 = 0.0
        vx2_raw = 0.0
        sustained = False
        collapsed = False
        # 개정6 AND-rule: SUSTAIN = cum > max(floor 13000, 2*lash실측)
        #                 AND vx_now >= 0.5*vx_max (a DECAYING transit never
        #                 qualifies — live retrofit: 6k/89k=0.07 -> stall).
        # COLLAPSE (vx_now < 0.5*vx_max after real motion) classifies the
        # dissipating free flight immediately; a PROMISING slow breakaway
        # (vx non-decaying) keeps the window open up to HOLD_POLLS_MAX —
        # its travel is unbounded and will cross the threshold; a transit's
        # travel is bounded by the free play and cannot.
        max_lash = max((le["travel_cnt"] for le in lash_events), default=0.0)
        sustain_thr = max(p.sustain_dpx_cnt, 2.0 * max_lash)
        vx_instant = HOLD_INSTANT_GUARD_FRAC * ctx.vx_guard_cnt
        prev_mode = ctx.guard_vx_only
        ctx.guard_vx_only = True        # MEDIUM: HOLD window = VX-only guard
        for _h in range(HOLD_POLLS_MAX):
            _sleep(ctx, p.poll_dt)
            px2 = _cmd(ctx, "PX")
            vx2 = _cmd(ctx, "VX")
            px2_f = float(px2) if isinstance(px2, (int, float)) else None
            step_d = (abs(px2_f - px_prev)
                      if px2_f is not None and px_prev is not None else 0.0)
            if px2_f is not None:
                px_prev = px2_f
            vx2_raw = float(vx2) if isinstance(vx2, (int, float)) else 0.0
            vxa2 = abs(vx2_raw)
            if px2_f is not None and px_detect is not None:
                cum_signed = px2_f - px_detect
                cum = abs(cum_signed)
            vx_max = max(vx_max, vxa2)
            moving = step_d > p.detect_dpx or vxa2 > p.detect_vx
            stall = 0 if moving else stall + 1
            trace.append((round(tc, 4), round(step_d, 1), round(vxa2, 1),
                          "HOLD"))
            if vxa2 >= vx_instant:      # 즉시확정 (유격비행 도달불가 속도)
                sustained = True
                break
            if cum > sustain_thr and vxa2 >= SUSTAIN_VX_END_FRAC * vx_max:
                sustained = True        # AND-rule: travel proof + no decay
                break
            if vx_max > p.detect_vx and vxa2 < SUSTAIN_VX_END_FRAC * vx_max:
                collapsed = True        # monotone transit dissipation (live)
                break
            if stall >= 2:
                break
        ctx.guard_vx_only = prev_mode
        if sustained:
            i_ba = tc               # frozen detection current = true breakaway
            # 보강1: motion SIGN at the latch — the +TC ramp must produce
            # +feedback; reversal is decided here, BEFORE any diagnostic pulse
            if abs(cum_signed) > p.detect_dpx:
                ba_direction = 1 if cum_signed > 0 else -1
                ba_dir_basis = "signed dpx(HOLD)=%.0f cnt" % cum_signed
            elif abs(vx2_raw) > p.detect_vx:
                ba_direction = 1 if vx2_raw > 0 else -1
                ba_dir_basis = "signed VX(HOLD)=%.0f cnt/s" % vx2_raw
            break
        # finite/decaying travel = backlash traversal: record + resume ramp
        lash_events.append({"tc_a": round(tc, 4), "travel_cnt": round(cum, 1),
                            "vx_max": round(vx_max, 1),
                            "vx_end": round(vxa2, 1),
                            "collapsed": bool(collapsed)})
        hits = 0
    if len(lash_events) > 2:
        ctx.warnings.append("브레이크어웨이 램프: 유격/실속 이벤트 %d회 — 디텐트"
                            " 래칫 의심(기구 점검 권장)" % len(lash_events))
    iq_cap = None
    if i_ba is None:                        # torque witness BEFORE de-energizing
        iq = _cmd(ctx, "IQ")
        iq_cap = float(iq) if isinstance(iq, (int, float)) else None
    _write(ctx, "TC", 0.0, allow_motion=True)
    _sleep(ctx, 0.15)                       # coast to rest (friction brakes fast)
    _seg(ctx, "idle")
    rec_w = None
    if ramp_rec_armed:
        try:
            rec_w = _record_fetch(ctx)      # free-runs to completion (TC=0 coast)
        except Exception as e:
            ctx.warnings.append("램프 레코딩 업로드 실패(%s) — windup rec 생략" % e)
    ctx.evidence["windup_curve"] = {
        "points": windup_pts, "levels_a": list(WINDUP_LEVELS_A),
        "rec": ({"i_cmd": _decimate(rec_w["icmd"]),
                 "i_act": _decimate(rec_w["i"]),
                 **{nm: _decimate(rec_w["extras"][nm])
                    for nm in rec_w.get("extras", {})}} if rec_w else None),
        "note": "홀드별 ΔPX(탄성이면 ~선형·모델 60·i cnt) — IQ 상승에 와인드업"
                " 포화면 토크가 메시 미도달=커뮤 적신호 조기포착; rec=램프 전구간"
                " 채널 데시메이션(Reactive/Field Angle는 personality 존재 시)"}
    probe = (min(max(p.breakaway_k * i_ba, p.probe_i_a), i_cap)
             if i_ba is not None else None)
    ctx.evidence["breakaway"] = {
        "i_cap_a": i_cap, "i_ba_a": i_ba, "detected": i_ba is not None,
        "iq_at_cap_a": iq_cap, "probe_i_a_adapted": probe,
        "ramp_time_s": p.ramp_time_s, "poll_dt_s": p.poll_dt,
        "detect_dpx_cnt": p.detect_dpx, "detect_vx_cnt_s": p.detect_vx,
        "breakaway_k": p.breakaway_k, "trace_tc_dpx_vx": trace[:200],
        "lash_events": lash_events,
        "hold_window_polls": p.hold_window_polls,
        "hold_polls_max": HOLD_POLLS_MAX,
        "sustain_dpx_cnt": p.sustain_dpx_cnt,
        "sustain_vx_end_frac": SUSTAIN_VX_END_FRAC,
        "direction": ba_direction, "direction_basis": ba_dir_basis,
        "note": "i_ba=브레이크어웨이 전류(정지마찰 전류등가 상계) — B·I_c 식별"
                " 선험치로 evidence 보존; probe=clip(k·i_ba, probe_i_a,"
                " 0.2·CL[1]); 검출=폴 간 델타 2연속 + HOLD-CONFIRM 지속확인"
                " (유격통과=거리유한→실속분류·램프재개, 진짜 이탈=토크유지 시"
                " 거리무한→지속검출; lash_events=유격 이벤트 기록;"
                " direction=+TC 램프에 대한 피드백 부호(래치 시점)"}
    if isinstance(i_ba, (int, float)) and i_ba > IBA_COMMUT_WARN_A:
        # ADVISORY (fable-physics 2026-07-14): the polluted-commutation run
        # inflated breakaway x3.5 (healthy S2: 2.03 A); high i_ba alone is
        # ambiguous (real gearbox stiction vs Kt derating) -> warning only
        ctx.warnings.append(
            "브레이크어웨이 과대(i_ba=%.2fA > %.1fA) — 커뮤 재오염 가능성"
            " (건강 기준 2.03A; 정보성, 하드게이트 아님)"
            % (i_ba, IBA_COMMUT_WARN_A))
    if i_ba is not None and ba_direction < 0:
        # 보강1 (fable-physics §3): 유효-역방향 커뮤테이션은 램프 trace에 이미
        # 드러난다 — 진단펄스 통전 전에 조기중단 (live: unit-diag가 19,571 cnt
        # 역회전을 돌린 뒤에야 B1에서 죽었음)
        raise AbortError(
            "방향 반전(유효-역방향 커뮤테이션) — +TC 램프에 음의 피드백 (%s):"
            " 진단펄스 통전 전 조기중단. %s" % (ba_dir_basis, DIR_FIX_MSG))
    if i_ba is None:
        if iq_cap is None:
            # hardening #3: no false "IQ witnessed the torque" claim — the
            # witness itself is unreadable, so defer to the UNIT-DIAG physics
            # branch (which re-derives the same discrimination from RECORDED
            # I_active vs I_cmd with the full MO/SR/MF/LC log)
            ctx.warnings.append(
                "브레이크어웨이 램프: 무이동 + IQ 판독불가 — 토크 실인가 미확인,"
                " UNIT-DIAG 물리분기로 판별 위임")
            return None
        if iq_cap < 0.5 * i_cap:
            ctx.warnings.append(
                "브레이크어웨이 램프: 무이동 + IQ=%.2fA ≪ 캡 %.2fA — 토크경로 이상"
                " 의심, UNIT-DIAG 물리분기로 판별 위임" % (iq_cap, i_cap))
            return None
        # ---- PART B: torque real + no breakaway at the cap -> UM=3 drag
        # discrimination via _drag_route (raises the routed RED itself).
        # HIGH-1 gate lives inside: only when i_cap >= UM3_DRAG_I_A (6 A) —
        # below that the drag torque exceeds the cap torque and would ALWAYS
        # follow, mis-routing healthy friction to a commutation RED.
        _drag_route(ctx, i_cap)             # returns only when 판별 불가/생략
        raise AbortError(
            "축 구속(클램프/브레이크?) — 브레이크어웨이 없음: TC=%.2fA"
            "(%.2f·CL[1])에서도 |ΔPX|≤%.0fcnt·|VX|≤%.0fcnt/s"
            " (IQ=%.2fA 토크 실인가 확인; UM3 판별 유보%s)"
            % (i_cap, p.ramp_frac, p.detect_dpx, p.detect_vx, iq_cap,
               " — 캡<%.0fA" % UM3_DRAG_I_A if i_cap < UM3_DRAG_I_A else ""))
    return probe


def _unit_diag(ctx: _Ctx, i_diag: float = UNITDIAG_I_A) -> float:
    """B1.5 escalation wrapper (fable-physics §4, 2026-07-13) — dual defense
    behind the breakaway ramp: a NO-MOTION or LASH-LANDING diag pulse (rotor
    crossed the free play and stopped mid-pulse) is retried at higher current
    (x1.5, x2.25, then the 0.2*CL[1] cap — at most 3 escalations) instead of
    dying immediately.  Success requires |dPos| > UNITDIAG_MIN_DPOS AND
    residual motion inside the late fitting window (lash landings rejected).
    Terminal REDs stay terminal: 토크미인가 (more current cannot fix a dead
    torque path), broken current channel, sample-starved window, hard gate.
    Only when the CAP itself cannot produce sustained motion does the final
    honest RED '축 구속/고마찰(기계구속)' fire.  Every attempt is protected by
    the 500 rpm early-stop.  Returns the current of the SUCCESSFUL pulse
    (the s/g/K_a discriminants were computed from exactly that pulse)."""
    i_cap = ctx.params.ramp_frac * ctx.cl1
    ladder = [min(i_diag, i_cap)]
    for f in (1.5, 2.25):
        nxt = min(f * i_diag, i_cap)
        if nxt > ladder[-1] * (1 + 1e-9):
            ladder.append(nxt)
    if i_cap > ladder[-1] * (1 + 1e-9):
        ladder.append(i_cap)                # last rung = the cap itself
    escal = []
    for idx, i_try in enumerate(ladder):
        fail = _unit_diag_pulse(ctx, i_try, escal)
        if fail is None:
            return i_try                    # success — corrections adopted
        escal.append(fail)
        wc = ctx.evidence.get("windup_curve")
        if isinstance(wc, dict):        # 개정6 fix-5: multi-point windup curve
            wc["points"].append({"tc_a": round(i_try, 3), "iq_a": None,
                                 "dpx_cnt": fail.get("d_pos_cnt"),
                                 "src": "unitdiag_escalation"})
        if idx == len(ladder) - 1:
            # LOW-2 + 개정6 fix-3: ANY exhaustion (무이동 OR 유격착지/꿈틀)
            # means NO SUSTAINED ROTATION was achieved — the same premise as
            # the ramp cap-out, so route through the drag oracle when the
            # gate allows (the live fake motion skipped the drag exactly
            # here), else mark the verdict 판별 유보.
            _drag_route(ctx, i_cap)         # raises the routed RED on success
            raise AbortError(
                "UNIT-DIAG: 축 구속/고마찰(기계구속) — 상향 %d회, 최종"
                " i_diag=%.2fA(캡 %.2fA)에도 지속모션 없음 (ΔPos=%.0fcnt,"
                " 모드=%s; IQ/기록전류로 토크 실인가 확인됨; UM3 판별 유보%s)"
                % (len(escal) - 1, i_try, i_cap,
                   fail.get("d_pos_cnt", 0.0), fail.get("mode"),
                   " — 캡<%.0fA" % UM3_DRAG_I_A if i_cap < UM3_DRAG_I_A
                   else ""))
        ctx.warnings.append(
            "UNIT-DIAG %s(i=%.2fA) — i_diag %.2f→%.2fA 상향 재펄스 (%d/%d)"
            % (fail.get("mode"), i_try, i_try, ladder[idx + 1],
               idx + 1, len(ladder) - 1))


def _unit_diag_pulse(ctx: _Ctx, i_diag: float, escal: list):
    """B1.5 UNIT-DIAG single pulse (SPEC §9) — hard gate before any main pulse.
    Returns None on success; a failure dict {'mode': '무이동'|'유격착지', ...}
    when escalation should retry; raises AbortError on terminal REDs.

    One +i_diag / 80 ms torque pulse recorded at TR=1 (dt = TS, the ONLY
    Phase-1-verified time base) with all four channels + a 30 ms VX poll log.
    i_diag = breakaway-ramp-adapted current (>= UNITDIAG_I_A floor) so the
    rotor ACTUALLY moves on geared/high-stiction units.

    T_host (2026-07-13 fix): the pulse duration is NOT the nominal 80 ms —
    poll_sleep interleaves VX serial round-trips, stretching the real pulse
    (live ~125 ms, +56%).  T_host is MEASURED by clock_fn brackets around the
    TC writes (midpoints, so the command-ack latency cancels), with
    max(bracket, nominal) as a physical floor (wall time can never undercut
    the requested sleeps; the floor only engages when clock_fn is not
    homogeneous with sleep_fn, i.e. an un-injected sim).  Without this the
    old g = 0.080/T_real = 0.64 would masquerade as a dt factor.
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
    clock = p.clock_fn
    _wait_rest(ctx)                 # from rest (prior attempt may still coast)
    _seg(ctx, "tc")
    _record_start(ctx, UNITDIAG_REC_S, tres_override=1)
    vx_log = []                                 # (t_nominal, t_clock, VX)
    t0_nom, t0_clk = ctx.elapsed_s, clock()

    def poll_sleep(dur):
        remaining = float(dur)
        while remaining > 1e-9:
            step = min(0.03, remaining)
            _sleep(ctx, step)
            remaining -= step
            vx = _cmd(ctx, "VX")
            if isinstance(vx, (int, float)):
                vx_log.append((ctx.elapsed_s - t0_nom, clock() - t0_clk,
                               float(vx)))

    poll_sleep(PRE_ROLL_S)
    tb_on = clock()
    _write(ctx, "TC", i_diag, allow_motion=True)
    ta_on = clock()
    # pulse window with MOTION EARLY-STOP (hardening #2): the ADAPTIVE i_diag
    # on a low-RUNNING-friction plant can cross the 1200 rpm guard inside the
    # nominal 80 ms (safe abort, but the run dies).  Cut the pulse the moment
    # |VX| crosses 500 rpm and analyze the captured window; a too-short window
    # falls into the existing honest "후반창 표본 부족" RED.
    vx_stop = ctx.ca18 * UNITDIAG_EARLYSTOP_RPM / 60.0
    early_stop = False
    remaining = float(UNITDIAG_T_S)
    ctx.guard_vx_only = True            # MEDIUM: pulse window = VX-only guard
    while remaining > 1e-9:
        step = min(RAMP_FAST_POLL_S, remaining)   # 10 ms VX-only during the
        _sleep(ctx, step)                         # pulse (adaptive current can
        remaining -= step                         # be near the 0.4*CL cap)
        vx = _cmd(ctx, "VX")
        if isinstance(vx, (int, float)):
            vx_log.append((ctx.elapsed_s - t0_nom, clock() - t0_clk, float(vx)))
            if abs(vx) > vx_stop:
                early_stop = True
                break
    ctx.guard_vx_only = False
    tb_off = clock()
    _write(ctx, "TC", 0.0, allow_motion=True)
    ta_off = clock()
    t_nom_applied = (UNITDIAG_T_S - remaining) if early_stop else UNITDIAG_T_S
    poll_sleep(UNITDIAG_REC_S - PRE_ROLL_S - t_nom_applied + 0.02)
    rec = _record_fetch(ctx)                    # corrections still 1.0 -> raw
    _seg(ctx, "idle")
    # measured pulse duration: write-bracket midpoints (ack latency cancels);
    # nominal floor = physical lower bound (sleep(d) always takes >= d)
    t_meas = 0.5 * (tb_off + ta_off) - 0.5 * (tb_on + ta_on)
    use_meas = math.isfinite(t_meas) and t_meas >= t_nom_applied * (1.0 - 1e-9)
    t_pulse = t_meas if use_meas else t_nom_applied
    vx_sel = [((tc if use_meas else tn), x) for tn, tc, x in vx_log]
    v, pos, i_act, icmd, dt = rec["v"], rec["p"], rec["i"], rec["icmd"], rec["dt"]
    d_pos = float(pos[-1] - pos[0])
    cmd_mask = icmd > 0.5 * i_diag
    act_mask = i_act > 0.5 * i_diag
    mean_icmd = float(np.mean(icmd[cmd_mask])) if cmd_mask.any() else 0.0
    mean_iact = float(np.mean(i_act[cmd_mask])) if cmd_mask.any() else 0.0
    ev = {"d_pos_cnt": d_pos, "dt_assumed_s": dt, "i_diag_a": i_diag,
          "t_pulse_host_s": t_pulse, "t_pulse_bracket_s": t_meas,
          "t_pulse_nominal_s": t_nom_applied,
          "early_stop": bool(early_stop),
          "early_stop_rpm": UNITDIAG_EARLYSTOP_RPM,
          "t_pulse_src": "measured(clock_fn)" if use_meas else "nominal-floor",
          "mean_i_cmd": mean_icmd, "mean_i_act": mean_iact,
          "vx_poll": [(round(t, 4), round(x, 1)) for t, x in vx_sel],
          "escalations": list(escal),
          "raw": {"pos": _decimate(pos), "vel": _decimate(v),
                  "i_act": _decimate(i_act), "i_cmd": _decimate(icmd)},
          "notes": "U-P9=Velocity 단위, U-P10=UM=5 TC 실효 — 이 진단이 실기 판별 경로;"
                   " T_host=클록 브래킷 실측(직렬왕복 지연 포함, 명목 80ms 아님)"}
    ctx.evidence["unit_diag"] = ev

    # ---- physics-anomaly branch first (Position = ground truth) -----------------------
    if abs(d_pos) < UNITDIAG_MIN_DPOS:
        logs = {k: _cmd(ctx, k) for k in ("MO", "SR", "MF", "LC")}
        ev["drive_logs"] = logs
        if mean_icmd > 0 and mean_iact < 0.5 * mean_icmd:
            raise AbortError(                # TERMINAL: current cannot fix this
                "UNIT-DIAG: 토크미인가 — I_active=%.2fA ≪ I_cmd=%.2fA, ΔPos=%.0fcnt"
                " (UM=5 TC경로 확인 필요, U-P10; 로그 %s)"
                % (mean_iact, mean_icmd, d_pos, logs))
        # torque real, no motion: ESCALATABLE (fable-physics §4 dual defense)
        return {"mode": "무이동", "i_diag_a": i_diag, "d_pos_cnt": d_pos,
                "mean_i_act": mean_iact, "logs": logs}

    # ---- (1) g: dt factor (MEASURED host pulse time, 2026-07-13 fix) -------------------
    n_pulse = int(act_mask.sum())
    ev["n_pulse"] = n_pulse
    if n_pulse == 0:
        # hardening #4: rotor MOVED (|dPos| >= threshold) but the recorded
        # Active Current never crossed 0.5*i_diag — that is a broken/mis-scaled
        # current CHANNEL, not physics.  Explicit RED instead of the opaque
        # IndexError (k_on[0]) / ZeroDivision (g_corr) the generic handler
        # would have reported as "내부 예외".
        raise AbortError(
            "UNIT-DIAG: 전류채널 이상 의심 — 로터는 이동(ΔPos=%.0fcnt)했는데"
            " 기록 Active Current가 임계(0.5×%.2fA)를 넘지 않음 (레코딩 전류채널"
            " 스케일/매핑 확인 필요)" % (d_pos, i_diag))
    g = t_pulse / (n_pulse * dt)
    # ---- (2) s: velocity-channel scale (true = rec * s) --------------------------------
    sum_v = float(np.sum(v)) * g * dt
    s = d_pos / sum_v if sum_v else float("inf")
    ratios = []
    v_ref = float(np.max(np.abs(v)))
    for t_rel, vx in vx_sel:
        k = int(round(t_rel / (g * dt)))
        if 0 <= k < len(v) and abs(v[k]) > 0.05 * v_ref:
            ratios.append(vx / v[k])
    s2 = float(np.median(ratios)) if ratios else None
    # ---- (3) channel-agnostic accel: POSITION-only late-window 2nd-order fit ----------
    t_true = np.arange(len(v)) * g * dt
    k_on = np.flatnonzero(act_mask)
    t_p0 = float(t_true[k_on[0]])
    # late-window start adapts to EARLY-STOPPED pulses (cap-raise: a near-cap
    # i_diag is cut in ~20-30 ms; a fixed 24 ms start would empty the window
    # on a HEALTHY fast pulse).  0.4*t_pulse >> current-loop tau (0.44 ms).
    w_start = min(0.024, 0.4 * t_pulse)
    w = (t_true >= t_p0 + w_start) & (t_true <= t_p0 + t_pulse) & act_mask
    if w.sum() < 8:
        raise AbortError("UNIT-DIAG: 후반창 표본 부족 (n=%d)" % int(w.sum()))
    # ---- lash-landing rejection (fable-physics §4; denominator fix
    # 2026-07-13): the rotor may have merely crossed the FREE PLAY early in
    # the pulse and stopped — |dPos| passes the MIN gate but the LATE fitting
    # window holds a frozen position, so the position-fit K_a would be
    # garbage.  The comparison base must be the travel INSIDE THE TORQUE
    # WINDOW only: the record-wide dPos includes the post-pulse COAST, which
    # on a low-running-friction plant dwarfs the pulse travel (live-class
    # case: dPos=157k cnt of which ~150k is coast after a 30 ms early-stopped
    # pulse) and made genuinely spinning rotors look "landed" (false RED).
    # True motion is quadratic inside the pulse: the late window carries a
    # large share of the PULSE travel; a landed rotor's late window is frozen.
    w_idx = np.flatnonzero(w)
    late_travel = float(pos[w_idx[-1]] - pos[w_idx[0]])
    k_act = np.flatnonzero(act_mask)
    pulse_travel = float(pos[k_act[-1]] - pos[k_act[0]])
    ev["late_travel_cnt"] = late_travel
    ev["pulse_travel_cnt"] = pulse_travel
    if abs(pulse_travel) < UNITDIAG_MIN_DPOS:
        # record-wide dPos came from OUTSIDE the torque window (drift/coast):
        # no usable in-pulse motion — same class as 무이동, escalate
        return {"mode": "무이동", "i_diag_a": i_diag, "d_pos_cnt": d_pos,
                "pulse_travel_cnt": pulse_travel}
    # 개정6 fix-2: success = SUSTAINED ROTATION, not "moved" — a 269 cnt
    # backlash jiggle passed the old ratio test.  Require BOTH:
    #   |late_travel| > max(MIN_DPOS, 3 x elastic-windup model 60*i_diag)
    #   AND pulse-end velocity > 3000 cnt/s, POSITION-derived (the velocity
    #   channel is itself under diagnosis — must not gate on it).
    min_late = max(UNITDIAG_MIN_DPOS, 3.0 * WINDUP_CNT_PER_A * i_diag)
    # tail velocity by LEAST SQUARES over ~10 ms (fable-critic MEDIUM-1: the
    # 2-point 0.8 ms diff read +-1.5 cnt position noise as >3000 cnt/s and
    # could pass a LATE lash landing as sustained rotation)
    n_tail = max(4, int(round(UNITDIAG_TAIL_S / (g * dt))))
    tail_idx = w_idx[-min(n_tail, len(w_idx)):]
    slope_tail, _ot, _rt = window_slope(t_true[tail_idx],
                                        pos[tail_idx].astype(float))
    v_end_pos = abs(slope_tail)
    ev["late_travel_min_cnt"] = round(min_late, 1)
    ev["v_end_pos_cnt_s"] = round(v_end_pos, 1)
    if abs(late_travel) < min_late or v_end_pos < UNITDIAG_END_V_MIN:
        return {"mode": "유격착지/꿈틀", "i_diag_a": i_diag,
                "d_pos_cnt": d_pos, "pulse_travel_cnt": pulse_travel,
                "late_travel_cnt": late_travel,
                "v_end_pos_cnt_s": round(v_end_pos, 1)}
    if abs(late_travel) < 0.2 * abs(pulse_travel):
        return {"mode": "유격착지", "i_diag_a": i_diag, "d_pos_cnt": d_pos,
                "pulse_travel_cnt": pulse_travel,
                "late_travel_cnt": late_travel}
    tt = t_true[w] - t_true[w][0]
    qc = np.polyfit(tt, pos[w], 2)
    a_pos = 2.0 * float(qc[0])
    i_w = float(np.mean(i_act[w]))
    ka_pos = a_pos / i_w if i_w else float("nan")
    if math.isfinite(ka_pos) and ka_pos <= 0.0:
        # 보강2 (fable-physics §3): the live run PASSED the hard gate with a
        # NEGATIVE K_a (ka_pos=-5.5e5; ka_dev compares magnitude-consistency
        # only) — a +i_diag pulse must accelerate POSITIVE.  Terminal RED.
        raise AbortError(
            "방향 반전(유효-역방향 커뮤테이션) — +%.2fA 펄스에 음의 가속"
            " (Position-fit K_a=%.3g ≤ 0). %s" % (i_diag, ka_pos, DIR_FIX_MSG))

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
    g_corr = t_pulse / (n_pulse * dt * ctx.g_dt)
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
    return None                             # success — corrections adopted


# ======================================================================================
# the pipeline (SPEC §6 P0..E2)
# ======================================================================================
_P1_READS = (["TS", "UM", "MF", "SR", "GS[0]", "GS[1]", "GS[2]",
              "KP[1]", "KP[2]", "KP[3]", "KI[1]", "KI[2]",
              "CA[7]", "CA[17]", "CA[18]", "CA[19]",
              "CA[41]", "CA[42]", "CA[43]", "CA[44]",
              "CL[1]", "PL[1]", "MC", "VH[2]", "VH[3]", "VL[3]",
              "ER[2]", "ER[3]", "HL[2]", "HL[3]", "LL[2]", "LL[3]",
              "AC", "DC", "SD", "SP", "FF[1]", "FF[2]", "VX", "PX", "BV",
              "WS[28]", "WS[55]"])

# informational commutation/feedback context (fable-physics 2026-07-14):
# CA[25]=direction invert, CA[54..57]=commutation feedback config,
# CA[16]=commutation search on every MO (1 = δ re-lottery per MO — worse).
# Read BEST-EFFORT — some firmware/personality combos may not answer; a
# missing key must never kill the run (recorded as None).
_P1_READS_OPT = ("CA[25]", "CA[54]", "CA[55]", "CA[56]", "CA[57]", "CA[16]")


def run_velpos_autotune(link, params: Optional[AutotuneVPParams] = None
                        ) -> AutotuneVPResult:
    """Phase 2 measurement pipeline (P0..E2).  Gain application (F1) and the
    verification run (F2) are separate calls: apply_gains_vp / verify_run_vp.

    SAFETY: sends MO=1/TC/JV/ST with allow_motion=True — the caller must have
    passed the operator gate (free rotation, load detached, expected revs
    shown) BEFORE calling this.  Never raises: failures return RED after the
    segment-appropriate abort chain."""
    params = params or AutotuneVPParams()
    # synthetic-run quarantine (2026-07-14): a sim link (is_synthetic=True on
    # the mock/smoke drive) or params.synthetic=True reroutes ALL persistence
    # (P3 snapshot json + K_a baseline) into snapshot_dir/synthetic — a
    # synthetic GREEN must NEVER re-baseline the live commutation fingerprint
    synthetic = (params.synthetic if params.synthetic is not None
                 else bool(getattr(link, "is_synthetic", False)))
    if synthetic:
        params = _dc_replace(params, snapshot_dir=os.path.join(
            params.snapshot_dir, SYNTHETIC_SUBDIR))
    ctx = _Ctx(link, params)
    if synthetic:
        ctx.evidence["synthetic_quarantine"] = params.snapshot_dir
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
    for c in _P1_READS_OPT:                     # informational, fail-open
        try:
            ctx.readings[c] = _cmd(ctx, c, retries=0)
        except Exception:
            ctx.readings[c] = None
    if ctx.readings.get("CA[16]") in (1, 1.0):
        # δ is a power-session RAM state (see the 2-layer model at
        # DIR_FIX_MSG); CA[16]=1 re-lotteries it on EVERY MO — never set it
        ctx.warnings.append("CA[16]=1 — 매 MO마다 커뮤 탐색: δ 복권이 MO"
                            " 단위로 악화, 0 권장")
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
        raise PreflightError("커뮤 변경감지: CA[7]=%r (명시 고정값 %s와 불일치 —"
                             " 다른 모터 장착?)"
                             % (r.get("CA[7]"), p.expected_ca7))
    for wsk in ("WS[28]", "WS[55]"):
        if isinstance(r.get(wsk), (int, float)) and r[wsk] != ts:
            raise PreflightError("%s=%r ≠ TS=%r — 루프주기 불일치" % (wsk, r[wsk], ts))
    cl1 = r.get("CL[1]")
    if not isinstance(cl1, (int, float)) or cl1 <= 0:
        raise PreflightError("CL[1]=%r 비정상" % (cl1,))
    ctx.cl1 = float(cl1)
    if not (0.0 < p.ramp_frac <= RAMP_FRAC_ABS_MAX + 1e-9):
        raise PreflightError(
            "ramp_frac=%.2f 허용범위(0, %.1f] 벗어남 — %.1f·CL 이상 자동 램프 금지"
            "(오퍼레이터 승인 전용 상수 RAMP_FRAC_OPERATOR_ONLY)"
            % (p.ramp_frac, RAMP_FRAC_ABS_MAX, RAMP_FRAC_ABS_MAX))
    ca18 = r.get("CA[18]")
    ctx.ca18 = float(ca18) if isinstance(ca18, (int, float)) and ca18 > 0 else 65536.0
    ctx.vx_guard_cnt = ctx.ca18 * GUARD_RPM / 60.0
    kp1 = r.get("KP[1]") if isinstance(r.get("KP[1]"), (int, float)) else 0.07177
    ki1 = r.get("KI[1]") if isinstance(r.get("KI[1]"), (int, float)) else 812.939
    _emit(ctx, "VALIDATE", "G0 통과: TS=%dµs UM=5 GS[2]=0 CA[17]=%d, CL[1]=%.2fA"
          " (CA[7]=%s — 모터별 커뮤값, 정보성 기록)"
          % (int(ts), p.expected_ca17, ctx.cl1, r.get("CA[7]")))

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
    _emit(ctx, "ENABLE", "MO=1 통전(UM=5), 서보온 확인 — 브레이크어웨이 램프(B1.4) 시작")

    # ---- B1.4 adaptive breakaway ramp (geared-stiction fix, 2026-07-13) ---------------
    _emit(ctx, "BREAKAWAY", "브레이크어웨이 램프: TC 0→%.2fA(0.2·CL[1]) ≤%.1fs,"
          " %.0fms 폴 (|ΔPX|>%.0f ∨ |VX|>%.0f ×2연속)"
          % (p.ramp_frac * ctx.cl1, p.ramp_time_s, p.poll_dt * 1e3,
             p.detect_dpx, p.detect_vx))
    probe_adapt = _breakaway_ramp(ctx)
    ba = ctx.evidence["breakaway"]
    _emit(ctx, "BREAKAWAY", "브레이크어웨이 %s"
          % ("i_ba=%.2fA → 적응 probe=%.2fA" % (ba["i_ba_a"], probe_adapt)
             if ba["detected"]
             else "미검출(IQ=%.2fA 토크경로 의심) — UNIT-DIAG 물리분기로"
                  % (ba["iq_at_cap_a"] or -1.0)))

    # ---- B1.5 UNIT-DIAG (§9 hard gate — the probe B1 moved AFTER this) ----------------
    i_diag = max(UNITDIAG_I_A, probe_adapt) if probe_adapt else UNITDIAG_I_A
    _emit(ctx, "UNIT_DIAG", "단위 진단: +%.2fA/%.0fms 펄스(적응), TR=1,"
          " dt·속도스케일·토크경로 판별" % (i_diag, UNITDIAG_T_S * 1e3))
    i_diag_final = _unit_diag(ctx, i_diag)
    ud = ctx.evidence["unit_diag"]
    _emit(ctx, "UNIT_DIAG", "단위 확정: s=%.4g g=%.4g (K_a③=%.3g, 편차 %.1f%%,"
          " T_host=%.3fs %s, i=%.2fA·상향%d회) — 게이트 통과"
          % (ud["s"], ud["g"], ud["ka_pos"], 100 * ud["ka_dev"],
             ud["t_pulse_host_s"], ud["t_pulse_src"], i_diag_final,
             len(ud.get("escalations", []))))

    # ---- B1 probe (uses the UNIT-DIAG-confirmed s/dt corrections) ----------------------
    # escalated diag success = PROVEN mover current: feed it forward as the
    # probe floor (otherwise the under-sized probe would die at B1 on the very
    # axis the escalation just recovered)
    probe_floor = i_diag_final if i_diag_final > i_diag * (1 + 1e-9) else 0.0
    i_probe = max(p.probe_i_a, probe_adapt or 0.0, probe_floor)
    k_a_probe = None
    for attempt in (0, 1):
        _wait_rest(ctx)                 # from rest (early-stopped diag may coast)
        _seg(ctx, "tc")
        rec_dt = _record_start(ctx, 0.4)
        _sleep(ctx, PRE_ROLL_S)
        _write(ctx, "TC", i_probe, allow_motion=True)
        # cap-raise: the ADAPTIVE probe current (mover-fed, up to 0.4*CL) can
        # cross the guard within 50 ms on a low-running-friction plant — the
        # same motion cut as the main pulses protects it (two-slope analysis
        # is duration-agnostic; the cut only shortens the on-window)
        probe_cut = _pulse_sleep_with_cut(
            ctx, PROBE_T_S, MAINPULSE_STOP_FRAC * ctx.vx_guard_cnt)
        _write(ctx, "TC", 0.0, allow_motion=True)
        _sleep(ctx, 0.4 - PRE_ROLL_S - PROBE_T_S + 0.02)
        rec = _record_fetch(ctx)
        _seg(ctx, "idle")
        k_a_probe, vpk, a_on, moved = _probe_ka(ctx, rec, i_probe)
        ctx.evidence.setdefault("probe", []).append(
            {"i_a": i_probe, "k_a_probe": k_a_probe, "v_peak": vpk,
             "slope_on": a_on, "moved": moved, "dt": rec_dt,
             "early_stop": bool(probe_cut)})
        if moved and k_a_probe > 0:
            break
        if attempt == 0:
            i_probe = max(i_probe,
                          min(2.0 * i_probe, PULSE_FRAC_ABS_MAX * ctx.cl1))
            ctx.warnings.append("프로브 v̇≈0 — 전류 ×2 재시도 (%.2fA)" % i_probe)
            continue
        raise AbortError("정지마찰 과대 — 프로브 무이동 (I=%.2fA)" % i_probe)
    _emit(ctx, "PROBE", "프로브 K_a=%.3g cnt/s²/A (on/off 2기울기, 마찰보정)" % k_a_probe)

    # ---- B2 pulse sizing ----------------------------------------------------------------
    # HIGH fix (fable-critic 2026-07-13, order-killer): i0 is FLOORED at the
    # PROVEN mover current (the final UNIT-DIAG pulse that actually moved the
    # rotor).  The old fixed i0 = 0.1*CL[1] sat BELOW the geared stiction
    # (~2.5 A) -> first pulse no motion -> retry doubled i0 to 4.24 A with the
    # STALE tp (71 ms) -> |VX| crossed the 1200 rpm guard at ~56 ms -> false
    # RED on a healthy axis.  With the mover floor the FIRST pulse moves, and
    # _size_tp keeps the peak near the target for whatever i0 is in force.
    i_mover = i_diag_final                  # proven rotor-moving current
    i_ba_val = ctx.evidence.get("breakaway", {}).get("i_ba_a")
    floor_ba = (1.25 * i_ba_val
                if isinstance(i_ba_val, (int, float)) and i_ba_val > 0 else 0.0)
    # cap-raise (fable-physics): the 0.2*CL pulse ceiling is RETIRED — a geared
    # unit with i_ba>4.24 A cannot be identified at 2.12 A.  Floors: configured
    # fraction, 1.25*i_ba (friction headroom), proven mover; ceiling 0.4*CL.
    i0 = min(max(p.i_pulse_frac * ctx.cl1, floor_ba, i_mover),
             PULSE_FRAC_ABS_MAX * ctx.cl1)
    # MEDIUM: the sizing TARGET must sit under the runtime cut (0.6*guard) by
    # margin, else every correctly-sized pulse would be truncated
    target_rpm_eff = min(p.tp_target_rpm,
                         PULSE_TARGET_CAP_FRAC * MAINPULSE_STOP_FRAC * GUARD_RPM)
    target_cnt = ctx.ca18 * target_rpm_eff / 60.0
    tp = _size_tp(k_a_probe, _i_net(i0, i_ba_val), target_cnt)

    def _warn_high_i0(cur_i0):
        # fable-physics 2026-07-14: the live i0 floor riding to 8.485 A
        # (0.4*CL) was the commutation-degradation fingerprint (delta~75 deg e
        # -> Kt x0.27 -> breakaway/friction inflated -> floors dragged up).
        # ADVISORY only — a healthy geared unit may legitimately sit here.
        if cur_i0 > HIGH_I0_WARN_FRAC * ctx.cl1 \
                and not any("고전류 식별" in w for w in ctx.warnings):
            ctx.warnings.append(
                "고전류 식별(i0=%.1fA > %.2f·CL=%.1fA) — Kt 저하/커뮤 열화"
                " 의심, K_a 과소추정 가능"
                % (cur_i0, HIGH_I0_WARN_FRAC, HIGH_I0_WARN_FRAC * ctx.cl1))
    _warn_high_i0(i0)
    rev_est = (k_a_probe * i0) * tp * tp / ctx.ca18   # ~both pulses combined
    ctx.evidence["sizing"] = {"i0_a": i0, "tp_s": tp, "rev_est": rev_est,
                              "k_a_probe": k_a_probe, "i_mover_a": i_mover,
                              "i_ba_floor_a": floor_ba,
                              "i_net_a": _i_net(i0, i_ba_val),
                              "target_rpm_eff": target_rpm_eff}
    _emit(ctx, "SIZING", "본펄스 I0=%.2fA(하한: frac %.2f/1.25·i_ba %.2f/mover"
          " %.2f, 캡 %.1f·CL) Tp=%.0fms, 예상회전≈%.2f rev/런"
          % (i0, p.i_pulse_frac * ctx.cl1, floor_ba, i_mover,
             PULSE_FRAC_ABS_MAX, tp * 1e3, rev_est))

    # ---- C1/C2 pulse-pair runs (G2 friction-ratio retry: once) -------------------------
    runs = None
    for sizing_try in (0, 1):
        runs = []
        for first_sign in (+1.0, -1.0):
            for m_try in (0, 1):                 # §9: 모션부족 적응 재시도 1회
                _wait_rest(ctx)                  # each pulse pair starts from rest
                _seg(ctx, "tc")
                dur = 2 * tp + 0.4
                cut_cnt = MAINPULSE_STOP_FRAC * ctx.vx_guard_cnt
                _record_start(ctx, dur)
                _sleep(ctx, PRE_ROLL_S)
                _write(ctx, "TC", first_sign * i0, allow_motion=True)
                cut1 = _pulse_sleep_with_cut(ctx, tp, cut_cnt)
                _write(ctx, "TC", -first_sign * i0, allow_motion=True)
                cut2 = _pulse_sleep_with_cut(ctx, tp, cut_cnt)
                _write(ctx, "TC", 0.0, allow_motion=True)
                _sleep(ctx, dur - PRE_ROLL_S - 2 * tp + 0.02)
                rec = _record_fetch(ctx)
                _seg(ctx, "idle")
                if cut1 or cut2:                 # analyzed from the captured window
                    ctx.evidence.setdefault("pulse_early_stops", []).append(
                        {"first_sign": first_sign, "cut_first": bool(cut1),
                         "cut_second": bool(cut2), "i0_a": i0, "tp_s": tp,
                         "cut_cnt_s": cut_cnt})
                    ctx.warnings.append(
                        "본펄스 모션 조기종료(|VX|>%.0f=%.2f·가드) — 사이징"
                        " 여유 재검토, 캡처창으로 분석 계속"
                        % (cut_cnt, MAINPULSE_STOP_FRAC))
                vpk_run = float(np.max(np.abs(rec["v"])))
                if vpk_run < ctx.ca18 * MOTION_MIN_RPM / 60.0:
                    if m_try == 0:
                        i0 = min(2.0 * i0, 0.4 * ctx.cl1)
                        tp = _size_tp(k_a_probe, _i_net(i0, i_ba_val),
                                      target_cnt)                  # HIGH fix:
                        # NEVER reuse the old tp with a bigger i0 (stale tp =
                        # v_pk x2 past the guard, the live order-killer)
                        ctx.warnings.append("모션부족(v_pk=%.0f<%.0frpm) — I0 ×2"
                                            " 재시도(%.2fA, Tp 재산정 %.0fms)"
                                            % (vpk_run, MOTION_MIN_RPM, i0,
                                               tp * 1e3))
                        _warn_high_i0(i0)
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
        i0 = min(1.5 * i0, PULSE_FRAC_ABS_MAX * ctx.cl1)
        tp = _size_tp(k_a_probe, _i_net(i0, i_ba_val),
                      target_cnt)                   # HIGH fix: resize with i0
        ctx.warnings.append("마찰비 %.2f>%.1f — I0 증액 재시도(%.2fA, Tp 재산정"
                            " %.0fms)" % (friction_ratio, FRICTION_RATIO_MAX,
                                          i0, tp * 1e3))
        _warn_high_i0(i0)
    ctx.evidence["pulse_runs"] = runs
    k_a = 0.5 * (runs[0]["k_a_diff"] + runs[1]["k_a_diff"])
    _emit(ctx, "IDENT_KA", "K_a=%.4g cnt/s²/A (±펄스 차분, 런2회 평균)" % k_a)
    # 개정6 fix-5: ABSOLUTE plausibility advisory — the live 46,000 (1/125 of
    # the FF[1]-implied value) should have been flagged loudly on the spot
    ff1_adv = ctx.readings.get("FF[1]")
    if isinstance(ff1_adv, (int, float)) and ff1_adv > 0 and k_a > 0:
        ka_impl = 1.0 / ff1_adv
        ratio = k_a / ka_impl
        if not (0.1 <= ratio <= 10.0):
            ctx.warnings.append(
                "K_a 절대 타당성 이탈 — 실측 %.3g = FF[1] 함의 %.3g의 %.3g×"
                " ([0.1,10]× 밖): 식별 오염 의심(유격/단위), 결과 신뢰불가"
                % (k_a, ka_impl, ratio))

    # ---- commutation-degradation early gate (fable-physics 2026-07-14) --------------
    # The last-GREEN K_a is this unit's fingerprint: a >2x drop between runs
    # is a commutation-health event, not a plant change (live: 3.82e5 =
    # 0.27 x 1.42e6 with delta~75 deg e; every LOCAL gate passed).  RED fires
    # BEFORE D1 so the motor is not spun further on a polluted commutation.
    ka_base = _load_ka_baseline(ctx)
    if ka_base is not None and 0 < k_a < KA_BASELINE_DROP_FRAC * ka_base:
        ratio_b = k_a / ka_base
        # cos(delta) = Kt_eff/Kt = K_a/baseline -> offset-angle estimate
        delta_deg = math.degrees(math.acos(min(1.0, max(0.0, ratio_b))))
        ctx.evidence["ka_baseline"] = {
            "baseline_k_a": ka_base, "k_a": k_a, "ratio": ratio_b,
            "delta_e_deg_est": delta_deg, "verdict": "RED",
            "path": _ka_baseline_path(ctx)}
        raise AbortError(
            "K_a가 마지막 GREEN의 %.0f%%로 급락(%.3g vs %.3g cnt/s²/A) —"
            " 커뮤테이션 열화 의심(δ≈%.0f°e), 재커뮤 필요"
            % (100.0 * ratio_b, k_a, ka_base, delta_deg))
    ctx.evidence["ka_baseline"] = {
        "baseline_k_a": ka_base, "k_a": k_a,
        "ratio": (k_a / ka_base) if ka_base else None,
        "verdict": "PASS" if ka_base is not None else "SKIP(기준 없음)",
        "path": _ka_baseline_path(ctx)}

    # ---- D1 JV steady states (method B friction + rotating commutation check) ---------
    jv_pts = []
    stop_cnt = ctx.ca18 * JV_STOP_RPM / 60.0
    # adaptive no-load current gate (fable-critic #1): this unit's geared
    # running friction can exceed the legacy fixed 0.10*CL (=2.12 A) at
    # 300 rpm while being perfectly healthy — i_ba (static breakaway) bounds
    # the running friction from above, so the gate scales with it
    i_ba_jv = ctx.evidence.get("breakaway", {}).get("i_ba_a")
    i_ss_max = (max(0.10 * ctx.cl1, JV_NOLOAD_IBA_FRAC * float(i_ba_jv))
                if isinstance(i_ba_jv, (int, float)) and i_ba_jv > 0
                else 0.10 * ctx.cl1)
    # partial-evidence hook (fable-physics 2026-07-14): jv_pts is registered
    # BEFORE the loop so an AbortError mid-D1 still leaves the collected
    # points in the result evidence (the dict holds the live list reference)
    ctx.evidence["jv"] = {"points": jv_pts, "partial": True}
    # ADAPTIVE settle (profiler-mock finding 2026-07-14, same family as the
    # verify-run capture artifact): JV rides the AC profiler, so a speed
    # TRANSITION takes |jv_new - jv_prev|/AC — the worst default rung
    # (+900 -> -300 rpm) is 1.31 s at AC=1e6, LONGER than the fixed 0.8 s
    # settle -> the record window catches mid-ramp and poisons the friction
    # fit (live runs were saved only by serial-latency-stretched sleeps).
    ac_d1 = ctx.readings.get("AC")
    ac_d1_ok = isinstance(ac_d1, (int, float)) and ac_d1 > 0
    jv_prev = 0.0
    for rpm in list(p.jv_speeds_rpm) + [-x for x in p.jv_speeds_rpm]:
        jv = ctx.ca18 * rpm / 60.0
        settle_s = (max(JV_SETTLE_S, abs(jv - jv_prev) / float(ac_d1) + 0.3)
                    if ac_d1_ok else JV_SETTLE_S)
        jv_prev = jv
        _seg(ctx, "jv")
        _write(ctx, "JV", jv, allow_motion=True)
        # CR p175: JV only takes effect on the next BG (begin motion).
        # Without BG the drive never starts the velocity move -> motor stays
        # still -> v_ss = record noise -> random sign-check RED (the live
        # Phase-2 D1 failure, 2026-07-14).  Same idiom as the UM=3 drag
        # sweep (PA write + BG).
        _cmd(ctx, "BG", allow_motion=True)
        _sleep(ctx, settle_s)
        _seg(ctx, "jv")                              # re-arm timebox per point
        _record_start(ctx, JV_RECORD_S)
        _sleep(ctx, JV_RECORD_S + 0.02)
        rec = _record_fetch(ctx)
        i_ss = float(np.mean(rec["i"]))
        v_ss = float(np.mean(rec["v"]))
        jv_pts.append({"rpm": rpm, "jv_cnt_s": jv, "v_ss": v_ss, "i_ss": i_ss})
        if v_ss * jv <= 0:
            raise AbortError("JV 커뮤검증 실패: sign(v) ≠ sign(JV) @%.0frpm" % rpm)
        if abs(i_ss) > i_ss_max:
            raise AbortError("JV 무부하전류 과대 |I_ss|=%.2fA > %.2fA @%.0frpm"
                             " (게이트=max(0.10·CL, %.1f·i_ba))"
                             % (abs(i_ss), i_ss_max, JV_NOLOAD_IBA_FRAC))
    _write(ctx, "JV", 0.0, allow_motion=True)
    _cmd(ctx, "BG", allow_motion=True)   # latch JV=0 (decel); ST remains the
    _cmd(ctx, "ST", allow_motion=True)   # authoritative stop right after
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
    ctx.evidence["jv"] = {"points": jv_pts, "b_jv": b_jv, "i_c_jv": i_c_jv,
                          "i_ss_max_a": i_ss_max,
                          # breakaway prior (B1.4): static friction upper bound
                          # — expect i_ba >= I_c (stiction >= Coulomb); kept as
                          # a cross-reference, NOT a gate (기록만, 2026-07-13)
                          "i_ba_prior_a":
                              ctx.evidence.get("breakaway", {}).get("i_ba_a")}
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
    gates["G1d_intv_dpos"] = {"dev": g1d, "tol": G1D_TOL,
                              "pass": g1d <= G1D_TOL,
                              "note": "본펄스 캡처의 ∫v·dt vs ΔPos 자동검증 —"
                                      " 레코딩 dt(tres=4 상한 ×4) 유계항목 폐색"
                                      " (U-P5, 개정6 fix-5)"}
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
    if status == GREEN:
        _save_ka_baseline(ctx, k_a)     # GREEN-only re-baseline (oracle rule)
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
APPLY_READBACK_RTOL = 1e-3   # write-readback agreement (drive stores IEEE
                             # floats; 0.1% catches truncation/quantize/refuse
                             # while ignoring ASCII round-trip rounding)
GAIN_DECIMALS_MAX = 6        # ROOT CAUSE (fable-physics, CR p178-179 / err162
                             # p98): the firmware parser SILENTLY stores 0 for
                             # decimals with >~7 fractional digits ("%.9g" on
                             # 1.66e-4 -> "0.000166142303" = 12 fractional
                             # digits -> stored 0, no error 162).  All
                             # EAS-native observed values use <=6 fractional
                             # digits (0.08444/747.328/0.000157/20.7/178) =
                             # the proven-safe envelope.
GAIN_ROUND_RTOL = 5e-3       # rounding-induced gain error budget (0.5% -> PM
                             # shift <0.1 deg); beyond it: honest failure


def _fmt_gain(v: float) -> str:
    """Drive-safe gain literal: PLAIN decimal, <= GAIN_DECIMALS_MAX fractional
    digits, trailing zeros stripped (the EAS-native wire format).  Scientific
    notation is FORBIDDEN (drive output uses it, INPUT acceptance unverified).
    0.000166142303 -> '0.000166'."""
    s = "%.*f" % (GAIN_DECIMALS_MAX, float(v))
    s = s.rstrip("0").rstrip(".")
    return s if s and s not in ("-",) else "0"


def apply_gains_vp(link, result: AutotuneVPResult, persist: bool = False):
    """F1: write KP[2]/KI[2]/KP[3] from a GREEN/YELLOW result (MO must be 0).
    FF[1] is NEVER written (advisory only).  SV only on explicit persist.

    LIVE INCIDENT 2026-07-14: the drive SILENTLY stored 0 for
    KP[2]=0.000166142303 (no error response), the old code saw no exception,
    ran SV, and reported success — a zero velocity P-gain was PERSISTED.
    Hardening (root cause owned by fable-physics, independent of it):
      * every write is READ BACK and compared (rtol 0.1%);
      * readback <= 0 is an explicit failure (gains are positive by design);
      * SV runs ONLY after ALL three readbacks verify — a partial failure
        returns False with the request/readback pair spelled out and the
        note that SV was NOT executed (power cycle restores saved gains)."""
    if result is None or result.status not in (GREEN, YELLOW) \
            or result.kp_vel is None:
        return False, "적용 불가: 결과 상태 %s" % (result.status if result else None)
    try:
        if _to_num(link.command("MO")) == 1:
            return False, "모터 ON(MO=1) — STOP 후 적용"
        applied = []
        for name, req in (("KP[2]", result.kp_vel), ("KI[2]", result.ki_vel_hz),
                          ("KP[3]", result.kp_pos)):
            req = float(req)
            lit = _fmt_gain(req)                 # drive-safe wire literal
            sent = float(lit)
            tail = (" — SV 미실행: 전원 재투입 시 이전 저장값 복귀"
                    " (RAM 반영분: %s)" % (", ".join(applied) or "없음"))
            if sent <= 0.0:
                # the exact silent-zero accident, caught BEFORE transmission:
                # a sub-1e-6 gain vanishes at 6 fractional digits
                return False, ("%s 전송 불가: 요청 %.9g가 소수 %d자리 반올림"
                               "에서 %s로 소멸 (0 전송 금지)%s"
                               % (name, req, GAIN_DECIMALS_MAX, lit, tail))
            if abs(sent / req - 1.0) > GAIN_ROUND_RTOL:
                return False, ("%s 전송 불가: 소수 %d자리 반올림 오차 %.2f%%"
                               " > %.1f%% (요청 %.9g → 전송 %s)%s"
                               % (name, GAIN_DECIMALS_MAX,
                                  100.0 * abs(sent / req - 1.0),
                                  100.0 * GAIN_ROUND_RTOL, req, lit, tail))
            link.command("%s=%s" % (name, lit))
            rb = _to_num(link.command(name))
            # readback is compared against the SENT (rounded) value, not the
            # raw design value — the rounding budget is owned by
            # GAIN_ROUND_RTOL above, the wire integrity by this gate
            if not isinstance(rb, (int, float)) or \
                    (isinstance(rb, float) and math.isnan(rb)):
                return False, "%s 되읽기 실패: 전송 %s → 응답 %r%s" % (
                    name, lit, rb, tail)
            if rb <= 0.0:
                return False, ("%s 쓰기 실패: 요청 %.9g(전송 %s) → 드라이브"
                               " %.9g (0/음수 — 무성 거부/절삭 의심)%s"
                               % (name, req, lit, rb, tail))
            if abs(rb - sent) > APPLY_READBACK_RTOL * abs(sent):
                return False, ("%s 쓰기 불일치: 요청 %.9g(전송 %s) → 드라이브"
                               " %.9g (편차 %.2f%% > %.1f%%)%s"
                               % (name, req, lit, rb,
                                  100.0 * abs(rb - sent) / sent,
                                  100.0 * APPLY_READBACK_RTOL, tail))
            applied.append("%s=%s(되읽기 %.6g)" % (name, lit, rb))
        if persist:
            try:
                link.command("SV")
            except Exception as e:
                return False, ("SV 실패: %s — 게인은 RAM 반영됨(%s), 영구저장"
                               " 안 됨" % (e, ", ".join(applied)))
        return True, "%s 적용·되읽기 검증 통과%s (FF[1] 미변경)" % (
            ", ".join(applied), " + SV" if persist else "")
    except Exception as e:
        return False, "적용 실패: %s — SV 미실행" % e


def verify_run_vp(link, params: Optional[AutotuneVPParams] = None
                  ) -> AutotuneVPResult:
    """F2/G5: JV step-response ACCEPTANCE run for the APPLIED gains.

    Speed ladder (default 300 -> 900 rpm, next step only after a pass); each
    step starts from rest, captures the full transient with the drive
    recorder (record BEFORE the step so the rise is in-frame), and is judged
    on: overshoot < 25% HARD (SPEC §6's 15% = YELLOW advisory), no sustained
    oscillation (steady-tail RMS must decay or sit under the noise floor),
    steady-state velocity sign+magnitude (+-5%), steady-state current under
    max(0.10*CL[1]) HARD with an optional unit window as YELLOW.

    SAFETY: real rotation — the CALLER owns the operator gate (free-rotation
    confirm dialog; NEVER unattended).  Reuses the D1 machinery wholesale:
    JV writes are latched with BG (CR p175), 1200 rpm VX guard + segment
    timebox during every sleep, and the JV abort chain
    (JV=0 -> BG -> ST -> wait |VX|<30rpm -> MO=0).  Never raises."""
    params = params or AutotuneVPParams()
    synthetic = (params.synthetic if params.synthetic is not None
                 else bool(getattr(link, "is_synthetic", False)))
    if synthetic:
        params = _dc_replace(params, snapshot_dir=os.path.join(
            params.snapshot_dir, SYNTHETIC_SUBDIR))
    ctx = _Ctx(link, params)
    if synthetic:
        ctx.evidence["synthetic_quarantine"] = params.snapshot_dir
    try:
        return _verify_pipeline(ctx)
    except PreflightError as e:
        return _red(ctx, str(e))
    except AbortError as e:
        _do_abort(ctx, str(e))
        return _red(ctx, str(e))
    except Exception as e:
        _do_abort(ctx, "내부 예외: %r" % (e,))
        return _red(ctx, "내부 예외: %r" % (e,))


_VERIFY_READS = ("TS", "UM", "MF", "GS[2]", "CA[18]", "CL[1]",
                 "KP[2]", "KI[2]", "KP[3]",
                 "VH[2]", "SD", "HL[2]", "LL[2]", "ER[2]")
_VERIFY_READS_OPT = ("AC", "DC")     # profiler limits: FAIL-OPEN (a missing
                                     # AC falls back to the fixed window)


def _analyze_jv_step(ctx: _Ctx, rec: dict, rpm: float,
                     t_ramp: Optional[float] = None,
                     record_s: float = VERIFY_RECORD_S) -> dict:
    """G5 metrics + verdict for one JV step capture.  Returns the step dict;
    hard failures are listed in step['fails'], advisories in step['notes'].

    PROFILER-AWARE (live artifact fix 2026-07-14): JV rides the AC/DC
    profiler, so the first t_ramp = |jv|/AC of the response is a commanded
    RAMP, not loop dynamics.  Steady-state / oscillation judgments use only
    the POST-RAMP region, and the settle time is split into total (ramp
    included — that is what the operator sees) and post-ramp (what the loop
    is responsible for; the gates judge THIS)."""
    v, i, dt = rec["v"], rec["i"], float(rec["dt"])
    n = len(v)
    v_t = ctx.ca18 * rpm / 60.0
    sgn = 1.0 if v_t >= 0 else -1.0
    fails, notes = [], []
    band_ref = abs(v_t)
    # onset = first sample with commanded motion visible (post pre-roll)
    onset = [k for k in range(n)
             if abs(v[k]) > max(VERIFY_BAND_FRAC * band_ref, 3000.0)]
    k0 = onset[0] if onset else 0
    k_end = (min(n, k0 + int(math.ceil(t_ramp / dt)))
             if t_ramp is not None else None)
    if k_end is not None and k_end >= int(0.9 * n):
        # the artifact class itself, gated honestly: never judge a ramp
        fails.append("정상상태 미도달: 캡처 %.2fs < 프로파일러 램프 %.3fs+여유"
                     " — 창 부족(아티팩트 방지 게이트)" % (n * dt, t_ramp))
    # steady window = last 30%, but never earlier than ramp end + 50 ms
    ss_start = int(0.7 * n)
    if k_end is not None:
        ss_start = min(max(ss_start, k_end + int(0.05 / dt)), int(0.9 * n))
    ss = slice(ss_start, n)
    v_ss = float(np.mean(v[ss]))
    i_ss = float(np.mean(i[ss]))
    short = bool(fails)                          # capture-shortfall gate hit
    # -- steady-state sign + magnitude (HARD; skipped on shortfall: a mid-
    #    ramp mean is not a steady state, judging it would stack phantoms) ---
    if not short:
        if v_ss * v_t <= 0:
            fails.append("정상상태 부호 불일치: v_ss=%.0f vs JV=%.0f cnt/s"
                         " (모션 미발효/커뮤 의심)" % (v_ss, v_t))
        elif abs(v_ss / v_t - 1.0) > VERIFY_VSS_TOL:
            fails.append("정상상태 크기 이탈: v_ss=%.0f vs %.0f cnt/s"
                         " (%.1f%% > %.0f%%)"
                         % (v_ss, v_t, 100 * abs(v_ss / v_t - 1.0),
                            100 * VERIFY_VSS_TOL))
    # -- overshoot (HARD 25%, SPEC 15% advisory) -------------------------------------
    ref = abs(v_ss) if v_ss * v_t > 0 else abs(v_t)
    os_frac = max(0.0, float(np.max(v * sgn)) / ref - 1.0) if ref > 0 else 0.0
    if not short:
        if os_frac > VERIFY_OVERSHOOT_MAX:
            fails.append("오버슈트 %.1f%% > %.0f%% (게인 과대/PM 부족 의심)"
                         % (100 * os_frac, 100 * VERIFY_OVERSHOOT_MAX))
        elif os_frac > VERIFY_OVERSHOOT_SPEC:
            notes.append("오버슈트 %.1f%% — physics 25%% 이내 통과, SPEC §6"
                         " 15%% 초과(advisory)" % (100 * os_frac))
    # -- settle time: TOTAL includes the profiler ramp (what the operator
    #    sees); the gates judge the POST-RAMP part (what the loop owns) ------
    band = VERIFY_BAND_FRAC * max(ref, 1.0)
    out = [k for k in range(k0, n) if abs(v[k] * sgn - abs(v_ss)) > band]
    settled = (not out) or (out[-1] < int(0.95 * n))
    t_settle = ((out[-1] + 1 - k0) * dt if out else 0.0) if settled else None
    t_post = (max(0.0, (out[-1] + 1 - k_end) * dt)
              if (settled and out and k_end is not None)
              else t_settle)
    if not short:
        if not settled:
            fails.append("±%.0f%% 대역 미정착 (캡처 %.2fs 내)"
                         % (100 * VERIFY_BAND_FRAC, n * dt))
        elif t_post is not None and t_post > VERIFY_SETTLE_MAX_S:
            fails.append("램프 후 정착시간 %.0fms > %.0fms (HARD)"
                         % (1e3 * t_post, 1e3 * VERIFY_SETTLE_MAX_S))
        elif t_post is not None and t_post > VERIFY_SETTLE_SPEC_S:
            notes.append("램프 후 정착 %.0fms — SPEC §6 60ms 초과(advisory;"
                         " 총 정착 %.0fms에는 프로파일러 램프 t_ramp=%.3fs"
                         " 포함)" % (1e3 * t_post,
                                     1e3 * (t_settle or 0.0), t_ramp or 0.0))
    # -- sustained oscillation (HARD): POST-RAMP tail residual must decay ----
    #    (live artifact: the ramp slope inside a too-short window reads as a
    #    48x-noise "oscillation" — the ss window above starts after ramp end)
    tail = v[ss] - v_ss
    half = len(tail) // 2
    rms1 = float(np.sqrt(np.mean(tail[:half] ** 2))) if half else 0.0
    rms2 = float(np.sqrt(np.mean(tail[half:] ** 2))) if half else 0.0
    osc_floor = VERIFY_OSC_FLOOR_FRAC * max(abs(v_ss), 1.0)
    sustained = rms2 > osc_floor and rms2 > VERIFY_OSC_DECAY * rms1
    if sustained and not short:
        fails.append("지속 발진: 정착후 잔진동 RMS %.0f→%.0f cnt/s 비감쇠"
                     " (>%.0f 노이즈층, 한계주기/게인과대 의심)"
                     % (rms1, rms2, osc_floor))
    # -- steady-state current (HARD generic + optional unit window YELLOW) ----------
    iss_max = 0.10 * ctx.cl1
    if abs(i_ss) > iss_max and not short:
        fails.append("무부하전류 과대 |I_ss|=%.2fA > %.2fA (0.10·CL)"
                     % (abs(i_ss), iss_max))
    exp = ctx.params.verify_iss_expect_a
    if exp is not None and len(exp) == 2 and not fails:
        lo, hi = float(exp[0]), float(exp[1])
        if not (lo <= abs(i_ss) <= hi):
            notes.append("I_ss=%.3fA가 유닛 기대창 [%.2f, %.2f]A 밖 —"
                         " 마찰 변화/온도 확인(advisory)" % (abs(i_ss), lo, hi))
    return {"rpm": rpm, "jv_cnt_s": v_t, "v_ss": round(v_ss, 1),
            "i_ss": round(i_ss, 4), "overshoot_frac": round(os_frac, 4),
            "t_settle_s": (round(t_settle, 4) if t_settle is not None
                           else None),
            "t_settle_post_s": (round(t_post, 4) if t_post is not None
                                else None),
            "settle_includes_ramp": t_ramp is not None,
            "t_ramp_s": (round(t_ramp, 4) if t_ramp is not None else None),
            "record_s_used": round(record_s, 4),
            "osc_rms_1st": round(rms1, 1), "osc_rms_2nd": round(rms2, 1),
            "dt_s": dt, "n_samples": n,
            "v_curve": [round(float(x), 1) for x in v[::max(1, n // 300)]],
            "i_curve": [round(float(x), 4) for x in i[::max(1, n // 300)]],
            "fails": fails, "notes": notes, "pass": not fails}


def _verify_pipeline(ctx: _Ctx) -> AutotuneVPResult:
    p = ctx.params
    # ---- P0 (mirror of the main pipeline) ----------------------------------------------
    if not getattr(ctx.link, "is_connected", False):
        raise PreflightError("드라이브 미연결")
    if _cmd(ctx, "MO") == 1:
        raise PreflightError("모터 ON(MO=1) — STOP 후 재시도 (자동 disable 금지)")
    _emit(ctx, "P0", "F2 검증런: 연결 확인, MO=0 게이트 통과")
    for c in _VERIFY_READS:
        ctx.readings[c] = _cmd(ctx, c)
    for c in _VERIFY_READS_OPT:                 # AC/DC: fail-open (fallback)
        try:
            ctx.readings[c] = _cmd(ctx, c, retries=0)
        except Exception:
            ctx.readings[c] = None
    ctx.evidence["readings"] = dict(ctx.readings)
    r = ctx.readings
    ts = r["TS"]
    if not isinstance(ts, (int, float)) or not (40 <= ts <= 200):
        raise PreflightError("TS=%r 비정상" % (ts,))
    ctx.ts_s = ts * 1e-6
    if r.get("UM") != 5:
        raise PreflightError("UM=%r (5 필요)" % (r.get("UM"),))
    if not isinstance(r.get("MF"), (int, float)) or r["MF"] != 0:
        raise PreflightError("모터 폴트 MF=%r" % (r.get("MF"),))
    if r.get("GS[2]") not in (0, 0.0):
        raise PreflightError("게인 스케줄링 활성(GS[2]=%r) — 검증 무의미" %
                             (r.get("GS[2]"),))
    cl1 = r.get("CL[1]")
    if not isinstance(cl1, (int, float)) or cl1 <= 0:
        raise PreflightError("CL[1]=%r 비정상" % (cl1,))
    ctx.cl1 = float(cl1)
    ca18 = r.get("CA[18]")
    ctx.ca18 = float(ca18) if isinstance(ca18, (int, float)) and ca18 > 0 \
        else 65536.0
    ctx.vx_guard_cnt = ctx.ca18 * GUARD_RPM / 60.0
    for rpm in p.verify_speeds_rpm:
        if abs(rpm) >= GUARD_RPM:
            raise PreflightError("검증속도 %.0frpm ≥ 가드 %.0frpm — 사다리 부적합"
                                 % (rpm, GUARD_RPM))
    _emit(ctx, "VALIDATE", "게인 하 검증: KP[2]=%s KI[2]=%s KP[3]=%s |"
          " 사다리 %s rpm" % (r.get("KP[2]"), r.get("KI[2]"), r.get("KP[3]"),
                              list(p.verify_speeds_rpm)))
    # ---- signals + snapshot (quarantine-aware dir) --------------------------------------
    _resolve_signals(ctx)
    ctx.snapshot = dict(ctx.readings)
    os.makedirs(p.snapshot_dir, exist_ok=True)
    ctx.snapshot_path = os.path.join(
        p.snapshot_dir, "verify_vp_snapshot_%d.json" % int(time.time() * 1000))
    with open(ctx.snapshot_path, "w", encoding="utf-8") as fj:
        json.dump({"t": time.time(), "readings": ctx.snapshot}, fj,
                  ensure_ascii=False, indent=1)
    ctx.evidence["snapshot_path"] = ctx.snapshot_path
    _emit(ctx, "SNAPSHOT", "스냅숏 저장: %s" % ctx.snapshot_path)
    # ---- explicit limits (same discipline as the main pipeline, U-P4) ------------------
    limit_rb = {}
    for cmd, val in LIMIT_WRITES:
        try:
            _write(ctx, cmd, val)
            limit_rb[cmd] = _cmd(ctx, cmd)
        except Exception as e:
            ctx.warnings.append("리밋 %s 쓰기 거부(%s) — SW가드로 보완(U-P4)"
                                % (cmd, e))
    ctx.evidence["limits"] = limit_rb
    # ---- enable ------------------------------------------------------------------------
    _cmd(ctx, "MO=1", allow_motion=True)
    ctx.motor_on = True
    waited = 0.0
    while _cmd(ctx, "SO") != 1:
        if waited >= 2.0:
            raise AbortError("SO!=1 (2s) — 서보온 실패")
        _sleep(ctx, p.poll_s)
        waited += p.poll_s
    _emit(ctx, "ENABLE", "MO=1 통전 — JV 스텝 사다리 시작")
    # ---- JV step ladder ------------------------------------------------------------------
    # adaptive capture window (live artifact fix 2026-07-14): JV rides the
    # AC profiler — the window must cover t_ramp = |jv|/AC plus a steady
    # tail, else mid-ramp is read as steady state (900 rpm @ AC=1e6 ramps
    # 0.983 s > the old fixed 0.6 s -> 3 phantom hard REDs)
    ac = ctx.readings.get("AC")
    ac_ok = isinstance(ac, (int, float)) and ac > 0
    if not ac_ok:
        ctx.warnings.append("AC 판독불가 — 프로파일러 램프 보정 불가(고정"
                            " %.1fs 창 폴백): 고속 스텝은 창 부족 게이트로"
                            " 정직 RED 될 수 있음" % VERIFY_RECORD_S)
    steps = []
    ctx.evidence["verify"] = {"speeds_rpm": list(p.verify_speeds_rpm),
                              "steps": steps,
                              "ac_cnt_s2": (float(ac) if ac_ok else None),
                              "criteria": {
                                  "overshoot_max": VERIFY_OVERSHOOT_MAX,
                                  "overshoot_spec": VERIFY_OVERSHOOT_SPEC,
                                  "settle_spec_s": VERIFY_SETTLE_SPEC_S,
                                  "settle_max_s": VERIFY_SETTLE_MAX_S,
                                  "settle_tail_s": VERIFY_SETTLE_TAIL_S,
                                  "vss_tol": VERIFY_VSS_TOL,
                                  "band_frac": VERIFY_BAND_FRAC,
                                  "osc_decay": VERIFY_OSC_DECAY,
                                  "osc_floor_frac": VERIFY_OSC_FLOOR_FRAC,
                                  "iss_max_a": 0.10 * ctx.cl1,
                                  "iss_expect_a": (list(p.verify_iss_expect_a)
                                                   if p.verify_iss_expect_a
                                                   else None)}}
    stop_cnt = ctx.ca18 * JV_STOP_RPM / 60.0

    def _stop_and_wait():
        _write(ctx, "JV", 0.0, allow_motion=True)
        _cmd(ctx, "BG", allow_motion=True)       # latch JV=0 (decel)
        _cmd(ctx, "ST", allow_motion=True)
        w = 0.0
        while True:
            vx = _cmd(ctx, "VX")
            if isinstance(vx, (int, float)) and abs(vx) < stop_cnt:
                return
            if w >= JV_STOP_TIMEOUT_S:
                raise AbortError("JV 정지 대기 실패 (|VX|=%.0f)" % abs(vx))
            _sleep(ctx, 0.05)
            w += 0.05
    failed_step = None
    for rpm in p.verify_speeds_rpm:
        _seg(ctx, "jv")
        # each step starts FROM REST (ladder contract)
        w = 0.0
        while True:
            vx = _cmd(ctx, "VX")
            if isinstance(vx, (int, float)) and abs(vx) < stop_cnt:
                break
            if w >= JV_STOP_TIMEOUT_S:
                raise AbortError("스텝 전 정지 미확인 (|VX|=%.0f)" % abs(vx))
            _sleep(ctx, 0.05)
            w += 0.05
        jv = ctx.ca18 * rpm / 60.0
        t_ramp = (abs(jv) / float(ac)) if ac_ok else None
        record_s = (max(VERIFY_RECORD_S, t_ramp + VERIFY_SETTLE_TAIL_S)
                    if t_ramp is not None else VERIFY_RECORD_S)
        _emit(ctx, "VERIFY_STEP", "JV 스텝 %.0frpm (기록 %.2fs, 프로파일러"
              " 램프 %s)" % (rpm, record_s,
                             "%.3fs" % t_ramp if t_ramp is not None
                             else "미상(AC 판독불가)"))
        _record_start(ctx, record_s)             # arm FIRST: rise in-frame
        _sleep(ctx, VERIFY_PRE_S)
        _write(ctx, "JV", jv, allow_motion=True)
        _cmd(ctx, "BG", allow_motion=True)       # CR p175: JV latches on BG
        _sleep(ctx, record_s + 0.02)
        rec = _record_fetch(ctx)
        _seg(ctx, "jv")                          # re-arm timebox for the stop
        _stop_and_wait()
        step = _analyze_jv_step(ctx, rec, rpm, t_ramp=t_ramp,
                                record_s=record_s)
        steps.append(step)
        for nt in step["notes"]:
            ctx.warnings.append("F2 @%.0frpm: %s" % (rpm, nt))
        if not step["pass"]:
            failed_step = step
            break                                # ladder stops at first fail
    _seg(ctx, "idle")
    _cmd(ctx, "MO=0")
    ctx.motor_on = False
    _restore_limits(ctx)
    # ---- verdict + persistence -----------------------------------------------------------
    result_path = os.path.join(
        p.snapshot_dir, "verify_vp_result_%d.json" % int(time.time() * 1000))
    if failed_step is not None:
        status, reason = RED, ("G5 실패 @%.0frpm: %s"
                               % (failed_step["rpm"],
                                  "; ".join(failed_step["fails"])))
    else:
        status = YELLOW if ctx.warnings else GREEN
        reason = "" if status == GREEN else "; ".join(ctx.warnings)
    ctx.evidence["verify"]["verdict"] = status
    try:
        with open(result_path, "w", encoding="utf-8") as fj:
            json.dump({"t": time.time(), "status": status, "reason": reason,
                       "verify": ctx.evidence["verify"],
                       "readings": ctx.readings,
                       "warnings": ctx.warnings}, fj,
                      ensure_ascii=False, indent=1)
        ctx.evidence["result_path"] = result_path
    except Exception as e:
        ctx.warnings.append("검증결과 저장 실패: %s" % e)
    _emit(ctx, "DONE", "F2 검증런 완료 — %s" % status)
    return AutotuneVPResult(status=status, reason=reason, ts_us=int(ts),
                            evidence=ctx.evidence, warnings=ctx.warnings)
