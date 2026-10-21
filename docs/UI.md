# Regulens UI/UX reference

Status: design reference for current and future frontend work  
Last researched and audited: 21 October 2026

This document is the central UI reference for Regulens. It records the intended information architecture, interaction patterns, visual system, and implementation priorities. It does not replace the product scope or regulatory safeguards in `VIP_SoC_Cosmetics_MVP_Scope.md` and `AGENTS.md`.

The guiding principle is:

> One workspace, one current task, details available on demand.

## 1. Product UX vision

Regulens is a professional regulatory-review workspace, not a general analytics dashboard and not a legal approval engine. It should help a consultant move quickly from a case to the next unresolved item while keeping the regulatory basis visible and trustworthy.

The experience should be:

- Clear for a first-time user without requiring repeated navigation between instructions and work.
- Efficient for a returning professional reviewing many ingredient rows.
- Calm and compact enough for extended use, without hiding important evidence.
- Explicit about what the deterministic screening engine found, what remains uncertain, and what a human reviewer has done.
- Traceable. Every finding must retain its source wording, document metadata, rule reference, and screening snapshot.
- Conservative in language. Regulens reports bounded ingredient-level screening findings; it never presents a product as approved, compliant, or safe.

Regulens is a desktop-first product workspace with low decorative spectacle and high useful density. Motion is limited to state feedback, selection, drawer movement, progress, and focus restoration. The existing teal identity and top-left logo remain unchanged.

### Working hierarchy

Every screen should make these three layers visually distinct:

1. **Action:** the next meaningful task, such as Continue clarification, Run screening, Review next finding, or Save note.
2. **Critical information:** regulatory findings, unresolved identity, missing information, source differences, and outstanding follow-ups.
3. **Supporting detail:** provenance, full source wording, technical metadata, activity history, and previous versions.

Supporting detail stays available but should not push the current task below multiple summaries or cards.

## 2. Reference-product research

### Research method and limits

The research below used publicly accessible official product documentation and the screenshots or demonstrations embedded in those pages. No authenticated private workspace was accessed, so this document does not claim first-hand inspection of private account-only screens. Observed behavior is separated from the proposed Regulens adaptation.

### Linear: focused list work and fast navigation

Sources inspected:

