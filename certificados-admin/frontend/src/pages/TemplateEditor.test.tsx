/**
 * The models list and the editor's save flow, with the canvas hook replaced
 * by a fake: jsdom has no canvas, and what is under test here is the model
 * lifecycle (edit, save, duplicate, delete/archive, archived + restore,
 * filters), not Fabric.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import TemplateEditor from "./TemplateEditor";
import { renderWithProviders } from "../test/renderWithProviders";
import {
  CertificateTemplate,
  deleteTemplate,
  duplicateTemplate,
  getTemplate,
  listCourses,
  listTemplates,
  restoreTemplate,
  saveTemplate,
} from "../services/templateApi";

vi.mock("../services/templateApi", () => ({
  GENERIC_TYPE: "__generic__",
  listTemplates: vi.fn(),
  listCourses: vi.fn(),
  getTemplate: vi.fn(),
  createTemplate: vi.fn(),
  saveTemplate: vi.fn(),
  duplicateTemplate: vi.fn(),
  activateTemplate: vi.fn(),
  deleteTemplate: vi.fn(),
  restoreTemplate: vi.fn(),
  getTemplateHistory: vi.fn(async () => []),
  getActiveVersion: vi.fn(),
  getVersion: vi.fn(),
  getTemplateSampleData: vi.fn(async () => ({
    values: {},
    empty_settings: [],
    can_manage_settings: true,
  })),
  computeTextLayouts: vi.fn(async () => []),
}));

const LAYOUT = {
  background: "/templates/versions/4/background",
  image_width: 400,
  image_height: 300,
  elements: [],
};

/* A static canvas: nothing changes, so the undo history never gets dirty. */
vi.mock("../hooks/useEditorCanvas", () => ({
  useEditorCanvas: () => ({
    canvasRef: () => undefined,
    stageRef: () => undefined,
    elements: [],
    selectedId: null,
    backgroundUrl: "/templates/versions/4/background",
    imageSize: { width: 400, height: 300 },
    scale: 1,
    displayScale: 1,
    showMockData: true,
    showGrid: false,
    canvasError: null,
    textLayouts: {},
    layoutSource: "pending",
    sampleSource: "local",
    setSampleData: () => undefined,
    addTextElement: () => undefined,
    addImageElement: async () => undefined,
    updateElement: () => undefined,
    nudgeElement: () => undefined,
    deleteElement: () => undefined,
    duplicateElement: () => undefined,
    selectElement: () => undefined,
    setBackground: () => undefined,
    loadTemplate: () => undefined,
    setShowMockData: () => undefined,
    setShowGrid: () => undefined,
    fitToArea: () => undefined,
    getLayout: () => LAYOUT,
    clearAll: () => undefined,
    exportJSON: () => "{}",
    importJSON: () => undefined,
    clearCanvasError: () => undefined,
  }),
}));

const COURSES = [
  { id: 3, name: "Direito", is_active: true },
  { id: 8, name: "Sistemas de Informação", is_active: true },
];

const ACTIVE: CertificateTemplate = {
  id: 1,
  name: "Modelo 2026",
  certificate_type: null,
  course_id: null,
  course_name: null,
  is_active: true,
  is_archived: false,
  revision: 3,
  current_version_id: 4,
  version_number: 4,
  image_width: 400,
  image_height: 300,
  background_url: "/templates/versions/4/background",
  certificate_count: 128,
  reference_count: 131,
  ever_activated: true,
  type_locked: true,
  edits_in_place: false,
  created_at: "2026-05-02T10:00:00Z",
  updated_at: "2026-05-02T10:30:00Z",
};

const DRAFT: CertificateTemplate = {
  ...ACTIVE,
  id: 2,
  name: "Certificado_OPL",
  course_id: 3,
  course_name: "Direito",
  is_active: false,
  revision: 1,
  current_version_id: 10,
  version_number: 10,
  background_url: "/templates/versions/10/background",
  certificate_count: 0,
  reference_count: 0,
  ever_activated: false,
  type_locked: false,
  edits_in_place: true,
};

const USED: CertificateTemplate = {
  ...DRAFT,
  id: 5,
  name: "Modelo usado",
  certificate_count: 12,
  reference_count: 12,
  type_locked: true,
  edits_in_place: false,
};

const ARCHIVED: CertificateTemplate = {
  ...USED,
  id: 4,
  name: "Modelo 2025",
  is_archived: true,
  archived_at: "2026-06-01T10:00:00Z",
};

