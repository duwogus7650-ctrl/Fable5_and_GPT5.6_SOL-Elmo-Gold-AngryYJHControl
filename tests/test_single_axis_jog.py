"""Endless JV jog kernel tests (single_axis_motion.run_jog).

Guard coverage follows the 2026-07-20 fable-physics motion-safety review:
signature interlock, command-freshness deadman, max-duration timebox, ramp-aware
overspeed + absolute ceiling, current-vector cap, two-tier stop chain
(operator = JV=0/BG decel, fault/runaway = immediate ST->MO=0), restore only when
torque-disable is GREEN-verified, no-rotation honesty, and never sending SV.

P2 CONTRACT CHANGE (fable-physics SPEC freeze 2026-07-21): the fixed
motor-specific limits (3000 rpm ceiling / 5.0 A cap / 3.0 A default) were
REPLACED by MotorProfile-derived values:
    jog_ceiling_rpm  = 1.0  * effective_rated_rpm  (invalid profile -> 300)
    cap ceiling      = 0.25 * CL[1]   (f_I_def; opt-in hard max 0.50 * CL[1])
    default cap      = 0.15 * CL[1]   (f_I_run)
    voltage warn     = 0.90 * rated   (N_WARN, confirm gate -- not a block)
The mock registers therefore encode the REAL bench unit (failure-ledger
2026-07-15 mock-vs-field discipline): CL[1]=21.2132 A (=15 Arms*sqrt2),
PL[1]=70.7107 A, VH[2]=3,932,160 counts/s (=3600 rpm at CA[18]=65536), and the
requests carry a matching MotorProfile.  Assertions were re-anchored to the
derived expectations WITHOUT weakening: over-ceiling is still a pre-write
reject, the cap is still enforced through PL[1]==CL[1]==cap.
"""
import dataclasses

import pytest

import single_axis_motion as sam
from motor_profile import MotorProfile

# Real bench unit (실기 확정치): 3600 rpm rated, CL[1]=15 Arms*sqrt2.
UNIT_DRIVE = {
    "CA[18]": 65536.0, "TS": 100e-6,
    "CL[1]": 21.2132, "PL[1]": 70.7107,
    "CA[19]": 21.0, "CA[28]": 0.0,
    "VH[2]": 3932160.0,
}
UNIT_PROFILE = MotorProfile.from_sources("unit21", UNIT_DRIVE)

# Virtual 8-pole-pair motor: 3000 rpm rated, low-current (CL[1]=2.5 A).
VIRT_DRIVE = {
    "CA[18]": 4096.0, "TS": 50e-6,
    "CL[1]": 2.5, "PL[1]": 7.07,
    "CA[28]": 1.0,
    "VH[2]": 204800.0,      # 204800*60/4096 = 3000 rpm exactly
}
VIRT_PROFILE = MotorProfile.from_sources("virt8", VIRT_DRIVE,
                                         {"pole_pairs": 8})
# Same drive readings but NO pole pairs from any source -> profile invalid.
INVALID_PROFILE = MotorProfile.from_sources("virt8-nopp", VIRT_DRIVE)
assert UNIT_PROFILE.is_valid and VIRT_PROFILE.is_valid
assert not INVALID_PROFILE.is_valid


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
        # Real bench-unit current limits (mock-vs-field ledger discipline);
        # they also feed the live-CL[1] leg of the P2 cap derivation.
        "PL[1]": 70.7107, "CL[1]": 21.2132,
    }
    for index in range(1, 13):
        reg.setdefault("FC[%d]" % index, 1)
    return reg


