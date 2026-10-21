/**
 * Perfil — what this account is and what it can do, plus the one security
 * action a user can take for themselves: ending every open session.
 *
 * That action matters on shared secretariat machines, where someone may have
 * stayed signed in on another computer. It is destructive to the current
 * session too, so it confirms first and says so plainly.
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader, PanelBody } from "../ui/Panel";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import Icon from "../ui/Icon";
import ConfirmDialog from "../ui/ConfirmDialog";
import { useAuth } from "../app/AuthContext";
import { failureMessage } from "../app/useAsyncData";
import { api } from "../services/api";
import {
  NAV_ITEMS,
} from "../app/navigation";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, Role, roleLabel } from "../app/permissions";
import PasswordChangeForm from "../components/PasswordChangeForm";

export default function Perfil() {
  const { user, can, signOut } = useAuth();
  const navigate = useNavigate();

  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const visibleScreens = NAV_ITEMS.filter(
    (item) => !item.permission || can(item.permission),
  );
  const hiddenScreens = NAV_ITEMS.filter(
    (item) => item.permission && !can(item.permission),
  );

  const revokeAllSessions = async () => {
    setBusy(true);
    setError("");
    try {
      await api.post("/auth/sessions/revoke-all");
      // The backend clears the cookie; drop local state and return to sign-in.
      await signOut();
      navigate("/entrar", { replace: true });
    } catch (requestError) {
      setError(failureMessage(requestError, "Não foi possível encerrar as sessões."));
      setBusy(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Meu perfil"
        description="Informações da sua conta e do seu nível de acesso."
      />

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
        <Panel>
          <PanelHeader title="Conta" />
          <PanelBody>
            <dl className="divide-y divide-[color:var(--line)]">
              <div className="grid gap-1 py-2.5 sm:grid-cols-[9rem_1fr] sm:items-baseline sm:gap-4">
                <dt className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  Nome
                </dt>
                <dd className="text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]">
                  {user?.name}
                </dd>
              </div>
              <div className="grid gap-1 py-2.5 sm:grid-cols-[9rem_1fr] sm:items-baseline sm:gap-4">
                <dt className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  Usuário
                </dt>
                <dd className="text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]">
                  {user?.username}
                </dd>
              </div>
              <div className="grid gap-1 py-2.5 sm:grid-cols-[9rem_1fr] sm:items-baseline sm:gap-4">
                <dt className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                  Perfil de acesso
                </dt>
                <dd className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
                  <span className="font-medium">{roleLabel(user?.role)}</span>
                  <span className="mt-0.5 block text-[color:var(--ink-muted)]">
                    {user?.role && user.role in ROLE_LABELS
                      ? ROLE_DESCRIPTIONS[user.role as Role]
                      : "Perfil não reconhecido. Procure um administrador."}
                  </span>
                </dd>
              </div>
            </dl>

          </PanelBody>
        </Panel>

        <div className="space-y-4">
          <Panel>
            <PanelHeader
              title="Alterar minha senha"
              description="A senha atual é exigida. Outras sessões da conta são encerradas depois da troca."
            />
            <PanelBody>
              <PasswordChangeForm />
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="Telas disponíveis para você"
              description="Definidas pelo seu perfil de acesso."
            />
            <PanelBody>
              <ul className="space-y-1.5">
                {visibleScreens.map((item) => (
                  <li
                    key={item.to}
                    className="flex items-center gap-2 text-[length:var(--text-sm)] text-[color:var(--ink)]"
                  >
                    <Icon name="success" size={15} className="shrink-0 text-[color:var(--ok-fg)]" />
                    {item.label}
                  </li>
                ))}
              </ul>

              {hiddenScreens.length > 0 && (
                <>
                  <p className="mt-4 text-[length:var(--text-xs)] font-semibold uppercase tracking-[0.04em] text-[color:var(--ink-muted)]">
                    Sem acesso
                  </p>
                  <ul className="mt-1.5 space-y-1.5">
                    {hiddenScreens.map((item) => (
                      <li
                        key={item.to}
                        className="flex items-center gap-2 text-[length:var(--text-sm)] text-[color:var(--ink-subtle)]"
                      >
                        <Icon name="lock" size={15} className="shrink-0" />
                        {item.label}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader
              title="Sessões"
              description="Use isto se você entrou em outro computador e não tem certeza se saiu."
            />
            <PanelBody>
              {error && (
                <Alert tone="danger" className="mb-3">
                  {error}
                </Alert>
              )}
              <Button
                variant="danger-quiet"
                icon="lock"
                onClick={() => setConfirming(true)}
              >
                Encerrar todas as sessões
              </Button>
            </PanelBody>
          </Panel>
        </div>
      </div>

      <ConfirmDialog
        open={confirming}
        title="Encerrar todas as sessões"
        description="Inclui a sessão que você está usando agora."
        confirmLabel="Encerrar todas as sessões"
        busy={busy}
        onConfirm={revokeAllSessions}
        onClose={() => {
          if (!busy) setConfirming(false);
        }}
      >
        <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
          Todos os acessos abertos com o usuário <strong>{user?.username}</strong>{" "}
          serão encerrados, em qualquer computador. Você precisará entrar
          novamente.
        </p>
      </ConfirmDialog>
    </>
  );
}
