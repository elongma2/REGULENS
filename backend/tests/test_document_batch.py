from __future__ import annotations

import pytest

from backend.app.services.agent_csv import ParsedCSV
from backend.app.services.document_batch import DocumentBatchError, select_primary_formulation


def _parsed(filename: str, rows: list[tuple[str, ...]]) -> ParsedCSV:
    return ParsedCSV(filename=filename, delimiter=",", rows=tuple(rows))


def test_selects_finished_formulation_among_supplier_documents() -> None:
    supplier = _parsed("supplier.csv", [
        ("Product Name: OPTASENSE",),
        ("INCI Name", "CAS No.", "FDA Code"),
        ("GLYCERIN", "56-81-5", "C"),
    ])
    formulation = _parsed("formula.csv", [
        ("Ingredient", "Concentration"),
        ("OPTASENSE", "2%"),
        ("AQUA", "98%"),
    ])

    assert select_primary_formulation([supplier, formulation]) == 1


def test_rejects_multiple_ingredient_lists_without_a_clear_finished_formulation() -> None:
    one = _parsed("one.csv", [("Ingredient", "Concentration"), ("AQUA", "100%")])
    two = _parsed("two.csv", [("INCI", "%"), ("GLYCERIN", "5")])

    with pytest.raises(DocumentBatchError) as error:
        select_primary_formulation([one, two])
    assert error.value.code == "multiple_ingredient_lists"


def test_explicit_finished_formulation_wins_over_supporting_ingredient_list() -> None:
    formulation = _parsed("finished.csv", [
        ("Finished product formulation",),
        ("Ingredient", "Amount used"),
        ("OPTASENSE", "2%"),
        ("AQUA", "98%"),
    ])
    ingredient_list = _parsed("inci-list.csv", [
        ("INCI", "Concentration"),
        ("GLYCERIN", "5%"),
    ])

    assert select_primary_formulation([ingredient_list, formulation]) == 1


def test_rejects_two_explicit_finished_formulations() -> None:
    first = _parsed("first.csv", [
        ("Finished product formulation",),
        ("Ingredient", "Amount used"),
        ("AQUA", "100%"),
    ])
    second = _parsed("second.csv", [
        ("Finished product formulation",),
        ("Ingredient", "Amount used"),
        ("GLYCERIN", "5%"),
    ])

    with pytest.raises(DocumentBatchError) as error:
        select_primary_formulation([first, second])
    assert error.value.code == "multiple_finished_formulations"


def test_rejects_supplier_only_batch_without_a_finished_formulation() -> None:
    supplier = _parsed("supplier.csv", [
        ("Supplier: Example Materials",),
        ("Product Name: OPTASENSE",),
        ("INCI Name", "CAS No.", "FDA Code"),
        ("GLYCERIN", "56-81-5", "C"),
    ])
    sds = _parsed("sds.pdf", [
        ("SAFETY DATA SHEET",),
        ("SECTION 3 Composition / information on ingredients",),
        ("Water 7732-18-5 40-60%",),
    ])

    with pytest.raises(DocumentBatchError) as error:
        select_primary_formulation([supplier, sds])
    assert error.value.code == "supplier_document_without_formulation"


def test_single_sds_is_not_silently_treated_as_the_finished_formulation() -> None:
    sds = _parsed("sds.pdf", [
        ("SAFETY DATA SHEET",),
        ("SECTION 3 Composition / information on ingredients",),
        ("Chemical name", "CAS No.", "Concentration"),
        ("Water", "7732-18-5", "40-60%"),
    ])

    with pytest.raises(DocumentBatchError) as error:
        select_primary_formulation([sds])

    assert error.value.code == "supplier_document_without_formulation"


def test_legacy_single_file_path_remains_unchanged() -> None:
    document = _parsed("legacy.csv", [("Anything",), ("A",)])
    assert select_primary_formulation([document], legacy_first_file=True) == 0
