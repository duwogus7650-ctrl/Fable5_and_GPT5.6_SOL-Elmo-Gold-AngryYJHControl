"""Session-only, zero-I/O projection for Status Monitor v0.1.

The model displays only telemetry that the application core has already
admitted.  ``fresh is True`` is therefore an explicit caller attestation; this
module does not poll a drive, own a timer, or duplicate the core's receive and
sample-finish age checks.  Every current sample is bound to one explicit
connection generation and one canonical hashed SN[4] identity.

Line layout is immutable and process-local.  Native EAS ``.smc``/``.sac``
configuration persistence is deliberately outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType


MAX_LINES = 16
_DRIVE_IDENTITY_RE = re.compile(r"elmo-sn4-sha256:[0-9a-f]{64}")


class StatusMonitorError(ValueError):
    """Base error for invalid local Status Monitor operations."""


class ConfigRejected(StatusMonitorError):
    """Raised before an invalid line layout can replace the current one."""


@dataclass(frozen=True, slots=True)
class SignalSpec:
    telemetry_key: str
    unit: str
    description: str


SIGNAL_SPECS = MappingProxyType({
    "PX": SignalSpec("pos", "cnt", "Position"),
    "VX": SignalSpec("vel", "cnt/s", "Velocity"),
    "PE": SignalSpec("pos_err", "cnt", "Position Error"),
    "IQ": SignalSpec("iq", "A", "Active Current"),
    "MO": SignalSpec("mo", "state", "Motor Enable"),
})
_SIGNAL_CODES = frozenset(SIGNAL_SPECS)


def _validate_lines(lines) -> None:
    if type(lines) is not tuple:
        raise ConfigRejected("status monitor lines must be a tuple")
    if len(lines) > MAX_LINES:
        raise ConfigRejected("status monitor accepts at most 16 lines")
    if any(type(signal) is not str for signal in lines):
        raise ConfigRejected("status monitor lines must contain plain strings")
    for signal in lines:
        if signal not in _SIGNAL_CODES:
            raise ConfigRejected("unknown signal: %s" % signal)
    if len(set(lines)) != len(lines):
        raise ConfigRejected("status monitor lines must be unique")


@dataclass(frozen=True, slots=True)
class StatusMonitorConfig:
    """Immutable ordered line layout for the current process session."""

    lines: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_lines(self.lines)


DEFAULT_CONFIG = StatusMonitorConfig(lines=tuple(SIGNAL_SPECS))


def validate_config(config: StatusMonitorConfig) -> StatusMonitorConfig:
    """Revalidate a candidate and return that exact frozen instance."""
    if type(config) is not StatusMonitorConfig:
        raise ConfigRejected("config must be a StatusMonitorConfig")
    _validate_lines(config.lines)
    return config


def _validated_signal(signal) -> str:
    if type(signal) is not str or signal not in _SIGNAL_CODES:
        raise ConfigRejected("unknown signal: %s" % str(signal))
    return signal


def insert_line(config: StatusMonitorConfig, signal: str,
                index: int) -> StatusMonitorConfig:
    """Return a new layout with one allowlisted signal inserted at ``index``."""
    validate_config(config)
    signal = _validated_signal(signal)
    if signal in config.lines:
        raise ConfigRejected("signal is already present: %s" % signal)
    if type(index) is not int or index < 0 or index > len(config.lines):
        raise ConfigRejected("insert index is outside the line layout")
    lines = config.lines[:index] + (signal,) + config.lines[index:]
    return StatusMonitorConfig(lines=lines)


def delete_line(config: StatusMonitorConfig, signal: str) -> StatusMonitorConfig:
    """Return a new layout without one currently displayed signal."""
    validate_config(config)
    signal = _validated_signal(signal)
    if signal not in config.lines:
        raise ConfigRejected("signal is not present: %s" % signal)
    return StatusMonitorConfig(
        lines=tuple(item for item in config.lines if item != signal))


def move_line(config: StatusMonitorConfig, signal: str,
              delta: int) -> StatusMonitorConfig:
    """Return a new layout with one displayed signal moved by ``delta``."""
    validate_config(config)
    signal = _validated_signal(signal)
    if type(delta) is not int:
        raise ConfigRejected("move delta must be an integer")
    if signal not in config.lines:
        raise ConfigRejected("signal is not present: %s" % signal)
    if delta == 0:
        return config

    source = config.lines.index(signal)
    destination = source + delta
    if destination < 0 or destination >= len(config.lines):
        raise ConfigRejected("move would place signal outside the line layout")
    reordered = list(config.lines)
    reordered.pop(source)
    reordered.insert(destination, signal)
    return StatusMonitorConfig(lines=tuple(reordered))


def reset_lines() -> StatusMonitorConfig:
    """Return the single immutable default layout without reading any file."""
    return DEFAULT_CONFIG


@dataclass(frozen=True, slots=True)
class StatusLine:
    signal: str
    telemetry_key: str
    unit: str
    description: str
    value: int | float | None


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    current: bool
    generation: int | None
    drive_alias: str | None
    sequence: int | None
    lines: tuple[StatusLine, ...]
    reason: str


def _is_positive_integer(value) -> bool:
    return type(value) is int and value > 0


def _is_canonical_drive_identity(value) -> bool:
    return type(value) is str and _DRIVE_IDENTITY_RE.fullmatch(value) is not None


def _validate_drive_identity(value) -> str:
    if not _is_canonical_drive_identity(value):
        raise StatusMonitorError(
            "canonical drive identity must be "
            "elmo-sn4-sha256:<64 lowercase hex>")
    return value


def _identity_alias(identity: str | None) -> str | None:
    if identity is None:
        return None
    # Snapshot/export-safe fixed alias.  The exact hash remains only in the
    # private equality binding; even a stable digest prefix would permit
    # unnecessary cross-session target correlation if a snapshot were logged.
    return "Drive01"


class StatusMonitorModel:
    """Fail-closed projection of already-admitted, identity-bound telemetry."""

    def __init__(self, config: StatusMonitorConfig | None = None):
        self._config = (
            DEFAULT_CONFIG if config is None else validate_config(config))
        self._active_generation: int | None = None
        self._active_drive_identity: str | None = None
        self._last_sequence = 0
        self._snapshot = self._blank_snapshot("NO_ACTIVE_GENERATION")

    @property
    def config(self) -> StatusMonitorConfig:
        return self._config

    @property
    def active_generation(self) -> int | None:
        return self._active_generation

    @property
    def active_drive_identity(self) -> str | None:
        """Exact in-memory binding used for comparison, never put in snapshots."""
        return self._active_drive_identity

    def snapshot(self) -> StatusSnapshot:
        return self._snapshot

    def _project_lines(self, values=None) -> tuple[StatusLine, ...]:
        projected = []
        for signal in self._config.lines:
            spec = SIGNAL_SPECS[signal]
            value = None if values is None else values[signal]
            projected.append(StatusLine(
                signal=signal,
                telemetry_key=spec.telemetry_key,
                unit=spec.unit,
                description=spec.description,
                value=value,
            ))
        return tuple(projected)

    def _blank_snapshot(self, reason: str) -> StatusSnapshot:
        return StatusSnapshot(
            current=False,
            generation=self._active_generation,
            drive_alias=_identity_alias(self._active_drive_identity),
            sequence=None,
            lines=self._project_lines(),
            reason=reason,
        )

    def _revoke_with(self, reason: str) -> StatusSnapshot:
        self._snapshot = self._blank_snapshot(reason)
        return self._snapshot

    def activate_generation(self, generation: int,
                            drive_identity: str) -> StatusSnapshot:
        """Reset sequence authority and bind an explicit connection context."""
        if not _is_positive_integer(generation):
            raise StatusMonitorError("generation must be a positive integer")
        identity = _validate_drive_identity(drive_identity)

        self._active_generation = generation
        self._active_drive_identity = identity
        self._last_sequence = 0
        return self._revoke_with("GENERATION_ACTIVATED")

    def end_generation(self, reason=None) -> StatusSnapshot:
        """Clear connection authority; caller details are intentionally ignored."""
        self._active_generation = None
        self._active_drive_identity = None
        self._last_sequence = 0
        return self._revoke_with("GENERATION_ENDED")

    def revoke(self, reason=None) -> StatusSnapshot:
        """Blank values while retaining authority for later same-session recovery."""
        return self._revoke_with("TELEMETRY_REVOKED")

    def replace_config(self, config: StatusMonitorConfig) -> StatusSnapshot:
        """Atomically replace only the process-local line layout."""
        candidate = validate_config(config)
        self._config = candidate
        return self._revoke_with("CONFIG_CHANGED")

    def observe(self, telemetry, *, generation, sequence, drive_identity,
                fresh) -> StatusSnapshot:
        """Project one already-admitted sample or revoke the complete display.

        ``fresh`` must be exactly ``True`` and represents the application core's
        freshness admission, including its receive and sample-finish clocks.
        This observer intentionally contains all telemetry access exceptions so
        a display-only failure cannot revoke core telemetry authority.
        """
        if fresh is not True:
            return self._revoke_with("STALE_TELEMETRY")
        if not _is_positive_integer(generation):
            return self._revoke_with("INVALID_GENERATION")
        if self._active_generation is None:
            return self._revoke_with("NO_ACTIVE_GENERATION")
        if generation != self._active_generation:
            return self._revoke_with("GENERATION_MISMATCH")
        if not _is_canonical_drive_identity(drive_identity):
            return self._revoke_with("INVALID_DRIVE_IDENTITY")
        if drive_identity != self._active_drive_identity:
            return self._revoke_with("IDENTITY_MISMATCH")
        if not _is_positive_integer(sequence):
            return self._revoke_with("INVALID_SEQUENCE")
        if sequence <= self._last_sequence:
            return self._revoke_with("SEQUENCE_NOT_INCREASING")

        values = {}
        try:
            # Validate the complete fixed telemetry contract even when the user
            # has hidden some lines.  Partial samples never produce partial UI.
            for signal, spec in SIGNAL_SPECS.items():
                try:
                    value = telemetry[spec.telemetry_key]
                except KeyError:
                    return self._revoke_with("TELEMETRY_INCOMPLETE")
                if type(value) not in (int, float) or not math.isfinite(value):
                    return self._revoke_with("TELEMETRY_INVALID")
                if signal == "MO" and float(value) not in (0.0, 1.0):
                    return self._revoke_with("TELEMETRY_INVALID")
                values[signal] = value
        except Exception:
            return self._revoke_with("OBSERVER_ERROR_LOCAL")

        self._last_sequence = sequence
        self._snapshot = StatusSnapshot(
            current=True,
            generation=self._active_generation,
            drive_alias=_identity_alias(self._active_drive_identity),
            sequence=sequence,
            lines=self._project_lines(values),
            reason="CURRENT",
        )
        return self._snapshot


# Descriptive alias for adapters that treat the model as a projection.
StatusMonitorProjection = StatusMonitorModel
