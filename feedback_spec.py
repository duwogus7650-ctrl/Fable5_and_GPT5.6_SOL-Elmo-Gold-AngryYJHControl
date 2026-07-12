"""Per-sensor feedback panel spec — mirrors EAS III's Feedback Settings screens.

Canonical sources (2026-07-12):
  docs/eas-feedback-panels.md      — per-sensor UI structure from the EAS video (fable-vision)
  docs/eas-feedback-command-map.md — field label -> CA[] command map + conversions (fable-reader)
  Gold Line Command Reference 1.406 p.46 — CA[41] sensor-ID enum (1..28)
Live-grounded on this drive: EnDat 2.2 = CA[41] 30 (undocumented in 2013 CR),
CA[59]=19 CA[61]=3 CA[58]=0 CA[62]=16 CA[35]=8 CA[18]=65536.

Field kinds: VALUE (line edit) / DD (dropdown, options carry RAW drive values) /
RO (read-only / derived / unmapped) / BTN (action button).
RULE: any field whose command mapping is unconfirmed is RO with note "미확정" — never written.
"""

# ---------------------------------------------------------------------------------------
# Field kinds
# ---------------------------------------------------------------------------------------
VALUE, DD, RO, BTN = "value", "dropdown", "ro", "button"


def F(label, cmd=None, kind=VALUE, options=None, editable=None, xform=None,
      note=None, static=None):
    """Build one field spec. editable defaults: VALUE/DD with a command -> True."""
    if editable is None:
        editable = (kind in (VALUE, DD)) and cmd is not None
    return {"label": label, "cmd": cmd, "kind": kind, "options": options,
            "editable": editable, "xform": xform, "note": note, "static": static}


# ---------------------------------------------------------------------------------------
# Sensor names — EAS verbatim (Port notation included). IDs = CR enum + live-measured.
# ---------------------------------------------------------------------------------------
SENSOR_NAMES = {
    # EAS-listed sensors, verbatim names
    1: "Encoder Quad, Port B", 2: "Quad Exclusive 1, Port A",
    3: "Analog Sin/Cos, Port B", 4: "Halls Only, Port A",
    5: "Serial Absolute - BiSS, Port A", 6: "Serial Absolute - Panasonic, Port A",
    9: "Serial Absolute - EnDat 2.1 designation 22, Port A",
    10: "Serial Absolute - Tamagawa, Port A",
    11: "Pulse and Direction, Port B", 12: "Pulse and Direction, Port A",
    16: "Analog Input #1, Port C", 17: "Virtual Absolute - Gurley, Port B",
    18: "Serial Absolute - SSI, Port A", 22: "Resolver, Port B",
    23: "Serial Absolute - Kawasaki, Port A",
    24: "Serial Absolute - BiSS General, Port A",
    25: "Serial Absolute - Sanyo / Nikon, Port A",
    28: "Serial Absolute - Hiperface, Port A and B",
    29: "Serial - Panasonic Incremental, Port A",
    30: "Serial Absolute - EnDat 2.2 designation 22, Port A",   # live: this drive
    # non-EAS reference IDs (CR/RN) kept so any reported CA[41] still gets a name
    7: "Serial Absolute Mitutoyo", 8: "Virtual 2-Sine (SE)",
    13: "Emulation (Port B)", 14: "Emulation (Port A)", 15: "Copy Main Profile",
    19: "Yaskawa", 20: "Gantry Master", 21: "Serial Exclusive",
    26: "Simple Profiler", 27: "Gantry Differential Copy",
    33: "Absolute SSI #2", 34: "Stepper Closed Loop", 35: "PWM Reference Input",
    36: "Super-Fast Quad (PAL)", 37: "Sensorless (Brushless)", 38: "Sensorless (DC Brush)",
}

