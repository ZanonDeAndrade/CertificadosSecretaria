/**
 * Who a certificate is for, as the panel lists it.
 *
 * An ordinary certificate names its holder, exactly as before. A per-work
 * certificate (Mostra) is valid for every author, so it is named by its work:
 * the title stands out and the authors follow. Past the first few authors the
 * list ends in "+N". The full list is that button's tooltip for a mouse, and
 * the button itself expands it in place, which is how touch, keyboard and
 * screen-reader users reach it; the detail view lists every author too.
 */
import { useState } from "react";
import { isPerWorkType } from "../domain/certificateTypes";

/** Authors shown before the list collapses into "+N". */
export const VISIBLE_AUTHORS = 3;

export interface SubjectSource {
  participant_name: string;
  certificate_type?: string | null;
  work_title?: string | null;
  authors?: string[];
}

export interface WorkSubject {
  /** Empty for works issued before the title became required. */
  title: string;
  authors: string[];
}

/** The work a per-work certificate is for, or null for a holder's certificate. */
export function workSubject(source: SubjectSource): WorkSubject | null {
  if (!isPerWorkType(source.certificate_type)) return null;
  const title = (source.work_title ?? "").trim();
  const authors = source.authors?.length ? source.authors : [];
  // A record issued before authors were stored keeps showing its holder.
  if (!title && !authors.length) return null;
  return { title, authors: authors.length ? authors : [source.participant_name] };
}

export function authorsLabel(count: number): string {
  return count === 1 ? "Autor" : "Autores";
}

function summarizeAuthors(authors: string[]): string {
  const hidden = authors.length - VISIBLE_AUTHORS;
  return hidden > 0
    ? `${authors.slice(0, VISIBLE_AUTHORS).join(", ")} e mais ${hidden}`
    : authors.join(", ");
}

/**
 * "de Nome" or "do trabalho “Título”", completing phrases such as "Baixar
 * certificado …" in accessible names and messages.
 */
export function certificateOf(source: SubjectSource): string {
  const work = workSubject(source);
  if (!work) return `de ${source.participant_name}`;
  return work.title
    ? `do trabalho “${work.title}”`
    : `do trabalho de ${summarizeAuthors(work.authors)}`;
}

/** The same phrase for dialogs, with the name or title in bold. */
export function CertificateOf({ source }: { source: SubjectSource }) {
  const work = workSubject(source);
  if (!work) {
    return (
      <>
        de <strong>{source.participant_name}</strong>
      </>
    );
  }
  return work.title ? (
    <>
      do trabalho <strong>{work.title}</strong>
    </>
  ) : (
    <>
      do trabalho de <strong>{summarizeAuthors(work.authors)}</strong>
    </>
  );
}

/** Every author of a per-work certificate in one line; nothing otherwise. */
export function AllAuthors({
  source,
  className,
}: {
  source: SubjectSource;
  className?: string;
}) {
  const work = workSubject(source);
  if (!work) return null;
  return (
    <p className={className}>
      {authorsLabel(work.authors.length)}: {work.authors.join(", ")}
    </p>
  );
}

/** Table cell / list item content: the holder, or the work and its authors. */
export default function CertificateSubject({ source }: { source: SubjectSource }) {
  const work = workSubject(source);
  if (!work) return <>{source.participant_name}</>;
  return (
    <>
      {work.title && <span className="block">{work.title}</span>}
      <AuthorList
        authors={work.authors}
        className={
          work.title
            ? "mt-0.5 block text-[length:var(--text-xs)] font-normal text-[color:var(--ink-muted)]"
            : "block"
        }
      />
    </>
  );
}

function AuthorList({ authors, className }: { authors: string[]; className?: string }) {
  const [expanded, setExpanded] = useState(false);
  const hidden = authors.length - VISIBLE_AUTHORS;
  const shown = expanded || hidden <= 0 ? authors : authors.slice(0, VISIBLE_AUTHORS);
  return (
    <span className={className}>
      {authorsLabel(authors.length)}: {shown.join(", ")}
      {hidden > 0 && (
        <>
          {" "}
          <button
            type="button"
            aria-expanded={expanded}
            // The name keeps the visible "+N" and says what pressing does.
            aria-label={expanded ? undefined : `+${hidden} autores; mostrar todos`}
            title={expanded ? undefined : authors.join(", ")}
            onClick={() => setExpanded((current) => !current)}
            className="inline-flex min-h-6 items-center rounded-[var(--radius)] px-1 font-medium text-[color:var(--brand-700)] underline underline-offset-2 hover:bg-[var(--surface-inset)]"
          >
            {expanded ? "mostrar menos" : `+${hidden}`}
          </button>
        </>
      )}
    </span>
  );
}
