import { describe, expect, test } from "vitest";
import {
  TEXT_BOX_MIN_SIZE,
  anchorFromRect,
  clampBoxHeight,
  clampBoxWidth,
  displayDeltaToArt,
  maxBoxWidth,
  pageMargin,
  rectFromAnchor,
  resizeBox,
  textBoxArea,
} from "./textBoxResize";

const IMAGE_W = 1414;
const IMAGE_H = 1000;
const limits = { minSize: TEXT_BOX_MIN_SIZE, area: textBoxArea(IMAGE_W, IMAGE_H) };
const start = { left: 300, top: 200, width: 400, height: 100 };

describe("conversão pelo zoom", () => {
  test("um deslocamento na tela vira pixels da arte dividindo pela escala", () => {
    // A arte de 1414 px é mostrada com 900 px (escala ≈ 0,6365).
    expect(displayDeltaToArt(63.65, 900 / IMAGE_W)).toBeCloseTo(100, 1);
    expect(displayDeltaToArt(-30, 0.5)).toBe(-60);
  });

  test("não divide por zero quando a escala ainda não foi calculada", () => {
    expect(Number.isFinite(displayDeltaToArt(10, 0))).toBe(true);
  });
});

describe("alças laterais mudam uma dimensão só", () => {
  test("direita: só a largura muda e a borda esquerda fica parada", () => {
    expect(resizeBox(start, "mr", 50, 999, limits)).toEqual({
      left: 300,
      top: 200,
      width: 450,
      height: 100,
    });
  });

  test("esquerda: X se ajusta para a borda direita ficar parada", () => {
    const next = resizeBox(start, "ml", -20, 0, limits);
    expect(next).toEqual({ left: 280, top: 200, width: 420, height: 100 });
    expect(next.left + next.width).toBe(start.left + start.width);
  });

  test("cima: Y se ajusta para a borda de baixo ficar parada", () => {
    const next = resizeBox(start, "mt", 999, 30, limits);
    expect(next).toEqual({ left: 300, top: 230, width: 400, height: 70 });
    expect(next.top + next.height).toBe(start.top + start.height);
  });

  test("baixo: só a altura muda", () => {
    expect(resizeBox(start, "mb", 0, 25, limits)).toEqual({
      left: 300,
      top: 200,
      width: 400,
      height: 125,
    });
  });
});

describe("cantos movem X e Y", () => {
  test("canto superior esquerdo mantém o canto inferior direito", () => {
    const next = resizeBox(start, "tl", 10, 15, limits);
    expect(next).toEqual({ left: 310, top: 215, width: 390, height: 85 });
    expect(next.left + next.width).toBe(700);
    expect(next.top + next.height).toBe(300);
  });

  test("canto inferior direito não move a origem", () => {
    expect(resizeBox(start, "br", -40, -10, limits)).toEqual({
      left: 300,
      top: 200,
      width: 360,
      height: 90,
    });
  });

  test("canto superior direito e inferior esquerdo", () => {
    expect(resizeBox(start, "tr", 20, -20, limits)).toEqual({
      left: 300,
      top: 180,
      width: 420,
      height: 120,
    });
    expect(resizeBox(start, "bl", -20, 20, limits)).toEqual({
      left: 280,
      top: 200,
      width: 420,
      height: 120,
    });
  });
});

describe("tamanho mínimo", () => {
  test("a caixa nunca fica menor que o mínimo, por qualquer alça", () => {
    const fromRight = resizeBox(start, "mr", -1000, 0, limits);
    expect(fromRight.width).toBe(TEXT_BOX_MIN_SIZE);
    expect(fromRight.left).toBe(300);

    const fromLeft = resizeBox(start, "ml", 1000, 0, limits);
    expect(fromLeft.width).toBe(TEXT_BOX_MIN_SIZE);
    expect(fromLeft.left + fromLeft.width).toBe(700);

    const fromTop = resizeBox(start, "tl", 1000, 1000, limits);
    expect(fromTop).toEqual({
      left: 680,
      top: 280,
      width: TEXT_BOX_MIN_SIZE,
      height: TEXT_BOX_MIN_SIZE,
    });
  });
});

