import { AlertCircle, CheckCircle2, ChevronDown, LoaderCircle, Pencil, Plus, Trash2, X } from "lucide-react";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { getOrInitializeFormulationAssembly, refreshFormulationAssembly, updateFormulationAssembly } from "../api/cases";
import type {
  AssemblyIssue,
  AssemblyPreparation,
  CompositionQuantity,
  FormulationDocument,
  SupplierMaterialState,
} from "../types/cases";
import type { RegulatedFunction } from "../types/screening";

const ASSEMBLY_DERIVATION_VERSION = "assembly-v6";

function quantityLabel(quantity: CompositionQuantity | null): string {
  if (!quantity) return "Not stated";
  const unit = quantity.unit === "percent" ? "%" : quantity.unit ? ` ${quantity.unit}` : "";
  if (quantity.kind === "exact" || quantity.kind === "approximate") {
    return `${quantity.kind === "approximate" ? "≈ " : ""}${quantity.value ?? "—"}${unit}`;
  }
  if (quantity.kind === "range") return `${quantity.lower ?? "—"}–${quantity.upper ?? "—"}${unit}`;
  if (quantity.kind === "upper_bound") return `${quantity.upper_inclusive ? "≤" : "<"}${quantity.upper ?? "—"}${unit}`;
  if (quantity.kind === "lower_bound") return `${quantity.lower_inclusive ? "≥" : ">"}${quantity.lower ?? "—"}${unit}`;
  if (quantity.kind === "coded_range") return quantity.reported_code || quantity.raw_text || "Coded range";
  if (quantity.kind === "remainder_to_total") return quantity.raw_text || `qsp ${quantity.value ?? 100}`;
  return quantity.raw_text || "Unavailable";
}

function supplierQuantity(raw: string): CompositionQuantity | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const normalized = trimmed.replace(/,/g, ".").replace(/\s+/g, " ");
  const number = "(\\d+(?:\\.\\d+)?)";
  const common = {
    value: null, lower: null, upper: null,
    lower_inclusive: null, upper_inclusive: null,
    unit: "percent", basis: null, preparation_stage: null,
    quantity_scope: "supplier_material" as const,
    raw_text: trimmed, reported_code: null, legend_entry_id: null,
    approximate: false,
  };
  let match: RegExpMatchArray | null;
  if ((match = normalized.match(new RegExp(`^(?:q\\.?s\\.?p\\.?)(?: to)?\\s*${number}\\s*%?$`, "i")))) {
    return { ...common, kind: "remainder_to_total", value: Number(match[1]) };
  }
  if ((match = normalized.match(new RegExp(`^(?:~|approx(?:imately)?\\.?)\\s*${number}\\s*%?$`, "i")))) {
    return { ...common, kind: "approximate", value: Number(match[1]), approximate: true };
  }
  if ((match = normalized.match(new RegExp(`^(?:max(?:imum)?\\.?\\s*)${number}\\s*%?$`, "i")))) {
    return { ...common, kind: "upper_bound", upper: Number(match[1]), upper_inclusive: true };
  }
  if ((match = normalized.match(new RegExp(`^(<=|≤|<)\\s*${number}\\s*%?$`)))) {
    return { ...common, kind: "upper_bound", upper: Number(match[2]), upper_inclusive: match[1] !== "<" };
  }
  if ((match = normalized.match(new RegExp(`^(>=|≥|>)\\s*${number}\\s*%?$`)))) {
    return { ...common, kind: "lower_bound", lower: Number(match[2]), lower_inclusive: match[1] !== ">" };
  }
  if ((match = normalized.match(new RegExp(`^${number}\\s*(?:-|–|—|to)\\s*${number}\\s*%?$`, "i")))) {
    const lower = Number(match[1]); const upper = Number(match[2]);
    if (lower > upper) return null;
    return { ...common, kind: "range", lower, upper, lower_inclusive: null, upper_inclusive: null };
  }
  if ((match = normalized.match(new RegExp(`^${number}\\s*%?$`)))) {
    return { ...common, kind: "exact", value: Number(match[1]) };
  }
  return null;
}

