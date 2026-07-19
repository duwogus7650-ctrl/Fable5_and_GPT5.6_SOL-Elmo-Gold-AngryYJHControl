"""Current-loop autotune, Phase 1 (measurement P0..E2) for Elmo Gold drives.

SPEC: docs/autotune-current-spec.md (fable-algorithm 2026-07-12).
Transport: elmo_link.ElmoLink.command() ONLY — this module never touches the
serial layer.  Motion-gated commands (MO=1 / TC / SE start) are sent with
allow_motion=True and MUST only be reached through an operator-confirmed UI
gate (caller's responsibility; see run_current_autotune docstring).

Method (SPEC §0/§3, voltage path re-grounded by fable-physics after live run #5):
  - UM=3 (stepper forced commutation, sensor-independent) at standstill.
  - Voltage channels 'A/B/C Voltage' are PER-LEG PWM DUTY COUNTS (mid 3750 =
    50% duty = 0 V; 'D Voltage' idle).  True phase voltage via NEUTRAL
    SUBTRACTION  v_phN = v_A - (v_A+v_B+v_C)/3  (removes 3750 offset, SVM
    common mode, and the 3/4 single-leg bias in one shot).
  - counts -> volts scale (fable-physics FINAL, live run #6): PRIMARY
    s = Vbus_rec/7500 (recorded DC Bus Voltage run-mean; live Vbus=48.46 V
    read-back confirmed; 400 Hz in-situ magnitude agreed within 2.6% = double
    confirmation).  The frequency-COMBINED in-situ scale is RETIRED (error
    phasor of two nearly-equal large phasors + continuous-C approximation +
    channel skew made z_model unphysical at 800 Hz); the in-situ MAGNITUDE at
    the LOWEST excitation frequency survives as gate G1 only.
  - R_pp = 2 * d(v_phN_bar)/dI  (two-point DC, dead-time cancels; x2 = ph->pp).
    This is the TERMINAL resistance (motor + cable/FET parasitics; live +19%
    over nameplate) — reported honestly, NOT corrected.  R does not enter the
    gain formula, so the parasitic is harmless there.
  - SKEW: the recorded voltage is THIS cycle's duty COMMAND; the motor sees it
    1 TS (compute) + 0.5 TS (PWM ZOH) later -> V leads I by tau ~ 1.5*TS.
    Z(f) = 2*s*V_phN(f)/I(f) * exp(-j*2*pi*f*1.5*TS)  (rotation correction),
    L_pp = median_f Im(Z(f))/(2*pi*f), R_ac(f) = Re(Z(f)).  Without the
    rotation the apparent L is +26..+59% high (skew-inflated).
  - Drive gain basis = PHASE-TO-PHASE (fable-physics: KP = wc*L_pp = 0.071757
    vs live 0.07177, -0.018%).  Gains: wc = 0.2010/TS_s, KP = wc*L_pp,
    KI = 2 * 1.2705 * wc/(2*pi)  — the 2x is the pp-basis factor CONFIRMED on
    live run #6 (reproduces EAS KI=812.939 at TS=100 us to ~0%).
  - GREEN gates (run #8 final — the in-situ SCALE gate G1 is ABOLISHED: the
    in-situ ratio measures the OPEN-LOOP GAIN |C(jw)G(jw)|, not the scale;
    live 4-point rms 0.3%, rho=1 crossing = 372 Hz = gain crossover):
    G0 platform grounding (pre-power, once): FS = 150e6*TS_s/XP[2]
       (document-confirmed; XP[2]!=2 recomputes; WS[57]~FS is a LIMIT note);
    G1' per run: idle leg ('D Voltage') mean == FS/2 +-1 count AND
       Vbus in [20,60] V  — these two now OWN the scale validity;
    G2 R_ac(f) in [0.8, 2.5]*R_dc at every f;
    G3 post-rotation L spread across f <= 10%;
    G4 plausibility ranges + stability gate (PM>=45 deg AND wc*TS<=0.25 AND
       0<KP<=100 AND 0<KI<=5000 on G(s)=KP(s+2*pi*KI)/s * 1/(L_pp s+R_pp)
       * exp(-1.5*TS*s));
    G5 loop-gain consistency: rho_meas(f)=|C·(Icmd-I)|/(|V_counts|*s) must
       match |C|/|R+jwL| within +-15% (validates channel combination, skew
       rotation, gain read-back and injection node — NOT s itself, which
       cancels between both sides).  All pass -> GREEN, else YELLOW.
    R nameplate band (nameplate+[5,40] mOhm) is an ADVISORY only — never
    blocks GREEN (parasitic allocation is a live question).

Recorder access (reworked 2026-07-13, docs/recording-api.md): the legacy
2-letter RC/RG/RR + BH path is RETIRED (BH takes a bitfield and returns a
hex-binary frame — our provisional text parser was wrong).  Recording now goes
through the link's .NET Drive Recording wrapper: link.recorder_signals()
(personality SignalsMetaData names) and link.record(names, length,
time_resolution) -> {name: physical doubles, 'dt': s}.  record() is BLOCKING
(~one segment, <=0.25 s): the I3 guard and cancel poll pause during it, which
stays within the 500 ms guard budget.

Honesty / hardware-pending items (cannot be verified headless — SPEC §10):
  U1  SE injection through CA[70] under UM=3 (silent-failure path -> RED).
  U2  CL[4] unit (interpreted as ms).
  U3  existence of a non-bus voltage-command signal in the personality list
      (runtime-resolved; RED+dump if absent).  Also live-unknown:
      CreatePersonalityModel upload behavior and target-specific post-Configure
      SamplingTime behavior.  The official example defines SamplingTime=TS in
      µs and dt=TimeResolution*TS; the link fails closed on readback mismatch.
  U4  SO==1 latency after MO=1 (absorbed by the B2 poll).

All failures return a RED AutotuneResult (never raise), after the fixed-order
abort chain (SPEC §6) whenever anything was already written to the drive.
"""
from __future__ import annotations

import cmath
import json
import math
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional, Sequence

import numpy as np
import persistence_audit

__all__ = ["AutotuneParams", "AutotuneResult", "run_current_autotune",
           "apply_gains", "verify_run", "loop_margins", "design_gains",
           "demod", "derive_freqs", "neutral_subtract", "pi_discrete",
           "pi_continuous", "loopgain_crossover_hz", "GainTrialP1",
           "begin_gain_trial_p1", "restore_gain_trial_p1",
           "commit_gain_trial_p1", "adopt_gain_trial_p1_for_restore",
           "p1_gain_trial_has_save_authority",
           "P1_CONFIG_NAMES", "GREEN", "YELLOW", "RED"]

GREEN, YELLOW, RED = "GREEN", "YELLOW", "RED"
P1_CONFIG_NAMES = persistence_audit.PHASE_REGISTERS["P1_CONFIG"]
_P1_CONFIG_INTEGER_NAMES = frozenset((
    "UM", "SC[8]", "CA[42]", "CA[43]", "CA[44]", "CA[70]",
    "SE[1]", "SE[4]", "SE[5]", "SE[6]", "SE[7]",
))

# --- calibration & gate constants (SPEC §4) -------------------------------------------
WC_TS_CAL = 0.2010        # wc*TS single-point calibration (EAS: KP/L_np*TS)
ALPHA_EAS = 1.2705        # base ratio; design KI = KI_PP_FACTOR*ALPHA_EAS*wc/(2*pi)
KI_PP_FACTOR = 2.0        # pp-basis 2x — live run #6 확정 (2*1.2705*wc/2pi = 812.9 = EAS)
SKEW_TAU_TS = 1.5         # recorded duty leads motor voltage by 1.5*TS (compute + ZOH/2)
PWM_CLOCK_HZ = 150e6      # G0: PWM command counter clock (CR p.291: WS[54..57] units)
G0_FS_RANGE = (500.0, 1e6)          # plausible duty full-scale counts
G1P_MID_TOL_COUNTS = 1.0  # G1': idle leg mean == FS/2 within +-1 count
G1P_VBUS_RANGE = (20.0, 60.0)       # G1': recorded bus voltage sanity [V]
G2_BAND = (0.8, 2.5)      # G2: R_ac(f)/R_dc band
G3_SPREAD = 0.10          # G3: post-rotation L spread across f
G5_TOL = 0.15             # G5: measured vs predicted LOOP GAIN per f (run #8: 2.6~4.1%)
R_ADVISORY_BAND = (0.005, 0.040)    # nameplate + [5,40] mOhm parasitic advisory (pp)
DELAY_MULT = 1.5          # loop dead time = 1.5*TS (command applied next cycle + ZOH/2)
PM_MIN_DEG = 45.0
WCTS_MAX = 0.25
KP_MAX = 100.0
KI_MAX = 5000.0
MAX_WC_REDUCTIONS = 3     # PM<45 -> wc*=0.8, at most 3 times (SPEC §4)

# E3 gain-write envelope.  The Gold drive accepted a long decimal literal but
# silently stored zero in the Phase-2 incident; EAS-native writes stay within
# six fractional digits.  Keep Phase 1 independently guarded against the same
# parser failure class.
APPLY_READBACK_RTOL = 1e-3
GAIN_DECIMALS_MAX = 6
GAIN_ROUND_RTOL = 5e-3

# --- pipeline timing constants (SPEC §7) ----------------------------------------------
T_PROBE_S = 0.20          # B3 stability probe record
T_DC_RECORD_S = 0.25      # C1 steady-window record per DC level
T_RAMP_LEVEL_S = 0.30     # C1 I1->I2 ramp
T_RAMP_BACK_S = 0.20      # C3 I2->I1 ramp
T_SINE_RECORD_S = 0.20    # D1 record (>=0.18 s required)
T_SINE_SETTLE_S = 0.05    # settle after WS[75]==2 before the record
T_RAMP_DOWN_S = 0.30      # E1 TC->0
ALIGN_STEPS = 10          # B4: 10 steps x 100 ms
ALIGN_STEP_S = 0.10
# B4 pre-alignment (2026-07-13 fix, fable-physics live RED |dPX|=2191>364):
# align at the MEASUREMENT MAXIMUM current i2 BEFORE latching px_ref, ratchet
# i1<->i2 quasi-statically until the cycle-end |dPX| converges, then latch.
PREALIGN_CYCLES_MAX = 3   # ratchet upper bound (no infinite loop)
PREALIGN_PITCH_MULT = 1.5 # relaxed PX guard during pre-align [pole pitches]
T_PREALIGN_SETTLE_S = 0.3 # settle after each pre-align ramp leg
POLE_PAIRS_FALLBACK = 16.0  # CA[19] unreadable -> legacy assumption + warning
GUARD_PERIOD_S = 0.5      # I3: MF/LC/PX poll period while MO=1
RECORDER_MAX_RL = 4096    # per-signal sample cap (CR: 16384/4 signals); longer -> TimeResolution up
# Reference values for THIS drive at TS=100us, XP[2]=2 (tests/mock use these).
# The PIPELINE never hardcodes them: G0 derives FS = PWM_CLOCK_HZ*TS_s/XP[2]
# (document-CONFIRMED, CR p.290/325: TS*f_pwm = XP[2]/2, default 2; live mid=3750).
DUTY_MID = 3750.0
DUTY_FS = 7500.0

_MOTION_TRUE = dict(allow_motion=True)


# ======================================================================================
# dataclasses (SPEC §1)
# ======================================================================================
def _noop_progress(code: str, detail: str) -> None:
    """Default progress hook: do nothing."""


def _never_cancel() -> bool:
    """Default cancel hook: never cancel."""
    return False


@dataclass
class AutotuneParams:
    i_frac_low: float = 0.25            # I1 = i_frac_low  * CL[1]  [A amplitude]
    i_frac_high: float = 0.50           # I2 = i_frac_high * CL[1]
    # None (default) = auto-derive from the MEASURED TS at P2 via derive_freqs()
    # (f1~0.32*f_max, f2~0.64*f_max, f_max=0.125/TS — drive-agnostic; TS=50us
    # reproduces the old fixed default (800,1600), TS=100us gives (400,800)).
    # An explicit tuple keeps the strict P2 validation (f>f_max -> RED) as before.
    freqs_hz: Optional[Sequence[float]] = None
    sine_target_amp: float = 3.0        # desired ACTUAL current sine amplitude [A]
    wc_override_hz: Optional[float] = None
    ki_rule: str = "eas_ratio"          # "eas_ratio" | "pole_zero"
    nameplate_r_pp: Optional[float] = None      # phase-to-phase [ohm]
    nameplate_l_pp_h: Optional[float] = None    # phase-to-phase [H]
    # --- injection points (headless tests replace sleep_fn with the sim clock) -------
    sleep_fn: Callable[[float], None] = time.sleep
    snapshot_dir: str = os.path.join(".omc", "state")
    poll_s: float = 0.01
    # --- GUI hooks (both NON-INVASIVE: their exceptions never kill the run) -----------
    # progress_fn(code, detail): phase-boundary notifications, codes =
    #   P0, VALIDATE, SNAPSHOT, ENABLE, ALIGN, MEASURE_R, MEASURE_L, DESIGN, DONE.
    #   Exceptions are swallowed (logged to evidence["progress_errors"] only, so a
    #   broken GUI hook cannot flip a GREEN verdict).
    # cancel_fn() -> True requests a SAFE operator stop: polled on every _sleep
    #   chunk; raises AbortError("작업자 중단 요청") so the SPEC §6 abort chain
    #   (MO=0 -> TW[80]=0 -> TC=0 -> snapshot restore -> RR=0) runs unchanged.
    #   A RAISING cancel_fn is NOT a cancel: ignored, noted once in warnings.
    progress_fn: Callable[[str, str], None] = _noop_progress
    cancel_fn: Callable[[], bool] = _never_cancel


@dataclass
class AutotuneResult:
    status: str
    reason: str = ""
    kp_v_per_a: Optional[float] = None
    ki_hz: Optional[float] = None
    r_phase_ohm: Optional[float] = None
    r_pp_ohm: Optional[float] = None
    l_phase_h: Optional[float] = None
    l_pp_h: Optional[float] = None
    wc_rad_s: Optional[float] = None
    pm_deg: Optional[float] = None
    ts_us: Optional[int] = None
    evidence: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


class PreflightError(Exception):
    """P0..P2 failure BEFORE anything was written: RED without the abort chain
    (in particular: never auto-disables an already-enabled motor)."""


class AbortError(Exception):
    """Failure after drive state may have been touched: run SPEC §6 abort chain."""


# ======================================================================================
# pure analysis functions (unit-testable without a link)
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


def _exact_config_snapshot_number(value, register: str):
    """Reject any P1_CONFIG snapshot value that float conversion would alter."""

    if isinstance(value, bool) or value is None:
        raise ValueError("%s is not a numeric literal: %r" % (register, value))
    token = str(value).strip().rstrip(";").strip()
    try:
        number = Decimal(token)
    except (InvalidOperation, ValueError):
        raise ValueError(
            "%s is not a numeric literal: %r" % (register, value)) from None
    if not number.is_finite():
        raise ValueError("%s is not finite: %r" % (register, value))
    if register in _P1_CONFIG_INTEGER_NAMES:
        if number != number.to_integral_value():
            raise ValueError(
                "%s is not an exact integer: %r" % (register, value))
        return int(number)
    observed = float(number)
    if not math.isfinite(observed) or number != Decimal(str(observed)):
        raise ValueError(
            "%s exceeds exact numeric precision: %r" % (register, value))
    return observed


def demod(x: np.ndarray, f_hz: float, dt_s: float) -> complex:
    """Single-frequency demodulation X_f = 2*mean(x*exp(-j*2*pi*f*k*dt)) (SPEC §3.3)."""
    k = np.arange(len(x))
    return complex(2.0 * np.mean(np.asarray(x, float) *
                                 np.exp(-1j * 2 * np.pi * f_hz * k * dt_s)))


def integer_cycle_window(n: int, f_hz: float, dt_s: float) -> int:
    """Largest window length <= n spanning an integer number of cycles of f."""
    n_cyc = int(math.floor(f_hz * n * dt_s))
    if n_cyc < 1:
        return 0
    return int(round(n_cyc / (f_hz * dt_s)))


def l_from_z(z_mag: float, r_ph: float, f_hz: float) -> float:
    return math.sqrt(max(z_mag * z_mag - r_ph * r_ph, 0.0)) / (2 * math.pi * f_hz)


