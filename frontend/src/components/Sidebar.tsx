import { FileText, FlaskConical, FolderKanban, LogOut } from "lucide-react";
import type { CSSProperties } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import regulensLogoMark from "../assets/regulens-logo-mark.png";

const items = [
  { label: "Cases", icon: FolderKanban, to: "/cases" },
  { label: "New Screen", icon: FlaskConical, to: "/screen" },
  { label: "Sources", icon: FileText, to: "/sources" },
];

export function Sidebar() {
  const auth = useAuth();
  const { pathname } = useLocation();
  const activeIndex = items.findIndex(({ to }) => pathname === to || pathname.startsWith(`${to}/`));
  return <aside className="sidebar-shell">
    <div className="sidebar-brand"><div className="brand-mark"><img src={regulensLogoMark} alt="Regulens logo" /></div><div className="sidebar-brand-copy"><div className="font-semibold tracking-tight text-slate-950">Regulens</div><div className="text-[11px] text-slate-500">Regulatory Intelligence</div></div></div>
    <div className="sidebar-divider" />
    <nav className="flex flex-1 flex-col px-3 pt-4" aria-label="Primary navigation">
      <div className="sidebar-links" style={{ "--active-nav-index": Math.max(0, activeIndex) } as CSSProperties}>
        {activeIndex >= 0 && <span className="nav-active-indicator" aria-hidden="true" />}
        {items.map(({ label, icon: Icon, to }) => <NavLink key={to} to={to} className={({ isActive }) => `nav-item ${isActive ? "nav-item-active" : "text-slate-500"}`}><Icon size={17} strokeWidth={1.8} /><span>{label}</span></NavLink>)}
      </div>
      <button className="nav-item mt-auto text-slate-500" type="button" onClick={() => void auth.signOut()}><LogOut size={17} /><span>Sign out</span></button>
    </nav>
  </aside>;
}
