"""Immutable Expert filter/scheduling documentation evidence.

This module is deliberately not a controller, filter evaluator, command
encoder, or drive interface.  It freezes only the topology that is stated in
MAN-G-CR 1.406 and preserves contradictions in that document as blockers.
"""

from __future__ import annotations

from dataclasses import dataclass


SOURCE = "Elmo MAN-G-CR 1.406 (February 2013), pp. 138-184"
SOURCE_SHA256 = (
    "55F620EA0E35812BC754FC9B4F7B6C9AF714C1041AECC0EB6DCCAEB63A44F156"
)


@dataclass(frozen=True, slots=True)
class FilterTypeEvidence:
    code: int
    name: str
    parameters: tuple[str, ...]
    exact_transfer_status: str = "NEED-DATA"


@dataclass(frozen=True, slots=True)
class FilterLocationEvidence:
    key: str
    label: str
    kv_indices: tuple[int, ...]
    type_index_candidates: tuple[int, ...]
    kg_index_ranges: tuple[tuple[int, int], ...] = ()
    gs_index: int | None = None
    status: str = "DOCUMENTED"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class KgTableEvidence:
    key: str
    label: str
    index_range: tuple[int, int]
    unit: str


@dataclass(frozen=True, slots=True)
class Gs2ModeEvidence:
    category: str
    code_min: int
    code_max: int
    description: str
    dependencies: tuple[str, ...]
    selection_algorithm_status: str = "NEED-DATA"


@dataclass(frozen=True, slots=True)
class ExpertEvidenceSnapshot:
    authority: str
    model_status: str
    source: str
    source_sha256: str
    filter_types: tuple[FilterTypeEvidence, ...]
    filter_locations: tuple[FilterLocationEvidence, ...]
    kg_tables: tuple[KgTableEvidence, ...]
    gs2_modes: tuple[Gs2ModeEvidence, ...]
    documented_facts: tuple[str, ...]
    conflicts: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    can_inspect: bool
    can_evaluate: bool
    can_emulate: bool
    can_write: bool


FILTER_TYPES = (
    FilterTypeEvidence(0, "Canceled", ()),
    FilterTypeEvidence(
        1, "Second-order low pass", ("Frequency [Hz]", "Damping")),
    FilterTypeEvidence(
        2, "First-order lead/lag", ("Frequency [Hz]", "Phase [deg]")),
    FilterTypeEvidence(
        3, "Second-order lead/lag", ("Frequency [Hz]", "Phase [deg]")),
    FilterTypeEvidence(
        4, "Notch",
        ("Frequency [Hz]", "Quality factor", "Attenuation [dB]")),
    FilterTypeEvidence(
        5, "Anti-notch",
        ("Frequency [Hz]", "Quality factor", "Amplification [dB]")),
    FilterTypeEvidence(
        6, "General bi-quad",
        (
            "Numerator frequency [Hz]",
            "Numerator damping",
            "Denominator frequency [Hz]",
            "Denominator damping",
        )),
)


FILTER_LOCATIONS = (
    FilterLocationEvidence(
        "velocity_output_1", "Velocity controller output · Filter 1",
        tuple(range(1, 6)), (5,)),
    FilterLocationEvidence(
        "velocity_output_2", "Velocity controller output · Filter 2",
        tuple(range(6, 11)), (10,)),
    FilterLocationEvidence(
        "velocity_output_3", "Velocity controller output · Filter 3",
        tuple(range(11, 16)), (15,)),
    FilterLocationEvidence(
        "velocity_output_4", "Velocity controller output · Filter 4",
        tuple(range(16, 21)), (20,)),
    FilterLocationEvidence(
        "scheduled_velocity_1", "Scheduled velocity filter 1",
        (25,), (25,),
        ((190, 252), (253, 315), (316, 378), (379, 441)),
        16,
        detail="63 rows × four physical parameters; activation by KV[25]."),
    FilterLocationEvidence(
        "scheduled_velocity_2", "Scheduled velocity filter 2",
        (30,), (30,),
        ((442, 504), (505, 567), (568, 630), (631, 693)),
        17,
        detail="63 rows × four physical parameters; activation by KV[30]."),
    FilterLocationEvidence(
        "position_output_1", "Position controller output · Filter 1",
        tuple(range(31, 36)), (35,)),
    FilterLocationEvidence(
        "position_output_2", "Position controller output · Filter 2",
        tuple(range(36, 41)), (40,)),
    FilterLocationEvidence(
        "scheduled_position", "Scheduled position filter",
        (), (45, 50),
        ((694, 756), (757, 819), (820, 882), (883, 945)),
        18,
        status="DOCUMENT_CONFLICT",
        detail=(
            "KV table/notes identify KV[45]; GS and KG sections identify "
            "KV[50]. No activation index is selected."
        )),
)


