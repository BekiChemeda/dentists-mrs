/** Departments of the clinic and their consultation rooms. */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import { api } from "../api/client";
import { useGet } from "../api/hooks";
import type { Department } from "../api/types";
import { RoomsPanel } from "./setup";
import { Badge, Empty, ErrorBanner, Field, Loading, Modal, PageHead, Panel, fieldErrors, toast } from "../ui";

// ---------------------------------------------------------------------------
// Departments
// ---------------------------------------------------------------------------
export function DepartmentsPage() {
  const { t } = useTranslation();
  const q = useGet<Department[]>(["departments", "all"], "/departments/");
  const [editing, setEditing] = useState<Department | "new" | null>(null);
  return (
    <div className="stack">
      <PageHead
        title={t("nav.departments", "Departments")}
        sub={t(
          "departments.sub",
          "Units of the clinic. Staff belong to one; those marked as triage destinations appear in the nurse's “Triage to” list.",
        )}
        actions={
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            <Plus size={18} aria-hidden /> {t("departments.new", "New department")}
          </button>
        }
      />
      <ErrorBanner error={q.error} />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : !q.data?.length ? (
          <Empty>{t("departments.none", "No departments yet.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("departments.name", "Name")}</th>
                  <th>{t("departments.code", "Code")}</th>
                  <th>{t("departments.triage", "Triage destination")}</th>
                  <th className="num">{t("departments.staff", "Staff")}</th>
                  <th>{t("users.status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {q.data.map((d) => (
                  <tr key={d.id} className={d.is_active ? "" : "muted"}>
                    <td>
                      <strong>{d.name}</strong>
                    </td>
                    <td className="mono small">{d.code}</td>
                    <td>{d.receives_triage ? <Badge tone="info">{t("common.yes", "Yes")}</Badge> : "—"}</td>
                    <td className="num">{d.staff_count ?? 0}</td>
                    <td>
                      <Badge tone={d.is_active ? "ok" : "muted"}>
                        {d.is_active ? t("common.active") : t("common.inactive")}
                      </Badge>
                    </td>
                    <td className="num">
                      <button className="btn btn-sm" onClick={() => setEditing(d)}>
                        {t("users.edit")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <RoomsPanel />
      <Modal
        open={editing !== null}
        title={editing === "new" ? t("departments.new", "New department") : t("departments.edit", "Edit department")}
        onClose={() => setEditing(null)}
      >
        {editing !== null && (
          <DepartmentForm dept={editing === "new" ? null : editing} onDone={() => setEditing(null)} />
        )}
      </Modal>
    </div>
  );
}

function DepartmentForm({ dept, onDone }: { dept: Department | null; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [f, setF] = useState({
    code: dept?.code ?? "",
    name: dept?.name ?? "",
    receives_triage: dept?.receives_triage ?? false,
    is_active: dept?.is_active ?? true,
    sort_order: dept?.sort_order ?? 0,
  });
  const save = useMutation({
    mutationFn: () => {
      const { code, ...rest } = f;
      return dept
        ? api.patch<Department>(`/departments/${dept.id}/`, rest, { ifMatch: dept.row_version })
        : api.post<Department>("/departments/", f);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["departments"] });
      toast(t("common.saved_toast", "Changes saved"));
      onDone();
    },
  });
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <ErrorBanner error={save.error} onReload={onDone} />
      <div className="form-grid">
        <Field label={t("departments.name", "Name")} id="dp-n" error={fieldErrors(save.error, "name")}>
          <input id="dp-n" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        </Field>
        <Field
          label={t("departments.code", "Code")}
          id="dp-c"
          error={fieldErrors(save.error, "code")}
          hint={
            dept
              ? t("departments.code_fixed", "Cannot change: it is stored on triage records.")
              : t("departments.code_hint", "Short, lowercase, no spaces, e.g. dental")
          }
        >
          <input
            id="dp-c"
            className="mono"
            value={f.code}
            disabled={!!dept}
            onChange={(e) => setF({ ...f, code: e.target.value.toLowerCase() })}
            required
          />
        </Field>
        <Field label={t("departments.order", "Position in lists")} id="dp-o">
          <input
            id="dp-o"
            type="number"
            min={0}
            value={f.sort_order}
            onChange={(e) => setF({ ...f, sort_order: Number(e.target.value) })}
          />
        </Field>
      </div>
      <label className="check">
        <input
          type="checkbox"
          checked={f.receives_triage}
          onChange={(e) => setF({ ...f, receives_triage: e.target.checked })}
        />{" "}
        {t("departments.triage_label", "Nurses can send patients here after triage")}
      </label>
      <label className="check">
        <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />{" "}
        {t("common.active")}
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending}>
          {t("common.save")}
        </button>
      </div>
    </form>
  );
}
