import { afterEach, describe, expect, it, vi } from "vitest";
import { createUuid } from "./uuid";

const originalCryptoDescriptor = Object.getOwnPropertyDescriptor(globalThis, "crypto");

function setCrypto(value: unknown): void {
  Object.defineProperty(globalThis, "crypto", {
    configurable: true,
    value,
  });
}

afterEach(() => {
  if (originalCryptoDescriptor) {
    Object.defineProperty(globalThis, "crypto", originalCryptoDescriptor);
  } else {
    Reflect.deleteProperty(globalThis, "crypto");
  }
});

describe("createUuid", () => {
  it("prefere crypto.randomUUID quando disponível", () => {
    const expected = "123e4567-e89b-42d3-a456-426614174000";
    const randomUUID = vi.fn(() => expected);
    const getRandomValues = vi.fn();
    setCrypto({ randomUUID, getRandomValues });

    expect(createUuid()).toBe(expected);
    expect(randomUUID).toHaveBeenCalledOnce();
    expect(getRandomValues).not.toHaveBeenCalled();
  });

  it("usa getRandomValues quando randomUUID não existe", () => {
    const getRandomValues = vi.fn((bytes: Uint8Array) => {
      bytes.fill(0xff);
      return bytes;
    });
    setCrypto({ getRandomValues });

    expect(createUuid()).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
    expect(getRandomValues).toHaveBeenCalledOnce();
  });

  it("gera UUID v4 canônico com version e variant corretos no fallback", () => {
    setCrypto({
      getRandomValues: (bytes: Uint8Array) => {
        for (let index = 0; index < bytes.length; index += 1) {
          bytes[index] = index * 13;
        }
        return bytes;
      },
    });

    expect(createUuid()).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  it("mantém unicidade em várias chamadas do fallback", () => {
    let call = 0;
    setCrypto({
      getRandomValues: (bytes: Uint8Array) => {
        bytes.fill(0);
        bytes[15] = call;
        call += 1;
        return bytes;
      },
    });

    const values = Array.from({ length: 64 }, () => createUuid());
    expect(new Set(values).size).toBe(values.length);
  });

  it("falha explicitamente quando não existe fonte criptográfica", () => {
    setCrypto(undefined);
    expect(() => createUuid()).toThrow("Web Crypto não está disponível");

    setCrypto({});
    expect(() => createUuid()).toThrow("nenhuma fonte criptográfica segura");
  });
});
