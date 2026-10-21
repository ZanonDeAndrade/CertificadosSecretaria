/**
 * Undo/redo and unsaved-change tracking for the template editor.
 *
 * Built as a layer ON TOP of useEditorCanvas rather than inside it: the canvas
 * hook owns fabric's mutable object graph, and threading an undo stack through
 * it would mean touching every mutation path. Instead this snapshots the
 * serialised layout — which is exactly what gets saved — and restores it with
 * the hook's own `loadTemplate`.
 *
 * Snapshots are debounced so a drag across the canvas collapses into one undo
 * step instead of dozens, and `restoringRef` stops a restore from being
 * recorded as a new edit (which would make undo un-undoable).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { EditorAPI } from "./useEditorCanvas";
import { TemplateLayout } from "../types/template";

const DEBOUNCE_MS = 350;
const MAX_HISTORY = 50;

export interface TemplateHistory {
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
  /** True when the layout differs from the last saved/loaded state. */
  isDirty: boolean;
  /** Call after a successful save, or when loading a version for editing. */
  markSaved: () => void;
  /**
   * Treat the next recorded snapshot as the saved baseline.
   *
   * Loading a version into the canvas is asynchronous (images resolve on their
   * own schedule), so there is no moment at which the caller can synchronously
   * say "this is the clean state". Waiting a fixed delay and calling markSaved
   * raced with the operator's first edit and could mark real changes as saved.
   * This defers the decision to the history layer, which knows exactly when the
   * loaded layout has settled into a snapshot.
   */
  markNextAsBaseline: () => void;
  /**
   * Announce that the operator changed something.
   *
   * Cancels a pending baseline: if an edit arrives before the loaded layout has
   * settled into its first snapshot, that snapshot contains the edit and must
   * NOT be treated as the clean state — otherwise the first change made right
   * after opening the editor would be silently considered "already saved".
   */
  noteUserEdit: () => void;
  /** Discard history and start again from the current layout. */
  reset: () => void;
}

function serialise(layout: TemplateLayout): string {
  return JSON.stringify(layout);
}

export function useTemplateHistory(editor: EditorAPI): TemplateHistory {
  const past = useRef<string[]>([]);
  const future = useRef<string[]>([]);
  const present = useRef<string | null>(null);
  const savedSnapshot = useRef<string | null>(null);
  const restoring = useRef(false);
  const baselinePending = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [isDirty, setIsDirty] = useState(false);

  const sync = useCallback(() => {
    setCanUndo(past.current.length > 0);
    setCanRedo(future.current.length > 0);
    setIsDirty(
      present.current !== null && present.current !== savedSnapshot.current,
    );
  }, []);

  /* Record a snapshot whenever the layout settles after a change. */
  useEffect(() => {
    if (restoring.current) return;
    if (timer.current) clearTimeout(timer.current);

    timer.current = setTimeout(() => {
      const snapshot = serialise(editor.getLayout());
      if (snapshot === present.current) return;

      if (baselinePending.current) {
        // First settled state after loading a version: this IS the clean state,
        // so it starts both the history and the saved marker.
        baselinePending.current = false;
        past.current = [];
        future.current = [];
        present.current = snapshot;
        savedSnapshot.current = snapshot;
        sync();
        return;
      }

      if (present.current !== null) {
        past.current = [...past.current, present.current].slice(-MAX_HISTORY);
        // A fresh edit invalidates the redo branch, as in every editor.
        future.current = [];
      }
      present.current = snapshot;
      sync();
    }, DEBOUNCE_MS);

    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
    // `elements` identity changes on every mutation the canvas syncs to state,
    // including drags (object:modified writes back into it).
  }, [editor.elements, editor.backgroundUrl, editor.getLayout, sync]);

  const restore = useCallback(
    (snapshot: string) => {
      restoring.current = true;
      try {
        editor.loadTemplate(JSON.parse(snapshot) as TemplateLayout);
        present.current = snapshot;
      } finally {
        // Release after the debounce window so the restore's own state updates
        // do not queue a snapshot of themselves.
        setTimeout(() => {
          restoring.current = false;
        }, DEBOUNCE_MS + 50);
      }
      sync();
    },
    [editor, sync],
  );

  const undo = useCallback(() => {
    const previous = past.current[past.current.length - 1];
    if (previous === undefined) return;
    past.current = past.current.slice(0, -1);
    if (present.current !== null) {
      future.current = [present.current, ...future.current];
    }
    restore(previous);
  }, [restore]);

  const redo = useCallback(() => {
    const next = future.current[0];
    if (next === undefined) return;
    future.current = future.current.slice(1);
    if (present.current !== null) {
      past.current = [...past.current, present.current];
    }
    restore(next);
  }, [restore]);

  const markSaved = useCallback(() => {
    savedSnapshot.current = present.current ?? serialise(editor.getLayout());
    sync();
  }, [editor, sync]);

  const markNextAsBaseline = useCallback(() => {
    baselinePending.current = true;
  }, []);

  const noteUserEdit = useCallback(() => {
    baselinePending.current = false;
  }, []);

  const reset = useCallback(() => {
    past.current = [];
    future.current = [];
    present.current = null;
    savedSnapshot.current = null;
    baselinePending.current = false;
    sync();
  }, [sync]);

  return {
    canUndo,
    canRedo,
    undo,
    redo,
    isDirty,
    markSaved,
    markNextAsBaseline,
    noteUserEdit,
    reset,
  };
}

/**
 * Warns before leaving with unsaved changes.
 *
 * Covers the browser-level exit (reload, tab close) via `beforeunload`. The
 * in-app navigation case is handled by the editor screen itself, which can show
 * a real dialog instead of the browser's generic one.
 */
export function useUnsavedChangesWarning(active: boolean) {
  useEffect(() => {
    if (!active) return;
    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Browsers ignore custom text now, but a non-empty returnValue is still
      // what triggers the confirmation in several of them.
      event.returnValue = "";
      return "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [active]);
}
