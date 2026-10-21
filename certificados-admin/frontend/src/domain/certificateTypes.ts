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
