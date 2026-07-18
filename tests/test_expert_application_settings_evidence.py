"""Pure contracts for the Expert Application Settings evidence inspector."""

from __future__ import annotations

import builtins
from dataclasses import FrozenInstanceError
import hashlib
import importlib
import socket
import subprocess
import sys

import pytest

import expert_application_settings_evidence as evidence


EXPECTED_CONFLICTS = (
    "VH_INDEX_RANGE_CONFLICT: MAN-G-CR attributes list VH[N] index range as "
    "N=2,3, while the same page defines VH[1] in Range, Remarks, and Indices; "
    "VH[1] default is not stated.",
    "IF_INDEX_SCOPE_CONFLICT: MAN-G-CR attributes list IF[N] index range "
    "1..16, while the Indices table lists 1..6; the page also says hardware "
    "is typically six inputs and unsupported indices may be accepted but "
    "ignored.",
    "OL_RANGE_CONFLICT: MAN-G-CR attributes state OL[N] range 0..9, while "
    "Possible Values defines OL[N]=10/11 for Target Reached.",
    "GO_INDEX_RANGE_CONFLICT: MAN-G-CR attributes state GO[14]..GO[15] range "
    "0..8, while the same page defines indices and behavior for GO[14]..GO[16].",
    "PORT_C_FUNCTION_CONFLICT: EAS section 8.2.7.3 lists Gantry and Daisy "
    "Chain choices for Port C, while MAN-G-CR v2.001 marks GO value 6 reserved "
    "and documents value 8 as absolute-sensor buffering; no exact EAS-to-"
    "command mapping is stated.",
    "OUTPUT_COMMAND_LABEL_CONFLICT: EAS section 8.2.7.3 says output functions "
    "use command IL, but the rows themselves use OL[N] and GO[N]; treat IL as "
    "a documentation typo, not an output mapping.",
    "HOME_INPUT_SCOPE_CONFLICT: EAS section 8.2.7.3 limits Home/Auxiliary Home "
    "selection by inputs 1..6 and WS[8], while MAN-G-CR IL[N] describes RevC "
    "input 5 only versus RevE any input via GI[N]; exact B01G hardware "
    "revision is not documented.",
    "IL_DEFAULT_CONFLICT: MAN-G-CR v2.001 states inputs 1..6 default to IL=7 "
    "and inputs 8..16 to IL=5, omitting input 7; firmware release notes state "
    "IL[6] and IL[7] defaults changed from General Purpose to Ignore in "
    "01.01.08.00.",
    "LEGACY_SOURCE_DRIFT: workspace MAN-G-CR v1.406 (2013) differs from "
    "installed MAN-G-CR v2.001 (2024) for GO/IL capabilities; legacy values "
    "are comparison-only and must not override installed NetHelp.",
)


