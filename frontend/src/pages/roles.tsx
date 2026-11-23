/** Roles and their permissions (matrix or list). */
import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useGet } from "../api/hooks";
import type { Permission, Role } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Banner, ErrorBanner, Modal, PageHead, Panel, Segmented, toast } from "../ui";
import { PermissionMatrix } from "./modules";

export function RolesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const roles = useGet<Role[]>(["roles"], "/roles/");
  const perms = useGet<Permission[]>(["permissions"], "/permissions/");
  const [editing, setEditing] = useState<Role | null>(null);
  const [saved, setSaved] = useState(false);
  const describe = useMemo(() => new Map((perms.data ?? []).map((p) => [p.code, p.description])), [perms.data]);
  return (
    <div className="stack">
      <PageHead title={t("roles.title")} sub={t("roles.intro")} />
      {saved && <Banner tone="ok">{t("roles.saved")}</Banner>}
      <ErrorBanner error={roles.error ?? perms.error} />
      {roles.data?.map((role) => (
        <Panel
          key={role.id}
          title={
            <div>
              <h2>
                {role.name} {role.is_system && <Badge>{t("roles.system_role")}</Badge>}
              </h2>
              <p className="small muted">
                {role.description} {t("roles.users_count", { count: role.user_count })}
              </p>
            </div>
          }
          actions={
            can("roles.manage") && (
              <button
                className="btn btn-sm"
                onClick={() => {
                  setSaved(false);
                  setEditing(role);
                }}
              >
                {t("roles.edit_permissions")}
              </button>
            )
          }
        >
          <div className="row" style={{ gap: 6 }}>
            {role.permission_codes.map((c) => (
              <span key={c} className="badge badge-muted" title={describe.get(c)}>
                {describe.get(c) ?? c}
              </span>
            ))}
          </div>
        </Panel>
      ))}
      <Modal open={editing !== null} wide title={editing?.name ?? ""} onClose={() => setEditing(null)}>
        {editing && perms.data && (
          <PermissionEditor
            role={editing}
            permissions={perms.data}
            onDone={() => {
              setEditing(null);
              setSaved(true);
            }}
          />
        )}
      </Modal>
    </div>
  );
}

function PermissionEditor({
  role,
  permissions,
  onDone,
}: {
  role: Role;
  permissions: Permission[];
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [selected, setSelected] = useState(new Set(role.permission_codes));
  const [layout, setLayout] = useState<"matrix" | "list">("matrix");
  const describe = useMemo(() => new Map(permissions.map((p) => [p.code, p.description])), [permissions]);
  const flip = (code: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(code)) n.delete(code);
      else n.add(code);
      return n;
    });
  const groups = useMemo(() => {
    const m = new Map<string, Permission[]>();
    for (const p of permissions) m.set(p.module, [...(m.get(p.module) ?? []), p]);
    return [...m.entries()];
  }, [permissions]);
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/roles/${role.id}/`, { permission_codes: [...selected].sort() }, { ifMatch: role.row_version }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["roles"] });
      void qc.invalidateQueries({ queryKey: ["auth", "me"] });
      toast(t("roles.saved_toast", "Role permissions saved"));
      onDone();
    },
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      className="stack-sm"
    >
      <ErrorBanner error={save.error} onReload={onDone} />
      <div className="row" style={{ justifyContent: "space-between" }}>
        <span className="small muted">
          {t("roles.selected_count", "{{n}} of {{total}} permissions", { n: selected.size, total: permissions.length })}
        </span>
        <Segmented
          label={t("roles.layout", "Layout")}
          value={layout}
          onChange={setLayout}
          options={[
            { key: "matrix", label: t("roles.matrix", "Matrix") },
            { key: "list", label: t("roles.list", "List") },
          ]}
        />
      </div>
      {layout === "matrix" ? (
        <PermissionMatrix selected={selected} onToggle={flip} describe={(c) => describe.get(c)} />
      ) : (
        <div className="cols-2">
          {groups.map(([module, list]) => (
            <fieldset key={module} className="fieldset">
              <legend style={{ textTransform: "capitalize" }}>{module}</legend>
              {list.map((p) => (
                <label key={p.code} className="check">
                  <input type="checkbox" checked={selected.has(p.code)} onChange={() => flip(p.code)} />
                  {p.description}
                </label>
              ))}
            </fieldset>
          ))}
        </div>
      )}
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending}>
          {save.isPending ? t("common.saving") : t("common.save")}
        </button>
      </div>
    </form>
  );
}
