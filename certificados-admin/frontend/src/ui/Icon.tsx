/**
 * Icon set — authored SVG paths on one 24×24 grid at a single 1.75 stroke
 * weight, round caps and joins, always `currentColor`. Kept in one file so the
 * stroke vocabulary cannot drift between screens.
 *
 * Icons are decorative by default (`aria-hidden`), because in this system every
 * icon sits next to a real text label. Pass a `title` only for the rare control
 * that is genuinely icon-only, and it becomes an accessible graphic instead.
 */
import { SVGProps } from "react";

export type IconName =
  | "dashboard"
  | "certificate"
  | "issue"
  | "history"
  | "users"
  | "audit"
  | "template"
  | "verify"
  | "logout"
  | "menu"
  | "close"
  | "chevron-left"
  | "chevron-right"
  | "chevron-down"
  | "chevron-up"
  | "search"
  | "download"
  | "upload"
  | "warning"
  | "success"
  | "error"
  | "info"
  | "help"
  | "revoked"
  | "clock"
  | "refresh"
  | "plus"
  | "trash"
  | "duplicate"
  | "undo"
  | "redo"
  | "zoom-in"
  | "zoom-out"
  | "grid"
  | "eye"
  | "save"
  | "user"
  | "filter"
  | "external"
  | "arrow-right"
  | "spreadsheet"
  | "shield"
  | "offline"
  | "text"
  | "image"
  | "lock"
  | "settings"
  | "folder";

/* Path data only — the wrapper owns sizing, stroke width and color. */
const PATHS: Record<IconName, string> = {
  dashboard: "M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6v-9h-6v9Zm0-16v5h6V4h-6Z",
  certificate:
    "M9 15a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 0-2 6 2-1.2L11 21l-2-6Zm6-8h5M15 11h5M4 4h16v13H4z",
  issue: "M14 3v5h5M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-5ZM12 11v6m-3-3h6",
  history:
    "M4 8h10M4 12h10M4 16h6m9.5 1.5L18 16v-3.5M18 21a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z",
  users:
    "M15 20v-1.5a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4V20M8.5 10.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7ZM22 20v-1.5a4 4 0 0 0-3-3.87M16 3.63a4 4 0 0 1 0 7.75",
  audit:
    "M9 3h6l1 2h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h3l1-2Zm-1 9 2.5 2.5L16 9",
  template:
    "M4 5h16v14H4zM4 9h16M9 9v10",
  verify: "M12 3.5 4.5 6.5v5c0 4.4 3.1 8.4 7.5 9.5 4.4-1.1 7.5-5.1 7.5-9.5v-5L12 3.5Zm-3 8 2.2 2.2L15.5 10",
  logout: "M15 17v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7a2 2 0 0 1 2 2v2m3 5H10m9 0-3-3m3 3-3 3",
  menu: "M4 7h16M4 12h16M4 17h16",
  close: "M6 6l12 12M18 6 6 18",
  "chevron-left": "M15 5l-7 7 7 7",
  "chevron-right": "M9 5l7 7-7 7",
  "chevron-down": "M5 9l7 7 7-7",
  "chevron-up": "M5 15l7-7 7 7",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5.2-1.8L21 21",
  download: "M12 3v12m0 0 4-4m-4 4-4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2",
  upload: "M12 21V9m0 0 4 4M12 9l-4 4M4 7V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v2",
  warning: "M12 4 2.5 20.5h19L12 4Zm0 6v4.5m0 3v.5",
  success: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-3.5-9.2L11 14.5l4.8-5",
  error: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM9 9l6 6m0-6-6 6",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-9.5V16m0-8.2v.4",
  help: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-2.2-11.3a2.3 2.3 0 1 1 3 2.2c-.5.2-.8.7-.8 1.3v.6m0 2.7v.4",
  revoked: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM5.6 5.6l12.8 12.8",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13.5V12l3 2",
  refresh: "M20 12a8 8 0 1 1-2.6-5.9M20 4v4h-4",
  plus: "M12 5v14M5 12h14",
  trash: "M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m-8 0 1 13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-13",
  duplicate:
    "M9 9V5a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-4M5 9h9a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1Z",
  undo: "M4 9h10a5 5 0 0 1 0 10h-6M4 9l4-4M4 9l4 4",
  redo: "M20 9H10a5 5 0 0 0 0 10h6m4-10-4-4m4 4-4 4",
  "zoom-in": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5.2-1.8L21 21M8.5 11h5M11 8.5v5",
  "zoom-out": "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5.2-1.8L21 21M8.5 11h5",
  grid: "M4 9h16M4 15h16M9 4v16M15 4v16",
  eye: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Zm9.5 2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  save: "M5 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm3 0v5h7V4M8 14h8v7H8z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9v-1a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v1",
  filter: "M3 5h18l-7 8v6l-4 2v-8L3 5Z",
  external: "M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  "arrow-right": "M4 12h15m0 0-5-5m5 5-5 5",
  spreadsheet: "M4 4h16v16H4zM4 9h16M4 14.5h16M10 9v11M15 9v11",
  shield: "M12 3.5 4.5 6.5v5c0 4.4 3.1 8.4 7.5 9.5 4.4-1.1 7.5-5.1 7.5-9.5v-5L12 3.5Z",
  offline:
    "M3 3l18 18M8.5 16.4a5 5 0 0 1 7 0M5 12.9a10 10 0 0 1 4-2.4m3-.6a10 10 0 0 1 7 3M12 20h.01",
  text: "M5 6V4h14v2M12 4v16m-3 0h6",
  image: "M4 5h16v14H4zM4 16l4.5-4.5 3 3L15 11l5 5M9 9.5h.01",
  lock: "M6 11h12a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1Zm2 0V7.5a4 4 0 0 1 8 0V11",
  settings:
    "M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm7-3.5 2-1-2-3.5-2.2.3-1.3-.8-.8-2.1h-4L9.9 7l-1.3.8-2.2-.3-2 3.5 2 1v1.5l-2 1 2 3.5 2.2-.3 1.3.8.8 2.1h4l.8-2.1 1.3-.8 2.2.3 2-3.5-2-1V12Z",
  folder: "M3 6h7l2 2h9v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6Z",
};

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  /** Pixel size of the square icon box. Defaults to 20 (inline with UI text). */
  size?: number;
  /**
   * Accessible name. Provide it ONLY when the icon is the sole content of a
   * control; otherwise the neighbouring text already names the action and a
   * second name makes screen readers announce it twice.
   */
  title?: string;
}

export default function Icon({ name, size = 20, title, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
      {...rest}
    >
      {title ? <title>{title}</title> : null}
      <path d={PATHS[name]} />
    </svg>
  );
}
