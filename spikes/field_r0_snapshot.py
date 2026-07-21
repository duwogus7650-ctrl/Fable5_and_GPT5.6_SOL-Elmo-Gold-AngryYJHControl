"""Field runbook R0 — READ-ONLY pre-state snapshot + JSON backup.

Reads every value the commutation-ID run may touch (CA[7] above all) BEFORE any
energize, and writes a timestamped restore point.  NO motion, NO MO=1 —
elmo_link blocks motion commands; this script only queries.

GREEN when: every item read, CA[17]==5 (serial-absolute commutation), MF==0.

Prereq: COM3 free (EAS disconnected AND the GUI app not connected).
Usage:  python spikes/field_r0_snapshot.py [COM3]
"""
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elmo_link import ElmoLink  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"

# R0 read set.  CA[7] is the restore-critical one (commutation phase offset).
QUERIES = [
    # identity / firmware
    "VR", "VP",
    # commutation parameters (CA[7] = the value the ID run rewrites)
    "CA[7]", "CA[16]", "CA[17]", "CA[25]",
    # motor / feedback identity
    "CA[18]", "CA[19]", "CA[28]", "CA[41]", "CA[45]",
    # state
    "UM", "MO", "SO", "MF", "SR",
    # current limits
    "CL[1]", "PL[1]", "TC",
    # speed / accel limits
    "VH[2]", "AC", "DC", "SD",
    # gains (restore point for tuning)
    "KP[1]", "KI[1]", "KP[2]", "KI[2]", "KP[3]",
]

EXPECT = {"CA[17]": 5, "MF": 0}


def _num(resp):
    if resp is None:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(resp))
    return float(m.group(0)) if m else None


snapshot = {"port": PORT, "unix_time": time.time(),
            "local_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "raw": {}, "num": {}, "errors": {}}

link = ElmoLink(PORT)
try:
    print("[R0] connecting %s (read-only, no motion) ..." % PORT)
    link.connect()
    print("[R0] IsConnected = %s\n" % link.is_connected)

    for q in QUERIES:
        try:
            r = link.command(q, timeout_ms=2000)
            snapshot["raw"][q] = r
            snapshot["num"][q] = _num(r)
            print("  %-8s -> %r" % (q, r))
        except Exception as e:                        # noqa: BLE001
            snapshot["errors"][q] = "%s: %s" % (type(e).__name__, e)
            print("  %-8s !! %s: %s" % (q, type(e).__name__, e))

    # ---- restore point ----
    out_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), ".omc", "state")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "field_r0_snapshot_%d.json" % int(time.time()))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=2)
    print("\n[R0] restore point saved -> %s" % path)

    # ---- verdict ----
    print("\n=== R0 GATE ===")
    checks = []
    missing = [q for q in QUERIES if q not in snapshot["raw"]]
    checks.append(("all items read (%d/%d)" % (len(snapshot["raw"]), len(QUERIES)),
                   not missing))
    for key, want in EXPECT.items():
        got = snapshot["num"].get(key)
        checks.append(("%s == %s (got %s)" % (key, want, got), got == want))
    ca7 = snapshot["num"].get("CA[7]")
    checks.append(("CA[7] readable (restore-critical) = %s" % ca7, ca7 is not None))

    for label, ok in checks:
        print("  [%s] %s" % ("GREEN" if ok else "RED  ", label))
    ok_all = all(ok for _, ok in checks)
    print("\n  R0 VERDICT: %s" % (
        "GREEN — pre-state captured, safe to proceed to R1"
        if ok_all else "RED — resolve before energizing"))
    if missing:
        print("  missing: %s" % missing)
finally:
    try:
        link.disconnect()
    except Exception:                                 # noqa: BLE001
        pass
    print("[R0] disconnected")
