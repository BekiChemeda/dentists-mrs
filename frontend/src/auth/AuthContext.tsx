import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, api, setUnauthenticatedHandler } from "../api/client";
import type { CurrentUser } from "../api/types";

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  /** Returns the user, or a token when the account also needs a code from the authenticator app. */
  login: (username: string, password: string) => Promise<CurrentUser | { mfa_required: true; mfa_token: string }>;
  loginWithCode: (token: string, code: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  can: (...anyOf: string[]) => boolean;
  /** False when the system administrator has switched this module off. */
  moduleOn: (key: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);
const ME_KEY = ["auth", "me"];

/** Drop every cached query except the current-user query, so no data leaks between accounts. */
function clearDataQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();

  const meQuery = useQuery({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return await api.get<CurrentUser>("/auth/me/");
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    // Any 401 from any request means the session ended (idle timeout, revoked, deactivated).
    setUnauthenticatedHandler(() => {
      queryClient.setQueryData(ME_KEY, null);
      clearDataQueries(queryClient);
    });
  }, [queryClient]);

  const login = useCallback(
    async (username: string, password: string) => {
      const result = await api.post<CurrentUser | { mfa_required: true; mfa_token: string }>("/auth/login/", {
        username,
        password,
      });
      if ("mfa_required" in result) return result;
      clearDataQueries(queryClient);
      queryClient.setQueryData(ME_KEY, result);
      return result;
    },
    [queryClient],
  );

  const loginWithCode = useCallback(
    async (token: string, code: string) => {
      const user = await api.post<CurrentUser>("/auth/login/mfa/", { mfa_token: token, code });
      clearDataQueries(queryClient);
      queryClient.setQueryData(ME_KEY, user);
      return user;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout/");
    } finally {
      clearDataQueries(queryClient);
      queryClient.setQueryData(ME_KEY, null);
    }
  }, [queryClient]);

  const refresh = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ME_KEY });
  }, [queryClient]);

  const user = meQuery.data ?? null;
  const value = useMemo<AuthState>(
    () => ({
      user,
      loading: meQuery.isLoading,
      login,
      loginWithCode,
      logout,
      refresh,
      can: (...anyOf) => !!user && anyOf.some((code) => user.permissions.includes(code)),
      moduleOn: (key) => !(user?.modules_off ?? []).includes(key),
    }),
    [user, meQuery.isLoading, login, loginWithCode, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
