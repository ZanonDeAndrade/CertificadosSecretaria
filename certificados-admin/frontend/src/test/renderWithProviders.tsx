/**
 * Test helper: renders a screen inside the same providers it has in the app
 * (router + auth), so component tests exercise the real wiring rather than a
 * stripped-down version of it.
 *
 * `role` controls which permissions the rendered screen sees, which is the axis
 * the permission tests vary. The auth value is supplied directly, so screens
 * under test never need the /auth/me request mocked.
 */
import { ReactElement, ReactNode, useMemo } from "react";
import { render, RenderResult } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthContext, AuthState } from "../app/AuthContext";
import { can, Permission } from "../app/permissions";

export const TEST_PERMISSIONS: Record<string, Permission[]> = {
  admin: [
    "dashboard.read",
    "certificates.read",
    "certificates.issue",
    "certificates.revoke",
    "certificates.reissue",
    "certificates.download",
    "templates.read",
    "templates.manage",
    "users.manage",
    "sessions.manage",
    "audit.read",
    "settings.read",
    "settings.manage",
  ],
  secretaria: [
    "dashboard.read",
    "certificates.read",
    "certificates.issue",
    "certificates.revoke",
    "certificates.reissue",
    "certificates.download",
  ],
  auditor: ["certificates.read", "audit.read"],
};

export interface ProviderOptions {
  /** Signed-in role: admin | secretaria | auditor. Defaults to admin. */
  role?: string;
  username?: string;
  /** Initial router entry, so route-dependent screens start where intended. */
  route?: string;
  /** Render signed-out, to exercise the guards. */
  signedOut?: boolean;
}

export function Providers({
  children,
  role = "admin",
  username = "secretaria",
  route = "/",
  signedOut = false,
}: ProviderOptions & { children: ReactNode }) {
  const value = useMemo<AuthState>(
    () => {
      const permissions = TEST_PERMISSIONS[role] ?? [];
      return ({
      user: signedOut ? null : {
        id: 1,
        name: username,
        username,
        role,
        permissions,
        must_change_password: false,
      },
      ready: true,
      notice: "",
      signIn: () => {},
      signOut: async () => {},
      refresh: async () => null,
      can: (permission: Permission) =>
        signedOut ? false : can(permissions, permission),
    });
    },
    [role, username, signedOut],
  );

  return (
    <MemoryRouter initialEntries={[route]}>
      <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
    </MemoryRouter>
  );
}

export function renderWithProviders(
  ui: ReactElement,
  options: ProviderOptions = {},
): RenderResult {
  return render(<Providers {...options}>{ui}</Providers>);
}
