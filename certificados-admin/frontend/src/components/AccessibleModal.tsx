import {
  ReactNode,
  RefObject,
  useEffect,
  useId,
  useRef,
} from "react";
import { createPortal } from "react-dom";
import { cn } from "../ui/cn";
import { IconButton } from "../ui/Button";

interface AccessibleModalProps {
  open: boolean;
  title: string;
  children: ReactNode;
  footer: ReactNode;
  onClose: () => void;
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Short sentence naming the consequence, read with the title. */
  description?: string;
  size?: "sm" | "md" | "lg";
  /**
   * Destructive confirmations set this so the dialog cannot be dismissed by an
   * accidental backdrop click — Escape and Cancel remain available.
   */
  dismissOnBackdrop?: boolean;
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const SIZES = {
  sm: "max-w-sm",
  md: "max-w-lg",
  lg: "max-w-2xl",
};

/**
 * Modal dialog with a real focus trap.
 *
 * Behaviour that the accompanying test pins: focus moves in on open (to
 * `initialFocusRef` when given), Tab cycles inside the panel, Escape closes,
 * and focus returns to the element that opened it.
 *
 * Additions for WCAG 2.2: background scroll is locked while open, the rest of
 * the app is hidden from assistive tech via `aria-hidden` on the app root, and
 * the panel scrolls internally so a tall dialog never runs off a short viewport
 * (the 1366×768 and 320×568 cases).
 */
export default function AccessibleModal({
  open,
  title,
  children,
  footer,
  onClose,
  initialFocusRef,
  description,
  size = "md",
  dismissOnBackdrop = true,
}: AccessibleModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusable = () =>
      Array.from(panel?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    (initialFocusRef?.current ?? focusable()[0] ?? panel)?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusable();
      if (!elements.length) {
        event.preventDefault();
        panel?.focus();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    // Lock background scroll and hide the app behind the dialog from AT.
    const { body } = document;
    const previousOverflow = body.style.overflow;
    body.style.overflow = "hidden";
    const appRoot = document.getElementById("root");
    appRoot?.setAttribute("aria-hidden", "true");

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      body.style.overflow = previousOverflow;
      appRoot?.removeAttribute("aria-hidden");
      previouslyFocused?.focus();
    };
  }, [initialFocusRef, open]);

  if (!open) return null;

  // Rendered into <body>, outside #root: the effect above marks #root
  // aria-hidden while the dialog is open, and a dialog living inside that
  // subtree would hide itself from assistive tech along with the page.
  return createPortal(
    <div
      className={cn(
        "fixed inset-0 z-[var(--z-modal)] flex items-end justify-center",
        "bg-[rgba(20,32,43,0.55)] p-0 sm:items-center sm:p-4",
      )}
      onMouseDown={(event) => {
        if (dismissOnBackdrop && event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "flex max-h-[92vh] w-full flex-col outline-none",
          "rounded-t-[var(--radius-lg)] border border-[color:var(--line)] bg-[var(--surface)]",
          "shadow-[var(--shadow-lg)] sm:rounded-[var(--radius-lg)]",
          SIZES[size],
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-[color:var(--line)] px-5 py-4">
          <div className="min-w-0">
            <h2
              id={titleId}
              className="text-[length:var(--text-lg)] font-semibold text-[color:var(--ink)]"
            >
              {title}
            </h2>
            {description && (
              <p
                id={descriptionId}
                className="mt-1 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]"
              >
                {description}
              </p>
            )}
          </div>
          <IconButton icon="close" label="Fechar" onClick={onClose} size="sm" />
        </div>

        {/* Internal scroll keeps tall dialogs inside short viewports. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

        <div className="flex flex-col-reverse gap-2 border-t border-[color:var(--line)] px-5 py-4 sm:flex-row sm:justify-end">
          {footer}
        </div>
      </div>
    </div>,
    document.body,
  );
}
