/**
 * Minimal .xlsx writer.
 *
 * The emission screen offers a "planilha modelo" download, and the upload only
 * accepts .xlsx — a CSV would be rejected by the very screen that offered it.
 * Rather than add a spreadsheet dependency (or a backend endpoint, which is out
 * of scope here), this writes the smallest workbook Excel and LibreOffice both
 * open: a ZIP with no compression (store method), which needs only a CRC-32.
 *
 * Scope is intentionally tiny — one sheet, inline strings, no styles, no
 * numbers. It exists to produce a column template, not to be a library.
 */

/* ── CRC-32 ──────────────────────────────────────────────────────────────── */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < bytes.length; i += 1) {
    crc = CRC_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/* ── ZIP (store only) ────────────────────────────────────────────────────── */

interface ZipEntry {
  name: string;
  data: Uint8Array;
}

function writeUint32(view: DataView, offset: number, value: number) {
  view.setUint32(offset, value, true);
}

function writeUint16(view: DataView, offset: number, value: number) {
  view.setUint16(offset, value, true);
}

/** Builds a ZIP archive with all entries stored uncompressed. */
function zip(entries: ZipEntry[]): Blob {
  const encoder = new TextEncoder();
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let offset = 0;

  for (const entry of entries) {
    const nameBytes = encoder.encode(entry.name);
    const crc = crc32(entry.data);
    const size = entry.data.length;

    // Local file header: 30 bytes + name.
    const local = new Uint8Array(30 + nameBytes.length);
    const localView = new DataView(local.buffer);
    writeUint32(localView, 0, 0x04034b50);
    writeUint16(localView, 4, 20); // version needed
    writeUint16(localView, 6, 0); // flags
    writeUint16(localView, 8, 0); // method: store
    writeUint16(localView, 10, 0); // mod time
    writeUint16(localView, 12, 0x21); // mod date (1980-01-01)
    writeUint32(localView, 14, crc);
    writeUint32(localView, 18, size);
    writeUint32(localView, 22, size);
    writeUint16(localView, 26, nameBytes.length);
    writeUint16(localView, 28, 0); // extra length
    local.set(nameBytes, 30);

    localParts.push(local, entry.data);

    // Central directory header: 46 bytes + name.
    const central = new Uint8Array(46 + nameBytes.length);
    const centralView = new DataView(central.buffer);
    writeUint32(centralView, 0, 0x02014b50);
    writeUint16(centralView, 4, 20); // version made by
    writeUint16(centralView, 6, 20); // version needed
    writeUint16(centralView, 8, 0);
    writeUint16(centralView, 10, 0);
    writeUint16(centralView, 12, 0);
    writeUint16(centralView, 14, 0x21);
    writeUint32(centralView, 16, crc);
    writeUint32(centralView, 20, size);
    writeUint32(centralView, 24, size);
    writeUint16(centralView, 28, nameBytes.length);
    writeUint16(centralView, 30, 0); // extra
    writeUint16(centralView, 32, 0); // comment
    writeUint16(centralView, 34, 0); // disk
    writeUint16(centralView, 36, 0); // internal attrs
    writeUint32(centralView, 38, 0); // external attrs
    writeUint32(centralView, 42, offset);
    central.set(nameBytes, 46);
    centralParts.push(central);

    offset += local.length + size;
  }

  const centralSize = centralParts.reduce((sum, part) => sum + part.length, 0);

  // End of central directory: 22 bytes.
  const end = new Uint8Array(22);
  const endView = new DataView(end.buffer);
  writeUint32(endView, 0, 0x06054b50);
  writeUint16(endView, 4, 0);
  writeUint16(endView, 6, 0);
  writeUint16(endView, 8, entries.length);
  writeUint16(endView, 10, entries.length);
  writeUint32(endView, 12, centralSize);
  writeUint32(endView, 16, offset);
  writeUint16(endView, 20, 0);

  return new Blob(
    [...localParts, ...centralParts, end] as BlobPart[],
    {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
  );
}

/* ── Workbook ────────────────────────────────────────────────────────────── */

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Converts a zero-based column index to its A1 letter (0 → A, 26 → AA). */
function columnLetter(index: number): string {
  let result = "";
  let n = index;
  while (n >= 0) {
    result = String.fromCharCode((n % 26) + 65) + result;
    n = Math.floor(n / 26) - 1;
  }
  return result;
}

/**
 * Builds a single-sheet .xlsx from a grid of strings. Every cell is written as
 * an inline string, which keeps the file free of a shared-strings table.
 */
export function buildXlsx(rows: string[][], sheetName = "Planilha1"): Blob {
  const encoder = new TextEncoder();

  const sheetRows = rows
    .map((cells, rowIndex) => {
      const cellXml = cells
        .map((cell, columnIndex) => {
          const ref = `${columnLetter(columnIndex)}${rowIndex + 1}`;
          return `<c r="${ref}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(
            cell,
          )}</t></is></c>`;
        })
        .join("");
      return `<row r="${rowIndex + 1}">${cellXml}</row>`;
    })
    .join("");

  const files: Record<string, string> = {
    "[Content_Types].xml":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
      '<Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' +
      "</Types>",

    "_rels/.rels":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
      "</Relationships>",

    "xl/workbook.xml":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' +
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
      `<sheets><sheet name="${escapeXml(sheetName)}" sheetId="1" r:id="rId1"/></sheets>` +
      "</workbook>",

    "xl/_rels/workbook.xml.rels":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
      '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>' +
      "</Relationships>",

    "xl/worksheets/sheet1.xml":
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
      '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
      `<sheetData>${sheetRows}</sheetData>` +
      "</worksheet>",
  };

  return zip(
    Object.entries(files).map(([name, content]) => ({
      name,
      data: encoder.encode(content),
    })),
  );
}
