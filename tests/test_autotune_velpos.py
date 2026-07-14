# -*- coding: utf-8 -*-
"""Headless tests for autotune_velpos.py (SPEC docs/autotune-velpos-spec.md §7).

T3: a simulated drive with the DISCRETE MECHANICAL PLANT
    v[k+1] = v[k] + dt*(K_a*I - D*v - C*sgn v)   (+ velocity quantization noise)
current loop = 362 Hz first-order + 1-sample delay; truth K_a=5.79e6,
B=1e-7, I_c=0.2 A.  It answers the real command sequence (MO/UM/TC/JV/ST/VX/
record_start/record_fetch) and the FULL pipeline must recover:
  K_a<=2%, B<=15%, I_c<=15%, KP[2]<=3%, KI[2]/KP[3]<=0.5% vs the oracles,
plus the one-sided (no +- cancellation) K_a regression tooth.
No hardware is touched anywhere in this file.
"""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autotune_velpos as vp
from autotune_velpos import (AutotuneVPParams, AutotuneVPResult,
                             run_velpos_autotune, apply_gains_vp, verify_run_vp,
                             vel_pos_margins, design_vp_gains, window_slope,
                             GREEN, YELLOW, RED)

# ---- frozen oracles (SPEC §7 — never re-baseline here) -------------------------------
KA_TRUTH = 5.79e6            # cnt/s^2/A  (T3 plant truth)
B_TRUTH = 1e-7               # A/(cnt/s)
IC_TRUTH = 0.2               # A
KA_STAR = 5.794e6            # 1/FF[1] (live fingerprint)
KP2_ORACLE = 7.896e-5        # EAS KP[2]
KI2_ORACLE = 10.70           # Hz (deterministic at TS=100us)
KP3_ORACLE = 85.2            # 1/s (deterministic at TS=100us)
TS_US = 100
CA18 = 65536.0
CL1 = 21.2132
KP1_EAS, KI1_EAS = 0.07177, 812.939
R_PP, L_PP = 0.139, 41.6e-6  # H_ci model inputs (live Phase-1)


# ======================================================================================
# simulated drive (T3 mechanical plant per SPEC §7)
# ======================================================================================
class VPSim:
    """Mock ElmoLink for Phase 2: UM=5 dual mode (TC torque / JV velocity),
    362 Hz first-order current loop + 1-sample delay, Coulomb+viscous plant
    with stiction, EAS velocity PI when in JV mode, free-running recorder via
    record_start/record_fetch.  Time advances ONLY via advance()."""

    _MOTION_PREFIXES = ("MO=1", "BG", "JV", "PA", "PR", "PT", "PVT", "TC",
                        "MI", "ST")

    def __init__(self, k_a=KA_TRUTH, b=B_TRUTH, i_c=IC_TRUTH, ts_us=TS_US,
                 fc_hz=362.0, vel_noise=1000.0, commut_sign=1.0,
                 kp2=KP2_ORACLE, ki2=KI2_ORACLE, kp3=KP3_ORACLE,
                 ff1=1.726e-7, gs2=0, um=5, ca17=5, ca7=438.0,
                 vel_scale_err=1.0, torque_disabled=False, vel_garbage=False,
                 hl_writable=True, mo0=0, mf=0, seed=1, um5_eff=1.0):
        # §9 fault-injection knobs:
        #  vel_scale_err: RECORDED Velocity = v_true * err (live 1/125
        #    hypothesis — internal units); VX polls stay TRUE cnt/s.
        #  torque_disabled: drive applies NO torque (I_active=0) while the
        #    Current Command channel shows the command (UNIT-DIAG physics RED).
        #  vel_garbage: Velocity channel nonlinearly broken (scale+offset) —
        #    a single scale factor cannot fix it -> hard gate must RED.
        self.vel_scale_err = float(vel_scale_err)
        # UM=5 torque efficiency (<1 = commutation mis-mapping analogue: the
        # commanded current flows — IQ real — but shaft torque is derated);
        # the UM=3 PA-follow path is INDEPENDENT of this knob (stator-angle
        # drive bypasses the commutation mapping)
        self.um5_eff = float(um5_eff)
        self.torque_disabled = bool(torque_disabled)
        self.vel_garbage = bool(vel_garbage)
        self.dt = ts_us * 1e-6
        self.k_a, self.b, self.i_c = float(k_a), float(b), float(i_c)
        self.D = self.k_a * self.b
        self.C = self.k_a * self.i_c
        self.commut_sign = float(commut_sign)   # -1 = commutation sign fault tooth
        self.a_i = math.exp(-2 * math.pi * fc_hz * self.dt)
        self.vel_noise = float(vel_noise)
        self.hl_writable = bool(hl_writable)
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.v = 0.0                 # true velocity [cnt/s]
        self.p = 0.0                 # true position [cnt]
        self.i_act = 0.0             # actual torque current [A]
        self.cmd_prev = 0.0          # 1-sample command delay
        self.integ = 0.0             # velocity-PI integrator
        self.mode = "tc"             # UM=5: last command wins (TC torque / JV vel)
        self.tc = 0.0
        self.jv = 0.0
        self.v_meas = 0.0
        self.regs = {"TS": ts_us, "UM": um, "MF": mf, "SR": 0,
                     "GS[0]": 0, "GS[1]": 0, "GS[2]": gs2,
                     "KP[1]": KP1_EAS, "KP[2]": kp2, "KP[3]": kp3,
                     "KI[1]": KI1_EAS, "KI[2]": ki2,
                     "CA[7]": ca7, "CA[17]": ca17, "CA[18]": CA18, "CA[19]": 21,
                     "PA": 0.0,
                     "CA[41]": 30, "CA[42]": 0, "CA[43]": 0, "CA[44]": 0,
                     "CL[1]": CL1, "PL[1]": 70.7107, "MC": 140,
                     "VH[2]": 3.93e6, "VH[3]": 0, "VL[3]": 0,
                     "ER[2]": 1e8, "ER[3]": 1e9,
                     "HL[2]": 0, "HL[3]": 0, "LL[2]": 0, "LL[3]": 0,
                     "AC": 1e6, "DC": 1e6, "SD": 1e6, "SP": 2e5,
                     "FF[1]": ff1, "FF[2]": 1, "BV": 48.4,
                     "WS[28]": ts_us, "WS[55]": ts_us,
                     "MO": mo0, "LC": 0}
        self.signals = ["Velocity", "Velocity Command", "Position",
                        "Position Command", "Position Error",
                        "Active Current [A]", "Reactive Current [A]",
                        "Current Command [A]", "Total Current Command [A]",
                        "DC Bus Voltage"]
        self._rec = None
        self.record_calls = 0
        self.log = []

    is_connected = True

    def recorder_signals(self):
        return list(self.signals)

    # ---- physics -----------------------------------------------------------------
    def _cmd_current(self):
        if self.regs["MO"] != 1:
            return 0.0
        if self.mode == "jv":
            e = self.jv - self.v_meas
            u_p = self.regs["KP[2]"] * e
            u = u_p + self.regs["KP[2]"] * self.integ
            cl = self.regs["CL[1]"]
            if abs(u) < cl or e * u < 0:       # conditional anti-windup
                self.integ += 2 * math.pi * self.regs["KI[2]"] * self.dt * e
                u = self.regs["KP[2]"] * (e + self.integ)
            return max(-cl, min(cl, u))
        return max(-self.regs["PL[1]"], min(self.regs["PL[1]"], self.tc))

    def _step(self, nk):
        cmd = self._cmd_current()
        # 362 Hz first-order current loop, 1-sample command delay
        if self.torque_disabled:                 # §9 tooth: command shown, no torque
            self.i_act = 0.0
        else:
            self.i_act = self.a_i * self.i_act + (1 - self.a_i) * self.cmd_prev
        self.cmd_prev = cmd
        drive = self.commut_sign * self.k_a * self.i_act * self.um5_eff
        if abs(self.v) < 1.0 and abs(drive) <= self.C:
            self.v = 0.0                        # stiction holds
        else:
            sgn = math.copysign(1.0, self.v) if abs(self.v) >= 1.0 \
                else math.copysign(1.0, drive)
            acc = drive - self.D * self.v - self.C * sgn
            v_new = self.v + self.dt * acc
            # Karnopp zero-crossing clamp (sim-physics fix 2026-07-13): plain
            # explicit integration of Coulomb friction overshoots zero and
            # chatters in a +-C*dt limit cycle FOREVER (|v|~116 > the 1.0
            # stick band) — the rotor never re-sticks, so static friction
            # never re-engages: unphysical (a real rotor stops).  Friction
            # may stop motion, never reverse it: clamp to 0 when the sign
            # flip is friction-driven (|drive| <= C).
            if self.v * v_new < 0.0 and abs(drive) <= self.C:
                v_new = 0.0
            self.v = v_new
        self.p += self.dt * self.v
        self.v_meas = self.v + nk
        if self._rec and self._rec["left"] > 0:
            r = self._rec
            if r["k"] % r["tres"] == 0:
                for nm in r["names"]:
                    r["bufs"][nm].append(self._chan(nm))
                r["left"] -= 1
            r["k"] += 1
        self.t += self.dt

    def advance(self, dur_s):
        n = int(round(dur_s / self.dt))
        if n <= 0:
            return
        noise = self.rng.standard_normal(n) * self.vel_noise
        for k in range(n):
            self._step(noise[k])

    def _chan(self, name):
        if name == "Velocity":
            if self.vel_garbage:                 # nonlinear break (scale+offset)
                return 0.3 * self.v_meas + 5000.0
            return self.v_meas * self.vel_scale_err
        if name == "Position":
            return float(round(self.p))          # ground-truth counts (PX-adjacent)
        if name == "Active Current [A]":
            return self.i_act
        if name == "Velocity Command":
            return self.jv if self.mode == "jv" else 0.0
        if name in ("Current Command [A]", "Total Current Command [A]"):
            return self.cmd_prev
        if name in ("Position Command", "Position Error", "Reactive Current [A]"):
            return 0.0
        if name == "DC Bus Voltage":
            return 48.4
        raise KeyError(name)

    # ---- recorder (start/fetch split) ---------------------------------------------
    def record_start(self, signals, length, time_resolution=1):
        self.record_calls += 1
        for s in signals:
            if s not in self.signals:
                raise KeyError("signals not in personality: %r" % s)
        self._rec = {"names": list(signals), "tres": max(1, int(time_resolution)),
                     "left": int(length), "k": 0,
                     "bufs": {s: [] for s in signals}}

    def record_fetch(self, timeout_s=10.0, poll_s=0.02):
        r = self._rec
        if r is None:
            raise RuntimeError("record_fetch without record_start")
        if r["left"] > 0:                       # recorder free-runs to completion
            self.advance(r["left"] * r["tres"] * self.dt + self.dt)
        self._rec = None
        out = {s: np.asarray(r["bufs"][s], dtype=float) for s in r["names"]}
        out["dt"] = r["tres"] * self.dt
        return out

    # ---- transport ------------------------------------------------------------------
    def command(self, cmd, timeout_ms=1000, allow_motion=False):
        self.log.append((cmd, allow_motion))
        u = cmd.replace(" ", "").upper()
        if not allow_motion and any(u.startswith(pf) for pf in self._MOTION_PREFIXES):
            raise PermissionError("refused motion command without allow_motion: %r"
                                  % cmd)
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
                self.tc, self.jv, self.integ = 0.0, 0.0, 0.0
                self.mode = "tc"
            else:
                regs["MO"] = 0
            return ""
        if name == "TC":
            if abs(v) > regs["PL[1]"]:
                raise IOError("TC exceeds PL[1]")
            self.tc, self.mode = v, "tc"
            return ""
        if name == "JV":
            if abs(v) > regs["VH[2]"]:
                raise IOError("JV exceeds VH[2]")
            self.jv, self.mode = v, "jv"
            return ""
        if name == "UM":
            if regs["MO"] == 1:
                raise IOError("UM change requires MO=0")
            regs["UM"] = int(v)
            return ""
        if name == "PA":
            # REAL CR semantics (HIGH-2): PA is only ARMED here — it takes
            # effect on the next BG (CR :12476).  A code path that skips BG
            # gets NO motion (the exact live failure mode being encoded).
            self.pa_pending = v
            return ""
        if name in ("HL[2]", "LL[2]") and not self.hl_writable:
            raise IOError("%s write refused (U-P4 tooth)" % name)
        regs[name] = v
        return ""

    def _apply_pa(self):
        """BG: apply the armed PA.  UM=3 stepper drag physics — the stator
        angle drags the rotor iff the held current exceeds the STATIC
        friction equivalent (i_s/i_s_load on subclasses); commutation-
        agnostic by construction (um5_eff NOT applied)."""
        regs = self.regs
        v = getattr(self, "pa_pending", None)
        if v is None:
            return
        old_pa = regs.get("PA", 0.0)
        regs["PA"] = v
        if regs.get("UM") == 3 and regs["MO"] == 1:
            th = getattr(self, "i_s", getattr(self, "i_s_load", self.i_c))
            if abs(self.tc) > th:
                pp = regs.get("CA[19]", 21)
                self.p += (v - old_pa) * (regs["CA[18]"] / (pp * 512.0))
        self.pa_pending = None

    def _query(self, name):
        if name == "BG":                        # arm/apply the pending PA
            self._apply_pa()
            return ""
        if name == "ST":                        # motion-gated stop (query form)
            self.jv = 0.0
            if self.mode != "jv":
                self.mode = "jv"                # decel via velocity loop to zero
            return ""
        if name == "VX":
            return "%.6f" % self.v_meas
        if name == "PX":
            return "%.6f" % self.p
        if name == "IQ":
            return "%.6f" % self.i_act
        if name == "SO":
            return "1" if self.regs["MO"] == 1 else "0"
        if name == "SV":
            return ""
        if name in self.regs:
            return str(self.regs[name])
        raise IOError("unknown query %r" % name)


