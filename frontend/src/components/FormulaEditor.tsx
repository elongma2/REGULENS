import { Plus, Trash2 } from "lucide-react";
import { HelpHint } from "./HelpHint";
import { preparationStageLabel } from "../lib/presentation";
import { IngredientCombobox } from "./IngredientCombobox";
import type {
  ConcentrationBasis,
  EditorIngredient,
  FieldIssue,
  ProductApplicabilityFacts,
  RegulatedFunction,
  ScreeningOptions,
} from "../types/screening";

interface FormulaEditorProps {
  formulationId: string;
  formulationName: string;
  productContext: string;
  productApplicability: ProductApplicabilityFacts;
  ingredients: EditorIngredient[];
  options: ScreeningOptions | null;
  issues: FieldIssue[];
  disabled: boolean;
  onFormulationIdChange: (value: string) => void;
  onFormulationNameChange: (value: string) => void;
  onProductContextChange: (value: string) => void;
  onProductApplicabilityChange: (value: ProductApplicabilityFacts) => void;
  onIngredientsChange: (ingredients: EditorIngredient[]) => void;
}

const fallbackUnits = ["percent", "mg/kg", "ppm"] as const;
const fallbackBases: Array<ConcentrationBasis | null> = [
  null,
  "NH3",
  "free base",
  "zinc",
  "sulphate",
  "hydrochloride",
  "tetrahydrochloride",
];
const fallbackStages = ["finished_product", "after_mixing", "ready_for_use"] as const;

function newIngredient(): EditorIngredient {
  return {
    id: crypto.randomUUID(),
    name: "",
    casNumber: "",
    concentrationEnabled: false,
    concentrationValue: "",
    unit: "percent",
    basis: null,
    preparationStage: "finished_product",
    regulatedFunctions: [],
  };
}

