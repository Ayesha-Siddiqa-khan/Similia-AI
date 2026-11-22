import { useCallback, useSyncExternalStore } from "react";

// A small browser-side preference (for example "show Urdu"). It reads localStorage without
// hydration mismatches, stays in sync across components and tabs, and still works for the current
// page if storage is blocked (private windows, strict settings).
const CHANGED = "similia:pref-changed";
const fallbackStore = new Map<string, string>();

function subscribe(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(CHANGED, onChange);
  return () => { window.removeEventListener("storage", onChange); window.removeEventListener(CHANGED, onChange); };
}

export function useLocalPref(key: string, defaultValue: string): [string, (value: string) => void] {
  const read = () => {
    try { return localStorage.getItem(key) ?? defaultValue; } catch { return fallbackStore.get(key) ?? defaultValue; }
  };
  const value = useSyncExternalStore(subscribe, read, () => defaultValue);
  const write = useCallback((next: string) => {
    try { localStorage.setItem(key, next); } catch { fallbackStore.set(key, next); }
    window.dispatchEvent(new Event(CHANGED));
  }, [key]);
  return [value, write];
}
