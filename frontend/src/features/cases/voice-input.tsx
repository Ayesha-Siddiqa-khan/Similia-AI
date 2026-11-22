"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Mic, MicOff } from "lucide-react";
import { useLocalPref } from "@/lib/use-local-pref";

// Voice typing uses the browser's own speech recognition (Chrome, Edge, Safari). The AI key is not
// involved: Anthropic's API does not transcribe audio. Audio goes to the browser vendor's speech
// service, so the UI says so and the doctor decides per use.
const VOICE_KEY = "similia.voice-language";
export type VoiceLang = "en-US" | "ur-PK";

interface RecognitionResult { isFinal: boolean; 0: { transcript: string } }
interface RecognitionEvent { resultIndex: number; results: ArrayLike<RecognitionResult> }
interface Recognition {
  lang: string; continuous: boolean; interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void; stop: () => void;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}
const noopSubscribe = () => () => {};

export const voiceErrors: Record<string, string> = {
  "not-allowed": "Microphone access is blocked. Allow the microphone for this site in the browser's address bar, then try again.",
  "service-not-allowed": "Microphone access is blocked. Allow the microphone for this site in the browser's address bar, then try again.",
  "no-speech": "No speech was heard. Press the microphone and try again.",
  "audio-capture": "No microphone was found. Connect one and try again.",
  network: "The speech service could not be reached. Check your internet connection.",
  "language-not-supported": "This browser does not support voice typing in that language.",
};

interface Props {
  /** Receives each finished phrase of dictated text. */
  onText: (text: string) => void;
  label?: string;
  /** Compact: icon only, uses the saved language. Full: adds the English/Urdu picker and privacy note. */
  compact?: boolean;
}

export function MicButton({ onText, label = "Voice typing", compact = false }: Props) {
  const supported = useSyncExternalStore(noopSubscribe, () => recognitionCtor() !== null, () => false);
  const [listening, setListening] = useState(false);
  const [langPref, setLangPref] = useLocalPref(VOICE_KEY, "en-US");
  const lang: VoiceLang = langPref === "ur-PK" ? "ur-PK" : "en-US";
  const [interim, setInterim] = useState("");
  const [error, setError] = useState("");
  const active = useRef<Recognition | null>(null);
  const onTextRef = useRef(onText);
  useEffect(() => { onTextRef.current = onText; });
  useEffect(() => () => { active.current?.stop(); }, []);

  function stop() { active.current?.stop(); }
  function start() {
    const Ctor = recognitionCtor();
    if (!Ctor) return;
    setError(""); setInterim("");
    const recognition = new Ctor();
    recognition.lang = lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let partial = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0].transcript;
        if (result.isFinal) { const clean = text.trim(); if (clean) onTextRef.current(clean); } else partial += text;
      }
      setInterim(partial);
    };
    recognition.onerror = (event) => setError(voiceErrors[event.error] ?? "Voice typing stopped unexpectedly. Try again.");
    recognition.onend = () => { setListening(false); setInterim(""); active.current = null; };
    active.current = recognition;
    try { recognition.start(); setListening(true); } catch { setError("Voice typing could not start. Try again."); active.current = null; }
  }

  if (!supported) return compact ? null : <p className="fine-print">Voice typing needs a browser with speech recognition, such as Chrome or Edge.</p>;
  return (
    <div className={`mic ${compact ? "mic-compact" : ""}`}>
      <button type="button" className={`mic-btn ${listening ? "listening" : ""}`} onClick={listening ? stop : start} aria-pressed={listening} aria-label={listening ? "Stop voice typing" : label} title={listening ? "Stop voice typing" : label}>
        {listening ? <MicOff size={16} aria-hidden /> : <Mic size={16} aria-hidden />}{!compact && (listening ? "Stop" : label)}
      </button>
      {!compact && (
        <select aria-label="Voice language" value={lang} disabled={listening} onChange={(e) => setLangPref(e.target.value)}>
          <option value="en-US">English</option>
          <option value="ur-PK">اردو (Urdu)</option>
        </select>
      )}
      {listening && <span className="mic-live" role="status">Listening… {interim}</span>}
      {error && <span className="field-error" role="alert">{error}</span>}
      {!compact && <span className="fine-print">Audio is processed by your browser&apos;s speech service (for example Google in Chrome). Use it only with the patient&apos;s agreement.</span>}
    </div>
  );
}
