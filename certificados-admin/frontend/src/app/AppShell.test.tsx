/**
 * Shell behaviour a page can ask for: the immersive mode the template editor
 * uses (no sidebar, no topbar, drawer on every size) and the leave guard that
 * makes every exit through the drawer ask before unsaved work is lost.
 */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { expect, test, vi } from "vitest";
import AppShell from "./AppShell";
import { useShell } from "./ShellContext";
import { renderWithProviders } from "../test/renderWithProviders";

vi.mock("./InstitutionContext", () => ({
  useInstitution: () => ({ institution_name: "Instituição Teste", public_url: "" }),
}));

/* A page that owns the viewport and holds unsaved work: it registers a guard
 * that records the pending navigation instead of letting it happen. */
function ImmersivePage({ dirty, onLeave }: { dirty: boolean; onLeave: (proceed: () => void) => void }) {
  const { setImmersive, openDrawer, setLeaveGuard } = useShell();
  useEffect(() => {
    setImmersive(true);
    return () => setImmersive(false);
  }, [setImmersive]);
  useEffect(() => {
    if (!dirty) {
      setLeaveGuard(null);
      return;
    }
    setLeaveGuard(onLeave);
    return () => setLeaveGuard(null);
  }, [dirty, onLeave, setLeaveGuard]);
  return (
    <button type="button" onClick={(event) => openDrawer(event.currentTarget)}>
      Abrir menu do editor
    </button>
  );
}

function WhereAmI() {
  const location = useLocation();
  return <output data-testid="route">{location.pathname}</output>;
}

function Harness({ dirty, onLeave }: { dirty: boolean; onLeave: (proceed: () => void) => void }) {
  return (
    <AppShell>
      <WhereAmI />
      <Routes>
        <Route path="/template" element={<ImmersivePage dirty={dirty} onLeave={onLeave} />} />
        <Route path="*" element={<p>Outra tela</p>} />
      </Routes>
    </AppShell>
  );
}

test("modo imersivo: o shell esconde menu lateral e cabeçalho e o menu abre pelo botão da página", async () => {
  const user = userEvent.setup();
  renderWithProviders(<Harness dirty={false} onLeave={vi.fn()} />, { route: "/template" });

  // Sidebar and topbar are gone; the content column has no padding class.
  expect(screen.queryByRole("link", { name: /Ajuda/ })).toBeNull();
  expect(screen.queryByText("Ambiente administrativo. As ações realizadas aqui são registradas.")).toBeNull();
  expect(screen.getByRole("main").className).not.toContain("max-w-");

  await user.click(screen.getByRole("button", { name: "Abrir menu do editor" }));
  const drawer = screen.getByRole("dialog", { name: "Menu de navegação" });
  expect(drawer.closest(".lg\\:hidden")).toBeNull();
  expect(drawer.parentElement?.className).not.toContain("lg:hidden");

  // Closing returns the focus to the page's own button.
  await user.click(screen.getByRole("button", { name: "Fechar menu" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Abrir menu do editor" })),
  );
});

test("um item do menu com alterações não salvas passa pela guarda antes de navegar", async () => {
  const user = userEvent.setup();
  let pending: (() => void) | null = null;
  const onLeave = vi.fn((proceed: () => void) => {
    pending = proceed;
  });
  renderWithProviders(<Harness dirty onLeave={onLeave} />, { route: "/template" });

  await user.click(screen.getByRole("button", { name: "Abrir menu do editor" }));
  await user.click(screen.getByRole("link", { name: /Histórico/ }));

  // The guard was asked, the drawer closed and the route did not change.
  expect(onLeave).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("dialog", { name: "Menu de navegação" })).toBeNull();
  expect(screen.getByTestId("route").textContent).toBe("/template");

  // Confirming continues exactly where the operator was going.
  pending!();
  await waitFor(() => expect(screen.getByTestId("route").textContent).toBe("/historico"));
});

test("sem alterações pendentes, o item do menu navega direto", async () => {
  const user = userEvent.setup();
  const onLeave = vi.fn();
  renderWithProviders(<Harness dirty={false} onLeave={onLeave} />, { route: "/template" });

  await user.click(screen.getByRole("button", { name: "Abrir menu do editor" }));
  await user.click(screen.getByRole("link", { name: /Auditoria/ }));

  expect(onLeave).not.toHaveBeenCalled();
  await waitFor(() => expect(screen.getByTestId("route").textContent).toBe("/auditoria"));
  // Leaving the immersive page brings the shell chrome back.
  await waitFor(() => expect(screen.getByRole("link", { name: /Ajuda/ })).toBeTruthy());
});

test("sair pelo menu também respeita a guarda", async () => {
  const user = userEvent.setup();
  const onLeave = vi.fn();
  renderWithProviders(<Harness dirty onLeave={onLeave} />, { route: "/template" });

  await user.click(screen.getByRole("button", { name: "Abrir menu do editor" }));
  await user.click(screen.getByRole("button", { name: "Sair" }));

  expect(onLeave).toHaveBeenCalledTimes(1);
  expect(screen.getByTestId("route").textContent).toBe("/template");
});