def derive_freqs(ts_s: float, r_ph: Optional[float] = None,
                 l_ph: Optional[float] = None, step_hz: float = 50.0,
                 f_min_hz: float = 150.0) -> tuple:
    """3-4 drive-agnostic excitation frequencies from the MEASURED sampling
    time (extended from 2 points per live run #6 — more f points firm up the
    L median and enable a future (L, tau) least-squares; tau stays fixed at
    1.5*TS for now).

    f_max = 0.125/TS; candidates at (0.16, 0.32, 0.48, 0.64)*f_max snapped to
    step_hz: TS=100us -> (200, 400, 600, 800), TS=50us -> (400, 800, 1200,
    1600); all in [f_min_hz, f_max).  L-observability (soft): when R/L are
    given (same basis, e.g. terminal R + nameplate L), drop low points with
    w*L < 0.25*R while >=2 remain; if none qualify, fall back to the top two
    grid points below f_max."""
    f_max = 0.125 / ts_s
    cands = []
    for frac in (0.16, 0.32, 0.48, 0.64):
        f = round(frac * f_max / step_hz) * step_hz
        while f >= f_max:
            f -= step_hz
        f = max(f, f_min_hz)
        if f < f_max and (not cands or f > cands[-1]):
            cands.append(float(f))
    if r_ph and l_ph:
        obs = [f for f in cands if 2 * math.pi * f * l_ph >= 0.25 * r_ph]
        if len(obs) >= 2:
            cands = obs
        else:                                       # all too resistive: go high
            top = math.floor((f_max - 1e-9) / step_hz) * step_hz
            cands = [float(f) for f in (top - step_hz, top)
                     if f_min_hz <= f < f_max]
    if len(cands) < 2:
        raise ValueError("derive_freqs: insufficient points (f_max=%.0f)" % f_max)
    return tuple(cands)


def neutral_subtract(leg_a, leg_b, leg_c) -> np.ndarray:
    """v_phN = leg_A - (leg_A+leg_B+leg_C)/3 (fable-physics correction, live
    run #5): removes the 3750 mid-duty offset, the SVM min-max common-mode
    injection, and the 3/4 single-leg bias in one shot — leaves the true
    phase-to-neutral voltage (still in duty counts, unscaled)."""
    a = np.asarray(leg_a, dtype=float)
    b = np.asarray(leg_b, dtype=float)
    c = np.asarray(leg_c, dtype=float)
    return a - (a + b + c) / 3.0


def pi_continuous(f_hz: float, kp: float, ki_hz: float) -> complex:
    """Continuous drive PI  C(jw) = KP*(jw + 2*pi*KI)/(jw)  — the G5 loop-gain
    prediction basis (run #9 fix: mixing the DISCRETE C into rho_pred made it
    look like a wrong inductance, L~34.5uH instead of the reported L-hat)."""
    w = 2 * math.pi * f_hz
    return kp * (1j * w + 2 * math.pi * ki_hz) / (1j * w)


def loopgain_crossover_hz(kp: float, ki_hz: float, r_pp: float, l_pp: float,
                          f_lo: float = 10.0, f_hi: float = 20000.0) -> Optional[float]:
    """Numeric solve of |C(jw)|/|R+jwL| = 1 (continuous C, log-grid + log-log
    interpolation) — replaces the retired KP/L asymptotic crossover formula."""
    fs = np.logspace(math.log10(f_lo), math.log10(f_hi), 4000)
    rho = np.array([abs(pi_continuous(f, kp, ki_hz))
                    / abs(complex(r_pp, 2 * math.pi * f * l_pp)) for f in fs])
    lr = np.log(rho)
    for i in range(len(fs) - 1):
        if lr[i] == 0:
            return float(fs[i])
        if lr[i] * lr[i + 1] < 0:
            t = lr[i] / (lr[i] - lr[i + 1])
            return float(math.exp(math.log(fs[i])
                                  + t * (math.log(fs[i + 1]) - math.log(fs[i]))))
    return None


def pi_discrete(f_hz: float, ts_s: float, kp: float, ki_hz: float) -> complex:
    """Drive PI frequency response C_d(e^{jwTS}) for the Elmo law
    u = KP*(e + 2*pi*KI*TS*sum(e))  (backward-sum integrator, SPEC §9).
    Used by the in-situ scale; the continuous C(s)=KP(s+2*pi*KI)/s deviates
    ~10% in magnitude / ~7 deg at f*TS~0.08, so the discrete form is required."""
    z = cmath.exp(1j * 2 * math.pi * f_hz * ts_s)
    return kp * (1.0 + 2 * math.pi * ki_hz * ts_s * (z / (z - 1.0)))


def loop_margins(kp: float, ki_hz: float, r_ph: float, l_ph: float, ts_s: float,
                 delay_mult: float = DELAY_MULT):
    """(crossover rad/s, PM deg) of G(s)=KP(s+2*pi*KI)/s * 1/(Ls+R) * e^(-delay*s)."""
    w = np.logspace(2, 5.3, 200000)
    C = kp * (1j * w + 2 * np.pi * ki_hz) / (1j * w)
    P = 1.0 / (l_ph * 1j * w + r_ph)
    D = np.exp(-1j * w * delay_mult * ts_s)
    G = C * P * D
    mag = np.abs(G)
    ph = np.unwrap(np.angle(G))
    ic = int(np.argmin(np.abs(mag - 1.0)))
    pm = 180.0 + math.degrees(ph[ic])
    return float(w[ic]), float(pm)


def design_gains(l_ph: float, r_ph: float, ts_s: float, params: AutotuneParams):
    """SPEC §4: gains + stability gate with up to 3 wc reductions.
    Returns (ok, kp, ki_hz, wc, pm_deg, wx_rad_s, iters)."""
    if params.wc_override_hz:
        wc = 2 * math.pi * float(params.wc_override_hz)
    else:
        wc = WC_TS_CAL / ts_s
    iters = []
    kp = ki = pm = wx = None
    for _ in range(1 + MAX_WC_REDUCTIONS):
        kp = wc * l_ph
        if params.ki_rule == "pole_zero":
            ki = r_ph / (2 * math.pi * l_ph)
        else:                                       # "eas_ratio" (default)
            # KI = 2*alpha*wc/2pi — the 2x pp-basis factor was CONFIRMED on
            # live run #6 (matches EAS KI=812.939 at TS=100us to ~0%)
            ki = KI_PP_FACTOR * ALPHA_EAS * wc / (2 * math.pi)
        wx, pm = loop_margins(kp, ki, r_ph, l_ph, ts_s)
        ok = (pm >= PM_MIN_DEG and wc * ts_s <= WCTS_MAX
              and 0 < kp <= KP_MAX and 0 < ki <= KI_MAX)
        iters.append({"wc_rad_s": wc, "kp": kp, "ki_hz": ki,
                      "pm_deg": pm, "crossover_hz": wx / (2 * math.pi),
                      "wc_ts": wc * ts_s, "pass": ok})
        if ok:
            return True, kp, ki, wc, pm, wx, iters
        wc *= 0.8
    return False, kp, ki, iters[-1]["wc_rad_s"], pm, wx, iters


# ======================================================================================
# pipeline context + low-level transport helpers
# ======================================================================================
class _Ctx:
    def __init__(self, link, params: AutotuneParams):
        self.link = link
        self.params = params
        self.readings: dict = {}
        self.raw_readings: dict = {}
        self.evidence: dict = {}
        self.warnings: list = []
        self.snapshot: dict = {}
        self.snapshot_path: Optional[str] = None
        self.dirty: list = []           # commands actually written (for targeted restore)
        self.socket: Optional[int] = None
        self.motor_on = False
        self.aborted = False
        self.ts_s: float = 0.0
        self.cl1: float = 0.0
        self.tc_now: float = 0.0
        self.px_ref: Optional[float] = None
        self.px_tol: float = float("inf")
        self.noise_std: float = 0.02
        self.bootstrapped = False
        self.guard_due_s = 0.0          # sim/wall seconds until next I3 guard poll
        self.cancel_err_logged = False  # first-only warning for a raising cancel_fn
        self.freqs: tuple = ()          # excitation frequencies resolved at P2
        self.dt_warned = False          # first-only warning for provisional dt fallback
        self.vbus_samples: list = []    # per-record Vbus means (primary scale source)
        self.duty_fs: float = DUTY_FS   # G0-derived duty full scale (never hardcoded)
        self.g0: dict = {}              # G0 platform-grounding gate record
        self.g1p: dict = {}             # G1' idle-leg/Vbus gate record
        self.config_attempt_id: Optional[str] = None
        self.config_restore_finalized = False


def _cmd(ctx: _Ctx, cmd: str, allow_motion: bool = False, retries: int = 2):
    """command() with I5 retry policy (1 s timeout x2 retries -> abort) and
    NaN gate (SPEC §8: NaN response -> immediate abort)."""
    last = None
    for _ in range(retries + 1):
        try:
            kwargs = {
                "timeout_ms": 1000,
                "allow_motion": allow_motion,
            }
            if ctx.config_attempt_id is not None:
                kwargs["_persistence_attempt_id"] = ctx.config_attempt_id
            resp = ctx.link.command(cmd, **kwargs)
            core = "".join(str(cmd).split()).upper().rstrip(";")
            if "=" not in core:
                ctx.raw_readings[core] = resp
            val = _to_num(resp)
            if isinstance(val, float) and math.isnan(val):
                raise AbortError("NaN 응답 (%s) — 즉시 중단" % cmd)
            return val
        except (AbortError, PermissionError):
            raise
        except Exception as e:                      # comm/drive error -> retry
            last = e
    raise AbortError("통신 실패 %r: %s" % (cmd, last))


def _write(ctx: _Ctx, cmd: str, value, allow_motion: bool = False):
    _check_cancel_before_mutation(ctx)
    ctx.dirty.append(cmd)
    return _cmd(ctx, "%s=%s" % (cmd, _fmt(value)), allow_motion=allow_motion)


def _fmt(v):
    if isinstance(v, float):
        return "%.9g" % v
    return str(v)


def _emit(ctx: _Ctx, code: str, detail: str):
    """Non-invasive progress notification.  Hook exceptions are swallowed and
    logged to evidence["progress_errors"] (NOT ctx.warnings — a broken GUI hook
    must not degrade the tuning verdict)."""
    try:
        ctx.params.progress_fn(code, detail)
    except Exception as e:
        errs = ctx.evidence.setdefault("progress_errors", [])
        if len(errs) < 8:
            errs.append("%s: %r" % (code, e))


def _check_cancel(ctx: _Ctx):
    """Operator-stop poll (every _sleep chunk).  True -> AbortError so the
    SPEC §6 abort chain runs.  A raising cancel_fn is NOT treated as a cancel:
    ignored and noted once in warnings (run continues)."""
    try:
        want = bool(ctx.params.cancel_fn())
    except Exception as e:
        if not ctx.cancel_err_logged:
            ctx.cancel_err_logged = True
            ctx.warnings.append("cancel_fn 예외 — 취소로 간주하지 않고 계속: %r" % (e,))
        return
    if want:
        raise AbortError("작업자 중단 요청")


def _check_cancel_before_mutation(ctx: _Ctx):
    """Poll cancel at a drive-mutation boundary.

    Before the first attempted write, cancellation is a read-only preflight
    failure: there is no drive state to restore and the abort chain itself
    would create writes. Once a write has been attempted, retain the normal
    AbortError path so the fixed safe-abort/restore chain runs.
    """
    try:
        _check_cancel(ctx)
    except AbortError as exc:
        if ctx.dirty:
            raise
        raise PreflightError(str(exc)) from None


def _guard(ctx: _Ctx):
    """I3 in-motion guard: MF!=0, LC==1, |dPX|>tol -> abort (SPEC §5/§8)."""
    mf = _cmd(ctx, "MF")
    if isinstance(mf, (int, float)) and mf != 0:
        extra = " (0x200000=스턱: 세그먼트 단축 후 재시도 권장)" \
            if int(mf) & 0x200000 else ""
        raise AbortError("모터 폴트 MF=0x%X%s" % (int(mf), extra))
    lc = _cmd(ctx, "LC")
    if lc == 1:
        raise AbortError("전류 리미터 포화 LC=1")
    px = _cmd(ctx, "PX")
    if ctx.px_ref is not None and isinstance(px, (int, float)):
        if abs(px - ctx.px_ref) > ctx.px_tol:
            raise AbortError("모션 감지 |dPX|=%.0f > %.0f counts"
                             % (abs(px - ctx.px_ref), ctx.px_tol))


def _sleep(ctx: _Ctx, dur_s: float):
    """Sleep in <=GUARD_PERIOD_S chunks, running the I3 guard while MO=1."""
    remaining = float(dur_s)
    while remaining > 1e-12:
        chunk = min(remaining, GUARD_PERIOD_S - ctx.guard_due_s
                    if ctx.motor_on else remaining)
        chunk = max(chunk, 1e-6)
        ctx.params.sleep_fn(chunk)
        remaining -= chunk
        _check_cancel(ctx)              # operator stop: polled on EVERY chunk
        if ctx.motor_on:
            ctx.guard_due_s += chunk
            if ctx.guard_due_s >= GUARD_PERIOD_S - 1e-9:
                ctx.guard_due_s = 0.0
                _guard(ctx)


def _ramp_tc(ctx: _Ctx, target: float, total_s: float, steps: int = 10,
             px_trace: Optional[list] = None):
    """Ramp TC from ctx.tc_now to target in `steps` writes over total_s.
    px_trace (list) collects a per-step (TC, PX) waveform — pre-alignment
    evidence for the stiction-snap characterization (delta0 / tumble)."""
    start = ctx.tc_now
    for k in range(1, steps + 1):
        val = start + (target - start) * k / steps
        _write(ctx, "TC", val, allow_motion=True)
        ctx.tc_now = val
        _sleep(ctx, total_s / steps)
        if px_trace is not None:
            px = _cmd(ctx, "PX")
            px_trace.append((val, px if isinstance(px, (int, float)) else None))


# ======================================================================================
# recorder access (SPEC §3.4)
# ======================================================================================
def _list_recorder_signals(ctx: _Ctx):
    """Recorder signal list via link.recorder_signals() (ElmoLink: personality
    SignalsMetaData; SimDrive: mock list).  Returns list[str] or None — None
    becomes the honest pre-power RED at P4."""
    lister = getattr(ctx.link, "recorder_signals", None)
    if callable(lister):
        try:
            names = lister()
            return list(names) if names else None
        except Exception:
            return None
    return None


def _resolve_signals(ctx: _Ctx):
    """Map personality signal names to measurement channels.

    Live-grounded names (2026-07-13, 254-signal personality): actual current =
    exactly 'Active Current [A]' (NEVER 'Reactive Current [A]'); command =
    'Current Command [A]' preferred over 'Total Current Command [A]'; voltage =
    ALL non-bus channels ('A/B/C/D Voltage').  WHICH voltage channel carries
    the applied voltage is LIVE-UNKNOWN — all are recorded into evidence and
    the FIRST is used provisionally for |Z|/R (flagged as a warning) until the
    live SE-excitation characterization picks the right one."""
    names = _list_recorder_signals(ctx)
    if not names:
        err = getattr(ctx.link, "_last_recorder_error", None)
        if err:
            ctx.evidence["recorder_error"] = str(err)
        raise PreflightError("레코더 신호목록 확보 실패%s"
                             % (" — %s" % err if err else " (personality 미확보)"))
    ctx.evidence["recorder_signals"] = list(names)
    # legs A/B/C = PWM duty counts (fable-physics, live run #5).  D = idle -> excluded.
    legs = []
    for phase in ("A", "B", "C"):
        m = [n for n in names if re.fullmatch(r"%s\s+Voltage" % phase, n, re.I)]
        if not m:
            raise PreflightError("레그 듀티 신호 '%s Voltage' 없음 — 전압 재구성 불가,"
                                 " 신호목록 덤프 참조" % phase)
        legs.append(m[0])
    bus = ([n for n in names if n == "DC Bus Voltage"]
           or [n for n in names
               if re.search(r"bus", n, re.I) and re.search(r"voltage", n, re.I)])
    if not bus:                                     # PRIMARY scale needs Vbus (run #6)
        raise PreflightError("DC Bus Voltage 신호 없음 — 주 스케일(Vbus/FS) 불가,"
                             " 신호목록 덤프 참조")
    bus_name = bus[0]
    # idle leg (G1': its mean must sit at FS/2) — absence fails G1', not RED
    idle = [n for n in names if re.fullmatch(r"D\s+Voltage", n, re.I)]
    idle_name = idle[0] if idle else None
    cur = ([n for n in names if n == "Active Current [A]"]
           or [n for n in names if re.search(r"active\s*current|\bIQ\b", n, re.I)
               and not re.search(r"reactive", n, re.I)])
    ref = ([n for n in names if n == "Current Command [A]"]
           or [n for n in names if n == "Total Current Command [A]"]
           or [n for n in names if re.search(r"current\s*command|DV\[?1\]?", n, re.I)
               and not re.search(r"voltage", n, re.I)])
    if not cur or not ref:
        raise PreflightError("전류(Active)/전류지령 레코더 신호 없음 — 신호목록 덤프 참조")
    ctx.evidence["signal_map"] = {
        "legs": list(legs), "bus": bus_name, "idle": idle_name,
        "current_name": cur[0], "ref_name": ref[0],
        "note": "레그신호=PWM 듀티카운트(mid=FS/2, FS=G0 산출); 'D Voltage'=유휴 레그"
                " (G1' 중점검증용 기록); v_phN=중성점차감 재구성, 스케일=Vbus/FS"}
    return {"legs": legs, "bus": bus_name, "idle": idle_name,
            "i": cur[0], "ref": ref[0]}


