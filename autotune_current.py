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
  - GREEN gates G1..G4 (replace the old scale-pending blanket YELLOW):
    G1 in-situ magnitude (lowest f) vs Vbus scale within +-10%;
    G2 R_ac(f) in [0.8, 2.5]*R_dc at every f;
    G3 post-rotation L spread across f <= 10%;
    G4 plausibility ranges + stability gate (PM>=45 deg AND wc*TS<=0.25 AND
    0<KP<=100 AND 0<KI<=5000 on G(s)=KP(s+2*pi*KI)/s * 1/(L_pp s+R_pp)
    * exp(-1.5*TS*s)).  All pass -> GREEN; else YELLOW with named failures.

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
      CreatePersonalityModel upload behavior, and recording dt semantics
      (SamplingTime vs TimeResolution*TS — fallback is flagged in warnings).
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
from typing import Callable, Optional, Sequence

import numpy as np

__all__ = ["AutotuneParams", "AutotuneResult", "run_current_autotune",
           "apply_gains", "verify_run", "loop_margins", "design_gains",
           "demod", "derive_freqs", "neutral_subtract", "pi_discrete",
           "GREEN", "YELLOW", "RED"]

GREEN, YELLOW, RED = "GREEN", "YELLOW", "RED"

# --- calibration & gate constants (SPEC §4) -------------------------------------------
WC_TS_CAL = 0.2010        # wc*TS single-point calibration (EAS: KP/L_np*TS)
ALPHA_EAS = 1.2705        # base ratio; design KI = KI_PP_FACTOR*ALPHA_EAS*wc/(2*pi)
KI_PP_FACTOR = 2.0        # pp-basis 2x — live run #6 확정 (2*1.2705*wc/2pi = 812.9 = EAS)
SKEW_TAU_TS = 1.5         # recorded duty leads motor voltage by 1.5*TS (compute + ZOH/2)
G1_TOL = 0.10             # G1: in-situ magnitude (lowest f) vs Vbus scale
G2_BAND = (0.8, 2.5)      # G2: R_ac(f)/R_dc band
G3_SPREAD = 0.10          # G3: post-rotation L spread across f
DELAY_MULT = 1.5          # loop dead time = 1.5*TS (command applied next cycle + ZOH/2)
PM_MIN_DEG = 45.0
WCTS_MAX = 0.25
KP_MAX = 100.0
KI_MAX = 5000.0
MAX_WC_REDUCTIONS = 3     # PM<45 -> wc*=0.8, at most 3 times (SPEC §4)

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
GUARD_PERIOD_S = 0.5      # I3: MF/LC/PX poll period while MO=1
RECORDER_MAX_RL = 4096    # per-signal sample cap (CR: 16384/4 signals); longer -> TimeResolution up
DUTY_MID = 3750.0         # leg duty count at 50% duty = 0 V (fable-physics, live run #5)
DUTY_FS = 7500.0          # duty full scale hypothesis: counts <-> Vbus (cross-check path)

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
    #   P0, VALIDATE, SNAPSHOT, ENABLE, MEASURE_R, MEASURE_L, DESIGN, DONE.
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


def _cmd(ctx: _Ctx, cmd: str, allow_motion: bool = False, retries: int = 2):
    """command() with I5 retry policy (1 s timeout x2 retries -> abort) and
    NaN gate (SPEC §8: NaN response -> immediate abort)."""
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
        except Exception as e:                      # comm/drive error -> retry
            last = e
    raise AbortError("통신 실패 %r: %s" % (cmd, last))


def _write(ctx: _Ctx, cmd: str, value, allow_motion: bool = False):
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


def _ramp_tc(ctx: _Ctx, target: float, total_s: float, steps: int = 10):
    """Ramp TC from ctx.tc_now to target in `steps` writes over total_s."""
    start = ctx.tc_now
    for k in range(1, steps + 1):
        val = start + (target - start) * k / steps
        _write(ctx, "TC", val, allow_motion=True)
        ctx.tc_now = val
        _sleep(ctx, total_s / steps)


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
        raise PreflightError("DC Bus Voltage 신호 없음 — 주 스케일(Vbus/7500) 불가,"
                             " 신호목록 덤프 참조")
    bus_name = bus[0]
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
        "legs": list(legs), "bus": bus_name,
        "current_name": cur[0], "ref_name": ref[0],
        "note": "레그신호=PWM 듀티카운트(mid 3750); 'D Voltage'=유휴 제외;"
                " v_phN=중성점차감으로 재구성(스케일은 in-situ+Vbus 2경로)"}
    return {"legs": legs, "bus": bus_name, "i": cur[0], "ref": ref[0]}


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
    tr = max(1, int(math.ceil(duration_s / (RECORDER_MAX_RL * ts))))
    n = int(math.ceil(duration_s / (ts * tr)))
    rec_fn = getattr(ctx.link, "record", None)
    if not callable(rec_fn):
        raise AbortError("링크에 record() 없음 — .NET Drive Recording 래퍼 필요")
    sig = ctx.sig
    names = list(sig["legs"]) + ([sig["bus"]] if sig["bus"] else []) \
        + [sig["i"], sig["ref"]]
    try:
        out = rec_fn(names, n, time_resolution=tr)
    except Exception as e:
        raise AbortError("드라이브 레코딩 실패: %s" % e)
    try:
        i_arr = np.asarray(out[sig["i"]], dtype=float)
        ref_arr = np.asarray(out[sig["ref"]], dtype=float)
        legs = {nm: np.asarray(out[nm], dtype=float) for nm in sig["legs"]}
        vbus = np.asarray(out[sig["bus"]], dtype=float) if sig["bus"] else None
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
            "vbus": vbus, "dt": float(dt)}


