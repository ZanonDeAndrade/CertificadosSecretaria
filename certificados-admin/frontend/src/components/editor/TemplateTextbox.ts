/**
 * Text element on the editor canvas.
 *
 * A Fabric Textbox whose line breaks come from the backend whenever possible
 * (`serverLines`), so the preview wraps where the PDF will. Width and height
 * are the element's box in pixels of the original art; the eight handles
 * resize that box instead of scaling the glyphs, which is what the renderer
 * expects. X stays the alignment anchor (left edge, centre or right edge),
 * exactly as the PDF reads it.
 */
import * as fabric from "fabric";
import {
  AnchorY,
  BoxRect,
  ResizeHandle,
  TEXT_BOX_MIN_SIZE,
  anchorFromRect,
  displayDeltaToArt,
  maxBoxWidth,
  rectFromAnchor,
  resizeBox,
  textBoxArea,
} from "../../lib/textBoxResize";
import { TextAlign } from "../../types/template";

/** Handle size on screen, whatever the zoom. */
export const HANDLE_SIZE_PX = 10;
export const TOUCH_HANDLE_SIZE_PX = 24;
export const SELECTION_COLOR = "#2563eb";
export const OVERFLOW_COLOR = "#dc2626";

/** How the box width is decided when the element has no explicit width. */
export type AutoWidth = "bound" | "hug";

export class TemplateTextbox extends fabric.Textbox {
  elementId = "";
  /** Display px per art px of the canvas this object lives on. */
  artScale = 1;
  artImageWidth = 1;
  artImageHeight = 1;
  /** Explicit box, art px. `null` keeps the historical behaviour. */
  boxWidthArt: number | null = null;
  boxHeightArt: number | null = null;
  autoWidth: AutoWidth = "hug";
  /** Lines as the PDF breaks them; `null` wraps locally (while dragging, or offline). */
  serverLines: string[] | null = null;
  /** Legacy name centring, display px: the box top sits at `y·scale − topOffset`. */
  topOffsetDisplay = 0;
  /**
   * Y is the base of the box: fabric's `originY` is "bottom", so `top` holds
   * the bottom edge and the box grows upward as lines are added.
   */
  anchorBottom = false;
  overflow = false;
  /** Height the laid-out text needs, display px, before the box height applies. */
  naturalHeight = 0;

  constructor(text: string, options: Partial<fabric.Textbox>) {
    super(text, {
      ...options,
      // Overflowing lines are drawn past the box; a cache canvas would clip them.
      objectCaching: false,
      hasControls: true,
      hasBorders: true,
      transparentCorners: false,
      cornerStyle: "rect",
      cornerColor: "#ffffff",
      cornerStrokeColor: SELECTION_COLOR,
      borderColor: SELECTION_COLOR,
      lockScalingX: true,
      lockScalingY: true,
      lockRotation: true,
      lockSkewingX: true,
      lockSkewingY: true,
    });
    this.editable = false;
    this.controls = createTextBoxControls();
  }

  _wrapText(lines: string[], desiredWidth: number): string[][] {
    if (this.serverLines && this.serverLines.length > 0) {
      return this.serverLines.map((line) => this.graphemeSplit(line));
    }
    if (this.boxWidthArt === null && this.autoWidth === "hug") {
      // Single-line fields are never wrapped by the PDF: only typed breaks.
      return lines.map((line) => this.graphemeSplit(line));
    }
    return super._wrapText(lines, desiredWidth);
  }

  initDimensions(): void {
    super.initDimensions();
    if (!this.initialized) return;
    if (this.boxWidthArt === null && this.autoWidth === "hug") {
      this.width = Math.max(this.calcTextWidth(), 1);
    }
  }

  calcTextHeight(): number {
    this.naturalHeight = super.calcTextHeight();
    if (this.boxHeightArt === null || this.boxHeightArt === undefined) return this.naturalHeight;
    return Math.max(this.boxHeightArt * this.artScale, 1);
  }

  _render(ctx: CanvasRenderingContext2D): void {
    super._render(ctx);
    if (!this.overflow) return;
    ctx.save();
    ctx.strokeStyle = OVERFLOW_COLOR;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.strokeRect(-this.width / 2, -this.height / 2, this.width, this.height);
    ctx.restore();
  }

  align(): TextAlign {
    return this.textAlign === "center" || this.textAlign === "right" ? this.textAlign : "left";
  }

  anchorY(): AnchorY {
    return this.anchorBottom ? "bottom" : "top";
  }

  /** The visual box in art px; `top` is where the first line starts. */
  artRect(): BoxRect {
    const sc = this.artScale;
    return rectFromAnchor(
      this.left / sc,
      this.top / sc,
      this.width / sc,
      this.height / sc,
      this.align(),
      this.anchorY(),
    );
  }