export function FormulaEditor(props: FormulaEditorProps) {
  const updateRow = (index: number, update: Partial<EditorIngredient>) => {
    props.onIngredientsChange(
      props.ingredients.map((ingredient, rowIndex) =>
        rowIndex === index ? { ...ingredient, ...update } : ingredient,
      ),
    );
  };

  const issueFor = (index: number, field: string) =>
    props.issues.find((issue) => issue.path.includes(`ingredients.${index}`) && issue.path.endsWith(field))?.message;
  const anyRegulatedFunction = props.ingredients.some((item) => (item.regulatedFunctions?.length ?? 0) > 0);
  const toggleFunction = (index: number, value: RegulatedFunction) => {
    const current = props.ingredients[index].regulatedFunctions ?? [];
    updateRow(index, {
      regulatedFunctions: current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value],
    });
  };
  const applicabilityFields: Array<[keyof ProductApplicabilityFacts, string]> = [
    ["rinse_off", "Rinse-off product"],
    ["leave_on", "Leave-on product"],
    ["oral_care", "Oral-care product"],
    ["eye_area", "Applied near the eyes"],
    ["mucous_membrane_contact", "Contacts mucous membranes"],
    ["brief_skin_contact", "Only brief skin contact"],
    ["spray_or_aerosol", "Spray or aerosol"],
    ["powder_form", "Powder form"],
    ["sun_protection_purpose", "Intended for sun protection"],
    ["product_protection_purpose", "UV use protects the product"],
    ["solely_hair_colouring", "Intended solely to colour hair"],
  ];

  return (
    <section className="editor-panel" aria-labelledby="formulation-input-heading">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">Formulation input</p>
          <h2 id="formulation-input-heading" className="section-title">Composition</h2>
        </div>
        <span className="text-xs text-slate-500">{props.ingredients.length} rows</span>
      </div>

      {anyRegulatedFunction && (
        <details className="border-b border-slate-200 px-5 py-4">
          <summary className="cursor-pointer text-sm font-semibold text-slate-800">Product-use facts for positive-list checks</summary>
          <p className="mt-2 text-sm text-slate-600">Only answer facts you can confirm. Regulens requests these because a colourant, preservative, or UV-filter use was selected.</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {applicabilityFields.map(([field, label]) => (
              <label className="field-label" key={field}>
                {label}
                <select
                  className="field-control"
                  value={props.productApplicability[field] == null ? "" : String(props.productApplicability[field])}
                  disabled={props.disabled}
                  onChange={(event) => props.onProductApplicabilityChange({
                    ...props.productApplicability,
                    [field]: event.target.value === "" ? null : event.target.value === "true",
                  })}
                >
                  <option value="">Unknown</option>
                  <option value="true">Yes</option>
                  <option value="false">No</option>
                </select>
              </label>
            ))}
          </div>
        </details>
      )}

      <div className="grid gap-3 border-b border-slate-200 px-5 py-4 md:grid-cols-3">
        <label className="field-label">
          Formulation ID <span className="optional-label">Optional</span>
          <input
            className="field-control"
            value={props.formulationId}
            disabled={props.disabled}
            onChange={(event) => props.onFormulationIdChange(event.target.value)}
            placeholder="TEST-001"
          />
        </label>
        <label className="field-label">
          Formulation name <span className="optional-label">Optional</span>
          <input
            className="field-control"
            value={props.formulationName}
            disabled={props.disabled}
            onChange={(event) => props.onFormulationNameChange(event.target.value)}
            placeholder="My test formulation"
          />
        </label>
        <div className="field-label">
          <div className="flex items-center gap-1.5">
            <span>Product context</span>
            <HelpHint label="Product context">
              <p>What type or use of cosmetic product is this? Some ingredient restrictions apply only to specific product types.</p>
              <p className="mt-2">Why this matters: the same ingredient may have different restrictions depending on the product type. Examples in the accepted options include All products, Rinse-off products, and Artificial nail systems.</p>
              <p className="mt-2">Only the exact selected value is used. The system does not infer a category.</p>
            </HelpHint>
          </div>
          <span className="optional-label">Optional</span>
          <select
            aria-label="Product context"
            className="field-control"
            value={props.productContext}
            disabled={props.disabled || !props.options}
            onChange={(event) => props.onProductContextChange(event.target.value)}
          >
            <option value="">No product context supplied</option>
            {props.options?.product_contexts.map((context) => <option key={context}>{context}</option>)}
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="min-w-[940px]">
          <div className="ingredient-grid ingredient-header">
            <span>Ingredient</span><span>CAS number</span><span>Concentration</span><span>Unit</span>
            <span className="flex items-center gap-1">Basis
              <HelpHint label="Concentration basis">
                <p>What the regulatory concentration is calculated as, when the rule specifies one.</p>
                <p className="mt-2">Examples include NH3, free base, zinc, and sulphate. No specific basis means the request sends JSON null. The system does not convert between bases.</p>
              </HelpHint>
            </span>
            <span className="flex items-center gap-1">Preparation stage
              <HelpHint label="Preparation stage">
                <p>When does this concentration apply? Limits may refer to the finished product, after mixing for use, or the ready-for-use preparation.</p>
                <p className="mt-2">The submitted stage must be compatible with the rule. The system does not convert a packaged-product concentration into an after-mixing concentration.</p>
              </HelpHint>
            </span><span />
          </div>
          {props.ingredients.map((ingredient, index) => (
            <div className="ingredient-grid ingredient-row" key={ingredient.id}>
              <div>
                <IngredientCombobox
                  rowNumber={index + 1}
                  value={ingredient.name}
                  disabled={props.disabled}
                  invalid={Boolean(issueFor(index, "name"))}
                  onChange={(value) => updateRow(index, { name: value })}
                />
                {issueFor(index, "name") && <p className="input-error">{issueFor(index, "name")}</p>}
                <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600" aria-label={`Ingredient ${index + 1} regulated functions`}>
                  {(props.options?.regulated_functions ?? ["colourant", "preservative", "uv_filter"] as RegulatedFunction[]).map((value) => (
                    <label className="inline-flex items-center gap-1" key={value}>
                      <input
                        type="checkbox"
                        checked={(ingredient.regulatedFunctions ?? []).includes(value)}
                        disabled={props.disabled}
                        onChange={() => toggleFunction(index, value)}
                      />
                      {value.replace("_", " ")}
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <input
                  aria-label={`Ingredient ${index + 1} CAS number`}
                  className={`field-control ${issueFor(index, "cas_number") ? "field-error" : ""}`}
                  value={ingredient.casNumber}
                  disabled={props.disabled}
                  onChange={(event) => updateRow(index, { casNumber: event.target.value })}
                  placeholder="Optional"
                />
                {issueFor(index, "cas_number") && <p className="input-error">{issueFor(index, "cas_number")}</p>}
              </div>
              <div className="flex items-center gap-2">
                <input
                  aria-label={`Enable concentration for ingredient ${index + 1}`}
                  type="checkbox"
                  className="h-4 w-4 accent-slate-900"
                  checked={ingredient.concentrationEnabled}
                  disabled={props.disabled}
                  onChange={(event) => updateRow(index, { concentrationEnabled: event.target.checked })}
                />
                <input
                  aria-label={`Ingredient ${index + 1} concentration value`}
                  className={`field-control min-w-0 ${issueFor(index, "value") ? "field-error" : ""}`}
                  type="number"
                  min="0"
                  step="any"
                  value={ingredient.concentrationValue}
                  disabled={props.disabled || !ingredient.concentrationEnabled}
                  onChange={(event) => updateRow(index, { concentrationValue: event.target.value })}
                  placeholder="—"
                />
              </div>
              <select
                aria-label={`Ingredient ${index + 1} concentration unit`}
                className="field-control"
                value={ingredient.unit}
                disabled={props.disabled || !ingredient.concentrationEnabled}
                onChange={(event) => updateRow(index, { unit: event.target.value as EditorIngredient["unit"] })}
              >
                {(props.options?.concentration_units ?? fallbackUnits).map((value) => (
                  <option key={value} value={value}>{value === "percent" ? "%" : value}</option>
                ))}
              </select>
              <select
                aria-label={`Ingredient ${index + 1} concentration basis`}
                className="field-control"
                value={ingredient.basis ?? ""}
                disabled={props.disabled || !ingredient.concentrationEnabled}
                onChange={(event) => updateRow(index, {
                  basis: event.target.value === "" ? null : event.target.value as ConcentrationBasis,
                })}
              >
                {(props.options?.concentration_bases ?? fallbackBases).map((value) => (
                  <option key={value ?? "none"} value={value ?? ""}>{value ?? "No specific basis"}</option>
                ))}
              </select>
              <select
                aria-label={`Ingredient ${index + 1} preparation stage`}
                className="field-control"
                value={ingredient.preparationStage}
                disabled={props.disabled || !ingredient.concentrationEnabled}
                onChange={(event) => updateRow(index, {
                  preparationStage: event.target.value as EditorIngredient["preparationStage"],
                })}
              >
                {(props.options?.preparation_stages ?? fallbackStages).map((value) => (
                  <option key={value} value={value}>{preparationStageLabel(value)}</option>
                ))}
              </select>
              <button
                type="button"
                aria-label={`Remove ingredient ${index + 1}`}
                className="icon-button"
                disabled={props.disabled || props.ingredients.length === 1}
                onClick={() => props.onIngredientsChange(props.ingredients.filter((_, rowIndex) => rowIndex !== index))}
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
      </div>
      <div className="border-t border-slate-200 px-5 py-3">
        <button
          type="button"
          className="secondary-button"
          disabled={props.disabled}
          onClick={() => props.onIngredientsChange([...props.ingredients, newIngredient()])}
        >
          <Plus size={15} /> Add ingredient
        </button>
      </div>
    </section>
  );
}
