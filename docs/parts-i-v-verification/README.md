# Parts III-V regulatory source verification

Candidate: `acd-2026-1__sg-2025-12-01__parts-i-v-r1`

## How to review

1. Open the page image in `source-pages/` and the corresponding immutable PDF.
2. Confirm the reference, name/CAS/CI, limit and basis, product-use conditions, warning, footnote, continuation rows, and document version.
3. Compare those facts with the extracted JSON values in `verification_checklist.json` or the workbook.
4. Record `PASS` only when all relevant facts match. Record `FAIL` and the mismatch otherwise.
5. All 15 added checks were recorded as `PASS` after source comparison. The candidate then passed regression and integrity validation and was promoted to the accepted baseline.

## Automated versus manual

Automated checks cover source hashes, record presence, provenance, schema validity, duplicate IDs, required sections, reproducible candidate hashes, and test expectations. Manual review covers visual row alignment, continuation text, column meaning, footnote/preamble attachment, warning scope, and Regulation 6 meaning.

## Verification cases

### 1. parts-i-v-01 — Third Schedule Part III 12085

- Purpose: colourant concentration and # qualification
- PDF: `data_pipeline/Sources/singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf`
- Pages: 169
- Expected on source: CI 12085#, Red; allowed in all cosmetic products; 3% maximum concentration in the finished product.
- Rule/provision: `sg-third-schedule-iii-12085`
- Result: **PASS**
- Evidence checked: Singapore Third Schedule Part III rendered page 169 compared with sg-third-schedule-iii-12085.
- Notes: CI 12085#, Red, all cosmetic products, and 3% maximum in the finished product match the source row.

### 2. parts-i-v-02 — Annex IV Part 1 12085

- Purpose: ACD colourant field-of-application mapping
- PDF: `data_pipeline/Sources/annexes-of-the-asean-cosmetic-directive.pdf`
- Pages: 259, 265
- Expected on source: CI 12085 (2), Red; X in field-of-application column 1 (all cosmetic products); 3% maximum in finished products; footnote (2) covers specified insoluble lakes, salts and pigments and the insolubility test.
- Rule/provision: `acd-iv-12085`
- Result: **PASS**
- Evidence checked: ACD Annex IV rendered pages 259 and 265 compared with acd-iv-12085.
- Notes: CI 12085 (2), Red, column-1 application, 3% finished-product limit, and footnote (2) match. The footnote linkage was corrected before this PASS was recorded.

### 3. parts-i-v-03 — Third Schedule Part III 10316

- Purpose: eye-area colourant restriction
- PDF: `data_pipeline/Sources/singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf`
- Pages: 169
- Expected on source: CI 10316#, Yellow; allowed except for products applied near the eyes, especially eye make-up and eye make-up remover.
- Rule/provision: `sg-third-schedule-iii-10316`
- Result: **PASS**
- Evidence checked: Singapore Third Schedule Part III rendered page 169 compared with sg-third-schedule-iii-10316.
- Notes: CI 10316#, Yellow, and the exclusion for products applied near the eyes match the source row.

### 4. parts-i-v-04 — Third Schedule Part IV 1

- Purpose: preservative multi-product concentration cases
- PDF: `data_pipeline/Sources/singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf`
- Pages: 182
- Expected on source: Benzoic acid and sodium salt: 2.5% (acid) for rinse-off except oral care, 1.7% (acid) for oral care, and 0.5% (acid) for leave-on products.
- Rule/provision: `sg-third-schedule-iv-1`
- Result: **PASS**
- Evidence checked: Singapore Third Schedule Part IV rendered page 182 compared with sg-third-schedule-iv-1.
- Notes: Benzoic acid/sodium salt product-specific limits of 2.5%, 1.7%, and 0.5%, expressed as acid, match.

### 5. parts-i-v-05 — Annex VI 1

