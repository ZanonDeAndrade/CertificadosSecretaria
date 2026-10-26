import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import * as fabric from "fabric";
import { EditorAPI, useEditorCanvas } from "./useEditorCanvas";
import { computeTextLayouts } from "../services/templateApi";

vi.mock("../services/templateApi", () => ({
  computeTextLayouts: vi.fn(async () => []),
}));

vi.mock("fabric", () => {
  class FabricObject {
    left = 0;
    top = 0;
    width = 1;
    height = 1;
    scaleX = 1;
    scaleY = 1;
    opacity = 1;
    cornerSize = 13;
    touchCornerSize = 24;
    borderColor = "";
    controls: Record<string, unknown> = {};
    data?: { elementId: string };

    set(keyOrValues: string | Record<string, unknown>, value?: unknown) {
      if (typeof keyOrValues === "string") {
        Object.assign(this, { [keyOrValues]: value });
      } else {
        Object.assign(this, keyOrValues);
      }
      return this;
    }

    setCoords() {}
  }

  class FabricImage extends FabricObject {
    static fromURL = vi.fn(async () => {
      const image = new FabricImage();
      image.width = 1200;
      image.height = 800;
      return image;
    });
  }

  /* Enough of fabric's text layout for the hook: lines split on typed breaks,
   * one line is fontSize × 1.13 tall and half as wide per character. */
  class IText extends FabricObject {
    text: string;
    fontSize = 32;
    textAlign = "left";
    lineHeight = 1.3;
    _fontSizeMult = 1.13;
    initialized = true;
    _textLines: string[][] = [];

    constructor(text: string, options: Record<string, unknown>) {
      super();
      this.text = text;
      this.set(options);
      this.initDimensions();
    }

    initDimensions() {
      this._textLines = this._wrapText(this.text.split("\n"), this.width);
      this.height = this.calcTextHeight();
    }

    _wrapText(lines: string[], _desiredWidth: number): string[][] {
      return lines.map((line) => this.graphemeSplit(line));
    }

    graphemeSplit(value: string): string[] {
      return Array.from(value);
    }

    calcTextHeight() {
      return Math.max(this._textLines.length, 1) * this.fontSize * this._fontSizeMult;
    }

    calcTextWidth() {
      const longest = Math.max(0, ...this._textLines.map((line) => line.length));
      return Math.max(longest * this.fontSize * 0.5, 1);
    }

    _render() {}
  }

  class Textbox extends IText {}

  class Control {
    constructor(public options: Record<string, unknown>) {}
  }

  class Canvas {
    static instances: Canvas[] = [];
    backgroundImage?: FabricImage;
    objects: FabricObject[] = [];
    handlers: Record<string, (event: unknown) => void> = {};
    width: number;
    height: number;
    requestRenderAll = vi.fn();
    renderAll = vi.fn();

    constructor(_element: HTMLCanvasElement, options: { width: number; height: number }) {
      this.width = options.width;
      this.height = options.height;
      Canvas.instances.push(this);
    }

    on(event: string, handler: (event: unknown) => void) {
      this.handlers[event] = handler;
    }
    fire(event: string, payload: unknown) {
      this.handlers[event]?.(payload);
    }
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

  return { Canvas, FabricImage, FabricObject, IText, Textbox, Control };
});

type MockCanvas = {
  objects: Array<
    fabric.FabricObject & {
      data?: { elementId: string };
      serverLines?: string[] | null;
      overflow?: boolean;
      applyResize?: (rect: object, handle: string) => boolean;
      cornerSize?: number;
    }
  >;
  fire: (event: string, payload: unknown) => void;
  backgroundImage?: fabric.FabricImage;
  width: number;
  height: number;
  requestRenderAll: ReturnType<typeof vi.fn>;
};

function canvasInstance(index = 0): MockCanvas {
  return (fabric.Canvas as unknown as { instances: MockCanvas[] }).instances[index];
}

let latest: EditorAPI | null = null;

function Harness() {
  const editor = useEditorCanvas();
  latest = editor;

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
      <output data-testid="source">{editor.layoutSource}</output>
    </>
  );
}

const LAYOUT = {
  background: "data:image/png;base64,ZmFrZQ==",
  image_width: 1200,
  image_height: 800,
  elements: [
    {
      id: "legacy",
      type: "text",
      key: "event",
      x: 600,
      y: 100,
      fontSize: 32,
      fontFamily: "Times New Roman",
      color: "#000000",
      align: "center",
      bold: false,
      italic: false,
    },
    {
      id: "boxed",
      type: "text",
      key: "static",
      staticText: "Texto fixo",
      x: 100,
      y: 300,
      width: 420,
      height: 90,
      fontSize: 24,
      fontFamily: "Arial",
      color: "#000000",
      align: "left",
      bold: false,
      italic: false,
    },
    { type: "qr", key: "qr", x: 60, y: 650, width: 140, height: 140 },
    {
      id: "authors",
      type: "text",
      key: "authors",
      x: 60,
      y: 620,
      anchorY: "bottom",
      fontSize: 20,
      fontFamily: "Times New Roman",
      color: "#000000",
      align: "left",
      bold: false,
      italic: false,
    },
  ],
};

