import { useEffect, useRef } from "react";

export function useWorkspaceScroll(pathname: string, accountId: string) {
  const main = useRef<HTMLElement>(null);

  useEffect(() => {
    const previous = history.scrollRestoration;
    history.scrollRestoration = "manual";
    return () => { history.scrollRestoration = previous; };
  }, []);

  useEffect(() => {
    const key = `similia.scroll.${accountId}:${pathname}`;
    const content = main.current;
    let saved = 0;
    try { saved = Number(localStorage.getItem(key)); } catch { /* Storage can be blocked. */ }
    const target = Number.isFinite(saved) && saved > 0 ? saved : 0;
    let restoring = !window.location.hash;
    let frame = 0;
    let position = target;
    let writeTimer: ReturnType<typeof setTimeout> | undefined;
    const interactionEvents = ["wheel", "touchstart", "pointerdown", "keydown"] as const;

    function stopRestoring() {
      restoring = false;
      observer.disconnect();
      window.removeEventListener("resize", scheduleRestore);
      for (const event of interactionEvents) window.removeEventListener(event, stopRestoring);
    }

    function scheduleRestore() {
      if (!restoring || frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        if (!restoring || window.location.pathname !== pathname) return;
        const viewport = document.scrollingElement ?? document.documentElement;
        // A loading placeholder may be shorter than the previous page position.
        if (target > Math.max(0, viewport.scrollHeight - viewport.clientHeight)) return;
        window.scrollTo({ top: target, behavior: "instant" });
        stopRestoring();
      });
    }

    function flush() {
      if (writeTimer === undefined) return;
      clearTimeout(writeTimer);
      writeTimer = undefined;
      try { localStorage.setItem(key, String(position)); } catch { /* Storage can be blocked. */ }
    }

    function trackScroll() {
      if (restoring || window.location.pathname !== pathname || window.scrollY === position) return;
      position = window.scrollY;
      writeTimer ??= setTimeout(flush, 100);
    }

    const observer = new ResizeObserver(scheduleRestore);
    if (restoring) {
      if (content) observer.observe(content);
      window.addEventListener("resize", scheduleRestore);
      // Respect any new interaction instead of scrolling under the user when data arrives.
      for (const event of interactionEvents) window.addEventListener(event, stopRestoring, { passive: true });
      scheduleRestore();
    }
    window.addEventListener("scroll", trackScroll, { passive: true });
    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", flush);

    return () => {
      stopRestoring();
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", trackScroll);
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", flush);
      flush();
    };
  }, [accountId, pathname]);

  return main;
}
