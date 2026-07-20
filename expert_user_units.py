"""Pure DS-402 position-scale formula preview for Expert Tuning.

The calculation uses explicit manual inputs only.  It does not read the
installed drive, infer the current axis configuration, write FC/OF values, or
claim parity with EAS.  Source identities are fixed provenance metadata; this
module intentionally performs no source-file I/O at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction


MAX_FC_VALUE = 2**31 - 1
DOCUMENTED_PRODUCT_LIMIT = 2**63

# A symmetric signed-64-bit magnitude is a conservative local display bound.
# It is not a drive range and is not used to validate FC configuration.
MAX_LOCAL_SAMPLE_COUNTS = 2**63 - 1

FORMULA_GROUPING = "(FC2*FC6*FC7)/(FC1*FC5*FC8)"
DOCUMENTED_LIMIT_GROUPINGS = (
    "FC1*FC6*FC8 < 2^63",
    "FC2*FC5*FC7 < 2^63",
)
DOCUMENT_CONFLICT = (
    "Documented grouping mismatch: the MAN-G-CR product-limit index grouping "
    "differs from the NetHelp position-scale formula grouping; its purpose "
    "and whether either document needs correction remain NEED-DATA."
)
BOUNDARY = (
    "EXPLICIT MANUAL INPUT · DOCUMENTED FORMULA PREVIEW · PARTIAL SCREENING "
    "· NOT CURRENT DRIVE CONFIG · NO FC/OF WRITE · NO APPLY/SV "
    "· NO DRIVE I/O"
)


@dataclass(frozen=True)
class DocumentSource:
    key: str
    location: str
    sha256: str


SOURCES = (
    DocumentSource(
        key="nethelp_html",
        location=(
            r"C:\Program Files\Elmo Motion Control"
            r"\Elmo Application Studio III\NetHelp\Content"
            r"\EAS_II_SimplIQ_Gold_UM"
            r"\Drive Setup and Motion Activities.htm"
        ),
        sha256=(
            "BD824C372BBBE7F0928F0F805F51EDA2C5CD73150AB3C20F9DE6279E9006E8EE"
        ),
    ),
    DocumentSource(
        key="nethelp_formula_image",
        location=(
            r"C:\Program Files\Elmo Motion Control"
            r"\Elmo Application Studio III\NetHelp\Content\Resources\Images"
            r"\EAS_II_SimplIQ_Gold_UM"
            r"\Drive Setup and Motion Activities_56.jpg"
        ),
        sha256=(
            "772B95FB672E43F54573AE498F137450810E601EB76636790275BC2B2E935CD9"
        ),
    ),
    DocumentSource(
        key="command_reference",
        location="docs/man-g-cr_GoldLine_CommandReference.pdf",
        sha256=(
            "89280DB57DBBE6877945CC8C4720C959B8295E68806DECBFB9F43892994C2A80"
        ),
    ),
)


@dataclass(frozen=True)
class PositionScalePreview:
    authority: str
    model_status: str
    fc1: int
    fc2: int
    fc5: int
    fc6: int
    fc7: int
    fc8: int
    unit_label: str
    sample_counts: int | None
    units_per_count: Fraction
    counts_per_unit: Fraction
    sample_units: Fraction | None
    units_per_count_decimal: str
    counts_per_unit_decimal: str
    sample_units_decimal: str | None
    formula_grouping: str
    documented_limit_groupings: tuple[str, str]
    documented_limit_products: tuple[int, int]
    document_conflict: str
    limitations: tuple[str, ...]
    boundary: str
    sources: tuple[DocumentSource, ...]
    can_read_drive: bool
    can_write: bool
    can_apply: bool
    can_persist: bool


def _strict_fc(value, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"{name} must be a strict integer in 1..{MAX_FC_VALUE}"
        )
    if not 1 <= value <= MAX_FC_VALUE:
        raise ValueError(f"{name} must be in 1..{MAX_FC_VALUE}")
    return value


def _sample_count(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("sample_counts must be a strict signed integer or None")
    if abs(value) > MAX_LOCAL_SAMPLE_COUNTS:
        raise ValueError(
            "sample_counts must be within the conservative local range "
            f"-{MAX_LOCAL_SAMPLE_COUNTS}..{MAX_LOCAL_SAMPLE_COUNTS}"
        )
    return value


def _unit_label(value: str | None) -> str:
    if value is None:
        return "unit"
    if not isinstance(value, str):
        raise TypeError("unit_label must be str or None")
    normalized = " ".join(value.split())
    if not normalized:
        return "unit"
    if len(normalized) > 48:
        raise ValueError("unit_label must not exceed 48 characters")
    return normalized


def _decimal_text(value: Fraction) -> str:
    """Return a deterministic, bounded 15-significant-digit display string."""
    if value == 0:
        return "0"
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_HALF_EVEN
        decimal_value = (
            Decimal(value.numerator) / Decimal(value.denominator)
        )
        return format(decimal_value, ".15g").replace("E", "e")


def build_position_scale_preview(
        *, fc1, fc2, fc5, fc6, fc7, fc8,
        unit_label: str | None = None,
        sample_counts: int | None = None) -> PositionScalePreview:
    """Build a deterministic local preview from explicit DS-402 FC inputs."""
    fc1 = _strict_fc(fc1, "FC1")
    fc2 = _strict_fc(fc2, "FC2")
    fc5 = _strict_fc(fc5, "FC5")
    fc6 = _strict_fc(fc6, "FC6")
    fc7 = _strict_fc(fc7, "FC7")
    fc8 = _strict_fc(fc8, "FC8")
    sample_counts = _sample_count(sample_counts)
    unit_label = _unit_label(unit_label)

    # These are the two MAN-G-CR restrictions verbatim.  Their index grouping
    # differs from the equation below, so they are separate document guards,
    # not a proof that the equation numerator/denominator cannot overflow.
    first_documented_product = fc1 * fc6 * fc8
    second_documented_product = fc2 * fc5 * fc7
    if first_documented_product >= DOCUMENTED_PRODUCT_LIMIT:
        raise ValueError(
            "MAN-G-CR literal guard requires FC1*FC6*FC8 < 2^63; "
            f"got {first_documented_product}"
        )
    if second_documented_product >= DOCUMENTED_PRODUCT_LIMIT:
        raise ValueError(
            "MAN-G-CR literal guard requires FC2*FC5*FC7 < 2^63; "
            f"got {second_documented_product}"
        )

    units_per_count = Fraction(
        fc2 * fc6 * fc7,
        fc1 * fc5 * fc8,
    )
    counts_per_unit = 1 / units_per_count
    sample_units = (
        None if sample_counts is None
        else sample_counts * units_per_count
    )

    return PositionScalePreview(
        authority="DOCUMENTED_FORMULA_PREVIEW",
        model_status="PARTIAL_SCREENING",
        fc1=fc1,
        fc2=fc2,
        fc5=fc5,
        fc6=fc6,
        fc7=fc7,
        fc8=fc8,
        unit_label=unit_label,
        sample_counts=sample_counts,
        units_per_count=units_per_count,
        counts_per_unit=counts_per_unit,
        sample_units=sample_units,
        units_per_count_decimal=_decimal_text(units_per_count),
        counts_per_unit_decimal=_decimal_text(counts_per_unit),
        sample_units_decimal=(
            None if sample_units is None else _decimal_text(sample_units)
        ),
        formula_grouping=FORMULA_GROUPING,
        documented_limit_groupings=DOCUMENTED_LIMIT_GROUPINGS,
        documented_limit_products=(
            first_documented_product,
            second_documented_product,
        ),
        document_conflict=DOCUMENT_CONFLICT,
        limitations=(
            DOCUMENT_CONFLICT,
            "Explicit manual inputs are not read from or compared with a drive.",
            "No EAS Enter/Apply/Revert/Summary or installed-value parity claim.",
            "No FC/OF command generation, persistence, or safety-limit conversion.",
        ),
        boundary=BOUNDARY,
        sources=SOURCES,
        can_read_drive=False,
        can_write=False,
        can_apply=False,
        can_persist=False,
    )
