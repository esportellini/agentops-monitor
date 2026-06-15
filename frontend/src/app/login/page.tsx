"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function LoginPage() {
  const { login, organizations } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email, password);
      router.push(organizations.length > 1 ? "/select-organization" : "/dashboard");
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        if (err.status === 429) setError("Account temporarily locked. Please try again later.");
        else setError("Invalid email or password.");
      } else {
        setError("An unexpected error occurred.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <span className="text-xl font-semibold text-text-primary">AgentOps</span>
          <span className="ml-1.5 rounded bg-brand-500/20 px-1.5 py-0.5 text-[10px] font-medium text-brand-500 uppercase tracking-wider">
            Monitor
          </span>
          <p className="mt-2 text-sm text-text-secondary">Sign in to your account</p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="rounded-xl border border-surface-border bg-surface-card p-6 space-y-4"
        >
          {error && (
            <div className="rounded-md bg-status-error/10 border border-status-error/20 px-3 py-2 text-sm text-status-error">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">
              Email
            </label>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:border-brand-500 focus:outline-none"
              placeholder="you@company.com"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-text-secondary mb-1.5">
              Password
            </label>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:border-brand-500 focus:outline-none"
              placeholder="••••••••"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className={cn(
              "w-full rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
              loading
                ? "bg-brand-500/50 cursor-not-allowed"
                : "bg-brand-500 hover:bg-brand-600"
            )}
          >
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-text-muted">
          Demo credentials in README
        </p>
      </div>
    </div>
  );
}
