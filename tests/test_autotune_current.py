# -*- coding: utf-8 -*-
"""Headless tests for autotune_current.py (SPEC docs/autotune-current-spec.md §9).

T3: a simulated Elmo drive answers the real command sequence through a mock
ElmoLink.  The plant (pp basis, fable-physics live run #5) runs at TS/2
half-steps with CENTER-ALIGNED current sampling (real PWM center sampling);
Elmo PI u=KP(e+2*pi*KI*TS*sum(e)); 1-period command delay; 0.24 V dead-time in
the plant; recorded voltages are PER-LEG PWM DUTY COUNTS (mid 3750, SVM min-max
common mode -> single leg = 3/4 phase voltage, counts = volts*7500/Vbus) with
an in-phase dead-time-like contamination (~0.06 V @ 3 A) that the retired |Z|
magnitude method misattributes to L.  The corrected pipeline (neutral
subtraction + in-situ/Vbus scale + complex Im(Z)) must recover the frozen
oracles: R_pp 0.119 ohm (<=1%), L_pp 35.7 uH (<=3%), KP 0.07177 (<=3%,
TS=100us pp), plus the naive-V/I regression.
No hardware is touched anywhere in this file.
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autotune_current as at
from autotune_current import (AutotuneParams, AutotuneResult, run_current_autotune,
                              apply_gains, verify_run, loop_margins, design_gains,
                              demod, GREEN, YELLOW, RED)

# ---- frozen oracles (SPEC §9 — never re-baseline here) -------------------------------
# Basis (fable-physics, live runs #5/#6): drive gain system is PHASE-TO-PHASE,
# real TS=100us -> KP = wc*L_pp reproduces EAS 0.07177 (-0.018%) and
# KI = 2*alpha*wc/2pi reproduces EAS 812.939 (~0%).  Measured R is the
# TERMINAL resistance (motor 0.119 + parasitics ~23 mOhm pp = 0.1421).
R_PP_ORACLE = 0.119          # ohm, phase-to-phase (motor nameplate)
R_TERM_PP = 0.1421           # ohm, terminal = motor + cable/FET parasitics (run #6)
L_PP_ORACLE = 0.0357e-3      # H,   phase-to-phase
KP_ORACLE = 0.07177          # V/A  (EAS, TS=100us, pp basis)
KI_ORACLE = 812.94           # Hz   (EAS — matched by 2*alpha*wc/2pi, run #6)
R_PH_TRUTH = R_PP_ORACLE / 2.0
L_PH_TRUTH = L_PP_ORACLE / 2.0
TS_US = 100                  # real drive sampling time
VBUS_TRUTH = 48.46           # live bus voltage read-back (run #6) [V]


# ======================================================================================
# simulated drive (T3 plant per SPEC §9)
# ======================================================================================
class SimDrive:
    """Mock ElmoLink: command()-compatible, with the T3 discrete plant inside.
    Time advances ONLY via advance(dt) — inject it as AutotuneParams.sleep_fn."""

    p1_config_durability_mode = "SYNTHETIC_NO_HARDWARE"
    p1_gain_trial_durability_mode = "SYNTHETIC_NO_HARDWARE"

    _MOTION_PREFIXES = ("MO=1", "BG", "JV", "PA", "PR", "PT", "PVT", "TC", "MI")

    def __init__(self, kp=KP_ORACLE, ki=812.939, r_pp=R_TERM_PP, l_pp=L_PP_ORACLE,
                 ts_us=TS_US, vdt=0.24, noise_a=0.02, vbus=VBUS_TRUTH,
                 r_dt_ac=0.0025, xp2=2, ripple_frac=0.055, se_injects=True,
                 with_voltage_signal=True, px_jump_at_s=None, mo0=0, mf=0, seed=1):
        # PHASE-TO-PHASE plant with TERMINAL resistance (run #6).  r_dt_ac =
        # small sample-aligned dead-time-like contamination on the RECORDED
        # legs (~0.008 V @ 3 A).  Larger values (run-#5's 0.02 ohm) are
        # counterfactual: the live post-rotation data shows clean Im
        # (L spread 0.6%), which a big sample-aligned injection would violate.
        self.r, self.l, self.vdt, self.noise_a = r_pp, l_pp, vdt, noise_a
        self.vbus, self.r_dt_ac = float(vbus), float(r_dt_ac)
        self.ts_s = ts_us * 1e-6
        # G0 platform truth: duty full scale from the 150 MHz PWM counter
        # (CR: TS*f_pwm = XP[2]/2).  XP[2]=2, TS=100us -> FS=7500, mid=3750.
        self.xp2 = int(xp2)
        self.duty_fs = 150e6 * self.ts_s / self.xp2
        self.duty_mid = self.duty_fs / 2.0
        self.a = math.exp(-r_pp * self.ts_s / l_pp)      # full-period plant step
        self.b = (1.0 - self.a) / r_pp
        self.rng = np.random.default_rng(seed)
        self.se_injects = se_injects
        self.px_jump_at_s = px_jump_at_s
        self.t = 0.0
        self.i = 0.0
        self.integ = 0.0
        self.u_prev = 0.0
        self.iq_now = 0.0
        self.iq_meas = 0.0
        # run-#10 realism: PWM current RIPPLE rides on the RECORDED/POLLED
        # current (the recorder and the IQ poll see it; the controller's own
        # sample is ripple-suppressed by center sampling).  Peak 5.5% ->
        # sigma ~3.9% of the DC level — reproduces the live probe std
        # (0.083 A @ 2.121 A) and the run-#10 poll-on-peak event.
        self.ripple_frac = float(ripple_frac)
        self.ripple_hz = 1170.0      # incommensurate with the 200..800 Hz SE bins
        self.last_ref = 0.0
        self.t0 = 0.0
        self.ws = 0
        self.regs = {"TS": ts_us, "MC": 100, "PL[1]": 70.71, "CL[1]": 21.21,
                     "CL[2]": 1, "CL[3]": 42.42, "CL[4]": 3000, "UM": 5,
                     "KP[1]": kp, "KI[1]": ki,
                     "CA[17]": 2, "CA[18]": 524288, "CA[19]": 16,
                     "CA[41]": 30, "CA[42]": 0, "CA[43]": 0, "CA[44]": 0,
                     "CA[45]": 1, "CA[46]": 1, "CA[47]": 1, "CA[70]": 0,
                     "SC[8]": 0, "SR": 0, "MF": mf, "BV": 48.1,
                     "XP[2]": self.xp2,
                     # WS platform regs (CR p.291): 54/56/57 = max/min/range PWM
                     # command in 150 MHz clock counts (LIMITS, slightly inside
                     # FS); 53 = internal-units -> bus-voltage float
                     "WS[53]": self.vbus / self.duty_fs,
                     "WS[54]": round(self.duty_fs * 0.998),
                     "WS[56]": 15,
                     "WS[57]": round(self.duty_fs * 0.998) - 15,
                     "MO": mo0, "TW[80]": 0, "LC": 0,
                     "RC": 0, "RG": 1, "RL": 4096, "RP[0]": 0, "RP[3]": 0}
        for n in range(1, 8):
            self.regs["SE[%d]" % n] = 0
        # live-grounded personality names (2026-07-13, 254-signal dump) with the
        # decoys that the precision mapping must reject or deprioritize
        self.signals = ["Position Feedback", "DC Bus Voltage",
                        "Current Command [A]", "Total Current Command [A]",
                        "Active Current [A]", "Reactive Current [A]"]
        if with_voltage_signal:
            self.signals += ["A Voltage", "B Voltage", "C Voltage", "D Voltage"]
        self.leg_counts = (self.duty_mid, self.duty_mid, self.duty_mid)
        self.record_calls = 0            # .NET-wrapper record() usage counter
        self.log = []

    is_connected = True

    def recorder_signals(self):
        """Mock of ElmoLink.recorder_signals() (personality SignalsMetaData names)."""
        return list(self.signals)

    def _chan_value(self, name):
        """Signal name -> instantaneous recorded value.  'A/B/C Voltage' are
        per-leg PWM DUTY COUNTS built in _step() (mid 3750, SVM common mode,
        counts=volts*7500/Vbus); 'D Voltage' is the idle constant leg."""
        if name == "Position Feedback":
            return self.px()
        if name == "DC Bus Voltage":
            return self.vbus
        if name in ("Current Command [A]", "Total Current Command [A]"):
            # run-#8/#9 realism: during SE this channel does NOT log the
            # controller-input command (SE injects via the CA[70] adder
            # socket).  Empirically the effective error phasor obeys
            # |Icmd_rec - I| ~ |I| x |C_cont|/|C_disc| — exactly what makes
            # the in-situ ratio track the OPEN-LOOP GAIN |C·G| (rho=1 near the
            # gain crossover) instead of the scale; the small uniform residual
            # is the continuous-C approximation.  Record-only channel — the
            # loop and the V/I measurement channels are untouched.
            if self.regs.get("TW[80]") == 1 and self.se_injects:
                f_se = float(self.regs.get("SE[3]", 0.0) or 0.0)
                if f_se > 0:
                    gam = (abs(at.pi_continuous(f_se, self.regs["KP[1]"],
                                                self.regs["KI[1]"]))
                           / abs(at.pi_discrete(f_se, self.ts_s,
                                                self.regs["KP[1]"],
                                                self.regs["KI[1]"])))
                    tc = self.regs.get("TC", 0.0)
                    return tc + (1.0 - gam) * (self.iq_meas - tc)
            return self.last_ref
        if name == "Active Current [A]":
            return self.iq_meas
        if name == "Reactive Current [A]":
            return 0.0
        if name == "A Voltage":
            return self.leg_counts[0]
        if name == "B Voltage":
            return self.leg_counts[1]
        if name == "C Voltage":
            return self.leg_counts[2]
        if name == "D Voltage":
            return self.duty_mid                     # idle leg (live: constant FS/2)
        raise KeyError(name)

    def record(self, signals, length, time_resolution=1):
        """Mock of ElmoLink.record(): advances the SAME discrete plant for
        length*time_resolution steps.  Mimics the REAL .NET upload behavior —
        Data keys are POSITIONAL 0..N-1 (live-confirmed run #4, NOT
        SignalIndex) — and routes through the production remap
        (elmo_link._map_upload_data), so SignalIndex-style regressions are
        caught by every sim run."""
        import elmo_link
        self.record_calls += 1
        tr = max(1, int(time_resolution))
        for s in signals:
            if s not in self.signals:
                raise KeyError("signals not in personality: %r" % s)
        bufs = {s: [] for s in signals}
        steps = int(length) * tr
        noise = self.rng.standard_normal(steps) * self.noise_a
        for k in range(steps):
            self._step(noise[k])
            if k % tr == 0:
                for s in signals:
                    bufs[s].append(self._chan_value(s))
        raw = {i: np.asarray(bufs[s], dtype=float)   # positional Dict<int,double[]>
               for i, s in enumerate(signals)}
        out = elmo_link._map_upload_data(list(signals), raw)
        out["dt"] = self.ts_s * tr
        return out

    # ---- physics ---------------------------------------------------------------------
    def px(self):
        base = 1000.0
        if self.px_jump_at_s is not None and self.t >= self.px_jump_at_s:
            base += 50000.0
        return base

    def advance(self, dur_s):
        n = int(round(dur_s / self.ts_s))
        if n <= 0:
            return
        noise = self.rng.standard_normal(n) * self.noise_a
        for k in range(n):
            self._step(noise[k])

    def _step(self, nk):
        """One PWM period (run-#6 timing): current sampled at period START;
        the controller output u[k] is RECORDED as this row's leg duty counts
        but APPLIED next period (1 TS compute delay + PWM ZOH/2) -> the
        recorded V leads the motor voltage by ~1.5*TS.  The pipeline's
        rotation correction exp(-j*w*1.5*TS) must remove exactly this skew
        (probe-verified: corrected L residual ~1%, uncorrected +26..+59%)."""
        regs = self.regs
        mo = regs["MO"]
        im = self.i + nk                             # sample at period start (+noise)
        ref = 0.0
        if mo == 1:
            ref = regs.get("TC", 0.0)
            if regs["TW[80]"] == 1 and self.se_injects:
                ref += (regs["SE[2]"] *
                        math.sin(2 * math.pi * regs["SE[3]"] * (self.t - self.t0))
                        + regs["SE[6]"])
            e = ref - im
            self.integ += 2 * math.pi * regs["KI[1]"] * self.ts_s * e
            u = regs["KP[1]"] * (e + self.integ)
            v_eff = self.u_prev - self.vdt * (1.0 if self.i >= 0 else -1.0)
        else:
            u, v_eff = 0.0, 0.0
            self.integ = 0.0
        self.i = self.a * self.i + self.b * v_eff    # plant sees LAST cycle's duty
        # recorded legs from THIS cycle's u (live-confirmed skew source) plus a
        # small sample-aligned contamination
        i_ac = (im - regs.get("TC", 0.0)) if mo == 1 else 0.0
        vph = u / 2.0 + self.r_dt_ac * i_ac          # phase-neutral volts
        ph = (vph, -vph / 2.0, -vph / 2.0)
        cm = -(max(ph) + min(ph)) / 2.0              # SVM min-max injection
        kv = self.duty_fs / self.vbus                # counts per volt (G0 truth)
        self.leg_counts = tuple(self.duty_mid + (pv + cm) * kv for pv in ph)
        self.u_prev = u
        # recorded/polled current = controller sample + PWM ripple (run #10):
        # the recorder and single IQ polls see the ripple; the loop does not
        rip = (self.ripple_frac * abs(regs.get("TC", 0.0))
               * math.sin(2 * math.pi * self.ripple_hz * self.t)) if mo == 1 else 0.0
        self.iq_now, self.iq_meas, self.last_ref = im, im + rip, ref
        self.t += self.ts_s

    # ---- transport -------------------------------------------------------------------
    def command(self, cmd, timeout_ms=1000, allow_motion=False):
        self.log.append((cmd, allow_motion))
        u = cmd.replace(" ", "").upper()
        if not allow_motion and any(u.startswith(p) for p in self._MOTION_PREFIXES):
            raise PermissionError("refused motion command without allow_motion: %r" % cmd)
        if "=" in cmd:
            name, val = cmd.split("=", 1)
            return self._write(name.strip(), float(val))
        return self._query(cmd.strip())

    def _write(self, name, v):
        regs = self.regs
        if name == "MO":
            if v == 1:
                if regs["MF"] != 0:
                    raise IOError("cannot enable: fault present")
                regs["MO"] = 1
                regs["TC"] = 0.0
                self.integ = 0.0
                self.u_prev = 0.0
            else:
                regs["MO"] = 0
            return ""
        if name == "UM":
            if regs["MO"] == 1:
                raise IOError("UM change requires MO=0")
            regs["UM"] = int(v)
            return ""
        if name == "TC":
            if regs["MO"] != 1:
                # live-realistic: torque command rejected with the servo off —
                # the abort chain's A3 (after A1 MO=0) must demote this to an
                # expected step, not a warning (2026-07-13 noise cleanup)
                raise IOError("Drive error 58: Servo must be on")
            if abs(v) > regs["PL[1]"]:
                raise IOError("TC exceeds PL[1]")
            regs["TC"] = v
            return ""
        if name == "TW[80]":
            regs["TW[80]"] = int(v)
            if int(v) == 1:
                self.t0 = self.t
                self.ws = 2
            else:
                self.ws = 0
            return ""
        if name == "RR":
            # RR=0 (abort A5 kill) is accepted; RR=2 legacy arming is RETIRED —
            # any attempt means the .NET record path regressed: fail loudly.
            if int(v) == 2:
                raise IOError("legacy RR=2 recording path retired (use link.record)")
            return ""
        if name == "BH":
            raise IOError("legacy BH upload retired (use link.record)")
        regs[name] = v
        return ""

    def _query(self, name):
        if name == "PX":
            return "%.6f" % self.px()
        if name == "IQ":
            return "%.6f" % self.iq_meas
        if name == "SO":
            return "1" if self.regs["MO"] == 1 else "0"
        if name == "WS[75]":
            return str(self.ws)
        if name == "RR":
            return "0"
        if name == "SV":
            return ""
        if name in self.regs:
            return str(self.regs[name])
        raise IOError("unknown query %r" % name)


class ConfigurationJournalSimDrive(SimDrive):
    """SimDrive with the same private RAM-transaction boundary as ElmoLink."""

    def __init__(self, *args, fail_prepare=False, fail_resolve=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_prepare = bool(fail_prepare)
        self.fail_resolve = bool(fail_resolve)
        self.config_attempt_id = "offline-p1-config-attempt"
        self.config_attempt_active = False
        self.config_rollback_active = False
        self.config_unknown = False
        self.journal_events = []
        self.capability_rejections = []

    def prepare_persistence_attempt(self, **kwargs):
        self.journal_events.append(("prepare", dict(kwargs)))
        if self.fail_prepare:
            raise IOError("synthetic journal prepare failure")
        self.config_attempt_active = True
        self.config_rollback_active = False
        return self.config_attempt_id

    def begin_persistence_ram_rollback(self, record_id):
        self.journal_events.append(("begin_rollback", record_id))
        assert record_id == self.config_attempt_id
        assert self.config_attempt_active
        self.config_rollback_active = True

    def resolve_persistence_ram_rollback(self, record_id):
        self.journal_events.append(("resolve", record_id))
        assert record_id == self.config_attempt_id
        assert self.config_rollback_active
        if self.fail_resolve:
            raise IOError("synthetic journal closeout failure")
        self.config_attempt_active = False
        self.config_rollback_active = False
        return {name: self.regs[name] for name in at.P1_CONFIG_NAMES}

    def mark_persistence_attempt_unknown(self, record_id, reason):
        self.journal_events.append(("unknown", record_id, str(reason)))
        assert record_id == self.config_attempt_id
        self.config_attempt_active = False
        self.config_rollback_active = False
        self.config_unknown = True

    def latch_persistence_unknown(self):
        self.journal_events.append(("runtime_latch",))
        self.config_unknown = True

    def persistence_unknown_latched(self):
        return self.config_unknown

    def command(self, cmd, timeout_ms=1000, allow_motion=False,
                _persistence_attempt_id=None):
        core = "".join(str(cmd).split()).upper().rstrip(";")
        assignment = "=" in core
        safe = core in {"MO=0", "TC=0"}
        if (self.config_attempt_active and assignment and not safe
                and _persistence_attempt_id != self.config_attempt_id):
            self.capability_rejections.append(core)
            raise RuntimeError("P1_CONFIG capability missing")
        self.journal_events.append((
            "command", core, _persistence_attempt_id,
            self.config_attempt_active))
        return super().command(
            cmd, timeout_ms=timeout_ms, allow_motion=allow_motion)


def _params(drive, tmpdir, **kw):
    return AutotuneParams(sleep_fn=drive.advance, snapshot_dir=str(tmpdir), **kw)


# ======================================================================================
# T3: full-pipeline oracle test (the core acceptance)
# ======================================================================================
@pytest.fixture(scope="module")
def green_run(tmp_path_factory):
    drive = SimDrive()
    params = _params(drive, tmp_path_factory.mktemp("snap"))
    res = run_current_autotune(drive, params)
    return drive, params, res


def test_t3_pipeline_completes_green_via_gates(green_run):
    """Run #8 final: gates G0/G1'/G2/G3/G4/G5 all pass on the nominal mock ->
    honest GREEN (the in-situ SCALE gate G1 is abolished)."""
    _, _, res = green_run
    assert res.status == GREEN, "status=%s reason=%s warn=%s" % (
        res.status, res.reason, res.warnings)
    assert res.warnings == []
    gates = res.evidence["gates"]
    assert set(gates) == {"G0_platform", "G1p_idle_vbus", "G2_rac_band",
                          "G3_l_spread", "G4_plaus_pm", "G5_loopgain"}
    assert all(g["pass"] for g in gates.values()), gates
    assert res.ts_us == TS_US


def test_t3_resistance_terminal_oracle(green_run):
    """R is the TERMINAL resistance (motor + parasitics) — reported honestly,
    NOT corrected to nameplate (run #6; R does not enter the gain formula)."""
    _, _, res = green_run
    err = res.r_pp_ohm / R_TERM_PP - 1.0
    assert abs(err) <= 0.01, "R_pp=%.6f ohm err=%+.2f%%" % (res.r_pp_ohm, 100 * err)
    assert "터미널" in res.evidence["dc"]["r_basis"]


def test_t3_inductance_oracle(green_run):
    _, _, res = green_run
    err = res.l_pp_h / L_PP_ORACLE - 1.0
    assert abs(err) <= 0.03, "L_pp=%.4g H err=%+.2f%%" % (res.l_pp_h, 100 * err)


def test_t3_kp_oracle(green_run):
    _, _, res = green_run
    err = res.kp_v_per_a / KP_ORACLE - 1.0
    assert abs(err) <= 0.03, "KP=%.5f err=%+.2f%%" % (res.kp_v_per_a, 100 * err)


def test_t3_ki_oracle_restored(green_run):
    """KI = 2*alpha*wc/(2*pi) — the pp-basis 2x confirmed on live run #6
    reproduces the EAS oracle 812.94 Hz (closes the previous open finding)."""
    _, _, res = green_run
    err = res.ki_hz / KI_ORACLE - 1.0
    assert abs(err) <= 0.005, "KI=%.3f err=%+.3f%%" % (res.ki_hz, 100 * err)
    ki_formula = (at.KI_PP_FACTOR * at.ALPHA_EAS
                  * (at.WC_TS_CAL / (TS_US * 1e-6)) / (2 * math.pi))
    assert res.ki_hz == pytest.approx(ki_formula, rel=1e-9)


def test_t3_naive_vi_regression(green_run):
    """SPEC §3.2/§9: naive V/I MUST be badly wrong (>= +30% at the I1 level,
    where the dead-time voltage weighs most) — proves the two-point method is
    load-bearing, not decorative."""
    _, _, res = green_run
    dc = res.evidence["dc"]
    naive_err = dc["r_naive_pp_i1_ohm"] / R_TERM_PP - 1.0
    assert naive_err >= 0.30, "naive err %+.1f%% (deadtime should inflate it)" \
        % (100 * naive_err)
    two_pt_err = dc["r_pp_ohm"] / R_TERM_PP - 1.0
    assert abs(two_pt_err) <= 0.01


def test_t2_v1_range_and_gate(green_run):
    """T2 mid-oracle: scaled v_phN at I1 in [0.15, 1.2] V; PM gate satisfied."""
    _, _, res = green_run
    s = res.evidence["scale"]["s_v_per_count"]
    v1_volts = s * res.evidence["dc"]["v1_counts"]
    assert 0.15 <= v1_volts <= 1.2, "v1=%.3f V" % v1_volts
    assert res.pm_deg >= 45.0
    assert res.wc_rad_s * TS_US * 1e-6 <= 0.25


def test_t3_snapshot_written_before_writes(green_run):
    _, _, res = green_run
    path = res.evidence["snapshot_path"]
    assert os.path.isfile(path)
    import json
    snap = json.load(open(path, encoding="utf-8"))
    assert snap["readings"]["KP[1]"] == pytest.approx(KP_ORACLE)
    assert snap["readings"]["UM"] == 5


def test_t3_drive_restored_after_run(green_run):
    """E1: UM/sockets/SE restored, motor off, drive gains untouched (E3 is separate)."""
    drive, _, res = green_run
    r = drive.regs
    assert r["MO"] == 0
    assert r["UM"] == 5
    assert r["CA[44]"] == 0 and r["CA[70]"] == 0        # socket 4 released
    assert all(r["SE[%d]" % n] == 0 for n in range(1, 8))
    assert r["KP[1]"] == pytest.approx(KP_ORACLE)       # not applied in Phase 1
    assert r["KI[1]"] == pytest.approx(812.939)


def test_t3_motion_commands_used_allow_motion_gate(green_run):
    """Every MO=1/TC send must have carried allow_motion=True (link contract)."""
    drive, _, _ = green_run
    sent = [(c, am) for c, am in drive.log
            if c.replace(" ", "").upper().startswith(("MO=1", "TC"))]
    assert sent and all(am for _, am in sent)


# ======================================================================================
# bootstrap path (P5/B3) — KP[1]==0 drive + nameplate
# ======================================================================================
def test_bootstrap_from_nameplate(tmp_path):
    drive = SimDrive(kp=0.0, ki=0.0)
    params = _params(drive, tmp_path, nameplate_r_pp=R_PP_ORACLE,
                     nameplate_l_pp_h=L_PP_ORACLE)
    res = run_current_autotune(drive, params)
    assert res.status in (GREEN, YELLOW), res.reason
    assert abs(res.r_pp_ohm / R_TERM_PP - 1.0) <= 0.02   # terminal R
    assert abs(res.l_pp_h / L_PP_ORACLE - 1.0) <= 0.05
    assert "bootstrap" in res.evidence
    # original (unconfigured) gains restored — apply is a separate operator action
    assert drive.regs["KP[1]"] == 0.0 and drive.regs["KI[1]"] == 0.0


def test_kp_zero_without_nameplate_is_red(tmp_path):
    drive = SimDrive(kp=0.0, ki=0.0)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "부트스트랩" in res.reason or "명판" in res.reason


# ======================================================================================
# RED / abort paths (SPEC §6/§8)
# ======================================================================================
def test_mo1_at_start_red_without_auto_disable(tmp_path):
    drive = SimDrive(mo0=1)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "STOP" in res.reason
    assert not any(c.replace(" ", "").startswith("MO=0") for c, _ in drive.log), \
        "must NOT auto-disable an enabled motor"


def test_motor_fault_red_before_any_write(tmp_path):
    drive = SimDrive(mf=0x10)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "폴트" in res.reason
    assert all("=" not in c for c, _ in drive.log), "P0..P2 must be read-only"


def test_missing_voltage_signal_red_with_dump(tmp_path):
    drive = SimDrive(with_voltage_signal=False)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "전압" in res.reason
    assert "recorder_signals" in res.evidence
    assert "Active Current [A]" in res.evidence["recorder_signals"]


def test_se_injection_failure_red_u1_and_abort_order(tmp_path):
    """U1 edge: WS reports running but no current appears -> RED after retries,
    abort chain order MO=0 -> TW[80]=0 -> TC=0 (SPEC §6, fixed)."""
    drive = SimDrive(se_injects=False)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "U1" in res.reason
    cmds = [c.replace(" ", "") for c, _ in drive.log]
    i_mo = cmds.index("MO=0")                       # first MO=0 == abort A1
    i_tw = next(i for i, c in enumerate(cmds) if i > i_mo and c == "TW[80]=0")
    i_tc = next(i for i, c in enumerate(cmds) if i > i_tw and c == "TC=0")
    assert i_mo < i_tw < i_tc
    # restore still happened
    assert drive.regs["UM"] == 5 and drive.regs["CA[44]"] == 0


def test_px_motion_guard_aborts(tmp_path):
    drive = SimDrive(px_jump_at_s=3.0)              # jump mid C-phase
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "모션" in res.reason or "dPX" in res.reason
    assert drive.regs["MO"] == 0


# ======================================================================================
# B4 pre-alignment / ratchet / CA[19] scaling (2026-07-13 fix — live RED
# "모션 감지 |dPX|=2191>364": stiction snap AFTER the i1-only latch)
# ======================================================================================
# Sim geometry: CA[18]=524288, CA[19]=16 -> theta_abort=2913, half pitch=16384,
# pre-align relaxed tol = 1.5 pole pitch = 49152 counts.
SIM_CA18 = 524288.0
SIM_THETA_ABORT = max(4.0, SIM_CA18 * 2.0 / 360.0)          # 2912.7
SIM_PREALIGN_TOL = 1.5 * SIM_CA18 / 16.0                    # 49152.0


class StictionDrive(SimDrive):
    """Rotor with stiction (reassembly 'first run' hazard): holds at px0 until
    |TC| >= breakaway_a, then snaps to px0+snap_counts and stays (latched).
    breakaway sits BETWEEN i1 (5.30 A) and i2 (10.61 A) — the exact live
    failure mode: an i1-only alignment never breaks it; the first rise to i2
    does."""

    def __init__(self, breakaway_a=8.0, snap_counts=17500.0, **kw):
        SimDrive.__init__(self, **kw)
        self.breakaway_a = float(breakaway_a)
        self.snap_counts = float(snap_counts)
        self.snapped = False

    def px(self):
        return SimDrive.px(self) + (self.snap_counts if self.snapped else 0.0)

    def _write(self, name, v):
        out = SimDrive._write(self, name, v)
        if name == "TC" and abs(v) >= self.breakaway_a:
            self.snapped = True
        return out


class CreepDrive(SimDrive):
    """Non-convergent rotor: advances step_counts on EVERY rising crossing of
    the breakaway current — never settles.  The ratchet must hit its cycle
    cap and return an honest RED (never an infinite loop, never GREEN)."""

    def __init__(self, step_counts=5000.0, breakaway_a=8.0, **kw):
        SimDrive.__init__(self, **kw)
        self.step_counts = float(step_counts)
        self.breakaway_a = float(breakaway_a)
        self.offset = 0.0

    def px(self):
        return SimDrive.px(self) + self.offset

    def _write(self, name, v):
        prev = self.regs.get("TC", 0.0)
        out = SimDrive._write(self, name, v)
        if name == "TC" and abs(prev) < self.breakaway_a <= abs(v):
            self.offset += self.step_counts
        return out


def test_prealign_burns_stiction_snap_before_latch(tmp_path):
    """(a) Half-aligned start + stiction: the snap (17500 cnt > theta_abort)
    must be exhausted DURING pre-align (relaxed guard), the ratchet must
    converge, and the measurement window must see zero motion -> GREEN.
    Under the OLD i1-only alignment this exact drive REDs mid-measurement."""
    drive = StictionDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == GREEN, (res.reason, res.warnings)
    assert drive.snapped, "i2 pre-align must have broken the stiction"
    pa = res.evidence["prealign"]
    assert pa["theta_abort_counts"] == pytest.approx(SIM_THETA_ABORT)
    cycles = pa["cycles"]
    assert 2 <= len(cycles) <= 3
    assert cycles[0]["dpx"] == pytest.approx(17500.0), \
        "snap must land in cycle 0 (pre-latch), not in the measurement window"
    assert cycles[0]["dpx"] > pa["theta_abort_counts"]
    assert cycles[-1]["dpx"] <= pa["theta_abort_counts"]   # converged
    # per-step (TC, PX) waveform captured as evidence for the live delta0 run
    tr = cycles[0]["trace_tc_px"]
    assert tr and any(isinstance(px, float) and px > 10000 for _tc, px in tr)


def test_prealign_relaxed_guard_still_reds_on_excess_motion(tmp_path):
    """(b) The relaxed pre-align guard allows a LEGIT snap (<=1.5 pole pitch,
    test above) but must still abort on motion beyond it (60000 > 49152)."""
    drive = StictionDrive(snap_counts=60000.0)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "dPX" in res.reason or "모션" in res.reason or "미수렴" in res.reason
    assert drive.regs["MO"] == 0 and drive.regs["UM"] == 5   # abort chain ran


def test_prealign_ratchet_nonconvergence_honest_red(tmp_path):
    """(c) A rotor that keeps moving on every i2 application: the ratchet must
    stop at its cycle cap with an honest RED '정렬 미수렴' (no infinite loop,
    no silent GREEN), drive safed and restored."""
    drive = CreepDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "미수렴" in res.reason
    pa = res.evidence["prealign"]
    assert len(pa["cycles"]) == 3                            # PREALIGN_CYCLES_MAX
    assert all(c["dpx"] > pa["theta_abort_counts"] for c in pa["cycles"])
    assert drive.regs["MO"] == 0 and drive.regs["UM"] == 5


def test_prealign_nominal_single_cycle(green_run):
    """Nominal (already-aligned) rotor: exactly one ratchet cycle, dpx within
    the strict gate, (TC, PX) trace present.  (ALIGN progress emission order
    is asserted in test_progress_fn_emits_all_phases_in_order.)"""
    _, _, res = green_run
    pa = res.evidence["prealign"]
    assert len(pa["cycles"]) == 1
    assert pa["cycles"][0]["dpx"] <= pa["theta_abort_counts"]
    assert pa["cycles"][0]["trace_tc_px"]


def test_align_tolerances_scale_with_ca19(tmp_path):
    """(d) The old hardcoded 11.25 deg (=180/16) is retired: all alignment
    tolerances must derive from CA[19].  p=21 vs p=16 give different, correct
    values; theta_abort (measurement gate) is pole-count independent."""
    tols = {}
    for pp in (16, 21):
        drive = SimDrive()
        drive.regs["CA[19]"] = pp
        res = run_current_autotune(drive, _params(drive, tmp_path / str(pp)))
        assert res.status == GREEN, (pp, res.reason, res.warnings)
        pa = res.evidence["prealign"]
        assert pa["pole_pairs"] == pp
        assert pa["half_pitch_counts"] == pytest.approx(SIM_CA18 / (2 * pp))
        assert pa["align_tol_counts"] == pytest.approx(SIM_CA18 / (2 * pp) * 1.2)
        assert pa["prealign_tol_counts"] == pytest.approx(1.5 * SIM_CA18 / pp)
        assert pa["theta_abort_counts"] == pytest.approx(SIM_THETA_ABORT)
        tols[pp] = pa["align_tol_counts"]
    assert tols[21] < tols[16]
    # regression teeth: p=21 must NOT reproduce the legacy 11.25-deg number
    legacy = SIM_CA18 * 11.25 / 360.0 * 1.2
    assert tols[16] == pytest.approx(legacy)     # p=16: formula change neutral
    assert abs(tols[21] / legacy - 1.0) > 0.2


def test_ca19_unreadable_falls_back_with_warning(tmp_path):
    """CA[19]<=0: legacy 16-pole-pair assumption + explicit warning (YELLOW)."""
    drive = SimDrive()
    drive.regs["CA[19]"] = 0
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW
    assert any("CA[19]" in w for w in res.warnings)
    assert res.evidence["prealign"]["pole_pairs"] == 16.0


def test_abort_a3_err58_demoted_not_warning(tmp_path):
    """After a successful A1 (MO=0), the drive's expected 'Drive error 58:
    Servo must be on' on A3 TC=0 is an expected step — NOT a warning.  The
    fixed abort order A1 -> A2 -> A3 is unchanged (asserted elsewhere)."""
    drive = SimDrive(se_injects=False)              # deterministic abort path
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert not any("A3" in w for w in res.warnings), res.warnings
    steps = res.evidence["abort"]["steps_done"]
    assert any(s.startswith("A3") and "58" in s for s in steps), steps


def test_ca18_unreadable_fails_closed_before_any_write(tmp_path):
    """CA[18]<=0 cannot establish a finite motion/position safety bound."""
    drive = SimDrive()
    drive.regs["CA[18]"] = 0
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "CA[18]" in res.reason
    assert not any("=" in command for command, _allow_motion in drive.log)


def test_prealign_unparseable_px_is_not_convergence(tmp_path):
    """[hardening LOW] PX parsing to a non-number: dpx=None must NOT count as
    convergence (absence of evidence != evidence of standstill) — the ratchet
    runs to its cap and returns an honest RED, drive safed and restored."""
    class NoPxDrive(SimDrive):
        def _query(self, name):
            if name == "PX":
                return "n/a"
            return SimDrive._query(self, name)

    drive = NoPxDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "미수렴" in res.reason and "판독불가" in res.reason
    assert len(res.evidence["prealign"]["cycles"]) == 3
    assert all(c["dpx"] is None for c in res.evidence["prealign"]["cycles"])
    assert drive.regs["MO"] == 0 and drive.regs["UM"] == 5


def test_prealign_reversible_excursion_visible_yellow_not_red(tmp_path):
    """[hardening LOW] Reversible intra-cycle deflection (gearbox compliance):
    cycle-end dpx~0 converges, but dev_max>theta_abort must surface as a
    WARNING (YELLOW) — visible, never a hard fail (no false RED on compliant
    gears) — and R/L stay valid."""
    class ElasticDrive(SimDrive):
        """Deflects +5000 cnt while TC>=8 A on the FIRST wind-up only (the
        spring releases on the way back down), then behaves rigid."""
        def __init__(self, **kw):
            SimDrive.__init__(self, **kw)
            self.offset = 0.0
            self.released = False

        def px(self):
            return SimDrive.px(self) + self.offset

        def _write(self, name, v):
            out = SimDrive._write(self, name, v)
            if name == "TC" and not self.released:
                if abs(v) >= 8.0:
                    self.offset = 5000.0
                elif self.offset:
                    self.offset = 0.0
                    self.released = True
            return out

    drive = ElasticDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW, (res.status, res.reason, res.warnings)
    assert any("가역 변위" in w for w in res.warnings)
    pa = res.evidence["prealign"]
    assert len(pa["cycles"]) == 1                       # converged first cycle
    c0 = pa["cycles"][0]
    assert c0["dpx"] <= pa["theta_abort_counts"]
    assert c0["max_dev_counts"] == pytest.approx(5000.0)
    assert abs(res.r_pp_ohm / R_TERM_PP - 1.0) <= 0.01
    assert abs(res.l_pp_h / L_PP_ORACLE - 1.0) <= 0.03


def test_nan_response_aborts(tmp_path):
    drive = SimDrive()
    drive.regs["BV"] = float("nan")
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "NaN" in res.reason


def test_stability_gate_red_on_absurd_override(tmp_path):
    """wc_override 4 kHz -> wc*TS>0.25 even after 3 reductions -> honest RED,
    with measured R/L still reported and the drive safed+restored first."""
    drive = SimDrive()
    params = _params(drive, tmp_path, wc_override_hz=4000.0)
    res = run_current_autotune(drive, params)
    assert res.status == RED and "게이트" in res.reason
    assert res.r_pp_ohm is not None and res.l_pp_h is not None
    assert drive.regs["MO"] == 0 and drive.regs["UM"] == 5


# ======================================================================================
# T4 + pure-function units
# ======================================================================================
def test_t4_gate_model_regression_point():
    """Pure-math regression of loop_margins at the prototype-verified point
    (0 dB @ 767 Hz, PM = 57.3 deg).  The point's ORIGINAL physical label
    ('EAS @ TS=50us, ph basis') was superseded by the pp/TS=100us re-grounding;
    the numbers stay valid as a function regression."""
    wx, pm = loop_margins(KP_ORACLE, 812.939, R_PH_TRUTH, L_PH_TRUTH, 50e-6)
    assert abs(pm - 57.3) <= 1.0, "PM=%.2f" % pm
    assert abs(wx / (2 * math.pi) - 767.0) <= 10.0, "fx=%.1f Hz" % (wx / (2 * math.pi))


def test_design_gains_eas_ratio_deterministic():
    """pp basis (fable-physics, runs #5/#6): KP = wc*L_pp reproduces the live
    EAS KP at TS=100us; KI = 2*alpha*wc/2pi reproduces the live EAS KI."""
    ok, kp, ki, wc, pm, wx, iters = design_gains(
        L_PP_ORACLE, R_PP_ORACLE, TS_US * 1e-6, AutotuneParams())
    assert ok
    assert abs(kp / KP_ORACLE - 1.0) <= 0.005        # -0.018% at exact L_pp
    assert abs(ki / KI_ORACLE - 1.0) <= 0.005        # 2x pp factor (run #6)
    assert pm >= 45.0


def test_design_gains_pole_zero_rule():
    ok, kp, ki, *_ = design_gains(L_PP_ORACLE, R_PP_ORACLE, TS_US * 1e-6,
                                  AutotuneParams(ki_rule="pole_zero"))
    assert ok
    assert ki == pytest.approx(R_PP_ORACLE / (2 * math.pi * L_PP_ORACLE), rel=1e-6)
    assert ki == pytest.approx(530.5, rel=0.01)      # same ratio on either basis


def test_demod_amplitude_exact():
    f, dt, amp, n = 800.0, 50e-6, 2.5, 4000          # integer cycles
    t = np.arange(n) * dt
    x = amp * np.sin(2 * np.pi * f * t + 0.7) + 1.23  # +DC offset must not leak
    assert abs(demod(x, f, dt)) == pytest.approx(amp, rel=1e-6)


def test_record_path_uses_net_wrapper_not_legacy(green_run):
    """Recorder access must go through link.record() (.NET wrapper); the retired
    RC/RG/RL/RP/RR=2/BH command path must never be emitted (SimDrive raises on
    RR=2/BH, so any regression would also RED the pipeline)."""
    drive, _, res = green_run
    assert res.status == GREEN
    assert drive.record_calls >= 7          # probe + 2 DC + 4 sine segments
    legacy = [c for c, _ in drive.log
              if c.replace(" ", "").upper().startswith(("RC=", "RG=", "RL=",
                                                        "RP[", "BH", "RR=2"))]
    assert legacy == [], "legacy recorder commands emitted: %s" % legacy
    assert not hasattr(at, "_parse_bh"), "_parse_bh must be retired"


def test_record_missing_dt_falls_back_with_warning(tmp_path):
    """dt semantics are live-unknown (U3): when record() reports no dt, the
    pipeline must fall back to TimeResolution*TS, warn once, and still measure
    correctly (in the sim the fallback equals the true dt)."""
    class NoDtDrive(SimDrive):
        def record(self, signals, length, time_resolution=1):
            out = SimDrive.record(self, signals, length, time_resolution)
            del out["dt"]
            return out

    drive = NoDtDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW
    assert sum("dt" in w for w in res.warnings) == 1
    assert abs(res.r_pp_ohm / R_TERM_PP - 1.0) <= 0.01
    assert abs(res.l_pp_h / L_PP_ORACLE - 1.0) <= 0.03


def test_signal_mapping_precision(green_run):
    """Live-grounded mapping: legs A/B/C (duty counts), D idle excluded,
    'Active Current [A]' (never Reactive), 'Current Command [A]' over Total,
    'DC Bus Voltage' as the scale cross-check channel."""
    _, _, res = green_run
    sm = res.evidence["signal_map"]
    assert sm["legs"] == ["A Voltage", "B Voltage", "C Voltage"]
    assert sm["bus"] == "DC Bus Voltage"
    assert sm["current_name"] == "Active Current [A]"
    assert sm["ref_name"] == "Current Command [A]"


def test_neutral_subtraction_removes_offset_cm_and_bias():
    """v_phN = A - (A+B+C)/3 must remove the 3750 offset, the SVM min-max
    common mode, and the 3/4 single-leg bias EXACTLY (pure function)."""
    rng = np.random.default_rng(7)
    vph_true = rng.uniform(-2.0, 2.0, 64)            # phase-neutral volts
    kv = at.DUTY_FS / VBUS_TRUTH
    legs = []
    for v in vph_true:
        ph = (v, -v / 2.0, -v / 2.0)
        cm = -(max(ph) + min(ph)) / 2.0
        legs.append([at.DUTY_MID + (p + cm) * kv for p in ph])
    legs = np.array(legs)
    # single raw leg (mid-removed) equals 3/4 of the phase voltage — the bias
    raw_leg = (legs[:, 0] - at.DUTY_MID) / kv
    assert np.allclose(raw_leg, 0.75 * vph_true)
    v_rec = at.neutral_subtract(legs[:, 0], legs[:, 1], legs[:, 2]) / kv
    assert np.allclose(v_rec, vph_true, atol=1e-12)


def test_skew_rotation_correction_recovers_l(green_run):
    """Run #6 core fix: the recorded duty leads the motor voltage by 1.5*TS.
    The rotation correction exp(-j*w*1.5*TS) must recover L (<=3% each f);
    WITHOUT it the apparent L stays badly inflated (>+10%, +26..59% here).
    R_ac(f)=Re(Z) must sit in the physical G2 band around the DC value."""
    _, _, res = green_run
    r_pp = res.evidence["dc"]["r_pp_ohm"]
    for e in res.evidence["sine"]:
        assert abs(e["l_pp_h"] / L_PP_ORACLE - 1.0) <= 0.03, \
            "f=%.0f corrected L err %+.1f%%" % (
                e["f_hz"], 100 * (e["l_pp_h"] / L_PP_ORACLE - 1))
        assert e["l_pp_uncorrected_h"] / L_PP_ORACLE - 1.0 > 0.10, \
            "f=%.0f uncorrected L should stay skew-inflated" % e["f_hz"]
        assert 0.8 * r_pp <= e["r_ac_pp_ohm"] <= 2.5 * r_pp


def test_vbus_primary_scale_exact(green_run):
    """PRIMARY scale = Vbus_rec/7500 (run #6); tau and Vbus land in evidence."""
    _, _, res = green_run
    sc = res.evidence["scale"]
    assert sc["vbus_v"] == pytest.approx(VBUS_TRUTH, rel=1e-6)
    assert sc["s_v_per_count"] == pytest.approx(VBUS_TRUTH / at.DUTY_FS, rel=1e-9)
    assert sc["tau_skew_s"] == pytest.approx(1.5 * TS_US * 1e-6, rel=1e-9)


def test_g0_platform_fs_computed_not_hardcoded(tmp_path):
    """G0: FS = 150e6*TS/XP[2] (document-confirmed).  XP[2]=3 mock -> FS=5000,
    scale s=Vbus/5000, and the measurement still recovers R/L -> GREEN."""
    drive = SimDrive(xp2=3)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == GREEN, "%s / %s" % (res.reason, res.warnings)
    g0 = res.evidence["gates"]["G0_platform"]
    assert g0["pass"] and g0["fs_counts"] == pytest.approx(5000.0)
    assert res.evidence["scale"]["fs_counts"] == pytest.approx(5000.0)
    assert res.evidence["scale"]["s_v_per_count"] == \
        pytest.approx(VBUS_TRUTH / 5000.0, rel=1e-9)
    assert abs(res.r_pp_ohm / R_TERM_PP - 1.0) <= 0.01
    assert abs(res.l_pp_h / L_PP_ORACLE - 1.0) <= 0.03


def test_g0_invalid_xp2_falls_back_yellow(tmp_path):
    """XP[2] unreadable -> provisional FS with default 2 + G0 fail -> YELLOW
    (measurement still correct because the physical XP[2] IS 2)."""
    drive = SimDrive()
    drive.regs["XP[2]"] = 0
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW
    assert not res.evidence["gates"]["G0_platform"]["pass"]
    assert any("XP[2]" in w for w in res.warnings)
    assert abs(res.l_pp_h / L_PP_ORACLE - 1.0) <= 0.03    # fallback FS correct here


def test_g1p_idle_leg_and_vbus(green_run):
    """G1': idle leg 'D Voltage' mean == FS/2 +-1 count, Vbus in [20,60] V."""
    _, _, res = green_run
    g1p = res.evidence["gates"]["G1p_idle_vbus"]
    assert g1p["pass"]
    assert abs(g1p["idle_leg_mean"] - g1p["expected_mid"]) <= 1.0
    assert 20.0 <= g1p["vbus_v"] <= 60.0


def test_g1p_fails_on_idle_leg_offset(tmp_path):
    """G1' teeth: idle leg off the midpoint (counter/config anomaly) -> YELLOW."""
    class BadIdleDrive(SimDrive):
        def _chan_value(self, name):
            if name == "D Voltage":
                return self.duty_mid - 5.0
            return SimDrive._chan_value(self, name)

    drive = BadIdleDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW
    assert not res.evidence["gates"]["G1p_idle_vbus"]["pass"]
    assert any("G1p" in w for w in res.warnings)


def test_g1p_fails_on_vbus_out_of_range(tmp_path):
    """G1' teeth: bus voltage outside [20,60] V -> YELLOW (gross bus anomaly)."""
    drive = SimDrive(vbus=70.0)                     # physics consistent at 70 V
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW
    assert not res.evidence["gates"]["G1p_idle_vbus"]["pass"]


def test_g5_loopgain_consistency_and_honest_label(green_run):
    """G5 (repurposed in-situ): rho_meas(f) must track the OPEN-LOOP GAIN
    |C|/|R+jwL| within +-15% (run #8: 2.6~4.1%), with the measured gain
    crossover reported (~372-390 Hz class).  Honest label: G5 does NOT verify
    s (it cancels on both sides) — s is owned by G0+G1'.  Also documents that
    the old G1-style SCALE interpretation of the same ratio is invalid."""
    _, _, res = green_run
    g5 = res.evidence["gates"]["G5_loopgain"]
    assert g5["pass"] and g5["tol"] == 0.15
    assert len(g5["rows"]) == len(res.evidence["sine"])
    for row in g5["rows"]:
        assert abs(row["dev"]) <= 0.15, row
    assert 250.0 <= g5["crossover_hz"] <= 500.0     # live: ~371 Hz measured
    # predicted crossover = numeric solve of |C(jw)G(jw)|=1 (asymptote retired)
    assert 250.0 <= g5["crossover_pred_hz"] <= 500.0
    assert abs(g5["crossover_hz"] / g5["crossover_pred_hz"] - 1.0) <= 0.08
    # uniform residual is RECORDED (never compensated)
    assert "mean_dev" in g5 and "보상 금지" in g5["residual_note"]
    assert "s 자체는 검증 안 함" in g5["note"] and "G0+G1'" in g5["note"]
    # the ratio interpreted as a SCALE check (old G1) would be nonsense:
    s = res.evidence["scale"]["s_v_per_count"]
    scale_style = [e["s_insitu_mag_v_per_count"] / s
                   for e in res.evidence["sine"]]
    assert any(abs(v - 1.0) > 0.10 for v in scale_style), \
        "G1-style scale gate should be unfit (loop gain, not scale): %s" % scale_style


def test_g5_run9_regression_fixture():
    """Run-9 correction fixture (fable-physics): the STORED live rho_meas
    (=s_insitu/s, outer x2 removed) against rho_pred with the CONTINUOUS C and
    the SAME reported R-hat=0.1502 / L-hat=41.29uH must land FLAT at
    (0.975, 0.965, 0.961, 0.965) — PASS with ~4x margin under +-15%.  The
    predicted numeric crossover is ~361 Hz (measured ~371)."""
    KP, KI, R, L = 0.07177, 812.94, 0.1502, 41.29e-6
    stored = {200.0: 1.843, 400.0: 0.859, 600.0: 0.537, 800.0: 0.386}
    expect = {200.0: 0.975, 400.0: 0.965, 600.0: 0.961, 800.0: 0.965}
    for f, rho_meas in stored.items():
        w = 2 * math.pi * f
        rho_pred = abs(at.pi_continuous(f, KP, KI)) / abs(complex(R, w * L))
        ratio = rho_meas / rho_pred
        assert ratio == pytest.approx(expect[f], abs=0.005), (f, ratio)
        assert abs(ratio - 1.0) <= 0.15
    fx = at.loopgain_crossover_hz(KP, KI, R, L)
    assert fx == pytest.approx(361.0, abs=8.0)


def test_g5_bug_teeth_both_directions(green_run):
    """Both run-9 bug classes stay detectable:
    (a) reintroducing the outer x2 on rho_meas -> gate FAILS at every f;
    (b) rho_pred consuming a different L than the reported one (ph/pp mixup,
    L-hat/2) -> gate FAILS at high f."""
    _, _, res = green_run
    g5 = res.evidence["gates"]["G5_loopgain"]
    assert all(abs(2.0 * r["rho_meas"] / r["rho_pred"] - 1.0) > 0.15
               for r in g5["rows"]), "outer x2 must be caught"
    r_pp, l_pp = res.r_pp_ohm, res.l_pp_h            # the REPORTED values
    devs_wrong_l = []
    for r in g5["rows"]:
        w = 2 * math.pi * r["f_hz"]
        pred_wrong = (abs(at.pi_continuous(r["f_hz"], KP_ORACLE, 812.939))
                      / abs(complex(r_pp, w * l_pp / 2.0)))
        devs_wrong_l.append(abs(r["rho_meas"] / pred_wrong - 1.0))
    assert max(devs_wrong_l) > 0.15, devs_wrong_l


def test_g5_reproducibility_rho_equals_insitu_over_s(green_run):
    """Run-8/9 reproducibility: rho_meas is EXACTLY the stored s_insitu/s
    (no hidden factors)."""
    _, _, res = green_run
    s = res.evidence["scale"]["s_v_per_count"]
    by_f = {e["f_hz"]: e for e in res.evidence["sine"]}
    for r in res.evidence["gates"]["G5_loopgain"]["rows"]:
        assert r["rho_meas"] == pytest.approx(
            by_f[r["f_hz"]]["s_insitu_mag_v_per_count"] / s, rel=1e-12)


def test_b3_selfcheck_ripple_peak_poll_passes(tmp_path):
    """Run #10: a single IQ poll landing on a RIPPLE PEAK (+5.2% vs the window
    mean — beyond the old hard 5% limit) must NOT warn: it lies inside the
    recorded [min,max] ripple band.  Full run stays GREEN.  Also confirms the
    mock ripple is real (probe std ~3-4.5% of the level, live 3.9%)."""
    class PeakPollDrive(SimDrive):
        def _query(self, name):
            if name == "IQ":
                return "%.6f" % (self.i * 1.052)     # poll on ripple peak
            return SimDrive._query(self, name)

    drive = PeakPollDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == GREEN, (res.reason, res.warnings)
    assert not any("폴링IQ" in w for w in res.warnings)
    probe = res.evidence["probe"]
    assert 0.025 <= probe["std"] / probe["ref"] <= 0.05   # ripple visible, <5% gate


def test_b3_selfcheck_true_scale_error_still_caught(tmp_path):
    """Teeth (other direction): a REAL current-scale error (poll = 1.2x the
    window mean — outside the ripple band AND outside max(5%, 3*std)) must
    still raise the self-check warning -> YELLOW."""
    class ScalePollDrive(SimDrive):
        def _query(self, name):
            if name == "IQ":
                return "%.6f" % (self.i * 1.2)
            return SimDrive._query(self, name)

    drive = ScalePollDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW
    assert any("폴링IQ" in w for w in res.warnings)
    # gates themselves still pass — the YELLOW comes from the self-check only
    assert all(g["pass"] for g in res.evidence["gates"].values())


def test_r_nameplate_band_advisory_never_blocks_green(tmp_path):
    """R nameplate band = ADVISORY only.  In-band (motor 0.119 + ~23 mOhm
    parasitic) records in_band=True; an out-of-band case still stays GREEN."""
    d1 = SimDrive()
    r1 = run_current_autotune(d1, _params(d1, tmp_path / "a",
                                          nameplate_r_pp=R_PP_ORACLE))
    adv = r1.evidence["dc"]["r_band_advisory"]
    assert r1.status == GREEN and adv["in_band"]
    assert adv["excess_ohm"] == pytest.approx(R_TERM_PP - R_PP_ORACLE, abs=2e-3)
    # nameplate set so the measured excess (~2 mOhm) falls BELOW the +5 mOhm
    # band floor -> advisory out-of-band, but GREEN must NOT be blocked
    d2 = SimDrive()
    r2 = run_current_autotune(d2, _params(d2, tmp_path / "b",
                                          nameplate_r_pp=0.140))
    adv2 = r2.evidence["dc"]["r_band_advisory"]
    assert not adv2["in_band"]
    assert r2.status == GREEN, "advisory must never block GREEN: %s" % r2.warnings


def test_read_platform_clock_helper():
    """elmo_link.read_platform_clock(): read-only XP[2]/WS[53..57] + FS math
    (duck-typed against the SimDrive transport — no hardware)."""
    import elmo_link
    out = elmo_link.ElmoLink.read_platform_clock(SimDrive())
    assert out["xp2"] == 2 and out["ts_us"] == TS_US
    assert out["fs_counts"] == pytest.approx(7500.0)
    assert out["ws57"] is not None and out["ws57"] < out["fs_counts"]


def test_missing_bus_signal_is_red(tmp_path):
    """DC Bus Voltage is the PRIMARY scale source now: absent -> pre-power RED."""
    drive = SimDrive()
    drive.signals.remove("DC Bus Voltage")
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "Bus" in res.reason or "주 스케일" in res.reason
    assert all("=" not in c for c, _ in drive.log), "must stay read-only"


# ======================================================================================
# personality upload ladder (elmo_link) — headless via fake .NET comm objects
# ======================================================================================
class _FakeEvent:
    def __iadd__(self, _h):
        return self


class _FakeErr:
    def __init__(self, lib_ec, lib_desc):
        self.ErrorCode = 0
        self.LibraryErrorCode = lib_ec
        self.ErrorDescription = ""
        self.LibraryErrorDescription = lib_desc


class _FakeUploadModel:
    def __init__(self, path, ok):
        self._path, self._ok = path, ok
        self.OnStart = _FakeEvent()
        self.OnProgress = _FakeEvent()
        self.OnFinish = _FakeEvent()
        self.OnFailed = _FakeEvent()
        self.OnCancel = _FakeEvent()
        self.OperationStatus = "UNDEFINED"

    def Start(self):
        if not self._ok:
            self.OperationStatus = "FAILED"
            return (False, _FakeErr(9, "No Callbacks Registered"))
        with open(self._path, "w", encoding="utf-8") as f:
            f.write("<personality/>")
        self.OperationStatus = "FINISHED"
        return (True, None)


class _FakeKV:
    def __init__(self, k, v):
        self.Key, self.Value = k, v


class _FakeSig:
    def __init__(self, i, name):
        self.SignalIndex = i
        self.Name = name
        self.CategoryName = "Cat"
        self.Classification = "Cls"


class _FakeMeta(list):
    @property
    def Count(self):
        return len(self)


class _FakeComm:
    """Pure-python stand-in for the .NET comm exposing the live-confirmed
    personality surface (UploadPersonality / CreatePersonalityModel /
    PersonalityModel)."""
    def __init__(self, upload_ok=True):
        self.PersonalityModel = None
        self.upload_calls = 0
        self._upload_ok = upload_ok

    def SendCommandAnalyzeError(self, command, _response, _error, _timeout):
        values = {
            "VR": "Twitter 01.01.16.00 08Mar2020B01G",
            "VP": "90",
            "SN[4]": "TEST-DRIVE-001",
        }
        return (True, values[command], None)

    def UploadPersonality(self, path):
        self.upload_calls += 1
        return (_FakeUploadModel(path, self._upload_ok), None)

    def CreatePersonalityModel(self, path):
        if not os.path.isfile(path):
            return (False, _FakeErr(8, "Cannot parse personality file"))
        meta = _FakeMeta(_FakeKV(i, _FakeSig(i, n)) for i, n in enumerate(
            ["A Voltage", "Active Current [A]", "Current Command [A]"]))

        class _Model:
            pass
        m = _Model()
        m.SignalsMetaData = meta
        self.PersonalityModel = m
        return (True, None)


def _fresh_link(tmp_path, monkeypatch, upload_ok=True):
    import elmo_link
    monkeypatch.setattr(elmo_link, "_LIBDIR", str(tmp_path / "lib"))
    monkeypatch.setattr(elmo_link, "_STATE_DIR", str(tmp_path / "state"))
    link = elmo_link.ElmoLink()
    link._comm = _FakeComm(upload_ok=upload_ok)
    return elmo_link, link


def test_personality_ladder_upload_then_parse(tmp_path, monkeypatch):
    """Cache miss -> UploadPersonality(+5 events)+Start+FINISHED -> parse ->
    signal names + durability dump written (live-confirmed flow, headless)."""
    import json
    _el, link = _fresh_link(tmp_path, monkeypatch)
    names = link.recorder_signals()
    assert names == ["A Voltage", "Active Current [A]", "Current Command [A]"]
    assert link._comm.upload_calls == 1
    assert (tmp_path / "lib" / "personality_model.xml").is_file()   # cached XML
    dump = tmp_path / "state" / "recorder_signals.json"
    assert dump.is_file()
    data = json.loads(dump.read_text(encoding="utf-8"))
    assert data["count"] == 3
    assert data["signals"][1]["name"] == "Active Current [A]"
    assert {"index", "signal_index", "name", "category",
            "classification"} <= set(data["signals"][0])


def test_personality_cache_first_skips_upload(tmp_path, monkeypatch):
    """Existing XML -> CreatePersonalityModel parses the cache; NO re-upload."""
    _el, link = _fresh_link(tmp_path, monkeypatch)
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
    (tmp_path / "lib" / "personality_model.xml").write_text(
        "<ROOT><version>Twitter 01.01.16.00 08Mar2020B01G Pal: 90</version></ROOT>",
        encoding="utf-8")
    names = link.recorder_signals()
    assert names is not None and len(names) == 3
    assert link._comm.upload_calls == 0
    assert link.recorder_personality_provenance()[
        "firmware_personality_match"] is True


def test_personality_cache_requires_nonempty_exact_firmware_match(
        tmp_path, monkeypatch):
    _el, link = _fresh_link(tmp_path, monkeypatch)
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "lib" / "personality_model.xml"
    path.write_text(
        "<ROOT><version>Twitter 01.01.16.00 08Mar2020B01G Pal: 90</version></ROOT>",
        encoding="utf-8")

    link.command = lambda command: "" if command == "VR" else "90"
    assert link._personality_cache_matches_drive(str(path))[0] is False

    link.command = lambda command: (
        "Twitter 01.01.16.00" if command == "VR" else "90")
    assert link._personality_cache_matches_drive(str(path))[0] is False


def test_prepopulated_communication_model_does_not_claim_firmware_match(
        tmp_path, monkeypatch):
    _el, link = _fresh_link(tmp_path, monkeypatch)
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "lib" / "prepopulated.xml"
    path.write_text("<personality/>", encoding="utf-8")
    ok, _err = link._comm.CreatePersonalityModel(str(path))
    assert ok

    assert link.recorder_signals() is not None
    provenance = link.recorder_personality_provenance()
    assert provenance["source"] == "connected_communication_model"
    assert provenance["firmware_personality_match"] is False


def test_personality_cache_identity_mismatch_forces_current_drive_upload(
        tmp_path, monkeypatch):
    _el, link = _fresh_link(tmp_path, monkeypatch)
    (tmp_path / "lib").mkdir(parents=True, exist_ok=True)
    (tmp_path / "lib" / "personality_model.xml").write_text(
        "<ROOT><version>Trombone 01.01.09.10 Pal: 48</version></ROOT>",
        encoding="utf-8")
    names = link.recorder_signals()
    assert names is not None and len(names) == 3
    assert link._comm.upload_calls == 1


def test_personality_failure_returns_none_with_reason(tmp_path, monkeypatch):
    """Upload Start failure -> recorder_signals()==None + _last_recorder_error
    carries the drive's LibraryErrorDescription (LibEC=9 pattern)."""
    _el, link = _fresh_link(tmp_path, monkeypatch, upload_ok=False)
    assert link.recorder_signals() is None
    assert "No Callbacks Registered" in (link._last_recorder_error or "")
    assert "LibraryErrorCode=9" in link._last_recorder_error


def test_upload_data_positional_mapping_regression():
    """Live run #4 bug class: UploadRecordingData().Data keys are POSITIONAL
    0..N-1 in request order (NOT SignalIndex).  The remap must unpack
    positionally and fail LOUDLY on any unexpected key set."""
    import elmo_link
    sigs = ["A Voltage", "Active Current [A]", "Current Command [A]"]
    raw = {0: np.array([1.0, 1.5]), 1: np.array([2.0, 2.5]), 2: np.array([3.0, 3.5])}
    out = elmo_link._map_upload_data(sigs, raw)
    assert out["A Voltage"][0] == 1.0
    assert out["Active Current [A]"][1] == 2.5
    assert out["Current Command [A]"][0] == 3.0
    # SignalIndex-style keys (the exact live failure: 'A Voltage'=19) -> IOError
    with pytest.raises(IOError):
        elmo_link._map_upload_data(sigs, {19: raw[0], 20: raw[1], 21: raw[2]})
    with pytest.raises(IOError):                     # missing a channel
        elmo_link._map_upload_data(sigs, {0: raw[0], 1: raw[1]})
    with pytest.raises(IOError):                     # extra unexpected channel
        elmo_link._map_upload_data(sigs, {0: raw[0], 1: raw[1], 2: raw[2],
                                          3: raw[0]})


def test_dotnet_recorder_structural_offline():
    """Offline structural check of the real .NET recording surface used by
    elmo_link.record(): types constructible, Immediate enum, interface members.
    Skips (honestly) when pythonnet/CLR is unavailable on the machine."""
    try:
        import elmo_link
        checks = elmo_link._reflect_recorder()
    except Exception as e:
        pytest.skip("CLR/DLL unavailable offline: %r" % (e,))
    bad = [k for k, v in checks.items() if not v]
    assert not bad, "structural checks failed: %s" % bad
    assert len(checks) >= 10


def test_l_from_z_roundtrip():
    f = 800.0
    z = math.hypot(R_PH_TRUTH, 2 * math.pi * f * L_PH_TRUTH)
    assert at.l_from_z(z, R_PH_TRUTH, f) == pytest.approx(L_PH_TRUTH, rel=1e-9)


# ======================================================================================
# TS-derived excitation frequencies (live TS=100us regression, 2026-07-12 field RED)
# ======================================================================================
def test_derive_freqs_values():
    """Run #6: 3-4 excitation points (firmer L median; future (L,tau) fit)."""
    assert at.derive_freqs(50e-6) == (400.0, 800.0, 1200.0, 1600.0)
    assert at.derive_freqs(100e-6) == (200.0, 400.0, 600.0, 800.0)   # live drive
    for ts_us in (40, 100, 120):
        fs = at.derive_freqs(ts_us * 1e-6)
        assert 3 <= len(fs) <= 4
        f_max = 0.125 / (ts_us * 1e-6)
        assert all(150.0 <= f < f_max for f in fs)
        assert list(fs) == sorted(fs) and len(set(fs)) == len(fs)
    # L-observability: hugely resistive motor -> all candidates dropped ->
    # top two grid points below f_max (contract: push toward f_max)
    assert at.derive_freqs(100e-6, r_ph=0.5, l_ph=17.85e-6) == (1150.0, 1200.0)
    # THIS motor (terminal R, pp L): all four points stay observable
    assert at.derive_freqs(100e-6, r_ph=R_TERM_PP, l_ph=L_PP_ORACLE) == \
        (200.0, 400.0, 600.0, 800.0)
    assert 2 * math.pi * 200.0 * L_PP_ORACLE >= 0.25 * R_TERM_PP


def test_ts100_default_freqs_full_pipeline(tmp_path):
    """Live-RED regression: TS=100us drive + DEFAULT params (freqs None) must
    pass P2, derive (400, 800) < 1250 Hz, and still recover R/L."""
    drive = SimDrive(ts_us=100)
    res = run_current_autotune(drive, _params(drive, tmp_path))
    assert res.status == GREEN, "%s / %s / %s" % (res.status, res.reason,
                                                  res.warnings)
    fr = res.evidence["freqs"]
    assert fr["mode"] == "derived"
    assert fr["freqs_hz"] == [200.0, 400.0, 600.0, 800.0]
    assert all(f < 1250.0 for f in fr["freqs_hz"])
    assert res.ts_us == 100
    r_err = res.r_pp_ohm / R_TERM_PP - 1.0
    l_err = res.l_pp_h / L_PP_ORACLE - 1.0
    assert abs(r_err) <= 0.01, "R err %+.2f%%" % (100 * r_err)
    assert abs(l_err) <= 0.03, "L err %+.2f%%" % (100 * l_err)


def test_ts100_explicit_over_limit_keeps_strict_red(tmp_path):
    """Explicit tuple keeps the old strict P2 gate (the honest live RED path)."""
    drive = SimDrive(ts_us=100)
    res = run_current_autotune(drive,
                               _params(drive, tmp_path, freqs_hz=(800.0, 1600.0)))
    assert res.status == RED
    assert "1600" in res.reason and "한계" in res.reason
    assert all("=" not in c for c, _ in drive.log), "P2 RED must stay read-only"


@pytest.mark.parametrize("bootstrap", [False, True])
def test_no_free_feedback_socket_is_read_only_preflight_red(
        tmp_path, bootstrap):
    drive = SimDrive(
        kp=0.0 if bootstrap else KP_ORACLE,
        ki=0.0 if bootstrap else KI_ORACLE)
    drive.regs.update({
        "CA[45]": 2, "CA[46]": 3, "CA[47]": 4,
        "SC[8]": 7,
    })
    original = dict(drive.regs)
    kwargs = {}
    if bootstrap:
        kwargs.update(
            nameplate_r_pp=R_PP_ORACLE,
            nameplate_l_pp_h=L_PP_ORACLE)

    res = run_current_autotune(
        drive, _params(drive, tmp_path, **kwargs))

    assignments = [command for command, _ in drive.log if "=" in command]
    assert res.status == RED and "소켓" in res.reason
    assert assignments == []
    assert not any(command.replace(" ", "").upper() == "MO=1"
                   for command, _ in drive.log)
    assert drive.regs == original


def test_dirty_preflight_error_runs_verified_snapshot_restore(
        tmp_path, monkeypatch):
    drive = SimDrive()
    original_um = drive.regs["UM"]

    def dirty_preflight(ctx):
        ctx.snapshot = {"UM": original_um}
        at._write(ctx, "UM", 3)
        raise at.PreflightError("synthetic late admission failure")

    monkeypatch.setattr(at, "_pipeline", dirty_preflight)

    res = run_current_autotune(drive, _params(drive, tmp_path))

    assert res.status == RED
    assert drive.regs["UM"] == original_um
    assert res.evidence["configuration_restore"]["pass"] is True
    assert res.evidence["configuration_state"] == "RESTORED"


def test_normal_completion_restore_mismatch_is_red_configuration_unknown(
        tmp_path):
    class SilentUMRestoreMismatchDrive(SimDrive):
        def _write(self, name, value):
            if (name == "UM" and int(value) == 5
                    and self.regs.get("UM") == 3):
                return ""
            return super()._write(name, value)

    drive = SilentUMRestoreMismatchDrive()

    res = run_current_autotune(drive, _params(drive, tmp_path))

    assert res.status == RED
    assert res.evidence["configuration_restore"]["pass"] is False
    assert res.evidence["configuration_state"] == "UNKNOWN"
    assert "UNKNOWN" in res.reason


def test_p1_configuration_journal_precedes_first_write_and_resolves(tmp_path):
    drive = ConfigurationJournalSimDrive()

    res = run_current_autotune(drive, _params(drive, tmp_path))

    assert res.status == GREEN, res.reason
    prepare = next(event for event in drive.journal_events
                   if event[0] == "prepare")
    assert prepare[1]["phase"] == "P1_CONFIG"
    assert tuple(prepare[1]["registers"]) == at.P1_CONFIG_NAMES
    assert prepare[1]["initial_state"] == "RAM_APPLYING"
    assert set(prepare[1]["mutation_bounds"]) == {
        "KP[1]", "KI[1]", "SE[2]", "SE[3]", "TC"}
    assert prepare[1]["mutation_bounds"]["SE[2]"][0] == 0.0
    assert prepare[1]["mutation_bounds"]["TC"][1] == pytest.approx(
        drive.regs["CL[1]"] * 0.5)
    assert next(i for i, event in enumerate(drive.journal_events)
                if event[0] == "prepare") < next(
                    i for i, event in enumerate(drive.journal_events)
                    if event[0] == "command" and "=" in event[1])
    assert ("begin_rollback", drive.config_attempt_id) in drive.journal_events
    assert ("resolve", drive.config_attempt_id) in drive.journal_events
    assert not any(event[0] == "unknown" for event in drive.journal_events)
    assert drive.capability_rejections == []
    assert res.evidence["configuration_restore"]["pass"] is True
    assert res.evidence["configuration_state"] == "RESTORED"
    assert set(res.evidence["configuration_restore"]["journal"][
        "verified_original_readback"]) == set(at.P1_CONFIG_NAMES)


def test_p1_configuration_journal_prepare_failure_is_read_only(tmp_path):
    drive = ConfigurationJournalSimDrive(fail_prepare=True)

    res = run_current_autotune(drive, _params(drive, tmp_path))

    assert res.status == RED
    assert "journal" in res.reason.lower()
    assert [command for command, _ in drive.log if "=" in command] == []
    assert not any(command.replace(" ", "").upper() == "MO=1"
                   for command, _ in drive.log)


def test_p1_configuration_sub_ulp_original_is_read_only_red(tmp_path):
    class FractionalOriginalDrive(ConfigurationJournalSimDrive):
        def command(self, cmd, timeout_ms=1000, allow_motion=False,
                    _persistence_attempt_id=None):
            response = super().command(
                cmd, timeout_ms=timeout_ms, allow_motion=allow_motion,
                _persistence_attempt_id=_persistence_attempt_id)
            core = "".join(str(cmd).split()).upper().rstrip(";")
            if core == "KI[1]":
                return "812.9390000000000001"
            return response

    drive = FractionalOriginalDrive()

    res = run_current_autotune(drive, _params(drive, tmp_path))

    assert res.status == RED
    assert "snapshot is not exact" in res.reason
    assert not any(event[0] == "prepare" for event in drive.journal_events)
    assert [command for command, _ in drive.log if "=" in command] == []


def test_production_like_link_without_configuration_journal_is_read_only_red(
        tmp_path):
    class ProductionLikeNoJournalDrive(SimDrive):
        p1_config_durability_mode = None

    drive = ProductionLikeNoJournalDrive()

    res = run_current_autotune(drive, _params(drive, tmp_path))

    assert res.status == RED
    assert "journal API is required" in res.reason
    assert [command for command, _ in drive.log if "=" in command] == []
    assert not any(command.replace(" ", "").upper() == "MO=1"
                   for command, _ in drive.log)


def test_p1_configuration_journal_closeout_failure_is_unknown(tmp_path):
    drive = ConfigurationJournalSimDrive(fail_resolve=True)

    res = run_current_autotune(drive, _params(drive, tmp_path))

    assert res.status == RED
    assert res.evidence["configuration_state"] == "UNKNOWN"
    assert res.evidence["configuration_restore"]["pass"] is False
    assert any(event[0] == "unknown" for event in drive.journal_events)
    assert drive.config_unknown is True


def test_cancel_after_p1_configuration_prepare_closes_verified_original(
        tmp_path):
    drive = ConfigurationJournalSimDrive()

    def cancel_after_prepare():
        return drive.config_attempt_active

    res = run_current_autotune(
        drive, _params(drive, tmp_path, cancel_fn=cancel_after_prepare))

    assert res.status == RED
    assert not any(command.replace(" ", "").upper() == "MO=1"
                   for command, _ in drive.log)
    assert ("resolve", drive.config_attempt_id) in drive.journal_events
    assert not any(event[0] == "unknown" for event in drive.journal_events)
    assert res.evidence["configuration_state"] == "RESTORED"
    assert set(res.evidence["configuration_restore"]["readback"]) == \
        set(at.P1_CONFIG_NAMES)


# ======================================================================================
# GUI hooks: progress_fn / cancel_fn (non-invasive contract)
# ======================================================================================
PROGRESS_ORDER = ["P0", "VALIDATE", "SNAPSHOT", "ENABLE", "ALIGN",
                  "MEASURE_R", "MEASURE_L", "DESIGN", "DONE"]


def test_progress_fn_emits_all_phases_in_order(tmp_path):
    drive = SimDrive()
    events = []
    params = _params(drive, tmp_path,
                     progress_fn=lambda code, detail: events.append((code, detail)))
    res = run_current_autotune(drive, params)
    assert res.status == GREEN, res.reason
    codes = [c for c, _ in events]
    firsts = [codes.index(c) for c in PROGRESS_ORDER]   # each appears >= once
    assert firsts == sorted(firsts), "out of order: %s" % codes
    assert all(codes.count(c) >= 1 for c in PROGRESS_ORDER)
    details = dict(events)
    assert "mΩ" in details["MEASURE_R"]                 # human-readable payloads
    assert "µH" in details["MEASURE_L"]
    assert "KP" in details["DESIGN"] and "PM" in details["DESIGN"]


def test_cancel_fn_triggers_spec6_abort_and_restore(tmp_path):
    """Cancel armed right after ENABLE: the first _sleep chunk while energized
    must raise the operator-stop AbortError and run the fixed §6 chain."""
    drive = SimDrive()
    state = {"armed": False}

    def on_progress(code, _detail):
        if code == "ENABLE":
            state["armed"] = True

    params = _params(drive, tmp_path, progress_fn=on_progress,
                     cancel_fn=lambda: state["armed"])
    res = run_current_autotune(drive, params)
    assert res.status == RED and "중단" in res.reason
    cmds = [c.replace(" ", "") for c, _ in drive.log]
    i_mo = cmds.index("MO=0")                           # abort A1 (first MO=0 ever)
    i_tw = next(i for i, c in enumerate(cmds) if i > i_mo and c == "TW[80]=0")
    i_tc = next(i for i, c in enumerate(cmds) if i > i_tw and c == "TC=0")
    assert i_mo < i_tw < i_tc, "abort order broken: %d/%d/%d" % (i_mo, i_tw, i_tc)
    # drive fully restored: UM / claimed socket / SE / gains / motor off
    r = drive.regs
    assert r["MO"] == 0 and r["UM"] == 5
    assert r["CA[44]"] == 0 and r["CA[70]"] == 0
    assert all(r["SE[%d]" % n] == 0 for n in range(1, 8))
    assert r["KP[1]"] == pytest.approx(KP_ORACLE)
    # RR=0 (A5) present after the abort chain started
    assert any(c == "RR=0" for c in cmds[i_tc:])


def test_cancel_latched_during_preflight_sends_no_drive_write(tmp_path):
    """A cancel that arrives during P1 reads must beat the first mutation.

    This is the negative control for the former hole where cancel was only
    polled by the first energized sleep, after configuration and MO=1.
    """
    state = {"cancelled": False}

    class CancelOnLastPreflightRead(SimDrive):
        def command(self, cmd, timeout_ms=1000, allow_motion=False):
            result = super().command(
                cmd, timeout_ms=timeout_ms, allow_motion=allow_motion)
            if cmd.replace(" ", "").upper() == "WS[57]":
                state["cancelled"] = True
            return result

    drive = CancelOnLastPreflightRead()
    res = run_current_autotune(
        drive, _params(drive, tmp_path,
                       cancel_fn=lambda: state["cancelled"]))

    assert state["cancelled"] and res.status == RED
    assert "abort" not in res.evidence
    assert [cmd for cmd, _ in drive.log if "=" in cmd] == []
    assert not any(cmd.replace(" ", "").upper() == "MO=1"
                   for cmd, _ in drive.log)


def test_cancel_after_configuration_blocks_enable_and_runs_abort(tmp_path):
    """After a write, cancellation keeps the existing restore abort chain."""
    drive = SimDrive()

    def cancelled_after_last_setup_write():
        return any(cmd.replace(" ", "").upper() == "SE[7]=50"
                   for cmd, _ in drive.log)

    res = run_current_autotune(
        drive, _params(drive, tmp_path,
                       cancel_fn=cancelled_after_last_setup_write))

    cmds = [cmd.replace(" ", "").upper() for cmd, _ in drive.log]
    assert res.status == RED and "abort" in res.evidence
    assert "SE[7]=50" in cmds
    assert "MO=1" not in cmds
    assert "MO=0" in cmds and "TW[80]=0" in cmds
    assert drive.regs["MO"] == 0 and drive.regs["UM"] == 5
    assert drive.regs["CA[44]"] == 0 and drive.regs["CA[70]"] == 0


def test_progress_fn_exception_does_not_kill_run(tmp_path):
    def bomb(code, detail):
        raise RuntimeError("GUI hook crashed at %s" % code)

    drive = SimDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path, progress_fn=bomb))
    # hook exception must not degrade the verdict: still GREEN, no warnings
    assert res.status == GREEN, "hook exception degraded the run: %s / %s" % (
        res.status, res.reason)
    assert res.warnings == []
    assert abs(res.kp_v_per_a / KP_ORACLE - 1.0) <= 0.03
    assert res.evidence.get("progress_errors"), "hook errors must be logged"


