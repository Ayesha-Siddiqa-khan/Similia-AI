"use strict";

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("similiaSetup", {
  bootstrap: () => ipcRenderer.invoke("similia:setup:bootstrap"),
  save: (values) => ipcRenderer.invoke("similia:setup:save", values),
  importBackend: () => ipcRenderer.invoke("similia:setup:import"),
  cancel: () => ipcRenderer.invoke("similia:setup:cancel"),
});