function loadLayout() {
  act(() => {
    latest?.loadTemplate(LAYOUT as never);
  });
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
  vi.mocked(computeTextLayouts).mockReset().mockResolvedValue([]);
  latest = null;
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

  const canvas = canvasInstance();
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

  const canvas = canvasInstance();
  expect(canvas.objects.some((object) => object instanceof fabric.IText)).toBe(true);
  expect(canvas.objects.some((object) => object instanceof fabric.FabricImage)).toBe(true);
});

test("o corpo do certificado é adicionado como Textbox (com quebra de linha)", async () => {
  render(<Harness />);

  fireEvent.click(screen.getByRole("button", { name: "corpo" }));

  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("1"));

  const canvas = canvasInstance();
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

test("o bloco de autores tem base fixa: Y é a borda de baixo e sobrevive ao salvar", async () => {
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  const canvas = canvasInstance();
  const object = canvas.objects.find((candidate) => candidate.data?.elementId === "authors") as
    | (fabric.FabricObject & {
        anchorBottom?: boolean;
        originY?: string;
        text?: string;
        elementY?: () => number;
        applyResize?: (rect: object, handle: string) => boolean;
      })
    | undefined;
  expect(object?.anchorBottom).toBe(true);
  expect(object?.originY).toBe("bottom");
  // Sample data lists eight authors, one per line under the heading, so the
  // tallest case is previewed.
  const lines = object?.text?.split("\n");
  expect(lines).toHaveLength(9);
  expect(lines?.[0]).toBe("Autores:");
  expect(lines?.[8]).toBe("Carla Dias");

  // Pulling the top handle makes the box taller; the base keeps Y = 620.
  act(() => {
    object!.applyResize!({ left: 60, top: 400, width: 300, height: 220 }, "mt");
    canvas.fire("object:modified", { target: object });
  });
  await waitFor(() =>
    expect(latest!.elements.find((element) => element.id === "authors")).toMatchObject({
      y: 620,
      height: 220,
      anchorY: "bottom",
    }),
  );
  const saved = latest!.getLayout().elements.find((element) => element.id === "authors")!;
  expect(saved).toMatchObject({ anchorY: "bottom", y: 620 });

  // A new authors block is created bottom-anchored and left-aligned.
  act(() => {
    latest!.addTextElement("authors");
  });
  await waitFor(() => expect(latest!.elements.length).toBe(5));
  const created = latest!.elements[4];
  expect(created).toMatchObject({ key: "authors", anchorY: "bottom", align: "left" });
});

test("largura e altura da caixa sobrevivem ao carregar e salvar; sem elas, nada é inventado", async () => {
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  const saved = latest!.getLayout();
  const legacy = saved.elements.find((element) => element.id === "legacy")!;
  const boxed = saved.elements.find((element) => element.id === "boxed")!;
  const qr = saved.elements.find((element) => element.key === "qr")!;

  expect("width" in legacy).toBe(false);
  expect("height" in legacy).toBe(false);
  expect(JSON.parse(JSON.stringify(legacy))).not.toHaveProperty("width");
  expect(boxed).toMatchObject({ width: 420, height: 90, x: 100, y: 300 });
  // The QR keeps its size through the round trip instead of falling back to 160 px.
  expect(qr).toMatchObject({ width: 140, height: 140 });
});

test("um arraste de alça vira uma única atualização com largura, altura e nova origem", async () => {
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  const canvas = canvasInstance();
  const object = canvas.objects.find((candidate) => candidate.data?.elementId === "legacy")!;
  expect(object.applyResize).toBeTypeOf("function");

  act(() => {
    // The top-left handle was pulled: the box now starts at (300, 80) and
    // measures 400 × 60 art px. X is the centre for a centred text.
    object.applyResize!({ left: 300, top: 80, width: 400, height: 60 }, "tl");
    canvas.fire("object:modified", { target: object });
  });

  await waitFor(() =>
    expect(latest!.elements.find((element) => element.id === "legacy")).toMatchObject({
      x: 500,
      y: 80,
      width: 400,
      height: 60,
    }),
  );
  // Only the dragged element changed.
  expect(latest!.elements.find((element) => element.id === "boxed")).toMatchObject({
    width: 420,
    height: 90,
  });
});

test("uma alça lateral grava só a largura", async () => {
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  const canvas = canvasInstance();
  const object = canvas.objects.find((candidate) => candidate.data?.elementId === "legacy")!;
  act(() => {
    object.applyResize!({ left: 400, top: 100, width: 400, height: 36 }, "mr");
    canvas.fire("object:modified", { target: object });
  });

  await waitFor(() =>
    expect(latest!.elements.find((element) => element.id === "legacy")).toMatchObject({
      width: 400,
    }),
  );
  expect(latest!.elements.find((element) => element.id === "legacy")).not.toHaveProperty(
    "height",
  );
});

test("aplica as quebras de linha do servidor e sinaliza o estouro da caixa", async () => {
  vi.mocked(computeTextLayouts).mockResolvedValue([
    {
      id: "boxed",
      lines: ["Texto", "fixo"],
      font_size: 24,
      line_height: 28,
      text_height: 100,
      wrap_width: 420,
      overflow: true,
      top_offset: 0,
    },
  ]);
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  await waitFor(() => expect(screen.getByTestId("source").textContent).toBe("server"));
  expect(vi.mocked(computeTextLayouts)).toHaveBeenCalledWith(
    1200,
    expect.arrayContaining([
      expect.objectContaining({ id: "boxed", text: "Texto fixo", width: 420, height: 90 }),
      expect.objectContaining({ id: "legacy", key: "event" }),
    ]),
  );
  // The QR is not a text box and is never measured.
  const sent = vi.mocked(computeTextLayouts).mock.calls.at(-1)![1];
  expect(sent.some((item) => item.key === "qr")).toBe(false);

  expect(latest!.textLayouts.boxed).toMatchObject({
    lines: ["Texto", "fixo"],
    overflow: true,
    source: "server",
  });
  const object = canvasInstance().objects.find(
    (candidate) => candidate.data?.elementId === "boxed",
  )!;
  expect(object.serverLines).toEqual(["Texto", "fixo"]);
  expect(object.overflow).toBe(true);
});

test("se o servidor falhar, a prévia local continua e o editor não trava", async () => {
  vi.mocked(computeTextLayouts).mockRejectedValue(new Error("offline"));
  const consoleWarn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  await waitFor(() => expect(screen.getByTestId("source").textContent).toBe("local"));
  expect(screen.getByTestId("error").textContent).toBe("sem erro");
  expect(latest!.textLayouts.boxed).toMatchObject({ source: "local", wrapWidth: 420 });
  expect(consoleWarn).toHaveBeenCalled();
});

test("a primeira largura de um nome centralizado em Y mantém a primeira linha no lugar", async () => {
  vi.mocked(computeTextLayouts).mockResolvedValue([
    {
      id: "legacy",
      lines: ["Maria Aparecida", "da Conceição"],
      font_size: 28,
      line_height: 34,
      text_height: 60,
      wrap_width: 1000,
      overflow: false,
      top_offset: 17,
    },
  ]);
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));
  await waitFor(() => expect(latest!.textLayouts.legacy?.topOffset).toBe(17));

  act(() => {
    latest!.updateElement("legacy", { width: 500 });
  });

  await waitFor(() =>
    expect(latest!.elements.find((element) => element.id === "legacy")).toMatchObject({
      width: 500,
      y: 83,
    }),
  );
});

