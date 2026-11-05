# Regulens pre-pilot backend verification

Date: 2026-11-05  
Accepted regulatory baseline: `acd-2026-1__sg-2025-12-01__parts-i-v-r1`  
Verdict: **READY WITH DOCUMENTED LIMITATIONS**, provided the two HIGH runtime-evidence issues below are fixed before external pilot use.

## 1. Scope and method

This verification used only local accepted regulatory data, official PDFs already stored in the repository, and synthetic test formulations. It did not use confidential customer data, paid live AI calls, production Supabase, deployment, or unapproved identity linkages.

Checks performed:

- accepted hash and source-manifest validation;
- raw-to-normalized regulatory validation;
- recorded official-source spot-check review;
- complete accepted index traversal for Singapore names, CAS values and CI values;
- exhaustive resolver execution for all 110 shared-CAS warnings;
- deterministic screening regression tests;
- CSV, XLSX and selectable-text PDF parsing/Agent tests using synthetic data and mocked model responses;
- API, persistence and immutable-screening regression tests;
- frontend result rendering tests and production build.

Automated validation cannot establish that every legal requirement was interpreted correctly. Only the recorded human source comparisons count as independent source verification.

## 2. Regulatory data accuracy

### Accepted coverage

| Measure | Count |
|---|---:|
| Raw regulatory records | 4,389 |
| Normalized rules | 4,464 |
| Regulatory substance records | 4,350 |
| Active Singapore Parts I–V rules | 2,202 |
| Singapore substances referenced by active rules | 2,166 |
| Singapore–ACD cross-references | 2,223 |
| Accepted catalogue identities | 30,416 |
| Accepted identity linkages | 2 |
| Pending identity-linkage candidates | 1 |
| Accepted JSON files checked | 24 |

### Source verification level

- 35/35 recorded human spot checks pass.
- These checks cover 27 distinct regulatory source rows and 8 Appendix I/Regulation 6 provisions.
- The remaining 4,362 raw regulatory rows pass automated structural, provenance, hash, raw-to-normalized and linkage validation, but were not independently compared row-by-row by a human.
- Parts III–V have 15 focused source checks with rendered PDF pages; the earlier baseline contributes 20 checks.

Therefore, `structurally validated` must not be interpreted as `independently confirmed legally accurate`.

### Normalization status

| Status | Rules |
|---|---:|
| Normalized | 3,039 |
| Manual review required | 1,386 |
| Inactive source entry | 39 |

Manual-review rules by section:

| Section | Rules |
|---|---:|
| Annex II Part 1 | 485 |
| Singapore Part I | 476 |
| Annex IV Part 1 | 145 |
| Annex III Part 1 | 127 |
| Singapore Part II | 88 |
| Annex VI | 24 |
| Singapore Part III | 17 |
| Annex VII | 11 |
| Singapore Part IV | 11 |
| Singapore Part V | 2 |

Most common reasons include 957 conditional prohibitions that are not safely structured, 145 ambiguous multi-case mappings, 141 ambiguous multi-case concentration structures, 113 multi-value concentration conditions and 48 additional numeric conditions not structured.

The engine conservatively withholds these rules for professional review rather than inventing deterministic conclusions.

### Cross-reference status

| Status | Count |
|---|---:|
| Aligned | 871 |
| Changed | 1,294 |
| ACD-only | 49 |
| Ambiguous | 9 |

- 1,352 cross-references require professional review.
- 484 are marked as material differences.
- ACD differences remain comparison evidence and do not silently replace Singapore rules.

### Accepted-data warnings

The accepted-data audit reports:

- confirmed errors: **0**;
- warnings: **127**;
- source-verification items: **1**.

Warning breakdown:

- 110 CAS values occur under multiple official source names;
- 9 malformed source CAS identifiers are preserved but not trusted as valid identifiers;
- 8 unassigned extraction fragments are table headers/column fragments rather than identified ingredient rows.

The malformed identifiers require source review before correction. They were not silently repaired or indexed as valid CAS numbers.

## 3. Identity resolution verification

### Index reachability

| Index/check | Result |
|---|---:|
| Exact normalized name keys | 3,345 |
| CAS index keys | 2,494 |
| CI index keys | 145 |
| Broken active Singapore rule targets | 0 |
| Singapore records missing exact-name index targets | 0 |
| Singapore CAS targets missing from the CAS index | 0 |
| Singapore CI targets missing from the CI index | 0 |

