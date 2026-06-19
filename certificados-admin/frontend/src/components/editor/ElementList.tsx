import { KEY_LABELS, TemplateElement, ElementKey } from "../../types/template";
import { EditorAPI } from "../../hooks/useEditorCanvas";

const QUICK_KEYS: { key: ElementKey; label: string }[] = [
  { key: "name", label: "Nome" },
  { key: "event", label: "Evento" },
  { key: "date", label: "Data" },
  { key: "validation_code", label: "Codigo" },
  { key: "texto_certificado", label: "Texto" },
  { key: "static", label: "Texto fixo" },
];

interface ElementListProps {
  elements: TemplateElement[];
  selectedId: string | null;
  onAdd: EditorAPI["addTextElement"];
  onSelect: EditorAPI["selectElement"];
  onDelete: EditorAPI["deleteElement"];
  onDuplicate: EditorAPI["duplicateElement"];
}

function ElementList({
  elements,
  selectedId,
  onAdd,
  onSelect,
  onDelete,
  onDuplicate,
}: ElementListProps) {
  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-3 py-3">
        <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
          Elementos
        </p>
      </div>

      <div className="border-b border-slate-100 p-3">
        <p className="mb-2 text-xs text-slate-400">Adicionar campo:</p>
        <div className="flex flex-wrap gap-1">
          {QUICK_KEYS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => onAdd(key)}
              className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-700 transition hover:border-sky-400 hover:bg-sky-50 hover:text-sky-700"
            >
              + {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {elements.length === 0 ? (
          <p className="px-3 py-4 text-xs text-slate-400">
            Nenhum elemento ainda.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {elements.map((el) => {
              const isSelected = el.id === selectedId;
              const icon = el.type === "image" ? "IMG" : "T";
              const label =
                el.type === "image"
                  ? el.label || KEY_LABELS.image
                  : el.key === "static"
                    ? el.staticText || "(vazio)"
                    : KEY_LABELS[el.key] ?? el.key;

              return (
                <li
                  key={el.id}
                  className={[
                    "group flex cursor-pointer items-center gap-2 px-3 py-2 transition",
                    isSelected
                      ? "bg-sky-50 text-sky-700"
                      : "text-slate-700 hover:bg-slate-50",
                  ].join(" ")}
                  onClick={() => onSelect(el.id)}
                >
                  <span className="shrink-0 text-[10px] font-semibold uppercase">
                    {icon}
                  </span>

                  <span className="flex-1 truncate text-xs font-medium">
                    {label}
                  </span>

                  <div className="flex shrink-0 gap-0.5 opacity-0 transition group-hover:opacity-100">
                    <button
                      type="button"
                      title="Duplicar"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDuplicate(el.id);
                      }}
                      className="rounded p-0.5 text-slate-400 hover:text-sky-600"
                    >
                      D
                    </button>
                    <button
                      type="button"
                      title="Excluir"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(el.id);
                      }}
                      className="rounded p-0.5 text-slate-400 hover:text-rose-600"
                    >
                      X
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

export default ElementList;
