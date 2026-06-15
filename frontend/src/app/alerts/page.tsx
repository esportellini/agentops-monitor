"use client";
import { ProtectedLayout } from "@/components/layout/ProtectedLayout";
export default function Page() {
  return (
    <ProtectedLayout>
      <div className="p-8">
        <h1 className="text-xl font-semibold text-text-primary">Alerts</h1>
        <p className="mt-2 text-sm text-text-secondary">Coming soon.</p>
      </div>
    </ProtectedLayout>
  );
}
