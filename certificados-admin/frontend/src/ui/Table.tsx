/**
 * Table primitives — semantically correct data tables.
 *
 * `<caption>` is required (visually hidden by default) so a screen-reader user
 * landing on the table knows what it lists. Header cells carry `scope`, sort
 * state uses `aria-sort`, and the scroll container is focusable with
 * `tabIndex={0}` + `role="region"` so keyboard users can actually reach a
 * horizontally scrolled table — the single most common a11y bug in data UI.
 */
import { ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "./cn";

export function TableScroll({
  children,
  label,
  className,
}: {
  children: ReactNode;
  /** Names the scrollable region for assistive tech. */
  label: string;
  className?: string;
}) {
  return (
    <div
      role="region"
      aria-label={label}
      tabIndex={0}
      className={cn(
        "table-scroll rounded-[var(--radius-md)] border border-[color:var(--line)] bg-[var(--surface)]",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function Table({
  children,
  caption,
  captionVisible = false,
  className,
}: {
  children: ReactNode;
  caption: string;
  captionVisible?: boolean;
  className?: string;
}) {
  return (
    <table
      className={cn(
        "w-full border-collapse text-left text-[length:var(--text-sm)]",
        className,
      )}
    >
      <caption
        className={cn(
          captionVisible
            ? "px-4 py-3 text-left text-[length:var(--text-sm)] text-[color:var(--ink-muted)]"
            : "sr-only",
        )}
      >
        {caption}
      </caption>
      {children}
    </table>
  );
}

export function Thead({ children }: { children: ReactNode }) {
  return (
    <thead className="bg-[var(--surface-sunken)] text-[color:var(--ink-muted)]">
      {children}
    </thead>
  );
}

export function Tbody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>;
}

export function Tr({
  children,
  className,
  ...rest
}: { children: ReactNode; className?: string } & React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-t border-[color:var(--line)] first:border-t-0",
        "hover:bg-[var(--surface-sunken)]",
        className,
      )}
      {...rest}
    >
      {children}
    </tr>
  );
}

type SortDirection = "ascending" | "descending" | "none";

export function Th({
  children,
  scope = "col",
  sort,
  numeric = false,
  className,
  ...rest
}: {
  children: ReactNode;
  scope?: "col" | "row";
  sort?: SortDirection;
  numeric?: boolean;
} & ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope={scope}
      aria-sort={sort}
      className={cn(
        "whitespace-nowrap px-4 py-2.5 text-[length:var(--text-xs)] font-semibold",
        "uppercase tracking-[0.04em]",
        numeric && "text-right tabular-nums",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

export function Td({
  children,
  numeric = false,
  mono = false,
  className,
  ...rest
}: {
  children: ReactNode;
  numeric?: boolean;
  mono?: boolean;
} & TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn(
        "px-4 py-2.5 align-middle text-[color:var(--ink)]",
        numeric && "text-right tabular-nums",
        // Codes are identifiers: breaking one across two lines makes it
        // unreadable and impossible to copy by eye.
        mono &&
          "whitespace-nowrap font-[family-name:var(--font-mono)] text-[length:var(--text-xs)]",
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}

/** Row header cell — the first column of each row, so rows are navigable. */
export function TdHeader({
  children,
  className,
  ...rest
}: { children: ReactNode; className?: string } & ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="row"
      className={cn(
        "px-4 py-2.5 text-left align-middle font-medium text-[color:var(--ink)]",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}
