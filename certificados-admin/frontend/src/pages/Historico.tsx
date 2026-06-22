import { useCallback, useEffect, useRef, useState } from "react";
import AccessibleModal from "../components/AccessibleModal";
import {
  AdminCertificate,
  downloadCertificateFile,
  downloadCertificatesZip,
  getApiErrorMessage,
  listCertificates,
  revokeCertificate,
} from "../services/api";

const PAGE_SIZE = 20;

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function canDownload(cert: AdminCertificate) {
  return cert.status === "ativo" && cert.download_available;
}

export default function Historico() {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [course, setCourse] = useState("");
  const [event, setEvent] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(0);
  const [items, setItems] = useState<AdminCertificate[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [downloadStatus, setDownloadStatus] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<AdminCertificate | null>(null);
  const [reason, setReason] = useState("");
  const [revokeError, setRevokeError] = useState("");
  const [revoking, setRevoking] = useState(false);
  const reasonRef = useRef<HTMLTextAreaElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listCertificates({
        name: name || undefined,
        code: code || undefined,
        course: course || undefined,
        event: event || undefined,
        status: status || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (requestError) {
      setError(getApiErrorMessage(requestError, "Não foi possível carregar os certificados."));
    } finally {
      setLoading(false);
    }
  }, [name, code, course, event, status, page]);

  useEffect(() => void load(), [load]);

  const availableOnPage = items.filter(canDownload).map((item) => item.unique_code);
  const pageSelected =
    availableOnPage.length > 0 && availableOnPage.every((item) => selected.has(item));
  const totalPages = Math.ceil(total / PAGE_SIZE);

  const toggle = (codeToToggle: string) => {
    if (!selected.has(codeToToggle) && selected.size >= 200) {
      setDownloadStatus("Selecione no máximo 200 certificados por arquivo ZIP.");
      return;
    }
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(codeToToggle)) next.delete(codeToToggle);
      else next.add(codeToToggle);
      return next;
    });
  };

  const togglePage = () => {
    setSelected((current) => {
      const next = new Set(current);
      availableOnPage.forEach((item) => {
        if (pageSelected) next.delete(item);
        else if (next.size < 200) next.add(item);
      });
      return next;
    });
  };

  const handleBatchDownload = async () => {
    if (!selected.size) return;
    setDownloading(true);
    setProgress(null);
    setDownloadStatus("");
    try {
      const result = await downloadCertificatesZip([...selected], setProgress);
      saveBlob(result.blob, "certificados.zip");
      if (result.skippedCodes.length) {
        setDownloadStatus(
          `ZIP gerado parcialmente. ${result.skippedCodes.length} certificado(s) ficaram indisponíveis: ${result.skippedCodes.join(", ")}.`,
        );
      } else {
        setDownloadStatus(`${selected.size} certificado(s) baixados com sucesso.`);
      }
      setSelected(new Set());
    } catch (requestError) {
      setDownloadStatus(
        getApiErrorMessage(requestError, "Não foi possível gerar o arquivo ZIP."),
      );
    } finally {
      setDownloading(false);
      setProgress(null);
    }
  };

  const handleSingleDownload = async (cert: AdminCertificate) => {
    setDownloadStatus("");
    try {
      const blob = await downloadCertificateFile(cert.unique_code);
      saveBlob(blob, `${cert.participant_name.replace(/[^\p{L}\p{N}._-]+/gu, "_")}.pdf`);
    } catch (requestError) {
      setDownloadStatus(
        getApiErrorMessage(requestError, "Não foi possível baixar o certificado."),
      );
    }
  };

  const openRevoke = (cert: AdminCertificate) => {
    setRevokeTarget(cert);
    setReason("");
    setRevokeError("");
  };

  const closeRevoke = () => {
    if (!revoking) setRevokeTarget(null);
  };

  const confirmRevoke = async () => {
    if (!revokeTarget) return;
    const cleanReason = reason.trim();
    if (cleanReason.length < 5) {
      setRevokeError("Informe um motivo com pelo menos 5 caracteres.");
      reasonRef.current?.focus();
      return;
    }
    setRevoking(true);
    setRevokeError("");
    try {
      await revokeCertificate(revokeTarget.unique_code, cleanReason);
      setSelected((current) => {
        const next = new Set(current);
        next.delete(revokeTarget.unique_code);
        return next;
      });
      setRevokeTarget(null);
      await load();
    } catch (requestError) {
      setRevokeError(getApiErrorMessage(requestError, "Não foi possível revogar o certificado."));
    } finally {
      setRevoking(false);
    }
  };

  return (
    <section className="space-y-6">
      <div className="space-y-1">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-700">Histórico</p>
        <h2 className="text-2xl font-semibold text-slate-950">Certificados emitidos</h2>
      </div>

      <div className="grid gap-3 rounded-[1.5rem] border border-slate-200/80 bg-white/88 p-4 md:grid-cols-5">
        {[
          ["Nome", name, setName],
          ["Código", code, setCode],
          ["Curso", course, setCourse],
          ["Evento", event, setEvent],
        ].map(([label, value, setter]) => (
          <input
            key={label as string}
            value={value as string}
            onChange={(input) => (setter as (value: string) => void)(input.target.value)}
            onKeyDown={(key) => key.key === "Enter" && setPage(0)}
            placeholder={label as string}
            aria-label={`Buscar por ${(label as string).toLowerCase()}`}
            className={`rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400 ${label === "Código" ? "font-mono" : ""}`}
          />
        ))}
        <select value={status} onChange={(input) => { setStatus(input.target.value); setPage(0); }} aria-label="Filtrar por status" className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400">
          <option value="">Todos os status</option>
          <option value="ativo">Ativo</option>
          <option value="revogado">Revogado</option>
        </select>
        <button type="button" onClick={() => setPage(0)} className="rounded-full bg-slate-950 px-5 py-2 text-sm font-semibold text-white hover:bg-slate-800">Buscar</button>
      </div>

      {error && <div role="alert" className="rounded-[1.5rem] border border-rose-200 bg-rose-50 p-4 text-sm font-medium text-rose-800">{error}</div>}

      <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <button type="button" onClick={togglePage} disabled={!availableOnPage.length} className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium disabled:opacity-40">
          {pageSelected ? "Remover página" : "Selecionar página"}
        </button>
        <button type="button" onClick={() => setSelected(new Set())} disabled={!selected.size} className="rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-medium disabled:opacity-40">Limpar seleção</button>
        <button type="button" onClick={handleBatchDownload} disabled={!selected.size || downloading} className="rounded-full bg-sky-700 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300">
          {downloading ? "Gerando ZIP…" : `Baixar ZIP (${selected.size})`}
        </button>
        {downloading && (
          <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-slate-600">
            <progress value={progress ?? undefined} max={100} aria-label="Progresso do download" />
            {progress == null ? "Recebendo arquivo…" : `${progress}%`}
          </div>
        )}
      </div>
      {downloadStatus && <div role="status" aria-live="polite" className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{downloadStatus}</div>}

      <div className="overflow-x-auto rounded-[1.5rem] border border-slate-200/80 bg-white/90">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2"><span className="sr-only">Selecionar</span></th>
              <th className="px-4 py-2">Nome</th><th className="px-4 py-2">Curso</th><th className="px-4 py-2">Evento</th><th className="px-4 py-2">Emissão</th><th className="px-4 py-2">Código</th><th className="px-4 py-2">Status</th><th className="px-4 py-2">Ações</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !loading ? (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-slate-400">Nenhum certificado encontrado.</td></tr>
            ) : items.map((cert) => {
              const available = canDownload(cert);
              return (
                <tr key={cert.unique_code} className="border-t border-slate-100">
                  <td className="px-4 py-2"><input type="checkbox" checked={selected.has(cert.unique_code)} disabled={!available} onChange={() => toggle(cert.unique_code)} aria-label={`Selecionar certificado de ${cert.participant_name}`} /></td>
                  <td className="px-4 py-2 text-slate-900">{cert.participant_name}</td>
                  <td className="px-4 py-2 text-slate-600">{cert.course_name}</td>
                  <td className="px-4 py-2 text-slate-600">{cert.event_name}</td>
                  <td className="px-4 py-2 text-slate-600">{cert.issue_date}</td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-700">{cert.unique_code}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${cert.status === "revogado" ? "bg-rose-100 text-rose-700" : available ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>
                      {cert.status === "revogado" ? "Revogado" : available ? "Ativo" : "Indisponível"}
                    </span>
                  </td>
                  <td className="px-4 py-2"><div className="flex gap-2">
                    <button type="button" disabled={!available} onClick={() => handleSingleDownload(cert)} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium disabled:opacity-40">Baixar</button>
                    {cert.status !== "revogado" && <button type="button" onClick={() => openRevoke(cert)} className="rounded-full border border-rose-200 px-3 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50">Revogar</button>}
                  </div></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">{total} certificado(s){loading ? " · carregando…" : ""}</p>
        {totalPages > 1 && <div className="flex items-center gap-3">
          <button type="button" onClick={() => setPage((current) => Math.max(0, current - 1))} disabled={page === 0} className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-sm disabled:opacity-40">← Anterior</button>
          <span className="text-sm text-slate-500">Página {page + 1} de {totalPages}</span>
          <button type="button" onClick={() => setPage((current) => current + 1 < totalPages ? current + 1 : current)} disabled={page + 1 >= totalPages} className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-sm disabled:opacity-40">Próxima →</button>
        </div>}
      </div>

      <AccessibleModal
        open={Boolean(revokeTarget)}
        title="Revogar certificado"
        onClose={closeRevoke}
        initialFocusRef={reasonRef}
        footer={<>
          <button type="button" onClick={closeRevoke} disabled={revoking} className="rounded-full border border-slate-300 px-4 py-2 text-sm">Cancelar</button>
          <button type="button" onClick={confirmRevoke} disabled={revoking || reason.trim().length < 5} className="rounded-full bg-rose-700 px-5 py-2 text-sm font-semibold text-white disabled:bg-slate-300">{revoking ? "Revogando…" : "Confirmar revogação"}</button>
        </>}
      >
        <p className="text-sm text-slate-600">Esta ação impede o download de <strong>{revokeTarget?.participant_name}</strong>. Informe o motivo obrigatório.</p>
        <label className="mt-4 block text-sm font-medium text-slate-800" htmlFor="revoke-reason">Motivo</label>
        <textarea ref={reasonRef} id="revoke-reason" value={reason} onChange={(input) => setReason(input.target.value)} minLength={5} maxLength={500} rows={4} aria-describedby="revoke-help revoke-error" className="mt-1 w-full rounded-xl border border-slate-300 p-3 focus:outline-none focus:ring-2 focus:ring-rose-500" />
        <p id="revoke-help" className="mt-1 text-xs text-slate-500">Entre 5 e 500 caracteres.</p>
        {revokeError && <p id="revoke-error" role="alert" className="mt-2 text-sm font-medium text-rose-700">{revokeError}</p>}
      </AccessibleModal>
    </section>
  );
}
