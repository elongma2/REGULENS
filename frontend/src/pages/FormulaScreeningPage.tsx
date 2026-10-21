import { AlertTriangle, Check, LoaderCircle, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, getScreeningOptions, screenFormulation } from "../api/screening";
import { EvidenceDrawer } from "../components/EvidenceDrawer";
import { FormulaEditor } from "../components/FormulaEditor";
import { ScreeningResultsPanel } from "../components/ScreeningResultsPanel";
import { adversePrimaryFindings } from "../lib/screening";
import type {
  EditorIngredient,
  FieldIssue,
  FormulationRequest,
  ProductApplicabilityFacts,
  ScreeningOptions,
  ScreeningResponse,
} from "../types/screening";

const initialIngredients: EditorIngredient[] = [
  {
    id: "example-aminophylline",
    name: "Aminophylline",
    casNumber: "317-34-0",
    concentrationEnabled: false,
    concentrationValue: "",
    unit: "percent",
    basis: null,
    preparationStage: "finished_product",
    regulatedFunctions: [],
  },
  {
    id: "example-tosylchloramide",
    name: "Tosylchloramide sodium",
    casNumber: "",
    concentrationEnabled: true,
    concentrationValue: "0.21",
    unit: "percent",
    basis: null,
    preparationStage: "finished_product",
    regulatedFunctions: [],
  },
  {
    id: "example-mystery",
    name: "Mystery Extract",
    casNumber: "",
    concentrationEnabled: false,
    concentrationValue: "",
    unit: "percent",
    basis: null,
    preparationStage: "finished_product",
    regulatedFunctions: [],
  },
];

function optionalValue(value: string): string | null {
  return value.trim() ? value.trim() : null;
}

function buildRequest(
  formulationId: string,
  formulationName: string,
  productContext: string,
  productApplicability: ProductApplicabilityFacts,
  ingredients: EditorIngredient[],
): { request: FormulationRequest | null; issues: FieldIssue[] } {
  const issues: FieldIssue[] = [];
  const rows = ingredients.map((ingredient, index) => {
    if (!ingredient.name.trim()) issues.push({ path: `ingredients.${index}.name`, message: "Ingredient name cannot be blank" });
    if (ingredient.concentrationEnabled && ingredient.concentrationValue.trim() === "") {
      issues.push({ path: `ingredients.${index}.concentration.value`, message: "Enter a concentration value" });
    }
    const parsed = Number(ingredient.concentrationValue);
    return {
      name: ingredient.name,
      cas_number: optionalValue(ingredient.casNumber),
      concentration: ingredient.concentrationEnabled
        ? {
            value: parsed,
            unit: ingredient.unit,
            basis: ingredient.basis,
            preparation_stage: ingredient.preparationStage,
          }
        : null,
      regulated_functions: ingredient.regulatedFunctions ?? [],
    };
  });
  if (issues.length) return { request: null, issues };
  return {
    request: {
      formulation_id: optionalValue(formulationId),
      formulation_name: optionalValue(formulationName),
      product_context: optionalValue(productContext),
      product_applicability: productApplicability,
      ingredients: rows,
    },
    issues: [],
  };
}

