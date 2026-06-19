import { useCallback, useEffect, useState } from "react";
import {
  AdminCertificate,
  certificateFileUrl,
  listCertificates,
  revokeCertificate,
} from "../services/api";

const PAGE_SIZE = 20;

function Historico() {
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
    } catch {
      setError("Não foi possível carregar os certificados.");
    } finally {
      setLoading(false);
    }
  }, [name, code, course, event, status, page]);

  useEffect(() => {
    load();
  }, [load]);

  const handleSearch = () => {
    setPage(0);
    load();
  };

  const handleRevoke = async (cert: AdminCertificate) => {
    const reason = window.prompt(
      `Revogar o certificado de ${cert.participant_name} (${cert.unique_code})?\nMotivo (opcional):`,
    );
    if (reason === null) return; // cancelled
    try {
      await revokeCertificate(cert.unique_code, reason);
      load();
    } catch {
      alert("Não foi possível revogar o certificado.");
    }
  };

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <section className="space-y-6">
      <div className="space-y-1">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-700">
          Histórico
        </p>
        <h2 className="text-2xl font-semibold text-slate-950">Certificados emitidos</h2>
      </div>

      {/* Filtros */}
      <div className="grid gap-3 rounded-[1.5rem] border border-slate-200/80 bg-white/88 p-4 md:grid-cols-5">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Nome"
          aria-label="Buscar por nome"
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
        />
        <input
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Código"
          aria-label="Buscar por código"
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-sky-400"
        />
        <input
          value={course}
          onChange={(e) => setCourse(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Curso"
          aria-label="Buscar por curso"
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
        />
        <input
          value={event}
          onChange={(e) => setEvent(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="Evento"
          aria-label="Buscar por evento"
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label="Filtrar por status"
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-400"
        >
          <option value="">Todos os status</option>
          <option value="ativo">Ativo</option>
          <option value="revogado">Revogado</option>
        </select>
        <button
          type="button"
          onClick={handleSearch}
          className="rounded-full bg-slate-950 px-5 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 md:col-span-1"
        >
          Buscar
        </button>
      </div>

      {error && (
        <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
          {error}
        </div>
      )}

      <div className="overflow-x-auto rounded-[1.5rem] border border-slate-200/80 bg-white/90">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-2">Nome</th>
              <th className="px-4 py-2">Curso</th>
              <th className="px-4 py-2">Evento</th>
              <th className="px-4 py-2">Emissão</th>
              <th className="px-4 py-2">Código</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Ações</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !loading ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-400">
                  Nenhum certificado encontrado.
                </td>
              </tr>
            ) : (
              items.map((cert) => (
                <tr key={cert.unique_code} className="border-t border-slate-100">
                  <td className="px-4 py-2 text-slate-900">{cert.participant_name}</td>
                  <td className="px-4 py-2 text-slate-600">{cert.course_name}</td>
                  <td className="px-4 py-2 text-slate-600">{cert.event_name}</td>
                  <td className="px-4 py-2 text-slate-600">{cert.issue_date}</td>
                  <td className="px-4 py-2 font-mono text-xs text-slate-700">
                    {cert.unique_code}
                  </td>
                  <td className="px-4 py-2">
                    {cert.status === "revogado" ? (
                      <span className="rounded-full bg-rose-100 px-2.5 py-1 text-xs font-semibold text-rose-700">
                        Revogado
                      </span>
                    ) : (
                      <span className="rounded-full bg-emerald-100 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                        Ativo
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex gap-2">
                      {cert.status !== "revogado" && (
                        <a
                          href={certificateFileUrl(cert.unique_code)}
                          target="_blank"
                          rel="noreferrer"
                          className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium text-slate-700 transition hover:bg-slate-100"
                        >
                          Baixar
                        </a>
                      )}
                      {cert.status !== "revogado" && (
                        <button
                          type="button"
                          onClick={() => handleRevoke(cert)}
                          className="rounded-full border border-rose-200 px-3 py-1 text-xs font-medium text-rose-600 transition hover:bg-rose-50"
                        >
                          Revogar
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-sm text-slate-500">
          {total} certificado(s){loading ? " · carregando..." : ""}
        </p>
        {totalPages > 1 && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:opacity-40"
            >
              ← Anterior
            </button>
            <span className="text-sm text-slate-500">
              Página {page + 1} de {totalPages}
            </span>
            <button
              type="button"
              onClick={() => setPage((p) => (p + 1 < totalPages ? p + 1 : p))}
              disabled={page + 1 >= totalPages}
              className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:opacity-40"
            >
              Próxima →
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

export default Historico;
