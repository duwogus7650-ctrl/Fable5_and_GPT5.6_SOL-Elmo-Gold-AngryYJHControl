# -*- coding: utf-8 -*-
"""P3 slice 2 — physics_gates wired INTO the autotune pipelines (spec §7).

End-to-end through the real kernels (run_current_autotune /
run_velpos_autotune) with parameterized sims:

  * multi-motor matrix A~D (Phase-1 pipeline, TS in {50,100} us) — healthy
    runs land on their honest verdict (C = YELLOW by physics, never forced
    GREEN);
  * fault injection -> honest RED (kappa_R over-range, in-situ loop-gain
    corruption -> P1_RHO, delta>=60 deg commutation family: signature-band
    RED / K_a-drop RED / first-run expect-slip follow RED);
  * chicken-and-egg E2E: first run on a fresh profile takes the provisional
    path (band OFF), a GREEN finish establishes i_ba_ref/ka_baseline, the
    second run gates on the band, and a YELLOW run never re-baselines;
  * cross-contamination: two profiles alternating on one drive never touch
    each other's baselines;
  * literal trip-wire: the gate paths of autotune_current.py /
    autotune_velpos.py contain none of the retired EAS/field literals.

No hardware is touched anywhere in this file.
"""
import math
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autotune_current as at
import autotune_velpos as vp
import motor_profile as mp
import physics_gates as pg
from tests.test_autotune_current import SimDrive, _params as _p1_params
from tests.test_autotune_velpos import (VPSim, _params as _p2_params,
                                        KA_TRUTH, CL1, CA18, TS_US)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ======================================================================================
# helpers
# ======================================================================================
def _p1_drive(r_pp, l_pp, cl1, pole_pairs, ts_us, kp, ki, **kw):
    """Parameterized Phase-1 motor (spec §7 matrix rows)."""
    drive = SimDrive(r_pp=r_pp, l_pp=l_pp, ts_us=ts_us, kp=kp, ki=ki, **kw)
    drive.regs["CL[1]"] = cl1
    drive.regs["CL[3]"] = 2.0 * cl1
    drive.regs["PL[1]"] = 10.0 / 3.0 * cl1
    drive.regs["CA[19]"] = pole_pairs
    return drive


def _fresh_profile(name, pole_pairs=21, cl1=CL1):
    return mp.MotorProfile.from_sources(
        name,
        drive_readings={"CA[18]": CA18, "CA[19]": pole_pairs,
                        "CL[1]": cl1, "VH[2]": CA18 * 3600.0 / 60.0,
                        "TS": TS_US * 1e-6},
        user_settings={})


def _pg_statuses(res):
    return {k: v["status"]
            for k, v in (res.evidence.get("physics_gates") or {}).items()}


# ======================================================================================
# 1) multi-motor matrix A~D through the FULL Phase-1 pipeline
# ======================================================================================
def test_matrix_A_unit_green_all_physics_gates(tmp_path):
    """Case A (this unit, regression anchor): profile-derived verdicts must
    reproduce the frozen GREEN — same verdict as before the wiring."""
    drive = SimDrive()                       # exact legacy T3 drive (TS=100)
    res = at.run_current_autotune(drive, _p1_params(drive, tmp_path))
    assert res.status == at.GREEN, (res.status, res.reason, res.warnings)
    st = _pg_statuses(res)
    assert st == {"P1_PM": "GREEN", "P1_WC_BAND": "GREEN", "P1_RHO": "GREEN",
                  "P1_R_REL": "GREEN", "P1_L_REL": "GREEN"}
    # spot-check the evidence numbers against the motor-agnostic formulas
    kappa = res.evidence["physics_gates"]["P1_R_REL"]["detail"]["kappa_r"]
    vbus = res.evidence["scale"]["vbus_v"]
    assert kappa == pytest.approx(res.r_pp_ohm * 21.21 / vbus, rel=1e-6)


