import { AlertTriangle, ArrowRight, Check, Download, FileUp, ListChecks, LoaderCircle, RotateCcw, Sparkles } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { answerAgentQuestions, prepareAgentFormulation, retryAgentSession, uploadAgentCSV } from "../api/agent";
import { answerFormulationVersion, getFormulationVersion, listFormulationScreenings, prepareFormulationVersion, retryFormulationVersion, screenFormulationVersion } from "../api/cases";
import { ApiError, getScreeningOptions, screenFormulation } from "../api/screening";
import { downloadAdHocScreeningReport, downloadSavedScreeningReport } from "../api/reports";
import { addFollowUp, addReviewerNote, getReviewWorkspace, updateFollowUp, updateReviewStatus } from "../api/review";
import { EvidenceDrawer, type DrawerTab } from "../components/EvidenceDrawer";
import { HelpHint } from "../components/HelpHint";
import { NotesActivityPanel } from "../components/NotesActivityPanel";
import { ScreeningResultsPanel } from "../components/ScreeningResultsPanel";
import { requiresAttention } from "../lib/screening";
import { idleWriteState, type WriteState } from "../lib/reviewPresentation";
import type { AgentPreparedFormulation, AgentQuestion, AgentSession, InputProvenance } from "../types/agent";
import type { ScreeningRun } from "../types/cases";
import type { FollowUp, ReviewDataState, ReviewerNote, ReviewItem, ReviewStatus, ReviewWorkspace } from "../types/review";
import type { ConcentrationBasis, ConcentrationUnit, PreparationStage, ProductApplicabilityFacts, RegulatedFunction, ScreeningOptions, ScreeningResponse } from "../types/screening";

interface RowDraft {
  name: string;
  cas: string;
  value: string;
  unit: ConcentrationUnit | "";
  basis: ConcentrationBasis | null;
  stage: PreparationStage | "";
  regulatedFunctions: RegulatedFunction[];
}

interface ReviewDraft {
  note: string;
  followUp: string;
}

type WorkspaceTab = "findings" | "formulation" | "activity";

function optional(value: string): string | null {
  return value.trim() || null;
}

const applicabilityFields: Array<{ key: keyof ProductApplicabilityFacts; label: string }> = [
  { key: "rinse_off", label: "Rinse-off product" },
  { key: "leave_on", label: "Leave-on product" },
  { key: "oral_care", label: "Oral-care product" },
  { key: "eye_area", label: "Used near the eyes" },
  { key: "mucous_membrane_contact", label: "Mucous-membrane contact" },
  { key: "brief_skin_contact", label: "Only brief skin contact" },
  { key: "spray_or_aerosol", label: "Spray or aerosol" },
  { key: "powder_form", label: "Powder form" },
  { key: "adult_use", label: "Intended for adults" },
  { key: "child_use", label: "Intended for children" },
  { key: "sun_protection_purpose", label: "Sun-protection purpose" },
  { key: "product_protection_purpose", label: "UV protection of the product only" },
  { key: "solely_hair_colouring", label: "Solely hair colouring" },
];

function fieldWasEdited(value: unknown, sourceValue: string | null | undefined, confirmedByUser: boolean | undefined): boolean {
  if (!confirmedByUser) return false;
  return String(value ?? "").trim().toLocaleLowerCase() !== String(sourceValue ?? "").trim().toLocaleLowerCase();
}

function rowDrafts(session: AgentSession): Record<string, RowDraft> {
  return Object.fromEntries(session.interpreted_rows.map((row) => [row.row_id, {
    name: String(row.name.value ?? ""),
    cas: String(row.cas_number?.value ?? ""),
    value: row.concentration?.value?.value == null ? "" : String(row.concentration.value.value),
    unit: row.concentration?.unit?.value ?? "",
    basis: row.concentration?.basis.value ?? null,
    stage: row.concentration?.preparation_stage?.value ?? "",
    regulatedFunctions: row.regulated_functions ?? [],
  }]));
}

