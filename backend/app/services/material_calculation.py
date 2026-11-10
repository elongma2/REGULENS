from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isclose
import re
from typing import Iterable

from backend.app.models.document_intake import (
    AggregatedIngredient,
    AssemblyCompleteness,
    AssemblyIssue,
    AssemblyIssueScope,
    AssemblyIssueSeverity,
    CalculatedContribution,
    CompositionQuantity,
    CompositionQuantityKind,
    ConfirmationStatus,
    DisclosureStatus,
    MaterialConstituent,
    SupplierMaterial,
)


COMPOSITION_ROUNDING_TOLERANCE_PERCENT = 0.5
_PERCENT_UNITS = {"%", "percent", "percentage", "w/w %", "% w/w"}
_MASS_FRACTION_UNITS = {*_PERCENT_UNITS, "ppm", "mg/kg"}
_REVERSED_PERCENT_RANGE_RE = re.compile(
    r"^\s*(?P<lower>\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*"
    r"(?P<upper>\d+(?:\.\d+)?)\s*(?:%\s*(?:w/w)?|w/w\s*%|percent)?"
    r"(?:\s*\([^)]*\))?\s*$",
    re.I,
)


@dataclass(frozen=True)
class QuantityInterval:
    lower: float | None
    upper: float | None
    lower_inclusive: bool | None
    upper_inclusive: bool | None
    approximate: bool


def _token(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.strip().casefold().split()) or None


def is_percent(quantity: CompositionQuantity) -> bool:
    return _token(quantity.unit) in _PERCENT_UNITS


def _mass_fraction_unit(quantity: CompositionQuantity) -> str | None:
    unit = _token(quantity.unit)
    if unit in _PERCENT_UNITS:
        return "percent"
    return unit if unit in {"ppm", "mg/kg"} else None


def quantity_label(quantity: CompositionQuantity) -> str:
    unit = "%" if is_percent(quantity) else f" {quantity.unit}" if quantity.unit else ""
    if quantity.kind == CompositionQuantityKind.RANGE:
        return f"{quantity.lower:g}–{quantity.upper:g}{unit}"
    if quantity.kind == CompositionQuantityKind.UPPER_BOUND:
        return f"{'≤' if quantity.upper_inclusive else '<'}{quantity.upper:g}{unit}"
    if quantity.kind == CompositionQuantityKind.LOWER_BOUND:
        return f"{'≥' if quantity.lower_inclusive else '>'}{quantity.lower:g}{unit}"
    if quantity.value is not None:
        return f"{'≈' if quantity.kind == CompositionQuantityKind.APPROXIMATE else ''}{quantity.value:g}{unit}"
    return quantity.raw_text or quantity.kind.value.replace("_", " ")


def quantity_interval(quantity: CompositionQuantity) -> QuantityInterval:
    approximate = quantity.approximate or quantity.kind == CompositionQuantityKind.APPROXIMATE
    if quantity.kind in {CompositionQuantityKind.EXACT, CompositionQuantityKind.APPROXIMATE}:
        return QuantityInterval(quantity.value, quantity.value, True, True, approximate)
    if quantity.kind == CompositionQuantityKind.RANGE:
        return QuantityInterval(
            quantity.lower,
            quantity.upper,
            quantity.lower_inclusive,
            quantity.upper_inclusive,
            approximate,
        )
    if quantity.kind == CompositionQuantityKind.UPPER_BOUND:
        return QuantityInterval(0.0, quantity.upper, True, quantity.upper_inclusive, approximate)
    if quantity.kind == CompositionQuantityKind.LOWER_BOUND:
        return QuantityInterval(quantity.lower, None, quantity.lower_inclusive, None, approximate)
    return QuantityInterval(None, None, None, None, approximate)


def _reversed_percentage_range(
    quantity: CompositionQuantity | None,
) -> tuple[float, float] | None:
    if quantity is None or quantity.kind != CompositionQuantityKind.UNKNOWN or not quantity.raw_text:
        return None
    match = _REVERSED_PERCENT_RANGE_RE.fullmatch(quantity.raw_text)
    if not match:
        return None
    lower = float(match.group("lower"))
    upper = float(match.group("upper"))
    return (lower, upper) if lower > upper else None


