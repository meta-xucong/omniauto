import fs from "node:fs";

const [, , requestPath, summaryPath, eventsPath] = process.argv;

if (!requestPath || !summaryPath || !eventsPath) {
  console.error("usage: node codex_app_server_rpc.mjs <request.json> <summary.json> <events.jsonl>");
  process.exit(2);
}

const request = JSON.parse(fs.readFileSync(requestPath, "utf8"));
const startedAt = new Date().toISOString();
const wsUrl = request.endpoint;
const timeoutMs = Number(request.timeout_ms || 180000);
const notifications = [];
const agentMessages = [];
let nextId = 1;
const pending = new Map();
let finalWritten = false;
let threadId = request.thread_id || null;
let turnId = null;
let completedTurn = null;
let initialized = null;
let startResult = null;
let resumeResult = null;
let readResult = null;
let listResult = null;

function appendEvent(obj) {
  fs.appendFileSync(eventsPath, JSON.stringify({ ts: new Date().toISOString(), ...obj }) + "\n", "utf8");
}

function writeSummary(status, extra = {}) {
  if (finalWritten) {
    return null;
  }
  finalWritten = true;
  const assistantText = agentMessages
    .filter((item) => !turnId || item.turnId === turnId)
    .map((item) => item.text)
    .join("\n")
    .trim();
  const summary = {
    status,
    endpoint: wsUrl,
    startedAt,
    finishedAt: new Date().toISOString(),
    threadId,
    turnId,
    assistantText,
    initialized,
    startResult,
    resumeResult,
    completedTurn,
    readResult,
    listHit: Boolean(listResult?.data?.some((thread) => thread.id === threadId)),
    notificationsSeen: notifications.map((item) => item.method),
    ...extra,
  };
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2), "utf8");
  console.log(JSON.stringify(summary, null, 2));
  return summary;
}

function fail(error) {
  if (finalWritten) {
    return;
  }
  writeSummary("error", { error: String(error?.stack || error) });
  process.exit(1);
}

function sendNotification(ws, method, params) {
  const message = params === undefined ? { method } : { method, params };
  appendEvent({ direction: "send", message });
  ws.send(JSON.stringify(message));
}

function rpc(ws, method, params) {
  const id = nextId++;
  const message = { id, method };
  if (params !== undefined) {
    message.params = params;
  }
  appendEvent({ direction: "send", message });
  ws.send(JSON.stringify(message));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      if (pending.has(id)) {
        pending.delete(id);
        reject(new Error(`timeout waiting for ${method}#${id}`));
      }
    }, timeoutMs);
    pending.set(id, { method, resolve, reject, timer });
  });
}

function handleMessage(message) {
  appendEvent({ direction: "recv", message });
  if (Object.prototype.hasOwnProperty.call(message, "id") && pending.has(message.id)) {
    const entry = pending.get(message.id);
    pending.delete(message.id);
    clearTimeout(entry.timer);
    if (message.error) {
      entry.reject(new Error(`${entry.method} error ${message.error.code}: ${message.error.message}`));
    } else {
      entry.resolve(message.result);
    }
    return;
  }

  if (!message.method) {
    return;
  }
  notifications.push(message);
  if (message.method === "item/completed" && message.params?.item?.type === "agentMessage") {
    agentMessages.push({
      text: message.params.item.text || "",
      threadId: message.params.threadId,
      turnId: message.params.turnId,
    });
  }
  if (message.method === "turn/completed" && message.params?.threadId === threadId) {
    completedTurn = message.params.turn;
  }
}

function buildThreadStartParams() {
  return {
    model: request.model || null,
    cwd: request.cwd || null,
    approvalPolicy: request.approval_policy || "never",
    sandbox: request.sandbox || "read-only",
    serviceName: request.service_name || "codex-wechat-bridge",
    ephemeral: false,
    experimentalRawEvents: false,
    persistExtendedHistory: true,
  };
}

function buildTurnStartParams() {
  return {
    threadId,
    input: [
      {
        type: "text",
        text: request.prompt,
        text_elements: [],
      },
    ],
    cwd: request.cwd || null,
    approvalPolicy: request.approval_policy || "never",
    model: request.model || null,
  };
}

async function run() {
  if (!globalThis.WebSocket) {
    throw new Error("This Node runtime does not expose global WebSocket; use Node 22+.");
  }
  if (!wsUrl) {
    throw new Error("request.endpoint is required");
  }
  const action = request.action || "send_prompt";
  if (action === "send_prompt" && !request.prompt) {
    throw new Error("request.prompt is required");
  }

  const ws = new WebSocket(wsUrl);
  const overallTimer = setTimeout(() => fail(new Error("overall timeout")), timeoutMs + 30000);

  ws.onmessage = (event) => {
    try {
      handleMessage(JSON.parse(event.data));
    } catch (error) {
      fail(error);
    }
  };
  ws.onerror = (event) => fail(new Error(String(event?.message || event)));

  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve, { once: true });
    ws.addEventListener("error", (event) => reject(new Error(String(event?.message || event))), {
      once: true,
    });
  });
  ws.onerror = (event) => fail(new Error(String(event?.message || event)));

  initialized = await rpc(ws, "initialize", {
    clientInfo: {
      name: "codex-wechat-bridge",
      title: "Codex WeChat Bridge",
      version: "0.1.0",
    },
    capabilities: {
      experimentalApi: true,
      optOutNotificationMethods: [],
    },
  });
  sendNotification(ws, "initialized");

  if (action === "list_threads") {
    listResult = await rpc(ws, "thread/list", {
      limit: Number(request.limit || 20),
      sortKey: request.sort_key || "updated_at",
      archived: Boolean(request.archived || false),
    });
    clearTimeout(overallTimer);
    writeSummary("ok", { threads: listResult?.data || [] });
    ws.onerror = null;
    ws.close();
    process.exit(0);
  }

  if (threadId) {
    resumeResult = await rpc(ws, "thread/resume", {
      threadId,
      model: request.model || null,
      cwd: request.cwd || null,
      approvalPolicy: request.approval_policy || "never",
      sandbox: request.sandbox || "read-only",
      persistExtendedHistory: true,
    });
  } else {
    startResult = await rpc(ws, "thread/start", buildThreadStartParams());
    threadId = startResult.thread.id;
    if (request.title) {
      await rpc(ws, "thread/name/set", { threadId, name: request.title });
    }
  }

  const turnResult = await rpc(ws, "turn/start", buildTurnStartParams());
  turnId = turnResult.turn.id;

  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (completedTurn?.id === turnId) {
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  if (!completedTurn || completedTurn.id !== turnId) {
    throw new Error(`turn ${turnId} did not complete before timeout`);
  }

  readResult = await rpc(ws, "thread/read", { threadId, includeTurns: true });
  listResult = await rpc(ws, "thread/list", { limit: 20, sortKey: "updated_at", archived: false });
  clearTimeout(overallTimer);
  writeSummary("ok");
  ws.onerror = null;
  ws.close();
  process.exit(0);
}

run().catch(fail);
