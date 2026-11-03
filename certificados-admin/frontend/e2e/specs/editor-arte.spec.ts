/**
 * "Trocar arte" keeps the layout: every element stays at its coordinates in
 * art pixels, with a new art of the same size or of another size, and the
 * editor says so when the size changes. Nothing is moved for the operator.
 */
import { test, expect, Page } from "@playwright/test";
import { readFileSync } from "node:fs";

async function scenario(page: Page) {
  await page.context().setExtraHTTPHeaders({ "x-mock-scenario": "default", "x-mock-role": "admin" });
}

/** A PNG of the given size, drawn by the browser itself. */
async function pngFile(page: Page, width: number, height: number) {
  const dataUrl = await page.evaluate(
    ([w, h]) => {
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const context = canvas.getContext("2d")!;
      context.fillStyle = "#e8eef8";
      context.fillRect(0, 0, w, h);
      return canvas.toDataURL("image/png");
    },
    [width, height] as const,
  );
  return {
    name: `arte-${width}x${height}.png`,
    mimeType: "image/png",
    buffer: Buffer.from(dataUrl.split(",")[1], "base64"),
  };
}

/** What the Properties panel shows for the selected element. */
const position = async (page: Page) => ({
  x: await page.getByLabel("X (px)").inputValue(),
  y: await page.getByLabel("Y (px)").inputValue(),
  width: await page.getByLabel("Largura da caixa de texto").inputValue(),
  height: await page.getByLabel("Altura da caixa de texto").inputValue(),
});

/** What would be saved: "Exportar JSON" serialises the canvas objects. */
async function exportedLayout(page: Page) {
  await page.getByRole("button", { name: "Mais" }).click();
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("menuitem", { name: "Exportar JSON" }).click(),
  ]);
  return JSON.parse(readFileSync(await download.path(), "utf8")) as {
    background: string;
    image_width: number;
    image_height: number;
    elements: Array<Record<string, unknown> & { key: string }>;
  };
}

test.describe("trocar arte no editor", () => {
  test("mantém posição, tamanho e fonte dos elementos, com arte igual ou de outro tamanho", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop", "editor é uma tela de desktop");
    await scenario(page);
    await page.goto("/template");
    await page
      .getByRole("main")
      .getByRole("listitem")
      .filter({ hasText: "Modelo 2026" })
      .getByRole("button", { name: "Editar" })
      .click();
    await expect(page.getByRole("button", { name: "Salvar", exact: true })).toBeVisible();

    const elements = page.getByRole("listbox", { name: "Elementos do template" }).getByRole("option");
    await elements.filter({ hasText: "Nome do participante" }).click();
    await page.getByLabel("X (px)").fill("1000");
    await page.getByLabel("Y (px)").fill("700");
    await page.getByLabel("Largura da caixa de texto").fill("800");
    await page.getByLabel("Largura da caixa de texto").press("Enter");
    await page.getByLabel("Altura da caixa de texto").fill("200");
    await page.getByLabel("Altura da caixa de texto").press("Enter");
    const edited = { x: "1000", y: "700", width: "800", height: "200" };
    await expect.poll(() => position(page)).toEqual(edited);

    // Same size: only the art changes; the selection and the numbers stay.
    await page.getByLabel("Arquivo da arte de fundo").setInputFiles(await pngFile(page, 3508, 2480));
    await expect(page.getByText("Não salvo")).toBeVisible();
    const sameSize = await exportedLayout(page);
    expect(sameSize.background.startsWith("data:image/png")).toBe(true);
    expect(sameSize.elements.find((element) => element.key === "name")).toMatchObject({
      x: 1000,
      y: 700,
      width: 800,
      height: 200,
      fontSize: 111,
    });
    expect(await position(page)).toEqual(edited);
    await expect(page.getByText(/A nova arte tem/)).toHaveCount(0);

    // Another size: the same numbers, and the editor says what happened.
    await page.getByLabel("Arquivo da arte de fundo").setInputFiles(await pngFile(page, 2000, 1414));
    const notice = page
      .getByRole("status")
      .filter({ hasText: "A nova arte tem 2000×1414 px; a anterior tinha 3508×2480 px." });
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("não foram reposicionados");
    await expect(notice).toContainText("Fora da nova página:");
    await expect(notice).toContainText("Nome do assinante");
    await expect(notice).toContainText("QR Code");
    expect(await position(page)).toEqual(edited);

    await elements.filter({ hasText: "QR Code" }).click();
    await expect(page.getByLabel("X (px)")).toHaveValue("175");
    await expect(page.getByLabel("Y (px)")).toHaveValue("2033");

    const otherSize = await exportedLayout(page);
    expect({ width: otherSize.image_width, height: otherSize.image_height }).toEqual({
      width: 2000,
      height: 1414,
    });
    expect(otherSize.elements).toHaveLength(9);
    expect(otherSize.elements.find((element) => element.key === "name")).toMatchObject({
      x: 1000,
      y: 700,
      width: 800,
      height: 200,
      fontSize: 111,
    });
    expect(otherSize.elements.find((element) => element.key === "qr")).toMatchObject({
      x: 175,
      y: 2033,
      width: 297,
      height: 297,
    });
    expect(otherSize.elements.find((element) => element.key === "texto_certificado")).toMatchObject({
      x: 175,
      y: 1140,
      fontSize: 59,
    });

    await notice.getByRole("button", { name: "Fechar" }).click();
    await expect(notice).toHaveCount(0);

    // Undo brings the previous art back, elements untouched.
    await page.getByRole("button", { name: /Desfazer/ }).click();
    await expect(page.getByRole("button", { name: /Refazer/ })).toBeEnabled();
    await expect.poll(async () => (await exportedLayout(page)).image_width).toBe(3508);
    const undone = await exportedLayout(page);
    expect(undone.elements.find((element) => element.key === "name")).toMatchObject({
      x: 1000,
      y: 700,
      width: 800,
      height: 200,
    });
  });
});