def _quantity_from_interval(
    interval: QuantityInterval,
    *,
    raw_text: str,
    unit: str = "percent",
    basis: str | None = None,
    preparation_stage: str | None = "finished_product",
    quantity_scope: str = "finished_product",
) -> CompositionQuantity:
    common = {
        "unit": unit,
        "basis": basis,
        "preparation_stage": preparation_stage,
        "quantity_scope": quantity_scope,
        "raw_text": raw_text,
        "approximate": interval.approximate,
    }
    if interval.lower is None and interval.upper is None:
        return CompositionQuantity(kind=CompositionQuantityKind.UNKNOWN, **common)
    if interval.lower is None:
        return CompositionQuantity(
            kind=CompositionQuantityKind.UPPER_BOUND,
            upper=interval.upper,
            upper_inclusive=interval.upper_inclusive,
            **common,
        )
    if interval.upper is None:
        return CompositionQuantity(
            kind=CompositionQuantityKind.LOWER_BOUND,
            lower=interval.lower,
            lower_inclusive=interval.lower_inclusive,
            **common,
        )
    if isclose(interval.lower, interval.upper, abs_tol=1e-12):
        return CompositionQuantity(
            kind=CompositionQuantityKind.APPROXIMATE if interval.approximate else CompositionQuantityKind.EXACT,
            value=interval.lower,
            **common,
        )
    return CompositionQuantity(
        kind=CompositionQuantityKind.RANGE,
        lower=interval.lower,
        upper=interval.upper,
        lower_inclusive=interval.lower_inclusive,
        upper_inclusive=interval.upper_inclusive,
        **common,
    )


def multiply_percentage_quantities(
    material_usage: CompositionQuantity,
    constituent_quantity: CompositionQuantity,
) -> CompositionQuantity:
    usage = quantity_interval(material_usage)
    constituent = quantity_interval(constituent_quantity)
    lower = None
    upper = None
    if usage.lower is not None and constituent.lower is not None:
        lower = usage.lower * constituent.lower / 100
    if usage.upper is not None and constituent.upper is not None:
        upper = usage.upper * constituent.upper / 100
    return _quantity_from_interval(
        QuantityInterval(
            lower=lower,
            upper=upper,
            lower_inclusive=(usage.lower_inclusive and constituent.lower_inclusive)
            if lower is not None else None,
            upper_inclusive=(usage.upper_inclusive and constituent.upper_inclusive)
            if upper is not None else None,
            approximate=usage.approximate or constituent.approximate,
        ),
        raw_text=(
            f"({material_usage.raw_text or material_usage.kind.value}) x "
            f"({constituent_quantity.raw_text or constituent_quantity.kind.value}) / 100"
        ),
        unit=_mass_fraction_unit(constituent_quantity) or "percent",
        basis=constituent_quantity.basis,
        preparation_stage=material_usage.preparation_stage,
        quantity_scope="finished_product",
    )


def _as_percent(quantity: CompositionQuantity) -> CompositionQuantity | None:
    unit = _mass_fraction_unit(quantity)
    if unit is None:
        return None
    if unit == "percent":
        return quantity.model_copy(update={"unit": "percent"})
    interval = quantity_interval(quantity)
    factor = 1 / 10_000
    return _quantity_from_interval(
        QuantityInterval(
            lower=interval.lower * factor if interval.lower is not None else None,
            upper=interval.upper * factor if interval.upper is not None else None,
            lower_inclusive=interval.lower_inclusive,
            upper_inclusive=interval.upper_inclusive,
            approximate=interval.approximate,
        ),
        raw_text=quantity.raw_text or quantity_label(quantity),
        unit="percent",
        basis=quantity.basis,
        preparation_stage=quantity.preparation_stage,
        quantity_scope=quantity.quantity_scope or "finished_product",
    )