export function AgentPage({ caseId, versionId }: { caseId?: string; versionId?: string } = {}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const fileInput = useRef<HTMLInputElement>(null);
  const findingsPanel = useRef<HTMLElement>(null);
  const formulationPanel = useRef<HTMLDivElement>(null);
  const initializedSessionId = useRef<string | null>(null);
  const reviewRequestId = useRef(0);
  const tabRefs = useRef<Record<WorkspaceTab, HTMLButtonElement | null>>({ findings: null, formulation: null, activity: null });
  const [session, setSession] = useState<AgentSession | null>(null);
  const [prepared, setPrepared] = useState<AgentPreparedFormulation | null>(null);
  const [options, setOptions] = useState<ScreeningOptions | null>(null);
  const [drafts, setDrafts] = useState<Record<string, RowDraft>>({});
  const [formulationId, setFormulationId] = useState("");
  const [formulationName, setFormulationName] = useState("");
  const [productContext, setProductContext] = useState("");
  const [productApplicability, setProductApplicability] = useState<ProductApplicabilityFacts>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<ScreeningResponse | null>(null);
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [manualValues, setManualValues] = useState<Record<string, { value: string; unit: ConcentrationUnit; stage: PreparationStage }>>({});
  const [retrying, setRetrying] = useState(false);
  const [exportingReport, setExportingReport] = useState(false);
  const [highlightedRow, setHighlightedRow] = useState<string | null>(null);
  const [highlightedQuestion, setHighlightedQuestion] = useState<string | null>(null);
  const [loadingPersisted, setLoadingPersisted] = useState(Boolean(versionId));
  const [screeningRuns, setScreeningRuns] = useState<ScreeningRun[]>([]);
  const [activeScreeningRunId, setActiveScreeningRunId] = useState<string | null>(null);
  const [formulationVersionNumber, setFormulationVersionNumber] = useState<number | null>(null);
  const [reviewWorkspace, setReviewWorkspace] = useState<ReviewWorkspace | null>(null);
  const [reviewDataState, setReviewDataState] = useState<ReviewDataState>(versionId ? "loading" : "not_applicable");
  const [workspaceTab, setWorkspaceTab] = useState<WorkspaceTab>("formulation");
  const [drawerTab, setDrawerTab] = useState<DrawerTab>("evidence");
  const [deepLinkNotice, setDeepLinkNotice] = useState<string | null>(null);
  const [visibleResultRows, setVisibleResultRows] = useState<number[]>([]);
  const [reviewDrafts, setReviewDrafts] = useState<Record<string, ReviewDraft>>({});
  const [reviewWriteStates, setReviewWriteStates] = useState<Record<string, WriteState>>({});
  const [pendingReviewStatuses, setPendingReviewStatuses] = useState<Record<string, ReviewStatus>>({});
  const [formulationNote, setFormulationNote] = useState("");
  const [clarificationNotes, setClarificationNotes] = useState<Record<string, string>>({});
  const [clarificationActions, setClarificationActions] = useState<Record<string, string>>({});
  const [activityRefreshToken, setActivityRefreshToken] = useState(0);
  const [confirmationTracker, setConfirmationTracker] = useState<{ sessionId: string | null; total: number }>({ sessionId: null, total: 0 });

  const writeState = (key: string): WriteState => reviewWriteStates[key] ?? idleWriteState;
  const setWriteState = (key: string, state: WriteState) => setReviewWriteStates((current) => ({ ...current, [key]: state }));

  const loadReviewWorkspace = async (runId: string | null, background = false) => {
    const requestId = ++reviewRequestId.current;
    if (!versionId) {
      setReviewWorkspace(null);
      setReviewDataState("not_applicable");
      return;
    }
    if (!background) {
      setReviewWorkspace(null);
      setReviewDataState("loading");
    }
    try {
      const workspace = await getReviewWorkspace(versionId, runId);
      if (reviewRequestId.current === requestId) {
        setReviewWorkspace(workspace);
        setReviewDataState("available");
      }
    } catch {
      if (reviewRequestId.current === requestId) {
        if (!background) {
          setReviewWorkspace(null);
          setReviewDataState("unavailable");
        }
      }
    }
  };

  const mergeReviewItem = (saved: ReviewItem) => {
    setReviewWorkspace((current) => current ? {
      ...current,
      review_items: current.review_items.map((item) => item.id === saved.id ? saved : item),
    } : current);
  };

  const mergeReviewerNote = (saved: ReviewerNote) => {
    setReviewWorkspace((current) => current ? {
      ...current,
      notes: [...current.notes.filter((item) => item.id !== saved.id), saved],
    } : current);
  };

  const mergeFollowUp = (saved: FollowUp) => {
    setReviewWorkspace((current) => current ? {
      ...current,
      follow_ups: [...current.follow_ups.filter((item) => item.id !== saved.id), saved],
    } : current);
  };

  const refreshActivity = () => setActivityRefreshToken((current) => current + 1);

  useEffect(() => { getScreeningOptions().then(setOptions).catch(() => setError("Unable to load screening options.")); }, []);
  useEffect(() => { setReviewDrafts({}); }, [versionId]);
  useEffect(() => {
    if (!versionId) return;
    let active = true;
    setLoadingPersisted(true);
    setReviewDataState("loading");
    Promise.all([getFormulationVersion(versionId), listFormulationScreenings(versionId)])
      .then(([version, runs]) => {
        if (!active) return;
        const requested = new URLSearchParams(window.location.search);
        const requestedRunId = requested.get("run");
        const requestedRun = runs.find((run) => run.id === requestedRunId) ?? runs[0] ?? null;
        const requestedTab = requested.get("tab");
        setFormulationVersionNumber(version.version_number);
        setSession(version.agent_session);
        if (version.agent_session && version.canonical_formulation) {
          setPrepared({ session: version.agent_session, formulation: version.canonical_formulation, row_provenance: version.agent_session.interpreted_rows });
        }
        setScreeningRuns(runs);
        if (requestedRun) {
          setResponse(requestedRun.result_snapshot);
          setActiveScreeningRunId(requestedRun.id);
          setWorkspaceTab(requestedTab === "formulation" ? "formulation" : requestedTab === "activity" && caseId ? "activity" : "findings");
          const requestedRow = Number(requested.get("row"));
          setSelectedRow(Number.isInteger(requestedRow) && requestedRun.result_snapshot.ingredient_results.some((item) => item.submitted_row_number === requestedRow) ? requestedRow : null);
          setDrawerTab(requested.get("drawer") === "review" ? "review" : "evidence");
        } else {
          setResponse(null);
          setActiveScreeningRunId(null);
          setWorkspaceTab(requestedTab === "activity" && caseId ? "activity" : "formulation");
          if (requestedTab === "results") setDeepLinkNotice("This formulation version has no saved screening results yet. Showing Formulation instead.");
        }
        if (requestedRunId && !runs.some((run) => run.id === requestedRunId)) setDeepLinkNotice("The requested screening run is unavailable. Showing the latest saved run.");
        void loadReviewWorkspace(requestedRun?.id ?? null);
      })
      .catch((caught) => active && setError(caught instanceof Error ? caught.message : "The saved formulation could not be loaded."))
      .finally(() => active && setLoadingPersisted(false));
    return () => { active = false; };
  }, [caseId, versionId]);
  useEffect(() => {
    if (!session) return;
    setDrafts(rowDrafts(session));
    if (initializedSessionId.current !== session.session_id) {
      initializedSessionId.current = session.session_id;
      setFormulationId(typeof session.formulation_id?.value === "string" ? session.formulation_id.value : "");
      setFormulationName(typeof session.formulation_name?.value === "string" ? session.formulation_name.value : "");
      setProductApplicability(session.product_applicability ?? session.canonical_formulation?.product_applicability ?? {});
    }
    setProductContext(typeof session.product_context?.value === "string" ? session.product_context.value : "");
  }, [session]);
  useEffect(() => {
    if (!session) {
      setConfirmationTracker({ sessionId: null, total: 0 });
      return;
    }
    setConfirmationTracker((current) => current.sessionId === session.session_id
      ? { ...current, total: Math.max(current.total, session.questions.length) }
      : { sessionId: session.session_id, total: session.questions.length });
  }, [session]);

  const upload = async (file?: File) => {
    if (!file || busy) return;
    setBusy(true); setError(null); setPrepared(null); setResponse(null); setSelectedRow(null); setVisibleResultRows([]); setReviewDrafts({}); setWorkspaceTab("formulation"); setReviewDataState("not_applicable"); setProductContext(""); setFormulationId(""); setFormulationName("");
    try { setSession(await uploadAgentCSV(file)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "The formulation file could not be uploaded."); }
    finally { setBusy(false); }
  };

  const answer = async (question: AgentQuestion, optionId: string) => {
    if (!session || busy) return;
    let value: unknown;
    if (question.question_type === "non_numeric_concentration" && optionId === "enter_manually") {
      const manual = manualValues[question.question_id] ?? { value: "", unit: "percent", stage: "finished_product" };
      const numeric = Number(manual.value);
      if (!Number.isFinite(numeric) || numeric < 0) { setError("Enter a non-negative numeric concentration."); return; }
      value = { value: numeric, unit: manual.unit, basis: null, preparation_stage: manual.stage };
    }
    setBusy(true); setError(null);
    try {
      if (versionId) setSession((await answerFormulationVersion(session, [{ question_id: question.question_id, option_id: optionId, value }])).agent_session);
      else setSession(await answerAgentQuestions(session, [{ question_id: question.question_id, option_id: optionId, value }]));
      setPrepared(null);
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "The answer could not be applied."); }
    finally { setBusy(false); }
  };

  const changeProductContext = async (value: string) => {
    setProductContext(value);
    const contextQuestion = session?.questions.find((question) => question.question_type === "product_context") ?? null;
    if (!contextQuestion) return;
    const option = contextQuestion.options.find((item) => item.value === (value || null));
    if (option) await answer(contextQuestion, option.option_id);
  };

  const saveRow = async (rowId: string, draft: RowDraft, field: "name" | "cas" | "concentration" | "functions") => {
    if (!session || busy) return;
    const currentRow = session.interpreted_rows.find((row) => row.row_id === rowId);
    if (!currentRow) return;
    if (field === "name" && draft.name.trim() === String(currentRow.name.value ?? "").trim() && !currentRow.name.needs_confirmation) return;
    if (field === "cas" && optional(draft.cas) === (currentRow.cas_number?.value ?? null)) return;
    const update = field === "name"
      ? { row_id: rowId, name: draft.name }
      : field === "cas"
        ? { row_id: rowId, cas_number: draft.cas }
        : field === "functions"
          ? { row_id: rowId, regulated_functions: draft.regulatedFunctions }
        : (() => {
            if (!draft.value.trim()) { setError("Enter a numeric concentration or use Leave unavailable in its clarification card."); return null; }
            const parsed = Number(draft.value);
            if (!Number.isFinite(parsed) || parsed < 0) { setError("Concentration edits must be non-negative numbers."); return null; }
            return {
              row_id: rowId,
              concentration_value: parsed,
              concentration_unit: draft.unit || null,
              concentration_basis: draft.basis,
              preparation_stage: draft.stage || null,
            };
          })();
    if (!update) return;
    setBusy(true); setError(null);
    try {
      if (versionId) setSession((await answerFormulationVersion(session, [], [update])).agent_session);
      else setSession(await answerAgentQuestions(session, [], [update]));
      setPrepared(null);
    }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Row edits could not be saved."); }
    finally { setBusy(false); }
  };

  const focusRow = (rowId: string, targetField?: AgentQuestion["target_field"]) => {
    const element = document.getElementById(`agent-row-${rowId}`);
    element?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightedRow(rowId);
    window.setTimeout(() => setHighlightedRow((current) => current === rowId ? null : current), 1400);
    const selector = targetField === "ingredient_name" ? "input[data-agent-field='ingredient_name']" : targetField === "concentration.unit" ? "select[data-agent-field='concentration.unit']" : targetField === "preparation_stage" ? "select[data-agent-field='preparation_stage']" : "input, select";
    window.setTimeout(() => element?.querySelector<HTMLElement>(selector)?.focus(), 250);
  };

  const focusQuestion = (questionId: string) => {
    const element = document.getElementById(`agent-question-${questionId}`);
    element?.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightedQuestion(questionId);
    window.setTimeout(() => setHighlightedQuestion((current) => current === questionId ? null : current), 1400);
    window.setTimeout(() => element?.querySelector<HTMLElement>("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])")?.focus(), 250);
  };

  const prepare = async () => {
    if (!session || busy) return;
    setBusy(true); setError(null);
    try {
      const metadata = {
        formulation_id: optional(formulationId), formulation_name: optional(formulationName), product_context: optional(productContext), product_applicability: productApplicability,
      };
      const next = versionId ? await prepareFormulationVersion(session, metadata) : await prepareAgentFormulation(session, metadata);
      setPrepared(next); setSession(next.session);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "The formulation could not be prepared."); }
    finally { setBusy(false); }
  };

  const screenPrepared = async () => {
    if (!prepared || busy) return;
    setBusy(true); setError(null);
    try {
      let next: ScreeningResponse;
      let savedRunId: string | null = null;
      if (versionId) {
        const run = await screenFormulationVersion(versionId);
        savedRunId = run.id;
        setScreeningRuns((current) => [run, ...current]);
        setActiveScreeningRunId(run.id);
        next = run.result_snapshot;
        void loadReviewWorkspace(run.id);
      } else {
        next = await screenFormulation(prepared.formulation);
        setReviewDataState("not_applicable");
      }
      setResponse(next);
      setWorkspaceTab("findings");
      const first = next.ingredient_results.find(requiresAttention) ?? next.ingredient_results[0];
      setSelectedRow(first?.submitted_row_number ?? null);
      if (versionId) updateWorkspaceParams({ tab: "results", run: savedRunId, row: first ? String(first.submitted_row_number) : null, drawer: "evidence", resume: null });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Screening failed.");
    } finally { setBusy(false); }
  };

  const exportReport = async () => {
    if (!response || exportingReport) return;
    setExportingReport(true);
    setError(null);
    try {
      if (versionId && activeScreeningRunId) {
        await downloadSavedScreeningReport(activeScreeningRunId);
      } else if (prepared) {
        await downloadAdHocScreeningReport(prepared.formulation);
      } else {
        throw new Error("The confirmed formulation is unavailable for export.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The PDF report could not be generated.");
    } finally {
      setExportingReport(false);
    }
  };

  const selectedReviewItem = reviewWorkspace?.review_items.find((item) => item.submitted_row_number === selectedRow) ?? null;
  const selectedReviewerNotes = selectedReviewItem ? reviewWorkspace?.notes.filter((item) => item.review_item_id === selectedReviewItem.id) ?? [] : [];
  const selectedFollowUps = selectedReviewItem ? reviewWorkspace?.follow_ups.filter((item) => item.review_item_id === selectedReviewItem.id) ?? [] : [];
  const formulationReviewerNotes = versionId
    ? reviewWorkspace?.notes.filter((item) => item.target_type === "formulation" && item.formulation_version_id === versionId) ?? []
    : [];
  const selectedStatusWriteState = selectedReviewItem ? writeState(`status:${selectedReviewItem.id}`) : idleWriteState;
  const selectedNoteWriteState = selectedReviewItem ? writeState(`note:${selectedReviewItem.id}`) : idleWriteState;
  const selectedFollowUpWriteState = selectedReviewItem ? writeState(`follow-up:${selectedReviewItem.id}`) : idleWriteState;
  const formulationNoteWriteState = versionId ? writeState(`formulation-note:${versionId}`) : idleWriteState;

  const changeReviewStatus = async (status: ReviewStatus) => {
    if (!selectedReviewItem || !versionId) return;
    const itemId = selectedReviewItem.id;
    const key = `status:${itemId}`;
    setPendingReviewStatuses((current) => ({ ...current, [itemId]: status }));
    setWriteState(key, { phase: "saving" });
    try {
      mergeReviewItem(await updateReviewStatus(itemId, status));
      setPendingReviewStatuses((current) => { const next = { ...current }; delete next[itemId]; return next; });
      setWriteState(key, { phase: "saved" });
      refreshActivity();
    } catch (caught) {
      setWriteState(key, { phase: "failed", message: caught instanceof Error ? caught.message : "Review status could not be saved." });
    }
  };

  const addFindingNote = async (body: string) => {
    if (!caseId || !selectedReviewItem) return;
    const key = `note:${selectedReviewItem.id}`;
    setWriteState(key, { phase: "saving" });
    const draftKey = reviewDraftKey;
    try { mergeReviewerNote(await addReviewerNote(caseId, "review_item", selectedReviewItem.id, body)); setReviewDrafts((current) => ({ ...current, [draftKey]: { ...(current[draftKey] ?? { note: "", followUp: "" }), note: "" } })); setWriteState(key, { phase: "saved" }); refreshActivity(); }
    catch (caught) { setWriteState(key, { phase: "failed", message: caught instanceof Error ? caught.message : "Reviewer note could not be saved. Your draft was kept." }); throw caught; }
  };

  const addFindingFollowUp = async (actionText: string) => {
    if (!caseId || !selectedReviewItem) return;
    const key = `follow-up:${selectedReviewItem.id}`;
    setWriteState(key, { phase: "saving" });
    const draftKey = reviewDraftKey;
    try { mergeFollowUp(await addFollowUp(caseId, "review_item", selectedReviewItem.id, actionText)); setReviewDrafts((current) => ({ ...current, [draftKey]: { ...(current[draftKey] ?? { note: "", followUp: "" }), followUp: "" } })); setWriteState(key, { phase: "saved" }); refreshActivity(); }
    catch (caught) { setWriteState(key, { phase: "failed", message: caught instanceof Error ? caught.message : "Follow-up could not be saved. Your draft was kept." }); throw caught; }
  };

  const toggleFollowUp = async (followUp: FollowUp) => {
    const key = `follow-up-toggle:${followUp.id}`;
    setWriteState(key, { phase: "saving" });
    try { mergeFollowUp(await updateFollowUp(followUp.id, { status: followUp.status === "open" ? "resolved" : "open" })); setWriteState(key, { phase: "saved" }); refreshActivity(); }
    catch (caught) { setWriteState(key, { phase: "failed", message: caught instanceof Error ? caught.message : "Follow-up could not be updated." }); }
  };

  const addClarificationNote = async (question: AgentQuestion, body: string) => {
    if (!caseId || !reviewWorkspace) return;
    const target = reviewWorkspace.clarification_targets.find((item) => item.question_key === question.question_id);
    if (!target || !body.trim()) return;
    const key = `clarification-note:${target.id}`;
    setWriteState(key, { phase: "saving" });
    try { mergeReviewerNote(await addReviewerNote(caseId, "clarification", target.id, body.trim())); setClarificationNotes((current) => ({ ...current, [question.question_id]: "" })); setWriteState(key, { phase: "saved" }); refreshActivity(); }
    catch (caught) { setWriteState(key, { phase: "failed", message: caught instanceof Error ? caught.message : "Reviewer note could not be saved. Your draft was kept." }); }
  };

  const addClarificationFollowUp = async (question: AgentQuestion, actionText: string) => {
    if (!caseId || !reviewWorkspace) return;
    const target = reviewWorkspace.clarification_targets.find((item) => item.question_key === question.question_id);
    if (!target || !actionText.trim()) return;
    const key = `clarification-follow-up:${target.id}`;
    setWriteState(key, { phase: "saving" });
    try { mergeFollowUp(await addFollowUp(caseId, "clarification", target.id, actionText.trim())); setClarificationActions((current) => ({ ...current, [question.question_id]: "" })); setWriteState(key, { phase: "saved" }); refreshActivity(); }
    catch (caught) { setWriteState(key, { phase: "failed", message: caught instanceof Error ? caught.message : "Follow-up could not be saved. Your draft was kept." }); }
  };

  const addFormulationNote = async () => {
    if (!caseId || !versionId) return;
    if (!formulationNote.trim()) return;
    const key = `formulation-note:${versionId}`;
    setWriteState(key, { phase: "saving" });
    try { mergeReviewerNote(await addReviewerNote(caseId, "formulation", versionId, formulationNote.trim())); setFormulationNote(""); setWriteState(key, { phase: "saved" }); refreshActivity(); }
    catch (caught) { setWriteState(key, { phase: "failed", message: caught instanceof Error ? caught.message : "Reviewer note could not be saved. Your draft was kept." }); }
  };

  const retry = async () => {
    if (!session || busy) return;
    setBusy(true); setRetrying(true); setError(null);
    try { setSession(versionId ? (await retryFormulationVersion(versionId)).agent_session : await retryAgentSession(session.session_id)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Retry failed."); }
    finally { setBusy(false); setRetrying(false); }
  };

  const startNewCSV = () => {
    if (busy) return;
    initializedSessionId.current = null;
    if (fileInput.current) fileInput.current.value = "";
    setSession(null);
    setPrepared(null);
    setResponse(null);
    setSelectedRow(null);
    setVisibleResultRows([]);
    setReviewDrafts({});
    setWorkspaceTab("formulation");
    setReviewDataState("not_applicable");
    setDrafts({});
    setFormulationId("");
    setFormulationName("");
    setProductContext("");
    setProductApplicability({});
    setManualValues({});
    setRetrying(false);
    setHighlightedRow(null);
    setHighlightedQuestion(null);
    setError(null);
  };

  const updateWorkspaceParams = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(changes).forEach(([key, value]) => value === null ? next.delete(key) : next.set(key, value));
    setSearchParams(next, { replace: true });
  };

  const activateWorkspaceTab = (tab: WorkspaceTab) => {
    setWorkspaceTab(tab);
    if (versionId) updateWorkspaceParams({ tab: tab === "findings" ? "results" : tab });
  };

  const selectResultRow = (row: number | null, tab: DrawerTab = drawerTab) => {
    setSelectedRow(row);
    if (!versionId) return;
    if (row === null) updateWorkspaceParams({ row: null, drawer: null, resume: null });
    else updateWorkspaceParams({ tab: "results", row: String(row), drawer: tab, resume: null });
  };

  const selectScreeningRun = (runId: string) => {
    const run = screeningRuns.find((item) => item.id === runId);
    if (!run || run.id === activeScreeningRunId) return;
    setResponse(run.result_snapshot);
    setActiveScreeningRunId(run.id);
    setSelectedRow(null);
    setVisibleResultRows([]);
    setWorkspaceTab("findings");
    setDrawerTab("evidence");
    setReviewWorkspace(null);
    updateWorkspaceParams({ tab: "results", run: run.id, row: null, drawer: null, resume: null });
    void loadReviewWorkspace(run.id);
  };

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, currentTab: WorkspaceTab) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const availableTabs: WorkspaceTab[] = response
      ? ["findings", "formulation", ...(caseId && versionId ? ["activity" as const] : [])]
      : ["formulation", ...(caseId && versionId ? ["activity" as const] : [])];
    const currentIndex = availableTabs.indexOf(currentTab);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? availableTabs.length - 1
        : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + availableTabs.length) % availableTabs.length;
    const nextTab = availableTabs[nextIndex];
    activateWorkspaceTab(nextTab);
    tabRefs.current[nextTab]?.focus();
  };

  const activeScreeningRun = screeningRuns.find((run) => run.id === activeScreeningRunId) ?? null;
  const activeScreeningRunIndex = activeScreeningRun ? screeningRuns.findIndex((run) => run.id === activeScreeningRun.id) : -1;
  const activeScreeningLabel = activeScreeningRunIndex >= 0 ? `Screening ${screeningRuns.length - activeScreeningRunIndex}` : null;
  const openFindingFollowUps = reviewWorkspace?.follow_ups.filter((item) => item.review_item_id && item.status === "open").length ?? 0;
  const findingsStateKey = activeScreeningRunId ?? `${session?.session_id ?? "ad-hoc"}:${response?.dataset.accepted_baseline_sha256 ?? "pending"}`;
  const selectedResult = workspaceTab === "findings"
    ? response?.ingredient_results.find((item) => item.submitted_row_number === selectedRow) ?? null
    : null;
  const selectedResultIndex = selectedRow === null ? -1 : visibleResultRows.indexOf(selectedRow);
  const hasPreviousResult = selectedResultIndex > 0;
  const hasNextResult = selectedResultIndex >= 0 && selectedResultIndex < visibleResultRows.length - 1;
  const reviewDraftKey = `${findingsStateKey}:${selectedReviewItem?.id ?? selectedRow ?? "none"}`;
  const selectedReviewDraft = reviewDrafts[reviewDraftKey] ?? { note: "", followUp: "" };

  const handleVisibleRowsChange = useCallback((rowNumbers: number[]) => {
    setVisibleResultRows((current) => current.length === rowNumbers.length && current.every((row, index) => row === rowNumbers[index]) ? current : rowNumbers);
    setSelectedRow((current) => {
      if (current === null || rowNumbers.includes(current)) return current;
      window.requestAnimationFrame(() => document.getElementById("screening-results-controls")?.focus());
      return null;
    });
  }, []);

  const closeEvidenceDrawer = () => {
    const row = selectedRow;
    setSelectedRow(null);
    if (versionId) updateWorkspaceParams({ row: null, drawer: null, resume: null });
    window.requestAnimationFrame(() => {
      const rowTarget = row === null ? null : document.getElementById(`screening-result-row-${row}`);
      (rowTarget ?? document.getElementById("screening-results-controls"))?.focus();
    });
  };
  const provenance: InputProvenance | null = selectedRow && prepared ? (() => {
    const row = prepared.row_provenance[selectedRow - 1];
    return row ? {
      filename: prepared.session.filename,
      sourceRow: row.source_row,
      sourceRows: row.source_rows,
      originalValue: row.name.source_value,
      interpretedValue: String(row.name.value),
      method: row.name.interpretation_method,
      confirmedByUser: row.name.confirmed_by_user,
      sourceMetadata: row.source_metadata,
    } : null;
  })() : null;
  const contextQuestion = session?.questions.find((question) => question.question_type === "product_context") ?? null;
  const clarificationQuestions = session?.questions.filter((question) => question.question_type !== "product_context") ?? [];
  const stageQuestion = session?.questions.find((question) => question.question_type === "preparation_stage") ?? null;
  const blockingItems = session?.questions.flatMap((question) => {
    if (question.row_id) {
      const row = session.interpreted_rows.find((item) => item.row_id === question.row_id);
      return row ? [`Row ${row.source_row} · ${row.name.source_value ?? row.name.value} · ${question.title.toLocaleLowerCase()}`] : [];
    }
    if (question.affected_row_ids.length) return question.affected_row_ids.flatMap((rowId) => {
      const row = session.interpreted_rows.find((item) => item.row_id === rowId);
      return row ? [`Row ${row.source_row} · ${row.name.source_value ?? row.name.value} · ${question.title.toLocaleLowerCase()}`] : [];
    });
    return [question.title];
  }) ?? [];
  const rowsNeedingConfirmation = new Set(session?.questions.flatMap((question) => question.row_id ? [question.row_id] : question.affected_row_ids) ?? []);
  const interruptedPersistentInterpretation = Boolean(versionId && session?.state === "parsing" && !retrying);
  const workflowStep = response ? 3 : prepared ? 2 : session ? 1 : 0;
  const remainingConfirmations = session?.questions.length ?? 0;
  const totalConfirmations = confirmationTracker.sessionId === session?.session_id
    ? Math.max(confirmationTracker.total, remainingConfirmations)
    : remainingConfirmations;
  const completedConfirmations = Math.max(0, totalConfirmations - remainingConfirmations);
  const confirmationPercent = totalConfirmations > 0 ? (completedConfirmations / totalConfirmations) * 100 : session ? 100 : 0;
  const showConfirmationControl = Boolean(session && !prepared && !response && ["interpreted", "needs_confirmation", "ready"].includes(session.state) && !retrying);
  const interpretationInProgress = loadingPersisted || retrying || (!session && busy);
  const guidanceTitle = interpretationInProgress
    ? "Preparing your formulation workspace"
    : interruptedPersistentInterpretation || session?.state === "failed"
      ? "Resume the interpretation"
      : response
        ? "Review the findings and their evidence"
        : prepared
          ? "Check the prepared input, then confirm screening"
          : blockingItems.length > 0
            ? `${session?.questions.length ?? 0} confirmation${session?.questions.length === 1 ? "" : "s"} needed before screening`
            : session
              ? "Your input is ready to prepare"
              : "Start with your formulation file";
  const guidanceDescription = interpretationInProgress
    ? "Your source values and interpretation will appear here when ready."
    : interruptedPersistentInterpretation || session?.state === "failed"
      ? "Use Retry below to continue from the uploaded file."
      : response
        ? "Select an ingredient to inspect its finding, source wording, and applicable conditions. Saved screenings also support reviewer notes, status, and follow-ups."
        : prepared
          ? "Review the ingredient values below. Confirm & Screen runs the regulatory checks; Back to interpretation lets you amend the input."
          : blockingItems.length > 0
            ? "Resolve the questions below and check the screening fields. Then prepare the formulation for a final confirmation."
            : session
              ? "Check the product details and ingredient fields below, then choose Confirm Formulation."
              : "Upload a file, confirm the interpreted values, then screen and review the findings.";

  useEffect(() => {
    if (!prepared && !response) return;
    (response ? findingsPanel.current : formulationPanel.current)?.scrollIntoView?.({
      behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
      block: "start",
    });
  }, [prepared, response]);

  useEffect(() => {
    if (!versionId || !session) return;
    const requestedTab = searchParams.get("tab");
    const requestedRunId = searchParams.get("run");
    const requestedRun = requestedRunId ? screeningRuns.find((run) => run.id === requestedRunId) : null;
    if (requestedRunId && screeningRuns.length > 0 && !requestedRun) {
      setDeepLinkNotice("The requested screening run is unavailable. Showing the current saved run.");
    }
    if (requestedRun && requestedRun.id !== activeScreeningRunId) {
      setResponse(requestedRun.result_snapshot);
      setActiveScreeningRunId(requestedRun.id);
      setSelectedRow(null);
      setVisibleResultRows([]);
      setReviewWorkspace(null);
      setDrawerTab(searchParams.get("drawer") === "review" ? "review" : "evidence");
      void loadReviewWorkspace(requestedRun.id);
      return;
    }

    if (requestedTab === "activity" && caseId) setWorkspaceTab("activity");
    else if (requestedTab === "formulation") setWorkspaceTab("formulation");
    else if (requestedTab === "results" && response) setWorkspaceTab("findings");

    const clarificationId = searchParams.get("clarification");
    if (clarificationId && reviewWorkspace) {
      const target = reviewWorkspace.clarification_targets.find((item) => item.id === clarificationId);
      const question = target ? session.questions.find((item) => item.question_id === target.question_key) : null;
      if (question) {
        setWorkspaceTab("formulation");
        window.setTimeout(() => focusQuestion(question.question_id), 0);
      } else {
        setDeepLinkNotice("The requested clarification is no longer available in this formulation version.");
      }
    }

    if (requestedTab === "results" && response) {
      const requestedRow = Number(searchParams.get("row"));
      if (Number.isInteger(requestedRow) && requestedRow > 0) {
        if (response.ingredient_results.some((item) => item.submitted_row_number === requestedRow)) {
          setSelectedRow(requestedRow);
          setDrawerTab(searchParams.get("drawer") === "review" ? "review" : "evidence");
        } else {
          setSelectedRow(null);
          setDeepLinkNotice("The requested result row is unavailable in this screening run.");
        }
      } else if (searchParams.get("resume") === "review" && reviewWorkspace) {
        const followUpItemIds = new Set(reviewWorkspace.follow_ups.filter((item) => item.status === "open" && item.review_item_id).map((item) => item.review_item_id));
        const nextItem = reviewWorkspace.review_items.find((item) => item.review_status && item.review_status !== "reviewed")
          ?? reviewWorkspace.review_items.find((item) => followUpItemIds.has(item.id));
        if (nextItem) {
          setSelectedRow(nextItem.submitted_row_number);
          setDrawerTab("review");
        }
      }
    }
  }, [activeScreeningRunId, caseId, response, reviewWorkspace, screeningRuns, searchParams, session, versionId]);

  return (
    <div className={`workspace guided-workspace ${selectedResult ? "workspace-with-drawer" : ""}`}>
      <main className="guided-workspace-main">
        <header className={`guided-header ${response ? "is-screened" : ""}`}>
          <div>
            {!response && <p className="eyebrow">Formulation agent</p>}
            <h1 className="page-title">{response ? "Screening results" : prepared ? "Confirm your screening input" : "Review your formulation"}</h1>
            {!response && <p className="guided-subtitle">Confirm the source values before running regulatory screening.{versionId && " · Saved formulation workspace"}</p>}
          </div>
          {response ? <button className="secondary-button report-download-button" type="button" onClick={() => void exportReport()} disabled={exportingReport}>
            {exportingReport ? <><LoaderCircle className="animate-spin" size={15} /> Preparing PDF…</> : <><Download size={15} /> Export PDF</>}
          </button> : !session && <span className="guided-market">Singapore screening</span>}
        </header>

        <div className={`guided-workflow-sticky ${response ? "is-screened" : ""}`}>
          <nav className="workflow-progress" aria-label="Formulation workflow">
            <ol>
              {["Upload", "Confirm input", "Screen", "Review findings"].map((label, index) => (
                <li key={label} className={index === workflowStep ? "is-current" : index < workflowStep ? "is-complete" : ""} aria-current={index === workflowStep ? "step" : undefined}>
                  <span className="workflow-step-number">{index < workflowStep ? <Check size={13} aria-hidden="true" /> : index + 1}</span>
                  <span>{label}</span>
                </li>
              ))}
            </ol>
          </nav>

          {showConfirmationControl && (
            <section className={`confirmation-control ${remainingConfirmations === 0 ? "is-complete" : ""}`} aria-label="Confirmation status">
              <div className="confirmation-meter" role="progressbar" aria-label="Confirmation progress" aria-valuemin={0} aria-valuemax={Math.max(totalConfirmations, 1)} aria-valuenow={totalConfirmations > 0 ? completedConfirmations : 1}>
                <span className="confirmation-progress-fill" style={{ transform: `scaleX(${confirmationPercent / 100})` }} aria-hidden="true" />
                <div className="confirmation-meter-content">
                  <strong className="confirmation-count">{remainingConfirmations}</strong>
                  <div>
                    <span className="confirmation-label">confirmation{remainingConfirmations === 1 ? "" : "s"} needed before screening</span>
                    <small>{remainingConfirmations > 0 ? `${blockingItems.length} item${blockingItems.length === 1 ? "" : "s"} to modify` : "All required confirmations are complete"}</small>
                  </div>
                </div>
              </div>
              <button className="primary-button confirmation-action" type="button" onClick={prepare} disabled={busy || remainingConfirmations > 0}>{busy ? "Confirming…" : <>Confirm Formulation <ArrowRight size={15} aria-hidden="true" /></>}</button>
            </section>
          )}
        </div>

        {!showConfirmationControl && !response && (
          <section className={`workflow-guidance ${blockingItems.length > 0 && !response && !prepared ? "needs-confirmation" : ""}`} aria-label="Next step">
            <ListChecks size={22} aria-hidden="true" />
            <div><h2>{guidanceTitle}</h2><p>{guidanceDescription}</p></div>
          </section>
        )}

        {error && <div className="mb-5 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="alert"><AlertTriangle size={16} />{error}</div>}
        {deepLinkNotice && <div className="workspace-link-notice" role="status"><span>{deepLinkNotice}</span><button className="text-button" type="button" onClick={() => setDeepLinkNotice(null)}>Dismiss</button></div>}

        {loadingPersisted && <section className="agent-dropzone"><LoaderCircle className="animate-spin text-slate-500" size={34} /><h2>Loading saved formulation</h2><p>Restoring the interpretation and clarification state.</p></section>}

        {!session && !versionId && (
          <section
            className="agent-dropzone"
            onDragOver={(event) => { event.preventDefault(); event.currentTarget.classList.add("is-dragging"); }}
            onDragLeave={(event) => event.currentTarget.classList.remove("is-dragging")}
            onDrop={(event) => { event.preventDefault(); event.currentTarget.classList.remove("is-dragging"); void upload(event.dataTransfer.files[0]); }}
          >
            {busy ? <LoaderCircle className="animate-spin text-slate-500" size={34} /> : <FileUp className="text-slate-500" size={34} />}
            <h2>{busy ? "Interpreting formulation" : "Drop formulation file here"}</h2>
            <p>{busy ? "Regulens is identifying the formulation structure and ingredient fields." : "or"}</p>
            <button className="secondary-button" type="button" onClick={() => fileInput.current?.click()} disabled={busy}>Browse files</button>
            <input ref={fileInput} className="sr-only" type="file" accept=".csv,.xlsx,.xls,.txt,.tsv,.json,.pdf,text/csv,application/json,application/pdf" aria-label="Choose formulation CSV" onChange={(event) => void upload(event.target.files?.[0])} />
            <small>CSV, XLSX, XLS, TXT, TSV, JSON, and PDF supported · maximum 2 MiB</small>
          </section>
        )}

        {session && (
          <div className="guided-session">
            <section className="review-workspace-navigation" aria-label="Review workspace navigation">
              <div className="screening-context-strip">
                <div className="screening-context-identity">
                  <strong>{formulationVersionNumber ? `Version ${formulationVersionNumber}` : "Working formulation"}</strong>
                  <span>{session.filename}</span>
                </div>
                {versionId && screeningRuns.length > 0 ? (
                  <label className="screening-run-control">
                    <span>Active screening run</span>
                    <select value={activeScreeningRunId ?? ""} onChange={(event) => selectScreeningRun(event.target.value)}>
                      {screeningRuns.map((run, index) => (
                        <option key={run.id} value={run.id}>Screening {screeningRuns.length - index} · {new Date(run.created_at).toLocaleString()}</option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <div className="screening-run-static">
                    <span>Active screening run</span>
                    <strong>{response ? "Unsaved screening" : "Not screened yet"}</strong>
                  </div>
                )}
                <div className="screening-context-meta">
                  <span>{activeScreeningRun?.jurisdiction ?? "Singapore"}</span>
                  <span>{response ? `Dataset ${response.dataset.dataset_version}` : "Screening not run"}</span>
                  {activeScreeningRun && <span>{activeScreeningLabel} · {new Date(activeScreeningRun.created_at).toLocaleString()}</span>}
                </div>
              </div>

              <div className="review-workspace-tabs" role="tablist" aria-label="Formulation review workspace">
                <button
                  ref={(node) => { tabRefs.current.findings = node; }}
                  id="review-workspace-tab-findings"
                  type="button"
                  role="tab"
                  aria-controls="review-workspace-panel-findings"
                  aria-selected={workspaceTab === "findings"}
                  tabIndex={workspaceTab === "findings" ? 0 : -1}
                  disabled={!response}
                  onClick={() => response && activateWorkspaceTab("findings")}
                  onKeyDown={(event) => handleTabKeyDown(event, "findings")}
                >Results</button>
                <button
                  ref={(node) => { tabRefs.current.formulation = node; }}
                  id="review-workspace-tab-formulation"
                  type="button"
                  role="tab"
                  aria-controls="review-workspace-panel-formulation"
                  aria-selected={workspaceTab === "formulation"}
                  tabIndex={workspaceTab === "formulation" ? 0 : -1}
                  onClick={() => activateWorkspaceTab("formulation")}
                  onKeyDown={(event) => handleTabKeyDown(event, "formulation")}
                >Formulation</button>
                {caseId && versionId && <button
                  ref={(node) => { tabRefs.current.activity = node; }}
                  id="review-workspace-tab-activity"
                  type="button"
                  role="tab"
                  aria-controls="review-workspace-panel-activity"
                  aria-selected={workspaceTab === "activity"}
                  tabIndex={workspaceTab === "activity" ? 0 : -1}
                  onClick={() => activateWorkspaceTab("activity")}
                  onKeyDown={(event) => handleTabKeyDown(event, "activity")}
                >Notes &amp; Activity</button>}
              </div>
            </section>

            <section
              ref={findingsPanel}
              id="review-workspace-panel-findings"
              className="review-workspace-panel guided-results"
              role="tabpanel"
              aria-labelledby="review-workspace-tab-findings"
              hidden={workspaceTab !== "findings"}
            >
              {response && <ScreeningResultsPanel key={findingsStateKey} response={response} reviewItems={reviewWorkspace?.review_items ?? []} reviewDataState={reviewDataState} openFindingFollowUps={openFindingFollowUps} selectedRow={selectedRow} onSelect={(row) => selectResultRow(row, "evidence")} onVisibleRowsChange={handleVisibleRowsChange} />}
            </section>

            {caseId && versionId && <section
              id="review-workspace-panel-activity"
              className="review-workspace-panel notes-activity-panel"
              role="tabpanel"
              aria-labelledby="review-workspace-tab-activity"
              hidden={workspaceTab !== "activity"}
            >
              <NotesActivityPanel caseId={caseId} initialOpenOnly={searchParams.get("activity") === "open-followups"} refreshToken={activityRefreshToken} onReviewDataChange={() => void loadReviewWorkspace(activeScreeningRunId, true)} />
            </section>}

            <div
              ref={formulationPanel}
              id="review-workspace-panel-formulation"
              className="review-workspace-panel formulation-workspace-panel"
              role="tabpanel"
              aria-labelledby="review-workspace-tab-formulation"
              hidden={workspaceTab !== "formulation"}
            >
            {prepared && !response && (
              <section className="agent-ready-panel">
                <div className="flex items-start justify-between gap-4"><div><p className="eyebrow">Formulation ready for screening</p><h2 className="section-title">{prepared.formulation.ingredients.length} ingredients</h2></div><Sparkles size={19} className="text-emerald-700" /></div>
                <div className="agent-ready-meta"><span>Formulation</span><strong>{prepared.formulation.formulation_name ?? "Untitled formulation"}</strong><span>Product context</span><strong>{prepared.formulation.product_context ?? "Not supplied"}</strong></div>
                <div className="mt-4 overflow-x-auto"><table className="agent-table"><thead><tr><th>Ingredient</th><th>Function</th><th>CAS</th><th>Concentration</th><th>Basis</th><th>Preparation stage</th><th>Source rows</th></tr></thead><tbody>{prepared.formulation.ingredients.map((ingredient, index) => <tr key={`${ingredient.name}-${index}`}><td><strong>{ingredient.name}</strong></td><td>{ingredient.regulated_functions?.map((item) => item.replaceAll("_", " ")).join(", ") || "Not declared"}</td><td>{ingredient.cas_number ?? "—"}</td><td>{ingredient.concentration ? `${ingredient.concentration.value} ${ingredient.concentration.unit}` : "—"}</td><td>{ingredient.concentration?.basis ?? "No specific basis"}</td><td>{ingredient.concentration ? ingredient.concentration.preparation_stage.replaceAll("_", " ") : "—"}</td><td>{prepared.row_provenance[index]?.source_rows.join(", ")}</td></tr>)}</tbody></table></div>
                <div className="mt-5 flex justify-between gap-3"><button className="secondary-button" type="button" onClick={() => setPrepared(null)}>Back to interpretation</button><button className="primary-button" type="button" onClick={screenPrepared} disabled={busy}>{busy ? <><LoaderCircle className="animate-spin" size={15} /> Screening…</> : <><Check size={15} /> Confirm & Screen</>}</button></div>
              </section>
            )}

            <section className="agent-status-panel">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="eyebrow">{retrying ? "Interpreting formulation" : interruptedPersistentInterpretation ? "Interpretation interrupted" : session.state === "failed" ? "Interpretation could not be completed" : "Analysis complete"}</p>
                  <h2 className="section-title">Formulation interpretation</h2>
                </div>
                {!versionId && <button className="secondary-button shrink-0" type="button" onClick={startNewCSV} disabled={busy}>
                  <FileUp size={14} /> Start new file
                </button>}
              </div>
              <div className="agent-stat-strip" aria-label="Formulation interpretation">
                <span><strong>{session.interpreted_rows.length - rowsNeedingConfirmation.size}</strong> formulation rows interpreted</span>
                <span><strong>{session.questions.length}</strong> input clarifications pending</span>
              </div>

              {retrying && <div className="agent-failure"><LoaderCircle className="animate-spin" size={17} /><span>Regulens is identifying the formulation structure and ingredient fields.</span></div>}
              {interruptedPersistentInterpretation && <div className="agent-failure"><AlertTriangle size={17} /><span>The previous request did not finish. Your uploaded file has been preserved.</span><button className="secondary-button" type="button" onClick={retry} disabled={busy}><RotateCcw size={14} /> Retry</button></div>}
              {session.state === "failed" && !retrying && <div className="agent-failure"><AlertTriangle size={17} /><span>{session.error?.message}</span><button className="secondary-button" type="button" onClick={retry} disabled={busy}><RotateCcw size={14} /> Retry</button></div>}
            </section>

            {clarificationQuestions.length > 0 && (
              <section className="guided-confirmations" aria-labelledby="confirmation-heading">
                <div className="guided-section-heading"><div><p className="eyebrow">Clarification required</p><h2 id="confirmation-heading" className="section-title">Needs confirmation</h2></div><span className="guided-count">{clarificationQuestions.length} question{clarificationQuestions.length === 1 ? "" : "s"}</span></div>
                <div className="agent-question-grid">{clarificationQuestions.map((question) => {
                  const row = question.row_id ? session.interpreted_rows.find((item) => item.row_id === question.row_id) : null;
                  const candidate = question.question_type === "identity" ? question.options.find((option) => option.option_id === "confirm_candidate") : null;
                  const enteredName = question.question_type === "identity" ? question.options.find((option) => option.option_id === "confirm_entered") : null;
                  const clarificationTarget = reviewWorkspace?.clarification_targets.find((item) => item.question_key === question.question_id);
                  const savedClarificationNotes = clarificationTarget ? reviewWorkspace?.notes.filter((item) => item.clarification_id === clarificationTarget.id) ?? [] : [];
                  const clarificationFollowUps = clarificationTarget ? reviewWorkspace?.follow_ups.filter((item) => item.clarification_id === clarificationTarget.id) ?? [] : [];
                  const clarificationNoteState = clarificationTarget ? writeState(`clarification-note:${clarificationTarget.id}`) : idleWriteState;
                  const clarificationFollowUpState = clarificationTarget ? writeState(`clarification-follow-up:${clarificationTarget.id}`) : idleWriteState;
                  return (
                  <article id={`agent-question-${question.question_id}`} className={`agent-question ${highlightedQuestion === question.question_id ? "agent-target-highlight" : ""}`} key={question.question_id}>
                    {row && <div className="agent-question-row"><strong>Row {row.source_row} · {row.name.source_value ?? row.name.value}</strong><button type="button" onClick={() => focusRow(row.row_id, question.target_field)}>View row</button></div>}
                    <h3>{question.title}</h3>
                    {question.question_type === "identity" && row ? <div className="agent-question-facts"><span>Submitted</span><strong>{row.name.source_value}</strong>{enteredName && <><span>Entered name</span><strong>{String(enteredName.value)}</strong></>}{candidate && <><span>Possible source-backed match</span><strong>{String(candidate.value)}</strong><span>Source</span><strong>{row.catalogue_identity?.source_name ?? "EU Common Ingredient Glossary"}</strong></>}</div> : <p>{question.prompt}</p>}
                    {question.question_type === "preparation_stage" && <ul className="agent-question-rows">{question.affected_row_ids.map((rowId) => { const affected = session.interpreted_rows.find((item) => item.row_id === rowId); return affected ? <li key={rowId}><span>Row {affected.source_row} · {affected.name.source_value ?? affected.name.value}</span><button type="button" onClick={() => focusRow(rowId, "preparation_stage")}>View row</button></li> : null; })}</ul>}
                    {question.question_type === "non_numeric_concentration" && (() => {
                      const manual = manualValues[question.question_id] ?? { value: "", unit: "percent" as ConcentrationUnit, stage: "finished_product" as PreparationStage };
                      return <div className="mt-3 grid grid-cols-3 gap-2">
                        <input className="field-control" type="number" min="0" placeholder="Value" aria-label={`${question.title} manual value`} value={manual.value} onChange={(event) => setManualValues((current) => ({ ...current, [question.question_id]: { ...manual, value: event.target.value } }))} />
                        <select className="field-control" aria-label={`${question.title} manual unit`} value={manual.unit} onChange={(event) => setManualValues((current) => ({ ...current, [question.question_id]: { ...manual, unit: event.target.value as ConcentrationUnit } }))}><option value="percent">%</option><option value="ppm">ppm</option><option value="mg/kg">mg/kg</option></select>
                        <select className="field-control" aria-label={`${question.title} manual stage`} value={manual.stage} onChange={(event) => setManualValues((current) => ({ ...current, [question.question_id]: { ...manual, stage: event.target.value as PreparationStage } }))}><option value="finished_product">Finished product</option><option value="after_mixing">After mixing</option><option value="ready_for_use">Ready for use</option></select>
                      </div>;
                    })()}
                    {question.question_type === "identity" && !candidate && row && <button className="secondary-button mt-3" type="button" onClick={() => focusRow(row.row_id, "ingredient_name")}>Edit ingredient name</button>}
                    <div className="mt-3 flex flex-wrap gap-2">{question.options.map((option) => <button className="secondary-button" key={option.option_id} type="button" onClick={() => void answer(question, option.option_id)} disabled={busy}>{option.label}</button>)}</div>
                    {versionId && reviewDataState === "available" && <details className="guided-question-notes">
                      <summary>Reviewer notes &amp; follow-ups{savedClarificationNotes.length + clarificationFollowUps.length > 0 ? ` · ${savedClarificationNotes.length} notes · ${clarificationFollowUps.length} follow-ups` : ""}</summary>
                      <div className="mt-3 space-y-2">
                      {savedClarificationNotes.length > 0 && <ul className="review-note-list compact">{savedClarificationNotes.map((item) => <li key={item.id}><p>{item.body}</p><small>{item.author_name} · {new Date(item.created_at).toLocaleString()}</small></li>)}</ul>}
                      <div className="review-inline-form compact"><input aria-label={`${question.title} reviewer note`} value={clarificationNotes[question.question_id] ?? ""} maxLength={4000} placeholder="Reviewer note" onChange={(event) => { setClarificationNotes((current) => ({ ...current, [question.question_id]: event.target.value })); if (clarificationTarget) setWriteState(`clarification-note:${clarificationTarget.id}`, idleWriteState); }} /><button className="text-button" type="button" disabled={clarificationNoteState.phase === "saving" || !(clarificationNotes[question.question_id] ?? "").trim()} onClick={() => void addClarificationNote(question, clarificationNotes[question.question_id] ?? "")}>{clarificationNoteState.phase === "saving" ? "Saving…" : clarificationNoteState.phase === "failed" ? "Retry note" : `Add note${savedClarificationNotes.length ? ` (${savedClarificationNotes.length} saved)` : ""}`}</button></div>
                      {clarificationNoteState.phase !== "idle" && clarificationNoteState.phase !== "saving" && <p className={`write-state is-${clarificationNoteState.phase}`} role={clarificationNoteState.phase === "failed" ? "alert" : "status"}>{clarificationNoteState.phase === "saved" ? "Note saved" : clarificationNoteState.message}</p>}
                      <div className="review-inline-form compact"><input aria-label={`${question.title} follow-up`} value={clarificationActions[question.question_id] ?? ""} maxLength={1000} placeholder="Follow-up action" onChange={(event) => { setClarificationActions((current) => ({ ...current, [question.question_id]: event.target.value })); if (clarificationTarget) setWriteState(`clarification-follow-up:${clarificationTarget.id}`, idleWriteState); }} /><button className="text-button" type="button" disabled={clarificationFollowUpState.phase === "saving" || !(clarificationActions[question.question_id] ?? "").trim()} onClick={() => void addClarificationFollowUp(question, clarificationActions[question.question_id] ?? "")}>{clarificationFollowUpState.phase === "saving" ? "Saving…" : clarificationFollowUpState.phase === "failed" ? "Retry follow-up" : "Add follow-up"}</button></div>
                      {clarificationFollowUpState.phase !== "idle" && clarificationFollowUpState.phase !== "saving" && <p className={`write-state is-${clarificationFollowUpState.phase}`} role={clarificationFollowUpState.phase === "failed" ? "alert" : "status"}>{clarificationFollowUpState.phase === "saved" ? "Follow-up saved" : clarificationFollowUpState.message}</p>}
                      {clarificationFollowUps.filter((item) => item.status === "open").map((item) => { const toggleState = writeState(`follow-up-toggle:${item.id}`); return <div className="review-follow-up-inline" key={item.id}><button className="text-button" type="button" disabled={toggleState.phase === "saving"} onClick={() => void toggleFollowUp(item)}>Open: {item.action_text} · {toggleState.phase === "saving" ? "Saving…" : toggleState.phase === "failed" ? "Retry resolve" : "Resolve"}</button>{toggleState.phase === "failed" && <p className="write-state is-failed" role="alert">{toggleState.message}</p>}</div>; })}
                      </div>
                    </details>}
                  </article>
                );})}</div>
              </section>
            )}

            {session.interpreted_rows.length > 0 && (
              <section className="agent-details-panel">
                <div>
                  <p className="eyebrow">Formulation details</p>
                  <h2 className="section-title">Screening input</h2>
                </div>
                <div className="mt-4 grid gap-4 md:grid-cols-3">
                  <label className="field-label">Formulation ID <span className="optional-label">Optional</span><input className="field-control" value={formulationId} onChange={(event) => setFormulationId(event.target.value)} /></label>
                  <label className="field-label">Formulation name <span className="optional-label">Optional</span><input className="field-control" value={formulationName} onChange={(event) => setFormulationName(event.target.value)} /></label>
                  <div className="field-label">
                    <div className="flex items-center gap-1.5"><span>Product context</span><HelpHint label="Agent Product context"><p>Some restrictions depend on the exact cosmetic product type. Select only an accepted backend option; the Agent does not infer a regulatory hierarchy.</p></HelpHint></div>
                    <span className="optional-label">Optional when unavailable</span>
                    <select aria-label="Agent Product context" className="field-control" value={contextQuestion && !productContext ? "__unresolved" : productContext} disabled={busy} onChange={(event) => void changeProductContext(event.target.value)}>
                      {contextQuestion && <option value="__unresolved" disabled>Choose a product context</option>}
                      <option value="">No product context supplied</option>
                      {options?.product_contexts.map((context) => <option key={context}>{context}</option>)}
                    </select>
                  </div>
                </div>
                <div className="agent-detail-notes">
                  <p>{session.product_context?.source_value
                    ? <>Detected source value: <strong>{session.product_context.source_value}</strong>{session.product_context.value ? <> · Exact accepted match</> : <> · Confirmation required</>}</>
                    : <>No Product Context was detected in the source file. Choose an accepted value if known, or explicitly confirm that it is unavailable.</>}</p>
                  <p>{stageQuestion
                    ? <>Preparation stage: <strong>Finished product</strong> is only a visible proposal and has not been applied.</>
                    : <>Preparation stage values shown below come from the source or a confirmed selection.</>}</p>
                </div>
                {contextQuestion && <div className="agent-inline-question"><div><strong>{contextQuestion.title}</strong><p>{contextQuestion.prompt}</p></div></div>}

                {session.interpreted_rows.some((row) => (row.regulated_functions ?? []).length > 0) && (
                  <details className="mt-5 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3">
                    <summary className="cursor-pointer font-medium text-slate-800">Product-use facts for colourant, preservative, and UV-filter checks</summary>
                    <p className="mt-2 text-xs leading-5 text-slate-500">Choose only facts you know. Unknown facts remain incomplete and Regulens will not guess them.</p>
                    <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {applicabilityFields.map((field) => {
                        const value = productApplicability[field.key];
                        return <label className="field-label" key={field.key}>{field.label}<select className="field-control" value={value == null ? "unknown" : String(value)} onChange={(event) => setProductApplicability((current) => ({ ...current, [field.key]: event.target.value === "unknown" ? null : event.target.value === "true" }))}><option value="unknown">Unknown</option><option value="true">Yes</option><option value="false">No</option></select></label>;
                      })}
                    </div>
                  </details>
                )}

              </section>
            )}

            {session.interpreted_rows.length > 0 && (
              <section className="editor-panel">
                  <div className="section-heading-row"><div><p className="eyebrow">Ingredient interpretation</p><h2 className="section-title">Source values and screening fields</h2></div><span className="text-xs text-slate-500">Source value → structured value</span></div>
                <div className="agent-table-scroll">
                  <table className="agent-table">
                    <thead><tr><th>Source</th><th>Interpreted ingredient</th><th>Concentration</th><th>Status</th></tr></thead>
                    <tbody>{session.interpreted_rows.map((row) => {
                      const draft = drafts[row.row_id];
                      if (!draft) return null;
                      const rowQuestions = session.questions.filter((question) => question.row_id === row.row_id || question.affected_row_ids.includes(row.row_id));
                      const requiredFieldsFilled = draft.name.trim().length > 0;
                      const rowStatus = rowQuestions.length ? "Clarification needed" : requiredFieldsFilled ? "Input ready" : "Input incomplete";
                      const nameEdited = fieldWasEdited(row.name.value, row.name.source_value, row.name.confirmed_by_user);
                      const casEdited = fieldWasEdited(row.cas_number?.value, row.cas_number?.source_value, row.cas_number?.confirmed_by_user);
                      const valueEdited = fieldWasEdited(row.concentration?.value?.value, row.concentration?.value?.source_value, row.concentration?.value?.confirmed_by_user);
                      const unitEdited = fieldWasEdited(row.concentration?.unit?.value, row.concentration?.unit?.source_value, row.concentration?.unit?.confirmed_by_user);
                      const basisEdited = fieldWasEdited(row.concentration?.basis?.value, row.concentration?.basis?.source_value, row.concentration?.basis?.confirmed_by_user);
                      const stageEdited = fieldWasEdited(row.concentration?.preparation_stage?.value, row.concentration?.preparation_stage?.source_value, row.concentration?.preparation_stage?.confirmed_by_user);
                      return <tr id={`agent-row-${row.row_id}`} className={highlightedRow === row.row_id ? "agent-target-highlight" : ""} key={row.row_id}>
                        <td><small>Row{row.source_rows.length > 1 ? "s" : ""} {row.source_rows.join(", ")}</small><strong>{row.name.source_value}</strong></td>
                        <td><div className="agent-field-stack">
                          <label><span>Ingredient name {nameEdited && <em className="edited-field-marker">Edited</em>}</span><input data-agent-field="ingredient_name" className="field-control" aria-label={`Row ${row.source_row} interpreted name`} value={draft.name} onChange={(event) => setDrafts((current) => ({ ...current, [row.row_id]: { ...draft, name: event.target.value } }))} onBlur={() => void saveRow(row.row_id, draft, "name")} /></label>
                          <label><span>CAS, if supplied {casEdited && <em className="edited-field-marker">Edited</em>}</span><input className="field-control" aria-label={`Row ${row.source_row} CAS`} value={draft.cas} placeholder="—" onChange={(event) => setDrafts((current) => ({ ...current, [row.row_id]: { ...draft, cas: event.target.value } }))} onBlur={() => void saveRow(row.row_id, draft, "cas")} /></label>
                          <fieldset data-agent-field="regulated_functions" className="mt-2"><legend className="text-xs font-medium text-slate-600">Regulated function</legend><div className="mt-1 flex flex-wrap gap-2">{(["colourant", "preservative", "uv_filter"] as RegulatedFunction[]).map((value) => <label className="inline-flex items-center gap-1 text-xs" key={value}><input type="checkbox" checked={draft.regulatedFunctions.includes(value)} onChange={(event) => { const next = { ...draft, regulatedFunctions: event.target.checked ? [...draft.regulatedFunctions, value] : draft.regulatedFunctions.filter((item) => item !== value) }; setDrafts((current) => ({ ...current, [row.row_id]: next })); void saveRow(row.row_id, next, "functions"); }} />{value.replace("_", " ")}</label>)}</div></fieldset>
                        </div></td>
                        <td><div className="agent-concentration-grid">
                          <label><span>Value {valueEdited && <em className="edited-field-marker">Edited</em>}</span><input data-agent-field="concentration" className="field-control" aria-label={`Row ${row.source_row} concentration`} value={draft.value} placeholder="—" onChange={(event) => setDrafts((current) => ({ ...current, [row.row_id]: { ...draft, value: event.target.value } }))} onBlur={() => { if (draft.value.trim()) void saveRow(row.row_id, draft, "concentration"); }} /></label>
                          <label><span>Unit {unitEdited && <em className="edited-field-marker">Edited</em>}</span><select data-agent-field="concentration.unit" className="field-control" aria-label={`Row ${row.source_row} unit`} value={draft.unit} onChange={(event) => { const next = { ...draft, unit: event.target.value as ConcentrationUnit | "" }; setDrafts((current) => ({ ...current, [row.row_id]: next })); if (next.value.trim()) void saveRow(row.row_id, next, "concentration"); }}><option value="">Choose unit</option><option value="percent">%</option><option value="ppm">ppm</option><option value="mg/kg">mg/kg</option></select></label>
                          <label><span>Basis {basisEdited && <em className="edited-field-marker">Edited</em>}</span><select className="field-control" aria-label={`Row ${row.source_row} basis`} value={draft.basis ?? ""} onChange={(event) => { const next = { ...draft, basis: optional(event.target.value) as ConcentrationBasis | null }; setDrafts((current) => ({ ...current, [row.row_id]: next })); if (next.value.trim()) void saveRow(row.row_id, next, "concentration"); }}><option value="">No specific basis</option>{options?.concentration_bases.filter((basis): basis is ConcentrationBasis => basis !== null).map((basis) => <option key={basis} value={basis}>{basis}</option>)}</select></label>
                          <label><span>Preparation stage {stageEdited && <em className="edited-field-marker">Edited</em>}</span><select data-agent-field="preparation_stage" className="field-control" aria-label={`Row ${row.source_row} stage`} value={draft.stage} onChange={(event) => { const next = { ...draft, stage: event.target.value as PreparationStage | "" }; setDrafts((current) => ({ ...current, [row.row_id]: next })); if (next.value.trim()) void saveRow(row.row_id, next, "concentration"); }}><option value="">Choose stage</option><option value="finished_product">Finished product</option><option value="after_mixing">After mixing for use</option><option value="ready_for_use">Ready for use</option></select></label>
                        </div></td>
                        <td>
                          <button className={`agent-row-status ${rowQuestions.length ? "warning" : rowStatus === "Input incomplete" ? "unresolved" : "ready"}`} type="button" title={rowStatus === "Input ready" ? "All required formulation input is complete" : undefined} onClick={() => rowQuestions[0] && focusQuestion(rowQuestions[0].question_id)}>{rowStatus}{rowQuestions.length ? ` · ${rowQuestions.length} issue${rowQuestions.length === 1 ? "" : "s"}` : ""}</button>
                        </td>
                      </tr>;
                    })}</tbody>
                  </table>
                </div>
              </section>
            )}

            {blockingItems.length > 0 && session.state !== "failed" && (
              <section className="agent-blocking-summary" aria-live="polite">
                <strong>{blockingItems.length} item{blockingItems.length === 1 ? "" : "s"} still need confirmation</strong>
                <ul>{blockingItems.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
              </section>
            )}

            {versionId && (
              <section className="agent-details-panel guided-formulation-notes" aria-labelledby="formulation-notes-heading">
                <p className="eyebrow">Supporting details</p>
                <h2 id="formulation-notes-heading" className="section-title">Formulation notes</h2>
                {reviewDataState === "loading" && <p className="review-data-notice mt-3">Loading review information…</p>}
                {reviewDataState === "unavailable" && <p className="review-data-notice mt-3">Review information is unavailable.</p>}
                {reviewDataState === "available" && <div className="mt-3 space-y-3">
                {formulationReviewerNotes.length > 0 && <ul className="review-note-list compact">{formulationReviewerNotes.map((item) => <li key={item.id}><p>{item.body}</p><small>{item.author_name} · {new Date(item.created_at).toLocaleString()}</small></li>)}</ul>}
                <div className="review-inline-form compact"><input aria-label="Formulation reviewer note" value={formulationNote} maxLength={4000} placeholder="Add a note about this formulation version" onChange={(event) => { setFormulationNote(event.target.value); if (versionId) setWriteState(`formulation-note:${versionId}`, idleWriteState); }} /><div className="flex items-center gap-3"><button className="secondary-button" type="button" disabled={formulationNoteWriteState.phase === "saving" || !formulationNote.trim()} onClick={() => void addFormulationNote()}>{formulationNoteWriteState.phase === "saving" ? "Saving…" : formulationNoteWriteState.phase === "failed" ? "Retry note" : "Add formulation note"}</button><span className="text-xs text-slate-500">{formulationReviewerNotes.length} saved</span></div></div>
                {formulationNoteWriteState.phase !== "idle" && formulationNoteWriteState.phase !== "saving" && <p className={`write-state is-${formulationNoteWriteState.phase}`} role={formulationNoteWriteState.phase === "failed" ? "alert" : "status"}>{formulationNoteWriteState.phase === "saved" ? "Formulation note saved" : formulationNoteWriteState.message}</p>}
                </div>}
              </section>
            )}

            {session.interpreted_rows.some((row) => row.source_metadata.length > 0) && (
              <details className="agent-source-metadata">
                <summary>Source metadata</summary>
                <p>Preserved exactly from non-regulatory CSV columns. These values are not sent to the screening engine.</p>
                <div className="mt-3 overflow-x-auto">
                  <table className="agent-table"><thead><tr><th>Source row</th><th>Column</th><th>Original value</th></tr></thead><tbody>
                    {session.interpreted_rows.flatMap((row) => row.source_metadata.map((item, index) => <tr key={`${row.row_id}-${item.source_row}-${item.source_column_index}-${index}`}><td>Row {item.source_row ?? row.source_row}</td><td>{item.source_column}</td><td>{item.source_value}</td></tr>))}
                  </tbody></table>
                </div>
              </details>
            )}

            <details className="agent-activity"><summary>Agent activity</summary><ul>{session.activity.map((item) => <li key={item.activity_id}><span>{item.status === "complete" ? "✓" : "⚠"}</span>{item.message}</li>)}</ul></details>
            {session.attempt_diagnostics.length > 0 && <details className="agent-activity"><summary>Technical activity</summary><p className="mt-3 text-xs text-slate-500">{session.attempts} attempt{session.attempts === 1 ? "" : "s"}{session.successful_attempt ? ` · successful attempt ${session.successful_attempt}` : ""}</p><ul>{session.attempt_diagnostics.map((attempt) => <li key={attempt.attempt_number}><span>{attempt.status === "success" ? "✓" : "⚠"}</span>Attempt {attempt.attempt_number} · {attempt.status}{attempt.failure_category ? ` · ${attempt.failure_category.replaceAll("_", " ")}` : ""} · {attempt.actual_model ?? attempt.configured_model} · {attempt.input_tokens} input · {attempt.output_tokens} output · {attempt.tool_calls} tool calls</li>)}</ul>{session.total_usage && <p className="mt-3 text-xs text-slate-500">Total usage · {session.total_usage.input_tokens} input tokens · {session.total_usage.output_tokens} output tokens · {session.total_usage.tool_calls} tool calls</p>}</details>}
            </div>

          </div>
        )}
      </main>
      <EvidenceDrawer key={findingsStateKey} result={selectedResult} sources={response?.dataset.sources ?? []} inputProvenance={provenance} explanationMetadata={response?.review_explanation_metadata ?? null}
        reviewDataState={reviewDataState} hasPrevious={hasPreviousResult} hasNext={hasNextResult}
        activeTab={drawerTab} onActiveTabChange={(tab) => { setDrawerTab(tab); updateWorkspaceParams({ drawer: tab }); }}
        onPrevious={() => hasPreviousResult && selectResultRow(visibleResultRows[selectedResultIndex - 1])}
        onNext={() => hasNextResult && selectResultRow(visibleResultRows[selectedResultIndex + 1])}
        reviewItem={selectedReviewItem} reviewerNotes={selectedReviewerNotes} followUps={selectedFollowUps}
        statusWriteState={selectedStatusWriteState} noteWriteState={selectedNoteWriteState} followUpWriteState={selectedFollowUpWriteState}
        pendingReviewStatus={selectedReviewItem ? pendingReviewStatuses[selectedReviewItem.id] ?? null : null}
        followUpWriteStates={Object.fromEntries(selectedFollowUps.map((item) => [item.id, writeState(`follow-up-toggle:${item.id}`)]))}
        noteDraft={selectedReviewDraft.note} followUpDraft={selectedReviewDraft.followUp}
        onNoteDraftChange={(note) => { setReviewDrafts((current) => ({ ...current, [reviewDraftKey]: { ...(current[reviewDraftKey] ?? { note: "", followUp: "" }), note } })); if (selectedReviewItem) setWriteState(`note:${selectedReviewItem.id}`, idleWriteState); }}
        onFollowUpDraftChange={(followUp) => { setReviewDrafts((current) => ({ ...current, [reviewDraftKey]: { ...(current[reviewDraftKey] ?? { note: "", followUp: "" }), followUp } })); if (selectedReviewItem) setWriteState(`follow-up:${selectedReviewItem.id}`, idleWriteState); }}
        onReviewStatusChange={versionId ? changeReviewStatus : undefined} onAddReviewerNote={versionId ? addFindingNote : undefined}
        onAddFollowUp={versionId ? addFindingFollowUp : undefined} onToggleFollowUp={versionId ? toggleFollowUp : undefined}
        onClose={closeEvidenceDrawer} />
    </div>
  );
}
