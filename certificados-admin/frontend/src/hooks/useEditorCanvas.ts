import { useCallback, useEffect, useRef, useState } from "react";
import * as fabric from "fabric";
import {
  ElementKey,
  ImageTemplateElement,
  KEY_LABELS,
  MOCK_DATA,
  TemplateElement,
  TemplateLayout,
  TextTemplateElement,
} from "../types/template";
import { API_BASE_URL } from "../services/api";

const CANVAS_MAX_WIDTH = 900;
const MIN_SCALE = 0.01;

function isTextElement(element: TemplateElement): element is TextTemplateElement {
  return element.type === "text";
}

function isImageElement(element: TemplateElement): element is ImageTemplateElement {
  return element.type === "image";
}

function resolveDisplayText(element: TextTemplateElement, useMock: boolean): string {
  if (element.key === "static") return element.staticText ?? "";
  if (useMock) return MOCK_DATA[element.key] ?? `{${element.key}}`;
  return `{${element.key}}`;
}

function toAbsoluteUrl(url: string): string {
  if (!url) return "";
  return url.startsWith("http") ? url : `${API_BASE_URL}${url}`;
}

function toAbsoluteImageSource(url: string): string {
  if (!url) return "";
  if (url.startsWith("data:image")) return url;
  if (url.startsWith("blob:")) return url;
  return toAbsoluteUrl(url);
}

function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (event) => {
      const result = event.target?.result;
      if (typeof result !== "string") {
        reject(new Error("Falha ao ler arquivo de imagem."));
        return;
      }
      resolve(result);
    };
    reader.onerror = () => reject(new Error("Falha ao ler arquivo de imagem."));
    reader.readAsDataURL(file);
  });
}

async function loadFabricImage(
  url: string,
  options?: { crossOrigin?: "" | "anonymous" | "use-credentials"; signal?: AbortSignal },
): Promise<fabric.FabricImage> {
  if (!url) throw new Error("URL de imagem inválida.");
  return await fabric.FabricImage.fromURL(url, options);
}

function buildFabricTextOptions(
  element: TextTemplateElement,
  scale: number,
): Partial<fabric.IText> {
  return {
    left: element.x * scale,
    top: element.y * scale,
    originX:
      element.align === "center"
        ? "center"
        : element.align === "right"
          ? "right"
          : "left",
    originY: "top",
    fontSize: Math.max(element.fontSize * scale, 4),
    fontFamily: element.fontFamily,
    fill: element.color,
    textAlign: element.align,
    fontWeight: element.bold ? "bold" : "normal",
    fontStyle: element.italic ? "italic" : "normal",
    lockScalingX: true,
    lockScalingY: true,
    lockSkewingX: true,
    lockSkewingY: true,
    hasControls: false,
    hasBorders: true,
    editable: false,
    selectable: true,
    hoverCursor: "move",
  };
}

// Text element keys whose content is the (long) certificate body. These are
// rendered as a wrapping Textbox so the editor preview mirrors the PDF.
const BODY_TEXT_KEYS = new Set<string>(["texto_certificado", "certificate_text"]);

function isBodyTextElement(element: TemplateElement): boolean {
  return element.type === "text" && BODY_TEXT_KEYS.has(element.key);
}

/** Image width in DISPLAY pixels (or the canvas width before a background). */
function computeDisplayImageWidth(
  naturalWidth: number,
  scale: number,
  canvas: fabric.Canvas | null,
): number {
  if (naturalWidth > 1) return naturalWidth * scale;
  return canvas ? canvas.getWidth() : CANVAS_MAX_WIDTH;
}

/**
 * Wrap width (display px) for a body Textbox — mirrors the PDF generator's
 * ``_wrap_bound``: the text grows toward the page edge implied by its alignment,
 * leaving a 4% margin, so the editor preview wraps where the PDF wraps.
 */
function bodyWrapWidthDisplay(
  element: TextTemplateElement,
  scale: number,
  displayImageWidth: number,
): number {
  const anchor = element.x * scale;
  const margin = Math.max(displayImageWidth * 0.04, 8);
  let bound: number;
  if (element.align === "center") {
    bound = 2 * (Math.min(anchor, displayImageWidth - anchor) - margin);
  } else if (element.align === "right") {
    bound = anchor - margin;
  } else {
    bound = displayImageWidth - anchor - margin;
  }
  return Math.max(bound, 16);
}

