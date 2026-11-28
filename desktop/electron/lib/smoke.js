"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const { setTimeout: delay } = require("node:timers/promises");
const { BrowserWindow } = require("electron");

async function waitFor(contents, js, label) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (await contents.executeJavaScript(js).catch(() => false)) return;
    await delay(250);
  }
  throw new Error(`Timed out waiting for ${label} (${new URL(contents.getURL()).pathname}).`);
}

async function runSmoke(window, services, config) {
  const contents = window.webContents;
  const fetchLocal = (url) => fetch(url, { redirect: "manual", signal: AbortSignal.timeout(5000) });
  assert.equal((await fetchLocal(`${services.origin}/login`)).status, 403);
  assert.equal((await fetchLocal(`http://127.0.0.1:${services.backendPort}/health`)).status, 401);
  await waitFor(contents, 'document.querySelector("#email") !== null', "sign-in form");
  const platform = await contents.executeJavaScript("window.similiaDesktop.getInfo().then(info => info.platform)");
  assert.equal(platform, "win32");
  const checks = ["authenticated readiness", "loopback access controls", "sign-in rendered"];
  if (!config.supabaseUrl.startsWith("http://127.0.0.1:")) return checks;

  // The fixture account and data exist solely in the smoke script's loopback server.
  await contents.executeJavaScript(`(() => {
    for (const [id, value] of [["email", "desktop-test@example.test"], ["password", "offline-test"]]) {
      const input = document.getElementById(id);
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(input, value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }
    document.querySelector("form button[type=submit], form button:not([type])").click();
  })()`);
  await waitFor(contents, 'location.pathname.startsWith("/workspace/")', "authenticated dashboard");
  const result = await contents.executeJavaScript(`(async () => {
    const list = await fetch("/api/backend/cases");
    if (!list.ok) return { list: list.status };
    const [record] = await list.json();
    const response = await fetch('/api/backend/cases/' + record.id, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({chief_complaint: 'Updated synthetic desktop case'}),
    });
    return { id: record.id, status: response.status, complaint: (await response.json()).chief_complaint };
  })()`);
  assert.equal(result.status, 200, `Fixture case request failed: ${JSON.stringify(result)}`);
  assert.equal(result.complaint, "Updated synthetic desktop case");
  await window.loadURL(`${services.origin}/workspace/case/${result.id}`);
  await waitFor(contents, '[...document.querySelectorAll("textarea")].some((el) => el.value === "Updated synthetic desktop case")', "case editor");
  checks.push("Supabase fixture sign-in", "synthetic case read, update and rendering");
  const reportUrl = `${services.origin}/workspace/report/${result.id}`;
  await contents.executeJavaScript(`window.open(${JSON.stringify(reportUrl)}, "_blank"); undefined;`, true);
  let report;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    report = BrowserWindow.getAllWindows().find((candidate) =>
      candidate !== window && candidate.webContents.getURL() === reportUrl);
    if (report) break;
    await delay(250);
  }
  assert.ok(report, "The report did not open in a separate local window.");
  report.close();
  checks.push("local report window");

  const model = process.env.SIMILIA_SMOKE_MODEL;
  const audio = process.env.SIMILIA_SMOKE_AUDIO;
  if (model && audio) {
    const wave = fs.readFileSync(audio).toString("base64");
    const speech = await contents.executeJavaScript(`(async () => {
      const settings = await fetch('/api/backend/speech/settings', {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model_path: ${JSON.stringify(model)}, device: 'cpu', compute_type: 'int8' }),
      });
      if (!settings.ok) return { status: settings.status, ...(await settings.json()) };
      const form = new FormData();
      form.set('audio', new Blob([Uint8Array.from(atob(${JSON.stringify(wave)}), char => char.charCodeAt(0))], { type: 'audio/wav' }), 'fixture.wav');
      form.set('language', 'en');
      const response = await fetch('/api/backend/speech/transcribe', { method: 'POST', body: form });
      return { status: response.status, ...(await response.json()) };
    })()`);
    assert.equal(speech.status, 200, `Packaged transcription failed: ${speech.detail}`);
    assert.ok(/desktop/i.test(speech.text), `Unexpected synthetic transcript: ${speech.text}`);
    checks.push("external model and frozen worker transcription");
  }
  return checks;
}

module.exports = { runSmoke };
