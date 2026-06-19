import { useEffect, useState } from "react";
import TemplateUpload from "./components/TemplateUpload";
import ValidateCertificate from "./components/ValidateCertificate";
import Login from "./components/Login";
import EmitirCertificados from "./pages/EmitirCertificados";
import Historico from "./pages/Historico";
import TemplateEditor from "./pages/TemplateEditor";
import { AdminUser, getMe, logout } from "./services/api";

type Tab = "emitir" | "historico" | "validate" | "editor" | "templates";

function App() {
  const [activeTab, setActiveTab] = useState<Tab>("emitir");
  const [user, setUser] = useState<AdminUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    document.title = "Certificados";
  }, []);

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  const handleLogout = async () => {
    try {
      await logout();
    } finally {
      setUser(null);
    }
  };

  if (!authChecked) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Carregando…
      </main>
    );
  }

  if (!user) {
    return <Login onLoggedIn={setUser} />;
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-6xl flex-col px-6 py-12 md:px-10 lg:py-20">
      <div className="rounded-[2.5rem] border border-white/60 bg-white/45 p-6 shadow-[0_30px_120px_rgba(15,23,42,0.08)] backdrop-blur md:p-10">
        <header className="mb-8 flex flex-col gap-3">
          <div className="flex items-start justify-between gap-4">
            <p className="text-sm font-semibold uppercase tracking-[0.3em] text-sky-700">
              Fluxo hibrido
            </p>
            <div className="flex items-center gap-3">
              <span className="text-sm text-slate-500">{user.username}</span>
              <button
                type="button"
                onClick={handleLogout}
                className="rounded-full border border-slate-300 bg-white px-4 py-1.5 text-xs font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-100"
              >
                Sair
              </button>
            </div>
          </div>
          <h1 className="text-4xl font-semibold tracking-tight text-slate-950 md:text-5xl">
            Certificados
          </h1>

          {/* Tab bar */}
          <div className="mt-2 flex gap-1 rounded-2xl border border-slate-200/80 bg-slate-100/60 p-1 w-fit">
            <TabButton
              label="Emitir certificados"
              active={activeTab === "emitir"}
              onClick={() => setActiveTab("emitir")}
            />
            <TabButton
              label="Histórico"
              active={activeTab === "historico"}
              onClick={() => setActiveTab("historico")}
            />
            <TabButton
              label="Validar certificado"
              active={activeTab === "validate"}
              onClick={() => setActiveTab("validate")}
            />
            <TabButton
              label="Editor visual"
              active={activeTab === "editor"}
              onClick={() => setActiveTab("editor")}
            />
            <TabButton
              label="Gerenciar templates"
              active={activeTab === "templates"}
              onClick={() => setActiveTab("templates")}
            />
          </div>
        </header>

        {activeTab === "emitir" && <EmitirCertificados />}
        {activeTab === "historico" && <Historico />}
        {activeTab === "validate" && <ValidateCertificate />}
        {activeTab === "editor" && <TemplateEditor />}
        {activeTab === "templates" && <TemplateUpload />}
      </div>
    </main>
  );
}

interface TabButtonProps {
  label: string;
  active: boolean;
  onClick: () => void;
}

function TabButton({ label, active, onClick }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-xl px-4 py-2 text-sm font-medium transition",
        active
          ? "bg-white text-slate-900 shadow-sm"
          : "text-slate-500 hover:text-slate-700",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

export default App;
