/**
 * Route guards.
 *
 * `RequireAuth` sends signed-out users to /entrar and remembers where they were
 * heading, so a deep link survives the sign-in round trip.
 *
 * `RequirePermission` renders an explicit "sem permissão" screen rather than
 * redirecting silently: a user who followed a colleague's link deserves to know
 * the page exists and their profile cannot open it, not to be bounced somewhere
 * unrelated with no explanation.
 */
import { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { Permission, roleLabel } from "./permissions";
import Panel from "../ui/Panel";
import { EmptyState } from "../ui/Feedback";
import PageHeader from "../ui/PageHeader";
import { LinkButton } from "../ui/Button";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  const location = useLocation();

  if (!ready) return <FullPageLoading />;
  if (!user) {
    return <Navigate to="/entrar" replace state={{ from: location.pathname }} />;
  }
  return <>{children}</>;
}

export function RequirePasswordChanged({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user?.must_change_password) {
    return <Navigate to="/trocar-senha" replace />;
  }
  return <>{children}</>;
}

export function RequirePermission({
  permission,
  children,
}: {
  permission: Permission;
  children: ReactNode;
}) {
  const { can, user } = useAuth();
  if (can(permission)) return <>{children}</>;
  const home = can("dashboard.read") ? "/painel" : "/historico";

  return (
    <>
      <PageHeader
        title="Sem permissão para esta tela"
        description="Seu perfil de acesso não inclui esta área do sistema."
      />
      <Panel>
        <EmptyState
          icon="lock"
          title="Acesso restrito"
          description={
            <>
              Você está conectado como <strong>{user?.username}</strong> com o perfil{" "}
              <strong>{roleLabel(user?.role)}</strong>, que não tem acesso a esta
              tela. Se precisar dela para o seu trabalho, peça a um administrador
              para revisar seu perfil.
            </>
          }
          action={
            <LinkButton
              to={home}
              variant="secondary"
              icon={can("dashboard.read") ? "dashboard" : "history"}
            >
              {can("dashboard.read") ? "Voltar ao painel" : "Voltar ao histórico"}
            </LinkButton>
          }
        />
      </Panel>
    </>
  );
}

/** Shown while the initial session check is in flight. */
export function FullPageLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-screen items-center justify-center bg-[var(--surface-sunken)] p-6 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]"
    >
      Verificando sua sessão…
    </div>
  );
}
