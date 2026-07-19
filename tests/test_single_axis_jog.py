"""Endless JV jog kernel tests (single_axis_motion.run_jog).

Guard coverage follows the 2026-07-20 fable-physics motion-safety review:
signature interlock, command-freshness deadman, max-duration timebox, ramp-aware
overspeed + absolute ceiling, current-vector cap, two-tier stop chain
(operator = JV=0/BG decel, fault/runaway = immediate ST->MO=0), restore only when
torque-disable is GREEN-verified, no-rotation honesty, and never sending SV.
"""
import pytest

import single_axis_motion as sam


class Clock:
    """Manual monotonic clock; advances only when ``advance`` is called.

    run_jog is driven by passing ``sleep_fn=clock.advance`` so every tick's
    ``sleep_fn(JOG_POLL_S)`` moves time forward deterministically.
    """

    def __init__(self, start=10.0):
        self.t = float(start)

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += float(dt)


class JogCmd:
    """Scriptable jog command source: yields {rpm, stop, ts} per poll.

    script entries are (rpm, stop) with a fresh timestamp, or (rpm, stop, age)
    where age subtracts from the live clock to simulate a stale/host-stalled
    command for the deadman path.
    """

    def __init__(self, clock, script):
        self.clock = clock
        self.script = list(script)
        self.i = 0

    def __call__(self):
        if self.i < len(self.script):
            item = self.script[self.i]
            self.i += 1
        else:
            item = self.script[-1] if self.script else (0.0, True)
        rpm, stop = item[0], item[1]
        ts = self.clock() - (item[2] if len(item) > 2 else 0.0)
        return {"rpm": rpm, "stop": stop, "ts": ts}


def _base_reg():
    reg = {
        "UM": 5, "RM": 0, "MO": 0, "SO": 0, "MF": 0, "PS": -2,
        "SR": (1 << 14) | (1 << 15),
        "PX": 0, "VX": 0, "PE": 0, "ID": 0.0, "IQ": 0.0, "MS": 3,
        "DV[3]": 0, "OV[2]": 3,
        "CA[18]": 65536,
        "VH[2]": 3_932_160,
        "VL[3]": -1_000_000, "VH[3]": 1_000_000,
        "XM[1]": -2_000_000, "XM[2]": 2_000_000,
        "SP": 100_000, "AC": 1_000_000, "DC": 1_000_000,
        "FS": 123, "SF[1]": 0, "SF[2]": 2, "SD": 1_000_000_000,
        "PL[1]": 10.0, "CL[1]": 5.0,
    }
    for index in range(1, 13):
        reg.setdefault("FC[%d]" % index, 1)
    return reg


class JogSimLink:
    """Command-level double for the JV jog: JV latches VX only on the next BG."""

    def __init__(self, *, persistence_unknown=False, vx_override=None,
                 iq_override=None, no_motion=False, disable_stuck=False,
                 reg_overrides=None):
        self.unknown = persistence_unknown
        self.vx_override = vx_override      # fixed feedback VX (overspeed/runaway)
        self.iq_override = iq_override      # fixed active current (excursion)
        self.no_motion = no_motion          # VX stays 0 despite JV (breakaway)
        self.disable_stuck = disable_stuck
        self.pending_jv = None
        self.log = []
        self.reg = _base_reg()
        if reg_overrides:
            self.reg.update(reg_overrides)

    def persistence_unknown_latched(self):
        return self.unknown

    def transaction_session_identity(self):
        return "session-A"

    def command(self, command, timeout_ms=1000, allow_motion=False):
        self.log.append((command, bool(allow_motion)))
        core = "".join(command.split()).rstrip(";")
        if "=" in core:
            key, raw = core.split("=", 1)
            value = float(raw)
            value = int(value) if value.is_integer() else value
            if key == "MO":
                if value != 0 and not allow_motion:
                    raise PermissionError("MO=1 requires allow_motion")
                if not (self.disable_stuck and value == 0):
                    self.reg["MO"] = int(value)
                    self.reg["SO"] = int(value)
                    self.reg["MS"] = 1 if value else 3
                    if value:
                        self.reg["SR"] |= (1 << 4)
                    else:
                        self.reg["SR"] &= ~(1 << 4)
                        self.reg["ID"] = 0
                        self.reg["IQ"] = 0
                        self.reg["VX"] = 0
                return ""
            if key == "JV":
                if not allow_motion:
                    raise PermissionError("JV requires allow_motion")
                self.pending_jv = int(value)
                self.reg["JV"] = int(value)
                return ""
            self.reg[key] = value
            return ""
        if core == "BG":
            if not allow_motion:
                raise PermissionError("BG requires allow_motion")
            if self.pending_jv is None:
                raise IOError("BG without JV")
            jv = self.pending_jv
            self.reg["OV[2]"] = 3
            if self.no_motion:
                self.reg["VX"] = 0
            elif self.vx_override is not None:
                self.reg["VX"] = self.vx_override
            else:
                self.reg["VX"] = jv
            self.reg["MS"] = 2 if jv != 0 else (1 if self.reg["MO"] else 3)
            return ""
        if core == "ST":
            self.reg["VX"] = 0
            self.reg["MS"] = 1 if self.reg["MO"] else 3
            return ""
        if core == "IQ" and self.iq_override is not None and self.reg["MO"]:
            return str(self.iq_override)
        if (core == "VX" and self.vx_override is not None and self.reg["MO"]
                and self.pending_jv not in (None, 0)):
            return str(self.vx_override)
        if core not in self.reg:
            raise KeyError(core)
        return str(self.reg[core])

    @property
    def writes(self):
        return [command for command, _allow in self.log
                if "=" in command or command in ("BG", "ST")]


