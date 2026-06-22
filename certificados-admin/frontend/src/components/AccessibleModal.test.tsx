import { useRef, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AccessibleModal from "./AccessibleModal";

function Harness() {
  const [open, setOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>Abrir modal</button>
      <AccessibleModal
        open={open}
        title="Confirmação"
        onClose={() => setOpen(false)}
        initialFocusRef={inputRef}
        footer={<button type="button" onClick={() => setOpen(false)}>Cancelar</button>}
      >
        <input ref={inputRef} aria-label="Motivo" />
      </AccessibleModal>
    </>
  );
}

test("gerencia foco, aria e Escape no modal", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  const opener = screen.getByRole("button", { name: "Abrir modal" });
  await user.click(opener);
  expect(screen.getByRole("dialog", { name: "Confirmação" }).getAttribute("aria-modal")).toBe("true");
  expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Motivo" }));
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(document.activeElement).toBe(opener);
});
