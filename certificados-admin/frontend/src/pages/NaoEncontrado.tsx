/**
 * 404 inside the shell — a mistyped URL should not look like a crash, and the
 * navigation stays available so the operator is one click from somewhere real.
 */
import PageHeader from "../ui/PageHeader";
import Panel from "../ui/Panel";
import { EmptyState } from "../ui/Feedback";
import { LinkButton } from "../ui/Button";
import { useAuth } from "../app/AuthContext";

export default function NaoEncontrado() {
  const { can } = useAuth();
  const hasDashboard = can("dashboard.read");
  return (
    <>
      <PageHeader title="Página não encontrada" />
      <Panel>
        <EmptyState
          icon="search"
          title="Este endereço não existe no sistema"
          description="O link pode estar incompleto ou a tela pode ter mudado de endereço. Use o menu lateral para chegar onde precisa."
          action={
            <LinkButton
              to={hasDashboard ? "/painel" : "/historico"}
              variant="primary"
              icon={hasDashboard ? "dashboard" : "history"}
            >
              {hasDashboard ? "Ir para o painel" : "Ir para o histórico"}
            </LinkButton>
          }
        />
      </Panel>
    </>
  );
}