class JogSimLink:
    """Command-level double for the JV jog: JV latches VX only on the next BG."""

    def __init__(self, *, persistence_unknown=False, vx_override=None,
                 iq_override=None, no_motion=False, disable_stuck=False,
                 reg_overrides=None, fail_write=None, vx_seq=None,
                 lc_active_polls=0, sr_mo1_extra=0):
        # lc_active_polls: SR bit 13 (LC / current-limit) is reported set on the
        # first N SR reads taken while MO=1, then clears -- models the closed-loop
        # enable inrush clamping at the cap for a few polls before it settles.
        # sr_mo1_extra: bits always OR'd into SR while MO=1 (clean at MO=0 preflight)
        # -- models an unsafe bit that only appears during the enable transient.
        self.lc_active_polls = lc_active_polls
        self.sr_mo1_extra = int(sr_mo1_extra)
        self._mo1_sr_reads = 0
        self.unknown = persistence_unknown
        self.vx_override = vx_override      # fixed feedback VX (overspeed/runaway)
        self.iq_override = iq_override      # fixed active current (excursion)
        self.no_motion = no_motion          # VX stays 0 despite JV (breakaway)
        self.disable_stuck = disable_stuck
        self.fail_write = fail_write        # (key, raw) -> bool: raise on that write
        self.vx_seq = list(vx_seq) if vx_seq is not None else None  # scripted VX
        self._vx_i = 0
        self._motion_begun = False          # scripted VX only after first jog BG
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
            if self.fail_write and self.fail_write(key, raw):
                raise IOError("injected write failure: %s" % command)
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
            if jv != 0:
                self._motion_begun = True
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
        if (core == "VX" and self.vx_seq is not None and self.reg["MO"]
                and self._motion_begun):
            v = self.vx_seq[min(self._vx_i, len(self.vx_seq) - 1)]
            self._vx_i += 1
            return str(v)
        if (core == "VX" and self.vx_override is not None and self.reg["MO"]
                and self.pending_jv not in (None, 0)):
            return str(self.vx_override)
        if core == "SR":
            sr = int(self.reg["SR"])
            if self.reg["MO"]:
                sr |= self.sr_mo1_extra
                if self._mo1_sr_reads < self.lc_active_polls:
                    sr |= (1 << 13)
                self._mo1_sr_reads += 1
            return str(sr)
        if core not in self.reg:
            raise KeyError(core)
        return str(self.reg[core])

    @property
    def writes(self):
        return [command for command, _allow in self.log
                if "=" in command or command in ("BG", "ST")]


def _jr(**overrides):
    # P2: requests carry the connected motor's profile (planning authority);
    # the explicit 1.30 A cap sits inside the derived ceiling 0.25*21.2132.
    values = dict(max_speed_rpm=100.0, accel_rpm_s=30.0,
                  current_cap_a=1.30, timebox_s=60.0,
                  profile=UNIT_PROFILE)
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
    # P2 contract change: the ceiling is the profile rated speed (3600 rpm for
    # this unit), not a fixed 3000; one rpm above it is still a pre-write REJECT
    # (silent clamping of the request remains forbidden).
    ceiling = sam.jog_rpm_ceiling(UNIT_PROFILE)
    assert ceiling == pytest.approx(3600.0)
    drive = JogSimLink()
    result = _run(drive, JogCmd(Clock(), [(100.0, False)]),
                  max_speed_rpm=ceiling + 1.0)
    assert result.status == sam.RED
    assert drive.writes == []


def test_jog_current_cap_over_ceiling_is_rejected():
    # P2 contract change: the cap ceiling derives as f_I_def*CL[1]
    # (0.25*21.2132 = 5.3033 A) instead of the fixed 5.0 A; above it is still
    # a reject before any write.
    ceiling = sam.jog_current_cap_ceiling_a(UNIT_PROFILE)
    assert ceiling == pytest.approx(0.25 * 21.2132)
    drive = JogSimLink()
    result = _run(drive, JogCmd(Clock(), [(50.0, False)]),
                  current_cap_a=ceiling + 0.5)
    assert result.status == sam.RED
    assert "current_cap" in result.reason.lower()
    assert drive.writes == []


def test_jog_runs_at_raised_max_current_cap():
    # The peak cap was raised 1.30 -> 3.50 A historically: 1.30 A sat inside the
    # static-friction band so the closed-loop enable/hold transient current-limited
    # the drive (SR bit 13) and the enable SR check aborted.  P2 contract change:
    # the ceiling is now profile-derived (f_I_def*CL[1] = 5.3033 A for this unit,
    # comfortably above that 3.5 A field need) and running AT the ceiling must
    # still drive a real jog.
    ceiling = sam.jog_current_cap_ceiling_a(UNIT_PROFILE)
    assert ceiling >= 3.5
    drive = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(50.0, False), (50.0, False), (0.0, True)])
    result = _run(drive, cmd, clock=clock, current_cap_a=ceiling)
    assert result.status == sam.GREEN, result.reason
    assert any(w.startswith("JV=") for w in drive.writes)
    assert int(drive.reg["MO"]) == 0 and "SV" not in drive.writes


def test_jog_enable_tolerates_transient_current_limit_then_runs():
    # SR bit 13 (LC) is a limit *selector*, not a saturation event, so it is not
    # in _UNSAFE_SR_MASK. Whether it is set on a few enable polls or not, the
    # enable completes on servo-on and the jog runs.
    drive = JogSimLink(lc_active_polls=3)
    clock = Clock()
    cmd = JogCmd(clock, [(50.0, False), (50.0, False), (50.0, False),
                         (0.0, True)])
    result = _run(drive, cmd, clock=clock)
    assert result.status == sam.GREEN, result.reason
    assert any(w.startswith("JV=") for w in drive.writes)   # actually enabled + moved
    assert int(drive.reg["MO"]) == 0


