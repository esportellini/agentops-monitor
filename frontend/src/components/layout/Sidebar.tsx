"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const nav = [
  { href: "/dashboard",   label: "Dashboard" },
  { href: "/projects",    label: "Projects" },
  { href: "/agents",      label: "Agents" },
  { href: "/traces",      label: "Traces" },
  { href: "/costs",       label: "Costs" },
  { href: "/evaluations", label: "Evaluations" },
  { href: "/security",    label: "Security" },
  { href: "/approvals",   label: "Approvals" },
  { href: "/alerts",      label: "Alerts" },
  { href: "/audit-logs",  label: "Audit Logs" },
  { href: "/api-keys",    label: "API Keys" },
  { href: "/members",     label: "Members" },
  { href: "/privacy",     label: "Privacy" },
  { href: "/settings",    label: "Settings" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-full w-56 flex-col border-r border-surface-border bg-surface-card">
      <div className="flex h-14 items-center px-5 border-b border-surface-border shrink-0">
        <span className="text-sm font-semibold tracking-wide text-text-primary">AgentOps</span>
        <span className="ml-1.5 rounded bg-brand-500/20 px-1.5 py-0.5 text-[10px] font-medium text-brand-500 uppercase tracking-wider">
          Monitor
        </span>
      </div>

      <nav className="flex-1 overflow-y-auto p-3">
        <ul className="space-y-0.5">
          {nav.map(({ href, label }) => (
            <li key={href}>
              <Link
                href={href}
                className={cn(
                  "block rounded-md px-3 py-2 text-sm transition-colors",
                  pathname === href || pathname.startsWith(href + "/")
                    ? "bg-brand-500/15 text-brand-500 font-medium"
                    : "text-text-secondary hover:bg-surface-muted hover:text-text-primary"
                )}
              >
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <div className="border-t border-surface-border p-4 shrink-0">
        <p className="text-xs text-text-muted">v0.1.0</p>
      </div>
    </aside>
  );
}
