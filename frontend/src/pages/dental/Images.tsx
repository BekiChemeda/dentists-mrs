/**
 * Dental images. Files stay on the clinic server and are shown only through the API after a permission check;
 * every view is audited. The original is kept unchanged; the browser shows a JPEG preview. No DICOM support.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { api } from "../../api/client";
import { useGet } from "../../api/hooks";
import { useAuth } from "../../auth/AuthContext";
import { Banner, Empty, ErrorBanner, Field, Loading, Modal, Panel, ReasonDialog, toast } from "../../ui";
import { formatDateTime } from "../../lib/format";
import { useDentalCatalog } from "./common";
import type { DentalImage } from "./types";

export function ImagesPanel({ patientId, encounterId }: { patientId: string; encounterId?: string }) {
  const { t } = useTranslation();
  const { can, moduleOn } = useAuth();
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const images = useGet<DentalImage[]>(
    ["dental", "images", patientId, showWithdrawn],
    moduleOn("dental_imaging") && can("dental.imaging.view")
      ? `/dental/patients/${patientId}/images/${showWithdrawn ? "?include_withdrawn=1" : ""}`
      : null,
  );
  const [uploading, setUploading] = useState(false);
  const [viewing, setViewing] = useState<DentalImage | null>(null);
  if (!moduleOn("dental_imaging"))
    return (
      <Banner tone="info">
        {t("dental.imaging_off", "The dental imaging module is switched off for this clinic.")}
      </Banner>
    );
  if (!can("dental.imaging.view")) return null;
  return (
    <Panel
      title={t("dental.images", "Images")}
      actions={
        <>
          <label className="check small">
            <input type="checkbox" checked={showWithdrawn} onChange={(e) => setShowWithdrawn(e.target.checked)} />{" "}
            {t("dental.show_withdrawn", "Show withdrawn")}
          </label>
          {can("dental.imaging.upload") && (
            <button className="btn btn-sm btn-primary" onClick={() => setUploading(true)}>
              <Upload size={15} aria-hidden /> {t("dental.upload", "Upload image")}
            </button>
          )}
        </>
      }
    >
      <ErrorBanner error={images.error} />
      {images.isLoading ? (
        <Loading />
      ) : !images.data?.length ? (
        <Empty>{t("dental.no_images", "No images.")}</Empty>
      ) : (
        <div className="image-grid">
          {images.data.map((img) => (
            <button
              key={img.id}
              type="button"
              className={`image-card${img.status === "withdrawn" ? " muted" : ""}`}
              onClick={() => setViewing(img)}
            >
              {img.status === "active" ? (
                <img
                  src={`/api/v1/dental/images/${img.id}/file/?preview=1`}
                  alt={`${img.kind_label} ${img.teeth.join(", ")}`}
                  loading="lazy"
                />
              ) : (
                <div className="image-withdrawn">{t("dental.withdrawn", "Withdrawn")}</div>
              )}
              <span className="small">
                <strong>{img.kind_label}</strong>
                {img.teeth.length > 0 && ` · ${img.teeth.join(", ")}`}
              </span>
              <span className="small subtle">{formatDateTime(img.captured_at ?? img.uploaded_at)}</span>
            </button>
          ))}
        </div>
      )}
      <Modal open={uploading} title={t("dental.upload", "Upload image")} onClose={() => setUploading(false)}>
        {uploading && <UploadForm patientId={patientId} encounterId={encounterId} onDone={() => setUploading(false)} />}
      </Modal>
      <Modal open={!!viewing} title={viewing?.kind_label ?? ""} onClose={() => setViewing(null)} wide>
        {viewing && <ImageViewer image={viewing} onClose={() => setViewing(null)} />}
      </Modal>
    </Panel>
  );
}

function UploadForm({
  patientId,
  encounterId,
  replaces,
  onDone,
}: {
  patientId: string;
  encounterId?: string;
  replaces?: DentalImage;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const catalog = useDentalCatalog();
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState(replaces?.kind ?? "periapical");
  const [teeth, setTeeth] = useState(replaces?.teeth.join(", ") ?? "");
  const [description, setDescription] = useState(replaces?.description ?? "");
  const [captured, setCaptured] = useState("");
  const send = useMutation({
    mutationFn: () => {
      const form = new FormData();
      if (file) form.append("file", file);
      form.append("kind", kind);
      form.append("teeth", teeth);
      form.append("description", description);
      if (captured) form.append("captured_at", new Date(captured).toISOString());
      if (encounterId) form.append("encounter_id", encounterId);
      if (replaces) form.append("replaces_id", replaces.id);
      return api.upload<DentalImage>(`/dental/patients/${patientId}/images/`, form);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental", "images", patientId] });
      toast(t("dental.uploaded", "Image uploaded"));
      onDone();
    },
  });
  return (
    <form
      className="stack-sm"
      onSubmit={(e) => {
        e.preventDefault();
        send.mutate();
      }}
    >
      <p className="small muted">
        {t(
          "dental.upload_hint",
          "JPEG, PNG or TIFF. DICOM files are not supported: export a PNG or TIFF from the X-ray software.",
        )}
      </p>
      <ErrorBanner error={send.error} />
      <Field label={t("dental.file", "File")} id="f-file" error={send.error}>
        <input
          id="f-file"
          type="file"
          accept="image/jpeg,image/png,image/tiff"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          required
        />
      </Field>
      <Field label={t("dental.image_type", "Type")} id="f-kind">
        <select id="f-kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          {(catalog.data?.image_kinds ?? []).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
      </Field>
      <Field label={t("dental.teeth", "Teeth (FDI, e.g. 36, 37)")} id="f-teeth" error={send.error}>
        <input id="f-teeth" value={teeth} onChange={(e) => setTeeth(e.target.value)} />
      </Field>
      <Field label={t("dental.captured", "Taken at (optional)")} id="f-captured_at" error={send.error}>
        <input
          id="f-captured_at"
          type="datetime-local"
          value={captured}
          onChange={(e) => setCaptured(e.target.value)}
        />
      </Field>
      <Field label={t("dental.description", "Description")} id="f-description">
        <input
          id="f-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={255}
        />
      </Field>
      <div className="form-actions">
        <button type="button" className="btn" onClick={onDone}>
          {t("common.cancel")}
        </button>
        <button className="btn btn-primary" disabled={send.isPending || !file}>
          {t("dental.upload", "Upload image")}
        </button>
      </div>
    </form>
  );
}

function ImageViewer({ image, onClose }: { image: DentalImage; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { can } = useAuth();
  const [withdrawing, setWithdrawing] = useState(false);
  const [replacing, setReplacing] = useState(false);
  const [zoom, setZoom] = useState(1);
  const withdraw = useMutation({
    mutationFn: (reason: string) => api.post(`/dental/images/${image.id}/withdraw/`, { reason }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["dental", "images", image.patient] });
      onClose();
    },
  });
  if (replacing) return <UploadForm patientId={image.patient} replaces={image} onDone={onClose} />;
  return (
    <div className="stack-sm">
      {image.status === "active" ? (
        <>
          <div className="row">
            <button className="btn btn-sm" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>
              −
            </button>
            <span className="small">{Math.round(zoom * 100)}%</span>
            <button className="btn btn-sm" onClick={() => setZoom((z) => Math.min(4, z + 0.25))}>
              +
            </button>
            <a className="btn btn-sm" href={`/api/v1/dental/images/${image.id}/file/?download=1`}>
              {t("dental.download_original", "Download original")}
            </a>
          </div>
          <div className="image-viewer">
            <img
              src={`/api/v1/dental/images/${image.id}/file/?preview=1`}
              alt={image.kind_label}
              style={{ transform: `scale(${zoom})`, transformOrigin: "top left" }}
            />
          </div>
        </>
      ) : (
        <Banner tone="warn">
          {t("dental.withdrawn_reason", "Withdrawn")}: {image.withdrawn_reason}
        </Banner>
      )}
      <dl className="facts small">
        <dt>{t("dental.teeth", "Teeth")}</dt>
        <dd>{image.teeth.join(", ") || "—"}</dd>
        <dt>{t("dental.description", "Description")}</dt>
        <dd>{image.description || "—"}</dd>
        <dt>{t("dental.uploaded_by", "Uploaded by")}</dt>
        <dd>
          {image.uploaded_by.full_name}, {formatDateTime(image.uploaded_at)}
        </dd>
        <dt>{t("dental.file", "File")}</dt>
        <dd>
          {image.original_name} · {image.width}×{image.height} · {(image.size_bytes / 1e6).toFixed(1)} MB
        </dd>
      </dl>
      {image.changes.length > 0 && (
        <details>
          <summary>{t("dental.corrections", "Corrections ({{n}})", { n: image.changes.length })}</summary>
          <ul className="small">
            {image.changes.map((c, i) => (
              <li key={i}>
                {c.field}: {c.old || "—"} → {c.new || "—"} ({c.reason}; {c.by}, {formatDateTime(c.at)})
              </li>
            ))}
          </ul>
        </details>
      )}
      {image.status === "active" && can("dental.imaging.manage") && (
        <div className="form-actions">
          <button className="btn" onClick={() => setReplacing(true)}>
            {t("dental.replace", "Upload a corrected image…")}
          </button>
          <button className="btn btn-danger" onClick={() => setWithdrawing(true)}>
            {t("dental.withdraw", "Withdraw…")}
          </button>
        </div>
      )}
      <ReasonDialog
        open={withdrawing}
        title={t("dental.withdraw_title", "Withdraw this image")}
        label={t("dental.withdraw_label", "Reason (e.g. wrong patient)")}
        confirmLabel={t("dental.withdraw", "Withdraw")}
        onClose={() => setWithdrawing(false)}
        onConfirm={(reason) => withdraw.mutate(reason)}
        busy={withdraw.isPending}
        error={withdraw.error}
        danger
      />
    </div>
  );
}
