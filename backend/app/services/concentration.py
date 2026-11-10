from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.models.screening import ConcentrationType


_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)"
_UNIT = (
    r"(?P<unit>%\s*(?:w\s*/\s*w)?|w\s*/\s*w\s*%|"
    r"percent(?:\s+w\s*/\s*w)?|ppm|mg\s*(?:/|per)\s*kg)"
)
_RANGE_RE = re.compile(
    rf"^\s*(?P<lower>{_NUMBER})\s*(?:-|–|—|to)\s*(?P<upper>{_NUMBER})\s*{_UNIT}?\s*$",
    re.IGNORECASE,
)
_BOUND_RE = re.compile(
    rf"^\s*(?P<operator><=|>=|<|>|≤|≥|less\s+than|more\s+than|at\s+most|at\s+least)\s*(?P<value>{_NUMBER})\s*{_UNIT}?\s*$",
    re.IGNORECASE,
)
_APPROX_RE = re.compile(
    rf"^\s*(?:approximately|approx\.?|about|~)\s*(?P<value>{_NUMBER})\s*{_UNIT}?\s*$",
    re.IGNORECASE,
)
_EXACT_RE = re.compile(rf"^\s*(?P<value>{_NUMBER})\s*{_UNIT}?\s*$", re.IGNORECASE)
_UNKNOWN = {
    "not disclosed",
    "not available",
    "unknown",
    "confidential",
    "proprietary",
    "withheld",
}


@dataclass(frozen=True)
class ParsedConcentrationText:
    concentration_type: ConcentrationType
    value: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    lower_inclusive: bool | None = None
    upper_inclusive: bool | None = None
    unit: str | None = None
    original_text: str | None = None


def _unit(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.casefold().replace(" ", "")
    if "%" in token or token.startswith("percent"):
        return "percent"
    return "mg/kg" if token in {"mg/kg", "mgperkg"} else "ppm"


def parse_concentration_text(value: str) -> ParsedConcentrationText | None:
    raw = value.strip()
    if not raw:
        return None
    normalized = " ".join(raw.casefold().split())
    if normalized in _UNKNOWN:
        return ParsedConcentrationText(
            concentration_type=ConcentrationType.UNKNOWN,
            original_text=raw,
        )
    if match := _RANGE_RE.fullmatch(raw):
        lower = float(match.group("lower"))
        upper = float(match.group("upper"))
        if lower > upper:
            return None
        return ParsedConcentrationText(
            concentration_type=ConcentrationType.RANGE,
            lower_bound=lower,
            upper_bound=upper,
            lower_inclusive=True,
            upper_inclusive=True,
            unit=_unit(match.group("unit")),
            original_text=raw,
        )
    if match := _BOUND_RE.fullmatch(raw):
        operator = " ".join(match.group("operator").casefold().split())
        number = float(match.group("value"))
        if operator in {"<", "<=", "≤", "less than", "at most"}:
            inclusive = operator in {"<=", "≤", "at most"}
            return ParsedConcentrationText(
                concentration_type=ConcentrationType.UPPER_BOUND,
                upper_bound=number,
                upper_inclusive=inclusive,
                unit=_unit(match.group("unit")),
                original_text=raw,
            )
        inclusive = operator in {">=", "≥", "at least"}
        return ParsedConcentrationText(
            concentration_type=ConcentrationType.LOWER_BOUND,
            lower_bound=number,
            lower_inclusive=inclusive,
            unit=_unit(match.group("unit")),
            original_text=raw,
        )
    if match := _APPROX_RE.fullmatch(raw):
        return ParsedConcentrationText(
            concentration_type=ConcentrationType.APPROXIMATE,
            value=float(match.group("value")),
            unit=_unit(match.group("unit")),
            original_text=raw,
        )
    if match := _EXACT_RE.fullmatch(raw):
        return ParsedConcentrationText(
            concentration_type=ConcentrationType.EXACT,
            value=float(match.group("value")),
            unit=_unit(match.group("unit")),
            original_text=raw,
        )
    return None
