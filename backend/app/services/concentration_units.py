from __future__ import annotations

from typing import Any


_MASS_FRACTION = {
    "percent": 1e-2,
    "ppm": 1e-6,
    "mg/kg": 1e-6,
}


def normalize_mass_fraction_unit(value: str | None) -> str | None:
    if value is None:
        return None
    token = " ".join(value.strip().casefold().split())
    compact = token.replace(" ", "")
    if "%" in token or "percent" in token or compact in {"w/w%", "%w/w"}:
        return "percent"
    if token == "ppm":
        return "ppm"
    if compact in {"mg/kg", "mgperkg"}:
        return "mg/kg"
    return None


def mass_fraction_conversion_factor(
    source_unit: str | None,
    target_unit: str | None,
) -> float | None:
    source = normalize_mass_fraction_unit(source_unit)
    target = normalize_mass_fraction_unit(target_unit)
    if source is None or target is None:
        return None
    return _MASS_FRACTION[source] / _MASS_FRACTION[target]


def convert_concentration_unit(concentration: Any, target_unit: str | None):
    """Return a model copy in a compatible mass-fraction unit, or None.

    The helper deliberately changes only numerical scale and unit. Chemical
    basis and preparation stage remain untouched and must still match the rule.
    """
    factor = mass_fraction_conversion_factor(concentration.unit, target_unit)
    if factor is None:
        return None
    updates: dict[str, Any] = {"unit": normalize_mass_fraction_unit(target_unit)}
    for field in ("value", "lower_bound", "upper_bound"):
        value = getattr(concentration, field, None)
        updates[field] = value * factor if value is not None else None
    return concentration.model_copy(update=updates)
