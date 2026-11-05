# Finding Accuracy Upgrade — Verification Report

Date: 2026-11-05

## Outcome

The system-wide finding-accuracy upgrade is implemented locally. It has not been pushed or deployed.

The accepted Singapore Parts I–V baseline now contains 4,466 rules and passes all 37 recorded source spot checks. Its accepted rules hash is:

`a3de95512af1397940d089de60b9639c8cb3448987656c35a2b4572793660ed0`

## Confirmed defects fixed

1. **Screening completeness:** an applicable withheld, missing, or unsupported rule condition now makes the screening disposition `partially_evaluated`. Identity resolution alone can no longer produce `fully_evaluated`.
2. **Octocrylene:** Singapore Part V Ref 10 is represented by its 9% propellant-spray and 10% other-product branches. Footnote 7 is linked to both branches and is included in runtime evidence. The benzophenone trace condition remains a professional-review issue rather than being silently treated as satisfied.
3. **Combined limits:** formulation screening resolves identities first and then evaluates rule conditions with formulation-level constituent context. Missing related constituents are named explicitly. Approximate or ranged amounts remain conservative.
4. **Ingredient functions:** Parts I and II are evaluated independently of cosmetic function. An empty optional function field no longer creates a regulatory warning. Positive-list absence remains enforceable only for a source-explicit or user-confirmed colourant, preservative, or UV-filter use.
5. **CI 42090 wording:** the current evidence is represented as related distinct forms/form relationship unresolved, not as a proven name–CAS conflict. No unsupported clearance is produced.
6. **Explanations:** 28 structured review-issue codes have deterministic templates. Multiple unresolved conditions are shown separately and explanations are populated only from structured evaluation evidence.

## Before and after examples

### Zinc Oxide

- Before: a vague request to check “combined constituent amounts and exposure details.”
- After: the finding states the submitted qualifier/value, the applicable 25% limit, names Zinc Oxide (nano) as the related constituent whose presence or amount is still needed, and separately requests inhalation-exposure information when the rule requires it.

### Octocrylene

- Before: a withheld professional-review condition could still display `fully_evaluated`, and footnote 7 was absent from the individual runtime evidence.
- After: the applicable 9% or 10% product branch is selected deterministically. Footnote 7 is visible, the trace benzophenone condition is explicit, and the overall disposition remains `partially_evaluated` until it is checked.

### Tosylchloramide sodium

- Before: absence of a submitted cosmetic function could lead to “Regulated function not listed.”
- After: Singapore Part II Ref 5 is evaluated at its 0.2% maximum for all products without requiring a function. Tests cover below, exactly at, and above the limit. A separately declared regulated function still triggers its independent positive-list evaluation.

### CI 42090

- Before: the submitted CI/name and CAS could be described as a name–CAS conflict.
- After: Regulens explains that the evidence concerns related but distinct chemical forms. CAS 3844-45-9, 2650-18-2, and 68921-42-6 are not treated as interchangeable exact identities. Runtime linkage remains pending rather than implying conflict or clearance.

## Identity and regulatory safeguards

- Singapore legislation remains authoritative for Singapore findings; ACD remains comparison and identity evidence.
- All applicable discovered regulatory records are retained independently.
- Regulatory limits, units, product branches, source wording, footnotes, and immutable historical results are preserved.
- Standard explanations are deterministic. The optional explanation model cannot change findings, dispositions, identity outcomes, limits, or evidence.
- Historical snapshots remain compatible through existing legacy fields and fallback rendering.

## CI 42090 status

Form-aware candidate data is present for:

- disodium form — CAS 3844-45-9;
- ammonium salt — CAS 2650-18-2;
- aluminium lake — CAS 68921-42-6.

The candidate preserves independent Part II Ref 190 and Part III Ref 42090 targets. It is **not accepted or active at runtime** because group-level versus form-specific applicability still requires a separate source approval. This is the sole `SOURCE_VERIFICATION_REQUIRED` item in the accepted-data audit.

## Validation results

- Backend: `222 passed, 2 skipped`.
- Data pipeline, glossary, and linkage suites: `38 passed`.
- Frontend: `94 passed`.
- Frontend production build: passed; the existing large-chunk advisory remains.
- Accepted structural validation: passed, `37/37` source spot checks.
- Accepted-data audit: `0 ERROR`, `127 WARNING`, `1 SOURCE_VERIFICATION_REQUIRED`.
- Candidate validation: passed; promoted accepted artifact verified.
- Git whitespace validation: passed after implementation.

Commands used:

```text
.venv\Scripts\python.exe -m pytest backend/tests -q
.venv\Scripts\python.exe -m pytest data_pipeline/tests data_pipeline/identity/eu_common_ingredient_glossary/tests data_pipeline/identity/eu_singapore_linkage/tests -q
npm test -- --run
npm run build
.venv\Scripts\python.exe -m data_pipeline.scripts.candidate_pipeline validate
.venv\Scripts\python.exe -m data_pipeline.scripts.validate_rules
.venv\Scripts\python.exe -m data_pipeline.scripts.validate_accepted_data
git diff --check
```

## Remaining limitations

- 1,384 normalized rules remain explicitly marked for professional review because their source conditions are not safely machine-executable.
- The 127 audit warnings are reviewable identity/source-data warnings, not accepted-data validation errors; they were not silently rewritten.
- CI 42090 remains pending form-specific approval.
- Extracted warning requirements do not establish that a product label satisfies them.
- Automated tests and source checks do not constitute a legal determination or product approval.
