"""Shared, side-effect-free operation classification for AngryYJH Control.

The catalog is deliberately pure data.  Importing it cannot open a serial port,
construct a worker, or issue a drive command.  UI code uses the same operation
IDs for labels/tooltips that safety tests use for boundary assertions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class OperationRisk(str, Enum):
    LOCAL_UI = "local_ui"
    LOCAL_FILE = "local_file"
    DRIVE_READ = "drive_read"
    DRIVE_STATE = "drive_state"
    RAM_WRITE = "ram_write"
    ENERGIZING = "energizing"
    MOTION = "motion"
    PERSISTENT_WRITE = "persistent_write"
    SAFETY_STOP = "safety_stop"
    NEED_DATA = "need_data"


class OperationStatus(str, Enum):
    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    NEED_DATA = "need_data"


@dataclass(frozen=True)
class OperationSpec:
    operation_id: str
    label: str
    risk: OperationRisk
    summary: str
    gates: frozenset[str] = frozenset()
    status: OperationStatus = OperationStatus.IMPLEMENTED
    menu_enabled: bool = False


_IDENTITY_FRESH = frozenset(("verified_identity", "fresh_telemetry"))
_STATUS_MONITOR_POLL = _IDENTITY_FRESH | frozenset((
    "bounded_read_allowlist", "poll_ownership", "poll_rate_limit"))
_SCOPED_MUTATION = _IDENTITY_FRESH | frozenset((
    "explicit_scope", "motor_disabled", "exact_readback"))
_ENERGY = _IDENTITY_FRESH | frozenset((
    "explicit_scope", "motor_disabled", "current_limit",
    "verified_closeout"))
_MOTION = _ENERGY | frozenset(("site_motion_envelope",))
_PERSIST = _SCOPED_MUTATION | frozenset(("durable_authority",))


def _spec(operation_id, label, risk, summary, *, gates=(),
          status=OperationStatus.IMPLEMENTED, menu_enabled=False):
    return OperationSpec(
        operation_id=operation_id,
        label=label,
        risk=risk,
        summary=summary,
        gates=frozenset(gates),
        status=status,
        menu_enabled=bool(menu_enabled),
    )


_SPECS = (
    # Always-safe application navigation.  These actions select a page only;
    # the controls inside each page retain their independent hardware gates.
    _spec("nav.motion", "Single Axis Motion", OperationRisk.LOCAL_UI,
          "Open the single-axis status and finite-motion page.",
          menu_enabled=True),
    _spec("nav.motor", "Motor Settings", OperationRisk.LOCAL_UI,
          "Open motor parameters; opening the page performs no drive write.",
          menu_enabled=True),
    _spec("nav.feedback", "Feedback Settings", OperationRisk.LOCAL_UI,
          "Open feedback inspection and encoder-maintenance controls.",
          menu_enabled=True),
    _spec("nav.tuning.quick", "Quick Tuning · Guided", OperationRisk.LOCAL_UI,
          "Open the guided identification/design view; Run still has an energizing gate.",
          menu_enabled=True),
    _spec("nav.tuning.expert", "Expert Tuning · Candidates / Installed Verify",
          OperationRisk.LOCAL_UI,
          "Review candidates and run installed-gain verification; hardware gain Apply/Save are locked.",
          menu_enabled=True),
    _spec("tuning.expert.offline.calculate",
          "Expert Candidate Lab · Calculate Offline Model",
          OperationRisk.LOCAL_UI,
          "Calculate a phase-to-phase MODEL candidate and bounded frequency "
          "response locally with no drive, worker, or command I/O."),
    _spec("tuning.expert.offline.calculate_p2",
          "Expert Candidate Lab · Calculate Offline P2 Model",
          OperationRisk.LOCAL_UI,
          "Project a velocity/position MODEL candidate from the complete "
          "Current P1 MODEL plus explicit K_a and B with no drive, worker, "
          "command, gain-write, or motion I/O."),
    _spec("tuning.expert.filter.evidence.inspect",
          "Expert Filter Contract · Documented Topology",
          OperationRisk.LOCAL_UI,
          "Inspect documented filter types, physical parameter names and "
          "controller slots locally with no drive, worker, command, model, "
          "emulation, or write I/O.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.scheduling.evidence.inspect",
          "Expert Gain Scheduling Contract · Documented Topology",
          OperationRisk.LOCAL_UI,
          "Inspect documented GS[2] modes and KG table topology locally with "
          "no drive, worker, command, gain selection, emulation, or write I/O.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.page_status.inspect",
          "Expert Page Status / Errors · LOCAL",
          OperationRisk.LOCAL_UI,
          "Project existing local P1/P2/evidence state with no drive I/O; "
          "this is not EAS Enter/Apply state and not installed-drive evidence.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.user_units.preview",
          "Expert User Units · Documented Formula Preview",
          OperationRisk.LOCAL_UI,
          "Evaluate the documented formula for DS-402 position scaling from "
          "explicit "
          "manual FC inputs with no drive I/O and no FC/OF write. The "
          "documented grouping mismatch between the NetHelp formula and "
          "MAN-G-CR limits remains visible with its purpose NEED-DATA; this "
          "is not current drive config.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.limits_protections.evidence.inspect",
          "Expert Limits / Protections · Documented Parameter Map",
          OperationRisk.LOCAL_UI,
          "Inspect an immutable documented parameter map locally. It is not "
          "current drive config, not active protection state, and not safety "
          "evidence. It performs no drive read, no validation/evaluation, "
          "no command generation, no write, no Apply/SV, and no unit "
          "propagation.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.application_settings.evidence.inspect",
          "Expert Application Settings · Documented Application Settings Map",
          OperationRisk.LOCAL_UI,
          "Inspect an immutable documented application settings map locally. "
          "It is not current drive config, not current I/O state, and not "
          "brake or safety evidence. It performs no drive read, no "
          "validation/evaluation, no command generation, no write, no "
          "Apply/Revert/SV, no output actuation, no motion, and no drive I/O.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.application_settings.transaction",
          "Expert Application Settings Transaction · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Conditional visibility, validation rules, command mapping, write "
          "order, readback, rollback, Revert, SV, and output actuation remain "
          "unimplemented and NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.bode_verification.evidence.inspect",
          "Expert Hidden Bode Verification · Documented Map",
          OperationRisk.LOCAL_UI,
          "Inspect an immutable document map of the hidden EAS Current and "
          "Velocity/Position Bode pages plus Tuner Verification settings. "
          "It performs no drive read, no acquisition, no evaluation, no "
          "Verify, no EAS settings change, no energization, and no motion.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.bode_verification.execute",
          "Expert Bode Verification Execution · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Current verification energizes and Velocity/Position verification "
          "can move the motor. Safe amplitude, frequency and current bounds, "
          "sampling provenance, abort and closeout behavior, and quantitative "
          "acceptance criteria remain unimplemented and NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.time_verification.evidence.inspect",
          "Expert Time Verification - Documented Map",
          OperationRisk.LOCAL_UI,
          "Inspect an immutable Verification-Time document map locally. It "
          "performs no drive read, no recorder configuration, no acquisition, "
          "no Verify, no enable, no PTP, no jog, no injection, no "
          "energization, and no motion.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.time_verification.current.execute",
          "Expert Current Time Verification Execution - NEED-DATA",
          OperationRisk.ENERGIZING,
          "Actual Current Verification-Time execution energizes the selected "
          "phase and can move or twitch the motor; EAS displays a motor-"
          "movement warning. The current envelope, recorder provenance, "
          "abort, closeout, and quantitative acceptance contracts remain "
          "unimplemented and NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.time_verification.velocity_position.execute",
          "Expert Velocity / Position Time Verification Execution - NEED-DATA",
          OperationRisk.MOTION,
          "Actual Velocity/Position Verification-Time execution can enable "
          "the drive, change a motion current input and control parameters, "
          "and perform PTP, jog, and sine/step motion. The travel envelope, "
          "independent stop, telemetry, restore, and fault-recovery contracts "
          "remain unimplemented and NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.summary.evidence.inspect",
          "Expert Summary - Documented Transaction Map",
          OperationRisk.LOCAL_UI,
          "Inspect an immutable Summary transaction document map locally. It "
          "performs no drive read, no SV, no file dialog, no file export, no "
          "database mutation, no Save, no Apply, no energization, and no "
          "motion.",
          status=OperationStatus.PARTIAL),
    _spec("tuning.expert.summary.drive_persist",
          "Expert Summary Drive Persistence (SV) - NEED-DATA",
          OperationRisk.PERSISTENT_WRITE,
          "Actual SV would persist the selected tuning parameters in drive "
          "flash. Exact target/parameter identity, pre-save snapshot, "
          "readback, power-cycle evidence, rollback, and closeout remain "
          "unimplemented and NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.summary.parameter_export",
          "Expert Summary Parameter Export - NEED-DATA",
          OperationRisk.LOCAL_FILE,
          "Actual parameter export combines a drive read with a local file "
          "write. Snapshot consistency, destination path, file format, "
          "integrity, overwrite, and recovery remain unimplemented and "
          "NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.summary.design_export",
          "Expert Summary Design Export - NEED-DATA",
          OperationRisk.LOCAL_FILE,
          "Actual design export would save identified plants and controllers. "
          "The source identity, complete artifact schema, destination path, "
          "integrity, overwrite, and recovery remain unimplemented and "
          "NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.summary.database_import",
          "Expert Summary Motor Database Import - NEED-DATA",
          OperationRisk.LOCAL_FILE,
          "Actual import would perform a motor database mutation. Exact "
          "database identity/schema, backup, duplicate policy, transaction "
          "verification, rollback, and closeout remain unimplemented and "
          "NEED-DATA.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.filter.offline.evaluate",
          "Expert Filter Model · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Exact EAS/drive filter transfer functions, discretization, ranges "
          "and interaction with loop design are not established.",
          status=OperationStatus.NEED_DATA),
    _spec("tuning.expert.scheduling.offline.evaluate",
          "Expert Gain Scheduling Model · NEED-DATA",
          OperationRisk.NEED_DATA,
          "GS/KG table selection, interpolation, units and transition "
          "semantics are not established; no emulation or writes are exposed.",
          status=OperationStatus.NEED_DATA),
    _spec("nav.axis", "Axis Summary · Read only", OperationRisk.LOCAL_UI,
          "Open the raw, read-only axis summary.", menu_enabled=True),
    _spec("axis.safety_snapshot",
          "Single Axis Safety Snapshot · DRIVE-REPORTED MODEL",
          OperationRisk.LOCAL_UI,
          "Decode an existing MO/SO/MF/PS/SR/MS snapshot locally with no new "
          "drive query; this is not STO test evidence."),
    _spec("axis.drive_mode.refresh",
          "Single Axis Drive Mode · READ ONLY v0.1",
          OperationRisk.DRIVE_READ,
          "Explicitly read only UM for the current identity-bound session; "
          "one bounded query, no UM assignment, no mode change, no "
          "enable/reference command, and no motion.",
          gates=_IDENTITY_FRESH | frozenset((
              "bounded_read_allowlist",
              "explicit_refresh",
              "um_only",
          )),
          status=OperationStatus.PARTIAL),
    _spec("axis.current_reference.refresh",
          "Single Axis Current Reference · READ ONLY v0.1",
          OperationRisk.DRIVE_READ,
          "Explicitly read only MO/SO/MF/SR pre+post and "
          "UM/TC/IQ/ID/CL[1]/PL[1]/LC/MC for the current identity-bound "
          "session; no TC assignment, loop change, enable, or motion.",
          gates=_IDENTITY_FRESH | frozenset((
              "bounded_read_allowlist",
              "explicit_refresh",
              "exact_current_reference_query_set",
          )),
          status=OperationStatus.PARTIAL),
    _spec("axis.position_velocity_reference.refresh",
          "Single Axis Position / Velocity References - READ ONLY v0.1",
          OperationRisk.DRIVE_READ,
          "Explicitly read only MO/SO/MF/SR pre+post and "
          "UM/PA[1]/PR[1]/JV/SP[1]/AC[1]/DC/SD/PX/VX for the current "
          "identity-bound session. PA/PR/JV are configured or queued "
          "readbacks, not active command or motion proof; no assignment, "
          "no BG, no enable, and no motion.",
          gates=_IDENTITY_FRESH | frozenset((
              "bounded_read_allowlist",
              "explicit_refresh",
              "exact_position_velocity_query_set",
          )),
          status=OperationStatus.PARTIAL),
    _spec("axis.digital_inputs.refresh",
          "Single Axis Digital Inputs · READ ONLY v0.1",
          OperationRisk.DRIVE_READ,
          "Explicitly read only IP, IL[1..6], and IF[1..6] for the current "
          "identity-bound session; inputs 1..6 only, IP is read only, no IB "
          "sticky clear, "
          "no mapping/filter change, no output read or write, no enable, and "
          "no motion.",
          gates=_IDENTITY_FRESH | frozenset((
              "bounded_read_allowlist",
              "explicit_refresh",
              "inputs_1_to_6_only",
          )),
          status=OperationStatus.PARTIAL),
    _spec("axis.digital_outputs.refresh",
          "Single Axis Digital Outputs · READ ONLY v0.1",
          OperationRisk.DRIVE_READ,
          "Explicitly read only OP, OL[1..4], and GO[1..4] for the current "
          "identity-bound session; Gold Twitter outputs 1..4 only, OP is "
          "read last, no assignment, no output actuation, no physical-pin or "
          "STO-test claim, no enable, and no motion.",
          gates=_IDENTITY_FRESH | frozenset((
              "bounded_read_allowlist",
              "explicit_refresh",
              "outputs_1_to_4_only",
          )),
          status=OperationStatus.PARTIAL),
    _spec("eas.single_axis.authority.evidence.inspect",
          "Single Axis Controls - Documented Authority Map",
          OperationRisk.LOCAL_UI,
          "Inspect an immutable Single Axis document map locally with no "
          "drive read, no digital output write, no mode change, no enable, "
          "no PTP or jog, no current/sine/homing/stepper command, no terminal "
          "command send, no recorder configuration/acquisition, no "
          "energization, and no motion.",
          status=OperationStatus.PARTIAL),
    _spec("nav.recorder", "Recorder", OperationRisk.LOCAL_UI,
          "Open Recorder configuration and View Design.", menu_enabled=True),
    _spec("nav.session_log", "Status / Session Log · HOST OBSERVED v0.1",
          OperationRisk.LOCAL_UI,
          "Open the bounded host-side event viewer; opening it issues no drive query.",
          status=OperationStatus.PARTIAL, menu_enabled=True),
    _spec("nav.system_config", "System Configuration · Inspector v0.1",
          OperationRisk.LOCAL_UI,
          "Project already-admitted single-target state; opening it issues no drive query.",
          status=OperationStatus.PARTIAL, menu_enabled=True),
    _spec("ui.capability_guide", "Capability & risk guide",
          OperationRisk.LOCAL_UI,
          "Explain LOCAL, READ, RAM, ENERGY, MOTION and SV boundaries.",
          menu_enabled=True),
    _spec("ui.tool_organizer", "Tool Organizer · LOCAL v0.1",
          OperationRisk.LOCAL_UI,
          "Customize visibility and order of existing application pages; no worker or drive query.",
          status=OperationStatus.PARTIAL, menu_enabled=True),
    _spec("ui.status_monitor", "Status Monitor · HOST OBSERVED v0.1",
          OperationRisk.LOCAL_UI,
          "Open a modeless view of already-admitted PX/VX/PE/IQ/MO telemetry; "
          "no new drive polling or query.",
          status=OperationStatus.PARTIAL, menu_enabled=True),

    # Local Recorder files are intentionally not advertised as EAS-compatible.
    _spec("recorder.workspace.open", "Open Recorder Setup… · LOCAL JSON",
          OperationRisk.LOCAL_FILE,
          "Open this application's versioned Recorder JSON.", menu_enabled=True),
    _spec("recorder.workspace.save", "Save Recorder Setup · LOCAL JSON",
          OperationRisk.LOCAL_FILE,
          "Save this application's versioned Recorder JSON.", menu_enabled=True),
    _spec("recorder.workspace.save_as", "Save Recorder Setup As… · LOCAL JSON",
          OperationRisk.LOCAL_FILE,
          "Save a copy in this application's local JSON format.",
          menu_enabled=True),
    _spec("session_log.export_json", "Export Session Log… · LOCAL JSON",
          OperationRisk.LOCAL_FILE,
          "Atomically export one frozen, redacted host-observed event snapshot.",
          status=OperationStatus.PARTIAL, menu_enabled=True),
    _spec("session_log.export_csv", "Export Session Log… · LOCAL CSV",
          OperationRisk.LOCAL_FILE,
          "Atomically export the same bounded host-observed event model as CSV.",
          status=OperationStatus.PARTIAL, menu_enabled=True),

    # Visible placeholders keep EAS parity gaps explicit instead of guessing.
    _spec("eas.native_files", "EAS native setup import/export · NEED-DATA",
          OperationRisk.NEED_DATA,
          "The EAS native file schema and atomic recovery contract are unknown.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.tool_organizer.native_persistence",
          "EAS-native Tool Organizer persistence · NEED-DATA",
          OperationRisk.NEED_DATA,
          "The EAS Tool Organizer storage path, schema and recovery contract are unknown.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.status_monitor.live_polling",
          "Full EAS Status Monitor polling · NEED-DATA",
          OperationRisk.DRIVE_READ,
          "True EAS 0.5 s polling, arbitrary signals/arrays, multi-target "
          "selection, user units, gauge and Quick Watch remain unimplemented.",
          gates=_STATUS_MONITOR_POLL, status=OperationStatus.NEED_DATA),
    _spec("eas.status_monitor.native_config",
          "EAS Status Monitor .smc import/export · NEED-DATA",
          OperationRisk.LOCAL_FILE,
          "The native schema and recovery contract are unknown; installed "
          "help conflicts on .smc/.sac for Append.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.multiaxis", "Motion – Multiple Axes · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Clocking, partial failure and coordinated stop contracts are missing.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.floating_terminal", "Floating Terminal · NEED-DATA",
          OperationRisk.NEED_DATA,
          "An unrestricted command terminal would bypass the command allowlist.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.fault_log", "Full EAS Fault/Ack/Clear Manager · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Drive history, fault taxonomy, acknowledge/clear and recovery semantics are incomplete.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.system_config.manage",
          "System Configuration Add/Remove/Edit · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Drive/device/group/I/O/virtual-axis side effects and rollback are not frozen.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.single_axis.digital_io",
          "Single Axis Digital In/Out · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Signal mapping, polarity, freshness and output-write rollback are not frozen.",
          status=OperationStatus.NEED_DATA),
    _spec("axis.drive_mode.change",
          "Single Axis Drive Mode Change · NEED-DATA",
          OperationRisk.NEED_DATA,
          "UM is non-volatile and the installed Gold reference requires the "
          "motor off; verified disabled/stationary state, exact readback, "
          "persistence recovery, and rollback authority are not frozen.",
          status=OperationStatus.NEED_DATA),
    _spec("axis.current_reference.command",
          "Single Axis Current Reference Command · NEED-DATA",
          OperationRisk.ENERGIZING,
          "TC assignment requires MO=1 and SO=1, immediately forces the "
          "current loop, and remains locked until an independent current/"
          "thermal/torque envelope, watchdog, abort, and software STOP "
          "(ST) -> MO=0 closeout contract are verified.",
          status=OperationStatus.NEED_DATA),
    _spec("axis.position_velocity_reference.command",
          "Single Axis Position / Velocity Command - NEED-DATA",
          OperationRisk.MOTION,
          "PA/PR/JV assignment and BG execution require MO=1 and observed "
          "SO=1. They remain locked until units and direction, travel/speed/"
          "acceleration limits, restrained load, watchdog, independent "
          "abort, exact readback, and software STOP (ST) -> MO=0 closeout "
          "are verified.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.single_axis.manual_references",
          "Single Axis Current/Stepper/Sine References · NEED-DATA",
          OperationRisk.NEED_DATA,
          "Mode-specific energy bounds, watchdogs and closeout contracts are missing.",
          status=OperationStatus.NEED_DATA),
    _spec("eas.single_axis.terminal",
          "Single Axis Terminal/Command Reference · NEED-DATA",
          OperationRisk.NEED_DATA,
          "An unrestricted terminal would bypass the operation catalog and command allowlist.",
          status=OperationStatus.NEED_DATA),

    # Hardware-bound controls.  The emergency STOP is intentionally special:
    # it must remain callable when telemetry is stale, so it does not require
    # the ordinary fresh-telemetry admission gate.
    _spec("drive.stop", "DRIVE STOP · ST → MO=0",
          OperationRisk.SAFETY_STOP,
          "Software stop/disable with terminal readback; not independent STO.",
          gates=("connected_transport", "terminal_readback")),
    _spec("axis.refresh", "Refresh Axis Summary",
          OperationRisk.DRIVE_READ,
          "Query the current drive identity-bound axis configuration.",
          gates=_IDENTITY_FRESH),
    _spec("session.zero", "Set Session Zero · PX=0",
          OperationRisk.RAM_WRITE,
          "Write only the volatile session coordinate and verify PX readback.",
          gates=_SCOPED_MUTATION | frozenset(("coordinate_authority",))),
    _spec("motor.enable", "Enable motor - LOCKED / NEED-DATA",
          OperationRisk.ENERGIZING,
          "Executable MO=1 remains locked and NEED-DATA until SO=1 "
          "completion semantics, a bounded current envelope, independent "
          "protection, operator authority, telemetry aborts, and verified "
          "closeout are commissioned.",
          status=OperationStatus.NEED_DATA),
    _spec("motor.save", "Save Motor Profile · SV",
          OperationRisk.PERSISTENT_WRITE,
          "Persist the verified full motor profile once.", gates=_PERSIST),
    _spec("feedback.encoder_maintenance", "Encoder Maintenance",
          OperationRisk.PERSISTENT_WRITE,
          "Change the encoder datum through the documented maintenance command.",
          gates=_PERSIST | frozenset(("encoder_reconnect_latch",))),
    _spec("tuning.p1.run", "Run Phase 1 · Current",
          OperationRisk.ENERGIZING,
          "Inject bounded current for R/L identification and current-loop design.",
          gates=_ENERGY),
    _spec("tuning.signature.run", "Run Commutation Signature",
          OperationRisk.ENERGIZING,
          "Inject bounded current to identify the commutation signature.",
          gates=_ENERGY),
    _spec("tuning.p2.run", "Run Phase 2 · Velocity / Position",
          OperationRisk.MOTION,
          "Move the rotor for plant identification and loop design.", gates=_MOTION),
    _spec("tuning.p2.verify", "Verify Installed P2 on Motor",
          OperationRisk.MOTION,
          "Run the bounded 300/900 rpm ladder for the currently installed gains under P2_LIMITS WAL.",
          gates=_MOTION | frozenset(("commutation_signature", "p2_limits_wal"))),
    _spec("tuning.p1.apply", "Apply P1 → RAM (LOCKED)", OperationRisk.RAM_WRITE,
          "Locked pending a durable pre-assignment gain-trial WAL; production rejects before drive I/O.",
          gates=_SCOPED_MUTATION | frozenset(("durable_gain_trial_wal",)),
          status=OperationStatus.NEED_DATA),
    _spec("tuning.p1.restore", "Restore P1 → Original", OperationRisk.RAM_WRITE,
          "Restore the frozen current-loop rollback set and verify it.",
          gates=_SCOPED_MUTATION | frozenset(("trial_capability",))),
    _spec("tuning.p1.save", "Save P1 → SV (LOCKED)",
          OperationRisk.PERSISTENT_WRITE,
          "Locked pending a durable pre-assignment gain-trial WAL and session-bound P1 verifier.",
          gates=_PERSIST | frozenset(("durable_gain_trial_wal", "verified_trial_capability")),
          status=OperationStatus.NEED_DATA),
    _spec("tuning.p2.apply", "Apply P2 → RAM (LOCKED)", OperationRisk.RAM_WRITE,
          "Locked pending a durable pre-assignment gain-trial WAL; production rejects before drive I/O.",
          gates=_SCOPED_MUTATION | frozenset(("durable_gain_trial_wal",)),
          status=OperationStatus.NEED_DATA),
    _spec("tuning.p2.restore", "Restore P2 → Original", OperationRisk.RAM_WRITE,
          "Restore the frozen velocity/position rollback set and verify it.",
          gates=_SCOPED_MUTATION | frozenset(("trial_capability",))),
    _spec("tuning.p2.save", "Save P2 → SV (LOCKED)",
          OperationRisk.PERSISTENT_WRITE,
          "Locked pending a durable pre-assignment gain-trial WAL for an exact verified P2 trial.",
          gates=_PERSIST | frozenset(("durable_gain_trial_wal", "verified_trial_capability")),
          status=OperationStatus.NEED_DATA),
    _spec("motion.ptp.run", "Run finite PTP move", OperationRisk.MOTION,
          "The offline finite-PTP kernel is implemented, but live execution "
          "remains locked until an identity-bound commissioning envelope is "
          "supplied and validated.",
          gates=_MOTION, status=OperationStatus.NEED_DATA),
    _spec("recorder.immediate", "Recorder Immediate",
          OperationRisk.DRIVE_STATE,
          "Configure and arm one finite Immediate recorder capture.",
          gates=_IDENTITY_FRESH | frozenset((
              "explicit_scope", "motor_disabled", "terminal_readback"))),
    _spec("recorder.upload", "Upload Recorder Buffer",
          OperationRisk.DRIVE_STATE,
          "Transfer the exact completed recorder buffer to the host.",
          gates=_IDENTITY_FRESH | frozenset((
              "explicit_scope", "motor_disabled", "terminal_readback"))),
    _spec("recorder.stop", "Recorder Stop",
          OperationRisk.DRIVE_STATE,
          "Stop recorder ownership only; this does not stop the motor.",
          gates=_IDENTITY_FRESH | frozenset((
              "explicit_scope", "motor_disabled", "terminal_readback"))),
)


OPERATIONS = MappingProxyType({spec.operation_id: spec for spec in _SPECS})
if len(OPERATIONS) != len(_SPECS):
    raise RuntimeError("duplicate operation id in operation catalog")


# SAFETY_STOP changes the drive, but is deliberately excluded because stale
# telemetry must never suppress the emergency stop path.
DRIVE_MUTATING_RISKS = frozenset((
    OperationRisk.DRIVE_STATE,
    OperationRisk.RAM_WRITE,
    OperationRisk.ENERGIZING,
    OperationRisk.MOTION,
    OperationRisk.PERSISTENT_WRITE,
))


TOP_MENU_OPERATIONS = MappingProxyType({
    "File": (
        "ui.tool_organizer",
        "recorder.workspace.open", "recorder.workspace.save",
        "recorder.workspace.save_as", "session_log.export_json",
        "session_log.export_csv", "eas.native_files",
        "eas.status_monitor.native_config",
        "eas.tool_organizer.native_persistence"),
    "Parameters": (
        "nav.tuning.quick", "nav.tuning.expert", "nav.motor",
        "nav.feedback", "nav.axis"),
    "Tools": (
        "nav.system_config", "nav.motion", "nav.recorder", "nav.session_log",
        "eas.system_config.manage", "eas.multiaxis"),
    "Views": (
        "nav.system_config", "nav.motion", "nav.motor", "nav.feedback",
        "nav.tuning.quick", "nav.axis", "nav.recorder", "nav.session_log"),
    "Floating Tools": (
        "ui.status_monitor", "ui.capability_guide", "nav.session_log",
        "eas.status_monitor.live_polling",
        "eas.floating_terminal", "eas.fault_log"),
})


_RISK_BADGES = MappingProxyType({
    OperationRisk.LOCAL_UI: "LOCAL UI",
    OperationRisk.LOCAL_FILE: "LOCAL FILE",
    OperationRisk.DRIVE_READ: "DRIVE READ",
    OperationRisk.DRIVE_STATE: "DRIVE STATE",
    OperationRisk.RAM_WRITE: "RAM WRITE",
    OperationRisk.ENERGIZING: "ENERGIZES",
    OperationRisk.MOTION: "MOTION",
    OperationRisk.PERSISTENT_WRITE: "PERSIST / SV",
    OperationRisk.SAFETY_STOP: "SAFETY STOP",
    OperationRisk.NEED_DATA: "NEED-DATA",
})


def operation_spec(operation_id: str) -> OperationSpec:
    try:
        return OPERATIONS[str(operation_id)]
    except KeyError as exc:
        raise KeyError("unknown operation id %r" % operation_id) from exc


def risk_badge(operation_id: str) -> str:
    return _RISK_BADGES[operation_spec(operation_id).risk]


def operation_tooltip(operation_id: str) -> str:
    spec = operation_spec(operation_id)
    gates = ", ".join(sorted(spec.gates)) if spec.gates else "none"
    return "[%s] %s\nGates: %s" % (
        _RISK_BADGES[spec.risk], spec.summary, gates)
