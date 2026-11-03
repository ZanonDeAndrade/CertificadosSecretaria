/**
 * Collapsible side panel of the editor.
 *
 * Open, it shows its content at a fixed width with a small toggle in the top
 * corner; collapsed, it shrinks to a narrow strip that names the panel and
 * brings it back. The canvas refits whenever a panel changes, so collapsing
 * both gives the certificate the whole width on a notebook screen. Panels
 * never open on their own: the scale must not change under a drag.
 */
import { ReactNode } from "react";
import { IconButton } from "../../ui/Button";
import { cn } from "../../ui/cn";

interface SidePanelProps {
  /** Short name used in the toggle labels and on the collapsed strip. */
  title: string;
  side: "left" | "right";
  collapsed: boolean;
  onToggle: () => void;
  /** Width class while open (e.g. "w-56"). */
  widthClass: string;
  children: ReactNode;
}

export default function SidePanel({
  title,
  side,
  collapsed,
  onToggle,
  widthClass,
  children,
}: SidePanelProps) {
  const border = side === "left" ? "border-r" : "border-l";
  // The chevron points where the panel goes: left panel folds left, right
  // panel folds right; collapsed, it points back into the editor.
  const collapseIcon = side === "left" ? "chevron-left" : "chevron-right";
  const expandIcon = side === "left" ? "chevron-right" : "chevron-left";

  if (collapsed) {
    return (
      <aside
        aria-label={`Painel ${title} recolhido`}
        className={cn(
          // 36 px: the 32 px button plus the border, with no half-pixel overflow.
          "flex w-9 shrink-0 flex-col items-center gap-2 border-[color:var(--line)] bg-[var(--surface)] py-1",
          border,
        )}
      >
        <IconButton
          size="sm"
          icon={expandIcon}
          label={`Mostrar painel ${title}`}
          onClick={onToggle}
        />
        <span
          aria-hidden="true"
          className="text-[length:var(--text-2xs)] font-semibold uppercase tracking-[0.06em] text-[color:var(--ink-muted)] [writing-mode:vertical-rl]"
        >
          {title}
        </span>
      </aside>
    );
  }

  return (
    <aside
      aria-label={`Painel ${title}`}
      className={cn("relative shrink-0 border-[color:var(--line)]", border, widthClass)}
    >
      {children}
      <IconButton
        size="sm"
        icon={collapseIcon}
        label={`Recolher painel ${title}`}
        onClick={onToggle}
        className="absolute right-1 top-1"
      />
    </aside>
  );
}