- [Comments and reactions](https://linear.app/docs/comment-on-issues)
- [Select issues](https://linear.app/docs/select-issues)
- [Display options](https://linear.app/docs/display-options)
- [Official issue-selection screenshot](https://webassets.linear.app/images/ornj730p/production/88dde87f01f1e2291aef98dc32bd916bea2cc3b9-1784x977.png?auto=format&dpr=2&q=95&w=1440)

Observed patterns:

- A row can be highlighted independently of a larger multi-selection workflow. Keyboard navigation moves the highlight through the current list.
- Contextual actions appear around the selected issue instead of permanently occupying every row.
- Display preferences control grouping, ordering, layout, and visible properties. Personal changes persist when the user leaves and returns.
- Comments live in the context of an issue. Unsent comments remain visible as drafts, and resolved threads distinguish completed discussion from active discussion.
- Sticky grouping headers maintain orientation in long lists.

Regulens adaptation:

- Keep one clearly highlighted finding row and open its details without losing the filtered table.
- Previous and next navigation follows the current filtered order, not the unfiltered dataset.
- Preserve active filters, sorting, selected finding, and draft note when the user changes workspace tabs.
- Keep finding-level notes attached to a stable review item, not to an ingredient name.
- Design the interaction model so keyboard shortcuts can be added later without changing the layout.

Do not copy:

- Do not require users to learn keyboard shortcuts for the primary flow.
- Do not add command menus, bulk editing, reactions, or issue-management concepts that do not serve regulatory review.
- Do not make the interface as terse as a software issue tracker where regulatory meaning would become ambiguous.

### Airtable: record review and table-detail relationships

Source inspected:

- [Record review interface layout](https://support.airtable.com/articles/4384405105-airtable-interface-layout-record-review), including its embedded list and record-detail screenshots.

Observed patterns:

- Record review is explicitly organised into a record list, a selected-record detail page, and field-level properties.
- The list can expose a title plus a small number of preview fields rather than every property.
- Filtering, sorting, and grouping constrain the review set while the selected record supplies deeper detail.
- Comments and revision history belong to the opened record.

Regulens adaptation:

- Treat the findings table as the primary work surface and the evidence drawer as the selected-record detail surface.
- Limit default table columns to identity, submitted concentration, regulatory result, principal rule, and human review status.
- Put the full source wording, comparisons, provenance, and review controls in the detail surface.
- Keep filters close to the table and expose an immediate result count.

Do not copy:

- Do not expose an open-ended interface builder or arbitrary field configuration in the immediate milestone.
- Do not turn regulatory evidence into user-editable record properties.
- Do not use conditional colour as the only status signal.

### Notion: contextual notes and views

Sources inspected:

- [Views, filters, sorts and groups](https://www.notion.com/help/views-filters-and-sorts)
- [Database properties](https://www.notion.com/help/database-properties)
- [Comments and discussions](https://www.notion.com/help/guides/comments-and-discussions)

Observed patterns:

- Table, list, board, and timeline views can open a record as a side peek, centre peek, or full page. Side peek keeps the underlying database interactive.
- Filters and sorts can be personal or saved for everyone.
- General discussion can live at the page level while comments on specific content provide tactical context.
- Typed properties keep status, text, dates, and relationships distinct.

Regulens adaptation:

- Use a right-side detail drawer so the findings table remains visible and interactive.
- Distinguish case notes from formulation, clarification, and finding notes.
- Build one Notes & Activity view that aggregates these contexts and clearly labels each entry.
- Let a user jump from an activity item to the associated finding or clarification.

Do not copy:

- Do not build a block editor, nested documents, arbitrary databases, or a general knowledge-management system.
- Do not introduce several interchangeable views before the findings-table workflow is mature.
- Do not hide regulatory concepts behind generic user-created properties.

### Vanta: automated evidence versus human assessment

Sources inspected:

- [Controls page](https://help.vanta.com/en/articles/11345373-controls-page)
- [Automated test evidence](https://help.vanta.com/en/articles/11345529-automated-test-evidence)
- [Tests page](https://help.vanta.com/en/articles/11345374-the-tests-page)

Observed patterns:

- Vanta states that a control status reflects mapped tests and documents, not an auditor's assessment.
- The tests list prioritises urgent work and supports search and status/category filtering.
- Test detail is separated into Results, Evidence, History, Tasks, Controls, Audits, and Notes.
- Evidence explains criteria, itemised resources, status, supporting data, exclusions, and retrieval details. Selecting an evidence row opens detailed information in a side panel.

Regulens adaptation:

- Visually separate the deterministic regulatory outcome from the human review status.
- Use evidence and review as distinct drawer tabs.
- Keep scope and exclusions visible so a completed scoped check is not mistaken for comprehensive compliance.
- Default the results list toward urgent or unresolved work while keeping All results one click away.

Do not copy:

- Do not use security-control language such as pass/fail where it would overstate a cosmetic regulatory conclusion.
- Do not add framework mapping, assignment hierarchies, audit workflows, or compliance scoring.
- Do not let a reviewer status alter or replace the engine finding.

### Filestage: future label-artwork review

Source inspected:

- [Commenting on files](https://help.filestage.io/en/articles/7002949-commenting-on-files), including its embedded marker, annotation, and document-view demonstrations.

Observed patterns:

- A comment can be general or attached to a precise position in an image, video, PDF, or Office document.
- Reviewers can use markers, drawings, rectangles, arrows, and text selection to anchor feedback.
- Comments can be replied to or pinned, and document views support zoom and fit-to-page controls.

Future Regulens adaptation:

- A label-review finding may eventually link to a page and bounded artwork location.
- General label observations and location-specific observations should remain different contexts.
- Formula-label mismatch and mandatory-particular findings should open the relevant artwork position while retaining regulatory evidence.

Do not copy now:

- Do not implement annotation tools, artwork comments, document version comparison, or label checking in the current UI milestone.
- Do not reuse formulation-review notes as artwork coordinates; the data model is different.

## 3. Current UI audit

### Existing routes and interfaces

| Route | Current purpose | Main implementation |
|---|---|---|
| `/sign-in`, `/sign-up` | Authentication | `frontend/src/pages/AuthPages.tsx` |
| `/cases`, `/cases/new` | Case list and creation | `frontend/src/pages/CasesPage.tsx` |
| `/cases/:caseId` | Case overview, versions, case notes | `frontend/src/pages/CasePage.tsx` |
| `/cases/:caseId/formulations/:versionId` | Persistent formulation interpretation, screening, evidence, and review | `frontend/src/pages/FormulationWorkspacePage.tsx`, `AgentPage.tsx` |
| `/screen` | Ad hoc manual screening without a saved case workflow | `frontend/src/pages/FormulaScreeningPage.tsx` |
| `/sources` | Accepted regulatory record search and source evidence | `frontend/src/pages/SourcesPage.tsx` |

### Strengths to preserve

- The route hierarchy already expresses cases, formulation versions, immutable screening runs, and sources.
- The four-stage formulation progress indicator and live confirmation control provide clear first-time guidance.
- `ResultsTable` already supports keyboard opening with Enter or Space and keeps selected-row styling.
- `EvidenceDrawer` exposes submitted facts, identity resolution, scope, source wording, accepted evidence, comparisons, warnings, and provenance.
- Reviewer status is explicitly described as separate from the regulatory finding.
- Notes and follow-ups are stored against typed targets (`case`, `formulation`, `clarification`, or `review_item`) rather than ingredient names.
- A `ReviewItem` retains the screening run and submitted row number, so duplicate ingredient names can remain distinct.
- Saved screening runs are immutable and can reload their matching review workspace.
- Draft note text is retained after a failed save inside `ReviewerWorkspace`.
- The existing teal branding, tinted canvas, subtle borders, focus outlines, reduced-motion fallback, and responsive drawer provide a sound visual base.

### Main usability problems

1. **The screening result repeats the same work set.** `ScreeningSummary.tsx` renders six large count cards, secondary counts, a Human Review list, and a What Needs Attention list before `ResultsTable.tsx`. The table already contains the actionable rows and status. The repetition lengthens the page and makes users reconcile several counts.
2. **Counts describe different units without a shared model.** Ingredient counts, finding counts, unresolved identities, review-required rows, and reviewer statuses are visually adjacent and can appear interchangeable.
3. **The primary table arrives too late.** On typical laptop heights, users may process summary cards and duplicate lists before reaching the main review surface.
4. **The persistent formulation page combines several jobs in one vertical document.** `AgentPage.tsx` contains upload, clarification, metadata, row editing, notes, source metadata, agent activity, screening results, and run history. After screening, formulation editing remains below the findings rather than becoming a separate workspace view.
5. **The detail drawer mixes two authorities.** `EvidenceDrawer.tsx` places `ReviewerWorkspace` near the top of the same long scroll as system-generated evidence. Users must distinguish editable human workflow from immutable regulatory evidence through copy alone.
6. **The drawer is deep and lacks review navigation.** There are no Evidence/Review tabs and no previous/next finding controls. Reviewing ten findings requires closing or returning to the table repeatedly.
7. **Notes are contextually stored but visually fragmented.** Case notes appear on `CasePage`, formulation notes and clarification notes appear in `AgentPage`, and finding notes appear in the drawer. There is no central activity view that identifies and links all contexts.
8. **The Case Overview has no single resume action.** Upload and Delete sit together in the header, while the user must infer which formulation version or screening run to open.
9. **Saving feedback is incomplete.** API-confirmed saves occur, and failures surface through a page-level error, but there is no consistent saving/saved/failed indicator near the action. Status changes also lack a compact retry affordance.
10. **Filters are useful but incomplete.** The screening page supports Needs attention, Finding, and Review status, but not ingredient search, explicit preset tabs, sorting, or state restoration.

### Component disposition

| Existing component or surface | Decision | Reason and intended change |
|---|---|---|
| `Sidebar.tsx` | Retain with visual improvements | The three destinations are appropriate. Keep the logo and teal active marker. Add no new primary destination until the case workspace is reorganised. |
| `CasesPage.tsx` | Retain with visual improvements | The list and inline create flow are useful. Improve row hierarchy and expose the next case state, not more dashboard cards. |
| `CasePage.tsx` | Restructure or relocate | Keep versions, review overview, upload, notes, and delete. Recompose them around one contextual Continue Review action, a compact progress summary, a concise version list, and a small activity preview. Move destructive action away from the primary controls. |
| `AgentPage.tsx` upload and clarification flow | Retain with visual improvements | The confirmation model, progress, explicit ambiguity handling, and row provenance are valuable. Place them in the Formulation workspace tab and preserve the sticky progress behavior. |
| `ScreeningSummary.tsx` | Consolidate with another component | Replace the six-card grid and two duplicate action lists with one compact summary directly above the findings table. |
| `ScreeningResultsPanel.tsx` | Restructure | Make it the Results tab shell: compact summary, preset filters, search/sort, result count, and the table. Preserve existing deterministic data and review filters. |
| `ResultsTable.tsx` | Retain with visual improvements | It is the correct primary work surface. Add concise columns, stronger selected/focus states, empty-filter state, sorting, and stable selection. |
| `EvidenceDrawer.tsx` | Restructure | Retain the drawer and all evidence. Add Evidence and Review tabs, grouping/collapse, previous/next controls, and focus restoration. |
| `ReviewerWorkspace.tsx` | Retain with visual improvements | Keep status, notes, follow-ups, and draft retention. Place it exclusively under the Review tab and add local save state/error retry. |
| Formulation notes and clarification note controls | Consolidate with another component | Keep contextual creation where useful, but aggregate every entry in Notes & Activity with explicit context and jump links. |
| Screening-run history | Restructure or relocate | Keep immutable history. Move the active-run selector into the workspace header or a compact menu so users can change snapshots without scrolling to the bottom. |
| `FormulaEditor.tsx` and interpreted-row table | Retain with visual improvements | Keep the existing input semantics and deterministic request construction. Use it in the Formulation tab; do not duplicate it below Results. |
| `FormulaScreeningPage.tsx` | Retain as a secondary utility | Keep the ad hoc screen for demos and unsaved checks. Align its result workspace with the case-based Results pattern, but do not make it the preferred persistent flow. |
| `SourcesPage.tsx` | Retain with visual improvements | Search, record list, evidence detail, full-page source viewing, and original wording are appropriate. Reuse the same evidence conventions as the finding drawer. |
| Auth pages | Retain as is | They are short, clear, and outside the review-workspace problem. |

Nothing in this audit requires changing regulatory evaluation, status enums, source data, API decisions, or the logo.

## 4. Information architecture

### Three product levels

#### Level 1: Case Overview

Answers: What is this case, what state is it in, and what should I do next?

Contains case identity, jurisdiction, client, current formulation version, compact progress, outstanding work, versions, recent activity, and one contextual Continue Review action. It does not contain the full formulation table or detailed evidence.

#### Level 2: Formulation Review Workspace

Answers: What am I reviewing in this formulation version?

Persistent tabs:

- **Results**: default after a screening exists; contains ingredient-result rows and their bounded regulatory findings.
- **Formulation**: uploaded/interpreted data, clarifications, and preparation.
- **Notes & Activity**: all case/formulation/clarification/finding notes, follow-ups, and relevant review activity.

The workspace header identifies the case, formulation version, screening run, jurisdiction, and current task. Switching tabs must not discard filters, row selection, or unsaved note text.

#### Level 3: Finding Details

Answers: Why did Regulens produce this result, and what should the reviewer do?

Open as a right-side drawer with two internal tabs:

- **Regulatory Evidence**: immutable system result and source traceability.
- **Review**: reviewer status, notes, follow-ups, and related activity.

### Navigation diagram

```text
Cases
  |
  +-- Case Overview
        |-- Continue Review (contextual)
        |-- Formulation versions
        |-- Recent Notes & Activity
        |
        +-- Formulation Review Workspace
              |-- Results (default after screening)
              |     |-- Filters + ingredient results table
              |     +-- Selected Finding Drawer
              |           |-- Regulatory Evidence
              |           +-- Review
              |
              |-- Formulation
              |     |-- Upload / interpretation
              |     |-- Clarifications
              |     +-- Confirm and screen
              |
              +-- Notes & Activity
                    |-- Case notes
                    |-- Formulation / clarification notes
                    |-- Finding notes
                    +-- Follow-ups and review events

Sources ------------------------------------------------> Regulatory evidence links
```

### Entity and context rules

- A case owns formulation versions.
- A formulation version owns its uploaded source, interpretation, clarifications, and screening runs.
- A screening run is an immutable snapshot of the request, regulatory dataset, and findings.
- A review item belongs to one screening run and one submitted row/subject key.
- A finding note targets a review item. It must never target only an ingredient name.
- A clarification note targets a clarification record, even when it refers to a row.
- A formulation note targets one version; a case note targets the case.
- A follow-up is an action with open/resolved state. A note is an observation or professional decision. Do not combine their status systems.
- Source records remain immutable evidence and are linked from findings; they are not owned by a case.

## 5. Page-by-page design specifications

### Cases list

**Purpose:** locate or create a case quickly.  
**Primary action:** New Case.  
**Hierarchy:** page title and New Case action, visible search and lifecycle controls, compact secondary-filter disclosure, then a compact row list.

Each row shows case/product name, client if present, current version/file, current workflow state, outstanding review work, open follow-ups, and last updated time. The case name opens Case Overview. Its contextual action opens the exact version/run/tab task directly, while a separate three-dot menu contains destructive actions. Do not turn the row itself into one nested click target and do not add analytics cards.

Search covers case name, client, and latest filename. Lifecycle remains visible; workflow and review filters live in a compact disclosure with an active-filter count and one Clear action. A restrained **Continue where you left off** row points directly to the newest active unfinished task rather than adding another dashboard section.

States:

- Loading: stable row skeletons or one restrained loading line; no layout shift in the header.
- Empty: explain that a case stores versions and review history, with one Create Case action.
- Error: inline retry preserving any case-creation draft.
- New case: keep the existing compact form, then navigate to the created case only after backend confirmation.

### Case Overview

**Purpose:** understand case state and resume work.  
**Primary action:** a contextual Continue Review button.  
**Secondary action:** Upload New Version.  
**Destructive action:** Delete Case inside a separated danger area or overflow menu with confirmation.

The shared case-action resolver supplies both label and destination. Continue/resume actions follow this order:

1. No formulation: **Upload formulation**.
2. Failed interpretation: **Retry interpretation**.
3. Uploaded/interpreting input or a genuine unresolved clarification: **Continue clarification**.
4. Interpreted/ready formulation without its own screening: **Start screening**. Backend `interpreted` means interpretation is complete; it must not be presented as a pending clarification.
5. Saved screening with unresolved reviewer items: **Continue review** in that exact Results run and Review drawer.
6. Open follow-ups without remaining reviewer items: **Continue review** in Notes & Activity with open follow-ups selected.
7. Otherwise: **View screening** in the latest known Results run.

Every generated destination preserves the applicable formulation version and historical screening run. When review metadata is unavailable, open the screened version and let the workspace resolve its latest run; never infer a zero count.

Do not label the final state Approved, Compliant, Passed, or Complete. The state only describes workflow progress.

Major components:

- Compact identity header: case, client, Singapore jurisdiction, current version.
- One-line progress summary with separate counts for findings requiring attention, unresolved clarifications, open follow-ups, and reviewer statuses.
- Concise formulation-version list with current version first and latest screening time.
- Recent Notes & Activity preview of the three newest concise entries, with View all.

States:

- No review metadata: case and version access remain usable; show that review summary is temporarily unavailable.
- Empty versions: upload call to action.
- Failed upload: retain the case and allow retry or a new file.

### Formulation workspace shell

**Purpose:** provide stable context across preparation, findings, and reviewer work.  
**Primary action:** depends on active state and tab.  
**Hierarchy:** compact workspace header, tabs, current tab content, contextual detail drawer.

Header contents:

- Breadcrumb back to Case Overview.
- Case/product name.
- Current version selector.
- Current screening-run selector when more than one run exists.
- Singapore scope label.
- Compact unresolved-work indicator.

Tabs should remain in one stable location. The active tab must be addressable in navigation state and restored when returning. A tab change must not create a new screening or save data by itself.

### Formulation tab

**Purpose:** inspect and correct interpreted source values before screening.  
**Primary action:** Confirm Formulation, then Confirm & Screen.  
**Hierarchy:** progress and live confirmation status, clarification questions, product/formulation metadata, interpreted rows, supporting provenance/details.

Retain the current four-stage progress indicator, live remaining-confirmation number, progress fill, disabled-until-ready behavior, explicit row links, and source-to-structured value comparison.

Place source metadata, agent activity, and technical activity in collapsed supporting-detail sections. Keep formulation notes accessible, but show their complete history in Notes & Activity.

States:

- Upload: clear file requirements before selection.
- Interpreting: state what is happening and preserve the uploaded file.
- Interrupted/failed: explain that the file is preserved and offer Retry.
- Clarification required: show exact blockers and jump to the affected row.
- Ready: show the prepared input and a separate screening confirmation.
- Screening failed: retain prepared input and allow retry; do not silently re-interpret.

### Results tab

**Purpose:** review screening outcomes efficiently.  
**Primary action:** open the next relevant finding.  
**Hierarchy:** compact summary, preset filters/search/sort, findings table, selected finding drawer.

Compact summary should use one horizontal block, not a card grid. It should state separately:

- Ingredients screened.
- Ingredient results requiring attention.
- Unresolved identities or incomplete information.
- Reviewer work remaining.
- Open follow-ups.

Recommended preset filters:

- **All results**
- **Needs Attention**
- **Not Reviewed**

Additional controls can include ingredient search, regulatory result, reviewer status, and sort. The default order should place confirmed regulatory issues first, then professional-review requirements, incomplete information, and completed scoped checks. This is a workflow ordering, not a legal risk score.

The table remains the dominant surface. Selecting a row opens its details and visibly highlights the row. When filters produce no rows, explain which filters are active and provide Clear filters.

### Finding detail drawer

**Purpose:** understand and act on one finding without losing list context.  
**Primary actions:** switch Evidence/Review, update review status, save note/follow-up, move previous/next.  
**Hierarchy:** sticky header, regulatory result, separate tabs, current section, navigation controls.

Sticky header:

- Resolved/display ingredient name and submitted row number.
- Regulatory-result badge.
- Separate reviewer-status badge when applicable.
- Previous, next, and close buttons.

Regulatory Evidence tab order:

1. Screening result and any unresolved question.
2. Submitted versus resolved identity and concentration/context.
3. Applicable Singapore rule, limit, and condition.
4. Original wording and accepted source evidence.
5. Required warnings/conditions and scope limitations.
6. ACD comparison and technical provenance in collapsed sections.

Review tab order:

1. Statement that reviewer status does not alter the regulatory finding.
2. Review status.
3. Finding-level notes with author and time.
4. Follow-ups with open/resolved state.
5. Related activity history.

The drawer should preserve its active tab when moving between findings. Previous/next must follow the filtered table order. Closing the drawer returns keyboard focus to the selected row. At laptop widths the drawer may overlay the table; at wide widths it may reserve space. On narrow screens it becomes a full-height sheet with essential evidence intact.

### Notes & Activity tab

**Purpose:** provide one trustworthy history of professional work.  
**Primary action:** add a case note or open the context of an existing item.  
**Hierarchy:** search/type presets, compact secondary-filter disclosure, outstanding follow-ups, chronological activity list.

Filters:

- All activity.
- Notes.
- Follow-ups.
- Review-status changes.
- Context: case, formulation, clarification, finding.
- Open follow-ups only.

Each item shows type, linked context, content, author, and relative time first. Version, run, exact timestamp, dataset, submitted row, and regulatory-result provenance remain in a collapsed context disclosure. The context label is the single jump action; do not repeat generic “Open context” buttons.

Activity types remain distinguishable by label and icon without depending on colour. Render the first 50 filtered entries, then expose **Show older activity** in batches of 50. Search and filtering still operate over the complete loaded feed.

Each item must preserve:

- Type: Note, Follow-up, or Review update.
- Context label: Case; Version N; Clarification, Row N; or Finding, Row N and result.
- Screening run/date when the context is run-specific.
- Author and timestamp.
- Note text or action/status.
- Jump to context when applicable.

Case-level note creation lives at the top of this tab and may also remain as a compact action on Case Overview. Finding-level note creation stays in the finding drawer. The central tab aggregates rather than duplicating creation controls everywhere.

States:

- Empty: explain the difference between a note and a follow-up.
- Loading: preserve filters and scroll position.
- Save failure: retain draft, show local error and Retry.
- Historical run: clearly identify that an item belongs to an earlier screening snapshot.

### Sources

**Purpose:** search accepted scoped regulatory records independent of a case.  
**Primary action:** search, select a record, inspect original evidence.  
**Hierarchy:** search, result list, selected record detail, full accepted page.

Retain exact/prefix/contains behavior, list/detail relationship, source wording, page image, and official link. Align source status and evidence components with the finding drawer. Do not imply that a source record alone establishes a product conclusion.

### Ad hoc New Screen

**Purpose:** quick unsaved screening and demonstrations.  
**Primary action:** Run screen.  
**Hierarchy:** input, results workspace, evidence drawer.

Keep this route secondary to Cases. Reuse the Results layout after a result exists. Clearly state that reviewer notes, status, follow-ups, and durable history require a case workspace.

## 6. Reusable component guidelines

### Tables

- Use a table when users compare multiple records with repeated fields. Ingredient results and regulatory sources qualify.
- Default rows should be approximately 48 to 56 px high, with a denser option considered later.
- Keep the first column identifiable without opening detail. Include row number as muted supporting text where duplicate names are possible.
- Use a tinted selected-row background plus a leading indicator and `aria-selected`; do not rely on colour alone.
- Hover, keyboard focus, selected, loading, empty, error, and disabled/action-unavailable states must be defined.
- Table headers may remain sticky within the table scroll container, but avoid competing page-level stickies.
- Horizontal scrolling is acceptable on narrow screens only when all columns remain reachable and the key result is visible early.

Existing mapping: refine `ResultsTable.tsx`; reuse source-list selection behavior from `SourcesPage.tsx` where appropriate.

### Detail drawers

- Use for one selected finding or source while preserving surrounding list context.
- Width target: 440 to 500 px on wide desktop; overlay below the layout breakpoint; full-screen or near-full-screen on mobile.
- Header stays visible and contains identity, status, navigation, and close.
- Tabs separate immutable evidence from editable human review.
- Escape closes; close returns focus; opening moves focus to the drawer heading or selected tab.
- Preserve selected record and drawer tab during in-workspace navigation.

Existing mapping: restructure `EvidenceDrawer.tsx`; preserve `SourceEvidence.tsx` and `IdentitySourceEvidence.tsx`.

### Tabs

- Use for sibling work modes that share context: Results, Formulation, Notes & Activity; Evidence, Review.
- Tabs are not progress steps and must not be styled like the four-stage workflow indicator.
- Arrow-key navigation and visible focus are required.
- Switching tabs does not discard unsaved text, filters, sorting, selection, or scroll position where practical.
- Show counts only when they are stable, meaningful, and clearly labelled.

### Filters and search

- Put preset filters first and advanced filters second.
- Always display the filtered result count.
- Active filters must be visible without reopening a menu.
- Provide Clear filters when the result is empty.
- Preserve filters per formulation version during the session. Saved personal display preferences are a later capability.
- Search matches submitted and resolved ingredient names; it must not change identity resolution.

### Status badges

Keep two independent families:

1. **Regulatory result badges:** issue identified, professional review required, information incomplete, scoped check completed.
2. **Human workflow badges:** Not reviewed, In review, Awaiting information, Reviewed.

Never style Reviewed with the same green treatment used for a completed scoped regulatory check. Use blue or neutral styling for reviewer workflow. Every badge includes text or an icon plus text; colour alone is insufficient.

Existing mapping: extend `FindingBadge.tsx` and replace the generic `review-status-badge` styling with named variants.

### Forms

- Put labels above controls throughout this product.
- State consequences and requirements in helper text, not placeholders.
- Validate on blur for editable rows and again before the consequential action.
- Never use a disabled primary button as the only explanation. The current confirmation progress/status must state exactly what is blocking it.
- Preserve draft input during recoverable errors.
- Separate source values, interpreted values, and user-confirmed edits visually and textually.

Existing mapping: retain `FormulaEditor.tsx` and the interpreted-row controls in `AgentPage.tsx`.

### Notes

- Notes are append-only professional observations or decisions.
- Every rendered note shows author, timestamp, and context.
- Draft text stays local until the backend confirms the save.
- A successful state appears only after the API succeeds.
- A failed save retains text and offers Retry.
- Do not add rich-text editing in the immediate milestone.

Existing mapping: retain `addReviewerNote`, `ReviewerNote`, and the draft-retention behavior in `ReviewerWorkspace.tsx`; centralise presentation in Notes & Activity.

### Follow-ups

- A follow-up is a required action, not a note and not a regulatory status.
- Show action text, context, author, created time, and Open/Resolved state.
- Resolve/Reopen requires backend confirmation; optimistic display is acceptable only if failure rolls back visibly.
- Open follow-ups are visible in Case Overview and Notes & Activity.

Existing mapping: retain `FollowUp`, `addFollowUp`, and `updateFollowUp`.

### Progress summaries

- Use one compact surface with labelled, non-interchangeable counts.
- Avoid a grid of equal-sized KPI cards when one count is materially more urgent.
- Show workflow progress without implying regulatory compliance.
- The formulation confirmation meter may use progress fill because completion is a literal finite set of required confirmations.

### Breadcrumbs

- Use short, factual paths: Cases / Case name / Version N.
- Breadcrumbs return to context; they do not repeat tab labels.
- Preserve the original top-left logo and primary navigation.

### Buttons

- One primary action per surface.
- Teal filled: current primary action.
- Neutral outlined: secondary or reversible action.
- Text button: low-emphasis inline action.
- Red outlined/text: destructive action, separated from primary actions.
- Disabled: unmet conditions with a nearby explanation.
- Loading label uses the active verb, such as Saving, Screening, or Confirming.

### Notifications and saving indicators

- Ordinary successful saves use a subtle local state: Saving, Saved at time, or Saved.
- Do not use intrusive success toasts for routine changes.
- Errors appear beside the failed action and, when the issue affects the whole page, in an accessible page banner.
- Consequential actions may use a persistent confirmation with the created screening/run facts.
- Destructive actions require a confirmation that names the consequence.

### Loading indicators

- Retain the surrounding layout and label the activity.
- Use an inline spinner for actions and stable skeleton/placeholder regions for page loads.
- Do not replace the entire workspace with an indefinite spinner when existing case context can remain visible.

### Source-evidence presentation

- Show Singapore rule/reference and original wording before optional comparative or technical material.
- Keep source URL, page, version, retrieval date, and accepted snapshot evidence together.
- Clearly label ACD comparison as comparison evidence, not the controlling Singapore outcome.
- Use expandable detail for long wording, API/provenance metadata, and multiple counterpart records.
- Full-page evidence viewing must fit the viewport and support scrolling/zoom without clipping.

## 7. Visual design system

### Direction

Professional, calm, restrained, and precise. The interface uses a warm neutral canvas, near-white tinted surfaces, deep teal brand actions, and semantic colours only where meaning requires them. Avoid decorative gradients, glass panels, coloured card walls, oversized dashboard headings, and motion without feedback value.

### Core colour tokens

These values are derived from `frontend/src/index.css` and should be centralised as semantic CSS custom properties over time.

| Role | Token/value | Use |
|---|---|---|
| Brand action | `#0F766E` | Primary buttons, focus, active controls |
| Brand deep | `#134E4A` | Brand text, primary hover |
| Brand pale | `#F0FDFA` | Guidance and subtle selected backgrounds |
| Canvas | `#FAFAF7` | Page background |
| Surface | `#FFFFFD` | Main panels and drawer |
| Soft surface | `#F6F8F3` | Supporting groups and metadata |
| Primary ink | `#172033` | Main text |
| Secondary ink | `#475569` | Supporting text |
| Muted ink | `#64748B` | Metadata and labels |
| Workspace border | `rgb(19 78 74 / 11%)` | Default separators and panel outlines |

Semantic status families:

| Meaning | Text | Background | Border | Notes |
|---|---|---|---|---|
| Regulatory issue identified | `#B91C1C` | `#FEF2F2` | `#FECACA` | Restrained red, always with explicit label |
| Professional review required | `#92400E` | `#FFFBEB` | `#FDE68A` | Amber, not equivalent to a confirmed violation |
| Information incomplete | `#475569` | `#F8FAFC` | `#CBD5E1` | Neutral warning styling |
| Scoped check completed | `#166534` | `#F0FDF4` | `#BBF7D0` | Never label as approved or compliant |
| Human review workflow | `#1D4ED8` | `#EFF6FF` | `#BFDBFE` | Separate blue family for review status |

### Typography

- Keep the current Inter/system sans-serif stack because compact tables and control labels are core to the product.
- Page title: 30 to 38 px desktop, 28 to 32 px laptop/mobile, weight 650 to 700.
- Section title: 17 to 20 px, weight 600 to 650.
- Body/table text: 13 to 14 px with 1.45 to 1.6 line height.
- Metadata/helper text: 11 to 12 px; never below 11 px for essential content.
- Use tabular numerals for concentrations, counts, timestamps where aligned, and progress values.
- Limit uppercase tracked labels. Use them only for occasional orientation, not above every section.

### Spacing and density

Base scale: 4, 8, 12, 16, 20, 24, 32, 40, 48 px.

- Page content padding: 24 to 40 px desktop, 16 px narrow screens.
- Major vertical sections: 24 to 32 px.
- Related controls: 8 to 12 px.
- Major panel padding: 20 to 24 px.
- Table cell padding: about 12 to 16 px vertical and horizontal.
- Dense supporting lists may use 8 to 12 px vertical padding.

Whitespace should separate tasks, not isolate every datum in its own card.

### Borders, radius, and elevation

- Hairline border: 1 px using tinted neutral/teal border tokens.
- Controls: 7 to 10 px radius.
- Tables and compact containers: 10 to 12 px radius.
- Major work surfaces and drawer: 14 to 18 px radius.
- Use the existing tinted shadow only for selected major work surfaces and the drawer. Most hierarchy should come from spacing and borders.
- Avoid side-stripe cards as a generic hierarchy device. A selected table row may retain a small leading indicator because it encodes selection.

### Icons

- Continue using Lucide at 14 to 18 px for controls and 18 to 22 px for section context.
- Icons support labels; they do not replace unfamiliar regulatory terminology.
- Use one icon consistently for each action family: evidence/source, note, follow-up, previous/next, close, and destructive action.

### Interaction states

Every interactive component requires default, hover, focus-visible, active/pressed, disabled, loading, error, and success/saved treatment where applicable.

- Focus ring: 2 px brand teal with 2 px offset.
- Hover: small background/border change, not movement that changes layout.
- Selected: tinted background plus outline/indicator and `aria-selected` or `aria-pressed`.
- Disabled: lower contrast but remain readable; explain the blocking condition nearby.
- Loading: retain control width and replace label with an active verb.

### Motion

- 120 to 180 ms for colour, border, and selection feedback.
- 180 to 240 ms for drawer entrance/exit.
- Approximately 300 ms for the confirmation progress fill.
- Animate `transform` and `opacity`; avoid animating layout dimensions.
- Respect `prefers-reduced-motion` with immediate final states.
- No decorative parallax, particle systems, hero animation, or repeated reveal animation in the professional workspace.

### Accessibility

- Body text contrast meets WCAG AA; do not rely on muted grey for essential findings.
- Status meaning uses text plus colour and, where helpful, an icon.
- All primary flows are keyboard operable.
- Opening/closing drawers and changing tabs use predictable focus management.
- Buttons and controls are at least 44 px on coarse pointers.
- Error banners use `role="alert"`; progress uses correct `aria-valuenow`; tabs follow the ARIA tabs pattern.
- Original source wording remains selectable and readable at increased zoom.

### Responsive behavior

- Primary target: 1280 to 1600 px desktop and common laptop widths around 1024 to 1280 px.
- Wide desktop: table plus reserved-space drawer is acceptable.
- Laptop: drawer overlays content; table context remains behind it.
- Tablet/narrow: workspace tabs scroll horizontally if needed; drawer becomes a full-height overlay.
- Mobile: keep essential finding, result, review state, and evidence available. The existing bottom navigation may remain. Do not hide columns without providing the same information in the opened detail.
- Use `overflow-x: clip` on page roots so sticky positioning continues to work. Limit page-level `top: 0` sticky surfaces to one coordinated header per route.

## 8. Core interaction flows

### Create case

1. User opens Cases and chooses New Case.
2. User enters case/product name and optional client.
3. UI sends the existing create request.
4. On backend success, navigate to Case Overview.
5. On failure, retain both fields and show Retry.

Preserve: typed values until success or explicit cancel.

### Upload and clarify formulation

1. Continue Review resolves to Upload formulation when the case is empty.
2. User chooses/drops a supported file after seeing format and size requirements.
3. UI shows interpretation state while preserving case context.
4. Clarifications appear with row/source context and View row actions.
5. The remaining-confirmation count, items-to-modify text, progress fill, and disabled action update together.
6. Confirm Formulation enables only when required confirmations are complete.

Preserve: uploaded file record, interpretation state, confirmed values, unresolved questions, reviewer notes, and draft text after recoverable errors.

### Screen formulation

1. User reviews the prepared input.
2. User chooses Confirm & Screen.
3. UI creates a new immutable screening run through the existing backend flow.
4. On success, the workspace opens Results for the new run and selects the first attention finding, or the first row if none require attention.
5. On failure, prepared input remains available with a retry action.

Preserve: formulation version, prepared request, and previous screening runs. Never overwrite a historical run.

### Review results

1. Results opens with compact summary and the table.
2. User applies preset or advanced filters.
3. User selects a row; drawer opens while the row remains highlighted.
4. Evidence tab explains the finding and source.
5. Review tab allows a status, note, or follow-up without changing the finding.
6. Previous/next moves through the current filtered order.
7. Closing returns focus to the row.

Preserve: active run, filters, sorting, selected row, drawer tab, and table scroll position.

### Addressable workspace context

Saved formulation workspaces accept these query parameters:

- `tab=results|formulation|activity`
- `run=<screening-run-id>`
- `row=<submitted-row-number>`
- `drawer=evidence|review`
- `clarification=<clarification-id>`
- `activity=open-followups`

Every identifier is validated against the loaded case, formulation version, and screening history. A stale or invalid target falls back to the nearest safe workspace state and shows a restrained notice. Activity links to a finding restore the historical run, submitted row, Results tab, and requested drawer tab. Clarification links open Formulation, scroll to the exact question, briefly highlight it, and move focus to an actionable control.

The activity feed is an existing-record read model. Notes are append-only, follow-ups expose their current Open or Resolved state, and reviewer updates expose only the latest persisted status per finding. It is not a complete status-transition audit trail and must not be presented as one.

### Record notes

1. User creates a case note from Notes & Activity, or a finding note from the drawer.
2. UI displays Saving locally.
3. Draft clears only after backend confirmation.
4. Saved note appears with author, timestamp, version, run/finding context, and jump action.
5. Failure retains the draft and offers Retry.

Preserve: target IDs and context. Never reconstruct the target from ingredient name.

### Create and resolve follow-up

1. User creates a follow-up from Review or relevant clarification context.
2. The open action appears in the drawer, Notes & Activity, and compact Case Overview count.
3. Resolve/Reopen updates only after backend confirmation or visibly rolls back on failure.

Preserve: original case, version, clarification/review item, author, timestamps, and action history.

### Resume saved case

1. The case name opens Case Overview; the resume row and contextual case action resolve directly to work.
2. The shared resolver evaluates the latest persisted formulation state and review summary.
3. The application opens the relevant version, historical run, tab, drawer, and unresolved task.
4. If a previously selected finding can be restored safely, restore it; otherwise select the first unresolved item.

Preserve: latest durable backend state. Client memory may improve convenience but must not be the source of truth.

### Permanently delete a case

1. Delete is available from the separate row menu and Case Overview overflow menu under the existing organisation-member permission model.
2. One shared accessible dialog names the case and explains that versions, screenings, clarifications, reviewer records, notes, follow-ups, and uploaded files are permanently removed.
3. Cancel receives initial focus; focus remains trapped; Escape cancels; failure retains the dialog and offers Retry.
4. Storage paths are collected for the authorised case and removed before database deletion. Any storage failure aborts database deletion and leaves the case available.
5. Directory success removes the case from local state and recomputes the resume suggestion without a reload. Overview success returns to Cases with a one-time notice.

Supabase Storage and PostgreSQL do not share a distributed transaction. The established storage-first convention therefore fails closed before database deletion, while a later database failure may require administrator recovery of the already-removed uploads.

### Update formulation and re-screen

1. User chooses Upload New Version from Case Overview.
2. A new formulation version is created; earlier versions and runs remain unchanged.
3. User clarifies and screens the new version.
4. New findings and review items belong to the new run.
5. Historical notes remain visible with their original version/run labels.

Do not automatically carry a Reviewed state to a new finding. Comparison of changed rows/findings is a later capability.

## 9. Regulatory UX safeguards

### Separate concepts

| Concept | Meaning | UI treatment |
|---|---|---|
| Regulatory finding | Deterministic bounded result from structured rules | Regulatory badge and evidence; immutable in review UI |
| Professional review status | Human workflow state for a review item | Separate blue/neutral badge and editable Review control |
| Information missing | Required submitted fact is absent | Neutral incomplete state with exact missing information |
| Identity unresolved | Ingredient could not be mapped confidently | Identity clarification state; never silently resolve |
| Source difference | Material Singapore/ACD comparison or complex condition | Amber professional-review requirement with both sources visible |
| Historical screening snapshot | Result from one request and accepted dataset version at one time | Run/date/version selector and immutable label |
| Unassessed requirement | Outside active rules, unsupported function/context, or future label check | Explicit scope limitation, not a positive conclusion |

### Language rules

Allowed examples:

- Regulatory issue identified.
- Prohibited substance identified within the scoped rules.
- Restriction exceeded.
- Professional review required.
- Information incomplete.
- No issue identified within the supported scoped rules.
- Reviewed by [person] on [date].

Avoid:

- Approved.
- Compliant formulation.
- Safe.
- Passed regulatory review.
- Fully checked.
- Review complete, when used to imply a regulatory conclusion.

### Count rules

- Label the unit every time: ingredients, findings, unresolved identities, reviewer actions, open follow-ups.
- Do not add unlike counts into one total.
- One ingredient may have multiple rule evaluations but one primary finding row; state which level a count uses.
- A Reviewed count describes human workflow only.

### Evidence and scope rules

- Preserve original wording, source URL, reference, page, revision/version, and retrieval/dataset version.
- Singapore legislation controls the Singapore finding; ACD comparison remains supporting evidence.
- Required warning output indicates a source requirement, not that a product label satisfies it.
- A completed scoped check remains bounded by the active dataset and submitted facts.
- UI grouping into four visual categories does not replace the underlying detailed status enum.

## 10. Implementation roadmap

### Completed milestones

#### Phase 1: results-focused workspace

- Add Results and Formulation tabs to the persistent formulation workspace.
- Move current upload/clarification/editor surfaces under Formulation.
- Replace the summary card grid and duplicate Human Review/What Needs Attention lists with one compact summary.
- Make `ResultsTable` the dominant Results surface.
- Add All results, Needs Attention, and Not Reviewed presets plus ingredient search.
- Preserve filters and selected row across tab changes.

#### Phase 2: focused finding details

- Add Regulatory Evidence and Review tabs to `EvidenceDrawer`.
- Group evidence in the documented order and collapse comparative/technical detail.
- Add previous/next finding controls based on current filtered results.
- Restore focus to the selected row on close.

#### Phase 3: contextual notes and activity

- Create the central Notes & Activity tab using existing note/follow-up persistence.
- Render explicit case/version/run/row/finding context.
- Add search/filter and open-follow-up view.
- Add jump-to-finding and jump-to-clarification behavior.
- Keep finding-note creation in the drawer and case-note creation in the central view.

Implementation note: Phase 4's streamlined Cases and Case Overview work was deliberately pulled ahead and completed before Phase 3 so the navigation now forms one coherent `Cases → Case Overview → Screening Workspace` path. Cases use separate lifecycle, workflow, and review filters, plus search and a restrained resume row. Case Overview uses an on-demand inline case-note composer rather than a permanently visible textarea.

#### Phase 4: streamlined Case Overview

- Add contextual Continue Review behavior.
- Replace the large review metric treatment with a compact progress summary.
- Shorten the version list and add a recent activity preview.
- Move Delete away from Upload/Continue actions.

Phases 1–4 are implemented. Phase 3 uses a read-only `/cases/{case_id}/activity` aggregation over existing records; no audit table or persistence migration was introduced.

#### Phase 5: reliability and consistency — implemented

- Standardise Saving, Saved, Failed, and Retry states for status, note, and follow-up writes.
- Preserve drafts on recoverable errors and navigation within the workspace.
- Apply the regulatory and reviewer status families consistently.
- Confirm version/run context on all human-review records.

Writes are keyed by stable target and operation, so unrelated reviewer controls remain usable while another save is pending. Status controls display a pending value while saving, merge only the confirmed response, and retain the last confirmed value on failure. Background reconciliation never replaces confirmed local state with a loading screen or clears a draft on refresh failure. Regulatory-result styling remains separate from the blue/neutral reviewer-status family.

Phases 1–5 now reuse the existing components, APIs, and persistence relationships without changing regulatory logic.

### Implement later

- Configurable finding-table columns and saved personal display preferences.
- Advanced keyboard shortcuts for row navigation, open/close, and search.
- Advanced version comparison showing changed formulation rows and newly introduced findings.
- Permission-aware deep links and direct finding sharing.
- Label-artwork viewer, mandatory-particular findings, formula-label mismatch findings, required-warning verification, and location-specific artwork comments.
- Expanded reporting and bounded workflow automation.

Do not add complex approval chains, collaboration hierarchies, task-management systems, or analytics dashboards unless product scope explicitly changes.

## 11. Acceptance criteria

### Streamlined Case Overview

- From each persisted case state, Continue Review opens the correct next task without the user choosing a version manually.
- A user can identify current version, latest screening, outstanding clarifications, open follow-ups, and review work without opening detailed evidence.
- Upload New Version remains available but visually secondary to Continue Review.
- Delete is separated and requires a consequence-specific confirmation.
- No text implies product approval or compliance.

### Compact screening summary

- The first viewport of Results includes the workspace header, compact summary/filter controls, and the beginning of the results table at a typical laptop height.
- The summary uses one compact surface, not six equal cards.
- Every count names its unit; ingredient, finding, identity, review, and follow-up counts are not presented as interchangeable.
- Human Review and What Needs Attention duplicate lists are removed when the table exposes the same rows.

### Results-focused workspace

- After a successful screening, Results is the active tab and the table is the primary surface.
- All results, Needs Attention, and Not Reviewed presets produce the expected row sets.
- Ingredient search matches submitted and resolved names without changing resolution data.
- Empty filtered results show active filters and a Clear filters action.
- Switching to Formulation and back preserves filters, sort, selection, and table position.

### Simplified evidence/review drawer

- Selecting a table row opens the correct finding while preserving the visible table context.
- Regulatory Evidence and Review are separate tabs; editable controls never appear in the evidence tab.
- Evidence includes submitted facts, identity, finding, applicable rule/limit, source wording, official source link, and scope.
- Previous/next navigates in filtered order and updates the selected table row.
- Closing the drawer returns keyboard focus to the originating row.

### Contextual notes and central activity

- A finding note is stored against the stable review item and displays its case, version, run, submitted row, author, and timestamp through direct fields or a reliable join.
- Two identical ingredient names in different rows can receive separate notes and jump back to the correct rows.
- Case notes are visibly different from finding, formulation, and clarification notes.
- Notes & Activity can filter by context and show open follow-ups.
- Jump from a finding note opens its screening run, Results tab, selected row, and Review drawer tab.
- Notes remain append-only; follow-ups retain separate Open/Resolved behavior.

### Next/previous finding navigation

- Navigation follows the current filtered/sorted rows and disables correctly at each end.
- Moving between findings preserves the drawer tab and any saved filters.
- Unsaved note text is not silently discarded; navigation warns or preserves a per-finding draft.
- A reviewer can inspect evidence, save a note/status, and advance without closing the drawer.

### Reliable saving and error recovery

- Saving indicators appear only after a write begins; Saved appears only after backend confirmation.
- A failed note or follow-up save retains the entered text and exposes Retry near the failure.
- Failed review-status updates keep or restore the last confirmed status.
- Navigating within the workspace does not discard recoverable drafts.
- Screening failure preserves the prepared formulation and does not overwrite a historical run.

### Consistent status presentation

- Regulatory-result and reviewer-status badges use visibly different colour families and labels.
- Reviewed never appears as evidence that a formulation or ingredient is compliant.
- Red is reserved for confirmed regulatory issues, amber for professional review requirements, neutral warning styling for incomplete information, and subtle green for completed checks within supported scope.
- The underlying detailed finding remains accessible wherever a visual group is shown.
- Every status remains understandable in greyscale and by screen reader text.

### Version-aware reviewer context

- Switching screening runs reloads the matching review items, notes, and follow-ups.
- Historical activity shows its original formulation version, screening run/date, and dataset identity.
- A new screening creates new review items and does not inherit Reviewed automatically.
- Earlier findings and notes remain inspectable after a new version is uploaded or re-screened.

## Using this reference

For future frontend tasks:

1. Read the relevant page and component sections above.
2. Inspect the existing component before creating a parallel implementation.
3. Reuse the documented tokens and interaction patterns.
4. Keep regulatory results, human workflow, and uncertainty separate.
5. Update this document when an intentional UI decision changes.

