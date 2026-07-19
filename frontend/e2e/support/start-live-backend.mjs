import { cp, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { createConnection, createServer } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../../..");
const backend = join(root, "backend");
const sourceWorkspace = resolve(
  process.env.TAME_INK_WORKSPACE ?? join(backend, ".tame-ink-workspace"),
);
const artifactDir = resolve(
  process.env.TAME_INK_LIVE_ARTIFACT_DIR ?? join(root, "output/live"),
);
const port = Number(process.env.TAME_INK_E2E_API_PORT ?? 8010);
const runId = process.env.TAME_INK_RUN_ID ?? `e2e-${Date.now()}`;

for (const name of [
  "TAME_INK_INPUT_PRICE_CNY_PER_1M_TOKENS",
  "TAME_INK_OUTPUT_PRICE_CNY_PER_1M_TOKENS",
]) {
  if (!process.env[name]) throw new Error(`${name} is required for live E2E`);
  if (
    !Number.isFinite(Number(process.env[name])) ||
    Number(process.env[name]) <= 0
  ) {
    throw new Error(`${name} must be a positive number`);
  }
}
const maxCost = Number(process.env.TAME_INK_MAX_COST_CNY ?? "20");
if (!Number.isFinite(maxCost) || maxCost <= 0)
  throw new Error("TAME_INK_MAX_COST_CNY must be a positive number");

await new Promise((resolveAvailable, rejectUnavailable) => {
  const server = createServer();
  server.once("error", () =>
    rejectUnavailable(new Error(`port ${port} is already in use`)),
  );
  server.listen(port, "127.0.0.1", () => server.close(resolveAvailable));
});

await mkdir(artifactDir, { recursive: true });
const temporaryWorkspace = await mkdtemp(join(artifactDir, "workspace-"));
await cp(
  join(sourceWorkspace, "settings.json"),
  join(temporaryWorkspace, "settings.json"),
);
const usageLog = resolve(
  process.env.TAME_INK_USAGE_LOG ?? join(artifactDir, `${runId}-usage.jsonl`),
);
await writeFile(
  join(artifactDir, "e2e-workspace-path.txt"),
  `${temporaryWorkspace}\n`,
  "utf8",
);
await writeFile(
  join(artifactDir, "e2e-usage-path.txt"),
  `${usageLog}\n`,
  "utf8",
);

const api = spawn(
  "uv",
  [
    "run",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    String(port),
  ],
  {
    cwd: backend,
    env: {
      ...process.env,
      TAME_INK_WORKSPACE: temporaryWorkspace,
      TAME_INK_USAGE_LOG: usageLog,
      TAME_INK_RUN_ID: runId,
    },
    stdio: "inherit",
  },
);
const worker = spawn(
  "uv",
  [
    "run",
    "huey_consumer",
    "app.infrastructure.worker.huey",
    "-w",
    "1",
    "-k",
    "thread",
  ],
  {
    cwd: backend,
    env: {
      ...process.env,
      TAME_INK_WORKSPACE: temporaryWorkspace,
      TAME_INK_USAGE_LOG: usageLog,
      TAME_INK_RUN_ID: runId,
    },
    stdio: "inherit",
  },
);
const children = [api, worker];
let cleaning = false;

async function cleanup() {
  if (cleaning) return;
  cleaning = true;
  for (const child of children)
    if (child.exitCode === null) child.kill("SIGTERM");
  await rm(temporaryWorkspace, { recursive: true, force: true });
}

for (const child of children) {
  child.once("exit", (code, signal) => {
    if (cleaning) return;
    console.error(
      `live backend process exited unexpectedly: code=${code} signal=${signal}`,
    );
    void cleanup().finally(() => process.exit(code && code !== 0 ? code : 1));
  });
}

function isHealthy() {
  return new Promise((resolveConnection) => {
    const socket = createConnection({ host: "127.0.0.1", port }, () => {
      socket.destroy();
      resolveConnection(true);
    });
    socket.once("error", () => resolveConnection(false));
  });
}

let healthy = false;
for (let attempt = 0; attempt < 60; attempt += 1) {
  for (const child of children) {
    if (child.exitCode !== null)
      throw new Error(`live backend process exited with ${child.exitCode}`);
  }
  if (await isHealthy()) {
    healthy = true;
    break;
  }
  await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
}
if (!healthy) {
  await cleanup();
  throw new Error("live backend did not start");
}

process.once("SIGTERM", async () => {
  await cleanup();
  process.exit(0);
});
process.once("SIGINT", async () => {
  await cleanup();
  process.exit(130);
});

await new Promise(() => {});
