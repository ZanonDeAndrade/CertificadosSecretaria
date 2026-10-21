/**
 * Sign-in.
 *
 * A single centred panel on the institutional ground — no marketing, no
 * imagery. Deliberate details: the error is a live region so it is announced,
 * autocomplete hints let the browser and password managers do their job, and
 * the submit button keeps its label while loading rather than swapping to a
 * spinner-only state.
 *
 * The 429 case is called out explicitly because the backend throttles repeated
 * failures, and "usuário ou senha inválidos" would send the operator hunting
 * for a typo that is not there.
 */
import { FormEvent, useState } from "react";
import axios from "axios";
import { AdminUser, API_BASE_URL, login } from "../services/api";
import { APP_NAME } from "../app/AppShell";
import { useInstitution } from "../app/InstitutionContext";
import Button from "../ui/Button";
import Alert from "../ui/Alert";
import { Field, TextInput } from "../ui/Field";

type LoginProps = {
  onLoggedIn: (user: AdminUser) => void;
  notice?: string;
};

export default function Login({ onLoggedIn, notice = "" }: LoginProps) {
  const { institution_name: institutionName } = useInstitution();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!username.trim() || !password) return;
    setLoading(true);
    setError("");
    try {
      const user = await login(username.trim(), password);
      onLoggedIn(user);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-[var(--surface-sunken)]">
      <main
        id="conteudo"
        className="flex flex-1 items-center justify-center px-4 py-10 sm:px-6"
      >
        <div className="w-full max-w-[26rem]">
          <div className="mb-6 flex items-center gap-3">
            <img
              src="/logo-amf.jpg"
              alt=""
              aria-hidden="true"
              className="h-16 w-16 shrink-0 rounded-[var(--radius-sm)] bg-white object-contain"
            />
            <div className="min-w-0">
              <p className="text-[length:var(--text-lg)] font-semibold leading-tight text-[color:var(--ink)]">
                {APP_NAME}
              </p>
              <p className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                {institutionName}
              </p>
            </div>
          </div>

          <div className="rounded-[var(--radius-md)] border border-[color:var(--line)] bg-[var(--surface)] p-5 shadow-[var(--shadow-sm)] sm:p-6">
            <h1 className="text-[length:var(--text-xl)] font-semibold text-[color:var(--ink)]">
              Entrar no sistema
            </h1>
            <p className="mt-1.5 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
              Acesso restrito aos servidores da secretaria acadêmica.
            </p>

            <form onSubmit={handleSubmit} className="mt-5 space-y-4" noValidate>
              {notice && <Alert tone="warn">{notice}</Alert>}

              <Field label="Usuário">
                {(props) => (
                  <TextInput
                    {...props}
                    value={username}
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    disabled={loading}
                    onChange={(event) => setUsername(event.target.value)}
                  />
                )}
              </Field>

              <Field label="Senha">
                {(props) => (
                  <TextInput
                    {...props}
                    type="password"
                    value={password}
                    autoComplete="current-password"
                    disabled={loading}
                    onChange={(event) => setPassword(event.target.value)}
                  />
                )}
              </Field>

              {error && <Alert tone="danger">{error}</Alert>}

              <Button
                type="submit"
                variant="primary"
                size="lg"
                block
                loading={loading}
                disabled={!username.trim() || !password}
              >
                {loading ? "Entrando…" : "Entrar"}
              </Button>
            </form>
          </div>

          <p className="mt-4 text-center text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
            Esqueceu a senha? A redefinição é feita pela equipe de TI da
            instituição.
          </p>
        </div>
      </main>

      <footer className="px-4 py-5 text-center text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
        Sistema de emissão e validação de certificados.
      </footer>
    </div>
  );
}

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return typeof navigator !== "undefined" && navigator.onLine === false
        ? "Sem conexão com a rede. Verifique a conexão da máquina e tente novamente."
        : `Não foi possível falar com o servidor em ${API_BASE_URL}. Avise a equipe de TI.`;
    }
    if (error.response.status === 401) {
      return "Usuário ou senha inválidos.";
    }
    if (error.response.status === 429) {
      return "Muitas tentativas seguidas. Aguarde alguns minutos antes de tentar novamente.";
    }
    const detail = error.response.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return "Não foi possível entrar. Tente novamente.";
}
