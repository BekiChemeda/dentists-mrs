import { Suspense } from "react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Bell,
  Boxes,
  Building2,
  CalendarRange,
  ChevronDown,
  Siren,
  ChevronRight,
  Menu,
  X,
  CalendarDays,
  ClipboardCheck,
  Cross,
  FlaskConical,
  HeartPulse,
  LayoutDashboard,
  ListOrdered,
  LogOut,
  Pill,
  ReceiptText,
  ScrollText,
  Smartphone,
  Search,
  ShieldCheck,
  Stethoscope,
  Tags,
  UserCog,
  Users,
  BarChart3,
  KeyRound,
  Megaphone,
  Monitor,
  Moon,
  Network,
  ServerCog,
  Sun,
  Smile,
  BellRing,
  Hammer,
  Sparkles,
} from "lucide-react";
import { api, queryString } from "../api/client";
import { useAction, useGet } from "../api/hooks";
import type { Notice, Paginated, Patient, Visit } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import { NAV_ITEMS, visibleNavItems, type NavGroup } from "../navigation";
import { Toaster, initials, Loading } from "../ui";
import { MaintenanceStrip } from "../pages/system";
import { logoSrc, useClinic } from "../pages/common";
import { useTheme, type ThemeChoice } from "../lib/theme";

const ICONS: Record<string, typeof Users> = {
  dashboard: LayoutDashboard,
  patients: Users,
  queue: ListOrdered,
  appointments: CalendarDays,
  triage: HeartPulse,
  consultations: Stethoscope,
  laboratory: FlaskConical,
  pharmacy: Pill,
  inventory: Boxes,
  billing: ReceiptText,
  approvals: ClipboardCheck,
  reports: BarChart3,
  catalogue: Tags,
  users: UserCog,
  roles: ShieldCheck,
  audit: ScrollText,
  clinic: Building2,
  calendar: CalendarRange,
  system: ServerCog,
  departments: Network,
  announcements: Megaphone,
  phones: Smartphone,
  dental_encounters: Smile,
  recalls: BellRing,
  ortho: Sparkles,
  lab_cases: Hammer,
  dental_catalogue: Tags,
};
const GROUPS: NavGroup[] = ["work", "departments", "management", "admin"];

