"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

if (!process.argv.includes("--confirm-import")) {
  console.error("Close Similia AI and pass --confirm-import to import backend/.env for your Windows account.");
  process.exit(1);
}

if (!process.versions.electron) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([name]) =>
    /^(systemroot|windir|path|pathext|temp|tmp|userprofile|appdata|localappdata|programdata)$/i.test(name)));
  const result = spawnSync(require("electron"), [__filename, ...process.argv.slice(2)], {
    env, stdio: "inherit", windowsHide: true,
  });
  process.exit(result.status ?? 1);
}

const { app } = require("electron");
const { loadConfig, saveConfig, validateConfig } = require("../electron/lib/config");
const { importBackendConfig, personalProject, readLocalEnv } = require("../electron/lib/project-config");

app.setName("Similia AI");
const userData = path.join(app.getPath("appData"), "Similia AI");
fs.mkdirSync(userData, { recursive: true });
app.setPath("userData", userData);
if (!app.requestSingleInstanceLock()) {
  console.error("Close Similia AI before importing.");
  app.exit(1);
} else {
  app.whenReady().then(async () => {
    const explicitInstall = process.argv.find((value) => value.startsWith("--installed-dir="));
    const installed = explicitInstall?.slice("--installed-dir=".length) ||
      path.join(process.env.LOCALAPPDATA, "Programs", "Similia AI");
    const manifest = path.join(installed, "resources", "desktop-build.json");
    let build;
    try {
      build = JSON.parse(fs.readFileSync(manifest, "utf8"));
    } catch {
      throw new Error("Personal installer metadata is unavailable. Install the personal build first.");
    }
    const root = path.join(__dirname, "..", "..");
    const project = personalProject(readLocalEnv(path.join(root, "frontend", ".env.local")));
    if (Object.keys(project).some((field) => project[field] !== build[field])) {
      throw new Error("The installed app does not match this repository's personal build.");
    }
    const config = importBackendConfig(readLocalEnv(path.join(root, "backend", ".env")), build);
    const previous = await loadConfig();
    try {
      await saveConfig({ ...(previous?.supabaseUrl === build.supabaseUrl ? previous : {}), ...config });
      if (!validateConfig(await loadConfig()).ok) throw new Error();
    } catch {
      throw new Error("Windows could not save and reload the encrypted configuration.");
    }
    console.log("Imported backend settings into the Windows credential store. Open Similia AI from your desktop.");
    app.quit();
  }).catch((error) => {
    console.error(error.message);
    app.exit(1);
  });
}
