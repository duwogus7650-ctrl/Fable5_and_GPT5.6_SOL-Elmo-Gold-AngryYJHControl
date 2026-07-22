"""Jog panel UI wiring (Motion page Velocity-tab Jogging).

Locks the GUI->worker contract: the direction buttons are gated offline, a press
enqueues run_jog with the panel's request and starts the deadman refresh timer,
a hold-to-run release stops it, and the jog_result signal releases the panel.
The kernel safety itself is covered by tests/test_single_axis_jog.py.

P2 CONTRACT CHANGE (SPEC freeze 2026-07-21): the jog/motion spinbox ceilings
are no longer fixed (3000 rpm / 5.0 A / default 3.0 A).  They derive from the
connected motor's MotorProfile at connect time (_on_motor_params ->
_apply_profile_motion_limits): speed ceiling = rated rpm, cap ceiling =
0.25*CL[1], default cap = 0.15*CL[1]; offline the caps stay fail-closed at the
minimum.  Requests above 0.90*rated open a voltage-margin confirm dialog
(warning gate, not a block).  Tests below arm the profile explicitly where the
old fixed ranges were assumed.
"""
import pytest
from PyQt6 import QtWidgets

import main as app_main
import motor_profile
import single_axis_motion


# Connect-time Motor Settings payload of the real bench unit (what
# DriveWorker.motor_params emits; see elmo_link.read_motor_params()).
UNIT_MP = {
    "peak_arms": 50.0, "cont_arms": 15.0, "rpm": 3600.0,
    "poles": 21.0, "mtype": 0,
    "pl_amp": 70.7107, "cl_amp": 21.2132,
    "vh": 3932160.0, "ca18": 65536.0,
}

# Virtual 8-pole-pair low-current motor (3000 rpm rated).
VIRT_MP = {
    "peak_arms": 5.0, "cont_arms": 1.77, "rpm": 3000.0,
    "poles": 8.0, "mtype": 0,
    "pl_amp": 7.07, "cl_amp": 2.5,
    "vh": 204800.0, "ca18": 4096.0,
}


def _arm_profile(window, mp=UNIT_MP):
    """Simulate the connect-time motor_params signal that builds the profile."""
    window._on_motor_params(dict(mp))


class _FakeWorker:
    def __init__(self):
        self.calls = []
        self.requests = []

    def isRunning(self):
        return True

    def run_jog(self, request):
        self.requests.append(request)
        self.calls.append(("run_jog", float(request.max_speed_rpm),
                           float(request.current_cap_a)))

    def jog_set_velocity(self, rpm):
        self.calls.append(("set", float(rpm)))

    def jog_stop(self):
        self.calls.append(("stop",))


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setattr(app_main, "list_serial_ports", lambda: ["COM_TEST"])
    win = app_main.MainWindow()
    win.resize(1366, 820)
    win.show()
    qapp.processEvents()
    yield win
    win.worker = None
    win.close()


def test_jog_controls_are_gated_offline(window):
    assert not window.btn_jog_fwd.isEnabled()
    assert not window.btn_jog_rev.isEnabled()
    assert window._jog_active is False


def test_press_enqueues_run_jog_and_starts_deadman_then_release_stops(window):
    fake = _FakeWorker()
    window.worker = fake
    # P2 contract change: offline the current-cap spinbox is fail-closed at the
    # minimum; arming the connect-time profile opens the derived ranges so the
    # 0.9 A cap below is representable.
    _arm_profile(window)
    window.spn_jog_speed.setValue(120.0)
    window.spn_jog_current.setValue(0.9)
    window.btn_jog_fwd.setEnabled(True)   # force the gate open for the wiring test

    window._jog_press(1)
    assert window._jog_active is True
    assert window._jog_timer.isActive()
    assert ("run_jog", 120.0, 0.9) in fake.calls
    assert ("set", 120.0) in fake.calls    # forward target streamed

    # Run Held is off by default -> releasing the button is a stop.
    assert window.chk_jog_run_held.isChecked() is False
    window._jog_release()
    assert ("stop",) in fake.calls
    assert not window._jog_timer.isActive()


