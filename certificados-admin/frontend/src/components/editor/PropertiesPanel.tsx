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

const VARIABLE_KEYS: ElementKey[] = [
  "name",
  "event",
  "date",
  "validation_code",
  "texto_certificado",
  "certificate_text",
  "static",
];

interface PropertiesPanelProps {
  elements: TemplateElement[];
  selectedId: string | null;
  onUpdate: EditorAPI["updateElement"];
  onDelete: EditorAPI["deleteElement"];
  onDuplicate: EditorAPI["duplicateElement"];
}

function isTextElement(element: TemplateElement): element is TextTemplateElement {
  return element.type === "text";
}

function isImageElement(element: TemplateElement): element is ImageTemplateElement {
  return element.type === "image";
}

function PropertiesPanel({
  elements,
  selectedId,
  onUpdate,
  onDelete,
  onDuplicate,
}: PropertiesPanelProps) {
  const el = elements.find((e) => e.id === selectedId) ?? null;

  if (!el) {
    return (
      <aside className="flex w-60 shrink-0 flex-col border-l border-slate-200 bg-white">
        <div className="border-b border-slate-200 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Propriedades
          </p>
        </div>
        <p className="px-4 py-5 text-xs text-slate-400">
          Selecione um elemento no canvas ou na lista a esquerda.
        </p>
      </aside>
    );
  }

  const upd = (changes: Partial<TemplateElement>) => onUpdate(el.id, changes);

  return (
    <aside className="flex w-60 shrink-0 flex-col overflow-y-auto border-l border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          Propriedades
        </p>
      </div>

      <div className="flex flex-col gap-4 p-4">
        {isTextElement(el) && (
          <>
            <Field label="Campo">
              <select
                value={el.key}
                onChange={(e) =>
                  upd({
                    key: e.target.value as ElementKey,
                    label: KEY_LABELS[e.target.value] ?? e.target.value,
                  })
                }
                className={selectCls}
              >
                {VARIABLE_KEYS.map((k) => (
                  <option key={k} value={k}>
                    {KEY_LABELS[k] ?? k}
                  </option>
                ))}
              </select>
            </Field>

            {el.key === "static" && (
              <Field label="Texto">
                <input
                  type="text"
                  value={el.staticText ?? ""}
                  onChange={(e) => upd({ staticText: e.target.value })}
                  className={inputCls}
                  placeholder="Digite o texto fixo..."
                />
              </Field>
            )}

            <Field label="Fonte">
              <select
                value={el.fontFamily}
                onChange={(e) => upd({ fontFamily: e.target.value })}
                className={selectCls}
              >
                {AVAILABLE_FONTS.map((font) => (
                  <option key={font} value={font} style={{ fontFamily: font }}>
                    {font}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Tamanho (px)">
              <input
                type="number"
                min={6}
                max={400}
                value={el.fontSize}
                onChange={(e) =>
                  upd({ fontSize: Math.max(6, Number(e.target.value)) })
                }
                className={inputCls}
              />
            </Field>

            <Field label="Cor">
              <div className="flex items-center gap-2">
                <input
                  type="color"
                  value={el.color}
                  onChange={(e) => upd({ color: e.target.value })}
                  className="h-8 w-10 cursor-pointer rounded border border-slate-200 p-0.5"
                />
                <input
                  type="text"
                  value={el.color}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (/^#[0-9a-fA-F]{0,6}$/.test(value)) upd({ color: value });
                  }}
                  className={`${inputCls} font-mono`}
                  maxLength={7}
                />
              </div>
            </Field>

            <Field label="Alinhamento">
              <div className="flex gap-1">
                {(["left", "center", "right"] as TextAlign[]).map((align) => (
                  <button
                    key={align}
                    type="button"
                    onClick={() => upd({ align })}
                    className={[
                      "flex-1 rounded-lg border py-1.5 text-sm transition",
                      el.align === align
                        ? "border-sky-500 bg-sky-50 font-bold text-sky-700"
                        : "border-slate-200 text-slate-500 hover:border-slate-400",
                    ].join(" ")}
                  >
                    {align.toUpperCase()}
                  </button>
                ))}
              </div>
            </Field>

            <Field label="Estilo">
              <div className="flex gap-2">
                <ToggleButton
                  label="N"
                  title="Negrito"
                  active={el.bold}
                  onClick={() => upd({ bold: !el.bold })}
                  boldDisplay
                />
                <ToggleButton
                  label="I"
                  title="Italico"
                  active={el.italic}
                  onClick={() => upd({ italic: !el.italic })}
                  italicDisplay
                />
              </div>
            </Field>
          </>
        )}

        {isImageElement(el) && (
          <>
            <Field label="Legenda">
              <input
                type="text"
                value={el.label}
                onChange={(e) => upd({ label: e.target.value })}
                className={inputCls}
              />
            </Field>

            <Field label="Largura (px)">
              <input
                type="number"
                min={1}
                value={el.width}
                onChange={(e) => upd({ width: Math.max(1, Number(e.target.value)) })}
                className={inputCls}
              />
            </Field>

            <Field label="Altura (px)">
              <input
                type="number"
                min={1}
                value={el.height}
                onChange={(e) => upd({ height: Math.max(1, Number(e.target.value)) })}
                className={inputCls}
              />
            </Field>

            <Field label="Opacidade">
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={el.opacity ?? 1}
                onChange={(e) => upd({ opacity: Number(e.target.value) })}
                className="w-full"
              />
            </Field>
          </>
        )}

        <Field label="Posicao (px)">
          <div className="flex gap-2">
            <div className="flex flex-1 flex-col gap-0.5">
              <span className="text-xs text-slate-400">X</span>
              <input
                type="number"
                value={el.x}
                onChange={(e) => upd({ x: Number(e.target.value) })}
                className={inputCls}
              />
            </div>
            <div className="flex flex-1 flex-col gap-0.5">
              <span className="text-xs text-slate-400">Y</span>
              <input
                type="number"
                value={el.y}
                onChange={(e) => upd({ y: Number(e.target.value) })}
                className={inputCls}
              />
            </div>
          </div>
        </Field>

        <div className="flex gap-2 pt-2">
          <button
            type="button"
            onClick={() => onDuplicate(el.id)}
            className="flex-1 rounded-full border border-slate-300 py-2 text-xs font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
          >
            Duplicar
          </button>
          <button
            type="button"
            onClick={() => onDelete(el.id)}
            className="flex-1 rounded-full bg-rose-600 py-2 text-xs font-semibold text-white transition hover:bg-rose-500"
          >
            Excluir
          </button>
        </div>
      </div>
    </aside>
  );
}

const inputCls =
  "w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-400";

const selectCls =
  "w-full rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-400";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-medium text-slate-500">{label}</label>
      {children}
    </div>
  );
}

function ToggleButton({
  label,
  title,
  active,
  onClick,
  boldDisplay,
  italicDisplay,
}: {
  label: string;
  title: string;
  active: boolean;
  onClick: () => void;
  boldDisplay?: boolean;
  italicDisplay?: boolean;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={[
        "flex-1 rounded-lg border py-1.5 text-sm transition",
        active
          ? "border-sky-500 bg-sky-50 text-sky-700"
          : "border-slate-200 text-slate-500 hover:border-slate-400",
        boldDisplay ? "font-bold" : "",
        italicDisplay ? "italic" : "",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

export default PropertiesPanel;
