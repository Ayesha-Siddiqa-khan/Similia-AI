"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {
  app,
  BrowserWindow,
  Menu,
  dialog,
  ipcMain,
  protocol,
  session,
  shell,
} = require("electron");

const {
  ensureDirectories,
  loadConfig,
  paths,
  publicConfig,
  readBuildMetadata,
  saveConfig,
} = require("./lib/config");
const { validateConfig } = require("./lib/env");
const { importBackendConfig, readLocalEnv } = require("./lib/project-config");
const {
  applicationWebPreferences, developerToolsMenuItems,
  applySessionHardening, hardenWebContents, isAllowedSender,
} = require("./lib/security");
const { ServiceManager } = require("./lib/services");

const SMOKE = app.isPackaged && readBuildMetadata().offlineTest === true &&
  process.env.SIMILIA_SMOKE_TEST === "1";
const DEV = !app.isPackaged;
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const RESOURCES = app.isPackaged
  ? process.resourcesPath
  : path.join(REPO_ROOT, "desktop", "resources");
const FONT_DIR = app.isPackaged
  ? path.join(process.resourcesPath, "assets")
  : path.join(REPO_ROOT, "frontend", "public", "fonts");
const SHELL_SCHEME = "similia-ui";
const SHELL_ORIGIN = `${SHELL_SCHEME}://local`;
const SETUP_URL = `${SHELL_ORIGIN}/setup.html`;
const SPLASH_URL = `${SHELL_ORIGIN}/splash.html`;
const SHELL_ASSETS = new Map([
  [SETUP_URL, ["setup.html", "text/html"]],
  [SPLASH_URL, ["splash.html", "text/html"]],
  [`${SHELL_ORIGIN}/setup.js`, ["setup.js", "text/javascript"]],
]);
protocol.registerSchemesAsPrivileged([
  { scheme: SHELL_SCHEME, privileges: { standard: true, secure: true } },
]);

app.setName("Similia AI");
const userData = SMOKE
  ? process.env.SIMILIA_SMOKE_USER_DATA || path.join(os.tmpdir(), `similia-smoke-${process.pid}`)
  : path.join(app.getPath("appData"), "Similia AI");
fs.mkdirSync(userData, { recursive: true });
app.setPath("userData", userData);

let mainWindow = null;
let splashWindow = null;
let setupWindow = null;
let pendingSetup = null;
let serviceManager = null;
let appOrigin = "";
let isQuitting = false;
let startupRunning = false;
let exitCode = 0;
const appContents = new Set();

const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });
}

function smokeResult(result) {
  if (!SMOKE) return;
  const output =
    process.env.SIMILIA_SMOKE_OUTPUT || path.join(os.tmpdir(), "similia-smoke-result.json");
  try {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
  } catch {
    // Smoke output is best effort.
  }
}

function fatal(error) {
  const message = error instanceof Error ? error.message : String(error);
  if (isQuitting) return;
  exitCode = 1;
  if (SMOKE) {
    smokeResult({ ok: false, error: message, logs: paths().logs });
    app.quit();
    return;
  }
  dialog.showErrorBox(
    "Similia AI could not start",
    `${message}\n\nLogs: ${paths().logs}`
  );
  app.quit();
}

function setSplashStatus(text) {
  if (!splashWindow || splashWindow.isDestroyed()) return;
  const encoded = JSON.stringify(text);
  splashWindow.webContents
    .executeJavaScript(
      `document.getElementById('status').textContent = ${encoded};`,
      true
    )
    .catch(() => {});
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 460,
    height: 300,
    frame: false,
    resizable: false,
    closable: false,
    show: true,
    backgroundColor: "#0f172a",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  splashWindow.on("closed", () => {
    splashWindow = null;
  });
  return splashWindow.loadURL(SPLASH_URL);
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) splashWindow.destroy();
}

function isSetupSender(event) {
  try {
    return setupWindow && event.sender === setupWindow.webContents && event.senderFrame &&
      event.senderFrame === event.sender.mainFrame && event.senderFrame.url === SETUP_URL;
  } catch {
    return false;
  }
}

async function currentConfigOrEmpty() {
  const config = await loadConfig({ smoke: SMOKE });
  const build = readBuildMetadata();
  return config && (!app.isPackaged ||
    (config.supabaseUrl === build.supabaseUrl && config.supabasePublishableKey === build.supabasePublishableKey))
    ? config : {};
}

