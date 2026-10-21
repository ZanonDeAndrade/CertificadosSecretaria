/**
 * Panel — the single container in this system.
 *
 * One flat surface with a hairline border and a small shadow. Panels are never
 * nested inside one another: a region that needs internal grouping uses
 * `PanelSection` dividers instead, which keeps the page from turning into the
 * stack of same-size cards that reads as a template.
 */
import { ReactNode } from "react";
import { cn } from "./cn";

export default function Panel({
  children,
  className,
  as: Tag = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article" | "aside" | "search";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag
      className={cn(
        "rounded-[var(--radius-md)] border border-[color:var(--line)] bg-[var(--surface)]",
        "shadow-[var(--shadow-sm)]",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/**
 * Panel header. `title` renders as the given heading level so document outline
 * stays correct — the caller decides the level, never the component.
 */
export function PanelHeader({
  title,
  headingLevel = 2,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  headingLevel?: 2 | 3 | 4;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  const Heading = `h${headingLevel}` as "h2" | "h3" | "h4";
  return (
    <div
      className={cn(
        "flex flex-wrap items-start justify-between gap-3 border-b border-[color:var(--line)] px-4 py-3 sm:px-5",
        className,
      )}
    >
      <div className="min-w-0">
        <Heading className="text-[length:var(--text-md)] font-semibold text-[color:var(--ink)]">
          {title}
        </Heading>
        {description && (
          <p className="mt-1 max-w-[var(--prose-max)] text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function PanelBody({
  children,
  className,
  padded = true,
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <div className={cn(padded && "px-4 py-4 sm:px-5", className)}>{children}</div>
  );
}

/** A horizontal rule inside a panel, for grouping without nesting containers. */
export function PanelSection({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("border-t border-[color:var(--line)] px-4 py-4 sm:px-5", className)}>
      {children}
    </div>
  );
}
