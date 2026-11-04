from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.app.models.formulation import FormulationScreeningResponse


BRAND = colors.HexColor("#0F766E")
BRAND_DARK = colors.HexColor("#134E4A")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#64748B")
BORDER = colors.HexColor("#DCE5E0")
SOFT = colors.HexColor("#F4F8F6")
WARNING = colors.HexColor("#92400E")
ADVERSE = colors.HexColor("#B91C1C")
SUCCESS = colors.HexColor("#166534")

FINDING_LABELS = {
    "no_issue_identified_within_scoped_rules": "No issue identified within scoped rules",
    "restriction_within_limit": "Restriction within limit",
    "restriction_exceeded": "Restriction limit exceeded",
    "prohibited_substance_identified": "Prohibited-list substance identified",
    "information_missing": "Information missing",
    "identity_unresolved": "Identity unresolved",
    "professional_review_required": "Professional review required",
    "permitted_use_within_conditions": "Permitted use within listed conditions",
    "permitted_use_condition_not_met": "Permitted-use condition not met",
    "regulated_function_not_permitted": "Regulated function not permitted",
}

ADVERSE_FINDINGS = {
    "restriction_exceeded",
    "prohibited_substance_identified",
    "permitted_use_condition_not_met",
    "regulated_function_not_permitted",
}
ATTENTION_FINDINGS = ADVERSE_FINDINGS | {"information_missing", "identity_unresolved", "professional_review_required"}


def _text(value: object | None, fallback: str = "Not supplied") -> str:
    if value is None:
        return fallback
    rendered = str(value).strip()
    return rendered or fallback


def _safe(value: object | None, fallback: str = "Not supplied") -> str:
    return escape(_text(value, fallback))


def _filename(value: str | None) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "screening-report").strip()).strip("-._")
    return f"{base or 'screening-report'}-screening-report.pdf"


def screening_report_filename(response: FormulationScreeningResponse) -> str:
    return _filename(response.formulation.formulation_id or response.formulation.formulation_name)


def _concentration(result) -> str:
    value = result.submitted_ingredient.concentration
    if value is None:
        return "Not supplied"
    unit = "%" if value.unit == "percent" else value.unit
    basis = f" as {value.basis}" if value.basis else ""
    stage = value.preparation_stage.replace("_", " ")
    return f"{value.value:g} {unit}{basis} ({stage})"


def _finding_colour(finding: str):
    if finding in ADVERSE_FINDINGS:
        return ADVERSE
    if finding in {"professional_review_required", "information_missing", "identity_unresolved"}:
        return WARNING
    return SUCCESS


def _requires_attention(result) -> bool:
    return result.review_required or result.primary_finding.value in ATTENTION_FINDINGS