function finishSetup() {
  if (pendingSetup) {
    pendingSetup.resolve(true);
    pendingSetup = null;
  }
  if (setupWindow && !setupWindow.isDestroyed()) setupWindow.close();
  return { ok: true };
}

function registerIpc() {
  ipcMain.handle("similia:pick-model-folder", async (event) => {
    if (!isAllowedSender(event, mainWindow, appOrigin)) throw new Error("Not allowed");
    const result = await dialog.showOpenDialog(mainWindow, {
      title: "Select a Faster-Whisper model folder",
      buttonLabel: "Use this folder",
      properties: ["openDirectory"],
    });
    if (result.canceled || !result.filePaths[0]) return null;
    const selected = result.filePaths[0];
    const stat = await fs.promises.stat(selected);
    return stat.isDirectory() ? selected : null;
  });

  ipcMain.handle("similia:info", (event) => {
    if (!isAllowedSender(event, mainWindow, appOrigin)) throw new Error("Not allowed");
    return {
      version: app.getVersion(),
      platform: process.platform,
      dataDir: paths().data,
    };
  });

  ipcMain.handle("similia:open-data-folder", async (event) => {
    if (!isAllowedSender(event, mainWindow, appOrigin)) throw new Error("Not allowed");
    await shell.openPath(paths().data);
  });

  ipcMain.handle("similia:open-logs-folder", async (event) => {
    if (!isAllowedSender(event, mainWindow, appOrigin)) throw new Error("Not allowed");
    await shell.openPath(paths().logs);
  });

  ipcMain.handle("similia:setup:bootstrap", async (event) => {
    if (!isSetupSender(event)) throw new Error("Not allowed");
    const config = await currentConfigOrEmpty();
    return {
      build: readBuildMetadata(),
      config: publicConfig(config),
      paths: paths(),
      hasConfig: Boolean(config.supabaseUrl),
    };
  });

  ipcMain.handle("similia:setup:import", async (event) => {
    if (!isSetupSender(event)) throw new Error("Not allowed");
    const build = readBuildMetadata();
    if (!app.isPackaged || build.offlineTest !== false) {
      return { ok: false, errors: { form: "Import is available in the personal installer." } };
    }
    const owner = setupWindow;
    const selection = await dialog.showOpenDialog(owner, {
      title: "Select Similia AI's existing backend .env file",
      properties: ["openFile", "showHiddenFiles", "dontAddToRecent"],
    });
    if (selection.canceled || !selection.filePaths[0] || !isSetupSender(event)) return { canceled: true };
    const file = selection.filePaths[0];
    if (path.basename(file).toLowerCase() !== ".env") {
      return { ok: false, errors: { form: "Select the backend .env file." } };
    }
    const confirmation = await dialog.showMessageBox(owner, {
      type: "question",
      message: "Import credentials for your Windows account?",
      detail: "Similia AI will read the selected .env file and replace the saved backend settings for this project. Windows will encrypt the imported secrets.",
      buttons: ["Cancel", "Import and start"],
      defaultId: 0,
      cancelId: 0,
      noLink: true,
    });
    if (confirmation.response !== 1 || !isSetupSender(event)) return { canceled: true };
    let imported;
    try {
      imported = importBackendConfig(readLocalEnv(file), build);
    } catch (error) {
      return { ok: false, errors: { form: error.message } };
    }
    try {
      const existing = await currentConfigOrEmpty();
      if (!isSetupSender(event)) return { canceled: true };
      await saveConfig({ ...existing, ...imported });
    } catch {
      return { ok: false, errors: { form: "Windows could not save the encrypted configuration." } };
    }
    return finishSetup();
  });

  ipcMain.handle("similia:setup:save", async (event, payload) => {
    if (!isSetupSender(event)) throw new Error("Not allowed");
    const existing = await currentConfigOrEmpty();
    if (!isSetupSender(event)) return { canceled: true };
    const build = readBuildMetadata();
    const text = (value) => typeof value === "string" && value.length <= 4096 ? value.trim() : "";
    // The browser bundle inlines NEXT_PUBLIC_SUPABASE_* at build time, so the
    // project must stay the one this installer was built for. Prefer build
    // metadata over anything typed, to avoid a mismatch that breaks sign-in.
    const merged = {
      ...existing,
      supabaseUrl: text(build.supabaseUrl) || text(payload?.supabaseUrl) || text(existing.supabaseUrl),
      supabasePublishableKey:
        text(build.supabasePublishableKey) ||
        text(payload?.supabasePublishableKey) ||
        text(existing.supabasePublishableKey),
      supabaseSecretKey:
        text(payload?.supabaseSecretKey) || text(existing.supabaseSecretKey),
      appEncryptionKey:
        text(payload?.appEncryptionKey) ||
        text(existing.appEncryptionKey),
      voyageApiKey: text(payload?.voyageApiKey) || text(existing.voyageApiKey),
      anthropicApiKey: text(payload?.anthropicApiKey) || text(existing.anthropicApiKey),
      anthropicModel: text(payload?.anthropicModel) || text(existing.anthropicModel),
      clinicalWorkflowEnabled: payload?.clinicalWorkflowEnabled === true,
      modelPath: text(existing.modelPath),
    };
    const validation = validateConfig(merged);
    if (!validation.ok) return { ok: false, errors: validation.errors };
    try {
      await saveConfig(merged);
    } catch {
      return { ok: false, errors: { form: "Windows could not save the encrypted configuration." } };
    }
    return finishSetup();
  });

  ipcMain.handle("similia:setup:cancel", (event) => {
    if (!isSetupSender(event)) throw new Error("Not allowed");
    if (pendingSetup) {
      pendingSetup.resolve(false);
      pendingSetup = null;
    }
    if (setupWindow && !setupWindow.isDestroyed()) setupWindow.close();
    return { ok: true };
  });
}

