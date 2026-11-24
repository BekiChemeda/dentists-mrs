/**
 * Shared UI building blocks. Every user-facing string goes through t(key, default) so that
 * `npx i18next-parser` can extract them for Amharic and Afaan Oromo translation files.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Check, CheckCircle2, Info, Inbox, MoreHorizontal, X, XCircle } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, isEditConflict } from "./api/client";
import { formatDateTime } from "./lib/format";

export function PageHead({ title, sub, actions }: { title: string; sub?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </header>
  );
}

export function Panel({
  title,
  actions,
  children,
  flush,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
}) {
  return (
    <section className="panel">
      {(title || actions) && (
        <div className="panel-head">
          {typeof title === "string" ? <h2>{title}</h2> : (title ?? <span />)}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {flush ? children : <div className="panel-body">{children}</div>}
    </section>
  );
}

type Tone = "error" | "warn" | "ok" | "info";
const ICONS = { error: XCircle, warn: AlertTriangle, ok: CheckCircle2, info: Info };

export function Banner({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  const Icon = ICONS[tone];
  return (
    <div className={`banner banner-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/**
 * Shows an API error. A save refused because someone else changed the record first gets its own
 * notice with a button that reloads the record; pass `onReload` to also discard the form's own copy.
 */
export function ErrorBanner({ error, onReload }: { error: unknown; onReload?: () => void }) {
  const { t } = useTranslation();
  if (!error) return null;
  if (isEditConflict(error)) return <ConflictNotice error={error} onReload={onReload} />;
  const message = error instanceof Error ? error.message : String(error);
  // A reference number only helps support with an unexpected failure, not with a message the user can act on.
  const ref = error instanceof ApiError && (error.status >= 500 || error.status === 0) ? error.requestId : undefined;
  return (
    <Banner tone="error">
      {message}
      {ref && <span className="small"> {t("common.error_reference", { id: ref })}</span>}
    </Banner>
  );
}

