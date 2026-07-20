import math

import pytest

import single_axis_motion as sam


class SimMotionLink:
    """Small command-level double; PA takes effect only on BG."""

    def __init__(self, *, persistence_unknown=False, fail_write=None,
                 trip_current=False, disable_stuck=False, final_ms_one=False,
                 corrupt_demand=False, ramp_once=False):
        self.unknown = persistence_unknown
        self.fail_write = fail_write
        self.trip_current = trip_current
        self.disable_stuck = disable_stuck
        self.final_ms_one = final_ms_one
        self.corrupt_demand = corrupt_demand
        self.ramp_once = ramp_once
        self.ramp_samples = 0
        self.enable_px_shift = 0
        self.switch_stop_after_bg = False
        self.wrong_mode_after_bg = False
        self.change_after_pa = {}
        self.motion_samples = []
        self.motion_sample_index = 0
        self.post_bg_id_a = None
        self.post_bg_iq_a = None
        self.begun = False
        self.log = []
        self.timeout_log = []
        self.pending_pa = None
        self.moving = False
        self.reg = {
            "UM": 5, "RM": 0, "MO": 0, "SO": 0, "MF": 0, "PS": -2,
            "SR": (1 << 14) | (1 << 15),
            "PX": 0, "VX": 0, "PE": 0, "ID": 0.0, "IQ": 0.0, "MS": 3,
            "DV[3]": 0, "OV[2]": 0,
            "CA[18]": 65536,
            "VH[2]": 2_000_000,
            "VL[3]": -1_000_000, "VH[3]": 1_000_000,
            "XM[1]": -2_000_000, "XM[2]": 2_000_000,
            "SP": 100_000, "AC": 1_000_000, "DC": 1_000_000,
            "FS": 123, "SF[1]": 0, "SF[2]": 2, "SD": 1_000_000_000,
            "PL[1]": 10.0, "CL[1]": 5.0,
            "CA[28]": 0, "CA[41]": 30, "CA[45]": 1,
            "CA[46]": 1, "CA[47]": 1, "CA[54]": 0,
            "CA[55]": 0, "CA[56]": 0, "CA[57]": 0,
            "FC[5]": 1, "FC[6]": 1,
            "BP[1]": 0, "BP[2]": 0, "SC[13]": 0,
        }
        for index in range(1, 13):
            self.reg.setdefault("FC[%d]" % index, 1)

    def persistence_unknown_latched(self):
        return self.unknown

    def transaction_session_identity(self):
        return "session-A"

    def command(self, command, timeout_ms=1000, allow_motion=False):
        self.log.append((command, bool(allow_motion)))
        self.timeout_log.append((command, timeout_ms))
        core = "".join(command.split()).rstrip(";")
        if "=" in core:
            key, raw = core.split("=", 1)
            if self.fail_write and self.fail_write(command, key, raw, self):
                raise IOError("injected write failure: %s" % command)
            value = float(raw)
            if value.is_integer():
                value = int(value)
            if key == "MO":
                if value != 0 and not allow_motion:
                    raise PermissionError("MO=1 requires allow_motion")
                if not (self.disable_stuck and value == 0):
                    self.reg["MO"] = int(value)
                    self.reg["SO"] = int(value)
                    self.reg["MS"] = 1 if value else 3
                    if value:
                        self.reg["SR"] |= (1 << 4)
                        if self.enable_px_shift:
                            self.reg["PX"] += self.enable_px_shift
                    else:
                        self.reg["SR"] &= ~(1 << 4)
                        self.reg["ID"] = 0
                        self.reg["IQ"] = 0
                return ""
            if key == "PA":
                if not allow_motion:
                    raise PermissionError("PA requires allow_motion")
                self.pending_pa = int(value)
                self.reg["PA"] = int(value)
                self.reg.update(self.change_after_pa)
                return ""
            self.reg[key] = value
            return ""
        if core == "BG":
            if not allow_motion:
                raise PermissionError("BG requires allow_motion")
            if self.pending_pa is None:
                raise IOError("BG without PA")
            self.moving = True
            self.begun = True
            self.reg["MS"] = 2
            self.reg["OV[2]"] = 2 if self.wrong_mode_after_bg else 1
            if self.switch_stop_after_bg:
                self.reg["SR"] |= (1 << 28)
            self.reg["DV[3]"] = 0 if self.ramp_once else (
                self.pending_pa + 1 if self.corrupt_demand else self.pending_pa)
            return ""
        if core == "ST":
            self.moving = False
            self.reg["VX"] = 0
            self.reg["MS"] = 1 if self.reg["MO"] else 3
            return ""
        if core == "PA" and not allow_motion:
            raise PermissionError("PA query requires supervised readback authority")
        if core == "PX" and self.moving:
            if self.motion_sample_index < len(self.motion_samples):
                values = self.motion_samples[self.motion_sample_index]
                self.motion_sample_index += 1
                self.reg.update(values)
                if int(self.reg.get("MS", 2)) == 0:
                    self.moving = False
            elif self.ramp_once and self.ramp_samples == 0:
                halfway = int(round(self.pending_pa / 2.0))
                self.reg["PX"] = halfway
                self.reg["DV[3]"] = halfway
                self.reg["PE"] = 0
                self.reg["VX"] = 100
                self.reg["MS"] = 2
                self.ramp_samples += 1
            else:
                self.reg["PX"] = self.pending_pa
                self.reg["DV[3]"] = (
                    self.pending_pa + 1 if self.corrupt_demand else self.pending_pa)
                self.reg["PE"] = 0
                self.reg["VX"] = 0
                self.reg["MS"] = 1 if self.final_ms_one else 0
                self.moving = False
        if (core == "ID" and self.begun and self.reg["MO"]
                and self.post_bg_id_a is not None):
            return str(self.post_bg_id_a)
        if (core == "IQ" and self.begun and self.reg["MO"]
                and self.post_bg_iq_a is not None):
            return str(self.post_bg_iq_a)
        if core == "IQ" and self.trip_current and self.reg["MO"]:
            return "2.0"
        if core not in self.reg:
            raise KeyError(core)
        return str(self.reg[core])

    @property
    def writes(self):
        return [command for command, _allow in self.log
                if "=" in command or command in ("BG", "ST")]


