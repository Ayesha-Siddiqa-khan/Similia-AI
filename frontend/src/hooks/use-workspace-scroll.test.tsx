import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useWorkspaceScroll } from "./use-workspace-scroll";

const first = "/workspace/case/example";
const second = "/workspace/books";
const key = `similia.scroll.account:${first}`;
let height: number;
let scrollY: number;
let resize: () => void;
const scrollTo = vi.fn(({ top }: ScrollToOptions) => { scrollY = top ?? 0; });

function Page({ path, account = "account" }: { path: string; account?: string }) {
  return <main ref={useWorkspaceScroll(path, account)} />;
}

function drawFrame() {
  act(() => { vi.advanceTimersToNextFrame(); });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  height = 2000;
  scrollY = 0;
  history.replaceState(null, "", first);
  vi.stubGlobal("scrollTo", scrollTo);
  vi.spyOn(window, "scrollY", "get").mockImplementation(() => scrollY);
  vi.spyOn(document.documentElement, "scrollHeight", "get").mockImplementation(() => height);
  vi.spyOn(document.documentElement, "clientHeight", "get").mockReturnValue(600);
  vi.stubGlobal("ResizeObserver", class {
    constructor(callback: () => void) { resize = callback; }
    observe() {}
    disconnect() {}
  });
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("keeps independent positions when navigating and reopening a page", () => {
  const page = render(<Page path={first} />);
  drawFrame();
  scrollY = 720;
  window.dispatchEvent(new Event("scroll"));

  history.pushState(null, "", second);
  page.rerender(<Page path={second} />);
  drawFrame();
  expect(scrollY).toBe(0);
  expect(localStorage.getItem(key)).toBe("720");
  scrollY = 200;
  window.dispatchEvent(new Event("scroll"));
  page.unmount();

  history.replaceState(null, "", first);
  render(<Page path={first} />);
  drawFrame();
  expect(scrollY).toBe(720);
  expect(localStorage.getItem(`similia.scroll.account:${second}`)).toBe("200");
});

it("waits for a page to grow before restoring a deep scroll position", () => {
  localStorage.setItem(key, "720");
  height = 600;
  render(<Page path={first} />);
  drawFrame();
  window.dispatchEvent(new Event("scroll"));
  expect(scrollTo).not.toHaveBeenCalled();
  expect(localStorage.getItem(key)).toBe("720");

  height = 2000;
  resize();
  drawFrame();
  expect(scrollY).toBe(720);
});

it("uses separate positions for different accounts", () => {
  localStorage.setItem(key, "720");
  render(<Page path={first} account="other" />);
  drawFrame();
  expect(scrollY).toBe(0);
  expect(localStorage.getItem(key)).toBe("720");
});
