import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import TemplateEditor from "./TemplateEditor";
import { renderWithProviders } from "../test/renderWithProviders";
import {
  deleteVersion,
  getActiveVersion,
  listVersions,
  renameVersion,
} from "../services/templateApi";

vi.mock("../services/templateApi", () => ({
  listVersions: vi.fn(),
  getActiveVersion: vi.fn(),
  getVersion: vi.fn(),
  createVersion: vi.fn(),
  activateVersion: vi.fn(),
  renameVersion: vi.fn(),
  deleteVersion: vi.fn(),
  getTemplateSampleData: vi.fn(async () => ({
    values: {},
    empty_settings: [],
    can_manage_settings: true,
  })),
  computeTextLayouts: vi.fn(async () => []),
}));

const ACTIVE = {
  id: 1,
  version_number: 1,
  name: "Oficial",
  is_active: true,
  image_width: 400,
  image_height: 300,
  background_url: "/templates/versions/1/background",
  created_at: "2026-08-01T10:00:00Z",
};

const DRAFT = {
  ...ACTIVE,
  id: 2,
  version_number: 2,
  name: "Rascunho",
  is_active: false,
  background_url: "/templates/versions/2/background",
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listVersions).mockResolvedValue([DRAFT, ACTIVE]);
  vi.mocked(getActiveVersion).mockResolvedValue(ACTIVE);
  vi.mocked(renameVersion).mockResolvedValue({ ...DRAFT, name: "Modelo 2027" });
  vi.mocked(deleteVersion).mockResolvedValue(undefined);
});

test("permite renomear e excluir somente uma versão inativa", async () => {
  const user = userEvent.setup();
  renderWithProviders(<TemplateEditor />);

  const draftRow = (await screen.findByText(/Versão 2 — Rascunho/)).closest("li");
  const activeRow = screen
    .getAllByText(/Versão 1 — Oficial/)
    .find((element) => element.closest("li"))
    ?.closest("li");
  expect(draftRow).not.toBeNull();
  expect(activeRow).not.toBeNull();
  expect(within(activeRow as HTMLElement).queryByRole("button", { name: "Excluir" })).toBeNull();

  await user.click(within(draftRow as HTMLElement).getByRole("button", { name: "Renomear" }));
  const renameDialog = screen.getByRole("dialog", { name: "Renomear versão 2" });
  const name = within(renameDialog).getByLabelText("Nome da versão");
  await user.clear(name);
  await user.type(name, "Modelo 2027");
  await user.click(within(renameDialog).getByRole("button", { name: "Salvar novo nome" }));
  await waitFor(() => expect(renameVersion).toHaveBeenCalledWith(2, "Modelo 2027"));

  await user.click(within(draftRow as HTMLElement).getByRole("button", { name: "Excluir" }));
  const deleteDialog = screen.getByRole("dialog", { name: "Excluir versão 2" });
  await user.type(within(deleteDialog).getByLabelText(/Digite “EXCLUIR”/), "EXCLUIR");
  await user.click(
    within(deleteDialog).getByRole("button", { name: "Excluir esta versão" }),
  );
  await waitFor(() => expect(deleteVersion).toHaveBeenCalledWith(2));
});

test("perfil somente leitura não recebe ações de alteração", async () => {
  renderWithProviders(<TemplateEditor />, { role: "auditor" });
  await screen.findByText(/Versão 2 — Rascunho/);
  expect(screen.queryByRole("button", { name: "Renomear" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Excluir" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Ativar" })).toBeNull();
});