async function row(name: string): Promise<HTMLElement> {
  const item = (await screen.findByText(name)).closest("li");
  expect(item).not.toBeNull();
  return item as HTMLElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listTemplates).mockImplementation(async (filters = {}) =>
    filters.include_archived ? [ACTIVE, DRAFT, USED, ARCHIVED] : [ACTIVE, DRAFT, USED],
  );
  vi.mocked(listCourses).mockResolvedValue(COURSES);
  vi.mocked(getTemplate).mockImplementation(async (id) => ({
    ...[ACTIVE, DRAFT, USED, ARCHIVED].find((template) => template.id === id)!,
    layout: LAYOUT,
  }));
  vi.mocked(saveTemplate).mockImplementation(async (id, input) => ({
    ...DRAFT,
    id,
    revision: input.revision + 1,
    outcome: input.layout ? "updated" : "unchanged",
  }));
  vi.mocked(duplicateTemplate).mockResolvedValue({ ...DRAFT, id: 9, name: "Cópia de Certificado_OPL" });
  vi.mocked(deleteTemplate).mockImplementation(async (id) => ({
    outcome: id === USED.id ? "archived" : "deleted",
    template_id: id,
  }));
  vi.mocked(restoreTemplate).mockResolvedValue({ ...ARCHIVED, is_archived: false });
});

test("a lista mostra um item por modelo, com tipo, curso, situação e certificados", async () => {
  renderWithProviders(<TemplateEditor />);

  const active = await row("Modelo 2026");
  expect(within(active).getByText("Ativo (genérico)")).toBeTruthy();
  expect(within(active).getByText(/128 certificados/)).toBeTruthy();
  expect(within(active).queryByRole("button", { name: "Excluir" })).toBeNull();

  const draft = await row("Certificado_OPL");
  expect(within(draft).getByText(/Genérico · Direito · Nenhum certificado/)).toBeTruthy();
  expect(within(draft).getByRole("button", { name: "Ativar" })).toBeTruthy();
  expect(within(draft).getByRole("button", { name: "Editar" })).toBeTruthy();
  expect(within(draft).getByRole("button", { name: "Excluir" })).toBeTruthy();
  expect(screen.queryByText("Modelo 2025")).toBeNull();
});

test("editar abre o modelo e salvar atualiza o mesmo item", async () => {
  const user = userEvent.setup();
  renderWithProviders(<TemplateEditor />);

  await user.click(within(await row("Certificado_OPL")).getByRole("button", { name: "Editar" }));
  await waitFor(() => expect(getTemplate).toHaveBeenCalledWith(2));
  expect(await screen.findByRole("button", { name: "Salvar" })).toBeTruthy();

  // Name and course live in "Dados do modelo".
  await user.click(screen.getByRole("button", { name: /Dados do modelo/ }));
  const dialog = screen.getByRole("dialog", { name: "Dados do modelo" });
  expect(within(dialog).getByText(/O curso só organiza a lista/)).toBeTruthy();
  const name = within(dialog).getByLabelText("Nome");
  await user.clear(name);
  await user.type(name, "Certificado OPL 2027");
  await user.selectOptions(within(dialog).getByLabelText("Curso"), "8");
  await user.click(within(dialog).getByRole("button", { name: "Pronto" }));
  expect(screen.getByText("Não salvo")).toBeTruthy();

  await user.click(screen.getByRole("button", { name: "Salvar" }));
  await waitFor(() =>
    expect(saveTemplate).toHaveBeenCalledWith(2, {
      name: "Certificado OPL 2027",
      certificate_type: null,
      course_id: 8,
      revision: 1,
      apply: false,
    }),
  );
  // Back to the list: the same item, no new one.
  expect(await screen.findByText("Dados do modelo salvos.")).toBeTruthy();
  expect(listTemplates).toHaveBeenCalledTimes(2);
});

test("salvar o modelo ativo pede a confirmação digitada e reenvia com apply", async () => {
  const user = userEvent.setup();
  vi.mocked(saveTemplate)
    .mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: "Este modelo está ativo… Confirme com “Salvar e aplicar às próximas emissões”." },
      },
    })
    .mockResolvedValueOnce({ ...ACTIVE, revision: 4, outcome: "applied" });
  renderWithProviders(<TemplateEditor />);

  await user.click(within(await row("Modelo 2026")).getByRole("button", { name: "Editar" }));
  await user.click(await screen.findByRole("button", { name: "Salvar" }));

  const dialog = await screen.findByRole("dialog", {
    name: "Salvar e aplicar às próximas emissões?",
  });
  const confirm = within(dialog).getByRole("button", {
    name: "Salvar e aplicar às próximas emissões",
  });
  expect(confirm).toHaveProperty("disabled", true);
  await user.type(within(dialog).getByLabelText(/Digite “APLICAR”/), "APLICAR");
  await user.click(confirm);

  await waitFor(() => expect(saveTemplate).toHaveBeenCalledTimes(2));
  expect(vi.mocked(saveTemplate).mock.calls[1][1]).toMatchObject({ apply: true, revision: 3 });
  // The type is locked on a model that issued certificates: it is not sent.
  expect(vi.mocked(saveTemplate).mock.calls[1][1]).not.toHaveProperty("certificate_type");
  expect(await screen.findByText(/aplicado: os próximos certificados/)).toBeTruthy();
});

