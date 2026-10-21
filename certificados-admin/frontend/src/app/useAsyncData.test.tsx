import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { useAsyncData } from "./useAsyncData";

function Probe({ loader }: { loader: () => Promise<string> }) {
  const state = useAsyncData(loader, []);
  return <span>{state.data ?? "carregando"}</span>;
}

test("StrictMode não duplica a requisição inicial", async () => {
  const loader = vi.fn().mockResolvedValue("pronto");
  render(
    <StrictMode>
      <Probe loader={loader} />
    </StrictMode>,
  );

  await screen.findByText("pronto");
  expect(loader).toHaveBeenCalledTimes(1);
});
