import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import CertificateSubject, { certificateOf } from "./CertificateSubject";

const MOSTRA = "scientific_initiation";
const TITLE = "Horta vertical automatizada";
const AUTHORS = [
  "Pessoa Exemplo Alfa",
  "Pessoa Exemplo Beta",
  "Pessoa Exemplo Gama",
  "Pessoa Exemplo Delta",
  "Pessoa Exemplo Épsilon",
  "Pessoa Exemplo Zeta",
  "Pessoa Exemplo Eta",
  "Pessoa Exemplo Teta",
];

const work = (count: number) => ({
  participant_name: AUTHORS[0],
  certificate_type: MOSTRA,
  work_title: TITLE,
  authors: AUTHORS.slice(0, count),
});

test("certificado comum mostra só o titular, mesmo com título de trabalho", () => {
  const ordinary = {
    participant_name: "Ana Ativa",
    certificate_type: "speaker",
    work_title: "Palestra de abertura",
    authors: [],
  };
  const { container } = render(<CertificateSubject source={ordinary} />);
  expect(container.textContent).toBe("Ana Ativa");
  expect(certificateOf(ordinary)).toBe("de Ana Ativa");
});

test("um autor: título e “Autor:” no singular, sem botão", () => {
  const { container } = render(<CertificateSubject source={work(1)} />);
  expect(container.textContent).toBe(`${TITLE}Autor: ${AUTHORS[0]}`);
  expect(screen.queryByRole("button")).toBeNull();
  expect(certificateOf(work(1))).toBe(`do trabalho “${TITLE}”`);
});

test("três autores: todos visíveis, sem “+N”", () => {
  const { container } = render(<CertificateSubject source={work(3)} />);
  expect(container.textContent).toBe(`${TITLE}Autores: ${AUTHORS.slice(0, 3).join(", ")}`);
  expect(screen.queryByRole("button")).toBeNull();
});

test("oito autores: três e “+5”, lista completa no tooltip e ao tocar", async () => {
  const user = userEvent.setup();
  const { container } = render(<CertificateSubject source={work(8)} />);
  const more = screen.getByRole("button", { name: "+5 autores; mostrar todos" });
  expect(more.getAttribute("title")).toBe(AUTHORS.join(", "));
  expect(more.getAttribute("aria-expanded")).toBe("false");
  expect(container.textContent).toContain(`Autores: ${AUTHORS.slice(0, 3).join(", ")} +5`);
  expect(container.textContent).not.toContain(AUTHORS[3]);

  await user.click(more);
  expect(container.textContent).toContain(`Autores: ${AUTHORS.join(", ")}`);
  const less = screen.getByRole("button", { name: "mostrar menos" });
  expect(less.getAttribute("aria-expanded")).toBe("true");

  await user.click(less);
  expect(container.textContent).not.toContain(AUTHORS[3]);
});

test("Mostra sem autores nem título gravados continua pelo titular", () => {
  const legacy = { participant_name: "Ana Antiga", certificate_type: MOSTRA, authors: [] };
  const { container } = render(<CertificateSubject source={legacy} />);
  expect(container.textContent).toBe("Ana Antiga");
  expect(certificateOf(legacy)).toBe("de Ana Antiga");
});

test("Mostra sem título lista os autores como linha principal", () => {
  const untitled = { ...work(8), work_title: null };
  const { container } = render(<CertificateSubject source={untitled} />);
  expect(container.textContent).toContain(`Autores: ${AUTHORS.slice(0, 3).join(", ")} +5`);
  expect(certificateOf(untitled)).toBe(
    `do trabalho de ${AUTHORS.slice(0, 3).join(", ")} e mais 5`,
  );
});
