from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import logging
import re
import threading
from typing import Any

from openai import OpenAI
from pydantic import Field, ValidationError

from backend.app.models.formulation import FormulationScreeningResponse, ReviewExplanationMetadata
from backend.app.models.openai import OpenAIUsage
from backend.app.models.screening import ReviewExplanation, ReviewExplanationItem, ReviewType, StrictModel


LOGGER = logging.getLogger(__name__)
MAX_MODEL_EXPLANATIONS = 50
MAX_CACHE_ENTRIES = 512
PROHIBITED_CLAIMS = re.compile(
    r"\b(?:allow(?:ed)?|permit(?:ted)?|approv(?:ed|al)?|compliant|compliance|legal|safe|unsafe|safety)\b",
    re.IGNORECASE,
)
PROHIBITED_JARGON = re.compile(
    r"\b(?:conditional wording|cited entry|corroborated identity|identifier evidence|"
    r"structure automatically|professional verification requested|applicable regulatory provision|"
    r"exception conditions associated with the entry)\b",
    re.IGNORECASE,
)
NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?")

EXPLANATION_INSTRUCTIONS = """You rewrite an existing deterministic cosmetic screening review result in plain English.
You do not perform regulatory analysis and you do not change the result, finding, review requirement, identity_outcome, identifier evidence, or reviewer action. Use only facts supplied for each item. Do not infer missing facts, values, thresholds, identities, rules, or applicability.

Write for a cosmetic compliance user who is not a software engineer. Use short sentences, simple words, and direct phrasing. The summary must say what Regulens already knows and what is still unknown. what_to_check must give one concrete action, normally beginning with "Check" or "Confirm". For example, say "This rule has an exception" rather than "conditional wording needs review", and say "The name and CAS do not match" rather than "identifier evidence needs review".

Do not use these phrases: conditional wording, cited entry, corroborated identity, identifier evidence, structure automatically, professional verification requested, applicable regulatory provision, or exception conditions associated with the entry. Never say an ingredient or product is allowed, permitted, approved, compliant, legal, safe, or unsafe.

Keep titles to eight words or fewer, summaries to one or two short sentences, and actions to one short sentence. submitted_fact and regulatory_fact must be copied exactly from the allowed fact fields or returned as null. Return only the strict structured output."""


class _ExplanationItem(StrictModel):
    item_id: str
    title: str = Field(max_length=80)
    summary: str = Field(max_length=500)
    what_to_check: str | None = Field(max_length=300)
    submitted_fact: str | None = Field(max_length=200)
    regulatory_fact: str | None = Field(max_length=300)


class _ExplanationBatch(StrictModel):
    explanations: list[_ExplanationItem]


def _display_unit(unit: str | None) -> str:
    return "%" if unit == "percent" else (unit or "")


def _stage_label(stage: str | None) -> str | None:
    return {
        "finished_product": "Finished product",
        "after_mixing": "After mixing for use",
        "ready_for_use": "Ready for use",
    }.get(stage or "")


def _identity_submitted_fact(result) -> str | None:
    submitted = result.submitted_ingredient
    parts = []
    if submitted.name:
        parts.append(f"Name: {submitted.name}")
    if submitted.cas_number:
        parts.append(f"CAS: {submitted.cas_number}")
    return " · ".join(parts) or None


def _source_identity_fact(result) -> str | None:
    submitted_name = result.submitted_ingredient.name
    if not submitted_name:
        return None
    for candidate in [*result.identity.singapore_candidates, *result.identity.acd_candidates]:
        if "exact_name" in candidate.match_methods and candidate.cas_numbers:
            return f"Source CAS for {submitted_name}: {', '.join(candidate.cas_numbers)}"
    return None


