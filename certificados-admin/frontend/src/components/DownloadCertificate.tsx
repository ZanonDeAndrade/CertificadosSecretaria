/**
 * The download control of one certificate, wherever a row or a dialog needs it.
 *
 * An ordinary certificate is a single button: one PDF, named by the API
 * (`Nome_Evento_Ano.pdf`). A per-work certificate (Mostra) is a menu: "Todos
 * os autores (ZIP)" plus one entry per author, each delivering the same stored
 * PDF under that author's name. One click per file keeps every browser happy;
 * a loop of downloads would trip Chrome's "download multiple files" prompt.
 *
 * The accessible name follows the subject the rest of the panel uses: "Baixar
 * certificado de Ana" or "Baixar certificado do trabalho “Horta…”".
 */
import { failureMessage } from "../app/useAsyncData";
import { isPerWorkType } from "../domain/certificateTypes";
import { saveBlob } from "../lib/download";
import {
  DownloadedFile,
  downloadCertificateAuthorsZip,
  downloadCertificateFile,
} from "../services/api";
import Button, { IconButton } from "../ui/Button";
import Menu, { MenuItem } from "../ui/Menu";
import { certificateOf } from "./CertificateSubject";

export interface DownloadSource {
  unique_code: string;
  participant_name: string;
  certificate_type?: string | null;
  work_title?: string | null;
  authors?: string[];
}

interface Props {
  cert: DownloadSource;
  /** `icon`: the compact control of a table row. `button`: cards and dialogs. */
  appearance?: "icon" | "button";
  size?: "sm" | "md";
  disabled?: boolean;
  /** Receives a message the screen shows where it reports download problems. */
  onError: (message: string) => void;
}

export const ALL_AUTHORS_LABEL = "Todos os autores (ZIP)";

export default function DownloadCertificate({
  cert,
  appearance = "button",
  size = "md",
  disabled = false,
  onError,
}: Props) {
  const authors = isPerWorkType(cert.certificate_type) && cert.authors?.length ? cert.authors : [];
  const name = `Baixar certificado ${certificateOf(cert)}`;

  const run = async (fetch: () => Promise<DownloadedFile>) => {
    try {
      const file = await fetch();
      saveBlob(file.blob, file.filename);
    } catch (error) {
      onError(failureMessage(error, "Não foi possível baixar o certificado."));
    }
  };

  if (!authors.length) {
    const download = () => void run(() => downloadCertificateFile(cert.unique_code));
    return appearance === "icon" ? (
      <IconButton size={size} icon="download" label={name} disabled={disabled} onClick={download} />
    ) : (
      <Button
        size={size}
        variant="secondary"
        icon="download"
        aria-label={name}
        disabled={disabled}
        onClick={download}
      >
        Baixar
      </Button>
    );
  }

  const items: MenuItem[] = [
    {
      label: ALL_AUTHORS_LABEL,
      icon: "download",
      onSelect: () => void run(() => downloadCertificateAuthorsZip(cert.unique_code)),
    },
    ...authors.map((author, index) => ({
      label: author,
      icon: "user" as const,
      onSelect: () => void run(() => downloadCertificateFile(cert.unique_code, index + 1)),
    })),
  ];
  return (
    <Menu
      label={appearance === "icon" ? name : "Baixar"}
      ariaLabel={name}
      icon="download"
      size={size}
      items={items}
      labelHidden={appearance === "icon"}
      variant={appearance === "icon" ? "ghost" : "secondary"}
      disabled={disabled}
    />
  );
}
