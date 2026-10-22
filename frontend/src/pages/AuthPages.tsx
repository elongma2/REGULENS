import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function SignInPage() {
  const auth = useAuth(); const navigate = useNavigate(); const location = useLocation();
  const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  if (auth.session) return <Navigate to="/cases" replace />;
  const submit = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(null); try { await auth.signIn(email, password); navigate((location.state as { from?: string } | null)?.from || "/cases", { replace: true }); } catch (caught) { setError(caught instanceof Error ? caught.message : "Sign in failed."); } finally { setBusy(false); } };
  return <main className="auth-shell"><form className="auth-card" onSubmit={submit}><p className="eyebrow">Regulens</p><h1>Sign in</h1><p>Open your private regulatory workspace.</p>{(location.state as { accountDeleted?: boolean } | null)?.accountDeleted && <div className="auth-success" role="status">Your Regulens account was permanently deleted.</div>}{error && <div role="alert" className="auth-error">{error}</div>}<label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label><label>Password<input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label><button className="primary-button" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button><small>New to Regulens? <Link to="/sign-up">Create an account</Link></small></form></main>;
}

export function SignUpPage() {
  const auth = useAuth(); const navigate = useNavigate();
  const [displayName, setDisplayName] = useState(""); const [email, setEmail] = useState(""); const [password, setPassword] = useState(""); const [error, setError] = useState<string | null>(null); const [verify, setVerify] = useState(false); const [busy, setBusy] = useState(false);
  if (verify) return <main className="auth-shell"><section className="auth-card"><p className="eyebrow">Account created</p><h1>Check your email</h1><p>Use the confirmation link sent to <strong>{email}</strong>, then return to sign in.</p><Link className="secondary-button" to="/sign-in">Back to sign in</Link></section></main>;
  const submit = async (event: FormEvent) => { event.preventDefault(); setBusy(true); setError(null); try { const confirmationNeeded = await auth.signUp(email, password, displayName); if (confirmationNeeded) setVerify(true); else navigate("/cases"); } catch (caught) { setError(caught instanceof Error ? caught.message : "Signup failed."); } finally { setBusy(false); } };
  return <main className="auth-shell"><form className="auth-card" onSubmit={submit}><p className="eyebrow">Regulens</p><h1>Create your workspace</h1><p>Your formulations and screening history stay private to your organisation.</p>{error && <div role="alert" className="auth-error">{error}</div>}<label>Display name<input required value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></label><label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label><label>Password<input type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label><button className="primary-button" disabled={busy}>{busy ? "Creating…" : "Create account"}</button><small>Already registered? <Link to="/sign-in">Sign in</Link></small></form></main>;
}

