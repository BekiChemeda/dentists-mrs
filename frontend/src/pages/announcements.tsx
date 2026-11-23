/** Announcements shown at the top of staff home pages. */
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Megaphone } from "lucide-react";
import { api, queryString } from "../api/client";
import { useGet } from "../api/hooks";
import type { Announcement, Department, Paginated, Role } from "../api/types";
import { Badge, Empty, ErrorBanner, Field, Loading, Modal, PageHead, Pager, Panel, fieldErrors, toast } from "../ui";
import { todayIso } from "./common";

// ---------------------------------------------------------------------------
// Announcements
// ---------------------------------------------------------------------------
export function AnnouncementsPage() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Announcement | "new" | null>(null);
  const q = useGet<Paginated<Announcement>>(["announcements", "all", page], `/announcements/${queryString({ page })}`);
  const roles = useGet<Role[]>(["roles"], "/roles/");
  const roleName = (id: string) => roles.data?.find((r) => r.id === id)?.name ?? "";
  const today = todayIso();
  const live = (a: Announcement) => a.is_active && a.starts_on <= today && (!a.ends_on || a.ends_on >= today);
  return (
    <div className="stack">
      <PageHead
        title={t("nav.announcements", "Announcements")}
        sub={t(
          "announcements.sub",
          "Notices shown at the top of staff dashboards. Do not include patient information.",
        )}
        actions={
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            <Megaphone size={18} aria-hidden /> {t("announcements.new", "New announcement")}
          </button>
        }
      />
      <ErrorBanner error={q.error} />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : !q.data?.results.length ? (
          <Empty>{t("announcements.none", "No announcements yet.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("announcements.title_col", "Announcement")}</th>
                  <th>{t("announcements.audience", "Shown to")}</th>
                  <th>{t("announcements.dates", "Dates")}</th>
                  <th>{t("users.status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {q.data.results.map((a) => (
                  <tr key={a.id} className={live(a) ? "" : "muted"}>
                    <td>
                      <strong>{a.title}</strong>{" "}
                      {a.level === "important" && (
                        <Badge tone="danger">{t("announcements.important", "Important")}</Badge>
                      )}
                      {a.body && <div className="small muted clamp-2">{a.body}</div>}
                      <div className="small subtle">{a.created_by_name}</div>
                    </td>
                    <td className="small">
                      {[a.role_ids.map(roleName).join(", "), a.department_name].filter(Boolean).join(" · ") ||
                        t("announcements.everyone", "Everyone")}
                    </td>
                    <td className="nowrap small">
                      {a.starts_on}
                      {a.ends_on ? ` → ${a.ends_on}` : ""}
                    </td>
                    <td>
                      {live(a) ? (
                        <Badge tone="ok">{t("announcements.live", "Showing")}</Badge>
                      ) : (
                        <Badge>
                          {a.is_active
                            ? t("announcements.scheduled", "Not showing now")
                            : t("announcements.withdrawn", "Withdrawn")}
                        </Badge>
                      )}
                    </td>
                    <td className="num">
                      <button className="btn btn-sm" onClick={() => setEditing(a)}>
                        {t("users.edit")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {q.data && <Pager page={page} count={q.data.count} pageSize={25} onPage={setPage} />}
      </Panel>
      <Modal
        open={editing !== null}
        wide
        title={
          editing === "new" ? t("announcements.new", "New announcement") : t("announcements.edit", "Edit announcement")
        }
        onClose={() => setEditing(null)}
      >
        {editing !== null && (
          <AnnouncementForm
            item={editing === "new" ? null : editing}
            roles={roles.data ?? []}
            onDone={() => setEditing(null)}
          />
        )}
      </Modal>
    </div>
  );
}

function AnnouncementForm({ item, roles, onDone }: { item: Announcement | null; roles: Role[]; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const depts = useGet<Department[]>(["departments", "active"], "/departments/?active=true");
  const [f, setF] = useState({
    title: item?.title ?? "",
    body: item?.body ?? "",
    level: item?.level ?? "info",
    starts_on: item?.starts_on ?? todayIso(),
    ends_on: item?.ends_on ?? "",
    is_active: item?.is_active ?? true,
    role_ids: item?.role_ids ?? ([] as string[]),
    department_id: item?.department_id ?? "",
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, ends_on: f.ends_on || null, department_id: f.department_id || null };
      return item
        ? api.patch(`/announcements/${item.id}/`, body, { ifMatch: item.row_version })
        : api.post("/announcements/", body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["announcements"] });
      toast(t("common.saved_toast", "Changes saved"));
      onDone();
    },
  });
  const toggleRole = (id: string) =>
    setF({ ...f, role_ids: f.role_ids.includes(id) ? f.role_ids.filter((x) => x !== id) : [...f.role_ids, id] });
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <ErrorBanner error={save.error} onReload={onDone} />
      <Field label={t("announcements.title_field", "Title")} id="an-t" error={fieldErrors(save.error, "title")}>
        <input
          id="an-t"
          value={f.title}
          maxLength={150}
          onChange={(e) => setF({ ...f, title: e.target.value })}
          required
        />
      </Field>
      <Field label={t("announcements.body", "Details (optional)")} id="an-b">
        <textarea
          id="an-b"
          rows={3}
          value={f.body}
          maxLength={2000}
          onChange={(e) => setF({ ...f, body: e.target.value })}
        />
      </Field>
      <div className="form-grid">
        <Field label={t("announcements.from", "Show from")} id="an-s" error={fieldErrors(save.error, "starts_on")}>
          <input
            id="an-s"
            type="date"
            value={f.starts_on}
            onChange={(e) => setF({ ...f, starts_on: e.target.value })}
            required
          />
        </Field>
        <Field
          label={t("announcements.until", "Until (optional)")}
          id="an-e"
          error={fieldErrors(save.error, "ends_on")}
        >
          <input id="an-e" type="date" value={f.ends_on} onChange={(e) => setF({ ...f, ends_on: e.target.value })} />
        </Field>
        <Field label={t("announcements.level", "Importance")} id="an-l">
          <select
            id="an-l"
            value={f.level}
            onChange={(e) => setF({ ...f, level: e.target.value as "info" | "important" })}
          >
            <option value="info">{t("announcements.info", "Information")}</option>
            <option value="important">{t("announcements.important", "Important")}</option>
          </select>
        </Field>
        <Field label={t("announcements.department", "Only for department")} id="an-d">
          <select id="an-d" value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })}>
            <option value="">{t("announcements.all_departments", "All departments")}</option>
            {depts.data?.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <fieldset className="fieldset">
        <legend>{t("announcements.roles", "Only for these roles (none ticked = everyone)")}</legend>
        <div className="cols-2">
          {roles.map((r) => (
            <label key={r.id} className="check">
              <input type="checkbox" checked={f.role_ids.includes(r.id)} onChange={() => toggleRole(r.id)} /> {r.name}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="check">
        <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />{" "}
        {t("announcements.active", "Published (untick to withdraw)")}
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending}>
          {item ? t("common.save") : t("announcements.publish", "Publish")}
        </button>
      </div>
    </form>
  );
}

/** Announcements for the signed-in user, at the top of every dashboard. */
export function AnnouncementsBlock() {
  const q = useGet<Announcement[]>(["announcements", "current"], "/announcements/current/", {
    refetchInterval: 300_000,
  });
  if (!q.data?.length) return null;
  return (
    <div className="announcements">
      {q.data.map((a) => (
        <article key={a.id} className={`announcement announcement-${a.level}`}>
          <Megaphone size={18} aria-hidden />
          <div>
            <strong>{a.title}</strong>
            {a.body && <p>{a.body}</p>}
            <span className="small subtle">
              {a.created_by_name} · {a.starts_on}
            </span>
          </div>
        </article>
      ))}
    </div>
  );
}
