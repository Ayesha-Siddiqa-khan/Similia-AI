import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const here = path.dirname(fileURLToPath(import.meta.url));
export const desktopDir = path.resolve(here, "..");
export const repoRoot = path.resolve(desktopDir, "..");
export const frontendDir = path.join(repoRoot, "frontend");
export const backendDir = path.join(repoRoot, "backend");
export const resourcesDir = path.join(desktopDir, "resources");
export const releaseDir = path.join(repoRoot, "release");

/** Run a command and fail loudly. */
export function run(command, args, options = {}) {
  console.log(`\n> ${[command, ...args].join(" ")}`);
  const result = spawnSync(command, args, { stdio: "inherit", ...options });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Command failed with exit code ${result.status}: ${command} ${args.join(" ")}`);
  }
  return result;
}

export async function runBuild(command, args, options) {
  console.log(`\n> ${[command, ...args].join(" ")}`);
  const child = spawn(command, args, { stdio: "inherit", ...options });
  const [code] = await once(child, "close");
  if (code !== 0) throw new Error(`${command} failed with exit code ${code}.`);
}

/** Resolve a package's bin script so it can be run with the current Node binary. */
export function resolveBin(packageName, binName) {
  const packageFile = path.join(desktopDir, "node_modules", packageName, "package.json");
  if (!fs.existsSync(packageFile)) {
    throw new Error(`Missing ${packageName}. Run: npm --prefix desktop install`);
  }
  const manifest = JSON.parse(fs.readFileSync(packageFile, "utf8"));
  const relative = typeof manifest.bin === "string" ? manifest.bin : manifest.bin?.[binName];
  if (!relative) throw new Error(`${packageName} does not expose a "${binName}" binary`);
  return path.join(path.dirname(packageFile), relative);
}

export function rmrf(target) {
  const absolute = path.resolve(target);
  if (![resourcesDir, path.join(desktopDir, ".build", "frontend"),
    ...[".next", "src", "public"].map((name) => path.join(desktopDir, ".build", "frontend", name))
  ].includes(absolute)) {
    throw new Error("Refusing to remove a path outside the desktop build directories.");
  }
  if (fs.existsSync(absolute) && fs.realpathSync(absolute) !== absolute) {
    throw new Error("Refusing to remove a redirected build directory.");
  }
  fs.rmSync(target, { recursive: true, force: true });
}

export function copyDir(from, to) {
  if (!fs.existsSync(from)) throw new Error(`Missing source directory: ${from}`);
  fs.cpSync(from, to, { recursive: true, filter: (source) =>
    !/^(?:\.env(?:\.|$)|model\.bin$)|\.(?:safetensors|gguf|pt|pth)$/i.test(path.basename(source)) });
}

export function readJson(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}
