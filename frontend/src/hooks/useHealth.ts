import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface HealthResponse {
  status: "ok" | "degraded";
  checks: Record<string, "ok" | "error">;
}

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: () => api.get<HealthResponse>("/api/v1/health"),
    refetchInterval: 30_000,
  });
}
