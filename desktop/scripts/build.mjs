/**
 * Stage everything the installer needs:
 *   1. Next.js production build (standalone output)
 *   2. PyInstaller onedir backend with the frozen speech worker
 *   3. Urdu font and build metadata
 *
 * Usage:
 *   node desktop/scripts/build.mjs
 *
 * Public values from frontend/.env.local are inlined at compile time.
 *   NEXT_PUBLIC_SUPABASE_URL
 *   NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY
 *
 * Pass --offline-test to build for the loopback test fixture.
 */

import fs from "node:fs";
import path from "node:path";
import projectConfig from "../electron/lib/project-config.js";

const { offlineProject, personalProject, readLocalEnv } = projectConfig;

import {
  backendDir,
  copyDir,
  desktopDir,
  frontendDir,
  readJson,
  resourcesDir,
  rmrf,
  runBuild,
} from "./util.mjs";

const project = process.argv.includes("--offline-test")
  ? offlineProject
  : personalProject(readLocalEnv(path.join(frontendDir, ".env.local")));
const { supabaseUrl: buildUrl, supabasePublishableKey: buildKey, offlineTest } = project;

// SIMILIA_DESKTOP_REPORTS_FALLBACK_V1
// Bundle real, read-only report data. Never bundle .env files or test fixtures.
const ingestionSource = path.resolve(desktopDir, "..", "reports", "ingestion");
for (const name of ["pdf_inventory.json", "ingestion_progress.json", "run_manifest.json"]) {
  const reportFile = path.join(ingestionSource, name);
  if (!fs.existsSync(reportFile)) {
    throw new Error(`Required RAG report missing: ${reportFile}`);
  }
  const parsed = JSON.parse(fs.readFileSync(reportFile, "utf8"));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`Invalid RAG report: ${reportFile}`);
  }
}

const buildRoot = path.join(desktopDir, ".build");
const cleanFrontend = path.join(buildRoot, "frontend");
const tempDir = path.join(buildRoot, "tmp");
const buildEnv = {
  ...Object.fromEntries(Object.entries(process.env).filter(([key]) =>
    /^(systemroot|windir|comspec|path|pathext|userprofile|appdata|localappdata|systemdrive|number_of_processors)$/i.test(key))),
  TEMP: tempDir,
  TMP: tempDir,
};

function findStandaloneApp(root) {
  if (!fs.existsSync(root)) throw new Error(`Next standalone output missing: ${root}`);
  if (fs.existsSync(path.join(root, "server.js"))) return root;
  throw new Error(`Next standalone server.js not found under ${root}`);
}

const reuseDependencies = process.argv.includes("--reuse-dependencies");
if (reuseDependencies &&
    (!fs.existsSync(path.join(cleanFrontend, "node_modules", "next", "package.json")) ||
     !fs.readFileSync(path.join(frontendDir, "package-lock.json")).equals(
       fs.readFileSync(path.join(cleanFrontend, "package-lock.json"))))) {
  throw new Error("Cached frontend dependencies are missing or stale. Run without --reuse-dependencies.");
}

console.log("Cleaning previous staging output…");
rmrf(resourcesDir);
rmrf(reuseDependencies ? path.join(cleanFrontend, ".next") : cleanFrontend);
if (reuseDependencies) {
  rmrf(path.join(cleanFrontend, "src"));
  rmrf(path.join(cleanFrontend, "public"));
}
fs.mkdirSync(cleanFrontend, { recursive: true });
fs.mkdirSync(tempDir, { recursive: true });

for (const file of ["package.json", "package-lock.json", "next.config.ts", "tsconfig.json"]) {
  fs.copyFileSync(path.join(frontendDir, file), path.join(cleanFrontend, file));
}
for (const directory of reuseDependencies ? ["src", "public"] : ["src", "public", "node_modules"]) {
  copyDir(path.join(frontendDir, directory), path.join(cleanFrontend, directory));
}
const frontendBuild = runBuild(process.execPath, [path.join(cleanFrontend, "node_modules", "next", "dist", "bin", "next"), "build"], {
  cwd: cleanFrontend,
  env: {
    ...buildEnv,
    NODE_ENV: "production",
    SIMILIA_DESKTOP: "1",
    NEXT_PUBLIC_SUPABASE_URL: buildUrl,
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: buildKey,
    API_BASE_URL: "http://127.0.0.1:8000",
    NEXT_TELEMETRY_DISABLED: "1",
  },
});

const backendBuild = runBuild(
  process.platform === "win32" ? "uv.exe" : "uv",
  ["run", "--offline", "--no-sync", "pyinstaller", "--noconfirm", "--clean",
    "--workpath", path.join(buildRoot, "pyinstaller"), "--distpath", path.join(buildRoot, "dist"),
    "similia-backend.spec"],
  {
    cwd: backendDir,
    env: { ...buildEnv, UV_CACHE_DIR: path.join(desktopDir, ".cache", "uv"),
      PYINSTALLER_CONFIG_DIR: path.join(buildRoot, "pyinstaller-cache"),
      HF_HUB_OFFLINE: "1", HF_HUB_DISABLE_TELEMETRY: "1" },
  }
);

const results = await Promise.allSettled([frontendBuild, backendBuild]);
const failures = results.filter((result) => result.status === "rejected");
if (failures.length) throw new AggregateError(failures.map((failure) => failure.reason), "Desktop runtime build failed.");

const standalone = findStandaloneApp(path.join(cleanFrontend, ".next", "standalone"));
const stagedFrontend = path.join(resourcesDir, "frontend");
copyDir(standalone, stagedFrontend);
copyDir(path.join(cleanFrontend, ".next", "static"), path.join(stagedFrontend, ".next", "static"));
copyDir(path.join(frontendDir, "public"), path.join(stagedFrontend, "public"));
fs.writeFileSync(path.join(stagedFrontend, "launch.cjs"),
  'process.stdin.on("end", () => process.exit(0));\nprocess.stdin.resume();\nrequire("./server.js");\n');
copyDir(path.join(buildRoot, "dist", "similia-backend"), path.join(resourcesDir, "backend"));
// Include the complete ingestion report tree, including frozen chunk plans.
// This is a PERSONAL installer: inspect the report directory before sharing it.
copyDir(ingestionSource, path.join(resourcesDir, "backend", "reports", "ingestion"));
console.log("Bundled existing ingestion reports for first-run, read-only monitoring.");

// ---------------------------------------------------------------- assets
const assets = path.join(resourcesDir, "assets");
fs.mkdirSync(assets, { recursive: true });
const font = path.join(frontendDir, "public", "fonts", "JameelNooriNastaleeq.ttf");
if (fs.existsSync(font)) {
  fs.copyFileSync(font, path.join(assets, "JameelNooriNastaleeq.ttf"));
} else {
  console.warn("Urdu font not found; Urdu report rendering will fall back to a system font.");
}

const version = readJson(path.join(desktopDir, "package.json")).version;
fs.writeFileSync(
  path.join(resourcesDir, "desktop-build.json"),
  JSON.stringify(
    {
      version,
      builtAt: new Date().toISOString(),
      supabaseUrl: buildUrl,
      supabasePublishableKey: buildKey,
      offlineTest,
    },
    null,
    2
  ),
  "utf8"
);

console.log("\nStaging complete:");
console.log(`  frontend : ${path.join(resourcesDir, "frontend")}`);
console.log(`  backend  : ${path.join(resourcesDir, "backend")}`);
console.log(`  version  : ${version}`);