KG_TABLES = (
    KgTableEvidence("velocity_ki", "Velocity KI", (1, 63), "Hz"),
    KgTableEvidence(
        "velocity_kp", "Velocity KP", (64, 126),
        "A/(counts/s) · peak/RMS basis not stated in this table"),
    KgTableEvidence("position_kp", "Position KP", (127, 189), "rad/s"),
    KgTableEvidence(
        "scheduled_velocity_1_p1", "Scheduled velocity filter 1 · P1",
        (190, 252), "by filter type"),
    KgTableEvidence(
        "scheduled_velocity_1_p2", "Scheduled velocity filter 1 · P2",
        (253, 315), "by filter type"),
    KgTableEvidence(
        "scheduled_velocity_1_p3", "Scheduled velocity filter 1 · P3",
        (316, 378), "by filter type"),
    KgTableEvidence(
        "scheduled_velocity_1_p4", "Scheduled velocity filter 1 · P4",
        (379, 441), "by filter type"),
    KgTableEvidence(
        "scheduled_velocity_2_p1", "Scheduled velocity filter 2 · P1",
        (442, 504), "by filter type"),
    KgTableEvidence(
        "scheduled_velocity_2_p2", "Scheduled velocity filter 2 · P2",
        (505, 567), "by filter type"),
    KgTableEvidence(
        "scheduled_velocity_2_p3", "Scheduled velocity filter 2 · P3",
        (568, 630), "by filter type"),
    KgTableEvidence(
        "scheduled_velocity_2_p4", "Scheduled velocity filter 2 · P4",
        (631, 693), "by filter type"),
    KgTableEvidence(
        "scheduled_position_p1", "Scheduled position filter · P1",
        (694, 756), "by filter type"),
    KgTableEvidence(
        "scheduled_position_p2", "Scheduled position filter · P2",
        (757, 819), "by filter type"),
    KgTableEvidence(
        "scheduled_position_p3", "Scheduled position filter · P3",
        (820, 882), "by filter type"),
    KgTableEvidence(
        "scheduled_position_p4", "Scheduled position filter · P4",
        (883, 945), "by filter type"),
)


GS2_MODES = (
    Gs2ModeEvidence(
        "DISABLED", 0, 0,
        "No gain scheduling; KP[2], KI[2], and KP[3] are active.",
        ()),
    Gs2ModeEvidence(
        "FIXED", 1, 63,
        "Use one documented controller-table index.",
        ("KG[1..189]",)),
    Gs2ModeEvidence(
        "SPEED", 64, 64,
        "Schedule by speed.",
        ("GS[1]", "GS[6]", "GS[7]", "GS[10]")),
    Gs2ModeEvidence(
        "POSITION", 65, 65,
        "Schedule by a selected position socket.",
        ("CA[65]", "GS[19]", "GS[20]")),
    Gs2ModeEvidence(
        "PROFILER", 66, 66,
        "Use controller indices 63, 62, and 61 around profiler stop.",
        ("GS[1]", "GS[11]")),
)


DOCUMENTED_FACTS = (
    "Advanced controller filters have DC gain equal to one at zero frequency.",
    "Each non-scheduled filter has four physical parameters and a fifth "
    "parameter that selects the type and enables the filter.",
    "Changing a KV filter type requires the motor off.",
)


CONFLICTS = (
    "KG attribute header states index range 1..504, but the table spans "
    "1..945.",
    "Scheduled position filter activation is KV[45] in the KV table/notes "
    "but KV[50] in the GS and KG sections.",
    "KV attribute header states index range 1..90, but the location table "
    "includes velocity-presentation filter KV[91..95].",
    "GS overview says position scheduling uses GS[18,20], while the detailed "
    "entries identify GS[19] and GS[20] as the position boundaries.",
    "GS speed-scheduling overview lists GS[1,6,8,10] and the GS[1] text "
    "assigns maximum speed to GS[8], while the detailed table assigns maximum "
    "speed to GS[6], speed source to GS[7], and marks GS[8] Reserved.",
)


MISSING_EVIDENCE = (
    "SimplIQ Software Manual §15.4 gain-scheduling algorithm is not present "
    "in the repository evidence set.",
    "Current Gold Twitter B01G firmware parity with MAN-G-CR 1.406 has not "
    "been established.",
    "Exact transfer equations, discretization/prewarp, legal numeric ranges, "
    "cascade order, quantization, saturation, and anti-windup are not fixed.",
    "Speed/position table interpolation and boundary behavior are not fixed.",
)


_SNAPSHOT = ExpertEvidenceSnapshot(
    authority="DOCUMENTED_TOPOLOGY_ONLY",
    model_status="NEED-DATA",
    source=SOURCE,
    source_sha256=SOURCE_SHA256,
    filter_types=FILTER_TYPES,
    filter_locations=FILTER_LOCATIONS,
    kg_tables=KG_TABLES,
    gs2_modes=GS2_MODES,
    documented_facts=DOCUMENTED_FACTS,
    conflicts=CONFLICTS,
    missing_evidence=MISSING_EVIDENCE,
    can_inspect=True,
    can_evaluate=False,
    can_emulate=False,
    can_write=False,
)


def build_evidence_snapshot() -> ExpertEvidenceSnapshot:
    """Return the immutable, I/O-free documentation snapshot."""
    return _SNAPSHOT


def filter_type_evidence(code: int) -> FilterTypeEvidence:
    """Return a documented type description without evaluating a filter."""
    if type(code) is not int:
        raise TypeError("filter type must be an integer")
    for item in FILTER_TYPES:
        if item.code == code:
            return item
    raise ValueError("filter type must be in 0..6")


def filter_location_evidence(key: str) -> FilterLocationEvidence:
    """Return one immutable controller-filter slot description."""
    if not isinstance(key, str):
        raise TypeError("filter location key must be text")
    for item in FILTER_LOCATIONS:
        if item.key == key:
            return item
    raise ValueError("unknown filter location %r" % key)


def classify_gs2_mode(value: int) -> Gs2ModeEvidence:
    """Classify GS[2] by documented mode only; never choose table gains."""
    if type(value) is not int:
        raise TypeError("GS[2] must be an integer")
    if value < 0 or value > 66:
        raise ValueError("GS[2] must be in 0..66")
    for item in GS2_MODES:
        if item.code_min <= value <= item.code_max:
            return item
    raise AssertionError("unreachable GS[2] classification")


__all__ = [
    "ExpertEvidenceSnapshot",
    "FilterLocationEvidence",
    "FilterTypeEvidence",
    "Gs2ModeEvidence",
    "KgTableEvidence",
    "build_evidence_snapshot",
    "classify_gs2_mode",
    "filter_location_evidence",
    "filter_type_evidence",
]
