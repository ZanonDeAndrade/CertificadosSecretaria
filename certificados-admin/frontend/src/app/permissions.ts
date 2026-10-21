/**
 * Permission names returned by the backend in /auth/login and /auth/me.
 *
 * This is a NAVIGATION and AFFORDANCE model, never a security boundary: the
 * backend is the only authority, and every protected endpoint re-checks the
 * role. What this buys is honesty in the interface — an auditor never sees an
 * "Emitir" button that would fail with 403 the moment they pressed it.
 *
 * The role-to-permission matrix deliberately does not live here: duplicating it
 * would let the UI drift from institutional policy. Runtime affordances consume
 * the effective permission list computed by the backend.
 */
export type Role = "admin" | "secretaria" | "auditor";

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Administrador",
  secretaria: "Secretaria",
  auditor: "Auditoria",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  admin: "Acesso total a usuários, templates, emissão, auditoria e configurações.",
  secretaria: "Emite, consulta, baixa, revoga e reemite conforme a política institucional.",
  auditor: "Somente leitura do histórico e da trilha de auditoria.",
};

export type Permission =
  | "dashboard.read"
  | "certificates.read"
  | "certificates.issue"
  | "certificates.revoke"
  | "certificates.reissue"
  | "certificates.download"
  | "templates.read"
  | "templates.manage"
  | "users.manage"
  | "sessions.manage"
  | "audit.read"
  | "settings.read"
  | "settings.manage";

/** Unknown or missing roles get nothing — fail closed. */
export function can(
  permissions: readonly string[] | undefined,
  permission: Permission,
): boolean {
  return Boolean(permissions?.includes(permission));
}

export function isKnownRole(role: string | undefined): role is Role {
  return role === "admin" || role === "secretaria" || role === "auditor";
}

export function roleLabel(role: string | undefined): string {
  return isKnownRole(role) ? ROLE_LABELS[role] : "Perfil não reconhecido";
}
