export const CERTIFICATE_TYPES = [
  { value: "listener", label: "Ouvinte" },
  { value: "speaker", label: "Palestrante" },
  { value: "organizing_committee", label: "Comissão Organizadora" },
  { value: "teams", label: "Equipes" },
  { value: "monitoring", label: "Monitoria" },
  {
    value: "tcc_board_professor",
    label: "Professores participantes de Banca de TCC",
  },
  {
    value: "scientific_initiation",
    label: "Mostra de Iniciação Científica",
  },
] as const;

export type CertificateType = (typeof CERTIFICATE_TYPES)[number]["value"];

/** Upper bound of authors a per-work certificate carries (mirrors the backend). */
export const MAX_WORK_AUTHORS = 8;

/**
 * Behaviour a type opts into. Mirrors `database/certificate_types.py`; code
 * checks these flags, never the label text.
 */
const PER_WORK_TYPES = new Set<string>(["scientific_initiation"]);

/** One certificate per work, valid for every author listed on it. */
export function isPerWorkType(value?: string | null): boolean {
  return Boolean(value && PER_WORK_TYPES.has(value));
}

export function certificateTypeLabel(
  value?: string | null,
  backendLabel?: string | null,
): string {
  return (
    backendLabel ||
    CERTIFICATE_TYPES.find((item) => item.value === value)?.label ||
    "Tipo não informado"
  );
}
