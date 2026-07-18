"""Offline regression tests for complete telemetry authority."""

import pytest
import threading
import time

from elmo_link import ElmoLink, TelemetrySnapshotError
import persistence_audit
import single_axis_digital_inputs
import single_axis_motion


class _CommandSpy:
    """Minimal vendor communication double that records crossed I/O."""

    IsConnected = True

    def __init__(self, responses=None):
        self.commands = []
        self.responses = dict(responses or {})

    def SendCommandAnalyzeError(self, command, _response, _error, _timeout_ms):
        self.commands.append(command)
        return True, str(self.responses.get(command, "0")), None


def _link_with_responses(monkeypatch, responses):
    link = ElmoLink("COM_TEST")

    def query(command):
        value = responses[command]
        if isinstance(value, BaseException):
            raise value
        return str(value)

    monkeypatch.setattr(link, "command", query)
    return link


def test_complete_finite_snapshot_has_timing_and_normalized_mo(monkeypatch):
    link = _link_with_responses(monkeypatch, {
        "PX": -123, "VX": 0, "PE": 0, "IQ": 0.0, "MO": 0.0,
    })

    sample = link.read_telemetry()

    assert {name: sample[name] for name in ("pos", "vel", "pos_err", "iq", "mo")} == {
        "pos": -123, "vel": 0, "pos_err": 0, "iq": 0, "mo": 0,
    }
    assert sample["_sample_duration_s"] >= 0.0
    assert sample["_sample_finished_monotonic"] >= sample["_sample_started_monotonic"]


@pytest.mark.parametrize("command,bad", [
    ("MO", RuntimeError("link lost")),
    ("MO", "nan"),
    ("MO", 2),
    ("PX", "inf"),
    ("IQ", None),
])
def test_partial_nonfinite_or_unknown_state_never_returns_snapshot(
        monkeypatch, command, bad):
    responses = {"PX": 1, "VX": 0, "PE": 0, "IQ": 0.0, "MO": 0}
    responses[command] = bad
    link = _link_with_responses(monkeypatch, responses)

    with pytest.raises(TelemetrySnapshotError):
        link.read_telemetry()


def _observe_only_link(monkeypatch):
    link = ElmoLink("COM_TEST")
    spy = _CommandSpy()
    link._comm = spy
    monkeypatch.setattr(link, "persistence_unknown_latched", lambda: False)
    link.enter_observe_only_session()
    return link, spy


@pytest.mark.parametrize("query", [
    "VR", "SN[4]", "CA[18]", "KP[1]", "PX", "MO", "SO", "VX", "PS", "MF",
])
def test_observe_only_transport_allows_bare_queries(monkeypatch, query):
    link, spy = _observe_only_link(monkeypatch)

    assert link.command(query) == "0"
    assert spy.commands == [query]


@pytest.mark.parametrize("command", [
    "UM=5", "CA[28]=0", "PX=0", "LD", "RS", "XQ", "SV",
    "MO=1", "BG", "JV=1", "PA=1", "TC=0.1", "TW[80]=1",
    "BG[1]", "XQ[1]", "ZZ",
    "BT", "CP", "DF", "DL", "EI", "EO", "HP", "KL", "KR", "PB", "XC",
])
def test_observe_only_transport_blocks_mutation_before_vendor_io(
        monkeypatch, command):
    link, spy = _observe_only_link(monkeypatch)

    with pytest.raises(PermissionError, match="observe-only"):
        link.command(command, allow_motion=True)

    assert spy.commands == []


@pytest.mark.parametrize("command", ["ST", "MO=0", "TC=0", "TW[80]=0"])
def test_observe_only_transport_preserves_safe_shutdown_escape(
        monkeypatch, command):
    link, spy = _observe_only_link(monkeypatch)

    assert link.command(command, allow_motion=True) == "0"
    assert spy.commands == [command]


