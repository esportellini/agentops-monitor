"use client";
import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Building2, Check, ChevronDown, LogOut, Menu, Settings, UserRound } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";

const names: Record<string, string> = { dashboard: "Overview", traces: "Traces", costs: "Costs", security: "Security", approvals: "Approvals", alerts: "Alerts", evaluations: "Evaluations", projects: "Projects", agents: "Agents", "api-keys": "API Keys", members: "Members", "audit-logs": "Audit Logs", privacy: "Privacy", settings: "Settings", profile: "Profile" };

export function Topbar({ onOpenNavigation }: { onOpenNavigation: () => void }) {
  const { user, organizations, activeOrg, setActiveOrg, logout } = useAuth();
  const pathname = usePathname(); const router = useRouter();
  const [orgOpen, setOrgOpen] = useState(false); const [userOpen, setUserOpen] = useState(false);
  const orgRef = useRef<HTMLDivElement>(null); const userRef = useRef<HTMLDivElement>(null);
  const context = names[pathname.split("/").filter(Boolean)[0]] ?? "AgentOps";
  useEffect(() => { const close = (event: MouseEvent) => { if (orgRef.current && !orgRef.current.contains(event.target as Node)) setOrgOpen(false); if (userRef.current && !userRef.current.contains(event.target as Node)) setUserOpen(false); }; const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setOrgOpen(false); setUserOpen(false); } }; document.addEventListener("mousedown", close); document.addEventListener("keydown", escape); return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", escape); }; }, []);
  return <header className="topbar"><div className="topbar-context"><button className="icon-button mobile-trigger" onClick={onOpenNavigation} aria-label="Open navigation"><Menu size={18} /></button><span className="breadcrumb-root">AgentOps</span><span className="breadcrumb-separator">/</span><strong>{context}</strong></div><div className="topbar-actions">
    <div className="menu-anchor" ref={orgRef}><button className="organization-trigger" onClick={() => setOrgOpen(!orgOpen)} aria-expanded={orgOpen}><Building2 size={15} /><span>{activeOrg?.name ?? "Select organization"}</span><ChevronDown size={13} /></button>{orgOpen && <div className="menu-panel menu-left" role="menu"><p className="menu-label">Organization</p>{organizations.map((org) => <button role="menuitem" key={org.id} onClick={() => { setActiveOrg(org); setOrgOpen(false); }} className="menu-item"><span><strong>{org.name}</strong><small>{org.plan}</small></span>{org.id === activeOrg?.id && <Check size={14} />}</button>)}</div>}</div>
    <div className="menu-anchor" ref={userRef}><button className="user-trigger" onClick={() => setUserOpen(!userOpen)} aria-expanded={userOpen} aria-label="Open user menu"><span>{user?.name?.[0]?.toUpperCase() ?? "U"}</span><ChevronDown size={13} /></button>{userOpen && <div className="menu-panel menu-right" role="menu"><div className="user-summary"><strong>{user?.name}</strong><small>{user?.email}</small></div><button className="menu-item" onClick={() => router.push("/profile")}><UserRound size={15} />Profile</button><button className="menu-item" onClick={() => router.push("/settings")}><Settings size={15} />Settings</button><button className={cn("menu-item", "menu-danger")} onClick={async () => { await logout(); router.push("/login"); }}><LogOut size={15} />Sign out</button></div>}</div>
  </div></header>;
}