def add_percentage_quantities(quantities: Iterable[CompositionQuantity]) -> CompositionQuantity:
    values = list(quantities)
    intervals = [quantity_interval(quantity) for quantity in values]
    if not intervals:
        return CompositionQuantity(
            kind=CompositionQuantityKind.UNKNOWN,
            unit="percent",
            basis=None,
            preparation_stage="finished_product",
            quantity_scope="finished_product",
            raw_text="No compatible contributions",
        )
    known_lowers = [interval.lower for interval in intervals if interval.lower is not None]
    lower = sum(known_lowers) if known_lowers else None
    upper = (
        sum(interval.upper for interval in intervals if interval.upper is not None)
        if all(interval.upper is not None for interval in intervals)
        else None
    )
    return _quantity_from_interval(
        QuantityInterval(
            lower=lower,
            upper=upper,
            lower_inclusive=all(interval.lower_inclusive is not False for interval in intervals),
            upper_inclusive=(all(interval.upper_inclusive is not False for interval in intervals)
            if upper is not None else None),
            approximate=any(interval.approximate for interval in intervals),
        ),
        raw_text=" + ".join(quantity.raw_text or quantity.kind.value for quantity in values),
        unit=_mass_fraction_unit(values[0]) or "percent",
        basis=values[0].basis,
        preparation_stage=values[0].preparation_stage,
        quantity_scope="finished_product",
    )


def _issue(
    material: SupplierMaterial,
    *,
    code: str,
    message: str,
    action: str,
    severity: AssemblyIssueSeverity = AssemblyIssueSeverity.REVIEW_REQUIRED,
    constituent: MaterialConstituent | None = None,
    blocking: bool = True,
) -> AssemblyIssue:
    suffix = constituent.constituent_id if constituent else material.material_id
    return AssemblyIssue(
        issue_id=f"{code}:{material.material_id}:{suffix}",
        code=code,
        severity=severity,
        scope=AssemblyIssueScope.CONSTITUENT if constituent else AssemblyIssueScope.MATERIAL,
        message=message,
        reviewer_action=action,
        blocking_for_calculation=blocking,
        material_ids=[material.material_id],
        constituent_ids=[constituent.constituent_id] if constituent else [],
        document_ids=[material.governing_document_id] if material.governing_document_id else material.attached_document_ids,
        evidence=constituent.source_evidence if constituent else [],
    )


def _derive_remainder(
    material: SupplierMaterial,
    *,
    tolerance: float,
) -> tuple[SupplierMaterial, list[AssemblyIssue]]:
    remainder_rows = [
        constituent for constituent in material.constituents
        if constituent.composition_quantity
        and constituent.composition_quantity.kind == CompositionQuantityKind.REMAINDER_TO_TOTAL
    ]
    if not remainder_rows:
        return material, []
    if len(remainder_rows) != 1 or material.disclosure_status != DisclosureStatus.COMPLETE:
        return material, [_issue(
            material,
            code="impossible_composition_total",
            message="The remainder-to-total value cannot be derived from this disclosure.",
            action="Confirm that the disclosure is complete and contains exactly one qsp/remainder constituent.",
            severity=AssemblyIssueSeverity.ERROR,
            constituent=remainder_rows[0] if remainder_rows else None,
        )]

    remainder = remainder_rows[0]
    target = remainder.composition_quantity.value or 0
    lower_sum = 0.0
    upper_sum = 0.0
    for constituent in material.constituents:
        if constituent.constituent_id == remainder.constituent_id:
            continue
        quantity = constituent.composition_quantity
        if quantity is None or not is_percent(quantity) or quantity.quantity_scope != "supplier_material":
            return material, [_issue(
                material,
                code="calculation_withheld",
                message="The qsp/remainder value depends on a missing or incompatible constituent quantity.",
                action="Confirm every other constituent as a compatible percentage of this supplier material.",
                constituent=remainder,
            )]
        interval = quantity_interval(quantity)
        if interval.lower is None or interval.upper is None:
            return material, [_issue(
                material,
                code="calculation_withheld",
                message="The qsp/remainder value cannot be bounded from the reported constituent quantities.",
                action="Provide bounded values for every other constituent before deriving the remainder.",
                constituent=remainder,
            )]
        lower_sum += interval.lower
        upper_sum += interval.upper

    lower = target - upper_sum
    upper = target - lower_sum
    if lower < -tolerance or upper < -tolerance or lower > upper:
        return material, [_issue(
            material,
            code="impossible_composition_total",
            message="The reported quantities produce a negative or impossible qsp/remainder value.",
            action="Correct the supplier composition values; Regulens will not clamp the remainder.",
            severity=AssemblyIssueSeverity.ERROR,
            constituent=remainder,
        )]
    lower = max(0.0, lower)
    upper = max(0.0, upper)
    derived = _quantity_from_interval(
        QuantityInterval(lower, upper, True, True, False),
        raw_text=f"Derived from {remainder.composition_quantity.raw_text or f'qsp {target:g}'}",
        basis=remainder.composition_quantity.basis,
        preparation_stage=None,
        quantity_scope="supplier_material",
    )
    updated_rows = [
        constituent.model_copy(update={"composition_quantity": derived})
        if constituent.constituent_id == remainder.constituent_id else constituent
        for constituent in material.constituents
    ]
    return material.model_copy(update={"constituents": updated_rows}), []


