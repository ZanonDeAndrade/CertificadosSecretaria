import { useState } from "react";
import { validateCertificate, ValidationResult } from "../services/api";

function ValidateCertificate() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleValidate = async () => {
    const trimmed = code.trim();
    if (!trimmed) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const data = await validateCertificate(trimmed);
      setResult(data);
    } catch {
      setError("Erro ao consultar o servidor. Tente novamente.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="space-y-6">
      <div className="space-y-1">
        <p className="text-sm font-semibold uppercase tracking-[0.24em] text-sky-700">
          Autenticidade
        </p>
        <h2 className="text-2xl font-semibold text-slate-950">
          Validar certificado
        </h2>
        <p className="text-sm text-slate-500">
          Digite o código no formato CERT-ANO-XXXXXX impresso no certificado.
        </p>
      </div>

      <div className="flex flex-col gap-3 sm:flex-row">
        <input
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleValidate()}
          placeholder="Ex: CERT-2026-AB1234"
          aria-label="Código de validação do certificado"
          maxLength={24}
          className="flex-1 rounded-2xl border border-slate-200 bg-white px-4 py-3 font-mono text-sm text-slate-900 placeholder-slate-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
        />
        <button
          type="button"
          onClick={handleValidate}
          disabled={loading || !code.trim()}
          className="inline-flex items-center justify-center rounded-full bg-sky-600 px-6 py-3 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          {loading ? "Consultando..." : "Validar"}
        </button>
      </div>

      {error && (
        <div className="rounded-[1.75rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
          {error}
        </div>
      )}

      {result && (
        result.valid && !result.revoked ? (
          <div className="rounded-[1.75rem] border border-emerald-200 bg-emerald-50/90 p-5 space-y-2">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-emerald-700">
              Certificado válido
            </p>
            <p className="text-lg font-semibold text-slate-950">{result.name}</p>
            <p className="text-sm text-slate-600">{result.event}</p>
            <p className="text-sm text-slate-500">{result.issued_at ?? result.date}</p>
            {result.certificate_text && (
              <div className="certificate-text text-slate-700">
                {result.certificate_text}
              </div>
            )}
          </div>
        ) : result.revoked ? (
          <div className="rounded-[1.75rem] border border-rose-200 bg-rose-50/90 p-5 space-y-2">
            <p className="text-sm font-semibold uppercase tracking-[0.2em] text-rose-700">
              Certificado revogado
            </p>
            <p className="text-lg font-semibold text-slate-950">{result.name}</p>
            <p className="text-sm text-slate-600">{result.event}</p>
            <p className="text-sm text-slate-500">{result.issued_at ?? result.date}</p>
          </div>
        ) : (
          <div className="rounded-[1.75rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
            Código inválido — certificado não encontrado.
          </div>
        )
      )}
    </section>
  );
}

export default ValidateCertificate;