function showSetup() {
  if (setupWindow && !setupWindow.isDestroyed()) {
    setupWindow.focus();
    return Promise.resolve(false);
  }
  return new Promise((resolve) => {
    pendingSetup = { resolve };
    setupWindow = new BrowserWindow({
      width: 780,
      height: 860,
      minWidth: 640,
      minHeight: 700,
      title: "Similia AI — Configuration",
      show: false,
      backgroundColor: "#0f172a",
      autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, "setup-preload.js"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        devTools: DEV,
      },
    });
    setupWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    setupWindow.webContents.on("will-navigate", (event) => event.preventDefault());
    setupWindow.webContents.on("will-redirect", (event) => event.preventDefault());
    setupWindow.loadURL(SETUP_URL).catch(fatal);
    setupWindow.once("ready-to-show", () => setupWindow.show());
    setupWindow.on("closed", () => {
      setupWindow = null;
      if (pendingSetup) {
        pendingSetup.resolve(false);
        pendingSetup = null;
      }
    });
  });
}

function createMainWindow(origin) {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1100,
    minHeight: 720,
    show: false,
    title: "Similia AI",
    backgroundColor: "#f8fafc",
    autoHideMenuBar: false,
    webPreferences: {
      ...applicationWebPreferences,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  const id = mainWindow.webContents.id;
  appContents.add(id);
  hardenWebContents(mainWindow.webContents, origin, openLocalWindow);
  applySessionHardening(
    session.defaultSession, mainWindow.webContents, appContents, origin, serviceManager.rendererToken
  );
  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    closeSplash();
  });
  mainWindow.on("closed", () => {
    appContents.delete(id);
    mainWindow = null;
  });
  return mainWindow.loadURL(`${origin}/`);
}

function openLocalWindow(url) {
  // The case UI opens reports and reauthentication in a separate window.
  const window = new BrowserWindow({
    width: 1150,
    height: 820,
    show: false,
    webPreferences: { ...applicationWebPreferences },
  });
  const id = window.webContents.id;
  appContents.add(id);
  hardenWebContents(window.webContents, appOrigin);
  window.once("ready-to-show", () => window.show());
  window.once("closed", () => appContents.delete(id));
  window.loadURL(url).catch(() => {
    if (!window.isDestroyed()) window.close();
  });
}