export function AppShell() {
  const { user, logout, can } = useAuth();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);
  if (!user) return null;
  if (user.must_change_password || user.mfa_setup_required)
    return (
      <Suspense fallback={<Loading />}>
        <Outlet />
      </Suspense>
    );

  const items = visibleNavItems(user.permissions, user.modules_off ?? []);
  const onLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };
  const roleNames = user.roles.map((r) => r.name).join(", ");

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside
        id="sidebar"
        className={`sidebar${menuOpen ? " sidebar-open" : ""}`}
        aria-label={t("nav.main", "Main navigation")}
      >
        <Brand />
        <nav>
          {GROUPS.map((group) => {
            const groupItems = items.filter((i) => i.group === group);
            if (!groupItems.length) return null;
            return (
              <div className="nav-group" key={group}>
                <div className="nav-heading">{t(`nav.group_${group}`)}</div>
                {groupItems.map((item) => {
                  const Icon = ICONS[item.key] ?? LayoutDashboard;
                  return (
                    <NavLink key={item.key} to={item.path} end={item.path === "/"} className="nav-item">
                      <Icon size={17} aria-hidden />
                      <span>{t(`nav.${item.key}`)}</span>
                      {item.key === "approvals" && <PendingApprovalsCount />}
                    </NavLink>
                  );
                })}
              </div>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-user">
            <span className="avatar avatar-sm" aria-hidden>
              {initials(user.full_name)}
            </span>
            <span>
              <strong>{user.full_name}</strong>
              <small>{roleNames}</small>
            </span>
            <button
              type="button"
              className="icon-button"
              title={t("auth.sign_out")}
              aria-label={t("auth.sign_out")}
              onClick={onLogout}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="topbar-left">
            <button
              type="button"
              className="icon-button mobile-menu"
              aria-controls="sidebar"
              aria-expanded={menuOpen}
              aria-label={t("shell.toggle_menu", "Toggle menu")}
              onClick={() => setMenuOpen(!menuOpen)}
            >
              {menuOpen ? <X size={21} /> : <Menu size={21} />}
            </button>
            <Breadcrumb />
          </div>
          <div className="topbar-right">
            {can("patients.view") && <GlobalPatientSearch />}
            <Notifications />
            <ProfileMenu name={user.full_name} roles={roleNames} username={user.username} onLogout={onLogout} />
          </div>
        </header>
        <MaintenanceStrip />
        {can("triage.record", "clinical.write") && <EmergencyStrip />}
        <main id="main" className="content" tabIndex={-1}>
          <Suspense fallback={<Loading />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      {menuOpen && <div className="sidebar-scrim" onClick={() => setMenuOpen(false)} aria-hidden />}
      <Toaster />
    </div>
  );
}

const DETAIL_LABELS: Record<string, [string, string]> = {
  patients: ["crumb.patient_chart", "Patient chart"],
  consultations: ["crumb.visit", "Visit"],
  billing: ["crumb.invoice", "Invoice"],
  dental_encounters: ["crumb.examination", "Examination"],
};

/** "Clinic › Section › Detail": the section is a link back whenever you are on a detail page. */
function Breadcrumb() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const match = [...NAV_ITEMS]
    .filter((i) => (i.path === "/" ? pathname === "/" : pathname.startsWith(i.path)))
    .sort((a, b) => b.path.length - a.path.length)[0];
  if (!match && pathname.startsWith("/dental/patients/")) {
    return (
      <nav className="breadcrumb" aria-label={t("shell.breadcrumb", "Breadcrumb")}>
        <span className="crumb-root">{t("app.name")}</span>
        <ChevronRight size={14} aria-hidden />
        <Link to="/patients">{t("nav.patients")}</Link>
        <ChevronRight size={14} aria-hidden />
        <strong aria-current="page">{t("crumb.dental_record", "Dental record")}</strong>
      </nav>
    );
  }
  const section = match ? t(`nav.${match.key}`) : pathname.startsWith("/account") ? t("auth.change_password") : "";
  const deeper = match && match.path !== "/" && pathname.replace(/\/$/, "") !== match.path;
  const detail = deeper ? t(...(DETAIL_LABELS[match.key] ?? ["crumb.details", "Details"])) : null;
  return (
    <nav className="breadcrumb" aria-label={t("shell.breadcrumb", "Breadcrumb")}>
      <span className="crumb-root">{t("app.name")}</span>
      <ChevronRight size={14} aria-hidden />
      {detail ? <Link to={match.path}>{section}</Link> : <strong aria-current="page">{section}</strong>}
      {detail && (
        <>
          <ChevronRight size={14} aria-hidden />
          <strong aria-current="page">{detail}</strong>
        </>
      )}
    </nav>
  );
}

function ProfileMenu({
  name,
  roles,
  username,
  onLogout,
}: {
  name: string;
  roles: string;
  username: string;
  onLogout: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div className="profile-control" ref={ref}>
      <button
        type="button"
        className="topbar-profile"
        aria-label={t("shell.account_menu", "Account menu")}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="avatar avatar-sm" aria-hidden>
          {initials(name)}
        </span>
        <span className="topbar-profile-text">
          <strong>{name}</strong>
          <small>{roles}</small>
        </span>
        <ChevronDown size={14} aria-hidden />
      </button>
      {open && (
        <div className="profile-menu">
          <div>
            <strong>{name}</strong>
            <small>@{username}</small>
          </div>
          <Link to="/account/password" onClick={() => setOpen(false)}>
            <KeyRound size={16} aria-hidden /> {t("auth.change_password")}
          </Link>
          <Link to="/account/security" onClick={() => setOpen(false)}>
            <ShieldCheck size={16} aria-hidden /> {t("mfa.page_title", "Security and alerts")}
          </Link>
          <ThemeChoiceRow />
          <button type="button" onClick={onLogout}>
            <LogOut size={16} aria-hidden /> {t("auth.sign_out")}
          </button>
        </div>
      )}
    </div>
  );
}

/** Emergency patients still waiting are visible on every screen, not just the queue. */
function EmergencyStrip() {
  const { t } = useTranslation();
  const q = useGet<Visit[]>(["visits", "emergency"], "/visits/?open=true", { refetchInterval: 20_000 });
  const waiting = (q.data ?? []).filter(
    (v) => v.priority === "emergency" && (v.status === "waiting_triage" || v.status === "waiting_doctor"),
  );
  if (!waiting.length) return null;
  return (
    <div className="emergency-strip" role="alert">
      <Siren size={18} aria-hidden />
      <strong>{t("shell.emergency", "Emergency waiting")}:</strong>
      <span>
        {waiting
          .map(
            (v) =>
              `${v.patient.full_name} (${t("queue.ticket_n", "Ticket {{n}}", { n: v.queue_number })}, ${v.status === "waiting_triage" ? t("queue.lane_triage", "waiting for triage") : t("queue.lane_doctor_inline", "waiting for the dentist")})`,
          )
          .join("; ")}
      </span>
      <Link to="/queue">{t("shell.open_queue", "Open waiting list")}</Link>
    </div>
  );
}

function PendingApprovalsCount() {
  const { can } = useAuth();
  const approver = can("pharmacy.dispense.override", "billing.discount.approve", "billing.void.approve");
  const q = useGet<Paginated<{ can_decide: boolean }>>(
    ["approvals", "pending-count"],
    approver ? "/approvals/?status=pending&page_size=50" : null,
    { refetchInterval: 60_000 },
  );
  const n = q.data?.results.filter((a) => a.can_decide).length ?? 0;
  return n > 0 ? (
    <span className="rail-count" aria-label={`${n} pending`}>
      {n}
    </span>
  ) : null;
}

function GlobalPatientSearch() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(id);
  }, [q]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) {
        e.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const results = useGet<Paginated<Patient>>(
    ["patients", "search", debounced],
    debounced.length >= 2 ? `/patients/${queryString({ q: debounced, page_size: 8 })}` : null,
  );
  const rows = results.data?.results ?? [];

  const go = (p: Patient) => {
    setOpen(false);
    setQ("");
    navigate(`/patients/${p.id}`);
  };

  return (
    <div className="global-search search-box" role="search">
      <Search size={18} aria-hidden />
      <input
        ref={input}
        value={q}
        placeholder={t("app.search_patients")}
        aria-label={t("app.search_patients")}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, rows.length - 1));
          }
          if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          }
          if (e.key === "Enter" && rows[active]) go(rows[active]);
          if (e.key === "Escape") {
            setOpen(false);
            input.current?.blur();
          }
        }}
      />
      {!q && <kbd>/</kbd>}
      {open && debounced.length >= 2 && (
        <div className="search-results" role="listbox">
          {results.isLoading && <div className="loading">{t("common.loading")}</div>}
          {!results.isLoading && rows.length === 0 && (
            <div className="loading">
              {t("patients.no_match", "No patient matches. Check the spelling or register a new patient.")}
            </div>
          )}
          {rows.map((p, i) => (
            <button
              key={p.id}
              type="button"
              className="search-item"
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => go(p)}
            >
              <strong>{p.full_name}</strong>
              <span className="mono subtle">{p.mrn}</span>
              <span className="subtle">
                {p.sex === "female" ? t("sex.female", "Female") : t("sex.male", "Male")}, {p.age}{" "}
                {t("common.years", "years")}
                {p.phone && `, ${p.phone}`}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const q = useGet<Paginated<Notice> & { unread: number }>(["notifications"], "/notifications/?page_size=15", {
    refetchInterval: 30_000,
  });
  const markAll = useAction(() => api.post("/notifications/read/", {}), [["notifications"]], undefined, false);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const unread = q.data?.unread ?? 0;
  return (
    <div className="bell" ref={ref}>
      <button
        type="button"
        className="icon-button"
        aria-label={
          unread
            ? `${t("notifications.title", "Notifications")} (${unread})`
            : t("notifications.title", "Notifications")
        }
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Bell size={19} />
        {unread > 0 && <i className="bell-dot" aria-hidden />}
      </button>
      {open && (
        <div className="popover">
          <header>
            <strong>{t("notifications.title", "Notifications")}</strong>
            {unread > 0 && (
              <button className="link-btn small" onClick={() => markAll.mutate(undefined)}>
                {t("notifications.mark_all", "Mark all as read")}
              </button>
            )}
          </header>
          {q.data?.results.length === 0 && <div className="empty">{t("notifications.none", "Nothing new.")}</div>}
          {q.data?.results.map((n) => (
            <Link
              key={n.id}
              to={n.link || "/"}
              className={`notice${n.read_at ? "" : " unread"}`}
              onClick={() => {
                setOpen(false);
                void api.post("/notifications/read/", { ids: [n.id] });
              }}
            >
              <strong>{n.title}</strong>
              {n.body && <div className="small muted">{n.body}</div>}
              <div className="small subtle">{formatDateTime(n.created_at)}</div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function ThemeChoiceRow() {
  const { t } = useTranslation();
  const [choice, setChoice] = useTheme();
  const options: { key: ThemeChoice; label: string; icon: ReactNode }[] = [
    { key: "light", label: t("theme.light", "Light"), icon: <Sun size={14} aria-hidden /> },
    { key: "dark", label: t("theme.dark", "Dark"), icon: <Moon size={14} aria-hidden /> },
    { key: "system", label: t("theme.system", "Device"), icon: <Monitor size={14} aria-hidden /> },
  ];
  return (
    <div className="theme-choice" role="group" aria-label={t("theme.label", "Appearance")}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={choice === o.key}
          onClick={() => setChoice(o.key)}
          title={o.key === "system" ? t("theme.system_hint", "Follow this device's light or dark setting") : undefined}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** The clinic's own logo and name when a logo is set; otherwise the product mark. */
function Brand() {
  const clinic = useClinic();
  const src = logoSrc(clinic);
  if (src && clinic) {
    return (
      <Link to="/" className="brand brand-clinic" title={clinic.facility_name}>
        <img className="brand-logo" src={src} alt="" />
        <span className="brand-name">{clinic.facility_name}</span>
      </Link>
    );
  }
  return (
    <Link to="/" className="brand">
      <span className="brand-mark" aria-hidden>
        <Cross size={17} strokeWidth={3} />
      </span>
      <span>
        dental<span className="brand-muted">mrs</span>
      </span>
    </Link>
  );
}
