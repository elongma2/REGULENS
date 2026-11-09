# Regulens synthetic trade-name pilot pack

These documents are synthetic test fixtures. They are not supplier specifications, safety advice, or regulatory sources.

## Recommended upload sequence

Create one new case and upload `07_Radiant_Barrier_Serum_Finished_Formula.pdf` as the finished formulation together with:

- `01_LumiMatrix_3000_Composition_RevA.pdf`
- `03_SiliSmooth_2315_SDS_Rev4.pdf`
- `04_Preserva_PX_Composition.pdf`
- `05_UV_Protect_OCZ_Composition.pdf`
- `06_Botanical_Glow_X_Partial_Composition.pdf`

Confirm the material associations and use the finished-product usages printed in the formula. Do not upload Rev B in the baseline scenario.

## Baseline expectations

- Exactly one finished formulation is selected.
- Four complete supplier materials and one partially disclosed supplier material are attached.
- `LumiMatrix 3000` resolves its document-local letter codes using the legend printed in that document.
- `SiliSmooth 2315` contributes exactly six Section 3 constituents. Section 2, 4, 8 and 14 safety text must not become ingredients.
- Supplier composition percentages are not mistaken for finished-product concentrations.
- Direct ingredients and verified supplier-derived constituents aggregate only after identity verification.
- The incomplete `Botanical Glow X` disclosure keeps assembly/screening partial. Its undisclosed carrier is not treated as zero and is not invented.
- AQUA `q.s. to 100%` remains unresolved because supplier ranges and an incomplete disclosure prevent a safe exact remainder calculation.
- Source evidence identifies the supplier material, document and source page for every derived contribution.

## Deterministic calculation checks

Using Rev A:

| Finished-product constituent | Expected contribution |
|---|---:|
| PHENOXYETHANOL from Preserva PX | 0.72% |
| PHENOXYETHANOL aggregated with direct addition | 1.02% |
| OCTOCRYLENE from UV Protect OCZ | 4.20% |
| OCTOCRYLENE aggregated with direct addition | 10.00% |
| ZINC OXIDE from UV Protect OCZ | 1.20% |
| CAPRYLIC/CAPRIC TRIGLYCERIDE from UV Protect OCZ | 0.60% |
| PEG-10 DIMETHICONE from SiliSmooth 2315 | 1.50-2.10% |
| ISODODECANE from SiliSmooth 2315 | 1.20-1.80% |
| ISOHEXADECANE from SiliSmooth 2315 | 0.90-1.80% |
| DISTEARDIMONIUM HECTORITE from SiliSmooth 2315 | 0.30-0.90% |
| DIMETHICONE from SiliSmooth 2315 | 0.06-0.30% |
| PROPYLENE CARBONATE from SiliSmooth 2315 | 0.12-0.24% |
| GLYCERIN aggregated from direct, LumiMatrix Rev A and Botanical Glow X | 3.80-4.60% |

The OCTOCRYLENE total is intentionally exactly 10%. Product branch, regulated function and other source conditions still need to be evaluated independently. The PHENOXYETHANOL total intentionally exceeds 1% so the regulatory engine can be checked for a retained adverse result after aggregation.

## Additional rigorous scenarios

### Exact duplicate

Upload `01_LumiMatrix_3000_Composition_RevA.pdf` twice. Regulens should reuse/deduplicate the exact private document and must not double its contributions.

### Conflicting revisions

Attach both LumiMatrix Rev A and `02_LumiMatrix_3000_Composition_RevB_CONFLICT.pdf`. They share one product code but disagree on the GLYCERIN range. Calculation must remain blocked until one governing revision is selected. Historical attachments and screenings must remain pinned to their original revision.

With Rev B selected, the expected aggregated GLYCERIN interval becomes 3.60-4.00% rather than 3.80-4.60%.

### Saved-document reuse

After confirming each supplier document, create another formulation version and attach the documents from the private saved-document library. Compatible extraction should be reused without uploading the files or repeating AI processing. The new formulation must receive its own local association and usage snapshot.

### Refresh and retry

Refresh while supplier processing is active, then reopen the formulation. Persisted progress should resume without duplicate processing. A failed document may be retried without re-uploading the finished formulation.

### Multiple-finished-formulation guard

Upload the finished-formulation PDF twice as separate documents in one batch. Regulens should require the user to select or split the formulations instead of merging them.

## Pass criteria

- No supplier trade name is screened as though it were a chemical ingredient.
- No source row is counted twice.
- No incompatible unit or unknown concentration is converted silently.
- An incomplete material cannot yield `fully_evaluated` or unsupported clearance.
- Adverse deterministic findings survive partial assembly status.
- Explanations show the supplier concentration, material usage, derived contribution, aggregation and applicable source-backed rule.
- Notes, reviewer status and follow-ups remain separate from immutable findings.

