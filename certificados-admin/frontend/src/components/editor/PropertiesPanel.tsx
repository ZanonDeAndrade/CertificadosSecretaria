/**
 * Properties panel for the selected element.
 *
 * Organised into labelled groups (Conteúdo · Posição · Tipografia · Aparência)
 * instead of one long column of controls, so an operator can find "font size"
 * without reading every field. Numeric inputs are real number inputs with
 * units stated in the label, and position is editable by keyboard — dragging on
 * the canvas cannot be the only way to place an element.
 */
import { useEffect, useState } from "react";
import {
  AVAILABLE_FONTS,
  ElementKey,
  ImageTemplateElement,
  KEY_LABELS,
  TemplateElement,
  TextAlign,
  TextTemplateElement,
} from "../../types/template";
import { EditorAPI } from "../../hooks/useEditorCanvas";
import { isPerWorkType } from "../../domain/certificateTypes";
import { PER_WORK_KEYS } from "../../types/template";
import { TEXT_BOX_MIN_SIZE, maxBoxWidth } from "../../lib/textBoxResize";
import Alert from "../../ui/Alert";
import Button from "../../ui/Button";
import Icon from "../../ui/Icon";
import { cn } from "../../ui/cn";

const VARIABLE_KEYS: ElementKey[] = [
  "name",
  "event",
  "course",
  "date",
  "institution_name",
  "issue_location",
  "issue_line",
  "signatory_name",
  "signatory_title",
  "validation_code",
  "texto_certificado",
  "certificate_type",
  "equipe",
  "work_title",
  "static",
];

interface PropertiesPanelProps {
  elements: TemplateElement[];
  selectedId: string | null;
  /** Type the template is dedicated to; null for the generic template. */
  certificateType?: string | null;
  onUpdate: EditorAPI["updateElement"];
  onDelete: EditorAPI["deleteElement"];
  onDuplicate: EditorAPI["duplicateElement"];
  /** Line breaks per text element, as the PDF will break them. */
  textLayouts?: EditorAPI["textLayouts"];
  layoutSource?: EditorAPI["layoutSource"];
  /** Size of the background art, which bounds the text boxes. */
  imageSize?: { width: number; height: number };
}

function isTextElement(element: TemplateElement): element is TextTemplateElement {
  return element.type === "text";
}

function isImageElement(element: TemplateElement): element is ImageTemplateElement {
  return element.type === "image";
}

