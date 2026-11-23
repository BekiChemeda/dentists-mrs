import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CalendarPlus, ChevronLeft, ChevronRight } from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Appointment, Paginated, PatientBrief } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { StateBadge } from "../labels";
import { formatLongDate } from "../lib/format";
import { Empty, ErrorBanner, Field, Loading, Menu, Modal, PageHead, Panel, ReasonDialog } from "../ui";
import { DoctorSelect, Ec, PatientLine, PatientPicker, timeOf, todayIso } from "./common";

function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function AppointmentsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [params] = useSearchParams();
  // A reminder can link straight to a day: /appointments?date=YYYY-MM-DD
  const [day, setDay] = useState(
    /^\d{4}-\d{2}-\d{2}$/.test(params.get("date") ?? "") ? params.get("date")! : todayIso(),
  );
  const [doctor, setDoctor] = useState("");
  const [booking, setBooking] = useState(false);
  const [cancelling, setCancelling] = useState<Appointment | null>(null);
  const [moving, setMoving] = useState<Appointment | null>(null);
  const list = useGet<Paginated<Appointment>>(
    ["appointments", day, doctor],
    `/appointments/${queryString({ date: day, doctor, page_size: 100 })}`,
  );
  const act = useAction(
    (v: { id: string; action: string; reason?: string }) =>
      api.post(`/appointments/${v.id}/${v.action}/`, { reason: v.reason ?? "" }),
    [["appointments"], ["visits"]],
    () => setCancelling(null),
  );
  const past = (a: Appointment) => new Date(a.scheduled_at).getTime() < Date.now();
  const isToday = day === todayIso();

  return (
    <div className="stack">
      <PageHead
        title={t("nav.appointments")}
        sub={
          <>
            {formatLongDate(new Date(`${day}T12:00:00`))}
            <Ec value={day} />
          </>
        }
        actions={
          can("appointments.manage") && (
            <button className="btn btn-primary" onClick={() => setBooking(true)}>
              <CalendarPlus size={18} aria-hidden /> {t("appointments.book", "Book appointment")}
            </button>
          )
        }
      />
      <div className="filters">
        <div className="row">
          <button
            className="btn btn-icon"
            onClick={() => setDay(shiftDate(day, -1))}
            aria-label={t("common.previous_day", "Previous day")}
          >
            <ChevronLeft size={18} />
          </button>
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value || todayIso())}
            aria-label={t("common.date", "Date")}
          />
          <button
            className="btn btn-icon"
            onClick={() => setDay(shiftDate(day, 1))}
            aria-label={t("common.next_day", "Next day")}
          >
            <ChevronRight size={18} />
          </button>
          {!isToday && (
            <button className="btn btn-ghost" onClick={() => setDay(todayIso())}>
              {t("common.today", "Today")}
            </button>
          )}
        </div>
        <div className="field">
          <label htmlFor="ap-doc">{t("queue.doctor", "Doctor")}</label>
          <DoctorSelect
            id="ap-doc"
            value={doctor}
            onChange={setDoctor}
            allowNone
            noneLabel={t("appointments.all_doctors", "All doctors")}
          />
        </div>
      </div>
      <ErrorBanner error={act.error} />
      <Panel flush>
        {list.isLoading ? (
          <Loading />
        ) : !list.data?.results.length ? (
          <Empty>{t("appointments.none", "No appointments on this day.")}</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data">
              <thead>
                <tr>
                  <th>{t("common.time", "Time")}</th>
                  <th>{t("patients.patient", "Patient")}</th>
                  <th>{t("queue.doctor", "Doctor")}</th>
                  <th>{t("appointments.reason", "Reason")}</th>
                  <th>{t("common.status", "Status")}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {list.data.results.map((a) => (
                  <tr key={a.id}>
                    <td className="nowrap">
                      <strong>{timeOf(a.scheduled_at)}</strong>
                      <div className="small subtle">{a.duration_minutes} min</div>
                    </td>
                    <td>
                      <PatientLine patient={a.patient} link />
                    </td>
                    <td>Dr. {a.doctor.full_name}</td>
                    <td>
                      {a.service && (
                        <div className="small">
                          <strong>{a.service.name}</strong>
                        </div>
                      )}
                      {a.reason || (a.service ? "" : "—")}
                      {a.notes && <div className="small subtle">{a.notes}</div>}
                      {a.cancel_reason && <div className="small subtle">{a.cancel_reason}</div>}
                      {a.source_encounter && (
                        <div className="small subtle">
                          {t("appointments.follow_up", "Follow-up booked by the doctor")}
                        </div>
                      )}
                    </td>
                    <td>
                      <StateBadge set="appointment" value={a.display_status} />
                      {a.reschedule_count > 0 && (
                        <div className="small subtle">
                          {t("appointments.moved", "Moved {{n}}×", { n: a.reschedule_count })}
                        </div>
                      )}
                    </td>
                    <td className="num">
                      {(a.status === "scheduled" || a.status === "confirmed") && (
                        <div className="row" style={{ justifyContent: "flex-end", gap: 6 }}>
                          {isToday && can("queue.manage") && (
                            <button
                              className="btn btn-sm btn-primary"
                              disabled={act.isPending}
                              onClick={() => act.mutate({ id: a.id, action: "check-in" })}
                            >
                              {t("appointments.check_in", "Mark arrived")}
                            </button>
                          )}
                          {a.status === "scheduled" && can("appointments.manage") && (
                            <button
                              className="btn btn-sm"
                              disabled={act.isPending}
                              onClick={() => act.mutate({ id: a.id, action: "confirm" })}
                            >
                              {t("appointments.confirm", "Confirm")}
                            </button>
                          )}
                          {can("appointments.manage") && (
                            <Menu
                              label={t("appointments.more", "More actions")}
                              items={[
                                { label: t("appointments.reschedule", "Reschedule…"), onSelect: () => setMoving(a) },
                                {
                                  label: t("appointments.no_show", "Mark no-show"),
                                  hidden: !past(a),
                                  onSelect: () => act.mutate({ id: a.id, action: "no-show" }),
                                },
                                {
                                  label: t("appointments.cancel", "Cancel appointment…"),
                                  danger: true,
                                  onSelect: () => setCancelling(a),
                                },
                              ]}
                            />
                          )}
                        </div>
                      )}
                      {a.visit_id && (
                        <Link to="/queue" className="small">
                          {a.visit_status === "completed"
                            ? t("appointments.visit_done", "Visit done")
                            : t("appointments.in_queue", "In queue")}
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
      <Modal open={booking} title={t("appointments.book", "Book appointment")} onClose={() => setBooking(false)}>
        <AppointmentForm defaultDate={day} onDone={() => setBooking(false)} />
      </Modal>
      <Modal
        open={moving !== null}
        title={t("appointments.reschedule_title", "Reschedule appointment")}
        onClose={() => setMoving(null)}
      >
        {moving && <RescheduleForm appt={moving} onDone={() => setMoving(null)} />}
      </Modal>
      <ReasonDialog
        open={cancelling !== null}
        title={t("appointments.cancel", "Cancel appointment")}
        label={t("appointments.cancel_reason", "Reason for cancelling")}
        confirmLabel={t("appointments.cancel", "Cancel appointment")}
        busy={act.isPending}
        error={act.error}
        onClose={() => setCancelling(null)}
        danger
        onConfirm={(reason) => cancelling && act.mutate({ id: cancelling.id, action: "cancel", reason })}
      />
    </div>
  );
}

function RescheduleForm({ appt, onDone }: { appt: Appointment; onDone: () => void }) {
  const { t } = useTranslation();
  const [date, setDate] = useState(appt.scheduled_date >= todayIso() ? appt.scheduled_date : todayIso());
  const [time, setTime] = useState(timeOf(appt.scheduled_at));
  const [doctor, setDoctor] = useState(appt.doctor.id);
  const [reason, setReason] = useState("");
  const save = useAction(
    () =>
      api.post(`/appointments/${appt.id}/reschedule/`, {
        scheduled_at: `${date}T${time}:00+03:00`,
        doctor_id: doctor,
        reason,
      }),
    [["appointments"]],
    onDone,
    t("appointments.moved_toast", "Appointment rescheduled"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <PatientLine patient={appt.patient} />
      <p className="small muted">
        {t(
          "appointments.currently",
          "Currently {{when}} with Dr. {{doctor}}. The patient will need to confirm again.",
          { when: `${appt.scheduled_date} ${timeOf(appt.scheduled_at)}`, doctor: appt.doctor.full_name },
        )}
      </p>
      <ErrorBanner error={save.error} />
      <div className="form-grid">
        <Field label={t("common.date", "Date")} id="rs-date">
          <input id="rs-date" type="date" min={todayIso()} value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label={t("common.time", "Time")} id="rs-time">
          <input id="rs-time" type="time" step={300} value={time} onChange={(e) => setTime(e.target.value)} />
        </Field>
        <Field label={t("queue.doctor", "Doctor")} id="rs-d">
          <DoctorSelect id="rs-d" value={doctor} onChange={setDoctor} />
        </Field>
        <Field label={t("appointments.reschedule_reason", "Reason (optional)")} id="rs-r">
          <input id="rs-r" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending}>
          {t("appointments.reschedule_save", "Move appointment")}
        </button>
      </div>
    </form>
  );
}

export function useServices(category?: string) {
  return (
    useGet<{ id: string; code: string; name: string; category: string; price: string; is_active: boolean }[]>(
      ["services", "active"],
      "/billing/services/?active=true",
    ).data?.filter((s) => !category || s.category === category) ?? []
  );
}

export function AppointmentForm({
  patient: fixed,
  defaultDate,
  encounterId,
  defaultDoctor,
  defaultReason,
  onDone,
}: {
  patient?: PatientBrief;
  defaultDate?: string;
  encounterId?: string;
  defaultDoctor?: string;
  defaultReason?: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [patient, setPatient] = useState<PatientBrief | null>(fixed ?? null);
  const [doctor, setDoctor] = useState(defaultDoctor ?? "");
  const [date, setDate] = useState(defaultDate && defaultDate >= todayIso() ? defaultDate : todayIso());
  const [time, setTime] = useState("09:00");
  const [duration, setDuration] = useState("15");
  const [reason, setReason] = useState(defaultReason ?? "");
  const [notes, setNotes] = useState("");
  const [service, setService] = useState("");
  const services = useServices("consultation");
  const save = useAction(
    () =>
      api.post("/appointments/", {
        patient_id: patient?.id,
        doctor_id: doctor,
        scheduled_at: `${date}T${time}:00+03:00`,
        duration_minutes: Number(duration),
        reason,
        notes,
        service_id: service || null,
        encounter_id: encounterId ?? null,
      }),
    [["appointments"], ["encounters"]],
    onDone,
    t("appointments.booked_toast", "Appointment booked"),
  );

  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} />
      {!fixed && (
        <div className="field">
          <span className="label">{t("patients.patient", "Patient")}</span>
          <PatientPicker value={patient} onChange={setPatient} autoFocus />
        </div>
      )}
      {fixed && <PatientLine patient={fixed} />}
      <div className="form-grid">
        <Field label={t("queue.doctor", "Doctor")} id="ap-d">
          <DoctorSelect id="ap-d" value={doctor} onChange={setDoctor} />
        </Field>
        <Field label={t("appointments.duration", "Length")} id="ap-len">
          <select id="ap-len" value={duration} onChange={(e) => setDuration(e.target.value)}>
            {["10", "15", "20", "30", "45", "60"].map((m) => (
              <option key={m} value={m}>
                {m} min
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("common.date", "Date")} id="ap-date">
          <input id="ap-date" type="date" min={todayIso()} value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <Field label={t("common.time", "Time")} id="ap-time">
          <input id="ap-time" type="time" step={300} value={time} onChange={(e) => setTime(e.target.value)} />
        </Field>
        <Field label={t("appointments.service", "Service")} id="ap-s">
          <select id="ap-s" value={service} onChange={(e) => setService(e.target.value)}>
            <option value="">{t("appointments.service_default", "Standard consultation")}</option>
            {services.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("appointments.reason", "Reason")} id="ap-r">
          <input id="ap-r" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <Field label={t("appointments.notes", "Notes for the clinic (optional)")} id="ap-n" className="span-all">
          <textarea
            id="ap-n"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            style={{ minHeight: 60 }}
            placeholder={t("appointments.notes_ph", "e.g. bring previous results, fasting required")}
          />
        </Field>
      </div>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!patient || !doctor || save.isPending}>
          {t("appointments.book", "Book appointment")}
        </button>
      </div>
    </form>
  );
}