EXPECTED_WARNINGS = (
    "DOCUMENTED_MAP_ONLY: The catalog is a frozen local documentation map, "
    "not current drive configuration, factory defaults for this unit, live "
    "I/O state, protection status, or a safety assessment.",
    "NO_RUNTIME_IO: Opening or changing sections must not connect, query, "
    "dispatch, read, write, apply, save, generate commands, or move hardware.",
    "BRAKE_OUTPUT_NEED_DATA: Exact Gold Twitter B01G output count, electrical "
    "rating, brake-current capability, polarity, external relay/flyback, "
    "wiring, coil data, and fail-safe behavior are not established.",
    "BRAKE_IS_NOT_STO: Logical/mechanical/dynamic brake behavior is not STO, "
    "an E-stop, or an independent safe stop; a fault can remove servo control "
    "before mechanical brake engagement completes.",
    "DYNAMIC_BRAKE_CONDITIONS: VH[1]=0 disables dynamic braking; feedback "
    "availability, motor type, dual-loop units, and no-sensor conditions "
    "affect behavior and can endanger the drive.",
    "BP_TRANSITION_TIMING: BP[1] applies on the next motor-off, BP[2] on the "
    "next motor-on, brake-output response resolution is 250 us, and profiler/"
    "auxiliary references are ignored during BP[2].",
    "SETTLING_IS_NOT_ACCURACY_OR_SAFETY: TR[1]..TR[4] only define Target "
    "Reached timing/window criteria; they do not prove positioning accuracy, "
    "stability, or safe operation.",
    "TR_RAW_UNITS: TR position and velocity windows are counts and counts/sec "
    "while linked CANopen objects use user units; no user-unit conversion or "
    "propagation is authorized.",
    "LIVE_STATUS_EXCLUDED: Input/output bulbs and IP/IB/OP/OB values are live "
    "state and must remain explicitly unavailable in a local no-I/O inspector.",
    "INPUT_ACTION_RISK: IL mappings can enable motion, begin motion, engage "
    "references, controlled-stop, or freewheel; Inhibit/Abort/Hard/Soft Stop "
    "are not interchangeable with STO.",
    "TIME_BASED_MODE_RISK: In CSP/IP modes, hard-stop and limit behavior "
    "depends on XA[4]; releasing a switch with mismatched host setpoint can "
    "resume or jump motion.",
    "FILTER_LIMITATION: IF[N] is quantized by firmware, hardware capture "
    "ignores the software filter, and unsupported hardware indices may be "
    "accepted but ignored.",
    "OUTPUT_ROUTING_RISK: GO/OL routing is hardware-dependent; Port C coupled "
    "routing and mutually exclusive emulation/output functions can suppress "
    "or reroute signals.",
    "STO_INDICATION_ONLY: GO[N]=7 is an STO status indication output, not STO "
    "actuation and not evidence that the machine is safe.",
    "B01G_APPLICABILITY_NEED_DATA: Installed 2024 Gold-line documents and a "
    "01.01.16.00 B01 release-note entry do not prove exact behavior of the "
    "reported 08Mar2020B01G build/personality.",
    "DOCUMENT_DEFAULT_NOT_CURRENT: Any documented default is reference text "
    "only; it must never be labeled current, installed, read back, or B01G "
    "factory default.",
)


EXPECTED_MISSING = (
    "Exact Gold Twitter orderable part number, CAN/EtherCAT variant, power "
    "rating, hardware revision, personality, and B01G delta/change record.",
    "Product-specific installation-guide pages for digital output count, "
    "pinout, voltage/current ratings, brake-current source, protection, and "
    "connector wiring.",
    "Brake manufacturer/coil voltage/current, release/engage time, relay/"
    "flyback, polarity, load holding and fail-safe data.",
    "Current drive values for OL[N], BP[1..2], VH[1], TR[1..4], IL[N], IF[N], "
    "GO[N], OP/IP/IB; intentionally not read.",
    "Actual operating mode, sensor topology, XA[4], WS[8], motor/servo state, "
    "I/O levels, and EAS page availability.",
    "Field verification of brake timing, target-reached behavior, I/O "
    "polarity/function, STO chain, stopping distance, and fault response.",
)


def test_snapshot_is_canonical_frozen_deterministic_and_has_exact_shape():
    first = evidence.build_evidence_snapshot()
    second = evidence.build_evidence_snapshot()

    assert first is second
    assert first.authority == "DOCUMENTED_APPLICATION_SETTINGS_MAP_ONLY"
    assert first.model_status == "PARTIAL_NEED_DATA"
    assert tuple(section.key for section in first.sections) == (
        "brake",
        "settling_window",
        "inputs_outputs",
    )
    assert tuple(len(section.parameters) for section in first.sections) == (
        4,
        4,
        5,
    )
    assert sum(len(section.parameters) for section in first.sections) == 13
    with pytest.raises(FrozenInstanceError):
        first.authority = "CURRENT_DRIVE_CONFIG"
    with pytest.raises(FrozenInstanceError):
        first.sections[0].parameters[0].command = "OL[1]"


