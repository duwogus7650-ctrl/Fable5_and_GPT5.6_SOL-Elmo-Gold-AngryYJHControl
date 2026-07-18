"""Deterministic shutdown-race regressions for ``main.DriveWorker``.

These tests never open a COM port.  ``main.ElmoLink`` is replaced with a
process-local fake before ``DriveWorker.run`` is entered.
"""

from __future__ import annotations

import threading
import time

import pytest

import main as app_main


class _FakeLink:
    """Small query-capable link with a shutdown-forbidden I/O audit trail."""

    def __init__(self, *, disconnect_error: bool = False):
        # These shutdown races queue mutation-capable jobs deliberately, so
        # their fake transport must attest the supervised mode explicitly.
        self.access_mode = app_main.DriveWorker.SUPERVISED_ACCESS_MODE
        self.disconnect_error = bool(disconnect_error)
        self.forbidden_after_stop_io: list[tuple[str, object]] = []
        self.disconnect_attempted = False
        self.telemetry = {
            "pos": 123,
            "vel": 0.0,
            "pos_err": 0,
            "iq": 0.0,
            "mo": 0,
            "_sample_started_monotonic": 0.0,
            "_sample_finished_monotonic": 0.0,
            "_sample_duration_s": 0.0,
        }

    def connect(self):
        return True

    def command(self, command, **_kwargs):
        text = str(command)
        if text == "SN[4]":
            self.forbidden_after_stop_io.append(("send_once", text))
        if "=" in text:
            self.forbidden_after_stop_io.append(("command", text))
            if text == "PX=0":
                self.telemetry["pos"] = 0
        if text == "VR":
            return "FakeFW"
        if text == "VP":
            return "90"
        if text == "VB":
            return "FakeBoot"
        return "0"

    def transaction_identity(self):
        return "elmo-sn4-sha256:" + ("0" * 64)

    def persistence_status(self):
        return {
            "status": "CLEAR",
            "resolved": True,
            "detail": "fake",
            "lock_active": False,
            "record_id": None,
            "phase": None,
            "other_active_count": 0,
            "ledger_error": None,
        }

    def recorder_recovery_unknown_latched(self):
        return False

    def read_motor_params(self):
        return {}

    def read_feedback(self):
        return {}

    def read_tuning_gains(self):
        return {}

    def read_telemetry(self):
        sample = dict(self.telemetry)
        now = time.monotonic()
        sample["_sample_started_monotonic"] = now
        sample["_sample_finished_monotonic"] = now
        sample["_sample_duration_s"] = 0.0
        return sample

    def write_motor_params(self, writes, expected_ca18=None):
        self.forbidden_after_stop_io.append((
            "motor_write",
            {"writes": dict(writes), "expected_ca18": expected_ca18},
        ))
        return True, "fake write"

    def disconnect(self):
        self.disconnect_attempted = True
        if self.disconnect_error:
            raise RuntimeError("negative-control disconnect failure")


def test_stop_discards_pending_and_normal_job_queues_immediately():
    worker = app_main.DriveWorker("COM_FAKE")
    worker.send_once("SN[4]")
    worker.write_motor({"PL[1]": 1.0})
    worker.soft_zero()

    assert list(worker._pending) == ["SN[4]"]
    assert [kind for kind, _payload in worker._jobs] == [
        "motor_write", "soft_zero"]

    worker.stop()

    assert list(worker._pending) == [], (
        "stop() must revoke queued raw-command authority immediately")
    assert list(worker._jobs) == [], (
        "stop() must discard normal structured jobs immediately")


@pytest.mark.parametrize("command", ("RS", "LD", "XQ", "ST", "BG", "MO" + "=1"))
def test_generic_query_queue_rejects_reset_program_and_motion_commands(command):
    worker = app_main.DriveWorker("COM_FAKE")
    with pytest.raises(ValueError):
        worker.send_once(command)
    assert list(worker._pending) == []


def test_stop_after_outer_loop_entry_blocks_raw_config_and_soft_zero_io(monkeypatch):
    link = _FakeLink()
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker = app_main.DriveWorker("COM_FAKE")
    # These jobs exist before shutdown, reproducing the original inner-loop
    # drain race.  More work is submitted after stop() below to prove that the
    # stopped worker cannot acquire fresh normal-command authority either.
    worker.send_once("SN[4]")
    worker.write_motor({"PL[1]": 1.0})
    worker.soft_zero()

    outer_loop_entered = threading.Event()
    release_worker = threading.Event()
    original_drain = worker._drain_urgent_motion_jobs
    first_drain = True

    def barrier_drain(fake_link):
        nonlocal first_drain
        if first_drain:
            first_drain = False
            outer_loop_entered.set()
            assert release_worker.wait(2.0), "test failed to release worker barrier"
        return original_drain(fake_link)

    monkeypatch.setattr(worker, "_drain_urgent_motion_jobs", barrier_drain)

    runner = threading.Thread(target=worker.run, name="fake-drive-worker")
    runner.start()
    assert outer_loop_entered.wait(2.0), "worker never entered its outer loop"

    worker.stop()
    worker.send_once("SN[4]")
    worker.write_motor({"CL[1]": 2.0})
    worker.soft_zero()
    release_worker.set()

    runner.join(3.0)
    assert not runner.is_alive(), "worker did not terminate after stop()"
    assert link.forbidden_after_stop_io == [], (
        "normal query/config/soft-zero I/O executed after shutdown authority was revoked: "
        f"{link.forbidden_after_stop_io!r}")


