import assert from "node:assert/strict";
import test from "node:test";

import {
  buildBackendEnv,
  buildFrontendEnv,
  buildNodeRuntimeEnv,
  isFernetKey,
  isLoopbackUrl,
  validateConfig,
} from "../electron/lib/env.js";

const fernetKey = "Zx8kQm2vTn5pRw7yLb4cJd6fHg9sKa3eUo1iYt0uVwE=";

const validConfig = {
  supabaseUrl: "https://project.supabase.co",
  supabasePublishableKey: "sb_publishable_public",
  supabaseSecretKey: "service-role-secret",
  appEncryptionKey: fernetKey,
  voyageApiKey: "pa-voyage",
};

test("a generated Fernet key is recognised", () => {
  assert.equal(isFernetKey(fernetKey), true);
  assert.equal(isFernetKey("not-a-key"), false);
  assert.equal(isFernetKey(""), false);
});

test("only loopback hosts count as local", () => {
  assert.equal(isLoopbackUrl("http://127.0.0.1:3000"), true);
  assert.equal(isLoopbackUrl("http://localhost:3000"), true);
  assert.equal(isLoopbackUrl("https://project.supabase.co"), false);
});

test("a complete configuration validates", () => {
  assert.deepEqual(validateConfig(validConfig), { ok: true, errors: {} });
});

test("missing values are reported per field", () => {
  const result = validateConfig({});
  assert.equal(result.ok, false);
  for (const field of [
    "supabaseUrl",
    "supabasePublishableKey",
    "supabaseSecretKey",
    "appEncryptionKey",
    "voyageApiKey",
  ]) {
    assert.ok(result.errors[field], `${field} should be reported`);
  }
});

test("a plain-http Supabase URL is rejected", () => {
  const result = validateConfig({ ...validConfig, supabaseUrl: "http://project.supabase.co" });
  assert.equal(result.ok, false);
  assert.ok(result.errors.supabaseUrl);
});

test("packaged backend environment carries the desktop contract", () => {
  const env = buildBackendEnv({
    config: validConfig,
    frontendPort: 41000,
    backendPort: 41001,
    desktopToken: "launch-token",
    dataDir: "C:\\Users\\test\\AppData\\Roaming\\Similia AI\\data",
    fontDir: "C:\\Program Files\\Similia AI\\resources\\assets",
    speechConfigPath: "C:\\Users\\test\\AppData\\Roaming\\Similia AI\\speech-settings.json",
  });

  assert.equal(env.ENVIRONMENT, "desktop");
  assert.equal(env.CORS_ORIGINS, "http://127.0.0.1:41000");
  assert.equal(env.SIMILIA_DESKTOP_TOKEN, "launch-token");
  assert.equal(env.SUPABASE_SECRET_KEY, "service-role-secret");
  assert.equal(env.APP_ENCRYPTION_KEY, fernetKey);
  assert.equal(env.SIMILIA_BACKEND_HOST, "127.0.0.1");
  assert.equal(env.SIMILIA_BACKEND_PORT, "41001");
  assert.ok(env.EMBEDDING_BUDGET_PATH.endsWith("voyage-budget.sqlite"));
  assert.equal(env.HF_HUB_OFFLINE, "1");
});

test("development backend environment leaves .env in charge", () => {
  const env = buildBackendEnv({
    frontendPort: 41000,
    backendPort: 41001,
    desktopToken: "launch-token",
    dataDir: "ignored",
    fontDir: "ignored",
    speechConfigPath: "ignored",
    dev: true,
  });

  assert.equal(env.SIMILIA_DESKTOP_TOKEN, "launch-token");
  assert.equal(env.SIMILIA_BACKEND_PORT, "41001");
  assert.equal(env.ENVIRONMENT, undefined);
  assert.equal(env.SUPABASE_SECRET_KEY, undefined);
  assert.equal(env.SIMILIA_DATA_DIR, undefined);
});

test("packaged frontend environment is a production standalone server", () => {
  const env = buildFrontendEnv({
    config: validConfig,
    frontendPort: 41000,
    backendPort: 41001,
    desktopToken: "launch-token",
    rendererToken: "renderer-token",
  });

  assert.equal(env.NODE_ENV, "production");
  assert.equal(env.HOSTNAME, "127.0.0.1");
  assert.equal(env.PORT, "41000");
  assert.equal(env.API_BASE_URL, "http://127.0.0.1:41001");
  assert.equal(env.SIMILIA_DESKTOP, "1");
  assert.equal(env.NEXT_PUBLIC_SUPABASE_URL, validConfig.supabaseUrl);
  assert.equal(env.SIMILIA_DESKTOP_TOKEN, "launch-token");
  assert.equal(env.SIMILIA_RENDERER_TOKEN, "renderer-token");
});

test("packaged frontend inherits neither backend credentials nor Node preload options", () => {
  const names = ["SUPABASE_SECRET_KEY", "VOYAGE_API_KEY", "APP_ENCRYPTION_KEY", "NODE_OPTIONS"];
  const before = names.map((name) => process.env[name]);
  try {
    for (const name of names) process.env[name] = "fixture";
    const env = buildFrontendEnv({ config: validConfig, frontendPort: 41000, backendPort: 41001 });
    for (const name of names) assert.equal(env[name], undefined);
  } finally {
    names.forEach((name, index) => {
      if (before[index] === undefined) delete process.env[name];
      else process.env[name] = before[index];
    });
  }
});

test("development frontend environment keeps next dev semantics", () => {
  const env = buildFrontendEnv({
    frontendPort: 41000,
    backendPort: 41001,
    desktopToken: "launch-token",
    dev: true,
  });

  assert.equal(env.NODE_ENV, undefined);
  assert.equal(env.SIMILIA_DESKTOP, undefined);
  assert.equal(env.API_BASE_URL, "http://127.0.0.1:41001");
});

test("the standalone server runs through Electron as Node", () => {
  const env = buildNodeRuntimeEnv({ NODE_ENV: "production" });
  assert.equal(env.ELECTRON_RUN_AS_NODE, "1");
  assert.equal(env.NODE_ENV, "production");
});
