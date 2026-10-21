/**
 * Route table.
 *
 * Every screen has a real URL, so refreshing the page or pasting a link keeps
 * the operator on the same screen — the tabbed single-route version lost both.
 * Route paths are in Portuguese to match the interface language and what the
 * secretariat would read in the address bar.
 *
 * The router itself is supplied by main.tsx (BrowserRouter) or by tests
 * (MemoryRouter), so this component stays router-agnostic and testable.
 */
import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import AppShell, { APP_NAME } from "./app/AppShell";
import { AuthProvider, useAuth } from "./app/AuthContext";
import {
  RequireAuth,
  RequirePasswordChanged,
  RequirePermission,
} from "./app/guards";
import LazyLoadBoundary from "./components/LazyLoadBoundary";
import Login from "./components/Login";
import Dashboard from "./pages/Dashboard";
import EmitirCertificados from "./pages/EmitirCertificados";
import Historico from "./pages/Historico";
import ValidateCertificate from "./components/ValidateCertificate";
import Usuarios from "./pages/Usuarios";
import Auditoria from "./pages/Auditoria";
import Ajuda from "./pages/Ajuda";
import Perfil from "./pages/Perfil";
import NaoEncontrado from "./pages/NaoEncontrado";
import { NAV_ITEMS } from "./app/navigation";
import Panel from "./ui/Panel";
import { InstitutionProvider } from "./app/InstitutionContext";
import AlterarSenha from "./pages/AlterarSenha";
import Configuracoes from "./pages/Configuracoes";

const TemplateEditor = lazy(() => import("./pages/TemplateEditor"));

/** Keeps the browser tab title in step with the current route. */
function useDocumentTitle() {
  const { pathname } = useLocation();
  useEffect(() => {
    const item = NAV_ITEMS.find((entry) => pathname.startsWith(entry.to));
    document.title = item ? `${item.label} · ${APP_NAME}` : APP_NAME;
  }, [pathname]);
}

function SignInRoute() {
  const { user, notice, signIn, ready } = useAuth();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from;

  if (ready && user) {
    const home = user.permissions.includes("dashboard.read") ? "/painel" : "/historico";
    return (
      <Navigate
        to={user.must_change_password ? "/trocar-senha" : from ?? home}
        replace
      />
    );
  }
  return <Login notice={notice} onLoggedIn={signIn} />;
}

function HomeRoute() {
  const { can } = useAuth();
  return <Navigate to={can("dashboard.read") ? "/painel" : "/historico"} replace />;
}

function EditorFallback() {
  return (
    <Panel>
      <div
        role="status"
        aria-live="polite"
        className="px-5 py-10 text-center text-[length:var(--text-sm)] text-[color:var(--ink-muted)]"
      >
        Carregando o editor de template…
      </div>
    </Panel>
  );
}

function AppRoutes() {
  useDocumentTitle();
  return (
    <Routes>
      <Route path="/entrar" element={<SignInRoute />} />
      <Route
        path="/trocar-senha"
        element={
          <RequireAuth>
            <AlterarSenha />
          </RequireAuth>
        }
      />

      <Route
        path="/*"
        element={
          <RequireAuth>
            <RequirePasswordChanged>
              <AppShell>
              <Routes>
                <Route path="/" element={<HomeRoute />} />
                <Route
                  path="/painel"
                  element={
                    <RequirePermission permission="dashboard.read">
                      <Dashboard />
                    </RequirePermission>
                  }
                />

                <Route
                  path="/emitir"
                  element={
                    <RequirePermission permission="certificates.issue">
                      <EmitirCertificados />
                    </RequirePermission>
                  }
                />

                <Route
                  path="/historico"
                  element={
                    <RequirePermission permission="certificates.read">
                      <Historico />
                    </RequirePermission>
                  }
                />

                <Route path="/validar" element={<ValidateCertificate />} />

                <Route
                  path="/template"
                  element={
                    <RequirePermission permission="templates.read">
                      <LazyLoadBoundary>
                        <Suspense fallback={<EditorFallback />}>
                          <TemplateEditor />
                        </Suspense>
                      </LazyLoadBoundary>
                    </RequirePermission>
                  }
                />

                <Route
                  path="/usuarios"
                  element={
                    <RequirePermission permission="users.manage">
                      <Usuarios />
                    </RequirePermission>
                  }
                />

                <Route
                  path="/auditoria"
                  element={
                    <RequirePermission permission="audit.read">
                      <Auditoria />
                    </RequirePermission>
                  }
                />

                <Route
                  path="/configuracoes"
                  element={
                    <RequirePermission permission="settings.read">
                      <Configuracoes />
                    </RequirePermission>
                  }
                />

                <Route path="/ajuda" element={<Ajuda />} />
                <Route path="/perfil" element={<Perfil />} />
                <Route path="*" element={<NaoEncontrado />} />
              </Routes>
              </AppShell>
            </RequirePasswordChanged>
          </RequireAuth>
        }
      />
    </Routes>
  );
}

export default function App() {
  return (
    <InstitutionProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </InstitutionProvider>
  );
}
