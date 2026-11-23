import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Download, Eye, Paperclip, Trash2 } from "lucide-react";
import { api } from "../api/client";
import { useGet } from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime } from "../lib/format";
import { Empty, ErrorBanner, Field, Loading, Modal, Panel, ReasonDialog, fieldErrors, toast } from "../ui";

export interface Attachment {
  id: string;
  kind: string;
  kind_label: string;
  title: string;
  document_date: string | null;
  file_name: string;
  content_type: string;
  size_bytes: number;
  uploaded_by_name: string;
  created_at: string;
}

const KINDS = [
  { key: "referral", label: "Referral letter from another facility" },
  { key: "outside_lab", label: "Outside laboratory result" },
  { key: "imaging", label: "X-ray, ultrasound or other imaging report" },
  { key: "consent", label: "Signed consent form" },
  { key: "other_clinical", label: "Other clinical document" },
];

const size = (n: number) =>
  n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;

/** Scanned papers and photos kept with the record: outside results, referral letters, consent forms. */
export function AttachmentsPanel({ patientId }: { patientId: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const qc = useQueryClient();
  const q = useGet<Attachment[]>(["attachments", patientId], `/patients/${patientId}/attachments/`);
  const [adding, setAdding] = useState(false);
  const [preview, setPreview] = useState<Attachment | null>(null);
  const [removing, setRemoving] = useState<Attachment | null>(null);
  const canOpen = can("clinical.view");
  const canAdd = can("clinical.write", "patients.update");
  const remove = useMutation({
    mutationFn: (v: { id: string; reason: string }) => api.post(`/attachments/${v.id}/remove/`, { reason: v.reason }),
    onSuccess: () => {
      setRemoving(null);
      void qc.invalidateQueries({ queryKey: ["attachments", patientId] });
      toast(t("att.removed", "Attachment removed"));
    },
  });
  const fileUrl = (a: Attachment, download = false) =>
    `/api/v1/attachments/${a.id}/file/${download ? "?download=1" : ""}`;
  return (
    <Panel
      flush
      title={
        <div>
          <h2>{t("att.title", "Attached documents")}</h2>
          <p className="small muted">
            {t(
              "att.sub",
              "Scans and photos of papers from outside: results, referral letters, consent forms. PDF, JPEG or PNG, up to 10 MB.",
            )}
          </p>
        </div>
      }
      actions={
        canAdd && (
          <button className="btn btn-sm" onClick={() => setAdding(true)}>
            <Paperclip size={15} aria-hidden /> {t("att.add", "Attach a document")}
          </button>
        )
      }
    >
      <ErrorBanner error={q.error} />
      {q.isLoading ? (
        <Loading />
      ) : !q.data?.length ? (
        <Empty>{t("att.none", "No documents attached.")}</Empty>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>{t("att.document", "Document")}</th>
                <th>{t("att.kind", "Kind")}</th>
                <th>{t("att.added", "Added")}</th>
                <th className="num">{t("att.size", "Size")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {q.data.map((a) => (
                <tr key={a.id}>
                  <td>
                    <strong>{a.title}</strong>
                    {a.document_date && (
                      <div className="small muted">{t("att.dated", "Dated {{date}}", { date: a.document_date })}</div>
                    )}
                  </td>
                  <td className="small">{t(`att.kind_${a.kind}`, a.kind_label)}</td>
                  <td className="small nowrap">
                    {formatDateTime(a.created_at)}
                    <div className="subtle">{a.uploaded_by_name}</div>
                  </td>
                  <td className="num small">{size(a.size_bytes)}</td>
                  <td className="num nowrap">
                    {canOpen && a.content_type.startsWith("image/") && (
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => setPreview(a)}
                        aria-label={t("att.view", "View {{title}}", { title: a.title })}
                      >
                        <Eye size={15} />
                      </button>
                    )}
                    {canOpen && (
                      <a
                        className="btn btn-sm btn-ghost"
                        href={fileUrl(a, true)}
                        aria-label={t("att.download", "Download {{title}}", { title: a.title })}
                      >
                        <Download size={15} />
                      </a>
                    )}
                    {canAdd && (
                      <button
                        className="btn btn-sm btn-ghost"
                        onClick={() => setRemoving(a)}
                        aria-label={t("att.remove", "Remove {{title}}", { title: a.title })}
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Modal open={adding} title={t("att.add", "Attach a document")} onClose={() => setAdding(false)}>
        {adding && <AttachmentForm patientId={patientId} onDone={() => setAdding(false)} />}
      </Modal>
      <Modal open={preview !== null} wide title={preview?.title ?? ""} onClose={() => setPreview(null)}>
        {preview && <img src={fileUrl(preview)} alt={preview.title} className="attachment-preview" />}
      </Modal>
      <ReasonDialog
        open={removing !== null}
        danger
        title={t("att.remove_title", "Remove {{title}}?", { title: removing?.title ?? "" })}
        label={t("att.remove_reason", "Why? (for example: belongs to another patient, unreadable)")}
        confirmLabel={t("att.remove_confirm", "Remove")}
        busy={remove.isPending}
        error={remove.error}
        onClose={() => setRemoving(null)}
        onConfirm={(reason) => removing && remove.mutate({ id: removing.id, reason })}
      />
    </Panel>
  );
}

function AttachmentForm({ patientId, onDone }: { patientId: string; onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [f, setF] = useState({ kind: "outside_lab", title: "", document_date: "" });
  const [file, setFile] = useState<File | null>(null);
  const save = useMutation({
    mutationFn: () => {
      const form = new FormData();
      form.append("file", file as File);
      form.append("kind", f.kind);
      form.append("title", f.title);
      if (f.document_date) form.append("document_date", f.document_date);
      return api.upload<Attachment>(`/patients/${patientId}/attachments/`, form);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["attachments", patientId] });
      toast(t("att.added_toast", "Document attached"));
      onDone();
    },
  });
  const tooBig = !!file && file.size > 10 * 1024 * 1024;
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <ErrorBanner error={save.error} />
      <Field
        label={t("att.file", "File (PDF, JPEG or PNG)")}
        id="at-f"
        error={[
          ...fieldErrors(save.error, "file"),
          ...(tooBig ? [t("att.too_big", "The file is larger than 10 MB.")] : []),
        ]}
      >
        <input
          id="at-f"
          ref={fileRef}
          type="file"
          accept="application/pdf,image/jpeg,image/png"
          onChange={(e) => {
            const chosen = e.target.files?.[0] ?? null;
            setFile(chosen);
            if (chosen && !f.title) setF({ ...f, title: chosen.name.replace(/\.[^.]+$/, "") });
          }}
        />
      </Field>
      <div className="form-grid">
        <Field label={t("att.kind", "Kind")} id="at-k">
          <select id="at-k" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
            {KINDS.map((k) => (
              <option key={k.key} value={k.key}>
                {t(`att.kind_${k.key}`, k.label)}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={t("att.title_field", "Title")}
          id="at-t"
          error={fieldErrors(save.error, "title")}
          hint={t("att.title_hint", "e.g. Ultrasound report, Adama Hospital")}
        >
          <input id="at-t" value={f.title} maxLength={120} onChange={(e) => setF({ ...f, title: e.target.value })} />
        </Field>
        <Field
          label={t("att.document_date", "Date on the document")}
          id="at-d"
          error={fieldErrors(save.error, "document_date")}
        >
          <input
            id="at-d"
            type="date"
            value={f.document_date}
            onChange={(e) => setF({ ...f, document_date: e.target.value })}
          />
        </Field>
      </div>
      <p className="small muted">
        {t(
          "att.privacy",
          "Photos are saved again without hidden details such as the phone's location. Do not attach ID cards or anything not needed for care.",
        )}
      </p>
      <div className="form-actions">
        <button className="btn btn-primary" disabled={!file || tooBig || !f.title.trim() || save.isPending}>
          {save.isPending ? t("att.uploading", "Attaching…") : t("att.attach", "Attach")}
        </button>
      </div>
    </form>
  );
}
