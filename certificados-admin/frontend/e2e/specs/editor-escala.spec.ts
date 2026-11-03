/**
 * The template editor shows the whole certificate, at the scale that fits.
 *
 * Checked on the two screens that matter: the 1366×768 notebook the
 * secretariat uses (about 1300×650 of page once the OS and browser bars are
 * out) and a 1920×1080 desktop. In both, the page must be entirely visible
 * with nothing to scroll, and dragging or resizing an element must still land
 * in pixels of the art. Screenshots go to e2e/screenshots/editor/.
 */
import { test, expect, Page } from "@playwright/test";
import { deflateSync } from "node:zlib";
import { mkdirSync } from "node:fs";
import path from "node:path";

/* The mock API's generic template: a 3508 × 2480 art. */
const ART = { width: 3508, height: 2480 };
const MARGIN = 8;
const SHOTS = path.join(process.cwd(), "e2e", "screenshots", "editor");

async function scenario(page: Page) {
  await page.context().setExtraHTTPHeaders({ "x-mock-scenario": "default", "x-mock-role": "admin" });
}

async function openEditor(page: Page) {
  await page.goto("/template");
  // An inactive model, so saving in the tests never touches the active one.
  await page
    .getByRole("listitem")
    .filter({ hasText: "Certificado_OPL" })
    .getByRole("button", { name: "Editar" })
    .click();
  await expect(page.getByRole("button", { name: "Salvar", exact: true })).toBeVisible();
  // The layout settles (background, elements, first line-break answer).
  await expect(page.getByRole("listbox", { name: "Elementos do template" })).toBeVisible();
  await page.waitForTimeout(700);
}

/** Bounding boxes of the stage and of the canvas fabric draws on. */
async function geometry(page: Page) {
  return page.evaluate(() => {
    const rect = (el: Element | null) => {
      const r = el!.getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    };
    const stage = document.querySelector('[data-testid="editor-stage"]')!;
    const canvas = document.querySelector("canvas.lower-canvas")!;
    return {
      viewport: { width: innerWidth, height: innerHeight },
      document: {
        scrollWidth: document.documentElement.scrollWidth,
        scrollHeight: document.documentElement.scrollHeight,
      },
      stage: { ...rect(stage), scrollWidth: stage.scrollWidth, scrollHeight: stage.scrollHeight },
      canvas: rect(canvas),
      toolbarRows: Math.round(
        document.querySelector('[data-testid="editor-toolbar"]')!.getBoundingClientRect().height,
      ),
    };
  });
}

function expectWholePage(g: Awaited<ReturnType<typeof geometry>>, art = ART) {
  // Nothing to scroll: not the document, not the stage.
  expect(g.document.scrollWidth).toBeLessThanOrEqual(g.viewport.width);
  expect(g.document.scrollHeight).toBeLessThanOrEqual(g.viewport.height);
  expect(g.stage.scrollWidth).toBeLessThanOrEqual(Math.ceil(g.stage.width));
  expect(g.stage.scrollHeight).toBeLessThanOrEqual(Math.ceil(g.stage.height));
  // The canvas sits inside the stage, whole, centred.
  expect(g.canvas.x).toBeGreaterThanOrEqual(g.stage.x - 0.5);
  expect(g.canvas.y).toBeGreaterThanOrEqual(g.stage.y - 0.5);
  expect(g.canvas.x + g.canvas.width).toBeLessThanOrEqual(g.stage.x + g.stage.width + 0.5);
  expect(g.canvas.y + g.canvas.height).toBeLessThanOrEqual(g.stage.y + g.stage.height + 0.5);
  const leftGap = g.canvas.x - g.stage.x;
  const rightGap = g.stage.x + g.stage.width - (g.canvas.x + g.canvas.width);
  expect(Math.abs(leftGap - rightGap)).toBeLessThanOrEqual(2);
  // Largest scale that fits the stage minus the margin, keeping the proportion.
  const expected = Math.min(
    (g.stage.width - 2 * MARGIN) / art.width,
    (g.stage.height - 2 * MARGIN) / art.height,
  );
  expect(g.canvas.width / art.width).toBeCloseTo(expected, 2);
  expect(g.canvas.width / g.canvas.height).toBeCloseTo(art.width / art.height, 2);
}