def _params(drive, tmpdir, **kw):
    # clock_fn homogeneous with the sim time base (2026-07-13: the UNIT-DIAG
    # pulse duration is wall-clock MEASURED; sims must supply their clock)
    kw.setdefault("clock_fn", lambda: drive.t)
    kw.setdefault("sleep_fn", drive.advance)
    return AutotuneVPParams(snapshot_dir=str(tmpdir), **kw)


# ======================================================================================
# T3 full-pipeline oracle tests
# ======================================================================================
@pytest.fixture(scope="module")
def green_run(tmp_path_factory):
    drive = VPSim()
    params = _params(drive, tmp_path_factory.mktemp("vpsnap"))
    res = run_velpos_autotune(drive, params)
    return drive, params, res


def test_t3_pipeline_completes_green(green_run):
    _, _, res = green_run
    assert res.status == GREEN, "status=%s reason=%s warn=%s" % (
        res.status, res.reason, res.warnings)
    assert res.warnings == []
    assert res.ts_us == TS_US
    gates = res.evidence["gates"]
    assert all(g["pass"] for g in gates.values()), \
        {k: g for k, g in gates.items() if not g["pass"]}


def test_t3_ka_oracle(green_run):
    _, _, res = green_run
    err = res.k_a / KA_TRUTH - 1.0
    assert abs(err) <= 0.02, "K_a=%.4g err=%+.2f%%" % (res.k_a, 100 * err)


def test_t3_friction_oracles(green_run):
    _, _, res = green_run
    b_err = res.b_visc / B_TRUTH - 1.0
    ic_err = res.i_c / IC_TRUTH - 1.0
    assert abs(b_err) <= 0.15, "B=%.3g err=%+.1f%%" % (res.b_visc, 100 * b_err)
    assert abs(ic_err) <= 0.15, "I_c=%.3f err=%+.1f%%" % (res.i_c, 100 * ic_err)


def test_t3_gain_oracles(green_run):
    _, _, res = green_run
    kp2_err = res.kp_vel / KP2_ORACLE - 1.0
    assert abs(kp2_err) <= 0.03, "KP2=%.4g err=%+.2f%%" % (res.kp_vel, 100 * kp2_err)
    assert abs(res.ki_vel_hz / KI2_ORACLE - 1.0) <= 0.005
    assert abs(res.kp_pos / KP3_ORACLE - 1.0) <= 0.005
    assert res.ff1_advisory == pytest.approx(1.0 / res.k_a, rel=1e-9)


def test_t3_one_sided_ka_tooth(green_run):
    """Regression tooth (Phase-1 naive-V/I sibling): WITHOUT the +- pulse
    cancellation the one-sided K_a stays friction-biased LOW while the
    matched-window difference recovers the truth."""
    _, _, res = green_run
    for run in res.evidence["pulse_runs"]:
        naive_bias = 1.0 - run["k_a_naive"] / KA_TRUTH
        assert naive_bias >= 0.08, \
            "one-sided K_a should be biased low (got %+.1f%%)" % (-100 * naive_bias)
        assert abs(run["k_a_diff"] / KA_TRUTH - 1.0) <= 0.02


def test_t3_safety_sizing_and_rotation(green_run):
    """Tp sizing from the friction-corrected probe keeps the pulse under the
    1200 rpm guard (~725 rpm peak) and ~<1.2 rev per run."""
    _, _, res = green_run
    sz = res.evidence["sizing"]
    assert vp.TP_MIN_S <= sz["tp_s"] <= vp.TP_MAX_S
    guard_cnt = CA18 * 1200.0 / 60.0
    for run in res.evidence["pulse_runs"]:
        assert abs(run["v_peak"]) < guard_cnt
    assert sz["rev_est"] < 1.5


def test_t3_limits_written_and_restored(green_run):
    """SPEC §4: SD/HL[2]/LL[2]/ER[2] explicitly set for the run and restored
    to snapshot values afterwards; motor off; gains untouched (F1 separate)."""
    drive, _, res = green_run
    r = drive.regs
    assert r["MO"] == 0
    assert r["SD"] == pytest.approx(1e6)        # restored
    assert r["ER[2]"] == pytest.approx(1e8)
    assert r["HL[2]"] == pytest.approx(0) and r["LL[2]"] == pytest.approx(0)
    assert r["KP[2]"] == pytest.approx(KP2_ORACLE)   # not applied in Phase 2 run
    assert res.evidence["limits"]["SD"] == pytest.approx(4e6)  # was in force


def test_t3_snapshot_written(green_run):
    _, _, res = green_run
    import json
    path = res.evidence["snapshot_path"]
    assert os.path.isfile(path)
    snap = json.load(open(path, encoding="utf-8"))
    assert snap["readings"]["FF[1]"] == pytest.approx(1.726e-7)
    assert snap["readings"]["SD"] == pytest.approx(1e6)