export default function PropertiesPanel({
  elements,
  selectedId,
  onUpdate,
  onDelete,
  onDuplicate,
  certificateType = null,
  textLayouts = {},
  layoutSource = "pending",
  imageSize = { width: 1, height: 1 },
}: PropertiesPanelProps) {
  const element = elements.find((entry) => entry.id === selectedId) ?? null;
  const layout = element ? textLayouts[element.id] : undefined;
  const variableKeys = isPerWorkType(certificateType)
    ? [...VARIABLE_KEYS, ...PER_WORK_KEYS]
    : VARIABLE_KEYS;

  if (!element) {
    return (
      <div className="flex h-full flex-col bg-[var(--surface)]">
        <PanelTitle />
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-4 py-8 text-center">
          <Icon name="template" size={22} className="text-[color:var(--neutral-400)]" />
          <p className="text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
            Selecione um elemento no canvas ou na lista à esquerda para editar
            suas propriedades.
          </p>
        </div>
      </div>
    );
  }

  const update = (changes: Partial<TemplateElement>) => onUpdate(element.id, changes);

  const title = isImageElement(element)
    ? element.label || KEY_LABELS.image
    : element.key === "static"
      ? "Texto fixo"
      : (KEY_LABELS[element.key] ?? element.key);

  return (
    <div className="flex h-full flex-col overflow-y-auto bg-[var(--surface)]">
      <PanelTitle />

      <div className="border-b border-[color:var(--line)] px-4 py-2.5">
        <p className="flex items-center gap-2 text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]">
          <Icon
            name={isImageElement(element) ? "image" : "text"}
            size={15}
            className="text-[color:var(--ink-muted)]"
          />
          <span className="min-w-0 truncate">{title}</span>
        </p>
      </div>

      {isTextElement(element) && (
        <>
          <Group title="Conteúdo">
            <Row label="Campo">
              <select
                value={element.key}
                onChange={(event) =>
                  update({
                    key: event.target.value as ElementKey,
                    label: KEY_LABELS[event.target.value] ?? event.target.value,
                  } as Partial<TemplateElement>)
                }
                className={CONTROL}
              >
                {variableKeys.map((key) => (
                  <option key={key} value={key}>
                    {KEY_LABELS[key] ?? key}
                  </option>
                ))}
              </select>
            </Row>

            {element.key === "static" && (
              <Row label="Texto fixo">
                <textarea
                  value={element.staticText ?? ""}
                  rows={3}
                  onChange={(event) =>
                    update({ staticText: event.target.value } as Partial<TemplateElement>)
                  }
                  className={cn(CONTROL, "h-auto resize-y py-1.5")}
                />
              </Row>
            )}
          </Group>

          <Group title="Posição">
            <div className="grid grid-cols-2 gap-2">
              <Row label="X (px)">
                <input
                  type="number"
                  value={Math.round(element.x)}
                  onChange={(event) =>
                    update({ x: Number(event.target.value) } as Partial<TemplateElement>)
                  }
                  className={CONTROL}
                />
              </Row>
              <Row label="Y (px)">
                <input
                  type="number"
                  value={Math.round(element.y)}
                  onChange={(event) =>
                    update({ y: Number(event.target.value) } as Partial<TemplateElement>)
                  }
                  className={CONTROL}
                />
              </Row>
            </div>
            <p className="text-[length:var(--text-2xs)] text-[color:var(--ink-subtle)]">
              Coordenadas em pixels da arte original. Com o elemento selecionado,
              as setas do teclado movem 1 px e, com Shift, 10 px.
            </p>
          </Group>

          {element.key !== "qr" && (
            <Group title="Caixa de texto">
              <div className="grid grid-cols-2 gap-2">
                <Row label="Largura (px)">
                  <SizeInput
                    value={element.width}
                    min={TEXT_BOX_MIN_SIZE}
                    max={Math.max(
                      maxBoxWidth(element.x, element.align, imageSize.width),
                      TEXT_BOX_MIN_SIZE,
                    )}
                    ariaLabel="Largura da caixa de texto"
                    onCommit={(width) => update({ width } as Partial<TemplateElement>)}
                  />
                </Row>
                <Row label="Altura (px)">
                  <SizeInput
                    value={element.height}
                    min={TEXT_BOX_MIN_SIZE}
                    max={Math.max(imageSize.height - element.y, TEXT_BOX_MIN_SIZE)}
                    ariaLabel="Altura da caixa de texto"
                    onCommit={(height) => update({ height } as Partial<TemplateElement>)}
                  />
                </Row>
              </div>
              {(element.width !== undefined || element.height !== undefined) && (
                <button
                  type="button"
                  onClick={() =>
                    update({ width: undefined, height: undefined } as Partial<TemplateElement>)
                  }
                  className="self-start text-[length:var(--text-xs)] font-medium text-[color:var(--brand-700)] hover:underline"
                >
                  Voltar ao tamanho automático
                </button>
              )}
              <label className="flex items-start gap-2 text-[length:var(--text-xs)] text-[color:var(--ink)]">
                <input
                  type="checkbox"
                  checked={element.anchorY === "bottom"}
                  onChange={(event) =>
                    update({
                      anchorY: event.target.checked ? "bottom" : undefined,
                    } as Partial<TemplateElement>)
                  }
                  className="mt-0.5 accent-[var(--brand-700)]"
                />
                <span>
                  Base fixa: Y é a base do bloco, que cresce para cima
                  {element.key === "authors" ? " conforme o número de autores" : ""}.
                </span>
              </label>
              {element.key === "authors" && (
                <p className="text-[length:var(--text-2xs)] text-[color:var(--ink-subtle)]">
                  A prévia mostra oito autores, o caso mais alto. Deixe espaço acima
                  do bloco para o corpo do texto.
                </p>
              )}
              {layout?.overflow && element.height !== undefined && (
                <Alert tone="warn" live={false}>
                  O texto não cabe na caixa: {layout.lines.length} linha(s) ocupam{" "}
                  {layout.textHeight} px e a altura é {element.height} px. Aumente a
                  altura, reduza a fonte ou o texto. O PDF não corta o texto.
                </Alert>
              )}
              {layoutSource === "local" && (
                <p className="text-[length:var(--text-2xs)] text-[color:var(--warn-fg)]">
                  Prévia aproximada: não foi possível consultar o servidor para as
                  quebras de linha exatas.
                </p>
              )}
              <p className="text-[length:var(--text-2xs)] text-[color:var(--ink-subtle)]">
                Arraste as alças da caixa no canvas ou digite os valores. A largura
                define onde o texto quebra a linha; a altura, a área reservada.
                Vazio significa automático.
              </p>
            </Group>
          )}

          <Group title="Tipografia">
            <Row label="Fonte">
              <select
                value={element.fontFamily}
                onChange={(event) =>
                  update({ fontFamily: event.target.value } as Partial<TemplateElement>)
                }
                className={CONTROL}
              >
                {AVAILABLE_FONTS.map((font) => (
                  <option key={font} value={font}>
                    {font}
                  </option>
                ))}
              </select>
            </Row>

            <div className="grid grid-cols-2 gap-2">
              <Row label="Tamanho (px)">
                <input
                  type="number"
                  min={6}
                  max={200}
                  value={Math.round(element.fontSize)}
                  onChange={(event) =>
                    update({
                      fontSize: Math.max(6, Number(event.target.value)),
                    } as Partial<TemplateElement>)
                  }
                  className={CONTROL}
                />
              </Row>
              <Row label="Cor">
                <div className="flex items-center gap-1.5">
                  <input
                    type="color"
                    value={element.color}
                    onChange={(event) =>
                      update({ color: event.target.value } as Partial<TemplateElement>)
                    }
                    aria-label="Cor do texto"
                    className="h-8 w-9 shrink-0 cursor-pointer rounded-[var(--radius)] border border-[color:var(--line-strong)] bg-[var(--surface)] p-0.5"
                  />
                  <input
                    type="text"
                    value={element.color}
                    onChange={(event) =>
                      update({ color: event.target.value } as Partial<TemplateElement>)
                    }
                    aria-label="Cor do texto em hexadecimal"
                    className={cn(CONTROL, "font-[family-name:var(--font-mono)]")}
                  />
                </div>
              </Row>
            </div>

            <Row label="Alinhamento">
              <div role="group" aria-label="Alinhamento do texto" className="flex gap-1">
                {(["left", "center", "right"] as TextAlign[]).map((align) => (
                  <button
                    key={align}
                    type="button"
                    aria-pressed={element.align === align}
                    onClick={() => update({ align } as Partial<TemplateElement>)}
                    className={cn(
                      "h-8 flex-1 rounded-[var(--radius)] border text-[length:var(--text-xs)] font-medium",
                      element.align === align
                        ? "border-[color:var(--brand-500)] bg-[var(--brand-50)] text-[color:var(--brand-800)]"
                        : "border-[color:var(--line-strong)] bg-[var(--surface)] text-[color:var(--ink-muted)] hover:text-[color:var(--ink)]",
                    )}
                  >
                    {align === "left"
                      ? "Esquerda"
                      : align === "center"
                        ? "Centro"
                        : "Direita"}
                  </button>
                ))}
              </div>
            </Row>

            <Row label="Estilo">
              <div role="group" aria-label="Estilo do texto" className="flex gap-1">
                <button
                  type="button"
                  aria-pressed={element.bold}
                  onClick={() => update({ bold: !element.bold } as Partial<TemplateElement>)}
                  className={cn(
                    "h-8 flex-1 rounded-[var(--radius)] border text-[length:var(--text-xs)] font-bold",
                    element.bold
                      ? "border-[color:var(--brand-500)] bg-[var(--brand-50)] text-[color:var(--brand-800)]"
                      : "border-[color:var(--line-strong)] bg-[var(--surface)] text-[color:var(--ink-muted)]",
                  )}
                >
                  Negrito
                </button>
                <button
                  type="button"
                  aria-pressed={element.italic}
                  onClick={() =>
                    update({ italic: !element.italic } as Partial<TemplateElement>)
                  }
                  className={cn(
                    "h-8 flex-1 rounded-[var(--radius)] border text-[length:var(--text-xs)] italic",
                    element.italic
                      ? "border-[color:var(--brand-500)] bg-[var(--brand-50)] text-[color:var(--brand-800)]"
                      : "border-[color:var(--line-strong)] bg-[var(--surface)] text-[color:var(--ink-muted)]",
                  )}
                >
                  Itálico
                </button>
              </div>
            </Row>
          </Group>
        </>
      )}

      {isImageElement(element) && (
        <>
          <Group title="Posição">
            <div className="grid grid-cols-2 gap-2">
              <Row label="X (px)">
                <input
                  type="number"
                  value={Math.round(element.x)}
                  onChange={(event) =>
                    update({ x: Number(event.target.value) } as Partial<TemplateElement>)
                  }
                  className={CONTROL}
                />
              </Row>
              <Row label="Y (px)">
                <input
                  type="number"
                  value={Math.round(element.y)}
                  onChange={(event) =>
                    update({ y: Number(event.target.value) } as Partial<TemplateElement>)
                  }
                  className={CONTROL}
                />
              </Row>
            </div>
          </Group>

          <Group title="Tamanho">
            <div className="grid grid-cols-2 gap-2">
              <Row label="Largura (px)">
                <input
                  type="number"
                  min={1}
                  value={Math.round(element.width)}
                  onChange={(event) =>
                    update({
                      width: Math.max(1, Number(event.target.value)),
                    } as Partial<TemplateElement>)
                  }
                  className={CONTROL}
                />
              </Row>
              <Row label="Altura (px)">
                <input
                  type="number"
                  min={1}
                  value={Math.round(element.height)}
                  onChange={(event) =>
                    update({
                      height: Math.max(1, Number(event.target.value)),
                    } as Partial<TemplateElement>)
                  }
                  className={CONTROL}
                />
              </Row>
            </div>
          </Group>

          <Group title="Aparência">
            <Row label={`Opacidade — ${Math.round((element.opacity ?? 1) * 100)}%`}>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((element.opacity ?? 1) * 100)}
                onChange={(event) =>
                  update({
                    opacity: Number(event.target.value) / 100,
                  } as Partial<TemplateElement>)
                }
                className="w-full accent-[var(--brand-700)]"
              />
            </Row>
          </Group>
        </>
      )}

      <div className="mt-auto flex gap-2 border-t border-[color:var(--line)] p-3">
        <Button
          size="sm"
          variant="secondary"
          icon="duplicate"
          onClick={() => onDuplicate(element.id)}
          className="flex-1"
        >
          Duplicar
        </Button>
        <Button
          size="sm"
          variant="danger-quiet"
          icon="trash"
          onClick={() => onDelete(element.id)}
          className="flex-1"
        >
          Excluir
        </Button>
      </div>
    </div>
  );
}

