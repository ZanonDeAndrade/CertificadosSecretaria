/**
 * Pagination — states the range in words ("21–40 de 137") rather than only
 * page numbers, which is what an operator reconciling a batch actually needs.
 *
 * Wrapped in <nav aria-label> so it is reachable as a landmark, and the range
 * summary is a polite live region so a screen-reader user hears the new range
 * after changing pages without the whole table being re-read.
 */
import Button from "./Button";

export default function Pagination({
  page,
  pageSize,
  total,
  loading = false,
  onPageChange,
  itemNoun = "registro",
  itemNounPlural = "registros",
}: {
  /** Zero-based page index. */
  page: number;
  pageSize: number;
  total: number;
  loading?: boolean;
  onPageChange: (page: number) => void;
  itemNoun?: string;
  itemNounPlural?: string;
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const first = total === 0 ? 0 : page * pageSize + 1;
  const last = Math.min(total, (page + 1) * pageSize);
  const noun = total === 1 ? itemNoun : itemNounPlural;

  return (
    <nav
      aria-label="Paginação"
      className="flex flex-col items-center justify-between gap-3 border-t border-[color:var(--line)] px-4 py-3 sm:flex-row"
    >
      <p
        role="status"
        aria-live="polite"
        className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]"
      >
        {total === 0
          ? `Nenhum ${itemNoun}`
          : `${first}–${last} de ${total} ${noun}`}
        {loading && " · carregando…"}
      </p>

      {totalPages > 1 && (
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            icon="chevron-left"
            disabled={page === 0 || loading}
            onClick={() => onPageChange(Math.max(0, page - 1))}
          >
            Anterior
          </Button>
          <span className="px-1 text-[length:var(--text-sm)] tabular-nums text-[color:var(--ink-muted)]">
            Página {page + 1} de {totalPages}
          </span>
          <Button
            size="sm"
            variant="secondary"
            iconAfter="chevron-right"
            disabled={page + 1 >= totalPages || loading}
            onClick={() => onPageChange(page + 1)}
          >
            Próxima
          </Button>
        </div>
      )}
    </nav>
  );
}
