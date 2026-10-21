/**
 * The four states every data region owes the user: loading, empty, error, and
 * offline. Having them as components means a screen cannot quietly ship with
 * only the happy path.
 */
import { ReactNode } from "react";
import { cn } from "./cn";
import Icon, { IconName } from "./Icon";
import Button from "./Button";

/**
 * Skeleton — structural loading. Shows the shape of what is coming instead of a
 * spinner floating in empty space. Animation is motion-safe only.
 */
export function Skeleton({
  className,
  width,
}: {
  className?: string;
  width?: string;
}) {
  return (
    <span
      aria-hidden="true"
      style={width ? { width } : undefined}
      className={cn(
        "block h-4 rounded-[var(--radius-sm)] bg-[var(--neutral-100)]",
        "motion-safe:animate-pulse",
        className,
      )}
    />
  );
}

/**
 * Rows of skeleton cells matching a table's column count. The live region
 * announces loading once, rather than the skeleton bars being read out.
 */
export function TableSkeleton({
  rows = 5,
  columns,
  label = "Carregando dados",
}: {
  rows?: number;
  columns: number;
  label?: string;
}) {
  // Only <tr> may live inside <tbody>, so the status text rides in the first
  // cell rather than as a sibling element.
  return (
    <>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <tr key={rowIndex} className="border-t border-[color:var(--line)]">
          {Array.from({ length: columns }, (_, columnIndex) => (
            <td key={columnIndex} className="px-4 py-3">
              {rowIndex === 0 && columnIndex === 0 && (
                <span role="status" className="sr-only">
                  {label}
                </span>
              )}
              <Skeleton width={columnIndex === 0 ? "70%" : "45%"} />
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}

/**
 * EmptyState — teaches the interface rather than saying "nothing here".
 * `reason` distinguishes a genuinely empty dataset from a filtered-to-nothing
 * one, because the recovery is different (create something vs. clear filters).
 */
export function EmptyState({
  icon = "info",
  title,
  description,
  action,
  className,
}: {
  icon?: IconName;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 px-6 py-12 text-center",
        className,
      )}
    >
      <span className="flex h-11 w-11 items-center justify-center rounded-[var(--radius-md)] border border-[color:var(--line)] bg-[var(--surface-sunken)] text-[color:var(--ink-muted)]">
        <Icon name={icon} size={22} />
      </span>
      <p className="text-[length:var(--text-md)] font-semibold text-[color:var(--ink)]">
        {title}
      </p>
      {description && (
        <p className="max-w-[46ch] text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
          {description}
        </p>
      )}
      {action && <div className="mt-1 flex flex-wrap justify-center gap-2">{action}</div>}
    </div>
  );
}

/**
 * ErrorState — names the problem and offers the recovery, never just "erro".
 * `offline` swaps the copy because the recovery genuinely differs: retrying
 * without a connection cannot work.
 */
export function ErrorState({
  title,
  description,
  onRetry,
  offline = false,
  className,
}: {
  title?: string;
  description?: ReactNode;
  onRetry?: () => void;
  offline?: boolean;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-3 px-6 py-12 text-center",
        className,
      )}
    >
      <span className="flex h-11 w-11 items-center justify-center rounded-[var(--radius-md)] border border-[color:var(--danger-line)] bg-[var(--danger-bg)] text-[color:var(--danger-fg)]">
        <Icon name={offline ? "offline" : "error"} size={22} />
      </span>
      <p className="text-[length:var(--text-md)] font-semibold text-[color:var(--ink)]">
        {title ?? (offline ? "Sem conexão com a rede" : "Não foi possível carregar")}
      </p>
      <p className="max-w-[52ch] text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
        {description ??
          (offline
            ? "Verifique a conexão da máquina. Os dados serão carregados assim que a rede voltar."
            : "O servidor não respondeu como esperado. Tente novamente em alguns instantes.")}
      </p>
      {onRetry && (
        <Button variant="secondary" icon="refresh" onClick={onRetry} className="mt-1">
          Tentar novamente
        </Button>
      )}
    </div>
  );
}
