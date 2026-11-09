# VIP@SoC MVP — Singapore Cosmetic Formula Screening

## 1. MVP Goal

Build a **Singapore-only cosmetic formulation screening tool** that takes a raw formulation, checks each ingredient against a structured regulatory rules database derived from official sources, and produces **source-backed findings for professional review**.

The MVP does **not** replace the regulatory professional and does **not** issue a final legal approval. Its purpose is to automate the repetitive first-pass checking work and present the reviewer with the relevant rule, concentration condition, warning, and direct regulatory evidence.

---

## 2. Core User Flow

```text
FORMULATION
ingredient + concentration
        ↓
PARSE + VALIDATE
        ↓
RESOLVE INGREDIENT IDENTITY
        ↓
LOAD PRODUCT CONTEXT
        ↓
LOOK UP APPLICABLE RULES
        ↓
APPLY DETERMINISTIC SG LOGIC
        ↓
GENERATE SOURCE-BACKED FINDINGS
        ↓
HUMAN REVIEW
        ↓
FORMULATION SCREENING REPORT
```

The professional should spend their time **reviewing findings and exceptions**, instead of manually searching and cross-referencing every ingredient.

---

# 3. Offline / Regulatory Data Pipeline

```text
              OFFICIAL REGULATORY SOURCES
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   ACD Appendix I    ACD Annex II   ACD Annex III
       │             prohibited      restricted
       │                 │              │
       │                 └──────┬───────┘
       │                        ▼
       │               Extract relevant tables
       │                        │
       │                        ▼
       │               Normalise rule schema
       │                        │
       │                        ▼
       │             SG Regulation 6 mapping
       │                 / rule semantics
       │                        │
       │                        ▼
       │               Manual QA / verify
       │                ~15–20 examples
       │                        │
       └──────────────┐         │
                      ▼         ▼
                 REGULATORY DATABASE
                   Supabase/Postgres
```

## What happens here

### A. Source collection
Use official Singapore/HSA-hosted regulatory sources for the prototype.

The MVP focuses on:

- **ACD Appendix I** — product/category context used to determine what kind of cosmetic product is being assessed.
- **ACD Annex II** — prohibited substances.
- **Scoped ACD Annex III** — restricted substances relevant to the selected demo product category.
- **Singapore Regulation 6 logic** — the local legal logic used to interpret the prohibited/restricted ingredient rules for the Singapore screening flow.

### B. Extract regulatory rules
Use tools such as `pdfplumber` or `camelot` to extract the relevant tables from the official PDFs.

The system should not query the PDF live every time a user uploads a formulation.

Instead:

```text
PDF
 ↓
structured rows
 ↓
cleaned regulatory rules
 ↓
database
```

### C. Normalise the rules
Convert extracted rows into a common machine-readable schema.

Example:

```json
{
  "rule_id": "ACD-III-XXX",
  "substance_name": "Example Ingredient",
  "cas_number": "123-45-6",
  "annex": "III",
  "reference_number": "XXX",
  "restriction_type": "maximum_concentration",
  "product_context": "leave-on facial product",
  "maximum_concentration": 2.0,
  "unit": "%",
  "required_warning": "Example warning",
  "source_page": 42,
  "source_text": "Original regulatory wording",
  "source_url": "Official HSA source",
  "revision_date": "Document revision",
  "retrieval_date": "Date retrieved"
}
```

### D. Manual verification
Before using the extracted data in the demo:

- manually compare approximately **15–20 representative entries** against the original official source;
- include examples of:
  - prohibited ingredients;
  - concentration-limited ingredients;
  - product-context conditions;
  - warning requirements;
  - entries with no numerical concentration limit.

This demonstrates that the regulatory database was not blindly generated.

---

# 4. Runtime Pipeline

```text
                USER UPLOADS FORMULATION
               ingredient + concentration
                         │
                         ▼
                1. PARSE + VALIDATE
                         │
                         ▼
                2. RESOLVE IDENTITY
       submitted name → canonical ingredient
                   → CAS / rule identity
                         │
                         ▼
                3. PRODUCT CONTEXT
                informed by Appendix I
          product type / leave-on / rinse-off /
              use area / user population
                         │
                         ▼
               4. REGULATORY LOOKUP
                    Annex II
                    Annex III
                         │
                         ▼
                5. APPLY SG LOGIC
                  Regulation 6
                         │
          ┌──────────────┼───────────────┐
          ▼              ▼               ▼
      prohibited?    restricted?    condition applies?
                          │
                    concentration?
                          │
                       warning?
                          │
                          ▼
                6. GENERATE FINDING
             deterministic + bounded
                          │
                          ▼
                 7. ATTACH EVIDENCE
          Annex / ref no. / original wording /
          source page / source URL / version
                          │
                          ▼
                8. HUMAN REVIEW
                approve / amend / flag
                          │
                          ▼
             FORMULATION SCREENING REPORT
```

