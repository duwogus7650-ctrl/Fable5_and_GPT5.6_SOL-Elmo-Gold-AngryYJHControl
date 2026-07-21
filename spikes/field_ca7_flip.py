"""Field R2 — manual 180-degree commutation flip: CA[7] += 256 (wrapped).

Why manual: the in-app commutation ID opens its own P2_LIMITS persistence
transaction in S0, which makes persistence_unknown true, which then blocks its
own CA[7] write (CA[7] is in no authorized mutation set).  Outside a run there
is no active record, so the plain assignment passes.  This is a field unblock;
the code fix (flip before the limits transaction, or an authorized commutation
mutation path) is a separate offline task.

Safety: MO=0 gate, MF==0 gate (fault must be cleared by a power cycle first),
integer readback verification, NO SV -> the value lives in RAM only and a power
cycle restores the flash value.  R0 restore point already captured.

Usage:  python spikes/field_ca7_flip.py [COM3]
"""
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from elmo_link import ElmoLink  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM3"
FLIP_TICKS = 256                     # 180 deg electrical (512 ticks = 360 deg)


def _wrap(v: int) -> int:
    return ((int(v) + 512) % 1024) - 512


def _num(resp):
    if resp is None:
        return None
    m = re.search(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", str(resp))
    return float(m.group(0)) if m else None


link = ElmoLink(PORT)
try:
    print("[flip] connecting %s ..." % PORT)
    link.connect()
    print("[flip] IsConnected = %s\n" % link.is_connected)

    mo = _num(link.command("MO", timeout_ms=2000))
    mf = _num(link.command("MF", timeout_ms=2000))
    um = _num(link.command("UM", timeout_ms=2000))
    ca7 = _num(link.command("CA[7]", timeout_ms=2000))
    print("  MO=%s  MF=%s  UM=%s  CA[7]=%s" % (mo, mf, um, ca7))

    # ---- fail-closed gates ------------------------------------------------
    problems = []
    if mo != 0:
        problems.append("MO=%s (모터가 켜져 있음 — MO=0 이어야 함)" % mo)
    if mf != 0:
        problems.append("MF=%s (폴트 래치 — 전원 재인가로 먼저 소거해야 함)" % mf)
    if ca7 is None or not float(ca7).is_integer() or not (-512 <= ca7 <= 512):
        problems.append("CA[7]=%r 비정상(정수 −512..512 기대)" % ca7)
    if problems:
        print("\n[flip] ABORT — 전제조건 불충족:")
        for p in problems:
            print("   - %s" % p)
        raise SystemExit(2)

    old = int(ca7)
    new = _wrap(old + FLIP_TICKS)
    print("\n[flip] 180° 플립: CA[7] %d -> %d  (wrap(%d+%d))"
          % (old, new, old, FLIP_TICKS))

    resp = link.command("CA[7]=%d" % new, timeout_ms=3000)
    print("  write resp: %r" % (resp,))

    back = _num(link.command("CA[7]", timeout_ms=2000))
    print("  readback  : %s" % back)

    if back is not None and int(back) == new:
        print("\n[flip] GREEN — CA[7]=%d 검증 완료 (RAM only, SV 안 함)" % new)
        print("       전원 재인가하면 %d 로 자동 원복됩니다." % old)
    else:
        print("\n[flip] RED — 되읽기 불일치: 기대 %d, 실제 %s" % (new, back))
        raise SystemExit(3)
finally:
    try:
        link.disconnect()
    except Exception:                                # noqa: BLE001
        pass
    print("[flip] disconnected")