test("duplicar cria uma cópia inativa a partir do modelo", async () => {
  const user = userEvent.setup();
  renderWithProviders(<TemplateEditor />);

  await user.click(within(await row("Certificado_OPL")).getByRole("button", { name: "Duplicar" }));
  await waitFor(() => expect(duplicateTemplate).toHaveBeenCalledWith(2, {}));
  expect(await screen.findByText(/Cópia criada como “Cópia de Certificado_OPL”/)).toBeTruthy();
});

test("excluir apaga um modelo sem certificados e arquiva um modelo com certificados", async () => {
  const user = userEvent.setup();
  renderWithProviders(<TemplateEditor />);

  await user.click(within(await row("Certificado_OPL")).getByRole("button", { name: "Excluir" }));
  let dialog = screen.getByRole("dialog", { name: "Excluir modelo “Certificado_OPL”" });
  expect(within(dialog).getByText(/será apagado de verdade/)).toBeTruthy();
  await user.type(within(dialog).getByLabelText(/Digite “EXCLUIR”/), "EXCLUIR");
  await user.click(within(dialog).getByRole("button", { name: "Excluir este modelo" }));
  await waitFor(() => expect(deleteTemplate).toHaveBeenCalledWith(2));
  expect(await screen.findByText("Modelo “Certificado_OPL” excluído.")).toBeTruthy();

  await user.click(within(await row("Modelo usado")).getByRole("button", { name: "Excluir" }));
  dialog = screen.getByRole("dialog", { name: "Arquivar modelo “Modelo usado”" });
  expect(within(dialog).getByText(/já gerou 12 certificados, por isso não será apagado/)).toBeTruthy();
  await user.type(within(dialog).getByLabelText(/Digite “EXCLUIR”/), "EXCLUIR");
  await user.click(within(dialog).getByRole("button", { name: "Arquivar este modelo" }));
  await waitFor(() => expect(deleteTemplate).toHaveBeenCalledWith(5));
  expect(await screen.findByText(/Modelo “Modelo usado” arquivado/)).toBeTruthy();
});

test("mostrar arquivados lista o modelo arquivado e permite restaurá-lo", async () => {
  const user = userEvent.setup();
  renderWithProviders(<TemplateEditor />);
  await screen.findByText("Modelo 2026");

  await user.click(screen.getByLabelText("Mostrar arquivados"));
  await waitFor(() =>
    expect(listTemplates).toHaveBeenLastCalledWith(
      expect.objectContaining({ include_archived: true }),
    ),
  );
  const archived = await row("Modelo 2025");
  expect(within(archived).getByText("Arquivado")).toBeTruthy();
  expect(within(archived).queryByRole("button", { name: "Editar" })).toBeNull();

  await user.click(within(archived).getByRole("button", { name: "Restaurar" }));
  await waitFor(() => expect(restoreTemplate).toHaveBeenCalledWith(4));
  expect(await screen.findByText(/Modelo “Modelo 2025” restaurado/)).toBeTruthy();
});

test("os filtros de curso e tipo vão ao servidor; a busca por nome filtra na hora", async () => {
  const user = userEvent.setup();
  renderWithProviders(<TemplateEditor />);
  await screen.findByText("Modelo 2026");

  await user.selectOptions(screen.getByLabelText("Curso"), "3");
  await waitFor(() =>
    expect(listTemplates).toHaveBeenLastCalledWith(
      expect.objectContaining({ course_id: 3, without_course: false }),
    ),
  );
  await user.selectOptions(screen.getByLabelText("Curso"), "none");
  await waitFor(() =>
    expect(listTemplates).toHaveBeenLastCalledWith(
      expect.objectContaining({ course_id: null, without_course: true }),
    ),
  );
  await user.selectOptions(screen.getByLabelText("Tipo de certificado"), "scientific_initiation");
  await waitFor(() =>
    expect(listTemplates).toHaveBeenLastCalledWith(
      expect.objectContaining({ certificate_type: "scientific_initiation" }),
    ),
  );

  await user.type(screen.getByLabelText("Buscar por nome"), "opl");
  expect(screen.getByText("Certificado_OPL")).toBeTruthy();
  expect(screen.queryByText("Modelo 2026")).toBeNull();
});

test("perfil somente leitura vê a lista sem ações de alteração", async () => {
  renderWithProviders(<TemplateEditor />, { role: "auditor" });
  await screen.findByText("Modelo 2026");
  expect(screen.queryByRole("button", { name: "Ativar" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Editar" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Excluir" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Novo modelo" })).toBeNull();
  expect(screen.getAllByRole("button", { name: "Ver histórico" }).length).toBeGreaterThan(0);
});
