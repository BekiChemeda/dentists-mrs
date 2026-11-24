import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Approval, Paginated } from "../api/types";
import { StateBadge } from "../labels";
import { formatDateTime } from "../lib/format";
import { Empty, ErrorBanner, Loading, PageHead, Panel, ReasonDialog, Segmented, money, qty } from "../ui";

export function ApprovalsPage() {
  const { t } = useTranslation();
  const [view, setView] = useState<"pending" | "history">("pending");
  const q = useGet<Paginated<Approval>>(
    ["approvals", "page", view],
    `/approvals/?status=${view === "pending" ? "pending,approved" : "rejected,used,cancelled"}&page_size=100`,
  );
  const [rejecting, setRejecting] = useState<Approval | null>(null);
  const act = useAction(
    (v: { id: string; action: string; note?: string }) =>
      api.post(`/approvals/${v.id}/${v.action}/`, { note: v.note ?? "" }),
    [["approvals"], ["invoice"], ["prescriptions"]],
    () => setRejecting(null),
  );

  return (
    <div className="stack">
      <PageHead
        title={t("nav.approvals")}
        sub={t(
          "approvals.sub",
          "Discounts, invoice voids and dispensing beyond recorded stock need a second person. You cannot approve your own request.",
        )}
        actions={
          <Segmented
            label="View"
            value={view}
            onChange={setView}
            options={[
              { key: "pending", label: t("approvals.open", "Open") },
              { key: "history", label: t("approvals.history", "History") },
            ]}
          />
        }
      />
      <ErrorBanner error={act.error} />
      <Panel flush>
        {q.isLoading ? (
          <Loading />
        ) : !q.data?.results.length ? (
          <Empty>{t("approvals.none", "Nothing waiting.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("approvals.request", "Request")}</th>
                  <th>{t("approvals.requested_by", "Requested by")}</th>
                  <th>{t("common.reason", "Reason")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {q.data.results.map((a) => (
                  <tr key={a.id}>
                    <td>
                      <strong>{a.kind_label}</strong>
                      <div>{a.summary}</div>
                      {a.amount && <div className="small muted">{money(a.amount)} ETB</div>}
                      {a.quantity && <div className="small muted">{qty(a.quantity)}</div>}
                      {a.problem && <div className="banner banner-warn small">{a.problem}</div>}
                      {a.object_type === "invoice" && (
                        <Link className="small" to={`/billing/invoices/${a.object_id}`}>
                          {t("approvals.open_invoice", "Open invoice")}
                        </Link>
                      )}
                    </td>
                    <td>
                      {a.requested_by.full_name}
                      <div className="small subtle">{formatDateTime(a.created_at)}</div>
                    </td>
                    <td>
                      {a.reason}
                      {a.decision_note && (
                        <div className="small muted">
                          {a.decided_by?.full_name}: {a.decision_note}
                        </div>
                      )}
                    </td>
                    <td>
                      <StateBadge set="approval" value={a.status} />
                    </td>
                    <td className="num">
                      {a.can_decide && (
                        <div className="row" style={{ justifyContent: "flex-end" }}>
                          {!a.problem && (
                            <button
                              className="btn btn-sm btn-primary"
                              disabled={act.isPending}
                              onClick={() => act.mutate({ id: a.id, action: "approve" })}
                            >
                              {t("approvals.approve", "Approve")}
                            </button>
                          )}
                          <button className="btn btn-sm btn-danger" onClick={() => setRejecting(a)}>
                            {t("approvals.reject", "Reject")}
                          </button>
                        </div>
                      )}
                      {a.status === "approved" && a.problem && (
                        <button
                          className="btn btn-sm"
                          disabled={act.isPending}
                          onClick={() => act.mutate({ id: a.id, action: "withdraw" })}
                        >
                          {t("approvals.close_stale", "Close without applying")}
                        </button>
                      )}
                      {!a.can_decide && a.status === "pending" && (
                        <span className="small subtle">{t("approvals.waiting_other", "Waiting for an approver")}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <ReasonDialog
        open={rejecting !== null}
        title={t("approvals.reject", "Reject")}
        label={t("approvals.reject_reason", "Reason for rejecting")}
        confirmLabel={t("approvals.reject", "Reject")}
        danger
        busy={act.isPending}
        error={act.error}
        onClose={() => setRejecting(null)}
        onConfirm={(note) => rejecting && act.mutate({ id: rejecting.id, action: "reject", note })}
      />
    </div>
  );
}