def _styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=23, leading=27, textColor=INK, alignment=TA_LEFT, spaceAfter=4),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=BRAND, tracking=1.2, spaceAfter=12),
        "h2": ParagraphStyle("ReportH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK, spaceBefore=8, spaceAfter=7),
        "detail_title": ParagraphStyle("ReportDetailTitle", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK),
        "body": ParagraphStyle("ReportBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.2, leading=11.2, textColor=INK),
        "small": ParagraphStyle("ReportSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7, leading=9.5, textColor=MUTED),
        "table_header": ParagraphStyle("ReportTableHeader", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=colors.white, alignment=TA_LEFT),
        "table": ParagraphStyle("ReportTable", parent=styles["Normal"], fontName="Helvetica", fontSize=7, leading=9.3, textColor=INK),
        "metric": ParagraphStyle("ReportMetric", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=BRAND_DARK, alignment=TA_CENTER),
        "metric_label": ParagraphStyle("ReportMetricLabel", parent=styles["Normal"], fontName="Helvetica", fontSize=6.8, leading=8.5, textColor=MUTED, alignment=TA_CENTER),
    }


def _page(canvas, document) -> None:
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(14 * mm, 15 * mm, width - 14 * mm, 15 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(14 * mm, 10 * mm, "Regulens - Regulatory Intelligence")
    canvas.drawRightString(width - 14 * mm, 10 * mm, f"Page {document.page}")
    canvas.restoreState()


def _summary_table(response: FormulationScreeningResponse, styles) -> Table:
    summary = response.summary
    metrics = [
        (summary.ingredients_submitted, "Ingredients screened"),
        (summary.total_requiring_review, "Professional review flags"),
        (summary.prohibited_substance_identified + summary.restriction_exceeded + summary.permitted_use_condition_not_met + summary.regulated_function_not_permitted, "Adverse findings"),
        (summary.information_missing + summary.identity_unresolved, "Incomplete results"),
    ]
    cells = [
        [Paragraph(str(value), styles["metric"]) for value, _ in metrics],
        [Paragraph(label, styles["metric_label"]) for _, label in metrics],
    ]
    table = Table(cells, colWidths=[45.5 * mm] * 4, rowHeights=[14 * mm, 8 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _results_table(response: FormulationScreeningResponse, styles) -> LongTable:
    rows = [[Paragraph(value, styles["table_header"]) for value in ("Row", "Ingredient", "Concentration", "Function", "Screening result", "Attention")]]
    finding_colours = []
    for index, result in enumerate(response.ingredient_results, start=1):
        functions = ", ".join(value.value.replace("_", " ") for value in result.submitted_ingredient.regulated_functions) or "Not confirmed"
        finding = result.primary_finding.value
        finding_colours.append((index, _finding_colour(finding)))
        rows.append([
            Paragraph(str(result.submitted_row_number), styles["table"]), Paragraph(_safe(result.submitted_ingredient.name), styles["table"]),
            Paragraph(_safe(_concentration(result)), styles["table"]), Paragraph(_safe(functions), styles["table"]),
            Paragraph(FINDING_LABELS.get(finding, finding.replace("_", " ")), styles["table"]),
            Paragraph("Needs attention" if _requires_attention(result) else "No", styles["table"]),
        ])
    table = LongTable(rows, colWidths=[9 * mm, 40 * mm, 35 * mm, 27 * mm, 46 * mm, 25 * mm], repeatRows=1)
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_DARK), ("GRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for row, colour in finding_colours:
        commands.extend([("TEXTCOLOR", (4, row), (4, row), colour), ("FONTNAME", (4, row), (4, row), "Helvetica-Bold")])
        if row % 2 == 0:
            commands.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor("#FAFCFB")))
    table.setStyle(TableStyle(commands))
    return table


def build_screening_report(
    response: FormulationScreeningResponse,
    *,
    jurisdiction: str = "Singapore",
    screening_reference: str | None = None,
    screened_at: datetime | None = None,
) -> bytes:
    styles = _styles()
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm, topMargin=15 * mm, bottomMargin=21 * mm,
        title="Regulens Screening Report", author="Regulens", subject="Singapore cosmetic formulation screening results",
    )
    timestamp = screened_at or datetime.now(UTC)
    formulation = response.formulation
    story = [Paragraph("REGULENS / REGULATORY INTELLIGENCE", styles["subtitle"]), Paragraph("Formulation Screening Report", styles["title"])]
    metadata = [
        ["Formulation ID", _text(formulation.formulation_id), "Formulation name", _text(formulation.formulation_name)],
        ["Product context", _text(formulation.product_context), "Jurisdiction", jurisdiction],
        ["Screened at", timestamp.astimezone(UTC).strftime("%d %b %Y, %H:%M UTC"), "Screening reference", _text(screening_reference, "Ad-hoc screening")],
    ]
    meta_table = Table(metadata, colWidths=[28 * mm, 63 * mm, 30 * mm, 61 * mm])
    meta_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("BACKGROUND", (0, 0), (-1, -1), SOFT), ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.extend([
        meta_table, Spacer(1, 6 * mm), Paragraph("Screening summary", styles["h2"]), _summary_table(response, styles),
        Spacer(1, 5 * mm), Paragraph("Ingredient screening results", styles["h2"]), _results_table(response, styles),
        Spacer(1, 5 * mm), Paragraph("Dataset traceability", styles["h2"]),
        Paragraph(
            f"Accepted dataset: <b>{response.dataset.dataset_version}</b><br/>Accepted baseline SHA-256: {response.dataset.accepted_baseline_sha256}<br/>"
            f"Identity catalogue: {_safe(response.dataset.identity_catalogue.dataset_version, 'Unavailable')}", styles["body"],
        ), PageBreak(), Paragraph("Result details", styles["title"]),
        Paragraph("Evidence and review notes for each submitted ingredient.", styles["small"]), Spacer(1, 3 * mm),
    ])

    for index, result in enumerate(response.ingredient_results):
        finding = result.primary_finding.value
        explanation = result.review_explanation
        review_guidance = (
            f"{explanation.title}: {explanation.summary}"
            if explanation is not None
            else "No additional professional-review guidance was generated."
        )
        evidence = [f"{item.evidence.regulatory_section} reference {item.evidence.reference_number}" for item in result.rule_evaluations]
        detail_table = Table([
                [Paragraph(f"Row {result.submitted_row_number} - {_safe(result.submitted_ingredient.name)}", styles["detail_title"]), ""],
                [Paragraph("Result", styles["table_header"]), Paragraph(FINDING_LABELS.get(finding, finding.replace("_", " ")), styles["body"])],
                [Paragraph("Submitted", styles["table_header"]), Paragraph(f"{_safe(_concentration(result))}; CAS {_safe(result.submitted_ingredient.cas_number)}", styles["body"])],
                [Paragraph("Identity", styles["table_header"]), Paragraph(result.identity.status.value.replace("_", " "), styles["body"])],
                [Paragraph("Attention", styles["table_header"]), Paragraph("Needs attention" if _requires_attention(result) else "No", styles["body"])],
            ], colWidths=[31 * mm, 151 * mm], style=TableStyle([
                ("SPAN", (0, 0), (-1, 0)),
                ("BACKGROUND", (0, 1), (0, -1), BRAND_DARK), ("GRID", (0, 1), (-1, -1), 0.4, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 1), (-1, -1), 5),
                ("RIGHTPADDING", (0, 1), (-1, -1), 5), ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, 0), 0), ("RIGHTPADDING", (0, 0), (-1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, 0), 8), ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
            ]))
        block = [
            detail_table, Spacer(1, 2 * mm),
            Paragraph(f"<b>Review guidance:</b> {_safe(review_guidance)}", styles["body"]),
            Paragraph(f"<b>Regulatory evidence:</b> {_safe(', '.join(evidence) if evidence else 'No matched executable rule.')}", styles["body"]),
            Paragraph(f"<b>Scope:</b> {_safe(result.scope_note)}", styles["small"]), Spacer(1, 4 * mm),
        ]
        if index < len(response.ingredient_results) - 1:
            block.append(Table([[""]], colWidths=[182 * mm], rowHeights=[0.2 * mm], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), BORDER)])))
        story.append(CondPageBreak(70 * mm))
        story.extend(block)

    story.extend([
        Spacer(1, 5 * mm), Paragraph("Important scope statement", styles["h2"]),
        Paragraph(
            "This report records an initial Singapore formulation screening within the implemented accepted rules. "
            "It is not a product approval, safety assessment, label review, or complete compliance determination. "
            "Professional review remains necessary wherever identified and for requirements outside the screening scope.", styles["body"],
        ),
    ])
    document.build(story, onFirstPage=_page, onLaterPages=_page)
    return output.getvalue()