def test_matrix_B_coreless_green(tmp_path):
    """Case B (coreless, kappa_R upper region): R=8 ohm, L=0.8 mH, CL=1.4 A,
    p=4, TS=50 us -> honest GREEN with kappa_r ~ 0.23."""
    wc = 0.2010 / 50e-6
    drive = _p1_drive(8.0, 0.8e-3, 1.4, 4, 50, kp=wc * 0.8e-3,
                      ki=2.0 * 1.2705 * wc / (2 * math.pi), noise_a=0.002)
    # explicit high excitation freqs: at the default (auto) frequencies this
    # very resistive motor sits at |Z|~R and the pipeline retries with a
    # warning; 1200/2400 Hz give omega*L/R in 0.75..1.5 cleanly (< f_max=2500)
    res = at.run_current_autotune(
        drive, _p1_params(drive, tmp_path, sine_target_amp=0.25,
                          freqs_hz=(1200.0, 2400.0)))
    assert res.status == at.GREEN, (res.status, res.reason, res.warnings)
    st = _pg_statuses(res)
    assert st["P1_R_REL"] == "GREEN" and st["P1_L_REL"] == "GREEN"
    kappa = res.evidence["physics_gates"]["P1_R_REL"]["detail"]["kappa_r"]
    assert 0.15 <= kappa <= 0.35                     # upper-region GREEN
    assert abs(res.r_pp_ohm / 8.0 - 1.0) <= 0.05
    assert abs(res.l_pp_h / 0.8e-3 - 1.0) <= 0.05


def test_matrix_C_servo_high_tau_yellow_is_the_answer(tmp_path):
    """Case C (mid servo, high tau_e = 5 ms): the control-effort gate
    KP*CL/Vbus lands in the YELLOW window (0.6..1.5) -> the run is YELLOW.
    Spec §7: YELLOW is the CORRECT verdict — never forced GREEN."""
    wc = 0.2010 / 100e-6
    drive = _p1_drive(0.5, 2.5e-3, 8.5, 5, 100, kp=wc * 2.5e-3,
                      ki=0.5 / (2 * math.pi * 2.5e-3), noise_a=0.005)
    res = at.run_current_autotune(
        drive, _p1_params(drive, tmp_path, ki_rule="pole_zero",
                          sine_target_amp=1.0))
    assert res.status == at.YELLOW, (res.status, res.reason, res.warnings)
    st = _pg_statuses(res)
    assert st["P1_L_REL"] == "YELLOW", st
    eff = res.evidence["physics_gates"]["P1_L_REL"]["detail"]["ctrl_effort"]
    assert 0.6 < eff <= 1.5
    assert any("P1_L_REL" in w for w in res.warnings)
    # the identification itself is still correct on this motor
    assert abs(res.r_pp_ohm / 0.5 - 1.0) <= 0.05
    assert abs(res.l_pp_h / 2.5e-3 - 1.0) <= 0.05


def test_matrix_D_direct_drive_green(tmp_path):
    """Case D (direct drive, low L): R=60 mOhm, L=25 uH, CL=30 A, p=21,
    TS=50 us, pole-zero KI -> GREEN with healthy observability."""
    wc = 0.2010 / 50e-6
    drive = _p1_drive(0.060, 25e-6, 30.0, 21, 50, kp=wc * 25e-6,
                      ki=0.060 / (2 * math.pi * 25e-6), noise_a=0.005)
    res = at.run_current_autotune(
        drive, _p1_params(drive, tmp_path, ki_rule="pole_zero"))
    assert res.status == at.GREEN, (res.status, res.reason, res.warnings)
    st = _pg_statuses(res)
    assert st["P1_R_REL"] == "GREEN" and st["P1_L_REL"] == "GREEN"
    obs = res.evidence["physics_gates"]["P1_L_REL"]["detail"]["observability"]
    assert obs >= pg.L_OBSERVABILITY_MIN


# ======================================================================================
# 2) fault injection -> honest RED (Phase 1)
# ======================================================================================
def test_fault_kappa_r_over_range_red_pipeline(tmp_path):
    """R raised so that kappa_R = R*CL/Vbus > 0.7 -> P1_R_REL RED and the
    run verdict is RED (a physics violation is not a YELLOW).  The sim's
    resident gains are stiffened (KP=0.3, KI=2000) so the excitation can
    actually push current through 2 ohm — the kappa gate, not an injection
    failure, must own the verdict."""
    drive = SimDrive(r_pp=2.0, kp=0.3, ki=2000.0)  # kappa ~ 2*21.21/48.4=0.88
    res = at.run_current_autotune(drive, _p1_params(drive, tmp_path))
    assert res.status == at.RED, (res.status, res.reason)
    assert "P1_R_REL" in res.reason and "물리 게이트 RED" in res.reason
    assert _pg_statuses(res)["P1_R_REL"] == "RED"


