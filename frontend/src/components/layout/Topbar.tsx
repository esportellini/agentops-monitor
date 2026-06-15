"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { cn } from "@/lib/utils";

export function Topbar() {
  const { user, organizations, activeOrg, setActiveOrg, logout } = useAuth();
  const router = useRouter();
  const [orgOpen, setOrgOpen] = useState(false);
  const [userOpen, setUserOpen] = useState(false);
  const orgRef = useRef<HTMLDivElement>(null);
  const userRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (orgRef.current && !orgRef.current.contains(e.target as Node)) setOrgOpen(false);
      if (userRef.current && !userRef.current.contains(e.target as Node)) setUserOpen(false);
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, []);

  async function handleLogout() {
    await logout();
    router.push("/login");
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-surface-border bg-surface-card px-5">
      {/* Org switcher */}
      <div className="relative" ref={orgRef}>
        <button
          onClick={() => setOrgOpen((o) => !o)}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-text-primary hover:bg-surface-muted transition-colors"
        >
          <span className="font-medium">{activeOrg?.name ?? "No org selected"}</span>
          <svg className="h-3.5 w-3.5 text-text-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {orgOpen && organizations.length > 0 && (
          <div className="absolute left-0 top-full z-50 mt-1 w-56 rounded-lg border border-surface-border bg-surface-card py-1 shadow-xl">
            {organizations.map((org) => (
              <button
                key={org.id}
                onClick={() => {
                  setActiveOrg(org);
                  setOrgOpen(false);
                }}
                className={cn(
                  "w-full px-3 py-2 text-left text-sm transition-colors hover:bg-surface-muted",
                  org.id === activeOrg?.id ? "text-brand-500 font-medium" : "text-text-secondary"
                )}
              >
                {org.name}
                <span className="ml-1.5 text-xs text-text-muted">{org.plan}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* User menu */}
      <div className="relative" ref={userRef}>
        <button
          onClick={() => setUserOpen((o) => !o)}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-surface-muted transition-colors"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-500/20 text-xs font-semibold text-brand-500 uppercase">
            {user?.name?.[0] ?? "?"}
          </div>
          <span className="text-text-secondary hidden sm:block">{user?.name}</span>
        </button>

        {userOpen && (
          <div className="absolute right-0 top-full z-50 mt-1 w-48 rounded-lg border border-surface-border bg-surface-card py-1 shadow-xl">
            <div className="border-b border-surface-border px-3 py-2">
              <p className="text-xs font-medium text-text-primary truncate">{user?.name}</p>
              <p className="text-xs text-text-muted truncate">{user?.email}</p>
            </div>
            <button
              onClick={() => { setUserOpen(false); router.push("/profile"); }}
              className="w-full px-3 py-2 text-left text-sm text-text-secondary hover:bg-surface-muted transition-colors"
            >
              Profile
            </button>
            <button
              onClick={() => { setUserOpen(false); router.push("/settings"); }}
              className="w-full px-3 py-2 text-left text-sm text-text-secondary hover:bg-surface-muted transition-colors"
            >
              Settings
            </button>
            <div className="border-t border-surface-border mt-1 pt-1">
              <button
                onClick={handleLogout}
                className="w-full px-3 py-2 text-left text-sm text-status-error hover:bg-surface-muted transition-colors"
              >
                Sign out
              </button>
            </div>
          </div>
        )}
      </div>
    </header>
  );
}