export function FormulaScreeningPage() {
  const [formulationId, setFormulationId] = useState("TEST-001");
  const [formulationName, setFormulationName] = useState("My test formulation");
  const [productContext, setProductContext] = useState("");
  const [productApplicability, setProductApplicability] = useState<ProductApplicabilityFacts>({});
  const [ingredients, setIngredients] = useState(initialIngredients);
  const [options, setOptions] = useState<ScreeningOptions | null>(null);
  const [response, setResponse] = useState<ScreeningResponse | null>(null);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [issues, setIssues] = useState<FieldIssue[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [integrityFailure, setIntegrityFailure] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getScreeningOptions()
      .then(setOptions)
      .catch((caught: unknown) => {
        if (caught instanceof ApiError && caught.code === "accepted_baseline_integrity_failure") {
          setIntegrityFailure(true);
          setError("Regulatory dataset integrity verification failed. Screening is unavailable.");
        } else {
          setError(caught instanceof Error ? caught.message : "Unable to load screening options.");
        }
      });
  }, []);

  const selectedResult = response?.ingredient_results.find((item) => item.submitted_row_number === selectedRow) ?? null;
  const submit = async () => {
    if (loading || integrityFailure) return;
    const built = buildRequest(formulationId, formulationName, productContext, productApplicability, ingredients);
    setIssues(built.issues);
    setError(null);
    if (!built.request) return;
    setLoading(true);
    try {
      const next = await screenFormulation(built.request);
      setResponse(next);
      const firstAttention = next.ingredient_results.find(
        (result) => adversePrimaryFindings.has(result.primary_finding) || result.review_required,
      );
      setSelectedRow((firstAttention ?? next.ingredient_results[0])?.submitted_row_number ?? null);
    } catch (caught) {
      if (caught instanceof ApiError) {
        setIssues(caught.issues);
        if (caught.code === "accepted_baseline_integrity_failure") {
          setIntegrityFailure(true);
          setError("Regulatory dataset integrity verification failed. Screening is unavailable.");
        } else {
          setError(caught.message);
        }
      } else {
        setError("The screening request failed.");
      }
    } finally {
      setLoading(false);
    }
  };

  const formLabel = [formulationId.trim(), formulationName.trim()].filter(Boolean).join(" · ") || "Untitled formulation";
  const workflowStep = loading ? 1 : response ? 2 : 0;

  return (
    <div className={`workspace ${selectedResult ? "workspace-with-drawer" : ""}`}>
      <main className="min-w-0 px-5 py-7 md:px-8 lg:px-10">
        <p className="eyebrow">Singapore regulatory workflow</p>
        <header className="screening-sticky-header">
          <div className="screening-title-bar">
            <h1 className="page-title">Formula screening</h1>
            <button className="primary-button" type="button" onClick={submit} disabled={loading || integrityFailure || !options}>
              {loading ? <><LoaderCircle className="animate-spin" size={16} /> Screening…</> : "Run screen"}
            </button>
          </div>
          <nav className="workflow-progress screening-workflow-progress" aria-label="Formula screening workflow">
            <ol>
              {["Enter & confirm input", "Screen", "Review findings"].map((label, index) => {
                return <li key={label} className={index === workflowStep ? "is-current" : index < workflowStep ? "is-complete" : ""} aria-current={index === workflowStep ? "step" : undefined}>
                  <span className="workflow-step-number">{index < workflowStep ? <Check size={13} aria-hidden="true" /> : index + 1}</span>
                  <span>{label}</span>
                </li>;
              })}
            </ol>
          </nav>
        </header>
        <div className="screening-page-context">
          <p className="text-sm font-medium text-slate-700">{formLabel}</p>
          <div className="scope-label"><ShieldCheck size={16} /> Singapore screening scope</div>
        </div>

        {error && (
          <div className={`mb-5 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${integrityFailure ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-900"}`} role="alert">
            <AlertTriangle className="mt-0.5 shrink-0" size={16} />
            <span>{error}</span>
          </div>
        )}

        <FormulaEditor
          formulationId={formulationId}
          formulationName={formulationName}
          productContext={productContext}
          productApplicability={productApplicability}
          ingredients={ingredients}
          options={options}
          issues={issues}
          disabled={loading}
          onFormulationIdChange={setFormulationId}
          onFormulationNameChange={setFormulationName}
          onProductContextChange={setProductContext}
          onProductApplicabilityChange={setProductApplicability}
          onIngredientsChange={setIngredients}
        />

        {response && <ScreeningResultsPanel response={response} selectedRow={selectedRow} onSelect={setSelectedRow} />}
      </main>
      <EvidenceDrawer result={selectedResult} sources={response?.dataset.sources ?? []} explanationMetadata={response?.review_explanation_metadata ?? null} onClose={() => setSelectedRow(null)} />
    </div>
  );
}
