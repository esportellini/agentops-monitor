"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Activity, AlertTriangle, Bot, Boxes, ChartNoAxesCombined, CircleDollarSign, ClipboardCheck, FileClock, Fingerprint, Gauge, KeyRound, Settings, ShieldCheck, SlidersHorizontal, Users, X } from "lucide-react";
import { cn } from "@/lib/utils";

const groups = [
  { label: "Overview", items: [{ href: "/dashboard", label: "Overview", icon: Gauge }] },
  { label: "Observe", items: [{ href: "/traces", label: "Traces", icon: Activity }, { href: "/costs", label: "Costs", icon: CircleDollarSign }] },
  { label: "Govern", items: [{ href: "/security", label: "Security", icon: ShieldCheck }, { href: "/approvals", label: "Approvals", icon: ClipboardCheck }, { href: "/alerts", label: "Alerts", icon: AlertTriangle }] },
  { label: "Evaluate", items: [{ href: "/evaluations", label: "Evaluations", icon: ChartNoAxesCombined }] },
  { label: "Build", items: [{ href: "/projects", label: "Projects", icon: Boxes }, { href: "/agents", label: "Agents", icon: Bot }, { href: "/api-keys", label: "API Keys", icon: KeyRound }] },
  { label: "Organization", items: [{ href: "/members", label: "Members", icon: Users }, { href: "/audit-logs", label: "Audit Logs", icon: FileClock }, { href: "/privacy", label: "Privacy", icon: Fingerprint }, { href: "/settings", label: "Settings", icon: Settings }] },
];

export function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const [mobile, setMobile] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => { const query = window.matchMedia("(max-width: 900px)"); const update = () => { setMobile(query.matches); if (!query.matches) onClose(); }; update(); query.addEventListener("change", update); return () => query.removeEventListener("change", update); }, [onClose]);
  useEffect(() => {
    if (!mobile || !open) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? []);
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => { document.removeEventListener("keydown", handleKeyDown); window.requestAnimationFrame(() => previousFocus?.focus()); };
  }, [mobile, onClose, open]);
  const hidden = mobile && !open;
  return <><button aria-label="Close navigation" aria-hidden={!open} tabIndex={-1} className={cn("sidebar-scrim", open && "is-open")} onClick={onClose} /><aside ref={sidebarRef} aria-label="Primary navigation" aria-hidden={hidden || undefined} className={cn("sidebar", open && "is-open")}>
    <div className="brand-lockup"><span className="brand-mark" aria-hidden="true"><span /></span><span><strong>AgentOps</strong><small>Monitor</small></span><button ref={closeRef} tabIndex={hidden ? -1 : undefined} className="icon-button sidebar-close" onClick={onClose} aria-label="Close navigation"><X size={17} /></button></div>
    <nav className="sidebar-nav">{groups.map((group) => <section key={group.label} className="nav-group"><h2>{group.label}</h2>{group.items.map(({ href, label, icon: Icon }) => { const active = pathname === href || pathname.startsWith(`${href}/`); return <Link tabIndex={hidden ? -1 : undefined} key={href} href={href} aria-current={active ? "page" : undefined} onClick={onClose} className={cn("nav-link", active && "is-active")}><Icon size={16} strokeWidth={1.8} /><span>{label}</span></Link>; })}</section>)}</nav>
    <div className="sidebar-footer"><SlidersHorizontal size={14} /><span>Operations console</span></div>
  </aside></>;
}