def request(**overrides):
    values = dict(mode="relative", target_rev=0.01, speed_rpm=5.0,
                  accel_rpm_s=30.0, travel_limit_rev=0.25,
                  current_cap_a=1.30)
    values.update(overrides)
    return sam.PositionMoveRequest(**values)


class FakeClock:
    def __init__(self, step=0.2):
        self.now = -step
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


def test_axis_summary_is_read_only_and_does_not_invent_eas_topology():
    drive = SimMotionLink()
    summary = sam.read_axis_summary(drive)

    assert summary["scope"] == "Single Axis (application scope)"
    assert summary["feedback_routing"] == "same socket routing (1)"
    assert summary["gear_ratio_raw"] == {"motor_shaft": 1, "driving_shaft": 1}
    assert summary["mode"] == "Position (UM=5)"
    assert drive.writes == []


@pytest.mark.parametrize(
    ("um", "expected"),
    (
        (1, "Torque (UM=1)"),
        (2, "Speed (UM=2)"),
        (3, "Stepper (UM=3)"),
        (5, "Position (UM=5)"),
        (6, "Stepper open/closed loop (UM=6)"),
    ),
)
def test_axis_summary_reuses_canonical_documented_um_names(um, expected):
    drive = SimMotionLink()
    drive.reg["UM"] = um

    summary = sam.read_axis_summary(drive)

    assert summary["mode"] == expected
    assert drive.writes == []


@pytest.mark.parametrize("um", (0, 4, 7, 1.5, True))
def test_axis_summary_does_not_coerce_reserved_or_invalid_um(um):
    drive = SimMotionLink()
    drive.reg["UM"] = um

    summary = sam.read_axis_summary(drive)

    assert summary["mode"].startswith("Unknown (UM=")
    assert drive.writes == []