class EffectiveGainDrive(SimDrive):
    """Run-#9 fault class at the mock's observable level: during SE the
    recorded command-error phasor is 2x what the REPORTED gains imply (the
    drive's effective error-to-voltage path disagrees with KP[1]/KI[1] by
    2x).  R-hat (DC) and L-hat (plant impedance) stay honest, every absolute
    backstop passes — only the in-situ loop-gain cross-check |C*G| (P1_RHO)
    can see the mismatch, and it must go RED (dev ~ +100%).  (A naive
    KP-doubling inside the loop is INVISIBLE by construction: the plant
    voltage is plant-determined and the mock's gamma model is gain-scale
    invariant — the fault must live in the err-phasor observable.)"""

    def _chan_value(self, name):
        v = SimDrive._chan_value(self, name)
        if name in ("Current Command [A]", "Total Current Command [A]") \
                and self.regs.get("TW[80]") == 1 and self.se_injects:
            # double the command-error observable AROUND the recorded current
            # (Icmd' - I) = 2*(Icmd - I) sample-by-sample -> the demodulated
            # err phasor doubles -> rho_meas doubles -> dev ~ +100%
            return self.iq_meas + 2.0 * (v - self.iq_meas)
        return v


def test_fault_effective_gain_mismatch_rho_red_pipeline(tmp_path):
    drive = EffectiveGainDrive()
    res = at.run_current_autotune(drive, _p1_params(drive, tmp_path))
    # the fault only corrupts the SE-window err phasor -> R/L stay honest
    assert res.status == at.RED, (res.status, res.reason)
    assert "P1_RHO" in res.reason
    st = _pg_statuses(res)
    assert st["P1_RHO"] == "RED"
    # the physical R/L stayed honest (the point of the rho cross-check)
    assert st["P1_R_REL"] != "RED" and st["P1_L_REL"] != "RED"
    for row in res.evidence["gates"]["G5_loopgain"]["rows"]:
        assert row["dev"] > 0.30                      # ~+100% at every f


# ======================================================================================
# 3) pole pairs: profile source + NEED_DATA refusal already covered in
#    tests/test_autotune_current.py (test_ca19_unreadable_*) — here only the
#    NEED_DATA-is-not-RED contract at the result level.
# ======================================================================================
def test_need_data_is_a_refusal_not_a_red(tmp_path):
    drive = SimDrive()
    drive.regs["CA[19]"] = 0
    res = at.run_current_autotune(drive, _p1_params(drive, tmp_path))
    assert res.status == at.NEED_DATA
    assert res.status not in (at.RED, at.YELLOW, at.GREEN)
    assert "abort" not in res.evidence           # nothing was energized


# ======================================================================================
# 4) Phase 2: delta>=60 deg commutation fault family -> honest RED
# ======================================================================================
def test_fault_delta_commutation_signature_band_red(tmp_path):
    """um5_eff=0.4 (cos delta -> delta ~ 66 deg): breakaway current inflates
    to ~1/0.4x the healthy baseline -> profile band ratio > 2.0 -> RED
    BEFORE any further motion (identification pulses never run)."""
    prof = _fresh_profile("band-red").with_green_run(i_ba_a=0.65,
                                                     k_a=KA_TRUTH)
    drive = VPSim(um5_eff=0.4, i_c=0.6)
    res = vp.run_velpos_autotune(
        drive, _p2_params(drive, tmp_path, profile=prof, synthetic=False))
    assert res.status == vp.RED, (res.status, res.reason)
    assert "서명 대역 RED" in res.reason
    sb = res.evidence["signature_band"]
    assert sb["status"] == "RED" and sb["detail"]["ratio"] > 2.0
    assert "pulse_runs" not in res.evidence      # stopped before main pulses
    assert drive.regs["MO"] == 0                 # abort chain safed