function buildMenu() {
  const template = [
    {
      label: "File",
      submenu: [
        {
          label: "Settings…",
          accelerator: "CmdOrCtrl+,",
          click: async () => {
            const saved = await showSetup();
            if (saved) {
              app.relaunch();
              app.quit();
            }
          },
        },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    {
      label: "View",
      submenu: [
        { role: "reload" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomOut" },
        { type: "separator" },
        ...developerToolsMenuItems(appContents),
      ],
    },
    {
      label: "Help",
      submenu: [
        {
          label: "Open Data Folder",
          click: () => shell.openPath(paths().data),
        },
        {
          label: "Open Logs Folder",
          click: () => shell.openPath(paths().logs),
        },
        { type: "separator" },
        {
          label: `About Similia AI ${app.getVersion()}`,
          click: () => {
            dialog.showMessageBox({
              type: "info",
              title: "Similia AI",
              message: `Similia AI ${app.getVersion()}`,
              detail:
                "Local desktop application. Patient data stays in your configured Supabase project; " +
                "speech recognition runs offline on this computer.",
            });
          },
        },
      ],
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

async function startApplication() {
  if (startupRunning) return;
  startupRunning = true;
  try {
    ensureDirectories();
    const build = readBuildMetadata();
    let config = await loadConfig({ smoke: SMOKE });
    // Development runs the real Next dev server and Uvicorn, which read
    // frontend/.env.local and backend/.env themselves.
    let validation = DEV && !SMOKE ? { ok: true, errors: {} } : validateConfig(config);
    if (app.isPackaged && !SMOKE &&
        (config?.supabaseUrl !== build.supabaseUrl || config?.supabasePublishableKey !== build.supabasePublishableKey)) {
      validation = { ok: false, errors: {} };
    }
    if (!validation.ok) {
      if (SMOKE) {
        throw new Error(
          `Smoke configuration is incomplete: ${Object.values(validation.errors).join(" ")}`
        );
      }
      const saved = await showSetup();
      if (!saved) {
        app.quit();
        return;
      }
      config = await loadConfig({ smoke: SMOKE });
      validation = validateConfig(config);
      if (!validation.ok) throw new Error("Configuration is still incomplete.");
    }
    config = config || {};

    await createSplash();
    setSplashStatus("Starting local clinical services…");

    serviceManager = new ServiceManager({
      repoRoot: REPO_ROOT,
      resourcesPath: RESOURCES,
      fontDir: FONT_DIR,
      logsDir: paths().logs,
      dev: DEV,
      onUnexpectedExit: (name) => {
        if (isQuitting) return;
        fatal(
          `The local ${name} service stopped unexpectedly. ` +
            `See ${paths().logs} for details.`
        );
      },
    });

    const { origin } = await serviceManager.start(config, paths());
    if (isQuitting) return;
    appOrigin = origin;
    setSplashStatus("Opening Similia AI…");
    await createMainWindow(origin);

    if (SMOKE) {
      const { runSmoke } = require("./lib/smoke");
      const checks = await runSmoke(mainWindow, serviceManager, config);
      smokeResult({
        ok: true,
        checks,
        backendPort: serviceManager.backendPort,
        frontendPort: serviceManager.frontendPort,
        logs: paths().logs,
      });
      app.quit();
    }
  } catch (error) {
    fatal(error);
  } finally {
    startupRunning = false;
  }
}

app.on("web-contents-created", (_event, contents) => {
  contents.on("will-attach-webview", (event) => event.preventDefault());
});

app.on("before-quit", (event) => {
  if (isQuitting) return;
  event.preventDefault();
  isQuitting = true;
  const finish = () => exitCode ? app.exit(exitCode) : app.quit();
  if (serviceManager) {
    serviceManager.stop().then(finish).catch(finish);
  } else {
    finish();
  }
});

app.on("window-all-closed", () => {
  if (!startupRunning && process.platform !== "darwin") app.quit();
});

app.on("activate", () => {
  if (!mainWindow && appOrigin && !isQuitting) createMainWindow(appOrigin).catch(fatal);
});

app.whenReady().then(async () => {
  app.setAppUserModelId("com.similia.ai");
  ensureDirectories();
  session.defaultSession.protocol.handle(SHELL_SCHEME, (request) => {
    const asset = SHELL_ASSETS.get(request.url);
    if (!asset || request.method !== "GET") return new Response(null, { status: 404 });
    const [filename, type] = asset;
    return new Response(fs.readFileSync(path.join(__dirname, filename)), {
      headers: { "Content-Type": `${type}; charset=utf-8`, "X-Content-Type-Options": "nosniff" },
    });
  });
  registerIpc();
  buildMenu();
  if (!singleInstance) return;
  await startApplication();
});

process.on("uncaughtException", fatal);
process.on("unhandledRejection", fatal);
