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
import { computeTextLayouts, TextLayoutItemResult } from "../services/templateApi";
import { createUuid } from "../lib/uuid";
import {
  LayoutSource,
  TextBoxLayoutInfo,
  approximateLineHeight,
  fabricLineHeight,
  textLayoutKind,
  wrapsAtPageBound,
} from "../lib/textBoxLayout";
import { TEXT_BOX_MIN_SIZE, clampBoxHeight, clampBoxWidth } from "../lib/textBoxResize";
import { TemplateTextbox, applyHandleSize } from "../components/editor/TemplateTextbox";

const CANVAS_MAX_WIDTH = 900;
const MIN_SCALE = 0.01;
/** Wait for the operator to pause before asking the backend for line breaks. */
const LAYOUT_SYNC_DEBOUNCE_MS = 250;

function isTextElement(element: TemplateElement): element is TextTemplateElement {
  return element.type === "text";
}

function isImageElement(element: TemplateElement): element is ImageTemplateElement {
  return element.type === "image";
}

/** The QR element travels as text with key "qr"; it has no text box of its own. */
function isQrElement(element: TemplateElement): boolean {
  return element.type === "text" && element.key === "qr";
}

function resolveDisplayText(
  element: TextTemplateElement,
  useMock: boolean,
  sample: Record<string, string>,
): string {
  if (element.key === "static") return element.staticText ?? "";
  if (useMock) return sample[element.key] ?? `{${element.key}}`;
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

function originForAlign(align: TextTemplateElement["align"]): "left" | "center" | "right" {
  return align === "center" ? "center" : align === "right" ? "right" : "left";
}

/* Plain shape shared by IText and Textbox: both accept these properties. */
interface FabricTextOptions {
  left: number;
  top: number;
  originX: "left" | "center" | "right";
  originY: "top";
  fontSize: number;
  fontFamily: string;
  fill: string;
  textAlign: TextTemplateElement["align"];
  fontWeight: "bold" | "normal";
  fontStyle: "italic" | "normal";
  lockScalingX: boolean;
  lockScalingY: boolean;
  lockSkewingX: boolean;
  lockSkewingY: boolean;
  hasControls: boolean;
  hasBorders: boolean;
  editable: boolean;
  selectable: boolean;
  hoverCursor: string;
}

function buildFabricTextOptions(element: TextTemplateElement, scale: number): FabricTextOptions {
  return {
    left: element.x * scale,
    top: element.y * scale,
    originX: originForAlign(element.align),
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

function positiveNumber(value: unknown): number | undefined {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : undefined;
}

function normalizeTemplateElement(raw: any): TemplateElement | null {
  if (!raw || typeof raw !== "object") return null;

  if (raw.type === "image") {
    const src = String(raw.src ?? "").trim();
    if (!src) return null;

    return {
      id: String(raw.id ?? createUuid()),
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
  const width = positiveNumber(raw.width);
  const height = positiveNumber(raw.height);
  return {
    id: String(raw.id ?? createUuid()),
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
    // Optional box; kept as-is so a sized QR survives the round trip too.
    ...(width !== undefined ? { width: Math.round(width) } : {}),
    ...(height !== undefined ? { height: Math.round(height) } : {}),
    ...(raw.anchorY === "bottom" ? { anchorY: "bottom" as const } : {}),
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
  /** Where each text element's lines break, as the PDF will break them. */
  textLayouts: Record<string, TextBoxLayoutInfo>;
  /** Whether the preview currently follows the backend or a local approximation. */
  layoutSource: LayoutSource;
  /**
   * Replace the sample values behind "Dados de exemplo". The backend resolves
   * them exactly as the PDF will (institutional data included); until it
   * answers, the built-in sample is shown.
   */
  setSampleData: (values: Record<string, string>) => void;
  sampleSource: "local" | "server";
  addTextElement: (key?: ElementKey) => void;
  addImageElement: (file: File) => Promise<void>;
  updateElement: (id: string, changes: Partial<TemplateElement>) => void;
  /** Move an element by whole art pixels (keyboard nudging). */
  nudgeElement: (id: string, dx: number, dy: number) => void;
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
  const zoomRef = useRef(1);
  const elementsRef = useRef<TemplateElement[]>([]);
  const bgUrlRef = useRef<string | null>(null);
  const imageSizeRef = useRef({ width: 1, height: 1 });
  const layoutTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const layoutSeqRef = useRef(0);
  const sampleRef = useRef<Record<string, string>>({ ...MOCK_DATA });

  const [elements, setElements] = useState<TemplateElement[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [backgroundUrl, setBackgroundUrl] = useState<string | null>(null);
  const [imageSize, setImageSize] = useState({ width: 1, height: 1 });
  const [scale, setScale] = useState(1);
  const [showMockData, setShowMockDataState] = useState(true);
  const [showGrid, setShowGridState] = useState(false);
  const [zoom, setZoomState] = useState(1);
  const [canvasError, setCanvasError] = useState<string | null>(null);
  const [textLayouts, setTextLayouts] = useState<Record<string, TextBoxLayoutInfo>>({});
  const [layoutSource, setLayoutSource] = useState<LayoutSource>("pending");
  const [sampleSource, setSampleSource] = useState<"local" | "server">("local");

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

  /* Art-space page size the text boxes must respect. Before a background is
   * loaded the canvas itself stands in for the page (scale is 1 then). */
  const artPageSize = useCallback(() => {
    const canvas = fabricRef.current;
    const sc = Math.max(scaleRef.current, MIN_SCALE);
    if (imageSizeRef.current.width > 1) return imageSizeRef.current;
    return {
      width: (canvas ? canvas.getWidth() : CANVAS_MAX_WIDTH) / sc,
      height: (canvas ? canvas.getHeight() : CANVAS_MAX_WIDTH * 0.707) / sc,
    };
  }, []);

  /* ── Line breaks from the backend ────────────────────────────────────────
   * The PDF measures text with its own fonts, so only the backend knows where
   * a line really breaks. Every change that can move a break schedules one
   * request for all text elements; the answer is applied only if it is still
   * the latest, and a failure leaves the local approximation in place. */

  const localLayoutInfo = useCallback(
    (object: TemplateTextbox, element: TextTemplateElement): TextBoxLayoutInfo => {
      const sc = Math.max(scaleRef.current, MIN_SCALE);
      const lines = (object._textLines ?? []).map((line) => line.join(""));
      const kind = textLayoutKind(element.key, element.width !== undefined);
      return {
        lines,
        fontSize: element.fontSize,
        lineHeight: approximateLineHeight(element.fontFamily, element.fontSize, kind),
        textHeight: Math.round(object.naturalHeight / sc),
        wrapWidth: element.width ?? null,
        overflow:
          element.height !== undefined && object.naturalHeight > element.height * sc + 0.5,
        topOffset: Math.round(object.topOffsetDisplay / sc),
        source: "local",
      };
    },
    [],
  );

  const refreshLocalLayouts = useCallback(() => {
    const next: Record<string, TextBoxLayoutInfo> = {};
    for (const element of elementsRef.current) {
      if (!isTextElement(element) || isQrElement(element)) continue;
      const object = objectMapRef.current.get(element.id);
      if (!(object instanceof TemplateTextbox)) continue;
      next[element.id] = localLayoutInfo(object, element);
      object.overflow = next[element.id].overflow;
      object.borderColor = object.overflow ? "#dc2626" : "#2563eb";
    }
    setTextLayouts(next);
    fabricRef.current?.requestRenderAll();
  }, [localLayoutInfo]);

  const applyServerLayouts = useCallback((results: TextLayoutItemResult[]) => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    const sc = Math.max(scaleRef.current, MIN_SCALE);
    const next: Record<string, TextBoxLayoutInfo> = {};

    for (const result of results) {
      const element = elementsRef.current.find((el) => el.id === result.id);
      const object = objectMapRef.current.get(result.id);
      if (!element || !isTextElement(element) || !(object instanceof TemplateTextbox)) continue;

      const fontSizeDisplay = Math.max(result.font_size * sc, 4);
      object.serverLines = result.lines.length > 0 ? result.lines : null;
      object.fontSize = fontSizeDisplay;
      object.lineHeight = fabricLineHeight(
        result.line_height * sc,
        fontSizeDisplay,
        object._fontSizeMult,
      );
      object.topOffsetDisplay = result.top_offset * sc;
      object.top = element.y * sc - object.topOffsetDisplay;
      object.overflow = result.overflow;
      object.borderColor = result.overflow ? "#dc2626" : "#2563eb";
      object.relayout();

      next[result.id] = {
        lines: result.lines,
        fontSize: result.font_size,
        lineHeight: result.line_height,
        textHeight: result.text_height,
        wrapWidth: result.wrap_width,
        overflow: result.overflow,
        topOffset: result.top_offset,
        source: "server",
      };
    }

    setTextLayouts(next);
    canvas.requestRenderAll();
  }, []);

  const runTextLayoutSync = useCallback(async () => {
    const canvas = fabricRef.current;
    if (!canvas) return;
    const items = elementsRef.current
      .filter((el): el is TextTemplateElement => isTextElement(el) && !isQrElement(el))
      .map((el) => ({
        id: el.id,
        key: el.key,
        text: resolveDisplayText(el, showMockRef.current, sampleRef.current),
        x: Math.round(el.x),
        fontSize: Math.round(el.fontSize),
        fontFamily: el.fontFamily,
        bold: el.bold,
        align: el.align,
        ...(el.width !== undefined ? { width: Math.round(el.width) } : {}),
        ...(el.height !== undefined ? { height: Math.round(el.height) } : {}),
      }));
    const seq = ++layoutSeqRef.current;
    if (items.length === 0) {
      setTextLayouts({});
      return;
    }
    try {
      const results = await computeTextLayouts(Math.round(artPageSize().width), items);
      if (seq !== layoutSeqRef.current || fabricRef.current !== canvas) return;
      applyServerLayouts(results);
      setLayoutSource("server");
    } catch (error) {
      if (seq !== layoutSeqRef.current || fabricRef.current !== canvas) return;
      console.warn("[EditorCanvas] prévia com quebras de linha aproximadas.", error);
      setLayoutSource("local");
      refreshLocalLayouts();
    }
  }, [applyServerLayouts, artPageSize, refreshLocalLayouts]);

  const scheduleTextLayoutSync = useCallback(() => {
    if (layoutTimerRef.current) clearTimeout(layoutTimerRef.current);
    layoutTimerRef.current = setTimeout(() => {
      layoutTimerRef.current = null;
      void runTextLayoutSync();
    }, LAYOUT_SYNC_DEBOUNCE_MS);
  }, [runTextLayoutSync]);

  const cancelTextLayoutSync = useCallback(() => {
    if (layoutTimerRef.current) clearTimeout(layoutTimerRef.current);
    layoutTimerRef.current = null;
    layoutSeqRef.current += 1;
  }, []);

  // Initialize fabric via a *callback ref* rather than a mount-time effect.
  // React invokes this with the node when the <canvas> mounts and with null
  // when it unmounts. This is required because the canvas only renders in
  // "edit" mode — a `useEffect(…, [])` would run once while the hook is still
  // in "list" mode (no canvas yet) and never re-run, leaving fabric
  // uninitialized so uploads silently do nothing.
  const attachCanvas = useCallback(
    (el: HTMLCanvasElement | null) => {
      if (!el) {
        const existing = fabricRef.current;
        if (existing) {
          cancelTextLayoutSync();
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
        // Pointer Events: one code path for mouse, pen and touch, and fabric
        // keeps tracking the drag on the document once it starts.
        enablePointerEvents: true,
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

      // Fired once per drag or resize, on release — so each gesture lands in
      // the history as a single step.
      canvas.on("object:modified", (event) => {
        const object = event.target;
        const id = (object as any)?.data?.elementId as string | undefined;
        if (!object || !id) return;

        const current = elementsRef.current.find((el2) => el2.id === id);
        if (!current) return;

        const sc = Math.max(scaleRef.current, MIN_SCALE);

        if (isTextElement(current) && object instanceof TemplateTextbox) {
          const changes: Partial<TextTemplateElement> = {
            x: Math.round((object.left ?? 0) / sc),
            y: Math.round(object.elementY()),
          };
          if (object.boxWidthArt !== null) changes.width = object.boxWidthArt;
          if (object.boxHeightArt !== null) changes.height = object.boxHeightArt;
          setElements((prev) =>
            prev.map((el2) =>
              el2.id === id ? ({ ...el2, ...changes } as TemplateElement) : el2,
            ),
          );
          // Moving a bound-wrapped text changes the page edge it grows toward.
          if (object.boxWidthArt === null) object.relayout();
          scheduleTextLayoutSync();
          canvas.requestRenderAll();
          return;
        }

        if (isTextElement(current)) {
          const newX = Math.round((object.left ?? 0) / sc);
          const newY = Math.round((object.top ?? 0) / sc);
          setElements((prev) =>
            prev.map((el2) => (el2.id === id ? { ...el2, x: newX, y: newY } : el2)),
          );
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
    },
    [cancelTextLayoutSync, scheduleTextLayoutSync],
  );

  const _addFabricTextObject = useCallback(
    (element: TextTemplateElement, sc: number, useMock: boolean) => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      const text = resolveDisplayText(element, useMock, sampleRef.current);
      let obj: fabric.FabricObject;
      if (isQrElement(element)) {
        obj = new fabric.IText(text, buildFabricTextOptions(element, sc));
      } else {
        const box = new TemplateTextbox(text, {
          ...buildFabricTextOptions(element, sc),
          hasControls: true,
        });
        const page = artPageSize();
        box.elementId = element.id;
        box.artScale = sc;
        box.artImageWidth = page.width;
        box.artImageHeight = page.height;
        box.autoWidth = wrapsAtPageBound(element.key) ? "bound" : "hug";
        box.boxWidthArt = element.width ?? null;
        box.boxHeightArt = element.height ?? null;
        if (element.anchorY === "bottom") {
          // `top` already holds y·scale, which is the base for this anchor.
          box.anchorBottom = true;
          box.originY = "bottom";
        }
        const kind = textLayoutKind(element.key, element.width !== undefined);
        box.lineHeight = fabricLineHeight(
          approximateLineHeight(element.fontFamily, element.fontSize, kind) * sc,
          box.fontSize,
          box._fontSizeMult,
        );
        applyHandleSize(box, zoomRef.current);
        box.relayout();
        obj = box;
      }
      (obj as any).data = { elementId: element.id };

      canvas.add(obj);
      objectMapRef.current.set(element.id, obj);
    },
    [artPageSize],
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
      applyHandleSize(img, zoomRef.current);
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

        // Text boxes already on the canvas now live on a different page.
        objectMapRef.current.forEach((object) => {
          if (object instanceof TemplateTextbox) {
            object.artScale = sc;
            object.artImageWidth = width;
            object.artImageHeight = height;
            object.relayout();
          }
        });

        await afterLoad?.();
        scheduleTextLayoutSync();
        canvas.requestRenderAll();
      } catch (error) {
        reportCanvasError(
          "Não foi possível carregar a imagem ou os elementos no canvas.",
          error,
        );
      }
    },
    [reportCanvasError, scheduleTextLayoutSync],
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

      cancelTextLayoutSync();
      canvas.getObjects().forEach((obj) => canvas.remove(obj));
      objectMapRef.current.clear();
      setElements([]);
      setSelectedId(null);
      setTextLayouts({});

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
          elementsRef.current = normalizedElements;
          setElements(normalizedElements);
          canvas.requestRenderAll();
        },
      );
    },
    [_addElementObject, _applyBackground, cancelTextLayoutSync],
  );

  const addTextElement = useCallback(
    (key: ElementKey = "name") => {
      const canvas = fabricRef.current;
      if (!canvas) return;

      const sc = Math.max(scaleRef.current, MIN_SCALE);
      const id = createUuid();
      // The authors block keeps its base fixed and grows upward, so it never
      // creeps down toward the QR code as authors are added.
      const authorsBlock = key === "authors";
      const element: TextTemplateElement = {
        id,
        type: "text",
        key,
        label: KEY_LABELS[key] ?? key,
        x: Math.round(canvas.getWidth() / 2 / sc),
        y: Math.round(canvas.getHeight() / 2 / sc),
        fontSize: authorsBlock ? 20 : 32,
        fontFamily: "Times New Roman",
        color: "#000000",
        align: authorsBlock ? "left" : "center",
        bold: false,
        italic: false,
        ...(authorsBlock ? { anchorY: "bottom" as const } : {}),
      };

      _addFabricTextObject(element, sc, showMockRef.current);
      const object = objectMapRef.current.get(id);
      if (object) canvas.setActiveObject(object);
      canvas.renderAll();

      setElements((prev) => [...prev, element]);
      setSelectedId(id);
      scheduleTextLayoutSync();
    },
    [_addFabricTextObject, scheduleTextLayoutSync],
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

        const id = createUuid();
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
      let applied = changes;

      if (current && object && canvas) {
        const sc = Math.max(scaleRef.current, MIN_SCALE);

        if (isTextElement(current) && object instanceof TemplateTextbox) {
          const textChanges = changes as Partial<TextTemplateElement>;
          const merged = { ...current, ...textChanges } as TextTemplateElement;
          const page = artPageSize();
          const next: Partial<TextTemplateElement> = { ...textChanges };

          if ("width" in textChanges) {
            const width =
              merged.width === undefined
                ? undefined
                : clampBoxWidth(merged.width, merged.x, merged.align, page.width);
            if (width !== undefined && current.width === undefined) {
              // First explicit width on a centred name: keep the first line
              // where it is on screen instead of letting the box jump down.
              const topOffset = Math.round(object.topOffsetDisplay / sc);
              if (topOffset > 0) next.y = merged.y - topOffset;
              object.topOffsetDisplay = 0;
            }
            next.width = width;
            object.boxWidthArt = width ?? null;
          }
          if ("height" in textChanges) {
            const height =
              merged.height === undefined
                ? undefined
                : clampBoxHeight(merged.height, next.y ?? merged.y, page.height);
            next.height = height;
            object.boxHeightArt = height ?? null;
          }
          if ("anchorY" in textChanges) {
            // Re-anchor without moving the box; Y then names the other edge.
            object.setAnchorBottom(textChanges.anchorY === "bottom");
            next.anchorY = textChanges.anchorY === "bottom" ? "bottom" : undefined;
            next.y = Math.round(object.elementY());
          }
          const final = { ...current, ...next } as TextTemplateElement;

          const props: Record<string, unknown> = {};
          if ("x" in next) props.left = final.x * sc;
          if ("y" in next) props.top = final.y * sc - object.topOffsetDisplay;
          if ("fontSize" in next) props.fontSize = Math.max(final.fontSize * sc, 4);
          if ("fontFamily" in next) props.fontFamily = final.fontFamily;
          if ("color" in next) props.fill = final.color;
          if ("align" in next) {
            props.textAlign = final.align;
            props.originX = originForAlign(final.align);
          }
          if ("bold" in next) props.fontWeight = final.bold ? "bold" : "normal";
          if ("italic" in next) props.fontStyle = final.italic ? "italic" : "normal";
          if ("key" in next || "staticText" in next) {
            props.text = resolveDisplayText(final, showMockRef.current, sampleRef.current);
            object.autoWidth = wrapsAtPageBound(final.key) ? "bound" : "hug";
          }

          // Anything that can move a line break: wrap locally until the
          // backend answers, with the line pitch the PDF would use.
          object.serverLines = null;
          if ("fontSize" in next || "fontFamily" in next || "width" in next || "key" in next) {
            const kind = textLayoutKind(final.key, final.width !== undefined);
            props.lineHeight = fabricLineHeight(
              approximateLineHeight(final.fontFamily, final.fontSize, kind) * sc,
              Math.max(final.fontSize * sc, 4),
              object._fontSizeMult,
            );
          }
          object.set(props);
          object.relayout();
          canvas.renderAll();
          scheduleTextLayoutSync();
          applied = next as Partial<TemplateElement>;
        } else if (isTextElement(current) && object instanceof fabric.IText) {
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
            textChanges.originX = originForAlign(merged.align);
          }
          if ("bold" in changes) {
            textChanges.fontWeight = changes.bold ? "bold" : "normal";
          }
          if ("italic" in changes) {
            textChanges.fontStyle = changes.italic ? "italic" : "normal";
          }
          if ("key" in changes || "staticText" in changes) {
            object.set("text", resolveDisplayText(merged, showMockRef.current, sampleRef.current));
          }

          object.set(textChanges);
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
        prev.map((el) => (el.id === id ? ({ ...el, ...applied } as TemplateElement) : el)),
      );
    },
    [artPageSize, scheduleTextLayoutSync],
  );

  const nudgeElement = useCallback(
    (id: string, dx: number, dy: number) => {
      const current = elementsRef.current.find((el) => el.id === id);
      if (!current) return;
      updateElement(id, { x: Math.round(current.x + dx), y: Math.round(current.y + dy) });
    },
    [updateElement],
  );

  const deleteElement = useCallback(
    (id: string) => {
      _removeFabricObject(id);
      setElements((prev) => prev.filter((el) => el.id !== id));
      setSelectedId((prev) => (prev === id ? null : prev));
      setTextLayouts((prev) => {
        if (!(id in prev)) return prev;
        const { [id]: _removed, ...rest } = prev;
        return rest;
      });
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

      const newId = createUuid();
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
        if (isTextElement(duplicated)) scheduleTextLayoutSync();
      }).catch((error: unknown) => {
        reportCanvasError("Não foi possível duplicar o elemento no canvas.", error);
        setElements((prev) => prev.filter((element) => element.id !== newId));
        setSelectedId((current) => (current === newId ? id : current));
      });

      setElements((prev) => [...prev, duplicated]);
      setSelectedId(newId);
    },
    [_addElementObject, reportCanvasError, scheduleTextLayoutSync],
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

  const setShowMockData = useCallback(
    (value: boolean) => {
      showMockRef.current = value;
      setShowMockDataState(value);

      const canvas = fabricRef.current;
      if (!canvas) return;

      elementsRef.current.forEach((el) => {
        if (!isTextElement(el)) return;
        const object = objectMapRef.current.get(el.id);
        if (object instanceof TemplateTextbox) {
          object.serverLines = null;
          object.set("text", resolveDisplayText(el, value, sampleRef.current));
          object.relayout();
        } else if (object instanceof fabric.IText) {
          object.set("text", resolveDisplayText(el, value, sampleRef.current));
        }
      });
      canvas.renderAll();
      scheduleTextLayoutSync();
    },
    [scheduleTextLayoutSync],
  );

  const setSampleData = useCallback(
    (values: Record<string, string>) => {
      sampleRef.current = { ...MOCK_DATA, ...values };
      setSampleSource("server");

      const canvas = fabricRef.current;
      if (!canvas || !showMockRef.current) return;
      elementsRef.current.forEach((el) => {
        if (!isTextElement(el) || el.key === "static") return;
        const object = objectMapRef.current.get(el.id);
        const text = resolveDisplayText(el, true, sampleRef.current);
        if (object instanceof TemplateTextbox) {
          if (object.text === text) return;
          object.serverLines = null;
          object.set("text", text);
          object.relayout();
        } else if (object instanceof fabric.IText) {
          object.set("text", text);
        }
      });
      canvas.renderAll();
      scheduleTextLayoutSync();
    },
    [scheduleTextLayoutSync],
  );

  const setShowGrid = useCallback((value: boolean) => {
    showGridRef.current = value;
    setShowGridState(value);
  }, []);

  const setZoom = useCallback((value: number) => {
    zoomRef.current = value;
    setZoomState(value);
    // The page is zoomed with CSS, so handles must shrink to stay the same
    // size on screen.
    objectMapRef.current.forEach((object) => applyHandleSize(object, value));
    fabricRef.current?.requestRenderAll();
  }, []);

  const getLayout = useCallback((): TemplateLayout => {
    const sc = Math.max(scaleRef.current, MIN_SCALE);

    const synced = elementsRef.current.map((el) => {
      const object = objectMapRef.current.get(el.id);
      if (!object) return el;

      if (isTextElement(el) && object instanceof TemplateTextbox) {
        return {
          ...el,
          x: Math.round((object.left ?? 0) / sc),
          y: Math.round(object.elementY()),
        };
      }

      if (isTextElement(el) && object instanceof fabric.IText) {
        return {
          ...el,
          x: Math.round((object.left ?? 0) / sc),
          y: Math.round((object.top ?? 0) / sc),
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

    cancelTextLayoutSync();
    canvas.getObjects().forEach((obj) => canvas.remove(obj));
    objectMapRef.current.clear();
    setElements([]);
    setSelectedId(null);
    setTextLayouts({});
    canvas.renderAll();
  }, [cancelTextLayoutSync]);

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
    textLayouts,
    layoutSource,
    setSampleData,
    sampleSource,
    addTextElement,
    addImageElement,
    updateElement,
    nudgeElement,
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

export { TEXT_BOX_MIN_SIZE };
