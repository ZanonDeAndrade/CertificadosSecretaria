/**
 * PageHeader and Breadcrumbs.
 *
 * The h1 lives here and appears exactly once per route, so heading order is
 * h1 → panel h2 → subsection h3 on every screen. There is deliberately no
 * eyebrow/kicker line above the title: the heading carries its own weight.
 */
import { ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "./cn";
import Icon from "./Icon";

export interface Crumb {
  label: string;
  /** Omit on the current page — the last crumb is text, not a link. */
  to?: string;
}

export function Breadcrumbs({ items }: { items: Crumb[] }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label="Trilha de navegação" className="mb-2">
      <ol className="flex flex-wrap items-center gap-1 text-[length:var(--text-xs)] text-[color:var(--ink-muted)]">
        {items.map((crumb, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={`${crumb.label}-${index}`} className="flex items-center gap-1">
              {crumb.to && !isLast ? (
                <Link
                  to={crumb.to}
                  className="rounded-[var(--radius-sm)] px-0.5 underline decoration-[color:var(--line-strong)] hover:text-[color:var(--ink)] hover:decoration-current"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span aria-current={isLast ? "page" : undefined} className="text-[color:var(--ink)]">
                  {crumb.label}
                </span>
              )}
              {!isLast && (
                <Icon name="chevron-right" size={13} className="text-[color:var(--neutral-400)]" />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  breadcrumbs?: Crumb[];
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-5", className)}>
      {breadcrumbs && <Breadcrumbs items={breadcrumbs} />}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[length:var(--text-xl)] font-semibold tracking-[-0.01em] text-[color:var(--ink)]">
            {title}
          </h1>
          {description && (
            <p className="mt-1.5 max-w-[var(--prose-max)] text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
        )}
      </div>
    </header>
  );
}
