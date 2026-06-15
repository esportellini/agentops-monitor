"use client";

import { useAuth } from "@/contexts/AuthContext";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

export default function ProfilePage() {
  const { user, logout } = useAuth();

  return (
    <ProtectedLayout>
      <div className="p-8 max-w-sm">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Profile</h1>
        </div>
        <div className="rounded-lg border border-surface-border bg-surface-card p-6 space-y-4">
          <div>
            <p className="text-xs text-text-muted">Name</p>
            <p className="mt-1 text-sm font-medium text-text-primary">{user?.name ?? "—"}</p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Email</p>
            <p className="mt-1 text-sm text-text-primary">{user?.email ?? "—"}</p>
          </div>
          <div className="pt-2 border-t border-surface-border">
            <button
              onClick={logout}
              className="w-full rounded-md border border-surface-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-muted transition-colors"
            >
              Sign out
            </button>
          </div>
        </div>
      </div>
    </ProtectedLayout>
  );
}
