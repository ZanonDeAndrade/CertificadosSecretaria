import { useRef, useState } from "react";
import axios from "axios";
import {
  API_BASE_URL,
  GenerationSummary,
  SpreadsheetPreview,
  generateCertificatesFromSpreadsheet,
  validateSpreadsheet,
} from "../services/api";

type Step = "upload" | "preview" | "done";

// Variables the secretaria may use in the body text (must mirror the backend
// allowlist in services/certificate_text.py). Each is offered as a button that
// inserts the token at the cursor position in the textarea.
const BODY_VARIABLE_OPTIONS: { token: string; label: string }[] = [
  { token: "{{nome}}", label: "Nome" },
  { token: "{{carga_horaria}}", label: "Carga horária" },
];

// Pre-filled example shown in the field — the secretaria edits the palestra/
// palestrante part and adjusts the wording for the batch.
const DEFAULT_BODY_TEXT =
  "participou da Semana de Inovação, promovida pelo Curso de Direito da " +
  "Faculdade Antonio Meneghetti, realizada de 10 a 12 de junho de 2026, com " +
  "carga horária total de {{carga_horaria}} horas. A atividade contou com " +
  "palestra ministrada por NOME DO(A) PALESTRANTE.";

function EmitirCertificados() {
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [dataEmissao, setDataEmissao] = useState("");
  const [textoPadrao, setTextoPadrao] = useState(DEFAULT_BODY_TEXT);
  const [preview, setPreview] = useState<SpreadsheetPreview | null>(null);
  const [summary, setSummary] = useState<GenerationSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const reset = () => {
    setStep("upload");
    setFile(null);
    setTextoPadrao(DEFAULT_BODY_TEXT);
    setPreview(null);
    setSummary(null);
    setError("");
  };

  // Insert a {{variable}} at the cursor position (replacing any selection), then
  // restore focus + caret right after the inserted token.
  const insertVariable = (token: string) => {
    const el = textareaRef.current;
    const start = el ? el.selectionStart : textoPadrao.length;
    const end = el ? el.selectionEnd : textoPadrao.length;
    setTextoPadrao(textoPadrao.slice(0, start) + token + textoPadrao.slice(end));
    const caret = start + token.length;
    const restore = () => {
      const node = textareaRef.current;
      if (node) {
        node.focus();
        node.setSelectionRange(caret, caret);
      }
    };
    if (typeof requestAnimationFrame === "function") requestAnimationFrame(restore);
    else setTimeout(restore, 0);
  };

  const handleValidate = async () => {
    if (!file || !textoPadrao.trim()) return;
    setLoading(true);
    setError("");
    try {
      const result = await validateSpreadsheet(
        file,
        dataEmissao || undefined,
        textoPadrao,
      );
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
      // Send EXACTLY the same text reviewed in the preview.
      const result = await generateCertificatesFromSpreadsheet(
        file,
        dataEmissao || undefined,
        textoPadrao,
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
          Colunas obrigatórias: <strong>nome, carga_horaria</strong>. As demais
          (curso, evento, datas, email…) são opcionais — escreva o restante no
          texto padrão. Colunas extras são ignoradas.
        </p>
      </div>

      {error && (
        <div className="rounded-[1.5rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
          {error}
        </div>
      )}

      {step === "upload" && (
        <div className="space-y-4 rounded-[1.75rem] border border-slate-200/80 bg-white/88 p-6">
          <div className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Planilha (.xlsx)</span>
            <div className="flex flex-wrap items-center gap-3">
              <label
                htmlFor="spreadsheet-upload"
                className="inline-flex cursor-pointer items-center justify-center rounded-lg bg-sky-50 px-3 py-1.5 text-sm font-medium text-sky-700 transition hover:bg-sky-100"
              >
                Escolher arquivo
              </label>
              <span className="min-w-0 max-w-full truncate text-sm text-slate-600">
                {file?.name ?? "Nenhum arquivo selecionado"}
              </span>
            </div>
            <input
              id="spreadsheet-upload"
              type="file"
              accept=".xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
          </div>

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

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">
              Texto padrão do certificado <span className="text-rose-600">*</span>
            </span>
            <textarea
              ref={textareaRef}
              value={textoPadrao}
              onChange={(e) => setTextoPadrao(e.target.value)}
              rows={5}
              required
              aria-label="Texto padrão do certificado"
              placeholder="Escreva o corpo do certificado para todo o lote…"
              className="resize-y rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm leading-relaxed text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-400"
            />
            <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-500">
              <p>
                Apenas o <strong>corpo</strong> do certificado. Título, nome em
                destaque, data, assinatura, QR Code e código de validação vêm do{" "}
                <strong>template global ativo</strong> (aba “Template global”).
              </p>
              <div className="mt-2">
                <p className="mb-1.5">
                  Clique para inserir uma variável onde o cursor estiver
                  (substituída por linha):
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {BODY_VARIABLE_OPTIONS.map(({ token, label }) => (
                    <button
                      key={token}
                      type="button"
                      onClick={() => insertVariable(token)}
                      aria-label={`Inserir ${token}`}
                      title={`Inserir ${token}`}
                      className="inline-flex items-center gap-1 rounded-full border border-slate-300 bg-white px-2.5 py-1 font-medium text-slate-600 transition hover:border-sky-400 hover:bg-sky-50 hover:text-sky-700"
                    >
                      <span aria-hidden>+</span>
                      {label}
                      <code className="font-mono text-[10px] text-slate-400">
                        {token}
                      </code>
                    </button>
                  ))}
                </div>
              </div>
              <p className="mt-2">
                Exemplo: <em>participou da Semana de Inovação, com carga horária
                de {"{{carga_horaria}}"} horas.</em>
              </p>
              <p className="mt-2">
                <strong>Palestra e palestrante</strong> podem ser escritos
                diretamente no texto. <code className="font-mono">{"{{carga_horaria}}"}</code>{" "}
                resulta apenas no número — escreva “horas” você mesma.
              </p>
            </div>
          </label>

          <button
            type="button"
            onClick={handleValidate}
            disabled={!file || !textoPadrao.trim() || loading}
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

          {preview.resolved_text_preview && (
            <div className="rounded-[1.5rem] border border-sky-200 bg-sky-50/70 p-4">
              <p className="mb-2 text-sm font-semibold text-sky-900">
                Prévia do texto (1ª linha válida)
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                {preview.resolved_text_preview}
              </p>
              <p className="mt-2 text-xs text-slate-500">
                Confira o resultado das variáveis antes de emitir. Este é
                exatamente o corpo que será gerado para cada participante.
              </p>
            </div>
          )}

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
