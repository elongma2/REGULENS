# AGENTS.md

## Purpose

This repository contains a 4-day MVP for the NUS VIP@SoC submission:
a **Singapore cosmetic formulation screening tool**.

The authoritative product specification is:

- `VIP_SoC_Cosmetics_MVP_Scope.md`

Read that file before making architectural or product decisions.

The MVP takes a cosmetic formulation, resolves ingredient identities, checks them against a
structured Singapore regulatory ruleset derived from official sources, applies deterministic
prohibition/restriction logic, attaches direct regulatory evidence, and presents findings for
human review.

The system is an **initial screening assistant**, not a legal approval engine.

---

## Non-negotiable product rules

1. Regulatory findings must come from structured regulatory data, not free-form LLM reasoning.
2. Never fabricate, infer, or silently "fix" regulatory rules.
3. If ingredient identity or rule interpretation is ambiguous, return/mark `manual_review_required`.
4. Preserve the original regulatory wording and source metadata.
5. Never output that an entire cosmetic product is "approved" or "compliant".
6. Prefer bounded findings defined in the MVP scope.
7. Human professional review remains the final step.
8. Do not expand scope without explicit user instruction.

---

## Current MVP scope

Build only the core flow:

```text
official regulatory PDFs
    -> extraction
    -> normalized rule data
    -> formulation input
    -> validation
    -> identity resolution
    -> regulatory lookup
    -> deterministic checks
    -> evidence-backed findings
    -> human review
```

Primary regulatory scope:

- ACD Appendix I
- ACD Annex II
- scoped ACD Annex III
- Singapore Regulation 6 mapping/semantics

Out of scope unless explicitly requested:

- full PIF generation
- claims assessment
- safety assessment
- EU/Japan/Korea comparison
- petitions/appeals
- automatic regulation monitoring
- OCR
- arbitrary Word/email ingestion
- embedding/vector ingredient matching
- authentication/payments
- production enterprise security work

---

## Repository structure

Keep the codebase small and predictable.

```text
/
├── AGENTS.md
├── VIP_SoC_Cosmetics_MVP_Scope.md
├── README.md
├── STATUS.md
│
├── data_pipeline/
│   ├── sources/          # original official PDFs; do not mutate
│   ├── raw/              # faithful extracted data
│   ├── processed/        # normalized machine-readable rules
│   ├── scripts/          # extraction/normalization/validation
│   └── tests/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── routes/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── parsing.py
│   │   │   ├── resolver.py
│   │   │   ├── compliance.py
│   │   │   └── evidence.py
│   │   └── graph/        # only if orchestration is actually needed
│   └── tests/
│
├── frontend/
│   └── ...
│
└── docs/
    └── ...
```

Do not create new top-level folders without a clear reason.

---

## Data pipeline rules

Maintain two distinct representations:

### Raw extraction
Faithfully preserve what was extracted from the source PDF.

Keep fields such as:

- source page
- original cell/row text
- reference number
- substance name
- CAS number
- raw condition/concentration/warning fields

### Normalized rules
Convert only clearly interpretable regulatory structure into machine-readable fields.

Typical fields:

- `rule_id`
- `annex`
- `reference_number`
- `substance_name`
- `cas_number`
- `restriction_type`
- `product_context`
- `maximum_concentration`
- `unit`
- `required_warning`
- `other_conditions`
- `source_text`
- `source_page`
- `source_url`
- `revision_date`
- `retrieval_date`
- `normalization_status`

If an Annex III row contains `(a)`, `(b)`, `(c)` conditions and their mapping is ambiguous,
preserve the raw text and flag the row rather than guessing.

Do not write directly from PDF extraction into the production rules table.
Use:

```text
PDF -> raw data -> normalized data -> validation -> database/runtime
```

---

## Regulatory source integrity

For every normalized rule, retain enough provenance to trace it back to the official source.

At minimum preserve:

- official source URL
- annex
- reference number
- PDF page
- original regulatory wording
- document revision/version when available
- retrieval date

Source traceability is a product requirement, not optional metadata.

---