---

# 5. Runtime Stage Details

## Stage 1 — Parse + Validate

### Input
For the demo, support one simple format only:

```csv
ingredient,concentration
Ingredient A,0.5
Ingredient B,2.0
Ingredient C,4.0
```

### Validate
Check for:

- missing ingredient name;
- missing concentration;
- invalid numeric values;
- negative concentrations;
- concentration greater than 100%;
- duplicate rows;
- malformed input.

Invalid or incomplete entries should be clearly surfaced for review rather than guessed.

---

## Stage 2 — Resolve Ingredient Identity

Convert the submitted ingredient into the canonical regulatory identity used by the database.

For the MVP:

1. normalise case and whitespace;
2. exact canonical-name match;
3. CAS match if supplied;
4. small controlled synonym/trade-name mapping.

Example:

```text
" PHENOXYETHANOL "
        ↓
"phenoxyethanol"
        ↓
canonical regulatory substance
        ↓
CAS / substance ID
```

If identity cannot be confidently resolved:

```text
IDENTITY UNRESOLVED
→ human review required
```

The system must never silently guess an ingredient identity.

---

## Stage 3 — Product Context

The formulation must be evaluated in the context of the finished product.

For the MVP, keep this tightly scoped.

Example demo context:

```text
Market: Singapore
Product category: Facial moisturiser
Use: Leave-on
Use area: Face
User population: Adult
```

The selected context determines which Annex III conditions are applicable.

---

## Stage 4 — Regulatory Lookup

For every resolved ingredient:

1. search the Annex II dataset;
2. search the scoped Annex III dataset;
3. retrieve every potentially applicable rule.

The database should return the regulatory rule together with its evidence and source metadata.

---

## Stage 5 — Apply Singapore Logic

The compliance decision is **deterministic code**, not an LLM decision.

The engine checks:

### Prohibited?
If the ingredient is covered by an applicable Annex II prohibition:

```text
→ prohibited substance identified
```

### Restricted?
If an Annex III restriction exists:

```text
→ determine whether the condition applies
→ compare submitted concentration with applicable limit
→ identify additional conditions
→ retrieve required warning, if any
```

Example:

```text
Submitted concentration = 3.0%
Applicable maximum = 2.0%

3.0 > 2.0
→ restriction exceeded
```

The engine should never claim that the complete cosmetic product is legally approved.

---

# 6. Bounded Findings

Use a controlled vocabulary instead of free-form AI conclusions.

Recommended result types:

### 1. No issue identified within scoped rules

```text
No prohibition or applicable restriction
was identified in the rules covered by
the current prototype.
```

This does **not** mean "the ingredient is fully compliant with all Singapore law."

### 2. Restricted — within applicable limit

```text
A regulatory restriction exists,
but the submitted use/concentration
falls within the applicable scoped condition.
```

### 3. Restriction exceeded

```text
The submitted use or concentration
exceeds the applicable scoped restriction.
```

### 4. Prohibited substance identified

```text
An applicable prohibition was identified
in the scoped Annex II rules.
```

### 5. Information missing

```text
Required information is unavailable,
so the rule cannot be evaluated.
```

### 6. Identity unresolved / professional review required

```text
The ingredient could not be mapped
confidently to a regulatory substance.
```

---

# 7. Evidence Attached to Every Finding

For every regulatory finding, show:

- canonical substance name;
- CAS number where available;
- ACD Annex;
- reference number;
- submitted concentration;
- applicable limit/condition;
- required warning, if relevant;
- original regulatory wording;
- source page;
- direct official source URL;
- regulatory document revision;
- retrieval date / ruleset version.

Example:

```text
INGREDIENT X

Finding:
Restriction exceeded

Submitted:
3.0%

Applicable limit:
2.0%

Applicable context:
Leave-on facial product

Source:
ASEAN Cosmetic Directive
Annex III
Reference XXX
Page XX

Original wording:
"..."

Source authority:
Health Sciences Authority

Ruleset version:
XXXX
```

This source traceability is a central MVP requirement.

---

# 8. Human Review

Every screening ends with a professional review stage.

Reviewer actions:

```text
[ Approve system finding ]
[ Amend finding ]
[ Further review required ]
```

