// Knos's demand check talks to Qloo through this sidecar: it starts Qloo's canonical local MCP server (`qloo mcp`,
// @qloo/qloo-harness >= 0.1.26) with the OFFICIAL MCP SDK, exactly as Qloo's starter does
// (Qloo's starter kit on github.com/qloo, starter/mcp-client/backend.mjs, SDK @modelcontextprotocol/sdk 1.30.1), and
// relays tool calls from the Python service over stdin/stdout, one JSON object per line.
//
//   in : {"id": 1, "op": "init"}                                      -> server info, tool names, qloo_capabilities
//        {"id": 2, "op": "call", "name": "qloo_find_tags", "arguments": {...}}  -> {"structuredContent", "isError"}
//   out: {"id": 1, "ok": true, ...} | {"id": 1, "ok": false, "error": "..."}
//
// Install the SDK once (no package.json is kept in the repository): sh apps/wanted/bridge/install.sh
// The server command defaults to `qloo mcp`; QLOO_MCP_COMMAND + QLOO_MCP_ARGS_JSON replace it (Knos's MOCK server and
// the tests). The environment is forwarded as Qloo's starter does (`env: process.env`) so QLOO_API_KEY reaches the
// server; this file never reads, prints or logs any variable's value.
import { createInterface } from "node:readline";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const command = process.env.QLOO_MCP_COMMAND || "qloo";
const args = process.env.QLOO_MCP_ARGS_JSON ? JSON.parse(process.env.QLOO_MCP_ARGS_JSON) : ["mcp"];
const CALL_TIMEOUT_MS = Number(process.env.QLOO_MCP_TIMEOUT_MS || 60000);

let client = null;
const out = (obj) => process.stdout.write(`${JSON.stringify(obj)}\n`);

async function connect() {
  const transport = new StdioClientTransport({ command, args, env: process.env, stderr: "ignore" });
  const c = new Client({ name: "knos-demand-check", version: "0.3.33" });
  await c.connect(transport).catch((error) => {
    throw error.code === "ENOENT" ? new Error(`cannot start ${command}: npm install --global @qloo/qloo-harness`) : error;
  });
  return c;
}

async function handle(msg) {
  if (msg.op === "init") {
    client = client || (await connect());
    const { tools } = await client.listTools();
    const cap = await client.callTool({ name: "qloo_capabilities", arguments: {} });
    return { server: client.getServerVersion(), tools: tools.map((t) => t.name), capabilities: cap.structuredContent ?? null };
  }
  if (msg.op === "call") {
    if (!client) throw new Error("init first");
    const r = await client.callTool({ name: msg.name, arguments: msg.arguments ?? {} }, undefined, { timeout: CALL_TIMEOUT_MS });
    let env = r.structuredContent;
    if (env === undefined) {
      const text = (r.content ?? []).find((c) => c.type === "text")?.text;
      try { env = text ? JSON.parse(text) : undefined; } catch { env = undefined; }
    }
    return { structuredContent: env ?? null, isError: Boolean(r.isError) };
  }
  if (msg.op === "close") {
    if (client) await client.close();
    client = null;
    return { closed: true };
  }
  throw new Error(`unknown op ${msg.op}`);
}

const rl = createInterface({ input: process.stdin });
let chain = Promise.resolve();
rl.on("line", (line) => {
  if (!line.trim()) return;
  chain = chain.then(async () => {
    let msg;
    try { msg = JSON.parse(line); } catch { return out({ id: null, ok: false, error: "not JSON" }); }
    try { out({ id: msg.id, ok: true, ...(await handle(msg)) }); }
    catch (error) { out({ id: msg.id, ok: false, error: String(error?.message ?? error).slice(0, 300) }); }
  });
});
rl.on("close", async () => { await chain; if (client) await client.close().catch(() => {}); process.exit(0); });
