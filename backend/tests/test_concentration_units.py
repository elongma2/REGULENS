from __future__ import annotations

import pytest

from backend.app.models.screening import ConcentrationInput, ConcentrationType
from backend.app.services.concentration_units import (
    convert_concentration_unit,
    mass_fraction_conversion_factor,
)


@pytest.mark.parametrize(
    ("source", "target", "factor"),
    [
        ("percent", "ppm", 10_000),
        ("ppm", "percent", 0.0001),
        ("mg/kg", "ppm", 1),
        ("ppm", "mg/kg", 1),
        ("% w/w", "percent", 1),
    ],
)
def test_exact_mass_fraction_conversion_factors(source, target, factor) -> None:
    assert mass_fraction_conversion_factor(source, target) == pytest.approx(factor)


def test_range_conversion_preserves_bounds_basis_and_stage() -> None:
    concentration = ConcentrationInput(
        concentration_type=ConcentrationType.RANGE,
        lower_bound=5_000,
        upper_bound=10_000,
        lower_inclusive=True,
        upper_inclusive=True,
        unit="ppm",
        basis="free base",
        preparation_stage="finished_product",
    )

    converted = convert_concentration_unit(concentration, "percent")

    assert converted is not None
    assert converted.lower_bound == pytest.approx(0.5)
    assert converted.upper_bound == pytest.approx(1.0)
    assert converted.unit == "percent"
    assert converted.basis == "free base"
    assert converted.preparation_stage == "finished_product"


def test_unknown_unit_is_never_guessed() -> None:
    concentration = ConcentrationInput(
        concentration_type=ConcentrationType.EXACT,
        value=25,
        unit=None,
        basis=None,
        preparation_stage="finished_product",
    )

    assert convert_concentration_unit(concentration, "percent") is None
    assert mass_fraction_conversion_factor("parts", "percent") is None
