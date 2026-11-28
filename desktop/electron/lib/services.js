"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const { spawn, execFile } = require("node:child_process");
const { once } = require("node:events");

const { buildBackendEnv, buildFrontendEnv, buildNodeRuntimeEnv } = require("./env");

const MAX_LOG_BYTES = 10 * 1024 * 1024;

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => (port ? resolve(port) : reject(new Error("No free port found"))));
    });
  });
}

function redact(text, secrets) {
  let value = String(text);
  for (const secret of secrets) {
    if (secret && secret.length >= 8) value = value.split(secret).join("[redacted]");
  }
  return value;
}

class ServiceManager {
  constructor({ repoRoot, resourcesPath, fontDir, logsDir, onUnexpectedExit, dev = false }) {
    this.repoRoot = repoRoot;
    this.resourcesPath = resourcesPath;
    this.fontDir = fontDir;
    this.logsDir = logsDir;
    this.onUnexpectedExit = onUnexpectedExit;
    this.dev = dev;
    this.backend = null;
    this.frontend = null;
    this.stopping = false;
    this.started = false;
    this.frontendPort = 0;
    this.backendPort = 0;
    this.desktopToken = "";
    this.rendererToken = "";
    this.secrets = [];
    this.streams = [];
    this.buffers = new Map();
  }

  get origin() {
    return `http://127.0.0.1:${this.frontendPort}`;
  }

  _openLog(name) {
    fs.mkdirSync(this.logsDir, { recursive: true });
    const file = path.join(this.logsDir, `${name}.log`);
    try {
      if (fs.statSync(file).size > MAX_LOG_BYTES) fs.truncateSync(file, 0);
    } catch {
      // A new log file is fine.
    }
    const stream = fs.createWriteStream(file, { flags: "a" });
    this.streams.push(stream);
    return stream;
  }

  _attach(child, name, stream) {
    const write = (chunk) => {
      const combined = (this.buffers.get(name) || "") + chunk.toString("utf8");
      const lines = combined.split(/\r?\n/);
      this.buffers.set(name, lines.pop() || "");
      for (const line of lines) {
        if (line.trim()) {
          stream.write(`${new Date().toISOString()} ${redact(line, this.secrets)}\n`);
        }
      }
    };
    child.stdout?.on("data", write);
    child.stderr?.on("data", write);
    child.on("error", (error) => {
      child.launchError = error;
      stream.write(`${new Date().toISOString()} spawn error: ${error.message}\n`);
    });
    child.on("close", (code, signal) => {
      stream.write(`${new Date().toISOString()} exited code=${code} signal=${signal}\n`);
      if (!this.stopping && this.started) {
        this.onUnexpectedExit?.(name, code, signal);
      }
    });
  }

