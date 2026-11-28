"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("similiaDesktop", {
  isDesktop: true,
  pickModelFolder: () => ipcRenderer.invoke("similia:pick-model-folder"),
  getInfo: () => ipcRenderer.invoke("similia:info"),
  openDataFolder: () => ipcRenderer.invoke("similia:open-data-folder"),
  openLogsFolder: () => ipcRenderer.invoke("similia:open-logs-folder"),
});
