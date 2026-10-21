/**
 * Session state for the whole app.
 *
 * Holds the signed-in user, the initial "am I still signed in?" check, and the
 * notice shown when the backend revokes a session mid-use (the
 * SESSION_EXPIRED_EVENT dispatched by the axios interceptor).
 */
import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  AdminUser,
  getMe,
  logout as apiLogout,
  SESSION_EXPIRED_EVENT,
} from "../services/api";
import { can, Permission } from "./permissions";

export interface AuthState {
  user: AdminUser | null;
  /** False until the initial session check resolves. */
  ready: boolean;
  /** Message explaining why the session ended, shown on the sign-in screen. */
  notice: string;
  signIn: (user: AdminUser) => void;
  signOut: () => Promise<void>;
  refresh: () => Promise<AdminUser | null>;
  /** Permission check bound to the current user's role. */
  can: (permission: Permission) => boolean;
}

/** Exported so tests can supply a session without stubbing the network. */
export const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AdminUser | null>(null);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    // Avoid the duplicate request caused by React StrictMode's development
    // effect probe while keeping the production/session behavior unchanged.
    Promise.resolve()
      .then(() => (cancelled ? null : getMe()))
      .then((me) => {
        if (!cancelled && me) setUser(me);
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const handleExpired = (event: Event) => {
      const detail = (event as CustomEvent<string>).detail;
      setNotice(detail || "Sua sessão expirou. Entre novamente.");
      setUser(null);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleExpired);
  }, []);

  const signIn = useCallback((next: AdminUser) => {
    setNotice("");
    setUser(next);
  }, []);

  const signOut = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      // Sign out locally even if the request failed — leaving the operator in a
      // half-signed-out state on a shared secretariat machine is worse.
      setNotice("");
      setUser(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const next = await getMe();
      setUser(next);
      return next;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      notice,
      signIn,
      signOut,
      refresh,
      can: (permission: Permission) => can(user?.permissions, permission),
    }),
    [user, ready, notice, signIn, signOut, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth precisa estar dentro de <AuthProvider>.");
  return context;
}