def test_cancel_fn_exception_is_not_a_cancel(tmp_path):
    def bad_cancel():
        raise RuntimeError("flaky GUI poll")

    drive = SimDrive()
    res = run_current_autotune(drive, _params(drive, tmp_path, cancel_fn=bad_cancel))
    # run completes (YELLOW; the ignored exception is noted exactly once)
    assert res.status == YELLOW
    assert res.kp_v_per_a is not None
    assert abs(res.kp_v_per_a / KP_ORACLE - 1.0) <= 0.03
    cancel_warns = [w for w in res.warnings if "cancel_fn" in w]
    assert len(cancel_warns) == 1                       # noted exactly once


# ======================================================================================
# E3/E4 separate operator actions
# ======================================================================================
class SilentGainStoreDrive(SimDrive):
    """Drive parser fault model: accept a write but silently store another value."""

    def __init__(self, silent_store, **kwargs):
        super().__init__(**kwargs)
        self.silent_store = dict(silent_store)

    def _write(self, name, value):
        return super()._write(name, self.silent_store.get(name, value))


class GainReadbackTimeoutDrive(SimDrive):
    """The write reaches RAM, but its immediate verification query times out."""

    def __init__(self, timeout_name, **kwargs):
        super().__init__(**kwargs)
        self.timeout_name = timeout_name

    def _query(self, name):
        if name == self.timeout_name:
            raise TimeoutError("simulated readback timeout")
        return super()._query(name)


