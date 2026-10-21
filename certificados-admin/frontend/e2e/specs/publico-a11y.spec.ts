/**
 * Accessibility of the public consultation area (certificados-consulta).
 *
 * The templates are rendered to static HTML by
 * `certificados-consulta/render_states.py`, one file per state, so this runs
 * without a database or the app's runtime secrets. Point PUBLIC_HTML_DIR at
 * that output; the spec skips when it is not present.
 */
import { test, expect } from "@playwright/test";
import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);
const AXE_SOURCE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const DIR = process.env.PUBLIC_HTML_DIR ?? "";

const STATES = [
  "busca-inicial",
  "busca-por-codigo",
  "busca-por-nome",
  "sem-resultados",
  "erro",
  "valido",
  "revogado",
  "inexistente",
  "bloqueado",
  "indisponivel",
];

test.describe("área pública", () => {
  test.skip(
    !DIR || !existsSync(DIR),
    "defina PUBLIC_HTML_DIR (veja render_states.py)",
  );

  for (const state of STATES) {
    test(`axe: ${state}`, async ({ page }) => {
      await page.goto(`file://${path.join(DIR, `${state}.html`)}`);
      await page.addScriptTag({ content: AXE_SOURCE });
      const result = await page.evaluate(
        async (tags) =>
          // @ts-expect-error injected at runtime
          await window.axe.run(document, { runOnly: { type: "tag", values: tags } }),
        TAGS,
      );

      const violations = (result.violations as {
        id: string;
        impact: string;
        help: string;
        nodes: { target: string[] }[];
      }[]).map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        targets: violation.nodes.map((node) => node.target.join(" ")),
      }));

      expect(
        violations,
        violations
          .map((v) => `${v.id} (${v.impact}): ${v.help}\n    ${v.targets.join("\n    ")}`)
          .join("\n"),
      ).toEqual([]);
    });
  }

  test("estrutura semântica das páginas de validação", async ({ page }) => {
    await page.goto(`file://${path.join(DIR, "valido.html")}`);

    // Exactly one h1, and the verdict is an h2 under it.
    await expect(page.locator("h1")).toHaveCount(1);
    await expect(page.getByRole("heading", { level: 2, name: "Certificado válido" })).toBeVisible();

    // Landmarks a screen-reader user navigates by.
    await expect(page.getByRole("banner")).toBeVisible();
    await expect(page.getByRole("main")).toBeVisible();
    await expect(page.getByRole("contentinfo")).toBeVisible();

    // Skip link is the first focusable element.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Ir para o conteúdo" })).toBeFocused();
  });

  test("estados negativos não vazam dados do participante", async ({ page }) => {
    for (const state of ["inexistente", "bloqueado", "indisponivel"]) {
      await page.goto(`file://${path.join(DIR, `${state}.html`)}`);
      const body = (await page.locator("body").textContent()) ?? "";
      expect(body).not.toContain("Ana Carolina");
      expect(body).not.toContain("CERT-2026-AB1234");
    }
  });
});
