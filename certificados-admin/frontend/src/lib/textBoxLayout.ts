/**
 * How a text element lays out, as the PDF renderer decides it.
 *
 * The exact line breaks come from the backend (`computeTextLayouts`), which
 * measures with the fonts the PDF uses. While that answer is pending, or if
 * it fails, the canvas wraps locally; the numbers here keep that local preview
 * close to the PDF so a box does not look taller or shorter than it will be.
 */

export type TextLayoutKind = "name" | "block" | "single";

export interface TextBoxLayoutInfo {
  lines: string[];
  /** Effective font size in art pixels (the name shrinks to fit). */
  fontSize: number;
  /** Distance between the tops of two consecutive lines, art pixels. */
  lineHeight: number;
  /** Height the text occupies, art pixels. */
  textHeight: number;
  wrapWidth: number | null;
  overflow: boolean;
  /** Legacy name centring: the first line starts at `y - topOffset`. */
  topOffset: number;
  source: "server" | "local";
}

export type LayoutSource = "pending" | "server" | "local";

export const BODY_TEXT_KEYS = new Set<string>(["texto_certificado", "certificate_text"]);

/** Body and name wrap at the page bound even without an explicit width. */
export function wrapsAtPageBound(key: string): boolean {
  return key === "name" || BODY_TEXT_KEYS.has(key);
}

export function textLayoutKind(key: string, hasWidth: boolean): TextLayoutKind {
  if (key === "name") return "name";
  if (BODY_TEXT_KEYS.has(key) || hasWidth) return "block";
  return "single";
}

/* Ink height of "Ag" over the font size, measured with Pillow on the fonts
 * shipped with the backend. Every other family falls back to Times there. */
const GLYPH_HEIGHT_RATIO: Record<string, number> = {
  "Times New Roman": 0.89,
  Arial: 0.93,
};
/* Bottom of "A" over the font size: the pitch Pillow uses for typed breaks. */
const CAP_HEIGHT_RATIO = 0.9;

/** Line pitch in art pixels, following the renderer's formulas. */
export function approximateLineHeight(
  fontFamily: string,
  fontSize: number,
  kind: TextLayoutKind,
): number {
  if (kind === "single") return Math.round(fontSize * CAP_HEIGHT_RATIO) + 4;
  const ratio = GLYPH_HEIGHT_RATIO[fontFamily] ?? GLYPH_HEIGHT_RATIO["Times New Roman"];
  const glyph = Math.round(fontSize * ratio);
  const spacing = Math.max(Math.floor(fontSize * (kind === "name" ? 0.12 : 0.3)), 2);
  return glyph + spacing;
}

/**
 * Fabric's `lineHeight` is a multiplier over `fontSize × _fontSizeMult`;
 * this converts an absolute pitch (display px) into that multiplier.
 */
export function fabricLineHeight(
  pitchDisplay: number,
  fontSizeDisplay: number,
  fontSizeMult: number,
): number {
  return pitchDisplay / Math.max(fontSizeDisplay * fontSizeMult, 1e-6);
}
