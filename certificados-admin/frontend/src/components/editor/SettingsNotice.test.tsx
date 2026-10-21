import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import SettingsNotice from "./SettingsNotice";
import { TemplateElement } from "../../types/template";

function textElement(key: string): TemplateElement {
  return {
    id: key,
    type: "text",
    key,
    label: key,
    x: 0,
    y: 0,
    fontSize: 24,
    fontFamily: "Times New Roman",
    color: "#000000",
    align: "left",
    bold: false,
    italic: false,
  };
}

const EMPTY = [
  { setting: "issue_location", label: "Cidade (local de emissão)" },
  { setting: "signatory_title", label: "Cargo do assinante" },
];

function renderNotice(props: Partial<Parameters<typeof SettingsNotice>[0]>) {
  return render(
    <MemoryRouter>
      <SettingsNotice
        emptySettings={EMPTY}
        canManage
        elements={[]}
        fallback={false}
        {...props}
      />
    </MemoryRouter>,
  );
}

test("fica em silêncio quando o layout não usa nenhuma configuração vazia", () => {
  const { container } = renderNotice({ elements: [textElement("name"), textElement("event")] });
  expect(container.textContent).toBe("");
});

test("avisa só sobre as configurações que o layout realmente imprime", () => {
  renderNotice({ elements: [textElement("issue_line"), textElement("signatory_name")] });

  expect(screen.getByText(/Sem valor nas Configurações/).textContent).toContain(
    "Cidade (local de emissão)",
  );
  expect(screen.queryByText(/Cargo do assinante/)).toBeNull();
  expect(screen.getByRole("link", { name: "Abrir Configurações" }).getAttribute("href")).toBe(
    "/configuracoes",
  );
});

test("quem não pode editar Configurações é orientado a falar com um administrador", () => {
  renderNotice({ elements: [textElement("signatory_title")], canManage: false });

  expect(screen.getByText(/Peça a um administrador/)).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
});

test("sem o servidor, explica que os dados de exemplo são locais", () => {
  renderNotice({ elements: [textElement("issue_line")], fallback: true });

  expect(screen.getByText(/Dados de exemplo locais/)).toBeTruthy();
  expect(screen.queryByText(/Sem valor nas Configurações/)).toBeNull();
});
