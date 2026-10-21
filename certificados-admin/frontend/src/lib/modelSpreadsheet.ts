/**
 * The "planilha modelo" offered on the emission screen.
 *
 * Columns mirror what services/spreadsheet.py accepts: `nome` and
 * `carga_horaria` are required, the rest optional. Two example rows show the
 * expected date format and that optional columns may be left blank, so the
 * operator can see the shape rather than infer it from prose.
 */
import { buildXlsx } from "./xlsx";

export const MODEL_COLUMNS = [
  "nome",
  "carga_horaria",
  "curso",
  "evento",
  "data_emissao",
  "data_inicio",
  "data_fim",
  "email",
  "registro_academico",
];

const EXAMPLE_ROWS = [
  [
    "Ana Carolina Souza",
    "12",
    "Direito",
    "Semana de Inovação",
    "10/06/2026",
    "10/06/2026",
    "12/06/2026",
    "ana.souza@exemplo.edu.br",
    "12345678900",
  ],
  ["João Pedro Lima", "8", "", "Semana de Inovação", "10/06/2026", "", "", "", ""],
];

/** Object URL for the model workbook. Built once and reused. */
let cachedUrl: string | null = null;

export function buildModelSpreadsheetUrl(): string {
  if (cachedUrl) return cachedUrl;
  // jsdom (tests) has no Blob URL support worth exercising here; guard so the
  // component can render in the test environment without throwing.
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return "#";
  }
  const blob = buildXlsx([MODEL_COLUMNS, ...EXAMPLE_ROWS], "certificados");
  cachedUrl = URL.createObjectURL(blob);
  return cachedUrl;
}
