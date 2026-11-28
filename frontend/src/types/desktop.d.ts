/**
 * API exposed by the Electron preload. Absent in a normal browser.
 * Keep this surface narrow: no generic IPC or Node access.
 */
export {};

declare global {
  interface SimiliaDesktopApi {
    isDesktop: true;
    pickModelFolder(): Promise<string | null>;
    getInfo(): Promise<{ version: string; platform: string; dataDir: string }>;
    openDataFolder(): Promise<void>;
    openLogsFolder(): Promise<void>;
  }

  interface Window {
    similiaDesktop?: SimiliaDesktopApi;
  }
}
