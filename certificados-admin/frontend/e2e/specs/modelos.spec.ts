/**
 * Certificate models: the list the secretariat manages (one item per model)
 * and the lifecycle behind it — edit and save the same item, duplicate,
 * delete or archive, show archived and restore, filter.
 */
import { test, expect, Page } from "@playwright/test";

async function scenario(page: Page, name = "default", role = "admin") {
  await page.context().setExtraHTTPHeaders({ "x-mock-scenario": name, "x-mock-role": role });
}

/* Rows of the models list (the navigation also has list items). */
const rows = (page: Page) => page.getByRole("main").getByRole("listitem");
const row = (page: Page, name: string) => rows(page).filter({ hasText: name });

async function openModel(page: Page, name: string) {
  await row(page, name).getByRole("button", { name: "Editar" }).click();
  await expect(page.getByRole("button", { name: "Salvar", exact: true })).toBeVisible();
}

test.describe("modelos de certificado", () => {
  // The mock keeps its state for the whole run; these tests write to it.
  test.beforeEach(async ({ request }) => {
    await request.post("http://localhost:8000/__mock/reset");
  });

  test("a lista mostra um item por modelo, com tipo, curso, situação e certificados, e filtra", async ({ page }) => {
    await scenario(page);
    await page.goto("/template");

    const active = row(page, "Modelo 2026");
    await expect(active.getByText("Ativo (genérico)")).toBeVisible();
    await expect(active.getByText(/128 certificados/)).toBeVisible();
    await expect(active.getByRole("button", { name: "Excluir" })).toHaveCount(0);

    const draft = row(page, "Certificado_OPL");
    await expect(draft.getByText(/Genérico · Direito · Nenhum certificado/)).toBeVisible();
    await expect(draft.getByRole("button", { name: "Ativar" })).toBeVisible();
    // The active ones come first.
    const names = await rows(page).allInnerTexts();
    expect(names[0]).toContain("Modelo 2026");
    expect(names.some((text) => text.includes("Modelo 2025"))).toBe(false);

    // Filters: course, type, name, archived.
    await page.getByLabel("Curso").selectOption("3");
    await expect(rows(page)).toHaveCount(1);
    await expect(row(page, "Certificado_OPL")).toBeVisible();
    await page.getByLabel("Curso").selectOption("");
    await page.getByLabel("Tipo de certificado").selectOption("scientific_initiation");
    await expect(rows(page)).toHaveCount(1);
    await expect(row(page, "Modelo Mostra de Iniciação Científica")).toBeVisible();
    await page.getByLabel("Tipo de certificado").selectOption("");
    await page.getByLabel("Buscar por nome").fill("ouvinte");
    await expect(rows(page)).toHaveCount(1);
    await expect(row(page, "Ouvinte 2024")).toBeVisible();
    await page.getByLabel("Buscar por nome").fill("");

    await page.getByLabel("Mostrar arquivados").check();
    await expect(row(page, "Modelo 2025").getByText("Arquivado")).toBeVisible();
  });

  test("duplicar cria uma cópia inativa e excluir apaga um modelo sem certificados", async ({ page }) => {
    await scenario(page);
    await page.goto("/template");

    await row(page, "Certificado_OPL").getByRole("button", { name: "Duplicar" }).click();
    await expect(page.getByText(/Cópia criada como “Cópia de Certificado_OPL”/)).toBeVisible();
    const copy = row(page, "Cópia de Certificado_OPL");
    await expect(copy).toBeVisible();
    await expect(copy.getByText(/Direito/)).toBeVisible();

    await copy.getByRole("button", { name: "Excluir" }).click();
    const dialog = page.getByRole("dialog", { name: /Excluir modelo/ });
    await expect(dialog).toContainText("será apagado de verdade");
    await dialog.getByLabel(/Digite “EXCLUIR”/).fill("EXCLUIR");
    await dialog.getByRole("button", { name: "Excluir este modelo" }).click();
    await expect(page.getByText(/Modelo “Cópia de Certificado_OPL” excluído/)).toBeVisible();
    await expect(row(page, "Cópia de Certificado_OPL")).toHaveCount(0);
  });

  test("excluir um modelo com certificados arquiva, e mostrar arquivados permite restaurar", async ({ page }) => {
    await scenario(page);
    await page.goto("/template");

    await row(page, "Ouvinte 2024").getByRole("button", { name: "Excluir" }).click();
    const dialog = page.getByRole("dialog", { name: /Arquivar modelo/ });
    await expect(dialog).toContainText("já gerou 12 certificados, por isso não será apagado");
    await expect(dialog).toContainText("a validação pública e a reemissão continuam funcionando");
    await dialog.getByLabel(/Digite “EXCLUIR”/).fill("EXCLUIR");
    await dialog.getByRole("button", { name: "Arquivar este modelo" }).click();
    await expect(page.getByText(/Modelo “Ouvinte 2024” arquivado/)).toBeVisible();
    await expect(row(page, "Ouvinte 2024")).toHaveCount(0);

    await page.getByLabel("Mostrar arquivados").check();
    const archived = row(page, "Ouvinte 2024");
    await expect(archived.getByText("Arquivado")).toBeVisible();
    await expect(archived.getByRole("button", { name: "Editar" })).toHaveCount(0);
    await archived.getByRole("button", { name: "Restaurar" }).click();
    await expect(page.getByText(/Modelo “Ouvinte 2024” restaurado/)).toBeVisible();
    await page.getByLabel("Mostrar arquivados").uncheck();
    await expect(row(page, "Ouvinte 2024").getByRole("button", { name: "Editar" })).toBeVisible();
  });

  test("ver histórico lista as revisões do modelo", async ({ page }) => {
    await scenario(page);
    await page.goto("/template");

    await row(page, "Modelo 2026").getByRole("button", { name: "Ver histórico" }).click();
    const dialog = page.getByRole("dialog", { name: /Histórico de “Modelo 2026”/ });
    const current = dialog.getByRole("listitem").filter({ hasText: "Revisão 4" });
    await expect(current).toBeVisible();
    await expect(current.getByText("Em uso nas emissões")).toBeVisible();
    await expect(dialog.getByRole("listitem").filter({ hasText: "Revisão 3" })).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Duplicar esta revisão" })).toHaveCount(1);
  });

  test("editar e salvar atualizam o mesmo item; o modelo ativo pede APLICAR", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
    await scenario(page);
    await page.goto("/template");

    await openModel(page, "Certificado_OPL");
    await page.getByRole("button", { name: /Dados do modelo/ }).click();
    const details = page.getByRole("dialog", { name: "Dados do modelo" });
    await expect(details).toContainText("O curso só organiza a lista de modelos");
    await details.getByLabel("Nome").fill("Certificado OPL 2027");
    await details.getByLabel("Curso").selectOption("8");
    await details.getByRole("button", { name: "Pronto" }).click();
    await expect(page.getByText("Não salvo")).toBeVisible();
    await page.getByRole("button", { name: "Salvar", exact: true }).click();

    await expect(page.getByText("Dados do modelo salvos.")).toBeVisible();
    await expect(row(page, "Certificado OPL 2027")).toBeVisible();
    await expect(row(page, "Certificado OPL 2027").getByText(/Sistemas de Informação/)).toBeVisible();
    await expect(row(page, "Certificado_OPL")).toHaveCount(0);

    // The active model: a layout change needs the typed confirmation.
    await openModel(page, "Modelo 2026");
    await page.waitForTimeout(600);
    await page.getByRole("button", { name: "Nome", exact: true }).click();
    await expect(page.getByText("Não salvo")).toBeVisible();
    await page.getByRole("button", { name: "Salvar", exact: true }).click();
    const apply = page.getByRole("dialog", { name: "Salvar e aplicar às próximas emissões?" });
    await expect(apply).toContainText("inclusive lotes que já estão na fila");
    const confirm = apply.getByRole("button", { name: "Salvar e aplicar às próximas emissões" });
    await expect(confirm).toBeDisabled();
    await apply.getByLabel(/Digite “APLICAR”/).fill("APLICAR");
    await confirm.click();
    await expect(page.getByText(/Modelo salvo e aplicado/)).toBeVisible();
    await expect(row(page, "Modelo 2026").getByText("Ativo (genérico)")).toBeVisible();
  });
});
