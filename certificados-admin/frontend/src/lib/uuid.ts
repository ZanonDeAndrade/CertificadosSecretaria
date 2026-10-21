const UUID_BYTES = 16;

/**
 * Create an RFC 4122 UUID v4 using only cryptographically secure browser APIs.
 *
 * `randomUUID` is restricted to secure contexts in some browsers, while
 * `getRandomValues` remains available on HTTP pages. The explicit error keeps
 * us from silently weakening identifiers when neither API exists.
 */
export function createUuid(): string {
  if (typeof globalThis.crypto === "undefined") {
    throw new Error("Não foi possível gerar UUID: Web Crypto não está disponível.");
  }

  const cryptoApi = globalThis.crypto;
  if (typeof cryptoApi.randomUUID === "function") {
    return cryptoApi.randomUUID();
  }

  if (typeof cryptoApi.getRandomValues !== "function") {
    throw new Error(
      "Não foi possível gerar UUID: nenhuma fonte criptográfica segura está disponível.",
    );
  }

  const bytes = cryptoApi.getRandomValues(new Uint8Array(UUID_BYTES));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;

  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0"));
  return (
    hex.slice(0, 4).join("") +
    "-" +
    hex.slice(4, 6).join("") +
    "-" +
    hex.slice(6, 8).join("") +
    "-" +
    hex.slice(8, 10).join("") +
    "-" +
    hex.slice(10, 16).join("")
  );
}
