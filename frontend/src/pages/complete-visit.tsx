/** Closing a visit: what is still open and how the visit ended. */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Outstanding, Visit, VisitOutcome } from "../api/types";
import { Banner, ErrorBanner, Field, Loading, Modal } from "../ui";

const OUTCOMES: { key: VisitOutcome; label: string; hint: string }[] = [
  { key: "completed", label: "Care completed", hint: "Everything planned for today is done." },
  { key: "follow_up", label: "Completed, follow-up booked", hint: "The patient will come back on a booked date." },
  { key: "referred", label: "Referred elsewhere", hint: "Say where the patient was referred." },
  { key: "left_early", label: "Left before completion", hint: "Say what was not done." },
];

/** Close a visit after the consultation. Shows what is still open and asks why when closing anyway. */
export function CompleteVisitDialog({ visit, onClose }: { visit: Visit | null; onClose: () => void }) {
  const { t } = useTranslation();
  const [outcome, setOutcome] = useState<VisitOutcome>("completed");
  const [note, setNote] = useState("");
  const [ack, setAck] = useState(false);
  const pending = useGet<Outstanding>(
    ["visits", visit?.id, "outstanding"],
    visit ? `/visits/${visit.id}/outstanding/` : null,
  );
  const done = useAction(
    () => api.post<Visit>(`/visits/${visit!.id}/complete/`, { outcome, note, acknowledge_outstanding: ack }),
    [["visits"], ["patients"]],
    () => {
      onClose();
      setNote("");
      setAck(false);
      setOutcome("completed");
    },
    t("visit.completed_toast", "Visit completed"),
  );
  const o = pending.data;
  const groups: [string, string[]][] = o
    ? [
        [t("visit.out_notes", "Unsigned notes"), o.draft_notes],
        [t("visit.out_lab", "Laboratory not finished"), o.lab_pending],
        [t("visit.out_rx", "Medicines not dispensed"), o.medicines_pending],
        [t("visit.out_unbilled", "Not yet invoiced"), o.unbilled],
        [t("visit.out_invoices", "Invoices"), o.open_invoices],
      ]
    : [];
  const needsNote = outcome === "referred" || outcome === "left_early" || !!o?.any;
  return (
    <Modal open={visit !== null} title={t("visit.complete_title", "Complete visit")} onClose={onClose}>
      {visit && (
        <form
          className="stack-sm"
          onSubmit={(e) => {
            e.preventDefault();
            done.mutate(undefined);
          }}
        >
          <p>
            <strong>{visit.patient.full_name}</strong>{" "}
            <span className="muted">
              {visit.visit_date}, {t("queue.ticket_n", "Ticket {{n}}", { n: visit.queue_number })}
            </span>
          </p>
          {pending.isLoading ? (
            <Loading />
          ) : (
            o &&
            (o.any ? (
              <Banner tone={o.blocking ? "error" : "warn"}>
                <strong>
                  {o.blocking
                    ? t("visit.blocking", "An unsigned note must be signed before the visit can close.")
                    : t("visit.open_items", "Still open for this visit:")}
                </strong>
                <ul className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {groups
                    .filter(([, items]) => items.length)
                    .map(([label, items]) => (
                      <li key={label}>
                        {label}: {items.join("; ")}
                      </li>
                    ))}
                  {Number(o.balance_due) > 0 && (
                    <li>{t("visit.out_balance", "Unpaid balance: {{b}} ETB", { b: o.balance_due })}</li>
                  )}
                </ul>
              </Banner>
            ) : (
              <Banner tone="ok">{t("visit.nothing_open", "Nothing is outstanding. The visit can be closed.")}</Banner>
            ))
          )}
          <ErrorBanner error={done.error} />
          <fieldset className="fieldset">
            <legend>{t("visit.outcome", "How did the visit end?")}</legend>
            {OUTCOMES.map((x) => (
              <label key={x.key} className="check">
                <input type="radio" name="outcome" checked={outcome === x.key} onChange={() => setOutcome(x.key)} />
                <span>
                  <strong>{t(`state.outcome.${x.key}`, x.label)}</strong>
                  <br />
                  <span className="small muted">{t(`visit.hint_${x.key}`, x.hint)}</span>
                </span>
              </label>
            ))}
          </fieldset>
          <Field
            label={needsNote ? t("visit.note_required", "Note (required)") : t("visit.note", "Note (optional)")}
            id="cv-note"
          >
            <textarea
              id="cv-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              placeholder={
                outcome === "referred" ? t("visit.note_ph_ref", "e.g. Referred to Adama Hospital surgical OPD") : ""
              }
            />
          </Field>
          {o?.any && !o.blocking && (
            <label className="check">
              <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span>
                {t(
                  "visit.ack",
                  "I understand these services are still open. Unpaid balances stay on the invoice; undispensed medicines are marked not collected.",
                )}
              </span>
            </label>
          )}
          <div className="form-actions">
            <button type="button" className="btn" onClick={onClose}>
              {t("common.cancel")}
            </button>
            <button
              className="btn btn-primary"
              disabled={done.isPending || !!o?.blocking || (o?.any && !ack) || (needsNote && !note.trim())}
            >
              {t("visit.complete", "Complete visit")}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
