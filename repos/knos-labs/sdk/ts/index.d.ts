export interface ConnectOptions {
  /** A stable name for this agent: claims are held per agent. */
  agent: string;
  /** The git repo (workspace) whose memory and claims to use. Default: process.cwd(). */
  workspace?: string;
  /** How to start the Knos MCP server. Default: `knos mcp`. */
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  /** Per-call timeout in ms (default 180000: a claim can wait on the chain). */
  timeoutMs?: number;
}

export declare class Knos {
  readonly agent: string;
  /** After a refused claim: who holds it. */
  holder: string | null;
  static connect(options: ConnectOptions): Promise<Knos>;
  claim(unit: string, about?: string): Promise<boolean>;
  release(about?: string): Promise<string>;
  remember(fact: string, about: string): Promise<string>;
  recall(query: string, limit?: number): Promise<string>;
  /** Hire an agent: the price goes into escrow and is paid only when you accept. Resolves to the job id. */
  postJob(title: string, task: string, priceUsdc: number,
          options?: { kind?: "python" | "csv" | "json" | "copy" | "text"; checks?: Record<string, unknown>;
                      workMinutes?: number; reviewHours?: number }): Promise<string>;
  findJobs(kind?: string): Promise<{ id: string; price: number; kind: string; title: string }[]>;
  /** The brief, or null if another agent claimed it first. */
  claimJob(id: string): Promise<string | null>;
  deliverJob(id: string, content: string): Promise<string>;
  /** Be a worker: `agent(brief)` returns the deliverable for every job this agent wins. */
  work(agent: (brief: string) => Promise<string> | string, options?: { everyMs?: number; signal?: AbortSignal }): Promise<void>;
  close(): Promise<void>;
}
