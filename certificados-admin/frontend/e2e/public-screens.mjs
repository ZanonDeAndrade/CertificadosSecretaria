/**
 * Renders the public (certificados-consulta) Jinja templates through Jinja
 * itself and screenshots every state at the required breakpoints.
 *
 * The templates are rendered by a small Python helper rather than by booting
 * the whole FastAPI app, because that app needs a database, secrets and Drive
 * configuration that a visual check does not.
 */
import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const OUT = path.resolve("e2e/screenshots-publico");
const HTML_DIR = process.env.PUBLIC_HTML_DIR;

const BREAKPOINTS = [
  { id: "320x568", width: 320, height: 568 },
  { id: "375x812", width: 375, height: 812 },
  { id: "768x1024", width: 768, height: 1024 },
  { id: "1366x768", width: 1366, height: 768 },
  { id: "1440x900", width: 1440, height: 900 },
];

const PAGES = [
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

const browser = await chromium.launch();
const findings = [];

for (const bp of BREAKPOINTS) {
  await mkdir(path.join(OUT, bp.id), { recursive: true });
  const context = await browser.newContext({
    viewport: { width: bp.width, height: bp.height },
  });
  const page = await context.newPage();

  for (const name of PAGES) {
    await page.goto(`file://${path.join(HTML_DIR, `${name}.html`)}`);
    await page.screenshot({
      path: path.join(OUT, bp.id, `${name}.png`),
      fullPage: true,
    });

    const problems = await page.evaluate((vw) => {
      const out = [];
      if (document.documentElement.scrollWidth > vw + 1) {
        out.push(`rola horizontalmente (${document.documentElement.scrollWidth} > ${vw})`);
      }
      for (const el of Array.from(
        document.querySelectorAll('a, button, input:not([type="hidden"])'),
      )) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (r.height < 23.5) {
          out.push(
            `alvo pequeno (${Math.round(r.width)}×${Math.round(r.height)}): ${
              el.textContent?.trim().slice(0, 24) || el.tagName
            }`,
          );
        }
        if (r.right > vw + 1.5) out.push(`fora da viewport: ${el.tagName}`);
      }
      return [...new Set(out)];
    }, bp.width);

    if (problems.length) findings.push({ bp: bp.id, page: name, problems });
    process.stdout.write(`${bp.id} ${name.padEnd(18)} ${problems.length ? "⚠" : "ok"}\n`);
  }
  await context.close();
}
await browser.close();

const html = `<!doctype html><meta charset="utf-8"><title>Área pública</title>
<style>body{font:14px system-ui;margin:0;background:#f6f8fa}h2{margin:20px 16px 6px;font-size:15px}
.row{display:flex;gap:12px;overflow-x:auto;padding:6px 16px 14px}
figure{margin:0;flex:0 0 auto;background:#fff;border:1px solid #e0e5ea;border-radius:6px;padding:8px}
figcaption{font-size:12px;color:#556170;margin-bottom:6px}img{display:block;height:400px;width:auto;border:1px solid #e0e5ea}</style>
<h1 style="margin:20px 16px;font-size:20px">Área pública — evidências</h1>
${BREAKPOINTS.map(
  (bp) =>
    `<h2>${bp.id}</h2><div class="row">${PAGES.map(
      (p) =>
        `<figure><figcaption>${p}</figcaption><img loading="lazy" src="${bp.id}/${p}.png" alt="${p}"></figure>`,
    ).join("")}</div>`,
).join("")}
<h2>Problemas</h2><pre style="margin:0 16px 40px;white-space:pre-wrap">${
  findings.length
    ? findings.map((f) => `${f.bp} · ${f.page}\n  ${f.problems.join("\n  ")}`).join("\n\n")
    : "Nenhum problema mecânico detectado."
}</pre>`;
await writeFile(path.join(OUT, "index.html"), html);
await writeFile(path.join(OUT, "findings.json"), JSON.stringify(findings, null, 2));
console.log(`\n${findings.length} problema(s). Veja ${OUT}/index.html`);
