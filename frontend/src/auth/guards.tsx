import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "./AuthContext";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  const { t } = useTranslation();

  if (loading) return <div className="page-loading">{t("common.loading")}</div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (user.must_change_password && location.pathname !== "/account/password") {
    return <Navigate to="/account/password" replace />;
  }
  if (!user.must_change_password && user.mfa_setup_required && location.pathname !== "/account/security") {
    return <Navigate to="/account/security" replace />;
  }
  return <>{children}</>;
}

/** UI convenience only: the API independently refuses requests without the permission. */
export function RequirePermission({ anyOf, children }: { anyOf: string[]; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(...anyOf)) return <Navigate to="/" replace />;
  return <>{children}</>;
}
