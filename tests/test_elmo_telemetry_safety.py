"""Offline regression tests for complete telemetry authority."""

import pytest

from elmo_link import ElmoLink, TelemetrySnapshotError


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