class SelectiveGainWriteFailureDrive(SimDrive):
    """Fail selected gain writes without preventing later commands."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fail_gain_writes = set()

    def _write(self, name, value):
        if name in self.fail_gain_writes:
            raise IOError("simulated %s write failure" % name)
        return super()._write(name, value)


class PersistenceLatchSimDrive(SimDrive):
    """SimDrive exposing the shared link-wide persistence latch contract."""

    def __init__(self, persistence_unknown=False, **kwargs):
        super().__init__(**kwargs)
        self.persistence_unknown = bool(persistence_unknown)
        self.persistence_latch_calls = 0
        self.latch_after_query = None

    def persistence_unknown_latched(self):
        return self.persistence_unknown

    def latch_persistence_unknown(self):
        self.persistence_latch_calls += 1
        self.persistence_unknown = True

    def _query(self, name):
        value = super()._query(name)
        if name == self.latch_after_query:
            self.latch_after_query = None
            self.persistence_unknown = True
        return value


class SvAppliedThenTimeoutDrive(PersistenceLatchSimDrive):
    """Model an SV request that reaches the drive but loses its response."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sv_applied = False

    def command(self, cmd, timeout_ms=1000, allow_motion=False):
        if cmd.strip().upper() == "SV":
            self.log.append((cmd, allow_motion))
            self.sv_applied = True
            raise TimeoutError("simulated timeout after SV was applied")
        return super().command(cmd, timeout_ms=timeout_ms,
                               allow_motion=allow_motion)


