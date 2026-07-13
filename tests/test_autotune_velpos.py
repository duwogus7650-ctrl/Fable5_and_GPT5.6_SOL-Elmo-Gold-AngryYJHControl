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
                 hl_writable=True, mo0=0, mf=0, seed=1):
        # §9 fault-injection knobs:
        #  vel_scale_err: RECORDED Velocity = v_true * err (live 1/125
        #    hypothesis — internal units); VX polls stay TRUE cnt/s.
        #  torque_disabled: drive applies NO torque (I_active=0) while the
        #    Current Command channel shows the command (UNIT-DIAG physics RED).
        #  vel_garbage: Velocity channel nonlinearly broken (scale+offset) —
        #    a single scale factor cannot fix it -> hard gate must RED.
        self.vel_scale_err = float(vel_scale_err)
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
                     "CA[7]": ca7, "CA[17]": ca17, "CA[18]": CA18,
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
        drive = self.commut_sign * self.k_a * self.i_act
        if abs(self.v) < 1.0 and abs(drive) <= self.C:
            self.v = 0.0                        # stiction holds
        else:
            sgn = math.copysign(1.0, self.v) if abs(self.v) >= 1.0 \
                else math.copysign(1.0, drive)
            acc = drive - self.D * self.v - self.C * sgn
            self.v += self.dt * acc
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
        if name in ("HL[2]", "LL[2]") and not self.hl_writable:
            raise IOError("%s write refused (U-P4 tooth)" % name)
        regs[name] = v
        return ""

    def _query(self, name):
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
    return AutotuneVPParams(sleep_fn=drive.advance, snapshot_dir=str(tmpdir), **kw)


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


def test_static_friction_too_high_red(tmp_path):
    """I_c above even the UNIT-DIAG current -> caught EARLIER now (§9): the
    diag sees dPos~0 while I_active ~ I_cmd -> mechanical-constraint/stiction
    RED (previously the B1 probe caught this after a x2 retry)."""
    drive = VPSim(i_c=0.6)
    res = run_velpos_autotune(drive, _params(drive, tmp_path))
    assert res.status == RED
    assert ("정지마찰" in res.reason) or ("기계구속" in res.reason)
    assert drive.regs["MO"] == 0


def test_overspeed_sw_guard_aborts(tmp_path):
    """Oversized Tp target -> |VX| crosses the 1200 rpm SW guard mid-pulse ->
    abort (TC=0 then MO=0), limits restored."""
    drive = VPSim()
    res = run_velpos_autotune(drive, _params(drive, tmp_path,
                                             tp_target_rpm=5000.0))
    assert res.status == RED and "과속" in res.reason
    cmds = [c.replace(" ", "") for c, _ in drive.log]
    i_tc = len(cmds) - 1 - cmds[::-1].index("TC=0")
    i_mo = next(i for i, c in enumerate(cmds) if i > i_tc and c == "MO=0")
    assert i_tc < i_mo
    assert drive.regs["SD"] == pytest.approx(1e6)    # limits restored on abort


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
