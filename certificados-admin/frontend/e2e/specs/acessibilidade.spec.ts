/**
 * Automated accessibility checks (axe-core, WCAG 2.2 A/AA rule sets).
 *
 * Automated testing catches roughly a third of real accessibility problems, so
 * this runs alongside the manual keyboard and screen-reader-structure checks
 * rather than standing in for them. The modal and drawer are exercised in their
 * open state, since that is when focus management can fail.
 */
import { test, expect, Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const AXE_SOURCE = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

interface Violation {
  id: string;
  impact: string;
  help: string;
  nodes: { target: string[]; failureSummary: string }[];
}

async function analyse(page: Page): Promise<Violation[]> {
  await page.addScriptTag({ content: AXE_SOURCE });
  const result = await page.evaluate(
    async (tags) =>
      // @ts-expect-error injected at runtime
      await window.axe.run(document, { runOnly: { type: "tag", values: tags } }),
    TAGS,
  );
  return (result.violations as Violation[]).map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    nodes: violation.nodes.map((node) => ({
      target: node.target,
      failureSummary: node.failureSummary,
    })),
  }));
}

function format(violations: Violation[]): string {
  return violations
    .map(
      (violation) =>
        `${violation.id} (${violation.impact}): ${violation.help}\n` +
        violation.nodes
          .slice(0, 3)
          .map((node) => `    ${node.target.join(" ")}`)
          .join("\n"),
    )
    .join("\n");
}

const SCREENS = [
  { route: "/entrar", name: "Entrar", role: "admin" },
  { route: "/painel", name: "Painel", role: "admin" },
  { route: "/emitir", name: "Emitir", role: "admin" },
  { route: "/historico", name: "Histórico", role: "admin" },
  { route: "/validar", name: "Validar", role: "admin" },
  { route: "/template", name: "Template", role: "admin" },
  { route: "/usuarios", name: "Usuários", role: "admin" },
  { route: "/auditoria", name: "Auditoria", role: "admin" },
  { route: "/ajuda", name: "Ajuda", role: "admin" },
  { route: "/perfil", name: "Perfil", role: "admin" },
  { route: "/emitir", name: "Sem permissão", role: "auditor" },
];

for (const screen of SCREENS) {
  test(`axe: ${screen.name} (${screen.role})`, async ({ page }) => {
    await page.context().setExtraHTTPHeaders({
      "x-mock-scenario": "default",
      "x-mock-role": screen.role,
    });
    await page.goto(screen.route);
    await page.waitForTimeout(300);

    const violations = await analyse(page);
    expect(violations, format(violations)).toEqual([]);
  });
}

test("axe: modal de revogação aberto", async ({ page }) => {
  await page.context().setExtraHTTPHeaders({
    "x-mock-scenario": "default",
    "x-mock-role": "admin",
  });
  await page.goto("/historico");
  await page.getByRole("button", { name: "Revogar" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();

  const violations = await analyse(page);
  expect(violations, format(violations)).toEqual([]);
});

test("axe: estados vazio e de erro", async ({ page }) => {
  await page.context().setExtraHTTPHeaders({
    "x-mock-scenario": "empty",
    "x-mock-role": "admin",
  });
  await page.goto("/historico");
  await page.waitForTimeout(300);
  let violations = await analyse(page);
  expect(violations, format(violations)).toEqual([]);

  await page.context().setExtraHTTPHeaders({
    "x-mock-scenario": "error",
    "x-mock-role": "admin",
  });
  await page.goto("/auditoria");
  await page.waitForTimeout(300);
  violations = await analyse(page);
  expect(violations, format(violations)).toEqual([]);
});

test("axe: drawer de navegação aberto (mobile)", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "drawer só existe abaixo de lg");
  await page.context().setExtraHTTPHeaders({
    "x-mock-scenario": "default",
    "x-mock-role": "admin",
  });
  await page.goto("/painel");
  await page.getByRole("button", { name: "Abrir menu de navegação" }).click();
  await expect(page.getByRole("dialog", { name: "Menu de navegação" })).toBeVisible();

  const violations = await analyse(page);
  expect(violations, format(violations)).toEqual([]);
});
