/**
 * "Ver histórico": the revisions of one model, newest first.
 *
 * Every save that could not change a revision in place (the model had issued
 * certificates or had been active) left a row here; certificates stay linked
 * to the exact revision they were issued with. Two revisions can be compared
 * side by side, and an older one can be duplicated into a new model — the
 * only way back, since the active revision is always the current one.
 */
import { useEffect, useState } from "react";
import { CertificateTemplate, TemplateVersion } from "../../services/templateApi";
import { API_BASE_URL } from "../../services/api";
import AccessibleModal from "../AccessibleModal";
import Button from "../../ui/Button";
import StatusBadge from "../../ui/StatusBadge";
import { ErrorState, Skeleton } from "../../ui/Feedback";

function bgUrl(version: TemplateVersion): string {
  return `${API_BASE_URL.replace(/\/$/, "")}${version.background_url}`;
}

export function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "—"
    : parsed.toLocaleString("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
}

interface TemplateHistoryDialogProps {
  template: CertificateTemplate | null;
  versions: TemplateVersion[] | null;
  loading: boolean;
  error: string;
  canManage: boolean;
  onDuplicate: (version: TemplateVersion) => void;
  onRetry: () => void;
  onClose: () => void;
}

export default function TemplateHistoryDialog({
  template,
  versions,
  loading,
  error,
  canManage,
  onDuplicate,
  onRetry,
  onClose,
}: TemplateHistoryDialogProps) {
  const [compare, setCompare] = useState<[number | null, number | null]>([null, null]);

  useEffect(() => {
    if (!versions) return;
    setCompare([versions[0]?.id ?? null, versions[1]?.id ?? null]);
  }, [versions]);

  const byId = (id: number | null) => versions?.find((version) => version.id === id) ?? null;

  return (
    <AccessibleModal
      open={Boolean(template)}
      title={template ? `Histórico de “${template.name}”` : "Histórico"}
      description="Cada revisão guarda o layout exato com que os certificados daquela época foram emitidos. A revisão atual é a que o editor abre."
      size="lg"
      onClose={onClose}
      footer={
        <Button variant="secondary" onClick={onClose}>
          Fechar
        </Button>
      }
    >
      {loading && (
        <div className="space-y-3">
          {[0, 1].map((row) => (
            <Skeleton key={row} className="h-14" />
          ))}
        </div>
      )}
      {!loading && error && <ErrorState description={error} onRetry={onRetry} />}
      {!loading && !error && versions && (
        <>
          <ul className="divide-y divide-[color:var(--line)] rounded-[var(--radius)] border border-[color:var(--line)]">
            {versions.map((version) => (
              <li
                key={version.id}
                className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-center"
              >
                <img
                  src={bgUrl(version)}
                  alt=""
                  className="h-12 w-20 shrink-0 rounded-[var(--radius)] border border-[color:var(--line)] object-contain"
                />
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-[color:var(--ink)]">
                    Revisão {version.version_number}
                    {version.name ? ` — ${version.name}` : ""}
                  </p>
                  <p className="mt-0.5 text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
                    Criada em {formatDateTime(version.created_at)} ·{" "}
                    {version.image_width} × {version.image_height} px
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {version.is_active && <StatusBadge tone="ok">Em uso nas emissões</StatusBadge>}
                  {version.is_current && !version.is_active && (
                    <StatusBadge tone="info">Atual</StatusBadge>
                  )}
                  {canManage && !version.is_current && (
                    <Button
                      size="sm"
                      variant="ghost"
                      icon="duplicate"
                      onClick={() => onDuplicate(version)}
                    >
                      Duplicar esta revisão
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>

          {versions.length > 1 && (
            <div className="mt-5">
              <h3 className="text-[length:var(--text-sm)] font-semibold text-[color:var(--ink)]">
                Comparar duas revisões
              </h3>
              <div className="mt-2 grid gap-4 sm:grid-cols-2">
                {([0, 1] as const).map((slot) => {
                  const chosen = byId(compare[slot]);
                  return (
                    <div key={slot}>
                      <label
                        htmlFor={`compare-${slot}`}
                        className="text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]"
                      >
                        {slot === 0 ? "Revisão A" : "Revisão B"}
                      </label>
                      <select
                        id={`compare-${slot}`}
                        value={compare[slot] ?? ""}
                        onChange={(event) => {
                          const next: [number | null, number | null] = [...compare];
                          next[slot] = Number(event.target.value) || null;
                          setCompare(next);
                        }}
                        className="mt-1 h-10 w-full rounded-[var(--radius)] border border-[color:var(--line-strong)] bg-[var(--surface)] px-2.5 text-[length:var(--text-sm)]"
                      >
                        {versions.map((version) => (
                          <option key={version.id} value={version.id}>
                            Revisão {version.version_number}
                            {version.name ? ` — ${version.name}` : ""}
                            {version.is_active ? " (em uso)" : ""}
                          </option>
                        ))}
                      </select>
                      {chosen && (
                        <img
                          src={bgUrl(chosen)}
                          alt={`Arte da revisão ${chosen.version_number}`}
                          className="mt-2 w-full rounded-[var(--radius)] border border-[color:var(--line)] object-contain"
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </AccessibleModal>
  );
}
