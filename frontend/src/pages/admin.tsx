import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { UserPlus } from "lucide-react";
import { api, queryString } from "../api/client";
import { useGet } from "../api/hooks";
import type { Department, Paginated, Role, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import {
  Badge,
  Banner,
  ConfirmDialog,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  Modal,
  PageHead,
  Pager,
  Panel,
  fieldErrors,
  toast,
} from "../ui";
type UserWithTemp = User & { temporary_password?: string; sessions_ended?: number };

export function UsersPage() {
  const { t } = useTranslation();
  const { can, user: me } = useAuth();
  const qc = useQueryClient();
  // System administrators manage every account; clinic administrators (staff.manage) only ordinary staff.
  const canManage = can("users.manage", "staff.manage");
  const staffOnly = !can("users.manage");
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [status, setStatus] = useState("");
  const [dept, setDept] = useState("");
  const depts = useGet<Department[]>(["departments", "all"], "/departments/");
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [secret, setSecret] = useState<{ username: string; password: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const users = useQuery({
    queryKey: ["users", applied, status, dept, page],
    queryFn: () =>
      api.get<Paginated<User>>(`/users/${queryString({ search: applied, is_active: status, department: dept, page })}`),
  });
  const roles = useGet<Role[]>(["roles"], "/roles/");
  const action = useMutation({
    mutationFn: ({ user, path }: { user: User; path: string }) => api.post<UserWithTemp>(`/users/${user.id}/${path}/`),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["users"] });
      if (r.temporary_password) setSecret({ username: r.username, password: r.temporary_password });
      if (r.sessions_ended !== undefined) setNotice(t("users.sessions_ended", { count: r.sessions_ended }));
      toast(t("common.saved_toast", "Changes saved"));
    },
  });
  const [pending, setPending] = useState<{ user: User; path: string; text: string } | null>(null);
  const run = (u: User, path: string, confirmText?: string) => {
    setNotice(null);
    if (confirmText) {
      setPending({ user: u, path, text: confirmText });
      return;
    }
    action.mutate({ user: u, path });
  };

  return (
    <div className="stack">
      <PageHead
        title={t("users.title")}
        actions={
          canManage && (
            <button className="btn btn-primary" onClick={() => setEditing("new")}>
              <UserPlus size={18} aria-hidden /> {t("users.new")}
            </button>
          )
        }
      />
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setApplied(search.trim());
        }}
      >
        <div className="field">
          <label htmlFor="us">{t("common.search")}</label>
          <input id="us" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ust">{t("users.status")}</label>
          <select
            id="ust"
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}
          >
            <option value="">{t("common.all")}</option>
            <option value="true">{t("common.active")}</option>
            <option value="false">{t("common.inactive")}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="udp">{t("users.department", "Department")}</label>
          <select
            id="udp"
            value={dept}
            onChange={(e) => {
              setPage(1);
              setDept(e.target.value);
            }}
          >
            <option value="">{t("common.all")}</option>
            {depts.data?.map((d) => (
              <option key={d.id} value={d.code}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
        <button className="btn" type="submit">
          {t("common.search")}
        </button>
      </form>
      <ConfirmDialog
        open={!!pending}
        onClose={() => setPending(null)}
        danger
        title={t("users.confirm_title", "Please confirm")}
        body={pending?.text}
        confirmLabel={t("common.confirm", "Confirm")}
        onConfirm={() => pending && action.mutate({ user: pending.user, path: pending.path })}
      />
      {staffOnly && canManage && (
        <Banner tone="info">
          {t(
            "users.staff_scope",
            "You can add and manage clinic staff. Accounts with administrative rights, and administrative roles, are handled by the system administrator.",
          )}
        </Banner>
      )}
      {notice && <Banner tone="ok">{notice}</Banner>}
      <ErrorBanner error={users.error ?? action.error} />
      <Panel flush>
        {users.isLoading ? (
          <Loading />
        ) : !users.data?.results.length ? (
          <Empty>{t("users.no_results")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("users.name", "Name")}</th>
                  <th>{t("users.username")}</th>
                  <th>{t("users.department", "Department")}</th>
                  <th>{t("users.roles")}</th>
                  <th>{t("users.status")}</th>
                  <th>{t("users.last_login")}</th>
                  {canManage && <th />}
                </tr>
              </thead>
              <tbody>
                {users.data.results.map((u) => (
                  <tr key={u.id} className={u.is_active ? "" : "muted"}>
                    <td>
                      <strong>{u.full_name}</strong>
                      {u.job_title && <div className="small subtle">{u.job_title}</div>}
                    </td>
                    <td className="mono">{u.username}</td>
                    <td>{u.department?.name ?? "—"}</td>
                    <td>{u.roles.map((r) => r.name).join(", ") || "—"}</td>
                    <td>
                      <div className="row" style={{ gap: 4 }}>
                        <Badge tone={u.is_active ? "ok" : "muted"}>
                          {u.is_active ? t("common.active") : t("common.inactive")}
                        </Badge>
                        {u.is_locked && <Badge tone="danger">{t("common.locked")}</Badge>}
                        {u.must_change_password && <Badge tone="wait">{t("users.pending_change")}</Badge>}
                        {u.mfa_enabled && <Badge tone="info">{t("users.mfa_on", "2-step")}</Badge>}
                      </div>
                    </td>
                    <td className="nowrap">{formatDateTime(u.last_login, t("common.never"))}</td>
                    {canManage && (
                      <td className="num">
                        {staffOnly && u.roles.some((r) => r.privileged) ? (
                          <span className="small subtle">{t("users.admin_account", "Administrator account")}</span>
                        ) : (
                          <div className="row" style={{ justifyContent: "flex-end", gap: 4 }}>
                            <button className="btn btn-sm" onClick={() => setEditing(u)}>
                              {t("users.edit")}
                            </button>
                            {u.is_locked && (
                              <button className="btn btn-sm" onClick={() => run(u, "unlock")}>
                                {t("users.unlock")}
                              </button>
                            )}
                            {u.id !== me?.id && (
                              <>
                                <button
                                  className="btn btn-sm"
                                  onClick={() =>
                                    run(u, "reset-password", t("users.confirm_reset", { name: u.full_name }))
                                  }
                                >
                                  {t("users.reset_password")}
                                </button>
                                {u.mfa_enabled && (
                                  <button
                                    className="btn btn-sm"
                                    onClick={() =>
                                      run(
                                        u,
                                        "reset-mfa",
                                        t(
                                          "users.confirm_reset_mfa",
                                          "Reset two-step sign-in for {{name}}? Do this only for a lost phone after checking who is asking. They will set it up again at their next sign-in, and their sessions end now.",
                                          { name: u.full_name },
                                        ),
                                      )
                                    }
                                  >
                                    {t("users.reset_mfa", "Reset 2-step")}
                                  </button>
                                )}
                                {can("sessions.manage") && u.is_active && (
                                  <button className="btn btn-sm" onClick={() => run(u, "revoke-sessions")}>
                                    {t("users.end_sessions")}
                                  </button>
                                )}
                                {u.is_active ? (
                                  <button
                                    className="btn btn-sm btn-danger"
                                    onClick={() =>
                                      run(u, "deactivate", t("users.confirm_deactivate", { name: u.full_name }))
                                    }
                                  >
                                    {t("users.deactivate")}
                                  </button>
                                ) : (
                                  <button className="btn btn-sm" onClick={() => run(u, "activate")}>
                                    {t("users.activate")}
                                  </button>
                                )}
                              </>
                            )}
                          </div>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {users.data && <Pager page={page} count={users.data.count} pageSize={25} onPage={setPage} />}
      </Panel>
      <Modal
        open={editing !== null}
        title={editing === "new" ? t("users.new") : t("users.edit")}
        onClose={() => setEditing(null)}
      >
        {editing !== null && (
          <UserForm
            user={editing === "new" ? null : editing}
            roles={roles.data ?? []}
            departments={depts.data ?? []}
            staffOnly={staffOnly}
            isSelf={editing !== "new" && editing.id === me?.id}
            onCancelEdit={() => setEditing(null)}
            onDone={(r) => {
              setEditing(null);
              void qc.invalidateQueries({ queryKey: ["users"] });
              if (r.temporary_password) setSecret({ username: r.username, password: r.temporary_password });
            }}
          />
        )}
      </Modal>
      <Modal
        open={secret !== null}
        title={t("users.temp_password_title", { username: secret?.username ?? "" })}
        onClose={() => setSecret(null)}
      >
        <div className="stack-sm">
          <p>{t("users.temp_password_body")}</p>
          <p className="receipt mono" style={{ fontSize: "1.6rem", textAlign: "center", letterSpacing: "0.08em" }}>
            {secret?.password}
          </p>
          <div className="form-actions">
            <button className="btn btn-primary" onClick={() => setSecret(null)}>
              {t("common.close")}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

/** One person doing several jobs, common in small clinics. Picking a preset sets exactly these roles. */
const ROLE_PRESETS: { key: string; label: string; codes: string[] }[] = [
  { key: "doctor_lab", label: "Doctor + Laboratory technician", codes: ["doctor", "lab_technician"] },
  {
    key: "doctor_lab_pharm",
    label: "Doctor + Laboratory + Pharmacist",
    codes: ["doctor", "lab_technician", "pharmacist"],
  },
  { key: "reception_cash", label: "Receptionist + Cashier", codes: ["receptionist", "cashier"] },
  {
    key: "reception_cash_pharm",
    label: "Receptionist + Cashier + Pharmacist",
    codes: ["receptionist", "cashier", "pharmacist"],
  },
  { key: "nurse_lab", label: "Nurse + Laboratory technician", codes: ["nurse", "lab_technician"] },
];

function UserForm({
  user,
  roles,
  departments,
  staffOnly,
  isSelf,
  onDone,
  onCancelEdit,
}: {
  user: User | null;
  roles: Role[];
  departments: Department[];
  staffOnly: boolean;
  isSelf: boolean;
  onDone: (r: UserWithTemp) => void;
  onCancelEdit?: () => void;
}) {
  const { t } = useTranslation();
  const [f, setF] = useState({
    username: user?.username ?? "",
    first_name: user?.first_name ?? "",
    last_name: user?.last_name ?? "",
    email: user?.email ?? "",
    phone: user?.phone ?? "",
    job_title: user?.job_title ?? "",
    registration_number: user?.registration_number ?? "",
    department_id: user?.department?.id ?? "",
    start_date: user?.start_date ?? "",
  });
  const [roleIds, setRoleIds] = useState<string[]>(user?.roles.map((r) => r.id) ?? []);
  const save = useMutation({
    mutationFn: () => {
      const { username, ...rest } = f;
      const editable = { ...rest, department_id: rest.department_id || null, start_date: rest.start_date || null };
      return user
        ? api.patch<UserWithTemp>(`/users/${user.id}/`, isSelf ? editable : { ...editable, role_ids: roleIds }, {
            ifMatch: user.row_version,
          })
        : api.post<UserWithTemp>("/users/", { ...editable, username, role_ids: roleIds });
    },
    onSuccess: (r) => {
      toast(user ? t("users.saved_toast", "Account updated") : t("users.created_toast", "Account created"));
      onDone(r);
    },
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setF({ ...f, [k]: e.target.value });
  const err = save.error;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <form onSubmit={submit} noValidate className="stack-sm">
      <ErrorBanner error={err} onReload={onCancelEdit} />
      <div className="form-grid">
        <Field label={t("users.username")} id="u-username" error={fieldErrors(err, "username")}>
          <input
            id="u-username"
            value={f.username}
            onChange={set("username")}
            disabled={!!user}
            autoCapitalize="none"
          />
        </Field>
        <Field label={t("users.job_title")} id="u-job">
          <input
            id="u-job"
            value={f.job_title}
            onChange={set("job_title")}
            placeholder={t("users.job_title_ph", "e.g. General Practitioner, Clinical Nurse, Pharmacist")}
          />
        </Field>
        <Field
          label={t("users.registration_number", "Professional registration number")}
          id="u-reg"
          hint={t(
            "users.reg_hint",
            "Licence number for clinicians. Printed on prescriptions, referrals and certificates.",
          )}
        >
          <input id="u-reg" value={f.registration_number} onChange={set("registration_number")} />
        </Field>
        <Field label={t("users.first_name")} id="u-first" error={fieldErrors(err, "first_name")}>
          <input id="u-first" value={f.first_name} onChange={set("first_name")} />
        </Field>
        <Field label={t("users.last_name")} id="u-last" error={fieldErrors(err, "last_name")}>
          <input id="u-last" value={f.last_name} onChange={set("last_name")} />
        </Field>
        <Field label={t("users.phone")} id="u-phone" error={fieldErrors(err, "phone")}>
          <input id="u-phone" type="tel" value={f.phone} onChange={set("phone")} />
        </Field>
        <Field label={t("users.email")} id="u-email" error={fieldErrors(err, "email")}>
          <input id="u-email" type="email" value={f.email} onChange={set("email")} />
        </Field>
        <Field label={t("users.department", "Department")} id="u-dept" error={fieldErrors(err, "department_id")}>
          <select id="u-dept" value={f.department_id} onChange={set("department_id")}>
            <option value="">{t("users.no_department", "Not assigned")}</option>
            {departments
              .filter((d) => d.is_active || d.id === f.department_id)
              .map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label={t("users.start_date", "Start date")} id="u-start" error={fieldErrors(err, "start_date")}>
          <input id="u-start" type="date" value={f.start_date} onChange={set("start_date")} />
        </Field>
      </div>
      {!isSelf && (
        <fieldset className="fieldset">
          <legend>{t("users.roles")}</legend>
          <div className="row preset-row" style={{ gap: 6, marginBottom: 6 }}>
            <span className="small muted">{t("users.presets", "Small-clinic combinations")}:</span>
            {ROLE_PRESETS.map((preset) => {
              const ids = preset.codes.map((c) => roles.find((r) => r.code === c)?.id).filter((x): x is string => !!x);
              if (ids.length !== preset.codes.length) return null;
              const active = ids.length === roleIds.length && ids.every((id) => roleIds.includes(id));
              return (
                <button
                  key={preset.key}
                  type="button"
                  className={`btn btn-sm${active ? " btn-primary" : ""}`}
                  aria-pressed={active}
                  onClick={() => setRoleIds(ids)}
                >
                  {t(`users.preset_${preset.key}`, preset.label)}
                </button>
              );
            })}
          </div>
          {roles.map((r) => {
            const locked = staffOnly && r.privileged;
            return (
              <label key={r.id} className={`check${locked ? " muted" : ""}`}>
                <input
                  type="checkbox"
                  checked={roleIds.includes(r.id)}
                  disabled={locked}
                  onChange={() =>
                    setRoleIds((ids) => (ids.includes(r.id) ? ids.filter((x) => x !== r.id) : [...ids, r.id]))
                  }
                />
                <span>
                  <strong>{r.name}</strong>{" "}
                  <span className="small muted">
                    {locked
                      ? t("users.role_sysadmin_only", "Only the system administrator can give this role.")
                      : r.description}
                  </span>
                </span>
              </label>
            );
          })}
          {fieldErrors(err, "role_ids").map((m) => (
            <span key={m} className="error small">
              {m}
            </span>
          ))}
        </fieldset>
      )}
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending || roleIds.length === 0}>
          {save.isPending ? t("common.saving") : t("common.save")}
        </button>
      </div>
    </form>
  );
}