def test_jog_enable_ignores_persistent_current_limit_selector():
    # Regression for the field bug: run_jog writes PL[1]==CL[1]==cap, which pins
    # LC (SR bit 13) set for the WHOLE enable+jog (no peak-budget window), exactly
    # as the real drive did (measured 0.1 A against a 3 A cap). LC is a selector,
    # not over-current, so a permanently-set bit 13 must still enable and jog
    # GREEN. Real over-current is bounded by the current-vector guard, not LC.
    drive = JogSimLink(lc_active_polls=10_000)   # bit 13 set on every MO=1 poll
    clock = Clock()
    cmd = JogCmd(clock, [(50.0, False), (50.0, False), (0.0, True)])
    result = _run(drive, cmd, clock=clock)
    assert result.status == sam.GREEN, result.reason
    assert any(w.startswith("JV=") for w in drive.writes)   # actually jogged
    assert int(drive.reg["MO"]) == 0


def test_jog_enable_still_aborts_immediately_on_other_unsafe_sr_bit():
    # Dropping bit 13 (LC selector) from the mask must not weaken the rest of it:
    # a genuinely unsafe bit that appears DURING the enable transient (here bit 6,
    # clean at the MO=0 preflight) still aborts on sight in the enable loop.
    drive = JogSimLink(sr_mo1_extra=(1 << 6))
    result = _run(drive, JogCmd(Clock(), [(50.0, False)]))
    assert result.status == sam.RED
    assert "unsafe sr status while enabling" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0


def test_jog_proceeds_with_zero_position_limits_that_a_ptp_move_would_reject():
    # Real Gold drives on this bench run with VL[3]=VH[3]=0 (no software position
    # window). A finite PA move requires a valid VL[3] < VH[3]; an endless JV jog
    # ignores VH[3]/VL[3] at the drive (CR p175), so the jog preflight must NOT
    # inherit that position-limit reject (regression: it did, blocking real jogs).
    drive = JogSimLink(reg_overrides={"VL[3]": 0, "VH[3]": 0,
                                      "XM[1]": 0, "XM[2]": 0})
    clock = Clock()
    cmd = JogCmd(clock, [(100.0, False), (100.0, False), (100.0, False),
                         (0.0, True)])
    result = _run(drive, cmd, clock=clock)
    assert result.status == sam.GREEN, result.reason
    assert "VL[3]" not in (result.reason or "")
    assert any(w.startswith("JV=") for w in drive.writes)   # actually energised
    assert int(drive.reg["MO"]) == 0 and "SV" not in drive.writes


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


# --- fable-critic HIGH/gap coverage ---------------------------------------------

def test_restore_failure_after_disable_reports_unknown_not_green():
    # Torque-off verifies GREEN, but the CL[1] restore write fails -> the session
    # settings are polluted; must be UNKNOWN (not a GREEN "restored"), never SV.
    drive = JogSimLink(
        fail_write=lambda k, raw: k == "CL[1]" and float(raw) == 21.2132)
    clock = Clock()
    result = _run(drive, JogCmd(clock, [(100.0, False), (0.0, True)]), clock=clock)
    assert result.status == sam.UNKNOWN
    assert result.evidence["settings_restored"] is False
    assert "restore" in result.reason.lower() or "config" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0
    assert not any("SV" in w for w in drive.writes)


def test_stuck_feedback_during_decel_is_caught_as_overspeed():
    # After stop is commanded the axis stays pinned at ~300 rpm (a stuck-at-speed
    # fault). The profiler-following overspeed reference decays and the guard must
    # fire (the old grace logic masked this).
    hi = int(round(300.0 * 65536 / 60.0))
    drive = JogSimLink(vx_seq=[hi])          # feedback pinned high forever
    clock = Clock()
    cmd = JogCmd(clock, [(300.0, False)] * 20 + [(0.0, True)] * 15)
    result = _run(drive, cmd, clock=clock, max_speed_rpm=300.0, accel_rpm_s=600.0)
    assert result.status == sam.RED
    assert "overspeed" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0


def test_operator_stop_decelerates_before_disable_runaway_abort_is_immediate():
    # Operator stop writes JV=0 (gentle decel) BEFORE ST; a runaway abort goes
    # straight to ST with no gentle JV=0 first.
    d1 = JogSimLink()
    r1 = _run(d1, JogCmd(Clock(), [(100.0, False), (0.0, True)]))
    assert r1.status == sam.GREEN
    seq1 = [w for w in d1.writes if w == "ST" or w.startswith("JV=")]
    assert "ST" in seq1
    jv0_idx = max(i for i, w in enumerate(seq1) if w == "JV=0")
    assert jv0_idx < seq1.index("ST"), "operator stop writes JV=0 before ST"

    d2 = JogSimLink(vx_override=2_000_000)   # instant runaway -> immediate abort
    r2 = _run(d2, JogCmd(Clock(), [(100.0, False)]))
    assert r2.status == sam.RED
    seq2 = [w for w in d2.writes if w == "ST" or w.startswith("JV=")]
    st2 = seq2.index("ST")
    assert not any(w == "JV=0" for w in seq2[:st2]), (
        "runaway abort must not do a gentle JV=0 decel before ST")