test("valores digitados respeitam o mínimo e o limite da arte", async () => {
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  act(() => {
    latest!.updateElement("boxed", { width: 5, height: 100000 });
  });
  await waitFor(() =>
    expect(latest!.elements.find((element) => element.id === "boxed")).toMatchObject({
      width: 20,
      height: 500,
    }),
  );

  act(() => {
    latest!.updateElement("boxed", { width: undefined, height: undefined });
  });
  await waitFor(() => {
    const boxed = latest!.elements.find((element) => element.id === "boxed")!;
    expect(boxed.width).toBeUndefined();
    expect(boxed.height).toBeUndefined();
  });
});

test("dados de exemplo do servidor substituem o texto da prévia e são remedidos", async () => {
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));
  await waitFor(() => expect(vi.mocked(computeTextLayouts)).toHaveBeenCalled());
  vi.mocked(computeTextLayouts).mockClear();

  act(() => {
    latest!.setSampleData({ event: "Semana do Conhecimento" });
  });

  const object = canvasInstance().objects.find(
    (candidate) => candidate.data?.elementId === "legacy",
  ) as (fabric.FabricObject & { text?: string }) | undefined;
  expect(object?.text).toBe("Semana do Conhecimento");
  expect(latest!.sampleSource).toBe("server");
  await waitFor(() =>
    expect(vi.mocked(computeTextLayouts)).toHaveBeenCalledWith(
      1200,
      expect.arrayContaining([
        expect.objectContaining({ id: "legacy", text: "Semana do Conhecimento" }),
      ]),
    ),
  );
});

test("as alças mantêm o tamanho na tela quando o zoom muda", async () => {
  render(<Harness />);
  loadLayout();
  await waitFor(() => expect(screen.getByTestId("elements").textContent).toBe("4"));

  act(() => {
    latest!.setZoom(2);
  });

  const canvas = canvasInstance();
  const text = canvas.objects.find((candidate) => candidate.data?.elementId === "boxed")!;
  expect(text.cornerSize).toBe(5);
});