def test_fault_delta_ka_drop_red_via_profile(tmp_path):
    """K_a collapsed to 0.27x the PROFILE baseline (delta ~ 74 deg e) ->
    profile-scoped RED with the delta estimate; the profile is NOT
    re-baselined by the RED run."""
    prof = _fresh_profile("ka-red").with_green_run(i_ba_a=0.25, k_a=KA_TRUTH)
    path = prof.save(str(tmp_path))
    before = open(path, encoding="utf-8").read()
    drive = VPSim(k_a=0.27 * KA_TRUTH)
    res = vp.run_velpos_autotune(
        drive, _p2_params(drive, tmp_path, profile=prof, synthetic=False))
    assert res.status == vp.RED, (res.status, res.reason)
    assert "커뮤테이션 열화" in res.reason and "재커뮤" in res.reason
    kb = res.evidence["ka_baseline"]
    assert kb["source"] == "profile" and kb["verdict"] == "RED"
    assert abs(kb["ratio"] - 0.27) <= 0.02
    assert abs(kb["delta_e_deg_est"] - 74.0) <= 3.0
    assert open(path, encoding="utf-8").read() == before   # oracle rule
    assert drive.regs["MO"] == 0


def test_fault_first_run_expect_slip_follow_red(tmp_path):
    """Fresh profile (no baseline) + delta ~ 66 deg unit: UM=5 needs ~7.6 A
    to break away, but UM=3 at I_drag = i_ba/sqrt2 ~ 5.4 A FOLLOWS (the
    stator-angle drive bypasses commutation) -> first-run expect-slip RED."""
    prof = _fresh_profile("first-red")
    drive = VPSim(um5_eff=0.4, i_c=3.0)
    res = vp.run_velpos_autotune(
        drive, _p2_params(drive, tmp_path, profile=prof, synthetic=False,
                          ramp_frac=0.4))
    assert res.status == vp.RED, (res.status, res.reason)
    assert "첫런 불합격" in res.reason and "δ≥45°" in res.reason
    fr = res.evidence["sig_first_run"]
    assert fr["status"] == "RED"
    assert fr["detail"]["follow_ratio"] >= pg.UM3_FOLLOW
    # derived drag current, not the retired 6.0 literal
    iba = res.evidence["breakaway"]["i_ba_a"]
    assert fr["i_drag_a"] == pytest.approx(iba / math.sqrt(2.0), rel=1e-9)
    assert drive.regs["MO"] == 0 and drive.regs["UM"] == 5


class InconsistentDtVPSim(VPSim):
    """dt fault the correction layer CANNOT absorb: the recorder dt metadata
    is honest through UNIT-DIAG (records 1..3: ramp capture, diag pulse, B1
    probe -> g == 1, no correction adopted) and then lies x1.25 from the main
    pulses on.  A UNIFORM dt lie is measured and corrected by the B1.5
    host-clock bracket (validated behavior: g=0.8 adopted, K_a recovered to
    +0.3%, honest GREEN) — only an INCONSISTENT dt must escalate, and G1d
    (int v dt vs dPos) owns exactly that."""

    def __init__(self, **kw):
        VPSim.__init__(self, **kw)
        self._rec_no = 0

    def record_start(self, signals, length, time_resolution=1):
        self._rec_no += 1
        return VPSim.record_start(self, signals, length, time_resolution)

    def record_fetch(self, timeout_s=10.0, poll_s=0.02):
        out = VPSim.record_fetch(self, timeout_s, poll_s)
        if self._rec_no >= 4:                      # main pulses + JV records
            out["dt"] = out["dt"] * 1.25
        return out


def test_fault_inconsistent_dt_g1d_red(tmp_path):
    drive = InconsistentDtVPSim(i_c=0.6)
    res = vp.run_velpos_autotune(drive, _p2_params(drive, tmp_path))
    assert res.status == vp.RED, (res.status, res.reason)
    assert "G1d" in res.reason and "dt" in res.reason
    g1d = res.evidence["gates"]["G1d_intv_dpos"]
    assert not g1d["pass"] and g1d["dev"] == pytest.approx(0.25, abs=0.05)