def test_t3_motion_commands_gated(green_run):
    drive, _, _ = green_run
    sent = [(c, am) for c, am in drive.log
            if c.replace(" ", "").upper().startswith(("MO=1", "TC", "JV", "ST"))]
    assert sent and all(am for _, am in sent)


# ======================================================================================
# T4 margin-model regression (SPEC §7)
# ======================================================================================
def test_t4_margins_at_eas_point():
    """EAS gains + K_a*: vel PM 67.6+-1 / GM 15+-0.5 dB, pos PM 81.1+-1
    (probe-locked model: extra 1.5*TS velocity-loop delay)."""
    m = vel_pos_margins(KP2_ORACLE, KI2_ORACLE, KP3_ORACLE, KA_STAR,
                        KA_STAR * B_TRUTH, KP1_EAS, KI1_EAS, R_PP, L_PP,
                        TS_US * 1e-6)
    assert abs(m["pm_vel"] - 67.6) <= 1.0, m
    assert abs(m["gm_db"] - 15.0) <= 0.5, m
    assert abs(m["pm_pos"] - 81.1) <= 1.0, m
    assert abs(m["w_cv"] / (2 * math.pi) - 73.9) <= 2.0


def test_design_deterministic():
    p = AutotuneVPParams()
    des = design_vp_gains(KA_STAR, KA_STAR * B_TRUTH, TS_US * 1e-6, p,
                          KP1_EAS, KI1_EAS)
    assert des["ok"]
    assert des["kp2"] == pytest.approx(KP2_ORACLE, rel=0.001)
    assert des["ki2"] == pytest.approx(10.6997, rel=1e-4)
    assert des["kp3"] == pytest.approx(85.211, rel=1e-4)
    assert des["wcv"] == pytest.approx(457.5, rel=1e-9)


def test_window_slope_unit():
    t = np.arange(50) * 4e-4
    y = 3e6 * t + 123.0
    sl, off, r2 = window_slope(t, y)
    assert sl == pytest.approx(3e6, rel=1e-9)
    assert r2 == pytest.approx(1.0, abs=1e-12)


# ======================================================================================
# RED / abort paths (SPEC §1/§4/§5)
# ======================================================================================
def test_mo1_at_start_red_without_auto_disable(tmp_path):
    drive = VPSim(mo0=1)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "STOP" in res.reason
    assert not any(c.replace(" ", "").startswith("MO=0") for c, _ in drive.log)


def test_gs2_gain_scheduling_red(tmp_path):
    drive = VPSim(gs2=1)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "스케줄링" in res.reason
    assert all("=" not in c for c, _ in drive.log), "pre-power RED must be read-only"


def test_commutation_config_change_red(tmp_path):
    drive = VPSim(ca17=1)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "커뮤 변경감지" in res.reason
    assert not any(c.startswith("CA[7]") and "=" in c for c, _ in drive.log), \
        "CS/CA[7] writes are absolutely forbidden"


def test_commutation_sign_fault_aborts(tmp_path):
    """§1-3: sign(dv/dt) != sign(TC) during the probe -> immediate abort RED,
    with the TC-segment chain order TC=0 -> MO=0."""
    drive = VPSim(commut_sign=-1.0)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "부호" in res.reason
    cmds = [c.replace(" ", "") for c, _ in drive.log]
    i_tc = next(i for i, c in enumerate(cmds) if c == "TC=0" and i > 5)
    i_mo = next(i for i, c in enumerate(cmds) if i > i_tc and c == "MO=0")
    assert i_tc < i_mo
    assert drive.regs["MO"] == 0


def test_axis_clamped_at_cap_red(tmp_path):
    """[HIGH-1] DEFAULT cap (0.2*CL=4.24 A < 6 A drag): PART B must NOT run
    (drag torque would exceed the cap torque and ALWAYS follow -> healthy
    friction mis-routed to a commutation RED).  Generic honest RED with the
    판별-유보 note; UM never touched."""
    drive = VPSim(i_c=6.0)                   # stiction above the default cap
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "축 구속" in res.reason and "브레이크어웨이 없음" in res.reason
    assert "판별 유보" in res.reason                  # drag skipped, said so
    assert "um3_drag" not in res.evidence            # PART B gate held
    ba = res.evidence["breakaway"]
    assert not ba["detected"] and ba["i_ba_a"] is None
    assert ba["iq_at_cap_a"] > 0.5 * ba["i_cap_a"]   # torque was real
    assert drive.regs["UM"] == 5                     # never switched
    assert drive.regs["MO"] == 0
    assert drive.regs["SD"] == pytest.approx(1e6)    # limits restored on abort


def test_previous_stiction_red_case_now_tunes(tmp_path):
    """Intent regression for the 2026-07-13 rework: I_c=0.6 A (the OLD
    '기계구속' RED at the fixed 0.5 A diag current) must now break away via
    the adaptive ramp and identify correctly — this is the live failed-unit
    scenario (0.5 A cannot move it, ~2 A can)."""
    drive = VPSim(i_c=0.6)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    ba = res.evidence["breakaway"]
    assert ba["detected"] and ba["i_ba_a"] > 0.6
    assert res.evidence["unit_diag"]["i_diag_a"] > vp.UNITDIAG_I_A
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02
    assert abs(res.i_c / 0.6 - 1.0) <= 0.15


def test_overspeed_sw_guard_aborts(tmp_path):
    """|VX| crossing the 1200 rpm SW guard -> abort, limits restored.
    Cap-raise update: TC-segment oversizing is now owned by the 10 ms motion
    cut (rise per cut poll < cut->guard band for any i0 <= 0.4*CL), so the
    guard's own teeth are proven on the JV segment (NO cut path there):
    commanding 1500 rpm crosses the guard during settle -> RED with the JV
    abort chain (JV=0 -> ST -> MO=0)."""
    drive = VPSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path,
                                             jv_speeds_rpm=(300.0, 1500.0)))
    assert res.status == RED and "과속" in res.reason
    cmds = [c.replace(" ", "") for c, _ in drive.log]
    i_jv0 = len(cmds) - 1 - cmds[::-1].index("JV=0")     # abort A1
    i_st = next(i for i, c in enumerate(cmds) if i > i_jv0 and c == "ST")
    i_mo = next(i for i, c in enumerate(cmds) if i > i_st and c == "MO=0")
    assert i_jv0 < i_st < i_mo
    assert drive.regs["MO"] == 0
    assert drive.regs["SD"] == pytest.approx(1e6)    # limits restored on abort


def test_mainpulse_motion_cut_saves_slow_oversize(tmp_path):
    """Counterpart of the guard test: a REALISTIC mis-sizing (the net-current
    model assumes running friction ~0.75*i_ba, but this plant runs at 0.1 A —
    actual net current ~2x the model) drives the pulse past the sizing target
    toward the guard; the motion cut TRUNCATES it and the run SURVIVES on the
    captured window (visible warning) — mis-sizing is no longer fatal.
    (The old absurd-tp_target scenario is now neutralized upstream by the
    target clamp <= 0.8*cut, so the teeth moved to the model-mismatch path.)"""
    drive = HiStictionLowRunSim(i_s=2.0, i_c=0.1)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW, (res.status, res.reason, res.warnings)
    assert "과속" not in res.reason
    assert any("조기종료" in w for w in res.warnings)
    assert res.evidence.get("pulse_early_stops")
    guard_cnt = CA18 * 1200.0 / 60.0
    for run in res.evidence["pulse_runs"]:
        assert abs(run["v_peak"]) < guard_cnt
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02     # window analysis intact


def test_jv_asymmetry_red(tmp_path):
    """Direction-dependent friction beyond x2 -> commutation/mechanics RED
    (JV-segment data already collected; motor safed)."""
    class AsymSim(VPSim):
        def _step(self, nk):
            # asymmetric Coulomb: strong +, weak -
            self.C = self.k_a * (0.2 if self.v >= 0 else 0.04)
            VPSim._step(self, nk)

    drive = AsymSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "비대칭" in res.reason
    assert drive.regs["MO"] == 0


def test_nan_response_aborts(tmp_path):
    drive = VPSim()
    drive.regs["BV"] = float("nan")
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "NaN" in res.reason


def test_hl_write_refused_is_warning_not_red(tmp_path):
    """U-P4: HL[2]/LL[2] refusal -> warnings only (SW guard covers), YELLOW."""
    drive = VPSim(hl_writable=False)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW
    assert any("HL[2]" in w for w in res.warnings)
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02     # measurement unaffected


# ======================================================================================
# B1.5 UNIT-DIAG (SPEC §9 — 125x discriminator + hard gate)
# ======================================================================================
def test_unit_diag_nominal_units_pass(green_run):
    """(b) both-direction tooth, healthy side: with correct units the diag
    reports s~1 / g~1, adopts NO corrections, and the hard gate passes.
    §9 raw-array evidence mandate (diag + main pulses + VX poll log)."""
    _, _, res = green_run
    ud = res.evidence["unit_diag"]
    assert ud["gate_pass"]
    assert abs(ud["s"] - 1.0) <= 0.05 and abs(ud["g"] - 1.0) <= 0.10
    assert ud["s_scale_adopted"] == 1.0 and ud["g_dt_adopted"] == 1.0
    assert ud["s2_vx"] is None or abs(ud["s2_vx"] - 1.0) <= 0.10
    assert len(ud["raw"]["pos"]) > 50 and len(ud["raw"]["i_cmd"]) > 50
    assert len(ud["vx_poll"]) >= 5
    for run in res.evidence["pulse_runs"]:
        assert len(run["raw"]["pos"]) > 50             # 요약만 금지 (run-1 재발방지)


