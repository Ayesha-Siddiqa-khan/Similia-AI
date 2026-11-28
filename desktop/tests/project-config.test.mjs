import assert from "node:assert/strict";
import test from "node:test";
import projectConfig from "../electron/lib/project-config.js";
import { buildBackendEnv } from "../electron/lib/env.js";

const { personalProject, offlineProject, importBackendConfig } = projectConfig;
const url = "https://example.supabase.co";
const key = "sb_publishable_fixture";
const fernet = Buffer.alloc(32).toString("base64url") + "=";
const frontend = {
  NEXT_PUBLIC_SUPABASE_URL: url + "/",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: key,
  VOYAGE_API_KEY: "frontend-secret-marker",
};
const backend = {
  SUPABASE_URL: url,
  SUPABASE_PUBLISHABLE_KEY: key,
  SUPABASE_SECRET_KEY: "sb_secret_fixture",
  APP_ENCRYPTION_KEY: fernet,
  APP_ENCRYPTION_KEY_PREVIOUS: fernet,
  VOYAGE_API_KEY: "voyage-secret-fixture",
  VOYAGE_MODEL: "voyage-fixture",
  EMBEDDING_BUDGET_TOKENS: "500",
  CLINICAL_WORKFLOW_ENABLED: "true",
  ANTHROPIC_API_KEY: "runtime-key-goes-in-ai-settings",
};

test("personal build extracts only the public Supabase values", () => {
  assert.deepEqual(personalProject(frontend), {
    supabaseUrl: url, supabasePublishableKey: key, offlineTest: false,
  });
});

test("personal build rejects missing, offline and privileged public configuration", () => {
  for (const changes of [
    { NEXT_PUBLIC_SUPABASE_URL: undefined },
    { NEXT_PUBLIC_SUPABASE_URL: offlineProject.supabaseUrl },
    { NEXT_PUBLIC_SUPABASE_URL: "https://127.0.0.1:39437" },
    { NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: offlineProject.supabasePublishableKey },
    { NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: backend.SUPABASE_SECRET_KEY },
  ]) {
    assert.throws(() => personalProject({ ...frontend, ...changes }), /requires a real HTTPS/);
  }
});

test("backend import checks project and does not leak mismatched values", () => {
  for (const changes of [
    { SUPABASE_URL: "https://mismatch.supabase.co" },
    { SUPABASE_PUBLISHABLE_KEY: "sb_publishable_mismatch" },
  ]) {
    assert.throws(() => importBackendConfig({ ...backend, ...changes }, personalProject(frontend)),
      (error) => /does not match/.test(error.message) && !error.message.includes("mismatch"));
  }
  assert.throws(() => importBackendConfig(backend, offlineProject), /does not match/);
});

test("backend import preserves encryption keys and retrieval settings", () => {
  const config = importBackendConfig(backend, personalProject(frontend));
  assert.equal(config.anthropicApiKey, undefined);
  const env = buildBackendEnv({ config, frontendPort: 1234, backendPort: 1235, dataDir: "data" });
  assert.equal(env.APP_ENCRYPTION_KEY, fernet);
  assert.equal(env.APP_ENCRYPTION_KEY_PREVIOUS, fernet);
  assert.equal(env.VOYAGE_MODEL, backend.VOYAGE_MODEL);
  assert.equal(env.EMBEDDING_BUDGET_TOKENS, "500");
  assert.equal(env.CLINICAL_WORKFLOW_ENABLED, "true");
  assert.throws(() => importBackendConfig({ ...backend, APP_ENCRYPTION_KEY: "bad" }, personalProject(frontend)),
    /missing or invalid/);
});
