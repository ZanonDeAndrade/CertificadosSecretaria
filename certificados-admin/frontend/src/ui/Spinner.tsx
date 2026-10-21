/**
 * Spinner — used only inside controls that are already busy (buttons, inline
 * status). Content areas get skeletons instead, so the page never flashes a
 * lone spinner where structure could be shown.
 *
 * Decorative: the surrounding control carries `aria-busy` and the status text.
 */
import { cn } from "./cn";

export default function Spinner({
  size = 16,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={cn("motion-safe:animate-spin", className)}
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="2.5"
        opacity="0.25"
      />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
