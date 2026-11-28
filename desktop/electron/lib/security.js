"use strict";

const applicationWebPreferences = Object.freeze({
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  webviewTag: false,
  devTools: true,
  spellcheck: false,
});

function developerToolsMenuItems(allowedContents) {
  const click = (_item, window) => {
    const contents = window?.webContents;
    if (contents && allowedContents.has(contents.id)) contents.toggleDevTools();
  };
  return [
    { label: "Toggle Developer Tools", accelerator: "F12", click },
    { label: "Toggle Developer Tools (alternate shortcut)", accelerator: "Ctrl+Shift+I", click },
  ];
}

function originOf(url) {
  try {
    return new URL(url).origin;
  } catch {
    return "";
  }
}

function isAllowedSender(event, window, allowedOrigin) {
  try {
    return Boolean(window && event.sender === window.webContents && event.senderFrame &&
      event.senderFrame === event.sender.mainFrame && event.senderFrame.origin === allowedOrigin);
  } catch {
    return false;
  }
}

/** Only the local app may use the microphone; every other permission is denied. */
function applySessionHardening(session, contents, allowedContents, allowedOrigin, token) {
  session.webRequest.onBeforeSendHeaders({ urls: ["http://127.0.0.1/*"] }, (details, callback) => {
    if (originOf(details.url) === allowedOrigin && allowedContents.has(details.webContentsId) &&
        (!details.initiatorOrigin || details.initiatorOrigin === allowedOrigin)) {
      details.requestHeaders["X-Similia-Renderer-Token"] = token;
    }
    callback({ requestHeaders: details.requestHeaders });
  });
  session.setPermissionRequestHandler((webContents, permission, callback, details) => {
    callback(webContents === contents && permission === "media" && details.isMainFrame &&
      details.mediaTypes?.length === 1 && details.mediaTypes[0] === "audio" &&
      originOf(details.requestingUrl) === allowedOrigin);
  });
  session.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    return webContents === contents && permission === "media" && details.isMainFrame &&
      details.mediaType === "audio" && originOf(requestingOrigin) === allowedOrigin;
  });
  if (typeof session.setDisplayMediaRequestHandler === "function") {
    session.setDisplayMediaRequestHandler((_request, callback) => callback({}));
  }
}

function hardenWebContents(contents, allowedOrigin, openLocalWindow) {
  contents.setWindowOpenHandler(({ url }) => {
    if (openLocalWindow && originOf(url) === allowedOrigin) openLocalWindow(url);
    return { action: "deny" };
  });
  contents.on("will-navigate", (event, url) => {
    if (originOf(url) !== allowedOrigin) event.preventDefault();
  });
  contents.on("will-redirect", (event, url) => {
    if (originOf(url) !== allowedOrigin) event.preventDefault();
  });
  contents.on("will-attach-webview", (event) => event.preventDefault());
}

module.exports = {
  applicationWebPreferences, developerToolsMenuItems,
  applySessionHardening, hardenWebContents, isAllowedSender, originOf,
};
