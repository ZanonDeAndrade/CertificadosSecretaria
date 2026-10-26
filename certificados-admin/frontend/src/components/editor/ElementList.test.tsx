import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import ElementList from "./ElementList";

function renderList(certificateType: string | null) {
  const onAdd = vi.fn();
  render(
    <ElementList
      elements={[]}
      selectedId={null}
      certificateType={certificateType}
      onAdd={onAdd}
      onSelect={vi.fn()}
      onDelete={vi.fn()}
      onDuplicate={vi.fn()}
    />,
  );
  return onAdd;
}

test("o bloco Autores só é oferecido em templates de certificado por trabalho", () => {
  renderList("scientific_initiation");
  expect(screen.getByRole("button", { name: "Autores" })).toBeTruthy();
});

test("templates genéricos e de outros tipos não oferecem Autores", () => {
  renderList(null);
  expect(screen.queryByRole("button", { name: "Autores" })).toBeNull();
  // Team and work title exist on every type's spreadsheet.
  expect(screen.getByRole("button", { name: "Equipe" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Título" })).toBeTruthy();
});

test("templates da Mostra não oferecem o Nome do participante", () => {
  renderList("scientific_initiation");
  expect(screen.queryByRole("button", { name: "Nome" })).toBeNull();
  expect(screen.getByRole("button", { name: "Corpo" })).toBeTruthy();
});

test("os demais templates continuam oferecendo o Nome", () => {
  renderList("listener");
  expect(screen.getByRole("button", { name: "Nome" })).toBeTruthy();
});

test("adicionar Autores passa a chave do elemento", () => {
  const onAdd = renderList("scientific_initiation");
  screen.getByRole("button", { name: "Autores" }).click();
  expect(onAdd).toHaveBeenCalledWith("authors");
});