- Purpose: ACD preservative comparison and acid basis
- PDF: `data_pipeline/Sources/annexes-of-the-asean-cosmetic-directive.pdf`
- Pages: 266, 267
- Expected on source: Benzoic acid CAS 65-85-0 and sodium salt CAS 532-32-1 with the same 2.5%, 1.7%, and 0.5% product-specific limits, all expressed as acid.
- Rule/provision: `acd-vi-1`
- Result: **PASS**
- Evidence checked: ACD Annex VI rendered pages 266 and 267 compared with acd-vi-1.
- Notes: Names, CAS 65-85-0 and 532-32-1, three product-specific limits, and acid basis match.

### 6. parts-i-v-06 — Third Schedule Part IV 12

- Purpose: combined paraben limits
- PDF: `data_pipeline/Sources/singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf`
- Pages: 182, 183
- Expected on source: Reference 12 lists the named methyl/ethyl parabens and salts; 0.4% as acid for one ester and 0.8% as acid for mixtures of esters.
- Rule/provision: `sg-third-schedule-iv-12`
- Result: **PASS**
- Evidence checked: Singapore Third Schedule Part IV rendered pages 182 and 183 compared with sg-third-schedule-iv-12.
- Notes: Named parabens/salts and the 0.4% single-ester and 0.8% mixture limits expressed as acid match.

### 7. parts-i-v-07 — Annex VI 20

- Purpose: formaldehyde warning and preamble interaction
- PDF: `data_pipeline/Sources/annexes-of-the-asean-cosmetic-directive.pdf`
- Pages: 266, 272
- Expected on source: Reference 20 is 5-Bromo-5-nitro-1,3 dioxane, CAS 30007-47-7, 0.1%, rinse-off only, avoid nitrosamines. Annex VI preamble requires 'contains formaldehyde' when released formaldehyde exceeds 0.05% for named entries including 20.
- Rule/provision: `acd-vi-20`
- Result: **PASS**
- Evidence checked: ACD Annex VI rendered pages 266 and 272 compared with acd-vi-20.
- Notes: Identity, CAS, 0.1%, rinse-off restriction, nitrosamine condition, and the preamble formaldehyde warning match. The structured warning linkage was corrected before this PASS was recorded.

### 8. parts-i-v-08 — Third Schedule Part IV 2

- Purpose: preservative qualification and salts
- PDF: `data_pipeline/Sources/singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf`
- Pages: 182
- Expected on source: Reference 2 is Propionic acid and its salts with a 2% maximum expressed as acid.
- Rule/provision: `sg-third-schedule-iv-2`
- Result: **PASS**
- Evidence checked: Singapore Third Schedule Part IV rendered page 182 compared with sg-third-schedule-iv-2.
- Notes: Propionic acid and its salts at 2% maximum expressed as acid match.

### 9. parts-i-v-09 — Third Schedule Part V 3

- Purpose: UV-filter concentration
- PDF: `data_pipeline/Sources/singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf`
- Pages: 188
- Expected on source: Singapore Part V reference 3 is Homosalate with a 10% maximum authorised concentration.
- Rule/provision: `sg-third-schedule-v-3`
- Result: **PASS**
- Evidence checked: Singapore Third Schedule Part V rendered page 188 compared with sg-third-schedule-v-3.
- Notes: Homosalate and the 10% maximum authorised concentration match.

### 10. parts-i-v-10 — Annex VII A29a

- Purpose: nano zinc oxide conditions
- PDF: `data_pipeline/Sources/annexes-of-the-asean-cosmetic-directive.pdf`
- Pages: 280, 282, 290
- Expected on source: ACD Annex VII A29a is Zinc Oxide (nano), CAS 1314-13-2, 25%; no inhalation exposure; listed purity, particle-size, solubility and coating conditions; footnote 2 requires combined zinc oxide and nano zinc oxide to remain within the column-c limit; Annex VII version 2025-2, 12 December 2025.
- Rule/provision: `acd-vii-a29a`
- Result: **PASS**
- Evidence checked: ACD Annex VII rendered pages 280, 282, and 290 compared with acd-vii-a29a.
- Notes: Zinc Oxide (nano), CAS, 25%, inhalation restriction, nano characteristics, combined-use footnote (2), and section version 2025-2 match. The combined-footnote linkage was corrected before this PASS was recorded.

