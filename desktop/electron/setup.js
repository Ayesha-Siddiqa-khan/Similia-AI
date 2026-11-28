"use strict";

const form = document.getElementById("config-form");
const save = document.getElementById("save");
const cancel = document.getElementById("cancel");
const formError = document.getElementById("form-error");
const importBackend = document.getElementById("import-backend");
const fields = [
  "supabaseUrl",
  "supabasePublishableKey",
  "supabaseSecretKey",
  "appEncryptionKey",
  "voyageApiKey",
  "anthropicApiKey",
  "anthropicModel",
];

function clearErrors() {
  formError.classList.remove("show");
  formError.textContent = "";
  document.querySelectorAll("[data-error-for]").forEach((element) => {
    element.textContent = "";
    element.classList.remove("show");
  });
}

function showErrors(errors) {
  for (const [field, message] of Object.entries(errors || {})) {
    if (field === "form" || field === "config") {
      formError.textContent = message;
      formError.classList.add("show");
      continue;
    }
    const target = document.querySelector(`[data-error-for="${field}"]`);
    if (target) {
      target.textContent = message;
      target.classList.add("show");
    } else {
      formError.textContent = message;
      formError.classList.add("show");
    }
  }
}

async function bootstrap() {
  const data = await window.similiaSetup.bootstrap();
  importBackend.hidden = data.build?.offlineTest !== false;
  document.getElementById("version").textContent = data.build?.version || "1.0.0";
  const config = data.config || {};
  document.getElementById("supabaseUrl").value = config.supabaseUrl || data.build?.supabaseUrl || "";
  document.getElementById("supabasePublishableKey").value =
    config.supabasePublishableKey || data.build?.supabasePublishableKey || "";
  document.getElementById("anthropicModel").value = config.anthropicModel || "";
  document.getElementById("clinicalWorkflowEnabled").checked = config.clinicalWorkflowEnabled === true;
  for (const field of ["supabaseSecretKey", "appEncryptionKey", "voyageApiKey", "anthropicApiKey"]) {
    const saved = document.getElementById(`saved-${field}`);
    if (saved) saved.hidden = !(config.has && config.has[field]);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearErrors();
  save.disabled = true;
  save.textContent = "Saving…";
  try {
    const values = {};
    for (const field of fields) values[field] = document.getElementById(field).value;
    values.clinicalWorkflowEnabled = document.getElementById("clinicalWorkflowEnabled").checked;
    const result = await window.similiaSetup.save(values);
    if (!result.ok) {
      showErrors(result.errors);
      save.disabled = false;
      save.textContent = "Save and start";
    }
  } catch (error) {
    showErrors({ form: error.message || "Could not save the configuration." });
    save.disabled = false;
    save.textContent = "Save and start";
  }
});

importBackend.addEventListener("click", async () => {
  clearErrors();
  importBackend.disabled = true;
  save.disabled = true;
  try {
    const result = await window.similiaSetup.importBackend();
    if (!result.ok && !result.canceled) showErrors(result.errors);
  } catch {
    showErrors({ form: "Could not import backend configuration." });
  } finally {
    importBackend.disabled = false;
    save.disabled = false;
  }
});

cancel.addEventListener("click", () => {
  void window.similiaSetup.cancel();
});

bootstrap().catch((error) => {
  showErrors({ form: error.message || "Could not read the current configuration." });
});