def test_nan_command_fails_safe_to_stop():
    drive = JogSimLink()
    clock = Clock()
    result = _run(drive, JogCmd(clock, [(float("nan"), False), (0.0, True)]),
                  clock=clock)
    assert result.status in (sam.GREEN, sam.UNKNOWN)
    assert int(drive.reg["MO"]) == 0
    # a NaN target is never sent as a live JV
    assert not any(w.startswith("JV=") and w not in ("JV=0",)
                   for w in drive.writes)


# --- retarget-tick dt skew: field false-overspeed regression (2026-07-19) --------
#
# Field failure: releasing a low-speed jog intermittently tripped the overspeed
# guard on the DECEL leg (|VX| 16889/19708/28088/28410 cnt/s vs limits
# 16384/17279/27633/28018 -- all inside the 15..~27 rpm window between the
# floor and 1.25x envelope).  Root cause: on the retarget tick the integrator
# debited the wall-clock interval since the PREVIOUS tick (which the drive
# spent still ramping toward the OLD target) in the NEW (decel) direction,
# opening a ~2*AC*dt expected-vs-VX gap that stayed frozen through the decel.
# Only a slow host tick (~100-140 ms) adjacent to the release made dt big
# enough to trip; the ~65 ms nominal tick left the window empty.
#
# The fix (single_axis_motion.py retarget block): pre-credit expected toward
# the OLD last_jv over [last_tick, t_bg], anchor last_tick at the BG instant,
# and never rewind the anchor (last_tick = max(last_tick, now)).

RTT_S = 0.0032   # one serial command round-trip (field timeline, jog_sim2)


class ProfilerClockLink(JogSimLink):
    """JogSimLink + shared-clock serial cost + drive-side velocity profiler.

    Every ``command()`` advances the shared ``Clock`` by ``serial_s`` (one
    serial round trip), so the 10-register jog sample costs ~32 ms and a poll
    tick ~62 ms of clock time -- reproducing the field timing that framed the
    2026-07-19 false trips.  The drive velocity ``_v`` ramps toward the last
    BG-latched target at ``accel_rpm_s`` in clock time and VX reads return the
    live profile value.

    Fault/latency injection:

    * ``stall_map={vx_read_index: extra_s}`` -- extra clock time consumed right
      after the profile value of that post-BG VX read is latched (index = the
      runtime poll index, the enable-loop/preflight reads are not counted).
      Models a slow host tick: the sample and the whole poll stretch, but the
      returned VX is the speed at read time.
    * ``chronic_vx_stall_s`` -- the same extra on EVERY post-BG VX read.
    * ``jv_stall_map={jv_write_index: extra_s}`` -- extra clock time consumed
      BY the JV= write itself (before BG lands): a slow retarget write leg.
    * ``freeze_on_stop`` -- on the first JV=0 after motion the profile freezes
      at its instantaneous speed (stuck-at-speed feedback fault at release).
    * ``runaway_on_stop`` -- on the first JV=0 after motion the profile keeps
      ACCELERATING in the motion direction instead of decelerating.
    """

    def __init__(self, clock, *, accel_rpm_s=30.0, serial_s=RTT_S,
                 stall_map=None, chronic_vx_stall_s=0.0, jv_stall_map=None,
                 freeze_on_stop=False, runaway_on_stop=False, **kwargs):
        super().__init__(**kwargs)
        self.clock = clock
        self.serial_s = float(serial_s)
        self.accel_cps = float(accel_rpm_s) * 65536.0 / 60.0
        self.stall_map = dict(stall_map or {})
        self.chronic_vx_stall_s = float(chronic_vx_stall_s)
        self.jv_stall_map = dict(jv_stall_map or {})
        self.freeze_on_stop = bool(freeze_on_stop)
        self.runaway_on_stop = bool(runaway_on_stop)
        self._v = 0.0
        self._t = clock()
        self._target = 0.0
        self._frozen = False
        self._runaway_dir = 0.0
        self._vx_reads = 0        # post-BG VX read counter == runtime poll index
        self._jv_writes = 0
        self.vx_trace = []        # (vx_read_index, clock_t, profile_v)

    def _advance_profile(self):
        t = self.clock()
        dt = t - self._t
        self._t = t
        if dt <= 0 or self._frozen:
            return
        if self._runaway_dir:
            self._v += self._runaway_dir * self.accel_cps * dt
            return
        dv = self._target - self._v
        step = self.accel_cps * dt
        if abs(dv) <= step:
            self._v = self._target
        else:
            self._v += step if dv > 0 else -step

    def command(self, command, timeout_ms=1000, allow_motion=False):
        core = "".join(command.split()).rstrip(";")
        if core.startswith("JV="):
            idx = self._jv_writes
            self._jv_writes += 1
            # the write itself may be slow: BG (and the profile retarget) lands late
            self.clock.advance(self.serial_s + self.jv_stall_map.get(idx, 0.0))
            jv = int(float(core[3:]))
            if jv == 0 and self._motion_begun:
                self._advance_profile()
                if self.freeze_on_stop:
                    self._frozen = True
                if self.runaway_on_stop and not self._runaway_dir:
                    self._runaway_dir = 1.0 if self._v >= 0 else -1.0
            return super().command(command, timeout_ms=timeout_ms,
                                   allow_motion=allow_motion)
        self.clock.advance(self.serial_s)
        if core == "BG":
            out = super().command(command, timeout_ms=timeout_ms,
                                  allow_motion=allow_motion)
            # ramp on the OLD target up to the BG instant, THEN switch target
            self._advance_profile()
            if not self._frozen and not self._runaway_dir:
                self._target = float(self.pending_jv)
            return out
        if core == "VX" and int(self.reg["MO"]) == 1 and self._motion_begun:
            self._advance_profile()
            value = self._v
            idx = self._vx_reads
            self._vx_reads += 1
            self.vx_trace.append((idx, self.clock(), value))
            extra = self.stall_map.get(idx, 0.0) + self.chronic_vx_stall_s
            if extra:
                self.clock.advance(extra)   # slow tick AFTER the value latched
            return str(int(round(value)))
        return super().command(command, timeout_ms=timeout_ms,
                               allow_motion=allow_motion)