def test_uniform_dt_lie_is_corrected_not_red(tmp_path):
    """Companion invariant: a UNIFORM x1.25 dt lie is measured by the B1.5
    host-clock bracket (g=0.8), corrected, and the run finishes GREEN with
    K_a recovered — the correction layer is real, so the G1d RED above is
    specifically about INCONSISTENCY, not scale."""
    class UniformDt(VPSim):
        def record_fetch(self, timeout_s=10.0, poll_s=0.02):
            out = VPSim.record_fetch(self, timeout_s, poll_s)
            out["dt"] = out["dt"] * 1.25
            return out

    drive = UniformDt(i_c=0.6)
    res = vp.run_velpos_autotune(drive, _p2_params(drive, tmp_path))
    assert res.status == vp.GREEN, (res.status, res.reason, res.warnings)
    assert res.evidence["unit_diag"]["g"] == pytest.approx(0.8, abs=0.01)
    assert abs(res.k_a / KA_TRUTH - 1.0) <= 0.02


# ======================================================================================
# 5) chicken-and-egg E2E + YELLOW no-rebaseline + cross-contamination
# ======================================================================================
def test_chicken_egg_first_run_establishes_baseline_then_band(tmp_path):
    """run1 (fresh profile): provisional path (band OFF, expect-slip=slip)
    -> GREEN -> i_ba_ref/ka_baseline persisted.  run2 (reloaded profile):
    the band gate is ACTIVE and GREEN; history grows."""
    prof0 = _fresh_profile("egg")
    drive1 = VPSim(i_c=0.6)
    res1 = vp.run_velpos_autotune(
        drive1, _p2_params(drive1, tmp_path, profile=prof0, synthetic=False))
    assert res1.status == vp.GREEN, (res1.status, res1.reason, res1.warnings)
    fr = res1.evidence["sig_first_run"]               # provisional path ran
    assert fr["status"] == "GREEN" and fr["detail"]["slip"] is True
    assert "signature_band" in res1.evidence
    assert res1.evidence["signature_band"]["status"] == "NEED_DATA"
    up = res1.evidence["profile_update"]
    iba1 = res1.evidence["breakaway"]["i_ba_a"]
    assert up["i_ba_ref_a"] == pytest.approx(iba1)
    assert up["ka_baseline"] == pytest.approx(res1.k_a)

    prof1 = mp.MotorProfile.load("egg", str(tmp_path))
    assert prof1.signature_band["i_ba_ref_a"] == pytest.approx(iba1)
    assert prof1.ka_baseline == pytest.approx(res1.k_a)
    assert len(prof1.i_ba_history) == 1

    drive2 = VPSim(i_c=0.6)
    res2 = vp.run_velpos_autotune(
        drive2, _p2_params(drive2, tmp_path, profile=prof1, synthetic=False))
    assert res2.status == vp.GREEN, (res2.status, res2.reason, res2.warnings)
    sb = res2.evidence["signature_band"]
    assert sb["status"] == "GREEN"                    # band ACTIVE now
    assert "sig_first_run" not in res2.evidence       # provisional path off
    prof2 = mp.MotorProfile.load("egg", str(tmp_path))
    assert len(prof2.i_ba_history) == 2               # GREEN-only append


def test_yellow_band_run_never_rebaselines(tmp_path):
    """A profile whose ref makes the healthy i_ba land in (1.5, 2.0]x ->
    band YELLOW -> run YELLOW -> the stored baseline is UNTOUCHED."""
    ref = 0.65 / 1.7                                  # healthy i_ba ~ 0.65
    prof = _fresh_profile("ylw").with_green_run(i_ba_a=ref, k_a=KA_TRUTH)
    path = prof.save(str(tmp_path))
    before = open(path, encoding="utf-8").read()
    drive = VPSim(i_c=0.6)
    res = vp.run_velpos_autotune(
        drive, _p2_params(drive, tmp_path, profile=prof, synthetic=False))
    assert res.status == vp.YELLOW, (res.status, res.reason, res.warnings)
    assert any("서명 대역 YELLOW" in w for w in res.warnings)
    sb = res.evidence["signature_band"]
    assert sb["status"] == "YELLOW" and 1.5 < sb["detail"]["ratio"] <= 2.0
    assert "profile_update" not in res.evidence       # GREEN-only update
    assert open(path, encoding="utf-8").read() == before


