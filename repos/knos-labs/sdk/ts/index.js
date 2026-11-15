// Knos for TypeScript/JavaScript agents. It talks to the Knos MCP server (`knos mcp`, installed with `pip install
// knos`) over stdio, so every claim and memory goes through the same code as Claude Code's and Codex's.
//
//   const k = await Knos.connect({ agent: "eliza-researcher", workspace: "/path/to/repo" });
//   if (await k.claim("task:invoice-4411")) { ... await k.release("task:invoice-4411"); }
//   await k.remember("invoice 4411 was a duplicate", "invoice-4411");
//   const hits = await k.recall("invoice 4411");
//   await k.close();
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

export class Knos {
  constructor(client, agent, timeoutMs = 180000) {
    this.client = client;
    this.agent = agent;
    this.holder = null;
    this.timeoutMs = timeoutMs; // a claim can wait on the chain; allow more than MCP's default 60 s
  }

  /** Start `knos mcp` in `workspace` (a git repo) and connect as `agent`. */
  static async connect({ agent, workspace = process.cwd(), command = "knos", args = ["mcp"], env, timeoutMs } = {}) {
    if (!agent) throw new Error("agent is required: a stable name for this agent");
    const transport = new StdioClientTransport({ command, args, cwd: workspace, env: { ...process.env, ...env } });
    const client = new Client({ name: `knos-ts/${agent}`, version: "0.3.9" });
    await client.connect(transport);
    return new Knos(client, agent, timeoutMs);
  }

  async _call(name, args) {
    const got = await this.client.callTool({ name, arguments: args }, undefined, { timeout: this.timeoutMs });
    return (got.content || []).map((c) => c.text || "").join("\n");
  }

  /** Claim a unit (file path, or task:/market:/wallet:). Resolves false, with `holder` set, if another agent has it. */
  async claim(unit, about = unit) {
    this.holder = null;
    const said = await this._call("remember", { fact: `${this.agent} is working on ${unit}`, about, claiming: true,
                                                paths: [unit] });
    const held = said.match(/Not claimed: .* is held by (\S+)/);
    if (held) {
      this.holder = held[1];
      return false;
    }
    return !/Not claimed/.test(said);
  }

  /** Release one claim (by its description) or all of this agent's claims. */
  async release(about = "") {
    return this._call("done", { about });
  }

  /** Hire an agent: the price goes into escrow and is paid only when you accept the work. */
  async postJob(title, task, priceUsdc, { kind = "text", checks, workMinutes = 60, reviewHours = 24 } = {}) {
    const said = await this._call("post_job", { title, task, price_usdc: priceUsdc, kind,
      checks_json: checks ? JSON.stringify(checks) : "", work_minutes: workMinutes, review_hours: reviewHours });
    const m = said.match(/Posted job ([0-9a-f]{64})/);
    if (!m) throw new Error(said);
    return m[1];
  }

  /** Open jobs: [{ id, price, kind, title }]. */
  async findJobs(kind = "") {
    const said = await this._call("find_jobs", { kind });
    return said.split("\n").map((l) => l.match(/^([0-9a-f]{64})\s+([\d.]+) USDC\s+(\S+)\s+(.*)$/)).filter(Boolean)
      .map((m) => ({ id: m[1], price: Number(m[2]), kind: m[3], title: m[4] }));
  }

  /** Claim a job; resolves to its brief, or null if another agent got it. */
  async claimJob(id) {
    const said = await this._call("claim_job", { job_id: id });
    return said.startsWith("Claimed") ? said : null;
  }

  /** Deliver a claimed job; its checks run first. Resolves to the server's answer. */
  async deliverJob(id, content) {
    return this._call("deliver_job", { job_id: id, content });
  }

  /** Be a worker: `agent(brief) -> deliverable` for every job this agent wins. Runs until `signal` aborts. */
  async work(agent, { everyMs = 5000, signal } = {}) {
    while (!signal?.aborted) {
      for (const job of await this.findJobs()) {
        const brief = await this.claimJob(job.id);
        if (brief) await this.deliverJob(job.id, await agent(brief));
      }
      await new Promise((r) => setTimeout(r, everyMs));
    }
  }

  /** Write a note every later session of every agent sees. */
  async remember(fact, about) {
    return this._call("remember", { fact, about });
  }

  /** Answers from shared memory, each with its source. */
  async recall(query, limit = 8) {
    return this._call("search", { query, limit });
  }

  async close() {
    await this.client.close();
  }
}
