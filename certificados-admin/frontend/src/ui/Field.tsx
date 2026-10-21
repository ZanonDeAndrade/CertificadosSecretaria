/**
 * Form primitives.
 *
 * `Field` owns the accessibility wiring that is easy to get wrong by hand: it
 * generates the id, binds a real <label> (never a placeholder standing in for
 * one), and links hint and error text through `aria-describedby` so both are
 * announced. Errors also set `aria-invalid` and are announced politely.
 *
 * Controls are rendered through a render-prop so the wiring cannot be bypassed:
 *
 *   <Field label="Nome" hint="Como consta no diploma">
 *     {(p) => <TextInput {...p} value={v} onChange={…} />}
 *   </Field>
 */
import {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  forwardRef,
  useId,
} from "react";
import { cn } from "./cn";

/** Props the Field hands to its control. */
export interface ControlProps {
  id: string;
  "aria-describedby": string | undefined;
  "aria-invalid": true | undefined;
  required: boolean | undefined;
}

interface FieldProps {
  label: string;
  /** Persistent helper text. Shown above the control so it is read before use. */
  hint?: ReactNode;
  error?: string;
  required?: boolean;
  /** Hide the visual label but keep it for assistive tech (toolbar filters). */
  labelHidden?: boolean;
  className?: string;
  children: (props: ControlProps) => ReactNode;
}

export function Field({
  label,
  hint,
  error,
  required,
  labelHidden = false,
  className,
  children,
}: FieldProps) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <label
        htmlFor={id}
        className={cn(
          "text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]",
          labelHidden && "sr-only",
        )}
      >
        {label}
        {required && (
          <>
            {" "}
            <span className="text-[color:var(--danger-fg)]" aria-hidden="true">
              *
            </span>
            <span className="sr-only">(obrigatório)</span>
          </>
        )}
      </label>

      {hint && !labelHidden && (
        <p id={hintId} className="text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
          {hint}
        </p>
      )}

      {children({
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
        required: required || undefined,
      })}

      {error && (
        <p
          id={errorId}
          className="flex items-start gap-1.5 text-[length:var(--text-xs)] font-medium text-[color:var(--danger-fg)]"
        >
          <span aria-hidden="true" className="mt-px leading-none">
            &#9679;
          </span>
          {error}
        </p>
      )}
    </div>
  );
}

/* Shared control chrome. 40px tall — comfortably above the touch floor and
 * consistent with `Button` size md, so a field and its button align exactly. */
const CONTROL = cn(
  "w-full rounded-[var(--radius)] border bg-[var(--surface)] px-3",
  "text-[length:var(--text-base)] text-[color:var(--ink)]",
  "placeholder:text-[color:var(--ink-subtle)]",
  "transition-colors duration-[var(--duration-fast)]",
  "hover:border-[color:var(--neutral-400)]",
  "disabled:cursor-not-allowed disabled:bg-[var(--surface-inset)] disabled:text-[color:var(--ink-subtle)]",
  "aria-[invalid=true]:border-[color:var(--danger-solid)]",
);

export const TextInput = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement>
>(function TextInput({ className, ...rest }, ref) {
  return (
    <input
      ref={ref}
      className={cn(CONTROL, "h-10 border-[color:var(--line-strong)]", className)}
      {...rest}
    />
  );
});

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, rows = 4, ...rest }, ref) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(
        CONTROL,
        "resize-y border-[color:var(--line-strong)] py-2 leading-[var(--leading-normal)]",
        className,
      )}
      {...rest}
    />
  );
});

export const Select = forwardRef<
  HTMLSelectElement,
  SelectHTMLAttributes<HTMLSelectElement>
>(function Select({ className, children, ...rest }, ref) {
  return (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          CONTROL,
          "h-10 appearance-none border-[color:var(--line-strong)] pr-9",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
      {/* Chevron is decorative; the native select already announces itself. */}
      <svg
        viewBox="0 0 24 24"
        width="16"
        height="16"
        aria-hidden="true"
        focusable="false"
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-[color:var(--ink-muted)]"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M5 9l7 7 7-7" />
      </svg>
    </div>
  );
});

/**
 * Checkbox with a real label. The 44×44 wrapper gives the touch target its size
 * without inflating the drawn box.
 */
export function Checkbox({
  label,
  labelHidden = false,
  compact = false,
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  labelHidden?: boolean;
  /**
   * Shrinks the hit box to 32px for use inside dense table rows, where the row
   * itself is the large target and a 44px box would set the row height.
   */
  compact?: boolean;
}) {
  const id = useId();
  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      <span
        className={cn(
          "relative inline-flex shrink-0 items-center justify-center",
          compact ? "h-8 w-8" : "h-11 w-11",
        )}
      >
        {/* 24px is the WCAG 2.2 (2.5.8) minimum target size. Even the compact
            variant holds it — a smaller box was flagged in the responsive
            audit at 320px, where the checkbox is a genuine touch target. */}
        <input
          id={id}
          type="checkbox"
          className={cn(
            "h-6 w-6 cursor-pointer rounded-[var(--radius-sm)]",
            "border border-[color:var(--line-strong)] accent-[var(--brand-700)]",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
          {...rest}
        />
      </span>
      <label
        htmlFor={id}
        className={cn(
          "cursor-pointer text-[length:var(--text-sm)] text-[color:var(--ink)]",
          labelHidden && "sr-only",
        )}
      >
        {label}
      </label>
    </div>
  );
}
