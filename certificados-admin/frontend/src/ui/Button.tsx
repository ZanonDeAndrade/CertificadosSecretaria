/**
 * Button — one shape for the whole system.
 *
 * Rectangular with a 4px radius: no pills anywhere. Every variant ships all
 * seven states (default, hover, focus, active, disabled, loading, and the
 * destructive treatment), because a component with half its states is what
 * makes an interface feel improvised.
 *
 * `loading` keeps the button's label in place and adds a spinner plus
 * `aria-busy`, so the control never changes width mid-action and screen readers
 * hear that work is in progress instead of a silently disabled button.
 */
import { AnchorHTMLAttributes, ButtonHTMLAttributes, forwardRef, ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "./cn";
import Icon, { IconName } from "./Icon";
import Spinner from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "danger-quiet";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-[var(--brand-700)] text-[color:var(--ink-inverse)] border border-[color:var(--brand-700)] " +
    "hover:bg-[var(--brand-800)] hover:border-[color:var(--brand-800)] " +
    "active:bg-[var(--brand-900)] shadow-[var(--shadow-sm)]",
  secondary:
    "bg-[var(--surface)] text-[color:var(--ink)] border border-[color:var(--line-strong)] " +
    "hover:bg-[var(--surface-sunken)] hover:border-[color:var(--neutral-400)] " +
    "active:bg-[var(--surface-inset)]",
  ghost:
    "bg-transparent text-[color:var(--ink-muted)] border border-transparent " +
    "hover:bg-[var(--surface-inset)] hover:text-[color:var(--ink)] active:bg-[var(--neutral-200)]",
  danger:
    "bg-[var(--danger-solid)] text-[color:var(--ink-inverse)] border border-[color:var(--danger-solid)] " +
    "hover:bg-[var(--danger-solid-hover)] hover:border-[color:var(--danger-solid-hover)] " +
    "shadow-[var(--shadow-sm)]",
  "danger-quiet":
    "bg-[var(--surface)] text-[color:var(--danger-fg)] border border-[color:var(--danger-line)] " +
    "hover:bg-[var(--danger-bg)] active:bg-[#fbdcdc]",
};

/* Heights meet the 44px touch floor at md/lg. `sm` is 32px and is reserved for
 * controls inside table rows and toolbars, where a pointer is the real input
 * and the row itself provides a larger hit area. */
const SIZES: Record<Size, string> = {
  sm: "h-8 px-2.5 text-[length:var(--text-sm)] gap-1.5",
  md: "h-10 px-3.5 text-[length:var(--text-base)] gap-2",
  lg: "h-11 px-5 text-[length:var(--text-base)] gap-2",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  /** Icon rendered before the label. */
  icon?: IconName;
  /** Icon rendered after the label (use for "next"-style forward motion). */
  iconAfter?: IconName;
  loading?: boolean;
  /** Stretch to the container width — used in the mobile drawer and forms. */
  block?: boolean;
  children?: ReactNode;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "secondary",
    size = "md",
    icon,
    iconAfter,
    loading = false,
    block = false,
    disabled,
    className,
    children,
    type = "button",
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center rounded-[var(--radius)] font-medium",
        "transition-colors duration-[var(--duration-fast)]",
        "disabled:cursor-not-allowed disabled:opacity-55 disabled:shadow-none",
        // Disabled must not keep a saturated fill — a dimmed brand block still
        // reads as "press me". Neutralise it instead.
        "disabled:bg-[var(--neutral-100)] disabled:text-[color:var(--ink-subtle)] disabled:border-[color:var(--line)]",
        block && "w-full",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Spinner size={size === "sm" ? 14 : 16} />
      ) : icon ? (
        <Icon name={icon} size={size === "sm" ? 15 : 17} />
      ) : null}
      {children}
      {iconAfter && !loading ? (
        <Icon name={iconAfter} size={size === "sm" ? 15 : 17} />
      ) : null}
    </button>
  );
});

export default Button;

/**
 * IconButton — for genuinely icon-only controls (drawer toggle, close, zoom).
 * `label` is required and becomes the accessible name; the 40px box keeps the
 * target comfortable even though the glyph is small.
 */
interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  label: string;
  variant?: Variant;
  size?: "sm" | "md";
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    { icon, label, variant = "ghost", size = "md", className, type = "button", ...rest },
    ref,
  ) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-[var(--radius)]",
        "transition-colors duration-[var(--duration-fast)]",
        "disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" ? "h-8 w-8" : "h-10 w-10",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      <Icon name={icon} size={size === "sm" ? 16 : 19} />
    </button>
  );
  },
);

/* Shared chrome so a link that acts as a button is visually identical to one,
 * without nesting a <Link> inside a <button> — which produces invalid,
 * double-focusable markup. */
function buttonChrome(variant: Variant, size: Size, block: boolean, className?: string) {
  return cn(
    "inline-flex items-center justify-center rounded-[var(--radius)] font-medium no-underline",
    "transition-colors duration-[var(--duration-fast)]",
    block && "w-full",
    VARIANTS[variant],
    SIZES[size],
    className,
  );
}

/** Internal navigation styled as a button. */
export function LinkButton({
  to,
  variant = "secondary",
  size = "md",
  icon,
  iconAfter,
  block = false,
  className,
  children,
  ...rest
}: {
  to: string;
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  iconAfter?: IconName;
  block?: boolean;
  children: ReactNode;
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  return (
    <Link to={to} className={buttonChrome(variant, size, block, className)} {...rest}>
      {icon && <Icon name={icon} size={size === "sm" ? 15 : 17} />}
      {children}
      {iconAfter && <Icon name={iconAfter} size={size === "sm" ? 15 : 17} />}
    </Link>
  );
}

/** External navigation (downloads, model spreadsheet) styled as a button. */
export function AnchorButton({
  variant = "secondary",
  size = "md",
  icon,
  iconAfter,
  block = false,
  className,
  children,
  ...rest
}: {
  variant?: Variant;
  size?: Size;
  icon?: IconName;
  iconAfter?: IconName;
  block?: boolean;
  children: ReactNode;
} & AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a className={buttonChrome(variant, size, block, className)} {...rest}>
      {icon && <Icon name={icon} size={size === "sm" ? 15 : 17} />}
      {children}
      {iconAfter && <Icon name={iconAfter} size={size === "sm" ? 15 : 17} />}
    </a>
  );
}