def _record(ctx: _Ctx, duration_s: float) -> dict:
    """Capture the 3 channels via link.record() (.NET Drive Recording wrapper;
    SimDrive mock in tests).  Returns {'i','v','ref': np.ndarray, 'dt': s}.

    The legacy 2-letter RC/RG/RR/BH path and its _parse_bh are RETIRED
    (docs/recording-api.md: BH is a bitfield + hex-binary frame — grounded bug).
    Blocking for ~duration_s; I3 guard / cancel poll resume right after."""
    cap = _max_segment_s(ctx)
    if duration_s > cap:
        ctx.warnings.append("레코딩 %.2fs를 CL[4] 세그먼트 한계 %.2fs로 단축" %
                            (duration_s, cap))
        duration_s = cap
    ts = ctx.ts_s
    sig = ctx.sig
    names = list(sig["legs"]) + ([sig["bus"]] if sig["bus"] else []) \
        + ([sig["idle"]] if sig.get("idle") else []) + [sig["i"], sig["ref"]]
    per_sig_cap = max(256, 16384 // max(1, len(names)))   # CR: 16384 total samples
    tr = max(1, int(math.ceil(duration_s / (per_sig_cap * ts))))
    n = int(math.ceil(duration_s / (ts * tr)))
    rec_fn = getattr(ctx.link, "record", None)
    if not callable(rec_fn):
        raise AbortError("링크에 record() 없음 — .NET Drive Recording 래퍼 필요")
    try:
        out = rec_fn(names, n, time_resolution=tr)
    except Exception as e:
        raise AbortError("드라이브 레코딩 실패: %s" % e)
    try:
        i_arr = np.asarray(out[sig["i"]], dtype=float)
        ref_arr = np.asarray(out[sig["ref"]], dtype=float)
        legs = {nm: np.asarray(out[nm], dtype=float) for nm in sig["legs"]}
        vbus = np.asarray(out[sig["bus"]], dtype=float) if sig["bus"] else None
        idle = np.asarray(out[sig["idle"]], dtype=float) if sig.get("idle") else None
    except KeyError as e:
        raise AbortError("레코딩 채널 누락: %s" % e)
    v_counts = neutral_subtract(legs[sig["legs"][0]], legs[sig["legs"][1]],
                                legs[sig["legs"][2]])
    if len(i_arr) == 0 or len(v_counts) != len(i_arr) or len(ref_arr) != len(i_arr):
        raise AbortError("레코딩 데이터 길이 이상 (i=%d v=%d ref=%d)"
                         % (len(i_arr), len(v_counts), len(ref_arr)))
    if np.isnan(i_arr).any() or np.isnan(v_counts).any() \
            or (vbus is not None and np.isnan(vbus).any()):
        raise AbortError("레코딩 데이터 NaN — 즉시 중단")
    dt = out.get("dt")
    if not isinstance(dt, (int, float)) or dt <= 0:
        dt = ts * tr                                # provisional (U3: dt live-unknown)
        if not ctx.dt_warned:
            ctx.dt_warned = True
            ctx.warnings.append("레코딩 dt 미보고 — TimeResolution×TS=%.3gs 잠정 적용"
                                % dt)
    if vbus is not None:
        ctx.vbus_samples.append(float(np.mean(vbus)))   # primary-scale source
    return {"i": i_arr, "ref": ref_arr, "v_counts": v_counts, "legs": legs,
            "vbus": vbus, "idle": idle, "dt": float(dt)}


def _dc_selfcheck(ctx: _Ctx, rec: dict, label: str):
    """T2/§3.4 self-check on DC segments — RIPPLE-AWARE (run #10 fix).

    Compares a SINGLE instantaneous IQ poll against the recorder WINDOW MEAN.
    A hard 5% limit is wrong for that pair: with ~4% current ripple the poll
    can legitimately land on a ripple peak (live run #10: poll 2.236 A vs mean
    2.121 A = 5.1%, yet inside the recorded band [mean±2σ]) while the
    MEASUREMENT only ever uses the window mean.  PASS when the polled value
    lies inside the recorded [min, max] band, OR within max(5%*|mean|, 3*std)
    of the mean.  This is ripple-tolerant judgement, not threshold inflation:
    a true scale error (e.g. poll = 1.2x mean) stays outside both criteria."""
    arr = np.asarray(rec["i"], dtype=float)
    mean_i = float(np.mean(arr))
    iq = _cmd(ctx, "IQ")
    if not isinstance(iq, (int, float)):
        return
    lo, hi = float(np.min(arr)), float(np.max(arr))
    std_i = float(np.std(arr))
    tol = max(0.05 * max(abs(mean_i), 0.1), 3.0 * std_i)
    if not (lo <= iq <= hi) and abs(mean_i - iq) > tol:
        ctx.warnings.append(
            "%s: 폴링IQ %.3fA가 기록범위[%.3f, %.3f] 밖이고 평균 %.3fA 대비 허용"
            "(max(5%%, 3σ)=%.3fA)도 초과" % (label, iq, lo, hi, mean_i, tol))


def _max_segment_s(ctx: _Ctx) -> float:
    """C3 guard: CL[2]>=2 -> segment <= 0.8*CL[4]/1000 s (CL[4] read as ms — U2)."""
    cl2 = ctx.readings.get("CL[2]")
    cl4 = ctx.readings.get("CL[4]")
    if isinstance(cl2, (int, float)) and cl2 >= 2 and isinstance(cl4, (int, float)):
        return max(0.05, 0.8 * cl4 / 1000.0)
    return float("inf")


# ======================================================================================
# abort chain (SPEC §6 — order is FIXED)
# ======================================================================================
_RESTORE_ORDER = ("SE[1]", "SE[2]", "SE[3]", "SE[4]", "SE[5]", "SE[6]", "SE[7]",
                  "CA[41]", "CA[42]", "CA[43]", "CA[44]", "CA[70]", "UM", "SC[8]",
                  "KP[1]", "KI[1]")


def _p1_config_journal_api(ctx: _Ctx):
    names = (
        "prepare_persistence_attempt",
        "begin_persistence_ram_rollback",
        "resolve_persistence_ram_rollback",
        "mark_persistence_attempt_unknown",
    )
    try:
        methods = tuple(getattr(ctx.link, name, None) for name in names)
    except Exception as exc:
        raise PreflightError(
            "P1 configuration journal API inspection failed: %s" % exc)
    if all(method is None for method in methods):
        try:
            synthetic_mode = getattr(
                ctx.link, "p1_config_durability_mode", None)
        except Exception as exc:
            raise PreflightError(
                "P1 configuration journal mode inspection failed: %s" % exc)
        if synthetic_mode == "SYNTHETIC_NO_HARDWARE":
            return None
        raise PreflightError(
            "P1 configuration journal API is required for a hardware-capable "
            "link")
    if not all(callable(method) for method in methods):
        raise PreflightError(
            "P1 configuration journal API is incomplete")
    return methods


def _latch_p1_config_unknown(ctx: _Ctx, attempt_id, reason: str):
    """Retain a durable incident; fall back to the runtime mutation latch."""
    mark_error = None
    try:
        marker = getattr(ctx.link, "mark_persistence_attempt_unknown", None)
        if not callable(marker):
            raise RuntimeError("configuration journal marker unavailable")
        marker(attempt_id, str(reason) or "CONFIGURATION_RESTORE_UNKNOWN")
    except Exception as exc:
        mark_error = "%s: %s" % (type(exc).__name__, exc)
        try:
            latch = getattr(ctx.link, "latch_persistence_unknown", None)
            if callable(latch):
                latch()
        except Exception:
            pass
    finally:
        ctx.config_attempt_id = None
    return mark_error


def _prepare_p1_config_journal(
        ctx: _Ctx, original: dict, applied: dict,
        mutation_bounds: dict):
    api = _p1_config_journal_api(ctx)
    if api is None:
        return
    prepare, _begin_rollback, _resolve, _mark = api
    _check_cancel_before_mutation(ctx)
    try:
        attempt_id = prepare(
            phase="P1_CONFIG",
            registers=P1_CONFIG_NAMES,
            original=original,
            applied=applied,
            initial_state="RAM_APPLYING",
            mutation_bounds=mutation_bounds,
        )
    except Exception as exc:
        try:
            latched = getattr(ctx.link, "persistence_unknown_latched", None)
            if callable(latched) and latched():
                ctx.evidence["configuration_state"] = "UNKNOWN"
        except Exception:
            ctx.evidence["configuration_state"] = "UNKNOWN"
        raise PreflightError(
            "P1 configuration journal preflight failed: %s" % exc) from None
    if not isinstance(attempt_id, str) or not attempt_id:
        try:
            latch = getattr(ctx.link, "latch_persistence_unknown", None)
            if callable(latch):
                latch()
        except Exception:
            pass
        ctx.evidence["configuration_state"] = "UNKNOWN"
        raise PreflightError(
            "P1 configuration journal returned no record capability")
    ctx.config_attempt_id = attempt_id
    ctx.evidence["configuration_transaction"] = {
        "phase": "P1_CONFIG",
        "record_id": attempt_id,
        "state": "RAM_APPLYING",
    }


def _restore_snapshot(ctx: _Ctx):
    """A4/E1: restore touched values and prove the full bounded config set."""
    if ctx.config_restore_finalized:
        evidence = ctx.evidence.get("configuration_restore", {})
        return list(evidence.get("failures", ()))
    ctx.config_restore_finalized = True
    attempted, write_errors = [], []
    dirty = set(ctx.dirty)
    targets = [cmd for cmd in P1_CONFIG_NAMES if cmd in ctx.snapshot]
    rollback_transition_error = None
    if ctx.config_attempt_id is not None:
        try:
            begin_rollback = getattr(
                ctx.link, "begin_persistence_ram_rollback", None)
            if not callable(begin_rollback):
                raise RuntimeError(
                    "configuration journal rollback transition unavailable")
            begin_rollback(ctx.config_attempt_id)
        except Exception as exc:
            rollback_transition_error = "%s: %s" % (
                type(exc).__name__, exc)
    for cmd in _RESTORE_ORDER:
        if (cmd not in P1_CONFIG_NAMES or cmd not in dirty
                or cmd not in ctx.snapshot):
            continue
        if rollback_transition_error is not None:
            continue
        attempted.append(cmd)
        try:
            _cmd(ctx, "%s=%s" % (cmd, _fmt(ctx.snapshot[cmd])), retries=1)
        except Exception as e:
            # A lost assignment reply is not itself proof of failure.  The
            # independent query below adjudicates the actual RAM state.
            write_errors.append("%s(%s)" % (cmd, e))

    readback, read_errors, mismatches, restored = {}, [], [], []
    if rollback_transition_error is not None:
        read_errors.append(
            "rollback transition failed: %s" % rollback_transition_error)
    if (ctx.config_attempt_id is not None
            and tuple(targets) != tuple(P1_CONFIG_NAMES)):
        missing = [name for name in P1_CONFIG_NAMES if name not in targets]
        read_errors.append("missing snapshot values: %s" % ", ".join(missing))
    for cmd in targets:
        try:
            observed = _cmd(ctx, cmd, retries=1)
            readback[cmd] = observed
        except Exception as e:
            read_errors.append("%s(%s)" % (cmd, e))
            continue
        expected = _to_num(ctx.snapshot[cmd])
        if (isinstance(expected, (int, float))
                and not isinstance(expected, bool)
                and isinstance(observed, (int, float))
                and not isinstance(observed, bool)):
            matches = bool(
                math.isfinite(float(expected))
                and math.isfinite(float(observed))
                and observed == expected)
        else:
            matches = observed == expected
        if matches:
            restored.append(cmd)
        else:
            mismatches.append("%s(expected=%r observed=%r)" % (
                cmd, expected, observed))

    failed = read_errors + mismatches
    ram_passed = not failed and len(restored) == len(targets)
    journal = {
        "record_id": ctx.config_attempt_id,
        "closeout": "NOT_REQUIRED",
        "error": None,
        "mark_unknown_error": None,
        "verified_original_readback": None,
    }
    if ctx.config_attempt_id is not None:
        attempt_id = ctx.config_attempt_id
        if ram_passed:
            try:
                resolver = getattr(
                    ctx.link, "resolve_persistence_ram_rollback", None)
                if not callable(resolver):
                    raise RuntimeError(
                        "configuration journal rollback resolver unavailable")
                verified_original = resolver(attempt_id)
                if (not isinstance(verified_original, dict)
                        or set(verified_original) != set(P1_CONFIG_NAMES)):
                    raise RuntimeError(
                        "configuration journal resolver returned incomplete "
                        "original-profile evidence")
                ctx.config_attempt_id = None
                journal["closeout"] = "RAM_ROLLBACK_VERIFIED"
                journal["verified_original_readback"] = dict(
                    verified_original)
            except Exception as exc:
                journal["closeout"] = "UNKNOWN"
                journal["error"] = "%s: %s" % (type(exc).__name__, exc)
                failed.append("journal closeout failed: %s" % journal["error"])
                journal["mark_unknown_error"] = _latch_p1_config_unknown(
                    ctx, attempt_id, "CONFIGURATION_JOURNAL_CLOSEOUT_FAILED")
        else:
            journal["closeout"] = "UNKNOWN"
            journal["mark_unknown_error"] = _latch_p1_config_unknown(
                ctx, attempt_id, "CONFIGURATION_RESTORE_UNVERIFIED")
    passed = not failed and ram_passed and journal["closeout"] != "UNKNOWN"
    ctx.evidence["restored"] = restored
    ctx.evidence["configuration_restore"] = {
        "attempted": attempted,
        "write_errors": write_errors,
        "readback": readback,
        "read_errors": read_errors,
        "mismatches": mismatches,
        "ram_pass": ram_passed,
        "journal": journal,
        "failures": list(failed),
        "pass": passed,
    }
    ctx.evidence["configuration_state"] = (
        "RESTORED" if passed else "UNKNOWN")
    if failed:
        ctx.warnings.append(
            "복원 되읽기 실패 %s — 설정 상태 UNKNOWN, 스냅숏(%s)으로 복구 필요"
            % (", ".join(failed), ctx.snapshot_path))
    return failed


def _do_abort(ctx: _Ctx, reason: str):
    if ctx.aborted:
        return ctx.evidence.get("configuration_state") != "UNKNOWN"
    ctx.aborted = True
    steps = []

    def _try(label, fn):
        try:
            fn()
            steps.append(label)
        except Exception as e:
            ctx.warnings.append("abort %s 실패: %s" % (label, e))

    _try("A1 MO=0", lambda: _cmd(ctx, "MO=0", retries=0))
    a1_ok = "A1 MO=0" in steps
    ctx.motor_on = False
    _try("A2 TW[80]=0", lambda: _cmd(ctx, "TW[80]=0", retries=0))
    # A3 TC=0 — after a SUCCESSFUL A1 the drive is expected to answer
    # "Drive error 58: Servo must be on" (torque command void with the bridge
    # off).  That is harmless: log it as an expected step, NOT a warning.
    # Any other failure (or err58 while A1 itself failed) stays a warning.
    try:
        _cmd(ctx, "TC=0", allow_motion=True, retries=0)
        steps.append("A3 TC=0")
    except Exception as e:
        msg = str(e)
        if a1_ok and (re.search(r"\b58\b", msg)
                      or "servo must be on" in msg.lower()):
            steps.append("A3 TC=0 (err58 예상 — MO=0 탈전 확정 상태, 무해)")
        else:
            ctx.warnings.append("abort A3 TC=0 실패: %s" % e)
    restore_failed = _restore_snapshot(ctx)
    if restore_failed:
        ctx.warnings.append(
            "abort A4 restore UNKNOWN: %s" % ", ".join(restore_failed))
    else:
        steps.append("A4 restore")
    _try("A5 RR=0", lambda: _cmd(ctx, "RR=0", retries=0))
    ctx.evidence["abort"] = {"reason": reason, "steps_done": steps}
    return not restore_failed


def _red(ctx: _Ctx, reason: str) -> AutotuneResult:
    ctx.evidence.setdefault("readings", ctx.readings)
    return AutotuneResult(status=RED, reason=reason,
                          ts_us=ctx.readings.get("TS"),
                          evidence=ctx.evidence, warnings=ctx.warnings)


# ======================================================================================
# the pipeline (SPEC §7, steps P0..E2)
# ======================================================================================
_P1_READS = (["TS", "MC", "PL[1]", "CL[1]", "CL[2]", "CL[3]", "CL[4]", "UM",
              "KP[1]", "KI[1]"] +
             ["SE[%d]" % i for i in range(1, 8)] +
             ["CA[17]", "CA[18]", "CA[19]", "CA[41]", "CA[42]", "CA[43]", "CA[44]",
              "CA[45]", "CA[46]", "CA[47]", "CA[70]", "SC[8]", "SR", "MF", "BV",
              "XP[2]", "WS[53]", "WS[54]", "WS[56]", "WS[57]"])


def run_current_autotune(link, params: Optional[AutotuneParams] = None) -> AutotuneResult:
    """Phase 1 measurement pipeline (P0..E2).  Gain application (E3) and the
    verification run (E4) are separate calls: apply_gains() / verify_run().

    SAFETY: sends MO=1/TC/SE with allow_motion=True — the caller must have
    passed the operator gate (axis-free confirmation) BEFORE calling this.
    Never raises: every failure comes back as a RED result, after the SPEC §6
    abort chain when drive state was already touched.
    """
    params = params or AutotuneParams()
    ctx = _Ctx(link, params)
    try:
        return _pipeline(ctx)
    except PreflightError as e:
        reason = str(e)
        if ctx.dirty or ctx.config_attempt_id is not None:
            restored = _do_abort(
                ctx, "late PreflightError after mutation: %s" % reason)
            if not restored:
                reason += "; configuration restore UNKNOWN"
        elif ctx.evidence.get("configuration_state") == "UNKNOWN":
            reason += "; configuration state UNKNOWN"
        return _red(ctx, reason)
    except AbortError as e:
        reason = str(e)
        if not _do_abort(ctx, reason):
            reason += "; configuration restore UNKNOWN"
        return _red(ctx, reason)
    except Exception as e:                          # never die on an exception
        reason = "내부 예외: %r" % (e,)
        if not _do_abort(ctx, reason):
            reason += "; configuration restore UNKNOWN"
        return _red(ctx, reason)


def _pipeline(ctx: _Ctx) -> AutotuneResult:
    p = ctx.params

    # Honor a cancel already latched before issuing even the first read. The
    # identical gate inside _write catches a cancel that arrives during P0-P4.
    _check_cancel_before_mutation(ctx)

    # ---- P0: connection + MO gate (no auto-disable) ----------------------------------
    if not getattr(ctx.link, "is_connected", False):
        raise PreflightError("드라이브 미연결")
    mo = _cmd(ctx, "MO")
    if mo == 1:
        raise PreflightError("모터 ON(MO=1) — STOP 후 재시도 (자동 disable 금지)")
    _emit(ctx, "P0", "연결 확인, MO=0 게이트 통과")

    # ---- P1: full state read ----------------------------------------------------------
    for cmd in _P1_READS:
        ctx.readings[cmd] = _cmd(ctx, cmd)
    ctx.evidence["readings"] = dict(ctx.readings)

    # ---- P2: validation ----------------------------------------------------------------
    ts = ctx.readings["TS"]
    if not isinstance(ts, (int, float)) or not (40 <= ts <= 120) \
            or int(ts) != ts or int(ts) % 2:
        raise PreflightError("TS=%r 유효범위(40..120, 짝수) 벗어남" % (ts,))
    ctx.ts_s = ts * 1e-6
    cl1 = ctx.readings["CL[1]"]
    if not isinstance(cl1, (int, float)) or cl1 <= 0:
        raise PreflightError("CL[1]=%r 비정상" % (cl1,))
    ctx.cl1 = float(cl1)
    ca18 = ctx.readings.get("CA[18]")
    if (not isinstance(ca18, (int, float)) or isinstance(ca18, bool)
            or not math.isfinite(float(ca18)) or float(ca18) <= 0):
        raise PreflightError(
            "CA[18]=%r invalid; finite positive counts/rev is required "
            "for every PX motion guard" % (ca18,))
    mf = ctx.readings["MF"]
    if not isinstance(mf, (int, float)) or mf != 0:
        raise PreflightError("모터 폴트 존재 MF=%r — 폴트 해소 후 재시도" % (mf,))
    if not (0 < p.i_frac_low < p.i_frac_high <= 0.6):
        raise PreflightError("i_frac (%.2f,%.2f) 범위 오류 (0<low<high<=0.6)"
                             % (p.i_frac_low, p.i_frac_high))
    f_max = 0.125 / ctx.ts_s
    l_np_ph = (p.nameplate_l_pp_h / 2.0) if p.nameplate_l_pp_h else None
    r_np_ph = (p.nameplate_r_pp / 2.0) if p.nameplate_r_pp else None
    if p.freqs_hz is None:                          # auto-derive from measured TS
        try:
            ctx.freqs = derive_freqs(ctx.ts_s, r_np_ph, l_np_ph)
        except ValueError as e:
            raise PreflightError("여진 주파수 파생 실패: %s" % e)
        ctx.evidence["freqs"] = {"mode": "derived", "f_max_hz": f_max,
                                 "freqs_hz": list(ctx.freqs)}
    else:                                           # explicit: strict validation as before
        for f in p.freqs_hz:
            if not (0 < f <= f_max):
                raise PreflightError("주파수 %.0fHz > 한계 %.0fHz(0.125/TS)"
                                     % (f, f_max))
        ctx.freqs = tuple(float(f) for f in p.freqs_hz)
        ctx.evidence["freqs"] = {"mode": "explicit", "f_max_hz": f_max,
                                 "freqs_hz": list(ctx.freqs)}
    i1 = p.i_frac_low * ctx.cl1
    i2 = p.i_frac_high * ctx.cl1
    if i2 > 0.85 * ctx.cl1:                         # I2 invariant
        raise PreflightError("전류지령 상한 I2 위반")

    # ---- G0: platform grounding (pre-power, run #8) ------------------------------------
    # FS = PWM_CLOCK*TS/XP[2] (CR p.290/325: TS*f_pwm = XP[2]/2, 150 MHz counter).
    # NEVER hardcode 7500 — XP[2]!=2 recomputes FS.  WS[57] (=WS[54]-WS[56], the
    # PWM command RANGE) should sit slightly BELOW FS: it is a command LIMIT in
    # the same clock counts, not the scale itself.
    xp2 = ctx.readings.get("XP[2]")
    xp2_valid = isinstance(xp2, (int, float)) and xp2 > 0
    xp2_eff = float(xp2) if xp2_valid else 2.0
    if not xp2_valid:
        ctx.warnings.append("XP[2] 판독 불가(%r) — 기본값 2로 FS 잠정 산출" % (xp2,))
    fs = PWM_CLOCK_HZ * ctx.ts_s / xp2_eff
    ws57 = ctx.readings.get("WS[57]")
    ws57_ok = (not isinstance(ws57, (int, float))
               or 0.8 * fs <= ws57 <= 1.001 * fs)
    g0_pass = xp2_valid and (G0_FS_RANGE[0] <= fs <= G0_FS_RANGE[1]) and ws57_ok
    ctx.duty_fs = fs
    ctx.g0 = {"xp2": xp2, "ws53": ctx.readings.get("WS[53]"),
              "ws54": ctx.readings.get("WS[54]"),
              "ws56": ctx.readings.get("WS[56]"), "ws57": ws57,
              "fs_counts": fs, "clock_hz": PWM_CLOCK_HZ,
              "ws57_note": "WS[57]=PWM 지령범위(리밋) — FS보다 약간 작을 수 있음, 스케일 아님",
              "pass": bool(g0_pass)}
    _emit(ctx, "VALIDATE", "검증 통과: TS=%dµs, CL[1]=%.2fA → I1=%.2f/I2=%.2fA,"
          " 여진 f=%s Hz (f_max=%.0f)"
          % (int(ts), ctx.cl1, i1, i2,
             "/".join("%.0f" % f for f in ctx.freqs), f_max))

    # ---- P4 (before any write): recorder signal resolution ----------------------------
    ctx.sig = _resolve_signals(ctx)

    # ---- P4b (before any write): feedback-socket admission ---------------------------
    # This is an admission decision, not a recoverable setup failure.  Resolve it
    # before bootstrap gains, UM, or SC[8] can touch drive RAM.
    used_sockets = {ctx.readings.get(k) for k in ("CA[45]", "CA[46]", "CA[47]")}
    ctx.socket = None
    for s in (4, 3, 2):
        sid = ctx.readings.get("CA[4%d]" % s)
        if s not in used_sockets and sid != 8:
            ctx.socket = s
            break
    if ctx.socket is None:
        raise PreflightError("SE용 빈 피드백 소켓 없음 (CA[42..44] 만석/ID8 선점)")

    # ---- P3: snapshot to disk (I1 invariant: BEFORE first drive write) ----------------
    ctx.snapshot = dict(ctx.readings)
    os.makedirs(p.snapshot_dir, exist_ok=True)
    ctx.snapshot_path = os.path.join(
        p.snapshot_dir, "autotune_snapshot_%d.json" % int(time.time() * 1000))
    with open(ctx.snapshot_path, "w", encoding="utf-8") as fjson:
        json.dump({"t": time.time(), "readings": ctx.snapshot}, fjson,
                  ensure_ascii=False, indent=1)
    ctx.evidence["snapshot_path"] = ctx.snapshot_path
    _emit(ctx, "SNAPSHOT", "드라이브 상태 스냅숏 저장: %s" % ctx.snapshot_path)

    # Freeze and durably prepare the complete temporary configuration before
    # the first assignment.  The later B3 fallback may choose bootstrap gains
    # after this target was frozen; that intermediate state intentionally
    # matches neither audit profile and therefore remains fail-closed.
    kp0 = ctx.readings["KP[1]"]
    planned_kp, planned_ki = kp0, ctx.readings["KI[1]"]
    if not isinstance(kp0, (int, float)) or kp0 <= 0:
        if not (l_np_ph and r_np_ph):
            raise PreflightError(
                "KP[1]<=0 and nameplate(명판) R/L are unavailable for "
                "bootstrap(부트스트랩)")
        planned_kp = (0.05 / ctx.ts_s) * p.nameplate_l_pp_h
        planned_ki = r_np_ph / (2 * math.pi * l_np_ph)

    original_config = {}
    for name in P1_CONFIG_NAMES:
        raw_value = ctx.raw_readings.get(name, ctx.snapshot.get(name))
        try:
            value = _exact_config_snapshot_number(raw_value, name)
        except ValueError as exc:
            raise PreflightError(
                "P1 configuration snapshot is not exact: %s" % exc) from None
        original_config[name] = value
    applied_config = dict(original_config)
    applied_config.update({
        "KP[1]": float(_to_num(_fmt(planned_kp))),
        "KI[1]": float(_to_num(_fmt(planned_ki))),
        "UM": 3.0,
        "SC[8]": 0.0,
        "CA[4%d]" % ctx.socket: 8.0,
        "CA[70]": float(ctx.socket),
        "SE[1]": 1.0,
        "SE[2]": 0.0,
        "SE[3]": float(_to_num(_fmt(ctx.freqs[0]))),
        "SE[4]": 0.0,
        "SE[5]": 0.0,
        "SE[6]": 0.0,
        "SE[7]": 50.0,
    })
    kp_candidates = [
        value for value in (
            original_config["KP[1]"], applied_config["KP[1]"])
        if value > 0.0]
    ki_candidates = [
        value for value in (
            original_config["KI[1]"], applied_config["KI[1]"])
        if value > 0.0]
    if (isinstance(l_np_ph, (int, float)) and l_np_ph > 0.0
            and isinstance(r_np_ph, (int, float)) and r_np_ph > 0.0):
        kp_candidates.append(float(_to_num(_fmt(
            (0.05 / ctx.ts_s) * p.nameplate_l_pp_h))))
        ki_candidates.append(float(_to_num(_fmt(
            r_np_ph / (2 * math.pi * l_np_ph)))))
    if not kp_candidates or not ki_candidates:
        raise PreflightError(
            "P1 configuration mutation bounds require positive KP[1]/KI[1]")
    se3_max = max(
        (2.0 * f if 2.0 * f <= f_max else f) for f in ctx.freqs)
    mutation_bounds = {
        "KP[1]": (min(kp_candidates), max(kp_candidates)),
        "KI[1]": (min(ki_candidates), max(ki_candidates)),
        "SE[2]": (0.0, 0.8 * i1),
        "SE[3]": (min(ctx.freqs), se3_max),
        "TC": (0.0, max(i2, 0.10 * ctx.cl1)),
    }
    _prepare_p1_config_journal(
        ctx, original_config, applied_config, mutation_bounds)

    # ---- P5: gain bootstrap if current loop is unconfigured ---------------------------
    kp0 = ctx.readings["KP[1]"]
    if not isinstance(kp0, (int, float)) or kp0 <= 0:
        if not (l_np_ph and r_np_ph):
            raise PreflightError("KP[1]<=0 이고 명판 R/L 없음 — 부트스트랩 불가")
        # bootstrap intent = wc_bootstrap 0.05/TS; on the CONFIRMED pp gain
        # basis that is KP = (0.05/TS)*L_pp (ph-based KP would halve the
        # bandwidth and starve the sine excitation below the 0.3 A floor)
        kp_bs = (0.05 / ctx.ts_s) * p.nameplate_l_pp_h
        ki_bs = r_np_ph / (2 * math.pi * l_np_ph)   # pole-zero cancel (basis-free)
        _write(ctx, "KP[1]", kp_bs)
        _write(ctx, "KI[1]", ki_bs)
        ctx.bootstrapped = True
        ctx.evidence["bootstrap"] = {"kp": kp_bs, "ki_hz": ki_bs,
                                     "orig_kp": kp0, "orig_ki": ctx.readings["KI[1]"]}

    # ---- A1: UM=3 (stepper), clear auto-current ---------------------------------------
    _write(ctx, "UM", 3)
    if ctx.readings["SC[8]"] not in (0, None):
        _write(ctx, "SC[8]", 0)

    # ---- A2: claim the preflight-admitted socket for Virtual-2-Sine (ID 8) ------------
    _write(ctx, "CA[4%d]" % ctx.socket, 8)
    _write(ctx, "CA[70]", ctx.socket)

    # ---- A3: SE generator armed but silent --------------------------------------------
    for idx, val in ((1, 1), (2, 0), (3, ctx.freqs[0]), (4, 0), (5, 0), (6, 0), (7, 50)):
        _write(ctx, "SE[%d]" % idx, val)

    # ---- B1/B2: enable (operator gate is the CALLER's), wait servo-on -----------------
    _check_cancel_before_mutation(ctx)
    _cmd(ctx, "MO=1", allow_motion=True)
    ctx.motor_on = True
    px0 = _cmd(ctx, "PX")
    ca18 = float(ctx.readings["CA[18]"])
    # motion thresholds are SENSOR- AND MOTOR-PARAMETERIZED: the old 11.25 deg
    # (=180/16 pole pairs) hardcoded THIS motor's pole count — a p=21 motor got
    # a wrong (too-wide) allowance.  half pole pitch [counts] = CA[18]/(2*p).
    ca19 = ctx.readings.get("CA[19]")
    pole_pairs = (float(ca19)
                  if isinstance(ca19, (int, float)) and ca19 > 0 else 0.0)
    if not pole_pairs:
        pole_pairs = POLE_PAIRS_FALLBACK
        ctx.warnings.append("CA[19] 판독 불가(%r) — 극쌍 %d 가정으로 정렬허용치 산출"
                            % (ca19, int(POLE_PAIRS_FALLBACK)))
    half_pitch = ca18 / (2.0 * pole_pairs)
    align_tol = half_pitch * 1.2
    prealign_tol = 2.0 * PREALIGN_PITCH_MULT * half_pitch
    theta_abort = max(4.0, ca18 * 2.0 / 360.0)
    if isinstance(px0, (int, float)):
        ctx.px_ref, ctx.px_tol = float(px0), align_tol
    waited = 0.0
    while _cmd(ctx, "SO") != 1:
        if waited >= 2.0:
            raise AbortError("SO!=1 (2s) — 서보온 실패")
        _sleep(ctx, ctx.params.poll_s)
        waited += ctx.params.poll_s
    _emit(ctx, "ENABLE", "MO=1 통전, 서보온(SO=1) 확인 — UM=3 스테퍼 모드")

    # ---- B3: closed-loop stability probe ----------------------------------------------
    probe_ref = 0.10 * ctx.cl1
    for attempt in (0, 1):
        _write(ctx, "TC", probe_ref, allow_motion=True)
        ctx.tc_now = probe_ref
        _sleep(ctx, 0.05)
        rec = _record(ctx, T_PROBE_S)
        tail = rec["i"][len(rec["i"]) // 2:]
        mean_t = float(np.mean(tail))
        k = np.arange(len(tail))
        resid = tail - np.polyval(np.polyfit(k, tail, 1), k)
        std_t = float(np.std(resid))
        ok = abs(mean_t - probe_ref) <= 0.10 * probe_ref and std_t <= 0.05 * probe_ref
        ctx.evidence["probe"] = {"ref": probe_ref, "mean": mean_t, "std": std_t,
                                 "ok": ok, "attempt": attempt}
        if ok:
            ctx.noise_std = max(std_t, 1e-4)
            break
        if attempt == 0 and not ctx.bootstrapped and l_np_ph and r_np_ph:
            kp_bs = (0.05 / ctx.ts_s) * p.nameplate_l_pp_h   # pp basis (see P5)
            ki_bs = r_np_ph / (2 * math.pi * l_np_ph)
            _write(ctx, "KP[1]", kp_bs)
            _write(ctx, "KI[1]", ki_bs)
            ctx.bootstrapped = True
            ctx.evidence["bootstrap"] = {"kp": kp_bs, "ki_hz": ki_bs,
                                         "orig_kp": ctx.readings["KP[1]"],
                                         "orig_ki": ctx.readings["KI[1]"]}
            ctx.warnings.append("프로브 실패 — 명판 부트스트랩 게인으로 재시도")
            continue
        raise AbortError("안정성 프로브 실패: mean=%.3fA(ref %.3f) std=%.3fA"
                         % (mean_t, probe_ref, std_t))
    _dc_selfcheck(ctx, rec, "B3")

    # ---- B4: HIGH-CURRENT pre-alignment + ratchet, THEN latch (2026-07-13 fix) --------
    # Root cause (fable-physics, live run: |dPX|=2191 cnt = 253 deg elec RED):
    # aligning at i1 only and latching px_ref lets the rotor break stiction
    # (gearbox friction) and SNAP to the commutation point when the current
    # first rises to i2 INSIDE the measurement window.  "Standstill" is not
    # "aligned".  Fix (b): burn the snap BEFORE the latch by ramping to the
    # measurement maximum i2 — quasi-static guarantee: a standstill that
    # survived i2 cannot break away when i2 is re-applied later.  Fix (c):
    # ratchet i1<->i2 up to PREALIGN_CYCLES_MAX quasi-static round trips until
    # the cycle-end |dPX| <= theta_abort (honest RED on non-convergence).
    # During the pre-align ramps ONLY, the PX guard relaxes to prealign_tol
    # (a legitimate align snap is <= ~1.5 pole pitch); MF!=0 / LC==1 guards
    # stay at full strength; the measurement-window gate theta_abort is NEVER
    # relaxed.  The per-step (TC, PX) trace is kept as evidence (delta0 /
    # tumble measurement on the next live run).
    if ctx.px_ref is not None:
        ctx.px_tol = prealign_tol
    prealign_ev = {"i1_a": i1, "i2_a": i2,
                   "prealign_tol_counts": prealign_tol,
                   "align_tol_counts": align_tol,
                   "theta_abort_counts": theta_abort,
                   "pole_pairs": pole_pairs, "counts_per_rev": ca18,
                   "half_pitch_counts": half_pitch,
                   "cycles": [],
                   "note": "사전정렬=측정최대 i2까지 램프로 stiction 스냅을 래치 전에"
                           " 소진(fix b) + i1↔i2 래칫 수렴(fix c); 완화가드는"
                           " 사전정렬 램프 구간 한정, 측정창 게이트 θ_abort 불변"}
    ctx.evidence["prealign"] = prealign_ev
    converged = False
    for cyc in range(PREALIGN_CYCLES_MAX):
        px_s = _cmd(ctx, "PX")
        if isinstance(px_s, (int, float)) and ctx.px_ref is not None:
            ctx.px_ref = float(px_s)        # judge each cycle on its OWN motion
        trace = []
        _ramp_tc(ctx, i2, ALIGN_STEPS * ALIGN_STEP_S, ALIGN_STEPS,
                 px_trace=trace)            # stiction breakaway happens HERE
        _sleep(ctx, T_PREALIGN_SETTLE_S)
        _ramp_tc(ctx, i1, T_RAMP_BACK_S, 5, px_trace=trace)
        _sleep(ctx, T_PREALIGN_SETTLE_S)
        px_e = _cmd(ctx, "PX")
        both_num = (isinstance(px_s, (int, float))
                    and isinstance(px_e, (int, float)))
        dpx = abs(px_e - px_s) if both_num else None
        px_vals = [p for _, p in trace if isinstance(p, (int, float))]
        dev_max = (max(abs(p - px_s) for p in px_vals)
                   if px_vals and isinstance(px_s, (int, float)) else None)
        prealign_ev["cycles"].append({
            "cycle": cyc, "px_start": px_s, "px_end": px_e, "dpx": dpx,
            "max_dev_counts": dev_max, "trace_tc_px": trace})
        if dpx is not None and dpx <= theta_abort:
            # cycle-end motion within the strict gate = converged.  dpx=None
            # (unparseable PX) is NOT convergence: no-motion EVIDENCE is
            # required, absence of evidence is not evidence of standstill
            # (fable-critic LOW #2) — keep cycling, honest RED at the cap.
            converged = True
            if dev_max is not None and dev_max > theta_abort:
                # reversible intra-cycle excursion that returned by cycle end
                # (gearbox compliance / elasticity candidate).  A standstill
                # rotor's elastic deflection does not contaminate the R/L
                # measurement, so this is made VISIBLE (YELLOW), never a hard
                # fail (fable-critic LOW #3: no false RED on compliant gears).
                ctx.warnings.append(
                    "사전정렬 수렴 사이클 내 가역 변위 — max|ΔPX|=%.0f > θ_abort"
                    "=%.0f counts (종단 |dPX|=%.0f로 복귀): 감속기 컴플라이언스/"
                    "탄성 후보, 측정은 정지 유지 시 유효(YELLOW)"
                    % (dev_max, theta_abort, dpx))
            break
    if not converged:
        last_dpx = prealign_ev["cycles"][-1]["dpx"]
        detail = ("사이클 종단 |dPX|=%.0f > %.0f counts"
                  % (last_dpx, theta_abort) if last_dpx is not None
                  else "PX 판독불가 — 무모션 증거 확보 실패")
        raise AbortError("정렬 미수렴 — 래칫 %d회 후 %s"
                         % (PREALIGN_CYCLES_MAX, detail))
    # tighten the guard AT convergence (not after the settle): convergence just
    # proved the rotor survived i2 within theta_abort — any motion from here on
    # is NOT a legitimate align snap and must trip the strict gate immediately
    last_end = prealign_ev["cycles"][-1]["px_end"]
    if isinstance(last_end, (int, float)) and ctx.px_ref is not None:
        ctx.px_ref, ctx.px_tol = float(last_end), theta_abort
    # standstill verification at i1 under the strict gate, then re-latch
    _sleep(ctx, 1.0)
    pxa = _cmd(ctx, "PX")
    _sleep(ctx, 0.2)
    pxb = _cmd(ctx, "PX")
    if isinstance(pxa, (int, float)) and isinstance(pxb, (int, float)):
        if abs(pxb - pxa) > theta_abort:
            raise AbortError("정렬 후 모션 잔존 |dPX|=%.0f > %.0f"
                             % (abs(pxb - pxa), theta_abort))
        ctx.px_ref, ctx.px_tol = float(pxb), theta_abort   # tighten guard post-align
    _emit(ctx, "ALIGN", "사전정렬 완료: 래칫 %d사이클(i2=%.2fA까지 소진), 종단"
          " |dPX|≤%.0f counts — 측정창 게이트 조임"
          % (len(prealign_ev["cycles"]), i2, theta_abort))

    # ---- C1/C2: two-point DC resistance (counts domain; volts after D-scale) ----------
    rec1 = _record(ctx, T_DC_RECORD_S)
    _dc_selfcheck(ctx, rec1, "C1@I1")
    i1_bar, v1c_bar = float(np.mean(rec1["i"])), float(np.mean(rec1["v_counts"]))
    _ramp_tc(ctx, i2, T_RAMP_LEVEL_S, 6)
    _sleep(ctx, 0.05)
    rec2 = _record(ctx, T_DC_RECORD_S)
    _dc_selfcheck(ctx, rec2, "C1@I2")
    i2_bar, v2c_bar = float(np.mean(rec2["i"])), float(np.mean(rec2["v_counts"]))
    if (i1_bar < 0) or (i2_bar < 0):
        raise AbortError("DC 레벨 부호 위반(deadtime 소거조건: 동일 + 부호)")
    di = i2_bar - i1_bar
    if abs(di) < 0.5:
        raise AbortError("전류 레벨차 %.3fA < 0.5A — R 분해능 부족" % di)
    r_counts = (v2c_bar - v1c_bar) / di             # phN duty-counts per A
    # provisional volts via the Vbus/FS hypothesis — sanity gate only; the FINAL
    # R uses the in-situ scale determined during the sine phase (D)
    vbus_means = [float(np.mean(rc["vbus"])) for rc in (rec1, rec2)
                  if rc["vbus"] is not None]
    vbus_dc = float(np.mean(vbus_means)) if vbus_means else None
    s_prov = (vbus_dc / ctx.duty_fs) if vbus_dc else None

    # ---- G1': idle-leg midpoint + bus-voltage sanity (per run, run #8) ----------------
    idle_mean = float(np.mean(rec1["idle"])) if rec1.get("idle") is not None else None
    mid_expected = ctx.duty_fs / 2.0
    idle_ok = (idle_mean is not None
               and abs(idle_mean - mid_expected) <= G1P_MID_TOL_COUNTS)
    vbus_ok = (vbus_dc is not None
               and G1P_VBUS_RANGE[0] <= vbus_dc <= G1P_VBUS_RANGE[1])
    ctx.g1p = {"idle_leg_mean": idle_mean, "expected_mid": mid_expected,
               "mid_tol_counts": G1P_MID_TOL_COUNTS,
               "vbus_v": vbus_dc, "vbus_range": list(G1P_VBUS_RANGE),
               "pass": bool(idle_ok and vbus_ok)}
    r_pp_prov = (2.0 * s_prov * r_counts) if s_prov else None
    if r_pp_prov is not None and not (1e-3 <= r_pp_prov <= 10.0):
        raise AbortError("R_pp(잠정 Vbus스케일)=%.4g Ω 타당범위[1mΩ,10Ω] 벗어남"
                         % r_pp_prov)
    ctx.evidence["dc"] = {
        "i1_bar": i1_bar, "i2_bar": i2_bar,
        "v1_counts": v1c_bar, "v2_counts": v2c_bar,
        "r_counts_per_a": r_counts, "vbus_v": vbus_dc,
        "r_pp_provisional_ohm": r_pp_prov,
        "leg_means": {"I1": {nm: float(np.mean(a)) for nm, a in rec1["legs"].items()},
                      "I2": {nm: float(np.mean(a)) for nm, a in rec2["legs"].items()}},
        "note": "v_counts=중성점차감 듀티카운트; naive V/I는 데드타임 오염으로 금지(SPEC §3.2)"}
    _emit(ctx, "MEASURE_R", "저항 실측(잠정 Vbus스케일): R_pp=%s mΩ (2점차분, ΔI=%.2fA;"
                            " 최종값은 in-situ 스케일 후)"
          % (("%.2f" % (r_pp_prov * 1e3)) if r_pp_prov else "N/A", di))

    # ---- C3: back to I1 ----------------------------------------------------------------
    _ramp_tc(ctx, i1, T_RAMP_BACK_S, 5)
    _sleep(ctx, 0.05)

    # ---- D1..D3: sine excitation -> complex Z + in-situ scale --------------------------
    kp_now = ctx.readings["KP[1]"] if not ctx.bootstrapped else \
        ctx.evidence["bootstrap"]["kp"]
    ki_now = ctx.readings["KI[1]"] if not ctx.bootstrapped else \
        ctx.evidence["bootstrap"]["ki_hz"]
    r_pp_seed = r_pp_prov if r_pp_prov else (p.nameplate_r_pp or 0.1)
    sine_ev = []
    for f_req in ctx.freqs:
        f_try = float(f_req)
        a_cmd = _initial_sine_cmd(p, kp_now, ki_now, r_pp_seed,
                                  p.nameplate_l_pp_h, f_try, i1)
        inj_fail = 0
        doubled = False
        entry = None
        while True:
            out = _measure_sine(ctx, f_try, a_cmd)
            if out is None:                          # WS never reached 2
                inj_fail += 1
                if inj_fail > 2:
                    raise AbortError("SE 미주입 — SE→CA[70] 가산 미확인(U1),"
                                     " 실기 검증 필요")
                continue
            i_f = out["i_f"]
            if i_f < max(0.3, 5.0 * ctx.noise_std):
                inj_fail += 1
                if inj_fail > 2:
                    raise AbortError("SE 주입전류 미검출 |I_f|=%.3fA —"
                                     " SE→CA[70] 가산 미확인(U1)" % i_f)
                a_cmd = min(max(a_cmd * 1.6, 0.3), 0.8 * i1)
                ctx.warnings.append("f=%.0fHz |I_f| 부족 — 진폭 증액 재시도" % f_try)
                continue
            if out["i_min"] < 0.1 * i1:
                a_cmd *= 0.6
                ctx.warnings.append("f=%.0fHz 전류하한 근접 — 진폭 0.6x 재시도" % f_try)
                inj_fail += 1
                if inj_fail > 2:
                    raise AbortError("정현 진폭 조정 실패 (전류하한)")
                continue
            z_cnt = out["z_counts"]
            if abs(z_cnt) <= 1.05 * abs(r_counts) and not doubled:
                if f_try * 2 <= f_max:               # counts-domain: scale cancels
                    doubled = True
                    ctx.warnings.append("f=%.0fHz |Z|~R — f x2 재시도" % f_try)
                    f_try *= 2
                    continue
            # in-situ MAGNITUDE model — gate G1 only (run #6: the frequency-
            # combined in-situ SCALE is retired; same-index recording -> no
            # delay factor; magnitude is rotation-free by construction)
            z_model = (pi_discrete(f_try, ctx.ts_s, kp_now, ki_now)
                       * (out["icmd_cplx"] - out["i_cplx"])
                       / (2.0 * out["i_cplx"]))           # phN volts per A (model)
            if z_cnt.imag <= 0:
                raise AbortError("Im(Z_counts)<=0 (f=%.0fHz: %.3g) — 유도성 분리 실패"
                                 % (f_try, z_cnt.imag))
            entry = {"f_hz": f_try, "a_cmd": a_cmd, "i_f": i_f,
                     "z_counts_re": z_cnt.real, "z_counts_im": z_cnt.imag,
                     "z_model_re": z_model.real, "z_model_im": z_model.imag,
                     "s_insitu_mag_v_per_count": abs(z_model) / abs(z_cnt),
                     # |I_cmd - I|: G1 conditioning metric — the in-situ model
                     # divides by this error phasor, so it is only trustworthy
                     # where the loop tracking error is LARGE (run #7 finding)
                     "err_phasor_a": abs(out["icmd_cplx"] - out["i_cplx"]),
                     "dt": out["dt"]}
            break
        sine_ev.append(entry)

    # ---- scale (PRIMARY: Vbus_rec/7500 — run #6 확정) + skew-corrected R/L --------------
    if not ctx.vbus_samples:
        raise AbortError("Vbus 미기록 — 주 스케일(Vbus/FS) 산출 불가")
    vbus_v = float(np.mean(ctx.vbus_samples))
    s_used = vbus_v / ctx.duty_fs                   # FS from G0 (never hardcoded)
    if not (s_used > 0 and math.isfinite(s_used)):
        raise AbortError("Vbus 스케일 비정상 (Vbus=%r V)" % vbus_v)
    tau_s = SKEW_TAU_TS * ctx.ts_s
    ctx.evidence["scale"] = {"s_v_per_count": s_used, "vbus_v": vbus_v,
                             "fs_counts": ctx.duty_fs, "tau_skew_s": tau_s,
                             "note": "주 스케일=Vbus_rec/FS — FS=150MHz·TS/XP[2]"
                                     " (CR 문서확정, run #8); in-situ=G5 루프게인 전용"}
    r_pp = 2.0 * s_used * r_counts                  # TERMINAL resistance (기생 포함)
    if not (1e-3 <= r_pp <= 10.0):
        raise AbortError("R_pp=%.4g Ω 타당범위[1mΩ,10Ω] 벗어남" % r_pp)
    ctx.evidence["dc"]["r_pp_ohm"] = r_pp
    ctx.evidence["dc"]["r_basis"] = (
        "터미널 저항(모터+케이블/FET 기생 포함) — 보정하지 않음(게인식에 R 미사용)"
        + (", 명판 %.1f mΩ 대비 %+.1f%%"
           % (p.nameplate_r_pp * 1e3, 100 * (r_pp / p.nameplate_r_pp - 1))
           if p.nameplate_r_pp else ""))
    ctx.evidence["dc"]["r_naive_pp_i1_ohm"] = \
        2.0 * s_used * v1c_bar / i1_bar if i1_bar else float("nan")
    ctx.evidence["dc"]["r_naive_pp_i2_ohm"] = \
        2.0 * s_used * v2c_bar / i2_bar if i2_bar else float("nan")
    # nameplate-band ADVISORY (run #8): terminal R expected in nameplate+[5,40]mΩ
    # — informational ONLY, never blocks GREEN (not appended to warnings)
    if p.nameplate_r_pp:
        excess = r_pp - p.nameplate_r_pp
        ctx.evidence["dc"]["r_band_advisory"] = {
            "nameplate_pp_ohm": p.nameplate_r_pp, "excess_ohm": excess,
            "band_ohm": list(R_ADVISORY_BAND),
            "in_band": R_ADVISORY_BAND[0] <= excess <= R_ADVISORY_BAND[1],
            "note": "YELLOW-advisory 전용 — GREEN 비차단(기생 배분은 실기 확인 대상)"}
    l_meas = []
    for e in sine_ev:
        w = 2 * math.pi * e["f_hz"]
        z_raw = complex(e["z_counts_re"], e["z_counts_im"])
        z_f = 2.0 * s_used * z_raw * cmath.exp(-1j * w * tau_s)   # 스큐 회전보정
        e["l_pp_h"] = z_f.imag / w
        e["l_pp_uncorrected_h"] = (2.0 * s_used * z_raw).imag / w  # 진단용(편향 가시화)
        e["r_ac_pp_ohm"] = z_f.real                 # G2 게이트용
        if e["l_pp_h"] <= 0:
            raise AbortError("스큐보정 후 Im(Z)<=0 (f=%.0fHz)" % e["f_hz"])
        l_meas.append(e["l_pp_h"])
    ctx.evidence["sine"] = sine_ev
    l_pp = float(np.median(l_meas))
    if l_pp <= 0:
        raise AbortError("L 측정 실패 (Im(Z)<=0 전 주파수)")
    spread = (max(l_meas) - min(l_meas)) / l_pp if l_pp else float("inf")
    _emit(ctx, "MEASURE_L", "실측 완료: L_pp=%.2f µH (스큐보정 Im(Z) median, 산포 %.1f%%),"
                            " R_pp=%.2f mΩ (터미널, Vbus스케일)"
          % (l_pp * 1e6, 100 * spread, r_pp * 1e3))

    # ---- E1: de-energize + restore ------------------------------------------------------
    _ramp_tc(ctx, 0.0, T_RAMP_DOWN_S, 10)
    _cmd(ctx, "MO=0")
    ctx.motor_on = False
    restore_failed = _restore_snapshot(ctx)
    if restore_failed:
        raise AbortError(
            "E1 configuration restore UNKNOWN: %s" %
            ", ".join(restore_failed))
    try:
        ctx.link.command("RR=0", timeout_ms=1000)   # leave recorder idle
    except Exception:
        pass

    # ---- E2: gain design + stability gate (pp basis — fable-physics 확정) --------------
    ok, kp, ki, wc, pm, wx, iters = design_gains(l_pp, r_pp, ctx.ts_s, p)
    ctx.evidence["design"] = {"iters": iters, "ki_rule": p.ki_rule,
                              "wc_ts_cal": WC_TS_CAL, "alpha": ALPHA_EAS,
                              "ki_pp_factor": KI_PP_FACTOR,
                              "gain_basis": "ph-ph (KP=ω_c·L_pp −0.018%,"
                                            " KI=2·α·ω_c/2π=EAS ~0% — 실기 6회차 확정)",
                              "calibration_note":
                                  "0.2010/1.2705/2×는 이 드라이브 EAS 단일점 캘리브레이션 —"
                                  " 타 모터/TS 일반화 미검증(SPEC §4)"}

    # ---- GREEN gates G0/G1'/G2/G3/G4/G5 (run #8: G1 스케일게이트 폐지) ----------------
    # run #8 규명: in-situ 비는 스케일이 아니라 개루프 루프게인 |C(jω)·G(jω)|을
    # 측정한다 (4점 rms 0.3%, ρ=1 교차 = 372 Hz = 게인 크로스오버).  스케일 검증은
    # 원리적으로 불가 -> G1 폐지.  s의 정당성은 G0(FS=150MHz·TS/XP[2] 문서확정)
    # + G1'(유휴레그 중점·Vbus 범위)이 담당하고, in-situ는 G5(루프게인 일치)로
    # 용도변경 — 채널조합·회전보정·게인읽기·주입노드를 검증한다.
    # run #9 code-bug fixes (fable-physics; NOT a physics change):
    #  (1) rho_meas had a spurious outer x2 (the pp conversion already sits in
    #      the s_insitu denominator 2*I) -> rho_meas = s_insitu/s;
    #  (2) rho_pred mixed the DISCRETE C into the prediction, which back-solves
    #      to a wrong-looking L (~34.5uH) — the CONTINUOUS C(jw)=KP(jw+2piKI)/jw
    #      with the SAME reported R-hat/L-hat is the contracted basis.
    #  Residual ~-3.5% uniform offset (continuous-C / min-max-4/3 approximation
    #  candidates) is RECORDED in evidence only — never compensated.
    g5_rows = []
    for e in sine_ev:
        w = 2 * math.pi * e["f_hz"]
        c_mag = abs(pi_continuous(e["f_hz"], kp_now, ki_now))
        rho_meas = e["s_insitu_mag_v_per_count"] / s_used
        rho_pred = c_mag / abs(complex(r_pp, w * l_pp))   # 보고되는 R̂·L̂ 그대로
        g5_rows.append({"f_hz": e["f_hz"], "rho_meas": rho_meas,
                        "rho_pred": rho_pred,
                        "dev": rho_meas / rho_pred - 1.0})
    g5_pass = all(abs(r["dev"]) <= G5_TOL for r in g5_rows)
    g5_mean_dev = float(np.mean([r["dev"] for r in g5_rows]))
    fx = None                                       # measured gain crossover (rho=1)
    rows = sorted(g5_rows, key=lambda r: r["f_hz"])
    for a, b in zip(rows, rows[1:]):
        if a["rho_meas"] > 0 and b["rho_meas"] > 0 \
                and (a["rho_meas"] - 1.0) * (b["rho_meas"] - 1.0) <= 0:
            la, lb = math.log(a["rho_meas"]), math.log(b["rho_meas"])
            t = la / (la - lb) if la != lb else 0.0
            fx = math.exp(math.log(a["f_hz"])
                          + t * (math.log(b["f_hz"]) - math.log(a["f_hz"])))
            break
    fx_pred = loopgain_crossover_hz(kp_now, ki_now, r_pp, l_pp)  # 수치해 (점근식 폐기)
    g2_ratios = [e["r_ac_pp_ohm"] / r_pp for e in sine_ev]
    gates = {
        "G0_platform": dict(ctx.g0),
        "G1p_idle_vbus": dict(ctx.g1p),
        "G5_loopgain": {"rows": g5_rows, "tol": G5_TOL,
                        "crossover_hz": fx, "crossover_pred_hz": fx_pred,
                        "mean_dev": g5_mean_dev,
                        "residual_note": "균일 오프셋(실기 ~-3.5%)은 연속C(jω)"
                                         " vs 이산·min-max 4/3 근사 잔차 후보 —"
                                         " 기록만, 보상 금지",
                        "pass": bool(g5_pass),
                        "note": "in-situ 비=개루프 루프게인 |C·G| 실측(run #8) —"
                                " 채널조합·회전보정·게인읽기·주입노드는 검증하나"
                                " s 자체는 검증 안 함(s는 양경로 상쇄);"
                                " s 담당은 G0+G1'"},
        "G2_rac_band": {"ratios": g2_ratios, "band": list(G2_BAND),
                        "pass": all(G2_BAND[0] <= v <= G2_BAND[1]
                                    for v in g2_ratios)},
        "G3_l_spread": {"spread": spread, "max": G3_SPREAD,
                        "pass": spread <= G3_SPREAD},
        "G4_plaus_pm": {"pm_deg": pm, "design_ok": bool(ok),
                        "pass": bool(ok) and 1e-3 <= r_pp <= 10.0
                                and 1e-6 <= l_pp <= 1e-2},
    }
    ctx.evidence["gates"] = gates
    for gname, g in gates.items():
        if not g["pass"]:
            ctx.warnings.append("게이트 %s 실패 — YELLOW (%s)"
                                % (gname, {k: v for k, v in g.items()
                                           if k != "pass"}))
    _emit(ctx, "DESIGN", "게인 설계: KP=%.5g V/A, KI=%.1f Hz, PM=%.1f° (%s)"
          % (kp if kp else -1, ki if ki else -1, pm if pm else -1,
             "게이트 통과" if ok else "게이트 실패"))
    if not ok:
        return AutotuneResult(
            status=RED, reason="안정성 게이트 실패 (PM %.1f°<45° 또는 한계 위반,"
                               " wc 3회 감축 후)" % (pm if pm else -1),
            r_phase_ohm=r_pp / 2, r_pp_ohm=r_pp, l_phase_h=l_pp / 2, l_pp_h=l_pp,
            ts_us=int(ctx.readings["TS"]), evidence=ctx.evidence,
            warnings=ctx.warnings)
    status = YELLOW if ctx.warnings else GREEN
    _emit(ctx, "DONE", "측정 파이프라인 완료 — %s (적용은 별도 사용자 액션 E3)" % status)
    return AutotuneResult(
        status=status,
        reason="" if status == GREEN else "; ".join(ctx.warnings),
        kp_v_per_a=kp, ki_hz=ki,
        r_phase_ohm=r_pp / 2, r_pp_ohm=r_pp,
        l_phase_h=l_pp / 2, l_pp_h=l_pp,
        wc_rad_s=wc, pm_deg=pm, ts_us=int(ctx.readings["TS"]),
        evidence=ctx.evidence, warnings=ctx.warnings)


def _initial_sine_cmd(p: AutotuneParams, kp, ki_hz, r_pp, l_np_pp, f_hz, i1):
    """D1 initial amplitude: target actual amp / |T(jw)| when an L estimate
    exists (pp basis), else assume |T|=1 (adaptive retries fix a bad guess)."""
    t_mag = 1.0
    if l_np_pp and isinstance(kp, (int, float)) and kp > 0 \
            and isinstance(ki_hz, (int, float)) and r_pp:
        w = 2 * math.pi * f_hz
        c = kp * (1j * w + 2 * math.pi * ki_hz) / (1j * w)
        g = c / (l_np_pp * 1j * w + r_pp)
        t_mag = abs(g / (1 + g))
        t_mag = max(t_mag, 0.05)
    return float(np.clip(p.sine_target_amp / t_mag, 0.0, 0.8 * i1))


def _measure_sine(ctx: _Ctx, f_hz: float, a_cmd: float):
    """One SE excitation + record + demod.  Returns (|Z|, |I_f|, min(i), dt)
    or None when WS[75] never reports the generator running."""
    _write(ctx, "SE[3]", f_hz)
    _write(ctx, "SE[2]", a_cmd)
    if ctx.tc_now + a_cmd > 0.85 * ctx.cl1:         # I2 invariant (TC+SE)
        raise AbortError("전류지령 총합 %.1fA > 0.85*CL[1]" % (ctx.tc_now + a_cmd))
    _write(ctx, "TW[80]", 1, allow_motion=True)
    try:
        waited = 0.0
        while _cmd(ctx, "WS[75]") != 2:
            if waited >= 1.0:
                return None
            _sleep(ctx, ctx.params.poll_s)
            waited += ctx.params.poll_s
        _sleep(ctx, T_SINE_SETTLE_S)
        rec = _record(ctx, T_SINE_RECORD_S)
    finally:
        try:
            _cmd(ctx, "TW[80]=0", retries=0)
        except Exception:
            pass
    dt = rec["dt"]
    nwin = integer_cycle_window(len(rec["i"]), f_hz, dt)
    if nwin < 8:
        raise AbortError("정수사이클 창 부족 (f=%.0fHz, n=%d)" % (f_hz, len(rec["i"])))
    i_c = demod(rec["i"][-nwin:], f_hz, dt)          # complex phasors — abs 금지
    v_c = demod(rec["v_counts"][-nwin:], f_hz, dt)
    r_c = demod(rec["ref"][-nwin:], f_hz, dt)
    i_f = abs(i_c)
    return {"z_counts": (v_c / i_c) if i_f > 0 else complex(0.0),
            "i_f": i_f, "i_cplx": i_c, "icmd_cplx": r_c, "v_counts_f": v_c,
            "i_min": float(np.min(rec["i"])), "dt": dt,
            "vbus_mean": float(np.mean(rec["vbus"]))
                         if rec["vbus"] is not None else None}


# ======================================================================================
# E3 / E4 — separate operator actions (Phase-1 stubs per segment contract)
# ======================================================================================
def _fmt_gain(v: float) -> str:
    """Return an EAS-safe plain-decimal gain literal (never scientific)."""
    text = "%.*f" % (GAIN_DECIMALS_MAX, float(v))
    text = text.rstrip("0").rstrip(".")
    return text if text and text != "-" else "0"


P1_GAIN_NAMES = ("KP[1]", "KI[1]")
P1_GAIN_TRIAL_SYNTHETIC_MODE = "SYNTHETIC_NO_HARDWARE"
P1_TRIAL_PREPARING = "PREPARING"
P1_TRIAL_RAM = "RAM_TRIAL"
P1_TRIAL_RESTORING = "RESTORING"
P1_TRIAL_RESTORED = "RESTORED"
P1_TRIAL_RESTORE_FAILED = "RESTORE_FAILED"
P1_TRIAL_PERSISTING = "PERSISTING"
P1_TRIAL_PERSISTED = "PERSISTED"
P1_TRIAL_UNKNOWN = "UNKNOWN"
P1_TRIAL_AUTHORITY_INVALID = "AUTHORITY_INVALID"


P1_GAIN_TRIAL_FIELD_RAM_MODE = "RAM_TRIAL_VOLATILE_ROLLBACK"


def _p1_gain_trial_mode_allows_ram(link) -> bool:
    """Permit a rollback-capable RAM-only trial write.

    Two contracts qualify, and ONLY these two:

    * ``SYNTHETIC_NO_HARDWARE`` — the offline/no-hardware test contract.
    * ``RAM_TRIAL_VOLATILE_ROLLBACK`` — a real drive link opting into the
      EAS-parity, field-verified RAM trial.  This is safe because KP[1]/KI[1]
      RAM writes are volatile: a power cycle reloads the durable (SV) set, so
      the drive self-recovers even if the powered rollback never runs, and no
      durable pre-assignment WAL is required.  The runtime guards below still
      apply on every write (MO=0 readback, frozen rollback plan, full readback
      verification) and this path never issues SV — that stays separately
      gated on the commit path.
    """
    try:
        mode = getattr(link, "p1_gain_trial_durability_mode", None)
    except Exception:
        return False
    return (type(mode) is str
            and mode in (P1_GAIN_TRIAL_SYNTHETIC_MODE,
                         P1_GAIN_TRIAL_FIELD_RAM_MODE))


@dataclass
class GainTrialP1:
    """One rollback-capable, unsaved current-loop gain trial.

    ``original`` is the pre-write RAM snapshot. ``applied`` contains the exact
    rounded values accepted by the drive. ``rollback_literals`` and
    ``rollback_expected`` freeze the exact representable rollback transaction
    before any trial write. Creating or restoring this object never sends
    ``SV``; only :func:`commit_gain_trial_p1` may persist it.
    """
    original: dict
    applied: dict
    rollback_literals: dict = field(default_factory=dict)
    rollback_expected: dict = field(default_factory=dict)
    applied_fingerprint: tuple = field(init=False, repr=False)
    persistence_state: str = field(
        default=P1_TRIAL_PREPARING, init=False, compare=False)
    owner_link: object = field(
        default=None, init=False, repr=False, compare=False)
    stable_identity: object = field(
        default=None, init=False, repr=False, compare=False)
    session_token: object = field(
        default=None, init=False, repr=False, compare=False)
    restore_only: bool = field(
        default=False, init=False, repr=False, compare=False)

    def __post_init__(self):
        # A directly-constructed object is only PREPARING, never commit
        # authority. begin_gain_trial_p1 promotes it to RAM_TRIAL only after
        # every write/readback succeeds. Copy and validate every mutable input
        # so a caller cannot smuggle NaN/Inf into the final SV comparison.
        self.original = dict(self.original)
        self.applied = dict(self.applied)
        derived_literals, derived_expected = _p1_wire_values(self.original)
        if not self.rollback_literals and not self.rollback_expected:
            self.rollback_literals = derived_literals
            self.rollback_expected = derived_expected
        elif not self.rollback_literals or not self.rollback_expected:
            raise ValueError("P1 rollback plan incomplete")
        else:
            supplied_literals = dict(self.rollback_literals)
            supplied_expected = dict(self.rollback_expected)
            for name in P1_GAIN_NAMES:
                if supplied_literals.get(name) != derived_literals[name]:
                    raise ValueError("%s rollback literal changed" % name)
                expected = supplied_expected.get(name)
                if not isinstance(expected, (int, float)) \
                        or not math.isfinite(float(expected)) \
                        or float(expected) != derived_expected[name]:
                    raise ValueError("%s rollback expected value changed" % name)
            self.rollback_literals = supplied_literals
            self.rollback_expected = {
                name: float(supplied_expected[name]) for name in P1_GAIN_NAMES
            }
        _, applied_expected = _p1_wire_values(self.applied)
        self.applied = dict(applied_expected)
        self.applied_fingerprint = tuple(
            (name, float(applied_expected[name])) for name in P1_GAIN_NAMES)


def _p1_wire_values(values: dict) -> tuple[dict, dict]:
    """Validate the complete P1 set before the first drive write."""
    literals, sent = {}, {}
    for name in P1_GAIN_NAMES:
        if name not in values:
            raise ValueError("%s 값 누락" % name)
        requested = float(values[name])
        if not math.isfinite(requested) or requested <= 0.0:
            raise ValueError("%s 값은 유한한 양수여야 함: %r" % (name, requested))
        literal = _fmt_gain(requested)
        rounded = float(literal)
        if rounded <= 0.0:
            raise ValueError("%s 전송값이 0으로 소멸: %s" % (name, literal))
        error = abs(rounded / requested - 1.0)
        if error > GAIN_ROUND_RTOL:
            raise ValueError(
                "%s 반올림 오차 %.3f%% > %.3f%% (요청 %.9g, 전송 %s)" %
                (name, 100.0 * error, 100.0 * GAIN_ROUND_RTOL,
                 requested, literal))
        literals[name], sent[name] = literal, rounded
    return literals, sent


def _p1_rollback_plan(trial: GainTrialP1) -> tuple[dict, dict]:
    """Return and integrity-check the frozen rollback wire transaction.

    Older callers may still construct ``GainTrialP1(original, applied)``;
    derive the plan for those objects before any restore write. New trials
    always freeze both dictionaries in :func:`begin_gain_trial_p1`.
    """
    derived_literals, derived_expected = _p1_wire_values(trial.original)
    if not trial.rollback_literals and not trial.rollback_expected:
        return derived_literals, derived_expected
    if not trial.rollback_literals or not trial.rollback_expected:
        raise ValueError("P1 rollback plan incomplete")
    for name in P1_GAIN_NAMES:
        literal = trial.rollback_literals.get(name)
        expected = trial.rollback_expected.get(name)
        if literal != derived_literals[name]:
            raise ValueError("%s rollback literal changed" % name)
        if not isinstance(expected, (int, float)) \
                or not math.isfinite(float(expected)) \
                or float(expected) != derived_expected[name]:
            raise ValueError("%s rollback expected value changed" % name)
    return dict(trial.rollback_literals), {
        name: float(trial.rollback_expected[name]) for name in P1_GAIN_NAMES
    }


def _p1_frozen_applied_plan(trial: GainTrialP1) -> dict:
    """Rebuild and integrity-check the immutable applied recovery authority."""
    fingerprint = trial.applied_fingerprint
    if not isinstance(fingerprint, tuple) \
            or len(fingerprint) != len(P1_GAIN_NAMES):
        raise ValueError("P1 applied authority fingerprint malformed")
    expected = {}
    for index, name in enumerate(P1_GAIN_NAMES):
        item = fingerprint[index]
        if not isinstance(item, tuple) or len(item) != 2 or item[0] != name:
            raise ValueError("P1 applied authority fingerprint malformed")
        value = item[1]
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(float(value)) or float(value) <= 0.0:
            raise ValueError("%s frozen applied value invalid" % name)
        expected[name] = float(value)
    _, rounded = _p1_wire_values(expected)
    rebuilt = tuple(
        (name, float(rounded[name])) for name in P1_GAIN_NAMES)
    if rebuilt != fingerprint:
        raise ValueError("P1 applied authority fingerprint changed")
    return rounded


def _p1_applied_plan(trial: GainTrialP1) -> dict:
    """Validate mutable presentation data against frozen save authority."""
    frozen = _p1_frozen_applied_plan(trial)
    _, expected = _p1_wire_values(trial.applied)
    mutable_fingerprint = tuple(
        (name, float(expected[name])) for name in P1_GAIN_NAMES)
    if mutable_fingerprint != trial.applied_fingerprint:
        raise ValueError("P1 applied authority fingerprint changed")
    return frozen


def p1_gain_trial_has_save_authority(trial: GainTrialP1) -> bool:
    """Return False until real E4 can mint a sealed on-motor capability."""
    # E4 is an honest RED stub.  This must remain a reviewed code boundary,
    # never an environment/configuration bypass.
    return False


def _freeze_p1_transaction_identity(value):
    """Canonicalize a JSON-like stable drive identity for exact comparison."""
    if value is None or isinstance(value, (str, bytes, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite transaction identity component")
        return value
    if isinstance(value, dict):
        items = [(_freeze_p1_transaction_identity(k),
                  _freeze_p1_transaction_identity(v))
                 for k, v in value.items()]
        return ("mapping", tuple(sorted(items, key=repr)))
    if isinstance(value, (tuple, list)):
        return ("sequence", tuple(
            _freeze_p1_transaction_identity(v) for v in value))
    if isinstance(value, (set, frozenset)):
        items = [_freeze_p1_transaction_identity(v) for v in value]
        return ("set", tuple(sorted(items, key=repr)))
    raise TypeError("unsupported transaction identity type %s" %
                    type(value).__name__)


def _p1_link_identity(link):
    """Return a stable canonical identity, or None when unavailable."""
    identity_fn = getattr(link, "transaction_identity", None)
    if not callable(identity_fn):
        return None
    try:
        identity = identity_fn()
        if identity is None:
            return None
        return _freeze_p1_transaction_identity(identity)
    except Exception:
        return None


def _p1_link_session_token(link):
    """Return the connection-generation token, with exact-link fallback."""
    missing = object()
    try:
        session_fn = getattr(link, "transaction_session_identity", missing)
    except Exception:
        return None
    if session_fn is missing:
        return ("link-object", id(link))
    if not callable(session_fn):
        return None
    try:
        # An exposed API returning None explicitly means that no live session
        # authority exists. Only links without the API receive the fallback.
        return session_fn()
    except Exception:
        return None


def _p1_persistence_unknown_latched(link) -> bool:
    """Read the optional link-wide UNKNOWN latch without drive I/O."""
    try:
        getter = getattr(link, "persistence_unknown_latched", None)
    except Exception:
        return True
    if not callable(getter):
        return False
    try:
        return bool(getter())
    except Exception:
        # Once a link exposes the safety API, inability to read it cannot grant
        # fresh RAM-write authority.
        return True


def _p1_latch_persistence_unknown(link) -> None:
    """Best-effort idempotent latch for transports/test doubles exposing it."""
    try:
        setter = getattr(link, "latch_persistence_unknown", None)
    except Exception:
        return
    if not callable(setter):
        return
    try:
        setter()
    except Exception:
        # The trial state still becomes UNKNOWN below; never replace the
        # original SV transport exception with a helper failure.
        pass


def _capture_p1_session(link) -> tuple[object, object]:
    """Capture identity between two reads of one exact session generation."""
    token_before = _p1_link_session_token(link)
    if token_before is None:
        raise RuntimeError("P1 link session identity unavailable")
    stable_identity = _p1_link_identity(link)
    token_after = _p1_link_session_token(link)
    if token_after is None or token_after != token_before:
        raise RuntimeError("P1 link session changed during identity capture")
    return stable_identity, token_before


def _p1_session_matches(link, stable_identity, session_token) -> bool:
    """Check token, optional stable identity, then token again."""
    if session_token is None:
        return False
    token_before = _p1_link_session_token(link)
    if token_before is None or token_before != session_token:
        return False
    if stable_identity is not None:
        current_identity = _p1_link_identity(link)
        if current_identity != stable_identity:
            return False
    token_after = _p1_link_session_token(link)
    return token_after is not None and token_after == session_token


def _bind_gain_trial_p1(link, trial: GainTrialP1, *, stable_identity,
                        session_token) -> None:
    """Bind a prepared trial to the exact live link/session before writes."""
    trial.owner_link = link
    trial.stable_identity = stable_identity
    trial.session_token = session_token
    trial.restore_only = False


def _p1_same_session(link, trial: GainTrialP1) -> bool:
    if trial.owner_link is not link:
        return False
    return _p1_session_matches(
        link, trial.stable_identity, trial.session_token)


def _read_p1_gain_values(link) -> dict:
    values = {}
    for name in P1_GAIN_NAMES:
        value = _to_num(link.command(name))
        if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise RuntimeError("%s 되읽기 실패: %r" % (name, value))
        value = float(value)
        if value <= 0.0:
            raise RuntimeError("%s 되읽기 값이 0/음수: %.9g" % (name, value))
        values[name] = value
    return values


def _assert_p1_motor_off(link) -> None:
    mo = _to_num(link.command("MO"))
    if mo != 0:
        raise RuntimeError("모터 OFF 필요(MO=%r)" % mo)


def _p1_values_match(actual: dict, expected: dict) -> tuple[bool, str]:
    for name in P1_GAIN_NAMES:
        av, ev = float(actual[name]), float(expected[name])
        if abs(av - ev) > APPLY_READBACK_RTOL * abs(ev):
            return False, ("%s RAM 값 불일치: 기대 %.9g, 현재 %.9g (SV 금지)" %
                           (name, ev, av))
    return True, ""


def _write_p1_gain_values(link, values: dict) -> tuple[dict, list]:
    """Write and read back the complete P1 set; never send ``SV``."""
    literals, sent = _p1_wire_values(values)
    details = []
    for name in P1_GAIN_NAMES:
        link.command("%s=%s" % (name, literals[name]))
        rb = _to_num(link.command(name))
        if not isinstance(rb, (int, float)) or not math.isfinite(float(rb)):
            raise RuntimeError("%s 되읽기 실패: %r" % (name, rb))
        rb = float(rb)
        expected = sent[name]
        if rb <= 0.0 or abs(rb - expected) > APPLY_READBACK_RTOL * abs(expected):
            raise RuntimeError(
                "%s 쓰기 불일치: 전송 %s, 되읽기 %.9g (SV 금지)" %
                (name, literals[name], rb))
        details.append("%s=%s(되읽기 %.6g)" % (name, literals[name], rb))
    return sent, details


def restore_gain_trial_p1(link, trial: GainTrialP1):
    """Restore and verify the pre-trial P1 RAM gains; never send ``SV``."""
    if not isinstance(trial, GainTrialP1):
        return False, "복원 불가: 유효한 P1 RAM 시험 스냅숏이 없음"
    state = trial.persistence_state
    allowed = (P1_TRIAL_PREPARING, P1_TRIAL_RAM,
               P1_TRIAL_RESTORE_FAILED, P1_TRIAL_AUTHORITY_INVALID)
    if state not in allowed:
        return False, ("P1 restore blocked: trial state %s; no RAM write and "
                       "no SV executed" % state)
    if not _p1_same_session(link, trial):
        return False, ("P1 restore blocked: different or unbound link session; "
                       "use verified restore-only adoption after reconnect")
    try:
        _assert_p1_motor_off(link)
        literals, expected = _p1_rollback_plan(trial)
    except Exception as exc:
        trial.persistence_state = P1_TRIAL_RESTORE_FAILED
        return False, "P1 원래 게인 복원 사전검사 실패: %s (SV 미실행)" % exc

    if not _p1_same_session(link, trial):
        return False, ("P1 restore blocked: link session changed before "
                       "rollback writes; no RAM write and no SV executed")

    trial.persistence_state = P1_TRIAL_RESTORING
    write_warnings = []
    for name in P1_GAIN_NAMES:
        try:
            link.command("%s=%s" % (name, literals[name]))
        except Exception as exc:
            # A transport error on one register must not suppress the other
            # rollback attempt. The final independent readback decides what
            # is actually known about RAM.
            write_warnings.append("%s write failed: %s" % (name, exc))

    errors = []
    actual = {}
    for name in P1_GAIN_NAMES:
        try:
            raw = _to_num(link.command(name))
            if not isinstance(raw, (int, float)) or not math.isfinite(float(raw)):
                raise ValueError("invalid value %r" % (raw,))
            actual[name] = float(raw)
        except Exception as exc:
            errors.append("%s full readback failed: %s" % (name, exc))

    for name in P1_GAIN_NAMES:
        if name not in actual:
            continue
        observed, target = actual[name], expected[name]
        if observed <= 0.0 or abs(observed - target) > \
                APPLY_READBACK_RTOL * abs(target):
            errors.append("%s restore mismatch: expected %.9g, readback %.9g" %
                          (name, target, observed))

    readback = ", ".join(
        "%s=%.9g" % (name, actual[name]) if name in actual
        else "%s=UNKNOWN" % name
        for name in P1_GAIN_NAMES)
    if errors:
        trial.persistence_state = P1_TRIAL_RESTORE_FAILED
        all_errors = write_warnings + errors
        return False, ("P1 원래 게인 복원 실패: %s; full readback: %s "
                       "(SV 미실행)" % ("; ".join(all_errors), readback))
    trial.persistence_state = P1_TRIAL_RESTORED
    warning = ("; warning: " + "; ".join(write_warnings)
               + "; exact full readback is authoritative") \
        if write_warnings else ""
    return True, ("P1 원래 게인 복원·되읽기 완료: " + ", ".join(
        "%s=%.9g" % (name, expected[name]) for name in P1_GAIN_NAMES)
        + "; full readback: " + readback + warning + " (SV 미실행)")


def begin_gain_trial_p1(link, result: AutotuneResult):
    """Apply P1 gains to RAM as a rollback-capable, unsaved trial."""
    if result is None or result.status not in (GREEN, YELLOW):
        return False, "P1 RAM 적용 불가: 결과 상태 %s" % (
            result.status if result else None), None
    if not _p1_gain_trial_mode_allows_ram(link):
        return False, (
            "P1 RAM gain trial locked: this link does not opt into a "
            "rollback-capable RAM trial; no drive command executed"), None
    if _p1_persistence_unknown_latched(link):
        return False, ("P1 RAM trial blocked: link persistence state UNKNOWN; "
                       "no drive command executed"), None
    try:
        requested = {"KP[1]": result.kp_v_per_a, "KI[1]": result.ki_hz}
        _, applied = _p1_wire_values(requested)
        stable_identity, session_token = _capture_p1_session(link)
        _assert_p1_motor_off(link)
        original = _read_p1_gain_values(link)
        # A RAM trial is rollback-capable only if every original value has a
        # safe, representable wire literal. Freeze that plan before the first
        # trial write so restoration cannot discover a formatting problem late.
        rollback_literals, rollback_expected = _p1_wire_values(original)
        trial = GainTrialP1(
            original=original,
            applied=applied,
            rollback_literals=rollback_literals,
            rollback_expected=rollback_expected,
        )
        _bind_gain_trial_p1(
            link, trial, stable_identity=stable_identity,
            session_token=session_token)
        if not _p1_same_session(link, trial):
            raise RuntimeError(
                "P1 link session changed before first RAM trial write")
        if _p1_persistence_unknown_latched(link):
            raise RuntimeError(
                "link persistence state became UNKNOWN before first P1 "
                "RAM trial write")
        try:
            _, details = _write_p1_gain_values(link, requested)
        except Exception as exc:
            restored, restore_msg = restore_gain_trial_p1(link, trial)
            return False, ("P1 RAM 임시 적용 실패: %s; %s" %
                           (exc, restore_msg)), (None if restored else trial)
        trial.persistence_state = P1_TRIAL_RAM
        return True, ("P1 RAM 임시 적용·되읽기 통과: %s (SV 미실행)" %
                      ", ".join(details)), trial
    except Exception as exc:
        return False, "P1 RAM 임시 적용 불가: %s (SV 미실행)" % exc, None


def commit_gain_trial_p1(link, trial: GainTrialP1):
    """Persist an unchanged P1 trial after a final full-set readback."""
    if not isinstance(trial, GainTrialP1):
        return False, "P1 저장 불가: 유효한 RAM 시험 스냅숏이 없음"
    if _p1_persistence_unknown_latched(link):
        return False, ("P1 save blocked: link persistence state UNKNOWN; "
                       "SV not executed")
    if trial.restore_only:
        return False, ("P1 save blocked: reconnect-adopted trial is "
                       "restore-only; SV not executed")
    if trial.persistence_state != P1_TRIAL_RAM:
        return False, ("P1 save blocked: trial state %s; SV not executed" %
                       trial.persistence_state)
    if not _p1_same_session(link, trial):
        return False, ("P1 save blocked: different or unbound link session; "
                       "SV not executed")
    try:
        applied = _p1_applied_plan(trial)
    except Exception as exc:
        trial.persistence_state = P1_TRIAL_AUTHORITY_INVALID
        return False, ("P1 applied authority invalid: %s; SV not executed" %
                       exc)
    if not p1_gain_trial_has_save_authority(trial):
        return False, (
            "P1 save blocked: session-bound on-motor verification capability "
            "is unavailable while E4 remains RED; SV not executed")
    try:
        _assert_p1_motor_off(link)
        actual = _read_p1_gain_values(link)
        match, mismatch = _p1_values_match(actual, applied)
        if not match:
            return False, mismatch + "; SV not executed"
    except Exception as exc:
        return False, "P1 저장 사전검사 실패: %s; SV not executed" % exc
    if not _p1_same_session(link, trial):
        return False, ("P1 save blocked: link session changed during final "
                       "readback; SV not executed")
    if _p1_persistence_unknown_latched(link):
        return False, ("P1 save blocked: link persistence state UNKNOWN "
                       "after final readback; SV not executed")
    # A real ElmoLink implements a write-ahead persistence journal.  Record
    # the frozen transaction before SV so a process exit cannot erase the
    # ambiguity.  Legacy test doubles without this optional API retain the
    # existing in-memory-only behaviour.
    prepare_attempt = getattr(link, "prepare_persistence_attempt", None)
    complete_attempt = getattr(link, "complete_persistence_attempt", None)
    mark_unknown = getattr(link, "mark_persistence_attempt_unknown", None)
    attempt_id = None
    if callable(prepare_attempt):
        if not callable(complete_attempt) or not callable(mark_unknown):
            return False, ("P1 persistence journal API incomplete; "
                           "SV not executed")
        try:
            _rollback_literals, rollback_expected = _p1_rollback_plan(trial)
            attempt_id = prepare_attempt(
                phase="P1",
                registers=P1_GAIN_NAMES,
                original=rollback_expected,
                applied=applied,
            )
        except Exception as exc:
            return False, ("P1 persistence journal preflight failed: %s; "
                           "SV not executed" % exc)
    # Crossing this state transition consumes the one-shot save authority.
    # No later return path may make the same trial eligible for another SV.
    trial.persistence_state = P1_TRIAL_PERSISTING
    try:
        if attempt_id is not None:
            link.command("SV", _persistence_attempt_id=attempt_id)
        else:
            # Legacy/offline test doubles without the persistence journal do
            # not expose the private capability keyword.
            link.command("SV")
    except Exception as exc:
        _p1_latch_persistence_unknown(link)
        ledger_error = None
        if attempt_id is not None:
            try:
                mark_unknown(attempt_id, type(exc).__name__)
            except Exception as ledger_exc:
                # The pre-SV PERSISTING record remains active and fail-closed.
                ledger_error = ledger_exc
        # Once SV was issued, a timeout cannot distinguish rejection from a
        # completed save whose response was lost. Repeating SV is not safe.
        trial.persistence_state = P1_TRIAL_UNKNOWN
        return False, ("P1 response failed after SV command issuance: %s; "
                       "persistence state UNKNOWN; do not repeat SV; verify "
                       "after reset before relying on stored gains%s" %
                       (exc, ("; ledger update failed: %s" % ledger_error)
                        if ledger_error is not None else ""))
    if attempt_id is not None:
        try:
            complete_attempt(attempt_id)
        except Exception as exc:
            # SV replied, but losing durable close-out would be fail-open after
            # restart.  Keep the write-ahead record active and require audit.
            _p1_latch_persistence_unknown(link)
            trial.persistence_state = P1_TRIAL_UNKNOWN
            return False, ("P1 SV replied, but persistence journal close-out "
                           "failed: %s; persistence state UNKNOWN" % exc)
    trial.persistence_state = P1_TRIAL_PERSISTED
    return True, "P1 RAM 게인 최종 되읽기 일치 — SV 영구저장 완료"


def adopt_gain_trial_p1_for_restore(link, trial: GainTrialP1):
    """Adopt a reconnect-surviving trial for restoration only.

    Adoption never grants commit authority. It requires a stable identity match,
    MO=0, and a complete finite readback equal either to the frozen applied set
    or the frozen rollback set. UNKNOWN/PERSISTED save states are terminal and
    cannot be adopted without an external reset/persistence audit.
    """
    if not isinstance(trial, GainTrialP1):
        return False, "P1 adoption rejected: invalid trial"
    if trial.persistence_state not in (P1_TRIAL_RAM,
                                        P1_TRIAL_RESTORE_FAILED,
                                        P1_TRIAL_AUTHORITY_INVALID):
        return False, ("P1 adoption rejected: trial state %s" %
                       trial.persistence_state)
    if trial.stable_identity is None:
        return False, "P1 adoption rejected: original stable identity unavailable"
    try:
        candidate_identity, candidate_session_token = _capture_p1_session(link)
    except Exception as exc:
        return False, ("P1 adoption rejected: reconnect session unavailable: "
                       "%s" % exc)
    if candidate_identity is None:
        return False, "P1 adoption rejected: reconnect stable identity unavailable"
    if candidate_identity != trial.stable_identity:
        return False, "P1 adoption rejected: stable identity mismatch"

    try:
        _assert_p1_motor_off(link)
        actual = _read_p1_gain_values(link)
        applied = _p1_frozen_applied_plan(trial)
        _, rollback = _p1_rollback_plan(trial)
    except Exception as exc:
        return False, "P1 adoption readback/precheck failed: %s" % exc

    rollback_match, _ = _p1_values_match(actual, rollback)
    applied_match, _ = _p1_values_match(actual, applied)
    if not rollback_match and not applied_match:
        current = ", ".join(
            "%s=%.9g" % (name, actual[name]) for name in P1_GAIN_NAMES)
        return False, ("P1 adoption rejected: RAM drift from both applied and "
                       "rollback sets (%s)" % current)

    if not _p1_session_matches(
            link, candidate_identity, candidate_session_token):
        return False, ("P1 adoption rejected: reconnect session changed during "
                       "full readback")

    # Mutate ownership only after every identity and readback gate has passed.
    trial.owner_link = link
    trial.session_token = candidate_session_token
    trial.restore_only = True
    if rollback_match:
        trial.persistence_state = P1_TRIAL_RESTORED
        return True, ("P1 restore-only adoption complete: RAM already restored; "
                      "no write and no SV executed")
    if trial.persistence_state == P1_TRIAL_AUTHORITY_INVALID:
        # Save authority stays permanently blocked. RESTORE_FAILED is the
        # worker-visible recovery state that permits only verified rollback.
        trial.persistence_state = P1_TRIAL_RESTORE_FAILED
    return True, ("P1 restore-only adoption complete: applied RAM set verified; "
                  "Restore P1 is allowed, SV is permanently blocked")


def _apply_tail(applied, observed=None, unknown=None) -> str:
    parts = ["SV not executed",
             "verified prior RAM: %s" % (", ".join(applied) or "none")]
    if observed is not None:
        parts.append("observed RAM: %s" % observed)
    if unknown is not None:
        parts.append("RAM state UNKNOWN: %s" % unknown)
    if applied or observed is not None or unknown is not None:
        parts.append("DO NOT ENABLE until corrected and re-read or power-cycled")
    return "; " + "; ".join(parts)


def apply_gains(link, result: AutotuneResult, persist: bool = False):
    """E3: write KP[1]/KI[1] from a GREEN/YELLOW result.  MO must be 0.
    The compatibility API is RAM-only; persistent saves require GainTrialP1.
    Returns (ok, message).  Live behavior pending hardware verification."""
    if persist:
        return False, ("legacy persist=True blocked before RAM write; use "
                       "begin_gain_trial_p1 then commit_gain_trial_p1; "
                       "SV not executed")
    if not _p1_gain_trial_mode_allows_ram(link):
        return False, (
            "P1 RAM gain apply locked: this link does not opt into a "
            "rollback-capable RAM trial; no drive command executed")
    if result is None or result.status not in (GREEN, YELLOW) \
            or result.kp_v_per_a is None or result.ki_hz is None:
        return False, "적용 불가: 결과 상태 %s" % (result.status if result else None)
    if _p1_persistence_unknown_latched(link):
        return False, ("RAM apply blocked: link persistence state UNKNOWN; "
                       "no drive command executed")
    applied = []
    try:
        # Match begin_gain_trial_p1's motor-off strictness: reject unless MO reads
        # back as exactly 0 (an unreadable/non-zero MO must fail closed, not write).
        if _to_num(link.command("MO")) != 0:
            return False, "모터 정지(MO=0)로 확인되지 않음 — STOP 후 적용"

        # Validate every wire literal before the first write so a formatting
        # failure cannot leave a partially-applied pair in RAM.
        prepared = []
        for name, requested in (("KP[1]", result.kp_v_per_a),
                                ("KI[1]", result.ki_hz)):
            requested = float(requested)
            if not math.isfinite(requested) or requested <= 0.0:
                return False, "%s invalid gain %.9g%s" % (
                    name, requested, _apply_tail(applied))
            literal = _fmt_gain(requested)
            sent = float(literal)
            if not math.isfinite(sent) or sent <= 0.0:
                return False, ("%s rounds to %s at %d decimals%s" %
                               (name, literal, GAIN_DECIMALS_MAX,
                                _apply_tail(applied)))
            round_error = abs(sent / requested - 1.0)
            if round_error > GAIN_ROUND_RTOL:
                return False, ("%s rounding error %.3f%% exceeds %.3f%% "
                               "(requested %.9g, wire %s)%s" %
                               (name, 100.0 * round_error,
                                100.0 * GAIN_ROUND_RTOL, requested, literal,
                                _apply_tail(applied)))
            prepared.append((name, requested, literal, sent))

        if _p1_persistence_unknown_latched(link):
            return False, ("RAM apply blocked: link persistence state became "
                           "UNKNOWN before first gain write; no gain write "
                           "executed")

        for name, requested, literal, sent in prepared:
            try:
                link.command("%s=%s" % (name, literal))
            except Exception as exc:
                # The drive may have accepted the write before the transport
                # reported failure.  Never claim that RAM stayed unchanged.
                return False, ("%s write response failed: %s%s" %
                               (name, exc,
                                _apply_tail(applied, unknown=name)))
            try:
                raw_readback = link.command(name)
            except Exception as exc:
                return False, ("%s readback failed after write: %s%s" %
                               (name, exc,
                                _apply_tail(applied, unknown=name)))
            try:
                readback = float(_to_num(raw_readback))
            except (TypeError, ValueError):
                return False, ("%s unparseable readback %r%s" %
                               (name, raw_readback,
                                _apply_tail(applied, unknown=name)))
            if not math.isfinite(readback) or readback <= 0.0:
                tail = _apply_tail(
                    applied, observed="%s=%.9g" % (name, readback))
                return False, ("%s invalid readback %.9g "
                               "(requested %.9g, wire %s)%s" %
                               (name, readback, requested, literal, tail))
            error = abs(readback - sent) / abs(sent)
            if error > APPLY_READBACK_RTOL:
                tail = _apply_tail(
                    applied, observed="%s=%.9g" % (name, readback))
                return False, ("%s readback mismatch: requested %.9g, wire %s, "
                               "readback %.9g (%.3f%% > %.3f%%)%s" %
                               (name, requested, literal, readback,
                                100.0 * error, 100.0 * APPLY_READBACK_RTOL,
                                tail))
            applied.append("%s=%s (readback %.6g)" %
                           (name, literal, readback))

        if persist:
            try:
                link.command("SV")
            except Exception as exc:
                return False, ("SV command failed after readback verification: "
                               "%s; persistence state unknown; RAM applied: %s" %
                               (exc, ", ".join(applied)))
        return True, "readback verified: %s%s" % (
            ", ".join(applied), " + SV" if persist else "")
    except Exception as e:
        return False, "apply failed: %s%s" % (e, _apply_tail(applied))


def verify_run(link):
    """E4 stub: closed-loop verification run (step at I1 with the new gains,
    overshoot<=25% / 2 ms settling / no oscillation).  NOT implemented in
    Phase 1 — requires live hardware; returns an honest RED placeholder."""
    return AutotuneResult(
        status=RED,
        reason="E4 검증런 미구현 — Phase 2 (실기 검증 대기)",
        evidence={"todo": "B1~B3 재수행 + 스텝응답 게이트 (SPEC §7 E4)"})
