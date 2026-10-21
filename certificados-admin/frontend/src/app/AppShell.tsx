/**
 * Application shell — persistent sidebar on desktop, drawer on mobile, topbar
 * with the signed-in user, help and sign-out.
 *
 * Structure notes that matter for accessibility:
 *  - one <nav> landmark for the primary navigation, labelled;
 *  - the skip link is the first focusable element and targets #conteudo;
 *  - the drawer traps focus, closes on Escape, restores focus to its trigger,
 *    and marks the rest of the shell inert while open;
 *  - route changes move focus to the main region and announce the page name,
 *    which is what a SPA otherwise loses compared with real page loads.
 */
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { cn } from "../ui/cn";
import Icon from "../ui/Icon";
import Button, { IconButton } from "../ui/Button";
import { useAuth } from "./AuthContext";
import { NAV_GROUPS, NAV_ITEMS, NavItem } from "./navigation";
import { roleLabel } from "./permissions";
import { useInstitution } from "./InstitutionContext";

/* ── Brand mark ──────────────────────────────────────────────────────────────
 * The product name and AMF logo live here so every authenticated layout uses
 * the same identity.
 */
export const APP_NAME = "Certificados Faculdade AMF";

function BrandMark({ className }: { className?: string }) {
  return (
    <img
      src="/logo-amf.jpg"
      alt=""
      aria-hidden="true"
      className={cn(
        "shrink-0 rounded-[var(--radius-sm)] bg-white object-contain",
        className,
      )}
    />
  );
}

/** Nav items the current user is allowed to see. */
function useVisibleNav(): NavItem[] {
  const { can } = useAuth();
  return NAV_ITEMS.filter((item) => !item.permission || can(item.permission));
}

