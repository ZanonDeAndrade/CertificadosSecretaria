/**
 * Says, inside the editor, what a template for a per-work type still needs.
 * The emission of such a type is blocked while its active template has the
 * participant name or lacks the authors block or the body, so the person
 * editing learns it here rather than at the batch review.
 */
import { certificateTypeLabel, isPerWorkType } from "../../domain/certificateTypes";
import { PER_WORK_PROBLEM_LABELS, perWorkProblems } from "../../domain/perWorkTemplate";
import { TemplateElement } from "../../types/template";
import Alert from "../../ui/Alert";

interface PerWorkNoticeProps {
  certificateType: string | null;
  elements: TemplateElement[];
}

export default function PerWorkNotice({ certificateType, elements }: PerWorkNoticeProps) {
  if (!isPerWorkType(certificateType)) return null;
  const label = certificateTypeLabel(certificateType);
  const problems = perWorkProblems(elements);

  if (problems.length === 0) {
    return (
      <Alert tone="info" live={false} className="rounded-none border-x-0">
        {label}: um certificado por trabalho, válido para todos os autores. Sem nome
        do participante; o Corpo fala do trabalho e do evento, e o bloco Autores cresce
        para cima a partir da base, acima do QR Code. Ajuste, salve e ative a versão.
      </Alert>
    );
  }
  const steps = problems.map((problem) => PER_WORK_PROBLEM_LABELS[problem]);
  return (
    <Alert tone="warn" live={false} className="rounded-none border-x-0">
      Para emitir {label}, {steps.join("; ")}. Enquanto isso, os lotes deste tipo
      ficam bloqueados na Conferência.
    </Alert>
  );
}