def test_observe_only_all_current_read_models_cross_only_allowlisted_queries(
        monkeypatch):
    link = ElmoLink("COM_TEST")
    spy = _CommandSpy({
        "CA[18]": 65536,
        "CA[41]": 30,
        "MO": 0,
        "SO": 0,
        "VX": 0,
        "PS": -2,
        "MF": 0,
    })
    link._comm = spy
    monkeypatch.setattr(link, "persistence_unknown_latched", lambda: False)
    link.enter_observe_only_session()

    link.read_telemetry()
    link.read_motor_params()
    link.read_feedback()
    link.read_tuning_gains()
    link.read_platform_clock()
    summary = single_axis_motion.read_axis_summary(link)
    inputs = single_axis_digital_inputs.read_digital_input_snapshot(link)
    for registers in persistence_audit.PHASE_REGISTERS.values():
        for register in registers:
            link.command(register)

    assert summary["errors"] == {}
    assert inputs.state == single_axis_digital_inputs.CURRENT
    assert spy.commands


def test_observe_only_transport_admits_only_bounded_digital_input_queries(
        monkeypatch):
    link = ElmoLink("COM_TEST")
    spy = _CommandSpy({
        "IP": 0,
        **{"IL[%d]" % index: 7 for index in range(1, 7)},
        **{"IF[%d]" % index: 0 for index in range(1, 7)},
    })
    link._comm = spy
    link.enter_observe_only_session()

    assert link.command("IP") == "0"
    for index in range(1, 7):
        assert link.command("IL[%d]" % index) == "7"
        assert link.command("IF[%d]" % index) == "0"

    for command in (
            "IP=1", "IL[1]=7", "IF[1]=0", "IB[17]=1",
            "IL[0]", "IL[17]", "IF[0]", "IF[17]"):
        with pytest.raises(PermissionError, match="observe-only"):
            link.command(command)

    assert spy.commands == [
        "IP",
        *(item for index in range(1, 7)
          for item in ("IL[%d]" % index, "IF[%d]" % index)),
    ]


@pytest.mark.parametrize("action", [
    lambda link: link.write_motor_params({}, persist=True),
    lambda link: link.recorder_signals(),
    lambda link: link._upload_personality("unused.xml"),
    lambda link: link.record_start(
        ["Position"], 16, time_resolution=1, sampling_time_us=100.0),
    lambda link: link.record_upload(),
])
def test_observe_only_blocks_direct_vendor_api_before_io(monkeypatch, action):
    link, spy = _observe_only_link(monkeypatch)

    with pytest.raises(PermissionError, match="observe-only"):
        action(link)

    assert spy.commands == []


def test_observe_only_preserves_recorder_safe_stop_without_pending_io(monkeypatch):
    link, spy = _observe_only_link(monkeypatch)

    assert link.record_stop() is False
    assert spy.commands == []


def test_observe_only_latch_cannot_race_past_direct_vendor_api_guard(monkeypatch):
    link = ElmoLink("COM_TEST")
    link._comm = object()
    entered = threading.Event()
    release = threading.Event()
    latch_done = threading.Event()
    call_errors = []

    monkeypatch.setattr(link, "_rec_ns", lambda: (object(), object()))

    def blocking_signal_lookup(_names):
        entered.set()
        assert release.wait(2.0)
        raise RuntimeError("intentional test stop before vendor I/O")

    monkeypatch.setattr(link, "_signal_setups", blocking_signal_lookup)

    def run_start():
        try:
            link.record_start(
                ["Position"], 16, time_resolution=1,
                sampling_time_us=100.0)
        except Exception as exc:
            call_errors.append(exc)

    start_thread = threading.Thread(target=run_start)
    start_thread.start()
    assert entered.wait(2.0)

    def latch_observe_only():
        link.enter_observe_only_session()
        latch_done.set()

    latch_thread = threading.Thread(target=latch_observe_only)
    latch_thread.start()
    time.sleep(0.05)
    assert not latch_done.is_set()

    release.set()
    start_thread.join(2.0)
    latch_thread.join(2.0)

    assert not start_thread.is_alive()
    assert not latch_thread.is_alive()
    assert latch_done.is_set()
    assert isinstance(call_errors[0], RuntimeError)
    assert link.access_mode == "OBSERVE_ONLY_WITH_SAFE_SHUTDOWN"
