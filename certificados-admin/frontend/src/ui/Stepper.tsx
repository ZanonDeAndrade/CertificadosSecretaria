/**
 * Stepper — short, linear progress indicator for the issuing flow.
 *
 * Rendered as an ordered list so the sequence is conveyed structurally. State
 * is never color-only: the current step is marked with `aria-current="step"`,
 * completed steps show a check glyph, and each step's state is also spelled out
 * in visually-hidden text ("concluído" / "etapa atual").
 *
 * Steps are not clickable. Jumping back would need the flow to re-validate the
 * spreadsheet, and a control that silently discards work is worse than none.
 */
import { cn } from "./cn";
import Icon from "./Icon";

export interface Step {
  id: string;
  label: string;
}

export default function Stepper({
  steps,
  current,
  className,
}: {
  steps: Step[];
  /** Index of the active step. */
  current: number;
  className?: string;
}) {
  return (
    <nav aria-label="Etapas da emissão" className={className}>
      <ol className="flex flex-wrap items-center gap-x-2 gap-y-2">
        {steps.map((step, index) => {
          const done = index < current;
          const active = index === current;
          return (
            <li key={step.id} className="flex items-center gap-2">
              <span
                aria-current={active ? "step" : undefined}
                className={cn(
                  "inline-flex items-center gap-2 rounded-[var(--radius)] border px-2.5 py-1.5",
                  "text-[length:var(--text-sm)] font-medium",
                  active &&
                    "border-[color:var(--brand-700)] bg-[var(--brand-50)] text-[color:var(--brand-800)]",
                  done &&
                    "border-[color:var(--ok-line)] bg-[var(--ok-bg)] text-[color:var(--ok-fg)]",
                  !active &&
                    !done &&
                    "border-[color:var(--line)] bg-[var(--surface)] text-[color:var(--ink-subtle)]",
                )}
              >
                <span
                  className={cn(
                    "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-[var(--radius-full)]",
                    "text-[length:var(--text-2xs)] font-semibold tabular-nums",
                    active && "bg-[var(--brand-700)] text-[color:var(--ink-inverse)]",
                    done && "bg-[var(--ok-fg)] text-[color:var(--ink-inverse)]",
                    !active && !done && "bg-[var(--neutral-200)] text-[color:var(--ink-muted)]",
                  )}
                >
                  {done ? <Icon name="success" size={13} /> : index + 1}
                </span>
                {step.label}
                <span className="sr-only">
                  {done ? " (concluído)" : active ? " (etapa atual)" : " (pendente)"}
                </span>
              </span>

              {index < steps.length - 1 && (
                <Icon
                  name="chevron-right"
                  size={14}
                  className="text-[color:var(--neutral-400)]"
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
