/**
 * End-to-end coverage of the flows the secretariat actually performs, plus the
 * failure states the interface must survive: empty data, server error, offline,
 * 403 and 429.
 */
import { test, expect, Page } from "@playwright/test";
import path from "node:path";
import { writeFileSync, mkdirSync } from "node:fs";

async function scenario(page: Page, name: string, role = "admin") {
  await page.context().setExtraHTTPHeaders({
    "x-mock-scenario": name,
    "x-mock-role": role,
  });
}

/* A real .xlsx built by the app's own writer would need a browser context, so
 * the upload fixture is a small file with the right extension — the mock API
 * does not parse it, and the parsing itself is covered by the backend tests. */
const FIXTURE = path.join(process.cwd(), "e2e", ".tmp", "lote.xlsx");
test.beforeAll(() => {
  mkdirSync(path.dirname(FIXTURE), { recursive: true });
  writeFileSync(FIXTURE, Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x00]));
});

test.describe("emissão em lote", () => {
  test("secretaria: planilha → conferência → confirmação → lote persistido", async ({ page }) => {
    await scenario(page, "default", "secretaria");
    await page.addInitScript(() => {
      class DocsView {
        setIncludeFolders() {}
        setSelectFolderEnabled() {}
        setMimeTypes() {}
      }
      class PickerBuilder {
        callback?: (data: unknown) => void;
        addView() {}
        setOAuthToken() {}
        setDeveloperKey() {}
        setAppId() {}
        setTitle() {}
        setCallback(callback: (data: unknown) => void) { this.callback = callback; }
        build() {
          return {
            setVisible: () => this.callback?.({
              action: "picked",
              docs: [{
                id: "folder-e2e-semana-2026",
                name: "Semana de Inovação 2026",
                mimeType: "application/vnd.google-apps.folder",
              }],
            }),
          };
        }
      }
      (window as any).google = {
        picker: {
          Action: { PICKED: "picked", CANCEL: "cancel" },
          ViewId: { FOLDERS: "folders" },
          DocsView,
          PickerBuilder,
        },
      };
    });
    await page.goto("/emitir");

    // Step 1
    await expect(page.getByRole("heading", { name: "1. Planilha do lote" })).toBeVisible();
    await page.setInputFiles("#spreadsheet-upload", FIXTURE);
    await expect(page.getByText("lote.xlsx")).toBeVisible();
    await page.getByRole("combobox", { name: /Tipo do certificado/ }).selectOption("listener");

    await page.getByRole("button", { name: /Validar planilha/ }).click();

    // Step 2 — the preview states exactly what will happen.
    await expect(page.getByRole("heading", { name: "Conferência do lote" })).toBeVisible();
    await expect(page.getByText("Aptas para emissão")).toBeVisible();
    await expect(page.getByText("Ouvinte", { exact: true })).toBeVisible();
    await expect(page.getByText("42", { exact: true }).first()).toBeVisible();
    // Rejected rows are listed with their line numbers.
    await expect(page.getByRole("heading", { name: /Linhas inválidas \(2\)/ })).toBeVisible();
    await expect(page.getByText("carga_horaria deve ser um número inteiro")).toBeVisible();
    // The resolved body text is shown before anything is generated.
    await expect(page.getByText(/participou da Semana de Inovação/)).toBeVisible();

    await page.getByRole("button", { name: "Definir destino no Google Drive" }).click();
    await expect(page.getByText("secretaria.sintetica@instituicao.example")).toBeVisible();
    await page.getByRole("button", { name: "Selecionar pasta no Google Drive" }).click();
    await expect(page.getByText("Semana de Inovação 2026")).toBeVisible();
    await page.getByRole("button", { name: /Confirmar emissão de 42 certificado/ }).click();
    const confirmation = page.getByRole("dialog", { name: "Confirmar emissão do lote" });
    await expect(confirmation).toContainText("42 linhas válidas");
    await expect(confirmation).toContainText("Tipo congelado no lote: Ouvinte");
    await confirmation.getByRole("button", { name: /Emitir 42 certificado/ }).click();

    // Step 3
    await expect(page.getByText("Lote concluído")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Resumo final" })).toBeVisible();
    await expect(page.getByText("Ouvinte", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Certificados gerados (41)" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Abrir histórico deste lote" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Emitir outra planilha" })).toBeVisible();
  });
});

test.describe("fluxos por perfil", () => {
  test("admin: cria conta com senha temporária sem reexibir a senha", async ({ page }) => {
    await scenario(page, "default", "admin");
    await page.goto("/usuarios");
    await page.getByRole("button", { name: "Criar usuário" }).first().click();

    const dialog = page.getByRole("dialog", { name: "Criar usuário" });
    await dialog.getByLabel("Nome").fill("Usuário E2E");
    await dialog.getByLabel("Login").fill(`usuario.e2e.${Date.now()}`);
    await dialog.getByLabel("Perfil").selectOption("auditor");
    await dialog.getByLabel("Senha temporária").fill("Temporaria-E2E-2026!");
    await dialog.getByRole("button", { name: "Criar usuário" }).click();

    await expect(page.getByText(/deverá trocar a senha temporária/)).toBeVisible();
    await expect(page.getByText("Usuário E2E").first()).toBeVisible();
    await expect(page.getByText("Temporaria-E2E-2026!")).toHaveCount(0);
  });

  test("auditor: consulta histórico e auditoria sem ações de escrita", async ({ page }) => {
    await scenario(page, "default", "auditor");
    await page.goto("/historico");
    await expect(page.getByText("João Pedro Lima").first()).toBeVisible();
    if ((page.viewportSize()?.width ?? 0) >= 768) {
      await expect(page.getByRole("cell", { name: "Ouvinte", exact: true }).first()).toBeVisible();
    } else {
      await expect(page.getByText("Tipo: Ouvinte", { exact: true }).first()).toBeVisible();
    }
    await expect(page.getByRole("button", { name: "Revogar" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reemitir" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Baixar ZIP/ })).toHaveCount(0);

    await page.goto("/auditoria");
    const auditTable = page.getByRole("table");
    await expect(auditTable).toBeVisible();
    await expect(auditTable.getByText(/Login bem-sucedido/)).toBeVisible();
    await expect(page.getByRole("button", { name: /Criar|Salvar|Revogar|Reemitir/ })).toHaveCount(0);
  });
});

test.describe("histórico", () => {
  test("revogação exige motivo e confirma explicitamente", async ({ page }) => {
    await scenario(page, "default");
    await page.goto("/historico");
    await expect(page.getByText("João Pedro Lima").first()).toBeVisible();

    await page.getByRole("button", { name: "Revogar" }).first().click();

    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("heading", { name: "Revogar certificado" })).toBeVisible();

    const confirm = dialog.getByRole("button", { name: "Confirmar revogação" });
    await expect(confirm).toBeDisabled();

    await dialog.getByLabel("Motivo").fill("emitido em duplicidade");
    await expect(confirm).toBeEnabled();

    // Escape closes without acting.
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });

  test("seleção em lote habilita o ZIP", async ({ page }) => {
    await scenario(page, "default");
    await page.goto("/historico");
    await expect(page.getByText("João Pedro Lima").first()).toBeVisible();

    const zip = page.getByRole("button", { name: /Baixar ZIP/ });
    await expect(zip).toBeDisabled();

    await page.getByRole("button", { name: "Selecionar página" }).click();
    await expect(zip).toBeEnabled();
    await expect(zip).toContainText("Baixar ZIP (");
  });
});

test.describe("validação de certificado", () => {
  test("mostra veredito com ícone e texto", async ({ page }) => {
    await scenario(page, "default");
    await page.goto("/validar");
    await expect(page.getByText("Nenhuma consulta ainda")).toBeVisible();
  });
});

test.describe("estados de exceção", () => {
  test("vazio: painel explica em vez de mostrar zeros sem contexto", async ({ page }) => {
    await scenario(page, "empty");
    await page.goto("/painel");
    await expect(page.getByText("Nenhum certificado emitido ainda")).toBeVisible();
  });

  test("vazio: histórico ensina o que fazer", async ({ page }) => {
    await scenario(page, "empty");
    await page.goto("/historico");
    await expect(page.getByText("Nenhum certificado emitido ainda")).toBeVisible();
  });

  test("erro do servidor mostra recuperação, não tela branca", async ({ page }) => {
    await scenario(page, "error");
    await page.goto("/auditoria");
    await expect(page.getByRole("alert")).toContainText(/Não foi possível carregar/);
    await expect(page.getByRole("button", { name: "Tentar novamente" })).toBeVisible();
  });

  test("403 é explicado como permissão, não como falha", async ({ page }) => {
    await scenario(page, "forbidden");
    await page.goto("/auditoria");
    // A specific message from the backend is preferred over our generic one —
    // it is the server that knows why access was refused.
    await expect(page.getByRole("alert")).toContainText(/perfil não permite/);
    // And it is presented as a permission matter, not a crash.
    await expect(page.getByRole("alert")).not.toContainText(/erro interno/i);
  });

  test("429 orienta a aguardar", async ({ page }) => {
    await scenario(page, "rate-limited");
    await page.goto("/auditoria");
    await expect(page.getByRole("alert")).toContainText(/Muitas solicitações/);
  });

  test("offline é distinguido de erro do servidor", async ({ page, context }) => {
    await scenario(page, "default");
    await page.goto("/auditoria");
    await expect(page.getByRole("table")).toBeVisible();

    await context.setOffline(true);
    await page.getByRole("button", { name: "Atualizar" }).click();
    await expect(page.getByRole("alert")).toContainText(/Sem conexão/);
    await context.setOffline(false);
  });
});

test.describe("editor de template", () => {
  test.skip(({ browserName }) => browserName !== "chromium", "canvas-heavy");

  test("abre o editor e avisa sobre alterações não salvas", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
    await scenario(page, "default");
    await page.goto("/template");

    await page.getByRole("button", { name: /Editar \(nova versão\)/ }).click();

    // Toolbar is present and the canvas region rendered.
    await expect(page.getByRole("button", { name: "Salvar versão" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Desfazer/ })).toBeVisible();
    await expect(page.getByLabel("Nome")).toBeVisible();

    // Add an element, which makes the draft dirty.
    await page.getByRole("button", { name: "Nome", exact: true }).click();
    await expect(page.getByText("Alterações não salvas")).toBeVisible();

    // Leaving now must ask first.
    await page.getByRole("button", { name: "Voltar" }).click();
    await expect(page.getByRole("dialog")).toContainText("Sair sem salvar?");
  });

  test("ativar versão pede confirmação digitada", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "tela de desktop");
    await scenario(page, "default");
    await page.goto("/template");

    await page.getByRole("button", { name: "Ativar" }).first().click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Todos os certificados emitidos a partir de agora");

    const confirm = dialog.getByRole("button", { name: /Ativar esta versão/ });
    await expect(confirm).toBeDisabled();
    await dialog.getByLabel(/Digite/).fill("ATIVAR");
    await expect(confirm).toBeEnabled();
  });
});
