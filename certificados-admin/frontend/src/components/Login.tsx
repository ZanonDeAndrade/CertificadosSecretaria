import { FormEvent, useState } from "react";
import axios from "axios";
import { AdminUser, API_BASE_URL, login } from "../services/api";

type LoginProps = {
  onLoggedIn: (user: AdminUser) => void;
};

function Login({ onLoggedIn }: LoginProps) {
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
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-12">
      <div className="w-full max-w-md rounded-[2rem] border border-white/60 bg-white/70 p-8 shadow-[0_30px_120px_rgba(15,23,42,0.12)] backdrop-blur">
        <div className="mb-6 space-y-1">
          <p className="text-sm font-semibold uppercase tracking-[0.3em] text-sky-700">
            Secretaria Acadêmica
          </p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-950">
            Entrar
          </h1>
          <p className="text-sm text-slate-500">
            Acesse o painel de emissão de certificados.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Usuário</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              disabled={loading}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50"
            />
          </label>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-slate-700">Senha</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              disabled={loading}
              className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50"
            />
          </label>

          {error && (
            <div className="rounded-xl border border-rose-200 bg-rose-50/90 p-3 text-sm font-medium text-rose-800">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="inline-flex w-full items-center justify-center rounded-full bg-slate-950 px-6 py-3 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {loading ? "Entrando..." : "Entrar"}
          </button>
        </form>
      </div>
    </main>
  );
}

function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 401) {
      return "Usuário ou senha inválidos.";
    }
    if (!error.response) {
      return `Não foi possível conectar ao backend em ${API_BASE_URL}.`;
    }
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return "Não foi possível entrar. Tente novamente.";
}

export default Login;