# EAS combo — exact 23 entries in EAS order. id=None -> CA[41] value unconfirmed
# (IAI / Mitsubishi are post-2013-CR additions with no documented ID; "Serial Exclusive #3"
# variant unverified vs CR's plain 21). Panel renders; CA[41] write is BLOCKED for these.
EAS_SENSORS = [
    ("Analog Input #1, Port C", 16),
    ("Analog Sin/Cos, Port B", 3),
    ("Encoder Quad, Port B", 1),
    ("Halls Only, Port A", 4),
    ("Pulse and Direction, Port A", 12),
    ("Pulse and Direction, Port B", 11),
    ("Quad Exclusive 1, Port A", 2),
    ("Resolver, Port B", 22),
    ("Serial - Panasonic Incremental, Port A", 29),
    ("Serial Absolute - BiSS General, Port A", 24),
    ("Serial Absolute - BiSS, Port A", 5),
    ("Serial Absolute - EnDat 2.1 designation 22, Port A", 9),
    ("Serial Absolute - EnDat 2.2 designation 22, Port A", 30),
    ("Serial Absolute - Hiperface, Port A and B", 28),
    ("Serial Absolute - IAI, Port A", None),
    ("Serial Absolute - Kawasaki, Port A", 23),
    ("Serial Absolute - Mitsubishi, Port A", None),
    ("Serial Absolute - Panasonic, Port A", 6),
    ("Serial Absolute - Sanyo / Nikon, Port A", 25),
    ("Serial Absolute - SSI, Port A", 18),
    ("Serial Absolute - Tamagawa, Port A", 10),
    ("Serial Exclusive #3", None),
    ("Virtual Absolute - Gurley, Port B", 17),
]

COMMUT_NAMES = {1: "Digital Hall", 2: "Stepper", 3: "Binary Search", 4: "Analog Hall",
                5: "Serial Absolute Encoder", 6: "Virtual Gurley", 7: "PAL Slave"}

# Coherent default commutation (CA[17]) per sensor (CA[41]) — confident cases only.
DEFAULT_COMMUT = {
    4: 1,                                    # Halls Only         -> Digital Hall
    1: 3, 2: 3, 3: 3,                        # quad / sin-cos     -> Binary Search
    5: 5, 9: 5, 18: 5, 24: 5, 28: 5, 30: 5,  # serial absolute    -> Serial Absolute Encoder
    6: 5, 10: 5, 23: 5, 25: 5,               # serial absolute    -> Serial Absolute Encoder
    17: 6,                                   # Gurley             -> Virtual Gurley
}

# ---------------------------------------------------------------------------------------
# Conversions (canonical, from eas-feedback-command-map.md)
# ---------------------------------------------------------------------------------------
def glitch_raw_to_ns(raw):
    """CA[35] raw -> nanoseconds: ns = (raw+1) * 13.333 (rounded to int ns)."""
    return int(round((raw + 1) * 13.333))


def glitch_ns_to_raw(ns):
    """nanoseconds -> CA[35] raw: raw = round(ns/13.333) - 1."""
    return int(round(ns / 13.333)) - 1


def clk_raw_to_mhz(raw):
    """CA[36] raw -> display MHz: MHz = raw / 10,000,000.

    Live-grounded 2026-07-12: CA[36] raw 50,000,000 <-> EAS display 5.000 MHz.
    """
    return raw / 10_000_000.0


def clk_mhz_to_raw(mhz):
    """display MHz -> CA[36] raw: raw = MHz * 10,000,000."""
    return int(round(mhz * 10_000_000))


def fcd_raw_to_us(raw):
    """CA[86] raw -> microseconds: us = raw * 0.4."""
    return raw * 0.4


def fcd_us_to_raw(us):
    """microseconds -> CA[86] raw."""
    return int(round(us / 0.4))


def sw_from_raw(hw_bits, ca61, high_bits_mask):
    """SW Sensor Resolution (bits) = CA[59] - CA[61] - CA[58]."""
    return hw_bits - ca61 - high_bits_mask