def test_section_and_parameter_order_preserve_documented_application_map():
    brake = evidence.section_evidence("brake")
    settling = evidence.section_evidence("settling_window")
    io_map = evidence.section_evidence("inputs_outputs")

    assert tuple(item.key for item in brake.parameters) == (
        "brake_output_assignment",
        "bp1",
        "bp2",
        "vh1",
    )
    assert tuple(item.command for item in brake.parameters) == (
        "OL[N]",
        "BP[1]",
        "BP[2]",
        "VH[1]",
    )
    assert tuple(item.command for item in settling.parameters) == (
        "TR[1]",
        "TR[2]",
        "TR[3]",
        "TR[4]",
    )
    assert tuple(item.command for item in io_map.parameters) == (
        "IL[N]",
        "IF[N]",
        "IP + IB[N]",
        "OL[N]",
        "GO[N] + OP",
    )

    assignment = brake.parameters[0]
    assert "4" in assignment.documented_effect
    assert "5" in assignment.documented_effect
    assert "Using Brake" in assignment.condition
    assert assignment.evidence_status == "HARDWARE_DEPENDENT"
    assert all(
        "document:" in item.access
        and "app: inspect-only" in item.access
        for section in evidence.build_evidence_snapshot().sections
        for item in section.parameters
    )


def test_boundary_and_capabilities_fail_closed():
    snapshot = evidence.build_evidence_snapshot()
    boundary = snapshot.boundary.upper()

    for phrase in (
        "STATIC DOCUMENT MAP ONLY",
        "PARTIAL / NEED-DATA",
        "NOT CURRENT DRIVE CONFIG",
        "NOT CURRENT I/O STATE",
        "NOT BRAKE OR SAFETY EVIDENCE",
        "NO DRIVE READ",
        "NO VALIDATION/EVALUATION",
        "NO COMMAND",
        "NO WRITE",
        "NO APPLY/REVERT/SV",
        "NO OUTPUT ACTUATION",
        "NO MOTION",
        "NO DRIVE I/O",
    ):
        assert phrase in boundary

    assert snapshot.can_inspect is True
    for capability in (
        "can_read_drive",
        "can_validate",
        "can_evaluate",
        "can_generate_commands",
        "can_write",
        "can_apply",
        "can_revert",
        "can_persist",
        "can_actuate_outputs",
        "can_move",
        "can_claim_safety",
    ):
        assert getattr(snapshot, capability) is False


def test_conflicts_and_warnings_are_exact_and_digest_locked():
    snapshot = evidence.build_evidence_snapshot()

    assert snapshot.document_conflicts == EXPECTED_CONFLICTS
    assert snapshot.persistent_warnings == EXPECTED_WARNINGS
    assert snapshot.missing_evidence == EXPECTED_MISSING
    conflicts = "\n".join(snapshot.document_conflicts)
    warnings = "\n".join(snapshot.persistent_warnings)
    missing = "\n".join(snapshot.missing_evidence)
    assert hashlib.sha256(conflicts.encode()).hexdigest() == (
        "6d687c62e1d2ec530bc6b129dc11eb280e46bf0ba10fb1eaaa93f4871d6fd01e"
    )
    assert hashlib.sha256(warnings.encode()).hexdigest() == (
        "6a3ede35ef5782ad9d31099c4062f57fcc8f0d2b11fdf47ac179169ab1817a95"
    )
    assert hashlib.sha256(missing.encode()).hexdigest() == (
        "f9688d0169a48ed1582363a1024518a209304190ad230ec6a89dad4019b58aaf"
    )

    combined = " ".join((
        snapshot.boundary,
        *snapshot.document_conflicts,
        *snapshot.missing_evidence,
        *snapshot.persistent_warnings,
        *(
            value
            for section in snapshot.sections
            for item in section.parameters
            for value in (
                item.label,
                item.command,
                item.documented_unit,
                item.access,
                item.documented_effect,
                item.condition,
                item.evidence_status,
            )
        ),
    )).upper()
    for forbidden in (
        "BRAKE IS SAFE",
        "VALIDATED SAFE",
        "CURRENT DRIVE IS",
        "CURRENT I/O IS",
        "RECOMMENDED VALUE",
        "APP: R/W",
        "OUTPUT ACTUATED",
    ):
        assert forbidden not in combined


