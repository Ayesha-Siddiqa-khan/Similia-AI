"use strict";

/**
 * Pure helpers for desktop configuration and child-process environments.
 * No Electron imports here, so node --test can exercise them directly.
 */

const path = require("node:path");

const FERNET_KEY = /^[A-Za-z0-9_-]{43}=$/;

function isFernetKey(value) {
  if (typeof value !== "string" || !FERNET_KEY.test(value)) return false;
  try {
    return Buffer.from(value, "base64url").length === 32;
  } catch {
    return false;
  }
}

function isHttpUrl(value) {
  try {
    const url = new URL(String(value));
    return !url.username && !url.password && !url.search && !url.hash &&
      url.pathname === "/" && (url.protocol === "https:" || url.protocol === "http:");
  } catch {
    return false;
  }
}

function isLoopbackUrl(value) {
  try {
    const host = new URL(String(value)).hostname.toLowerCase();
    return host === "127.0.0.1" || host === "localhost" || host === "[::1]";
  } catch {
    return false;
  }
}

/** Validate the values the backend needs before it will start in desktop mode. */
function validateConfig(config, options = {}) {
  const requireVoyage = options.requireVoyage !== false;
  const errors = {};

  if (!config || typeof config !== "object") {
    return { ok: false, errors: { config: "Configuration is missing." } };
  }
  if (!isHttpUrl(config.supabaseUrl)) {
    errors.supabaseUrl = "Enter the Supabase project URL (https://…).";
  } else if (
    !String(config.supabaseUrl).startsWith("https://") &&
    !isLoopbackUrl(config.supabaseUrl)
  ) {
    errors.supabaseUrl = "The Supabase URL must use https://.";
  }
  if (!String(config.supabasePublishableKey || "").trim()) {
    errors.supabasePublishableKey = "Enter the Supabase publishable (anon) key.";
  }
  if (!String(config.supabaseSecretKey || "").trim()) {
    errors.supabaseSecretKey = "Enter the Supabase service-role key.";
  }
  if (!isFernetKey(config.appEncryptionKey)) {
    errors.appEncryptionKey = "The local encryption key is missing or invalid.";
  }
  if (requireVoyage && !String(config.voyageApiKey || "").trim()) {
    errors.voyageApiKey = "Enter the Voyage API key used for search and analysis.";
  }
  return { ok: Object.keys(errors).length === 0, errors };
}

/**
 * Environment for the packaged backend.
 *
 * Development passes `dev: true` and only adds the launcher-specific values; the
 * backend then keeps reading its own `.env`, so a developer does not have to
 * duplicate credentials into the desktop configuration.
 */
function buildBackendEnv({
  config = {},
  frontendPort,
  backendPort,
  desktopToken,
  dataDir,
  fontDir,
  speechConfigPath,
  dev = false,
}) {
  const shared = {
    SIMILIA_DESKTOP_TOKEN: desktopToken,
    SIMILIA_BACKEND_HOST: "127.0.0.1",
    SIMILIA_BACKEND_PORT: String(backendPort),
    PYTHONUTF8: "1",
    PYTHONIOENCODING: "utf-8",
  };

  if (dev) {
    return { ...process.env, ...shared };
  }

  const env = {
    ...runtimeEnvironment(),
    ...shared,
    ENVIRONMENT: "desktop",
    CORS_ORIGINS: `http://127.0.0.1:${frontendPort}`,
    SUPABASE_URL: config.supabaseUrl,
    SUPABASE_PUBLISHABLE_KEY: config.supabasePublishableKey,
    SUPABASE_SECRET_KEY: config.supabaseSecretKey,
    APP_ENCRYPTION_KEY: config.appEncryptionKey,
    APP_ENCRYPTION_KEY_PREVIOUS: config.appEncryptionKeyPrevious || "",
    VOYAGE_API_KEY: config.voyageApiKey || "",
    VOYAGE_MODEL: config.voyageModel || "voyage-4-lite",
    AUTO_RESUME_ENABLED: "false",
    CLINICAL_WORKFLOW_ENABLED: String(config.clinicalWorkflowEnabled === true),
    LANGSMITH_TRACING: "false",
    SIMILIA_DATA_DIR: dataDir,
    HF_HOME: path.join(dataDir, "huggingface"),
    EMBEDDING_BUDGET_PATH: path.join(dataDir, "voyage-budget.sqlite"),
    URDU_FONT_DIR: fontDir,
    SIMILIA_SPEECH_CONFIG_PATH: speechConfigPath,
    // The backend uses this only to migrate an older Electron model path.
    SIMILIA_SPEECH_MODEL_PATH: config.modelPath || "",
    HF_HUB_OFFLINE: "1",
    HF_HUB_DISABLE_TELEMETRY: "1",
  };
  if (config.anthropicApiKey) env.ANTHROPIC_API_KEY = config.anthropicApiKey;
  if (config.anthropicModel) env.ANTHROPIC_MODEL = config.anthropicModel;
  if (config.embeddingBudgetTokens) env.EMBEDDING_BUDGET_TOKENS = config.embeddingBudgetTokens;
  return env;
}

/** Environment for the Next.js server (standalone in production, `next dev` in development). */
function buildFrontendEnv({
  config = {},
  frontendPort,
  backendPort,
  desktopToken,
  rendererToken,
  dev = false,
}) {
  const shared = {
    PORT: String(frontendPort),
    HOSTNAME: "127.0.0.1",
    API_BASE_URL: `http://127.0.0.1:${backendPort}`,
    SIMILIA_DESKTOP_TOKEN: desktopToken,
    SIMILIA_RENDERER_TOKEN: rendererToken,
    SIMILIA_DESKTOP_ORIGIN: `http://127.0.0.1:${frontendPort}`,
    NEXT_TELEMETRY_DISABLED: "1",
  };

  if (dev) {
    // `next dev` loads frontend/.env.local and needs NODE_ENV=development.
    return { ...process.env, ...shared };
  }

  return {
    ...runtimeEnvironment(),
    ...shared,
    NODE_ENV: "production",
    NEXT_PUBLIC_SUPABASE_URL: config.supabaseUrl,
    NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: config.supabasePublishableKey,
    SIMILIA_DESKTOP: "1",
  };
}

function runtimeEnvironment() {
  return Object.fromEntries(Object.entries(process.env).filter(([name]) =>
    /^(systemroot|windir|comspec|path|pathext|temp|tmp|userprofile|appdata|localappdata|programdata|systemdrive|number_of_processors|processor_architecture)$/i.test(name)
  ));
}

/** Environment for the Next standalone server when run through Electron-as-Node. */
function buildNodeRuntimeEnv(frontendEnv) {
  return { ...frontendEnv, ELECTRON_RUN_AS_NODE: "1" };
}

module.exports = {
  buildBackendEnv,
  buildFrontendEnv,
  buildNodeRuntimeEnv,
  isFernetKey,
  isHttpUrl,
  isLoopbackUrl,
  validateConfig,
};
