import { describe, expect, test } from "vitest";
import { STAGE_MARGIN_PX, fitScale, fitSize } from "./canvasFit";

const LANDSCAPE = { width: 1600, height: 1131 };
const PORTRAIT = { width: 1131, height: 1600 };

describe("fitScale", () => {
  test("uma arte paisagem numa área mais larga é limitada pela altura", () => {
    // 820 × 585 úteis: 585 / 1131 ≈ 0,517 é menor que 820 / 1600 = 0,5125.
    expect(fitScale(LANDSCAPE, { width: 836, height: 601 })).toBeCloseTo(0.5125, 4);
  });

  test("a mesma arte numa área alta e estreita é limitada pela largura", () => {
    expect(fitScale(LANDSCAPE, { width: 416, height: 900 })).toBeCloseTo(400 / 1600, 6);
  });

  test("uma arte retrato na área do notebook é limitada pela altura", () => {
    expect(fitScale(PORTRAIT, { width: 836, height: 601 })).toBeCloseTo(585 / 1600, 6);
  });

  test("área pequena: a escala cai abaixo de 10% em vez de cortar a arte", () => {
    const scale = fitScale(LANDSCAPE, { width: 160, height: 120 });
    expect(scale).toBeCloseTo(144 / 1600, 6);
    expect(scale * LANDSCAPE.height).toBeLessThanOrEqual(120 - 2 * STAGE_MARGIN_PX);
  });

  test("área grande: a escala passa de 100% quando a arte é menor que a área", () => {
    expect(fitScale({ width: 800, height: 600 }, { width: 1920, height: 1080 })).toBeCloseTo(
      1064 / 600,
      6,
    );
  });

  test("sem medida ainda, ou área menor que a margem, não há escala", () => {
    expect(fitScale(LANDSCAPE, { width: 0, height: 0 })).toBe(0);
    expect(fitScale(LANDSCAPE, { width: 16, height: 300 })).toBe(0);
    expect(fitScale({ width: 0, height: 0 }, { width: 800, height: 600 })).toBe(0);
  });

  test("a margem é descontada dos dois lados", () => {
    expect(fitScale({ width: 100, height: 100 }, { width: 140, height: 140 }, 20)).toBe(1);
  });
});

describe("fitSize", () => {
  test("arredonda para pixels inteiros e nunca ultrapassa a área útil", () => {
    const fit = fitSize(LANDSCAPE, { width: 836, height: 601 });
    expect(fit.width).toBe(820);
    expect(fit.height).toBe(580);
    expect(fit.scale).toBeCloseTo(0.5125, 4);
    expect(fit.width).toBeLessThanOrEqual(836 - 2 * STAGE_MARGIN_PX);
    expect(fit.height).toBeLessThanOrEqual(601 - 2 * STAGE_MARGIN_PX);
  });

  test("mantém a proporção da arte em qualquer área", () => {
    for (const area of [
      { width: 1456, height: 1031 },
      { width: 300, height: 1000 },
      { width: 1000, height: 300 },
    ]) {
      const fit = fitSize(PORTRAIT, area);
      expect(fit.width / fit.height).toBeCloseTo(PORTRAIT.width / PORTRAIT.height, 2);
    }
  });

  test("devolve zero enquanto a área não foi medida", () => {
    expect(fitSize(LANDSCAPE, { width: 0, height: 0 })).toEqual({ width: 0, height: 0, scale: 0 });
  });
});