def _dc_selfcheck(ctx: _Ctx, rec: dict, label: str):
    """T2/§3.4 self-check on DC segments: recorded IQ mean vs polled IQ <=5%."""
    mean_i = float(np.mean(rec["i"]))
    iq = _cmd(ctx, "IQ")
    if isinstance(iq, (int, float)):
        denom = max(abs(mean_i), 0.1)
        if abs(mean_i - iq) / denom > 0.05:
            ctx.warnings.append("%s: 기록IQ평균 %.3fA vs 폴링IQ %.3fA 편차>5%%"
                                % (label, mean_i, iq))


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


def _restore_snapshot(ctx: _Ctx):
    """A4/E1: restore only what we actually wrote, in fixed order, from snapshot."""
    restored, failed = [], []
    dirty = set(ctx.dirty)
    for cmd in _RESTORE_ORDER:
        if cmd not in dirty or cmd not in ctx.snapshot:
            continue
        try:
            _cmd(ctx, "%s=%s" % (cmd, _fmt(ctx.snapshot[cmd])), retries=1)
            restored.append(cmd)
        except Exception as e:
            failed.append("%s(%s)" % (cmd, e))
    if failed:
        ctx.warnings.append("복원 실패 %s — 전원 재투입 시 스냅숏(%s)으로 복원 필요"
                            % (", ".join(failed), ctx.snapshot_path))
    ctx.evidence["restored"] = restored
    return failed


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

    _try("A1 MO=0", lambda: ctx.link.command("MO=0", timeout_ms=1000))
    ctx.motor_on = False
    _try("A2 TW[80]=0", lambda: ctx.link.command("TW[80]=0", timeout_ms=1000))
    _try("A3 TC=0", lambda: ctx.link.command("TC=0", timeout_ms=1000,
                                             allow_motion=True))
    _try("A4 restore", lambda: _restore_snapshot(ctx))
    _try("A5 RR=0", lambda: ctx.link.command("RR=0", timeout_ms=1000))
    ctx.evidence["abort"] = {"reason": reason, "steps_done": steps}


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
              "XP[2]"])


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
        return _red(ctx, str(e))
    except AbortError as e:
        _do_abort(ctx, str(e))
        return _red(ctx, str(e))
    except Exception as e:                          # never die on an exception
        _do_abort(ctx, "내부 예외: %r" % (e,))
        return _red(ctx, "내부 예외: %r" % (e,))