def validate_material_composition(
    material: SupplierMaterial,
    *,
    tolerance: float = COMPOSITION_ROUNDING_TOLERANCE_PERCENT,
) -> tuple[SupplierMaterial, list[AssemblyIssue]]:
    material, issues = _derive_remainder(material, tolerance=tolerance)
    if issues:
        return material, issues

    intervals: list[QuantityInterval] = []
    exact_values: list[float] = []
    all_exact = True
    for constituent in material.constituents:
        quantity = constituent.composition_quantity
        if quantity is None:
            continue
        reversed_range = _reversed_percentage_range(quantity)
        if reversed_range is not None:
            lower, upper = reversed_range
            issues.append(_issue(
                material,
                code="invalid_concentration_bound",
                message=(
                    f"The reported range for {constituent.submitted_name} is invalid: "
                    f"the lower bound {lower:g}% exceeds the upper bound {upper:g}%."
                ),
                action=(
                    "Correct the range from the governing supplier document. Regulens will not "
                    "swap the endpoints or calculate this contribution."
                ),
                severity=AssemblyIssueSeverity.ERROR,
                constituent=constituent,
            ))
            continue
        if not is_percent(quantity):
            continue
        interval = quantity_interval(quantity)
        supplied_bounds = [
            value for value in (quantity.value, quantity.lower, quantity.upper)
            if value is not None
        ]
        if any(value > 100 for value in supplied_bounds):
            issues.append(_issue(
                material,
                code="invalid_concentration_bound",
                message=(
                    f"The reported amount for {constituent.submitted_name} is outside the valid "
                    "0% to 100% range."
                ),
                action="Correct the reported percentage or range using the supplier document.",
                severity=AssemblyIssueSeverity.ERROR,
                constituent=constituent,
            ))
            continue
        intervals.append(interval)
        if quantity.kind == CompositionQuantityKind.EXACT and quantity.value is not None:
            exact_values.append(quantity.value)
        else:
            all_exact = False

    exact_total = sum(exact_values)
    minimum_total = sum(interval.lower or 0 for interval in intervals)
    if exact_total > 100 + tolerance or minimum_total > 100 + tolerance:
        issues.append(_issue(
            material,
            code="impossible_composition_total",
            message="The ingredient percentages in this supplier document add up to more than 100%.",
            action="Check the percentages and confirm that every row belongs to this raw material.",
            severity=AssemblyIssueSeverity.ERROR,
        ))
    elif (
        material.disclosure_status == DisclosureStatus.COMPLETE
        and all_exact
        and material.constituents
        and exact_total < 100 - tolerance
    ):
        missing_total = 100 - exact_total
        issues.append(_issue(
            material,
            code="incomplete_supplier_disclosure",
            message=(
                f"This supplier file describes the disclosed ingredients as complete, but the exact "
                f"percentages shown total {exact_total:g}%."
            ),
            action=(
                f"Regulens will not invent the remaining {missing_total:g}%. Screening covers the "
                "ingredients and amounts actually disclosed."
            ),
            severity=AssemblyIssueSeverity.WARNING,
            blocking=False,
        ))
    return material, issues