# Field danger window: floor (15 rpm) < |VX| < ~27.4 rpm where the frozen gap
# could beat 1.25*expected+margin without the floor saving it.
_WINDOW_LO = 16384.0
_WINDOW_HI = 29930.0


def test_jog_release_during_accel_slow_tick_no_false_overspeed():
    # A) 50 rpm tap at 30 rpm/s: release after ~9 polls (mid-ramp, |VX|~20-27k)
    #    with a ~0.13 s host stall on the VX read of the tick JUST BEFORE the
    #    release.  Pre-fix this froze a ~2*AC*dt gap and tripped the guard in
    #    the field window; the fixed retarget accounting must ride the decel
    #    down to a clean operator stop.
    clock = Clock()
    drive = ProfilerClockLink(clock, accel_rpm_s=30.0, stall_map={8: 0.13})
    cmd = JogCmd(clock, [(50.0, False)] * 9 + [(0.0, True)] * 60)
    result = _run(drive, cmd, clock=clock,
                  max_speed_rpm=50.0, accel_rpm_s=30.0)
    assert result.status == sam.GREEN, (result.reason, drive.vx_trace[-3:])
    assert result.reason == "stopped"
    assert int(drive.reg["MO"]) == 0
    # the double really released inside the field danger window (else this
    # test would not exercise the bug at all)
    release_v = abs(drive.vx_trace[9][2])
    assert _WINDOW_LO < release_v < _WINDOW_HI, release_v

    # B) hardened variant: EVERY VX read chronically slow by 0.13 s.  Sample
    #    age stays under the host watchdog (10 reads * RTT + 0.13 < 0.25 s),
    #    so no age abort masks the check; the run must still end GREEN.
    assert (len(sam._JOG_SAMPLE_READS) * RTT_S + 0.13
            < sam.MAX_ACTIVE_SAMPLE_AGE_S)
    clock2 = Clock()
    drive2 = ProfilerClockLink(clock2, accel_rpm_s=30.0,
                               chronic_vx_stall_s=0.13)
    cmd2 = JogCmd(clock2, [(50.0, False)] * 3 + [(0.0, True)] * 60)
    result2 = _run(drive2, cmd2, clock=clock2,
                   max_speed_rpm=50.0, accel_rpm_s=30.0)
    assert result2.status == sam.GREEN, (result2.reason, drive2.vx_trace[-3:])
    assert result2.reason == "stopped"
    release_v2 = abs(drive2.vx_trace[3][2])
    assert _WINDOW_LO < release_v2 < _WINDOW_HI, release_v2


