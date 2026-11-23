import { useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CheckCheck, FlaskConical, Printer, TestTube2 } from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { LabItem, LabOrder, Paginated } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { FLAG_LABEL, StateBadge, isCriticalFlag } from "../labels";
import { formatDateTime } from "../lib/format";
import {
  Badge,
  Banner,
  Empty,
  ErrorBanner,
  Field,
  Loading,
  Menu,
  Modal,
  PageHead,
  Pager,
  Panel,
  ReasonDialog,
  Segmented,
  printElement,
  qty,
} from "../ui";
import { ClinicHeader, Ec, sexAge, DocFooter } from "./common";

type View = "worklist" | "completed";

export function LaboratoryPage() {
  const { t } = useTranslation();
  const [view, setView] = useState<View>("worklist");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const status = view === "worklist" ? "ordered,in_progress" : "completed,cancelled";
  const list = useGet<Paginated<LabOrder>>(
    ["lab", "orders", view, q, page],
    `/lab/orders/${queryString({ status, q, page, worklist: view === "worklist" ? "1" : "", page_size: 20 })}`,
    { refetchInterval: view === "worklist" ? 20_000 : undefined },
  );

  return (
    <div className="stack">
      <PageHead
        title={t("nav.laboratory")}
        sub={t(
          "lab.sub",
          "Collect specimens, enter results and verify them. Doctors see results only after verification.",
        )}
        actions={
          <Segmented
            label={t("lab.view", "View")}
            value={view}
            onChange={(v) => {
              setView(v);
              setPage(1);
            }}
            options={[
              { key: "worklist", label: t("lab.worklist", "Worklist") },
              { key: "completed", label: t("lab.completed", "Completed") },
            ]}
          />
        }
      />
      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <div className="field">
          <label htmlFor="lq">{t("lab.find", "Accession number, MRN or name")}</label>
          <input
            id="lq"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </div>
      </form>
      {list.isLoading ? (
        <Loading />
      ) : !list.data?.results.length ? (
        <Empty icon={<FlaskConical size={28} />}>
          {view === "worklist"
            ? t("lab.nothing", "No pending tests.")
            : t("lab.none_completed", "No completed orders match.")}
        </Empty>
      ) : (
        list.data.results.map((o) => <OrderCard key={o.id} order={o} />)
      )}
      {list.data && <Pager page={page} count={list.data.count} pageSize={20} onPage={setPage} />}
    </div>
  );
}

