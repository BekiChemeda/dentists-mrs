/** Audit log viewer. */
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { queryString } from "../api/client";
import { useGet } from "../api/hooks";
import type { AuditEvent, Paginated } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime, isoDateDaysAgo } from "../lib/format";
import { Badge, Empty, ErrorBanner, Field, Loading, PageHead, Pager, Panel, type BadgeTone } from "../ui";

const OUTCOME_TONE: Record<string, BadgeTone> = { success: "ok", failure: "wait", denied: "danger" };

export function AuditPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const operationalOnly = !can("audit.view");
  const initial = { action: "", outcome: "", date_from: isoDateDaysAgo(7), date_to: "" };
  const [draft, setDraft] = useState(initial);
  const [filters, setFilters] = useState(initial);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const events = useGet<Paginated<AuditEvent>>(
    ["audit", filters, page],
    `/audit-events/${queryString({ ...filters, page, page_size: 50 })}`,
  );
  const set = (k: keyof typeof initial) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setDraft({ ...draft, [k]: e.target.value });
  return (
    <div className="stack">
      <PageHead
        title={t("audit.title")}
        sub={
          operationalOnly
            ? t(
                "audit.sub_operational",
                "Clinic work: records viewed and changed, payments, dispensing, settings. Sign-ins and security events are kept for the system administrator.",
              )
            : t("audit.sub", "Every sign-in, record view and change. Entries cannot be edited or deleted.")
        }
      />
      <form
        className="filters"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setFilters(draft);
        }}
      >
        <Field label={t("audit.action_prefix")} id="af-a">
          <input id="af-a" value={draft.action} onChange={set("action")} placeholder="patient." />
        </Field>
        <Field label={t("audit.outcome")} id="af-o">
          <select id="af-o" value={draft.outcome} onChange={set("outcome")}>
            <option value="">{t("common.all")}</option>
            <option value="success">{t("audit.outcome_success")}</option>
            <option value="failure">{t("audit.outcome_failure")}</option>
            <option value="denied">{t("audit.outcome_denied")}</option>
          </select>
        </Field>
        <Field label={t("audit.date_from")} id="af-f">
          <input id="af-f" type="date" value={draft.date_from} onChange={set("date_from")} />
        </Field>
        <Field label={t("audit.date_to")} id="af-t">
          <input id="af-t" type="date" value={draft.date_to} onChange={set("date_to")} />
        </Field>
        <button className="btn" type="submit">
          {t("common.search")}
        </button>
      </form>
      <ErrorBanner error={events.error} />
      <Panel flush>
        {events.isLoading ? (
          <Loading />
        ) : !events.data?.results.length ? (
          <Empty>{t("audit.empty")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("audit.when")}</th>
                  <th>{t("audit.who")}</th>
                  <th>{t("audit.action")}</th>
                  <th>{t("audit.object")}</th>
                  <th>{t("audit.outcome")}</th>
                  <th>{t("audit.from")}</th>
                </tr>
              </thead>
              <tbody>
                {events.data.results.map((e) => (
                  <Fragment key={e.id}>
                    <tr>
                      <td className="nowrap">{formatDateTime(e.occurred_at)}</td>
                      <td>{e.actor_username || t("audit.system")}</td>
                      <td>
                        {Object.keys(e.details).length ? (
                          <button
                            className="link-btn mono"
                            onClick={() => setOpen(open === e.id ? null : e.id)}
                            aria-expanded={open === e.id}
                          >
                            {e.action}
                          </button>
                        ) : (
                          <span className="mono">{e.action}</span>
                        )}
                      </td>
                      <td className="small">{e.object_type ? `${e.object_type} ${e.object_id.slice(0, 8)}` : "—"}</td>
                      <td>
                        <Badge tone={OUTCOME_TONE[e.outcome]}>{t(`audit.outcome_${e.outcome}`)}</Badge>
                      </td>
                      <td className="small">{e.ip_address ?? "—"}</td>
                    </tr>
                    {open === e.id && (
                      <tr>
                        <td colSpan={6}>
                          <pre className="small" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                            {JSON.stringify(e.details, null, 2)}
                          </pre>
                          <span className="small subtle">request {e.request_id}</span>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {events.data && <Pager page={page} count={events.data.count} pageSize={50} onPage={setPage} />}
      </Panel>
    </div>
  );
}
