/**
 * Validar certificado — the counter tool.
 *
 * Someone is standing in front of the operator asking whether a printed
 * certificate is genuine, so the answer must be unmistakable: a full-width
 * verdict block with an icon, a heading and a sentence, never a colour alone.
 *
 * This calls the SAME public endpoint the student-facing site uses, so what the
 * operator sees is exactly what the person holding the paper would see.
 */
import { FormEvent, useState } from "react";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader, PanelBody } from "../ui/Panel";
import Button from "../ui/Button";
import Icon, { IconName } from "../ui/Icon";
import { Field, TextInput } from "../ui/Field";
import { cn } from "../ui/cn";
import { classifyError, validateCertificate, ValidationResult } from "../services/api";
import { certificateTypeLabel } from "../domain/certificateTypes";

type Verdict = "valid" | "revoked" | "missing" | "rate-limited" | "unavailable";

const VERDICTS: Record<
  Verdict,
  { icon: IconName; title: string; message: string; className: string }
> = {
  valid: {
    icon: "success",
    title: "Certificado válido",
    message:
      "Este código consta no registro oficial e o certificado está ativo.",
    className: "border-[color:var(--ok-line)] bg-[var(--ok-bg)] text-[color:var(--ok-fg)]",
  },
  revoked: {
    icon: "revoked",
    title: "Certificado revogado",
    message:
      "O registro existe, mas o certificado foi cancelado pela secretaria e não é mais válido.",
    className:
      "border-[color:var(--danger-line)] bg-[var(--danger-bg)] text-[color:var(--danger-fg)]",
  },
  missing: {
    icon: "error",
    title: "Código não encontrado",
    message:
      "Nenhum certificado corresponde a este código. Confira a digitação — o formato é CERT-ANO-XXXXXX.",
    className:
      "border-[color:var(--danger-line)] bg-[var(--danger-bg)] text-[color:var(--danger-fg)]",
  },
  "rate-limited": {
    icon: "clock",
    title: "Muitas consultas seguidas",
    message:
      "O serviço limitou temporariamente as consultas. Aguarde alguns instantes e tente novamente.",
    className: "border-[color:var(--warn-line)] bg-[var(--warn-bg)] text-[color:var(--warn-fg)]",
  },
  unavailable: {
    icon: "offline",
    title: "Não foi possível consultar agora",
    message:
      "O serviço de validação não respondeu. Nenhuma informação do certificado foi exibida. Tente novamente em instantes.",
    className: "border-[color:var(--warn-line)] bg-[var(--warn-bg)] text-[color:var(--warn-fg)]",
  },
};

export default function ValidateCertificate() {
  const [code, setCode] = useState("");
  const [result, setResult] = useState<ValidationResult | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = code.trim();
    if (!trimmed) return;
    setLoading(true);
    setResult(null);
    setVerdict(null);
    try {
      const data = await validateCertificate(trimmed);
      setResult(data);
      setVerdict(data.revoked ? "revoked" : data.valid ? "valid" : "missing");
    } catch (requestError) {
      const failure = classifyError(requestError);
      setVerdict(failure === "rate-limited" ? "rate-limited" : "unavailable");
    } finally {
      setLoading(false);
    }
  };

  const spec = verdict ? VERDICTS[verdict] : null;
  const showDetails = verdict === "valid" || verdict === "revoked";

  return (
    <>
      <PageHeader
        title="Validar certificado"
        description="Confira a autenticidade de um certificado pelo código impresso nele."
      />

      <div className="grid gap-4 lg:grid-cols-[22rem_minmax(0,1fr)] lg:items-start">
        <Panel role="search">
          <PanelHeader title="Código de validação" />
          <PanelBody>
            <form onSubmit={handleSubmit} className="space-y-3">
              <Field
                label="Código do certificado"
                hint="Formato CERT-ANO-XXXXXX, impresso no rodapé do certificado."
              >
                {(props) => (
                  <TextInput
                    {...props}
                    value={code}
                    maxLength={24}
                    autoComplete="off"
                    autoCapitalize="characters"
                    spellCheck={false}
                    className="font-[family-name:var(--font-mono)] uppercase"
                    onChange={(event) => setCode(event.target.value)}
                  />
                )}
              </Field>
              <Button
                type="submit"
                variant="primary"
                icon="verify"
                block
                loading={loading}
                disabled={!code.trim()}
              >
                {loading ? "Consultando…" : "Validar"}
              </Button>
            </form>
          </PanelBody>
        </Panel>

        <div>
          {!spec ? (
            <Panel>
              <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-[var(--radius-md)] border border-[color:var(--line)] bg-[var(--surface-sunken)] text-[color:var(--ink-muted)]">
                  <Icon name="verify" size={22} />
                </span>
                <p className="text-[length:var(--text-md)] font-semibold text-[color:var(--ink)]">
                  Nenhuma consulta ainda
                </p>
                <p className="max-w-[46ch] text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  Informe o código ao lado para conferir se o certificado é
                  autêntico e continua válido.
                </p>
              </div>
            </Panel>
          ) : (
            <div className="space-y-4">
              <div
                role="status"
                aria-live="polite"
                className={cn(
                  "flex items-start gap-3 rounded-[var(--radius-md)] border p-4 sm:p-5",
                  spec.className,
                )}
              >
                <Icon name={spec.icon} size={24} className="mt-0.5 shrink-0" />
                <div className="min-w-0">
                  <p className="text-[length:var(--text-lg)] font-semibold">
                    {spec.title}
                  </p>
                  <p className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ink)]">
                    {spec.message}
                  </p>
                </div>
              </div>

              {showDetails && result && (
                <Panel>
                  <PanelHeader title="Dados do certificado" />
                  <PanelBody>
                    <dl className="divide-y divide-[color:var(--line)]">
                      <DetailRow label="Participante" value={result.name} />
                      <DetailRow label="Curso ou evento" value={result.event} />
                      <DetailRow
                        label="Tipo do certificado"
                        value={certificateTypeLabel(
                          result.certificate_type,
                          result.certificate_type_label,
                        )}
                      />
                      <DetailRow
                        label="Data de emissão"
                        value={result.issued_at ?? result.date}
                      />
                      <DetailRow label="Código consultado" value={code.trim()} mono />
                    </dl>

                    {result.certificate_text && (
                      <div className="mt-4 border-t border-[color:var(--line)] pt-4">
                        <p className="text-[length:var(--text-xs)] font-semibold uppercase tracking-[0.04em] text-[color:var(--ink-muted)]">
                          Texto do certificado
                        </p>
                        <p className="certificate-text text-[color:var(--ink)]">
                          {result.certificate_text}
                        </p>
                      </div>
                    )}
                  </PanelBody>
                </Panel>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function DetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value?: string | null;
  mono?: boolean;
}) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[11rem_1fr] sm:items-baseline sm:gap-4">
      <dt className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">{label}</dt>
      <dd
        className={cn(
          "min-w-0 break-words text-[length:var(--text-sm)] text-[color:var(--ink)]",
          mono && "font-[family-name:var(--font-mono)]",
        )}
      >
        {value || "—"}
      </dd>
    </div>
  );
}