def test_unit_diag_velocity_scale_detected_corrected(tmp_path, green_run):
    """(a) the live-1/125 hypothesis: recorded Velocity in internal units,
    Position in true counts.  B1.5 must detect s~125 (VX second path agrees),
    adopt the correction, and the WHOLE pipeline recovers truth K_a/gains.
    YELLOW = honest (scale correction applied; U-P9 pending live)."""
    drive = VPSim(vel_scale_err=1.0 / 125.0)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW, (res.status, res.reason, res.warnings)
    assert any("U-P9" in w for w in res.warnings)
    ud = res.evidence["unit_diag"]
    assert abs(ud["s"] / 125.0 - 1.0) <= 0.05          # detected
    assert ud["s2_vx"] is not None and abs(ud["s2_vx"] / 125.0 - 1.0) <= 0.10
    assert ud["gate_pass"] and ud["s_scale_adopted"] == pytest.approx(ud["s"])
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02       # K_a restored post-correction
    assert abs(res.kp_vel / KP2_ORACLE - 1.0) <= 0.03
    assert abs(res.ki_vel_hz / KI2_ORACLE - 1.0) <= 0.005
    # (3) Position-only accel is the FINAL JUDGE — identical whether the
    # Velocity channel is scaled or not (channel-agnostic invariant)
    _, _, res_nom = green_run
    ka_pos_nom = res_nom.evidence["unit_diag"]["ka_pos"]
    assert abs(ud["ka_pos"] / ka_pos_nom - 1.0) <= 0.05


def test_unit_diag_torque_not_applied_red(tmp_path):
    """(c) physics-anomaly branch: I_active=0 while the command channel shows
    the pulse -> dPos~0 -> RED '토크미인가' with the MO/SR/MF/LC log."""
    drive = VPSim(torque_disabled=True)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "토크미인가" in res.reason
    ud = res.evidence["unit_diag"]
    assert "drive_logs" in ud
    assert abs(ud["d_pos_cnt"]) < 200.0
    assert ud["mean_i_cmd"] > 0.3 and ud["mean_i_act"] < 0.1
    assert drive.regs["MO"] == 0


def test_unit_diag_hard_gate_red_on_broken_velocity(tmp_path):
    """Hard-gate tooth: a NONLINEARLY broken Velocity channel (scale+offset)
    cannot be fixed by one scale factor — the Position cross-check (3) must
    refuse (>10% mismatch) -> RED, and the main pulses never run."""
    drive = VPSim(vel_garbage=True)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "하드게이트" in res.reason
    assert "pulse_runs" not in res.evidence            # gated BEFORE main pulses
    assert drive.regs["MO"] == 0


# ======================================================================================
# B1.4 adaptive breakaway ramp + UNIT-DIAG wall-clock timing (2026-07-13)
# ======================================================================================
def test_breakaway_adaptive_probe_low_vs_high_friction(tmp_path):
    """(a) the ramp finds i_ba just above the true stiction, records it, and
    sizes probe = clip(1.5*i_ba, probe_i_a, 0.2*CL[1]) — DIFFERENT probes for
    low- vs high-friction plants, both identifying K_a correctly."""
    probes = {}
    for ic in (0.2, 1.2):
        drive = VPSim(i_c=ic)
        res = run_velpos_autotune(drive, _params(drive, tmp_path / str(ic)))
        assert res.status in (GREEN, YELLOW), (ic, res.status, res.reason)
        ba = res.evidence["breakaway"]
        assert ba["detected"]
        assert ic < ba["i_ba_a"] <= ic + 0.35        # prompt, just above I_s
        assert ba["probe_i_a_adapted"] == pytest.approx(
            min(max(1.5 * ba["i_ba_a"], 0.25), 0.2 * CL1))
        assert len(ba["trace_tc_dpx_vx"]) >= 2       # ramp trace evidence
        assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02, (ic, res.k_a)
        assert res.evidence["jv"]["i_ba_prior_a"] == ba["i_ba_a"]
        probes[ic] = ba["probe_i_a_adapted"]
    assert probes[1.2] > 2.0 * probes[0.2]           # adapts with friction


def test_unit_diag_g_uses_measured_wall_clock(tmp_path):
    """(c) live run-2 timing bug: serial VX round-trips stretch the REAL pulse
    to ~125 ms while the nominal reference stays 80 ms — the OLD
    g = 0.080/(N*dt) would read ~0.64 and wrongly adopt a dt factor.  With a
    sleep_fn stretched x1.5625 and an accurate injected clock, the measured
    T_host must be ~125 ms, g ~ 1, and NO dt correction adopted."""
    drive = VPSim()
    stretch = 1.5625                                  # 80 ms -> 125 ms (live)
    params = _params(drive, tmp_path,
                     sleep_fn=lambda d: drive.advance(d * stretch),
                     clock_fn=lambda: drive.t,
                     tp_target_rpm=500.0)             # stretched pulses < guard
    res = run_velpos_autotune(drive, params)
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    ud = res.evidence["unit_diag"]
    assert ud["t_pulse_src"] == "measured(clock_fn)"
    assert ud["t_pulse_host_s"] == pytest.approx(vp.UNITDIAG_T_S * stretch,
                                                 rel=0.06)
    assert abs(ud["g"] - 1.0) <= 0.10                 # measured time -> g~1
    assert ud["g_dt_adopted"] == 1.0 and ud["s_scale_adopted"] == 1.0
    # the OLD nominal-reference formula would have claimed a dt factor:
    g_old = vp.UNITDIAG_T_S / (ud["n_pulse"] * ud["dt_assumed_s"])
    assert g_old < 0.75, "old formula must show the ~0.64 artifact (got %.3f)" \
        % g_old
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02      # pipeline unharmed


def test_high_stiction_unit_diag_position_ka_no_125x(tmp_path):
    """(d) the live failed unit (0.5 A cannot move the geared rotor): the
    breakaway-adapted diag current ACTUALLY moves it, UNIT-DIAG judges via the
    position-based accel, the hard gate passes with NO 125x-style corrections
    (s=1, g=1), and the pipeline completes with the true K_a."""
    drive = VPSim(i_c=1.2)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    ud = res.evidence["unit_diag"]
    assert ud["i_diag_a"] > vp.UNITDIAG_I_A           # adaptive current used
    assert abs(ud["d_pos_cnt"]) > vp.UNITDIAG_MIN_DPOS  # rotor actually moved
    assert ud["gate_pass"] and ud["ka_dev"] <= vp.UNITDIAG_KA_TOL
    assert ud["s_scale_adopted"] == 1.0 and ud["g_dt_adopted"] == 1.0  # no 125x
    assert abs(ud["s"] - 1.0) <= 0.05 and abs(ud["g"] - 1.0) <= 0.10
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02
    assert abs(res.i_c / 1.2 - 1.0) <= 0.15


# ======================================================================================
# hardening round 2 (fable-critic): windup rejection / early-stop / honest IQ /
# current-channel guard / nominal-floor branch (2026-07-13)
# ======================================================================================
class WindupSim(VPSim):
    """Backlash/compliance windup: a ONE-SHOT +2000 cnt PX jump when TC first
    exceeds 0.3 A (spring winds up, then SATURATES — no further motion, no
    velocity signature); the TRUE breakaway is at i_c=1.4 A."""

    def __init__(self, windup_at=0.3, windup_cnt=2000.0, **kw):
        kw.setdefault("i_c", 1.4)
        VPSim.__init__(self, **kw)
        self.windup_at = float(windup_at)
        self.windup_cnt = float(windup_cnt)
        self.wound = False

    def _query(self, name):
        if name == "PX":
            off = self.windup_cnt if self.wound else 0.0
            return "%.6f" % (self.p + off)
        return VPSim._query(self, name)

    def _write(self, name, v):
        out = VPSim._write(self, name, v)
        if name == "TC" and abs(v) >= self.windup_at:
            self.wound = True
        return out


def test_breakaway_rejects_windup_single_jump(tmp_path):
    """[#1 MEDIUM] cumulative-dpx regression: a one-shot windup jump at 0.3 A
    must NOT latch i_ba (the old |px-px0| test would self-satisfy '2연속'
    forever and freeze i_ba~0.36 A -> probe too small -> the exact false RED
    this ramp was built to remove).  Per-poll DELTA detection must ride
    through the jump and latch at the TRUE breakaway ~1.4 A."""
    drive = WindupSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    ba = res.evidence["breakaway"]
    assert drive.wound                                   # windup DID happen
    tr = ba["trace_tc_dpx_vx"]
    assert any(d > 400.0 and tc < 1.0 for tc, d, vv, _ph in tr), \
        "the one-shot jump must be visible in the trace (and rejected)"
    assert ba["i_ba_a"] > 1.4, \
        "i_ba latched below the true breakaway: %.3f (windup accepted?)" \
        % ba["i_ba_a"]
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


