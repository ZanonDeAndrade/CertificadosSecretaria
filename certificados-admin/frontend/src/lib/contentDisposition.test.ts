import { describe, expect, it } from "vitest";
import { filenameFromContentDisposition } from "./contentDisposition";

const UTF8_NAME = "Lisieli Rorato Dotto - Semana de Inovação - CERT-2026-3ETWK9.pdf";
const HEADER =
  'attachment; filename="Lisieli Rorato Dotto - Semana de Inovacao - CERT-2026-3ETWK9.pdf"; ' +
  `filename*=UTF-8''${encodeURIComponent(UTF8_NAME)}`;

describe("filenameFromContentDisposition", () => {
  it("prefere o nome UTF-8, com acentos", () => {
    expect(filenameFromContentDisposition(HEADER, "x.pdf")).toBe(UTF8_NAME);
  });

  it("usa o nome ASCII quando não há filename*", () => {
    expect(filenameFromContentDisposition('attachment; filename="Ana Silva.pdf"', "x.pdf")).toBe(
      "Ana Silva.pdf",
    );
    expect(filenameFromContentDisposition("attachment; filename=ana.pdf", "x.pdf")).toBe(
      "ana.pdf",
    );
  });

  it("recorre ao nome ASCII quando o filename* está malformado", () => {
    const header = `attachment; filename="Joao.pdf"; filename*=UTF-8''Jo%E3o%.pdf`;
    expect(filenameFromContentDisposition(header, "x.pdf")).toBe("Joao.pdf");
  });

  it("usa o nome de reserva sem cabeçalho ou sem nome", () => {
    expect(filenameFromContentDisposition(undefined, "CERT-2026-AB1234.pdf")).toBe(
      "CERT-2026-AB1234.pdf",
    );
    expect(filenameFromContentDisposition("attachment", "CERT-2026-AB1234.pdf")).toBe(
      "CERT-2026-AB1234.pdf",
    );
  });
});