def _pipeline(ctx: _Ctx) -> AutotuneResult:
    p = ctx.params

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
    _emit(ctx, "VALIDATE", "검증 통과: TS=%dµs, CL[1]=%.2fA → I1=%.2f/I2=%.2fA,"
          " 여진 f=%s Hz (f_max=%.0f)"
          % (int(ts), ctx.cl1, i1, i2,
             "/".join("%.0f" % f for f in ctx.freqs), f_max))

    # ---- P4 (before any write): recorder signal resolution ----------------------------
    ctx.sig = _resolve_signals(ctx)

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

    # ---- A2: claim a free feedback socket for Virtual-2-Sine (ID 8) -------------------
    used_sockets = {ctx.readings.get(k) for k in ("CA[45]", "CA[46]", "CA[47]")}
    ctx.socket = None
    for s in (4, 3, 2):
        sid = ctx.readings.get("CA[4%d]" % s)
        if s not in used_sockets and sid != 8:
            ctx.socket = s
            break
    if ctx.socket is None:
        raise PreflightError("SE용 빈 피드백 소켓 없음 (CA[42..44] 만석/ID8 선점)")
    _write(ctx, "CA[4%d]" % ctx.socket, 8)
    _write(ctx, "CA[70]", ctx.socket)

    # ---- A3: SE generator armed but silent --------------------------------------------
    for idx, val in ((1, 1), (2, 0), (3, ctx.freqs[0]), (4, 0), (5, 0), (6, 0), (7, 50)):
        _write(ctx, "SE[%d]" % idx, val)

    # ---- B1/B2: enable (operator gate is the CALLER's), wait servo-on -----------------
    _cmd(ctx, "MO=1", allow_motion=True)
    ctx.motor_on = True
    px0 = _cmd(ctx, "PX")
    ca18 = ctx.readings.get("CA[18]")
    ca18 = float(ca18) if isinstance(ca18, (int, float)) and ca18 > 0 else 0.0
    align_tol = (ca18 * 11.25 / 360.0) * 1.2 if ca18 else float("inf")
    theta_abort = max(4.0, ca18 * 2.0 / 360.0) if ca18 else float("inf")
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

    # ---- B4: alignment ramp to I1, standstill verification ----------------------------
    _ramp_tc(ctx, i1, ALIGN_STEPS * ALIGN_STEP_S, ALIGN_STEPS)
    _sleep(ctx, 1.0)
    pxa = _cmd(ctx, "PX")
    _sleep(ctx, 0.2)
    pxb = _cmd(ctx, "PX")
    if isinstance(pxa, (int, float)) and isinstance(pxb, (int, float)):
        if abs(pxb - pxa) > theta_abort:
            raise AbortError("정렬 후 모션 잔존 |dPX|=%.0f > %.0f"
                             % (abs(pxb - pxa), theta_abort))
        ctx.px_ref, ctx.px_tol = float(pxb), theta_abort   # tighten guard post-align

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
    s_prov = (vbus_dc / DUTY_FS) if vbus_dc else None
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
        raise AbortError("Vbus 미기록 — 주 스케일(Vbus/7500) 산출 불가")
    vbus_v = float(np.mean(ctx.vbus_samples))
    s_used = vbus_v / DUTY_FS
    if not (s_used > 0 and math.isfinite(s_used)):
        raise AbortError("Vbus 스케일 비정상 (Vbus=%r V)" % vbus_v)
    tau_s = SKEW_TAU_TS * ctx.ts_s
    ctx.evidence["scale"] = {"s_v_per_count": s_used, "vbus_v": vbus_v,
                             "tau_skew_s": tau_s,
                             "note": "주 스케일=Vbus_rec/7500(실기 6회차 확정);"
                                     " in-situ 크기(max|I_cmd−I| 주파수)=G1 게이트 전용"}
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
    _restore_snapshot(ctx)
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

    # ---- GREEN gates G1..G4 (run #6: replace the scale-pending blanket YELLOW) --------
    # G1 frequency selection (run #7 fix): the in-situ model divides by the
    # error phasor (I_cmd - I), which is SMALL at low f (tight tracking) ->
    # ill-conditioned there (live 200 Hz gave ratio 1.85 while the measurement
    # itself was perfect).  Cross-check at the excitation with the LARGEST
    # |I_cmd - I| — the best-conditioned estimator point.  Gate strength
    # unchanged (+-10%); only WHERE the estimator is evaluated changed.
    pick = max(sine_ev, key=lambda e: e["err_phasor_a"])
    g1_ratio = pick["s_insitu_mag_v_per_count"] / s_used
    g2_ratios = [e["r_ac_pp_ohm"] / r_pp for e in sine_ev]
    gates = {
        "G1_insitu_vs_vbus": {"f_hz": pick["f_hz"], "ratio": g1_ratio,
                              "err_phasor_a": pick["err_phasor_a"],
                              "criterion": "max|I_cmd-I| (well-conditioned)",
                              "tol": G1_TOL,
                              "pass": abs(g1_ratio - 1.0) <= G1_TOL},
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
    _write(ctx, "TW[80]", 1)
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
            ctx.link.command("TW[80]=0", timeout_ms=1000)
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
def apply_gains(link, result: AutotuneResult, persist: bool = False):
    """E3: write KP[1]/KI[1] from a GREEN/YELLOW result.  MO must be 0.
    SV only on explicit persist=True (I4: never inside the measurement run).
    Returns (ok, message).  Live behavior pending hardware verification."""
    if result is None or result.status not in (GREEN, YELLOW) \
            or result.kp_v_per_a is None or result.ki_hz is None:
        return False, "적용 불가: 결과 상태 %s" % (result.status if result else None)
    try:
        if _to_num(link.command("MO")) == 1:
            return False, "모터 ON(MO=1) — STOP 후 적용"
        link.command("KP[1]=%.9g" % result.kp_v_per_a)
        link.command("KI[1]=%.9g" % result.ki_hz)
        if persist:
            link.command("SV")
        return True, "KP[1]=%.5g KI[1]=%.5g 적용%s" % (
            result.kp_v_per_a, result.ki_hz, " + SV 영속화" if persist else "")
    except Exception as e:
        return False, "적용 실패: %s" % e


def verify_run(link):
    """E4 stub: closed-loop verification run (step at I1 with the new gains,
    overshoot<=25% / 2 ms settling / no oscillation).  NOT implemented in
    Phase 1 — requires live hardware; returns an honest RED placeholder."""
    return AutotuneResult(
        status=RED,
        reason="E4 검증런 미구현 — Phase 2 (실기 검증 대기)",
        evidence={"todo": "B1~B3 재수행 + 스텝응답 게이트 (SPEC §7 E4)"})
