/**
 * Hand a Blob to the browser as a file download.
 *
 * The object URL is revoked only after a delay: revoking it in the same tick
 * as the click works for one file but drops the second of two downloads
 * started close together in Firefox, which reads the URL after the handler
 * returns. A minute is far longer than any browser needs to start a download.
 */
export const REVOKE_DELAY_MS = 60_000;

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