def test_source_identity_is_exact_and_complete():
    sources = {
        source.key: source.sha256
        for source in evidence.build_evidence_snapshot().sources
    }

    assert sources == {
        "eassg_root": (
            "87FC7B5904C712748BA7B22361690CB9977D4C0994607E32840C1E4ABBB93864"
        ),
        "app_settings_html": (
            "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
        ),
        "brake_img72": (
            "1F9AC24B682B666B19A184618CCB9EB2B43B5A7D7BEB3DFD423464DA07D4CC45"
        ),
        "settling_img73": (
            "FE90AC9D8A3CD3416DDEE6A59083D0A4B7C0EE0933B569CE25AB7B83B092C4D6"
        ),
        "io_img74": (
            "8DD5E4F1232A607EECE43612543F72FE2763C14D84C0500722A3124B523ECD8F"
        ),
        "man_g_cr_root": (
            "6141445EEC7C53BDFB8CD3E65FB1BC780813C784CBBECDB1DF8A5A91C4C54E6A"
        ),
        "attributes": (
            "599A94FEBFECDBE05F9099A1C51B760B708B35D445286F6339B87A867FAA7F35"
        ),
        "bp": (
            "590F4D17B6C03F944E34EE2C60FB30BCF335315785409003D942F8AB084D6C7F"
        ),
        "tr": (
            "E67F57644C8B1A80E387066101F79CCA1EC0A44531C71A65A905F431664C0907"
        ),
        "vh_vl": (
            "5FE1D381510E409BDD14F9F15EC98F65E48EB8A1FAEF6DFF2F112C55C5FECC06"
        ),
        "il": (
            "F5C058B8A2CE435411A8114D7BB30ADD4E640D5BBA8B14737702096BF60F99C2"
        ),
        "if": (
            "1803C3A188B45B4E0945D161211FDD04887B12727F209977C52871F4292260BA"
        ),
        "ib": (
            "A28EA3A50BB95D548CC482A325AE52B30D1AC7A841987A4644F48C6337000571"
        ),
        "ip": (
            "0594BD5A9A1B8DCC0128985747E0ED86861A917A87CB292528180B186A413336"
        ),
        "ol": (
            "F6A33CF4609B61AA31EB36F3B811387537A8208B495ACCA81CFB9A7B93331291"
        ),
        "go": (
            "4D4E7CBCE1EADBA8ED820224B441AFC370D5E264676A4AD22CC399361CE247BE"
        ),
        "op": (
            "BFDE83C2EC00D1FCD3F2A8ADA8CCF7288836DE0E510431591E8A7078EF61FDF6"
        ),
        "firmware_pdf": (
            "E2E28E5530A57ACF7CF54EF2A9249CA8FCAC5A34348DDF0F37E20A07E23758B2"
        ),
        "firmware_text": (
            "3E70090E7E9E43290A972EE96ED057AF7E4E6D74FDA92780F6AD7D47BD201719"
        ),
        "legacy_cr_pdf": (
            "89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80"
        ),
        "legacy_cr_text": (
            "55F620EA0E35812BC754FC9B4F7B6C9AF714C1041AECC0EB6DCCAEB63A44F156"
        ),
        "admin_root": (
            "CE06646F84327A602BFDAA0548A619453BB0B7D756D036D9F470ED590B135212"
        ),
        "admin_io_stub": (
            "3AF6E75BFD4DC80C2FFC4A2E5C72B41DC97DB37B7F76464AAB5FB21076C96224"
        ),
        "admin_enable_stub": (
            "E3AB1340756C00903CD97845E92854DA7B8502A3F818253816F481BFF127EDFC"
        ),
    }
    assert len(sources) == 24
    assert all(len(digest) == 64 for digest in sources.values())


def test_fresh_module_import_performs_no_application_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("evidence module import attempted application I/O")

    module_name = evidence.__name__
    previous = sys.modules.pop(module_name)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    try:
        fresh = importlib.import_module(module_name)
        assert fresh.build_evidence_snapshot().can_read_drive is False
        assert calls == []
    finally:
        sys.modules[module_name] = previous


def test_snapshot_build_and_lookup_perform_no_runtime_io(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("immutable evidence lookup attempted runtime I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)

    snapshot = evidence.build_evidence_snapshot()
    assert evidence.section_evidence("brake") is snapshot.sections[0]
    assert calls == []


@pytest.mark.parametrize("key", [None, True, 1, "", "unknown"])
def test_section_lookup_rejects_noncanonical_keys(key):
    expected = TypeError if not isinstance(key, str) or isinstance(key, bool) \
        else KeyError
    with pytest.raises(expected):
        evidence.section_evidence(key)
