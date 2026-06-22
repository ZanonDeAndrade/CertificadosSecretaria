import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import * as fabric from "fabric";
import { useEditorCanvas } from "./useEditorCanvas";

vi.mock("fabric", () => {
  class FabricObject {
    left = 0;
    top = 0;
    width = 1;
    height = 1;
    scaleX = 1;
    scaleY = 1;
    opacity = 1;
    data?: { elementId: string };

    set(keyOrValues: string | Record<string, unknown>, value?: unknown) {
      if (typeof keyOrValues === "string") {
        Object.assign(this, { [keyOrValues]: value });
      } else {
        Object.assign(this, keyOrValues);
      }
      return this;
    }
  }

  class FabricImage extends FabricObject {
    static fromURL = vi.fn(async () => {
      const image = new FabricImage();
      image.width = 1200;
      image.height = 800;
      return image;
    });
  }

  class IText extends FabricObject {
    constructor(public text: string, options: Record<string, unknown>) {
      super();
      this.set(options);
    }
  }

  class Textbox extends IText {}

  class Canvas {
    static instances: Canvas[] = [];
    backgroundImage?: FabricImage;
    objects: FabricObject[] = [];
    width: number;
    height: number;
    requestRenderAll = vi.fn();
    renderAll = vi.fn();

    constructor(_element: HTMLCanvasElement, options: { width: number; height: number }) {
      this.width = options.width;
      this.height = options.height;
      Canvas.instances.push(this);
    }

    on() {}
    dispose() {}
    add(object: FabricObject) {
      this.objects.push(object);
    }
    remove(object: FabricObject) {
      this.objects = this.objects.filter((candidate) => candidate !== object);
    }
    getObjects() {
      return this.objects;
    }
    setActiveObject() {}
    discardActiveObject() {}
    setDimensions(dimensions: { width: number; height: number }) {
      this.width = dimensions.width;
      this.height = dimensions.height;
    }
    getWidth() {
      return this.width;
    }
    getHeight() {
      return this.height;
    }
  }

  return { Canvas, FabricImage, FabricObject, IText, Textbox };
});

function Harness() {
  const editor = useEditorCanvas();

  return (
    <>
      <canvas ref={editor.canvasRef} />
      <button
        type="button"
        onClick={() =>
          editor.setBackground("data:image/png;base64,ZmFrZQ==", 1200, 800)
        }
      >
        fundo
      </button>
      <button type="button" onClick={() => editor.addTextElement("name")}>
        texto
      </button>
      <button type="button" onClick={() => editor.addTextElement("texto_certificado")}>
        corpo
      </button>
      <button
        type="button"
        onClick={() =>
          void editor.addImageElement(
            new File(["imagem"], "logo.png", { type: "image/png" }),
          )
        }
      >
        imagem
      </button>
      <output data-testid="background">{editor.backgroundUrl ?? "sem fundo"}</output>
      <output data-testid="elements">{editor.elements.length}</output>
      <output data-testid="error">{editor.canvasError ?? "sem erro"}</output>
    </>
  );
}

beforeEach(() => {
  const FabricImage = fabric.FabricImage as unknown as {
    fromURL: ReturnType<typeof vi.fn>;
  };
  FabricImage.fromURL.mockReset().mockImplementation(async () => {
    const image = new fabric.FabricImage(document.createElement("img"));
    image.set({ width: 1200, height: 800 });
    return image;
  });
  (
    fabric.Canvas as unknown as { instances: unknown[] }
  ).instances.length = 0;
});

test("carrega o fundo com a API assíncrona do Fabric v7", async () => {
  render(<Harness />);

  fireEvent.click(screen.getByRole("button", { name: "fundo" }));

  await waitFor(() =>
    expect(screen.getByTestId("background").textContent).toContain("data:image/png"),
  );
  expect(fabric.FabricImage.fromURL).toHaveBeenCalledWith(
    "data:image/png;base64,ZmFrZQ==",
    { crossOrigin: "anonymous" },
  );

  const canvas = (
    fabric.Canvas as unknown as {
      instances: Array<{
        backgroundImage?: fabric.FabricImage;
        width: number;
        height: number;
        requestRenderAll: ReturnType<typeof vi.fn>;
      }>;
    }
  ).instances[0];
  expect(canvas.backgroundImage).toBeInstanceOf(fabric.FabricImage);
  expect({ width: canvas.width, height: canvas.height }).toEqual({
    width: 900,
    height: 600,
  });
  expect(canvas.requestRenderAll).toHaveBeenCalled();
});

test("adiciona elementos de texto e imagem ao canvas", async () => {
  render(<Harness />);

  fireEvent.click(screen.getByRole("button", { name: "texto" }));
  fireEvent.click(screen.getByRole("button", { name: "imagem" }));

  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("2"));

  const canvas = (
    fabric.Canvas as unknown as {
      instances: Array<{ objects: fabric.FabricObject[] }>;
    }
  ).instances[0];
  expect(canvas.objects.some((object) => object instanceof fabric.IText)).toBe(true);
  expect(canvas.objects.some((object) => object instanceof fabric.FabricImage)).toBe(true);
});

test("o corpo do certificado é adicionado como Textbox (com quebra de linha)", async () => {
  render(<Harness />);

  fireEvent.click(screen.getByRole("button", { name: "corpo" }));

  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("1"));

  const canvas = (
    fabric.Canvas as unknown as {
      instances: Array<{ objects: fabric.FabricObject[] }>;
    }
  ).instances[0];
  const body = canvas.objects.find((object) => object instanceof fabric.Textbox);
  expect(body).toBeTruthy();
  // A Textbox carries a wrap width (the IText branch would not set one).
  expect((body as fabric.Textbox).width).toBeGreaterThan(0);
});

test("expõe a falha de carregamento em vez de ignorá-la", async () => {
  const error = new Error("imagem recusada");
  vi.mocked(fabric.FabricImage.fromURL).mockRejectedValueOnce(error);
  const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
  render(<Harness />);

  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "fundo" }));
  });

  await waitFor(() =>
    expect(screen.getByTestId("error").textContent).toContain(
      "Não foi possível carregar",
    ),
  );
  expect(consoleError).toHaveBeenCalledWith(
    expect.stringContaining("[EditorCanvas]"),
    error,
  );
});
