"""Tests for physics_gates.py (P3 motor-agnostic validation gates).

Covers: threshold boundaries, reproduction of the field-frozen constants from
motor-agnostic formulas, multi-motor derivations (spec §7 A-D), fault injection
-> honest RED, combine() precedence, and a literal trip-wire (no EAS constants
baked into the gate module).
"""
import os
import math

import pytest

import physics_gates as pg


# --- lightweight profile double (only the attrs the gates read) --------------
class Prof:
    def __init__(self, rated=None, cl=None, ka_baseline=None, i_ba_ref=None):
        self.effective_rated_rpm = rated
        self.cont_current_a = cl
        self.ka_baseline = ka_baseline
        self.signature_band = {"i_ba_ref_a": i_ba_ref} if i_ba_ref is not None else {}


# spec §7 motor matrix (R_pp, L_pp, CL[1], p, rated_rpm)
MOTORS = {
    "A_unit":   dict(r=0.139, l=41.6e-6, cl=21.2132, p=16, rated=3600.0, vbus=48.41),
    "B_coreless": dict(r=8.0,  l=0.8e-3, cl=1.4,    p=4,  rated=4000.0, vbus=48.0),
    "C_servo":  dict(r=0.5,   l=2.5e-3, cl=8.5,    p=5,  rated=3000.0, vbus=48.0),
    "D_direct": dict(r=0.060, l=25e-6,  cl=30.0,   p=21, rated=200.0,  vbus=48.0),
}


# ===================== reproduction of frozen field constants ================
def test_repro_drag_current_6A():
    # 0.4·CL/sqrt2 == 6.0000 for the unit motor (i_cap = 0.4·CL)
    cl = 21.2132
    i_drag, det = pg.derive_drag_current(cl, i_cap_a=0.4 * cl)
    assert i_drag == pytest.approx(6.0, abs=1e-3)
    assert det["discrimination_deg"] == 45.0
    assert det["route_ok"] is True


def test_repro_guard_rpm_1200():
    assert pg.derive_guard_rpm(Prof(rated=3600.0)) == pytest.approx(1200.0)


def test_repro_verify_speeds_360_900():
    # frozen field values: v1=360, v2=900 (0.10/0.25 * 3600), guard=1200.
    # v2 = 0.75*guard passes the 0.8*guard backstop, so it is NOT clipped.
    v1, v2 = pg.derive_verify_speeds(Prof(rated=3600.0))
    assert v1 == pytest.approx(360.0)
    assert v2 == pytest.approx(900.0)


def test_repro_verify_v2_capped_by_guard():
    # with an artificially small guard the 0.8*guard backstop binds
    v1, v2 = pg.derive_verify_speeds(Prof(rated=3600.0), guard_rpm=1000.0)
    assert v2 == pytest.approx(min(900.0, 0.8 * 1000.0))  # 800


def test_repro_signature_band_reproduces_050_130():
    # [0.5,1.5]*0.887 ~= [0.444,1.331] ~ the frozen [0.50,1.30]
    prof = Prof(cl=21.2132, i_ba_ref=0.887)
    assert pg.sig_band(0.887 * 0.5, prof).status == "GREEN"      # 0.4435 (lo edge)
    assert pg.sig_band(0.887 * 1.5, prof).status == "GREEN"      # 1.3305 (hi edge)
    assert pg.sig_band(0.887 * 1.6, prof).status == "YELLOW"
    assert pg.sig_band(0.887 * 2.1, prof).status == "RED"


# ===================== §1 boundaries =========================================
def test_p1_pm_boundaries():
    assert pg.p1_pm(45.0).status == "GREEN"
    assert pg.p1_pm(44.9).status == "YELLOW"
    assert pg.p1_pm(40.0).status == "YELLOW"
    assert pg.p1_pm(39.9).status == "RED"
    assert pg.p1_pm(None).status == "NEED_DATA"


def test_p1_wc_band_boundaries():
    ts = 100e-6
    # green lower = 0.13725/ts, yellow lower = 0.070272/ts, max = 0.25/ts
    assert pg.p1_wc_band(0.14 / ts, ts).status == "GREEN"
    assert pg.p1_wc_band(0.10 / ts, ts).status == "YELLOW"
    assert pg.p1_wc_band(0.05 / ts, ts).status == "RED"
    assert pg.p1_wc_band(0.30 / ts, ts).status == "RED"    # over Nyquist margin


def test_p1_rho_boundaries():
    def rows(dev):
        return [{"rho_meas": 1.0 + dev, "rho_pred": 1.0}]
    assert pg.p1_rho(rows(0.15)).status == "GREEN"
    assert pg.p1_rho(rows(0.25)).status == "YELLOW"
    assert pg.p1_rho(rows(0.35)).status == "RED"
    assert pg.p1_rho([]).status == "NEED_DATA"


def test_p1_r_relative_unit_green_and_abs_backstop():
    m = MOTORS["A_unit"]
    v = pg.p1_r_relative(m["r"], m["cl"], m["vbus"])
    assert v.status == "GREEN"
    assert v.detail["kappa_r"] == pytest.approx(0.0609, abs=2e-3)
    # absolute backstop: 20 ohm is out of [1mOhm,10ohm]
    assert pg.p1_r_relative(20.0, 21.2, 48.0).status == "RED"