def _jr(**overrides):
    values = dict(max_speed_rpm=100.0, accel_rpm_s=30.0,
                  current_cap_a=1.30, timebox_s=60.0)
    values.update(overrides)
    return sam.JogRequest(**values)


def _run(drive, cmd, *, signature_green=True, clock=None, **kw):
    clock = clock or Clock()
    return sam.run_jog(
        drive, _jr(**kw), signature_green=signature_green,
        jog_cmd_fn=cmd, sleep_fn=clock.advance,
        clock_fn=clock, sample_clock_fn=clock)


# --- gate / preflight ------------------------------------------------------------

def test_jog_rejects_without_signature_before_any_write():
    drive = JogSimLink()
    result = _run(drive, JogCmd(Clock(), [(100.0, False)]), signature_green=False)
    assert result.status == sam.RED
    assert "signature" in result.reason.lower()
    assert drive.writes == []


def test_jog_rejects_persistence_unknown_before_any_write():
    drive = JogSimLink(persistence_unknown=True)
    result = _run(drive, JogCmd(Clock(), [(100.0, False)]))
    assert result.status == sam.RED
    assert "unknown" in result.reason.lower()
    assert drive.writes == []


@pytest.mark.parametrize("key,value,needle", [
    ("MO", 1, "MO=0"),
    ("MF", 1, "fault"),
    ("PS", 1, "program"),
    ("UM", 2, "UM=5"),
])
def test_jog_preflight_rejects_unsafe_state_without_write(key, value, needle):
    drive = JogSimLink(reg_overrides={key: value})
    result = _run(drive, JogCmd(Clock(), [(100.0, False)]))
    assert result.status == sam.RED
    assert needle.lower() in result.reason.lower()
    assert drive.writes == []


def test_jog_speed_over_ceiling_is_rejected():
    drive = JogSimLink()
    result = _run(drive, JogCmd(Clock(), [(100.0, False)]),
                  max_speed_rpm=sam.JOG_MAX_RPM_CEILING + 1.0)
    assert result.status == sam.RED
    assert drive.writes == []


# --- green run / stop / restore --------------------------------------------------

def test_green_jog_runs_then_operator_stop_disables_and_restores():
    drive = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(100.0, False), (100.0, False), (100.0, False),
                         (0.0, True)])
    result = _run(drive, cmd, clock=clock)
    assert result.status == sam.GREEN
    # JV was written and BG-paired; motion energised then fully disabled.
    assert any(w.startswith("JV=") for w in drive.writes)
    assert "BG" in drive.writes
    assert "SV" not in drive.writes and "SV;" not in drive.writes
    assert int(drive.reg["MO"]) == 0 and int(drive.reg["SO"]) == 0
    # every temporary setting restored to its captured original
    for name in sam.TEMPORARY_SETTING_ORDER:
        assert result.evidence["original_settings"][name] == drive.reg[name]
    assert result.evidence["settings_restored"] is True


