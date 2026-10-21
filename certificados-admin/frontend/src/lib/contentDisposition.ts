/**
 * Filename a download response suggests through its Content-Disposition.
 *
 * The API sends the exact UTF-8 name in `filename*` (accents intact) and an
 * ASCII-only `filename` for older clients; the UTF-8 one wins. Returns
 * `fallback` when the header names neither, e.g. when a proxy dropped it.
 */
export function filenameFromContentDisposition(header: unknown, fallback: string): string {
  if (typeof header !== "string") return fallback;
  const extended = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header);
  if (extended) {
    try {
      const decoded = decodeURIComponent(extended[1].trim());
      if (decoded) return decoded;
    } catch {
      // Malformed percent-encoding: fall back to the ASCII name below.
    }
  }
  const plain = /filename\s*=\s*(?:"([^"]*)"|([^;]+))/i.exec(header);
  const name = (plain?.[1] ?? plain?.[2] ?? "").trim();
  return name || fallback;
}