function OrderCard({ order: o }: { order: LabOrder }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [resultFor, setResultFor] = useState<{ item: LabItem; amend: boolean } | null>(null);
  const [cancelling, setCancelling] = useState<LabItem | null>(null);
  const [repeating, setRepeating] = useState<LabItem | null>(null);
  const [verifyingCritical, setVerifyingCritical] = useState<LabItem | null>(null);
  const [printing, setPrinting] = useState(false);
  const act = useAction(
    (v: { id: string; action: string; body?: object }) => api.post(`/lab/items/${v.id}/${v.action}/`, v.body ?? {}),
    [["lab"]],
    () => {
      setCancelling(null);
      setRepeating(null);
      setVerifyingCritical(null);
    },
    false,
  );
  const toCollect = o.items.filter((i) => i.status === "ordered");
  // Critical results are verified one at a time, with the clinician who was told.
  const toVerify = o.items.filter((i) => i.status === "resulted" && !isCriticalFlag(i.flag));
  const verify = (i: LabItem) =>
    isCriticalFlag(i.flag) ? setVerifyingCritical(i) : act.mutate({ id: i.id, action: "verify" });

  return (
    <Panel
      flush
      title={
        <div>
          <div className="row">
            <h2 className="mono">{o.accession_number}</h2>
            {o.priority === "urgent" && <Badge tone="danger">Urgent</Badge>}
            <StateBadge set="labOrder" value={o.status} />
          </div>
          <div className="small muted">
            <Link to={`/patients/${o.patient.id}?tab=labs`}>
              <strong>{o.patient.full_name}</strong>
            </Link>
            , {sexAge(o.patient, t)}, <span className="mono">{o.patient.mrn}</span>, {requesterOf(o)},{" "}
            {formatDateTime(o.created_at)}
          </div>
          {o.clinical_notes && (
            <div className="small">
              {t("lab.notes", "Clinical notes")}: {o.clinical_notes}
            </div>
          )}
        </div>
      }
      actions={
        <>
          {o.items.some((i) => i.status === "verified") && (
            <button className="btn btn-sm" onClick={() => setPrinting(true)}>
              <Printer size={15} aria-hidden /> {t("lab.report", "Result report")}
            </button>
          )}
          {can("lab.result.enter") && toCollect.length > 1 && (
            <button
              className="btn btn-sm"
              disabled={act.isPending}
              onClick={() => toCollect.forEach((i) => act.mutate({ id: i.id, action: "collect" }))}
            >
              <TestTube2 size={15} aria-hidden /> {t("lab.collect_all", "Collect all")}
            </button>
          )}
          {can("lab.result.verify") && toVerify.length > 1 && (
            <button
              className="btn btn-sm btn-primary"
              disabled={act.isPending}
              onClick={() => toVerify.forEach((i) => act.mutate({ id: i.id, action: "verify" }))}
            >
              <CheckCheck size={15} aria-hidden /> {t("lab.verify_all", "Verify all")}
            </button>
          )}
        </>
      }
    >
      <ErrorBanner error={act.error} />
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>{t("lab.test", "Test")}</th>
              <th>{t("lab.specimen", "Specimen")}</th>
              <th>{t("lab.result", "Result")}</th>
              <th>{t("lab.reference", "Reference")}</th>
              <th>{t("common.status", "Status")}</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {o.items.map((i) => (
              <tr key={i.id} className={i.status === "cancelled" ? "muted" : ""}>
                <td>
                  <strong>{i.test.name}</strong>
                  <div className="small subtle">{i.specimen_type || i.test.specimen_type}</div>
                  {i.repeat_of && (
                    <div className="small">
                      <span className="badge badge-info">{t("lab.repeat", "Repeat")}</span> {i.repeat_reason}
                      {!i.is_chargeable && `, ${t("lab.not_charged", "not charged")}`}
                    </div>
                  )}
                </td>
                <td className="mono small">{i.specimen_label || "—"}</td>
                <td>
                  {i.display_result ? (
                    <span className={`flag-${i.flag}`}>
                      {i.display_result} {i.unit}
                      {i.flag && i.flag !== "N" ? ` (${FLAG_LABEL[i.flag]})` : ""}
                    </span>
                  ) : (
                    "—"
                  )}
                  {i.critical_reported_to && (
                    <div className="small">
                      {t("lab.reported_to", "Reported to {{who}}", { who: i.critical_reported_to })}
                      {i.critical_acknowledged_at ? `, ${t("lab.acknowledged", "acknowledged")}` : ""}
                    </div>
                  )}
                  {i.result_comment && <div className="small muted">{i.result_comment}</div>}
                  {i.amendments.length > 0 && (
                    <div className="small subtle">
                      {t("lab.corrected_times", "Corrected {{n}} time(s)", { n: i.amendments.length })}
                    </div>
                  )}
                  {i.entered_by && (
                    <div className="small subtle">
                      {t("lab.entered_by", "Entered by {{who}}", { who: i.entered_by.full_name })}
                      {i.verified_by
                        ? `, ${t("lab.verified_by", "verified by {{who}}", { who: i.verified_by.full_name })}`
                        : ""}
                    </div>
                  )}
                  {i.cancel_reason && <div className="small subtle">{i.cancel_reason}</div>}
                </td>
                <td className="small muted">
                  {i.ref_low !== null || i.ref_high !== null
                    ? `${i.ref_low !== null ? qty(i.ref_low) : ""}–${i.ref_high !== null ? qty(i.ref_high) : ""}`
                    : i.ref_text || i.test.normal_choice || "—"}
                </td>
                <td>
                  <StateBadge set="labItem" value={i.status} />
                </td>
                <td className="num">
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    {i.status === "ordered" && can("lab.result.enter") && (
                      <button
                        className="btn btn-sm btn-primary"
                        onClick={() => act.mutate({ id: i.id, action: "collect" })}
                      >
                        {t("lab.collect", "Collect")}
                      </button>
                    )}
                    {(i.status === "collected" || i.status === "resulted") && can("lab.result.enter") && (
                      <button
                        className={`btn btn-sm${i.status === "collected" ? " btn-primary" : ""}`}
                        onClick={() => setResultFor({ item: i, amend: false })}
                      >
                        {i.status === "collected" ? t("lab.enter", "Enter result") : t("lab.edit", "Edit")}
                      </button>
                    )}
                    {i.status === "resulted" && can("lab.result.verify") && (
                      <button
                        className={`btn btn-sm ${isCriticalFlag(i.flag) ? "btn-danger-solid" : "btn-primary"}`}
                        onClick={() => verify(i)}
                      >
                        {isCriticalFlag(i.flag)
                          ? t("lab.verify_critical", "Verify critical…")
                          : t("lab.verify", "Verify")}
                      </button>
                    )}
                    {i.status === "verified" && can("lab.result.verify") && (
                      <button className="btn btn-sm btn-ghost" onClick={() => setResultFor({ item: i, amend: true })}>
                        {t("lab.correct", "Correct")}
                      </button>
                    )}
                    <Menu
                      label={t("lab.more", "More actions for {{test}}", { test: i.test.name })}
                      items={[
                        {
                          label: t("lab.repeat_action", "Repeat test…"),
                          hidden:
                            !["collected", "resulted", "verified"].includes(i.status) ||
                            !can("lab.result.enter", "lab.request"),
                          onSelect: () => setRepeating(i),
                        },
                        {
                          label: t("lab.cancel_test", "Cancel test…"),
                          danger: true,
                          hidden:
                            ["verified", "cancelled"].includes(i.status) || !can("lab.result.enter", "lab.request"),
                          onSelect: () => setCancelling(i),
                        },
                      ]}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Modal
        open={resultFor !== null}
        title={
          resultFor
            ? `${resultFor.amend ? t("lab.correct_title", "Correct result") : t("lab.enter", "Enter result")}: ${resultFor.item.test.name}`
            : ""
        }
        onClose={() => setResultFor(null)}
      >
        {resultFor && <ResultForm item={resultFor.item} amend={resultFor.amend} onDone={() => setResultFor(null)} />}
      </Modal>
      <Modal open={printing} wide title={t("lab.report", "Result report")} onClose={() => setPrinting(false)}>
        {printing && <LabReport order={o} />}
      </Modal>
      <ReasonDialog
        open={repeating !== null}
        title={t("lab.repeat_title", "Repeat test")}
        label={t(
          "lab.repeat_reason",
          "Why is the test repeated? (e.g. haemolysed or clotted specimen, result questioned)",
        )}
        confirmLabel={t("lab.repeat_confirm", "Request repeat")}
        busy={act.isPending}
        error={act.error}
        onClose={() => setRepeating(null)}
        onConfirm={(reason) => repeating && act.mutate({ id: repeating.id, action: "repeat", body: { reason } })}
      />
      <ReasonDialog
        open={verifyingCritical !== null}
        title={t("lab.critical_title", "Verify critical result")}
        label={t(
          "lab.critical_label",
          "Critical result: inform the requesting clinician directly now, in person or by phone. Who did you inform, and how?",
        )}
        confirmLabel={t("lab.critical_confirm", "Verify and record")}
        danger
        busy={act.isPending}
        error={act.error}
        onClose={() => setVerifyingCritical(null)}
        onConfirm={(who) =>
          verifyingCritical &&
          act.mutate({ id: verifyingCritical.id, action: "verify", body: { critical_reported_to: who } })
        }
      />
      <ReasonDialog
        open={cancelling !== null}
        title={t("lab.cancel_test", "Cancel test")}
        label={t("lab.cancel_reason", "Reason (e.g. specimen haemolysed, patient left)")}
        confirmLabel={t("lab.cancel_test", "Cancel test")}
        danger
        busy={act.isPending}
        error={act.error}
        onClose={() => setCancelling(null)}
        onConfirm={(reason) => cancelling && act.mutate({ id: cancelling.id, action: "cancel", body: { reason } })}
      />
    </Panel>
  );
}

/** Who asked for the tests: the doctor here, or the outside clinician on a laboratory-only visit. */
export function requesterOf(o: LabOrder): string {
  if (o.external_requester)
    return `${o.external_requester}${o.external_facility ? `, ${o.external_facility}` : ""} (outside request)`;
  return `Dr. ${o.ordered_by.full_name}`;
}

/** Printable report of verified results only; unverified results never leave the laboratory. */
export function LabReport({ order: o }: { order: LabOrder }) {
  const { t } = useTranslation();
  const done = o.items.filter((i) => i.status === "verified");
  const pending = o.items.filter((i) => !["verified", "cancelled"].includes(i.status));
  const verifiers = [...new Set(done.map((i) => i.verified_by?.full_name).filter(Boolean))];
  return (
    <div className="stack-sm">
      <article className="doc" id="lab-report">
        <ClinicHeader title={t("lab.report", "Laboratory result report")} number={o.accession_number} />
        <dl className="facts">
          <dt>{t("patients.patient", "Patient")}</dt>
          <dd>
            <strong>{o.patient.full_name}</strong>, {sexAge(o.patient, t)}, MRN{" "}
            <span className="mono">{o.patient.mrn}</span>
          </dd>
          <dt>{t("lab.requested_by", "Requested by")}</dt>
          <dd>{requesterOf(o)}</dd>
          <dt>{t("lab.requested_at", "Requested")}</dt>
          <dd>
            {formatDateTime(o.created_at)}
            <Ec value={o.created_at} />
          </dd>
        </dl>
        <table className="data">
          <thead>
            <tr>
              <th>{t("lab.test", "Test")}</th>
              <th>{t("lab.result", "Result")}</th>
              <th>{t("lab.reference", "Reference")}</th>
              <th>{t("lab.flag", "Flag")}</th>
              <th>{t("lab.verified", "Verified")}</th>
            </tr>
          </thead>
          <tbody>
            {done.map((i) => (
              <tr key={i.id}>
                <td>
                  {i.test.name}
                  <div className="small subtle">{i.specimen_type || i.test.specimen_type}</div>
                </td>
                <td>
                  <strong>
                    {i.display_result} {i.unit}
                  </strong>
                  {i.result_comment && <div className="small">{i.result_comment}</div>}
                </td>
                <td className="small">
                  {i.ref_low !== null || i.ref_high !== null
                    ? `${i.ref_low !== null ? qty(i.ref_low) : ""}–${i.ref_high !== null ? qty(i.ref_high) : ""} ${i.unit}`
                    : i.ref_text || i.test.normal_choice || "—"}
                </td>
                <td>{i.flag && i.flag !== "N" ? FLAG_LABEL[i.flag] : t("lab.normal", "Normal")}</td>
                <td className="small">{formatDateTime(i.verified_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {pending.length > 0 && (
          <p className="small">
            {t("lab.report_pending", "Still in progress, not on this report")}:{" "}
            {pending.map((i) => i.test.name).join(", ")}
          </p>
        )}
        <div className="doc-sign">
          <div>
            {t("lab.verified_by_n", "Verified by")} {verifiers.join(", ") || "—"}
          </div>
          <div className="doc-sign-line">{t("consult.signature_stamp", "Signature and stamp")}</div>
        </div>
        <DocFooter kind="note_lab_report" />
      </article>
      <div className="form-actions">
        <button className="btn btn-primary" onClick={() => printElement("lab-report", o.accession_number)}>
          <Printer size={16} aria-hidden /> {t("common.print", "Print")}
        </button>
      </div>
    </div>
  );
}

function ResultForm({ item, amend, onDone }: { item: LabItem; amend: boolean; onDone: () => void }) {
  const { t } = useTranslation();
  const [value, setValue] = useState(item.display_result);
  const [comment, setComment] = useState(item.result_comment);
  const [reason, setReason] = useState("");
  const save = useAction(
    () =>
      api.post(`/lab/items/${item.id}/${amend ? "amend" : "result"}/`, {
        value,
        comment,
        reason,
        critical_reported_to: reportedTo,
      }),
    [["lab"]],
    onDone,
    amend ? t("lab.corrected_toast", "Result corrected") : t("lab.saved_toast", "Result saved"),
  );
  const numeric = Number(value.replace(",", "."));
  const looksCritical =
    item.test.result_type === "numeric" &&
    value.trim() !== "" &&
    !Number.isNaN(numeric) &&
    ((item.critical_low !== null && numeric <= Number(item.critical_low)) ||
      (item.critical_high !== null && numeric >= Number(item.critical_high)));
  const choices = item.test.answers ?? [];
  const [reportedTo, setReportedTo] = useState("");
  const range =
    item.ref_low !== null || item.ref_high !== null
      ? `${item.ref_low !== null ? qty(item.ref_low) : ""}–${item.ref_high !== null ? qty(item.ref_high) : ""} ${item.unit}`
      : item.ref_text;
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      <Field
        label={`${t("lab.result", "Result")}${item.unit ? ` (${item.unit})` : ""}`}
        id="r-v"
        hint={range ? `${t("lab.reference", "Reference")}: ${range}` : undefined}
      >
        {item.test.result_type === "choice" || item.test.result_type === "qualitative" ? (
          <select id="r-v" value={value} onChange={(e) => setValue(e.target.value)} autoFocus>
            <option value="">{t("common.choose", "Choose…")}</option>
            {choices.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        ) : item.test.result_type === "numeric" ? (
          <input id="r-v" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
        ) : (
          <textarea id="r-v" value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
        )}
      </Field>
      <Field label={t("lab.comment", "Comment (optional)")} id="r-c">
        <input id="r-c" value={comment} onChange={(e) => setComment(e.target.value)} />
      </Field>
      {looksCritical && (
        <Banner tone="error">
          {t(
            "lab.critical_warn",
            "This value is in the critical range. After saving, verify it and inform the requesting clinician immediately.",
          )}
        </Banner>
      )}
      {amend && (
        <Field label={t("lab.amend_reason", "Reason for correction")} id="r-r">
          <input id="r-r" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      )}
      {amend && looksCritical && (
        <Field label={t("lab.reported_to_label", "Clinician informed (name and how)")} id="r-rt" error={save.error}>
          <input id="r-rt" value={reportedTo} onChange={(e) => setReportedTo(e.target.value)} />
        </Field>
      )}
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!value.trim() || (amend && !reason.trim()) || save.isPending}>
          {amend ? t("lab.save_correction", "Save correction") : t("lab.save_result", "Save result")}
        </button>
      </div>
    </form>
  );
}
