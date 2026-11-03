/**
 * How large the certificate is drawn in the editor.
 *
 * The page is always shown whole, at the largest scale that fits the stage
 * minus a small margin, so its edge stays visible against the grey ground.
 * There is no zoom control: the scale follows the stage, which changes with
 * the window, the side panels and the art itself. Everything here is in CSS
 * pixels; the conversion to pixels of the art is the canvas hook's job.
 */

export interface Size {
  width: number;
  height: number;
}

export interface FitResult extends Size {
  /** Display px per content px; 0 when nothing can be shown yet. */
  scale: number;
}

/** Grey margin kept around the page, on every side. */
export const STAGE_MARGIN_PX = 8;

/**
 * Largest scale at which `content` fits inside `area` with the margin.
 * Returns 0 when either size is unknown (not measured yet) or too small.
 */
export function fitScale(content: Size, area: Size, margin = STAGE_MARGIN_PX): number {
  const availableWidth = area.width - 2 * margin;
  const availableHeight = area.height - 2 * margin;
  if (!(content.width > 0) || !(content.height > 0)) return 0;
  if (!(availableWidth > 0) || !(availableHeight > 0)) return 0;
  return Math.min(availableWidth / content.width, availableHeight / content.height);
}

/** Whole-pixel size the canvas element needs for `content` to fit `area`. */
export function fitSize(content: Size, area: Size, margin = STAGE_MARGIN_PX): FitResult {
  const raw = fitScale(content, area, margin);
  if (raw <= 0) return { width: 0, height: 0, scale: 0 };
  // Whole pixels, so the drawn page never bleeds past its element by a
  // fraction. The epsilon absorbs float noise (1600 × 0,5125 is 819,999…).
  const width = Math.max(1, Math.floor(content.width * raw + 1e-6));
  const scale = width / content.width;
  return { width, height: Math.max(1, Math.round(content.height * scale)), scale };
}