def ca61_from_sw(hw_bits, sw_bits, high_bits_mask):
    """CA[61] = CA[59] - SW - CA[58] (inverse of sw_from_raw)."""
    return hw_bits - sw_bits - high_bits_mask


# ---------------------------------------------------------------------------------------
# Dropdown option tables — (display text, RAW drive value)
# ---------------------------------------------------------------------------------------
OPT_DIR = [("Non Invert", 0), ("Invert", 1)]
OPT_YESNO = [("No", 0), ("Yes", 1)]
OPT_SIGNAL = [("Current", 1), ("Velocity", 2), ("Position", 3)]
OPT_RESOLVER_FREQ = [("10", 0), ("5", 1), ("2.5", 2), ("1.2", 4)]     # kHz -> CA[34]
OPT_GLITCH_NS = [(str(40 * n), 3 * n - 1) for n in range(1, 10)]      # 40..360 ns -> CA[35]
OPT_HIGH_BITS = [(str(i), i) for i in range(0, 9)]                    # 0..8 -> CA[58]
OPT_FCD_US = [("%.1f" % (0.4 * i), i) for i in range(0, 16)]          # 0.0..6.0 us -> CA[86]
OPT_CLK_MHZ = [("1.250", 12_500_000), ("2.500", 25_000_000),          # MHz -> CA[36]
               ("5.000", 50_000_000)]                                 # (raw = MHz * 1e7, live)
OPT_GURLEY_HW = [("10", 10), ("11", 11), ("12", 12)]                  # bits -> CA[21]
OPT_FIR = [("Disabled", 0)] + [(str(i), i) for i in range(2, 9)]      # display only

# ---------------------------------------------------------------------------------------
# Reusable field builders (socket s=1 on this drive: CA[54]/CA[71]/CA[91])
# ---------------------------------------------------------------------------------------
_D = lambda: F("Direction", "CA[54]", DD, OPT_DIR)
_HALLS_USE = lambda: F("Use Digital Halls", "CA[20]", DD, OPT_YESNO)
_FIR = lambda: F("Velocity FIR Filter Window", "CA[71]", RO, xform="fir",
                 note="쓰기 미확정(Disabled 이중후보 CA[71]/CA[75]) — 표시전용")
_APO = lambda: F("Absolute Position Offset", "CA[91]", VALUE)
_CLK = lambda: F("Clock Frequency (MHz)", "CA[36]", DD, OPT_CLK_MHZ, xform="clk_mhz",
                 note="MHz = CA[36]/1e7 — 라이브 확정 (raw 50,000,000 ↔ EAS 5.000)")
_GLITCH_NS = lambda: F("Input Glitch Filter (nanosecond)", "CA[35]", DD, OPT_GLITCH_NS,
                       xform="glitch_ns")
_POLL = lambda: F("Serial Data Polling", None, RO, note="미확정")
_CTIME = lambda: F("Communication Time (microsecond)", None, RO, note="미확정")
_EBM_HEX = lambda: F("Error Bitwise Mask", "CA[8]", VALUE, xform="hex")
_EBM_BOOL = lambda: F("Error Bit Mask", "CA[8]", RO,
                      note="미확정(False/True 극성) — 표시전용")
_HW_BITS = lambda: F("HW Sensor Resolution (Bits)", "CA[59]", VALUE)
_SW_BITS = lambda: F("SW Sensor Resolution (Bits)", "CA[61]", VALUE, xform="sw_res",
                     note="쓰기 시 CA[61]=CA[59]−SW−CA[58] 변환")
_MULTITURN = lambda: F("Rotary Multi-turn Resolution", "CA[62]", VALUE)
_HBM = lambda: F("High Bits Mask", "CA[58]", DD, OPT_HIGH_BITS)
_LSB = lambda: F("Position LSB Number", "CA[67]", VALUE)
_EBN = lambda: F("Error Bit Number", "CA[22]", VALUE)
_PTB = lambda: F("Protocol Total Bits", "CA[66]", VALUE)
_FCD = lambda: F("First Clock Delay (us)", "CA[86]", DD, OPT_FCD_US, xform="fcd_us")
_MAINT = lambda: F("Encoder Maintenance", None, BTN,
                   note="TW[18]/[19]/[20] 매핑 M등급 — live-diff 후 활성화")