class HiStictionLowRunSim(VPSim):
    """High STATIC friction (i_s) with LOW running Coulomb friction (i_c):
    the adaptive diag current is large while the moving rotor barely brakes —
    the 80 ms pulse would cross the 1200 rpm guard without the early-stop."""

    def __init__(self, i_s=2.0, **kw):
        kw.setdefault("i_c", 0.1)
        VPSim.__init__(self, **kw)
        self.i_s = float(i_s)

    def _step(self, nk):
        self.C = self.k_a * (self.i_s if abs(self.v) < 1.0 else self.i_c)
        VPSim._step(self, nk)


def test_unit_diag_early_stop_prevents_overspeed(tmp_path):
    """[#2 MEDIUM] adaptive i_diag ~3.2 A + low running friction: without the
    early-stop the diag pulse crosses 1200 rpm inside the nominal 80 ms (safe
    abort, run dies).  The 500 rpm motion early-stop must cut the pulse, the
    analysis proceeds on the captured window, and the pipeline completes with
    the true K_a — no 과속 abort anywhere."""
    drive = HiStictionLowRunSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    ud = res.evidence["unit_diag"]
    assert ud["i_diag_a"] > 2.5                          # adaptive current engaged
    assert ud["early_stop"] is True
    assert ud["t_pulse_nominal_s"] < vp.UNITDIAG_T_S     # pulse actually cut
    assert ud["gate_pass"]
    # teeth: at this accel the uncut 80 ms pulse WOULD have crossed the guard
    accel = KA_TRUTH * (ud["i_diag_a"] - 0.1)
    assert accel * vp.UNITDIAG_T_S > CA18 * 1200.0 / 60.0
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


def test_breakaway_iq_unreadable_defers_honestly(tmp_path):
    """[#3 LOW] cap + no motion + IQ unparseable: no false 'IQ witnessed the
    torque' claim — defer to the UNIT-DIAG physics branch (which re-derives
    the discrimination from RECORDED currents with full logs)."""
    class NoIqClampSim(VPSim):
        def __init__(self, **kw):
            kw.setdefault("i_c", 6.0)                    # clamped beyond cap
            VPSim.__init__(self, **kw)

        def _query(self, name):
            if name == "IQ":
                return "n/a"
            return VPSim._query(self, name)

    drive = NoIqClampSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    # the RAMP itself must not claim the axis is clamped (its IQ witness was
    # unreadable) — the final verdict comes from the UNIT-DIAG escalation
    # ladder, whose RECORDED currents legitimately witness the torque
    assert any("IQ 판독불가" in w for w in res.warnings)
    assert res.evidence["breakaway"]["iq_at_cap_a"] is None
    assert "기계구속" in res.reason and "상향" in res.reason
    assert drive.regs["MO"] == 0


def test_unit_diag_current_channel_broken_explicit_red(tmp_path):
    """[#4 LOW] rotor moved (dPos big) but the RECORDED Active Current never
    crosses 0.5*i_diag: must be an explicit '전류채널 이상' RED, not the opaque
    IndexError/ZeroDivision '내부 예외' the generic handler would report."""
    class BadCurrentChanSim(VPSim):
        def _chan(self, name):
            if name == "Active Current [A]":
                return self.i_act * 0.01                 # recorder channel broken
            return VPSim._chan(self, name)

    drive = BadCurrentChanSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED and "전류채널 이상" in res.reason
    assert "내부 예외" not in res.reason
    assert abs(res.evidence["unit_diag"]["d_pos_cnt"]) > vp.UNITDIAG_MIN_DPOS
    assert drive.regs["MO"] == 0


def test_unit_diag_nominal_floor_branch(tmp_path):
    """[#5 LOW] clock_fn NOT homogeneous with sleep_fn (frozen clock = the
    un-injected-sim class): the physical nominal floor must engage, be labeled
    honestly, and the diag still passes with g~1 and no corrections."""
    drive = VPSim()
    params = _params(drive, tmp_path, clock_fn=lambda: 0.0)   # out-of-band clock
    res = run_velpos_autotune(drive, params)
    assert res.status in (GREEN, YELLOW), (res.status, res.reason)
    ud = res.evidence["unit_diag"]
    assert ud["t_pulse_src"] == "nominal-floor"
    assert ud["t_pulse_host_s"] == pytest.approx(vp.UNITDIAG_T_S)
    assert abs(ud["g"] - 1.0) <= 0.10
    assert ud["g_dt_adopted"] == 1.0 and ud["s_scale_adopted"] == 1.0
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


# ======================================================================================
# backlash false-positive fix: RAMP->HOLD-CONFIRM + UNIT-DIAG escalation
# (fable-physics field verdict 2026-07-13: live i_ba=1.01 A was a lash
#  traversal, 4166 cnt = 0.76 deg output; true load breakaway > 1.52 A)
# ======================================================================================
class GearLashSim(VPSim):
    """Geared axis with BACKLASH + load-side static friction: inside the free
    play the rotor flies on its OWN inertia (k_a_free, tiny Coulomb); at the
    lash end it engages the load (inelastic, v->0) and further motion needs
    i > i_s_load; once broken away it runs on the normal plant (i_c).
    Engagement is permanent (teeth stay in contact) — a simplification that is
    sufficient to prove the ramp classification."""

    def __init__(self, lash_cnt=4500.0, i_s_load=2.5, i_c_free=0.05,
                 k_a_free_mult=3.0, **kw):
        kw.setdefault("i_c", 0.2)
        VPSim.__init__(self, **kw)
        self.lash_left = float(lash_cnt)
        self.i_s_load = float(i_s_load)
        self.i_c_free = float(i_c_free)
        self.k_a_free = self.k_a * float(k_a_free_mult)
        self.engaged = False

    def _step(self, nk):
        if self.engaged:
            self.C = self.k_a * (self.i_s_load if abs(self.v) < 1.0
                                 else self.i_c)
            VPSim._step(self, nk)
            return
        # free-play flight: rotor-only inertia, tiny Coulomb, no load
        cmd = self._cmd_current()
        if self.torque_disabled:
            self.i_act = 0.0
        else:
            self.i_act = self.a_i * self.i_act + (1 - self.a_i) * self.cmd_prev
        self.cmd_prev = cmd
        drive = self.commut_sign * self.k_a_free * self.i_act
        c_free = self.k_a_free * self.i_c_free
        if abs(self.v) < 1.0 and abs(drive) <= c_free:
            self.v = 0.0
        else:
            sgn = math.copysign(1.0, self.v) if abs(self.v) >= 1.0 \
                else math.copysign(1.0, drive)
            v_new = self.v + self.dt * (drive - c_free * sgn)
            if self.v * v_new < 0.0 and abs(drive) <= c_free:
                v_new = 0.0                     # Karnopp clamp (same as base)
            self.v = v_new
        dp = self.dt * self.v
        if dp > 0:
            self.lash_left -= dp
            if self.lash_left <= 0:
                dp += self.lash_left            # clamp at the lash end
                self.lash_left = 0.0
                self.v = 0.0                    # inelastic engagement
                self.engaged = True
        self.p += dp
        self.v_meas = self.v + nk
        if self._rec and self._rec["left"] > 0:
            r = self._rec
            if r["k"] % r["tres"] == 0:
                for nm in r["names"]:
                    r["bufs"][nm].append(self._chan(nm))
                r["left"] -= 1
            r["k"] += 1
        self.t += self.dt


class StictionRiseSim(VPSim):
    """Stiction RISES after the breakaway ramp (detent/re-mesh analogue): the
    ramp honestly measures a small i_ba, but by UNIT-DIAG time the axis needs
    i_rise to move — exercises the escalation ladder in isolation."""

    def __init__(self, i_rise=1.5, **kw):
        kw.setdefault("i_c", 0.2)
        VPSim.__init__(self, **kw)
        self.i_rise = float(i_rise)
        self.risen = False

    def _write(self, name, v):
        out = VPSim._write(self, name, v)
        if name == "TC" and v == 0.0:
            self.risen = True                    # first TC=0 = ramp end
        return out

    def _step(self, nk):
        if self.risen:
            self.C = self.k_a * (self.i_rise if abs(self.v) < 1.0
                                 else self.i_c)
        else:
            self.C = self.k_a * self.i_c
        VPSim._step(self, nk)


def test_gear_lash_ramp_classifies_and_finds_true_breakaway(tmp_path):
    """(a) FIELD CASE: the low-current lash burst must be classified as STALL
    (finite travel, recorded in lash_events), the ramp RESUMES, and the TRUE
    load breakaway (~2.5 A) is latched by the HOLD-CONFIRM sustain rule; the
    adapted diag current really moves the rotor -> pipeline completes with the
    true K_a and NO 125x corrections.

    HIGH-fix teeth (fable-critic): NO i_pulse_frac override — with the DEFAULT
    0.10 the OLD sizing had i0=2.12 A < 2.5 A stiction -> motion retry doubled
    i0 to 4.24 A with the STALE tp=71 ms -> 1200 rpm guard crossed at ~56 ms
    -> false RED.  Mover-floored i0 + per-i0 tp resize must pass on defaults."""
    drive = GearLashSim()                        # lash 4500 cnt, load 2.5 A
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    ba = res.evidence["breakaway"]
    assert ba["detected"]
    assert 2.5 < ba["i_ba_a"] <= 2.9, ba["i_ba_a"]   # TRUE breakaway, not ~0.13
    assert len(ba["lash_events"]) >= 1               # burst classified as lash
    for lev in ba["lash_events"]:
        assert lev["travel_cnt"] < 6000.0            # finite travel = backlash
        assert lev["tc_a"] < 1.0                     # happened at LOW current
    assert any(ph == "HOLD" for *_x, ph in ba["trace_tc_dpx_vx"])
    ud = res.evidence["unit_diag"]
    assert ud["i_diag_a"] > 3.0                      # adapted from the true i_ba
    assert ud["s_scale_adopted"] == 1.0 and ud["g_dt_adopted"] == 1.0
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02
    assert drive.engaged