Store:

- original system finding;
- reviewer action;
- reviewer note;
- timestamp.

The MVP is therefore an **initial regulatory screening assistant**, not an automated regulatory sign-off system.

---

# 9. Final Formulation Screening Report

The main output is a formula-level summary plus ingredient-level evidence.

Example:

```text
FORMULATION SCREENING SUMMARY

Market:
Singapore

Product:
Leave-on facial moisturiser

Ingredients submitted:             20

No issue identified:               14
Restricted — within limit:          3
Restriction exceeded:               1
Prohibited substance identified:    1
Professional review required:       1

Reviewer status:
PENDING
```

Each ingredient row can be opened to inspect the underlying regulatory evidence.

---

# 10. Technical Architecture

```text
React / Vite / Tailwind
          │
          ▼
        FastAPI
          │
          ▼
      LangGraph
          │
    ┌─────┼────────┐
    ▼     ▼        ▼
 parser resolver compliance engine
                   │
                   ▼
             Supabase/Postgres
```

## LangGraph flow

```text
START
  ↓
parse_formula
  ↓
validate_input
  ↓
resolve_identity
  ↓
load_product_context
  ↓
lookup_rules
  ↓
apply_deterministic_checks
  ↓
build_evidence
  ↓
human_review
  ↓
END
```

LangGraph is used to orchestrate the workflow, not to make the regulatory conclusion.

---

# 11. Core Database Entities

## `substances`

```text
id
canonical_name
cas_number
```

## `aliases`

```text
id
alias
substance_id
```

## `rules`

```text
rule_id
substance_id
annex
reference_number
restriction_type
product_context
maximum_concentration
unit
required_warning
other_conditions
source_text
source_page
source_url
revision_date
retrieval_date
```

## `screening_results`

```text
screening_id
submitted_name
substance_id
concentration
finding
matched_rule_id
review_status
reviewer_note
```

---

# 12. Builder Split

## Person A — Regulatory Data + Deterministic Core

Responsible for:

```text
official PDFs
    ↓
table extraction
    ↓
normalisation
    ↓
manual QA
    ↓
Supabase rules
    ↓
compliance engine
```

Core deliverable:

```python
check_compliance(
    substance_id,
    concentration,
    product_context,
    ruleset_version
)
```

returns a structured result containing the finding and regulatory evidence.

---

## Person B — Input + Orchestration + UI

Responsible for:

```text
CSV/form input
    ↓
validation
    ↓
identity resolution
    ↓
LangGraph orchestration
    ↓
reviewer dashboard
    ↓
screening report
```

Person B should consume Person A's structured result without needing to understand the underlying Annex parsing logic.

---

# 13. MVP Demo

The demo should prove one complete end-to-end workflow.

### Demo sequence

1. Show the official HSA-hosted regulation.
2. Show one extracted rule and its structured database representation.
3. Upload a sample formulation.
4. Run the screening.
5. Show several different outcomes:
   - no issue identified;
   - restricted but within limit;
   - restriction exceeded;
   - prohibited ingredient;
   - unresolved/missing case.
6. Click a flagged ingredient.
7. Show:
   - submitted concentration;
   - applicable regulatory limit;
   - applicable context;
   - exact ACD Annex/reference;
   - original regulatory text;
   - official source URL.
8. Have the reviewer approve/amend the finding.
9. Show the final formulation summary.

---

# 14. Explicitly Out of Scope

Do not build these for the current MVP:

- full PIF generation;
- claims assessment;
- automated safety assessment;
- multi-country comparison;
- EU COSING integration;
- Japan/Korea rules;
- regulatory petitions/appeals;
- automatic legal-update ingestion;
- full label/artwork image checking;
- OCR;
- Word/Excel/email ingestion;
- vector-based ingredient matching;
- payment/account systems;
- enterprise permissions;
- full production-grade security/compliance certification.

These belong on the roadmap.

---

# 15. What the MVP Proves

The prototype is designed to test this hypothesis:

> Can structured, source-traceable regulatory screening reduce the repetitive ingredient-research and cross-referencing work currently performed by cosmetic regulatory professionals, while preserving professional control over the final regulatory judgement?

The MVP succeeds if it can reliably demonstrate:

```text
FORMULATION
     ↓
STRUCTURED REGULATORY CHECK
     ↓
CLEAR FINDINGS
     ↓
DIRECT OFFICIAL EVIDENCE
     ↓
HUMAN VERIFICATION
```

That is the full scope of the VIP@SoC prototype.
