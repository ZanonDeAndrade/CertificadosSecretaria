/**
 * Dropdown menu for secondary actions.
 *
 * A trigger button and a `menu` of `menuitem` buttons, following the WAI-ARIA
 * menu button pattern: Escape and an outside click close it, arrow keys move
 * between items, and closing returns the focus to the trigger. Used by the
 * editor toolbar to keep rarely used actions off the single row.
 */
import { useEffect, useId, useRef, useState } from "react";
import Button from "./Button";
import Icon, { IconName } from "./Icon";
import { cn } from "./cn";

export interface MenuItem {
  label: string;
  icon?: IconName;
  onSelect: () => void;
  tone?: "default" | "danger";
}

interface MenuProps {
  /** Visible label of the trigger. */
  label: string;
  icon?: IconName;
  items: MenuItem[];
  size?: "sm" | "md";
}

export default function Menu({ label, icon, items, size = "md" }: MenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();

    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const close = (restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) triggerRef.current?.focus();
  };

  const onListKeyDown = (event: React.KeyboardEvent) => {
    const entries = Array.from(
      listRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [],
    );
    const index = entries.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      entries[(index + 1) % entries.length]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      entries[(index - 1 + entries.length) % entries.length]?.focus();
    } else if (event.key === "Home") {
      event.preventDefault();
      entries[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      entries[entries.length - 1]?.focus();
    } else if (event.key === "Tab") {
      close(false);
    }
  };

  return (
    <div ref={rootRef} className="relative">
      <Button
        ref={triggerRef}
        variant="ghost"
        size={size}
        icon={icon}
        iconAfter="chevron-down"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen((value) => !value)}
      >
        {label}
      </Button>

      {open && (
        <div
          ref={listRef}
          id={menuId}
          role="menu"
          aria-label={label}
          onKeyDown={onListKeyDown}
          className={cn(
            "absolute right-0 top-full z-[var(--z-sticky)] mt-1 min-w-[12rem] rounded-[var(--radius-md)] border",
            "border-[color:var(--line)] bg-[var(--surface)] p-1 shadow-[var(--shadow-lg)]",
          )}
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => {
                close();
                item.onSelect();
              }}
              className={cn(
                "flex w-full items-center gap-2 rounded-[var(--radius)] px-2.5 py-2 text-left",
                "text-[length:var(--text-sm)] hover:bg-[var(--surface-inset)] focus-visible:bg-[var(--surface-inset)]",
                item.tone === "danger"
                  ? "text-[color:var(--danger-fg)]"
                  : "text-[color:var(--ink)]",
              )}
            >
              {item.icon && <Icon name={item.icon} size={15} className="shrink-0" />}
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