def test_reverse_direction_streams_negative_target(window):
    fake = _FakeWorker()
    window.worker = fake
    window.spn_jog_speed.setValue(90.0)
    window.btn_jog_fwd.setEnabled(True)
    window._jog_press(-1)
    assert ("set", -90.0) in fake.calls


def test_latched_run_held_does_not_stop_on_release(window):
    fake = _FakeWorker()
    window.worker = fake
    window.btn_jog_fwd.setEnabled(True)
    window.chk_jog_run_held.setChecked(True)
    window._jog_press(1)
    window._jog_release()               # latched -> no stop on release
    assert ("stop",) not in fake.calls
    assert window._jog_active is True
    # explicit Stop Jog ends it
    window._jog_stop_clicked()
    assert ("stop",) in fake.calls


def test_jog_result_releases_panel_and_stops_timer(window):
    fake = _FakeWorker()
    window.worker = fake
    window.btn_jog_fwd.setEnabled(True)
    window._jog_press(1)
    assert window._jog_active is True
    window._on_jog_result(
        single_axis_motion.MotionResult(single_axis_motion.GREEN, "done"))
    assert window._jog_active is False
    assert not window._jog_timer.isActive()


def test_jog_sample_updates_live_velocity_readout(window):
    window._on_jog_sample({"VX": 109226.0, "IQ": 0.42})
    assert "109" in window.m_vel.text().replace(",", "")


# --- P2: profile-derived spinbox ceilings + voltage-margin confirm dialog --------


def test_offline_spinboxes_are_fail_closed_not_motor_constants(window):
    # Without a profile there is no CL[1]/rated basis: speed ceiling is the
    # 300 rpm default (never 3000/3600) and the current caps are locked at the
    # minimum.
    assert window.spn_jog_speed.maximum() == pytest.approx(
        single_axis_motion.JOG_MAX_RPM_DEFAULT)
    assert window.spn_jog_current.maximum() == pytest.approx(
        single_axis_motion.MIN_CURRENT_CAP_A)
    assert window.spn_motion_current.maximum() == pytest.approx(
        single_axis_motion.MIN_CURRENT_CAP_A)


def test_connect_profile_sets_derived_ceilings_and_defaults(window):
    _arm_profile(window)   # real unit: 3600 rpm rated, CL[1]=21.2132 A
    assert window.spn_jog_speed.maximum() == pytest.approx(3600.0)
    # Spinbox maxima are FLOORED to the 2-decimal widget precision so the
    # operator can never select a value the kernel would reject:
    # f_I_def ceiling = 0.25*21.2132 = 5.3033 -> 5.30 displayed max.
    assert window.spn_jog_current.maximum() == pytest.approx(5.30)
    assert window.spn_jog_current.value() == pytest.approx(
        round(0.15 * 21.2132, 4), abs=0.006)   # f_I_run default = 3.182 A
    assert window.spn_motion_current.maximum() == pytest.approx(5.30)
    prof = window._motor_profile
    assert prof.is_valid
    assert prof.effective_rated_rpm == pytest.approx(3600.0)


def test_connect_virtual_8pp_profile_follows_new_motor(window):
    # Swapping motors re-derives the ceilings: 3000 rpm rated, CL[1]=2.5 A.
    _arm_profile(window, VIRT_MP)
    assert window.spn_jog_speed.maximum() == pytest.approx(3000.0)
    # 0.25*2.5 = 0.625 floored to the widget precision -> 0.62 (never 0.63,
    # which the kernel ceiling would reject).
    assert window.spn_jog_current.maximum() == pytest.approx(0.62)
    assert window.spn_jog_current.value() == pytest.approx(0.375, abs=0.006)


def test_jog_request_carries_profile_to_kernel(window):
    fake = _FakeWorker()
    window.worker = fake
    _arm_profile(window)
    window.btn_jog_fwd.setEnabled(True)
    window._jog_press(1)
    assert fake.requests, "run_jog was not enqueued"
    assert fake.requests[0].profile is window._motor_profile