_MULT = lambda: F("Multiplication Factor", "CA[31]", VALUE, note="counts/cycle = 2^CA[31]")
_SDPRES = lambda: F("Sensor Data Presentation", None, RO, note="미확정 (Binary)")

# derived Resolution rows (display-only per contract)
_RES_COUNTS = lambda note=None: F("Counts / Revolution", "CA[18]", RO,
                                  note=note or "표시전용 파생")
_RES_CYCLES = lambda: F("Cycles / Revolution", "CA[18]", RO, xform="cycles",
                        note="= CA[18] / 2^CA[31] · 표시전용")
_RES_LINES = lambda: F("Lines / Revolution", "CA[18]", RO, xform="lines",
                       note="= CA[18] / 4 · 표시전용")


def _general(halls=False):
    rows = [F("Sensor Name", None, RO, static="(선택 센서명)"),
            F("Sensor Type", None, RO, static="Rotary"),
            F("Feedback Control Function", None, RO,
              static="Position + Velocity + Commutation")]
    if halls:
        rows.append(_HALLS_USE())
    return rows


def _sef(*fields):
    return ("Serial Encoder Frame", list(fields))


# ---------------------------------------------------------------------------------------
# Per-sensor group layouts — mirrors docs/eas-feedback-panels.md
# key: sensor id (int) or EAS name (str) for unconfirmed-ID sensors
# value: [(group title, [fields]), ...]
# ---------------------------------------------------------------------------------------
_SERIAL_KAWASAKI_STYLE = lambda maint: [
    _D(), _HW_BITS(), _SW_BITS(), _HBM(), _MULTITURN(), _CLK(), _GLITCH_NS(),
    _POLL(), _EBM_HEX(), _CTIME(), _APO()] + ([_MAINT()] if maint else []) + [_FIR()]

