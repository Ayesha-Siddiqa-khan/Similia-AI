/**
 * Public export surface for the speech feature.
 * Follows AGENTS.md rule 7: features only import via index.ts.
 */

export { LocalMicButton } from "./components/local-mic-button";
export type { LocalMicButtonProps } from "./components/local-mic-button";
export { SpeechSettingsPanel } from "./components/speech-settings";
export { useLocalSpeechRecorder } from "./logic/use-local-speech-recorder";
export type { RecorderState } from "./logic/use-local-speech-recorder";
export * from "./types";
export * from "./services/speech-api";