def test_jog_release_at_cruise_slow_retarget_tick_no_false_overspeed():
    # Reach 50 rpm cruise, then release with the retarget JV=0 write itself
    # slow by 0.2 s (BG lands late).  Pre-fix the integrator debited that
    # whole interval in the decel direction before the drive ever received
    # the command, freezing a gap that tripped as the decel crossed the
    # danger window.  Post-fix the BG anchor removes the skew -> GREEN.
    clock = Clock()
    drive = ProfilerClockLink(clock, accel_rpm_s=30.0, jv_stall_map={1: 0.2})
    cmd = JogCmd(clock, [(50.0, False)] * 32 + [(0.0, True)] * 80)
    result = _run(drive, cmd, clock=clock,
                  max_speed_rpm=50.0, accel_rpm_s=30.0)
    assert result.status == sam.GREEN, (result.reason, drive.vx_trace[-4:])
    assert result.reason == "stopped"
    assert int(drive.reg["MO"]) == 0
    # released from cruise, and the decel leg really swept the danger window
    assert abs(drive.vx_trace[32][2]) > 45000.0
    swept = [abs(v) for _i, _t, v in drive.vx_trace[32:]
             if _WINDOW_LO < abs(v) < _WINDOW_HI]
    assert swept, "decel leg never sampled inside the field danger window"


def test_jog_stuck_feedback_after_release_still_red_despite_slow_tick():
    # HIGH-2 tooth check: the SAME timing as the false-positive scenario, but
    # the feedback genuinely freezes at the release speed (stuck-at-speed
    # fault).  The fix must not blunt the guard: expected decays at AC while
    # |VX| stays pinned above the floor -> still RED overspeed.
    clock = Clock()
    drive = ProfilerClockLink(clock, accel_rpm_s=30.0, stall_map={8: 0.13},
                              freeze_on_stop=True)
    cmd = JogCmd(clock, [(50.0, False)] * 9 + [(0.0, True)] * 300)
    result = _run(drive, cmd, clock=clock,
                  max_speed_rpm=50.0, accel_rpm_s=30.0)
    assert result.status == sam.RED, result.reason
    assert "overspeed" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0
    # the frozen speed sat above the guard floor (the fault was catchable)
    assert abs(drive.vx_trace[-1][2]) > _WINDOW_LO


# --- P2 profile-derived ceilings / caps / warning thresholds ---------------------
#
# Acceptance criterion 4 of the P2 segment contract: prove on TWO virtual
# profiles (real unit 3600 rpm / virtual 8-pole-pair 3000 rpm) that the
# ceilings, caps and warning thresholds come out exactly per the frozen SPEC
# derivations, each cross-checked by literal arithmetic (two-path check).


def test_p2_derivations_current_unit_3600():
    # jog_ceiling_rpm = 1.0 * effective_rated_rpm (no fraction)
    assert sam.jog_rpm_ceiling(UNIT_PROFILE) == pytest.approx(3600.0)
    assert UNIT_PROFILE.effective_rated_rpm == pytest.approx(
        3932160.0 * 60.0 / 65536.0)          # cross-path: VH[2]*60/CA[18]
    # cap ceiling = f_I_def * CL[1]
    assert sam.jog_current_cap_ceiling_a(UNIT_PROFILE) == pytest.approx(
        0.25 * 21.2132)                       # = 5.3033 A
    # default cap = f_I_run * CL[1] (rounded to drive-safe 4 decimals)
    assert sam.jog_default_current_cap_a(UNIT_PROFILE) == pytest.approx(
        round(0.15 * 21.2132, 4))             # = 3.182 A
    # opt-in hard max = f_I_max * CL[1]
    assert sam.jog_current_cap_ceiling_a(
        UNIT_PROFILE, allow_high_current=True) == pytest.approx(0.5 * 21.2132)
    # voltage warn threshold = N_WARN * rated
    assert sam.jog_voltage_warn_rpm(UNIT_PROFILE) == pytest.approx(
        0.90 * 3600.0)                        # = 3240 rpm


def test_p2_derivations_virtual_8pp_3000():
    assert sam.jog_rpm_ceiling(VIRT_PROFILE) == pytest.approx(3000.0)
    assert VIRT_PROFILE.effective_rated_rpm == pytest.approx(
        204800.0 * 60.0 / 4096.0)             # cross-path
    assert sam.jog_current_cap_ceiling_a(VIRT_PROFILE) == pytest.approx(
        0.25 * 2.5)                           # = 0.625 A
    assert sam.jog_default_current_cap_a(VIRT_PROFILE) == pytest.approx(
        round(0.15 * 2.5, 4))                 # = 0.375 A
    assert sam.jog_voltage_warn_rpm(VIRT_PROFILE) == pytest.approx(2700.0)