def test_main_pulse_sized_by_proven_mover_no_overspeed(tmp_path):
    """[HIGH] order-killer regression (fable-critic): stiction 2.5 A /
    running 0.2 A unit with DEFAULT params.  OLD path: i0=2.12<2.5 -> first
    pulse no motion -> retry i0=4.24 with tp STILL 71 ms -> accel 2.34e7
    cnt/s^2 -> |VX| crosses the 1.31e6 guard at ~56 ms -> false RED.  NEW
    path: i0 floored at the proven mover current identifies on the FIRST
    pulse pair, tp resized per i0, every pulse peak under the guard."""
    drive = GearLashSim()                            # defaults everywhere
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    assert "과속" not in res.reason
    sz = res.evidence["sizing"]
    assert sz["i_mover_a"] == res.evidence["unit_diag"]["i_diag_a"]
    assert sz["i0_a"] >= res.evidence["breakaway"]["i_ba_a"]   # mover floor
    assert sz["i0_a"] >= sz["i_mover_a"]
    assert vp.TP_MIN_S <= sz["tp_s"] <= vp.TP_MAX_S
    guard_cnt = CA18 * 1200.0 / 60.0
    for run in res.evidence["pulse_runs"]:
        assert abs(run["v_peak"]) < guard_cnt            # never near the abort
    assert not any("모션부족" in w for w in res.warnings)  # FIRST-try motion
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


def test_hold_confirm_sustain_vs_stall_branches(green_run, tmp_path):
    """(b) HOLD-CONFIRM branch pair: a plain plant SUSTAINS at the detection
    current (no lash events); the geared plant STALLS first (lash event
    recorded) and only sustains at the load breakaway."""
    _, _, res_nom = green_run
    ba_nom = res_nom.evidence["breakaway"]
    assert ba_nom["lash_events"] == []               # sustain branch
    assert 0.2 < ba_nom["i_ba_a"] <= 0.55
    drive = GearLashSim(i_s_load=2.0)                # default i0=2.12 > 2.0
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason)
    ba = res.evidence["breakaway"]
    assert len(ba["lash_events"]) >= 1 and ba["i_ba_a"] > 2.0   # stall branch
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


def test_unit_diag_escalation_recovers_low_probe(tmp_path):
    """(c) dual defense: stiction rises after the ramp so the ramp-sized diag
    current cannot move the axis — the escalation ladder must find a mover,
    adopt s/g/K_a from the SUCCESSFUL pulse, feed the proven current forward
    to the B1 probe, and the pipeline completes (YELLOW: escalations are
    visible warnings)."""
    drive = StictionRiseSim(i_rise=1.5)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == YELLOW, (res.status, res.reason, res.warnings)
    assert any("상향" in w for w in res.warnings)
    ud = res.evidence["unit_diag"]
    assert len(ud["escalations"]) >= 1
    assert ud["i_diag_a"] > 1.5                      # final successful rung
    assert ud["gate_pass"]
    assert ud["s_scale_adopted"] == 1.0 and ud["g_dt_adopted"] == 1.0
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


def test_unit_diag_escalation_exhausted_cap_red(tmp_path):
    """(d) truly constrained axis (stiction above the cap, arising after the
    ramp): the ladder exhausts at 0.2*CL[1] and only then the honest final RED
    '축 구속/고마찰(기계구속)' fires, escalation history in evidence."""
    drive = StictionRiseSim(i_rise=6.0)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "기계구속" in res.reason and "상향" in res.reason
    ud = res.evidence["unit_diag"]
    assert ud["i_diag_a"] == pytest.approx(0.2 * CL1)   # last rung = the cap
    assert len(ud["escalations"]) == 3                  # 0.5/0.75/1.125 failed
    assert drive.regs["MO"] == 0


# ======================================================================================
# PART A/B (fable-physics cap-raise + UM=3 drag discrimination, 2026-07-13)
# ======================================================================================
def test_raised_cap_finds_high_iba_and_identifies(tmp_path):
    """PART A: live-class unit (i_ba above the retired 0.2*CL cap): with
    ramp_frac=0.4 the FAST-POLL ramp (VX-only, 10 ms above 2 A) catches the
    high-current breakaway, HOLD confirms INSTANTLY at 300 rpm (no overspeed
    anywhere), the pulse ceiling unlocks past 0.2*CL, and the pipeline
    identifies the true K_a.  Windup-curve points captured at 1/2/4 A."""
    drive = HiStictionLowRunSim(i_s=4.5, i_c=1.0)
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.4))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    assert "과속" not in res.reason
    ba = res.evidence["breakaway"]
    assert ba["i_cap_a"] == pytest.approx(0.4 * CL1)
    assert ba["i_ba_a"] > 0.2 * CL1                  # beyond the OLD cap
    assert any(ph == "RAMPF" for *_x, ph in ba["trace_tc_dpx_vx"])
    sz = res.evidence["sizing"]
    assert sz["i0_a"] > 0.2 * CL1                    # pulse ceiling unlocked
    assert sz["i0_a"] >= sz["i_ba_floor_a"] - 1e-9
    assert sz["i0_a"] >= sz["i_mover_a"] - 1e-9
    guard_cnt = CA18 * 1200.0 / 60.0
    for run in res.evidence["pulse_runs"]:
        assert abs(run["v_peak"]) < guard_cnt
    wc = res.evidence["windup_curve"]
    assert [int(q["tc_a"]) for q in wc["points"]] == [1, 2, 4]
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


def test_um3_drag_routes_commutation_fault(tmp_path):
    """PART B: UM=5 torque efficiency 30% (commutation mis-mapping analogue —
    IQ real, shaft torque derated): no breakaway even at the raised cap, but
    the UM=3 stator drag (commutation-AGNOSTIC) FOLLOWS both directions ->
    routed honest RED '커뮤테이션 토크효율' (never more current); UM restored;
    full 1..8 A windup curve captured on the way."""
    drive = VPSim(um5_eff=0.3, i_c=3.0)
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.4))
    assert res.status == RED
    assert "커뮤테이션" in res.reason and "CA[7]" in res.reason
    ba = res.evidence["breakaway"]
    assert not ba["detected"]
    assert ba["iq_at_cap_a"] > 0.5 * ba["i_cap_a"]   # IQ real (the deceit)
    drag = res.evidence["um3_drag"]
    assert drag["pa_effective"] is True
    assert drag["follow_ratio"] >= 0.9
    assert len(drag["directions"]) == 2
    assert all(d["follow"] >= 0.9 for d in drag["directions"])
    assert drag["directions"][0]["trace_pa_px"]      # 지령각-PX 추종 시계열
    # BG-armed integer PA: the mock ONLY moves on BG, so follow=1.0 proves
    # the code sends int PA + BG per step (HIGH-2 semantics teeth)
    assert any(c.replace(" ", "") == "BG" for c, _ in drive.log)
    wc = res.evidence["windup_curve"]
    assert [int(q["tc_a"]) for q in wc["points"]] == [1, 2, 4, 6, 8]
    assert drive.regs["UM"] == 5 and drive.regs["MO"] == 0
    assert drive.regs["SD"] == pytest.approx(1e6)


class BGIgnoredSim(VPSim):
    """PA/BG dead end (soft-limit clip / BG-inactive analogue): BG is
    acknowledged but the armed PA is NEVER applied — the stator angle stays
    frozen while the axis itself is movable (um5_eff keeps UM=5 from breaking
    away, so the drag oracle runs)."""

    def __init__(self, **kw):
        kw.setdefault("um5_eff", 0.3)
        kw.setdefault("i_c", 3.0)
        VPSim.__init__(self, **kw)

    def _apply_pa(self):
        v = getattr(self, "pa_pending", None)
        if v is not None:
            self.regs["PA"] = v          # readback moves, rotor does NOT
            self.pa_pending = None


def test_um3_pa_ineffective_honest_red(tmp_path):
    """[HIGH-2] PA sweep not effective (PX no response by 0.5 elec rev):
    honest '판별 불가' RED — NEVER a mechanical verdict (a dead stator
    command and a stuck axis are indistinguishable headless)."""
    drive = BGIgnoredSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.4))
    assert res.status == RED
    assert "판별 불가" in res.reason and "실효 미확인" in res.reason
    assert "기계 점검" not in res.reason             # no mechanical claim
    assert "커뮤테이션" not in res.reason            # no commutation claim
    drag = res.evidence["um3_drag"]
    assert drag["pa_effective"] is False
    assert drag["early_px_response_cnt"] < 0.2 * drag["early_expected_cnt"]
    assert drive.regs["UM"] == 5 and drive.regs["MO"] == 0


