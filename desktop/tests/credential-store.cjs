"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

if (!process.versions.electron) {
  const cache = path.join(__dirname, "..", ".cache");
  fs.mkdirSync(cache, { recursive: true });
  const fixture = fs.mkdtempSync(path.join(cache, "dpapi-"));
  for (const phase of ["save", "verify"]) {
    const result = spawnSync(require("electron"), [__filename, fixture, phase], {
      windowsHide: true, stdio: "inherit",
    });
    if (result.status !== 0) process.exit(1);
  }
} else {
  const { app } = require("electron");
  const { saveConfig, loadConfig, paths, publicConfig } = require("../electron/lib/config");
  const [fixture, phase] = process.argv.slice(2);
  app.setPath("userData", fixture);
  app.whenReady().then(async () => {
    const config = {
      supabaseUrl: "https://fixture.supabase.co",
      supabasePublishableKey: "sb_publishable_fixture",
      supabaseSecretKey: "sb_secret_synthetic_only",
      appEncryptionKey: Buffer.alloc(32, 21).toString("base64url") + "=",
      voyageApiKey: "synthetic-voyage-key",
    };
    if (phase === "save") {
      await saveConfig(config);
    } else {
      const loaded = await loadConfig();
      const stored = fs.readFileSync(paths().config, "utf8");
      const publicSettings = JSON.stringify(publicConfig(loaded));
      for (const field of ["supabaseSecretKey", "appEncryptionKey", "voyageApiKey"]) {
        assert.equal(loaded[field], config[field]);
        assert.ok(!stored.includes(config[field]));
        assert.ok(!publicSettings.includes(config[field]));
      }
      assert.ok(!fs.readdirSync(fixture).some((name) => name.startsWith("config.json.") && name.endsWith(".tmp")));
      console.log("Windows DPAPI restored synthetic secrets across Electron launches.");
    }
    app.quit();
  }).catch(() => {
    console.error("DPAPI fixture verification failed.");
    app.exit(1);
  });
}
