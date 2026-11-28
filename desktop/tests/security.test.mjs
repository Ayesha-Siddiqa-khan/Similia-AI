import assert from "node:assert/strict";
import test from "node:test";

import {
  applicationWebPreferences, applySessionHardening, developerToolsMenuItems, isAllowedSender,
} from "../electron/lib/security.js";

const origin = "http://127.0.0.1:41000";

test("both DevTools accelerators toggle only the focused app or report window", () => {
  const items = developerToolsMenuItems(new Set([1, 2]));
  assert.deepEqual(items.map(({ accelerator }) => accelerator), ["F12", "Ctrl+Shift+I"]);
  const toggled = [];
  const window = (id) => ({ webContents: { id, toggleDevTools: () => toggled.push(id) } });
  items[0].click(null, window(1));
  items[1].click(null, window(2));
  items[0].click(null, window(3));
  items[1].click(null, undefined);
  assert.deepEqual(toggled, [1, 2]);
});

test("DevTools are available with isolated and sandboxed app web preferences", () => {
  assert.equal(applicationWebPreferences.devTools, true);
  assert.equal(applicationWebPreferences.contextIsolation, true);
  assert.equal(applicationWebPreferences.sandbox, true);
  assert.equal(applicationWebPreferences.nodeIntegration, false);
  assert.equal(applicationWebPreferences.webviewTag, false);
});

test("desktop IPC is restricted to the window's main frame", () => {
  const frame = { origin };
  const sender = { id: 1, mainFrame: frame };
  const window = { webContents: sender };
  assert.equal(isAllowedSender({ sender, senderFrame: frame }, window, origin), true);
  assert.equal(isAllowedSender({ sender, senderFrame: { origin } }, window, origin), false);
  assert.equal(isAllowedSender({ sender, senderFrame: frame }, window, "https://example.test"), false);
  assert.equal(isAllowedSender({ sender, senderFrame: frame }, null, origin), false);
});

test("only authorized local windows receive the frontend token", () => {
  let intercept;
  const session = {
    webRequest: { onBeforeSendHeaders: (_filter, handler) => { intercept = handler; } },
    setPermissionRequestHandler() {},
    setPermissionCheckHandler() {},
  };
  applySessionHardening(session, { id: 1 }, new Set([1, 2]), origin, "fixture-token");
  const headers = (overrides) => {
    let sent;
    intercept({ url: origin + "/login", webContentsId: 1, requestHeaders: {}, ...overrides },
      (result) => { sent = result.requestHeaders; });
    return sent;
  };
  assert.equal(headers({})["X-Similia-Renderer-Token"], "fixture-token");
  assert.equal(headers({ webContentsId: 2 })["X-Similia-Renderer-Token"], "fixture-token");
  assert.deepEqual(headers({ webContentsId: 3 }), {});
  assert.deepEqual(headers({ url: "http://127.0.0.1:41001/login" }), {});
  assert.deepEqual(headers({ initiatorOrigin: "https://example.test" }), {});
});
