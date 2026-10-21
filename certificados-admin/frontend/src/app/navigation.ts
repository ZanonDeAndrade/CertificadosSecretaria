/**
 * The single source of truth for navigation.
 *
 * Both the desktop sidebar and the mobile drawer render from this list, and the
 * route guards read the same `permission` field, so a screen cannot appear in
 * the menu without being protected, or be protected without appearing.
 */
import { IconName } from "../ui/Icon";
import { Permission } from "./permissions";

export interface NavItem {
  to: string;
  label: string;
  icon: IconName;
  /** Omit for screens every signed-in user may open. */
  permission?: Permission;
  /** Short line shown in the mobile drawer, where there is room to explain. */
  hint?: string;
  /** Section heading this item is grouped under in the sidebar. */
  group: "Operação" | "Administração";
}

export const NAV_ITEMS: NavItem[] = [
  {
    to: "/painel",
    label: "Painel",
    icon: "dashboard",
    permission: "dashboard.read",
    hint: "Situação geral das emissões",
    group: "Operação",
  },
  {
    to: "/emitir",
    label: "Emitir certificados",
    icon: "issue",
    permission: "certificates.issue",
    hint: "Emissão em lote por planilha",
    group: "Operação",
  },
  {
    to: "/historico",
    label: "Histórico",
    icon: "history",
    permission: "certificates.read",
    hint: "Consultar, baixar e revogar",
    group: "Operação",
  },
  {
    to: "/validar",
    label: "Validar certificado",
    icon: "verify",
    hint: "Conferir um código de validação",
    group: "Operação",
  },
  {
    to: "/template",
    label: "Template do certificado",
    icon: "template",
    permission: "templates.read",
    hint: "Layout e versões do modelo",
    group: "Administração",
  },
  {
    to: "/usuarios",
    label: "Usuários",
    icon: "users",
    permission: "users.manage",
    hint: "Perfis e acesso ao sistema",
    group: "Administração",
  },
  {
    to: "/auditoria",
    label: "Auditoria",
    icon: "audit",
    permission: "audit.read",
    hint: "Registro de ações do sistema",
    group: "Administração",
  },
  {
    to: "/configuracoes",
    label: "Configurações",
    icon: "settings",
    permission: "settings.read",
    hint: "Dados e regras institucionais",
    group: "Administração",
  },
];

export const NAV_GROUPS = ["Operação", "Administração"] as const;
