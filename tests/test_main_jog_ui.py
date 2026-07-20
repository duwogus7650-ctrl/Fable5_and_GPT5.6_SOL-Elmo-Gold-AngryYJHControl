"""Jog panel UI wiring (Motion page Velocity-tab Jogging).

Locks the GUI->worker contract: the direction buttons are gated offline, a press
enqueues run_jog with the panel's request and starts the deadman refresh timer,
a hold-to-run release stops it, and the jog_result signal releases the panel.
The kernel safety itself is covered by tests/test_single_axis_jog.py.
"""
import pytest
from PyQt6 import QtWidgets

import main as app_main
import single_axis_motion


class _FakeWorker:
    def __init__(self):
        self.calls = []

    def isRunning(self):
        return True

    def run_jog(self, request):
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
