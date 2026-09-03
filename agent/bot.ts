/**
 * One process: the Virtuals agent, its Telegram face, and the x402 payer.
 *
 * Three things run here and share one memory:
 *
 *   ACP provider   answers paid jobs from Virtuals, exactly as offering.ts
 *                  does, with the deliverable read out of knos.
 *   Telegram       /brief <question> makes the agent pay for an answer over
 *                  x402 on Base and write what it bought back into knos.
 *   x402 payer     the buying half. The seller is `knos serve`, which is the
 *                  same store this bot writes to, so a paid answer and a
 *                  withheld one come from one place.
 *
 * Every path ends in knos. Delete the store and this bot has nothing to sell,
 * nothing to answer with, and nothing to write down: `scripts/gate.py` is
 * that claim as a test.
 *
 * Settings live outside the repo in ~/.knos-keys/bot.json. No key is ever
 * read into this file's source, and nothing here prints one.
 *
 *   npm run bot
 */

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const TELEGRAM = "https://api.telegram.org";

type Settings = {
  /** Optional. Without it the bot runs on the console instead of Telegram. */
  telegramToken?: string;
  /** Where `knos serve` is listening. The x402 seller. */
  paidEndpoint?: string;
  /** The interpreter that has knos installed. Defaults to `python`. */
  python?: string;
  knos: string;
};

/**
 * Where /brief buys from when bot.json does not say otherwise.
 *
 * PayAI's echo merchant: a real x402 seller on Base Sepolia at 0.01 test
 * USDC, which refunds every payment. Testnet and refunded means the demo
 * costs nothing and still exercises the real rail - a 402, a signed payment,
 * a settlement, and a receipt header.
 */
/**
 * The two sellers this bot buys from, both live on Base mainnet.
 *
 * BRIEF: x402-seller's market regime call - spot, funding and open interest,
 * sentiment, resolved to risk_on or risk_off. x402 v2, $0.01.
 * NEWS: Superhighway's real-time news search - actual headlines with links
 * and dates. x402 v1, $0.001.
 *
 * Two versions, one client: v2 answers the 402 in a header and wants
 * PAYMENT-SIGNATURE back, v1 answers in the body and wants X-PAYMENT.
 * `knos.buy402` reads whichever came and replies in kind.
 *
 * Both were checked by asking without paying and reading the 402 they
 * returned. Override BRIEF with `paidEndpoint` in bot.json.
 */
const BRIEF = "https://x402-seller-m8nx.onrender.com/brief";
const NEWS = "https://superhighway.walls.sh/news";

function settings(): Settings {
  const path =
    process.env.KNOS_BOT_SETTINGS ??
    resolve(process.env.USERPROFILE ?? process.env.HOME ?? ".", ".knos-keys", "bot.json");
  try {
    return JSON.parse(readFileSync(path, "utf8")) as Settings;
  } catch {
    throw new Error(
      `No bot settings at ${path}. It needs telegramToken and knos at minimum.`,
    );
  }
}

/** Run knos and hand back exactly what it printed. */
function run(exe: string, args: string[]): Promise<string> {
  return new Promise((done) => {
    const run = spawn(exe, args, { windowsHide: true });
    let said = "";
    run.stdout.on("data", (c) => (said += c));
    run.stderr.on("data", (c) => (said += c));
    run.on("close", () => done(said.trim()));
    run.on("error", (why) => done(`knos did not run: ${why}`));
  });
}

/**
 * Every ACP job this process has sold, newest last.
 *
 * The provider used to answer jobs into a log nobody reads. These are the
 * same sales, kept so `/jobs` can show them and so the chat is told the
 * moment one lands - a paid job arriving is the most interesting thing that
 * happens to this agent, and it should not be invisible.
 */
const sold: { at: string; jobId: string; question: string; usdc: number }[] = [];

/** Chats to tell when an ACP job settles. Whoever last spoke to the bot. */
const listening = new Set<number>();