describe("limites da arte", () => {
  const margin = pageMargin(IMAGE_W);

  test("a margem lateral segue a fórmula do PDF (4%, mínimo 8 px)", () => {
    expect(margin).toBe(56);
    expect(pageMargin(100)).toBe(8);
    expect(textBoxArea(IMAGE_W, IMAGE_H)).toEqual({
      left: 56,
      top: 0,
      width: 1302,
      height: 1000,
    });
  });

  test("não cresce além da margem direita nem da esquerda", () => {
    const right = resizeBox(start, "mr", 5000, 0, limits);
    expect(right.left + right.width).toBe(IMAGE_W - margin);

    const left = resizeBox(start, "ml", -5000, 0, limits);
    expect(left.left).toBe(margin);
    expect(left.left + left.width).toBe(700);
  });

  test("não passa do topo nem do fim da arte", () => {
    expect(resizeBox(start, "mt", 0, -5000, limits).top).toBe(0);
    const bottom = resizeBox(start, "mb", 0, 5000, limits);
    expect(bottom.top + bottom.height).toBe(IMAGE_H);
  });

  test("uma caixa que já está fora da área não é empurrada de volta, só não cresce mais", () => {
    const outside = { left: 10, top: 200, width: 300, height: 100 };
    expect(resizeBox(outside, "ml", -5, 0, limits).left).toBe(10);
    expect(resizeBox(outside, "ml", 15, 0, limits).left).toBe(25);
  });

  test("largura máxima digitada segue o limite do PDF para cada alinhamento", () => {
    expect(maxBoxWidth(707, "center", IMAGE_W)).toBe(1302);
    expect(maxBoxWidth(90, "left", IMAGE_W)).toBe(1268);
    expect(maxBoxWidth(1324, "right", IMAGE_W)).toBe(1268);
    expect(clampBoxWidth(5000, 707, "center", IMAGE_W)).toBe(1302);
    expect(clampBoxWidth(3, 707, "center", IMAGE_W)).toBe(TEXT_BOX_MIN_SIZE);
    expect(clampBoxWidth(500, 707, "center", IMAGE_W)).toBe(500);
  });

  test("altura digitada fica dentro da arte", () => {
    expect(clampBoxHeight(5000, 900, IMAGE_H)).toBe(100);
    expect(clampBoxHeight(1, 900, IMAGE_H)).toBe(TEXT_BOX_MIN_SIZE);
  });
});

describe("âncora de alinhamento", () => {
  test("X continua sendo a âncora: esquerda, centro ou direita da caixa", () => {
    expect(rectFromAnchor(100, 50, 200, 40, "left")).toEqual({
      left: 100,
      top: 50,
      width: 200,
      height: 40,
    });
    expect(rectFromAnchor(100, 50, 200, 40, "center").left).toBe(0);
    expect(rectFromAnchor(300, 50, 200, 40, "right").left).toBe(100);
  });

  test("ida e volta entre retângulo e âncora preserva X e Y", () => {
    for (const align of ["left", "center", "right"] as const) {
      const rect = rectFromAnchor(707, 300, 400, 80, align);
      expect(anchorFromRect(rect, align)).toEqual({ x: 707, y: 300 });
    }
  });

  test("com base fixa, Y é a borda de baixo e a caixa cresce para cima", () => {
    const rect = rectFromAnchor(90, 900, 400, 120, "left", "bottom");
    expect(rect).toEqual({ left: 90, top: 780, width: 400, height: 120 });
    expect(anchorFromRect(rect, "left", "bottom")).toEqual({ x: 90, y: 900 });

    // Pulling the top handle changes the height; the base stays at Y = 900.
    const taller = resizeBox(rect, "mt", 0, -60, limits);
    expect(taller).toEqual({ left: 90, top: 720, width: 400, height: 180 });
    expect(anchorFromRect(taller, "left", "bottom").y).toBe(900);
  });

  test("puxar a alça direita de um texto centralizado move X pela metade", () => {
    const rect = rectFromAnchor(707, 300, 400, 80, "center");
    const next = resizeBox(rect, "mr", 100, 0, limits);
    expect(anchorFromRect(next, "center").x).toBe(757);
    expect(next.left).toBe(rect.left);
  });
});