def _submitted_fact(result) -> str | None:
    if ReviewType.IDENTITY in result.review_types:
        return _identity_submitted_fact(result)
    concentration = result.submitted_ingredient.concentration
    if concentration is None:
        return None
    unit = _display_unit(concentration.unit)
    suffix = unit if unit == "%" else f" {unit}" if unit else ""
    if concentration.original_text:
        value = concentration.original_text
    elif concentration.concentration_type.value == "range":
        value = f"{concentration.lower_bound:g}–{concentration.upper_bound:g}{suffix}"
    elif concentration.concentration_type.value == "upper_bound":
        marker = "≤" if concentration.upper_inclusive else "<"
        value = f"{marker}{concentration.upper_bound:g}{suffix}"
    elif concentration.concentration_type.value == "lower_bound":
        marker = "≥" if concentration.lower_inclusive else ">"
        value = f"{marker}{concentration.lower_bound:g}{suffix}"
    elif concentration.concentration_type.value == "approximate":
        value = f"Approximately {concentration.value:g}{suffix}"
    elif concentration.concentration_type.value == "unknown":
        value = "Concentration not disclosed"
    else:
        value = f"{concentration.value:g}{suffix}"
    stage = _stage_label(concentration.preparation_stage)
    return f"{value} · {stage}" if stage else value


def _regulatory_fact(result) -> str | None:
    if ReviewType.IDENTITY in result.review_types:
        return _source_identity_fact(result)
    facts: list[str] = []
    for evaluation in result.rule_evaluations:
        concentration = evaluation.evidence.concentration
        if concentration and isinstance(concentration.get("value"), (int, float)):
            unit = _display_unit(concentration.get("unit"))
            value = f"{concentration['value']:g}{unit if unit == '%' else f' {unit}'}".strip()
            stage = _stage_label(concentration.get("preparation_stage"))
            prefix = "Rule limit"
            comparator = concentration.get("comparator")
            if comparator == "less_than_or_equal":
                prefix = "Maximum"
            context = evaluation.evidence.product_context
            fact = f"{prefix} {value}"
            if context:
                fact = f"{fact} ({context})"
            elif stage:
                fact = f"{fact} · {stage}"
            if fact not in facts:
                facts.append(fact)
        if evaluation.evidence.product_context:
            fact = f"Rule context: {evaluation.evidence.product_context}"
            if fact not in facts and not concentration:
                facts.append(fact)
    return "; ".join(facts)[:300] or None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        key = " ".join(value.casefold().split()).rstrip(".")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(value)
    return output


