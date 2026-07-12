"""Live read-only handshake against the real Gold Twitter on COM3.

Reads firmware/PAL version and compares to what EAS III displayed:
  VR should contain "Twitter 01.01.16.00 ... G"  (GCON core)
NO motion commands are sent (elmo_link blocks MO=1/BG/etc by default).
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elmo_link import ElmoLink  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
READ_ONLY_CMDS = ["VR", "VP", "VB"]  # firmware ver, PAL ver, boot ver — all read-only

EXPECT = {"fw_contains": "01.01.16", "core_suffix": "G"}  # from EAS III screenshot

link = ElmoLink(PORT)
try:
    print(f"[connect] {PORT} ...")
    link.connect()
    print(f"[connect] IsConnected = {link.is_connected}")

    results = {}
    for c in READ_ONLY_CMDS:
        try:
            r = link.command(c, timeout_ms=2000)
            results[c] = r
            print(f"  {c} -> {r!r}")
        except Exception as e:
            print(f"  {c} !! {type(e).__name__}: {e}")

    vr = results.get("VR", "") or ""
    ok_fw = EXPECT["fw_contains"] in vr
    ok_core = vr.rstrip().endswith(EXPECT["core_suffix"]) or (EXPECT["core_suffix"] in vr.split()[-1] if vr.split() else False)
    print("\n=== ORACLE CHECK (vs EAS III display) ===")
    print(f"  VR contains '{EXPECT['fw_contains']}': {ok_fw}")
    print(f"  GCON core marker 'G' present     : {ok_core}")
    print("  VERDICT:", "GREEN" if ok_fw else "RED (VR mismatch)")
finally:
    link.disconnect()
    print("[disconnect] done")
