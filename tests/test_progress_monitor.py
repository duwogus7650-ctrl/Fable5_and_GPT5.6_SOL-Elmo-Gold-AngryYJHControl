"""Offline fail-closed contracts for the project progress monitor."""

from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtTest, QtWidgets

import progress_monitor


VALID_STATUS = """\
<!-- scope_progress: 100 -->
<!-- offline_progress: 60 -->
<!-- field_progress: 0 -->

# Quick Tuning + bounded single-axis status

Offline readiness is provisional.
Focused evidence: 481 passed.
Current-revision field validation is NEED-DATA.
"""


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_parse_status_markers_accepts_current_exact_snapshot():
    parsed = progress_monitor.parse_status_markers(VALID_STATUS)

    assert parsed.valid
    assert parsed.values == {
        "scope_progress": 100,
        "offline_progress": 60,
        "field_progress": 0,
    }
    assert "<!--" not in parsed.visible_markdown
    assert "NEED-DATA" in parsed.visible_markdown
    assert parsed.error == ""


@pytest.mark.parametrize(
    ("marker", "value"),
    (
        ("scope_progress", "100"),
        ("offline_progress", "60"),
        ("field_progress", "0"),
    ),
)
@pytest.mark.parametrize(
    ("replacement", "problem"),
    (
        (None, "missing"),
        ("nope", "malformed"),
        ("-1", "out of range"),
        ("101", "out of range"),
        ("duplicate", "duplicate"),
    ),
)
def test_parse_status_markers_rejects_missing_malformed_out_of_range_and_duplicate(
        marker, value, replacement, problem):
    marker_comment = f"<!-- {marker}: {value} -->"
    if replacement is None:
        status = VALID_STATUS.replace(marker_comment + "\n", "")
    elif replacement == "duplicate":
        status = VALID_STATUS + "\n" + marker_comment + "\n"
    else:
        status = VALID_STATUS.replace(
            f"{marker}: {value}", f"{marker}: {replacement}")

    parsed = progress_monitor.parse_status_markers(status)

    assert not parsed.valid
    assert parsed.values is None
    assert problem in parsed.error.lower()


@pytest.fixture
def monitor(qapp, tmp_path):
    path = tmp_path / "tasks" / "status.md"
    path.parent.mkdir()
    path.write_text(VALID_STATUS, encoding="utf-8")
    window = progress_monitor.ProgressMonitor(status_path=path)
    window.show()
    qapp.processEvents()
    yield window, path
    window.close()
    qapp.processEvents()


def test_valid_status_has_exact_values_and_honest_labels(monitor):
    window, path = monitor

    assert window.feed_valid is True
    assert window.state.text() == "STATUS FEED ACTIVE"
    assert window.scope_bar.value() == 100
    assert window.offline_bar.value() == 60
    assert window.field_bar.value() == 0
    assert "QUICK TUNING" in window.scope_label.text()
    assert "PROVISIONAL" in window.offline_label.text()
    assert "NEED-DATA" in window.field_label.text()
    assert window.scope_bar.format() == "%p% · SCOPE FROZEN"
    assert window.offline_bar.format() == "%p% · PROVISIONAL"
    assert window.field_bar.format() == "NEED-DATA · LIVE NOT RUN"
    assert "481 passed" in window.document.toPlainText()
    assert window.windowTitle() == "AngryYJH · Quick + Single Axis Monitor"
    assert window.findChild(QtWidgets.QLabel, "title").text() == (
        "GOLD TWITTER QUICK + SINGLE AXIS")
    assert window.findChild(QtWidgets.QLabel, "subtitle").text() == (
        "OFFLINE HARDEN → FIELD GATES → SUPERVISED VALIDATION")
    assert "NEED-DATA" in window.document.toPlainText()
    assert str(path) in window.watcher.files()
    assert str(path.parent) in window.watcher.directories()


def test_status_markdown_preserves_korean_after_consecutive_html_breaks(monitor):
    window, path = monitor
    path.write_text(
        """\
<!-- scope_progress: 100 -->
<!-- offline_progress: 60 -->
<!-- field_progress: 0 -->

# Gold Twitter Quick Tuning + 제한형 단일축 모니터

상세 인계: [`handoff.md`](handoff.md)<br>
상태: **OFFLINE HARDENED CANDIDATE**<br>
## 현재 기준점

한글 상태 본문이 화면에서 사라지면 안 된다.
""",
        encoding="utf-8",
    )

    window.reload()

    rendered = window.document.toPlainText()
    assert "현재 기준점" in rendered
    assert "한글 상태 본문이 화면에서 사라지면 안 된다." in rendered