SENSOR_GROUPS = {
    # --- Analog Input #1, Port C (f2) ---
    16: [("General", _general(halls=True)),
         ("Sensor Parameters", [
             _D(), F("Signal Type", "AR[1]", DD, OPT_SIGNAL),
             F("Analog Offset", "AS[1]", VALUE),
             F("Neg Dead-Band", "AD[1]", VALUE), F("Pos Dead-Band", "AD[2]", VALUE),
             F("Gain (A/V)", "AG[1]", VALUE),
             F("Analog Input Filter Type", None, RO, note="미확정"), _FIR()]),
         ("Resolution", [_RES_COUNTS()])],
    # --- Analog Sin/Cos, Port B (f5) ---
    3: [("General", _general()),
        ("Sensor Parameters", [
            _D(), _MULT(),
            F("Glitch Filter (Cycles/sec)", "CA[50]", VALUE, note="Port B"),
            _APO(), _FIR()]),
        ("Resolution", [_RES_CYCLES(), _RES_COUNTS()])],
    # --- Encoder Quad, Port B (f7) ---
    1: [("General", _general()),
        ("Sensor Parameters", [
            _D(), F("Glitch Filter (cnt/sec)", "CA[50]", VALUE, note="Port B"), _FIR()]),
        ("Resolution", [_RES_LINES(), _RES_COUNTS()])],
    # --- Halls Only, Port A (f9) ---
    4: [("General", _general()),
        ("Sensor Parameters", [_FIR()]),
        ("Resolution", [_RES_COUNTS(note="= 6 × 극쌍(CA[19]) · 표시전용")])],
    # --- Pulse and Direction, Port A / Port B (f11/f13) ---
    12: [("General", _general(halls=True)),
         ("Sensor Parameters", [_D(), _GLITCH_NS(), _FIR()]),
         ("Resolution", [_RES_COUNTS()])],
    11: [("General", _general(halls=True)),
         ("Sensor Parameters", [_D(), _GLITCH_NS(), _FIR()]),
         ("Resolution", [_RES_COUNTS()])],
    # --- Quad Exclusive 1, Port A (f15) ---
    2: [("General", _general(halls=True)),
        ("Sensor Parameters", [
            _D(), F("Glitch Filter (cnt/sec)", "CA[51]", VALUE, note="Port A"), _FIR()]),
        ("Resolution", [_RES_LINES(), _RES_COUNTS()])],
    # --- Resolver, Port B (f17) ---
    22: [("General", _general()),
         ("Sensor Parameters", [
             _D(), F("Resolver Pole Pairs", "CA[32]", VALUE), _MULT(),
             F("Resolver Frequency [kHz]", "CA[34]", DD, OPT_RESOLVER_FREQ,
               note="1.2kHz↔4 가정 1건 포함"),
             _APO(), _FIR()]),
         ("Resolution", [_RES_CYCLES(), _RES_COUNTS()])],
    # --- Serial - Panasonic Incremental, Port A (f21) ---
    29: [("General", _general()),
         ("Sensor Parameters", [
             _D(), _HW_BITS(), _SW_BITS(), _CLK(), _GLITCH_NS(), _POLL(),
             _EBM_HEX(), _CTIME(), _MAINT(), _FIR()]),
         ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - BiSS General, Port A (f27) ---
    24: [("General", _general()),
         ("Sensor Parameters", [
             _D(), F("Resolution Type", None, RO, note="미확정 (Binary)"),
             F("BiSS Mode", None, RO, note="미확정 (C-Mode)"),
             _CLK(), _GLITCH_NS(), _POLL(), _EBM_BOOL(),
             F("Warning Report", "CA[60]", RO, xform="bit10",
               note="CA[60] bit10 — RMW 쓰기 미지원"),
             _CTIME(), _APO(), _FIR()]),
         _sef(_HW_BITS(), _SW_BITS(), _MULTITURN(), _HBM(), _LSB(), _EBN(), _PTB()),
         ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - BiSS, Port A (f36) ---
    5: [("General", _general()),
        ("Sensor Parameters", [
            _D(), F("Temperature Support", "CA[60]", RO, xform="bit0",
                    note="CA[60] bit0 — RMW 쓰기 미지원"),
            _CLK(), _GLITCH_NS(), _POLL(), _EBM_BOOL(), _CTIME(), _APO(), _FIR()]),
        _sef(_HW_BITS(), _SW_BITS()),
        ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - EnDat 2.1 (f40) ---
    9: [("General", _general()),
        ("Sensor Parameters", [
            _D(), _CLK(), _GLITCH_NS(), _POLL(), _EBM_BOOL(), _CTIME(), _APO(), _FIR()]),
        _sef(_HW_BITS(), _SW_BITS(), _MULTITURN(), _HBM()),
        ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - EnDat 2.2 (f48) ★ this drive ---
    30: [("General", _general()),
         ("Sensor Parameters", [
             _D(), _CLK(), _GLITCH_NS(), _POLL(), _EBM_HEX(),
             F("Read EnDat External Temperature", "CA[60]", RO, xform="bit0",
               note="CA[60] bit0 — FW 01.01.16.10↑ 필요·RMW 쓰기 미지원"),
             _CTIME(), _APO(), _MAINT(), _FIR()]),
         _sef(_HW_BITS(), _SW_BITS(), _MULTITURN(), _HBM()),
         ("Resolution", [_RES_COUNTS(note="= 2^SW (실측 65536) · 표시전용")])],
    # --- Serial Absolute - Hiperface, Port A and B (f51) ---
    28: [("General", _general()),
         ("Sensor Parameters", [
             _D(), _HW_BITS(), _HBM(), _MULTITURN(), _MULT(),
             F("Hiperface serial status polling", None, RO, note="미확정 (Inactive)"),
             F("Glitch Filter (Cycles/sec)", "CA[50]", VALUE, note="Port B(sin/cos)"),
             _APO(), _FIR()]),
         ("Resolution", [_RES_CYCLES(), _RES_COUNTS()])],
    # --- Serial Absolute - Kawasaki, Port A (f61) ---
    23: [("General", _general()),
         ("Sensor Parameters", _SERIAL_KAWASAKI_STYLE(maint=False)),
         ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - Panasonic, Port A (f75) ---
    6: [("General", _general()),
        ("Sensor Parameters", _SERIAL_KAWASAKI_STYLE(maint=True)),
        ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - Sanyo / Nikon, Port A (f78) ---
    25: [("General", _general()),
         ("Sensor Parameters", _SERIAL_KAWASAKI_STYLE(maint=True)),
         ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - SSI, Port A (f84) ---
    18: [("General", _general()),
         ("Sensor Parameters", [
             _D(), _CLK(), _GLITCH_NS(), _SDPRES(), _FCD(), _POLL(), _EBM_BOOL(),
             _CTIME(), _APO(), _FIR()]),
         _sef(_HW_BITS(), _SW_BITS(), _MULTITURN(), _HBM(), _LSB(), _EBN(), _PTB()),
         ("Resolution", [_RES_COUNTS()])],
    # --- Serial Absolute - Tamagawa, Port A (f94) ---
    10: [("General", _general()),
         ("Sensor Parameters", _SERIAL_KAWASAKI_STYLE(maint=True)),
         ("Resolution", [_RES_COUNTS(note="실측 16384 = 2^14 · 표시전용")])],
    # --- Virtual Absolute - Gurley, Port B (f105) ---
    17: [("General", _general()),
         ("Sensor Parameters", [
             _D(), F("HW Sensor Resolution (Bits)", "CA[21]", DD, OPT_GURLEY_HW),
             _MULT(),
             F("Quad Glitch Filter (Cycles/sec)", "CA[50]", VALUE, note="Port B"),
             _GLITCH_NS(), _APO(), _FIR()]),
         ("Resolution", [_RES_CYCLES(), _RES_COUNTS()])],
    # --- unconfirmed-ID sensors (CA[41] value unknown -> selection/write blocked) ---
    "Serial Absolute - IAI, Port A": [
        ("General", _general()),
        ("Sensor Parameters", [
            _D(), _CLK(), _GLITCH_NS(), _HW_BITS(), _SW_BITS(), _HBM(), _MULTITURN(),
            _POLL(), _EBM_HEX(), _CTIME(), _APO(), _MAINT(), _FIR()]),
        ("Resolution", [_RES_COUNTS()])],
    "Serial Absolute - Mitsubishi, Port A": [
        ("General", _general()),
        ("Sensor Parameters", [
            _D(), _CLK(), _GLITCH_NS(), _HW_BITS(), _SW_BITS(), _HBM(), _MULTITURN(),
            _POLL(), _EBM_HEX(), _CTIME(), _APO(), _MAINT(), _FIR()]),
        ("Resolution", [_RES_COUNTS()])],
    "Serial Exclusive #3": [
        ("General", _general()),
        ("Sensor Parameters", [
            _D(), _HW_BITS(), _SW_BITS(), _HBM(), _MULTITURN(), _CLK(), _GLITCH_NS(),
            _PTB(), _LSB(), _SDPRES(), _FCD(), _EBM_BOOL(), _POLL(), _CTIME(), _APO()]),
        ("Resolution", [_RES_COUNTS()])],
}

# every EAS-grounded key (screen-verified from the EAS video)
SCREEN_VERIFIED = set(SENSOR_GROUPS.keys())

# xform -> extra commands needed to decode it
_XFORM_DEPS = {
    "sw_res": ("CA[59]", "CA[61]", "CA[58]"),
    "cycles": ("CA[18]", "CA[31]"),
    "lines": ("CA[18]",),
    "fir": ("CA[71]",),
}


def _norm_key(key):
    """Normalize a sensor key: numeric -> int, else the EAS name string."""
    if key is None:
        return None
    if isinstance(key, str) and not key.isdigit():
        return key
    try:
        return int(key)
    except (TypeError, ValueError):
        return key


def spec_for(key):
    """Return (groups, verified) for a sensor id or EAS name.

    groups = [(group_title, [field dicts])]; unknown sensor -> ([], False).
    """
    k = _norm_key(key)
    groups = SENSOR_GROUPS.get(k, [])
    return groups, (k in SCREEN_VERIFIED)


def iter_fields(key):
    """Yield every field dict of a sensor's groups."""
    groups, _ = spec_for(key)
    for _title, fields in groups:
        for f in fields:
            yield f


def commands_for(key):
    """All readable drive commands needed to populate this sensor's panel."""
    cmds = []
    for f in iter_fields(key):
        if f["cmd"] and f["kind"] != BTN:
            cmds.append(f["cmd"])
        for dep in _XFORM_DEPS.get(f["xform"] or "", ()):
            cmds.append(dep)
    seen, out = set(), []
    for c in cmds:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def decode_field(f, raws):
    """Raw drive values -> display value for one field. None if unavailable."""
    raws = raws or {}
    if f.get("static") is not None:
        return f["static"]
    cmd, x = f.get("cmd"), f.get("xform")
    v = raws.get(cmd) if cmd else None
    num = isinstance(v, (int, float))
    if x == "sw_res":
        hw, ca61, hbm = raws.get("CA[59]"), raws.get("CA[61]"), raws.get("CA[58]")
        if all(isinstance(t, (int, float)) for t in (hw, ca61, hbm)):
            return int(sw_from_raw(hw, ca61, hbm))
        return None
    if x == "cycles":
        ca18, ca31 = raws.get("CA[18]"), raws.get("CA[31]")
        if isinstance(ca18, (int, float)) and isinstance(ca31, (int, float)):
            return ca18 / (2 ** ca31)
        return None
    if x == "lines":
        ca18 = raws.get("CA[18]")
        return (ca18 / 4.0) if isinstance(ca18, (int, float)) else None
    if v is None:
        return None
    if x == "glitch_ns":
        return glitch_raw_to_ns(int(v)) if num else v
    if x == "clk_mhz":
        return ("%.3f" % clk_raw_to_mhz(v)) if num else v
    if x == "fcd_us":
        return "%.1f" % fcd_raw_to_us(v) if num else v
    if x == "hex":
        return ("0x%X" % int(v)) if num and v >= 0 else v
    if x == "fir":
        return "Disabled" if v == 0 else v
    if x in ("bit0", "bit10") and num:
        bit = 0 if x == "bit0" else 10
        return "Yes" if (int(v) >> bit) & 1 else "No"
    if f["kind"] == DD and f.get("options"):
        for text, raw in f["options"]:
            if raw == v:
                return text
    return v


def encode_value(f, text, raws=None, pending=None):
    """UI text -> (command, raw value) for an editable VALUE field.

    sw_res uses CA[59]/CA[58] from `pending` writes first, then live raws.
    Raises ValueError on bad input or missing dependencies.
    """
    raws, pending = raws or {}, pending or {}
    x = f.get("xform")
    if x == "hex":
        return f["cmd"], int(text, 0)
    if x == "sw_res":
        sw = int(float(text))
        hw = pending.get("CA[59]", raws.get("CA[59]"))
        hbm = pending.get("CA[58]", raws.get("CA[58]"))
        if not isinstance(hw, (int, float)) or not isinstance(hbm, (int, float)):
            raise ValueError("SW Res 변환에 CA[59]/CA[58] 필요 — 드라이브 읽기 후 가능")
        return "CA[61]", int(ca61_from_sw(int(hw), sw, int(hbm)))
    fv = float(text)
    return f["cmd"], (int(fv) if fv == int(fv) else fv)
