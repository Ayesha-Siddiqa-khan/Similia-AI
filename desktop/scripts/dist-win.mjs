/**
 * Build the staged runtime, then package the x64 NSIS installer.
 *
 *   node desktop/scripts/dist-win.mjs
 *
 * Result: <repo>/release/Similia AI Setup.exe
 */

import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import projectConfig from "../electron/lib/project-config.js";

import { desktopDir, frontendDir, readJson, releaseDir, resolveBin, run } from "./util.mjs";

if (process.platform !== "win32" || process.arch !== "x64") {
  throw new Error("Build the x64 installer with x64 Node.js on Windows.");
}
const require = createRequire(import.meta.url);
const distribution = path.dirname(require("electron"));
const cache = path.join(desktopDir, ".cache");
const temporary = path.join(cache, "tmp");
fs.mkdirSync(temporary, { recursive: true });

if (!process.argv.includes("--staged")) await import("./build.mjs");

const staged = path.join(desktopDir, "resources");
for (const file of ["desktop-build.json", "frontend/launch.cjs", "frontend/server.js", "backend/similia-backend.exe"]) {
  if (!fs.existsSync(path.join(staged, file))) throw new Error(`Missing staged resource: ${file}`);
}
const offlineTest = process.argv.includes("--offline-test");
const expected = offlineTest ? projectConfig.offlineProject :
  projectConfig.personalProject(projectConfig.readLocalEnv(path.join(frontendDir, ".env.local")));
const metadata = readJson(path.join(staged, "desktop-build.json"));
if (Object.keys(expected).some((field) => expected[field] !== metadata[field])) {
  throw new Error("Staged configuration differs from the requested build. Rebuild before packaging.");
}
if (fs.readdirSync(staged, { recursive: true, withFileTypes: true }).some((file) => file.isSymbolicLink())) {
  throw new Error("Staged resources contain links and cannot be installed independently.");
}

const output = offlineTest ? path.join(releaseDir, "offline-test") : releaseDir;
const installer = path.join(output, "Similia AI Setup.exe");
fs.rmSync(installer, { force: true });

console.log("\nPackaging the Windows installer with electron-builder…");
run(
  process.execPath,
  [resolveBin("electron-builder", "electron-builder"), "--win", "--x64", "--publish", "never",
    `--config.electronDist=${distribution}`, `--config.directories.output=${output}`],
  {
    cwd: desktopDir,
    env: { ...process.env, ELECTRON_BUILDER_CACHE: cache, TEMP: temporary, TMP: temporary,
      CSC_IDENTITY_AUTO_DISCOVERY: "false" },
  }
);

if (!fs.existsSync(installer)) throw new Error("Expected installer was not created.");
if (!fs.existsSync(path.join(output, "win-unpacked", "resources", "frontend", "node_modules", "next", "package.json"))) {
  throw new Error("The packaged frontend is missing its Next.js runtime dependencies.");
}
// Validate that the installed app will actually be able to read its bundled reports.
for (const name of ["pdf_inventory.json", "ingestion_progress.json", "run_manifest.json"]) {
  const packagedReport = path.join(output, "win-unpacked", "resources", "backend", "reports", "ingestion", name);
  if (!fs.existsSync(packagedReport)) {
    throw new Error(`Packaged installer is missing RAG report: ${packagedReport}`);
  }
}
console.log(`\nInstaller: ${installer}`);