function buildFabricTextboxOptions(
  element: TextTemplateElement,
  scale: number,
  width: number,
): Partial<fabric.Textbox> {
  return {
    left: element.x * scale,
    top: element.y * scale,
    width,
    originX:
      element.align === "center"
        ? "center"
        : element.align === "right"
          ? "right"
          : "left",
    originY: "top",
    fontSize: Math.max(element.fontSize * scale, 4),
    fontFamily: element.fontFamily,
    fill: element.color,
    textAlign: element.align,
    fontWeight: element.bold ? "bold" : "normal",
    fontStyle: element.italic ? "italic" : "normal",
    lineHeight: 1.3,
    lockScalingX: true,
    lockScalingY: true,
    lockSkewingX: true,
    lockSkewingY: true,
    hasControls: false,
    hasBorders: true,
    editable: false,
    selectable: true,
    hoverCursor: "move",
  };
}

function normalizeTemplateElement(raw: any): TemplateElement | null {
  if (!raw || typeof raw !== "object") return null;

  if (raw.type === "image") {
    const src = String(raw.src ?? "").trim();
    if (!src) return null;

    return {
      id: String(raw.id ?? crypto.randomUUID()),
      type: "image",
      key: "image",
      label: String(raw.label ?? KEY_LABELS.image),
      x: Number(raw.x ?? 0),
      y: Number(raw.y ?? 0),
      width: Math.max(1, Number(raw.width ?? 200)),
      height: Math.max(1, Number(raw.height ?? 120)),
      src,
      opacity: Math.min(Math.max(Number(raw.opacity ?? 1), 0), 1),
    };
  }

  const key = String(raw.key ?? "name");
  return {
    id: String(raw.id ?? crypto.randomUUID()),
    type: "text",
    key,
    label: String(raw.label ?? KEY_LABELS[key] ?? key),
    x: Number(raw.x ?? 0),
    y: Number(raw.y ?? 0),
    fontSize: Math.max(6, Number(raw.fontSize ?? 32)),
    fontFamily: String(raw.fontFamily ?? "Times New Roman"),
    color: String(raw.color ?? "#000000"),
    align:
      raw.align === "center" || raw.align === "right" || raw.align === "left"
        ? raw.align
        : "left",
    bold: Boolean(raw.bold),
    italic: Boolean(raw.italic),
    staticText: raw.staticText ? String(raw.staticText) : undefined,
  };
}

export interface EditorAPI {
  /**
   * Callback ref to attach to the `<canvas>` element. Fabric is initialized the
   * moment the node mounts and torn down when it unmounts — this is essential
   * because the canvas only exists in "edit" mode, not when the hook first
   * mounts in "list" mode.
   */
  canvasRef: React.RefCallback<HTMLCanvasElement>;
  elements: TemplateElement[];
  selectedId: string | null;
  backgroundUrl: string | null;
  imageSize: { width: number; height: number };
  scale: number;
  showMockData: boolean;
  showGrid: boolean;
  zoom: number;
  canvasError: string | null;
  addTextElement: (key?: ElementKey) => void;
  addImageElement: (file: File) => Promise<void>;
  updateElement: (id: string, changes: Partial<TemplateElement>) => void;
  deleteElement: (id: string) => void;
  duplicateElement: (id: string) => void;
  selectElement: (id: string | null) => void;
  setBackground: (url: string, width: number, height: number) => void;
  loadTemplate: (layout: TemplateLayout) => void;
  setShowMockData: (v: boolean) => void;
  setShowGrid: (v: boolean) => void;
  setZoom: (v: number) => void;
  getLayout: () => TemplateLayout;
  clearAll: () => void;
  exportJSON: () => string;
  importJSON: (json: string) => void;
  clearCanvasError: () => void;
}

