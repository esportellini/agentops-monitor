import { useCallback } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { api, ApiError } from "@/lib/api";

export function useAuthFetch() {
  const { accessToken, logout } = useAuth();

  const authHeaders = useCallback((): Record<string, string> => {
    if (!accessToken) return {};
    return { Authorization: `Bearer ${accessToken}` };
  }, [accessToken]);

  const get = useCallback(
    async <T>(path: string): Promise<T> => {
      try {
        return await api.get<T>(path, authHeaders());
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          await logout();
          window.location.href = "/login";
        }
        throw e;
      }
    },
    [authHeaders, logout],
  );

  const post = useCallback(
    async <T>(path: string, body?: unknown): Promise<T> => {
      return api.post<T>(path, body, authHeaders());
    },
    [authHeaders],
  );

  const patch = useCallback(
    async <T>(path: string, body?: unknown): Promise<T> => {
      return api.patch<T>(path, body);
    },
    [],
  );

  const del = useCallback(
    async <T>(path: string): Promise<T> => {
      return api.delete<T>(path);
    },
    [],
  );

  return { get, post, patch, delete: del };
}
