import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useAutosave } from "./use-autosave";

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

function gate() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

describe("useAutosave", () => {
  it("saves the newest draft after a pause in typing", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useAutosave<string>({ save }));
    act(() => result.current.schedule("a"));
    expect(result.current.state).toBe("dirty");
    act(() => result.current.schedule("ab"));
    await tick(899);
    expect(save).not.toHaveBeenCalled();
    await tick(2);
    expect(save).toHaveBeenCalledTimes(1);
    expect(save).toHaveBeenCalledWith("ab");
    expect(result.current.state).toBe("saved");
  });

  it("never runs two saves at once and sends edits made during a save right after it", async () => {
    const gates: ReturnType<typeof gate>[] = [];
    const seen: string[] = [];
    let active = 0;
    let most = 0;
    const save = vi.fn((value: string) => {
      seen.push(value); active += 1; most = Math.max(most, active);
      const g = gate(); gates.push(g);
      return g.promise.finally(() => { active -= 1; });
    });
    const { result } = renderHook(() => useAutosave<string>({ save }));
    act(() => result.current.schedule("a"));
    await tick(900);
    expect(seen).toEqual(["a"]);
    act(() => result.current.schedule("b")); // typed while "a" is still being sent
    await tick(900); // the debounce fires, but a save is already running
    expect(seen).toEqual(["a"]);
    await act(async () => { gates[0].resolve(); await Promise.resolve(); });
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(seen).toEqual(["a", "b"]);
    await act(async () => { gates[1].resolve(); await vi.advanceTimersByTimeAsync(0); });
    expect(most).toBe(1);
    expect(result.current.state).toBe("saved");
  });

  it("keeps the work, reports the reason and retries by itself after a failure", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("Network down")).mockResolvedValue(undefined);
    const { result } = renderHook(() => useAutosave<string>({ save }));
    act(() => result.current.schedule("a"));
    await tick(900);
    expect(result.current.state).toBe("error");
    expect(result.current.error).toBe("Network down");
    await tick(2000);
    expect(save).toHaveBeenCalledTimes(2);
    expect(save).toHaveBeenLastCalledWith("a");
    expect(result.current.state).toBe("saved");
    expect(result.current.error).toBe("");
  });

  it("retries as soon as the network comes back", async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error("offline")).mockResolvedValue(undefined);
    const { result } = renderHook(() => useAutosave<string>({ save, retryDelaysMs: [60_000] }));
    act(() => result.current.schedule("a"));
    await tick(900);
    expect(result.current.state).toBe("error");
    await act(async () => { window.dispatchEvent(new Event("online")); await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.state).toBe("saved");
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("saveNow flushes at once and fails loudly if the save fails", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useAutosave<string>({ save }));
    act(() => result.current.schedule("a"));
    await act(async () => { await result.current.saveNow(); });
    expect(save).toHaveBeenCalledWith("a"); // no waiting for the pause
    expect(result.current.state).toBe("saved");
    await act(async () => { await result.current.saveNow(); });
    expect(save).toHaveBeenCalledTimes(1); // nothing new to save

    const failing = vi.fn().mockRejectedValue(new Error("boom"));
    const second = renderHook(() => useAutosave<string>({ save: failing }));
    act(() => second.result.current.schedule("x"));
    await act(async () => { await expect(second.result.current.saveNow()).rejects.toThrow("boom"); });
  });

  it("asks the browser to confirm closing the tab while work is unsaved, and stops once saved", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useAutosave<string>({ save }));
    const closing = () => { const event = new Event("beforeunload", { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented; };
    expect(closing()).toBe(false);
    act(() => result.current.schedule("a"));
    expect(closing()).toBe(true);
    await tick(900);
    expect(closing()).toBe(false);
  });

  it("flushes the last edits when the screen is left", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result, unmount } = renderHook(() => useAutosave<string>({ save }));
    act(() => result.current.schedule("last words"));
    unmount();
    expect(save).toHaveBeenCalledWith("last words");
  });

  it("does nothing when switched off (read-only screens)", async () => {
    const save = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() => useAutosave<string>({ save, enabled: false }));
    act(() => result.current.schedule("a"));
    await tick(5000);
    expect(save).not.toHaveBeenCalled();
    await act(async () => { await result.current.saveNow(); });
    expect(result.current.state).toBe("idle");
  });
});
