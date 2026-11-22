"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export type AutosaveState = "idle" | "dirty" | "saving" | "saved" | "error";

interface Options<T> {
  /** Sends the whole draft to the server. Must throw if the save failed. */
  save: (value: T) => Promise<void>;
  /** Read-only screens (for example a signed-off case) turn saving off. */
  enabled?: boolean;
  delayMs?: number;
  /** Waits (ms) before each automatic retry after a failure; the last value repeats. */
  retryDelaysMs?: number[];
  /** Return false for a failure that retrying cannot fix (for example a read-only record): no automatic retry is scheduled. */
  shouldRetry?: (failure: unknown) => boolean;
}

/**
 * Reliable autosave for a draft:
 *  - one save at a time, always sending the NEWEST draft (an old save can never overwrite a newer one);
 *  - edits made while a save is running are sent right after it;
 *  - a failed save retries by itself (and when the network comes back) and keeps the work unsaved;
 *  - `saveNow()` flushes immediately (used before analysis) and rejects if the save fails;
 *  - leaving the page flushes the draft, and closing the tab with unsaved work asks for confirmation.
 */
export function useAutosave<T>({ save, enabled = true, delayMs = 900, retryDelaysMs = [2000, 5000, 10000, 30000], shouldRetry }: Options<T>) {
  const [state, setState] = useState<AutosaveState>("idle");
  const [error, setError] = useState("");
  const latest = useRef<T | undefined>(undefined);
  const dirty = useRef(false);
  const running = useRef<Promise<void> | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const attempt = useRef(0);
  const saveRef = useRef(save);
  const enabledRef = useRef(enabled);
  const retryDelays = useRef(retryDelaysMs);
  const shouldRetryRef = useRef(shouldRetry);
  const runRef = useRef<() => Promise<void>>(() => Promise.resolve());
  useEffect(() => { saveRef.current = save; enabledRef.current = enabled; retryDelays.current = retryDelaysMs; shouldRetryRef.current = shouldRetry; });

  const clearTimers = () => { clearTimeout(timer.current); clearTimeout(retryTimer.current); };

  const run = useCallback((): Promise<void> => {
    if (running.current) return running.current;
    clearTimers();
    const task = (async () => {
      while (dirty.current && enabledRef.current) {
        const snapshot = latest.current as T;
        dirty.current = false; // edits made while saving set it again and are sent next
        setState("saving");
        try {
          await saveRef.current(snapshot);
          attempt.current = 0;
        } catch (failure) {
          dirty.current = true; // still unsaved
          setState("error");
          setError(failure instanceof Error ? failure.message : "The save failed");
          if (shouldRetryRef.current?.(failure) !== false) {
            const delays = retryDelays.current;
            const wait = delays[Math.min(attempt.current, delays.length - 1)] ?? 30000;
            attempt.current += 1;
            retryTimer.current = setTimeout(() => { runRef.current().catch(() => {}); }, wait);
          }
          throw failure;
        }
      }
      setError("");
      setState("saved");
    })();
    const tracked = task.finally(() => { running.current = null; });
    running.current = tracked;
    return tracked;
  }, []);
  useEffect(() => { runRef.current = run; }, [run]);

  /** Call whenever the draft changes, with the complete newest draft. */
  const schedule = useCallback((value: T) => {
    if (!enabledRef.current) return;
    latest.current = value;
    dirty.current = true;
    if (!running.current) setState("dirty");
    clearTimeout(timer.current);
    clearTimeout(retryTimer.current);
    timer.current = setTimeout(() => { run().catch(() => {}); }, delayMs);
  }, [delayMs, run]);

  /** Save everything now. Resolves when nothing is left unsaved; rejects if the save fails. */
  const saveNow = useCallback((): Promise<void> => {
    if (!enabledRef.current || (!dirty.current && !running.current)) return Promise.resolve();
    return run();
  }, [run]);

  // Back online after a failure: try again at once.
  useEffect(() => {
    const retry = () => { if (dirty.current && !running.current) run().catch(() => {}); };
    window.addEventListener("online", retry);
    return () => window.removeEventListener("online", retry);
  }, [run]);

  // Closing or reloading the tab with unsaved work asks the browser to confirm.
  const unsaved = state === "dirty" || state === "saving" || state === "error";
  useEffect(() => {
    if (!unsaved) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [unsaved]);

  // Leaving this screen flushes the last edits instead of dropping them.
  useEffect(() => () => {
    clearTimers();
    if (dirty.current && enabledRef.current) run().catch(() => {});
  }, [run]);

  return { state, error, schedule, saveNow };
}
