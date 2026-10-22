import { AlertCircle, LogOut, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteAccount, getMe } from "../api/cases";
import { useAuth } from "../auth/AuthContext";
import { TypedDeleteDialog } from "../components/TypedDeleteDialog";
import type { CurrentUser } from "../types/cases";

export function AccountPage() {
  const auth = useAuth(); const navigate = useNavigate();
  const [profile, setProfile] = useState<CurrentUser | null>(null); const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false); const [deleting, setDeleting] = useState(false); const [deleteError, setDeleteError] = useState<string | null>(null);
  useEffect(() => { let active = true; void getMe().then((value) => { if (active) setProfile(value); }).catch((caught) => { if (active) setError(caught instanceof Error ? caught.message : "Your account details could not be loaded."); }); return () => { active = false; }; }, []);
  const remove = async () => { setDeleting(true); setDeleteError(null); try { await deleteAccount(); await auth.clearLocalSession(); navigate("/sign-in", { replace: true, state: { accountDeleted: true } }); } catch (caught) { setDeleteError(caught instanceof Error ? caught.message : "The account could not be deleted. Please retry."); setDeleting(false); } };
  return <main className="workspace"><div className="account-page" aria-hidden={dialogOpen}>
    <header><p className="eyebrow">Account</p><h1 className="page-title">Your account</h1><p>Manage sign-in and your private Regulens workspace.</p></header>
    {error && <div className="page-error-row" role="alert"><AlertCircle size={16} />{error}</div>}
    <section className="account-panel" aria-label="Account details"><dl><div><dt>Name</dt><dd>{profile?.display_name ?? "Loading…"}</dd></div><div><dt>Email</dt><dd>{profile?.email ?? auth.user?.email ?? "—"}</dd></div><div><dt>Workspace</dt><dd>{profile?.organisations[0]?.name ?? "Loading…"}</dd></div></dl><button className="secondary-button" type="button" onClick={() => void auth.signOut()}><LogOut size={15} /> Sign out</button></section>
    <section className="account-danger" aria-labelledby="delete-account-heading"><div><h2 id="delete-account-heading">Delete account</h2><p>Permanently remove your sole-member workspaces, cases, formulation files, screening history, notes, follow-ups, and sign-in account.</p><p>Deletion is blocked if any workspace has another member.</p></div><button className="danger-button" type="button" onClick={() => { setDialogOpen(true); setDeleteError(null); }}><Trash2 size={14} /> Delete account</button></section>
  </div><TypedDeleteDialog open={dialogOpen} title="Delete your Regulens account?" description="This permanently removes your eligible workspaces and all saved case data. This action cannot be undone." actionLabel="Delete account" busy={deleting} error={deleteError} onCancel={() => { if (!deleting) { setDialogOpen(false); setDeleteError(null); } }} onConfirm={() => void remove()} /></main>;
}