function usageQuantity(raw: string): CompositionQuantity | null {
  const quantity = supplierQuantity(raw);
  if (!quantity || quantity.kind === "remainder_to_total" || quantity.kind === "coded_range") return null;
  const numericValues = [quantity.value, quantity.lower, quantity.upper].filter(
    (value): value is number => value !== null,
  );
  if (numericValues.some((value) => value < 0 || value > 100)) return null;
  return {
    ...quantity,
    preparation_stage: "finished_product",
    quantity_scope: "finished_product",
  };
}

const regulatedFunctionLabels: Record<RegulatedFunction, string> = {
  colourant: "Colourant",
  preservative: "Preservative",
  uv_filter: "UV filter",
};

function validCas(value: string): boolean {
  const normalized = value.trim();
  if (!normalized) return true;
  const match = normalized.match(/^(\d{2,7})-(\d{2})-(\d)$/);
  if (!match) return false;
  const body = `${match[1]}${match[2]}`;
  const sum = [...body].reverse().reduce((total, digit, index) => total + Number(digit) * (index + 1), 0);
  return sum % 10 === Number(match[3]);
}

function ConstituentEditorRow({
  item,
  disabled,
  onChange,
  onRemove,
}: {
  item: SupplierMaterialState["constituents"][number];
  disabled: boolean;
  onChange: (item: SupplierMaterialState["constituents"][number]) => void;
  onRemove: () => void;
}) {
  const [name, setName] = useState(item.submitted_name);
  const [cas, setCas] = useState(item.cas_number ?? "");
  const [quantity, setQuantity] = useState(quantityLabel(item.composition_quantity));
  const parsedQuantity = supplierQuantity(quantity);
  const quantityInvalid = quantity.trim() !== "" && parsedQuantity === null;
  const casInvalid = !validCas(cas);
  const baseId = `constituent-${item.constituent_id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const commit = (changes: Partial<typeof item>) => onChange({
    ...item,
    ...changes,
    user_edits: {
      ...item.user_edits,
      ...Object.fromEntries(Object.entries(changes).map(([key, value]) => [key, value])),
    },
  });
  return <tr>
    <td><label className="sr-only" htmlFor={`${baseId}-name`}>Ingredient name</label><input
      id={`${baseId}-name`} value={name} disabled={disabled}
      onChange={(event) => setName(event.target.value)}
      onBlur={() => { const next = name.trim(); if (next && next !== item.submitted_name) commit({ submitted_name: next }); }}
    />{item.source_evidence?.[0] ? <small className="constituent-source-reference">
      {item.source_evidence[0].page ? `Page ${item.source_evidence[0].page}` : `Source row ${item.source_evidence[0].source_row ?? "—"}`}
      {item.source_evidence[0].source_snippet ? ` · ${item.source_evidence[0].source_snippet}` : ""}
    </small> : <small className="constituent-source-reference">Added by reviewer</small>}</td>
    <td><label className="sr-only" htmlFor={`${baseId}-cas`}>CAS number</label><input
      id={`${baseId}-cas`} value={cas} disabled={disabled}
      aria-invalid={casInvalid}
      onChange={(event) => setCas(event.target.value)}
      onBlur={() => { const next = cas.trim() || null; if (!casInvalid && next !== item.cas_number) commit({ cas_number: next }); }}
    />{casInvalid ? <small className="field-error">Enter a CAS number with a valid checksum, or leave it blank.</small> : null}</td>
    <td><label className="sr-only" htmlFor={`${baseId}-quantity`}>Inside raw material</label><input
      id={`${baseId}-quantity`} value={quantity} disabled={disabled}
      aria-invalid={quantityInvalid}
      onChange={(event) => setQuantity(event.target.value)}
      onBlur={() => {
        if (!quantityInvalid && parsedQuantity
          && quantity.trim() !== quantityLabel(item.composition_quantity)) {
          commit({ composition_quantity: parsedQuantity });
        }
      }}
    />{quantityInvalid ? <small className="field-error">Use an exact %, range, bound, approximate value, max, or qsp.</small> : null}</td>
    <td><fieldset className="constituent-function-options"><legend>Special use</legend>
      {(Object.keys(regulatedFunctionLabels) as RegulatedFunction[]).map((regulatedFunction) => <label key={regulatedFunction}>
        <input
          type="checkbox"
          checked={item.regulated_functions.includes(regulatedFunction)}
          disabled={disabled}
          onChange={(event) => commit({
            regulated_functions: event.target.checked
              ? [...new Set([...item.regulated_functions, regulatedFunction])]
              : item.regulated_functions.filter((value) => value !== regulatedFunction),
          })}
        />
        {regulatedFunctionLabels[regulatedFunction]}
      </label>)}
    </fieldset></td>
    <td>{item.verified_identity_group ? "Matched" : "Check name"}</td>
    <td><button
      className="icon-button"
      type="button"
      disabled={disabled}
      aria-label={`Remove ${item.submitted_name}`}
      onClick={onRemove}
    ><Trash2 size={14} /></button></td>
  </tr>;
}

function MaterialCard({
  material,
  issues,
  disabled,
  onChange,
}: {
  material: SupplierMaterialState;
  issues: AssemblyIssue[];
  disabled: boolean;
  onChange: (material: SupplierMaterialState) => void;
}) {
  const [usage, setUsage] = useState(
    material.finished_product_usage ? quantityLabel(material.finished_product_usage) : "",
  );
  const usageId = `material-usage-${material.material_id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const disclosureId = `material-disclosure-${material.material_id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
  const usageInvalid = usage.trim() !== "" && usageQuantity(usage) === null;
  const needsUsage = issues.some((issue) => issue.code === "material_usage_missing");
  const needsConstituentReview = issues.some((issue) => [
    "constituent_concentration_missing",
    "constituent_identity_unresolved",
    "incompatible_quantity_basis",
    "impossible_composition_total",
  ].includes(issue.code));
  const compositionScopeIssue = issues.find((issue) => issue.code === "incomplete_supplier_disclosure");
  const actionableIssues = useMemo(() => issues.filter((issue) => issue.severity !== "warning"), [issues]);
  const uniqueIssues = useMemo(() => {
    const seen = new Set<string>();
    return actionableIssues.filter((issue) => {
      const key = `${issue.code}:${issue.message.trim().toLocaleLowerCase()}:${issue.reviewer_action.trim().toLocaleLowerCase()}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }, [actionableIssues]);
  return <article className="trade-material-card">
    <div className="trade-material-header">
      <div>
        <h3>{material.trade_name}</h3>
        <p>{[material.supplier_name, material.product_code, `${material.constituents.length} ingredients`].filter(Boolean).join(" · ")}</p>
      </div>
      {!needsUsage && material.finished_product_usage ? <div className="trade-material-calculated">
        <CheckCircle2 size={16} />
        <span>Calculated automatically</span>
        <strong>{quantityLabel(material.finished_product_usage)} used</strong>
      </div> : <label className="trade-material-usage" htmlFor={usageId}>
        <span>Used in finished product</span>
        <div><input
          id={usageId}
          aria-label="Used in finished product"
          inputMode="decimal"
          value={usage}
          disabled={disabled}
          aria-invalid={usageInvalid}
          onChange={(event) => setUsage(event.target.value)}
          onBlur={() => {
            if (!usageInvalid) onChange({
              ...material,
              finished_product_usage: usageQuantity(usage),
              confirmation_status: "confirmed",
            });
          }}
          placeholder="e.g. 2"
        /></div>
        {usageInvalid ? <small>Use an exact value, range, bound or approximate value from 0 to 100.</small> : null}
      </label>}
    </div>
    {uniqueIssues.length ? <div className="trade-material-attention" role="status">
      <div><strong>What needs attention</strong><span>{uniqueIssues.length} remaining</span></div>
      <ol>{uniqueIssues.map((issue) => <li key={issue.issue_id}>
        <strong>{issue.message}</strong>
        <span>{issue.reviewer_action}</span>
        <small>{issue.blocking_for_calculation ? "Must be fixed before this material can be calculated." : "You may screen now, but the result will be limited to the information available."}</small>
      </li>)}</ol>
      <p>Make the corrections below. Regulens will recheck them automatically.</p>
    </div> : null}
    <details className="trade-material-identity">
      <summary>Supplier details</summary>
      <div className="trade-material-identity-grid">
        <label>Trade name<input value={material.trade_name} disabled={disabled} onChange={(event) => onChange({
          ...material,
          trade_name: event.target.value,
          confirmation_status: "confirmed",
        })} /></label>
        <label>Supplier<input value={material.supplier_name ?? ""} disabled={disabled} onChange={(event) => onChange({
          ...material,
          supplier_name: event.target.value || null,
          confirmation_status: "confirmed",
        })} /></label>
        <label>Product or material code<input value={material.product_code ?? ""} disabled={disabled} onChange={(event) => onChange({
          ...material,
          product_code: event.target.value || null,
          confirmation_status: "confirmed",
        })} /></label>
      </div>
      <p>Use these details to match the raw material in the finished formula to the correct supplier file. Changes apply only to this formulation.</p>
    </details>
    <div className="trade-material-controls">
      <span id={disclosureId}>{material.disclosure_status === "complete"
        ? "Document appears to list the full raw-material composition"
        : material.disclosure_status === "partial"
          ? "Document lists only part of the raw-material composition"
          : "The document does not say whether every ingredient is listed"}</span>
      <span>{material.constituents.length} extracted ingredient{material.constituents.length === 1 ? "" : "s"}</span>
    </div>
    {compositionScopeIssue ? <p className="composition-scope-help">
      Screening can cover the ingredients shown here. If you have a complete supplier composition, upload it to include the ingredients that are not listed.
    </p> : null}
    <details className="trade-material-constituents">
      <summary><ChevronDown size={15} /> {needsConstituentReview ? "Review ingredients needing attention" : "View extracted ingredients"}</summary>
      <div className="trade-material-table-wrap">
        <table>
          <thead><tr><th>Ingredient</th><th>CAS</th><th>Amount inside raw material</th><th>Used as</th><th>Name check</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>{material.constituents.map((item) => <ConstituentEditorRow
            key={item.constituent_id}
            item={item}
            disabled={disabled}
            onChange={(nextItem) => onChange({
              ...material,
              constituents: material.constituents.map((current) =>
                current.constituent_id === nextItem.constituent_id ? nextItem : current),
              confirmation_status: "confirmed",
            })}
            onRemove={() => onChange({
              ...material,
              constituents: material.constituents.filter((current) =>
                current.constituent_id !== item.constituent_id),
              removed_constituent_ids: item.user_edits.added_by_reviewer
                ? (material.removed_constituent_ids || [])
                : [...new Set([...(material.removed_constituent_ids || []), item.constituent_id])],
              confirmation_status: "confirmed",
            })}
          />)}</tbody>
        </table>
      </div>
      <button className="secondary-button trade-material-add-row" type="button" disabled={disabled} onClick={() => onChange({
        ...material,
        constituents: [...material.constituents, {
          constituent_id: `reviewer:${crypto.randomUUID()}`,
          submitted_name: "New ingredient",
          cas_number: null,
          composition_quantity: null,
          source_evidence: [],
          verified_identity_group: null,
          regulated_functions: [],
          role_label: null,
          user_edits: { added_by_reviewer: true },
        }],
        confirmation_status: "confirmed",
      })}><Plus size={14} /> Add missing ingredient</button>
    </details>
  </article>;
}

