import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Sidebar } from "./components/Sidebar";
import { CasesPage } from "./pages/CasesPage";
import { CasePage } from "./pages/CasePage";
import { FormulaScreeningPage } from "./pages/FormulaScreeningPage";
import { FormulationWorkspacePage } from "./pages/FormulationWorkspacePage";
import { SignInPage, SignUpPage } from "./pages/AuthPages";
import { SourcesPage } from "./pages/SourcesPage";
import { AccountPage } from "./pages/AccountPage";

function Protected() {
  const auth = useAuth();
  const location = useLocation();
  if (auth.loading) return <div className="auth-shell"><div className="auth-card">Loading your workspace…</div></div>;
  if (!auth.configured) return <div className="auth-shell"><div className="auth-card"><h1>Supabase setup required</h1><p>Add the public Supabase URL and publishable key to the frontend environment.</p></div></div>;
  if (!auth.session) return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}
function AppLayout() {
  return <div className="app-shell"><Sidebar /><div className="app-view"><Outlet /></div></div>;
}

export default function App() {
  return <Routes>
    <Route path="/sign-in" element={<SignInPage />} />
    <Route path="/sign-up" element={<SignUpPage />} />
    <Route element={<Protected />}>
      <Route element={<AppLayout />}>
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/cases/new" element={<CasesPage />} />
        <Route path="/cases/:caseId" element={<CasePage />} />
        <Route path="/cases/:caseId/formulations/:versionId" element={<FormulationWorkspacePage />} />
        <Route path="/screen" element={<FormulaScreeningPage />} />
        <Route path="/sources" element={<SourcesPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="*" element={<Navigate to="/cases" replace />} />
      </Route>
    </Route>
  </Routes>;
}
