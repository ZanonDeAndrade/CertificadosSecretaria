export const MIN_PASSWORD_LENGTH = 6;

export const PASSWORD_POLICY_HINT =
  "Mínimo de 6 caracteres, com letra maiúscula, minúscula, número e caractere especial.";

export function passwordPolicyError(password: string): string {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return "Use pelo menos 6 caracteres.";
  }
  if (!/[A-ZÀ-ÖØ-Þ]/u.test(password)) {
    return "Inclua uma letra maiúscula.";
  }
  if (!/[a-zà-öø-ÿ]/u.test(password)) {
    return "Inclua uma letra minúscula.";
  }
  if (!/\d/u.test(password)) {
    return "Inclua um número.";
  }
  if (![...password].some((character) => !/[\p{L}\p{N}\s]/u.test(character))) {
    return "Inclua um caractere especial.";
  }
  return "";
}