class PartialDragSim(VPSim):
    """Mechanical jam AFTER a finite drag travel: PA applies (early check
    passes) but the rotor jams once drag_budget_cnt is consumed -> partial
    follow < 0.9 (the honest mechanical-dominant slip case)."""

    def __init__(self, drag_budget_cnt=2000.0, **kw):
        kw.setdefault("um5_eff", 0.3)
        kw.setdefault("i_c", 3.0)
        VPSim.__init__(self, **kw)
        self.drag_budget = float(drag_budget_cnt)

    def _apply_pa(self):
        p_before = self.p
        VPSim._apply_pa(self)
        moved = abs(self.p - p_before)
        if moved > 0.0:
            if moved > self.drag_budget:
                import math as _m
                self.p -= _m.copysign(moved - self.drag_budget,
                                      self.p - p_before)
                self.drag_budget = 0.0
            else:
                self.drag_budget -= moved


def test_um3_partial_slip_mechanical_red(tmp_path):
    """[HIGH-2 4] partial follow (early response OK, then jam): the
    mechanical verdict fires but honestly labeled '슬립 또는 PA 미실효'
    (실기 특성화 owns the final word)."""
    drive = PartialDragSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.4))
    assert res.status == RED
    assert "슬립 또는 PA 미실효" in res.reason and "기계 점검" in res.reason
    drag = res.evidence["um3_drag"]
    assert drag["pa_effective"] is True              # early check passed
    assert drag["follow_ratio"] < 0.9
    assert drive.regs["UM"] == 5 and drive.regs["MO"] == 0


def test_poll_latency_cut_before_guard(tmp_path):
    """[MEDIUM] serial-latency analogue: every sleep stretched x2 (~60 ms
    effective poll pairs, the live-measured figure) with an accurate clock —
    the pulse overshoot must be caught by the 0.6*guard motion cut, never by
    the 1200 rpm guard (no 과속 RED), and identification completes."""
    drive = VPSim()
    res = run_velpos_autotune(drive, _params(
        drive, tmp_path,
        sleep_fn=lambda d: drive.advance(2.0 * d),
        clock_fn=lambda: drive.t))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    assert "과속" not in res.reason
    guard_cnt = CA18 * 1200.0 / 60.0
    for run in res.evidence["pulse_runs"]:
        assert abs(run["v_peak"]) < guard_cnt
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


class TransitDecaySim(VPSim):
    """LIVE raised-cap run analogue (fable-physics 개정6): at ~1.2 A the rotor
    is KICKED through a long free play (8634 cnt) with monotonically DECAYING
    velocity (the recorded 89k->68k->55k->6k HOLD signature — transit
    dissipation, NOT drive), lands, and the TRUE load breakaway is 5 A.
    The old magnitude-only sustain latched the fake i_ba=1.33 A here."""

    def __init__(self, kick_at=1.2, v0=89000.0, tau=0.11, travel=8634.0,
                 i_s_load=5.0, **kw):
        kw.setdefault("i_c", 0.2)
        VPSim.__init__(self, **kw)
        self.kick_at = float(kick_at)
        self.v_kick = float(v0)
        self.tau = float(tau)
        self.travel_left = float(travel)
        self.i_s_load = float(i_s_load)
        self.burst = False
        self.landed = False

    def _step(self, nk):
        cmd = self._cmd_current()
        if self.torque_disabled:
            self.i_act = 0.0
        else:
            self.i_act = self.a_i * self.i_act + (1 - self.a_i) * self.cmd_prev
        self.cmd_prev = cmd
        if self.landed:                      # engaged: hard load stiction
            drive = self.commut_sign * self.k_a * self.i_act * self.um5_eff
            c_hold = self.k_a * (self.i_s_load if abs(self.v) < 1.0
                                 else self.i_c)
            if abs(self.v) < 1.0 and abs(drive) <= c_hold:
                self.v = 0.0
            else:
                sgn = math.copysign(1.0, self.v) if abs(self.v) >= 1.0 \
                    else math.copysign(1.0, drive)
                acc = drive - self.D * self.v - self.k_a * self.i_c * sgn
                v_new = self.v + self.dt * acc
                if self.v * v_new < 0.0 and abs(drive) <= c_hold:
                    v_new = 0.0
                self.v = v_new
            self.p += self.dt * self.v
        elif self.burst:                     # decaying free-flight transit
            self.v *= math.exp(-self.dt / self.tau)
            dp = self.dt * self.v
            if dp >= self.travel_left:
                dp = self.travel_left
                self.v = 0.0
                self.burst = False
                self.landed = True
            self.travel_left -= dp
            self.p += dp
        else:                                # stuck pre-kick
            self.v = 0.0
            if abs(self.i_act) >= self.kick_at:
                self.burst = True
                self.v = self.v_kick
        self.v_meas = self.v + nk
        if self._rec and self._rec["left"] > 0:
            r = self._rec
            if r["k"] % r["tres"] == 0:
                for nm in r["names"]:
                    r["bufs"][nm].append(self._chan(nm))
                r["left"] -= 1
            r["k"] += 1
        self.t += self.dt


def test_transit_decay_stall_classified_true_iba_latched(tmp_path):
    """[개정6-1] the live fake: a decaying transit (89k->..->6k) must be
    classified STALL (collapse rule) and recorded as a lash event; the ramp
    keeps ramping PAST 1.33 A and latches the TRUE breakaway ~5 A; the
    pipeline identifies K_a on the real load."""
    drive = TransitDecaySim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.4))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    ba = res.evidence["breakaway"]
    assert ba["i_ba_a"] > 4.5, \
        "fake transit latched again: i_ba=%.2f" % ba["i_ba_a"]
    assert len(ba["lash_events"]) >= 1            # the transit, classified
    assert all(le["tc_a"] < 1.7 for le in ba["lash_events"])
    assert any(le.get("collapsed") for le in ba["lash_events"]), \
        "decay signature must be recorded as collapse"
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


class RiseJiggleSim(VPSim):
    """269 cnt residual free play appearing AFTER the ramp (re-mesh) + load
    stiction ABOVE the escalation cap: the first diag pulse jiggles 269 cnt
    (the live '이동>200cnt' false-success), later pulses do nothing."""

    def __init__(self, i_rise=9.5, jiggle_cnt=269.0, **kw):
        kw.setdefault("i_c", 0.2)
        VPSim.__init__(self, **kw)
        self.i_rise = float(i_rise)
        self.i_s = float(i_rise)             # UM3 drag threshold attribute
        self.jiggle_left = float(jiggle_cnt)
        self.risen = False

    def _write(self, name, v):
        out = VPSim._write(self, name, v)
        if name == "TC" and v == 0.0:
            self.risen = True                # ramp end
        return out

    def _step(self, nk):
        if not self.risen:
            self.C = self.k_a * self.i_c
            VPSim._step(self, nk)
            return
        cmd = self._cmd_current()
        self.i_act = self.a_i * self.i_act + (1 - self.a_i) * self.cmd_prev
        self.cmd_prev = cmd
        if self.jiggle_left > 0.0 and abs(self.i_act) > 0.3:
            dp = min(self.jiggle_left, 67250.0 * self.dt)   # ~4 ms crossing
            self.p += math.copysign(dp, self.i_act)
            self.jiggle_left -= dp
            self.v = (math.copysign(dp / self.dt, self.i_act)
                      if self.jiggle_left > 0.0 else 0.0)
        else:
            self.v = 0.0                     # stiction above every rung
        self.v_meas = self.v + nk
        if self._rec and self._rec["left"] > 0:
            r = self._rec
            if r["k"] % r["tres"] == 0:
                for nm in r["names"]:
                    r["bufs"][nm].append(self._chan(nm))
                r["left"] -= 1
            r["k"] += 1
        self.t += self.dt


def test_jiggle_escalates_not_success(tmp_path):
    """[개정6-2] a 269 cnt backlash jiggle (>200 cnt = the old success hole)
    must NOT pass the sustained-rotation success test — it escalates, exhausts
    at the default cap (<6 A: drag gate holds) and REDs honestly with the
    escalation history."""
    drive = RiseJiggleSim()                  # default ramp cap 4.24 A < 6 A
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "기계구속" in res.reason and "판별 유보" in res.reason
    ud = res.evidence["unit_diag"]
    assert len(ud["escalations"]) >= 1
    assert ud["escalations"][0]["mode"] in ("유격착지/꿈틀", "무이동")
    assert any(e["mode"] == "유격착지/꿈틀" for e in ud["escalations"]), \
        "the jiggle must be classified as non-sustained, not success"
    assert "um3_drag" not in res.evidence    # gate: cap 4.24 < 6 A
    assert drive.regs["MO"] == 0


def test_exhaustion_routes_drag_when_gate_met(tmp_path):
    """[개정6-3] '지속회전 없음' routing: ladder exhaustion (jiggle + 무이동)
    with the raised cap (8.49 A >= 6 A) must run the UM3 drag from the
    EXHAUSTION path; stiction 9.5 A blocks the 6 A drag -> honest '판별 불가'
    RED (never a bare 기계구속 verdict when the oracle could run)."""
    drive = RiseJiggleSim(i_rise=9.5)
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.4))
    assert res.status == RED
    assert "판별 불가" in res.reason
    assert "um3_drag" in res.evidence        # drag DID run from exhaustion
    assert res.evidence["um3_drag"]["pa_effective"] is False
    ud = res.evidence["unit_diag"]
    assert len(ud["escalations"]) >= 2       # jiggle then 무이동 rungs
    # fix-5: escalation levels recorded as windup-curve points
    wc = res.evidence["windup_curve"]
    assert any(q.get("src") == "unitdiag_escalation" for q in wc["points"])
    assert drive.regs["UM"] == 5 and drive.regs["MO"] == 0


