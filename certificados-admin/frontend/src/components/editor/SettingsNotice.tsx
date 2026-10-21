/**
 * Warns, inside the editor, when an element on the canvas prints an
 * institutional setting that is empty: the certificate would come out without
 * it. Only settings the current layout actually uses are mentioned, so the
 * notice is about this template, not about the settings screen in general.
 */
import { Link } from "react-router-dom";
import { INSTITUTIONAL_SETTING_FOR_KEY, TemplateElement } from "../../types/template";
import Alert from "../../ui/Alert";

interface SettingsNoticeProps {
  emptySettings: { setting: string; label: string }[];
  canManage: boolean;
  elements: TemplateElement[];
  /** The backend could not be asked; the built-in sample is being shown. */
  fallback: boolean;
}

export default function SettingsNotice({
  emptySettings,
  canManage,
  elements,
  fallback,
}: SettingsNoticeProps) {
  if (fallback) {
    return (
      <Alert tone="info" live={false} className="rounded-none border-x-0">
        Dados de exemplo locais: não foi possível consultar as Configurações da
        instituição, então a prévia pode mostrar valores que o PDF não terá.
      </Alert>
    );
  }

  const used = new Set(
    elements.flatMap((element) =>
      element.type === "text" ? [INSTITUTIONAL_SETTING_FOR_KEY[element.key] ?? ""] : [],
    ),
  );
  const missing = emptySettings.filter((item) => used.has(item.setting));
  if (missing.length === 0) return null;

  return (
    <Alert tone="warn" live={false} className="rounded-none border-x-0">
      Sem valor nas Configurações da instituição:{" "}
      <strong>{missing.map((item) => item.label).join(", ")}</strong>. Os certificados
      sairão sem {missing.length > 1 ? "esses campos" : "esse campo"}.{" "}
      {canManage ? (
        <Link to="/configuracoes" className="font-medium underline">
          Abrir Configurações
        </Link>
      ) : (
        "Peça a um administrador para preencher em Configurações."
      )}
    </Alert>
  );
}
