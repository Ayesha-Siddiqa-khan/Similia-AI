"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { app, safeStorage } = require("electron");

const SECRET_FIELDS = [
  "supabaseSecretKey", "appEncryptionKey", "appEncryptionKeyPrevious", "voyageApiKey", "anthropicApiKey",
];

function paths() {
  const userData = app.getPath("userData");
  return {
    userData,
    config: path.join(userData, "config.json"),
    data: path.join(userData, "data"),
    logs: path.join(userData, "logs"),
    speech: path.join(userData, "speech-settings.json"),
  };
}

function ensureDirectories() {
  const locations = paths();
  for (const directory of [locations.userData, locations.data, locations.logs]) {
    fs.mkdirSync(directory, { recursive: true });
  }
  return locations;
}

async function encrypt(value) {
  if (!value) return "";
  if (!await safeStorage.isAsyncEncryptionAvailable()) {
    throw new Error(
      "Windows credential protection is unavailable. Sign in to Windows and try again."
    );
  }
  return (await safeStorage.encryptStringAsync(String(value))).toString("base64");
}

async function decrypt(value) {
  if (!value) return "";
  try {
    if (!await safeStorage.isAsyncEncryptionAvailable()) return "";
    return (await safeStorage.decryptStringAsync(Buffer.from(value, "base64"))).result;
  } catch {
    return "";
  }
}

async function readConfigFile() {
  const file = paths().config;
  if (!fs.existsSync(file)) return null;
  try {
    const stored = JSON.parse(fs.readFileSync(file, "utf8"));
    const encrypted = stored.encrypted || {};
    return {
      supabaseUrl: stored.supabaseUrl || "",
      supabasePublishableKey: stored.supabasePublishableKey || "",
      supabaseSecretKey: await decrypt(encrypted.supabaseSecretKey),
      appEncryptionKey: await decrypt(encrypted.appEncryptionKey),
      appEncryptionKeyPrevious: await decrypt(encrypted.appEncryptionKeyPrevious),
      voyageApiKey: await decrypt(encrypted.voyageApiKey),
      anthropicApiKey: await decrypt(encrypted.anthropicApiKey),
      anthropicModel: stored.anthropicModel || "",
      voyageModel: stored.voyageModel || "",
      embeddingBudgetTokens: stored.embeddingBudgetTokens || "",
      clinicalWorkflowEnabled: stored.clinicalWorkflowEnabled === true,
      modelPath: stored.modelPath || "",
    };
  } catch {
    return null;
  }
}

async function writeConfigFile(config) {
  const locations = ensureDirectories();
  const encrypted = {};
  for (const field of SECRET_FIELDS) {
    if (config[field]) encrypted[field] = await encrypt(config[field]);
  }
  const stored = {
    version: 1,
    supabaseUrl: config.supabaseUrl,
    supabasePublishableKey: config.supabasePublishableKey,
    anthropicModel: config.anthropicModel || "",
    voyageModel: config.voyageModel || "",
    embeddingBudgetTokens: config.embeddingBudgetTokens || "",
    clinicalWorkflowEnabled: config.clinicalWorkflowEnabled === true,
    modelPath: config.modelPath || "",
    encrypted,
    updatedAt: new Date().toISOString(),
  };
  const temporary = `${locations.config}.${randomUUID()}.tmp`;
  try {
    fs.writeFileSync(temporary, JSON.stringify(stored, null, 2), {
      encoding: "utf8", mode: 0o600, flag: "wx",
    });
    fs.renameSync(temporary, locations.config);
  } finally {
    fs.rmSync(temporary, { force: true });
  }
  try {
    fs.chmodSync(locations.config, 0o600);
  } catch {
    // Windows inherits the user profile ACL; chmod is a best-effort extra.
  }
}

/** Test/automation hook. Never used by an installed app unless smoke mode is on. */
function configFromEnvironment() {
  const inline = process.env.SIMILIA_DESKTOP_CONFIG_JSON;
  const file = process.env.SIMILIA_DESKTOP_CONFIG_FILE;
  let value = null;
  try {
    if (inline) value = JSON.parse(inline);
    else if (file) value = JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
  if (!value) return null;
  return {
    supabaseUrl: value.supabaseUrl || "",
    supabasePublishableKey: value.supabasePublishableKey || "",
    supabaseSecretKey: value.supabaseSecretKey || "",
    appEncryptionKey: value.appEncryptionKey || "",
    voyageApiKey: value.voyageApiKey || "",
    anthropicApiKey: value.anthropicApiKey || "",
    anthropicModel: value.anthropicModel || "",
    modelPath: value.modelPath || "",
  };
}

async function loadConfig({ smoke = false } = {}) {
  if (smoke) return configFromEnvironment();
  return readConfigFile();
}

async function saveConfig(config) {
  await writeConfigFile(config);
}

function publicConfig(config) {
  if (!config) return null;
  return {
    supabaseUrl: config.supabaseUrl,
    supabasePublishableKey: config.supabasePublishableKey,
    anthropicModel: config.anthropicModel,
    clinicalWorkflowEnabled: config.clinicalWorkflowEnabled,
    modelPath: config.modelPath,
    has: {
      supabaseSecretKey: Boolean(config.supabaseSecretKey),
      appEncryptionKey: Boolean(config.appEncryptionKey),
      voyageApiKey: Boolean(config.voyageApiKey),
      anthropicApiKey: Boolean(config.anthropicApiKey),
    },
  };
}

function readBuildMetadata() {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, "desktop-build.json")]
    : [path.join(__dirname, "..", "..", "resources", "desktop-build.json")];
  for (const file of candidates) {
    try {
      if (fs.existsSync(file)) return JSON.parse(fs.readFileSync(file, "utf8"));
    } catch {
      // A missing or malformed metadata file only means the setup form starts blank.
    }
  }
  return { version: app.getVersion() };
}

module.exports = {
  SECRET_FIELDS,
  ensureDirectories,
  loadConfig,
  paths,
  publicConfig,
  readBuildMetadata,
  readConfigFile,
  saveConfig,
  validateConfig: require("./env").validateConfig,
};
