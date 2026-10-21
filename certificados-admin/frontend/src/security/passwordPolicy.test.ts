import { describe, expect, test } from "vitest";
import { MIN_PASSWORD_LENGTH, passwordPolicyError } from "./passwordPolicy";

describe("política de senha", () => {
  test("aceita exatamente seis caracteres com as quatro classes", () => {
    expect(MIN_PASSWORD_LENGTH).toBe(6);
    expect(passwordPolicyError("Aa1!bc")).toBe("");
  });

  test.each([
    ["Aa1!x", "Use pelo menos 6 caracteres."],
    ["abcdef1!", "Inclua uma letra maiúscula."],
    ["ABCDEF1!", "Inclua uma letra minúscula."],
    ["Abcdef!!", "Inclua um número."],
    ["Abcdef12", "Inclua um caractere especial."],
  ])("rejeita %s", (password, message) => {
    expect(passwordPolicyError(password)).toBe(message);
  });
});
