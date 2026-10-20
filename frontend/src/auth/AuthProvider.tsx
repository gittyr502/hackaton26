import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { api, type Role, type User } from "@/lib/api";
import { hasRole } from "@/lib/labels";
import { getToken, setToken } from "@/lib/token";
import { useI18n } from "@/i18n";

interface Auth {
  user: User | null;
  /** True until the stored token has been checked against /api/auth/me. */
  loading: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => void;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(() => !!getToken());

  useEffect(() => {
    if (!getToken()) return;
    api
      .me()
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.login(username, password);
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Where a user lands after login: the screen of their highest role. */
export function homeFor(user: User): string {
  if (hasRole(user, "admin") && !hasRole(user, "lab_manager", "intake", "approver")) return "/admin/users";
  if (hasRole(user, "lab_manager")) return "/dashboard";
  if (hasRole(user, "intake", "approver")) return "/me";
  return hasRole(user, "admin") ? "/admin/users" : "/me";
}

/** Renders child routes only for a logged-in user (optionally of the given roles). */
export function RequireAuth({ roles }: { roles?: Role[] }) {
  const { user, loading } = useAuth();
  const { t } = useI18n();
  const location = useLocation();
  if (loading)
    return (
      <div className="flex items-center gap-2 p-6 text-outline">
        <span className="material-symbols-outlined animate-spin">progress_activity</span> {t("common.loading")}
      </div>
    );
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (roles && !hasRole(user, ...roles)) return <Navigate to={homeFor(user)} replace />;
  return <Outlet />;
}
