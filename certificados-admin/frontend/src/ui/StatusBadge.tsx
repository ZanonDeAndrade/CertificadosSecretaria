/**
 * StatusBadge — status is never carried by color alone (WCAG 1.4.1).
 *
 * Every badge pairs three independent signals: a distinct icon shape, a text
 * label, and color. Printed in greyscale or seen by a user with a color-vision
 * deficiency, the shape and the word still separate "Ativo" from "Revogado".
 *
 * Square-ish (4px radius) rather than a pill, matching the button vocabulary.
 */
import { cn } from "./cn";
import Icon, { IconName } from "./Icon";

export type StatusTone = "ok" | "warn" | "danger" | "info" | "neutral";

const TONES: Record<StatusTone, { className: string; icon: IconName }> = {
  ok: {
    className:
      "bg-[var(--ok-bg)] text-[color:var(--ok-fg)] border-[color:var(--ok-line)]",
    icon: "success",
  },
  warn: {
    className:
      "bg-[var(--warn-bg)] text-[color:var(--warn-fg)] border-[color:var(--warn-line)]",
    icon: "warning",
  },
  danger: {
    className:
      "bg-[var(--danger-bg)] text-[color:var(--danger-fg)] border-[color:var(--danger-line)]",
    icon: "revoked",
  },
  info: {
    className:
      "bg-[var(--info-bg)] text-[color:var(--info-fg)] border-[color:var(--info-line)]",
    icon: "info",
  },
  neutral: {
    className:
      "bg-[var(--neutral-bg)] text-[color:var(--neutral-fg)] border-[color:var(--neutral-line)]",
    icon: "clock",
  },
};

export default function StatusBadge({
  tone,
  children,
  icon,
  className,
}: {
  tone: StatusTone;
  children: React.ReactNode;
  /** Override the tone's default glyph when a more specific one exists. */
  icon?: IconName;
  className?: string;
}) {
  const spec = TONES[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-[var(--radius)] border",
        "px-2 py-0.5 text-[length:var(--text-xs)] font-medium",
        spec.className,
        className,
      )}
    >
      <Icon name={icon ?? spec.icon} size={13} />
      {children}
    </span>
  );
}

/**
 * Maps a certificate's backend state to a badge. `download_available` is what
 * separates a genuinely active certificate from one whose stored PDF is missing
 * — the operator needs to see that difference, so it gets its own status.
 */
export function certificateStatus(cert: {
  status: string;
  download_available?: boolean;
}): { tone: StatusTone; label: string; icon?: IconName } {
  if (cert.status === "revogado") {
    return { tone: "danger", label: "Revogado" };
  }
  if (cert.status === "ativo" && cert.download_available) {
    return { tone: "ok", label: "Ativo" };
  }
  if (cert.status === "ativo") {
    return { tone: "warn", label: "Arquivo indisponível", icon: "warning" };
  }
  if (cert.status === "pending") {
    return { tone: "neutral", label: "Pendente", icon: "clock" };
  }
  if (cert.status === "failed") {
    return { tone: "danger", label: "Falha na emissão", icon: "error" };
  }
  return { tone: "neutral", label: cert.status };
}
