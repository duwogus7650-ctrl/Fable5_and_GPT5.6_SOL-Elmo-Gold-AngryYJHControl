import csv
import json

import pytest

import recorder_control as rc


def request(**overrides):
    values = dict(signals=("Position", "Velocity"), resolution_us=200.0,
                  record_time_s=1.0, trigger="immediate")
    values.update(overrides)
    return rc.RecorderRequest(**values)


def test_resolve_immediate_recording_exposes_actual_quantized_timing():
    resolved = rc.resolve_request(request(), ts_us=50.0)
    assert resolved.time_resolution == 4
    assert resolved.actual_resolution_us == 200.0
    assert resolved.length_per_signal == 5000
    assert resolved.total_buffer_samples == 10000
    assert resolved.actual_record_time_s == pytest.approx(1.0)


def test_shared_16k_capacity_is_fail_closed():
    with pytest.raises(rc.RecorderConfigError, match="16K"):
        rc.resolve_request(
            request(signals=("A", "B", "C", "D"), record_time_s=1.0),
            ts_us=50.0)


@pytest.mark.parametrize("bad", [
    request(signals=()),
    request(signals=("Position", "Position")),
    request(trigger="normal"),
    request(resolution_us=float("nan")),
])
def test_unsupported_or_ambiguous_config_is_rejected(bad):
    with pytest.raises(rc.RecorderConfigError):
        rc.validate_request(bad)


def test_workspace_roundtrip_is_versioned_and_local(tmp_path):
    path = tmp_path / "scope.ayrec.json"
    original = request(signals=("Active Current [A]",), record_time_s=0.5)
    rc.save_workspace(path, original)

    assert rc.load_workspace(path) == original
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == rc.WORKSPACE_SCHEMA


def test_csv_export_has_exact_signal_names_and_time_axis(tmp_path):
    path = tmp_path / "capture.csv"
    meta = rc.export_csv(
        path,
        {"dt": 0.0002, "Position": [1, 2, 3], "Active Current [A]": [0.1, 0.2, 0.3]},
        ("Position", "Active Current [A]"))

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == ["time_s", "Position", "Active Current [A]"]
    assert [float(row[0]) for row in rows[1:]] == pytest.approx([0.0, 0.0002, 0.0004])
    assert meta["units"].startswith("personality-owned")
    sidecar = json.loads((tmp_path / "capture.csv.meta.json").read_text(encoding="utf-8"))
    assert sidecar["csv_sha256"] == meta["csv_sha256"]
    assert sidecar["schema"].endswith("/v1")


def test_csv_export_rejects_missing_or_nonfinite_data(tmp_path):
    with pytest.raises(rc.RecorderConfigError, match="missing"):
        rc.export_csv(tmp_path / "x.csv", {"dt": 0.1}, ("A",))
    with pytest.raises(rc.RecorderConfigError, match="non-finite"):
        rc.export_csv(tmp_path / "x.csv", {"dt": 0.1, "A": [1, float("nan")]}, ("A",))
    with pytest.raises(rc.RecorderConfigError, match="empty"):
        rc.export_csv(tmp_path / "x.csv", {"dt": 0.1, "A": []}, ("A",))


def test_capture_validation_requires_exact_count_finite_data_and_resolved_dt():
    resolved = rc.resolve_request(
        request(signals=("Position",), resolution_us=200.0, record_time_s=0.001),
        ts_us=50.0)
    assert resolved.length_per_signal == 5
    good = {"dt": 0.0002, "Position": [0, 1, 2, 3, 4]}
    assert rc.validate_capture(good, resolved)["samples_per_signal"] == 5

    with pytest.raises(rc.RecorderConfigError, match="exactly 5"):
        rc.validate_capture({"dt": 0.0002, "Position": [0, 1]}, resolved)
    with pytest.raises(rc.RecorderConfigError, match="disagrees"):
        rc.validate_capture({"dt": 0.0001, "Position": [0, 1, 2, 3, 4]}, resolved)
