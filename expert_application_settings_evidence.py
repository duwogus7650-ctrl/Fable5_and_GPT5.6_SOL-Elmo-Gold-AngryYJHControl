"""Immutable documentation evidence for Expert Application Settings.

This module is a frozen local catalog.  It does not inspect a drive, sample
I/O, validate a brake, generate a command, actuate an output, or move
hardware.  Source identities and normalized documentation facts are constants
so import, build, and lookup perform no file, process, network, worker, or
drive I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


MODEL_ID = "expert_application_settings_documented_map_v0_1"
BOUNDARY = (
    "STATIC DOCUMENT MAP ONLY · DOCUMENTED APPLICATION SETTINGS MAP · "
    "PARTIAL / NEED-DATA · NOT CURRENT DRIVE CONFIG · "
    "NOT CURRENT I/O STATE · NOT BRAKE OR SAFETY EVIDENCE · "
    "NO DRIVE READ · NO VALIDATION/EVALUATION · NO COMMAND · NO WRITE · "
    "NO APPLY/REVERT/SV · NO OUTPUT ACTUATION · NO MOTION · NO DRIVE I/O"
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DocumentedApplicationParameter:
    key: str
    label: str
    command: str
    documented_unit: str
    access: str
    documented_effect: str
    condition: str
    evidence_status: str = "DOCUMENTED"


@dataclass(frozen=True, slots=True)
class DocumentedApplicationSection:
    key: str
    label: str
    reference: str
    parameters: tuple[DocumentedApplicationParameter, ...]


@dataclass(frozen=True, slots=True)
class ApplicationSettingsSnapshot:
    model_id: str
    authority: str
    model_status: str
    fidelity: str
    boundary: str
    sections: tuple[DocumentedApplicationSection, ...]
    document_conflicts: tuple[str, ...]
    persistent_warnings: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    sources: tuple[DocumentSource, ...]
    can_inspect: bool
    can_read_drive: bool
    can_validate: bool
    can_evaluate: bool
    can_generate_commands: bool
    can_write: bool
    can_apply: bool
    can_revert: bool
    can_persist: bool
    can_actuate_outputs: bool
    can_move: bool
    can_claim_safety: bool


_EAS_ROOT = (
    r"C:\Program Files\Elmo Motion Control\Elmo Application Studio III"
    r"\NetHelp\Content"
)
_EAS_UM_ROOT = _EAS_ROOT + r"\EAS_II_SimplIQ_Gold_UM"
_EAS_IMAGE_ROOT = _EAS_ROOT + r"\Resources\Images\EAS_II_SimplIQ_Gold_UM"
_COMMAND_ROOT = _EAS_ROOT + r"\Gold Line Command Reference"
_ADMIN_ROOT = _EAS_ROOT + r"\Gold Administrative Software Manual"


SOURCES = (
    DocumentSource(
        "eassg_root",
        _EAS_UM_ROOT + r"\EAS_II_SimplIQ_Gold_UM.htm",
        "87FC7B5904C712748BA7B22361690CB9977D4C0994607E32840C1E4ABBB93864",
    ),
    DocumentSource(
        "app_settings_html",
        _EAS_UM_ROOT + r"\Drive Setup and Motion Activities.htm",
        "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE",
    ),
    DocumentSource(
        "brake_img72",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_72.png",
        "1F9AC24B682B666B19A184618CCB9EB2B43B5A7D7BEB3DFD423464DA07D4CC45",
    ),
    DocumentSource(
        "settling_img73",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_73.png",
        "FE90AC9D8A3CD3416DDEE6A59083D0A4B7C0EE0933B569CE25AB7B83B092C4D6",
    ),
    DocumentSource(
        "io_img74",
        _EAS_IMAGE_ROOT + r"\Drive Setup and Motion Activities_74.png",
        "8DD5E4F1232A607EECE43612543F72FE2763C14D84C0500722A3124B523ECD8F",
    ),
    DocumentSource(
        "man_g_cr_root",
        _COMMAND_ROOT + r"\MAN-G-CR.htm",
        "6141445EEC7C53BDFB8CD3E65FB1BC780813C784CBBECDB1DF8A5A91C4C54E6A",
    ),
    DocumentSource(
        "attributes",
        _COMMAND_ROOT + r"\Description of Attributes.htm",
        "599A94FEBFECDBE05F9099A1C51B760B708B35D445286F6339B87A867FAA7F35",
    ),
    DocumentSource(
        "bp",
        _COMMAND_ROOT + r"\BP Brake Parameters.htm",
        "590F4D17B6C03F944E34EE2C60FB30BCF335315785409003D942F8AB084D6C7F",
    ),
    DocumentSource(
        "tr",
        _COMMAND_ROOT + r"\TR Target Radius.htm",
        "E67F57644C8B1A80E387066101F79CCA1EC0A44531C71A65A905F431664C0907",
    ),
    DocumentSource(
        "vh_vl",
        _COMMAND_ROOT + r"\VH VL High Low Reference Limit.htm",
        "5FE1D381510E409BDD14F9F15EC98F65E48EB8A1FAEF6DFF2F112C55C5FECC06",
    ),
    DocumentSource(
        "il",
        _COMMAND_ROOT + r"\IL Digital Input Logic.htm",
        "F5C058B8A2CE435411A8114D7BB30ADD4E640D5BBA8B14737702096BF60F99C2",
    ),
    DocumentSource(
        "if",
        _COMMAND_ROOT + r"\IF Digital Input Filter.htm",
        "1803C3A188B45B4E0945D161211FDD04887B12727F209977C52871F4292260BA",
    ),
    DocumentSource(
        "ib",
        _COMMAND_ROOT + r"\IB Digital Input Bits.htm",
        "A28EA3A50BB95D548CC482A325AE52B30D1AC7A841987A4644F48C6337000571",
    ),
    DocumentSource(
        "ip",
        _COMMAND_ROOT + r"\IP Input Port.htm",
        "0594BD5A9A1B8DCC0128985747E0ED86861A917A87CB292528180B186A413336",
    ),
    DocumentSource(
        "ol",
        _COMMAND_ROOT + r"\OL Output Logic.htm",
        "F6A33CF4609B61AA31EB36F3B811387537A8208B495ACCA81CFB9A7B93331291",
    ),
    DocumentSource(
        "go",
        _COMMAND_ROOT + r"\GO Digital Output Source.htm",
        "4D4E7CBCE1EADBA8ED820224B441AFC370D5E264676A4AD22CC399361CE247BE",
    ),
    DocumentSource(
        "op",
        _COMMAND_ROOT + r"\OP Output Port.htm",
        "BFDE83C2EC00D1FCD3F2A8ADA8CCF7288836DE0E510431591E8A7078EF61FDF6",
    ),
    DocumentSource(
        "firmware_pdf",
        r"vendor\elmo-downloads\Elmo Gold Drive Firmware Release Notes "
        r"Version 01.02.18.00 B00 Ver.1.019.pdf",
        "E2E28E5530A57ACF7CF54EF2A9249CA8FCAC5A34348DDF0F37E20A07E23758B2",
    ),
    DocumentSource(
        "firmware_text",
        r"docs\firmware-release-notes.txt",
        "3E70090E7E9E43290A972EE96ED057AF7E4E6D74FDA92780F6AD7D47BD201719",
    ),
    DocumentSource(
        "legacy_cr_pdf",
        r"docs\man-g-cr_GoldLine_CommandReference.pdf",
        "89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80",
    ),
    DocumentSource(
        "legacy_cr_text",
        r"docs\command-reference.txt",
        "55F620EA0E35812BC754FC9B4F7B6C9AF714C1041AECC0EB6DCCAEB63A44F156",
    ),
    DocumentSource(
        "admin_root",
        _ADMIN_ROOT + r"\MAN-G-ADMING.htm",
        "CE06646F84327A602BFDAA0548A619453BB0B7D756D036D9F470ED590B135212",
    ),
    DocumentSource(
        "admin_io_stub",
        _ADMIN_ROOT + r"\Digital Inputs and Outputs.htm",
        "3AF6E75BFD4DC80C2FFC4A2E5C72B41DC97DB37B7F76464AAB5FB21076C96224",
    ),
    DocumentSource(
        "admin_enable_stub",
        _ADMIN_ROOT + r"\Enabling a Motor.htm",
        "E3AB1340756C00903CD97845E92854DA7B8502A3F818253816F481BFF127EDFC",
    ),
)


def _parameter(
        key: str,
        label: str,
        command: str,
        unit: str,
        document_access: str,
        role: str,
        condition: str,
        status: str = "DOCUMENTED",
) -> DocumentedApplicationParameter:
    return DocumentedApplicationParameter(
        key=key,
        label=label,
        command=command,
        documented_unit=unit,
        access=(
            "document: %s · app: inspect-only" % document_access
        ),
        documented_effect=role,
        condition=condition,
        evidence_status=status,
    )


BRAKE = DocumentedApplicationSection(
    key="brake",
    label="Brake",
    reference="EAS III §8.2.7.1",
    parameters=(
        _parameter(
            "brake_output_assignment",
            "Output Brake Assignment",
            "OL[N]",
            "none",
            "R/W · non-volatile",
            "Documented mapping: 4 active-low; 5 active-high. "
            "Reference only; not current.",
            "Visible in EAS only when Using Brake is selected; actual "
            "supported outputs and electrical capability are hardware-"
            "dependent.",
            "HARDWARE_DEPENDENT",
        ),
        _parameter(
            "bp1",
            "Brake Engage Time",
            "BP[1]",
            "ms",
            "R/W · non-volatile",
            "Documented range 0..1000; documented reference 0 · NOT CURRENT.",
            "Requires an OL[N] brake output; takes effect on the next "
            "motor-off.",
        ),
        _parameter(
            "bp2",
            "Brake Release Time",
            "BP[2]",
            "ms",
            "R/W · non-volatile",
            "Documented range 0..1000; documented reference 0 · NOT CURRENT.",
            "Requires an OL[N] brake output; takes effect on the next "
            "motor-on.",
        ),
        _parameter(
            "vh1",
            "Dynamic Brake Speed Threshold",
            "VH[1]",
            "counts/sec",
            "R/W · non-volatile",
            "Documented range 0..2^31-1; reference not stated · NOT CURRENT.",
            "0 disables dynamic braking; command-reference index metadata "
            "conflicts.",
            "DOCUMENT_CONFLICT",
        ),
    ),
)


SETTLING_WINDOW = DocumentedApplicationSection(
    key="settling_window",
    label="Settling Window",
    reference="EAS III §8.2.7.2",
    parameters=(
        _parameter(
            "tr1",
            "Target Position Window",
            "TR[1]",
            "counts",
            "R/W · non-volatile",
            "Documented range: -1 inactive; otherwise 0..2^31-1. "
            "Documented reference 100 · NOT CURRENT.",
            "Target Reached criterion only; linked object 0x6067.",
        ),
        _parameter(
            "tr2",
            "Target Position Window Time",
            "TR[2]",
            "ms",
            "R/W · non-volatile",
            "Range not stated; documented reference 20 · NOT CURRENT.",
            "Target Reached criterion only; linked object 0x6068.",
            "NEED_DATA",
        ),
        _parameter(
            "tr3",
            "Target Velocity Window",
            "TR[3]",
            "counts/sec",
            "R/W · non-volatile",
            "Range not stated; documented reference 100 · NOT CURRENT.",
            "Used with TR[4]; Target Reached criterion only; linked object "
            "0x606D.",
            "NEED_DATA",
        ),
        _parameter(
            "tr4",
            "Target Velocity Window Time",
            "TR[4]",
            "ms",
            "R/W · non-volatile",
            "Range not stated; documented reference 20 · NOT CURRENT.",
            "Used with TR[3]; Target Reached criterion only; linked object "
            "0x606E.",
            "NEED_DATA",
        ),
    ),
)


INPUTS_OUTPUTS = DocumentedApplicationSection(
    key="inputs_outputs",
    label="Inputs and Outputs",
    reference="EAS III §8.2.7.3",
    parameters=(
        _parameter(
            "il",
            "Digital Input Function / Polarity",
            "IL[N]",
            "bit field",
            "R/W · non-volatile",
            "Documented function/logic mappings; indices 1..16. "
            "Reference withheld because documents conflict · NOT CURRENT.",
            "Available inputs and Home routing depend on hardware revision "
            "and personality.",
            "DOCUMENT_CONFLICT",
        ),
        _parameter(
            "if",
            "Digital Input Filter",
            "IF[N]",
            "ms",
            "access not explicit in Type · non-volatile",
            "Documented range 0.0..500.0; documented reference 0 (no "
            "filter) · NOT CURRENT.",
            "Index scope conflicts; firmware quantizes; hardware capture "
            "ignores this software filter.",
            "DOCUMENT_CONFLICT",
        ),
        _parameter(
            "input_status",
            "Digital Input Status Semantics",
            "IP + IB[N]",
            "Boolean / bit field",
            "live semantics; IB[1..16] read-only; IB[17..32] R/W sticky-clear",
            "Documented 0/1 semantics; unavailable · not sampled.",
            "No current bulb, port, or bit value is present in this "
            "inspector.",
            "LIVE_SEMANTICS_ONLY",
        ),
        _parameter(
            "ol",
            "Digital Output Function / Polarity",
            "OL[N]",
            "bit field",
            "R/W · non-volatile",
            "Documented mapping: 0/1 General; 2/3 AOK; 4/5 Brake; 6/7 "
            "Motor Enable; 8/9 Motor Fault; 10/11 Target Reached. Not "
            "current; range conflict.",
            "Actual outputs and electrical behavior are hardware-dependent.",
            "DOCUMENT_CONFLICT",
        ),
        _parameter(
            "output_status",
            "Digital Output Routing / Status Semantics",
            "GO[N] + OP",
            "none / bit field",
            "GO R/W non-volatile; OP port state",
            "GO[1..4]: 0..2 or 7; GO[14..16]: documented 0..8 with "
            "conflicts. Unavailable · not sampled.",
            "No current output state; Port C routing is coupled and "
            "hardware-dependent.",
            "LIVE_SEMANTICS_ONLY",
        ),
    ),
)


SECTIONS = (BRAKE, SETTLING_WINDOW, INPUTS_OUTPUTS)


DOCUMENT_CONFLICTS = (
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


PERSISTENT_WARNINGS = (
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


MISSING_EVIDENCE = (
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


_SNAPSHOT = ApplicationSettingsSnapshot(
    model_id=MODEL_ID,
    authority="DOCUMENTED_APPLICATION_SETTINGS_MAP_ONLY",
    model_status="PARTIAL_NEED_DATA",
    fidelity="DOCUMENTED_STATIC_REFERENCE",
    boundary=BOUNDARY,
    sections=SECTIONS,
    document_conflicts=DOCUMENT_CONFLICTS,
    persistent_warnings=PERSISTENT_WARNINGS,
    missing_evidence=MISSING_EVIDENCE,
    sources=SOURCES,
    can_inspect=True,
    can_read_drive=False,
    can_validate=False,
    can_evaluate=False,
    can_generate_commands=False,
    can_write=False,
    can_apply=False,
    can_revert=False,
    can_persist=False,
    can_actuate_outputs=False,
    can_move=False,
    can_claim_safety=False,
)


def build_evidence_snapshot() -> ApplicationSettingsSnapshot:
    """Return the canonical immutable documentation snapshot."""
    return _SNAPSHOT


def section_evidence(key: str) -> DocumentedApplicationSection:
    """Return a canonical section by strict string key."""
    if isinstance(key, bool) or not isinstance(key, str):
        raise TypeError("section key must be str")
    for section in SECTIONS:
        if section.key == key:
            return section
    raise KeyError(key)