## Backend rules

Keep regulatory decision logic deterministic and testable.

Good:

```python
if submitted_concentration > applicable_rule.maximum_concentration:
    finding = "restriction_exceeded"
```

Bad:

```python
finding = llm.ask("Is this ingredient compliant?")
```

Separate responsibilities:

- `parsing.py` — input validation/parsing
- `resolver.py` — deterministic identity normalization/matching
- `compliance.py` — rule selection and deterministic evaluation
- `evidence.py` — structured evidence/result assembly
- routes — HTTP only; no business logic

Prefer small pure functions for compliance logic.

---

## Allowed findings

Use bounded statuses such as:

- `no_issue_identified_within_scoped_rules`
- `restriction_within_limit`
- `restriction_exceeded`
- `prohibited_substance_identified`
- `information_missing`
- `identity_unresolved`
- `professional_review_required`

Do not replace these with uncontrolled free-form conclusions.

---

## Frontend rules

The UI should make the regulatory evidence easy to inspect.

Use `docs/UI.md` as the shared reference for frontend information architecture, component patterns,
visual tokens, interaction behavior, and UI acceptance criteria.

Minimum flow:

1. formulation input/upload
2. screening results table
3. ingredient detail/evidence panel
4. reviewer action
5. formulation summary

A flagged ingredient should visibly show:

- submitted ingredient/concentration
- resolved identity
- finding
- applicable rule/limit
- ACD annex/reference
- original source wording
- official source link
- review status

Do not spend time on decorative features before the full end-to-end flow works.

---

## Coding practices

- Prefer simple code over premature abstraction.
- Use type hints/types for shared data structures.
- Keep business logic outside routes/UI components.
- Avoid duplicate models/constants across files.
- Centralize status enums and rule schemas.
- Use descriptive names; avoid `data1`, `temp2`, `thing`.
- Delete dead experimental code instead of leaving commented blocks.
- Do not introduce dependencies unless they materially reduce implementation time.
- Do not refactor working unrelated code during a time-critical feature task.
- Keep secrets/keys in environment variables; never commit them.
- Add `.env` to `.gitignore`.
- Keep original regulatory PDFs read-only.

---

## Testing priorities

Prioritize tests around regulatory logic over UI tests.

At minimum cover:

1. prohibited Annex II ingredient
2. restricted Annex III ingredient within limit
3. restricted Annex III ingredient above limit
4. product-context-specific rule
5. required warning returned correctly
6. unknown ingredient
7. missing concentration
8. ambiguous/unresolved identity

For data validation, check:

- duplicate rule IDs
- malformed/missing reference numbers
- invalid concentration values
- duplicate substance aliases
- rows marked for manual review
- missing source provenance

---

## Documentation and status

Keep `STATUS.md` current and short.

It should contain:

- what currently works
- current blocker
- next highest-priority task
- known shortcuts/limitations
- last verified end-to-end workflow

After a meaningful task:

1. run relevant tests/checks;
2. summarize files changed;
3. update `STATUS.md` if project state changed;
4. state any assumptions or unresolved regulatory rows.

Do not turn documentation into a long diary.

---

## Working style for Codex

Before editing:

1. read this `AGENTS.md`;
2. read `VIP_SoC_Cosmetics_MVP_Scope.md`;
3. inspect the existing repository before proposing new structure;
4. read `STATUS.md` if present.

When implementing:

- make the smallest change that advances the MVP;
- reuse existing code before creating parallel implementations;
- do not change product scope on your own;
- do not rewrite unrelated working modules;
- surface regulatory ambiguity instead of resolving it by assumption.

Before finishing:

- run relevant tests or validation scripts;
- report exactly what changed;
- report anything not completed;
- identify manual verification still required.

---

## Deadline priority

Submission deadline is imminent.

Priority order:

1. correct regulatory extraction + provenance
2. deterministic rule evaluation
3. working end-to-end API
4. usable results/evidence UI
5. human review interaction
6. polish
7. optional architecture/framework additions

A boring end-to-end system that works is better than an ambitious partially working system.