  /**
   * The element's Y as the PDF reads it: above the box for a legacy centred
   * name, the base of the box for a bottom-anchored one.
   */
  elementY(): number {
    return (this.top + this.topOffsetDisplay) / this.artScale;
  }

  /** Switch the anchored edge without moving the box on screen. */
  setAnchorBottom(bottom: boolean): void {
    if (bottom === this.anchorBottom) return;
    const rect = this.artRect();
    this.anchorBottom = bottom;
    this.originY = bottom ? "bottom" : "top";
    if (bottom) this.topOffsetDisplay = 0;
    this.top = (bottom ? rect.top + rect.height : rect.top) * this.artScale;
    this.setCoords();
  }

  /** Lay the text out again: explicit width, the page bound, or hugging the text. */
  relayout(): void {
    const sc = this.artScale;
    if (this.boxWidthArt !== null) {
      this.width = Math.max(this.boxWidthArt * sc, 1);
    } else if (this.autoWidth === "bound") {
      const bound = maxBoxWidth(this.left / sc, this.align(), this.artImageWidth) * sc;
      this.width = Math.max(bound, 1);
    }
    this.initDimensions();
    this.setCoords();
  }

  /**
   * Apply a box dragged by a handle. Only the edges that handle controls
   * changed, so the opposite edges stay put. Setting a width on a name for
   * the first time keeps its first line where it is on screen.
   */
  applyResize(rect: BoxRect, handle: ResizeHandle): boolean {
    const sc = this.artScale;
    if (handle.includes("l") || handle.includes("r")) {
      if (this.boxWidthArt === null) this.topOffsetDisplay = 0;
      this.boxWidthArt = rect.width;
    }
    if (handle.includes("t") || handle.includes("b")) this.boxHeightArt = rect.height;
    // Wrap locally while dragging; the backend answer follows the drop.
    this.serverLines = null;
    const anchor = anchorFromRect(rect, this.align(), this.anchorY());
    this.left = anchor.x * sc;
    this.top = (this.anchorBottom ? rect.top + rect.height : rect.top) * sc;
    this.relayout();
    return true;
  }
}

/** Keep handles the same size on screen whatever the zoom. */
export function applyHandleSize(object: fabric.FabricObject, zoom: number): void {
  const factor = Math.max(zoom, 0.05);
  object.set({
    cornerSize: HANDLE_SIZE_PX / factor,
    touchCornerSize: TOUCH_HANDLE_SIZE_PX / factor,
  });
  object.setCoords();
}

const HANDLES: Record<ResizeHandle, { x: number; y: number; cursor: string }> = {
  tl: { x: -0.5, y: -0.5, cursor: "nwse-resize" },
  tr: { x: 0.5, y: -0.5, cursor: "nesw-resize" },
  bl: { x: -0.5, y: 0.5, cursor: "nesw-resize" },
  br: { x: 0.5, y: 0.5, cursor: "nwse-resize" },
  ml: { x: -0.5, y: 0, cursor: "ew-resize" },
  mr: { x: 0.5, y: 0, cursor: "ew-resize" },
  mt: { x: 0, y: -0.5, cursor: "ns-resize" },
  mb: { x: 0, y: 0.5, cursor: "ns-resize" },
};

function sameRect(a: BoxRect, b: BoxRect): boolean {
  return (
    Math.abs(a.left - b.left) < 0.5 &&
    Math.abs(a.top - b.top) < 0.5 &&
    Math.abs(a.width - b.width) < 0.5 &&
    Math.abs(a.height - b.height) < 0.5
  );
}

function resizeActionHandler(handle: ResizeHandle): fabric.TransformActionHandler {
  return (_event, transform, x, y) => {
    const target = transform.target;
    if (!(target instanceof TemplateTextbox)) return false;
    const sc = target.artScale;
    // `transform` holds the geometry at the start of the drag, so each move is
    // computed from the same origin and never accumulates rounding.
    const start = rectFromAnchor(
      transform.original.left / sc,
      transform.original.top / sc,
      transform.width / sc,
      transform.height / sc,
      target.align(),
      target.anchorY(),
    );
    const next = resizeBox(
      start,
      handle,
      displayDeltaToArt(x - transform.ex, sc),
      displayDeltaToArt(y - transform.ey, sc),
      {
        minSize: TEXT_BOX_MIN_SIZE,
        area: textBoxArea(target.artImageWidth, target.artImageHeight),
      },
    );
    if (sameRect(target.artRect(), next)) return false;
    return target.applyResize(next, handle);
  };
}

export function createTextBoxControls(): Record<string, fabric.Control> {
  const controls: Record<string, fabric.Control> = {};
  for (const handle of Object.keys(HANDLES) as ResizeHandle[]) {
    const spec = HANDLES[handle];
    controls[handle] = new fabric.Control({
      x: spec.x,
      y: spec.y,
      cursorStyle: spec.cursor,
      actionName: "resizing",
      actionHandler: resizeActionHandler(handle),
    });
  }
  return controls;
}
