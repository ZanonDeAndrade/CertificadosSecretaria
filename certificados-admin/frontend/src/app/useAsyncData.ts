/**
 * One data-loading primitive for every screen, so the four states the brief
 * asks for (loading, empty, error, offline) plus 401/403/429 are handled the
 * same way everywhere instead of being reinvented per page.
 *
 * 401 is deliberately NOT handled here: the axios interceptor already dispatches
 * SESSION_EXPIRED_EVENT, which AuthContext turns into a sign-out and a notice.
 * Duplicating it would show the operator two conflicting messages.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { classifyError, getApiErrorMessage, RequestFailure } from "../services/api";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string;
  failure: RequestFailure | null;
  /** True only for the very first load, so refreshes don't flash a skeleton. */
  initialLoading: boolean;
  reload: () => void;
}

const MESSAGES: Record<RequestFailure, string> = {
  offline:
    "Sem conexão com a rede. Os dados serão carregados assim que a conexão voltar.",
  unauthorized: "Sua sessão expirou. Entre novamente.",
  forbidden: "Seu perfil de acesso não permite consultar estas informações.",
  "rate-limited":
    "Muitas solicitações em pouco tempo. Aguarde alguns instantes e tente novamente.",
  server: "Não foi possível carregar os dados. Tente novamente em instantes.",
};

export function failureMessage(error: unknown, fallback?: string): string {
  const failure = classifyError(error);
  // A specific message from the backend beats our generic one, except for
  // offline/429 where the backend has not spoken at all.
  if (failure === "offline" || failure === "rate-limited") return MESSAGES[failure];
  return getApiErrorMessage(error, fallback ?? MESSAGES[failure]);
}

export function useAsyncData<T>(
  loader: () => Promise<T>,
  deps: unknown[],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState("");
  const [failure, setFailure] = useState<RequestFailure | null>(null);
  const [nonce, setNonce] = useState(0);

  // Keep the latest loader without making it a dependency — callers pass an
  // inline arrow, which would otherwise re-run the effect on every render.
  const loaderRef = useRef(loader);
  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setFailure(null);

    // Defer one microtask so React StrictMode can perform its development-only
    // setup → cleanup → setup cycle before any HTTP request starts. Without
    // this guard every screen load issued the same request twice in local dev.
    Promise.resolve()
      .then(() => (cancelled ? undefined : loaderRef.current()))
      .then((result) => {
        if (cancelled) return;
        if (result !== undefined) setData(result);
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setFailure(classifyError(requestError));
        setError(failureMessage(requestError));
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
        setInitialLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { data, loading, initialLoading, error, failure, reload };
}

/** Tracks browser connectivity so screens can pre-empt a doomed request. */
export function useOnline(): boolean {
  const [online, setOnline] = useState(
    typeof navigator === "undefined" ? true : navigator.onLine !== false,
  );
  useEffect(() => {
    const goOnline = () => setOnline(true);
    const goOffline = () => setOnline(false);
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);
  return online;
}