/** Screen position of a point given in pixels of the art. */
function artToScreen(g: Awaited<ReturnType<typeof geometry>>, x: number, y: number) {
  const scale = g.canvas.width / ART.width;
  return { x: g.canvas.x + x * scale, y: g.canvas.y + y * scale, scale };
}

async function numberField(page: Page, label: string) {
  return Number(await page.getByLabel(label).inputValue());
}

/** A valid PNG of the given size (one colour), for the art upload. */
function pngBuffer(width: number, height: number): Buffer {
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (buf: Buffer) => {
    let c = 0xffffffff;
    for (const byte of buf) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type: string, data: Buffer) => {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length);
    const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
    const sum = Buffer.alloc(4);
    sum.writeUInt32BE(crc(body));
    return Buffer.concat([length, body, sum]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; // bit depth
  header[9] = 2; // RGB
  const row = Buffer.concat([Buffer.from([0]), Buffer.alloc(width * 3, 0xee)]);
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

test.describe("editor: certificado inteiro", () => {
  test.beforeAll(() => mkdirSync(SHOTS, { recursive: true }));

  for (const size of [
    { width: 1300, height: 650, name: "notebook" },
    { width: 1920, height: 1080, name: "desktop" },
  ]) {
    test(`${size.width}×${size.height}: a página aparece inteira, sem rolagem, e arrastar e redimensionar seguem em pixels da arte`, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
      await page.setViewportSize({ width: size.width, height: size.height });
      await scenario(page);
      await openEditor(page);

      // The system chrome is gone and the toolbar is one row.
      await expect(page.getByRole("link", { name: "Ajuda" })).toHaveCount(0);
      await expect(page.getByRole("navigation", { name: "Navegação principal" })).toHaveCount(0);
      const g = await geometry(page);
      expect(g.toolbarRows).toBeLessThanOrEqual(50);
      expectWholePage(g);
      await page.screenshot({ path: path.join(SHOTS, `editor-${size.width}x${size.height}.png`) });

      // ── Drag: the title sits centred at x = 1754, y = 297, 124 px tall.
      const list = page.getByRole("listbox", { name: "Elementos do template" });
      // A regex keeps the match case-sensitive ("Corpo do certificado" exists too).
      await list.getByRole("option").filter({ hasText: /^CERTIFICADO/ }).click();
      const x0 = await numberField(page, "X (px)");
      const y0 = await numberField(page, "Y (px)");
      expect(x0).toBe(1754);
      expect(y0).toBe(297);

      const from = artToScreen(g, 1754, 297 + 62);
      const dx = 120;
      const dy = 60;
      await page.mouse.move(from.x, from.y);
      await page.mouse.down();
      await page.mouse.move(from.x + dx / 2, from.y + dy / 2, { steps: 4 });
      await page.mouse.move(from.x + dx, from.y + dy, { steps: 4 });
      await page.mouse.up();

      await expect
        .poll(() => numberField(page, "X (px)"))
        .toBeGreaterThan(x0 + Math.round(dx / from.scale) - 4);
      expect(await numberField(page, "X (px)")).toBeLessThan(x0 + Math.round(dx / from.scale) + 4);
      expect(Math.abs((await numberField(page, "Y (px)")) - (y0 + dy / from.scale))).toBeLessThan(4);

      // ── Resize: give the body an explicit box, then pull its right handle.
      await list.getByRole("option").filter({ hasText: "Corpo do certificado" }).click();
      const widthField = page.getByLabel("Largura da caixa de texto");
      const heightField = page.getByLabel("Altura da caixa de texto");
      await widthField.fill("1000");
      await widthField.press("Enter");
      await heightField.fill("300");
      await heightField.press("Enter");
      await expect(widthField).toHaveValue("1000");
      await page.waitForTimeout(400);
      // Keep the selection on the box so its handles are drawn.
      await list.getByRole("option").filter({ hasText: "Corpo do certificado" }).click();
      const handle = artToScreen(g, 175 + 1000, 1140 + 150);
      await page.mouse.move(handle.x, handle.y);
      await page.mouse.down();
      await page.mouse.move(handle.x + 40, handle.y, { steps: 4 });
      await page.mouse.move(handle.x + 80, handle.y, { steps: 4 });
      await page.mouse.up();
      const grown = Math.round(80 / handle.scale);
      const boxWidth = () => numberField(page, "Largura da caixa de texto");
      await expect.poll(boxWidth).toBeGreaterThan(1000 + grown - 6);
      expect(await boxWidth()).toBeLessThan(1000 + grown + 6);
      // The left edge did not move: only the dragged side changed.
      expect(await numberField(page, "X (px)")).toBe(175);
    });
  }

  test("recolher os painéis e trocar a arte reajustam a escala sem rolagem", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
    await page.setViewportSize({ width: 1300, height: 650 });
    await scenario(page);
    await openEditor(page);
    const before = await geometry(page);

    await page.getByRole("button", { name: "Recolher painel Elementos" }).click();
    await page.getByRole("button", { name: "Recolher painel Propriedades" }).click();
    await expect(page.getByRole("button", { name: "Mostrar painel Elementos" })).toBeVisible();
    await page.waitForTimeout(300);
    const collapsed = await geometry(page);
    expect(collapsed.stage.width).toBeGreaterThan(before.stage.width + 300);
    expectWholePage(collapsed);
    await page.screenshot({ path: path.join(SHOTS, "editor-1300x650-paineis-recolhidos.png") });

    await page.getByRole("button", { name: "Mostrar painel Elementos" }).click();
    await page.getByRole("button", { name: "Mostrar painel Propriedades" }).click();
    await page.waitForTimeout(300);
    expectWholePage(await geometry(page));

    // A portrait art: another proportion, still whole.
    await page.getByLabel("Arquivo da arte de fundo").setInputFiles({
      name: "retrato.png",
      mimeType: "image/png",
      buffer: pngBuffer(600, 900),
    });
    await page.waitForTimeout(800);
    const portrait = await geometry(page);
    expectWholePage(portrait, { width: 600, height: 900 });
    expect(portrait.canvas.height).toBeGreaterThan(portrait.canvas.width);
    await page.screenshot({ path: path.join(SHOTS, "editor-1300x650-arte-retrato.png") });
  });

  test("o menu ☰ do editor pede confirmação antes de sair com alterações não salvas", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
    await page.setViewportSize({ width: 1300, height: 650 });
    await scenario(page);
    await openEditor(page);

    await page.getByRole("button", { name: "Nome", exact: true }).click();
    await expect(page.getByText("Não salvo")).toBeVisible();

    await page.getByRole("button", { name: "Abrir menu de navegação" }).click();
    const drawer = page.getByRole("dialog", { name: "Menu de navegação" });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("link", { name: /Histórico/ }).click();

    const confirm = page.getByRole("dialog", { name: "Sair sem salvar?" });
    await expect(confirm).toBeVisible();
    await expect(page).toHaveURL(/\/template$/);

    await confirm.getByRole("button", { name: "Continuar editando" }).click();
    await expect(page.getByRole("button", { name: "Salvar", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Abrir menu de navegação" }).click();
    await drawer.getByRole("link", { name: /Histórico/ }).click();
    await page.getByRole("dialog", { name: "Sair sem salvar?" }).getByRole("button", { name: "Sair sem salvar" }).click();
    await expect(page).toHaveURL(/\/historico$/);
  });
});
