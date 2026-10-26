import { expect, test } from "vitest";
import { TemplateElement, TemplateLayout, TextTemplateElement } from "../types/template";
import { perWorkProblems, perWorkStartingPoint } from "./perWorkTemplate";

const W = 3508;
const H = 2480;

function text(key: string, y: number, extra: Partial<TextTemplateElement> = {}): TextTemplateElement {
  return {
    id: `${key}-${y}`,
    type: "text",
    key,
    label: key,
    x: 1754,
    y,
    fontSize: 54,
    fontFamily: "Times New Roman",
    color: "#000000",
    align: "center",
    bold: false,
    italic: false,
    ...extra,
  };
}

/** The backend's default (generic) template for an A4 art at 300 dpi. */
function genericLayout(qr: Partial<TextTemplateElement> = {}): TemplateLayout {
  return {
    background: "/templates/versions/4/background",
    image_width: W,
    image_height: H,
    elements: [
      text("static", 297, { staticText: "CERTIFICADO", fontSize: 124, bold: true }),
      text("static", 744, { staticText: "Certificamos, para os devidos fins, que" }),
      text("name", 880, { fontSize: 111, bold: true }),
      text("texto_certificado", 1140, { x: 175, align: "left", fontSize: 59 }),
      text("issue_line", 1785),
      text("signatory_name", 1959, { fontSize: 44 }),
      text("validation_code", 2281, { fontSize: 34 }),
      text("qr", 2033, { x: 175, width: 297, height: 297, ...qr }),
    ],
  };
}

function byKey(elements: TemplateElement[], key: string): TextTemplateElement[] {
  return elements.filter(
    (element): element is TextTemplateElement => element.type === "text" && element.key === key,
  );
}

test("a cópia do template genérico vira o ponto de partida da Mostra", () => {
  const generic = genericLayout();
  expect(perWorkProblems(generic.elements)).toEqual(["name", "authors"]);

  const start = perWorkStartingPoint(generic);
  const keys = start.elements.map((element) => (element.type === "text" ? element.key : "image"));
  expect(keys).not.toContain("name");
  // The fixed text announcing the name is gone; the title stays.
  expect(byKey(start.elements, "static").map((element) => element.staticText)).toEqual([
    "CERTIFICADO",
  ]);
  for (const kept of ["issue_line", "signatory_name", "validation_code", "qr"]) {
    expect(keys).toContain(kept);
  }

  // The body moves up into the space the preamble and the name leave.
  const [body] = byKey(start.elements, "texto_certificado");
  expect(body).toMatchObject({ x: 175, y: 744, align: "left", fontSize: 59 });

  // The authors block sits just above the QR code and grows upward.
  const [authors] = byKey(start.elements, "authors");
  expect(authors).toMatchObject({
    x: 175,
    y: 2033 - Math.round(H * 0.015),
    align: "left",
    anchorY: "bottom",
    width: Math.round(W * 0.3),
    fontSize: Math.round(59 * 0.8),
  });
  expect(authors.y).toBeLessThan(byKey(start.elements, "qr")[0].y);
  expect(perWorkProblems(start.elements)).toEqual([]);

  // Applying it again changes nothing.
  expect(perWorkStartingPoint(start)).toEqual(start);
});

test("com o QR Code à direita, o bloco alinha pela borda direita dele", () => {
  const start = perWorkStartingPoint(genericLayout({ x: 3036 }));
  const [authors] = byKey(start.elements, "authors");
  expect(authors).toMatchObject({ align: "right", x: 3036 + 297 });
});

test("sem QR Code nem corpo, o ponto de partida inclui os dois", () => {
  const layout: TemplateLayout = {
    ...genericLayout(),
    elements: [
      text("static", 297, { staticText: "CERTIFICADO" }),
      text("static", 744, { staticText: "  CERTIFICAMOS que  " }),
      text("name", 880),
    ],
  };
  const start = perWorkStartingPoint(layout);
  const [body] = byKey(start.elements, "texto_certificado");
  expect(body).toMatchObject({ y: 744, align: "left", x: Math.round(W * 0.05) });
  const [qr] = byKey(start.elements, "qr");
  expect(qr).toMatchObject({ x: Math.round(W * 0.05), y: Math.round(H * 0.82) });
  const [authors] = byKey(start.elements, "authors");
  expect(authors.y).toBeLessThan(qr.y);
  expect(perWorkProblems(start.elements)).toEqual([]);
});

test("textos fixos que não anunciam o nome são mantidos", () => {
  const layout: TemplateLayout = {
    ...genericLayout(),
    elements: [
      ...genericLayout().elements,
      text("static", 2400, { staticText: "Secretaria Acadêmica" }),
    ],
  };
  const start = perWorkStartingPoint(layout);
  expect(byKey(start.elements, "static").map((element) => element.staticText)).toEqual([
    "CERTIFICADO",
    "Secretaria Acadêmica",
  ]);
});

test("sem arte de fundo o layout não é alterado", () => {
  const layout: TemplateLayout = { background: "", image_width: 0, image_height: 0, elements: [] };
  expect(perWorkStartingPoint(layout)).toBe(layout);
});

test("problemas seguem as mesmas regras do backend", () => {
  expect(perWorkProblems([])).toEqual(["authors", "body"]);
  expect(perWorkProblems([text("certificate_text", 1), text("authors", 2)])).toEqual([]);
  expect(perWorkProblems([text("name", 1), text("texto_certificado", 2)])).toEqual([
    "name",
    "authors",
  ]);
});