### 11. parts-i-v-11 — Third Schedule Part V A29a

- Purpose: Singapore nano UV-filter conditions
- PDF: `data_pipeline/Sources/singapore-health-products-cosmetic-products-acd-regulations-2007-current-2025-12-01.pdf`
- Pages: 188, 193, 194, 195
- Expected on source: Singapore Part V A29a is Zinc oxide (nano), 25%; no inhalation exposure; listed purity, particle-size, solubility and coating conditions continue across pages 193-194; footnote 4 on page 195 applies the combined zinc-oxide limit.
- Rule/provision: `sg-third-schedule-v-a29a`
- Result: **PASS**
- Evidence checked: Singapore Third Schedule Part V rendered pages 188, 193, 194, and 195 compared with sg-third-schedule-v-a29a.
- Notes: Zinc oxide (nano), 25%, inhalation restriction, continuation conditions, and combined-use footnote (4) match. The combined-footnote linkage was corrected before this PASS was recorded.

### 12. parts-i-v-12 — Annex VII A28

- Purpose: section-specific Annex VII version
- PDF: `data_pipeline/Sources/annexes-of-the-asean-cosmetic-directive.pdf`
- Pages: 280, 281
- Expected on source: ACD Annex VII A28 is Menthyl anthranilate at 5%; the section is version 2025-2, 12 December 2025 even though the bundle is 2026-1.
- Rule/provision: `acd-vii-a28`
- Result: **PASS**
- Evidence checked: ACD Annex VII rendered pages 280 and 281 compared with acd-vii-a28.
- Notes: Menthyl anthranilate at 5% and Annex VII section version 2025-2 dated 12 December 2025 match.

### 13. parts-i-v-regulation-6-3 — Regulation 6 6(3)

- Purpose: Singapore positive-list legal semantics
- PDF: `data_pipeline/Sources/Health Products (Cosmetic Products — ASEAN Cosmeti.pdf`
- Pages: 3
- Expected on source: Regulation 6(3): except for products intended solely to colour hair, a colouring agent must be in Part III and used according to Part III requirements.
- Rule/provision: `sg-regulation-6-3`
- Result: **PASS**
- Evidence checked: Singapore Regulation 6 rendered page 3 compared with sg-regulation-6-3.
- Notes: The solely-hair-colouring exception and Part III listing/use requirements match Regulation 6(3).

### 14. parts-i-v-regulation-6-4 — Regulation 6 6(4)

- Purpose: Singapore positive-list legal semantics
- PDF: `data_pipeline/Sources/Health Products (Cosmetic Products — ASEAN Cosmeti.pdf`
- Pages: 3
- Expected on source: Regulation 6(4): a preservative must be listed in Part IV, stay within the Part IV limit, and meet the other Part IV requirements.
- Rule/provision: `sg-regulation-6-4`
- Result: **PASS**
- Evidence checked: Singapore Regulation 6 rendered page 3 compared with sg-regulation-6-4.
- Notes: Part IV listing, maximum concentration, and other-requirements clauses match Regulation 6(4).

### 15. parts-i-v-regulation-6-5 — Regulation 6 6(5)

- Purpose: Singapore positive-list legal semantics
- PDF: `data_pipeline/Sources/Health Products (Cosmetic Products — ASEAN Cosmeti.pdf`
- Pages: 3, 4
- Expected on source: Regulation 6(5): a UV filter must be listed in Part V, stay within the Part V limit, and meet the other Part V requirements.
- Rule/provision: `sg-regulation-6-5`
- Result: **PASS**
- Evidence checked: Singapore Regulation 6 rendered pages 3 and 4 compared with sg-regulation-6-5.
- Notes: Part V listing, maximum concentration, and other-requirements clauses match Regulation 6(5).
