import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useState } from "react";
import { ReviewerWorkspace } from "./ReviewerWorkspace";

const item = {
  id: "review-1", screening_run_id: "run-1", subject_type: "formulation_ingredient_result",
  subject_key: "ingredient:2", submitted_row_number: 2, engine_finding: "information_missing",
  requires_attention: true, review_status: "not_reviewed" as const, updated_by: null,
  updated_at: "2026-10-14T00:00:00Z", reviewed_at: null,
};

describe("ReviewerWorkspace", () => {
  it("keeps reviewer status and notes separate from the engine finding", async () => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn().mockResolvedValue(undefined);
    const onAddNote = vi.fn().mockResolvedValue(undefined);
    function Harness() {
      const [noteDraft, setNoteDraft] = useState("");
      const [followUpDraft, setFollowUpDraft] = useState("");
      return <ReviewerWorkspace reviewItem={item} notes={[]} followUps={[]}
        noteDraft={noteDraft} followUpDraft={followUpDraft}
        onNoteDraftChange={setNoteDraft} onFollowUpDraftChange={setFollowUpDraft}
        onStatusChange={onStatusChange} onAddNote={async (body) => { await onAddNote(body); setNoteDraft(""); }}
        onAddFollowUp={vi.fn()} onToggleFollowUp={vi.fn()} />;
    }
    render(<Harness />);
    await user.selectOptions(screen.getByLabelText("Review status"), "awaiting_information");
    expect(onStatusChange).toHaveBeenCalledWith("awaiting_information");
    await user.type(screen.getByLabelText("Reviewer note"), "Confirm with the client.");
    await user.click(screen.getByRole("button", { name: "Add note" }));
    expect(onAddNote).toHaveBeenCalledWith("Confirm with the client.");
    expect(screen.getByLabelText("Reviewer note")).toHaveValue("");
    expect(screen.getByText(/do not change the regulatory finding/i)).toBeInTheDocument();
  });

  it("retains a controlled draft when saving fails", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [noteDraft, setNoteDraft] = useState("Needs another check");
      const [followUpDraft, setFollowUpDraft] = useState("");
      return <ReviewerWorkspace reviewItem={item} notes={[]} followUps={[]}
        noteDraft={noteDraft} followUpDraft={followUpDraft}
        onNoteDraftChange={setNoteDraft} onFollowUpDraftChange={setFollowUpDraft}
        onStatusChange={vi.fn()} onAddNote={vi.fn().mockRejectedValue(new Error("offline"))}
        onAddFollowUp={vi.fn()} onToggleFollowUp={vi.fn()} />;
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Add note" }));
    expect(screen.getByLabelText("Reviewer note")).toHaveValue("Needs another check");
  });

  it("restores the confirmed status after failure while retaining the attempted value for Retry", async () => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn().mockResolvedValue(undefined);
    render(<ReviewerWorkspace reviewItem={item} notes={[]} followUps={[]}
      statusWriteState={{ phase: "failed", message: "Status save failed" }}
      pendingReviewStatus="awaiting_information"
      noteDraft="" followUpDraft="" onNoteDraftChange={vi.fn()} onFollowUpDraftChange={vi.fn()}
      onStatusChange={onStatusChange} onAddNote={vi.fn()} onAddFollowUp={vi.fn()} onToggleFollowUp={vi.fn()} />);

    expect(screen.getByLabelText("Review status")).toHaveValue("not_reviewed");
    expect(screen.getByRole("alert")).toHaveTextContent("Status save failed");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onStatusChange).toHaveBeenCalledWith("awaiting_information");
  });
});