export function useEditorCanvas(): EditorAPI {
  const fabricRef = useRef<fabric.Canvas | null>(null);
  const objectMapRef = useRef<Map<string, fabric.FabricObject>>(new Map());
  const scaleRef = useRef(1);
  const showMockRef = useRef(true);
  const showGridRef = useRef(false);
  const elementsRef = useRef<TemplateElement[]>([]);
  const bgUrlRef = useRef<string | null>(null);
  const imageSizeRef = useRef({ width: 1, height: 1 });

  const [elements, setElements] = useState<TemplateElement[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [backgroundUrl, setBackgroundUrl] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState({ width: 1, height: 1 });
  const [scale, setScale] = useState(1);
  const [showMockData, setShowMockDataState] = useState(true);
  const [showGrid, setShowGridState] = useState(false);
  const [zoom, setZoomState] = useState(1);
  const [canvasError, setCanvasError] = useState<string | null>(null);

  const reportCanvasError = useCallback((message: string, error: unknown) => {
    console.error(`[EditorCanvas] ${message}`, error);
    setCanvasError(message);
  }, []);

  useEffect(() => {
    elementsRef.current = elements;
  }, [elements]);
  useEffect(() => {
    bgUrlRef.current = backgroundUrl;
  }, [backgroundUrl]);
  useEffect(() => {
    imageSizeRef.current = imageSize;
  }, [imageSize]);
  useEffect(() => {
    scaleRef.current = scale;
  }, [scale]);

  // Initialize fabric via a *callback ref* rather than a mount-time effect.
  // React invokes this with the node when the <canvas> mounts and with null
  // when it unmounts. This is required because the canvas only renders in
  // "edit" mode — a `useEffect(…, [])` would run once while the hook is still
  // in "list" mode (no canvas yet) and never re-run, leaving fabric
  // uninitialized so uploads silently do nothing.
  const attachCanvas = useCallback((el: HTMLCanvasElement | null) => {
    if (!el) {
      const existing = fabricRef.current;
      if (existing) {
        existing.dispose();
        fabricRef.current = null;
        objectMapRef.current.clear();
      }
      return;
    }
    if (fabricRef.current) return;

    const canvas = new fabric.Canvas(el, {
      width: CANVAS_MAX_WIDTH,
      height: Math.round(CANVAS_MAX_WIDTH * 0.707),
      backgroundColor: "#d1d5db",
      selection: true,
    });
    fabricRef.current = canvas;

    const onSelect = (event: { selected?: fabric.FabricObject[] }) => {
      const selected = event.selected?.[0];
      const id = (selected as any)?.data?.elementId as string | undefined;
      if (id) setSelectedId(id);
    };
    canvas.on("selection:created", onSelect);
    canvas.on("selection:updated", onSelect);
    canvas.on("selection:cleared", () => setSelectedId(null));

    canvas.on("object:modified", (event) => {
      const object = event.target;
      const id = (object as any)?.data?.elementId as string | undefined;
      if (!object || !id) return;

      const current = elementsRef.current.find((el2) => el2.id === id);
      if (!current) return;

      const sc = Math.max(scaleRef.current, MIN_SCALE);

      if (isTextElement(current)) {
        const newX = Math.round((object.left ?? 0) / sc);
        const newY = Math.round((object.top ?? 0) / sc);
        setElements((prev) =>
          prev.map((el2) => (el2.id === id ? { ...el2, x: newX, y: newY } : el2)),
        );
        // Body Textbox: re-derive the wrap width from the new position so the
        // preview keeps matching the PDF after a drag.
        if (isBodyTextElement(current) && object instanceof fabric.Textbox) {
          const displayImgW = computeDisplayImageWidth(
            imageSizeRef.current.width, sc, fabricRef.current,
          );
          object.set(
            "width",
            bodyWrapWidthDisplay({ ...current, x: newX } as TextTemplateElement, sc, displayImgW),
          );
          fabricRef.current?.requestRenderAll();
        }
        return;
      }

      if (isImageElement(current) && object instanceof fabric.FabricImage) {
        const naturalW = object.width ?? 1;
        const naturalH = object.height ?? 1;
        const scaledWidth = (naturalW * (object.scaleX ?? 1)) / sc;
        const scaledHeight = (naturalH * (object.scaleY ?? 1)) / sc;

        setElements((prev) =>
          prev.map((el2) =>
            el2.id === id && isImageElement(el2)
              ? {
                  ...el2,
                  x: Math.round((object.left ?? 0) / sc),
                  y: Math.round((object.top ?? 0) / sc),
                  width: Math.max(1, Math.round(scaledWidth)),
                  height: Math.max(1, Math.round(scaledHeight)),
                  opacity: object.opacity ?? el2.opacity ?? 1,
                }
              : el2,
          ),
        );
      }
    });

    canvas.on("object:moving", (event) => {
      if (!showGridRef.current) return;
      const object = event.target;
      if (!object) return;

      const gridPx = 10 * Math.max(scaleRef.current, MIN_SCALE);
      object.set({
        left: Math.round((object.left ?? 0) / gridPx) * gridPx,
        top: Math.round((object.top ?? 0) / gridPx) * gridPx,
      });
    });
  }, []);

  const _addFabricTextObject = useCallback(
    (element: TextTemplateElement, sc: number, useMock: boolean) => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      const text = resolveDisplayText(element, useMock);
      let obj: fabric.FabricObject;
      if (isBodyTextElement(element)) {
        // The body wraps to a derived width (matches the PDF) — use a Textbox.
        const displayImgW = computeDisplayImageWidth(
          imageSizeRef.current.width, sc, canvas,
        );
        obj = new fabric.Textbox(
          text,
          buildFabricTextboxOptions(element, sc, bodyWrapWidthDisplay(element, sc, displayImgW)),
        );
      } else {
        obj = new fabric.IText(text, buildFabricTextOptions(element, sc));
      }
      (obj as any).data = { elementId: element.id };

      canvas.add(obj);
      objectMapRef.current.set(element.id, obj);
    },
    [],
  );

  const _addFabricImageObject = useCallback(
    async (element: ImageTemplateElement, sc: number) => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      const img = await loadFabricImage(toAbsoluteImageSource(element.src), {
        crossOrigin: "anonymous",
      });

      const naturalW = Math.max(img.width ?? 1, 1);
      const naturalH = Math.max(img.height ?? 1, 1);
      const desiredDisplayW = Math.max(element.width * sc, 1);
      const desiredDisplayH = Math.max(element.height * sc, 1);

      img.set({
        left: element.x * sc,
        top: element.y * sc,
        originX: "left",
        originY: "top",
        scaleX: Math.max(desiredDisplayW / naturalW, MIN_SCALE),
        scaleY: Math.max(desiredDisplayH / naturalH, MIN_SCALE),
        selectable: true,
        hasControls: true,
        lockRotation: true,
        lockSkewingX: true,
        lockSkewingY: true,
        hasBorders: true,
        opacity: element.opacity ?? 1,
      });
      (img as any).data = { elementId: element.id };

      canvas.add(img);
      objectMapRef.current.set(element.id, img);
    },
    [],
  );

  const _addElementObject = useCallback(
    async (element: TemplateElement, sc: number, useMock: boolean) => {
      if (isImageElement(element)) {
        await _addFabricImageObject(element, sc);
        return;
      }
      _addFabricTextObject(element, sc, useMock);
    },
    [_addFabricImageObject, _addFabricTextObject],
  );

  const _removeFabricObject = useCallback((id: string) => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    const object = objectMapRef.current.get(id);
    if (object) {
      canvas.remove(object);
      objectMapRef.current.delete(id);
    }
  }, []);

  const _applyBackground = useCallback(
    async (
      url: string,
      width: number,
      height: number,
      afterLoad?: () => void | Promise<void>,
    ) => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      const displayW = Math.min(CANVAS_MAX_WIDTH, width);
      const sc = displayW / Math.max(width, 1);
      const displayH = Math.round(height * sc);

      setCanvasError(null);

      try {
        const img = await loadFabricImage(toAbsoluteImageSource(url), {
          crossOrigin: "anonymous",
        });
        if (fabricRef.current !== canvas) return;

        canvas.setDimensions({ width: displayW, height: displayH });
        img.set({
          selectable: false,
          evented: false,
          scaleX: sc,
          scaleY: sc,
          originX: "left",
          originY: "top",
        });
        canvas.backgroundImage = img;

        scaleRef.current = sc;
        imageSizeRef.current = { width, height };
        bgUrlRef.current = url;

        setScale(sc);
        setImageSize({ width, height });
        setBackgroundUrl(url);

        await afterLoad?.();
        canvas.requestRenderAll();
      } catch (error) {
        reportCanvasError(
          "Não foi possível carregar a imagem ou os elementos no canvas.",
          error,
        );
      }
    },
    [reportCanvasError],
  );

  const setBackground = useCallback(
    (url: string, width: number, height: number) => {
      void _applyBackground(url, width, height);
    },
    [_applyBackground],
  );

  const loadTemplate = useCallback(
    (layout: TemplateLayout) => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      canvas.getObjects().forEach((obj) => canvas.remove(obj));
      objectMapRef.current.clear();
      setElements([]);
      setSelectedId(null);

      const normalizedElements = (layout.elements ?? [])
        .map((el) => normalizeTemplateElement(el))
        .filter((el): el is TemplateElement => Boolean(el));

      _applyBackground(
        layout.background,
        layout.image_width,
        layout.image_height,
        async () => {
          const sc = scaleRef.current;
          for (const el of normalizedElements) {
            await _addElementObject(el, sc, showMockRef.current);
          }
          setElements(normalizedElements);
          canvas.requestRenderAll();
        },
      );
    },
    [_addElementObject, _applyBackground],
  );

  const addTextElement = useCallback(
    (key: ElementKey = "name") => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      const sc = Math.max(scaleRef.current, MIN_SCALE);
      const id = crypto.randomUUID();
      const element: TextTemplateElement = {
        id,
        type: "text",
        key,
        label: KEY_LABELS[key] ?? key,
        x: Math.round(canvas.getWidth() / 2 / sc),
        y: Math.round(canvas.getHeight() / 2 / sc),
        fontSize: 32,
        fontFamily: "Times New Roman",
        color: "#000000",
        align: "center",
        bold: false,
        italic: false,
      };

      _addFabricTextObject(element, sc, showMockRef.current);
      const object = objectMapRef.current.get(id);
      if (object) canvas.setActiveObject(object);
      canvas.renderAll();

      setElements((prev) => [...prev, element]);
      setSelectedId(id);
    },
    [_addFabricTextObject],
  );

  const addImageElement = useCallback(
    async (file: File) => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      try {
        setCanvasError(null);
        const sc = Math.max(scaleRef.current, MIN_SCALE);
        const src = await readFileAsDataURL(file);

        const probe = await loadFabricImage(src, { crossOrigin: "anonymous" });
        const naturalW = Math.max(probe.width ?? 1, 1);
        const naturalH = Math.max(probe.height ?? 1, 1);

        const maxDisplayW = canvas.getWidth() * 0.35;
        const maxDisplayH = canvas.getHeight() * 0.35;
        const fitScale = Math.min(maxDisplayW / naturalW, maxDisplayH / naturalH, 1);
        const displayW = Math.max(naturalW * fitScale, 1);
        const displayH = Math.max(naturalH * fitScale, 1);
        const displayX = Math.max((canvas.getWidth() - displayW) / 2, 0);
        const displayY = Math.max((canvas.getHeight() - displayH) / 2, 0);

        const id = crypto.randomUUID();
        const element: ImageTemplateElement = {
          id,
          type: "image",
          key: "image",
          label: file.name || KEY_LABELS.image,
          x: Math.round(displayX / sc),
          y: Math.round(displayY / sc),
          width: Math.max(1, Math.round(displayW / sc)),
          height: Math.max(1, Math.round(displayH / sc)),
          src,
          opacity: 1,
        };

        await _addFabricImageObject(element, sc);
        const object = objectMapRef.current.get(id);
        if (object) canvas.setActiveObject(object);
        canvas.requestRenderAll();

        setElements((prev) => [...prev, element]);
        setSelectedId(id);
      } catch (error) {
        reportCanvasError("Não foi possível adicionar a imagem ao canvas.", error);
        throw error;
      }
    },
    [_addFabricImageObject, reportCanvasError],
  );

  const updateElement = useCallback(
    (id: string, changes: Partial<TemplateElement>) => {
      const canvas = fabricRef.current;
      const object = objectMapRef.current.get(id);
      const current = elementsRef.current.find((el) => el.id === id);

      if (current && object && canvas) {
        const sc = Math.max(scaleRef.current, MIN_SCALE);

        if (isTextElement(current) && object instanceof fabric.IText) {
          const textChanges: Record<string, unknown> = {};
          const merged = { ...current, ...changes } as TextTemplateElement;

          if ("x" in changes) textChanges.left = (changes.x ?? 0) * sc;
          if ("y" in changes) textChanges.top = (changes.y ?? 0) * sc;
          if ("fontSize" in changes) {
            textChanges.fontSize = Math.max((changes.fontSize ?? 8) * sc, 4);
          }
          if ("fontFamily" in changes) textChanges.fontFamily = changes.fontFamily;
          if ("color" in changes) textChanges.fill = changes.color;
          if ("align" in changes) {
            textChanges.textAlign = changes.align;
            textChanges.originX =
              changes.align === "center"
                ? "center"
                : changes.align === "right"
                  ? "right"
                  : "left";
          }
          if ("bold" in changes) {
            textChanges.fontWeight = changes.bold ? "bold" : "normal";
          }
          if ("italic" in changes) {
            textChanges.fontStyle = changes.italic ? "italic" : "normal";
          }
          if ("key" in changes || "staticText" in changes) {
            object.set("text", resolveDisplayText(merged, showMockRef.current));
          }

          object.set(textChanges);
          // Body Textbox: x or alignment changes move the page-edge the text
          // grows toward, so re-derive the wrap width to keep matching the PDF.
          if (
            isBodyTextElement(merged) &&
            object instanceof fabric.Textbox &&
            ("x" in changes || "align" in changes)
          ) {
            const displayImgW = computeDisplayImageWidth(
              imageSizeRef.current.width, sc, canvas,
            );
            object.set("width", bodyWrapWidthDisplay(merged, sc, displayImgW));
          }
          canvas.renderAll();
        }

        if (isImageElement(current) && object instanceof fabric.FabricImage) {
          const imageChanges: Record<string, unknown> = {};
          const naturalW = Math.max(object.width ?? 1, 1);
          const naturalH = Math.max(object.height ?? 1, 1);
          const merged = { ...current, ...changes } as ImageTemplateElement;

          if ("x" in changes) imageChanges.left = (changes.x ?? 0) * sc;
          if ("y" in changes) imageChanges.top = (changes.y ?? 0) * sc;
          if ("opacity" in changes) {
            imageChanges.opacity = Math.min(Math.max(merged.opacity ?? 1, 0), 1);
          }
          if ("width" in changes) {
            imageChanges.scaleX = Math.max((merged.width * sc) / naturalW, MIN_SCALE);
          }
          if ("height" in changes) {
            imageChanges.scaleY = Math.max((merged.height * sc) / naturalH, MIN_SCALE);
          }

          object.set(imageChanges);
          canvas.renderAll();
        }
      }

      setElements((prev) =>
        prev.map((el) => (el.id === id ? ({ ...el, ...changes } as TemplateElement) : el)),
      );
    },
    [],
  );

  const deleteElement = useCallback(
    (id: string) => {
      _removeFabricObject(id);
      setElements((prev) => prev.filter((el) => el.id !== id));
      setSelectedId((prev) => (prev === id ? null : prev));
      fabricRef.current?.renderAll();
    },
    [_removeFabricObject],
  );

  const duplicateElement = useCallback(
    (id: string) => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      const source = elementsRef.current.find((el) => el.id === id);
      if (!source) return;

      const newId = crypto.randomUUID();
      const duplicated: TemplateElement = {
        ...source,
        id: newId,
        x: source.x + 20,
        y: source.y + 20,
      };
      const sc = Math.max(scaleRef.current, MIN_SCALE);

      void _addElementObject(duplicated, sc, showMockRef.current).then(() => {
        const object = objectMapRef.current.get(newId);
        if (object) canvas.setActiveObject(object);
        canvas.requestRenderAll();
      }).catch((error: unknown) => {
        reportCanvasError("Não foi possível duplicar o elemento no canvas.", error);
        setElements((prev) => prev.filter((element) => element.id !== newId));
        setSelectedId((current) => (current === newId ? id : current));
      });

      setElements((prev) => [...prev, duplicated]);
      setSelectedId(newId);
    },
    [_addElementObject, reportCanvasError],
  );

  const selectElement = useCallback((id: string | null) => {
    const canvas = fabricRef.current;
    if (!canvas) return;

    if (id === null) {
      canvas.discardActiveObject();
    } else {
      const object = objectMapRef.current.get(id);
      if (object) canvas.setActiveObject(object);
    }

    canvas.renderAll();
    setSelectedId(id);
  }, []);

  const setShowMockData = useCallback((value: boolean) => {
    showMockRef.current = value;
    setShowMockDataState(value);

    const canvas = fabricRef.current;
    if (!canvas) return;

    elementsRef.current.forEach((el) => {
      if (!isTextElement(el)) return;
      const object = objectMapRef.current.get(el.id);
      if (object instanceof fabric.IText) {
        object.set("text", resolveDisplayText(el, value));
      }
    });
    canvas.renderAll();
  }, []);

  const setShowGrid = useCallback((value: boolean) => {
    showGridRef.current = value;
    setShowGridState(value);
  }, []);

  const setZoom = useCallback((value: number) => {
    setZoomState(value);
  }, []);

  const getLayout = useCallback((): TemplateLayout => {
    const sc = Math.max(scaleRef.current, MIN_SCALE);

    const synced = elementsRef.current.map((el) => {
      const object = objectMapRef.current.get(el.id);
      if (!object) return el;

      if (isTextElement(el) && object instanceof fabric.IText) {
        return {
          ...el,
          x: Math.round((object.left ?? 0) / sc),
          y: Math.round((object.top ?? 0) / sc),
          fontSize: Math.max(6, Math.round((object.fontSize ?? el.fontSize) / sc)),
        };
      }

      if (isImageElement(el) && object instanceof fabric.FabricImage) {
        const naturalW = Math.max(object.width ?? 1, 1);
        const naturalH = Math.max(object.height ?? 1, 1);
        return {
          ...el,
          x: Math.round((object.left ?? 0) / sc),
          y: Math.round((object.top ?? 0) / sc),
          width: Math.max(1, Math.round((naturalW * (object.scaleX ?? 1)) / sc)),
          height: Math.max(1, Math.round((naturalH * (object.scaleY ?? 1)) / sc)),
          opacity: object.opacity ?? el.opacity ?? 1,
        };
      }

      return el;
    });

    return {
      background: bgUrlRef.current ?? "",
      image_width: imageSizeRef.current.width,
      image_height: imageSizeRef.current.height,
      elements: synced,
    };
  }, []);

  const clearAll = useCallback(() => {
    const canvas = fabricRef.current;
    if (!canvas) return;

    canvas.getObjects().forEach((obj) => canvas.remove(obj));
    objectMapRef.current.clear();
    setElements([]);
    setSelectedId(null);
    canvas.renderAll();
  }, []);

  const exportJSON = useCallback((): string => {
    return JSON.stringify(getLayout(), null, 2);
  }, [getLayout]);

  const importJSON = useCallback(
    (json: string) => {
      try {
        const parsed = JSON.parse(json) as TemplateLayout;
        loadTemplate(parsed);
      } catch (error) {
        throw new Error("JSON inválido ou malformado.", { cause: error });
      }
    },
    [loadTemplate],
  );

  return {
    canvasRef: attachCanvas,
    elements,
    selectedId,
    backgroundUrl,
    imageSize,
    scale,
    showMockData,
    showGrid,
    zoom,
    addTextElement,
    addImageElement,
    updateElement,
    deleteElement,
    duplicateElement,
    selectElement,
    setBackground,
    loadTemplate,
    setShowMockData,
    setShowGrid,
    setZoom,
    getLayout,
    clearAll,
    exportJSON,
    importJSON,
    canvasError,
    clearCanvasError: () => setCanvasError(null),
  };
}
