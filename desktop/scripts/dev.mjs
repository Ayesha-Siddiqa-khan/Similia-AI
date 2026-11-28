/**
 * Run the desktop shell against the repository's own dev servers.
 *
 * The backend keeps using backend/.env and the frontend keeps using
 * frontend/.env.local, so no credentials are duplicated into desktop config.
 */

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

import { backendDir, desktopDir, frontendDir } from "./util.mjs";

const require = createRequire(import.meta.url);

function requirePath(target, message) {
  if (!fs.existsSync(target)) {
    console.error(message);
    process.exit(1);
  }
}

requirePath(path.join(frontendDir, "node_modules"), "Run: cd frontend && npm install");
requirePath(
  path.join(backendDir, ".venv", "Scripts", "python.exe"),
  "Run: cd backend && uv sync --group speech"
);
requirePath(
  path.join(desktopDir, "node_modules", "electron"),
  "Run: npm --prefix desktop install"
);

let electron;
try {
  electron = require("electron");
} catch {
  console.error("Electron is not installed. Run: npm --prefix desktop install");
  process.exit(1);
}

const result = spawnSync(electron, ["."], {
  cwd: desktopDir,
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 0);
