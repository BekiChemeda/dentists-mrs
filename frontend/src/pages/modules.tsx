import { Fragment, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ApiError, api } from "../api/client";
import { useGet } from "../api/hooks";
import type { ClinicModule, PermissionLayout } from "../api/types";
import { Badge, Banner, ConfirmDialog, ErrorBanner, Loading, Panel, toast } from "../ui";

/**
 * Which parts of the system this clinic uses. Only the system administrator (system.security.manage)
 * switches modules on and off; everyone else, including the clinic administrator, sees the list read-only.
 */
export function ModulesPanel({ editable }: { editable: boolean }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useGet<ClinicModule[]>(["system", "modules"], "/system/modules/");
  const [confirm, setConfirm] = useState<ClinicModule | null>(null);
  const toggle = useMutation({
    mutationFn: (v: { key: string; enabled: boolean }) =>
      api.patch<ClinicModule[]>(`/system/modules/${v.key}/`, { enabled: v.enabled }),
    onSuccess: (rows, v) => {
      qc.setQueryData(["system", "modules"], rows);
      // Permissions and menus change for everyone; refresh this user's now, others on their next request.
      void qc.invalidateQueries({ queryKey: ["auth", "me"] });
      void qc.invalidateQueries({ queryKey: ["system", "permission-layout"] });
      const name = rows.find((r) => r.key === v.key)?.name ?? v.key;
      toast(
        v.enabled
          ? t("modules.on_toast", "{{name}} switched on", { name })
          : t("modules.off_toast", "{{name}} switched off", { name }),
      );
    },
  });
  const openWork =
    toggle.error instanceof ApiError ? (toggle.error.details.open_work as string[] | undefined) : undefined;
  const nameOf = (key: string) => q.data?.find((m) => m.key === key)?.name ?? key;

  if (!q.data) return q.error ? <ErrorBanner error={q.error} /> : <Loading />;
  return (
    <Panel
      title={
        <div>
          <h2>{t("modules.title", "Modules")}</h2>
          <p className="small muted">
            {editable
              ? t(
                  "modules.intro_admin",
                  "Switch off the parts this clinic does not use. Menus, permissions and the patient flow follow at once. Records already made are kept.",
                )
              : t(
                  "modules.intro_readonly",
                  "The parts of the system this clinic uses. Only the system administrator can change them.",
                )}
          </p>
        </div>
      }
    >
      {toggle.error && (
        <Banner tone="error">
          <div>{toggle.error.message}</div>
          {openWork && openWork.length > 0 && (
            <ul className="small" style={{ margin: "6px 0 0" }}>
              {openWork.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
        </Banner>
      )}
      <ul className="module-list">
        {q.data.map((m) => {
          const forced = m.off_because_of.length > 0;
          return (
            <li key={m.key} className="module-row">
              <div className="module-text">
                <div className="row" style={{ gap: 8 }}>
                  <strong>{m.name}</strong>
                  <Badge tone={m.enabled ? "ok" : "muted"}>
                    {m.enabled ? t("modules.on", "On") : t("modules.off", "Off")}
                  </Badge>
                </div>
                <p className="small" style={{ margin: "2px 0" }}>
                  {m.description}
                </p>
                {!m.enabled && (
                  <p className="small muted" style={{ margin: 0 }}>
                    {t("modules.when_off", "While off")}: {m.when_off}
                  </p>
                )}
                {forced && (
                  <p className="small muted" style={{ margin: 0 }}>
                    {t("modules.off_because", "Off because {{names}} is off.", {
                      names: m.off_because_of.map(nameOf).join(", "),
                    })}
                  </p>
                )}
                {m.requires.length > 0 && !forced && (
                  <p className="small subtle" style={{ margin: 0 }}>
                    {t("modules.needs", "Needs {{names}}.", { names: m.requires.map(nameOf).join(", ") })}
                  </p>
                )}
              </div>
              {editable && (
                <label className="switch" aria-label={m.name}>
                  <input
                    type="checkbox"
                    role="switch"
                    checked={m.enabled}
                    disabled={toggle.isPending || forced}
                    onChange={() => {
                      toggle.reset();
                      if (m.enabled) setConfirm(m);
                      else toggle.mutate({ key: m.key, enabled: true });
                    }}
                  />
                </label>
              )}
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        open={confirm !== null}
        danger
        title={t("modules.confirm_off_title", "Switch off {{name}}?", { name: confirm?.name ?? "" })}
        body={
          <div className="stack-sm">
            <p>{confirm?.when_off}</p>
            {confirm && confirm.needed_by.length > 0 && (
              <p>
                {t("modules.also_off", "{{names}} will also stop working, because it needs this module.", {
                  names: confirm.needed_by.map(nameOf).join(", "),
                })}
              </p>
            )}
            <p className="small muted">
              {t("modules.confirm_note", "Records already made are kept. You can switch it back on at any time.")}
            </p>
          </div>
        }
        confirmLabel={t("modules.switch_off", "Switch off")}
        onClose={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm) toggle.mutate({ key: confirm.key, enabled: false });
          setConfirm(null);
        }}
      />
    </Panel>
  );
}

/**
 * Permissions laid out as areas of work (rows) by kinds of action (columns), like a permission matrix
 * in an ERP. Rows of switched-off modules are greyed: their permissions do nothing while the module is off.
 */
export function PermissionMatrix({
  selected,
  onToggle,
  describe,
}: {
  selected: Set<string>;
  onToggle?: (code: string) => void;
  describe?: (code: string) => string | undefined;
}) {
  const { t } = useTranslation();
  const q = useGet<PermissionLayout>(["system", "permission-layout"], "/system/permission-layout/");
  if (!q.data) return q.error ? <ErrorBanner error={q.error} /> : <Loading />;
  const { actions, areas } = q.data;
  const toggleArea = (codes: string[]) => {
    if (!onToggle) return;
    const allOn = codes.every((c) => selected.has(c));
    codes.filter((c) => selected.has(c) === allOn).forEach(onToggle);
  };
  return (
    <div className="table-wrap">
      <table className="data perm-matrix">
        <thead>
          <tr>
            <th scope="col">{t("roles.area", "Area of work")}</th>
            {actions.map((a) => (
              <th key={a.key} scope="col">
                {a.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {areas.map((area) => (
            <tr key={area.key} className={area.module_on ? undefined : "muted"}>
              <th scope="row">
                {onToggle ? (
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => toggleArea(area.permissions.map((p) => p.code))}
                    title={t("roles.toggle_area", "Select or clear the whole row")}
                  >
                    {area.name}
                  </button>
                ) : (
                  area.name
                )}
                {!area.module_on && <div className="small subtle">{t("roles.module_off", "Module switched off")}</div>}
              </th>
              {actions.map((a) => {
                const cells = area.permissions.filter((p) => p.action === a.key);
                return (
                  <td key={a.key}>
                    {cells.map((p) => (
                      <Fragment key={p.code}>
                        <label className="check perm-cell" title={p.code}>
                          <input
                            type="checkbox"
                            checked={selected.has(p.code)}
                            disabled={!onToggle}
                            onChange={() => onToggle?.(p.code)}
                          />
                          <span className="small">
                            {describe?.(p.code) ?? p.label}
                            {p.privileged && (
                              <>
                                {" "}
                                <Badge tone="danger">{t("roles.privileged", "Sensitive")}</Badge>
                              </>
                            )}
                          </span>
                        </label>
                      </Fragment>
                    ))}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
