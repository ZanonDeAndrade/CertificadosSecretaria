/**
 * "Dados do modelo": name, certificate type and course of the model being
 * edited. Lives in a dialog so the toolbar keeps one row on a notebook.
 *
 * The type locks once the model issued certificates or was ever active (the
 * layout would be re-aimed at another type); the operator duplicates instead.
 * The course only files the model in the list, and the dialog says so.
 */
import { CERTIFICATE_TYPES } from "../../domain/certificateTypes";
import { Course } from "../../services/templateApi";
import AccessibleModal from "../AccessibleModal";
import Alert from "../../ui/Alert";
import Button from "../../ui/Button";
import { Field, Select, TextInput } from "../../ui/Field";

export interface ModelDetails {
  name: string;
  certificateType: string | null;
  courseId: number | null;
}

interface ModelDetailsDialogProps {
  open: boolean;
  details: ModelDetails;
  courses: Course[];
  typeLocked: boolean;
  onChange: (details: ModelDetails) => void;
  onClose: () => void;
}

export default function ModelDetailsDialog({
  open,
  details,
  courses,
  typeLocked,
  onChange,
  onClose,
}: ModelDetailsDialogProps) {
  // An inactive course a model still points at stays selectable here.
  const options = courses.filter(
    (course) => course.is_active || course.id === details.courseId,
  );
  return (
    <AccessibleModal
      open={open}
      title="Dados do modelo"
      description="Nome, tipo de certificado e curso. As alterações valem ao salvar o modelo."
      onClose={onClose}
      footer={
        <Button variant="primary" onClick={onClose}>
          Pronto
        </Button>
      }
    >
      <div className="space-y-4">
        <Field label="Nome">
          {(props) => (
            <TextInput
              {...props}
              value={details.name}
              maxLength={255}
              autoComplete="off"
              onChange={(event) => onChange({ ...details, name: event.target.value })}
            />
          )}
        </Field>

        <Field
          label="Tipo"
          hint={
            typeLocked
              ? "O tipo não muda mais: este modelo já emitiu certificados ou já esteve ativo. Para outro tipo, duplique o modelo."
              : "Um modelo de um tipo vale só para lotes desse tipo; o genérico vale para os tipos sem modelo próprio ativo."
          }
        >
          {(props) => (
            <Select
              {...props}
              value={details.certificateType ?? ""}
              disabled={typeLocked}
              onChange={(event) =>
                onChange({ ...details, certificateType: event.target.value || null })
              }
            >
              <option value="">Genérico (todos os tipos)</option>
              {CERTIFICATE_TYPES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Field label="Curso">
          {(props) => (
            <Select
              {...props}
              value={details.courseId ?? ""}
              onChange={(event) =>
                onChange({
                  ...details,
                  courseId: event.target.value ? Number(event.target.value) : null,
                })
              }
            >
              <option value="">Todos os cursos</option>
              {options.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.name}
                  {course.is_active ? "" : " (inativo)"}
                </option>
              ))}
            </Select>
          )}
        </Field>

        <Alert tone="info" live={false}>
          O curso só organiza a lista de modelos. A emissão continua escolhendo o modelo
          ativo pelo tipo de certificado, não pelo curso.
        </Alert>
      </div>
    </AccessibleModal>
  );
}
