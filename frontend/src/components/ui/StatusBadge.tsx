import { cn } from "@/lib/utils";

type Status = "ok" | "degraded" | "error" | "unknown";

const styles: Record<Status, string> = {
  ok: "bg-status-ok/15 text-status-ok",
  degraded: "bg-status-warn/15 text-status-warn",
  error: "bg-status-error/15 text-status-error",
  unknown: "bg-surface-muted text-text-muted",
};

const dot: Record<Status, string> = {
  ok: "bg-status-ok",
  degraded: "bg-status-warn",
  error: "bg-status-error",
  unknown: "bg-text-muted",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        styles[status],
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dot[status])} />
      {status}
    </span>
  );
}