const CONTROL = cn(
  "h-8 w-full rounded-[var(--radius)] border border-[color:var(--line-strong)] bg-[var(--surface)] px-2",
  "text-[length:var(--text-xs)] text-[color:var(--ink)]",
);

/**
 * Number field for a box dimension. Keeps a local draft while typing so a
 * half-typed "15" is not snapped to the minimum before "150" is complete:
 * values inside the range apply live, the rest on blur or Enter. Empty means
 * automatic.
 */
function SizeInput({
  value,
  min,
  max,
  ariaLabel,
  onCommit,
}: {
  value: number | undefined;
  min: number;
  max: number;
  ariaLabel: string;
  onCommit: (value: number | undefined) => void;
}) {
  const shown = value === undefined ? "" : String(Math.round(value));
  const [draft, setDraft] = useState(shown);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) setDraft(shown);
  }, [shown, focused]);

  const commit = (raw: string) => {
    const trimmed = raw.trim();
    if (trimmed === "") {
      onCommit(undefined);
      return;
    }
    const number = Number(trimmed);
    if (!Number.isFinite(number)) return;
    onCommit(Math.min(Math.max(Math.round(number), min), max));
  };

  return (
    <input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      placeholder="Auto"
      value={draft}
      aria-label={ariaLabel}
      onFocus={() => setFocused(true)}
      onChange={(event) => {
        const raw = event.target.value;
        setDraft(raw);
        const number = Number(raw);
        if (raw.trim() !== "" && Number.isFinite(number) && number >= min && number <= max) {
          onCommit(Math.round(number));
        }
      }}
      onBlur={(event) => {
        setFocused(false);
        commit(event.target.value);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit(event.currentTarget.value);
        }
      }}
      className={CONTROL}
    />
  );
}

function PanelTitle() {
  return (
    <div className="border-b border-[color:var(--line)] px-4 py-2.5">
      <h2 className="text-[length:var(--text-xs)] font-semibold uppercase tracking-[0.06em] text-[color:var(--ink-muted)]">
        Propriedades
      </h2>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-[color:var(--line)] px-4 py-3">
      <h3 className="mb-2 text-[length:var(--text-2xs)] font-semibold uppercase tracking-[0.06em] text-[color:var(--ink-subtle)]">
        {title}
      </h3>
      <div className="flex flex-col gap-2.5">{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[length:var(--text-xs)] font-medium text-[color:var(--ink-muted)]">
        {label}
      </span>
      {children}
    </label>
  );
}