def test_jog_signed_direction_and_speed_clamp_to_max():
    drive = JogSimLink()
    clock = Clock()
    # request -250 rpm but session max is 100 rpm -> clamp to -100 rpm
    cmd = JogCmd(clock, [(-250.0, False), (-250.0, False), (0.0, True)])
    result = _run(drive, cmd, clock=clock)
    assert result.status == sam.GREEN
    jv_writes = [int(w.split("=")[1]) for w in drive.writes if w.startswith("JV=")]
    clamp = int(round(-100.0 * 65536 / 60.0))
    assert clamp in jv_writes            # clamped negative jog velocity
    assert all(abs(v) <= abs(clamp) for v in jv_writes)


def test_jog_never_sends_sv_on_any_path():
    drive = JogSimLink()
    result = _run(drive, JogCmd(Clock(), [(100.0, False), (0.0, True)]))
    assert result.evidence["sv_sent"] is False
    assert not any("SV" in w for w in drive.writes)


# --- deadman / timebox -----------------------------------------------------------

def test_stale_command_deadman_demotes_to_stop_and_disables():
    drive = JogSimLink()
    clock = Clock()
    # first tick fresh, then a command older than the deadman window -> stop
    cmd = JogCmd(clock, [(100.0, False),
                         (100.0, False, sam.JOG_DEADMAN_AGE_S + 0.2)])
    result = _run(drive, cmd, clock=clock)
    assert result.status == sam.GREEN
    assert int(drive.reg["MO"]) == 0
    # JV was driven back to zero by the deadman before disabling
    assert 0 in [int(w.split("=")[1]) for w in drive.writes if w.startswith("JV=")]


def test_timebox_expiry_stops_disables_and_restores():
    drive = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(100.0, False)])   # holds forever; timebox must end it
    result = _run(drive, cmd, clock=clock, timebox_s=0.5)
    assert result.status == sam.GREEN
    assert "timebox" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0
    assert result.evidence["settings_restored"] is True


# --- fault / runaway aborts (immediate torque-off) -------------------------------

def test_overspeed_runaway_aborts_immediately_disables_and_restores():
    # feedback VX far above the absolute ceiling -> immediate ST->MO=0
    drive = JogSimLink(vx_override=2_000_000)
    clock = Clock()
    result = _run(drive, JogCmd(clock, [(100.0, False)]), clock=clock)
    assert result.status == sam.RED
    assert "overspeed" in result.reason.lower()
    assert "ST" in drive.writes            # immediate torque-off path
    assert int(drive.reg["MO"]) == 0
    assert result.evidence["settings_restored"] is True


def test_current_excursion_aborts_disables_and_restores():
    drive = JogSimLink(iq_override=3.0)     # >> bounded jog cap
    clock = Clock()
    result = _run(drive, JogCmd(clock, [(100.0, False)]), clock=clock)
    assert result.status == sam.RED
    assert "current" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0


def test_unverified_disable_keeps_caps_and_never_restores_or_sends_sv():
    drive = JogSimLink(iq_override=3.0, disable_stuck=True)
    clock = Clock()
    result = _run(drive, JogCmd(clock, [(100.0, False)]), clock=clock)
    assert result.status == sam.UNKNOWN
    assert result.evidence["settings_restored"] is False
    # caps NOT restored while torque-disable is unverified
    assert drive.reg["CL[1]"] != result.evidence["original_settings"]["CL[1]"]
    assert not any("SV" in w for w in drive.writes)


# --- no rotation honesty ---------------------------------------------------------

def test_jog_commanded_but_no_rotation_reports_unknown():
    drive = JogSimLink(no_motion=True)
    clock = Clock()
    cmd = JogCmd(clock, [(100.0, False), (100.0, False), (0.0, True)])
    result = _run(drive, cmd, clock=clock)
    assert result.status == sam.UNKNOWN
    assert "breakaway" in result.reason.lower() or "no rotation" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0
    assert result.evidence["settings_restored"] is True
