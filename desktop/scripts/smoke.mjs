import assert from "node:assert/strict";
import { spawn, execFile } from "node:child_process";
import { randomBytes } from "node:crypto";
import { once } from "node:events";
import fs from "node:fs";
import path from "node:path";

import { startFixture } from "./smoke-fixture.mjs";
import { desktopDir, releaseDir } from "./util.mjs";

const exeIndex = process.argv.indexOf("--exe");
const exe = exeIndex === -1 ? path.join(releaseDir, "offline-test", "win-unpacked", "Similia AI.exe")
  : path.resolve(process.argv[exeIndex + 1]);
const metadata = JSON.parse(fs.readFileSync(path.join(path.dirname(exe), "resources", "desktop-build.json"), "utf8"));
assert.equal(metadata.offlineTest, true, "Smoke requires an offline test build.");
assert.equal(Boolean(process.env.SIMILIA_SMOKE_MODEL), Boolean(process.env.SIMILIA_SMOKE_AUDIO),
  "Set both SIMILIA_SMOKE_MODEL and SIMILIA_SMOKE_AUDIO for the transcription check.");

const smokeRoot = path.join(desktopDir, ".cache", "smoke");
fs.mkdirSync(smokeRoot, { recursive: true });
const runDir = fs.mkdtempSync(path.join(smokeRoot, "run-"));
const resultFile = path.join(runDir, "result.json");
const fakeConfig = {
  supabaseUrl: metadata.supabaseUrl,
  supabasePublishableKey: metadata.supabasePublishableKey,
  supabaseSecretKey: "offline-test-service-role",
  appEncryptionKey: randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_"),
  voyageApiKey: "offline-test-voyage",
};

const fixture = await startFixture(metadata);
const windows = process.env.SystemRoot || "C:\\Windows";
const env = Object.fromEntries(Object.entries(process.env).filter(([name]) =>
  !/^(?:path|ELECTRON_.*|NODE_OPTIONS|SIMILIA_.*)$/i.test(name)));
const child = spawn(exe, [], {
  stdio: "inherit",
  env: {
    ...env,
    PATH: [path.join(windows, "System32"), windows].join(path.delimiter),
    TEMP: runDir,
    TMP: runDir,
    SIMILIA_SMOKE_TEST: "1",
    SIMILIA_SMOKE_OUTPUT: resultFile,
    SIMILIA_SMOKE_USER_DATA: path.join(runDir, "profile"),
    SIMILIA_DESKTOP_CONFIG_JSON: JSON.stringify(fakeConfig),
    SIMILIA_SMOKE_MODEL: process.env.SIMILIA_SMOKE_MODEL || "",
    SIMILIA_SMOKE_AUDIO: process.env.SIMILIA_SMOKE_AUDIO || "",
  },
});
const timer = setTimeout(() => {
  execFile(path.join(windows, "System32", "taskkill.exe"), ["/pid", String(child.pid), "/T", "/F"],
    { windowsHide: true }, () => {});
}, 360_000);
try {
  const [code] = await once(child, "exit");
  const result = fs.existsSync(resultFile) ? JSON.parse(fs.readFileSync(resultFile, "utf8")) : null;
  assert.ok(code === 0 && result?.ok, result?.error || `App exited with code ${code}. Logs: ${runDir}`);
  for (const port of [result.backendPort, result.frontendPort]) {
    await assert.rejects(fetch(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(3000) }),
      (error) => error.cause?.code === "ECONNREFUSED", `Service on port ${port} did not shut down.`);
  }
  const backendLog = fs.readFileSync(path.join(result.logs, "backend.log"), "utf8");
  assert.match(backendLog, /Application shutdown complete/);
  if (process.env.SIMILIA_SMOKE_MODEL) {
    const workers = [...backendLog.matchAll(/Started speech worker pid=(\d+)/g)];
    assert.ok(workers.length, "The backend did not launch a speech worker.");
    for (const [, pid] of workers) {
      assert.throws(() => process.kill(Number(pid), 0), { code: "ESRCH" },
        `Speech worker ${pid} survived shutdown.`);
    }
  }
  for (const check of result.checks) console.log(`PASS ${check}`);
  console.log(`PASS local services stopped. Logs: ${result.logs}`);
} finally {
  clearTimeout(timer);
  fixture?.close();
}