class AppliedThenTimeoutGainWriteDrive(SimDrive):
    """Apply selected gain writes but lose their transport response."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.timeout_after_gain_writes = set()

    def _write(self, name, value):
        response = super()._write(name, value)
        if name in self.timeout_after_gain_writes:
            raise TimeoutError("response lost after %s write applied" % name)
        return response


class IdentitySimDrive(SimDrive):
    """SimDrive with a stable identity shared across connection objects."""

    def __init__(self, stable_identity, **kwargs):
        super().__init__(**kwargs)
        self.stable_identity = stable_identity
        self.session_identity = object()

    def transaction_identity(self):
        return self.stable_identity

    def transaction_session_identity(self):
        return self.session_identity

    def rotate_session(self):
        self.session_identity = object()


class SessionRotatingQueryDrive(IdentitySimDrive):
    """Rotate the connection generation after one selected readback."""

    def __init__(self, stable_identity, **kwargs):
        super().__init__(stable_identity, **kwargs)
        self.rotate_after_query = None

    def _query(self, name):
        value = super()._query(name)
        if name == self.rotate_after_query:
            self.rotate_after_query = None
            self.rotate_session()
        return value


class FailedApplyLeavesAppliedDrive(SimDrive):
    """Lose the final trial readback and reject both rollback writes."""

    def __init__(self, **kwargs):
        super().__init__(kp=0.06, ki=700.0, **kwargs)
        self._lose_ki_readback_once = False

    def _write(self, name, value):
        if name == "KI[1]" and abs(value - 812.9) < 1e-9:
            response = super()._write(name, value)
            self._lose_ki_readback_once = True
            return response
        if (name == "KP[1]" and abs(value - 0.06) < 1e-12) or \
                (name == "KI[1]" and abs(value - 700.0) < 1e-9):
            raise IOError("simulated rollback write rejection for %s" % name)
        return super()._write(name, value)

    def _query(self, name):
        if name == "KI[1]" and self._lose_ki_readback_once:
            self._lose_ki_readback_once = False
            raise TimeoutError("trial KI readback response lost")
        return super()._query(name)


def test_apply_gains_writes_when_motor_off(tmp_path):
    drive = SimDrive()
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg = apply_gains(drive, res)
    assert ok, msg
    assert drive.regs["KP[1]"] == pytest.approx(0.0712)
    assert drive.regs["KI[1]"] == pytest.approx(812.9)
    assert not any(c == "SV" for c, _ in drive.log)   # I4: no SV unless persist


def test_apply_gains_wire_literals_drive_safe():
    """Every Phase-1 gain uses the proven EAS-safe plain-decimal envelope."""
    drive = SimDrive()
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.07123456789,
                         ki_hz=812.9391234)
    ok, msg = apply_gains(drive, res)
    assert ok, msg
    writes = [c for c, _ in drive.log
              if c.startswith(("KP[1]=", "KI[1]="))]
    assert writes == ["KP[1]=0.071235", "KI[1]=812.939123"]
    for command in writes:
        literal = command.split("=", 1)[1]
        assert "e" not in literal.lower(), command
        fraction = literal.split(".", 1)[1] if "." in literal else ""
        assert len(fraction) <= 6, command


def test_apply_gains_incident_silent_zero_blocks_persist():
    """Accepted-but-stored-as-zero must fail honestly and never reach SV."""
    drive = SilentGainStoreDrive({"KP[1]": 0.0})
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg = apply_gains(drive, res)
    assert not ok, msg
    assert "KP[1]" in msg and "readback" in msg and "SV not executed" in msg
    assert "observed RAM: KP[1]=0" in msg and "DO NOT ENABLE" in msg
    assert drive.regs["KP[1]"] == 0.0
    assert not any(c == "SV" for c, _ in drive.log)


def test_apply_gains_late_readback_mismatch_exposes_partial_apply():
    """A bad KI readback leaves KP in RAM but must suppress persistence."""
    drive = SilentGainStoreDrive({"KI[1]": 800.0})
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg = apply_gains(drive, res)
    assert not ok, msg
    assert "KI[1]" in msg and "mismatch" in msg and "KP[1]" in msg
    assert "SV not executed" in msg
    assert "observed RAM: KI[1]=800" in msg and "DO NOT ENABLE" in msg
    assert drive.regs["KP[1]"] == pytest.approx(0.0712)
    assert drive.regs["KI[1]"] == pytest.approx(800.0)
    assert not any(c == "SV" for c, _ in drive.log)


def test_apply_gains_readback_timeout_reports_unknown_ram_state():
    drive = GainReadbackTimeoutDrive("KP[1]")
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg = apply_gains(drive, res)
    assert not ok, msg
    assert drive.regs["KP[1]"] == pytest.approx(0.0712)  # write did reach RAM
    assert "RAM state UNKNOWN: KP[1]" in msg and "DO NOT ENABLE" in msg
    assert "verified prior RAM: none" in msg and "SV not executed" in msg
    assert not any(c == "SV" for c, _ in drive.log)


def test_apply_gains_rejects_legacy_persist_before_any_drive_command():
    drive = SimDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg = apply_gains(drive, res, persist=True)
    assert not ok
    assert "persist=True" in msg and "begin_gain_trial_p1" in msg
    assert "SV not executed" in msg
    assert drive.log == []
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_apply_gains_rejects_latched_unknown_before_any_drive_command():
    drive = PersistenceLatchSimDrive(
        persistence_unknown=True, kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg = apply_gains(drive, res)

    assert not ok and "UNKNOWN" in msg
    assert drive.log == []
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_apply_gains_rechecks_unknown_latch_immediately_before_first_write():
    drive = PersistenceLatchSimDrive(kp=0.06, ki=700.0)
    drive.latch_after_query = "MO"
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg = apply_gains(drive, res)

    assert not ok and "UNKNOWN" in msg
    assert not any(c.startswith(("KP[1]=", "KI[1]=")) for c, _ in drive.log)
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_apply_gains_refuses_gain_that_vanishes_on_wire():
    drive = SimDrive()
    res = AutotuneResult(status=GREEN, kp_v_per_a=1e-8, ki_hz=812.9)
    ok, msg = apply_gains(drive, res)
    assert not ok, msg
    assert "KP[1]" in msg and "round" in msg and "SV not executed" in msg
    assert not any(c.startswith("KP[1]=") for c, _ in drive.log)
    assert not any(c == "SV" for c, _ in drive.log)


def test_apply_gains_refuses_motor_on():
    drive = SimDrive(mo0=1)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.07, ki_hz=800.0)
    ok, msg = apply_gains(drive, res)
    assert not ok and "MO=1" in msg


def test_apply_gains_refuses_red_result():
    drive = SimDrive()
    ok, _ = apply_gains(drive, AutotuneResult(status=RED, reason="x"))
    assert not ok


def test_verify_run_is_honest_stub():
    res = verify_run(SimDrive())
    assert res.status == RED and "실기" in res.reason


def test_p1_gain_trial_apply_restore_never_saves():
    drive = SimDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.071234567,
                         ki_hz=812.939123)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    assert isinstance(trial, at.GainTrialP1)
    assert trial.original == pytest.approx({"KP[1]": 0.06, "KI[1]": 700.0})
    assert drive.regs["KP[1]"] == pytest.approx(0.071235)
    assert drive.regs["KI[1]"] == pytest.approx(812.939123)
    assert not any(c == "SV" for c, _ in drive.log)

    ok, msg = at.restore_gain_trial_p1(drive, trial)
    assert ok, msg
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)
    assert not any(c == "SV" for c, _ in drive.log)


def test_p1_gain_trial_begin_rejects_latched_unknown_before_drive_command():
    drive = PersistenceLatchSimDrive(
        persistence_unknown=True, kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(drive, res)

    assert not ok and trial is None and "UNKNOWN" in msg
    assert drive.log == []
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_begin_rechecks_unknown_latch_before_first_write():
    drive = PersistenceLatchSimDrive(kp=0.06, ki=700.0)
    drive.latch_after_query = "KI[1]"
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(drive, res)

    assert not ok and trial is None and "UNKNOWN" in msg
    assert not any(c.startswith(("KP[1]=", "KI[1]=")) for c, _ in drive.log)
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_rejects_unrepresentable_original_before_trial_writes():
    drive = SimDrive(kp=4e-7, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(drive, res)

    assert not ok and trial is None
    assert "KP[1]" in msg and ("0" in msg or "round" in msg.lower())
    assert not any(c.startswith(("KP[1]=", "KI[1]=")) for c, _ in drive.log)
    assert drive.regs["KP[1]"] == pytest.approx(4e-7)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_prevalidates_second_original_rounding_before_any_write():
    """A nonzero >0.5% KI rounding error must block even the earlier KP write."""
    drive = SimDrive(kp=0.06, ki=1.01e-6)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(drive, res)

    assert not ok and trial is None
    assert "KI[1]" in msg and "0.990%" in msg
    assert not any(c.startswith(("KP[1]=", "KI[1]=")) for c, _ in drive.log)
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(1.01e-6)


def test_p1_gain_trial_restore_compares_to_representable_original():
    drive = SimDrive(kp=0.0002004, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg

    ok, msg = at.restore_gain_trial_p1(drive, trial)

    assert ok, msg
    assert trial.original["KP[1]"] == pytest.approx(0.0002004)
    assert trial.rollback_literals["KP[1]"] == "0.0002"
    assert trial.rollback_expected["KP[1]"] == pytest.approx(0.0002)
    assert drive.regs["KP[1]"] == pytest.approx(0.0002)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_restore_attempts_both_registers_and_full_readback():
    drive = SelectiveGainWriteFailureDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    drive.fail_gain_writes.add("KP[1]")
    log_start = len(drive.log)

    ok, msg = at.restore_gain_trial_p1(drive, trial)

    restore_commands = [c for c, _ in drive.log[log_start:]]
    assert not ok
    assert "KP[1]" in msg and "write" in msg.lower()
    assert "full readback" in msg.lower()
    assert "KP[1]=0.0712" in msg and "KI[1]=700" in msg
    assert "KP[1]=0.06" in restore_commands
    assert "KI[1]=700" in restore_commands
    assert "KP[1]" in restore_commands and "KI[1]" in restore_commands
    assert drive.regs["KP[1]"] == pytest.approx(0.0712)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_restore_accepts_exact_full_readback_after_write_timeout():
    drive = AppliedThenTimeoutGainWriteDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    drive.timeout_after_gain_writes.add("KP[1]")

    ok, msg = at.restore_gain_trial_p1(drive, trial)

    assert ok, msg
    assert "warning" in msg.lower() and "KP[1]" in msg
    assert getattr(trial, "persistence_state", None) == "RESTORED"
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_save_is_locked_until_e4_exists():
    drive = SimDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    log_count = len(drive.log)
    ok, msg = at.commit_gain_trial_p1(drive, trial)
    assert not ok and "on-motor" in msg.lower()
    assert "SV not executed" in msg
    assert len(drive.log) == log_count
    assert getattr(trial, "persistence_state", None) == "RAM_TRIAL"

    ok, msg = at.restore_gain_trial_p1(drive, trial)
    assert ok, msg
    assert getattr(trial, "persistence_state", None) == "RESTORED"

def test_p1_gain_trial_commit_requires_on_motor_verification_before_drive_io():
    drive = SimDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    drive.log.clear()

    ok, msg = at.commit_gain_trial_p1(drive, trial)

    assert not ok
    assert "on-motor" in msg.lower() and "verification" in msg.lower()
    assert "SV not executed" in msg
    assert drive.log == []
    assert trial.persistence_state == "RAM_TRIAL"


def test_p1_gain_trial_commit_rejects_preexisting_latch_without_drive_command():
    drive = PersistenceLatchSimDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    drive.persistence_unknown = True
    drive.log.clear()

    ok, msg = at.commit_gain_trial_p1(drive, trial)

    assert not ok and "UNKNOWN" in msg and "SV not executed" in msg
    assert trial.persistence_state == "RAM_TRIAL"
    assert drive.log == []


def test_p1_gain_trial_verification_gate_precedes_final_readback():
    drive = PersistenceLatchSimDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    drive.latch_after_query = "KI[1]"
    log_start = len(drive.log)

    ok, msg = at.commit_gain_trial_p1(drive, trial)

    commit_commands = [c for c, _ in drive.log[log_start:]]
    assert not ok and "on-motor" in msg.lower() and "SV not executed" in msg
    assert trial.persistence_state == "RAM_TRIAL"
    assert commit_commands == []
    assert drive.persistence_unknown_latched() is False


def test_p1_gain_trial_verification_gate_prevents_ambiguous_sv_path():
    drive = SvAppliedThenTimeoutDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg

    ok, msg = at.commit_gain_trial_p1(drive, trial)

    assert not ok and not drive.sv_applied
    assert "on-motor" in msg.lower() and "SV not executed" in msg
    assert not any(c == "SV" for c, _ in drive.log)
    assert getattr(trial, "persistence_state", None) == "RAM_TRIAL"
    assert drive.persistence_unknown_latched() is False
    assert drive.persistence_latch_calls == 0

    ok, msg = at.restore_gain_trial_p1(drive, trial)
    assert ok, msg


def test_p1_gain_trial_production_link_is_locked_before_any_drive_io():
    class ProductionLikeDrive(SimDrive):
        p1_gain_trial_durability_mode = None

    drive = ProductionLikeDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(
        status=GREEN, kp_v_per_a=0.071234567, ki_hz=812.939123)

    ok, msg, trial = at.begin_gain_trial_p1(drive, res)

    assert not ok and trial is None
    assert "durable" in msg.lower() and "locked" in msg.lower()
    assert drive.log == []
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_legacy_p1_apply_is_production_locked_before_any_drive_io():
    class ProductionLikeDrive(SimDrive):
        p1_gain_trial_durability_mode = None

    drive = ProductionLikeDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(
        status=GREEN, kp_v_per_a=0.071234567, ki_hz=812.939123)

    ok, msg = at.apply_gains(drive, res, persist=False)

    assert not ok
    assert "durable" in msg.lower() and "locked" in msg.lower()
    assert drive.log == []
    assert drive.regs["KP[1]"] == pytest.approx(0.06)
    assert drive.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_failed_apply_rolls_back_and_suppresses_sv():
    drive = SilentGainStoreDrive({"KI[1]": 600.0})
    original = {"KP[1]": drive.regs["KP[1]"], "KI[1]": drive.regs["KI[1]"]}
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert not ok, msg
    # The simulated persistent refusal also blocks KI rollback, so the retained
    # trial is the honest recovery authority and SV remains forbidden.
    assert trial is not None
    assert drive.regs["KP[1]"] == pytest.approx(original["KP[1]"])
    assert not any(c == "SV" for c, _ in drive.log)


def test_p1_gain_trial_failed_apply_recovery_authority_cannot_commit():
    drive = FailedApplyLeavesAppliedDrive()
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(drive, res)

    assert not ok and trial is not None
    assert drive.regs["KP[1]"] == pytest.approx(0.0712)
    assert drive.regs["KI[1]"] == pytest.approx(812.9)
    assert getattr(trial, "persistence_state", None) == "RESTORE_FAILED"
    ok, msg = at.commit_gain_trial_p1(drive, trial)
    assert not ok and "RESTORE_FAILED" in msg
    assert not any(c == "SV" for c, _ in drive.log)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_p1_gain_trial_direct_construction_rejects_nonfinite_applied(bad):
    with pytest.raises(ValueError):
        at.GainTrialP1(
            original={"KP[1]": 0.06, "KI[1]": 700.0},
            applied={"KP[1]": bad, "KI[1]": 812.9})


def test_p1_gain_trial_direct_construction_is_not_commit_authority():
    drive = SimDrive(kp=0.0712, ki=812.9)
    trial = at.GainTrialP1(
        original={"KP[1]": 0.06, "KI[1]": 700.0},
        applied={"KP[1]": 0.0712, "KI[1]": 812.9})

    ok, msg = at.commit_gain_trial_p1(drive, trial)

    assert not ok and "PREPARING" in msg
    assert not any(c == "SV" for c, _ in drive.log)
    log_count = len(drive.log)
    ok, msg = at.restore_gain_trial_p1(drive, trial)
    assert not ok and "session" in msg.lower()
    assert len(drive.log) == log_count
    ok, msg = at.adopt_gain_trial_p1_for_restore(drive, trial)
    assert not ok and "PREPARING" in msg
    assert len(drive.log) == log_count


def test_p1_gain_trial_mutated_applied_authority_blocks_sv():
    drive = SimDrive(kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(drive, res)
    assert ok, msg
    trial.applied["KP[1]"] = 99.0
    drive.regs["KP[1]"] = 99.0

    ok, msg = at.commit_gain_trial_p1(drive, trial)

    assert not ok and "authority" in msg.lower()
    assert getattr(trial, "persistence_state", None) == "AUTHORITY_INVALID"
    assert not any(c == "SV" for c, _ in drive.log)


def test_p1_gain_trial_cross_link_commit_and_restore_are_rejected():
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    other_session = IdentitySimDrive(
        ("gold", "serial-1"), kp=0.0712, ki=812.9)

    log_count = len(other_session.log)
    ok, msg = at.commit_gain_trial_p1(other_session, trial)
    assert not ok and "session" in msg.lower()
    assert len(other_session.log) == log_count
    ok, msg = at.restore_gain_trial_p1(other_session, trial)
    assert not ok and "session" in msg.lower()
    assert len(other_session.log) == log_count
    assert not any(c == "SV" for c, _ in other_session.log)


def test_p1_gain_trial_same_link_new_session_requires_restore_only_adoption():
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    source.rotate_session()

    log_count = len(source.log)
    ok, msg = at.commit_gain_trial_p1(source, trial)
    assert not ok and "session" in msg.lower()
    assert len(source.log) == log_count
    ok, msg = at.restore_gain_trial_p1(source, trial)
    assert not ok and "session" in msg.lower()
    assert len(source.log) == log_count

    ok, msg = at.adopt_gain_trial_p1_for_restore(source, trial)
    assert ok, msg
    assert trial.restore_only is True
    ok, msg = at.commit_gain_trial_p1(source, trial)
    assert not ok and "restore-only" in msg.lower()


def test_p1_gain_trial_same_session_rechecks_stable_identity():
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    source.stable_identity = ("gold", "serial-2")

    log_count = len(source.log)
    ok, msg = at.commit_gain_trial_p1(source, trial)
    assert not ok and "session" in msg.lower()
    assert len(source.log) == log_count
    ok, msg = at.restore_gain_trial_p1(source, trial)
    assert not ok and "session" in msg.lower()
    assert len(source.log) == log_count


def test_p1_gain_trial_rechecks_session_before_first_trial_write():
    source = SessionRotatingQueryDrive(
        ("gold", "serial-1"), kp=0.06, ki=700.0)
    source.rotate_after_query = "KI[1]"
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(source, res)

    assert not ok and trial is None and "session" in msg.lower()
    assert not any(c.startswith(("KP[1]=", "KI[1]=")) for c, _ in source.log)
    assert source.regs["KP[1]"] == pytest.approx(0.06)
    assert source.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_rechecks_session_immediately_before_restore_writes():
    source = SessionRotatingQueryDrive(
        ("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    source.rotate_after_query = "MO"
    log_start = len(source.log)

    ok, msg = at.restore_gain_trial_p1(source, trial)

    restore_commands = [c for c, _ in source.log[log_start:]]
    assert not ok and "session" in msg.lower()
    assert trial.persistence_state == "RAM_TRIAL"
    assert not any(c.startswith(("KP[1]=", "KI[1]="))
                   for c in restore_commands)
    assert source.regs["KP[1]"] == pytest.approx(0.0712)
    assert source.regs["KI[1]"] == pytest.approx(812.9)


def test_p1_gain_trial_rechecks_session_after_final_readback_before_sv():
    source = SessionRotatingQueryDrive(
        ("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    source.rotate_after_query = "KI[1]"

    ok, msg = at.commit_gain_trial_p1(source, trial)

    assert not ok and "session" in msg.lower()
    assert trial.persistence_state == "RAM_TRIAL"
    assert not any(c == "SV" for c, _ in source.log)


def test_p1_gain_trial_rejects_unavailable_session_token_before_writes():
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)

    def unavailable():
        raise RuntimeError("session token unavailable")

    source.transaction_session_identity = unavailable
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(source, res)

    assert not ok and trial is None and "session" in msg.lower()
    assert not any(c.startswith(("KP[1]=", "KI[1]=")) for c, _ in source.log)


def test_p1_gain_trial_rejects_none_session_token_before_writes():
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    source.transaction_session_identity = lambda: None
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)

    ok, msg, trial = at.begin_gain_trial_p1(source, res)

    assert not ok and trial is None and "session" in msg.lower()
    assert not any(c.startswith(("KP[1]=", "KI[1]=")) for c, _ in source.log)


def test_p1_gain_trial_reconnect_adoption_is_restore_only():
    identity = {"target": "gold", "serial": "serial-1"}
    source = IdentitySimDrive(identity, kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    reconnected = IdentitySimDrive(
        {"serial": "serial-1", "target": "gold"},
        kp=0.0712, ki=812.9)

    ok, msg = at.adopt_gain_trial_p1_for_restore(reconnected, trial)

    assert ok, msg
    assert trial.restore_only is True
    assert trial.owner_link is reconnected
    assert trial.persistence_state == "RAM_TRIAL"
    log_count = len(reconnected.log)
    ok, msg = at.commit_gain_trial_p1(reconnected, trial)
    assert not ok and "restore-only" in msg.lower()
    assert len(reconnected.log) == log_count
    ok, msg = at.restore_gain_trial_p1(reconnected, trial)
    assert ok, msg
    assert trial.persistence_state == "RESTORED"
    assert reconnected.regs["KP[1]"] == pytest.approx(0.06)
    assert reconnected.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_authority_invalid_reconnect_uses_frozen_applied():
    identity = ("gold", "serial-1")
    source = IdentitySimDrive(identity, kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    trial.applied["KP[1]"] = float("nan")
    ok, msg = at.commit_gain_trial_p1(source, trial)
    assert not ok and trial.persistence_state == "AUTHORITY_INVALID"

    reconnected = IdentitySimDrive(identity, kp=0.0712, ki=812.9)
    ok, msg = at.adopt_gain_trial_p1_for_restore(reconnected, trial)

    assert ok, msg
    assert trial.owner_link is reconnected
    assert trial.restore_only is True
    assert trial.persistence_state == "RESTORE_FAILED"
    ok, msg = at.restore_gain_trial_p1(reconnected, trial)
    assert ok, msg
    assert trial.persistence_state == "RESTORED"
    assert reconnected.regs["KP[1]"] == pytest.approx(0.06)
    assert reconnected.regs["KI[1]"] == pytest.approx(700.0)


def test_p1_gain_trial_adoption_rechecks_session_before_rebinding():
    identity = ("gold", "serial-1")
    source = IdentitySimDrive(identity, kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    candidate = SessionRotatingQueryDrive(
        identity, kp=0.0712, ki=812.9)
    candidate.rotate_after_query = "KI[1]"

    ok, msg = at.adopt_gain_trial_p1_for_restore(candidate, trial)

    assert not ok and "session" in msg.lower()
    assert trial.owner_link is source
    assert trial.restore_only is False


def test_p1_gain_trial_reconnect_adoption_accepts_restore_failed_applied_ram():
    source = FailedApplyLeavesAppliedDrive()
    source.transaction_identity = lambda: ("gold", "serial-1")
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert not ok and trial.persistence_state == "RESTORE_FAILED"
    reconnected = IdentitySimDrive(
        ("gold", "serial-1"), kp=0.0712, ki=812.9)

    ok, msg = at.adopt_gain_trial_p1_for_restore(reconnected, trial)

    assert ok, msg
    assert trial.restore_only is True
    assert trial.persistence_state == "RESTORE_FAILED"
    ok, msg = at.commit_gain_trial_p1(reconnected, trial)
    assert not ok and "restore-only" in msg.lower()
    ok, msg = at.restore_gain_trial_p1(reconnected, trial)
    assert ok, msg


def test_p1_gain_trial_reconnect_adoption_marks_already_restored_without_writes():
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    reconnected = IdentitySimDrive(
        ("gold", "serial-1"), kp=0.06, ki=700.0)

    ok, msg = at.adopt_gain_trial_p1_for_restore(reconnected, trial)

    assert ok and "already restored" in msg.lower()
    assert trial.restore_only is True
    assert trial.persistence_state == "RESTORED"
    assert not any("=" in c for c, _ in reconnected.log)


@pytest.mark.parametrize("identity", [("gold", "serial-2"), None])
def test_p1_gain_trial_reconnect_adoption_rejects_different_or_missing_identity(
        identity):
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    if identity is None:
        reconnected = SimDrive(kp=0.0712, ki=812.9)
    else:
        reconnected = IdentitySimDrive(identity, kp=0.0712, ki=812.9)

    ok, msg = at.adopt_gain_trial_p1_for_restore(reconnected, trial)

    assert not ok and "identity" in msg.lower()
    assert trial.owner_link is source and trial.restore_only is False
    assert reconnected.log == []


def test_p1_gain_trial_reconnect_adoption_rejects_drift_motor_on_and_nonfinite():
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg

    drifted = IdentitySimDrive(
        ("gold", "serial-1"), kp=0.08, ki=812.9)
    ok, msg = at.adopt_gain_trial_p1_for_restore(drifted, trial)
    assert not ok and "drift" in msg.lower()
    assert trial.owner_link is source

    motor_on = IdentitySimDrive(
        ("gold", "serial-1"), kp=0.0712, ki=812.9, mo0=1)
    ok, msg = at.adopt_gain_trial_p1_for_restore(motor_on, trial)
    assert not ok and "MO" in msg
    assert trial.owner_link is source

    nonfinite = IdentitySimDrive(
        ("gold", "serial-1"), kp=0.0712, ki=812.9)
    nonfinite.regs["KP[1]"] = float("nan")
    ok, msg = at.adopt_gain_trial_p1_for_restore(nonfinite, trial)
    assert not ok and "readback" in msg.lower()
    assert trial.owner_link is source


@pytest.mark.parametrize("terminal_state", ["UNKNOWN", "PERSISTED"])
def test_p1_gain_trial_reconnect_adoption_rejects_terminal_save_state(
        terminal_state):
    source = IdentitySimDrive(("gold", "serial-1"), kp=0.06, ki=700.0)
    res = AutotuneResult(status=GREEN, kp_v_per_a=0.0712, ki_hz=812.9)
    ok, msg, trial = at.begin_gain_trial_p1(source, res)
    assert ok, msg
    trial.persistence_state = terminal_state
    reconnected = IdentitySimDrive(
        ("gold", "serial-1"), kp=0.0712, ki=812.9)

    ok, msg = at.adopt_gain_trial_p1_for_restore(reconnected, trial)

    assert not ok and terminal_state in msg
    assert reconnected.log == []
