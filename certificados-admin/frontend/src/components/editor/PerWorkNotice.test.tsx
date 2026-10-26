import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { TextTemplateElement } from "../../types/template";
import PerWorkNotice from "./PerWorkNotice";

function text(key: string): TextTemplateElement {
  return {
    id: key,
    type: "text",
    key,
    label: key,
    x: 0,
    y: 0,
    fontSize: 20,
    fontFamily: "Times New Roman",
    color: "#000000",
    align: "left",
    bold: false,
    italic: false,
  };
}

test("template da Mostra com o nome e sem Autores diz o que falta", () => {
  render(
    <PerWorkNotice
      certificateType="scientific_initiation"
      elements={[text("name"), text("texto_certificado")]}
    />,
  );
  expect(
    screen.getByText(
      /Para emitir Mostra de Iniciação Científica, remova o Nome do participante; adicione o bloco Autores acima do QR Code\./,
    ),
  ).toBeTruthy();
  expect(screen.getByText(/ficam bloqueados na Conferência/)).toBeTruthy();
});

test("template da Mostra adequado só explica o formato", () => {
  render(
    <PerWorkNotice
      certificateType="scientific_initiation"
      elements={[text("texto_certificado"), text("authors")]}
    />,
  );
  expect(screen.getByText(/válido para todos os autores/)).toBeTruthy();
  expect(screen.queryByText(/ficam bloqueados/)).toBeNull();
});

test("templates genéricos e de outros tipos não mostram o aviso", () => {
  const { container } = render(
    <>
      <PerWorkNotice certificateType={null} elements={[text("name")]} />
      <PerWorkNotice certificateType="listener" elements={[text("name")]} />
    </>,
  );
  expect(container.textContent).toBe("");
});
