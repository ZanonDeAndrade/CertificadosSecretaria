import { useNavigate } from "react-router-dom";
import { APP_NAME } from "../app/AppShell";
import { useAuth } from "../app/AuthContext";
import { useInstitution } from "../app/InstitutionContext";
import PasswordChangeForm from "../components/PasswordChangeForm";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import Panel, { PanelBody, PanelHeader } from "../ui/Panel";

export default function AlterarSenha() {
  const { user, refresh, signOut } = useAuth();
  const { institution_name: institutionName } = useInstitution();
  const navigate = useNavigate();

  const changed = async () => {
    const next = await refresh();
    if (next && !next.must_change_password) {
      navigate(
        next.permissions.includes("dashboard.read") ? "/painel" : "/historico",
        { replace: true },
      );
    }
  };

  const cancel = async () => {
    await signOut();
    navigate("/entrar", { replace: true });
  };

  return (
    <main
      id="conteudo"
      className="flex min-h-screen items-center justify-center bg-[var(--surface-sunken)] px-4 py-10"
    >
      <div className="w-full max-w-[31rem]">
        <p className="mb-4 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
          {APP_NAME} · {institutionName}
        </p>
        <Panel>
          <PanelHeader
            title="Defina sua senha permanente"
            description={`Olá, ${user?.name || user?.username}. A senha temporária só pode ser usada para esta troca.`}
          />
          <PanelBody>
            <Alert tone="warn" live={false} className="mb-4">
              Por segurança, nenhuma outra área fica disponível antes de concluir
              esta etapa.
            </Alert>
            <PasswordChangeForm
              onChanged={changed}
              submitLabel="Salvar senha e continuar"
            />
            <Button variant="ghost" className="mt-3" onClick={cancel}>
              Sair sem alterar
            </Button>
          </PanelBody>
        </Panel>
      </div>
    </main>
  );
}