def test_positive_field_evidence_replaces_live_not_run_label(monitor):
    window, path = monitor
    path.write_text(
        VALID_STATUS.replace("field_progress: 0", "field_progress: 15"),
        encoding="utf-8",
    )

    window.reload()

    assert window.feed_valid is True
    assert window.field_bar.value() == 15
    assert "PROVISIONAL" in window.field_label.text()
    assert window.field_bar.format() == "%p% · EVIDENCE TO DATE"
    assert "LIVE NOT RUN" not in window.field_bar.format()


def test_missing_file_and_missing_marker_render_invalid_stale_not_active(
        monitor, qapp):
    window, path = monitor
    path.unlink()
    window.reload()
    qapp.processEvents()

    assert window.feed_valid is False
    assert window.state.text() == "STATUS FEED INVALID/STALE"
    assert window.scope_bar.format() == "INVALID / STALE"
    assert window.offline_bar.format() == "INVALID / STALE"
    assert window.field_bar.format() == "INVALID / STALE"
    assert str(path.parent) in window.watcher.directories()

    path.write_text(VALID_STATUS.replace("<!-- scope_progress: 100 -->\n", ""),
                    encoding="utf-8")
    window.reload()

    assert window.feed_valid is False
    assert window.state.text() == "STATUS FEED INVALID/STALE"
    assert "missing" in window.document.toPlainText().lower()


@pytest.mark.parametrize(
    "invalid_status",
    (
        VALID_STATUS.replace("offline_progress: 60", "offline_progress: nope"),
        VALID_STATUS.replace("offline_progress: 60", "offline_progress: -1"),
        VALID_STATUS.replace("offline_progress: 60", "offline_progress: 101"),
    ),
)
def test_invalid_marker_classes_render_invalid_stale_ui(
        monitor, invalid_status):
    window, path = monitor
    path.write_text(invalid_status, encoding="utf-8")

    window.reload()

    assert window.feed_valid is False
    assert window.state.text() == "STATUS FEED INVALID/STALE"
    assert window.offline_bar.format() == "INVALID / STALE"


def _wait_until(qapp, predicate, *, timeout_ms=2000):
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        QtTest.QTest.qWait(20)
    assert predicate(), "filesystem watcher did not deliver the expected state"


def test_atomic_replace_delete_and_recreate_refresh_watch_and_state(
        monitor, qapp, tmp_path):
    window, path = monitor
    replacement = tmp_path / "replacement.md"
    replacement.write_text(
        VALID_STATUS.replace("offline_progress: 60", "offline_progress: 61"),
        encoding="utf-8",
    )
    os.replace(replacement, path)
    _wait_until(qapp, lambda: window.feed_valid and window.offline_bar.value() == 61)

    assert window.feed_valid is True
    assert window.offline_bar.value() == 61
    assert str(path) in window.watcher.files()
    assert str(path.parent) in window.watcher.directories()

    path.unlink()
    _wait_until(qapp, lambda: not window.feed_valid)
    assert window.feed_valid is False
    assert str(path.parent) in window.watcher.directories()

    path.write_text(VALID_STATUS, encoding="utf-8")
    _wait_until(
        qapp,
        lambda: window.feed_valid and window.offline_bar.value() == 60,
    )

    assert window.feed_valid is True
    assert window.state.text() == "STATUS FEED ACTIVE"
    assert (window.scope_bar.value(), window.offline_bar.value(),
            window.field_bar.value()) == (100, 60, 0)
    assert str(path) in window.watcher.files()


def test_read_status_source_detects_fingerprint_change(tmp_path, monkeypatch):
    path = tmp_path / "status.md"
    path.write_text(VALID_STATUS, encoding="utf-8")
    real_stat = Path.stat
    calls = 0

    def changed_stat(self, *args, **kwargs):
        nonlocal calls
        stat = real_stat(self, *args, **kwargs)
        if self != path:
            return stat
        calls += 1
        if calls == 1:
            return stat
        return SimpleNamespace(
            st_dev=stat.st_dev,
            st_ino=stat.st_ino,
            st_size=stat.st_size + 1,
            st_mtime_ns=stat.st_mtime_ns,
            st_mtime=stat.st_mtime,
        )

    monkeypatch.setattr(Path, "stat", changed_stat)

    with pytest.raises(progress_monitor.StatusSourceRace, match="changed during read"):
        progress_monitor.read_status_source(path)


def test_read_or_stat_race_fails_closed(monitor, monkeypatch):
    window, _path = monitor

    def raced(_path):
        raise progress_monitor.StatusSourceRace("status file changed during read")

    monkeypatch.setattr(progress_monitor, "read_status_source", raced)
    window.reload()

    assert window.feed_valid is False
    assert window.state.text() == "STATUS FEED INVALID/STALE"
    assert "changed during read" in window.document.toPlainText()
