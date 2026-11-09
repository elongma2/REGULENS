import { displayIngredientName } from "./presentation";
import type { IngredientResult } from "../types/screening";

export type AssemblyQuantity = {
  kind?: string;
  value?: number | null;
  lower?: number | null;
  upper?: number | null;
  unit?: string | null;
  raw_text?: string | null;
};

export type AssemblyContribution = {
  contribution_id?: string;
  source_type?: "direct_ingredient" | "material_constituent";
  source_material_id?: string | null;
  governing_document_id?: string | null;
  display_name?: string;
  cas_number?: string | null;
  composition_quantity?: AssemblyQuantity | null;
  material_usage?: AssemblyQuantity | null;
  finished_product_quantity?: AssemblyQuantity | null;
  calculation_formula?: string;
  source_evidence?: Array<{ page?: number | null; source_snippet?: string | null }>;
};

export type AssemblyAggregate = {
  verified_identity_group?: string;
  display_name?: string;
  cas_number?: string | null;
  aggregate_quantity?: AssemblyQuantity;
  contributions?: AssemblyContribution[];
};

type AssemblyMaterial = {
  material_id?: string;
  trade_name?: string;
  supplier_name?: string | null;
};

type SourceDocumentMetadata = {
  original_filename?: string | null;
  supplier_name?: string | null;
  trade_name?: string | null;
};

const normalized = (value: string | null | undefined) => value?.trim().toLocaleLowerCase() ?? "";

export function formatAssemblyQuantity(quantity?: AssemblyQuantity | null): string {
  if (!quantity) return "—";
  const unit = quantity.unit === "percent" ? "%" : quantity.unit ? ` ${quantity.unit}` : "";
  if (quantity.raw_text && quantity.kind === "unknown") return quantity.raw_text;
  if (quantity.kind === "range" && quantity.lower != null && quantity.upper != null) return `${quantity.lower}–${quantity.upper}${unit}`;
  if (quantity.kind === "upper_bound" && quantity.upper != null) return `<${quantity.upper}${unit}`;
  if (quantity.kind === "lower_bound" && quantity.lower != null) return `>${quantity.lower}${unit}`;
  if (quantity.value != null) return `${quantity.kind === "approximate" ? "≈" : ""}${quantity.value}${unit}`;
  return quantity.raw_text || "Unavailable";
}

export function findAssemblyAggregate(
  snapshot: Record<string, unknown> | null | undefined,
  result: IngredientResult,
): AssemblyAggregate | null {
  const aggregates = Array.isArray(snapshot?.aggregates) ? snapshot.aggregates as AssemblyAggregate[] : [];
  const submittedCas = result.submitted_ingredient.cas_number?.trim();
  const names = new Set([
    result.submitted_ingredient.name,
    displayIngredientName(result),
    result.identity.catalogue_identity?.canonical_name,
    ...result.identity.singapore_candidates.map((candidate) => candidate.original_substance_name),
  ].map(normalized).filter(Boolean));
  return aggregates.find((aggregate) => submittedCas && aggregate.cas_number === submittedCas)
    ?? aggregates.find((aggregate) => names.has(normalized(aggregate.display_name)))
    ?? null;
}

function materialFor(
  snapshot: Record<string, unknown> | null | undefined,
  materialId: string | null | undefined,
): AssemblyMaterial | null {
  if (!materialId || !Array.isArray(snapshot?.materials)) return null;
  return (snapshot.materials as AssemblyMaterial[]).find((item) => item.material_id === materialId) ?? null;
}

function sourceDocumentFor(
  snapshot: Record<string, unknown> | null | undefined,
  documentId: string | null | undefined,
): SourceDocumentMetadata | null {
  if (!documentId || !snapshot?.source_documents || typeof snapshot.source_documents !== "object") return null;
  return (snapshot.source_documents as Record<string, SourceDocumentMetadata>)[documentId] ?? null;
}

export function contributionSourceName(
  snapshot: Record<string, unknown> | null | undefined,
  contribution: AssemblyContribution,
): string {
  if (contribution.source_type === "direct_ingredient" || !contribution.source_material_id) return "Formulation";
  const material = materialFor(snapshot, contribution.source_material_id);
  const document = sourceDocumentFor(snapshot, contribution.governing_document_id);
  const tradeName = material?.trade_name || document?.trade_name || contribution.source_material_id;
  const supplier = material?.supplier_name || document?.supplier_name;
  return supplier ? `${tradeName} · ${supplier}` : tradeName;
}

export function contributionDocumentReference(
  snapshot: Record<string, unknown> | null | undefined,
  contribution: AssemblyContribution,
): string | null {
  const document = sourceDocumentFor(snapshot, contribution.governing_document_id);
  return document?.original_filename || contribution.governing_document_id || null;
}

export function combinedSourceNote(
  snapshot: Record<string, unknown> | null | undefined,
  result: IngredientResult,
): string | null {
  const contributions = findAssemblyAggregate(snapshot, result)?.contributions ?? [];
  const directEntries = contributions.filter((item) => item.source_type === "direct_ingredient" || !item.source_material_id).length;
  const supplierMaterials = new Set(
    contributions.map((item) => item.source_material_id).filter((value): value is string => Boolean(value)),
  );
  if (directEntries > 0 && supplierMaterials.size > 0) {
    const totalSources = 1 + supplierMaterials.size;
    return `Combined from ${totalSources} sources · Formulation + ${supplierMaterials.size} supplier${supplierMaterials.size === 1 ? "" : "s"}`;
  }
  if (supplierMaterials.size > 1) return `Combined from ${supplierMaterials.size} supplier materials`;
  if (directEntries > 1) return `Combined from ${directEntries} formulation entries`;
  return null;
}