def test_p2_jog_at_full_rated_speed_is_accepted():
    # 3600 rpm = the profile ceiling AND exactly the live VH[2]; the request is
    # accepted (<= on both authorities) and the JV target equals VH[2].
    drive = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(3600.0, False), (3600.0, False), (0.0, True)])
    result = _run(drive, cmd, clock=clock, max_speed_rpm=3600.0,
                  current_cap_a=3.0)
    assert result.status == sam.GREEN, result.reason
    jv = [int(w.split("=")[1]) for w in drive.writes if w.startswith("JV=")]
    assert int(round(3600.0 * 65536 / 60.0)) in jv     # = 3,932,160 = VH[2]
    assert int(drive.reg["MO"]) == 0


def test_p2_virtual_profile_speed_bounds():
    # 3000 rpm passes; 3001 rpm is rejected before any write.
    d1 = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(3000.0, False), (0.0, True)])
    r1 = _run(d1, cmd, clock=clock, profile=VIRT_PROFILE,
              max_speed_rpm=3000.0, current_cap_a=0.5)
    assert r1.status == sam.GREEN, r1.reason
    d2 = JogSimLink()
    r2 = _run(d2, JogCmd(Clock(), [(100.0, False)]), profile=VIRT_PROFILE,
              max_speed_rpm=3001.0, current_cap_a=0.5)
    assert r2.status == sam.RED
    assert d2.writes == []


def test_p2_virtual_profile_current_bounds_min_wins():
    # Profile CL[1]=2.5 A although the live drive still reports 21.2132 A:
    # min wins (fail-closed), so the ceiling is 0.625 A and 0.7 A is rejected.
    d1 = JogSimLink()
    r1 = _run(d1, JogCmd(Clock(), [(50.0, False)]), profile=VIRT_PROFILE,
              current_cap_a=0.7)
    assert r1.status == sam.RED
    assert "ceiling" in r1.reason.lower()
    assert d1.writes == []
    # A None cap resolves to the f_I_run default 0.375 A and is applied as
    # PL[1]==CL[1]==0.375 in the RAM profile.
    d2 = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(50.0, False), (0.0, True)])
    r2 = _run(d2, cmd, clock=clock, profile=VIRT_PROFILE, current_cap_a=None)
    assert r2.status == sam.GREEN, r2.reason
    assert r2.evidence["applied_settings"]["CL[1]"] == pytest.approx(0.375)
    assert r2.evidence["cap_derivation"]["default_used"] is True
    assert r2.evidence["cap_derivation"]["basis_a"] == pytest.approx(2.5)


def test_p2_invalid_profile_falls_back_to_300_and_live_cl1():
    # Invalid profile (no pole pairs): ceiling = JOG_MAX_RPM_DEFAULT = 300 rpm
    # (never 3000/3600), current basis = live CL[1] alone.
    d1 = JogSimLink()
    r1 = _run(d1, JogCmd(Clock(), [(100.0, False)]), profile=INVALID_PROFILE,
              max_speed_rpm=301.0)
    assert r1.status == sam.RED
    assert "300" in r1.reason
    assert d1.writes == []
    d2 = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(250.0, False), (0.0, True)])
    r2 = _run(d2, cmd, clock=clock, profile=INVALID_PROFILE,
              max_speed_rpm=250.0, current_cap_a=None)
    assert r2.status == sam.GREEN, r2.reason
    # default = f_I_run * live CL[1] = 0.15*21.2132 = 3.182 (4-decimal wire)
    assert r2.evidence["applied_settings"]["CL[1]"] == pytest.approx(3.182)
    assert r2.evidence["cap_derivation"]["profile_valid"] is False
    assert r2.evidence["cap_derivation"]["basis_a"] == pytest.approx(21.2132)


def test_p2_no_profile_behaves_like_invalid_profile():
    drive = JogSimLink()
    result = _run(drive, JogCmd(Clock(), [(100.0, False)]), profile=None,
                  max_speed_rpm=301.0)
    assert result.status == sam.RED
    assert drive.writes == []
    d2 = JogSimLink()
    clock = Clock()
    r2 = _run(d2, JogCmd(clock, [(100.0, False), (0.0, True)]), clock=clock,
              profile=None, max_speed_rpm=100.0, current_cap_a=None)
    assert r2.status == sam.GREEN, r2.reason
    assert r2.evidence["applied_settings"]["CL[1]"] == pytest.approx(3.182)


def test_p2_opt_in_high_current_ceiling():
    # 8.0 A is above the default ceiling (5.3033 A) -> reject without the
    # explicit opt-in; with allow_high_current it sits under f_I_max*CL[1]
    # (10.6066 A) and runs.
    d1 = JogSimLink()
    r1 = _run(d1, JogCmd(Clock(), [(50.0, False)]), current_cap_a=8.0)
    assert r1.status == sam.RED
    assert d1.writes == []
    d2 = JogSimLink()
    clock = Clock()
    cmd = JogCmd(clock, [(50.0, False), (0.0, True)])
    r2 = _run(d2, cmd, clock=clock, current_cap_a=8.0, allow_high_current=True)
    assert r2.status == sam.GREEN, r2.reason
    assert r2.evidence["applied_settings"]["CL[1]"] == pytest.approx(8.0)
    assert r2.evidence["cap_derivation"]["fraction"] == pytest.approx(0.5)