  _spawn(name, command, args, options) {
    const stream = this._openLog(name);
    const child = spawn(command, args, {
      ...options,
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    child.stdin.on("error", () => {});
    this._attach(child, name, stream);
    return child;
  }

  _backendCommand() {
    if (this.dev) {
      const python =
        process.env.SIMILIA_BACKEND_PYTHON ||
        path.join(this.repoRoot, "backend", ".venv", "Scripts", "python.exe");
      if (!fs.existsSync(python)) {
        throw new Error(
          `Backend virtual environment not found at ${python}. ` +
            "Run: cd backend && uv sync --group speech"
        );
      }
      return {
        command: python,
        args: [
          "desktop_entry.py",
          "--host",
          "127.0.0.1",
          "--port",
          String(this.backendPort),
        ],
        cwd: path.join(this.repoRoot, "backend"),
      };
    }
    const executable = path.join(this.resourcesPath, "backend", "similia-backend.exe");
    if (!fs.existsSync(executable)) {
      throw new Error(`Packaged backend not found at ${executable}. Run: npm run desktop:build`);
    }
    return {
      command: executable,
      args: ["--host", "127.0.0.1", "--port", String(this.backendPort)],
      cwd: path.dirname(executable),
    };
  }

  _frontendCommand() {
    if (this.dev) {
      const node = process.env.SIMILIA_NODE_BINARY || "node";
      const next = path.join(
        this.repoRoot,
        "frontend",
        "node_modules",
        "next",
        "dist",
        "bin",
        "next"
      );
      if (!fs.existsSync(next)) {
        throw new Error("Frontend dependencies not found. Run: cd frontend && npm install");
      }
      return {
        command: node,
        args: [next, "dev", "-H", "127.0.0.1", "-p", String(this.frontendPort)],
        cwd: path.join(this.repoRoot, "frontend"),
      };
    }
    const standalone = path.join(this.resourcesPath, "frontend");
    const server = path.join(standalone, "launch.cjs");
    if (!fs.existsSync(server)) {
      throw new Error(`Packaged frontend not found at ${server}. Run: npm run desktop:build`);
    }
    // Electron's own binary is a Node runtime when ELECTRON_RUN_AS_NODE=1.
    return { command: process.execPath, args: [server], cwd: standalone };
  }

  async _waitFor(label, child, url, headers, check, timeoutMs) {
    const deadline = Date.now() + timeoutMs;
    let lastError = "";
    while (Date.now() < deadline) {
      if (this.stopping) throw new Error("Application is closing.");
      if (child.launchError || child.exitCode !== null || child.signalCode !== null) {
        throw new Error(`${label} exited during startup. See ${this.logsDir}.`);
      }
      try {
        const response = await fetch(url, { headers, redirect: "error", signal: AbortSignal.timeout(3000), cache: "no-store" });
        const body = await response.json().catch(() => null);
        if (response.ok && check(body)) return body;
        lastError = `HTTP ${response.status}`;
      } catch (error) {
        lastError = error.message;
      }
      await delay(300);
    }
    throw new Error(
      `${label} did not become ready within ${Math.round(timeoutMs / 1000)}s ` +
        `(${lastError}). See ${this.logsDir}.`
    );
  }

  async start(config, paths) {
    this.stopping = false;
    this.frontendPort = await findFreePort();
    do {
      this.backendPort = await findFreePort();
    } while (this.backendPort === this.frontendPort);
    if (this.stopping) throw new Error("Application is closing.");
    this.desktopToken = crypto.randomBytes(32).toString("hex");
    this.rendererToken = crypto.randomBytes(32).toString("hex");
    this.secrets = [
      config.supabaseSecretKey,
      config.appEncryptionKey,
      config.voyageApiKey,
      config.anthropicApiKey,
      this.desktopToken,
      this.rendererToken,
    ].filter(Boolean);
    this.streams = [];

    const dev = this.dev;
    const backendEnv = buildBackendEnv({
      config,
      frontendPort: this.frontendPort,
      backendPort: this.backendPort,
      desktopToken: this.desktopToken,
      dataDir: paths.data,
      fontDir: this.fontDir,
      speechConfigPath: paths.speech,
      dev,
    });
    const frontendEnv = buildFrontendEnv({
      config,
      frontendPort: this.frontendPort,
      backendPort: this.backendPort,
      desktopToken: this.desktopToken,
      rendererToken: this.rendererToken,
      dev,
    });

    const backend = this._backendCommand();
    const frontend = this._frontendCommand();
    this.backend = this._spawn("backend", backend.command, backend.args, {
      cwd: backend.cwd,
      env: backendEnv,
    });
    await this._waitFor(
      "Backend",
      this.backend,
      `http://127.0.0.1:${this.backendPort}/health`,
      { "X-Similia-Desktop-Token": this.desktopToken },
      (body) => body?.status === "ok",
      120_000
    );
    if (this.stopping) throw new Error("Application is closing.");
    this.started = true;
    this.frontend = this._spawn("frontend", frontend.command, frontend.args, {
      cwd: frontend.cwd,
      env: dev ? frontendEnv : buildNodeRuntimeEnv(frontendEnv),
    });
    await this._waitFor(
      "Frontend",
      this.frontend,
      `http://127.0.0.1:${this.frontendPort}/api/health`,
      { "X-Similia-Renderer-Token": this.rendererToken },
      (body) => body?.backend === "ok",
      90_000
    );
    return { origin: this.origin, backendPort: this.backendPort, frontendPort: this.frontendPort };
  }

  async stop() {
    if (this.stopping) return;
    this.stopping = true;
    const backend = this.backend;
    const backendExited = backend?.pid && backend.exitCode === null && backend.signalCode === null
      ? once(backend, "exit").catch(() => {}) : Promise.resolve();
    const frontend = this.frontend;
    const frontendExited = frontend?.pid && frontend.exitCode === null && frontend.signalCode === null
      ? once(frontend, "exit").catch(() => {}) : Promise.resolve();
    frontend?.stdin.end();
    const frontendStopped = Promise.race([frontendExited, delay(1000)]).then(() => killTree(frontend));
    backend?.stdin.end();
    await Promise.race([backendExited, delay(8000)]);
    await Promise.all([frontendStopped, killTree(backend)]);

    this.frontend = null;
    this.backend = null;
    this.started = false;
    await Promise.all(this.streams.map((stream) => new Promise((resolve) => stream.end(resolve))));
    this.streams = [];
  }
}

async function killTree(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32") {
    await new Promise((resolve) => execFile(
      path.join(process.env.SystemRoot || "C:\\Windows", "System32", "taskkill.exe"),
      ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true, timeout: 5000 }, resolve
    ));
  }
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

module.exports = { ServiceManager, findFreePort };
