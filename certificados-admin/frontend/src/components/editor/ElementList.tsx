/**
 * Element panel — add fields, and select/reorder what is already on the canvas.
 *
 * The list is a listbox rather than a set of clickable <li>s, so arrow keys
 * move the selection and each row has a real role. Row actions stay visible
 * (not hover-only) for the selected row and are reachable by keyboard; the old
 * `opacity-0 group-hover` treatment hid them from touch and keyboard entirely.
 */
import { KEY_LABELS, TemplateElement, ElementKey } from "../../types/template";
import { EditorAPI } from "../../hooks/useEditorCanvas";
import { isPerWorkType } from "../../domain/certificateTypes";
import Icon from "../../ui/Icon";
import { IconButton } from "../../ui/Button";
import { cn } from "../../ui/cn";

/* Offered only on templates for per-work certificate types. */
const PER_WORK_QUICK_KEYS: { key: ElementKey; label: string; title: string }[] = [
  {
    key: "authors",
    label: "Autores",
    title:
      "Lista “Autor N: Nome” só com os autores preenchidos. A base do bloco " +
      "fica fixa e ele cresce para cima.",
  },
];

const QUICK_KEYS: { key: ElementKey; label: string; title: string }[] = [
  { key: "name", label: "Nome", title: "Nome do participante (vem da planilha)" },
  {
    key: "texto_certificado",
    label: "Corpo",
    title:
      "Onde o texto padrão escrito na emissão é impresso. Posicione este bloco " +
      "onde o parágrafo deve começar.",
  },
  { key: "event", label: "Evento", title: "Nome do evento (vem da planilha)" },
  {
    key: "certificate_type",
    label: "Tipo",
    title: "Tipo do certificado congelado no lote de emissão",
  },
  {
    key: "institution_name",
    label: "Instituição",
    title: "Nome definido nas configurações institucionais",
  },
  {
    key: "issue_line",
    label: "Local/data",
    title: "Local institucional e data de emissão",
  },
  {
    key: "signatory_name",
    label: "Assinante",
    title: "Nome definido nas configurações institucionais",
  },
  {
    key: "validation_code",
    label: "Código",
    title: "Código de validação do certificado",
  },
  { key: "equipe", label: "Equipe", title: "Coluna “equipe” da planilha (opcional)" },
  {
    key: "work_title",
    label: "Título",
    title: "Coluna “titulo_trabalho” da planilha (opcional)",
  },
  {
    key: "static",
    label: "Texto fixo",
    title: "Texto igual em todos os certificados",
  },
];

interface ElementListProps {
  elements: TemplateElement[];
  selectedId: string | null;
  /** Type the template is dedicated to; null for the generic template. */
  certificateType?: string | null;
  onAdd: EditorAPI["addTextElement"];
  onSelect: EditorAPI["selectElement"];
  onDelete: EditorAPI["deleteElement"];
  onDuplicate: EditorAPI["duplicateElement"];
}

export default function ElementList({
  elements,
  selectedId,
  certificateType = null,
  onAdd,
  onSelect,
  onDelete,
  onDuplicate,
}: ElementListProps) {
  const quickKeys = isPerWorkType(certificateType)
    ? [...QUICK_KEYS, ...PER_WORK_QUICK_KEYS]
    : QUICK_KEYS;
  const handleListKeyDown = (event: React.KeyboardEvent) => {
    if (elements.length === 0) return;
    const index = elements.findIndex((element) => element.id === selectedId);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      onSelect(elements[Math.min(elements.length - 1, index + 1)].id);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      onSelect(elements[Math.max(0, index <= 0 ? 0 : index - 1)].id);
    } else if (event.key === "Delete" && selectedId) {
      event.preventDefault();
      onDelete(selectedId);
    }
  };

  return (
    <div className="flex h-full flex-col bg-[var(--surface)]">
      <div className="border-b border-[color:var(--line)] px-3 py-2.5">
        <h2 className="text-[length:var(--text-xs)] font-semibold uppercase tracking-[0.06em] text-[color:var(--ink-muted)]">
          Adicionar campo
        </h2>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {quickKeys.map(({ key, label, title }) => (
            <button
              key={key}
              type="button"
              onClick={() => onAdd(key)}
              title={title}
              className={cn(
                "inline-flex items-center gap-1 rounded-[var(--radius)] border px-2 py-1.5",
                "border-[color:var(--line-strong)] bg-[var(--surface)]",
                "text-[length:var(--text-xs)] font-medium text-[color:var(--ink)]",
                "hover:border-[color:var(--brand-500)] hover:bg-[var(--brand-50)]",
              )}
            >
              <Icon name="plus" size={12} />
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="border-b border-[color:var(--line)] px-3 py-2">
        <h2 className="text-[length:var(--text-xs)] font-semibold uppercase tracking-[0.06em] text-[color:var(--ink-muted)]">
          Elementos ({elements.length})
        </h2>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {elements.length === 0 ? (
          <p className="px-3 py-4 text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
            Nenhum elemento no template ainda. Use os botões acima para adicionar
            campos.
          </p>
        ) : (
          <ul
            role="listbox"
            aria-label="Elementos do template"
            tabIndex={0}
            onKeyDown={handleListKeyDown}
            className="divide-y divide-[color:var(--line)] outline-none"
          >
            {elements.map((element) => {
              const isSelected = element.id === selectedId;
              const label =
                element.type === "image"
                  ? element.label || KEY_LABELS.image
                  : element.key === "static"
                    ? element.staticText || "(texto vazio)"
                    : (KEY_LABELS[element.key] ?? element.key);

              return (
                <li
                  key={element.id}
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => onSelect(element.id)}
                  className={cn(
                    "flex cursor-pointer items-center gap-2 px-3 py-2",
                    isSelected
                      ? "bg-[var(--brand-50)] text-[color:var(--brand-800)]"
                      : "text-[color:var(--ink)] hover:bg-[var(--surface-sunken)]",
                  )}
                >
                  <Icon
                    name={element.type === "image" ? "image" : "text"}
                    size={15}
                    className="shrink-0 text-[color:var(--ink-muted)]"
                  />
                  <span className="min-w-0 flex-1 truncate text-[length:var(--text-xs)] font-medium">
                    {label}
                  </span>

                  {/* Visible for the selected row so touch and keyboard users
                      can reach them; hover-only controls exclude both. */}
                  <span
                    className={cn(
                      "flex shrink-0 gap-0.5",
                      isSelected ? "opacity-100" : "opacity-0 focus-within:opacity-100",
                    )}
                  >
                    <IconButton
                      size="sm"
                      icon="duplicate"
                      label={`Duplicar ${label}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        onDuplicate(element.id);
                      }}
                    />
                    <IconButton
                      size="sm"
                      icon="trash"
                      label={`Excluir ${label}`}
                      variant="danger-quiet"
                      onClick={(event) => {
                        event.stopPropagation();
                        onDelete(element.id);
                      }}
                    />
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