function NavList({
  items,
  onNavigate,
  variant,
}: {
  items: NavItem[];
  onNavigate?: () => void;
  variant: "sidebar" | "drawer";
}) {
  return (
    <>
      {NAV_GROUPS.map((group) => {
        const groupItems = items.filter((item) => item.group === group);
        if (groupItems.length === 0) return null;
        return (
          <div key={group} className="mb-5 last:mb-0">
            <h3 className="mb-1.5 px-3 text-[length:var(--text-2xs)] font-semibold uppercase tracking-[0.08em] text-[color:var(--ink-nav-muted)]">
              {group}
            </h3>
            <ul className="space-y-0.5">
              {groupItems.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      cn(
                        "flex items-start gap-2.5 rounded-[var(--radius)] px-3 transition-colors duration-[var(--duration-fast)]",
                        variant === "drawer" ? "py-2.5" : "py-2",
                        "text-[length:var(--text-base)]",
                        isActive
                          ? "bg-[var(--surface-nav-active)] font-medium text-[color:var(--ink-inverse)]"
                          : "text-[color:var(--ink-nav)] hover:bg-[var(--surface-nav-hover)] hover:text-[color:var(--ink-inverse)]",
                      )
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {/* 2px rule marks the active item for anyone who cannot
                            distinguish the background tint. */}
                        <span
                          aria-hidden="true"
                          className={cn(
                            "mt-0.5 h-5 w-0.5 shrink-0 rounded-full",
                            isActive ? "bg-[var(--brand-300)]" : "bg-transparent",
                          )}
                        />
                        <Icon name={item.icon} size={18} className="mt-0.5 shrink-0" />
                        <span className="min-w-0">
                          <span className="block">{item.label}</span>
                          {variant === "drawer" && item.hint && (
                            <span className="mt-0.5 block text-[length:var(--text-xs)] text-[color:var(--ink-nav-muted)]">
                              {item.hint}
                            </span>
                          )}
                        </span>
                      </>
                    )}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const { user, signOut, can } = useAuth();
  const { institution_name: institutionName } = useInstitution();
  const items = useVisibleNav();
  const location = useLocation();
  const navigate = useNavigate();

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerToggleRef = useRef<HTMLButtonElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  const currentItem = items.find((item) => location.pathname.startsWith(item.to));

  /* Close the drawer on navigation. */
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  /* SPA route changes: move focus to main so keyboard and screen-reader users
   * land on the new content instead of staying where the old link was. */
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [location.pathname]);

  /* Drawer: focus trap, Escape, and focus restoration. */
  useEffect(() => {
    if (!drawerOpen) return;
    const panel = drawerRef.current;
    const focusables = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
    focusables()[0]?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setDrawerOpen(false);
        drawerToggleRef.current?.focus();
        return;
      }
      if (event.key !== "Tab") return;
      const elements = focusables();
      if (!elements.length) return;
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

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [drawerOpen]);

  const handleSignOut = useCallback(async () => {
    setSigningOut(true);
    try {
      await signOut();
      navigate("/entrar", { replace: true });
    } finally {
      setSigningOut(false);
    }
  }, [signOut, navigate]);

  return (
    <div className="min-h-screen bg-[var(--surface-sunken)]">
      <a href="#conteudo" className="skip-link">
        Ir para o conteúdo
      </a>

      {/* ── Desktop sidebar ─────────────────────────────────────────────── */}
      <div
        className={cn(
          "on-dark fixed inset-y-0 left-0 z-[var(--z-sticky)] hidden w-[var(--sidebar-width)] lg:flex",
          "flex-col border-r border-[color:var(--line-nav)] bg-[var(--surface-nav)]",
        )}
      >
        <div className="flex h-[var(--topbar-height)] items-center gap-2.5 border-b border-[color:var(--line-nav)] px-4 text-[color:var(--ink-inverse)]">
          <BrandMark className="h-10 w-10" />
          <span className="min-w-0">
            <span className="block text-[length:var(--text-sm)] font-semibold leading-tight">
              {APP_NAME}
            </span>
            <span className="block truncate text-[length:var(--text-2xs)] leading-tight text-[color:var(--ink-nav-muted)]">
              {institutionName}
            </span>
          </span>
        </div>

        <nav aria-label="Navegação principal" className="flex-1 overflow-y-auto p-3">
          <NavList items={items} variant="sidebar" />
        </nav>

        <div className="border-t border-[color:var(--line-nav)] p-3">
          <p className="px-3 text-[length:var(--text-2xs)] text-[color:var(--ink-nav-muted)]">
            Ambiente administrativo. As ações realizadas aqui são registradas.
          </p>
        </div>
      </div>

      {/* ── Mobile drawer ───────────────────────────────────────────────── */}
      {drawerOpen && (
        <div className="fixed inset-0 z-[var(--z-drawer)] lg:hidden">
          <div
            className="absolute inset-0 bg-[rgba(20,32,43,0.55)]"
            onClick={() => {
              setDrawerOpen(false);
              drawerToggleRef.current?.focus();
            }}
            aria-hidden="true"
          />
          <div
            ref={drawerRef}
            id="menu-navegacao"
            role="dialog"
            aria-modal="true"
            aria-label="Menu de navegação"
            className={cn(
              "on-dark absolute inset-y-0 left-0 flex w-[17.5rem] max-w-[85vw] flex-col",
              "border-r border-[color:var(--line-nav)] bg-[var(--surface-nav)] shadow-[var(--shadow-lg)]",
            )}
          >
            <div className="flex h-[var(--topbar-height)] items-center justify-between gap-2 border-b border-[color:var(--line-nav)] px-3 text-[color:var(--ink-inverse)]">
              <span className="flex min-w-0 items-center gap-2.5">
                <BrandMark className="h-10 w-10" />
                <span className="min-w-0">
                  <span className="block text-[length:var(--text-sm)] font-semibold leading-tight">
                    {APP_NAME}
                  </span>
                  <span className="block truncate text-[length:var(--text-2xs)] text-[color:var(--ink-nav-muted)]">
                    {institutionName}
                  </span>
                </span>
              </span>
              <IconButton
                icon="close"
                label="Fechar menu"
                onClick={() => {
                  setDrawerOpen(false);
                  drawerToggleRef.current?.focus();
                }}
                className="text-[color:var(--ink-nav)] hover:bg-[var(--surface-nav-hover)] hover:text-[color:var(--ink-inverse)]"
              />
            </div>

            <nav aria-label="Navegação principal" className="flex-1 overflow-y-auto p-3">
              <NavList items={items} variant="drawer" />
            </nav>

            <div className="border-t border-[color:var(--line-nav)] p-3">
              <p className="mb-2 px-1 text-[length:var(--text-xs)] text-[color:var(--ink-nav)]">
                {user?.username}
                <span className="block text-[length:var(--text-2xs)] text-[color:var(--ink-nav-muted)]">
                  {roleLabel(user?.role)}
                </span>
              </p>
              <Button
                variant="secondary"
                icon="logout"
                block
                loading={signingOut}
                onClick={handleSignOut}
              >
                Sair
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Content column ──────────────────────────────────────────────── */}
      <div className="lg:pl-[var(--sidebar-width)]">
        <header
          className={cn(
            "sticky top-0 z-[var(--z-sticky)] flex h-[var(--topbar-height)] items-center gap-2",
            "border-b border-[color:var(--line)] bg-[var(--surface)] px-3 sm:px-4",
          )}
        >
          <IconButton
            ref={drawerToggleRef}
            icon="menu"
            label="Abrir menu de navegação"
            aria-expanded={drawerOpen}
            aria-controls="menu-navegacao"
            onClick={() => setDrawerOpen(true)}
            className="lg:hidden"
          />

          {/* Mobile: the brand sits in the topbar since the sidebar is hidden. */}
          <Link
            to={can("dashboard.read") ? "/painel" : "/historico"}
            className="flex min-w-0 items-center gap-2 rounded-[var(--radius)] text-[color:var(--ink)] lg:hidden"
          >
            <BrandMark className="h-9 w-9" />
            <span className="truncate text-[length:var(--text-base)] font-semibold">
              {APP_NAME}
            </span>
          </Link>

          {/* Desktop: current section, so the topbar states where you are. */}
          <p className="hidden min-w-0 truncate text-[length:var(--text-base)] font-medium text-[color:var(--ink)] lg:block">
            {currentItem?.label ?? APP_NAME}
          </p>

          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            <Link
              to="/ajuda"
              className={cn(
                "inline-flex h-10 items-center gap-1.5 rounded-[var(--radius)] px-2.5",
                "text-[length:var(--text-sm)] font-medium text-[color:var(--ink-muted)]",
                "hover:bg-[var(--surface-inset)] hover:text-[color:var(--ink)]",
              )}
            >
              <Icon name="help" size={17} />
              {/* Below `sm` the label is hidden, which would leave an
                  icon-only link with no accessible name. The sr-only copy keeps
                  the name present at every width. */}
              <span className="hidden sm:inline">Ajuda</span>
              <span className="sr-only sm:hidden">Ajuda</span>
            </Link>

            <div className="hidden h-6 w-px bg-[var(--line)] sm:block" />

            <Link
              to="/perfil"
              className={cn(
                "inline-flex items-center gap-2 rounded-[var(--radius)] px-1.5 py-1",
                "hover:bg-[var(--surface-inset)]",
              )}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-full)]",
                  "bg-[var(--brand-100)] text-[length:var(--text-sm)] font-semibold text-[color:var(--brand-800)]",
                )}
              >
                {(user?.username ?? "?").slice(0, 2).toUpperCase()}
              </span>
              <span className="hidden min-w-0 text-left sm:block">
                <span className="block max-w-[10rem] truncate text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]">
                  {user?.username}
                </span>
                <span className="block text-[length:var(--text-2xs)] text-[color:var(--ink-muted)]">
                  {roleLabel(user?.role)}
                </span>
              </span>
              {/* The avatar is decorative initials, so below `sm` this link
                  would otherwise have no accessible name at all. */}
              <span className="sr-only sm:hidden">
                Meu perfil — {user?.username}, {roleLabel(user?.role)}
              </span>
            </Link>

            <Button
              size="sm"
              variant="secondary"
              icon="logout"
              loading={signingOut}
              onClick={handleSignOut}
              className="hidden sm:inline-flex"
            >
              Sair
            </Button>
            <IconButton
              icon="logout"
              label="Sair"
              onClick={handleSignOut}
              disabled={signingOut}
              className="sm:hidden"
            />
          </div>
        </header>

        <main
          id="conteudo"
          ref={mainRef}
          tabIndex={-1}
          className="mx-auto w-full max-w-[var(--content-max)] px-3 py-5 outline-none sm:px-5 sm:py-6 lg:px-8"
        >
          {children}
        </main>
      </div>
    </div>
  );
}