def test_p2_voltage_warn_evidence_flag():
    # The kernel records (does not block on) the N_WARN band: 3300 rpm > 3240
    # flags over_voltage_warn; 3200 rpm does not.
    d1 = JogSimLink()
    clock = Clock()
    r1 = _run(d1, JogCmd(clock, [(3300.0, False), (0.0, True)]), clock=clock,
              max_speed_rpm=3300.0, current_cap_a=3.0)
    assert r1.status == sam.GREEN, r1.reason
    sd = r1.evidence["speed_derivation"]
    assert sd["over_voltage_warn"] is True
    assert sd["voltage_warn_rpm"] == pytest.approx(3240.0)
    assert sd["jog_ceiling_rpm"] == pytest.approx(3600.0)
    d2 = JogSimLink()
    clock2 = Clock()
    r2 = _run(d2, JogCmd(clock2, [(3200.0, False), (0.0, True)]), clock=clock2,
              max_speed_rpm=3200.0, current_cap_a=3.0)
    assert r2.status == sam.GREEN, r2.reason
    assert r2.evidence["speed_derivation"]["over_voltage_warn"] is False


def test_p2_hold_current_advisory_from_i_ba_history():
    # SPEC: the fixed "hold current ~3.25 A" comment is replaced by the
    # profile's measured i_ba_history with the k_hold=1.5 margin (advisory,
    # never a gate).
    prof = dataclasses.replace(UNIT_PROFILE, i_ba_history=(3.0, 2.1))
    d1 = JogSimLink()
    clock = Clock()
    r1 = _run(d1, JogCmd(clock, [(50.0, False), (0.0, True)]), clock=clock,
              profile=prof, current_cap_a=4.0)
    assert r1.status == sam.GREEN, r1.reason
    adv = r1.evidence["hold_current_advisory"]
    assert adv["required_cap_a"] == pytest.approx(1.5 * 3.0)
    assert adv["cap_ok"] is False            # 4.0 < 4.5: advisory only
    d2 = JogSimLink()
    clock2 = Clock()
    r2 = _run(d2, JogCmd(clock2, [(50.0, False), (0.0, True)]), clock=clock2,
              profile=prof, current_cap_a=5.0)
    assert r2.status == sam.GREEN, r2.reason
    assert r2.evidence["hold_current_advisory"]["cap_ok"] is True


def test_p2_px_overflow_projection_recorded_and_gate_fail_closed():
    # Normal run records the projection numbers (comment constants moved to
    # evidence per SPEC); a huge live PX with a fast/long session still
    # rejects before any write.
    d1 = JogSimLink()
    clock = Clock()
    r1 = _run(d1, JogCmd(clock, [(100.0, False), (0.0, True)]), clock=clock)
    assert r1.status == sam.GREEN, r1.reason
    proj = r1.evidence["px_overflow_projection"]
    assert proj["gate_counts"] == pytest.approx(0.5 * 2 ** 31)
    assert proj["v_cap_counts_per_s"] == pytest.approx(100.0 * 65536 / 60.0)
    assert proj["projected_abs_counts"] < proj["gate_counts"]
    d2 = JogSimLink(reg_overrides={"PX": 1_000_000_000})
    r2 = _run(d2, JogCmd(Clock(), [(3600.0, False)]),
              max_speed_rpm=3600.0, current_cap_a=3.0, timebox_s=120.0)
    assert r2.status == sam.RED
    assert "overflow" in r2.reason.lower()
    assert d2.writes == []
    assert (r2.evidence["px_overflow_projection"]["projected_abs_counts"]
            >= r2.evidence["px_overflow_projection"]["gate_counts"])


def test_jog_runaway_during_decel_still_red():
    # After release the profiler ACCELERATES instead of decelerating (runaway
    # during the decel leg).  Expected decays while |VX| climbs -> RED within
    # a few polls, immediate two-tier abort path.
    clock = Clock()
    drive = ProfilerClockLink(clock, accel_rpm_s=30.0, runaway_on_stop=True)
    cmd = JogCmd(clock, [(50.0, False)] * 32 + [(0.0, True)] * 300)
    result = _run(drive, cmd, clock=clock,
                  max_speed_rpm=50.0, accel_rpm_s=30.0)
    assert result.status == sam.RED, result.reason
    assert "overspeed" in result.reason.lower()
    assert int(drive.reg["MO"]) == 0
    # it really was accelerating past the release speed when caught
    assert abs(drive.vx_trace[-1][2]) > abs(drive.vx_trace[31][2])
