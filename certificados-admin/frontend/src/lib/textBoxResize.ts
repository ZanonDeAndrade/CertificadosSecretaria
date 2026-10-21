/**
 * Geometry of resizing a text box in the template editor.
 *
 * Everything here is in pixels of the original art, which is what the layout
 * stores. The canvas converts the pointer movement from display pixels first
 * (`displayDeltaToArt`), so the same rules hold at every zoom level. The
 * horizontal limits mirror the PDF renderer, which never wraps text past a 4%
 * margin on either side of the page.
 */
import { TextAlign } from "../types/template";

export type ResizeHandle = "tl" | "tr" | "bl" | "br" | "ml" | "mr" | "mt" | "mb";

export interface BoxRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface ResizeLimits {
  minSize: number;
  /** Area the box may occupy. */
  area: BoxRect;
}

export const TEXT_BOX_MIN_SIZE = 20;

/** Side margin the PDF keeps (same formula as the backend's wrap bound). */
export function pageMargin(imageWidth: number): number {
  return Math.max(Math.floor(imageWidth * 0.04), 8);
}

/** Where a text box may sit: inside the side margins, anywhere vertically. */
export function textBoxArea(imageWidth: number, imageHeight: number): BoxRect {
  const margin = pageMargin(imageWidth);
  return {
    left: margin,
    top: 0,
    width: Math.max(imageWidth - 2 * margin, 1),
    height: Math.max(imageHeight, 1),
  };
}

/**
 * Widest line the PDF will draw for an anchor and alignment: the text grows
 * toward the page edge implied by its alignment and stops at the margin.
 */
export function maxBoxWidth(anchorX: number, align: TextAlign, imageWidth: number): number {
  const margin = pageMargin(imageWidth);
  if (align === "center") {
    return Math.max(2 * (Math.min(anchorX, imageWidth - anchorX) - margin), 1);
  }
  if (align === "right") return Math.max(anchorX - margin, 1);
  return Math.max(imageWidth - anchorX - margin, 1);
}

export function displayDeltaToArt(delta: number, scale: number): number {
  return delta / Math.max(scale, 1e-6);
}

export type AnchorY = "top" | "bottom";

/**
 * X/Y are the alignment anchor, as the PDF reads them, not a box corner. With
 * `anchorY: "bottom"` Y is the base of the box, which then grows upward.
 */
export function rectFromAnchor(
  x: number,
  y: number,
  width: number,
  height: number,
  align: TextAlign,
  anchorY: AnchorY = "top",
): BoxRect {
  const left = align === "center" ? x - width / 2 : align === "right" ? x - width : x;
  const top = anchorY === "bottom" ? y - height : y;
  return { left, top, width, height };
}

export function anchorFromRect(
  rect: BoxRect,
  align: TextAlign,
  anchorY: AnchorY = "top",
): { x: number; y: number } {
  const x =
    align === "center"
      ? rect.left + rect.width / 2
      : align === "right"
        ? rect.left + rect.width
        : rect.left;
  const y = anchorY === "bottom" ? rect.top + rect.height : rect.top;
  return { x: Math.round(x), y: Math.round(y) };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * Move the edges a handle controls by the pointer delta. The opposite edges
 * never move, so pulling the top or left handle shifts the box origin.
 *
 * A box that already lies outside the allowed area is not pushed back in —
 * it only cannot grow further out.
 */
export function resizeBox(
  start: BoxRect,
  handle: ResizeHandle,
  dx: number,
  dy: number,
  limits: ResizeLimits,
): BoxRect {
  const minSize = Math.max(limits.minSize, 1);
  const startRight = start.left + start.width;
  const startBottom = start.top + start.height;
  const areaLeft = Math.min(limits.area.left, start.left);
  const areaTop = Math.min(limits.area.top, start.top);
  const areaRight = Math.max(limits.area.left + limits.area.width, startRight);
  const areaBottom = Math.max(limits.area.top + limits.area.height, startBottom);

  let left = start.left;
  let right = startRight;
  let top = start.top;
  let bottom = startBottom;

  if (handle.includes("l")) left = clamp(start.left + dx, areaLeft, right - minSize);
  if (handle.includes("r")) right = clamp(startRight + dx, left + minSize, areaRight);
  if (handle.includes("t")) top = clamp(start.top + dy, areaTop, bottom - minSize);
  if (handle.includes("b")) bottom = clamp(startBottom + dy, top + minSize, areaBottom);

  return {
    left: Math.round(left),
    top: Math.round(top),
    width: Math.round(right - left),
    height: Math.round(bottom - top),
  };
}

/** Typed width for the properties panel: at least the minimum, at most the PDF bound. */
export function clampBoxWidth(
  width: number,
  anchorX: number,
  align: TextAlign,
  imageWidth: number,
): number {
  const max = Math.max(maxBoxWidth(anchorX, align, imageWidth), TEXT_BOX_MIN_SIZE);
  return Math.round(clamp(width, TEXT_BOX_MIN_SIZE, max));
}

/** Typed height for the properties panel: stays inside the art. */
export function clampBoxHeight(height: number, top: number, imageHeight: number): number {
  const max = Math.max(imageHeight - top, TEXT_BOX_MIN_SIZE);
  return Math.round(clamp(height, TEXT_BOX_MIN_SIZE, max));
}
