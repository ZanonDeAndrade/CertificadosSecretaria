import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";
import Historico from "./Historico";
import {
  downloadCertificatesZip,
  listCertificates,
  revokeCertificate,
} from "../services/api";

vi.mock("../services/api", () => ({
  listCertificates: vi.fn(),
  revokeCertificate: vi.fn(),
  downloadCertificatesZip: vi.fn(),
  downloadCertificateFile: vi.fn(),
  getApiErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}));

const active = {
  unique_code: "CERT-2026-ACTIVE",
  participant_name: "Ana Ativa",
  course_name: "Direito",
  event_name: "Evento",
  issue_date: "10/06/2026",
  status: "ativo",
  download_available: true,
};
const revoked = {
  ...active,
  unique_code: "CERT-2026-REVOKED",
  participant_name: "Rita Revogada",
  status: "revogado",
  download_available: false,
};
const unavailable = {
  ...active,
  unique_code: "CERT-2026-MISSING",
  participant_name: "Ivo Indisponível",
  download_available: false,
};

beforeEach(() => {
  vi.mocked(listCertificates).mockResolvedValue({
    items: [active, revoked, unavailable],
    total: 3,
    limit: 20,
    offset: 0,
  });
  vi.mocked(revokeCertificate).mockResolvedValue({ ...active, status: "revogado" });
  vi.mocked(downloadCertificatesZip).mockImplementation(async (_codes, progress) => {
    progress?.(50);
    return { blob: new Blob(["zip"]), skippedCodes: ["CERT-2026-MISSING"] };
  });
});

test("seleciona apenas disponíveis e informa download ZIP parcial", async () => {
  const user = userEvent.setup();
  render(<Historico />);
  await screen.findByText("Ana Ativa");

  expect((screen.getByRole("checkbox", { name: /Rita Revogada/ }) as HTMLInputElement).disabled).toBe(true);
  expect((screen.getByRole("checkbox", { name: /Ivo Indisponível/ }) as HTMLInputElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", { name: "Selecionar página" }));
  await user.click(screen.getByRole("button", { name: "Baixar ZIP (1)" }));

  await waitFor(() => expect(downloadCertificatesZip).toHaveBeenCalledWith([active.unique_code], expect.any(Function)));
  expect(await screen.findByText(/ZIP gerado parcialmente/)).not.toBeNull();
});

test("exige motivo e preserva erro específico ao revogar", async () => {
  const user = userEvent.setup();
  vi.mocked(revokeCertificate).mockRejectedValueOnce(new Error("Conflito específico do backend."));
  render(<Historico />);
  await screen.findByText("Ana Ativa");
  await user.click(screen.getAllByRole("button", { name: "Revogar" })[0]);

  const reason = screen.getByRole("textbox", { name: "Motivo" });
  expect(document.activeElement).toBe(reason);
  const confirm = screen.getByRole("button", { name: "Confirmar revogação" }) as HTMLButtonElement;
  expect(confirm.disabled).toBe(true);
  await user.type(reason, "erro de emissão");
  expect(confirm.disabled).toBe(false);
  await user.click(confirm);
  expect(await screen.findByText("Conflito específico do backend.")).not.toBeNull();
});
