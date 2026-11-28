import { render } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ProgressDots } from "./progress-dots";

it("starts staggered opacity animations and cancels them when processing ends", () => {
  const original = Object.getOwnPropertyDescriptor(Element.prototype, "animate");
  const cancel = vi.fn();
  const animate = vi.fn<(frames: Keyframe[], options: KeyframeAnimationOptions) => Pick<Animation, "cancel">>(() => ({ cancel }));
  Object.defineProperty(Element.prototype, "animate", { value: animate, configurable: true });
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  try {
    const { unmount } = render(<ProgressDots />);
    expect(animate.mock.calls.map(([, options]) => options.delay)).toEqual([0, 150, 300]);
    unmount();
    expect(cancel).toHaveBeenCalledTimes(3);
  } finally {
    if (original) Object.defineProperty(Element.prototype, "animate", original);
    else Reflect.deleteProperty(Element.prototype, "animate");
    vi.unstubAllGlobals();
  }
});