def test_cross_contamination_two_profiles_alternate(tmp_path):
    """Two motors alternating on the same drive: each GREEN run updates ONLY
    its own profile JSON; the other file is byte-identical."""
    prof_a = _fresh_profile("motor-a")
    prof_b = _fresh_profile("motor-b")
    drive_a = VPSim(i_c=0.6)
    res_a = vp.run_velpos_autotune(
        drive_a, _p2_params(drive_a, tmp_path, profile=prof_a,
                            synthetic=False))
    assert res_a.status == vp.GREEN, (res_a.status, res_a.reason)
    path_a = mp.MotorProfile.path_for("motor-a", str(tmp_path))
    path_b = mp.MotorProfile.path_for("motor-b", str(tmp_path))
    assert os.path.exists(path_a) and not os.path.exists(path_b)
    a_after_first = open(path_a, encoding="utf-8").read()

    drive_b = VPSim(i_c=1.2)                          # different friction
    res_b = vp.run_velpos_autotune(
        drive_b, _p2_params(drive_b, tmp_path, profile=prof_b,
                            synthetic=False))
    assert res_b.status in (vp.GREEN, vp.YELLOW), (res_b.status, res_b.reason)
    if res_b.status == vp.GREEN:
        assert os.path.exists(path_b)
        ref_a = mp.MotorProfile.load("motor-a", str(tmp_path)) \
            .signature_band["i_ba_ref_a"]
        ref_b = mp.MotorProfile.load("motor-b", str(tmp_path)) \
            .signature_band["i_ba_ref_a"]
        assert ref_a != ref_b                          # per-motor values
    # motor-a's baseline is untouched by motor-b's run either way
    assert open(path_a, encoding="utf-8").read() == a_after_first


# ======================================================================================
# 6) literal trip-wire — gate paths carry NO retired EAS/field literals
# ======================================================================================
_BANNED = (
    re.compile(r"POLE_PAIRS_FALLBACK"),
    re.compile(r"UM3_DRAG_I_A"),
    re.compile(r"0\.0712"),
    re.compile(r"812\.9"),
    re.compile(r"(?<![\d.])0\.50(?![\d])"),   # signature band low (retired)
    re.compile(r"(?<![\d.])1\.30(?![\d])"),   # signature band high / cap
    re.compile(r"(?<![\d.])6\.0(?![\d])"),    # fixed drag current
)
_ALLOWED_EXAMPLES = ("0.2010", "1.2705", "2.0")  # drive-rule constants stay


# The 1.30 A signature ENERGIZE ceiling is a SAFETY constant (operator
# low-current envelope), not a motor-specific decision-band literal.  Lines that
# define/use it are exempt from the ban.
_EXEMPT_MARKERS = ("SIGNATURE_ENERGIZE_ABS_MAX_A",)


@pytest.mark.parametrize("fname", ["autotune_current.py",
                                   "autotune_velpos.py"])
def test_tripwire_no_retired_literals_in_gate_sources(fname):
    src = open(os.path.join(ROOT, fname), encoding="utf-8").read()
    lines = src.split("\n")
    hits = []
    for rx in _BANNED:
        for m in rx.finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            if any(mk in lines[line - 1] for mk in _EXEMPT_MARKERS):
                continue  # safety energize ceiling, not a gate literal
            hits.append("%s:%d:%s" % (fname, line, m.group(0)))
    assert not hits, "retired literals present in gate source: %s" % hits
    # sanity: the drive-rule constants are intentionally still allowed
    if fname == "autotune_current.py":
        assert "0.2010" in src


def test_tripwire_derivations_reproduce_frozen_field_values():
    """The retired literals are REPRODUCED by the motor-agnostic formulas on
    this unit (proof the values were formulas all along): 6.0 A drag and the
    [0.44, 1.33] signature band around ref=0.887."""
    i_drag, det = pg.derive_drag_current(21.2132, i_cap_a=0.4 * 21.2132)
    assert i_drag == pytest.approx(6.0, abs=1e-3)
    lo = pg.SIG_GREEN[0] * 0.887
    hi = pg.SIG_GREEN[1] * 0.887
    assert lo == pytest.approx(0.4435) and hi == pytest.approx(1.3305)
