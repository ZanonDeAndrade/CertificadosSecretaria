/**
 * Dropdown menu for secondary actions.
 *
 * A trigger button and a `menu` of `menuitem` buttons, following the WAI-ARIA
 * menu button pattern: Escape and an outside click close it, arrow keys move
 * between items, and closing returns the focus to the trigger. Used by the
 * editor toolbar to keep rarely used actions off the single row, and by the
 * download control of a per-work certificate.
 *
 * The list is rendered in a portal, positioned from the trigger, so a menu
 * inside a scrolling table or a dialog is never clipped by its container. It
 * opens below the trigger, or above it when the room below is too small, and
 * follows the trigger while the page or a table scrolls underneath it.
 */
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
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
  /** Visible label of the trigger; its accessible name when `labelHidden`. */
  label: string;
  icon?: IconName;
  items: MenuItem[];
  size?: "sm" | "md";
  /** Icon-only trigger (table rows): the label is announced, not shown. */
  labelHidden?: boolean;
  /** Accessible name of a visible trigger when it needs more than its label. */
  ariaLabel?: string;
  variant?: "ghost" | "secondary";
  disabled?: boolean;
}

interface Placement {
  top?: number;
  bottom?: number;
  right: number;
  maxHeight: number;
}

const GAP = 4;
const MARGIN = 8;
/** Below this, the list opens upward instead, when there is more room above. */
const MIN_HEIGHT = 160;

function placeFrom(rect: DOMRect): Placement {
  const right = Math.max(MARGIN, window.innerWidth - rect.right);
  const below = window.innerHeight - rect.bottom - GAP - MARGIN;
  const above = rect.top - GAP - MARGIN;
  if (below >= MIN_HEIGHT || below >= above) {
    return { top: rect.bottom + GAP, right, maxHeight: Math.max(MIN_HEIGHT, below) };
  }
  return {
    bottom: window.innerHeight - rect.top + GAP,
    right,
    maxHeight: Math.max(MIN_HEIGHT, above),
  };
}

function inViewport(rect: DOMRect): boolean {
  return (
    rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < window.innerWidth
  );
}

export default function Menu({
  label,
  icon,
  items,
  size = "md",
  labelHidden = false,
  ariaLabel,
  variant = "ghost",
  disabled = false,
}: MenuProps) {
  const [placement, setPlacement] = useState<Placement | null>(null);
  const open = placement !== null;
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  const openMenu = () => {
    const rect = triggerRef.current?.getBoundingClientRect();
    setPlacement(rect ? placeFrom(rect) : null);
  };

  useEffect(() => {
    if (!open) return;
    listRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();

    const inside = (target: EventTarget | null) =>
      Boolean(
        rootRef.current?.contains(target as Node) || listRef.current?.contains(target as Node),
      );
    const onPointerDown = (event: PointerEvent) => {
      if (!inside(event.target)) setPlacement(null);
    };
    /* The list is positioned from the trigger. When the page, a table or a
     * dialog scrolls underneath it (a scroll started right before the click
     * still fires after the menu opened) or the window resizes, follow the
     * trigger instead of drifting away from it, and close once the trigger
     * leaves the viewport. The list's own scrolling changes nothing. */
    const follow = (event: Event) => {
      if (listRef.current?.contains(event.target as Node)) return;
      const rect = triggerRef.current?.getBoundingClientRect();
      setPlacement(rect && inViewport(rect) ? placeFrom(rect) : null);
    };
    document.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("scroll", follow, true);
    window.addEventListener("resize", follow);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("scroll", follow, true);
      window.removeEventListener("resize", follow);
    };
  }, [open]);

  const close = (restoreFocus = true) => {
    setPlacement(null);
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
    <div ref={rootRef} className="relative inline-flex">
      <Button
        ref={triggerRef}
        variant={variant}
        size={size}
        icon={icon}
        iconAfter="chevron-down"
        aria-label={labelHidden ? label : ariaLabel}
        title={labelHidden ? label : undefined}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        disabled={disabled}
        className={labelHidden ? "px-1.5" : undefined}
        onClick={() => (open ? close() : openMenu())}
      >
        {labelHidden ? null : label}
      </Button>

      {open &&
        createPortal(
          <div
            ref={listRef}
            id={menuId}
            role="menu"
            aria-label={labelHidden ? label : (ariaLabel ?? label)}
            onKeyDown={onListKeyDown}
            style={{
              position: "fixed",
              top: placement.top,
              bottom: placement.bottom,
              right: placement.right,
              maxHeight: placement.maxHeight,
            }}
            className={cn(
              /* Above the modal layer: the menu may open from a dialog's footer. */
              "z-[var(--z-toast)] min-w-[12rem] max-w-[min(24rem,calc(100vw-1rem))] overflow-y-auto rounded-[var(--radius-md)] border",
              "border-[color:var(--line)] bg-[var(--surface)] p-1 shadow-[var(--shadow-lg)]",
            )}
          >
            {items.map((item, index) => (
              <button
                key={`${index}-${item.label}`}
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
                <span className="min-w-0 break-words">{item.label}</span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </div>
  );
}
