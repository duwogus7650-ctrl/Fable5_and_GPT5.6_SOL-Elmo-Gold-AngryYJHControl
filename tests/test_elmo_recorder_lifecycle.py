from types import SimpleNamespace

import numpy as np
import pytest

import elmo_link
from elmo_link import ElmoLink


class Status:
    ROff = object()
    RWait = object()
    REnd = object()
    RProgress = object()


class FakeRecorder:
    def __init__(self, status=Status.REnd, *, values=None, stop_error=None):
        self.status = status
        self.stopped = False
        self.uploaded = False
        self.values = values or ([1.0, 2.0], [3.0, 4.0])
        self.stop_error = stop_error

    def GetRecordingStatus(self):
        return self.status

    def StopRecorder(self):
        if self.stop_error:
            raise self.stop_error
        self.stopped = True
        self.status = Status.ROff

    def UploadRecordingData(self):
        self.uploaded = True
        return SimpleNamespace(Data=[
            SimpleNamespace(Key=0, Value=self.values[0]),
            SimpleNamespace(Key=1, Value=self.values[1]),
        ])


class NonConfirmingStopRecorder(FakeRecorder):
    def StopRecorder(self):
        if self.stop_error:
            raise self.stop_error
        self.stopped = True


def link_with_pending(status=Status.REnd, sampling_time=50.0, *, values=None,
                      stop_error=None):
    link = ElmoLink("COM_TEST")
    recorder = FakeRecorder(status, values=values, stop_error=stop_error)
    link._rec_pending = {
        "obj": recorder,
        "setup": SimpleNamespace(
            SamplingTime=sampling_time, TimeResolution=4, RecordingLength=2),
        "REC": SimpleNamespace(RecordingStatus=Status),
        "signals": ["Position", "Velocity"],
        "length": 2,
        "sampling_time_us": 50.0,
        "time_resolution": 4,
    }
    return link, recorder


@pytest.mark.parametrize("raw,normalized", [
    (Status.RWait, "WAITING_FOR_TRIGGER"),
    (Status.RProgress, "RECORDING"),
    (Status.REnd, "READY_TO_UPLOAD"),
    (Status.ROff, "OFF"),
])
def test_nonblocking_status_mapping(raw, normalized):
    link, _ = link_with_pending(raw)
    assert link.record_status() == normalized


def test_upload_requires_ready_and_preserves_exact_signal_order():
    link, recorder = link_with_pending()
    data = link.record_upload()

    assert recorder.uploaded
    assert np.array_equal(data["Position"], [1.0, 2.0])
    assert np.array_equal(data["Velocity"], [3.0, 4.0])
    assert data["dt"] == pytest.approx(0.0002)
    assert link.record_status() == "IDLE"


def test_upload_before_ready_does_not_discard_pending_capture():
    link, _ = link_with_pending(Status.RProgress)
    with pytest.raises(RuntimeError, match="not ready"):
        link.record_upload()
    assert link.record_status() == "RECORDING"


def test_recorder_stop_is_separate_idempotent_cancel():
    link, recorder = link_with_pending(Status.RProgress)
    assert link.record_stop() is True
    assert recorder.stopped
    assert link.record_stop() is False
    assert link.record_status() == "IDLE"


def test_stop_failure_retains_pending_handle_for_retry():
    link, _ = link_with_pending(
        Status.RProgress, stop_error=OSError("negative-control stop failure"))
    with pytest.raises(OSError, match="negative-control"):
        link.record_stop()
    assert link.record_status() == "RECORDING"


def test_stop_without_terminal_readback_retains_pending_owner():
    link, _ = link_with_pending(Status.RProgress)
    recorder = NonConfirmingStopRecorder(Status.RProgress)
    link._rec_pending["obj"] = recorder
    with pytest.raises(IOError, match="without terminal status confirmation"):
        link.record_stop()
    assert recorder.stopped
    assert link._rec_pending is not None
    assert link.record_status() == "RECORDING"


@pytest.mark.parametrize("sampling_time", [float("nan"), 0.0, -1.0])
def test_upload_rejects_invalid_sampling_time_and_preserves_pending(sampling_time):
    link, recorder = link_with_pending(sampling_time=sampling_time)
    with pytest.raises(IOError, match="timing|SamplingTime"):
        link.record_upload()
    assert not recorder.uploaded
    assert link._rec_pending is not None


