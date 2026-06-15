"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api, ApiError } from "@/lib/api";

export interface AuthUser {
  id: number;
  email: string;
  name: string;
  is_active: boolean;
}

export interface Organization {
  id: number;
  name: string;
  slug: string;
  plan: string;
}

interface AuthState {
  user: AuthUser | null;
  accessToken: string | null;
  organizations: Organization[];
  activeOrg: Organization | null;
}

interface AuthCtx extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setActiveOrg: (org: Organization) => void;
  refreshOrgs: () => Promise<void>;
  isLoading: boolean;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    accessToken: null,
    organizations: [],
    activeOrg: null,
  });
  const [isLoading, setIsLoading] = useState(true);

  const fetchMe = useCallback(async (token: string) => {
    try {
      const user = await api.get<AuthUser>("/api/v1/auth/me", {
        Authorization: `Bearer ${token}`,
      });
      return user;
    } catch {
      return null;
    }
  }, []);

  const fetchOrgs = useCallback(async (token: string) => {
    try {
      return await api.get<Organization[]>("/api/v1/organizations", {
        Authorization: `Bearer ${token}`,
      });
    } catch {
      return [];
    }
  }, []);

  // On mount, try to restore session via refresh cookie
  useEffect(() => {
    (async () => {
      try {
        const { access_token } = await api.post<{ access_token: string }>(
          "/api/v1/auth/refresh"
        );
        const [user, orgs] = await Promise.all([
          fetchMe(access_token),
          fetchOrgs(access_token),
        ]);
        if (user) {
          const storedOrgId = localStorage.getItem("activeOrgId");
          const activeOrg =
            orgs.find((o) => o.id === Number(storedOrgId)) ?? orgs[0] ?? null;
          setState({ user, accessToken: access_token, organizations: orgs, activeOrg });
        }
      } catch {
        // No valid session — stay logged out
      } finally {
        setIsLoading(false);
      }
    })();
  }, [fetchMe, fetchOrgs]);

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await api.post<{ access_token: string }>(
        "/api/v1/auth/login",
        { email, password }
      );
      const [user, orgs] = await Promise.all([
        fetchMe(access_token),
        fetchOrgs(access_token),
      ]);
      if (!user) throw new Error("Failed to load user");
      const activeOrg = orgs[0] ?? null;
      if (activeOrg) localStorage.setItem("activeOrgId", String(activeOrg.id));
      setState({ user, accessToken: access_token, organizations: orgs, activeOrg });
    },
    [fetchMe, fetchOrgs]
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/api/v1/auth/logout", undefined, {
        Authorization: `Bearer ${state.accessToken ?? ""}`,
      });
    } catch { /* best effort */ }
    localStorage.removeItem("activeOrgId");
    setState({ user: null, accessToken: null, organizations: [], activeOrg: null });
  }, [state.accessToken]);

  const setActiveOrg = useCallback((org: Organization) => {
    localStorage.setItem("activeOrgId", String(org.id));
    setState((s) => ({ ...s, activeOrg: org }));
  }, []);

  const refreshOrgs = useCallback(async () => {
    if (!state.accessToken) return;
    const orgs = await fetchOrgs(state.accessToken);
    setState((s) => ({ ...s, organizations: orgs }));
  }, [state.accessToken, fetchOrgs]);

  const value = useMemo(
    () => ({ ...state, login, logout, setActiveOrg, refreshOrgs, isLoading }),
    [state, login, logout, setActiveOrg, refreshOrgs, isLoading]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
