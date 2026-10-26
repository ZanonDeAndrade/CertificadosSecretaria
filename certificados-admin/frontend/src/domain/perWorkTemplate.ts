/**
 * Templates for per-work certificate types (the Mostra de Iniciação Científica).
 *
 * One certificate per work, valid for every author: nothing highlights a
 * participant name. The body names the work and the event, and the authors
 * block, whose base sits just above the QR code, lists who wrote it. The
 * backend refuses a batch whose template breaks these rules; this module lets
 * the editor build a starting point and say what is still missing.
 */
import { createUuid } from "../lib/uuid";
import {
  KEY_LABELS,
  TemplateElement,
  TemplateLayout,
  TextTemplateElement,
} from "../types/template";

const BODY_KEYS = new Set(["texto_certificado", "certificate_text"]);

export type PerWorkProblem = "name" | "authors" | "body";

/** What each problem means to the person editing, in the editor's wording. */
export const PER_WORK_PROBLEM_LABELS: Record<PerWorkProblem, string> = {
  name: "remova o Nome do participante",
  authors: "adicione o bloco Autores acima do QR Code",
  body: "adicione o Corpo",
};

function isText(element: TemplateElement): element is TextTemplateElement {
  return element.type === "text";
}

/** Same rules as the backend's `per_work.layout_problems`. */
export function perWorkProblems(elements: TemplateElement[]): PerWorkProblem[] {
  const keys = new Set(elements.filter(isText).map((element) => element.key));
  const problems: PerWorkProblem[] = [];
  if (keys.has("name")) problems.push("name");
  if (!keys.has("authors")) problems.push("authors");
  if (![...keys].some((key) => BODY_KEYS.has(key))) problems.push("body");
  return problems;
}

function plain(text: string): string {
  return text
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim()
    .toLowerCase();
}

/**
 * The fixed text that announces the highlighted name ("Certificamos, para os
 * devidos fins, que"). The per-work body opens with "Certificamos que" itself.
 */
function announcesName(element: TextTemplateElement): boolean {
  return element.key === "static" && /^certificamos\b/.test(plain(element.staticText ?? ""));
}

/**
 * Turn a layout (usually a copy of the generic template) into the starting
 * point of a per-work template:
 *
 * - drops the participant name and the fixed text that announces it;
 * - moves the body up into the space they leave (or adds one);
 * - adds the authors block, left aligned with the QR code and growing upward
 *   from just above it (adding the QR code when the layout has none).
 *
 * Everything else (title, date, signature, code) is kept as it is. A layout
 * without art dimensions is returned unchanged, as is one already fit.
 */
export function perWorkStartingPoint(layout: TemplateLayout): TemplateLayout {
  const width = layout.image_width;
  const height = layout.image_height;
  if (!width || !height) return layout;

  const removed = layout.elements.filter(
    (element) => isText(element) && (element.key === "name" || announcesName(element)),
  );
  const freedTop = removed.length ? Math.min(...removed.map((element) => element.y)) : null;
  let elements = layout.elements.filter((element) => !removed.includes(element));
  const margin = Math.round(width * 0.05);

  const body = elements.find(
    (element): element is TextTemplateElement => isText(element) && BODY_KEYS.has(element.key),
  );
  if (body) {
    if (freedTop !== null && freedTop < body.y) {
      elements = elements.map((element) =>
        element === body ? { ...body, y: freedTop } : element,
      );
    }
  } else {
    elements = [
      ...elements,
      {
        id: createUuid(),
        type: "text",
        key: "texto_certificado",
        label: KEY_LABELS.texto_certificado,
        x: margin,
        y: freedTop ?? Math.round(height * 0.3),
        fontSize: Math.max(Math.round(height * 0.024), 8),
        fontFamily: "Times New Roman",
        color: "#000000",
        align: "left",
        bold: false,
        italic: false,
      },
    ];
  }

  if (!elements.some((element) => isText(element) && element.key === "authors")) {
    let qr = elements.find(
      (element): element is TextTemplateElement => isText(element) && element.key === "qr",
    );
    if (!qr) {
      const side = Math.round(height * 0.12);
      qr = {
        id: createUuid(),
        type: "text",
        key: "qr",
        label: KEY_LABELS.qr,
        x: margin,
        y: Math.round(height * 0.82),
        fontSize: 12,
        fontFamily: "Times New Roman",
        color: "#000000",
        align: "left",
        bold: false,
        italic: false,
        width: side,
        height: side,
      };
      elements = [...elements, qr];
    }
    const qrWidth = qr.width ?? Math.round(height * 0.12);
    // A QR code on the right half gets a block aligned to its right edge.
    const onRight = qr.x + qrWidth / 2 > width / 2;
    const bodySize = body?.fontSize ?? Math.round(height * 0.024);
    elements = [
      ...elements,
      {
        id: createUuid(),
        type: "text",
        key: "authors",
        label: KEY_LABELS.authors,
        x: onRight ? qr.x + qrWidth : qr.x,
        y: qr.y - Math.max(Math.round(height * 0.015), 4),
        fontSize: Math.max(Math.round(bodySize * 0.8), 8),
        fontFamily: body?.fontFamily ?? "Times New Roman",
        color: "#000000",
        align: onRight ? "right" : "left",
        bold: false,
        italic: false,
        // Long names wrap instead of running into the signature.
        width: Math.round(width * 0.3),
        anchorY: "bottom",
      },
    ];
  }

  return { ...layout, elements };
}
