import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CalendarPlus, ChevronLeft, ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Appointment, Paginated } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { StateBadge } from "../labels";
import { EC_MONTHS, ecMonthLength, formatEc, fromEthiopian, toEthiopian } from "../lib/ethiopian";
import { formatLongDate } from "../lib/format";
import { ConfirmDialog, ErrorBanner, Field, Loading, Modal, PageHead, Panel, Segmented, fieldErrors } from "../ui";
import { AppointmentForm } from "./appointments";
import { DoctorSelect, timeOf, todayIso } from "./common";

type Mode = "ec" | "gc";
type HolidayKind = "national" | "religious" | "memorial" | "clinic";
interface Holiday {
  row_version?: number;
  id: number | null;
  date: string;
  name: string;
  kind: HolidayKind;
  tentative: boolean;
  editable: boolean;
  note: string;
  offices_closed: boolean;
}
interface CalendarData {
  days: Record<string, { total: number; by_status: Record<string, number> }>;
  holidays: Holiday[];
  doctors: number;
}

const GC_MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const KIND_LABEL: Record<HolidayKind, string> = {
  national: "National holiday",
  religious: "Religious holiday",
  memorial: "Memorial day",
  clinic: "Clinic day",
};

const iso = (d: Date) => d.toISOString().slice(0, 10);
const parse = (s: string) => new Date(`${s}T00:00:00Z`);
const addDays = (s: string, n: number) => iso(new Date(parse(s).getTime() + n * 86_400_000));
/** Monday = 0 … Sunday = 6 */
const weekday = (s: string) => (parse(s).getUTCDay() + 6) % 7;

function monthDays(mode: Mode, year: number, month: number): string[] {
  if (mode === "gc") {
    const n = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return Array.from({ length: n }, (_, i) => iso(new Date(Date.UTC(year, month - 1, i + 1))));
  }
  const first = fromEthiopian(year, month, 1)!;
  return Array.from({ length: ecMonthLength(year, month) }, (_, i) => addDays(first, i));
}

/** Booked appointments per doctor on duty: how full the day looks. */
function loadLevel(total: number, doctors: number): "none" | "quiet" | "busy" | "full" {
  if (!total) return "none";
  const per = total / Math.max(doctors, 1);
  return per <= 4 ? "quiet" : per <= 8 ? "busy" : "full";
}