def test_move_rejects_without_session_commutation_signature_before_write():
    drive = SimMotionLink()
    result = sam.run_position_move(drive, request(), signature_green=False,
                                   sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "signature" in result.reason.lower()
    assert drive.writes == []


def test_move_rejects_persistence_unknown_before_write():
    drive = SimMotionLink(persistence_unknown=True)
    result = sam.run_position_move(drive, request(), signature_green=True,
                                   sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "UNKNOWN" in result.reason
    assert drive.writes == []


@pytest.mark.parametrize("key,value,needle", [
    ("UM", 2, "UM=5"),
    ("RM", 1, "RM=0"),
    ("MF", 8, "MF=0"),
    ("PS", 1, "user program"),
    ("SR", 0, "STO"),
    ("ID", 0.11, "current vector"),
    ("FC[5]", 2, "FC scaling"),
])
def test_preflight_rejects_unsafe_axis_state_without_write(key, value, needle):
    drive = SimMotionLink()
    drive.reg[key] = value
    result = sam.run_position_move(drive, request(), signature_green=True,
                                   sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert needle.lower() in result.reason.lower()
    assert drive.writes == []


def test_target_outside_session_envelope_is_rejected_before_write():
    drive = SimMotionLink()
    result = sam.run_position_move(
        drive, request(mode="session_absolute", target_rev=0.24,
                       travel_limit_rev=0.20),
        signature_green=True, sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "session envelope" in result.reason
    assert drive.writes == []


def test_session_absolute_delta_cannot_bypass_hard_step_limit():
    drive = SimMotionLink()
    drive.reg["PX"] = -65536  # -1 rev from the explicit session zero

    result = sam.run_position_move(
        drive,
        request(mode="session_absolute", target_rev=0.25,
                travel_limit_rev=1.0),
        signature_green=True,
        sleep_fn=lambda _s: None,
    )

    assert result.status == sam.RED
    assert "hard limit" in result.reason
    assert drive.writes == []


def test_green_finite_move_caps_energy_auto_disables_and_restores_all_settings():
    drive = SimMotionLink()
    before = {key: drive.reg[key] for key in sam.TEMPORARY_SETTING_ORDER}

    result = sam.run_position_move(drive, request(), signature_green=True,
                                   sleep_fn=lambda _s: None)

    assert result.status == sam.GREEN, result.reason
    assert "SV" not in drive.writes
    assert "PL[1]=1.3" in drive.writes
    assert "CL[1]=1.3" in drive.writes
    assert "SP=5461" in drive.writes
    assert "AC=32768" in drive.writes and "DC=32768" in drive.writes
    assert "SD=32768" in drive.writes
    assert "FS=0" in drive.writes
    assert "SF[1]=20" in drive.writes and "SF[2]=0" in drive.writes
    assert "MO=1" in drive.writes and "PA=655" in drive.writes
    assert "BG" in drive.writes and "ST" in drive.writes and "MO=0" in drive.writes
    assert drive.writes.index("FS=0") < drive.writes.index("PA=655")
    assert drive.writes.index("PA=655") < drive.writes.index("BG")
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0
    assert {key: drive.reg[key] for key in sam.TEMPORARY_SETTING_ORDER} == before
    assert result.final_state["disabled_verified"] is True
    assert result.evidence["settings_restored"] is True


def test_cancel_after_begin_motion_stops_disables_and_restores():
    drive = SimMotionLink()

    def cancelled():
        return any(command == "BG" for command, _allow in drive.log)

    result = sam.run_position_move(drive, request(), signature_green=True,
                                   cancel_fn=cancelled,
                                   sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "cancel" in result.reason.lower()
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0
    assert result.evidence["settings_restored"] is True


def test_current_excursion_aborts_and_restores():
    drive = SimMotionLink(trip_current=True)
    result = sam.run_position_move(drive, request(current_cap_a=1.0),
                                   signature_green=True,
                                   sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "current" in result.reason.lower()
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0
    assert result.evidence["settings_restored"] is True


def test_restore_failure_is_unknown_and_never_sends_sv():
    original_sp = 100_000

    def fail_restore(command, key, raw, drive):
        return (key == "SP" and math.isclose(float(raw), original_sp)
                and any(c == "BG" for c, _ in drive.log))

    drive = SimMotionLink(fail_write=fail_restore)
    result = sam.run_position_move(drive, request(), signature_green=True,
                                   sleep_fn=lambda _s: None)

    assert result.status == sam.UNKNOWN
    assert result.evidence["settings_restored"] is False
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0
    assert "SV" not in drive.writes


def test_stop_disable_is_allowed_even_when_persistence_state_is_unknown():
    drive = SimMotionLink(persistence_unknown=True)
    drive.reg.update({"MO": 1, "SO": 1, "MS": 2, "VX": 100})

    result = sam.safe_stop_disable(drive, sleep_fn=lambda _s: None)

    assert result.status == sam.GREEN
    assert drive.writes[:2] == ["ST", "MO=0"]
    assert result.final_state["disabled_verified"] is True


def test_unverified_disable_keeps_lower_caps_and_skips_restore():
    drive = SimMotionLink(disable_stuck=True)

    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sleep_fn=lambda _s: None,
        clock_fn=FakeClock())

    assert result.status == sam.UNKNOWN
    assert result.evidence["settings_restored"] is False
    assert drive.reg["PL[1]"] == pytest.approx(1.3)
    assert drive.reg["CL[1]"] == pytest.approx(1.3)
    assert drive.reg["FS"] == 0
    assert drive.reg["SD"] == 32768
    # Original high limits/profile must not be restored while MO/SO are unknown.
    assert "PL[1]=10" not in drive.writes
    assert "CL[1]=5" not in drive.writes


def test_cancel_before_transaction_performs_no_drive_io():
    drive = SimMotionLink()

    result = sam.run_position_move(
        drive, request(), signature_green=True,
        cancel_fn=lambda: True, sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "cancel" in result.reason.lower()
    assert drive.log == []


def test_cancel_after_pa_never_sends_bg():
    drive = SimMotionLink()

    def cancelled():
        return any(command.startswith("PA=") for command, _ in drive.log)

    result = sam.run_position_move(
        drive, request(), signature_green=True,
        cancel_fn=cancelled, sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "BG" not in drive.writes
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0


@pytest.mark.parametrize("changed,needle", [
    ({"MO": 0}, "enable feedback"),
    ({"SO": 0}, "enable feedback"),
    ({"MF": 2}, "fault"),
    ({"SR": (1 << 4) | (1 << 7) | (1 << 14) | (1 << 15)}, "SR"),
    ({"SR": (1 << 4) | (1 << 12) | (1 << 14) | (1 << 15)}, "SR"),
    ({"SR": (1 << 4) | (1 << 13) | (1 << 14) | (1 << 15)}, "SR"),
    ({"SR": (1 << 4) | (1 << 28) | (1 << 14) | (1 << 15)}, "SR"),
    ({"SR": (1 << 4) | (1 << 14)}, "STO"),
    ({"PS": 1}, "user program"),
])
def test_bg_preflight_rereads_live_enable_fault_sto_and_program_state(
        changed, needle):
    drive = SimMotionLink()
    drive.change_after_pa = changed

    result = sam.run_position_move(
        drive, request(), signature_green=True, sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert needle.lower() in result.reason.lower()
    assert "BG" not in drive.writes
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0


def test_cancel_latched_during_motion_sample_cannot_be_reported_green():
    drive = SimMotionLink()

    def cancelled():
        commands = [command for command, _allow in drive.log]
        if "BG" not in commands:
            return False
        return "OV[2]" in commands[commands.index("BG") + 1:]

    result = sam.run_position_move(
        drive, request(), signature_green=True,
        cancel_fn=cancelled, sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "cancel" in result.reason.lower()
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0


def test_stale_active_sample_aborts_instead_of_declaring_green():
    drive = SimMotionLink()
    sample_times = iter((0.0, 0.01, 1.0, 1.01, 2.0, 2.5))

    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sample_clock_fn=lambda: next(sample_times),
        sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "sample age" in result.reason.lower()
    assert "BG" in drive.writes
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0


def test_active_motion_reads_use_bounded_transport_timeout():
    drive = SimMotionLink()

    result = sam.run_position_move(
        drive, request(), signature_green=True, sleep_fn=lambda _s: None)

    assert result.status == sam.GREEN, result.reason
    bg_index = next(index for index, (command, _timeout)
                    in enumerate(drive.timeout_log) if command == "BG")
    st_index = next(index for index, (command, _timeout)
                    in enumerate(drive.timeout_log[bg_index + 1:], bg_index + 1)
                    if command == "ST")
    active_reads = drive.timeout_log[bg_index + 1:st_index]
    assert active_reads
    assert all(timeout == sam.ACTIVE_READ_TIMEOUT_MS
               for _command, timeout in active_reads)


def test_ms_one_is_not_accepted_as_position_settled():
    drive = SimMotionLink(final_ms_one=True)
    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sleep_fn=lambda _s: None, clock_fn=FakeClock(step=1.0))

    assert result.status == sam.RED
    assert "timed out" in result.reason


def test_dv3_mismatch_aborts_and_disables():
    drive = SimMotionLink(corrupt_demand=True)
    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "DV[3]" in result.reason
    assert drive.reg["MO"] == 0 and drive.reg["SO"] == 0


def test_dv3_ramp_demand_is_not_mistaken_for_final_target():
    drive = SimMotionLink(ramp_once=True)
    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sleep_fn=lambda _s: None)

    assert result.status == sam.GREEN, result.reason
    assert drive.ramp_samples == 1


def test_actual_px_wrong_direction_aborts_before_demand_can_hide_it():
    drive = SimMotionLink()
    drive.motion_samples = [
        {"PX": -20, "DV[3]": 100, "PE": 120, "VX": 100, "MS": 2},
    ]

    result = sam.run_position_move(
        drive, request(), signature_green=True, sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "PX" in result.reason and "wrong direction" in result.reason
    assert drive.motion_sample_index == 1


def test_actual_px_nonmonotonic_reversal_aborts_promptly():
    drive = SimMotionLink()
    drive.motion_samples = [
        {"PX": 200, "DV[3]": 200, "PE": 0, "VX": 100, "MS": 2},
        {"PX": 150, "DV[3]": 400, "PE": 250, "VX": 100, "MS": 2},
    ]

    result = sam.run_position_move(
        drive, request(), signature_green=True, sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "PX" in result.reason and "nonmonotonic" in result.reason
    assert drive.motion_sample_index == 2


def test_position_error_uses_small_absolute_bound_not_twice_move_distance():
    drive = SimMotionLink()
    drive.motion_samples = [
        {"PX": 100, "DV[3]": 1000, "PE": 900, "VX": 100, "MS": 2},
    ]

    result = sam.run_position_move(
        drive, request(target_rev=0.25), signature_green=True,
        sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "tracking error" in result.reason
    assert result.evidence["tracking_error_limit_counts"] <= (
        drive.reg["CA[18]"] * sam.MAX_POSITION_ERROR_REV + 1e-9)


def test_id_iq_vector_magnitude_is_capped_in_native_amperes():
    drive = SimMotionLink()
    drive.post_bg_id_a = 0.8
    drive.post_bg_iq_a = 0.8

    result = sam.run_position_move(
        drive, request(current_cap_a=1.0), signature_green=True,
        sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "current vector" in result.reason.lower()
    assert "ID=0.800 A" in result.reason
    assert "IQ=0.800 A" in result.reason
    assert result.evidence["current_convention"]["unit"] == "A"


def test_relative_target_is_recomputed_from_fresh_post_enable_px():
    drive = SimMotionLink()
    drive.enable_px_shift = 1000
    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sleep_fn=lambda _s: None)

    assert result.status == sam.GREEN, result.reason
    assert "PA=1655" in drive.writes
    assert result.target_counts == 1655


def test_switch_stop_sr_bit_after_bg_aborts_instead_of_green():
    drive = SimMotionLink()
    drive.switch_stop_after_bg = True
    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "SR" in result.reason
    assert drive.reg["MO"] == 0


def test_wrong_actual_motion_mode_after_bg_aborts():
    drive = SimMotionLink()
    drive.wrong_mode_after_bg = True
    result = sam.run_position_move(
        drive, request(), signature_green=True,
        sleep_fn=lambda _s: None)

    assert result.status == sam.RED
    assert "OV[2]" in result.reason


def test_sd_obeys_drive_minimum_even_with_low_resolution_axis():
    drive = SimMotionLink()
    drive.reg["CA[18]"] = 60
    drive.reg["VH[2]"] = 10_000
    drive.reg["VL[3]"] = -1000
    drive.reg["VH[3]"] = 1000
    result = sam.run_position_move(
        drive, request(target_rev=0.1, accel_rpm_s=1.0),
        signature_green=True, sleep_fn=lambda _s: None)

    assert result.status == sam.GREEN, result.reason
    assert "AC=10" in drive.writes and "DC=10" in drive.writes
    assert "SD=100" in drive.writes
