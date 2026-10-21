/**
 * Responsive evidence run.
 *
 * Captures every main screen at the five required breakpoints and writes them
 * to e2e/screenshots/<breakpoint>/<screen>.png, plus a contact-sheet HTML index
 * so the whole set can be reviewed at once.
 *
 * It also reports mechanical defects the eye misses in a thumbnail:
 *   - horizontal overflow of the document
 *   - any element wider than the viewport
 *   - interactive targets below the 24px WCAG 2.2 floor
 *
 * Usage: node e2e/screenshots.mjs   (mock API + vite preview must be running)
 */
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const BASE = process.env.E2E_BASE_URL ?? "http://localhost:4173";
const OUT = path.resolve("e2e/screenshots");

const BREAKPOINTS = [
  { id: "320x568", width: 320, height: 568, label: "Celular pequeno" },
  { id: "375x812", width: 375, height: 812, label: "Celular" },
  { id: "768x1024", width: 768, height: 1024, label: "Tablet" },
  { id: "1366x768", width: 1366, height: 768, label: "Notebook" },
  { id: "1440x900", width: 1440, height: 900, label: "Desktop" },
];

const SCREENS = [
  { id: "login", route: "/entrar", label: "Entrar", signedOut: true },
  { id: "painel", route: "/painel", label: "Painel" },
  { id: "emitir", route: "/emitir", label: "Emitir certificados" },
  { id: "historico", route: "/historico", label: "Histórico" },
  { id: "validar", route: "/validar", label: "Validar certificado" },
  { id: "template", route: "/template", label: "Template" },
  { id: "usuarios", route: "/usuarios", label: "Usuários" },
  { id: "auditoria", route: "/auditoria", label: "Auditoria" },
  { id: "ajuda", route: "/ajuda", label: "Ajuda" },
  { id: "perfil", route: "/perfil", label: "Meu perfil" },
];

/** Defects that are measurable rather than visual. */
async function audit(page, viewportWidth) {
  return page.evaluate((vw) => {
    const problems = [];

    const doc = document.documentElement;
    if (doc.scrollWidth > vw + 1) {
      problems.push(
        `Página rola horizontalmente: scrollWidth ${doc.scrollWidth} > viewport ${vw}`,
      );
    }

    // Elements sticking out of the viewport.
    for (const element of Array.from(document.body.querySelectorAll("*"))) {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (rect.right > vw + 1.5) {
        const style = getComputedStyle(element);
        // A deliberately scrollable region is not an overflow bug.
        const scrollable =
          style.overflowX === "auto" || style.overflowX === "scroll";
        const insideScroller = element.closest(
          '[style*="overflow"], .table-scroll, [class*="overflow-"]',
        );
        if (!scrollable && !insideScroller) {
          problems.push(
            `Elemento ultrapassa a viewport: <${element.tagName.toLowerCase()}${
              element.className && typeof element.className === "string"
                ? "." + element.className.split(" ").slice(0, 2).join(".")
                : ""
            }> right=${Math.round(rect.right)}`,
          );
        }
      }
    }

    // Touch/click targets below the WCAG 2.2 (2.5.8) 24px minimum.
    const interactive = Array.from(
      document.querySelectorAll(
        'button, a[href], input:not([type="hidden"]), select, textarea, [role="button"], [role="option"], [role="tab"]',
      ),
    );
    for (const element of interactive) {
      const rect = element.getBoundingClientRect();
      if (rect.width === 0 || rect.height === 0) continue;
      if (getComputedStyle(element).visibility === "hidden") continue;
      // Visually-hidden controls (a file input behind a styled <label>) are not
      // the target the user aims at — the label is, and it is measured here in
      // its own right. Flagging the 1×1 input would be a false positive.
      if (element.closest(".sr-only") || element.classList.contains("sr-only")) {
        continue;
      }
      if (rect.height < 23.5 || rect.width < 23.5) {
        const name =
          element.getAttribute("aria-label") ||
          element.textContent?.trim().slice(0, 30) ||
          element.tagName.toLowerCase();
        problems.push(
          `Alvo pequeno (${Math.round(rect.width)}×${Math.round(rect.height)}): ${name}`,
        );
      }
    }

    return [...new Set(problems)];
  }, viewportWidth);
}

async function main() {
  const browser = await chromium.launch();
  const findings = [];

  for (const breakpoint of BREAKPOINTS) {
    await mkdir(path.join(OUT, breakpoint.id), { recursive: true });

    const context = await browser.newContext({
      viewport: { width: breakpoint.width, height: breakpoint.height },
      deviceScaleFactor: 1,
      // The mock API reads these to pick a scenario and a role.
      extraHTTPHeaders: { "x-mock-scenario": "default", "x-mock-role": "admin" },
    });
    const page = await context.newPage();

    for (const screen of SCREENS) {
      await page.goto(`${BASE}${screen.route}`, { waitUntil: "networkidle" });
      // Let skeletons resolve into real content.
      await page.waitForTimeout(400);

      const file = path.join(OUT, breakpoint.id, `${screen.id}.png`);
      await page.screenshot({ path: file, fullPage: true });

      const problems = await audit(page, breakpoint.width);
      if (problems.length) {
        findings.push({ breakpoint: breakpoint.id, screen: screen.id, problems });
      }
      process.stdout.write(
        `${breakpoint.id} ${screen.id.padEnd(12)} ${problems.length ? "⚠ " + problems.length : "ok"}\n`,
      );
    }

    await context.close();
  }

  await browser.close();

  await writeFile(
    path.join(OUT, "findings.json"),
    JSON.stringify(findings, null, 2),
  );

  // Contact sheet for reviewing everything at once.
  const html = `<!doctype html><meta charset="utf-8"><title>Evidências responsivas</title>
<style>
 body{font:14px system-ui;margin:0;background:#f6f8fa;color:#1a2129}
 h1{font-size:20px;margin:24px 16px 8px} h2{font-size:16px;margin:24px 16px 8px}
 .row{display:flex;gap:12px;overflow-x:auto;padding:8px 16px 16px}
 figure{margin:0;flex:0 0 auto;background:#fff;border:1px solid #e0e5ea;border-radius:6px;padding:8px}
 figcaption{font-size:12px;color:#556170;margin-bottom:6px}
 img{display:block;border:1px solid #e0e5ea;height:420px;width:auto}
 .bad{color:#a32020}
</style>
<h1>Evidências responsivas — Certificados</h1>
${BREAKPOINTS.map(
  (bp) => `<h2>${bp.label} — ${bp.id}</h2><div class="row">${SCREENS.map(
    (s) =>
      `<figure><figcaption>${s.label}</figcaption><img loading="lazy" src="${bp.id}/${s.id}.png" alt="${s.label} em ${bp.id}"></figure>`,
  ).join("")}</div>`,
).join("")}
<h2>Problemas detectados</h2>
<pre style="margin:0 16px 40px;white-space:pre-wrap" class="${findings.length ? "bad" : ""}">${
    findings.length
      ? findings
          .map(
            (f) => `${f.breakpoint} · ${f.screen}\n  ${f.problems.join("\n  ")}`,
          )
          .join("\n\n")
      : "Nenhum problema mecânico detectado."
  }</pre>`;
  await writeFile(path.join(OUT, "index.html"), html);

  console.log(`\n${findings.length} tela(s) com problemas. Veja ${OUT}/index.html`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
