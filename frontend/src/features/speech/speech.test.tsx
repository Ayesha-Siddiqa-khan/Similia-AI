import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LocalMicButton } from "./components/local-mic-button";
import { SpeechSettingsPanel } from "./components/speech-settings";
import type { ModelValidationResult, SpeechSettings } from "./types";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  delete window.similiaDesktop;
});

function mount(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

const mockSpeechResponse = {
  settings: {
    enabled: true,
    engine: "faster-whisper",
    model_path: "E:\\models\\faster-whisper-large-v3",
    device: "auto",
    compute_type: "int8",
    idle_timeout_seconds: 600,
    default_language: "auto",
    python_executable: "",
  },
  status: {
    status: "ready",
    engine: "faster-whisper",
    model_path: "E:\\models\\faster-whisper-large-v3",
    device: "cpu",
    compute_type: "int8",
    idle_seconds_remaining: 540,
    idle_timeout_seconds: 600,
    memory_rss_mb: 2947.6,
    last_active_timestamp: Date.now() / 1000 - 60,
    error_message: null,
    python_executable: null,
    supported_devices: ["cpu", "cuda", "auto"],
    supported_languages: [
      { code: "auto", label: "Auto-detect" },
      { code: "en", label: "English" },
      { code: "ur", label: "Urdu" },
    ],
  },
};

const selectedPath = "E:\\Model Library — اردو\\faster-whisper-large-v3";

function usePicker(path: string | null) {
  const pickModelFolder = vi.fn(async () => path);
  window.similiaDesktop = {
    isDesktop: true, pickModelFolder, getInfo: vi.fn(), openDataFolder: vi.fn(), openLogsFolder: vi.fn(),
  };
  return pickModelFolder;
}

const modelInput = () => screen.getByRole("textbox", { name: "Local Model Weights Directory" });
const saveButton = () => screen.getByRole("button", { name: "Save Speech Settings" });

describe("LocalMicButton", () => {
  it("renders compact mode with accessible title and icon", () => {
    const onText = vi.fn();
    mount(<LocalMicButton compact label="Voice input" onText={onText} />);
    const button = screen.getByRole("button", { name: /Voice typing/i });
    expect(button).toBeInTheDocument();
    expect(button).toHaveAttribute("title", "Voice input (Local Faster-Whisper)");
  });

  it("renders full mode with language picker and privacy indicator", () => {
    const onText = vi.fn();
    mount(<LocalMicButton compact={false} label="Voice typing" onText={onText} />);
    expect(screen.getByRole("button", { name: /Voice typing/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Speech language/i)).toBeInTheDocument();
    expect(screen.getByText(/Offline & Private • Faster-Whisper/i)).toBeInTheDocument();
  });
});

describe("SpeechSettingsPanel", () => {
  let saved: typeof mockSpeechResponse;
  let rejectWrite: boolean;
  let ignoreWrite: boolean;
  let loadedPath: string | undefined;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/speech/settings")) {
      if (init?.method === "PUT") {
        if (rejectWrite) return Response.json({ detail: "Could not save speech settings." }, { status: 503 });
        if (!ignoreWrite) Object.assign(saved.settings, JSON.parse(String(init.body)) as Partial<SpeechSettings>);
      }
      return Response.json(saved);
    }
    if (url.endsWith("/speech/validate")) {
      return Response.json({
        valid: true, engine: "faster-whisper", model_path: selectedPath,
        size_bytes: 128, size_mb: 0, files_found: [], missing_files: [],
      } satisfies ModelValidationResult);
    }
    if (url.endsWith("/speech/load")) {
      loadedPath = saved.settings.model_path;
      return Response.json(saved);
    }
    throw new Error("Unexpected request");
  });

  beforeEach(() => {
    saved = structuredClone(mockSpeechResponse);
    rejectWrite = false;
    ignoreWrite = false;
    loadedPath = undefined;
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("renders model configuration and live RAM status badge", async () => {
    mount(<SpeechSettingsPanel />);

    await waitFor(() => {
      expect(
        screen.getByText(/Local Speech Recognition \(Faster-Whisper\)/i)
      ).toBeInTheDocument();
    });

    expect(screen.getByText(/Ready \(Loaded\)/i)).toBeInTheDocument();
    expect(screen.getByText(/2947.6 MB/i)).toBeInTheDocument();
    expect(screen.getByText(/Auto-unloading in: 9m 00s/i)).toBeInTheDocument();

    const pathInput = screen.getByDisplayValue("E:\\models\\faster-whisper-large-v3");
    expect(pathInput).toBeInTheDocument();

    const idleTimeout = screen.getByDisplayValue("600");
    expect(idleTimeout).toBeInTheDocument();
  });

  it("uses the native folder picker when the desktop preload is available", async () => {
    const pickModelFolder = usePicker(selectedPath);

    mount(<SpeechSettingsPanel />);
    const browse = await screen.findByRole("button", { name: /Browse/i });
    fireEvent.click(browse);

    await waitFor(() => {
      expect(pickModelFolder).toHaveBeenCalledTimes(1);
      expect(modelInput()).toHaveValue(selectedPath);
    });
    expect(screen.getByText(/Unsaved changes/i)).toBeInTheDocument();
  });

  it("keeps the saved path when Browse is canceled", async () => {
    usePicker(null);
    mount(<SpeechSettingsPanel />);
    const browse = await screen.findByRole("button", { name: /Browse/i });
    fireEvent.click(browse);
    await waitFor(() => expect(browse).toBeEnabled());
    expect(modelInput()).toHaveValue(saved.settings.model_path);
    expect(saveButton()).toBeDisabled();
  });

  it("validates a draft separately and blocks loading until the saved path is confirmed", async () => {
    saved.settings.model_path = "";
    saved.status.status = "unloaded";
    usePicker(selectedPath);
    mount(<SpeechSettingsPanel />);
    expect(await screen.findByText(/choose a model folder and save/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Browse/i }));
    await waitFor(() => expect(modelInput()).toHaveValue(selectedPath));
    fireEvent.click(screen.getByRole("button", { name: "Validate" }));
    expect(await screen.findByText("Valid Faster-Whisper Model Detected")).toBeInTheDocument();
    expect(screen.queryByText(/saved successfully/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Load Model Now" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("sends the selected Unicode path, confirms it with GET, and loads it after remount", async () => {
    saved.status.status = "unloaded";
    usePicker(selectedPath);
    const first = mount(<SpeechSettingsPanel />);
    fireEvent.click(await screen.findByRole("button", { name: /Browse/i }));
    await waitFor(() => expect(saveButton()).toBeEnabled());
    expect(saveButton()).toHaveClass("button", "primary");
    fireEvent.click(saveButton());
    expect(await screen.findByText(/saved successfully/i)).toBeInTheDocument();
    const write = fetchMock.mock.calls.findIndex(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(fetchMock.mock.calls[write][1]?.body))).toEqual({ model_path: selectedPath });
    expect(fetchMock.mock.calls[write + 1][1]?.method).toBe("GET");
    first.unmount();

    mount(<SpeechSettingsPanel />);
    const load = await screen.findByRole("button", { name: "Load Model Now" });
    expect(modelInput()).toHaveValue(selectedPath);
    fireEvent.click(load);
    await waitFor(() => expect(loadedPath).toBe(selectedPath));
  });

  it.each([true, false])("keeps the draft and reports an unsuccessful or unconfirmed save (%s)", async (reject) => {
    rejectWrite = reject;
    ignoreWrite = !reject;
    mount(<SpeechSettingsPanel />);
    const input = await screen.findByRole("textbox", { name: "Local Model Weights Directory" });
    fireEvent.change(input, { target: { value: selectedPath } });
    fireEvent.click(saveButton());
    expect(await screen.findByRole("alert")).toHaveTextContent(reject ? /could not save/i : /did not confirm/i);
    expect(screen.queryByText(/saved successfully/i)).not.toBeInTheDocument();
    expect(input).toHaveValue(selectedPath);
    expect(saveButton()).toBeEnabled();
  });

  it("preserves edits across status refreshes and cannot submit an empty replacement", async () => {
    mount(<SpeechSettingsPanel />);
    const input = await screen.findByRole("textbox", { name: "Local Model Weights Directory" });
    fireEvent.change(input, { target: { value: selectedPath } });
    const calls = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByTitle("Refresh status"));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(calls));
    expect(input).toHaveValue(selectedPath);
    expect(screen.getByText(/Unsaved changes/i)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "  " } });
    expect(saveButton()).toBeDisabled();
  });

  it("does not show the native picker in a browser", async () => {
    mount(<SpeechSettingsPanel />);
    await screen.findByText(/Local Speech Recognition \(Faster-Whisper\)/i);
    expect(screen.queryByRole("button", { name: /Browse/i })).not.toBeInTheDocument();
  });
});