def test_voltage_warn_dialog_gates_above_090_rated(window, monkeypatch):
    # 3300 rpm > 0.90*3600 = 3240 rpm: the confirm dialog must appear; a "No"
    # answer aborts before run_jog, a "Yes" answer proceeds (warning gate,
    # never a hard block).
    fake = _FakeWorker()
    window.worker = fake
    _arm_profile(window)
    window.btn_jog_fwd.setEnabled(True)
    window.spn_jog_speed.setValue(3300.0)
    seen = []
    answer = {"value": QtWidgets.QMessageBox.StandardButton.No}

    def fake_warning(*args, **kwargs):
        seen.append(args)
        return answer["value"]

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning",
                        staticmethod(fake_warning))
    window._jog_press(1)
    assert len(seen) == 1                       # dialog shown
    assert not any(c[0] == "run_jog" for c in fake.calls)   # No -> no jog
    assert window._jog_active is False

    answer["value"] = QtWidgets.QMessageBox.StandardButton.Yes
    window._jog_press(1)
    assert len(seen) == 2
    assert any(c[0] == "run_jog" and c[1] == pytest.approx(3300.0)
               for c in fake.calls)             # Yes -> proceeds
    window._jog_stop_clicked()


def test_below_voltage_warn_no_dialog(window, monkeypatch):
    fake = _FakeWorker()
    window.worker = fake
    _arm_profile(window)
    window.btn_jog_fwd.setEnabled(True)
    window.spn_jog_speed.setValue(3200.0)       # < 3240 rpm threshold
    seen = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox, "warning",
        staticmethod(lambda *a, **k: seen.append(a)
                     or QtWidgets.QMessageBox.StandardButton.No))
    window._jog_press(1)
    assert seen == []                           # no dialog below the band
    assert any(c[0] == "run_jog" for c in fake.calls)
    window._jog_stop_clicked()


def test_motion_io_safety_panel_shows_sto_unverified_never_ok(window):
    # The drive holds no independent STO/E-STOP evidence, so these must stay an
    # honest "unverified" — never a false green "OK" that would misrepresent safety.
    ok_bg = app_main.MainWindow._PILL_STYLE["ok"][0]
    for name in ("io_sto1", "io_sto2", "io_estop"):
        pill = getattr(window, name)
        assert "미검증" in pill.text()
        assert "OK" not in pill.text().upper()
        # amber "unverified" background, never the green "ok" background
        assert ok_bg not in pill.styleSheet()
        assert app_main.MainWindow._PILL_STYLE["unverified"][0] in pill.styleSheet()
    # Repainting through the honest "unverified" path keeps the pill non-green;
    # the build path never wires telemetry into these pills, so green never appears.
    window._paint_safety_pill(window.io_sto1, "미검증", "unverified")
    assert app_main.MainWindow._PILL_STYLE["ok"][0] not in window.io_sto1.styleSheet()


# ======================================================================================
# Connect-time carry-over of the LEARNED profile state (field defect 2026-07-22)
# ======================================================================================
def _learned_profile(name="drive-xyz"):
    return motor_profile.MotorProfile.from_sources(
        name,
        drive_readings={"VH[2]": 3932160.0, "CA[18]": 65536.0,
                        "CA[19]": 16.0, "CA[28]": 0.0,
                        "CL[1]": 21.2132, "PL[1]": 70.7107},
    ).with_green_run(i_ba_a=1.3297826865671643, k_a=1792123.278946844)