function ConflictNotice({ error, onReload }: { error: ApiError; onReload?: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const who = error.details.changed_by as string | null | undefined;
  const when = error.details.changed_at as string | null | undefined;
  const reload = () => {
    void qc.invalidateQueries();
    onReload?.();
  };
  return (
    <div className="banner banner-warn conflict-notice" role="alert">
      <AlertTriangle size={18} aria-hidden />
      <div className="stack-sm">
        <strong>{t("conflict.title", "Someone else saved this record first")}</strong>
        <span>{error.message}</span>
        {(who || when) && (
          <span className="small muted">
            {t("conflict.by", "Last saved by {{who}} at {{when}}.", {
              who: who ?? t("conflict.someone", "another user"),
              when: when ? formatDateTime(when) : "—",
            })}
          </span>
        )}
        <div className="row">
          <button type="button" className="btn btn-sm" onClick={reload}>
            {t("conflict.reload", "Load the latest version")}
          </button>
        </div>
      </div>
    </div>
  );
}

export function fieldErrors(error: unknown, field: string): string[] {
  return error instanceof ApiError ? (error.fields[field] ?? []) : [];
}

export function Field({
  label,
  id,
  error,
  hint,
  children,
  className,
}: {
  label: string;
  id: string;
  error?: unknown;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  const errors =
    error === undefined ? [] : Array.isArray(error) ? (error as string[]) : fieldErrors(error, id.replace(/^f-/, ""));
  return (
    <div className={`field${errors.length ? " invalid" : ""}${className ? ` ${className}` : ""}`}>
      <label htmlFor={id}>{label}</label>
      {children}
      {hint && !errors.length && <span className="hint">{hint}</span>}
      {errors.map((m) => (
        <span key={m} className="error">
          {m}
        </span>
      ))}
    </div>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
  wide,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const { t } = useTranslation();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`modal${wide ? " wide" : ""}`} onClose={onClose} aria-labelledby={titleId}>
      <div className="modal-head">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="btn btn-ghost btn-icon" onClick={onClose} aria-label={t("common.close")}>
          <X size={20} />
        </button>
      </div>
      <div className="modal-body">{open && children}</div>
    </dialog>
  );
}

export type BadgeTone = "ok" | "wait" | "danger" | "info" | "muted";
export function Badge({ tone = "muted", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function Empty({ children, icon }: { children: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon ?? <Inbox size={28} aria-hidden />}
      <div>{children}</div>
    </div>
  );
}

export function Loading() {
  const { t } = useTranslation();
  return <div className="loading">{t("common.loading")}</div>;
}

export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: T; label: string; count?: number }[];
  value: T;
  onChange: (key: T) => void;
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          role="tab"
          className="tab"
          aria-selected={tab.key === value}
          onClick={() => onChange(tab.key)}
        >
          {tab.label}
          {tab.count !== undefined && <span className="subtle"> {tab.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { key: T; label: string }[];
  value: T;
  onChange: (key: T) => void;
  label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.key} type="button" aria-pressed={o.key === value} onClick={() => onChange(o.key)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Pager({
  page,
  count,
  pageSize,
  onPage,
}: {
  page: number;
  count: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages <= 1) return null;
  return (
    <nav className="pager" aria-label="Pagination">
      <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t("common.previous")}
      </button>
      <span className="muted small">{t("common.page_of", { page, pages })}</span>
      <button className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        {t("common.next")}
      </button>
    </nav>
  );
}

/** Ask for a short reason before a consequential action (cancel, reject, void...). */
export function ReasonDialog({
  open,
  title,
  label,
  confirmLabel,
  onClose,
  onConfirm,
  busy,
  error,
  danger,
}: {
  open: boolean;
  title: string;
  label: string;
  confirmLabel: string;
  onClose: () => void;
  onConfirm: (reason: string) => void;
  busy?: boolean;
  error?: unknown;
  danger?: boolean;
}) {
  const [reason, setReason] = useState("");
  useEffect(() => {
    if (!open) setReason("");
  }, [open]);
  const { t } = useTranslation();
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onConfirm(reason);
        }}
        className="stack-sm"
      >
        <ErrorBanner error={error} />
        <Field label={label} id="f-reason">
          <textarea id="f-reason" value={reason} onChange={(e) => setReason(e.target.value)} required autoFocus />
        </Field>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button
            type="submit"
            className={`btn ${danger ? "btn-danger" : "btn-primary"}`}
            disabled={busy || !reason.trim()}
          >
            {confirmLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function money(value: string | number | null | undefined): string {
  const n = typeof value === "string" ? Number(value) : (value ?? 0);
  return new Intl.NumberFormat("en-ET", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
}

export function qty(value: string | number | null | undefined): string {
  const n = typeof value === "string" ? Number(value) : (value ?? 0);
  return new Intl.NumberFormat("en-ET", { maximumFractionDigits: 3 }).format(n);
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
}

/* ------------------------------------------------------------------ toasts */
type ToastItem = { id: number; text: string; tone: "ok" | "error" };
let toastItems: ToastItem[] = [];
let toastSeq = 0;
const toastListeners = new Set<(items: ToastItem[]) => void>();
const emitToasts = () => toastListeners.forEach((fn) => fn(toastItems));

/** Show a short confirmation in the bottom-right corner. Safe to call from anywhere. */
export function toast(text: string, tone: "ok" | "error" = "ok") {
  const item = { id: ++toastSeq, text, tone };
  toastItems = [...toastItems.filter((i) => i.text !== text), item].slice(-3);
  emitToasts();
  setTimeout(() => {
    toastItems = toastItems.filter((i) => i.id !== item.id);
    emitToasts();
  }, 3600);
}

export function Toaster() {
  const [items, setItems] = useState(toastItems);
  useEffect(() => {
    toastListeners.add(setItems);
    return () => {
      toastListeners.delete(setItems);
    };
  }, []);
  return (
    <div className="toasts" aria-live="polite" role="status">
      {items.map((i) => (
        <div key={i.id} className={`toast toast-${i.tone}`}>
          {i.tone === "ok" ? <Check size={17} aria-hidden /> : <XCircle size={17} aria-hidden />}
          <span>{i.text}</span>
        </div>
      ))}
    </div>
  );
}

/** In-app replacement for window.confirm, styled like every other dialog. */
export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  onClose,
  onConfirm,
  danger,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  onClose: () => void;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <Modal open={open} title={title} onClose={onClose}>
      <div className="stack-sm">
        <p className="muted">{body}</p>
        <div className="form-actions">
          <button type="button" className="btn" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button
            type="button"
            autoFocus
            className={`btn ${danger ? "btn-danger-solid" : "btn-primary"}`}
            onClick={() => {
              onClose();
              onConfirm();
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}

/** A compact "more actions" menu so secondary actions do not crowd a row. */
export function Menu({
  label,
  items,
}: {
  label: string;
  items: { label: string; onSelect: () => void; hidden?: boolean; danger?: boolean }[];
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const visible = items.filter((i) => !i.hidden);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  if (!visible.length) return null;
  return (
    <div className="menu" ref={ref}>
      <button
        type="button"
        className="btn btn-sm btn-ghost btn-icon"
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div className="menu-list" role="menu">
          {visible.map((i) => (
            <button
              key={i.label}
              type="button"
              role="menuitem"
              className={i.danger ? "danger" : undefined}
              onClick={() => {
                setOpen(false);
                i.onSelect();
              }}
            >
              {i.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Print one element in a clean window, using the app's stylesheet (receipts, letters, certificates). */
export function printElement(id: string, title: string) {
  const node = document.getElementById(id);
  if (!node) return;
  const w = window.open("", "_blank", "width=820,height=960");
  if (!w) return;
  const styles = [...document.querySelectorAll("style, link[rel=stylesheet]")].map((n) => n.outerHTML).join("");
  const safeTitle = title.replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] ?? c,
  );
  w.document.write(
    `<!doctype html><html><head><title>${safeTitle}</title>${styles}</head><body class="print-body">${node.outerHTML}</body></html>`,
  );
  w.document.close();
  w.focus();
  setTimeout(() => {
    w.print();
    w.close();
  }, 300);
}