def test_truncated_or_nonfinite_upload_is_rejected_without_releasing_owner():
    link, _ = link_with_pending(values=([1.0], [3.0]))
    with pytest.raises(IOError, match="invalid Recorder upload"):
        link.record_upload()
    assert link._rec_pending is not None

    link, _ = link_with_pending(values=([1.0, float("nan")], [3.0, 4.0]))
    with pytest.raises(IOError, match="non-finite"):
        link.record_upload()
    assert link._rec_pending is not None


@pytest.mark.parametrize("field,bad,match", [
    ("TimeResolution", 8, "TimeResolution"),
    ("RecordingLength", 3, "RecordingLength"),
])
def test_upload_rejects_mutated_timing_or_length_readback(field, bad, match):
    link, recorder = link_with_pending()
    setattr(link._rec_pending["setup"], field, bad)
    with pytest.raises(IOError, match=match):
        link.record_upload()
    assert not recorder.uploaded
    assert link._rec_pending is not None


def test_disconnect_stop_failure_creates_cross_session_recovery_latch(
        tmp_path, monkeypatch):
    marker = tmp_path / "recorder_unknown.json"
    monkeypatch.setattr(elmo_link, "_RECORDER_UNKNOWN_PATH", str(marker))

    class Communication:
        def __init__(self, recorder):
            self.recorder = recorder

        def Disconnect(self):
            return None

        def GetRecordingObject(self):
            return self.recorder

    failed = FakeRecorder(
        Status.RProgress, stop_error=OSError("lost stop confirmation"))
    link, _ = link_with_pending(Status.RProgress, stop_error=failed.stop_error)
    link.com_port = "COM_TEST"
    identity_a = "elmo-sn4-sha256:drive-a"
    identity_b = "elmo-sn4-sha256:drive-b"
    link._connected_drive_identity = identity_a
    link._rec_pending["drive_identity"] = identity_a
    link._comm = Communication(link._rec_pending["obj"])
    link.disconnect()

    # A different drive on the same COM port is neither blocked by nor allowed
    # to clear drive A's durable unknown record.
    other_drive = ElmoLink("COM_TEST")
    other_drive._connected_drive_identity = identity_b
    other_drive._refresh_recorder_recovery_state()
    assert not other_drive.recorder_recovery_unknown_latched()
    assert other_drive.record_stop() is False

    recovered = ElmoLink("COM_TEST")
    assert recovered.recorder_recovery_unknown_latched()
    recovered._connected_drive_identity = identity_a
    recovered._refresh_recorder_recovery_state()
    recovery_recorder = FakeRecorder(Status.ROff)
    recovered._comm = Communication(recovery_recorder)
    recovered._rec_ns = lambda: (
        SimpleNamespace(RecordingStatus=Status), None)
    assert recovered.record_stop() is True
    assert recovery_recorder.stopped
    assert not ElmoLink("COM_TEST").recorder_recovery_unknown_latched()


def test_disconnect_aggregates_unhandled_failures_after_clearing_session(
        tmp_path, monkeypatch):
    marker = tmp_path / "recorder_unknown.json"
    monkeypatch.setattr(elmo_link, "_RECORDER_UNKNOWN_PATH", str(marker))

    class FailingDisconnect:
        def __init__(self):
            self.called = False

        def Disconnect(self):
            self.called = True
            raise OSError("negative-control transport disconnect failure")

    link = ElmoLink("COM_TEST")
    comm = FailingDisconnect()
    link._comm = comm
    link._factory = object()
    link._connected_drive_identity = "elmo-sn4-sha256:test-drive"
    link._rec_pending = {
        "drive_identity": link._connected_drive_identity,
    }
    link._prepared_persistence_attempt_id = "prepared"
    link._acknowledged_persistence_attempt_id = "acknowledged"
    link._connection_epoch = "epoch"
    link._personality_provenance = {"source": "stale-session"}

    def stop_lost():
        raise RuntimeError("negative-control Recorder Stop failure")

    def latch_lost(*_args, **_kwargs):
        raise PermissionError("negative-control Recorder latch failure")

    monkeypatch.setattr(link, "record_stop", stop_lost)
    monkeypatch.setattr(elmo_link, "_latch_recorder_unknown", latch_lost)

    with pytest.raises(elmo_link.DisconnectCleanupError) as caught:
        link.disconnect()

    assert comm.called
    assert [phase for phase, _exc in caught.value.failures] == [
        "Recorder Stop", "Recorder UNKNOWN latch", "vendor Disconnect"]
    assert link._comm is None
    assert link._factory is None
    assert link._rec_pending is None
    assert link._personality_provenance == {}
    assert link._connected_drive_identity is None
    assert link._prepared_persistence_attempt_id is None
    assert link._acknowledged_persistence_attempt_id is None
    assert link._connection_epoch is None
