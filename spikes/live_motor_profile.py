"""Live READ-ONLY motor-profile probe against the real Gold Twitter on COM3.

Reads version + motor identity params, builds a MotorProfile (P1), derives the
jog ceiling / current caps (P2), and compares to the EAS III oracle.
NO motion / NO MO=1 — elmo_link blocks motion commands; this script only queries.

Prereq: EAS III must be DISCONNECTED (COM3 is single-owner).
Usage:  python spikes/live_motor_profile.py [COM3]
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elmo_link import ElmoLink            # noqa: E402
from motor_profile import MotorProfile    # noqa: E402
import single_axis_motion as sam          # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"

# Read-only queries. Version strings + motor identity params.
VERSION_CMDS = ["VR", "VP"]
PARAM_CMDS = ["CA[18]", "CA[19]", "CA[28]", "VH[2]", "CL[1]", "PL[1]", "TS"]

# Oracle (what EAS III showed for THIS unit — brief/memory grounding).
ORACLE = {
    "fw_contains": "01.01.16",
    "CA[18]": 65536,      # counts/rev
    "CA[19]": 16,         # pole pairs — THIS bench motor (user-confirmed 2026-07-21).
                          # (The "21" in old AngryYJH memory was a DIFFERENT motor.)
    "rated_rpm": 3600.0,  # VH[2]*60/CA[18]
}
RPM_TOL = 1.0  # rpm


def _num(resp):
    """Extract the first numeric token from a drive text response, or None."""
    if resp is None:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(resp))
    return float(m.group(0)) if m else None


link = ElmoLink(PORT)
raw = {}
try:
    print("[connect] %s ..." % PORT)
    link.connect()
    print("[connect] IsConnected = %s" % link.is_connected)

    print("\n=== version (read-only) ===")
    ver = {}
    for c in VERSION_CMDS:
        try:
            r = link.command(c, timeout_ms=2000)
            ver[c] = r
            print("  %-6s -> %r" % (c, r))
        except Exception as e:                       # noqa: BLE001
            print("  %-6s !! %s: %s" % (c, type(e).__name__, e))

    print("\n=== motor identity params (read-only) ===")
    for c in PARAM_CMDS:
        try:
            r = link.command(c, timeout_ms=2000)
            raw[c] = r
            print("  %-8s -> %r   (num=%s)" % (c, r, _num(r)))
        except Exception as e:                       # noqa: BLE001
            print("  %-8s !! %s: %s" % (c, type(e).__name__, e))

    # --- build MotorProfile (P1) from live drive reads ---
    drive_readings = {k: _num(raw.get(k)) for k in PARAM_CMDS}
    prof = MotorProfile.from_sources("live-com3", drive_readings=drive_readings)

    print("\n=== MotorProfile (P1, from live reads) ===")
    print("  counts_per_rev (CA[18]) : %s" % prof.counts_per_rev)
    print("  pole_pairs (CA[19])     : %s  [%s]" % (prof.pole_pairs, prof.pole_pairs_state))
    print("  motor_type (CA[28])     : %s" % prof.motor_type)
    print("  cont_current CL[1] [A]  : %s" % prof.cont_current_a)
    print("  peak_current PL[1] [A]  : %s" % prof.peak_current_a)
    print("  VH[2] [counts/s]        : %s" % prof.vh2_counts_per_s)
    print("  rated_rpm_drive         : %s" % prof.rated_rpm_drive)
    print("  effective_rated_rpm     : %s  [%s]" % (prof.effective_rated_rpm, prof.rated_rpm_flag))
    print("  is_valid                : %s" % prof.is_valid)

    # --- derived jog limits (P2) ---
    print("\n=== derived jog/motion limits (P2) ===")
    print("  jog_rpm_ceiling          : %s rpm" % sam.jog_rpm_ceiling(prof))
    print("  jog_voltage_warn_rpm     : %s rpm" % sam.jog_voltage_warn_rpm(prof))
    print("  jog_current_cap_ceiling  : %s A" % sam.jog_current_cap_ceiling_a(prof))
    print("  jog_default_current_cap  : %s A" % sam.jog_default_current_cap_a(prof))

    # --- oracle comparison ---
    print("\n=== ORACLE CHECK (vs EAS III / brief grounding) ===")
    checks = []
    vr = (ver.get("VR", "") or "")
    ok_fw = ORACLE["fw_contains"] in vr
    checks.append(("VR contains %r" % ORACLE["fw_contains"], ok_fw))
    ok_ca18 = _num(raw.get("CA[18]")) == ORACLE["CA[18]"]
    checks.append(("CA[18] == %d" % ORACLE["CA[18]"], ok_ca18))
    ok_ca19 = _num(raw.get("CA[19]")) == ORACLE["CA[19]"]
    checks.append(("CA[19] == %d (pole pairs)" % ORACLE["CA[19]"], ok_ca19))
    ok_rpm = (prof.effective_rated_rpm is not None
              and abs(prof.effective_rated_rpm - ORACLE["rated_rpm"]) <= RPM_TOL)
    checks.append(("effective_rated_rpm ~= %.0f" % ORACLE["rated_rpm"], ok_rpm))
    ok_ceil = abs(sam.jog_rpm_ceiling(prof) - ORACLE["rated_rpm"]) <= RPM_TOL
    checks.append(("jog ceiling ~= rated %.0f" % ORACLE["rated_rpm"], ok_ceil))

    for label, ok in checks:
        print("  [%s] %s" % ("GREEN" if ok else "RED  ", label))
    all_ok = all(ok for _, ok in checks)
    print("\n  VERDICT: %s" % ("GREEN — live read-only grounding OK"
                               if all_ok else "RED — see mismatches above"))
finally:
    try:
        link.disconnect()
    except Exception:                                # noqa: BLE001
        pass
    print("[disconnect] done")
