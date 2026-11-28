"use client";

import { useSyncExternalStore, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  CheckCircle2,
  FolderSearch,
  Loader2,
  Mic,
  Power,
  RefreshCw,
  Save,
  Square,
  Zap,
} from "lucide-react";
import { Badge, Notice, Panel } from "@/components/ui";
import {
  fetchSpeechStatus,
  loadSpeechModel,
  transcribeAudio,
  unloadSpeechModel,
  updateSpeechSettings,
  validateModelPath,
} from "../services/speech-api";
import { ModelValidationResult, SpeechSettings } from "../types";

const noopSubscribe = () => () => {};
const speechStatusKey = ["speech-status"] as const;

/**
 * The Electron preload is only present in the desktop app. Reading it through
 * useSyncExternalStore keeps the server render (false) and the hydrated client
 * render consistent without a state update inside an effect.
 */
function useDesktopPickerAvailable(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => Boolean(window.similiaDesktop?.pickModelFolder),
    () => false
  );
}

export function SpeechSettingsPanel() {
  const queryClient = useQueryClient();

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: speechStatusKey,
    queryFn: ({ signal }) => fetchSpeechStatus(signal),
    refetchInterval: (query) => {
      // Poll faster if model is loading or ready to show active idle countdown
      const status = query.state.data?.status?.status;
      return status === "loading" || status === "transcribing"
        ? 2000
        : status === "ready"
        ? 5000
        : 15000;
    },
  });

  const [overrides, setOverrides] = useState<Partial<SpeechSettings>>({});
  const form: SpeechSettings = {
    enabled: true,
    engine: "faster-whisper",
    model_path: "",
    device: "auto",
    compute_type: "auto",
    idle_timeout_seconds: 600,
    default_language: "auto",
    python_executable: "",
    ...(data?.settings ?? {}),
    ...overrides,
  };

  const savedPath = data?.settings.model_path ?? "";
  const pendingSettings = Object.fromEntries(
    (Object.keys(overrides) as (keyof SpeechSettings)[]).flatMap((key) => {
      const value = key === "model_path" ? form.model_path.trim() : form[key];
      return value === data?.settings[key] ? [] : [[key, value]];
    })
  ) as Partial<SpeechSettings>;
  const isDirty = Object.keys(pendingSettings).length > 0;
  const emptyPathEdit = pendingSettings.model_path === "";

  const [validationResult, setValidation] = useState<{ path: string; result: ModelValidationResult } | null>(null);
  const validation = validationResult?.path === form.model_path.trim() ? validationResult?.result : undefined;
  const [validating, setValidating] = useState(false);
  const [successNotice, setSuccessNotice] = useState<string | null>(null);
  const [browseError, setBrowseError] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const desktopPicker = useDesktopPickerAvailable();

  // Test recording state
  const [testRecording, setTestRecording] = useState(false);
  const [testTranscribing, setTestTranscribing] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [mediaRecorder, setMediaRecorder] = useState<MediaRecorder | null>(null);

  const saveMutation = useMutation({
    mutationFn: updateSpeechSettings,
    onMutate: () => queryClient.cancelQueries({ queryKey: speechStatusKey }),
    onSuccess: async (res) => {
      await queryClient.cancelQueries({ queryKey: speechStatusKey });
      queryClient.setQueryData(speechStatusKey, res);
      setOverrides({});
      setSuccessNotice("Speech recognition settings saved successfully.");
    },
  });

  const loadMutation = useMutation({
    mutationFn: loadSpeechModel,
    onSuccess: (res) => queryClient.setQueryData(speechStatusKey, res),
  });

  const unloadMutation = useMutation({
    mutationFn: unloadSpeechModel,
    onSuccess: (res) => {
      queryClient.setQueryData(speechStatusKey, res);
      setSuccessNotice("Speech model unloaded. All host RAM released.");
      setTimeout(() => setSuccessNotice(null), 4000);
    },
  });

  const updateForm = (patch: Partial<SpeechSettings>) => {
    setSuccessNotice(null);
    if (saveMutation.isError) saveMutation.reset();
    if (loadMutation.isError) loadMutation.reset();
    setOverrides((prev) => ({ ...prev, ...patch }));
  };

  const handleValidate = async (pathToValidate?: string) => {
    const target = (pathToValidate ?? form.model_path).trim();
    if (!target) return;
    setValidating(true);
    try {
      const res = await validateModelPath(target);
      setValidation({ path: target, result: res });
    } catch (err) {
      setValidation({ path: target, result: {
        valid: false,
        error: err instanceof Error ? err.message : "Validation failed",
        engine: "faster-whisper",
        model_path: target,
        size_bytes: 0,
        size_mb: 0,
        files_found: [],
        missing_files: [],
      } });
    } finally {
      setValidating(false);
    }
  };

  const handleBrowseModelFolder = async () => {
    setBrowseError(false);
    setBrowsing(true);
    try {
      const picked = await window.similiaDesktop?.pickModelFolder();
      if (picked) {
        updateForm({ model_path: picked });
        setValidation(null);
      }
    } catch {
      setBrowseError(true);
    } finally {
      setBrowsing(false);
    }
  };

  const handleStartTestRecord = async () => {
    setTestError(null);
    setTestResult(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunks.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setTestTranscribing(true);
        try {
          const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
          const res = await transcribeAudio(blob, {
            language: form.default_language,
          });
          setTestResult(res.text || "(No speech detected)");
          void refetch();
        } catch (err) {
          setTestError(err instanceof Error ? err.message : "Test transcription failed.");
        } finally {
          setTestTranscribing(false);
        }
      };
      recorder.start();
      setMediaRecorder(recorder);
      setTestRecording(true);
    } catch (err) {
      setTestError(
        "Microphone error: " + (err instanceof Error ? err.message : String(err))
      );
    }
  };

  const handleStopTestRecord = () => {
    if (mediaRecorder && mediaRecorder.state !== "inactive") {
      mediaRecorder.stop();
    }
    setTestRecording(false);
  };

  if (isLoading) {
    return (
      <Panel title="Local Speech Recognition" description="Offline Voice-to-Text inference">
        <div className="flex items-center gap-2 p-4 text-sm text-gray-500">
          <Loader2 size={16} className="animate-spin text-primary-600" />
          <span>Loading speech engine status…</span>
        </div>
      </Panel>
    );
  }

  if (!data) {
    return (
      <Panel title="Local Speech Recognition">
        <Notice error>Could not read the saved speech settings.</Notice>
        <button type="button" className="button" onClick={() => void refetch()}>Retry</button>
      </Panel>
    );
  }

  const engineStatus = data?.status;
  const isLoaded = engineStatus?.status === "ready" || engineStatus?.status === "transcribing";

  const formatIdleTime = (secs?: number | null) => {
    if (secs === null || secs === undefined) return "N/A";
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}m ${s < 10 ? "0" : ""}${s}s`;
  };

  return (
    <Panel
      title="Local Speech Recognition (Faster-Whisper)"
      description="Offline, privacy-preserving clinical voice typing with 10-minute automatic idle memory release."
    >
      <div className="panel-padding space-y-6">
        {/* Status Bar */}
        <div className="flex flex-wrap items-center justify-between gap-3 p-3.5 bg-gray-50 border border-gray-200 rounded-lg">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold text-gray-800">Status:</span>
            {engineStatus?.status === "ready" && (
              <Badge tone="good">
                <span className="flex items-center gap-1"><CheckCircle2 size={13} /> Ready (Loaded)</span>
              </Badge>
            )}
            {engineStatus?.status === "transcribing" && (
              <Badge tone="good">
                <span className="flex items-center gap-1 animate-pulse"><Loader2 size={13} className="animate-spin" /> Transcribing</span>
              </Badge>
            )}
            {engineStatus?.status === "loading" && (
              <Badge tone="warn">
                <span className="flex items-center gap-1"><Loader2 size={13} className="animate-spin" /> Loading Model…</span>
              </Badge>
            )}
            {engineStatus?.status === "unloaded" && (
              <Badge tone="neutral">
                <span className="flex items-center gap-1"><Power size={13} /> Unloaded (Idle)</span>
              </Badge>
            )}
            {engineStatus?.status === "error" && (
              <Badge tone="bad">
                <span className="flex items-center gap-1"><AlertCircle size={13} /> Error</span>
              </Badge>
            )}

            {/* RAM Footprint */}
            <span className="text-xs text-gray-600 border-l border-gray-300 pl-3">
              <strong>RAM:</strong>{" "}
              {engineStatus?.memory_rss_mb && engineStatus.memory_rss_mb > 0
                ? `${engineStatus.memory_rss_mb} MB`
                : "0 MB (Worker terminated)"}
            </span>

            {/* Idle Countdown */}
            {isLoaded && engineStatus?.idle_seconds_remaining !== null && (
              <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                Auto-unloading in: {formatIdleTime(engineStatus?.idle_seconds_remaining)}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refetch()}
              disabled={isFetching}
              className="p-1.5 text-gray-500 hover:text-gray-700 rounded hover:bg-gray-200"
              title="Refresh status"
            >
              <RefreshCw size={14} className={isFetching ? "animate-spin" : ""} />
            </button>

            {isLoaded ? (
              <button
                type="button"
                onClick={() => unloadMutation.mutate()}
                disabled={unloadMutation.isPending}
                className="text-xs px-2.5 py-1 bg-amber-100 hover:bg-amber-200 text-amber-900 border border-amber-300 rounded font-medium flex items-center gap-1"
              >
                {unloadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Power size={12} />}
                Unload to Free RAM
              </button>
            ) : (
              <button
                type="button"
                onClick={() => loadMutation.mutate()}
                disabled={loadMutation.isPending || saveMutation.isPending || isDirty || !savedPath.trim()}
                className="text-xs px-2.5 py-1 bg-white hover:bg-gray-100 text-gray-800 border border-gray-300 rounded font-medium flex items-center gap-1 shadow-sm"
              >
                {loadMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Zap size={12} />}
                Load Model Now
              </button>
            )}
          </div>
        </div>

        {loadMutation.isError ? <Notice error>{loadMutation.error.message}</Notice> : engineStatus?.error_message && (
          <Notice error>
            Engine error: {engineStatus.error_message}
          </Notice>
        )}

        {!savedPath.trim() && <p>Choose a model folder and save Speech Settings before loading.</p>}

        {/* Configuration Form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!isDirty || emptyPathEdit || browsing || saveMutation.isPending || loadMutation.isPending) return;
            setSuccessNotice(null);
            saveMutation.mutate(pendingSettings);
          }}
          className="space-y-4"
        >
        <fieldset disabled={saveMutation.isPending || loadMutation.isPending || browsing} className="min-w-0 space-y-4">
          {/* Enabled Checkbox */}
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="speech-enabled"
              checked={form.enabled}
              onChange={(e) => updateForm({ enabled: e.target.checked })}
              className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
            />
            <label htmlFor="speech-enabled" className="text-sm font-medium text-gray-900">
              Enable Local Speech-to-Text Recognition
            </label>
          </div>

          {/* Model Directory Path */}
          <div className="space-y-1.5">
            <label htmlFor="speech-model-path" className="block text-sm font-medium text-gray-700">
              Local Model Weights Directory
            </label>
            <p className="text-xs text-gray-500">
              Directory containing Faster-Whisper / CTranslate2 files (<code>model.bin</code>, <code>config.json</code>, <code>tokenizer.json</code>).
            </p>
            <div className="flex flex-wrap gap-2">
              <input
                id="speech-model-path"
                type="text"
                value={form.model_path}
                onChange={(e) => {
                  updateForm({ model_path: e.target.value });
                  setValidation(null);
                }}
                placeholder="C:\Models\faster-whisper-large-v3"
                className="min-w-0 flex-1 basis-full sm:basis-auto text-sm border border-gray-300 rounded-md px-3 py-2 font-mono text-gray-800"
              />
              {desktopPicker && (
                <button
                  type="button"
                  onClick={() => void handleBrowseModelFolder()}
                  className="inline-flex items-center gap-1.5 bg-gray-100 hover:bg-gray-200 border border-gray-300 text-gray-700 px-3 py-2 rounded-md text-sm font-medium transition-colors"
                  title="Choose the Faster-Whisper model folder"
                >
                  <FolderSearch size={15} />
                  Browse…
                </button>
              )}
              <button
                type="button"
                onClick={() => handleValidate()}
                disabled={validating || !form.model_path.trim()}
                className="inline-flex items-center gap-1.5 bg-gray-100 hover:bg-gray-200 border border-gray-300 text-gray-700 px-3 py-2 rounded-md text-sm font-medium transition-colors"
              >
                {validating ? (
                  <Loader2 size={15} className="animate-spin text-primary-600" />
                ) : (
                  <FolderSearch size={15} />
                )}
                Validate
              </button>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" className="button primary"
              disabled={!isDirty || emptyPathEdit || saveMutation.isPending}>
              {saveMutation.isPending ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              Save Speech Settings
            </button>
            {isDirty && <span role="status">Unsaved changes. Save before loading.</span>}
          </div>
          {emptyPathEdit && <Notice error>Choose an existing model folder before saving.</Notice>}
          {browseError && <Notice error>Could not open or read the selected folder. Try Browse again.</Notice>}
          {saveMutation.isError && <Notice error>{saveMutation.error.message}</Notice>}
          {successNotice && <Notice>{successNotice}</Notice>}

          {/* Validation Report */}
          {validation && (
            <div
              className={`p-3 rounded-lg border text-sm ${
                validation.valid
                  ? "bg-green-50 border-green-200 text-green-900"
                  : "bg-red-50 border-red-200 text-red-900"
              }`}
            >
              <div className="flex items-center gap-2 font-semibold">
                {validation.valid ? (
                  <CheckCircle2 size={16} className="text-green-600" />
                ) : (
                  <AlertCircle size={16} className="text-red-600" />
                )}
                <span>
                  {validation.valid
                    ? "Valid Faster-Whisper Model Detected"
                    : "Incompatible or Missing Model"}
                </span>
              </div>
              {validation.valid ? (
                <div className="mt-2 text-xs space-y-1 text-green-800">
                  <p>
                    <strong>Architecture:</strong> {validation.architecture || "Whisper Large V3"} (CTranslate2)
                  </p>
                  <p>
                    <strong>Model Size:</strong> {validation.size_mb} MB ({validation.size_bytes.toLocaleString()} bytes)
                  </p>
                  <p>
                    <strong>Verified Files:</strong> {validation.files_found.join(", ")}
                  </p>
                </div>
              ) : (
                <div className="mt-2 text-xs text-red-700">
                  <p>{validation.error}</p>
                  {validation.missing_files.length > 0 && (
                    <p className="mt-1 font-mono">
                      Missing required files: {validation.missing_files.join(", ")}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Hardware & Execution Controls */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600 mb-1">
                Execution Device
              </label>
              <select
                value={form.device}
                onChange={(e) => updateForm({ device: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md p-2 bg-white text-gray-800"
              >
                <option value="auto">Auto (Detect best hardware)</option>
                <option value="cpu">CPU (Multi-threaded)</option>
                <option value="cuda">CUDA GPU (NVIDIA Acceleration)</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600 mb-1">
                Compute Precision
              </label>
              <select
                value={form.compute_type}
                onChange={(e) => updateForm({ compute_type: e.target.value })}
                className="w-full text-sm border border-gray-300 rounded-md p-2 bg-white text-gray-800"
              >
                <option value="auto">Auto (Recommended: int8 / float16)</option>
                <option value="int8">int8 (Optimized for CPU)</option>
                <option value="float16">float16 (Optimized for GPU)</option>
                <option value="float32">float32 (High precision CPU)</option>
                <option value="default">default</option>
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase text-gray-600 mb-1">
                Idle Unload Timeout
              </label>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  min="30"
                  max="3600"
                  step="30"
                  value={form.idle_timeout_seconds}
                  onChange={(e) =>
                    updateForm({
                      idle_timeout_seconds: parseInt(e.target.value, 10) || 600,
                    })
                  }
                  className="w-full text-sm border border-gray-300 rounded-md p-2 text-gray-800"
                />
                <span className="text-xs text-gray-500 whitespace-nowrap">seconds</span>
              </div>
              <p className="text-[11px] text-gray-500 mt-0.5">
                Default: 600s (10 min). Completely frees RAM when idle.
              </p>
            </div>
          </div>

          {/* Language Selection */}
          <div className="pt-2">
            <label className="block text-xs font-semibold uppercase text-gray-600 mb-1">
              Default Speech Language
            </label>
            <select
              value={form.default_language}
              onChange={(e) => updateForm({ default_language: e.target.value })}
              className="max-w-xs text-sm border border-gray-300 rounded-md p-2 bg-white text-gray-800"
            >
              <option value="auto">Auto-detect (English / Urdu)</option>
              <option value="en">English</option>
              <option value="ur">Urdu (اردو)</option>
            </select>
            <p className="text-[11px] text-gray-500 mt-1">
              Urdu speech is transcribed directly into Urdu script without translation.
            </p>
          </div>

        </fieldset>
        </form>

        {/* Test Speech Console */}
        <div className="p-4 bg-primary-50/40 border border-primary-200 rounded-lg space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold text-gray-900">
                Microphone & Transcription Test
              </h3>
              <p className="text-xs text-gray-600">
                Record a test utterance to verify that the local Faster-Whisper model transcribes properly.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {testRecording ? (
              <button
                type="button"
                onClick={handleStopTestRecord}
                className="inline-flex items-center gap-1.5 bg-red-600 text-white text-xs px-3 py-1.5 rounded-md hover:bg-red-700 font-medium animate-pulse"
              >
                <Square size={13} className="fill-current" />
                Stop Test Recording
              </button>
            ) : testTranscribing ? (
              <div className="inline-flex items-center gap-2 text-xs text-blue-700 bg-blue-100 px-3 py-1.5 rounded-md font-medium">
                <Loader2 size={14} className="animate-spin text-blue-600" />
                Transcribing test audio locally…
              </div>
            ) : (
              <button
                type="button"
                onClick={handleStartTestRecord}
                disabled={isDirty || saveMutation.isPending || !savedPath.trim()}
                className="inline-flex items-center gap-1.5 bg-white border border-gray-300 text-gray-800 text-xs px-3 py-1.5 rounded-md hover:bg-gray-50 font-medium shadow-sm"
              >
                <Mic size={14} className="text-primary-600" />
                Start Test Recording
              </button>
            )}

            <span className="text-xs text-gray-500">
              Language: {form.default_language === "ur" ? "Urdu" : form.default_language === "en" ? "English" : "Auto"}
            </span>
          </div>

          {testError && (
            <div className="text-xs text-red-600 bg-red-50 p-2 rounded border border-red-200">
              {testError}
            </div>
          )}

          {testResult && (
            <div className="bg-white p-3 rounded border border-gray-200 space-y-1">
              <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">
                Recognized Text:
              </span>
              <p className="text-sm text-gray-900">{testResult}</p>
            </div>
          )}
        </div>
      </div>
    </Panel>
  );
}
