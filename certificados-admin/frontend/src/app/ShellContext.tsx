/**
 * What a page may ask of the application shell.
 *
 * The template editor needs the whole viewport: it hides the sidebar and the
 * topbar ("immersive" mode) and offers a menu button of its own that opens the
 * navigation drawer. While it holds unsaved work it registers a leave guard, so
 * every way out of the page through the shell (a drawer link, "Sair") asks
 * first, the same way the editor's own "Voltar" does.
 *
 * The default value is inert, so screens render unchanged in tests and in any
 * tree without an AppShell.
 */
import { createContext, useContext } from "react";

/** Called instead of leaving; runs `proceed` once the operator confirms. */
export type LeaveGuard = (proceed: () => void) => void;

export interface ShellControls {
  /** Sidebar and topbar hidden; the page owns the viewport. */
  immersive: boolean;
  setImmersive: (value: boolean) => void;
  drawerOpen: boolean;
  /** `trigger` gets the focus back when the drawer closes. */
  openDrawer: (trigger?: HTMLElement | null) => void;
  setLeaveGuard: (guard: LeaveGuard | null) => void;
}

const noop = () => undefined;

export const ShellContext = createContext<ShellControls>({
  immersive: false,
  setImmersive: noop,
  drawerOpen: false,
  openDrawer: noop,
  setLeaveGuard: noop,
});

export function useShell(): ShellControls {
  return useContext(ShellContext);
}