async function tg(token: string, method: string, body: unknown): Promise<any> {
  const reply = await fetch(`${TELEGRAM}/bot${token}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return reply.json();
}

/**
 * Buy something over x402, on Base, and keep it.
 *
 * The 402 handshake, the signature and the settlement belong to the official
 * client, which is Python here because the Node one still speaks x402 v1 and
 * the merchants speak v2. `knos.buy402` is that client; this shells out to
 * it exactly as the ACP provider shells out to `knos ask`.
 *
 * What this adds is the line afterwards: whatever was bought is written into
 * knos, so the next agent to want it does not pay again. That is the whole
 * reason a memory sits under a paying agent.
 */
async function payFor(
  config: Settings,
  topic: string,
  url: string,
  body?: unknown,
): Promise<string> {
  const args = ["-m", "knos.buy402", url];
  if (body !== undefined) args.push(JSON.stringify(body));
  const bought = await run(config.python ?? "python", args);

  let said: { ok: boolean; content: string; paid: string; why: string; from?: string };
  try {
    said = JSON.parse(bought.split("\n").filter(Boolean).pop() ?? "{}");
  } catch {
    return `The seller did not answer in a way I could read:
${bought.slice(0, 400)}`;
  }
  if (!said.ok) return `Not paid. ${said.why}`;

  const content = said.content.slice(0, 1500).trim();
  // The receipt is the durable half: even where the content goes stale, what
  // is worth keeping is that this agent paid for it, when, and from where.
  const note =
    `Bought over x402 on Base: ${url}.` +
    (said.paid ? ` Receipt: ${said.paid.slice(0, 160)}.` : "") +
    (content ? `

${content}` : "");
  await run(config.knos, ["remember", note, "--about", topic]);

  return [
    content || "(the seller returned nothing readable)",
    "",
    `Paid over x402 on Base and written into knos under "${topic}".`,
    "Ask any agent on this machine for it now - nobody pays for it twice.",
  ].join("\n");
}

/**
 * One command, one reply. `say` is where the reply goes, so the same handler
 * serves Telegram and the console without knowing which it is talking to.
 */
async function handle(
  config: Settings,
  message: any,
  say: (said: string) => Promise<void>,
): Promise<void> {
  const text = String(message?.text ?? "").trim();
  if (!text) return;
  const chat = Number(message?.chat?.id ?? 0);
  if (chat) listening.add(chat);

  if (text.startsWith("/start") || text.startsWith("/help")) {
    await say(
      [
        "knos, as one agent.",
        "",
        "/ask <question>    read this machine's memory, free",
        "/news <topic>      buy real headlines, $0.001 on Base, then keep them",
        "/brief <symbol>    buy a market brief, $0.01 on Base, then keep it",
        "/status            what is claimed, and how full the store is",
        "/jobs              ACP jobs this agent has sold, from its memory",
        "",
        "Everything answers out of one SQLite file. Work another agent has",
        "claimed is withheld here too - the bot gets no special access.",
      ].join("\n"),
    );
    return;
  }
  if (text.startsWith("/jobs")) {
    // Read the store, not this process. `/jobs` in a fresh shell must show
    // the same history the long-running bot would.
    const past = await run(config.knos, ["ask", "acp sales"]);
    const lines = past.split("\n").filter((l) => l.includes("Sold an ACP job"));
    if (lines.length === 0) {
      await say(
        "No ACP job sold yet. The provider is listening on the Virtuals" +
          " marketplace; when a buyer funds a job, knos reads the answer out" +
          " of this machine's memory, submits it, and it is recorded here.",
      );
      return;
    }
    await say([`${lines.length} ACP sale(s), out of knos:`, "", ...lines].join("\n"));
    return;
  }
  if (text.startsWith("/status")) {
    await say(await run(config.knos, ["status"]));
    return;
  }
  if (text.startsWith("/ask")) {
    const question = text.slice("/ask".length).trim();
    if (!question) return void (await say("Ask something: /ask why did we drop redis"));
    await say(await run(config.knos, ["ask", question]));
    return;
  }
  if (text.startsWith("/news")) {
    const topic = text.slice("/news".length).trim() || "bitcoin";
    await say(`Buying news about ${topic} for $0.001 on Base...`);
    try {
      const url = `${NEWS}?q=${encodeURIComponent(topic)}`;
      await say(await payFor(config, `news: ${topic}`, url));
    } catch (why) {
      await say(`Could not buy it: ${why instanceof Error ? why.message : String(why)}`);
    }
    return;
  }
  if (text.startsWith("/brief")) {
    const symbol = text.slice("/brief".length).trim().toUpperCase() || "BTC";
    await say(`Buying a market brief for ${symbol} for $0.01 on Base...`);
    try {
      const url = `${config.paidEndpoint ?? BRIEF}?symbol=${encodeURIComponent(symbol)}`;
      await say(await payFor(config, `market brief: ${symbol}`, url));
    } catch (why) {
      await say(`Could not buy it: ${why instanceof Error ? why.message : String(why)}`);
    }
    return;
  }
}

/**
 * Answer one command and print the reply.
 *
 * The same handler Telegram uses, wired to stdout instead. This is what
 * makes the bot provable without a Telegram account: `npm run bot -- /status`
 * runs the real path against the real store and prints what a person in the
 * chat would have seen.
 */
async function once(config: Settings, text: string): Promise<void> {
  await handle(config, { text, chat: { id: 0 } }, async (said) => {
    console.log(said);
  });
}

async function main(): Promise<void> {
  const config = settings();

  // One command, printed, done. No ACP: connecting to Virtuals takes minutes
  // and a one-shot question does not need a provider running.
  const asked = process.argv.slice(2).join(" ").trim();
  if (asked) {
    await once(config, asked);
    return;
  }

  // The ACP half, started but never awaited. Connecting took ten minutes the
  // first time; blocking the chat half on it would mean a bot that looks
  // dead for ten minutes. It reports when it is up, and a failure there
  // leaves Telegram and the console working.
  console.log("ACP: connecting...");
  import("./offering.js")
    .then(({ serveJobs }) =>
      serveJobs((sale) => {
        // A paid job landing is the most interesting thing that happens to
        // this agent. Record it, and say so wherever someone is listening.
        sold.push({
          at: new Date().toISOString().slice(11, 19),
          jobId: sale.jobId,
          question: sale.question,
          usdc: sale.priceUsdc,
        });
        // Terminal only. The chat is a product surface for the person
        // using it; who bought what out of the store is operator detail,
        // and `/jobs` is there for anyone who wants to ask.
        console.log(
          `ACP sale: job ${sale.jobId}, ${sale.priceUsdc} USDC, asked` +
            ` "${sale.question}"`,
        );
        console.log(sale.answer);
        // Into knos, not just this process's memory. A sale that vanishes on
        // restart is not a record, and putting it in the store means the
        // same delete that kills the withhold path kills the earnings history
        // too - which is the honest position, because both only ever existed
        // in that one file.
        void run(config.knos, [
          "remember",
          `Sold an ACP job for ${sale.priceUsdc} USDC. Asked: ${sale.question}`,
          "--about",
          "acp sales",
        ]);
      }),
    )
    .then(() => console.log("ACP: answering jobs."))
    .catch((why) =>
      console.log(`ACP: not started (${why instanceof Error ? why.message : why})`),
    );

  if (!config.telegramToken) {
    console.log(
      "No telegramToken in bot.json, so this is the console instead.\n" +
        "Type a command (/help, /status, /ask ..., /brief ...) or Ctrl+C.",
    );
    process.stdin.setEncoding("utf8");
    for await (const line of process.stdin) {
      const text = String(line).trim();
      if (text) await once(config, text);
    }
    return;
  }

  const token = config.telegramToken;
  console.log("Telegram: polling.");
  let offset = 0;
  for (;;) {
    try {
      const got = await fetch(
        `${TELEGRAM}/bot${token}/getUpdates?timeout=30&offset=${offset}`,
      ).then((r) => r.json() as any);
      for (const update of got.result ?? []) {
        offset = update.update_id + 1;
        const message = update.message;
        if (!message) continue;
        await handle(config, message, (said) =>
          tg(token, "sendMessage", {
            chat_id: message.chat?.id,
            text: said.slice(0, 4000),
          }).then(() => undefined),
        );
      }
    } catch (why) {
      // A dropped poll is not a reason to stop answering ACP jobs.
      console.error(`poll: ${why instanceof Error ? why.message : why}`);
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
}

main().catch((why) => {
  console.error(String(why instanceof Error ? why.message : why));
  process.exit(1);
});
