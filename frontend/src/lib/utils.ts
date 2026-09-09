import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCost(value: number | null | undefined, options?: { unpriced?: boolean }) {
  if (options?.unpriced) return "Unpriced";
  if (value == null) return "—";
  if (value < 0.0001 && value > 0) return `$${value.toFixed(8)}`;
  if (value < 0.01 && value > 0) return `$${value.toFixed(6)}`;
  if (value < 1) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export function formatTokens(value: number | null | undefined) {
  if (value == null) return "—";
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toLocaleString();
}

export function formatDuration(value: number | null | undefined) {
  if (value == null) return "—";
  return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(2)}s`;
}

export function formatDateTime(value: string | null | undefined) {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—";
}

export function formatPercentage(value: number | null | undefined) {
  return value == null ? "—" : `${value.toFixed(value % 1 ? 1 : 0)}%`;
}
