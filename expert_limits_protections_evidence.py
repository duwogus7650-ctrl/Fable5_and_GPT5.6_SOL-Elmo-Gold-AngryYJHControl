"""Immutable documentation evidence for Expert Limits / Protections.

This module is a static catalog, not a drive configuration reader, validator,
command generator, protection simulator, or safety assessor.  Source identity
and normalized document facts are frozen constants so importing or inspecting
the catalog performs no file, process, network, worker, or drive I/O.
"""

from __future__ import annotations

from dataclasses import dataclass


BOUNDARY = (
    "STATIC DOCUMENT MAP ONLY · DOCUMENTED PARAMETER MAP · "
    "PARTIAL / NEED-DATA · NOT CURRENT DRIVE CONFIG · "
    "NOT ACTIVE PROTECTION STATE · NOT A SAFETY ASSESSMENT · "
    "NO DRIVE READ · NO VALIDATION / EVALUATION · NO COMMAND · NO WRITE · "
    "NO APPLY/SV · NO UNIT PROPAGATION · NO DRIVE I/O"
)


@dataclass(frozen=True, slots=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DocumentedParameter:
    key: str
    label: str
    command: str
    documented_unit: str
    access: str
    documented_effect: str
    condition: str
    evidence_status: str = "DOCUMENTED"


@dataclass(frozen=True, slots=True)
class DocumentedSection:
    key: str
    label: str
    reference: str
    parameters: tuple[DocumentedParameter, ...]


@dataclass(frozen=True, slots=True)
class LimitsProtectionsSnapshot:
    authority: str
    model_status: str
    boundary: str
    sections: tuple[DocumentedSection, ...]
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
    can_persist: bool
    can_propagate_units: bool


_EAS_ROOT = (
    r"C:\Program Files\Elmo Motion Control\Elmo Application Studio III"
    r"\NetHelp\Content"
)
_NETHELP_HTML = (
    _EAS_ROOT
    + r"\EAS_II_SimplIQ_Gold_UM\Drive Setup and Motion Activities.htm"
)
_NETHELP_IMAGE_ROOT = (
    _EAS_ROOT + r"\Resources\Images\EAS_II_SimplIQ_Gold_UM"
)
_COMMAND_ROOT = _EAS_ROOT + r"\Gold Line Command Reference"


SOURCES = (
    DocumentSource(
        "nethelp_html",
        _NETHELP_HTML,
        "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE",
    ),
    DocumentSource(
        "nethelp_current_limits_image",
        _NETHELP_IMAGE_ROOT + r"\Drive Setup and Motion Activities_66.png",
        "248D74A6F9CCAF06847481061586AC730D280CA531E427FC03EF289DE4F3D156",
    ),
    DocumentSource(
        "nethelp_motion_limits_image",
        _NETHELP_IMAGE_ROOT + r"\Drive Setup and Motion Activities_68.png",
        "C7D1FDB9B1D6C8CA898E7C9B6972B6C9E840EC354F2652FC116940EE94A5BEAE",
    ),
    DocumentSource(
        "nethelp_protections_image",
        _NETHELP_IMAGE_ROOT + r"\Drive Setup and Motion Activities_69.png",
        "0840FB3554AD30DB8DE1DC429031C70CA03B2A1C3C772007367D515C445CE223",
    ),
    DocumentSource(
        "nethelp_disable_feedback_limits_image",
        _NETHELP_IMAGE_ROOT + r"\Drive Setup and Motion Activities_71.png",
        "8B4CE688DBA5960C7289344B17EEAB2A5D668954918B1F8D94B1DBD0217DCA46",
    ),
    DocumentSource(
        "command_reference",
        "docs/man-g-cr_GoldLine_CommandReference.pdf",
        "89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80",
    ),
    DocumentSource(
        "firmware_release_notes",
        "docs/firmware-release-notes.txt",
        "3E70090E7E9E43290A972EE96ED057AF7E4E6D74FDA92780F6AD7D47BD201719",
    ),
    DocumentSource(
        "simpliq_alphabetical_listing",
        _EAS_ROOT
        + r"\SimplIQ Command Reference\Alphabetical Listing.htm",
        "6387D916255910290468D103E42A796977D3BD44482EC4A04135B8E5780AFBEB",
    ),
    DocumentSource(
        "gold_command_cl",
        _COMMAND_ROOT + r"\CL Current Limit Parameters.htm",
        "A881FE3E645E42D417E6E598EE3A8016AA04910277B935DD92AC02999598F48C",
    ),
    DocumentSource(
        "gold_command_pl",
        _COMMAND_ROOT + r"\PL N Peak Limit.htm",
        "5A65892FA038EEE704A23F232EC4A901F4A29584345AC02BD7E502A07F5C37D2",
    ),
    DocumentSource(
        "gold_command_us",
        _COMMAND_ROOT + r"\US User Saturation Parameters.htm",
        "AEE98B4B985E6A9B6906A1A138E0B29B848E2536CE2C9629C964C62A7F46AF40",
    ),
    DocumentSource(
        "gold_command_sd",
        _COMMAND_ROOT + r"\SD Stop Deceleration.htm",
        "785E2AEDF1CB90A71DF41349742DD2ED207BCAD6FDCF1226D38C3EC38D24E935",
    ),
    DocumentSource(
        "gold_command_vh_vl",
        _COMMAND_ROOT + r"\VH VL High Low Reference Limit.htm",
        "5FE1D381510E409BDD14F9F15EC98F65E48EB8A1FAEF6DFF2F112C55C5FECC06",
    ),
    DocumentSource(
        "gold_command_xm",
        _COMMAND_ROOT + r"\XM Position Modulo.htm",
        "50438049A6EB55D7D1461AE25EA77E747FF4CE8D565735027E912357132C49BC",
    ),
    DocumentSource(
        "gold_command_xa",
        _COMMAND_ROOT + r"\XA Extra Parameters.htm",
        "8A56F93F0D4F9F1FF9F4280619B5E9DAA2A4FF227D94219A76DC6EAC136A65CB",
    ),
    DocumentSource(
        "gold_command_er",
        _COMMAND_ROOT + r"\ER Maximum Tracking Error.htm",
        "E1FCBAA4DE08A7107665A0EACC154DC478A3E7023A70D9F89D9AB333E9776787",
    ),
    DocumentSource(
        "gold_command_xp",
        _COMMAND_ROOT + r"\XP Extra General Parameters.htm",
        "6D92C62A84CC26306CDFC504CFCCF762127514B548E2A2514D5BE2D1D30D50E3",
    ),
    DocumentSource(
        "gold_command_hl_ll",
        _COMMAND_ROOT + r"\HL LL High Low Feedback Limit.htm",
        "75BC54ACF8D84C6946FFB546CEAE22D70E81266A5FEDE6726669227A606461E5",
    ),
    DocumentSource(
        "gold_command_mc",
        _COMMAND_ROOT + r"\MC Maximum Current.htm",
        "26EBD384B34F4616454A41BECD66DBD193A4093AE5BEC73941D1B7E05C112205",
    ),
    DocumentSource(
        "gold_command_bv",
        _COMMAND_ROOT + r"\BV Bus Voltage.htm",
        "27C23DD08385BBDB7558F7165312791D300650B1E4E1AD2252AF1A50295596D6",
    ),
)


CURRENT_LIMITS = DocumentedSection(
    key="current_limits",
    label="Current Limits",
    reference="NetHelp §8.2.6.1",
    parameters=(
        DocumentedParameter(
            "mc", "Drive maximum current", "MC", "A", "read-only",
            "Product-dependent drive current rating.",
            "No generic range; static definition only."),
        DocumentedParameter(
            "bv", "Drive maximum bus voltage", "BV", "V", "read-only",
            "Product-dependent drive bus-voltage rating.",
            "Positive/product dependent; static definition only."),
        DocumentedParameter(
            "pl1", "Peak current limit", "PL[1]", "A", "R/W",
            "Peak sine-current amplitude limit.",
            "Documented range depends on drive product and motor rating."),
        DocumentedParameter(
            "cl1", "Continuous current limit", "CL[1]", "A", "R/W",
            "Continuous sine-current amplitude limit.",
            "Product R/non-R authority required; NetHelp cross-reference "
            "conflict preserved.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "pl2", "Peak current duration", "PL[2]", "s", "R/W",
            "Documented peak-current duration before continuous limiting.",
            "Range/default depend on product; post-duration target wording "
            "conflicts.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "us1", "PWM duty-cycle limit", "US[1]", "% max PWM", "R/W",
            "Limits documented PWM output duty cycle.",
            "0..100 documented; current firmware applicability unverified."),
        DocumentedParameter(
            "us2", "Current-integral output limit", "US[2]",
            "% max PWM", "R/W / version-dependent",
            "Limits the documented current-controller integral contribution.",
            "Installed NetHelp/firmware notes conflict with MAN-G-CR reserved "
            "indices; exact firmware applicability NEED-DATA.",
            "DOCUMENT_CONFLICT"),
    ),
)


MOTION_LIMITS = DocumentedSection(
    key="motion_limits",
    label="Motion Limits and Modulo",
    reference="NetHelp §8.2.6.2",
    parameters=(
        DocumentedParameter(
            "sd", "Emergency-stop deceleration", "SD",
            "FC-based acceleration unit; EAS labels cnt/s²", "R/W",
            "Emergency-stop deceleration and documented acceleration ceiling.",
            "Current FC/display-unit configuration is absent."),
        DocumentedParameter(
            "vh2", "Maximum velocity", "VH[2]",
            "FC-based velocity unit; EAS labels cnt/s", "R/W",
            "Maximum documented reference velocity.",
            "Rotary modes also involve DS-402 0x6080."),
        DocumentedParameter(
            "vl3", "Feedback lower position limit", "VL[3]",
            "FC-based position unit; EAS labels cnt", "R/W",
            "Documented lower software feedback position limit.",
            "Requires relation VH[3] > VL[3]."),
        DocumentedParameter(
            "vh3", "Feedback upper position limit", "VH[3]",
            "FC-based position unit; EAS labels cnt", "R/W",
            "Documented upper software feedback position limit.",
            "Requires relation VH[3] > VL[3]."),
        DocumentedParameter(
            "xm1", "Absolute feedback range minimum", "XM[1]",
            "FC-based position unit", "R/W in command ref / EAS page read-only",
            "Defines the lower absolute-feedback or modulo range boundary.",
            "Motor off and HM[1]=0 restrictions; EAS transaction map unknown.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "xm2", "Absolute feedback range maximum", "XM[2]",
            "FC-based position unit", "R/W in command ref / EAS page read-only",
            "Defines the exclusive upper absolute-feedback/modulo boundary.",
            "Motor off and HM[1]=0 restrictions; EAS transaction map unknown.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "modulo", "Modulo option", "MODULO MODE",
            "documented mode", "EAS mapping NEED-DATA",
            "Selects documented non-modulo/modulo and cyclic-limit behavior.",
            "PO/0x60F2 direction bits are documented separately; exact EAS "
            "dropdown write mapping is unknown.",
            "NEED_DATA"),
        DocumentedParameter(
            "xa4_bit1", "Bypass acceleration limiting", "XA[4]:1",
            "bit flag", "dangerous / version-dependent",
            "Bypasses documented acceleration limiting.",
            "Static danger row only; no toggle or encoded-value preview.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "xa4_bit2", "Ignore position-limit inputs in cyclic/IP modes",
            "XA[4]:2", "bit flag", "dangerous / version-dependent",
            "Ignores documented hardware/software position limits in cyclic "
            "and interpolated-position modes.",
            "Static danger row only; default and command authority conflict.",
            "DOCUMENT_CONFLICT"),
    ),
)


PROTECTIONS = DocumentedSection(
    key="protections",
    label="Protections",
    reference="NetHelp §8.2.6.3",
    parameters=(
        DocumentedParameter(
            "er3", "Maximum position tracking error", "ER[3]", "count", "R/W",
            "Documented position-error threshold that disables the motor.",
            "Configured value and protection efficacy are not inspected."),
        DocumentedParameter(
            "er2", "Maximum velocity tracking error", "ER[2]", "count/s", "R/W",
            "Documented velocity-error threshold that disables the motor.",
            "EAS table/body unit wording conflicts."),
        DocumentedParameter(
            "er5", "Maximum yaw tracking error", "ER[5]", "count",
            "EAS read-only / array command R/W",
            "Conditional yaw/stepper tracking-error threshold.",
            "Visibility and write semantics conflict; 0 is documented disable.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "cl2", "Motor-stuck current threshold", "CL[2]", "% CL[1]", "R/W",
            "Documented motor-stuck current threshold.",
            "CL[2] < 2 disables motor-stuck protection."),
        DocumentedParameter(
            "cl3", "Motor-stuck velocity threshold", "CL[3]", "count/s", "R/W",
            "Documented motor-stuck velocity threshold.",
            "CL index semantics conflict in other manual tables."),
        DocumentedParameter(
            "cl4", "Motor-stuck duration", "CL[4]",
            "ms in EAS/index; seconds in remarks", "R/W",
            "Documented motor-stuck duration threshold.",
            "Raw alternatives only; no time conversion or stuck verdict.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "xp1", "Overvoltage threshold", "XP[1]", "V", "R/W",
            "Documented overvoltage protection threshold.",
            "Depends on product WI[35] and installation guide."),
        DocumentedParameter(
            "xp13", "Undervoltage threshold", "XP[13]", "V", "R/W",
            "Documented undervoltage protection threshold.",
            "Command table has no explicit generic numeric range.",
            "NEED_DATA"),
        DocumentedParameter(
            "ll3", "Minimum feedback position", "LL[3]",
            "FC-based position unit; EAS labels cnt", "R/W · motor off",
            "Documented lower feedback position-range threshold.",
            "Lower-bound sign prose conflicts with [LL[3]..HL[3]] notation.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "hl3", "Maximum feedback position", "HL[3]",
            "FC-based position unit; EAS labels cnt", "R/W · motor off",
            "Documented upper feedback position-range threshold.",
            "NetHelp maximum row says 'See LL[3]'; trigger parity NEED-DATA.",
            "DOCUMENT_CONFLICT"),
        DocumentedParameter(
            "hl2", "Maximum feedback speed", "HL[2]",
            "FC-based velocity unit; EAS labels cnt/s", "R/W · motor off",
            "Documented overspeed threshold that disables the drive.",
            "0 disables documented overspeed protection."),
    ),
)


SECTIONS = (CURRENT_LIMITS, MOTION_LIMITS, PROTECTIONS)


DOCUMENT_CONFLICTS = (
    "US[2] is a current-integral saturation limit in installed NetHelp and "
    "firmware notes, while MAN-G-CR 1.406 marks US[2] and US[3] Reserved.",
    "ER[5] is exposed conditionally by EAS, but ER index/access descriptions "
    "are internally incomplete and disagree on read-only versus R/W.",
    "CL[2], CL[3], and CL[4] detailed motor-stuck semantics conflict with "
    "another table that swaps CL[2]/CL[3]; CL[4] is milliseconds in EAS/index "
    "but seconds in remarks, alongside fixed '3 seconds' wording.",
    "XA[4] bit 1/2 bypasses are exposed by Gold NetHelp/EAS while the "
    "installed SimplIQ Alphabetical Listing calls XA[4] Reserved and warns "
    "not to modify XA[].",
    "Current Limits text for CL[1] refers to PL[1]; peak-duration text says "
    "post-duration current is limited to PL[1] while the command reference "
    "states CL[1].",
    "The Maximum HL[3] NetHelp row says 'See LL[3]', and LL[3] lower-bound "
    "sign prose conflicts with the displayed [LL[3]..HL[3]] interval.",
    "XM[1]/XM[2] are presented read-only on the EAS page but R/W with motor-"
    "off restrictions in the command reference; dropdown transaction mapping "
    "is not documented.",
    "XA[4] default authority conflicts: one command presentation implies zero "
    "while VH/VL notes say bit 2 is factory-set.",
    "EAS count/count-per-second labels conflict with command pages that make "
    "SD/VH/VL/XM/HL/LL units dependent on FC user scaling.",
)


PERSISTENT_WARNINGS = (
    "CL[2] < 2 disables the documented motor-stuck protection.",
    "XA[4] bypass bits can remove acceleration or hardware/software position-"
    "limit enforcement; this inspector never exposes a toggle or value.",
    "All-zero XM/VH/VL combinations can select a documented no-limits mode.",
    "LL[3]=HL[3]=0 disables the documented feedback position-range "
    "protection; HL[2]=0 disables documented overspeed protection.",
    "Displayed rows are documentation facts, not current values, active "
    "protections, recommendations, or a safety assessment.",
)


MISSING_EVIDENCE = (
    "Current Gold Twitter exact SKU/product class, firmware applicability, "
    "MC/BV/WI[35]/WI[38], FC/UM/DS-402 mode, XA[4], and all live values.",
    "Authoritative CL[4] unit/logic, LL[3] lower-bound sign, ER[5] access "
    "semantics, XA[4] default, and XP[13] generic range.",
    "Current EAS III conditional visibility, validation rules, dropdown-to-"
    "register mapping, write order, readback, rollback, Revert, and SV flow.",
    "Motor ratings, mechanical envelope, direction, limit-input polarity, "
    "stop distance, brake behavior, and independent E-stop/STO evidence.",
)


_SNAPSHOT = LimitsProtectionsSnapshot(
    authority="DOCUMENTED_PARAMETER_MAP_ONLY",
    model_status="PARTIAL_NEED_DATA",
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
    can_persist=False,
    can_propagate_units=False,
)


def build_evidence_snapshot() -> LimitsProtectionsSnapshot:
    """Return the canonical immutable documentation snapshot."""
    return _SNAPSHOT


def section_evidence(key: str) -> DocumentedSection:
    """Return a canonical section by strict string key."""
    if isinstance(key, bool) or not isinstance(key, str):
        raise TypeError("section key must be str")
    for section in SECTIONS:
        if section.key == key:
            return section
    raise KeyError(key)
