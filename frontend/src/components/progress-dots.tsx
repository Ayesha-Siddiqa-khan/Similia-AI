"use client";

import { useEffect, useRef } from "react";

export function ProgressDots() {
  const dots = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const circles = dots.current?.querySelectorAll("circle");
    if (!circles || typeof Element.prototype.animate !== "function") return;
    const animations = Array.from(circles, (circle, index) => circle.animate(
      [{ opacity: 0.3 }, { opacity: 1, offset: 0.35 }, { opacity: 0.3, offset: 0.7 }, { opacity: 0.3 }],
      { duration: 1200, delay: index * 150, easing: "ease-in-out", iterations: Infinity },
    ));
    return () => { animations.forEach((animation) => animation.cancel()); };
  }, []);

  return <svg ref={dots} width="19" height="6" viewBox="0 0 19 6" fill="currentColor" aria-hidden="true">
    <circle cx="2" cy="3" r="2" /><circle cx="9.5" cy="3" r="2" /><circle cx="17" cy="3" r="2" />
  </svg>;
}
