import { useEffect, useState } from "react";
import axios from "axios";
import {
  API_BASE_URL,
  GenerationSummary,
  SpreadsheetPreview,
  generateCertificatesFromSpreadsheet,
  validateSpreadsheet,
} from "../services/api";
import { listVisualTemplates } from "../services/visualTemplateApi";
import { VisualTemplate } from "../types/template";

type Step = "upload" | "preview" | "done";

function EmitirCertificados() {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dataEmissao, setDataEmissao] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [visualTemplates, setVisualTemplates] = useState<VisualTemplate[]>([]);
  const [preview, setPreview] = useState<SpreadsheetPreview | null>(null);
  const [summary, setSummary] = useState<GenerationSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    listVisualTemplates().then(setVisualTemplates).catch(() => {});
  }, []);

  const reset = () => {
    setStep("upload");
    setFile(null);
    setPreview(null);
    setSummary(null);
    setError("");
  };

  const handleValidate = async () => {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const result = await validateSpreadsheet(file, dataEmissao || undefined);
      setPreview(result);
      setStep("preview");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const handleGenerate = async () => {
    if (!file) return;
    setLoading(true);
    setError("");
    try {
      const result = await generateCertificatesFromSpreadsheet(
        file,
        dataEmissao || undefined,
        templateId || undefined,
      );
      setSummary(result);
      setStep("done");
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="space-y-6">
      <div className="space-y-1">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-700">
          Emissão em lote
        </p>
        <h2 className="text-2xl font-semibold text-slate-950">
          Emitir certificados por planilha
        </h2>
        <p className="text-sm text-slate-500">
          Colunas aceitas: <strong>nome, curso, evento, carga_horaria, data_emissao</strong>{" "}
          (e opcionais: email, documento, data_inicio, data_fim).
        </p>
      </div>

      {error && (
        <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
          {error}
        </div>
      )}

      {step === "upload" && (
        <div className="space-y-4 rounded-[1.75rem] border border-slate-200/80 bg-white/88 p-6">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Planilha (.xlsx)</span>
            <input
              type="file"
              accept=".xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm text-slate-700 file:mr-3 file:rounded-lg file:border-0 file:bg-sky-50 file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-sky-700 hover:file:bg-sky-100"
            />
          </label>

          <label className="flex flex-col gap-1.5 md:max-w-sm">
            <span className="text-sm font-medium text-slate-700">
              Data de emissão padrão (opcional)
            </span>
            <input
              type="text"
              value={dataEmissao}
              onChange={(e) => setDataEmissao(e.target.value)}
              placeholder="Ex.: 10/06/2026 (usada quando a linha não tem data)"
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-400"
            />
          </label>

          {visualTemplates.length > 0 && (
            <label className="flex flex-col gap-1.5 md:max-w-sm">
              <span className="text-sm font-medium text-slate-700">
                Template visual (opcional)
              </span>
              <select
                value={templateId}
                onChange={(e) => setTemplateId(e.target.value)}
                className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-400"
              >
                <option value="">— Layout padrão —</option>
                {visualTemplates.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
          )}

          <button
            type="button"
            onClick={handleValidate}
            disabled={!file || loading}
            className="inline-flex items-center justify-center rounded-full bg-slate-950 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {loading ? "Validando..." : "Validar planilha"}
          </button>
        </div>
      )}

      {step === "preview" && preview && (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-3">
            <StatCard label="Total de linhas" value={preview.total} tone="slate" />
            <StatCard label="Aptas para gerar" value={preview.valid_count} tone="emerald" />
            <StatCard label="Com erro" value={preview.invalid_count} tone="rose" />
          </div>

          {preview.valid_count > 0 && (
            <div className="overflow-x-auto rounded-[1.5rem] border border-slate-200/80 bg-white/90">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Nome</th>
                    <th className="px-4 py-2">Curso</th>
                    <th className="px-4 py-2">Evento</th>
                    <th className="px-4 py-2">Carga</th>
                    <th className="px-4 py-2">Emissão</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.valid.slice(0, 50).map((r) => (
                    <tr key={r.row_number} className="border-t border-slate-100">
                      <td className="px-4 py-2 text-slate-900">{r.nome}</td>
                      <td className="px-4 py-2 text-slate-600">{r.curso}</td>
                      <td className="px-4 py-2 text-slate-600">{r.evento}</td>
                      <td className="px-4 py-2 text-slate-600">{r.carga_horaria}h</td>
                      <td className="px-4 py-2 text-slate-600">{r.data_emissao}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {preview.invalid_count > 0 && (
            <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50/70 p-4">
              <p className="mb-2 text-sm font-semibold text-rose-800">
                Linhas com erro (não serão geradas)
              </p>
              <ul className="space-y-1 text-sm text-rose-700">
                {preview.invalid.slice(0, 50).map((r) => (
                  <li key={r.row_number}>
                    <span className="font-medium">Linha {r.row_number}:</span>{" "}
                    {r.errors.join("; ")}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex gap-3">
            <button
              type="button"
              onClick={handleGenerate}
              disabled={loading || preview.valid_count === 0}
              className="inline-flex items-center justify-center rounded-full bg-emerald-700 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-600 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {loading ? "Gerando..." : `Gerar ${preview.valid_count} certificado(s)`}
            </button>
            <button
              type="button"
              onClick={reset}
              className="inline-flex items-center justify-center rounded-full border border-slate-300 bg-white px-6 py-2.5 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
            >
              Trocar arquivo
            </button>
          </div>
        </div>
      )}

      {step === "done" && summary && (
        <div className="space-y-5">
          <div className="flex flex-wrap gap-3">
            <StatCard label="Gerados" value={summary.generated_count} tone="emerald" />
            <StatCard label="Duplicados (ignorados)" value={summary.duplicate_count} tone="amber" />
            <StatCard label="Inválidos" value={summary.invalid_count} tone="rose" />
          </div>

          {summary.generated.length > 0 && (
            <div className="overflow-x-auto rounded-[1.5rem] border border-slate-200/80 bg-white/90">
              <table className="w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-4 py-2">Nome</th>
                    <th className="px-4 py-2">Código</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.generated.map((g) => (
                    <tr key={g.code} className="border-t border-slate-100">
                      <td className="px-4 py-2 text-slate-900">{g.name}</td>
                      <td className="px-4 py-2 font-mono text-slate-700">{g.code}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {summary.duplicates.length > 0 && (
            <div className="rounded-[1.5rem] border border-amber-200 bg-amber-50/70 p-4 text-sm text-amber-800">
              <p className="mb-2 font-semibold">Já existiam (não duplicados):</p>
              <ul className="space-y-1">
                {summary.duplicates.map((d, i) => (
                  <li key={i}>
                    {d.name} — <span className="font-mono">{d.existing_code}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <button
            type="button"
            onClick={reset}
            className="inline-flex items-center justify-center rounded-full bg-slate-950 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            Emitir outra planilha
          </button>
        </div>
      )}
    </section>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "slate" | "emerald" | "rose" | "amber";
}) {
  const tones: Record<string, string> = {
    slate: "border-slate-200 bg-slate-50 text-slate-900",
    emerald: "border-emerald-200 bg-emerald-50 text-emerald-800",
    rose: "border-rose-200 bg-rose-50 text-rose-800",
    amber: "border-amber-200 bg-amber-50 text-amber-800",
  };
  return (
    <div className={`min-w-[10rem] flex-1 rounded-2xl border p-4 ${tones[tone]}`}>
      <p className="text-3xl font-semibold">{value}</p>
      <p className="text-xs font-medium uppercase tracking-wide opacity-80">{label}</p>
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (!error.response) return `Não foi possível conectar ao backend em ${API_BASE_URL}.`;
  }
  return "Ocorreu um erro. Tente novamente.";
}

export default EmitirCertificados;
