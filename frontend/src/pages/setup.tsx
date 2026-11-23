import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Circle, DoorOpen, Plus } from "lucide-react";
import { api } from "../api/client";
import { useGet } from "../api/hooks";
import type { ClinicSettings, Department, Room } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Badge, Empty, ErrorBanner, Field, Loading, Modal, Panel, fieldErrors, toast } from "../ui";

// ---------------------------------------------------------------------------------------------------------------
// Rooms: managed with the departments; a doctor picks the room they work in today.
// ---------------------------------------------------------------------------------------------------------------
export function RoomsPanel() {
  const { t } = useTranslation();
  const rooms = useGet<Room[]>(["rooms", "all"], "/rooms/");
  const [editing, setEditing] = useState<Room | "new" | null>(null);
  return (
    <Panel
      flush
      title={
        <div>
          <h2>{t("rooms.title", "Consultation rooms")}</h2>
          <p className="small muted">
            {t(
              "rooms.sub",
              "Doctors choose the room they work in today. When they call a patient, the waiting list shows which room to go to.",
            )}
          </p>
        </div>
      }
      actions={
        <button className="btn btn-sm" onClick={() => setEditing("new")}>
          <Plus size={15} aria-hidden /> {t("rooms.new", "New room")}
        </button>
      }
    >
      <ErrorBanner error={rooms.error} />
      {rooms.isLoading ? (
        <Loading />
      ) : !rooms.data?.length ? (
        <Empty>{t("rooms.none", "No rooms yet. Add the rooms where doctors see patients.")}</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("rooms.name", "Room")}</th>
                <th>{t("rooms.department", "Department")}</th>
                <th>{t("users.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rooms.data.map((r) => (
                <tr key={r.id} className={r.is_active ? "" : "muted"}>
                  <td>
                    <strong>{r.name}</strong>
                  </td>
                  <td>{r.department_name || "—"}</td>
                  <td>
                    <Badge tone={r.is_active ? "ok" : "muted"}>
                      {r.is_active ? t("common.active") : t("common.inactive")}
                    </Badge>
                  </td>
                  <td className="num">
                    <button className="btn btn-sm" onClick={() => setEditing(r)}>
                      {t("users.edit")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal
        open={editing !== null}
        title={editing === "new" ? t("rooms.new", "New room") : t("rooms.edit", "Edit room")}
        onClose={() => setEditing(null)}
      >
        {editing !== null && <RoomForm room={editing === "new" ? null : editing} onDone={() => setEditing(null)} />}
      </Modal>
    </Panel>
  );
}

function RoomForm({ room, onDone }: { room: Room | null; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const depts = useGet<Department[]>(["departments", "active"], "/departments/?active=true");
  const [f, setF] = useState({
    name: room?.name ?? "",
    department_id: room?.department_id ?? "",
    is_active: room?.is_active ?? true,
    sort_order: room?.sort_order ?? 0,
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, department_id: f.department_id || null };
      return room
        ? api.patch<Room>(`/rooms/${room.id}/`, body, { ifMatch: room.row_version })
        : api.post<Room>("/rooms/", body);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["rooms"] });
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
        <Field
          label={t("rooms.name", "Room")}
          id="rm-n"
          error={fieldErrors(save.error, "name")}
          hint={t("rooms.name_hint", "As written on the door, e.g. Room 3 or OPD 1")}
        >
          <input id="rm-n" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        </Field>
        <Field label={t("rooms.department", "Department")} id="rm-d">
          <select id="rm-d" value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })}>
            <option value="">{t("rooms.any_department", "Any department")}</option>
            {(depts.data ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("departments.order", "Position in lists")} id="rm-o">
          <input
            id="rm-o"
            type="number"
            min={0}
            value={f.sort_order}
            onChange={(e) => setF({ ...f, sort_order: Number(e.target.value) })}
          />
        </Field>
      </div>
      <label className="check">
        <input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />{" "}
        {t("common.active")}
      </label>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={save.isPending || !f.name.trim()}>
          {t("common.save")}
        </button>
      </div>
    </form>
  );
}

/** "I am working in": the doctor's room for today, shown to patients when they are called. */
export function MyRoomPicker() {
  const { t } = useTranslation();
  const { user, refresh } = useAuth();
  const rooms = useGet<Room[]>(["rooms", "active"], "/rooms/?active=true");
  const set = useMutation({
    mutationFn: (roomId: string) =>
      api.patch<{ room: { id: string; name: string } | null }>("/auth/me/room/", { room_id: roomId || null }),
    onSuccess: (r) => {
      void refresh();
      toast(
        r.room
          ? t("rooms.set_toast", "You are in {{room}}", { room: r.room.name })
          : t("rooms.cleared_toast", "Room cleared"),
      );
    },
  });
  if (!rooms.data?.length) return null;
  return (
    <label className="row small" style={{ gap: 8 }}>
      <DoorOpen size={16} aria-hidden />
      <span>{t("rooms.working_in", "My room")}</span>
      <select
        value={user?.room?.id ?? ""}
        disabled={set.isPending}
        onChange={(e) => set.mutate(e.target.value)}
        aria-label={t("rooms.working_in", "My room")}
      >
        <option value="">{t("rooms.not_set", "Not set")}</option>
        {rooms.data.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </select>
    </label>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// Opening hours: appointments can only be booked inside them.
// ---------------------------------------------------------------------------------------------------------------
const DAYS: { key: string; label: string }[] = [
  { key: "mon", label: "Monday" },
  { key: "tue", label: "Tuesday" },
  { key: "wed", label: "Wednesday" },
  { key: "thu", label: "Thursday" },
  { key: "fri", label: "Friday" },
  { key: "sat", label: "Saturday" },
  { key: "sun", label: "Sunday" },
];
type Hours = Record<string, { open: string; close: string } | null>;
const DEFAULT_HOURS: Hours = Object.fromEntries(
  DAYS.map((d) => [d.key, d.key === "sun" ? null : { open: "08:00", close: d.key === "sat" ? "12:30" : "17:30" }]),
);

export function OpeningHoursPanel({ clinic }: { clinic: ClinicSettings }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const stored = clinic.opening_hours ?? {};
  const limited = Object.keys(stored).length > 0;
  const [draft, setDraft] = useState<Hours | null>(null);
  const hours = draft ?? (limited ? stored : DEFAULT_HOURS);
  const [on, setOn] = useState(limited);
  const save = useMutation({
    mutationFn: () =>
      api.patch<ClinicSettings>(
        "/settings/clinic/",
        { opening_hours: on ? hours : {} },
        { ifMatch: clinic.row_version },
      ),
    onSuccess: (data) => {
      qc.setQueryData(["settings", "clinic"], data);
      setDraft(null);
      toast(t("hours.saved", "Opening hours saved"));
    },
  });
  const setDay = (day: string, value: { open: string; close: string } | null) => setDraft({ ...hours, [day]: value });
  const dirty = draft !== null || on !== limited;
  return (
    <Panel
      title={
        <div>
          <h2>{t("hours.title", "Opening hours")}</h2>
          <p className="small muted">
            {t("hours.sub", "Appointments can only be booked inside these hours. Walk-ins are always accepted.")}
          </p>
        </div>
      }
    >
      <ErrorBanner
        error={save.error}
        onReload={() => {
          setDraft(null);
          setOn(limited);
        }}
      />
      <label className="check">
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />{" "}
        {t("hours.limit", "Limit appointments to opening hours")}
      </label>
      {on && (
        <div className="table-wrap">
          <table className="data hours-table">
            <thead>
              <tr>
                <th>{t("hours.day", "Day")}</th>
                <th>{t("hours.open_day", "Open")}</th>
                <th>{t("hours.from", "From")}</th>
                <th>{t("hours.to", "To")}</th>
              </tr>
            </thead>
            <tbody>
              {DAYS.map((d) => {
                const h = hours[d.key];
                return (
                  <tr key={d.key}>
                    <th scope="row">{t(`hours.${d.key}`, d.label)}</th>
                    <td>
                      <input
                        type="checkbox"
                        checked={!!h}
                        aria-label={t("hours.open_on", "Open on {{day}}", { day: d.label })}
                        onChange={(e) => setDay(d.key, e.target.checked ? { open: "08:00", close: "17:30" } : null)}
                      />
                    </td>
                    <td>
                      {h ? (
                        <input
                          type="time"
                          value={h.open}
                          aria-label={t("hours.opens", "{{day}} opens", { day: d.label })}
                          onChange={(e) => setDay(d.key, { ...h, open: e.target.value })}
                        />
                      ) : (
                        <span className="muted">{t("hours.closed", "Closed")}</span>
                      )}
                    </td>
                    <td>
                      {h && (
                        <input
                          type="time"
                          value={h.close}
                          aria-label={t("hours.closes", "{{day}} closes", { day: d.label })}
                          onChange={(e) => setDay(d.key, { ...h, close: e.target.value })}
                        />
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {fieldErrors(save.error, "opening_hours").map((m) => (
        <p key={m} className="error small">
          {m}
        </p>
      ))}
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!dirty || save.isPending} onClick={() => save.mutate()}>
          {t("hours.save", "Save opening hours")}
        </button>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------------------------------------------
// First-run checklist on the clinic administrator's home page.
// ---------------------------------------------------------------------------------------------------------------
interface Checklist {
  hidden: boolean;
  done: number;
  total: number;
  items: { key: string; label: string; done: boolean; link: string }[];
}

export function SetupChecklistBlock() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useGet<Checklist>(["settings", "setup-checklist"], "/settings/setup-checklist/");
  const clinic = useGet<ClinicSettings>(["settings", "clinic"], "/settings/clinic/");
  const hide = useMutation({
    mutationFn: () =>
      api.patch<ClinicSettings>(
        "/settings/clinic/",
        { setup_checklist_hidden: true },
        { ifMatch: clinic.data?.row_version },
      ),
    onSuccess: (data) => {
      qc.setQueryData(["settings", "clinic"], data);
      void qc.invalidateQueries({ queryKey: ["settings", "setup-checklist"] });
    },
  });
  if (!q.data || q.data.hidden) return null;
  const { items, done, total } = q.data;
  return (
    <Panel
      title={
        <div>
          <h2>{t("setup.title", "Getting the clinic ready")}</h2>
          <p className="small muted">{t("setup.progress", "{{done}} of {{total}} done", { done, total })}</p>
        </div>
      }
      actions={
        <button className="btn btn-sm" disabled={hide.isPending || !clinic.data} onClick={() => hide.mutate()}>
          {done === total ? t("setup.close_done", "Close") : t("setup.hide", "Hide this list")}
        </button>
      }
    >
      <ErrorBanner error={hide.error} />
      <div
        className="meter-bar meter-ok"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-label={t("setup.progress", "{{done}} of {{total}} done", { done, total })}
      >
        <span style={{ width: `${(done / total) * 100}%` }} />
      </div>
      <ul className="checklist">
        {items.map((i) => (
          <li key={i.key} className={i.done ? "done" : ""}>
            {i.done ? (
              <CheckCircle2 size={18} aria-hidden className="check-done" />
            ) : (
              <Circle size={18} aria-hidden className="muted" />
            )}
            <span className="sr-only">{i.done ? t("setup.done", "Done") : t("setup.todo", "To do")}: </span>
            {i.done ? <span>{i.label}</span> : <Link to={i.link}>{i.label}</Link>}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
