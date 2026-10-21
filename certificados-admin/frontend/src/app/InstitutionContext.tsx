import {
  createContext,
  ReactNode,
  useContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  getPublicInstitutionSettings,
  PublicInstitutionSettings,
} from "../services/api";

const SAFE_FALLBACK: PublicInstitutionSettings = {
  institution_name: "Instituição de ensino",
  public_url: "",
};

interface InstitutionState extends PublicInstitutionSettings {
  ready: boolean;
  refresh: () => Promise<void>;
}

const InstitutionContext = createContext<InstitutionState>({
  ...SAFE_FALLBACK,
  ready: false,
  refresh: async () => {},
});

/**
 * Loads non-sensitive institutional presentation data independently of auth,
 * so the sign-in screen and shell use the same server-owned business value.
 */
export function InstitutionProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState(SAFE_FALLBACK);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const value = await getPublicInstitutionSettings();
      if (value.institution_name.trim()) setSettings(value);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    getPublicInstitutionSettings()
      .then((value) => {
        if (!cancelled && value.institution_name.trim()) setSettings(value);
      })
      .catch(() => {
        // Authentication and public validation remain usable during a
        // transient presentation-settings outage.
      })
      .finally(() => {
        if (!cancelled) setReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo(
    () => ({ ...settings, ready, refresh }),
    [settings, ready, refresh],
  );
  return (
    <InstitutionContext.Provider value={value}>
      {children}
    </InstitutionContext.Provider>
  );
}

export function useInstitution(): InstitutionState {
  return useContext(InstitutionContext);
}