def test_p1_l_relative_effort_and_observability():
    m = MOTORS["A_unit"]
    wc = 0.201 / 100e-6  # ω_c from drive rule
    v = pg.p1_l_relative(m["l"], m["r"], wc, 800.0, m["cl"], m["vbus"])
    assert v.status == "GREEN"
    # low observability -> YELLOW (tiny L)
    vy = pg.p1_l_relative(1e-6, 1.0, wc, 50.0, 5.0, 48.0)
    assert vy.status in ("YELLOW", "RED")


# ===================== §2 signature / ka ====================================
def test_sig_first_run_follow_slip_direction():
    assert pg.sig_first_run(True, 0.95, True).status == "RED"    # follows -> bad commutation
    assert pg.sig_first_run(True, 0.3, True).status == "GREEN"   # slips + ka ok
    assert pg.sig_first_run(True, 0.3, False).status == "YELLOW"
    assert pg.sig_first_run(False, 0.3, True).status == "RED"    # wrong direction
    assert pg.sig_first_run(True, 0.7, True).status == "YELLOW"  # indeterminate


def test_ka_drop_boundaries():
    prof = Prof(ka_baseline=1000.0)
    assert pg.ka_drop(1000.0, prof).status == "GREEN"
    assert pg.ka_drop(690.0, prof).status == "YELLOW"   # 0.69 < 0.7
    assert pg.ka_drop(490.0, prof).status == "RED"      # 0.49 < 0.5
    assert pg.ka_drop(500.0, Prof()).status == "NEED_DATA"  # no baseline


def test_sig_band_floor_and_need_data():
    prof = Prof(cl=21.2132, i_ba_ref=0.887)
    assert pg.sig_band(0.01, prof).status == "YELLOW"   # below 0.02*CL floor
    assert pg.sig_band(0.9, Prof(cl=21.2132)).status == "NEED_DATA"  # no ref


# ===================== §7 multi-motor derivations ============================
@pytest.mark.parametrize("name", list(MOTORS))
def test_multi_motor_derivations_finite_and_sane(name):
    m = MOTORS[name]
    prof = Prof(rated=m["rated"], cl=m["cl"])
    g = pg.derive_guard_rpm(prof)
    assert pg.GUARD_RPM_CLIP[0] <= g <= pg.GUARD_RPM_CLIP[1]
    v1, v2 = pg.derive_verify_speeds(prof, g)
    assert 0 < v1 <= v2 <= pg.VERIFY_GUARD_FRAC * g + 1e-9
    i_drag, _ = pg.derive_drag_current(m["cl"], i_cap_a=0.4 * m["cl"])
    assert i_drag == pytest.approx(0.4 * m["cl"] / math.sqrt(2))


def test_multi_motor_C_high_tau_is_yellow_not_forced_green():
    # spec §7: case C (high tau_e) legitimately lands YELLOW on ω_c band when
    # ω_c is reduced for PM.  A reduced ω_c·TS in the yellow window stays YELLOW.
    ts = 100e-6
    assert pg.p1_wc_band(0.10 / ts, ts).status == "YELLOW"


def test_multi_motor_D_direct_drive_low_L_observability():
    m = MOTORS["D_direct"]
    wc = 0.201 / 50e-6
    v = pg.p1_l_relative(m["l"], m["r"], wc, 200.0, m["cl"], m["vbus"])
    assert v.status in ("GREEN", "YELLOW")  # low-L direct drive, not RED by itself


# ===================== fault injection -> honest RED =========================
def test_fault_delta70_ka_drop_red():
    # delta=70deg -> K_a/base = cos70 = 0.342 < 0.5 -> RED
    prof = Prof(ka_baseline=1000.0)
    assert pg.ka_drop(1000.0 * math.cos(math.radians(70)), prof).status == "RED"


def test_fault_L_pollution_rho_red():
    rows = [{"rho_meas": 1.9, "rho_pred": 1.0}]  # ~190% in-situ error
    assert pg.p1_rho(rows).status == "RED"


def test_fault_kappa_r_over_range_red():
    # R chosen so kappa_R > 0.7
    assert pg.p1_r_relative(3.0, 21.2132, 48.41).status == "RED"


# ===================== combine precedence ====================================
def test_combine_precedence():
    G = pg.GateVerdict("GREEN", "x")
    Y = pg.GateVerdict("YELLOW", "x")
    N = pg.GateVerdict("NEED_DATA", "x")
    R = pg.GateVerdict("RED", "x")
    adv = pg.GateVerdict("RED", "x", advisory=True)
    assert pg.combine([G, G]) == "GREEN"
    assert pg.combine([G, Y]) == "YELLOW"
    assert pg.combine([Y, N]) == "NEED_DATA"
    assert pg.combine([N, R]) == "RED"          # RED dominates NEED_DATA
    assert pg.combine([G, adv]) == "GREEN"      # advisory excluded


def test_advisory_eas_never_gates():
    adv = pg.advisory_eas({"KP[1]": 0.0712}, {"kp_cur": 0.0800})
    assert "deviations" in adv
    assert adv["deviations"]["KP[1]"] == pytest.approx(0.0800 / 0.0712 - 1.0)


# ===================== literal trip-wire =====================================
def test_no_eas_or_field_literals_in_gate_module():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "physics_gates.py"), encoding="utf-8").read()
    for bad in ("0.0712", "812.9", "POLE_PAIRS_FALLBACK"):
        assert bad not in src, "gate module must not bake in EAS/field literal %r" % bad
