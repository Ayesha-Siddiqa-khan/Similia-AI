"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ArrowUpRight, BookOpen, Boxes, ChevronDown, FileText, FlaskConical, LayoutDashboard, KeyRound, Leaf, LogOut, Menu, Moon, Search, Settings, ShieldCheck, Users, Workflow, X } from "lucide-react";
import type { ReactNode } from "react";
import { StatusBadge } from "@/components/status-badge";
import { useBackendHealth } from "@/hooks/use-backend-health";
import { useWorkspaceScroll } from "@/hooks/use-workspace-scroll";
import { useLocalPref } from "@/lib/use-local-pref";

const casesPath = "/workspace/case";
const caseDetailPath = /^\/workspace\/case\/[a-f0-9-]{36}$/;

export const sections = [
  { id: "dashboard", title: "Dashboard", icon: LayoutDashboard },
  { id: "knowledge", title: "Knowledge Base", icon: BookOpen },
  { id: "books", title: "PDF Books", icon: FileText },
  { id: "ingestion", title: "Ingestion Jobs", icon: Workflow },
  { id: "chunks", title: "Chunk Explorer", icon: Boxes },
  { id: "search", title: "RAG Search", icon: Search },
  { id: "case", title: "AI Case Workspace", icon: FlaskConical },
  { id: "patients", title: "Patients", icon: Users },
  { id: "ai", title: "AI Settings", icon: KeyRound },
  { id: "settings", title: "Settings", icon: Settings },
];

function BackendStatus() {
  const health = useBackendHealth();
  return <StatusBadge status={health.isPending ? "checking" : health.data?.backend ?? "down"} />;
}

export function AppShell({ children, accountId, userLabel = "Operator", sectionIds }: { children: ReactNode; accountId: string; userLabel?: string; sectionIds?: string[] }) {
  const pathname = usePathname();
  const main = useWorkspaceScroll(pathname, accountId);
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [logoutError, setLogoutError] = useState("");
  const root = "/workspace";
  const [lastCase, saveLastCase] = useLocalPref(`similia.last-case.${accountId}`, casesPath);
  const currentCase = caseDetailPath.test(pathname);
  const caseDestination = currentCase ? pathname : caseDetailPath.test(lastCase) ? lastCase : casesPath;
  useEffect(() => {
    if (currentCase || pathname === casesPath) saveLastCase(pathname);
  }, [currentCase, pathname, saveLastCase]);
  const activeId = pathname.startsWith(`${root}/report/`) || pathname.startsWith(`${root}/workflow/`) ? "case" : undefined;
  const active = sections.find((s) => s.id === activeId || pathname === `${root}/${s.id}` || pathname.startsWith(`${root}/${s.id}/`)) ?? sections[0];
  async function logout() {
    try {
      const res = await fetch("/api/auth/logout", { method: "POST" });
      if (!res.ok) throw new Error();
      router.replace("/login");
      router.refresh();
    } catch { setLogoutError("Unable to sign out. Please try again."); }
  }
  return <div className="application">
    <a className="skip-link no-print" href="#main">Skip to content</a>
    {open && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setOpen(false)} />}
    <aside className={`sidebar no-print ${open ? "sidebar-open" : ""}`}>
      <Link href={`${root}/dashboard`} className="brand"><span className="brand-mark"><Leaf size={23} aria-hidden /></span><span>similia<span className="brand-ai">AI</span><small>KNOWLEDGE WORKSPACE</small></span></Link>
      <button className="icon-button mobile-close" onClick={() => setOpen(false)} aria-label="Close navigation"><X size={20} /></button>
      <div className="workspace-label"><span className="workspace-avatar">S</span><div>Similia workspace<small>{sectionIds ? "Practitioner tools" : "Operator tools"}</small></div><ChevronDown size={15} aria-hidden /></div>
      <p className="nav-caption">WORKSPACE</p>
      <nav aria-label="Main navigation">{sections.filter((s) => !sectionIds || sectionIds.includes(s.id)).map(({ id, title, icon: Icon }) => <Link key={id} href={id === "case" ? caseDestination : `${root}/${id}`} onClick={() => setOpen(false)} aria-current={active.id === id ? "page" : undefined} className={`nav-link ${active.id === id ? "active" : ""}`}><Icon size={18} aria-hidden /><span>{title}</span></Link>)}</nav>
      <div className="sidebar-bottom"><ShieldCheck size={20} aria-hidden /><strong>Practitioner supervised</strong><p>Knowledge retrieval to support careful, informed review.</p><Link href={`${root}/settings`}>Workspace settings <ArrowUpRight size={14} aria-hidden /></Link></div>
      <div className="sidebar-foot"><span className="dot" /> Similia AI</div>
    </aside>
    <div className="app-body"><header className="topbar no-print"><div className="topbar-left"><button className="icon-button mobile-menu" aria-expanded={open} aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={22} /></button><span className="breadcrumb">Workspace <span>/</span> <strong>{active.title}</strong>{currentCase && <> <span>/</span> <Link href={casesPath} className="text-link">Recent cases</Link></>}</span></div><div className="topbar-right"><BackendStatus /><button className="icon-button" aria-label="Toggle color theme" onClick={() => { const dark = document.documentElement.dataset.theme === "dark"; document.documentElement.dataset.theme = dark ? "light" : "dark"; }}><Moon size={18} /></button><details className="user-menu"><summary aria-label="User menu"><span className="user-avatar">{userLabel.charAt(0).toUpperCase()}</span><span className="user-name">{userLabel}</span><ChevronDown size={14} aria-hidden /></summary><div className="menu-panel"><p>{userLabel}</p><button onClick={logout}><LogOut size={15} aria-hidden /> Sign out</button></div></details></div></header>
      {logoutError && <div role="alert" className="notice notice-error">{logoutError}</div>}
      <main ref={main} id="main" className="main-content" tabIndex={-1}>{children}</main>
      <footer className="app-footer no-print"><span>Similia AI · Knowledge with traceability</span><span>Historical text retrieval is not evidence of clinical efficacy.</span></footer>
    </div>
  </div>;
}
