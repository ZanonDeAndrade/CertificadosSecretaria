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
    // The insert buttons come from the API, team and event included.
    await expect(page.getByRole("button", { name: "Inserir {{equipe}}" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Inserir {{evento}}" })).toBeVisible();

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

  test("Mostra: texto automático e conferência com título e autores de cada trabalho", async ({ page }) => {
    await scenario(page, "default", "secretaria");
    await page.goto("/emitir");
    await page.setInputFiles("#spreadsheet-upload", FIXTURE);

    // The ordinary pre-filled text would print the certificate as an ordinary one.
    const text = page.getByLabel("Texto padrão do certificado");
    await expect(text).toHaveValue(/participou da atividade/);
    await page.getByRole("combobox", { name: /Tipo do certificado/ }).selectOption("scientific_initiation");
    await expect(text).toHaveValue("");
    await expect(page.locator("q", { hasText: "foi apresentado no evento" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Inserir {{titulo_trabalho}}" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Inserir {{nome}}" })).toHaveCount(0);

    await page.getByRole("button", { name: /Validar planilha/ }).click();
    await expect(page.getByRole("heading", { name: "Conferência do lote" })).toBeVisible();
    await expect(page.getByText('Certificamos que o trabalho "Horta vertical automatizada" foi apresentado', { exact: false })).toBeVisible();
    const table = page.getByRole("table", { name: "Trabalhos aptos para emissão" });
    await expect(table.getByText("Horta vertical automatizada")).toBeVisible();
    await expect(table.getByText("Robô seguidor de linha")).toBeVisible();
    await expect(
      table.getByRole("list", { name: "Autores do trabalho da linha 2" }).getByRole("listitem"),
    ).toHaveText(["Ana Carolina Souza", "João Pedro Lima", "Mariana Alves Ferreira"]);
    await expect(
      table.getByRole("list", { name: "Autores do trabalho da linha 3" }).getByRole("listitem"),
    ).toHaveText(["Carlos Eduardo Nunes"]);
    await expect(page.getByRole("button", { name: "Definir destino no Google Drive" })).toBeEnabled();
  });

  test("Mostra sem template do tipo: a conferência bloqueia e explica como corrigir", async ({ page }) => {
    await scenario(page, "mostra-sem-template", "admin");
    await page.goto("/emitir");
    await page.setInputFiles("#spreadsheet-upload", FIXTURE);
    await page.getByRole("combobox", { name: /Tipo do certificado/ }).selectOption("scientific_initiation");
    await page.getByRole("button", { name: /Validar planilha/ }).click();

    await expect(page.getByText(/Não há template ativo do tipo Mostra de Iniciação Científica/)).toBeVisible();
    await expect(page.getByRole("link", { name: "Abrir Template" })).toHaveAttribute("href", "/template");
    await expect(page.getByRole("button", { name: "Definir destino no Google Drive" })).toBeDisabled();
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

  test("download individual usa titular, evento e código no nome", async ({ page }) => {
    await scenario(page, "default");
    await page.goto("/historico");
    await expect(page.getByText("João Pedro Lima").first()).toBeVisible();

    // Desktop shows an icon button per row, mobile a "Baixar" button per card.
    const download = page
      .getByRole("button", { name: /^Baixar( certificado de .+)?$/ })
      .and(page.locator(":enabled"))
      .first();
    const [file] = await Promise.all([page.waitForEvent("download"), download.click()]);
    expect(file.suggestedFilename()).toMatch(/^.+ - .+ - CERT-2026-\d{4}A\.pdf$/);
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

/* Per-work (Mostra) certificates in the mock: 1, 3 and 8 synthetic authors. */
const WORK_AUTHORS = [
  "Pessoa Exemplo Alfa",
  "Pessoa Exemplo Beta",
  "Pessoa Exemplo Gama",
  "Pessoa Exemplo Delta",
  "Pessoa Exemplo Épsilon",
  "Pessoa Exemplo Zeta",
  "Pessoa Exemplo Eta",
  "Pessoa Exemplo Teta",
];

/** The cell (desktop) or record (mobile) that lists a work. */
function workEntry(page: Page, wide: boolean, title: string) {
  return wide
    ? page.getByRole("rowheader", { name: new RegExp(`^${title}`) })
    : page.getByRole("listitem").filter({ hasText: title });
}

test.describe("histórico da Mostra", () => {
  test("lista o trabalho e todos os autores; o comum continua pelo titular", async ({ page }, testInfo) => {
    const wide = testInfo.project.name === "desktop";
    await scenario(page, "default");
    await page.goto("/historico");
    await expect(page.getByText("Robô seguidor de linha", { exact: true })).toBeVisible();
    await expect(page.getByText("João Pedro Lima").first()).toBeVisible();
    if (wide) {
      await expect(page.getByRole("columnheader", { name: "Participante / Trabalho" })).toBeVisible();
    }

    await expect(workEntry(page, wide, "Compostagem doméstica")).toContainText(
      `Compostagem domésticaAutor: ${WORK_AUTHORS[0]}`,
    );
    const three = workEntry(page, wide, "Horta vertical automatizada");
    await expect(three).toContainText(`Autores: ${WORK_AUTHORS.slice(0, 3).join(", ")}`);
    await expect(three.getByRole("button", { name: /mostrar todos/ })).toHaveCount(0);

    const eight = workEntry(page, wide, "Robô seguidor de linha");
    await expect(eight).toContainText(`Autores: ${WORK_AUTHORS.slice(0, 3).join(", ")} +5`);
    await expect(eight).not.toContainText(WORK_AUTHORS[7]);
    const more = eight.getByRole("button", { name: "+5 autores; mostrar todos" });
    // Mouse: the tooltip carries every author. Touch: the button expands the list.
    await expect(more).toHaveAttribute("title", WORK_AUTHORS.join(", "));
    if (wide) await more.click();
    else await more.tap();
    await expect(eight).toContainText(`Autores: ${WORK_AUTHORS.join(", ")}`);
    await eight.getByRole("button", { name: "mostrar menos" }).click();
    await expect(eight).not.toContainText(WORK_AUTHORS[7]);
  });

  test("o detalhe lista o trabalho, todos os autores e a equipe", async ({ page }, testInfo) => {
    const wide = testInfo.project.name === "desktop";
    await scenario(page, "default");
    await page.goto("/historico");
    await expect(page.getByText("Robô seguidor de linha", { exact: true })).toBeVisible();

    if (wide) {
      await page
        .getByRole("button", { name: "Ver detalhes do trabalho “Robô seguidor de linha”" })
        .click();
    } else {
      await workEntry(page, wide, "Robô seguidor de linha").getByRole("button", { name: "Detalhes" }).tap();
    }
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("heading", { name: "Detalhes do certificado" })).toBeVisible();
    await expect(dialog.getByText("Trabalho", { exact: true })).toBeVisible();
    await expect(dialog.getByText("Equipe Verde")).toBeVisible();
    await expect(dialog.getByText("Participante", { exact: true })).toHaveCount(0);
    await expect(dialog.getByRole("listitem")).toHaveText(WORK_AUTHORS);
  });

  test("a busca por nome encontra o trabalho por qualquer autor, sem acento", async ({ page }) => {
    await scenario(page, "default");
    await page.goto("/historico");
    await page.getByLabel("Nome do participante").fill("exemplo epsilon");
    await page.getByRole("button", { name: "Buscar" }).click();

    await expect(page).toHaveURL(/name=exemplo/);
    await expect(page.getByText("Robô seguidor de linha", { exact: true })).toBeVisible();
    await expect(page.getByText("Horta vertical automatizada", { exact: true })).toHaveCount(0);
    await expect(page.getByText("João Pedro Lima")).toHaveCount(0);
  });

  test("o painel mostra o trabalho e os autores nas emissões recentes", async ({ page }) => {
    await scenario(page, "default");
    await page.goto("/painel");
    const table = page.getByRole("table", { name: /Últimos certificados emitidos/ });
    await expect(table.getByRole("columnheader", { name: "Participante / Trabalho" })).toBeVisible();
    const eight = table.getByRole("rowheader", { name: /^Robô seguidor de linha/ });
    await expect(eight).toContainText(`Autores: ${WORK_AUTHORS.slice(0, 3).join(", ")} +5`);
    await expect(eight.getByRole("button", { name: "+5 autores; mostrar todos" })).toHaveAttribute(
      "title",
      WORK_AUTHORS.join(", "),
    );
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
    await expect(page.getByRole("textbox", { name: "Nome" })).toBeVisible();

    // Add an element, which makes the draft dirty.
    await page.getByRole("button", { name: "Nome", exact: true }).click();
    await expect(page.getByText("Alterações não salvas")).toBeVisible();

    // Leaving now must ask first.
    await page.getByRole("button", { name: "Voltar" }).click();
    await expect(page.getByRole("dialog")).toContainText("Sair sem salvar?");
  });

  test("o bloco Autores só é oferecido em templates da Mostra", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
    await scenario(page, "default");
    await page.goto("/template");
    await page.getByRole("button", { name: /Editar \(nova versão\)/ }).click();

    // Generic template: no per-work field.
    await expect(page.getByRole("button", { name: "Nome", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Autores", exact: true })).toHaveCount(0);

    const typeSelect = page.getByLabel("Tipo", { exact: true });
    await typeSelect.selectOption("scientific_initiation");
    const authors = page.getByRole("button", { name: "Autores", exact: true });
    await expect(authors).toBeVisible();
    await authors.click();
    await expect(page.getByText("Base fixa: Y é a base do bloco")).toBeVisible();

    await typeSelect.selectOption("");
    await expect(page.getByRole("button", { name: "Autores", exact: true })).toHaveCount(0);
  });

  test("escolher a Mostra monta o ponto de partida: sem o nome, Autores acima do QR", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
    await scenario(page, "default");
    await page.goto("/template");
    await page.getByRole("button", { name: /Editar \(nova versão\)/ }).click();

    const list = page.getByRole("listbox", { name: "Elementos do template" });
    const option = (text: string) => list.getByRole("option").filter({ hasText: text });
    await expect(option("Nome do participante")).toHaveCount(1);
    await expect(option("Certificamos, para os devidos fins, que")).toHaveCount(1);
    // The history takes the loaded copy as its baseline once the layout settles.
    await page.waitForTimeout(600);

    await page.getByLabel("Tipo", { exact: true }).selectOption("scientific_initiation");
    await expect(option("Autores")).toHaveCount(1);
    await expect(option("Nome do participante")).toHaveCount(0);
    await expect(option("Certificamos, para os devidos fins, que")).toHaveCount(0);
    await expect(option("Corpo do certificado")).toHaveCount(1);
    await expect(option("QR Code")).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Nome", exact: true })).toHaveCount(0);
    await expect(page.getByText(/um certificado por trabalho, válido para todos os autores/)).toBeVisible();

    // An ordinary edit: undo brings the copy back, and the editor says what is missing.
    const undo = page.getByRole("button", { name: /Desfazer/ });
    await expect(undo).toBeEnabled();
    await undo.click();
    await expect(option("Nome do participante")).toHaveCount(1);
    await expect(page.getByText(/remova o Nome do participante/)).toBeVisible();
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