def test_connect_carries_learned_state_when_identity_is_known(window,
                                                              monkeypatch):
    """The profile used to be write-only: GREEN runs saved a baseline and the
    next connection never read it back, so the signature stayed on its
    first-run cap forever and censored its own measurement."""
    learned = _learned_profile()
    seen = []
    monkeypatch.setattr(
        app_main.MainWindow, "_load_persisted_profile",
        staticmethod(lambda name: (seen.append(name), learned)[1]))
    window._connected_identity = {"drive_identity": "drive-xyz"}
    _arm_profile(window)

    assert seen == ["drive-xyz"]
    prof = window._motor_profile
    assert prof.has_learned_state() is True
    assert prof.ka_baseline == pytest.approx(1792123.278946844)
    assert prof.signature_band["i_ba_ref_a"] == pytest.approx(
        1.3297826865671643)
    # ...while the drive-derived side still comes from THIS connection
    assert prof.effective_rated_rpm == pytest.approx(3600.0)
    assert prof.cont_current_a == pytest.approx(21.2132)


def test_connect_without_identity_never_imports_a_baseline(window,
                                                           monkeypatch):
    """"connected-motor" is a shared fallback bucket.  One motor's baseline
    must never authorize another motor's energize envelope, so an unidentified
    drive gets no learned state at all."""
    called = []
    monkeypatch.setattr(
        app_main.MainWindow, "_load_persisted_profile",
        staticmethod(lambda name: (called.append(name), _learned_profile())[1]))
    window._connected_identity = {}          # drive identity unavailable
    _arm_profile(window)

    assert called == [], "unidentified drive must not load a saved baseline"
    assert window._motor_profile.has_learned_state() is False


# ======================================================================================
# Hold-to-run must survive the motor enabling (field defect 2026-07-22)
# ======================================================================================
def test_a_running_jog_keeps_its_direction_buttons_enabled(window):
    """Off Run-Held the direction button IS the deadman, and Qt emits
    released() when a pressed button is disabled.  jog_ready requires MO==0,
    which is right for STARTING a jog and wrong for continuing one: the moment
    the jog enabled the motor, the button disabled itself, Qt synthesised a
    release and the motor stopped after ~1-2 s while it was still being held.
    """
    window._jog_active = True
    window._update_motion_controls()      # offline: jog_ready is False
    assert window.btn_jog_fwd.isEnabled() is True
    assert window.btn_jog_rev.isEnabled() is True


def test_direction_buttons_stay_gated_when_no_jog_runs(window):
    """The relaxation is scoped to a LIVE jog; it must not open the gate."""
    window._jog_active = False
    window._update_motion_controls()
    assert window.btn_jog_fwd.isEnabled() is False
    assert window.btn_jog_rev.isEnabled() is False


def test_releasing_a_direction_button_stops_an_unlatched_jog(window):
    """The other half of hold-to-run: a real release must still stop."""
    fake = _FakeWorker()
    window.worker = fake
    window._jog_active = True
    window.chk_jog_run_held.setChecked(False)
    window._jog_release()
    assert ("stop",) in fake.calls


# ======================================================================================
# Session Zero must not be a one-shot button (field defect 2026-07-22)
# ======================================================================================
def test_a_refused_session_zero_leaves_its_button_usable(window):
    """A refusal used to latch the button off with nothing to re-enable it, so
    one ill-timed click killed Session Zero for the whole session — and Jog,
    which requires a verified Session Zero, stayed locked with no way back but
    an app restart."""
    window.btn_zero.setEnabled(True)
    window.worker = None                      # authority missing -> refusal
    window.zero_position()
    assert window.btn_zero.isEnabled() is True


def test_session_zero_enable_state_is_derived_not_latched():
    """The button's state comes from _set_connected_ui, like every other
    mutation control, so it recovers on its own."""
    import inspect
    src = inspect.getsource(app_main.MainWindow._set_connected_ui)
    assert "btn_zero" in src, "Session Zero is not re-derived with the others"


def test_persisted_profile_loader_degrades_on_a_bad_file(monkeypatch):
    """A missing file is the normal first-contact case; a corrupt one must not
    block the connection — both degrade to "no baseline"."""
    for exc in (FileNotFoundError, OSError, ValueError, KeyError, TypeError):
        monkeypatch.setattr(
            motor_profile.MotorProfile, "load",
            staticmethod(lambda *a, **k: (_ for _ in ()).throw(exc("x"))))
        assert app_main.MainWindow._load_persisted_profile("any") is None