export function CalendarPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const today = todayIso();
  const [mode, setMode] = useState<Mode>("ec");
  const [cursor, setCursor] = useState(() => {
    const [y, m, d] = today.split("-").map(Number);
    const ec = toEthiopian(y, m, d);
    return { ec: { year: ec.year, month: ec.month }, gc: { year: y, month: m } };
  });
  const [doctor, setDoctor] = useState("");
  const [selected, setSelected] = useState(today);
  const cur = cursor[mode];
  const days = useMemo(() => monthDays(mode, cur.year, cur.month), [mode, cur.year, cur.month]);
  const from = days[0],
    to = days[days.length - 1];
  const data = useGet<CalendarData>(
    ["calendar", from, to, doctor],
    `/calendar/?date_from=${from}&date_to=${to}${doctor ? `&doctor=${doctor}` : ""}`,
  );
  const holidaysByDay = useMemo(() => {
    const m = new Map<string, Holiday[]>();
    for (const h of data.data?.holidays ?? []) m.set(h.date, [...(m.get(h.date) ?? []), h]);
    return m;
  }, [data.data]);

  const months = mode === "ec" ? 13 : 12;
  const shift = (n: number) =>
    setCursor((c) => {
      let { year, month } = c[mode];
      month += n;
      if (month < 1) {
        year -= 1;
        month = months;
      }
      if (month > months) {
        year += 1;
        month = 1;
      }
      return { ...c, [mode]: { year, month } };
    });
  const goToday = () => {
    const [y, m, d] = today.split("-").map(Number);
    const ec = toEthiopian(y, m, d);
    setCursor({ ec: { year: ec.year, month: ec.month }, gc: { year: y, month: m } });
    setSelected(today);
  };
  const title =
    mode === "ec" ? `${EC_MONTHS[cur.month - 1]} ${cur.year} EC` : `${GC_MONTHS[cur.month - 1]} ${cur.year}`;
  // The other calendar's months this page spans, e.g. "November – December 2026".
  const span =
    mode === "ec"
      ? (() => {
          const a = parse(from),
            b = parse(to);
          const ma = GC_MONTHS[a.getUTCMonth()],
            mb = GC_MONTHS[b.getUTCMonth()];
          return ma === mb
            ? `${ma} ${a.getUTCFullYear()}`
            : `${ma} ${a.getUTCFullYear() !== b.getUTCFullYear() ? a.getUTCFullYear() + " " : ""}– ${mb} ${b.getUTCFullYear()}`;
        })()
      : (() => {
          const a = formatEc(from).replace(/ EC$/, ""),
            b = formatEc(to);
          return `${a.replace(/ \d+,.*/, "")} – ${b.replace(/ \d+,/, "")}`;
        })();
  const lead = weekday(from);

  return (
    <div className="stack">
      <PageHead
        title={t("nav.calendar", "Calendar")}
        sub={t(
          "cal.sub",
          "Holidays and how full each day is with appointments. Clinics stay open on public holidays (Proclamation 1334/2024, Art. 8).",
        )}
        actions={
          <Segmented
            label={t("cal.calendar", "Calendar")}
            value={mode}
            onChange={setMode}
            options={[
              { key: "ec", label: t("cal.ethiopian", "Ethiopian") },
              { key: "gc", label: t("cal.gregorian", "Gregorian") },
            ]}
          />
        }
      />
      <div className="cal-layout">
        <Panel flush>
          <div className="cal-head">
            <div className="row" style={{ gap: 6 }}>
              <button className="btn btn-icon" onClick={() => shift(-1)} aria-label={t("cal.prev", "Previous month")}>
                <ChevronLeft size={18} />
              </button>
              <button className="btn btn-icon" onClick={() => shift(1)} aria-label={t("cal.next", "Next month")}>
                <ChevronRight size={18} />
              </button>
              <div className="cal-title">
                <h2>{title}</h2>
                <span>{span}</span>
              </div>
            </div>
            <div className="row" style={{ gap: 8 }}>
              <button className="btn btn-sm" onClick={goToday}>
                {t("common.today", "Today")}
              </button>
              <DoctorSelect
                id="cal-doc"
                value={doctor}
                onChange={setDoctor}
                allowNone
                noneLabel={t("cal.all_doctors", "All doctors")}
              />
            </div>
          </div>
          <ErrorBanner error={data.error} />
          <div className="cal-grid" role="grid" aria-label={title}>
            {WEEKDAYS.map((w) => (
              <div key={w} className="cal-wd" role="columnheader">
                {t(`wd.${w}`, w)}
              </div>
            ))}
            {Array.from({ length: lead }, (_, i) => (
              <div key={`pad${i}`} className="cal-pad" />
            ))}
            {days.map((d) => {
              const [y, m, dd] = d.split("-").map(Number);
              const ec = toEthiopian(y, m, dd);
              const hs = holidaysByDay.get(d) ?? [];
              const load = data.data?.days[d];
              const level = loadLevel(load?.total ?? 0, data.data?.doctors ?? 1);
              const closed = hs.some((h) => h.offices_closed);
              const main = mode === "ec" ? ec.day : dd;
              const other =
                mode === "ec"
                  ? `${GC_MONTHS[m - 1].slice(0, 3)} ${dd}`
                  : `${EC_MONTHS[ec.month - 1].slice(0, 3)} ${ec.day}`;
              return (
                <button
                  key={d}
                  type="button"
                  role="gridcell"
                  aria-selected={d === selected}
                  className={`cal-day${d === today ? " is-today" : ""}${d === selected ? " is-selected" : ""}${d < today ? " is-past" : ""}${closed ? " is-holiday" : ""}${weekday(d) === 6 ? " is-sunday" : ""}`}
                  onClick={() => setSelected(d)}
                  aria-label={`${formatLongDate(parse(d))}, ${formatEc(d)}${hs.length ? `, ${hs.map((h) => h.name).join(", ")}` : ""}${load?.total ? `, ${load.total} appointments` : ""}`}
                >
                  <span className="cal-num">{main}</span>
                  <span className="cal-other">{other}</span>
                  <span className="cal-hols">
                    {hs.slice(0, 2).map((h) => (
                      <span
                        key={h.name}
                        className={`cal-hol k-${h.kind}${h.tentative ? " tentative" : ""}`}
                        title={h.name}
                      >
                        {h.name}
                      </span>
                    ))}
                    {hs.length > 2 && <span className="cal-more">+{hs.length - 2}</span>}
                  </span>
                  {!!load?.total && (
                    <span className={`cal-load l-${level}`}>
                      {t("cal.n_booked", "{{n}} booked", { n: load.total })}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <div className="cal-legend" aria-label={t("cal.legend", "Legend")}>
            <span>
              <i className="sw k-national" />
              {t("cal.leg_holiday", "Public holiday (offices closed, clinic open)")}
            </span>
            <span>
              <i className="sw k-memorial" />
              {t("cal.leg_memorial", "Memorial day (offices open)")}
            </span>
            <span>
              <i className="sw k-clinic" />
              {t("cal.leg_clinic", "Clinic day")}
            </span>
            <span>
              <i className="sw tentative" />
              {t("cal.leg_tentative", "Date not yet confirmed")}
            </span>
            <span>
              <i className="sw l-quiet" />
              {t("cal.leg_quiet", "Up to 4 per doctor")}
            </span>
            <span>
              <i className="sw l-busy" />
              {t("cal.leg_busy", "5–8 per doctor")}
            </span>
            <span>
              <i className="sw l-full" />
              {t("cal.leg_full", "More than 8 per doctor")}
            </span>
          </div>
        </Panel>
        <DayPanel
          day={selected}
          holidays={holidaysByDay.get(selected) ?? []}
          doctor={doctor}
          canEdit={can("settings.manage")}
          canBook={can("appointments.manage")}
        />
      </div>
    </div>
  );
}

function DayPanel({
  day,
  holidays,
  doctor,
  canEdit,
  canBook,
}: {
  day: string;
  holidays: Holiday[];
  doctor: string;
  canEdit: boolean;
  canBook: boolean;
}) {
  const { t } = useTranslation();
  const appts = useGet<Paginated<Appointment>>(
    ["appointments", day, doctor],
    `/appointments/?date=${day}&page_size=100${doctor ? `&doctor=${doctor}` : ""}`,
  );
  const [editing, setEditing] = useState<Holiday | "new" | null>(null);
  const [deleting, setDeleting] = useState<Holiday | null>(null);
  const [booking, setBooking] = useState(false);
  const del = useAction(
    (id: number) => api.delete(`/calendar/holidays/${id}/`),
    [["calendar"]],
    () => setDeleting(null),
    t("cal.deleted", "Removed from the calendar"),
  );
  const rows = appts.data?.results ?? [];
  const active = rows.filter((a) => !["cancelled", "no_show"].includes(a.status));
  return (
    <Panel
      title={
        <div>
          <div>{formatLongDate(parse(day))}</div>
          <div className="small muted" style={{ fontWeight: 500 }}>
            {formatEc(day)}
          </div>
        </div>
      }
      actions={
        canEdit && (
          <button className="btn btn-sm" onClick={() => setEditing("new")}>
            <Plus size={15} aria-hidden /> {t("cal.add_day", "Add holiday")}
          </button>
        )
      }
    >
      <div className="stack-sm">
        {holidays.map((h) => (
          <div key={h.name} className={`cal-hol-row k-${h.kind}${h.tentative ? " tentative" : ""}`}>
            <div>
              <strong>{h.name}</strong>
              <div className="small">
                {KIND_LABEL[h.kind]}
                {h.tentative ? `, ${t("cal.tentative", "date not yet confirmed")}` : ""}
              </div>
              {h.note && <div className="small muted">{h.note}</div>}
            </div>
            {canEdit && h.editable && h.id !== null && (
              <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                <button
                  className="btn btn-sm btn-ghost btn-icon"
                  aria-label={t("common.edit", "Edit")}
                  onClick={() => setEditing(h)}
                >
                  <Pencil size={15} />
                </button>
                <button
                  className="btn btn-sm btn-ghost btn-icon"
                  aria-label={t("common.remove", "Remove")}
                  onClick={() => setDeleting(h)}
                >
                  <Trash2 size={15} />
                </button>
              </div>
            )}
          </div>
        ))}
        {holidays.some((h) => h.offices_closed) && (
          <p className="small muted">
            {t(
              "cal.open_note",
              "Government and private offices close; clinics and pharmacies must stay open. Expect fewer staff and different patient numbers.",
            )}
          </p>
        )}

        <div className="row-between" style={{ marginTop: 8 }}>
          <h3 className="note-group-title" style={{ margin: 0 }}>
            {t("cal.appointments", "Appointments")} ({active.length})
          </h3>
          <div className="row" style={{ gap: 6 }}>
            {canBook && day >= todayIso() && (
              <button className="btn btn-sm btn-primary" onClick={() => setBooking(true)}>
                <CalendarPlus size={15} aria-hidden /> {t("appointments.book", "Book")}
              </button>
            )}
            <Link className="btn btn-sm" to={`/appointments?date=${day}`}>
              {t("cal.open_day", "Open day")}
            </Link>
          </div>
        </div>
        {appts.isLoading ? (
          <Loading />
        ) : rows.length === 0 ? (
          <p className="subtle small">{t("cal.no_appts", "No appointments.")}</p>
        ) : (
          <table className="data compact">
            <tbody>
              {rows.map((a) => (
                <tr key={a.id} className={["cancelled", "no_show"].includes(a.status) ? "muted" : ""}>
                  <td className="mono nowrap">{timeOf(a.scheduled_at)}</td>
                  <td>
                    <Link to={`/patients/${a.patient.id}`}>
                      <strong>{a.patient.full_name}</strong>
                    </Link>
                    <div className="small subtle">
                      Dr. {a.doctor.full_name}
                      {a.reason && `, ${a.reason}`}
                    </div>
                  </td>
                  <td className="num">
                    <StateBadge set="appointment" value={a.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <Modal
        open={editing !== null}
        title={editing === "new" ? t("cal.add_day", "Add holiday") : t("cal.edit_day", "Edit holiday")}
        onClose={() => setEditing(null)}
      >
        {editing && (
          <HolidayForm holiday={editing === "new" ? null : editing} day={day} onDone={() => setEditing(null)} />
        )}
      </Modal>
      <Modal open={booking} title={t("appointments.book", "Book appointment")} onClose={() => setBooking(false)}>
        {booking && (
          <AppointmentForm
            defaultDate={day}
            defaultDoctor={doctor || undefined}
            onDone={() => {
              setBooking(false);
              void appts.refetch();
            }}
          />
        )}
      </Modal>
      <ConfirmDialog
        open={deleting !== null}
        danger
        title={t("cal.delete_title", "Remove this day?")}
        confirmLabel={t("common.remove", "Remove")}
        body={deleting ? `${deleting.name}, ${deleting.date}` : ""}
        onClose={() => setDeleting(null)}
        onConfirm={() => deleting?.id != null && del.mutate(deleting.id)}
      />
    </Panel>
  );
}

function HolidayForm({ holiday, day, onDone }: { holiday: Holiday | null; day: string; onDone: () => void }) {
  const { t } = useTranslation();
  const [f, setF] = useState({
    date: holiday?.date ?? day,
    name: holiday?.name ?? "",
    kind: holiday?.kind ?? "clinic",
    tentative: holiday?.tentative ?? false,
    note: holiday?.note ?? "",
  });
  const save = useAction(
    () =>
      holiday?.id != null
        ? api.patch(`/calendar/holidays/${holiday.id}/`, f, { ifMatch: holiday.row_version })
        : api.post("/calendar/holidays/", f),
    [["calendar"]],
    onDone,
    t("cal.saved", "Calendar updated"),
  );
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(undefined);
      }}
    >
      <ErrorBanner error={save.error} onReload={onDone} />
      <div className="form-grid">
        <Field
          label={t("common.date", "Date")}
          id="hd-d"
          hint={f.date ? formatEc(f.date) : undefined}
          error={fieldErrors(save.error, "date")}
        >
          <input id="hd-d" type="date" value={f.date} onChange={(e) => setF({ ...f, date: e.target.value })} required />
        </Field>
        <Field label={t("cal.kind", "Type")} id="hd-k">
          <select id="hd-k" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as HolidayKind })}>
            {(Object.keys(KIND_LABEL) as HolidayKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label={t("cal.name", "Name")} id="hd-n" error={fieldErrors(save.error, "name")}>
        <input
          id="hd-n"
          value={f.name}
          onChange={(e) => setF({ ...f, name: e.target.value })}
          placeholder={t("cal.name_ph", "e.g. Eid al-Fitr, or Staff training: reduced service")}
          required
        />
      </Field>
      <Field label={t("cal.note", "Note")} id="hd-o">
        <input id="hd-o" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} />
      </Field>
      <label className="check">
        <input type="checkbox" checked={f.tentative} onChange={(e) => setF({ ...f, tentative: e.target.checked })} />
        <span>{t("cal.tentative_label", "Date not yet confirmed (for holidays set by moon sighting)")}</span>
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!f.name.trim() || !f.date || save.isPending}>
          {t("common.save", "Save")}
        </button>
      </div>
    </form>
  );
}
