"use client";

import { useState } from "react";
import { AlertCircle, Loader2, Mic, Square, X } from "lucide-react";
import { useLocalSpeechRecorder } from "../logic/use-local-speech-recorder";

export interface LocalMicButtonProps {
  onText: (text: string) => void;
  label?: string;
  compact?: boolean;
  initialLanguage?: string;
  className?: string;
}

export function LocalMicButton({
  onText,
  label = "Voice typing",
  compact = false,
  initialLanguage = "auto",
  className = "",
}: LocalMicButtonProps) {
  const [selectedLang, setSelectedLang] = useState<string>(initialLanguage);

  const {
    isRecording,
    isTranscribing,
    duration,
    error,
    startRecording,
    stopRecording,
    cancelRecording,
    clearError,
  } = useLocalSpeechRecorder({
    onText,
    language: selectedLang,
  });

  const formatTime = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s < 10 ? "0" : ""}${s}`;
  };

  if (compact) {
    return (
      <div className={`inline-flex items-center gap-1.5 ${className}`}>
        {isRecording ? (
          <div className="flex items-center gap-1.5 bg-red-50 border border-red-300 rounded-full px-2 py-0.5 animate-pulse">
            <span className="w-2 h-2 rounded-full bg-red-600 inline-block animate-ping" />
            <span className="text-xs font-mono font-medium text-red-700">
              {formatTime(duration)}
            </span>
            <button
              type="button"
              onClick={() => stopRecording()}
              className="p-1 text-red-600 hover:text-red-800 rounded-full hover:bg-red-100"
              title="Stop and transcribe"
              aria-label="Stop recording"
            >
              <Square size={12} className="fill-current" />
            </button>
            <button
              type="button"
              onClick={cancelRecording}
              className="p-1 text-gray-500 hover:text-gray-700 rounded-full hover:bg-gray-100"
              title="Cancel recording"
              aria-label="Cancel recording"
            >
              <X size={12} />
            </button>
          </div>
        ) : isTranscribing ? (
          <div className="flex items-center gap-1.5 bg-blue-50 border border-blue-200 rounded-full px-2 py-0.5 text-xs text-blue-700">
            <Loader2 size={12} className="animate-spin text-blue-600" />
            <span className="text-xs">Transcribing…</span>
          </div>
        ) : (
          <button
            type="button"
            onClick={startRecording}
            className="p-1.5 text-gray-500 hover:text-primary-600 rounded hover:bg-gray-100 transition-colors"
            title={`${label} (Local Faster-Whisper)`}
            aria-label="Voice typing"
          >
            <Mic size={15} />
          </button>
        )}

        {error && (
          <div className="flex items-center gap-1 text-xs text-red-600 bg-red-50 px-2 py-0.5 rounded border border-red-200 max-w-xs truncate">
            <AlertCircle size={12} className="shrink-0" />
            <span className="truncate">{error}</span>
            <button
              type="button"
              onClick={clearError}
              className="p-0.5 text-red-500 hover:text-red-700"
              aria-label="Dismiss error"
            >
              <X size={10} />
            </button>
          </div>
        )}
      </div>
    );
  }

  // Full view (e.g. for Chief Complaint)
  return (
    <div className={`space-y-1.5 ${className}`}>
      <div className="flex flex-wrap items-center gap-2">
        {isRecording ? (
          <div className="flex items-center gap-2 bg-red-50 border border-red-300 rounded-md px-3 py-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-red-600 inline-block animate-ping" />
            <span className="text-sm font-mono font-medium text-red-700">
              Recording: {formatTime(duration)}
            </span>
            <button
              type="button"
              onClick={() => stopRecording()}
              className="inline-flex items-center gap-1.5 bg-red-600 text-white text-xs px-2.5 py-1 rounded hover:bg-red-700 font-medium"
            >
              <Square size={12} className="fill-current" />
              Done & Transcribe
            </button>
            <button
              type="button"
              onClick={cancelRecording}
              className="text-xs text-gray-600 hover:text-gray-900 px-1.5 py-1"
            >
              Cancel
            </button>
          </div>
        ) : isTranscribing ? (
          <div className="flex items-center gap-2 bg-blue-50 border border-blue-200 rounded-md px-3 py-1.5 text-sm text-blue-700">
            <Loader2 size={16} className="animate-spin text-blue-600" />
            <span>Transcribing locally with Faster-Whisper…</span>
          </div>
        ) : (
          <button
            type="button"
            onClick={startRecording}
            className="inline-flex items-center gap-2 bg-white border border-gray-300 hover:border-primary-500 hover:text-primary-600 text-gray-700 text-sm font-medium px-3 py-1.5 rounded-md shadow-sm transition-colors"
          >
            <Mic size={16} className="text-primary-600" />
            {label}
          </button>
        )}

        <select
          value={selectedLang}
          onChange={(e) => setSelectedLang(e.target.value)}
          disabled={isRecording || isTranscribing}
          className="text-xs border border-gray-300 rounded-md px-2 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-primary-500"
          aria-label="Speech language"
        >
          <option value="auto">Auto (English / اردو)</option>
          <option value="en">English</option>
          <option value="ur">Urdu (اردو)</option>
        </select>

        <span className="text-xs text-gray-500">
          Offline & Private • Faster-Whisper
        </span>
      </div>

      {error && (
        <div className="flex items-center gap-1.5 text-xs text-red-600 bg-red-50 p-2 rounded border border-red-200">
          <AlertCircle size={14} className="shrink-0" />
          <span>{error}</span>
          <button
            type="button"
            onClick={clearError}
            className="ml-auto text-red-500 hover:text-red-700"
            aria-label="Dismiss error"
          >
            <X size={12} />
          </button>
        </div>
      )}
    </div>
  );
}