export interface TradeMaterialAssemblyPanelHandle {
  savePendingChanges: () => Promise<void>;
}

interface TradeMaterialAssemblyPanelProps {
  versionId: string;
  documents: FormulationDocument[];
  compact?: boolean;
  onHandledMaterialRowIdsChange?: (rowIds: string[]) => void;
  onAssemblyRevisionChange?: (revision: number | null) => void;
  onIssueAction?: (issue: AssemblyIssue) => void;
}

export const TradeMaterialAssemblyPanel = forwardRef<TradeMaterialAssemblyPanelHandle, TradeMaterialAssemblyPanelProps>(({ versionId, documents, compact = false, onHandledMaterialRowIdsChange, onAssemblyRevisionChange, onIssueAction }, ref) => {
  const [assembly, setAssembly] = useState<AssemblyPreparation | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
  const savePromiseRef = useRef<Promise<void> | null>(null);
  const dirtyRef = useRef(false);
  const signature = useMemo(() => documents
    .filter((item) => item.extraction_result)
    .map((item) => `${item.id}:${item.revision}:${item.governing_for_material}`)
    .sort().join("|"), [documents]);

  useEffect(() => {
    if (!signature) { setAssembly(null); return; }
    let active = true;
    setLoading(true); setError(null);
    void getOrInitializeFormulationAssembly(versionId).then(async (value) => {
      const expectedSnapshots = Object.fromEntries(documents
        .filter((item) => item.extraction_result)
        .map((item) => [
          item.id,
          `${ASSEMBLY_DERIVATION_VERSION}|${item.attached_extraction_key || `revision:${item.revision}`}|revision:${item.revision}|governing:${item.governing_for_material}|roles:${[...item.confirmed_roles].sort().join(",")}`,
        ]));
      const currentSnapshots = value.state.source_document_snapshots || {};
      const snapshotsMatch = JSON.stringify(
        Object.entries(currentSnapshots).sort(),
      ) === JSON.stringify(Object.entries(expectedSnapshots).sort());
      const current = snapshotsMatch ? value : await refreshFormulationAssembly(versionId);
      if (active) { setAssembly(current); setDirty(false); dirtyRef.current = false; }
    }).catch((caught) => {
      if (active) setError(caught instanceof Error ? caught.message : "Material calculations could not be prepared.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [versionId, signature]);

  const changeMaterial = (nextMaterial: SupplierMaterialState) => {
    if (!assembly) return;
    setError(null);
    setAssembly({
      ...assembly,
      state: {
        ...assembly.state,
        materials: assembly.state.materials.map((item) =>
          item.material_id === nextMaterial.material_id ? nextMaterial : item),
      },
    });
    setDirty(true);
    dirtyRef.current = true;
  };

  const recalculate = useCallback(async () => {
    if (savePromiseRef.current) return savePromiseRef.current;
    if (!assembly || !dirtyRef.current) return;
    const task = (async () => {
      setSaving(true); setError(null);
      try {
        const updated = await updateFormulationAssembly(
          versionId,
          assembly.assembly_revision,
          assembly.state,
        );
        setAssembly(updated); setDirty(false); dirtyRef.current = false;
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Material calculations could not be saved.");
      } finally { setSaving(false); }
    })();
    savePromiseRef.current = task;
    try {
      await task;
    } finally {
      if (savePromiseRef.current === task) savePromiseRef.current = null;
    }
  }, [assembly, versionId]);

  useEffect(() => {
    if (!compact || !dirty || saving || error) return;
    const timer = window.setTimeout(() => { void recalculate(); }, 450);
    return () => window.clearTimeout(timer);
  }, [compact, dirty, error, recalculate, saving]);

  useImperativeHandle(ref, () => ({
    savePendingChanges: async () => {
      if (savePromiseRef.current) await savePromiseRef.current;
      if (dirtyRef.current) await recalculate();
    },
  }), [recalculate]);

  const selectedMaterial = assembly?.state.materials.find((item) => item.material_id === selectedMaterialId) ?? null;
  const allIssues = assembly?.assembly.issues ?? [];
  const attentionIssues = allIssues.filter((issue) => issue.severity !== "warning");
  const coverageIssues = allIssues.filter((issue) => issue.severity === "warning");
  const materialAttentionIssues = attentionIssues.filter((issue) => issue.material_ids.length > 0);
  const generalAttentionIssues = attentionIssues.filter((issue) => (
    issue.material_ids.length === 0
    && !(issue.code === "calculation_withheld" && attentionIssues.length > 1)
  ));
  const materialAttentionGroups = useMemo(() => assembly?.state.materials.flatMap((material) => {
    const seen = new Set<string>();
    const issues = materialAttentionIssues.filter((issue) => {
      if (!issue.material_ids.includes(material.material_id)) return false;
      const key = `${issue.code}:${issue.reviewer_action.trim().toLocaleLowerCase()}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    return issues.length ? [{ material, issues }] : [];
  }) ?? [], [assembly?.state.materials, materialAttentionIssues]);

  useEffect(() => {
    onHandledMaterialRowIdsChange?.(assembly?.state.formulation_row_ownership
      .filter((item) => item.owner_type === "supplier_material")
      .map((item) => item.row_id) ?? []);
  }, [assembly?.state.formulation_row_ownership, onHandledMaterialRowIdsChange]);

  useEffect(() => {
    onAssemblyRevisionChange?.(assembly?.assembly_revision ?? null);
  }, [assembly?.assembly_revision, onAssemblyRevisionChange]);

  if (!signature) return null;

  if (!compact) return <section className="trade-material-panel" aria-labelledby="trade-material-title">
    <div className="trade-material-panel-heading">
      <div><h2 id="trade-material-title">Ingredient calculation</h2><p>Regulens reads recognised supplier documents, applies the amounts from the finished formula and calculates the ingredients automatically.</p></div>
      {assembly ? <span className={`assembly-state assembly-${assembly.assembly.completeness}`}>{assembly.assembly.completeness === "complete" ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}{assembly.assembly.completeness === "complete" ? "Calculated" : assembly.assembly.completeness === "blocked" ? "Cannot calculate" : "Some checks remain"}</span> : null}
    </div>
    {loading ? <div className="supplier-document-loading"><LoaderCircle className="spin" size={18} /> Preparing source-backed materials</div> : null}
    {error ? <div className="supplier-document-error" role="alert"><AlertCircle size={17} /><span>{error}</span></div> : null}
    {assembly ? <>
      <div className="trade-material-list">{assembly.state.materials.map((material) => <MaterialCard key={material.material_id} material={material} issues={assembly.assembly.issues.filter((issue) => issue.material_ids.includes(material.material_id))} disabled={saving} onChange={changeMaterial} />)}</div>
      {assembly.assembly.issues.some((issue) => issue.material_ids.length === 0) ? <details className="assembly-issues"><summary>Other checks</summary><ul>{assembly.assembly.issues.filter((issue) => issue.material_ids.length === 0).map((issue) => <li key={issue.issue_id}><strong>{issue.message}</strong><span>{issue.reviewer_action}</span></li>)}</ul></details> : null}
      {assembly.assembly.included_ingredients.length ? <details className="trade-material-preview"><summary>Preview calculated finished-product ingredients ({assembly.assembly.included_ingredients.length})</summary><div className="trade-material-table-wrap"><table><thead><tr><th>Ingredient</th><th>CAS</th><th>Finished product</th><th>Source contributions</th></tr></thead><tbody>{assembly.assembly.included_ingredients.map((ingredient) => <tr key={ingredient.verified_identity_group}><td>{ingredient.display_name}</td><td>{ingredient.cas_number || "—"}</td><td>{quantityLabel(ingredient.aggregate_quantity)}</td><td>{ingredient.contributions.length}</td></tr>)}</tbody></table></div></details> : null}
      <div className="trade-material-actions"><p>{assembly.assembly.included_ingredients.length} ingredient{assembly.assembly.included_ingredients.length === 1 ? "" : "s"} calculated from the finished formula and supplier documents.</p><button className="primary-button" type="button" disabled={!dirty || saving} onClick={() => void recalculate()}>{saving ? <LoaderCircle className="spin" size={16} /> : null}Save and recalculate</button></div>
    </> : null}
  </section>;

  return <section className="trade-material-panel" aria-labelledby="trade-material-title">
    <div className="trade-material-panel-heading">
      <div><p className="eyebrow">Review</p><h2 id="trade-material-title">Formulation overview</h2>
        <p>Review only the items that need correction. When you select Run screening, Regulens will calculate the finished-product ingredient concentrations and screen them in one step.</p>
      </div>
      {assembly ? <span className={`assembly-state assembly-${assembly.assembly.completeness}`}>
        {assembly.assembly.completeness === "complete" ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
        {assembly.assembly.completeness === "complete" ? "Ready for screening" : assembly.assembly.completeness === "blocked" ? "Information needed" : "Can screen with limits"}
      </span> : null}
    </div>
    {loading ? <div className="supplier-document-loading"><LoaderCircle className="spin" size={18} /> Preparing source-backed materials</div> : null}
    {error ? <div className="supplier-document-error" role="alert"><AlertCircle size={17} /><span>{error}</span></div> : null}
    {assembly ? <>
      {attentionIssues.length ? <section className="attention-summary" aria-labelledby="attention-summary-title">
        <div><h3 id="attention-summary-title">Needs attention</h3><span>{attentionIssues.length} check{attentionIssues.length === 1 ? "" : "s"} remaining</span></div>
        <ul>{materialAttentionGroups.map(({ material, issues }) => {
          return <li key={material.material_id}><button type="button" onClick={() => setSelectedMaterialId(material.material_id)}>
            <span><strong>{material.trade_name}</strong><small>{issues[0].message}</small><small>{issues[0].reviewer_action}</small>{issues.length > 1 ? <small>Open to review all {issues.length} checks.</small> : null}</span>
            <span className="attention-level">{issues.some((issue) => issue.blocking_for_calculation) ? "Must fix" : "Can screen with limits"}</span>
          </button></li>;
        })}{generalAttentionIssues.map((issue) => {
          const hasTarget = issue.document_ids.length > 0 || issue.constituent_ids.length > 0;
          const hasDirectRowTarget = issue.constituent_ids.some((id) => id.startsWith("agent:"));
          const content = <>
            <span><strong>{issue.message}</strong><small>{issue.reviewer_action}</small>{hasTarget ? <small>Open the affected {hasDirectRowTarget ? "formulation row" : "source file"}.</small> : <small>This is a system-level limitation with no value to invent.</small>}</span>
            <span className="attention-level">{issue.blocking_for_calculation && hasTarget ? "Must fix" : issue.blocking_for_calculation ? "System check" : "Can screen with limits"}</span>
          </>;
          return <li key={issue.issue_id}>{hasTarget ? <button type="button" onClick={() => onIssueAction?.(issue)}>{content}</button> : <div className="attention-static">{content}</div>}</li>;
        })}</ul>
      </section> : <div className="review-ready-summary"><CheckCircle2 size={17} /><span>No changes needed. Regulens will calculate these materials when screening runs.</span></div>}

      {coverageIssues.length ? <section className="coverage-summary" aria-labelledby="coverage-summary-title">
        <div><h3 id="coverage-summary-title">Screening coverage</h3><span>Kept with the results</span></div>
        <p>Some supplier files disclose only selected ingredients or amounts. Regulens will screen the supported information without asking you to invent the rest.</p>
        <details><summary>View coverage details</summary><ul>{coverageIssues.map((issue) => <li key={issue.issue_id}>{issue.message}</li>)}</ul></details>
      </section> : null}

      <div className="compact-formulation-list">
        <div className="compact-list-heading"><div><h3>Supplier materials</h3><p>{assembly.assembly.included_ingredients.length} ingredient{assembly.assembly.included_ingredients.length === 1 ? "" : "s"} will be calculated from these materials when screening runs</p></div>{saving ? <span><LoaderCircle className="spin" size={14} /> Rechecking…</span> : dirty ? <span>Rechecking changes…</span> : <span>Up to date</span>}</div>
        <div className="compact-material-columns" aria-hidden="true"><span>Material</span><span>Used in finished product</span><span>Status</span><span></span></div>
        <ul>{assembly.state.materials.map((material) => {
          const issues = attentionIssues.filter((issue) => issue.material_ids.includes(material.material_id));
          return <li key={material.material_id}>
            <div><strong>{material.trade_name}</strong><small>{[material.supplier_name, material.product_code].filter(Boolean).join(" · ") || `${material.constituents.length} extracted ingredients`}</small>{issues[0] ? <small className="material-issue-summary">{issues[0].reviewer_action}{issues.length > 1 ? ` · ${issues.length - 1} more to check` : ""}</small> : null}</div>
            <span>{material.finished_product_usage ? quantityLabel(material.finished_product_usage) : "Usage needed"}</span>
            <span className={issues.length ? "compact-status attention" : "compact-status"}>{issues.length ? "Needs input" : "Ready"}</span>
            <button className="text-button" type="button" onClick={() => setSelectedMaterialId(material.material_id)}><Pencil size={13} /> {issues.length ? "Review" : "View"}</button>
          </li>;
        })}</ul>
      </div>

      {selectedMaterial ? <div className="workspace-drawer-backdrop" role="presentation" onMouseDown={(event) => {
        if (event.target === event.currentTarget) setSelectedMaterialId(null);
      }}><aside className="workspace-drawer workspace-drawer-wide" role="dialog" aria-modal="true" aria-label={`Edit ${selectedMaterial.trade_name}`}>
        <div className="workspace-drawer-heading"><div><p className="eyebrow">Raw material</p><h2>{selectedMaterial.trade_name}</h2></div><button className="icon-button" type="button" aria-label="Close material editor" onClick={() => setSelectedMaterialId(null)}><X size={18} /></button></div>
        <MaterialCard material={selectedMaterial} issues={allIssues.filter((issue) => issue.material_ids.includes(selectedMaterial.material_id))} disabled={saving} onChange={changeMaterial} />
        <p className="drawer-save-state">{saving ? "Rechecking your correction…" : dirty ? "Your correction is waiting to be checked." : "All corrections are up to date."}</p>
      </aside></div> : null}
    </> : null}
  </section>;
});

TradeMaterialAssemblyPanel.displayName = "TradeMaterialAssemblyPanel";