def test_stop_during_pre_mutation_refresh_blocks_popped_write(monkeypatch):
    """A job popped before STOP must re-check authority after its fresh query."""
    refresh_entered = threading.Event()
    release_refresh = threading.Event()

    class _BlockingRefreshLink(_FakeLink):
        def __init__(self):
            super().__init__()
            self.telemetry_reads = 0

        def read_telemetry(self):
            self.telemetry_reads += 1
            if self.telemetry_reads == 2:
                refresh_entered.set()
                assert release_refresh.wait(2.0), (
                    "test did not release pre-mutation refresh")
            return super().read_telemetry()

    link = _BlockingRefreshLink()
    worker = app_main.DriveWorker("COM_FAKE")
    worker.write_motor({"PL[1]": 1.0})
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    runner = threading.Thread(target=worker.run, name="blocked-fresh-query")
    runner.start()
    assert refresh_entered.wait(2.0), "worker never reached pre-mutation refresh"
    worker.stop()
    release_refresh.set()
    runner.join(3.0)

    assert not runner.is_alive()
    assert not any(kind == "motor_write" for kind, _ in link.forbidden_after_stop_io)
    assert link.telemetry_reads == 2, (
        "worker performed post-stop periodic telemetry after leaving job dispatch")
    assert link.disconnect_attempted


@pytest.mark.parametrize("target", ("motor_write", "autotune"))
def test_pre_mutation_refresh_failure_never_calls_write_or_tuning_target(
        monkeypatch, target):
    """The fresh read is a hard gate, not advisory telemetry."""

    class _FailedRefreshLink(_FakeLink):
        def __init__(self):
            super().__init__()
            self.telemetry_reads = 0

        def read_telemetry(self):
            self.telemetry_reads += 1
            if self.telemetry_reads == 2:
                raise TimeoutError("negative-control pre-mutation refresh loss")
            return super().read_telemetry()

    link = _FailedRefreshLink()
    target_calls: list[str] = []
    worker = app_main.DriveWorker("COM_FAKE")
    if target == "motor_write":
        worker.write_motor({"PL[1]": 1.0})
    else:
        def forbidden_autotune(*_args, **_kwargs):
            target_calls.append("autotune")
            raise AssertionError("autotune target crossed failed fresh gate")

        monkeypatch.setattr(
            app_main.autotune_current, "run_current_autotune",
            forbidden_autotune)
        worker.start_autotune({})

    failures: list[str] = []
    terminal: list[bool] = []
    worker.failed.connect(failures.append)
    worker.stopped.connect(lambda: terminal.append(True))
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker.run()

    assert link.telemetry_reads == 2
    assert not any(
        kind == "motor_write" for kind, _payload in link.forbidden_after_stop_io)
    assert target_calls == []
    assert failures and "pre-mutation refresh loss" in failures[-1]
    assert terminal == [True]
    assert link.disconnect_attempted


def test_disconnect_exception_still_emits_a_terminal_notification(monkeypatch):
    link = _FakeLink(disconnect_error=True)
    monkeypatch.setattr(app_main, "ElmoLink", lambda _port: link)

    worker = app_main.DriveWorker("COM_FAKE")
    terminal_events: list[tuple[str, tuple[object, ...]]] = []
    for signal_name in ("stopped", "failed", "connection_lost"):
        signal = getattr(worker, signal_name, None)
        if signal is not None:
            signal.connect(
                lambda *args, name=signal_name:
                terminal_events.append((name, tuple(args))))

    # Stop immediately after successful read-only admission so the complete
    # connect/identity/startup/final-disconnect path is exercised.  Calling
    # stop() before run() now intentionally avoids opening a transport at all.
    original_drain = worker._drain_urgent_motion_jobs

    def stop_on_first_loop(fake_link):
        worker.stop()
        return original_drain(fake_link)

    monkeypatch.setattr(worker, "_drain_urgent_motion_jobs", stop_on_first_loop)
    try:
        worker.run()
    except RuntimeError as exc:
        assert "negative-control disconnect failure" in str(exc)

    assert link.disconnect_attempted
    assert terminal_events, (
        "disconnect() failure must still produce stopped/failed/connection_lost "
        "so the UI cannot remain falsely ONLINE")