def _compatible_for_calculation(
    material_usage: CompositionQuantity,
    constituent_quantity: CompositionQuantity,
) -> bool:
    return (
        is_percent(material_usage)
        and _mass_fraction_unit(constituent_quantity) is not None
        and material_usage.quantity_scope == "finished_product"
        and constituent_quantity.quantity_scope == "supplier_material"
        and _token(material_usage.preparation_stage) in {"finished_product", "finished product"}
    )


def calculate_material_contributions(
    material: SupplierMaterial,
) -> tuple[SupplierMaterial, list[CalculatedContribution], list[AssemblyIssue]]:
    material, issues = validate_material_composition(material)
    if material.conflicting_document_ids:
        issues.append(_issue(
            material,
            code="composition_statement_conflict",
            message=f"More than one file describes {material.trade_name}, and the ingredient lists differ.",
            action=f"Choose the one current supplier file for {material.trade_name}. Regulens will ignore the other revision.",
            severity=AssemblyIssueSeverity.ERROR,
        ))
    if material.disclosure_status != DisclosureStatus.COMPLETE:
        issues.append(_issue(
            material,
            code="incomplete_supplier_disclosure",
            message=f"The document for {material.trade_name} may list only some of its ingredients.",
            action="Regulens will screen the disclosed ingredients and record that the supplier disclosure is partial.",
            severity=AssemblyIssueSeverity.WARNING,
            blocking=False,
        ))
    if material.confirmation_status != ConfirmationStatus.CONFIRMED:
        issues.append(_issue(
            material,
            code="unresolved_raw_material",
            message=f"Regulens could not confidently connect {material.trade_name} to a supplier file.",
            action=f"Choose the supplier file that describes {material.trade_name}.",
        ))
    if material.governing_document_id is None:
        issues.append(_issue(
            material,
            code="document_association_unconfirmed",
            message=f"No current supplier file is selected for {material.trade_name}.",
            action=f"Choose the supplier file for {material.trade_name} that applies to this formulation.",
        ))
    usage = material.finished_product_usage
    if usage is None:
        issues.append(_issue(
            material,
            code="material_usage_missing",
            message=f"Finished-product usage is missing for {material.trade_name}.",
            action=f"Enter the percentage of {material.trade_name} used in the finished product.",
        ))

    contributions: list[CalculatedContribution] = []
    for constituent in material.constituents:
        quantity = constituent.composition_quantity
        if quantity is None or quantity.kind in {
            CompositionQuantityKind.UNKNOWN,
            CompositionQuantityKind.CODED_RANGE,
            CompositionQuantityKind.REMAINDER_TO_TOTAL,
        }:
            if _reversed_percentage_range(quantity) is not None:
                # validate_material_composition already emitted the precise,
                # actionable error. Do not dilute it with a generic "could not
                # be read" message for the same source row.
                continue
            partial_evidence = material.disclosure_status != DisclosureStatus.COMPLETE
            issues.append(_issue(
                material,
                code="constituent_concentration_missing",
                message=f"The amount of {constituent.submitted_name} inside {material.trade_name} could not be read.",
                action=(
                    "Regulens will preserve this constituent without inventing an amount and will limit "
                    "any concentration-dependent check."
                    if partial_evidence else
                    f"Enter the percentage or range for {constituent.submitted_name} shown in the supplier file."
                ),
                severity=(
                    AssemblyIssueSeverity.WARNING
                    if partial_evidence else AssemblyIssueSeverity.REVIEW_REQUIRED
                ),
                constituent=constituent,
                blocking=not partial_evidence,
            ))
            continue
        if not constituent.verified_identity_group:
            partial_evidence = material.disclosure_status != DisclosureStatus.COMPLETE
            issues.append(_issue(
                material,
                code="constituent_identity_unresolved",
                message=f"Regulens could not confidently identify {constituent.submitted_name}.",
                action=(
                    "Regulens will preserve the submitted name but cannot perform identity-based checks "
                    "for this constituent."
                    if partial_evidence else
                    f"Confirm the ingredient name and optional CAS number for {constituent.submitted_name}."
                ),
                severity=(
                    AssemblyIssueSeverity.WARNING
                    if partial_evidence else AssemblyIssueSeverity.REVIEW_REQUIRED
                ),
                constituent=constituent,
                blocking=not partial_evidence,
            ))
            continue
        if usage is None or material.governing_document_id is None:
            continue
        if not _compatible_for_calculation(usage, quantity):
            issues.append(_issue(
                material,
                code="incompatible_quantity_basis",
                message=f"The amount for {constituent.submitted_name} uses units that cannot be combined safely.",
                action=(
                    "Confirm that the supplier amount uses %, ppm or mg/kg for the raw material, and that "
                    "the material usage is a percentage of the finished product."
                ),
                constituent=constituent,
            ))
            continue
        finished = multiply_percentage_quantities(usage, quantity)
        contributions.append(CalculatedContribution(
            contribution_id=(
                f"material:{material.material_id}:constituent:{constituent.constituent_id}:"
                f"document:{material.governing_document_id}"
            ),
            source_type="material_constituent",
            source_material_id=material.material_id,
            source_constituent_id=constituent.constituent_id,
            governing_document_id=material.governing_document_id,
            verified_identity_group=constituent.verified_identity_group,
            display_name=constituent.submitted_name,
            cas_number=constituent.cas_number,
            regulated_functions=constituent.regulated_functions,
            composition_quantity=quantity,
            material_usage=usage,
            finished_product_quantity=finished,
            calculation_formula=(
                f"{quantity_label(usage)} × {quantity_label(quantity)} ÷ 100 = "
                f"{quantity_label(finished)}"
            ),
            source_evidence=constituent.source_evidence,
        ))
    return material, contributions, issues


