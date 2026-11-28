"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { transcribeAudio } from "../services/speech-api";
import { TranscriptionResult } from "../types";

export type RecorderState = "idle" | "recording" | "transcribing" | "error";

interface UseLocalSpeechRecorderOptions {
  onText?: (text: string) => void;
  language?: string;
  initialPrompt?: string;
}

export function useLocalSpeechRecorder({
  onText,
  language = "auto",
  initialPrompt,
}: UseLocalSpeechRecorderOptions = {}) {
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [duration, setDuration] = useState<number>(0);
  const [lastResult, setLastResult] = useState<TranscriptionResult | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onTextRef = useRef(onText);
  useEffect(() => {
    onTextRef.current = onText;
  }, [onText]);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const releaseStream = useCallback(() => {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      clearTimer();
      releaseStream();
    };
  }, [clearTimer, releaseStream]);

  const startRecording = useCallback(async () => {
    setError(null);
    setDuration(0);
    audioChunksRef.current = [];

    if (
      typeof window === "undefined" ||
      !navigator.mediaDevices ||
      !navigator.mediaDevices.getUserMedia
    ) {
      setError("Microphone recording is not supported in this browser.");
      setState("error");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      mediaStreamRef.current = stream;

      // Select supported audio mime type
      let mimeType = "";
      const candidates = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/ogg;codecs=opus",
        "audio/mp4",
      ];
      for (const candidate of candidates) {
        if (MediaRecorder.isTypeSupported(candidate)) {
          mimeType = candidate;
          break;
        }
      }

      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined
      );
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstart = () => {
        setState("recording");
        setDuration(0);
        clearTimer();
        timerRef.current = setInterval(() => {
          setDuration((prev) => prev + 1);
        }, 1000);
      };

      recorder.start(250); // Collect slices every 250ms
    } catch (err: unknown) {
      releaseStream();
      setState("error");
      const errName = (err as { name?: string }).name;
      if (errName === "NotAllowedError" || errName === "PermissionDeniedError") {
        setError(
          "Microphone access was denied. Please allow microphone permissions in your browser."
        );
      } else if (errName === "NotFoundError" || errName === "DevicesNotFoundError") {
        setError("No microphone was detected on this device.");
      } else {
        setError("Could not access microphone: " + (err instanceof Error ? err.message : String(err)));
      }
    }
  }, [clearTimer, releaseStream]);

  const stopRecording = useCallback(async () => {
    clearTimer();
    const recorder = mediaRecorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      setState("idle");
      releaseStream();
      return;
    }

    setState("transcribing");

    return new Promise<void>((resolve) => {
      recorder.onstop = async () => {
        releaseStream();
        try {
          const mimeType = recorder.mimeType || "audio/webm";
          const audioBlob = new Blob(audioChunksRef.current, { type: mimeType });
          audioChunksRef.current = [];

          if (audioBlob.size < 500) {
            setError("Recording was too short. Please speak and try again.");
            setState("error");
            resolve();
            return;
          }

          const result = await transcribeAudio(audioBlob, {
            language,
            initialPrompt,
          });

          setLastResult(result);
          if (result.text && onTextRef.current) {
            onTextRef.current(result.text);
          }
          setState("idle");
        } catch (err: unknown) {
          setState("error");
          setError(
            err instanceof Error
              ? err.message
              : "Transcription failed. Check local speech model in Settings."
          );
        } finally {
          resolve();
        }
      };

      recorder.stop();
    });
  }, [clearTimer, releaseStream, language, initialPrompt]);

  const cancelRecording = useCallback(() => {
    clearTimer();
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    audioChunksRef.current = [];
    releaseStream();
    setState("idle");
    setError(null);
  }, [clearTimer, releaseStream]);

  return {
    state,
    error,
    duration,
    lastResult,
    isRecording: state === "recording",
    isTranscribing: state === "transcribing",
    startRecording,
    stopRecording,
    cancelRecording,
    clearError: () => setError(null),
  };
}
