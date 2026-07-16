"""Event-driven project progress monitor; no hardware or network access."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from PyQt6 import QtCore, QtWidgets


ROOT = Path(__file__).resolve().parent
STATUS_PATH = ROOT / "tasks" / "status.md"
REQUIRED_MARKERS = (
    "scope_progress",
    "offline_progress",
    "field_progress",
)
_MARKER_COMMENT = re.compile(
    r"<!--\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([^\r\n]*?)\s*-->"
)


@dataclass(frozen=True)
class ParsedStatus:
    """Result of validating progress markers without touching the filesystem."""

    valid: bool
    values: Mapping[str, int] | None
    visible_markdown: str
    error: str = ""


@dataclass(frozen=True)
class StatusSource:
    text: str
    modified_seconds: int


class StatusSourceRace(OSError):
    """The status file identity changed while a snapshot was being read."""


def parse_status_markers(text: str) -> ParsedStatus:
    """Validate the three required 0..100 integer markers fail-closed."""

    raw_by_name: dict[str, list[str]] = {name: [] for name in REQUIRED_MARKERS}
    for match in _MARKER_COMMENT.finditer(text):
        name, raw = match.groups()
        if name in raw_by_name:
            raw_by_name[name].append(raw.strip())

    errors: list[str] = []
    values: dict[str, int] = {}
    for name in REQUIRED_MARKERS:
        raw_values = raw_by_name[name]
        if not raw_values:
            errors.append(f"missing required marker: {name}")
            continue
        if len(raw_values) != 1:
            errors.append(f"duplicate marker: {name}")
            continue
        raw = raw_values[0]
        if not re.fullmatch(r"[+-]?\d+", raw):
            errors.append(f"malformed integer marker: {name}={raw!r}")
            continue
        value = int(raw)
        if not 0 <= value <= 100:
            errors.append(f"out of range marker: {name}={value}; expected 0..100")
            continue
        values[name] = value

    visible = _MARKER_COMMENT.sub("", text).strip()
    if errors:
        return ParsedStatus(False, None, visible, "; ".join(errors))
    return ParsedStatus(True, values, visible)


def _source_fingerprint(stat_result) -> tuple[int, int, int, int]:
    return (
        int(getattr(stat_result, "st_dev", 0)),
        int(getattr(stat_result, "st_ino", 0)),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
    )


def read_status_source(path: Path) -> StatusSource:
    """Read one stable status snapshot or raise instead of mixing revisions."""

    before = path.stat()
    text = path.read_text(encoding="utf-8")
    after = path.stat()
    if _source_fingerprint(before) != _source_fingerprint(after):
        raise StatusSourceRace("status file changed during read; retry required")
    return StatusSource(text=text, modified_seconds=int(after.st_mtime))


class ProgressMonitor(QtWidgets.QMainWindow):
    def __init__(self, *, status_path: Path = STATUS_PATH):
        super().__init__()
        self.status_path = Path(status_path).resolve()
        self.feed_valid = False
        self.setWindowTitle("AngryYJH · Quick + Single Axis Monitor")
        self.resize(900, 720)
        self.setMinimumSize(720, 520)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        header = QtWidgets.QHBoxLayout()
        title_col = QtWidgets.QVBoxLayout()
        title = QtWidgets.QLabel("GOLD TWITTER QUICK + SINGLE AXIS")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel(
            "OFFLINE HARDEN → FIELD GATES → SUPERVISED VALIDATION")
        subtitle.setObjectName("subtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        header.addLayout(title_col)
        header.addStretch(1)
        self.state = QtWidgets.QLabel("STATUS FEED INVALID/STALE")
        self.state.setObjectName("state")
        self.state.setProperty("feedValid", False)
        header.addWidget(self.state)
        root.addLayout(header)

        progress_grid = QtWidgets.QGridLayout()
        progress_grid.setHorizontalSpacing(12)
        progress_grid.setVerticalSpacing(8)
        self.scope_label = QtWidgets.QLabel(
            "SCOPED PLAN · QUICK TUNING + FINITE PTP")
        progress_grid.addWidget(self.scope_label, 0, 0)
        self.scope_bar = QtWidgets.QProgressBar()
        self.scope_bar.setRange(0, 100)
        progress_grid.addWidget(self.scope_bar, 0, 1)
        self.offline_label = QtWidgets.QLabel(
            "SOFTWARE / OFFLINE READINESS · PROVISIONAL")
        progress_grid.addWidget(self.offline_label, 1, 0)
        self.offline_bar = QtWidgets.QProgressBar()
        self.offline_bar.setRange(0, 100)
        progress_grid.addWidget(self.offline_bar, 1, 1)
        self.field_label = QtWidgets.QLabel(
            "CURRENT-REVISION FIELD VALIDATION · NEED-DATA")
        progress_grid.addWidget(self.field_label, 2, 0)
        self.field_bar = QtWidgets.QProgressBar()
        self.field_bar.setRange(0, 100)
        progress_grid.addWidget(self.field_bar, 2, 1)
        root.addLayout(progress_grid)

        self.document = QtWidgets.QTextBrowser()
        self.document.setOpenExternalLinks(False)
        self.document.setObjectName("document")
        root.addWidget(self.document, 1)

        footer = QtWidgets.QHBoxLayout()
        self.updated = QtWidgets.QLabel("Not loaded")
        self.updated.setObjectName("footer")
        footer.addWidget(self.updated)
        footer.addStretch(1)
        scope = QtWidgets.QLabel("PROJECT-LOCAL · NO DRIVE I/O")
        scope.setObjectName("safe")
        footer.addWidget(scope)
        root.addLayout(footer)

        self.setStyleSheet("""
            QMainWindow, QWidget { background:#08182a; color:#d8e8f8; }
            QLabel#title { font-size:24px; font-weight:900; letter-spacing:2px; color:#f4f8fc; }
            QLabel#subtitle { color:#52bce8; font:700 11px 'Consolas'; letter-spacing:1px; }
            QLabel#state { background:#12304c; border:1px solid #3aaee0; border-radius:5px;
                           padding:9px 16px; color:#8edcff; font:800 12px 'Consolas'; }
            QLabel#state[feedValid="false"] { background:#3a2028; border-color:#d85c70;
                                                color:#ff9aaa; }
            QLabel#footer { color:#7893ad; font:11px 'Consolas'; }
            QLabel#safe { color:#54d6a1; font:800 11px 'Consolas'; }
            QProgressBar { min-height:22px; border:1px solid #244967; border-radius:4px;
                           background:#071421; text-align:center; color:#e9f5ff;
                           font:700 11px 'Consolas'; }
            QProgressBar::chunk { background:#278fbd; border-radius:3px; }
            QTextBrowser#document { background:#0b1e32; border:1px solid #21445f;
                                    border-radius:6px; padding:12px; color:#d8e8f8;
                                    selection-background-color:#278fbd; }
            QScrollBar:vertical { background:#091827; width:12px; }
            QScrollBar::handle:vertical { background:#28516d; min-height:30px; border-radius:5px; }
        """)

        self.watcher = QtCore.QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.reload)
        self.watcher.directoryChanged.connect(self.reload)
        self._ensure_watch_paths()
        self.reload()

    def _ensure_watch_paths(self) -> None:
        parent = str(self.status_path.parent)
        if self.status_path.parent.is_dir() and parent not in self.watcher.directories():
            self.watcher.addPath(parent)
        source = str(self.status_path)
        if self.status_path.is_file() and source not in self.watcher.files():
            self.watcher.addPath(source)

    def _refresh_state_style(self, valid: bool) -> None:
        self.state.setProperty("feedValid", valid)
        style = self.state.style()
        style.unpolish(self.state)
        style.polish(self.state)

    def _render_invalid(self, reason: str) -> None:
        self.feed_valid = False
        self.state.setText("STATUS FEED INVALID/STALE")
        self._refresh_state_style(False)
        for bar in (self.scope_bar, self.offline_bar, self.field_bar):
            bar.setValue(0)
            bar.setFormat("INVALID / STALE")
        self.document.setPlainText(
            "STATUS FEED INVALID/STALE\n\n"
            f"Source: {self.status_path}\n"
            f"Reason: {reason}\n\n"
            "Progress values are withheld until all required markers validate."
        )
        self.updated.setText("STATUS SOURCE · INVALID / STALE")

    def _render_valid(self, parsed: ParsedStatus, source: StatusSource) -> None:
        assert parsed.values is not None
        self.feed_valid = True
        self.scope_bar.setValue(parsed.values["scope_progress"])
        self.scope_bar.setFormat("%p% · SCOPE FROZEN")
        self.offline_bar.setValue(parsed.values["offline_progress"])
        self.offline_bar.setFormat("%p% · PROVISIONAL")
        field_progress = parsed.values["field_progress"]
        self.field_bar.setValue(field_progress)
        if field_progress == 0:
            self.field_label.setText(
                "CURRENT-REVISION FIELD VALIDATION · NEED-DATA")
            self.field_bar.setFormat("NEED-DATA · LIVE NOT RUN")
        else:
            self.field_label.setText(
                "CURRENT-REVISION FIELD VALIDATION · PROVISIONAL")
            self.field_bar.setFormat("%p% · EVIDENCE TO DATE")
        self.document.setMarkdown(parsed.visible_markdown)
        updated = QtCore.QDateTime.fromSecsSinceEpoch(
            source.modified_seconds).toString("yyyy-MM-dd HH:mm:ss")
        self.updated.setText("STATUS SOURCE · tasks/status.md · " + updated)
        self.state.setText("STATUS FEED ACTIVE")
        self._refresh_state_style(True)

    def reload(self, *_args) -> None:
        self._ensure_watch_paths()
        try:
            source = read_status_source(self.status_path)
        except (OSError, UnicodeError) as exc:
            self._render_invalid(str(exc) or exc.__class__.__name__)
            self._ensure_watch_paths()
            return

        parsed = parse_status_markers(source.text)
        if not parsed.valid:
            self._render_invalid(parsed.error)
            self._ensure_watch_paths()
            return

        self._render_valid(parsed, source)
        self._ensure_watch_paths()


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Quick + Single Axis Monitor")
    window = ProgressMonitor()
    window.show()
    if "--smoke" in sys.argv:
        app.processEvents()
        assert window.feed_valid is True
        assert window.state.text() == "STATUS FEED ACTIVE"
        assert (window.scope_bar.value(), window.offline_bar.value(),
                window.field_bar.value()) == (100, 60, 0)
        assert window.scope_bar.format() == "%p% · SCOPE FROZEN"
        assert window.offline_bar.format() == "%p% · PROVISIONAL"
        assert window.field_bar.format() == "NEED-DATA · LIVE NOT RUN"
        assert "Quick Tuning" in window.document.toPlainText()
        print("GREEN · scoped snapshot 100/60/0 · no hardware I/O")
        window.close()
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