def aggregate_contributions(
    contributions: Iterable[CalculatedContribution],
) -> tuple[list[AggregatedIngredient], list[AssemblyIssue]]:
    groups: dict[str, list[CalculatedContribution]] = defaultdict(list)
    for contribution in contributions:
        groups[contribution.verified_identity_group].append(contribution)

    aggregates: list[AggregatedIngredient] = []
    issues: list[AssemblyIssue] = []
    for identity_group, items in sorted(groups.items()):
        cas_numbers = {item.cas_number for item in items if item.cas_number}
        original_units = {
            _mass_fraction_unit(item.finished_product_quantity)
            for item in items
        }
        convertible_units = None not in original_units
        normalized_items = items
        if convertible_units and len(original_units) > 1:
            normalized_items = [
                item.model_copy(update={
                    "finished_product_quantity": _as_percent(item.finished_product_quantity),
                })
                for item in items
            ]
        semantics = {
            (
                _token(item.finished_product_quantity.unit),
                _token(item.finished_product_quantity.basis),
                _token(item.finished_product_quantity.preparation_stage),
                item.finished_product_quantity.quantity_scope,
            )
            for item in normalized_items
        }
        if not convertible_units or len(semantics) != 1 or len(cas_numbers) > 1:
            issues.append(AssemblyIssue(
                issue_id=f"unverified_identity_aggregation:{identity_group}",
                code="unverified_identity_aggregation",
                severity=AssemblyIssueSeverity.REVIEW_REQUIRED,
                scope=AssemblyIssueScope.CALCULATION,
                message=f"Regulens found {items[0].display_name} in more than one place, but cannot safely add the amounts together.",
                reviewer_action=(
                    "Confirm that the entries are the same ingredient and use compatible %, ppm or mg/kg "
                    "mass-fraction units with the same chemical basis."
                ),
                blocking_for_calculation=True,
                material_ids=sorted({item.source_material_id for item in items if item.source_material_id}),
                constituent_ids=sorted({item.source_constituent_id for item in items if item.source_constituent_id}),
                document_ids=sorted({item.governing_document_id for item in items}),
            ))
            continue
        aggregate = add_percentage_quantities(
            item.finished_product_quantity for item in normalized_items
        )
        aggregates.append(AggregatedIngredient(
            verified_identity_group=identity_group,
            display_name=items[0].display_name,
            cas_number=next(iter(cas_numbers), None),
            regulated_functions=sorted(
                {function for item in items for function in item.regulated_functions},
                key=lambda function: function.value,
            ),
            aggregate_quantity=aggregate,
            contributions=normalized_items,
            completeness=AssemblyCompleteness.COMPLETE,
        ))
    return aggregates, issues
