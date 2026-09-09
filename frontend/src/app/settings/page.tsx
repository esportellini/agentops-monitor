"use client";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";

const sections = [
  { title: "Privacy & LGPD", href: "/privacy", description: "Data map, retention policies, subject rights, anonymization" },
  { title: "Security Policies", href: "/security", description: "Agent policies, tool approvals, threat findings" },
  { title: "Audit Logs", href: "/audit-logs", description: "Immutable record of all organization events" },
  { title: "API Keys", href: "/api-keys", description: "Manage ingest API keys" },
  { title: "Members", href: "/members", description: "Invite and manage team members" },
  { title: "Alert Rules", href: "/alerts", description: "Configure cost, latency, and security alerts" },
];

export default function SettingsPage() {
  return (
    <ProtectedLayout>
      <div className="p-8 max-w-2xl">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-text-primary">Settings</h1>
          <p className="mt-1 text-sm text-text-secondary">Organization configuration and compliance</p>
        </div>
        <div className="space-y-2">
          {sections.map(s => (
            <Link key={s.href} href={s.href} className="flex items-center justify-between rounded-lg border border-surface-border bg-surface-card p-4 hover:bg-surface-muted/30 transition-colors group">
              <div>
                <p className="text-sm font-medium text-text-primary group-hover:text-brand-500 transition-colors">{s.title}</p>
                <p className="text-xs text-text-secondary mt-0.5">{s.description}</p>
              </div>
              <ChevronRight className="h-4 w-4 text-text-muted" />
            </Link>
          ))}
        </div>
      </div>
    </ProtectedLayout>
  );
}
