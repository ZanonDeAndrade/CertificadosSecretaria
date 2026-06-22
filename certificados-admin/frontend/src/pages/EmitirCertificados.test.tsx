import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import EmitirCertificados from "./EmitirCertificados";
import {
  generateCertificatesFromSpreadsheet,
  validateSpreadsheet,
} from "../services/api";

vi.mock("../services/api", () => ({
  API_BASE_URL: "http://test",
  validateSpreadsheet: vi.fn(),
  generateCertificatesFromSpreadsheet: vi.fn(),
}));

const PREVIEW = {
  total: 1,
  valid_count: 1,
  invalid_count: 0,
  valid: [
    {
      row_number: 2,
      nome: "Ana",
      curso: "Direito",
      evento: "Semana",
      carga_horaria: 40,
      data_emissao: "10/06/2026",
      email: "",
      documento: "",
      data_inicio: "",
      data_fim: "",
    },
  ],
  invalid: [],
  resolved_text_preview: "participou da Semana, com carga horária de 40 horas.",
};

beforeEach(() => {
  vi.mocked(validateSpreadsheet).mockResolvedValue(PREVIEW);
  vi.mocked(generateCertificatesFromSpreadsheet).mockResolvedValue({
    generated: [],
    generated_count: 0,
    duplicates: [],
    duplicate_count: 0,
    invalid: [],
    invalid_count: 0,
    total_rows: 1,
  });
});

function textarea(): HTMLTextAreaElement {
  return screen.getByLabelText("Texto padrão do certificado") as HTMLTextAreaElement;
}

function validateButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /Validar planilha/i }) as HTMLButtonElement;
}

function selectFile(): File {
  const input = document.getElementById("spreadsheet-upload") as HTMLInputElement;
  const file = new File([new Uint8Array([1, 2, 3])], "p.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

test("texto é obrigatório, controla o botão e é enviado ao backend", async () => {
  render(<EmitirCertificados />);

  // The example body is pre-filled in the field.
  expect(textarea().value).toContain("{{carga_horaria}}");

  // No file yet → validate is disabled even with text present.
  expect(validateButton().disabled).toBe(true);

  const file = selectFile();
  expect(validateButton().disabled).toBe(false);

  // Clearing the text disables it again (obrigatório).
  fireEvent.change(textarea(), { target: { value: "   " } });
  expect(validateButton().disabled).toBe(true);

  // A real body re-enables and is sent verbatim.
  fireEvent.change(textarea(), { target: { value: "corpo de {{nome}}" } });
  expect(validateButton().disabled).toBe(false);
  fireEvent.click(validateButton());

  await waitFor(() =>
    expect(validateSpreadsheet).toHaveBeenCalledWith(file, undefined, "corpo de {{nome}}"),
  );
});

test("mostra a prévia resolvida e envia o mesmo texto ao gerar", async () => {
  render(<EmitirCertificados />);
  selectFile();
  fireEvent.change(textarea(), { target: { value: "texto {{nome}}" } });
  fireEvent.click(validateButton());

  // Preview step shows the interpolated text returned by the backend.
  await screen.findByText(PREVIEW.resolved_text_preview);

  fireEvent.click(screen.getByRole("button", { name: /Gerar/i }));
  await waitFor(() =>
    expect(generateCertificatesFromSpreadsheet).toHaveBeenCalledWith(
      expect.any(File),
      undefined,
      "texto {{nome}}",
    ),
  );
});

test("limpa o texto ao iniciar outra emissão", async () => {
  render(<EmitirCertificados />);
  selectFile();
  fireEvent.change(textarea(), { target: { value: "corpo editado {{nome}}" } });
  fireEvent.click(validateButton());
  await screen.findByText(PREVIEW.resolved_text_preview);
  fireEvent.click(screen.getByRole("button", { name: /Gerar/i }));

  const again = await screen.findByRole("button", { name: /Emitir outra planilha/i });
  fireEvent.click(again);

  // Back at the upload step with the example restored (custom edit cleared).
  expect(textarea().value).toContain("{{carga_horaria}}");
  expect(textarea().value).not.toContain("corpo editado");
});

test("botão insere a variável na posição do cursor", () => {
  render(<EmitirCertificados />);
  const ta = textarea();
  fireEvent.change(ta, { target: { value: "AB" } });
  ta.focus();
  ta.setSelectionRange(1, 1); // cursor between A and B

  fireEvent.click(screen.getByRole("button", { name: "Inserir {{nome}}" }));
  expect(ta.value).toBe("A{{nome}}B");

  // Move the caret to the end and insert another variable there.
  ta.setSelectionRange(ta.value.length, ta.value.length);
  fireEvent.click(screen.getByRole("button", { name: "Inserir {{carga_horaria}}" }));
  expect(ta.value).toBe("A{{nome}}B{{carga_horaria}}");
});
