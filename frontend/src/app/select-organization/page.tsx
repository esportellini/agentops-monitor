"use client";

import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { useEffect } from "react";

export default function SelectOrgPage() {
  const { user, organizations, setActiveOrg, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) router.replace("/login");
    if (!isLoading && organizations.length === 1) {
      setActiveOrg(organizations[0]);
      router.replace("/dashboard");
    }
  }, [isLoading, user, organizations, router, setActiveOrg]);

  if (isLoading) return null;

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-md">
        <h1 className="mb-2 text-lg font-semibold text-text-primary">Select organization</h1>
        <p className="mb-6 text-sm text-text-secondary">
          You belong to multiple organizations. Choose one to continue.
        </p>
        <div className="space-y-2">
          {organizations.map((org) => (
            <button
              key={org.id}
              onClick={() => {
                setActiveOrg(org);
                router.push("/dashboard");
              }}
              className="w-full rounded-lg border border-surface-border bg-surface-card px-4 py-3 text-left transition-colors hover:border-brand-500/50 hover:bg-surface-muted"
            >
              <p className="text-sm font-medium text-text-primary">{org.name}</p>
              <p className="mt-0.5 text-xs text-text-muted">
                {org.plan} · /{org.slug}
              </p>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
