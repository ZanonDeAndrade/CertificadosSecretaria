import type { GoogleDrivePickerSession } from "../services/api";

const FOLDER_MIME_TYPE = "application/vnd.google-apps.folder";
const GOOGLE_API_SCRIPT = "https://apis.google.com/js/api.js";

interface PickerDocument {
  id?: string;
  name?: string;
  mimeType?: string;
}

interface GooglePickerNamespace {
  Action: { PICKED: string; CANCEL: string };
  DocsView: new (viewId: string) => {
    setIncludeFolders(value: boolean): unknown;
    setSelectFolderEnabled(value: boolean): unknown;
    setMimeTypes(value: string): unknown;
  };
  ViewId: { FOLDERS: string };
  PickerBuilder: new () => {
    addView(view: unknown): unknown;
    setOAuthToken(token: string): unknown;
    setDeveloperKey(key: string): unknown;
    setAppId(id: string): unknown;
    setCallback(callback: (data: { action?: string; docs?: PickerDocument[] }) => void): unknown;
    setTitle(title: string): unknown;
    build(): { setVisible(value: boolean): void };
  };
}

declare global {
  interface Window {
    gapi?: { load(name: string, options: { callback: () => void; onerror: () => void }): void };
    google?: { picker: GooglePickerNamespace };
  }
}

let loader: Promise<void> | null = null;

function loadPicker(): Promise<void> {
  if (window.google?.picker) return Promise.resolve();
  if (loader) return loader;
  loader = new Promise((resolve, reject) => {
    const finish = () => {
      if (!window.gapi) {
        reject(new Error("Biblioteca do Google Picker indisponível."));
        return;
      }
      window.gapi.load("picker", {
        callback: resolve,
        onerror: () => reject(new Error("Não foi possível carregar o Google Picker.")),
      });
    };
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${GOOGLE_API_SCRIPT}"]`,
    );
    if (existing) {
      existing.addEventListener("load", finish, { once: true });
      existing.addEventListener("error", () => reject(new Error("Google Picker indisponível.")), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.src = GOOGLE_API_SCRIPT;
    script.async = true;
    script.defer = true;
    script.crossOrigin = "anonymous";
    script.referrerPolicy = "no-referrer";
    script.addEventListener("load", finish, { once: true });
    script.addEventListener("error", () => reject(new Error("Google Picker indisponível.")), {
      once: true,
    });
    document.head.appendChild(script);
  });
  return loader;
}

export async function pickGoogleDriveFolder(
  session: GoogleDrivePickerSession,
): Promise<{ id: string; name: string } | null> {
  await loadPicker();
  const picker = window.google?.picker;
  if (!picker) throw new Error("Google Picker indisponível.");
  return new Promise((resolve, reject) => {
    try {
      const view = new picker.DocsView(picker.ViewId.FOLDERS);
      view.setIncludeFolders(true);
      view.setSelectFolderEnabled(true);
      view.setMimeTypes(FOLDER_MIME_TYPE);
      const builder = new picker.PickerBuilder();
      builder.addView(view);
      builder.setOAuthToken(session.access_token);
      builder.setDeveloperKey(session.api_key);
      if (session.app_id) builder.setAppId(session.app_id);
      builder.setTitle("Selecione a pasta dos certificados");
      builder.setCallback((data) => {
        if (data.action === picker.Action.CANCEL) {
          resolve(null);
          return;
        }
        if (data.action !== picker.Action.PICKED) return;
        const selected = data.docs?.[0];
        if (!selected?.id || selected.mimeType !== FOLDER_MIME_TYPE) {
          reject(new Error("Selecione uma pasta do Google Drive."));
          return;
        }
        resolve({ id: selected.id, name: selected.name || "Pasta selecionada" });
      });
      builder.build().setVisible(true);
    } catch (error) {
      reject(error);
    }
  });
}
