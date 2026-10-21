/**
 * Media query as state.
 *
 * Used where a responsive change must alter the DOM rather than just its
 * styling — chiefly the history screen, which renders a data table on wide
 * viewports and a record list on narrow ones. Doing that with `hidden`/`block`
 * utilities would keep BOTH structures in the DOM, so every row would be
 * announced twice by a screen reader and appear twice to any query. Rendering
 * exactly one is the accessible option.
 *
 * Defaults to the wide layout when `matchMedia` is unavailable (jsdom, older
 * browsers), so tests and server-side rendering see the table.
 */
import { useEffect, useState } from "react";

export function useMediaQuery(query: string, fallback = false): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return fallback;
    }
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return;
    }
    const list = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    setMatches(list.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** True at the `md` breakpoint and above (Tailwind's 768px). */
export function useIsWide(): boolean {
  return useMediaQuery("(min-width: 768px)", true);
}
