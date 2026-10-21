/**
 * Alert — inline messages.
 *
 * `role` is chosen by urgency rather than by tone: only `danger` alerts that
 * appear in response to a user action get `role="alert"` (assertive). Anything
 * informational uses `role="status"` or no live role at all, because an
 * interface that announces every panel interrupts the screen-reader user
 * constantly. Callers that render a static, always-present notice pass
 * `live={false}`.
 */
import { ReactNode } from "react";
import { cn } from "./cn";
import Icon, { IconName } from "./Icon";

type Tone = "info" | "ok" | "warn" | "danger";

const TONES: Record<Tone, { className: string; icon: IconName; label: string }> = {
  info: {
    className: "border-[color:var(--info-line)] bg-[var(--info-bg)] text-[color:var(--info-fg)]",
    icon: "info",
    label: "Informação",
  },
  ok: {
    className: "border-[color:var(--ok-line)] bg-[var(--ok-bg)] text-[color:var(--ok-fg)]",
    icon: "success",
    label: "Sucesso",
  },
  warn: {
    className: "border-[color:var(--warn-line)] bg-[var(--warn-bg)] text-[color:var(--warn-fg)]",
    icon: "warning",
    label: "Atenção",
  },
  danger: {
    className:
      "border-[color:var(--danger-line)] bg-[var(--danger-bg)] text-[color:var(--danger-fg)]",
    icon: "error",
    label: "Erro",
  },
};

export default function Alert({
  tone = "info",
  title,
  children,
  actions,
  live = true,
  className,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
  /** Set false for permanent explanatory notices that must not be announced. */
  live?: boolean;
  className?: string;
}) {
  const spec = TONES[tone];
  const role = !live ? undefined : tone === "danger" ? "alert" : "status";
  return (
    <div
      role={role}
      className={cn(
        "flex items-start gap-3 rounded-[var(--radius-md)] border p-3 sm:p-4",
        "text-[length:var(--text-sm)]",
        spec.className,
        className,
      )}
    >
      <Icon name={spec.icon} size={18} className="mt-px shrink-0" />
      <div className="min-w-0 flex-1">
        {/* Tone is also stated in words for anyone who cannot see the color. */}
        <span className="sr-only">{spec.label}: </span>
        {title && <p className="font-semibold">{title}</p>}
        {children && (
          <div className={cn("text-[color:var(--ink)]", title && "mt-1")}>{children}</div>
        )}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </div>
  );
}
