"use strict";

const fs = require("node:fs");
const { isIP } = require("node:net");
const { parseEnv } = require("node:util");
const { validateConfig, isFernetKey } = require("./env");

const offlineProject = {
  supabaseUrl: "http://127.0.0.1:39437",
  supabasePublishableKey: "similia-offline-test-publishable",
  offlineTest: true,
};

function readLocalEnv(file) {
  try {
    const fd = fs.openSync(file, "r");
    try {
      const stat = fs.fstatSync(fd);
      if (!stat.isFile() || stat.size > 128 * 1024) throw new Error();
      return parseEnv(fs.readFileSync(fd, "utf8"));
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    throw new Error("Could not read a local configuration file. Select the project's .env file.");
  }
}

function projectOrigin(value) {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && !url.username && !url.password && !url.search &&
        !url.hash && url.pathname === "/" && url.hostname.includes(".") &&
        !url.hostname.endsWith(".localhost") && url.hostname !== "placeholder.supabase.co" &&
        !isIP(url.hostname)) return url.origin;
  } catch {}
  return "";
}

function isPublishable(key) {
  if (/^sb_publishable_[\w-]+$/.test(key)) return true;
  try {
    const parts = key.split(".");
    return parts.length === 3 &&
      JSON.parse(Buffer.from(parts[1], "base64url").toString("utf8")).role === "anon";
  } catch {
    return false;
  }
}

function personalProject(env) {
  const supabaseUrl = projectOrigin(env.NEXT_PUBLIC_SUPABASE_URL);
  const supabasePublishableKey = env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "";
  if (!supabaseUrl || !isPublishable(supabasePublishableKey)) {
    throw new Error("Personal build requires a real HTTPS Supabase URL and publishable key in frontend/.env.local.");
  }
  return { supabaseUrl, supabasePublishableKey, offlineTest: false };
}

function importBackendConfig(env, build) {
  if (build.offlineTest !== false || !projectOrigin(build.supabaseUrl) ||
      projectOrigin(env.SUPABASE_URL) !== build.supabaseUrl ||
      env.SUPABASE_PUBLISHABLE_KEY !== build.supabasePublishableKey) {
    throw new Error("The selected backend configuration does not match this installer's Supabase project and public key.");
  }
  const config = {
    supabaseUrl: build.supabaseUrl,
    supabasePublishableKey: build.supabasePublishableKey,
    supabaseSecretKey: env.SUPABASE_SECRET_KEY || "",
    appEncryptionKey: env.APP_ENCRYPTION_KEY || "",
    appEncryptionKeyPrevious: env.APP_ENCRYPTION_KEY_PREVIOUS || "",
    voyageApiKey: env.VOYAGE_API_KEY || "",
    voyageModel: env.VOYAGE_MODEL || "",
    embeddingBudgetTokens: env.EMBEDDING_BUDGET_TOKENS || "",
    clinicalWorkflowEnabled: /^(?:true|1|yes|on)$/i.test(env.CLINICAL_WORKFLOW_ENABLED || ""),
  };
  const validation = validateConfig(config);
  const invalidBudget = config.embeddingBudgetTokens && !/^\d+$/.test(config.embeddingBudgetTokens);
  const invalidPrevious = config.appEncryptionKeyPrevious &&
    !config.appEncryptionKeyPrevious.split(",").filter((key) => key.trim()).every((key) => isFernetKey(key.trim()));
  if (!validation.ok || invalidBudget || invalidPrevious ||
      config.supabaseSecretKey === config.supabasePublishableKey || isPublishable(config.supabaseSecretKey)) {
    throw new Error("The backend configuration has missing or invalid credentials or settings. Check the selected .env locally.");
  }
  return config;
}

module.exports = { offlineProject, readLocalEnv, personalProject, importBackendConfig };