This establishes mechanical reachability through accepted identifiers. It does not establish complete real-world alias coverage.

### Shared-CAS investigation

- Shared CAS values examined: 110.
- Official source name/CAS pairs executed through the resolver: 223.
- Resolved to a supported identity: 220.
- Conservatively retained for review: 3.
- False name–CAS conflicts: 0.

CAS-only inputs:

- 107 returned `multiple_possible_identities`;
- 3 returned an unresolved/review-required result;
- none received a misleading clearance.

The three source-name relationships retained for review are:

- Triclosan / CAS 3380-34-5;
- the ACD Formaldehyde relationship / CAS 50-00-0;
- Quaternium-15 / CAS 51229-78-8.

Runtime checks confirmed that the applicable Singapore rules are still reached. Triclosan reaches Part IV Ref 25, Formaldehyde reaches Part I Ref 1577, and Quaternium-15 reaches Part I Ref 1385. Triclosan and Quaternium-15 retain identity review; Formaldehyde is resolved and prohibited.

### Known identity cases

| Ingredient | Current behavior |
|---|---|
| PHENOXYETHANOL / 122-99-6 | Verified accepted linkage; Part IV Ref 29 reached and evaluated. |
| OCTOCRYLENE / 6197-30-4 | Verified accepted linkage; Part V Ref 10 reached, but multi-case conditions remain professional review. |
| CI 42090 / 3844-45-9 | Pending. Distinct disodium, ammonium and aluminium-lake forms cannot safely be represented by the current exact-identity group. No rules are treated as cleared. |

### Remaining identity limitations

- CI 42090 needs form-specific members and relationship semantics before promotion.
- Exhaustive semantic alias completeness cannot be proven from the accepted sources alone.
- The 110 shared-CAS warnings are safe in current tests but should remain a maintained review queue.
- Three source-supported ACD name relationships remain unaccepted even though CAS-backed Singapore evaluation can proceed conservatively.

## 4. Screening correctness

The focused screening/upload/API suite executed 180 tests: 180 passed, with 1 optional live-service test skipped. The complete backend suite executed 217 tests: 217 passed, with 2 optional live-service tests skipped.

Representative verified behavior:

| Scenario | Expected | Actual |
|---|---|---|
| Aminophylline | Prohibited | Prohibited |
| Duplicate Pentachloroethane records | One identity, all prohibition records retained | Passed |
| Tosylchloramide sodium at 0.2% | Within limit | Within limit |
| Tosylchloramide sodium at 0.2001% | Limit exceeded | Limit exceeded |
| Missing restricted concentration | Information missing | Information missing |
| Range fully below limit | Within supported limit | Passed |
| Range crossing limit | Professional review | Passed |
| Range wholly above limit | Limit exceeded | Passed |
| Approximate concentration | Professional review | Passed |
| Incompatible unit/basis/stage | No conversion; professional review | Passed |
| Chlorates without product context | Information missing | Passed |
| Chlorates with exact Toothpaste context | Applicable case selected | Passed |
| CI 12085 at 2% as colourant | Permitted-use condition satisfied | Passed |
| CI 12085 at 4% as colourant | Permitted-use condition not met | Passed |
| PHENOXYETHANOL at 0.5% as preservative | Part IV limit evaluated | Passed; source comparison still requires review |
| OCTOCRYLENE at 8% as UV filter | Rule found; product-specific branch requires review | Passed conservatively |
| CI 42090 | Identity unresolved; no clearance | Passed conservatively |
| Manual multi-case rule | Withheld for professional review | Passed |
| Unknown ingredient | Identity unresolved; no regulatory clearance | Passed |

No tested unresolved or partially evaluated ingredient received `no_issue_identified_within_scoped_rules`.

### Incorrect or missing runtime behavior found

1. **Top-level screening disposition is inaccurate for withheld rules.** OCTOCRYLENE Ref 10 has `evaluation_status=withheld_professional_review`, but the result reports `screening_disposition=fully_evaluated` because the disposition currently reflects identity completion rather than rule-evaluation completeness. The primary result remains `professional_review_required`, so this is not a silent clearance, but the coverage label is misleading.
2. **OCTOCRYLENE footnote 7 is not attached to Ref 10 runtime evidence.** The accepted raw and processed source data preserve the Singapore page 195 requirement that benzophenone impurity/degradation product remain at trace level. However, `sg-third-schedule-v-10` currently has an empty `footnotes` list, so the finding drawer may not expose that text directly.