def _legacy_fallback_explanation(result) -> ReviewExplanation:
    reasons = " ".join(result.review_reasons).casefold()
    submitted = _submitted_fact(result)
    regulatory = _regulatory_fact(result)
    if result.primary_finding.value == "regulated_function_not_permitted":
        functions = ", ".join(item.value.replace("_", " ") for item in result.submitted_ingredient.regulated_functions)
        return ReviewExplanation(
            title="Regulated use needs attention",
            summary=f"The ingredient was submitted for use as {functions or 'a regulated function'}, but no matching entry was found in the current Singapore list.",
            what_to_check="Confirm the ingredient identity and its intended function against the Singapore source.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if result.primary_finding.value == "permitted_use_condition_not_met":
        return ReviewExplanation(
            title="Listed use condition is not met",
            summary="The submitted use does not meet one or more conditions in the Singapore entry.",
            what_to_check="Check the submitted function, concentration, and product use against the source conditions.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if ReviewType.IDENTITY in result.review_types:
        outcome = result.identity.identity_outcome.value
        if outcome == "genuine_name_cas_conflict":
            return ReviewExplanation(
                title="Name and CAS do not match",
                summary="The submitted name and CAS number match different source-backed ingredient identities.",
                what_to_check="Confirm the correct ingredient name and CAS number.",
                submitted_fact=submitted,
                regulatory_fact=regulatory,
                source="deterministic_fallback",
            )
        if outcome == "name_recognised_cas_unverified":
            return ReviewExplanation(
                title="CAS association is not verified",
                summary="Regulens recognises the submitted ingredient name, but the accepted sources do not independently link the submitted CAS to that name.",
                what_to_check="Check the CAS against the supplier specification if the CAS is needed for this review.",
                submitted_fact=submitted,
                regulatory_fact=regulatory,
                source="deterministic_fallback",
            )
        if outcome == "cas_recognised_name_unverified":
            return ReviewExplanation(
                title="Ingredient name needs confirmation",
                summary="The submitted CAS matches a source-backed ingredient, but the accepted identity sources do not yet confirm the submitted name relationship.",
                what_to_check="Confirm that the submitted name belongs to the CAS-matched ingredient.",
                submitted_fact=submitted,
                regulatory_fact=regulatory,
                source="deterministic_fallback",
            )
        if outcome == "multiple_possible_identities":
            return ReviewExplanation(
                title="Several identities are possible",
                summary="The submitted identifiers match more than one source-backed ingredient identity.",
                what_to_check="Confirm the exact ingredient identity using the supplier specification.",
                submitted_fact=submitted,
                regulatory_fact=regulatory,
                source="deterministic_fallback",
            )
        return ReviewExplanation(
            title="Ingredient identity needs confirmation",
            summary="The ingredient name and CAS information do not clearly point to one source-backed ingredient.",
            what_to_check="Confirm the correct INCI or common name and CAS number.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if "preparation_stage" in reasons or "preparation stage" in reasons:
        return ReviewExplanation(
            title="Concentration stage needs confirmation",
            summary="The submitted concentration is for one stage, but the rule applies at a different stage.",
            what_to_check="Confirm the concentration at the stage stated in the rule.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if "product context" in reasons or "product_context" in reasons:
        return ReviewExplanation(
            title="Product information is needed",
            summary="More product information is needed before this rule can be checked.",
            what_to_check="Confirm the product type or context stated in the rule.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if "incompatible" in reasons and "unit" in reasons:
        return ReviewExplanation(
            title="Concentration unit needs confirmation",
            summary="The submitted concentration and the rule use different units.",
            what_to_check="Confirm the concentration using the unit stated in the rule.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if "incompatible" in reasons and "basis" in reasons:
        return ReviewExplanation(
            title="Concentration basis needs confirmation",
            summary="The submitted concentration and the rule use different concentration bases.",
            what_to_check="Confirm the concentration using the basis stated in the rule.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if "conditional" in reasons or "condition" in reasons or "exception" in reasons:
        return ReviewExplanation(
            title="Rule exception needs confirmation",
            summary="This rule has an exception that still needs checking.",
            what_to_check="Check whether the exception shown in the regulatory source applies to this formulation.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    if "concentration" in reasons or "information" in reasons or "missing" in reasons:
        return ReviewExplanation(
            title="More product information is needed",
            summary="Regulens needs more product information before it can check this rule.",
            what_to_check="Confirm the missing concentration or product details shown in the rule.",
            submitted_fact=submitted,
            regulatory_fact=regulatory,
            source="deterministic_fallback",
        )
    return ReviewExplanation(
        title="This rule needs confirmation",
        summary="Regulens found a rule but could not confirm how it applies to this formulation.",
        what_to_check="Check the rule details against the submitted formulation.",
        submitted_fact=submitted,
        regulatory_fact=regulatory,
        source="deterministic_fallback",
    )


def fallback_explanation(result) -> ReviewExplanation:
    legacy = _legacy_fallback_explanation(result)
    issues = result.review_issues or []
    if not issues:
        return legacy
    evaluations = {item.rule_id: item for item in result.rule_evaluations}
    items: list[ReviewExplanationItem] = []
    for issue in issues:
        evaluation = evaluations.get(issue.rule_id) if issue.rule_id else None
        facts: list[str] = []
        if evaluation and evaluation.submitted_concentration:
            submitted = evaluation.submitted_concentration
            submitted_text = submitted.original_text or (
                f"{submitted.value:g} {submitted.unit}" if submitted.value is not None else None
            )
            if submitted_text:
                facts.append(f"Submitted concentration: {submitted_text}.")
        if evaluation and evaluation.evidence.concentration:
            limit = evaluation.evidence.concentration
            if limit.get("value") is not None and limit.get("unit"):
                facts.append(f"Recorded source limit: {limit['value']:g} {limit['unit']}.")
        if issue.source_reference:
            facts.append(f"Source: {issue.source_reference}.")
        items.append(ReviewExplanationItem(
            issue_code=issue.code,
            what_happened=issue.message,
            why_it_matters=" ".join(facts) or "This check remains incomplete within the current screening scope.",
            what_to_check=issue.reviewer_action,
            source_references=[issue.source_reference] if issue.source_reference else [],
        ))
    actions = _unique([issue.reviewer_action for issue in issues])
    source_references = _unique([issue.source_reference for issue in issues if issue.source_reference])
    first = issues[0]
    titles = {
        "combined_limit_information_missing": "Combined concentration needs confirmation",
        "impurity_trace_requirement": "Trace impurity needs confirmation",
        "identity_related_forms": "Chemical form needs confirmation",
        "regulated_function_not_listed": "Declared regulated use is not listed",
        "source_difference_material": "Singapore and ACD sources differ",
        "preparation_stage_mismatch": "Concentration stage needs confirmation",
        "concentration_unit_mismatch": "Concentration unit needs confirmation",
        "concentration_basis_mismatch": "Concentration basis needs confirmation",
        "rule_exception_unresolved": "Rule exception needs confirmation",
        "screening_incomplete": "Screening is incomplete",
    }
    adverse_findings = {
        "prohibited_substance_identified",
        "restriction_exceeded",
        "permitted_use_condition_not_met",
        "regulated_function_not_permitted",
    }
    title = legacy.title if result.primary_finding.value in adverse_findings else titles.get(first.code, legacy.title)
    summary = legacy.summary if result.primary_finding.value in adverse_findings else first.message
    return legacy.model_copy(update={
        "title": title,
        "summary": summary,
        "what_to_check": actions[0] if actions else first.reviewer_action,
        "items": items,
        "reviewer_actions": actions,
        "primary_source_references": source_references,
    })


class ReviewExplanationService:
    def __init__(
        self,
        api_key: str | None,
        model: str = "gpt-5.6-luna",
        timeout_seconds: float = 15,
        client_factory=OpenAI,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self._cache: OrderedDict[str, ReviewExplanation] = OrderedDict()
        self._lock = threading.RLock()

    def fallback_only(self, response: FormulationScreeningResponse) -> FormulationScreeningResponse:
        enriched = response.model_copy(deep=True)
        review_results = [result for result in enriched.ingredient_results if result.review_required]
        for result in review_results:
            result.review_explanation = fallback_explanation(result)
        enriched.review_explanation_metadata = ReviewExplanationMetadata(
            configured=bool(self.api_key),
            configured_model=self.model,
            status="fallback" if review_results else "not_needed",
            requested_count=len(review_results),
            fallback_count=len(review_results),
        )
        return enriched

    def enrich(self, response: FormulationScreeningResponse) -> FormulationScreeningResponse:
        enriched = response.model_copy(deep=True)
        review_results = [result for result in enriched.ingredient_results if result.review_required]
        if not review_results:
            enriched.review_explanation_metadata = ReviewExplanationMetadata(
                configured=bool(self.api_key), configured_model=self.model, status="not_needed",
            )
            return enriched

        # Standard outcomes use source-backed deterministic templates. The
        # optional model is retained only for historical/unknown results that
        # do not yet carry structured review issues.
        model_candidates = [result for result in review_results if not result.review_issues]
        eligible = model_candidates[:MAX_MODEL_EXPLANATIONS]
        truncated = model_candidates[MAX_MODEL_EXPLANATIONS:]
        payloads = [self._payload(result) for result in eligible]
        cached: dict[str, ReviewExplanation] = {}
        missing: list[tuple[Any, dict[str, Any], str]] = []
        for result, payload in zip(eligible, payloads, strict=True):
            key = self._cache_key(payload)
            cached_value = self._cache_get(key)
            if cached_value is None:
                missing.append((result, payload, key))
            else:
                cached[str(result.submitted_row_number)] = cached_value

        generated: dict[str, ReviewExplanation] = {}
        usage: OpenAIUsage | None = None
        actual_model: str | None = None
        if missing and self.api_key:
            try:
                generated, usage, actual_model = self._generate([payload for _, payload, _ in missing])
                for result, _, key in missing:
                    explanation = generated[str(result.submitted_row_number)]
                    self._cache_put(key, explanation)
            except Exception as error:
                LOGGER.warning("Review explanation generation failed (%s); deterministic fallback retained", type(error).__name__)

        if usage is None and cached:
            usage = OpenAIUsage(
                configured_model=self.model,
                actual_model=self.model,
                cache_hits=len(cached),
            )
        elif usage is not None:
            usage.cache_hits = len(cached)

        model_count = 0
        fallback_count = 0
        for result in review_results:
            item_id = str(result.submitted_row_number)
            explanation = cached.get(item_id) or generated.get(item_id)
            if explanation is None:
                explanation = fallback_explanation(result)
                fallback_count += 1
            else:
                model_count += 1
            result.review_explanation = explanation

        status = "model" if model_count and not fallback_count else ("mixed" if model_count else "fallback")
        enriched.review_explanation_metadata = ReviewExplanationMetadata(
            configured=bool(self.api_key),
            configured_model=self.model,
            actual_model=actual_model,
            status=status,
            requested_count=len(review_results),
            model_count=model_count,
            fallback_count=fallback_count,
            truncated_count=len(truncated),
            usage=usage,
        )
        return enriched

    def _payload(self, result) -> dict[str, Any]:
        submitted_fact = _submitted_fact(result)
        regulatory_fact = _regulatory_fact(result)
        return {
            "item_id": str(result.submitted_row_number),
            "primary_finding": result.primary_finding,
            "review_types": result.review_types,
            "review_reasons": result.review_reasons,
            "review_issues": [item.model_dump(mode="json") for item in result.review_issues],
            "identity_outcome": result.identity.identity_outcome,
            "identifier_evidence": [item.model_dump(mode="json") for item in result.identity.identifier_evidence],
            "applicable_regulatory_record_ids": result.identity.applicable_regulatory_record_ids,
            "reviewer_action": result.identity.reviewer_action,
            "submitted": {
                "ingredient": result.submitted_ingredient.model_dump(mode="json"),
                "product_context": result.submitted_product_context,
            },
            "allowed_submitted_fact": submitted_fact,
            "allowed_regulatory_fact": regulatory_fact,
            "rule_evaluations": [
                {
                    "evaluation_status": evaluation.evaluation_status,
                    "reasons": evaluation.reasons,
                    "rule_id": evaluation.rule_id,
                    "section": evaluation.evidence.regulatory_section,
                    "reference": evaluation.evidence.reference_number,
                    "source_version": evaluation.evidence.source_version,
                    "substance_name": evaluation.evidence.substance_name,
                    "product_context": evaluation.evidence.product_context,
                    "concentration": evaluation.evidence.concentration,
                    "other_conditions": evaluation.evidence.other_conditions,
                    "required_warning": evaluation.evidence.required_warning,
                    "source_text": evaluation.evidence.source_text[:2_000],
                }
                for evaluation in result.rule_evaluations
            ],
        }

    def _generate(self, payloads: list[dict[str, Any]]) -> tuple[dict[str, ReviewExplanation], OpenAIUsage, str | None]:
        response = self.client_factory(api_key=self.api_key, timeout=self.timeout_seconds).responses.create(
            model=self.model,
            instructions=EXPLANATION_INSTRUCTIONS,
            input=[{"role": "user", "content": json.dumps({"review_items": payloads}, ensure_ascii=False)}],
            tools=[],
            store=False,
            text={"format": {
                "type": "json_schema",
                "name": "review_explanations",
                "strict": True,
                "schema": _ExplanationBatch.model_json_schema(),
            }},
        )
        try:
            batch = _ExplanationBatch.model_validate_json(response.output_text)
        except (ValidationError, ValueError) as error:
            raise ValueError("Explanation model returned invalid structured output") from error
        expected = {payload["item_id"] for payload in payloads}
        if {item.item_id for item in batch.explanations} != expected or len(batch.explanations) != len(expected):
            raise ValueError("Explanation model did not return one result per review item")
        payload_by_id = {payload["item_id"]: payload for payload in payloads}
        explanations: dict[str, ReviewExplanation] = {}
        for item in batch.explanations:
            payload = payload_by_id[item.item_id]
            self._validate_explanation(item, payload)
            explanations[item.item_id] = ReviewExplanation(
                title=item.title,
                summary=item.summary,
                what_to_check=item.what_to_check,
                submitted_fact=item.submitted_fact,
                regulatory_fact=item.regulatory_fact,
                source="model",
            )
        raw_usage = getattr(response, "usage", None)
        usage = OpenAIUsage(
            configured_model=self.model,
            actual_model=getattr(response, "model", None),
            input_tokens=int(getattr(raw_usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(raw_usage, "output_tokens", 0) or 0),
            total_tokens=int(getattr(raw_usage, "total_tokens", 0) or 0),
            request_rounds=1,
        )
        LOGGER.info(
            "Review explanations: model=%s input_tokens=%s output_tokens=%s items=%s",
            usage.actual_model or self.model,
            usage.input_tokens,
            usage.output_tokens,
            len(explanations),
        )
        return explanations, usage, usage.actual_model

    @staticmethod
    def _validate_explanation(item: _ExplanationItem, payload: dict[str, Any]) -> None:
        if len(item.title.split()) > 8:
            raise ValueError("Explanation title exceeds eight words")
        combined = " ".join(filter(None, [item.title, item.summary, item.what_to_check, item.submitted_fact, item.regulatory_fact]))
        if PROHIBITED_CLAIMS.search(combined):
            raise ValueError("Explanation contains a prohibited conclusion")
        if PROHIBITED_JARGON.search(combined):
            raise ValueError("Explanation contains technical review jargon")
        if item.submitted_fact not in {None, payload["allowed_submitted_fact"]}:
            raise ValueError("Explanation changed the submitted fact")
        if item.regulatory_fact not in {None, payload["allowed_regulatory_fact"]}:
            raise ValueError("Explanation changed the regulatory fact")
        grounding_payload = {key: value for key, value in payload.items() if key != "item_id"}
        grounded_numbers = set(NUMBER_TOKEN.findall(json.dumps(grounding_payload, ensure_ascii=False)))
        if not set(NUMBER_TOKEN.findall(combined)).issubset(grounded_numbers):
            raise ValueError("Explanation introduced an unsupported numeric value")

    def _cache_key(self, payload: dict[str, Any]) -> str:
        cache_payload = {
            "model": self.model,
            "explanation_contract": hashlib.sha256(EXPLANATION_INSTRUCTIONS.encode("utf-8")).hexdigest(),
            **{key: value for key, value in payload.items() if key != "item_id"},
        }
        return hashlib.sha256(
            json.dumps(cache_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _cache_get(self, key: str) -> ReviewExplanation | None:
        with self._lock:
            value = self._cache.get(key)
            if value is not None:
                self._cache.move_to_end(key)
                return value.model_copy(deep=True)
            return None

    def _cache_put(self, key: str, value: ReviewExplanation) -> None:
        with self._lock:
            self._cache[key] = value.model_copy(deep=True)
            self._cache.move_to_end(key)
            while len(self._cache) > MAX_CACHE_ENTRIES:
                self._cache.popitem(last=False)