def test_jv_noload_gate_adapts_to_iba(tmp_path):
    """[실기전 #1] geared unit with HIGH running friction (i_c=3.0 A > the
    legacy fixed 0.10*CL=2.12 A gate) and static breakaway ~5 A: the OLD
    fixed gate would kill the run at D1 AFTER K_a already succeeded; the
    adaptive gate max(0.10*CL, 1.2*i_ba) must pass it and identify B/I_c."""
    drive = HiStictionLowRunSim(i_s=5.0, i_c=3.0)
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.4))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason, res.warnings)
    jv = res.evidence["jv"]
    ba = res.evidence["breakaway"]
    assert ba["i_ba_a"] > 4.5
    assert jv["i_ss_max_a"] == pytest.approx(1.2 * ba["i_ba_a"])
    # teeth: the measured steady currents DID exceed the legacy fixed gate
    assert all(abs(q["i_ss"]) > 0.10 * CL1 for q in jv["points"])
    assert all(abs(q["i_ss"]) <= jv["i_ss_max_a"] for q in jv["points"])
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02
    assert abs(res.i_c / 3.0 - 1.0) <= 0.15


class LateLandSim(VPSim):
    """LATE lash landing + position noise (fable-critic MEDIUM-1 boundary):
    the rotor crosses a 400 cnt free play at ~50 ms INTO the diag pulse and
    freezes; the recorded Position carries +-2 cnt noise.  The old 2-point
    0.8 ms end-velocity diff could read that noise as >3000 cnt/s and pass
    the landing as sustained rotation — the 10 ms least-squares tail slope
    must reject it (escalation, never success)."""

    def __init__(self, i_rise=9.5, jiggle_cnt=400.0, delay_s=0.05, **kw):
        kw.setdefault("i_c", 0.2)
        VPSim.__init__(self, **kw)
        self.i_rise = float(i_rise)
        self.i_s = float(i_rise)             # UM3 drag threshold attribute
        self.jiggle_left = float(jiggle_cnt)
        self.delay_s = float(delay_s)
        self.risen = False
        self.t_on = None

    def _write(self, name, v):
        out = VPSim._write(self, name, v)
        if name == "TC":
            if v == 0.0:
                self.risen = True            # ramp end
                self.t_on = None
            elif self.risen and abs(v) > 0.3 and self.t_on is None:
                self.t_on = self.t           # diag pulse onset
        return out

    def _chan(self, name):
        if name == "Position":               # quantization/readout noise
            return float(round(self.p + self.rng.uniform(-2.0, 2.0)))
        return VPSim._chan(self, name)

    def _step(self, nk):
        if not self.risen:
            self.C = self.k_a * self.i_c
            VPSim._step(self, nk)
            return
        cmd = self._cmd_current()
        self.i_act = self.a_i * self.i_act + (1 - self.a_i) * self.cmd_prev
        self.cmd_prev = cmd
        late_now = (self.t_on is not None
                    and (self.t - self.t_on) >= self.delay_s)
        if late_now and self.jiggle_left > 0.0 and abs(self.i_act) > 0.3:
            dp = min(self.jiggle_left, 80000.0 * self.dt)   # ~5 ms crossing
            self.p += math.copysign(dp, self.i_act)
            self.jiggle_left -= dp
            self.v = (math.copysign(dp / self.dt, self.i_act)
                      if self.jiggle_left > 0.0 else 0.0)
        else:
            self.v = 0.0                     # stiction above every rung
        self.v_meas = self.v + nk
        if self._rec and self._rec["left"] > 0:
            r = self._rec
            if r["k"] % r["tres"] == 0:
                for nm in r["names"]:
                    r["bufs"][nm].append(self._chan(nm))
                r["left"] -= 1
            r["k"] += 1
        self.t += self.dt


def test_late_landing_with_noise_rejected_by_lsq_tail(tmp_path):
    """[실기전 #2] late landing passes the TRAVEL test (400 > min_late) — the
    decision falls entirely on the tail velocity: with +-2 cnt position noise
    the least-squares 10 ms slope must stay far below 3000 cnt/s ->
    유격착지/꿈틀 escalation, exhaustion, honest RED (never a false success)."""
    drive = LateLandSim()                    # default cap 4.24 < 6 A: no drag
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert "기계구속" in res.reason and "판별 유보" in res.reason
    ud = res.evidence["unit_diag"]
    esc0 = ud["escalations"][0]
    assert esc0["mode"] == "유격착지/꿈틀"
    assert esc0["late_travel_cnt"] > 200.0   # travel test PASSED (the trap)
    assert esc0["v_end_pos_cnt_s"] < 3000.0  # LSQ tail caught the freeze
    assert drive.regs["MO"] == 0


def test_ca7_other_motor_no_false_alarm(tmp_path):
    """Multi-motor workflow: CA[7] is a PER-MOTOR commutation value — a
    different motor (CA[7]=272) must NOT trip the preflight (the old
    hardcoded 438 expectation killed the run); CA[7] stays recorded in
    evidence and the CA[17]==5 config gate still owns validity."""
    drive = VPSim(ca7=272.0)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status in (GREEN, YELLOW), (res.status, res.reason)
    assert "커뮤 변경감지" not in res.reason
    assert res.evidence["readings"]["CA[7]"] == 272.0   # still recorded
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02
    # opt-in pin still gates (explicit expected_ca7 keeps its teeth)
    drive2 = VPSim(ca7=272.0)
    res2 = run_velpos_autotune(drive2, _params(drive2, tmp_path / "pin",
                                               expected_ca7=438.0))
    assert res2.status == RED and "커뮤 변경감지" in res2.reason
    assert all("=" not in c for c, _ in drive2.log)     # pre-power, read-only


def test_ramp_frac_above_abs_max_is_preflight_red(tmp_path):
    """0.6*CL automatic ramping is FORBIDDEN: ramp_frac beyond the 0.4 abs max
    -> pre-power RED (operator-approval constant, never a parameter path)."""
    drive = VPSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path, ramp_frac=0.6))
    assert res.status == RED and "ramp_frac" in res.reason
    assert all("=" not in c for c, _ in drive.log)   # pre-power, read-only


# ======================================================================================
# infra: record_start/record_fetch split (elmo_link wrapper contract)
# ======================================================================================
def test_elmo_link_record_is_start_plus_fetch():
    """ElmoLink.record() must be exactly record_start + record_fetch (duck
    test — no CLR needed)."""
    import elmo_link

    class FakeSelf:
        def __init__(self):
            self.calls = []

        def record_start(self, signals, length, time_resolution=1):
            self.calls.append(("start", tuple(signals), length, time_resolution))

        def record_fetch(self, timeout_s=10.0, poll_s=0.02):
            self.calls.append(("fetch", timeout_s))
            return {"X": np.array([1.0]), "dt": 4e-4}

    fake = FakeSelf()
    out = elmo_link.ElmoLink.record(fake, ["X"], 100, time_resolution=4,
                                    timeout_s=3.0)
    assert fake.calls[0] == ("start", ("X",), 100, 4)
    assert fake.calls[1][0] == "fetch"
    assert out["dt"] == pytest.approx(4e-4)


def test_vpsim_record_split_contract(tmp_path):
    """The mock recorder free-runs across advance() — samples taken while the
    pipeline keeps commanding (the reason for the split)."""
    d = VPSim()
    d.regs["MO"] = 1
    d.record_start(["Velocity", "Active Current [A]"], 100, time_resolution=4)
    d.command("TC=1.0", allow_motion=True)
    d.advance(100 * 4 * d.dt)
    out = d.record_fetch()
    assert len(out["Velocity"]) == 100
    assert out["dt"] == pytest.approx(4e-4)
    assert np.max(out["Active Current [A]"]) > 0.5   # pulse visible in-record


# ======================================================================================
# F1 / F2 separate operator actions
# ======================================================================================
def test_apply_gains_vp_writes_when_motor_off(tmp_path):
    drive = VPSim()
    res = AutotuneVPResult(status=GREEN, kp_vel=8.0e-5, ki_vel_hz=10.7,
                           kp_pos=85.2)
    ok, msg = apply_gains_vp(drive, res)
    assert ok, msg
    assert drive.regs["KP[2]"] == pytest.approx(8.0e-5)
    assert drive.regs["KI[2]"] == pytest.approx(10.7)
    assert drive.regs["KP[3]"] == pytest.approx(85.2)
    assert drive.regs["FF[1]"] == pytest.approx(1.726e-7)   # NEVER written
    assert not any(c == "SV" for c, _ in drive.log)


def test_apply_gains_vp_refuses_motor_on():
    drive = VPSim(mo0=1)
    ok, msg = apply_gains_vp(drive, AutotuneVPResult(
        status=GREEN, kp_vel=8e-5, ki_vel_hz=10.7, kp_pos=85.2))
    assert not ok and "MO=1" in msg


def test_verify_run_vp_is_honest_stub():
    res = verify_run_vp(VPSim())
    assert res.status == RED and "F2" in res.reason and "실기" in res.reason