These are HIGH pre-pilot defects and should be repaired with targeted, source-backed changes.

## 5. Upload and persistence verification

### CSV

- UTF-8/BOM parsing and original cell preservation pass.
- Invalid, empty and malformed input tests pass.
- Clarification, preparation and screening flow tests pass.
- Retry tests preserve the parsed upload without requiring re-upload.

### XLSX

- Workbook parsing and browser upload-route tests pass.
- Extracted grids retain source values.
- Corrupt XLSX/XLS inputs fail clearly.

### Selectable-text PDF

- Multi-page selectable text and page provenance tests pass.
- Exact, ranged, bounded, approximate and undisclosed concentrations are preserved.
- Image-only/blank PDFs are rejected with an actionable message.
- No-ingredient PDFs fail without fabricating formulation rows.
- OCR remains intentionally unsupported.

### Persistence and historical results

- Stored formulation state, clarifications and immutable screening snapshots pass fake-repository integration tests.
- Previous screening runs retain their stored dataset identity.
- A new screen does not overwrite the older immutable result.

Limitations:

- No live hosted Supabase/OpenAI end-to-end upload was performed.
- Agent calls in tests use deterministic fakes/mocks; no paid external calls were made.
- The two skipped tests are optional live-service/integration checks, not deterministic engine failures.

## 6. Issue classification

### CRITICAL

No demonstrated scenario produced incorrect regulatory clearance or silently skipped an unresolved ingredient in the executed tests.

### HIGH

1. `screening_disposition` can say `fully_evaluated` while an applicable rule is withheld for professional review.
2. Singapore OCTOCRYLENE footnote 7 is preserved in source data but absent from the individual Ref 10 runtime evidence.
3. CI 42090 cannot yet preserve and evaluate its distinct related forms safely; it is correctly blocked rather than cleared.
4. Only 27 of 4,389 regulatory rows have direct recorded human row-level source checks. Automated validation covers the remainder but cannot establish complete legal accuracy.

### MEDIUM

1. 1,386 rules are intentionally non-executable and require professional review.
2. Three source-supported name/CAS relationships remain conservative identity-review cases.
3. Nine malformed source identifiers require source verification.
4. Complete semantic alias coverage is not established.
5. No live hosted authentication/storage/AI end-to-end smoke test was performed.

### LOW

1. Eight unassigned extraction fragments are table-header artifacts retained as warnings.
2. Frontend production build emits a bundle-size warning; this does not affect regulatory correctness.
3. Starlette reports one dependency deprecation warning during API tests.

## 7. Readiness verdict

**READY WITH DOCUMENTED LIMITATIONS**, after the two HIGH runtime-evidence defects are fixed and regression-tested:

1. derive `screening_disposition` from both identity and applicable rule-evaluation completeness;
2. attach Singapore footnote 7 to OCTOCRYLENE Ref 10 evidence and keep its trace-level requirement visible.

CI 42090 may remain unavailable for automated assessment during a controlled pilot only if the UI continues to block clearance and the limitation is explicitly documented for reviewers.

Pilot safeguards:

- position Regulens as an initial screening assistant, not an approval or complete compliance engine;
- require professional review of every review-required, incomplete or unresolved result;
- expose dataset version and source evidence in every saved screening;
- provide the known-limitation list to pilot users;
- do not treat structurally validated rules as independently source-verified;
- complete a two-user hosted Supabase/OpenAI smoke test before onboarding external users.

## 8. Test results

- Backend: **217 passed, 2 skipped**.
- Focused screening/upload/API/persistence: **180 passed, 1 skipped**.
- Data pipeline: **36 passed**.
- Frontend: **94 passed**.
- Frontend production build: passed with one non-blocking bundle-size warning.
- Accepted structural validation: passed.
- Recorded source spot checks: **35/35 passed**.
- Accepted-data audit: **0 errors, 127 warnings, 1 source-verification item**.

No code, regulatory data, linkages, infrastructure, deployment or production state was changed as part of this verification. This report is the only new persistent artifact.
