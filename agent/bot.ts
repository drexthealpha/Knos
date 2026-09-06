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
 * nothing to answer with, and nothing to write down:
 * `tests/test_sibyl_is_load_bearing.py` is that claim as a test.
 *
 * Settings live outside the repo in ~/.knos-keys/bot.json. No key is ever
 * read into this file's source, and nothing here prints one.
 *
 *   npm run bot
 */

import { spawn } from "node:child_process";
import dns from "node:dns";
import { readFileSync } from "node:fs";
import net from "node:net";
import { resolve } from "node:path";

// api.telegram.org resolves to an IPv6 address first, and on a network whose
// IPv6 path to it is broken the TCP connect succeeds while the TLS handshake
// never completes - small packets get through, the larger ClientHello does
// not. Measured on one such network: IPv6 TLS timed out 4/4 at 9s, IPv4
// succeeded 4/4 at ~500ms.
//
// Both lines are needed and reordering alone is not enough. Happy Eyeballs
// dials every address family in parallel no matter what order DNS returned,
// so it still reaches the dead path and the poll dies intermittently while
// one-shot calls look fine. Measured across 20 requests: reordering alone
// left 1 failure, disabling the race as well left 0 at a 243ms median.
//
// Delete these two lines only on a network where IPv6 to Telegram works.
net.setDefaultAutoSelectFamily(false);
dns.setDefaultResultOrder("ipv4first");

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
    let out = "";
    let err = "";
    run.stdout.on("data", (c) => (out += c));
    run.stderr.on("data", (c) => (err += c));
    // stdout and stderr used to be one string, so a Python traceback came
    // back to the chat as though it were an answer. They are kept apart now,
    // and the exit code decides which one the person is shown.
    run.on("close", (code) => {
      const said = out.trim();
      if (code === 0 || said) return done(said || err.trim());
      done(FAILED + (err.trim() || `${exe} exited ${code}`));
    });
    run.on("error", (why) => done(FAILED + why));
  });
}

/** Marks a `run` result as a failure rather than an answer. */
const FAILED = "[knos-run-failed] ";

/** Whether `run` reported a failure rather than an answer. */
function broke(said: string): boolean {
  return said.startsWith(FAILED);
}

/**
 * A failure, as one sentence a person can act on.
 *
 * The detail still matters when something is genuinely wrong, so the first
 * line of it is kept; what is dropped is the stack trace underneath, which
 * tells the reader nothing and fills the screen.
 */
function apology(said: string, doing: string): string {
  const why = said.replace(FAILED, "").split("\n").filter(Boolean)[0] ?? "";
  return `Could not ${doing}.${why ? ` ${why.slice(0, 200)}` : ""}`;
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

/** Escape the three characters Telegram's HTML mode would read as markup. */
function safe(text: string): string {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

/**
 * A chat message, not a terminal dump.
 *
 * This bot is a product in its own right, and the person reading it did not
 * ask to see a console. Replies are prose with a little bold, which is what
 * a phone renders well; `<b>` markers written by the caller survive, and
 * everything else is escaped so a literal `<question>` in the help text
 * cannot be mistaken for a tag and make Telegram reject the whole message.
 *
 * The 4096-character limit applies to the finished payload, so the cut
 * happens before escaping - a slice taken afterwards could halve an entity.
 */
function chat(said: string): { text: string; parse_mode: string } {
  // Telegram's limit is 4096 on the finished payload. Cutting silently left
  // a sentence hanging mid-word with nothing to say it had been cut, which
  // reads as a bug rather than a limit.
  const kept =
    said.length > 3500
      ? said.slice(0, 3400) + "\n\n[cut here - ask again, narrower]"
      : said;
  const text = safe(kept).replaceAll("&lt;b&gt;", "<b>").replaceAll("&lt;/b&gt;", "</b>");
  return { text, parse_mode: "HTML" };
}

/**
 * `knos status` as a sentence.
 *
 * The CLI prints five Sibyl tiers in aligned columns, which is right for a
 * terminal and wrong for a phone: the columns collapse into noise, and the
 * store's absolute path is on the operator's disk, not something to show a
 * stranger. This keeps the three numbers that mean something to a reader
 * and drops the rest. If the format ever changes underneath it, the raw
 * output goes out instead of a wrong summary.
 */
function statusForChat(raw: string): string {
  const find = (re: RegExp) => raw.match(re)?.[1]?.trim();
  const claims = find(/(\d+) claims? held right now/);
  const only = find(/(\d+) of them exist nowhere else/);
  const size = find(/([\d.]+ MB of \d+ MB) used/);
  const agents = find(/agent history: (.+)/);
  if (claims === undefined || only === undefined || size === undefined) {
    return raw;
  }
  const held = Number(claims);
  const lines = [
    "<b>Knos</b> - one memory every coding agent here shares.",
    "",
    held === 0
      ? "Nothing is claimed, so nothing is being withheld."
      : `<b>${held}</b> thing${held === 1 ? " is" : "s are"} being worked on` +
        " right now, and withheld from every other agent.",
    "",
    `${only} things written down that exist nowhere else`,
    `${size} used`,
  ];
  if (agents) lines.push(`Shared by: ${agents}`);
  lines.push(
    "",
    `Delete the store and only those ${only} go. Everything else is` +
      " re-read from the repo.",
  );
  return lines.join("\n");
}

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
  price: string,
  body?: unknown,
): Promise<string> {
  // The memory decides whether this costs anything. Three answers, and only
  // the last one spends: somebody is mid-change on this topic and the answer
  // is about to be stale, the store already has it, or neither and we buy.
  //
  // This is the half that made "nobody here pays twice" true. The write-back
  // was always there; the look-before-paying was not, so the second identical
  // request paid again for something already sitting in the store.
  const asked = await run(config.python ?? "python", [
    "-m", "knos.gate", "--topic", topic, "--ask", topic,
  ]);
  if (!broke(asked)) {
    try {
      const gate = JSON.parse(asked.split("\n").filter(Boolean).pop() ?? "{}");
      if (gate.verdict === "withheld") {
        return [
          gate.answer,
          "",
          "Nothing was bought. " +
            (gate.holder === "you"
              ? "You are on this right now"
              : `${gate.holder || "Another agent"} is on this right now`) +
            ", so a paid answer would be out of date before it arrived.",
        ].join("\n");
      }
      if (gate.verdict === "have") {
        return [
          english(gate.answer) || gate.answer,
          "",
          "Free. This machine already paid for it once" +
            (gate.where ? ` (${gate.where})` : "") + ", so nobody paid again.",
        ].join("\n");
      }
    } catch {
      // A gate that cannot be read must not become a gate that blocks. Fall
      // through and buy, which is what happened before it existed.
    }
  }

  const args = ["-m", "knos.buy402", url];
  if (body !== undefined) args.push(JSON.stringify(body));
  const bought = await run(config.python ?? "python", args);

  let said: {
    ok: boolean;
    content: string;
    paid: string;
    tx?: string;
    payer?: string;
    why: string;
    from?: string;
  };
  try {
    said = JSON.parse(bought.split("\n").filter(Boolean).pop() ?? "{}");
  } catch {
    return broke(bought)
      ? apology(bought, "reach the seller")
      : "The seller did not answer in a way I could read. Nothing was paid.";
  }
  if (!said.ok) return `Not paid. ${said.why}`;

  const readable = english(said.content);

  // The receipt is the durable half: even where the content goes stale, what
  // is worth keeping is that this agent paid for it, when, and from where.
  //
  // The link, not the header. This used to store the settlement header cut
  // at 160 characters, which still decoded - to a 34-character transaction
  // hash that looks like a hash and resolves to nothing. A receipt nobody
  // can follow is worse than no receipt, because it reads as evidence.
  const receipt = said.tx
    ? ` Paid: https://basescan.org/tx/${said.tx}`
    : said.paid
      ? " Paid, but the settlement receipt did not decode."
      : "";
  const note =
    `Bought over x402 on Base: ${url}.${receipt}` +
    (readable ? `\n\n${readable}` : "");
  // If the write-back fails the money is still spent, so the person is told
  // the truth: they were charged, and the next agent will be charged again.
  const wrote = await run(config.knos, ["remember", note, "--about", topic]);

  return [
    readable || "(the seller returned nothing readable)",
    "",
    said.tx ? `Paid $${price} on Base: https://basescan.org/tx/${said.tx}` : "Paid on Base.",
    broke(wrote)
      ? `Paid, but knos did not record it, so this will cost again. ${apology(wrote, "write it down")}`
      : `Written into knos under "${topic}" - ask any agent here and nobody pays twice.`,
  ].join("\n");
}

/**
 * What the seller sent, as sentences.
 *
 * Every other surface in this bot speaks English; the two paid commands used
 * to print the seller's JSON body verbatim, which is the one place a person
 * is shown a machine payload. The shapes are known - a search result list, a
 * market brief - so they are formatted by name, and anything unrecognised is
 * flattened rather than dumped. If it is not JSON at all it was already prose
 * and is passed through.
 */
function english(body: string): string {
  const raw = (body ?? "").trim();
  if (!raw) return "";

  let data: any;
  try {
    data = JSON.parse(raw);
  } catch {
    return raw.slice(0, 1200); // already prose
  }

  // A search result list.
  if (Array.isArray(data?.results)) {
    const hits = data.results.slice(0, 5).map((r: any, i: number) => {
      const title = String(r?.title ?? "").trim() || "(untitled)";
      const why = String(r?.description ?? "").replace(/\s+/g, " ").trim();
      const line = `${i + 1}. <b>${title}</b>`;
      return why ? `${line}\n   ${why.slice(0, 180)}${why.length > 180 ? "..." : ""}` : line;
    });
    const what = String(data.query ?? "").trim();
    return [what ? `Top headlines for "${what}":` : "Top headlines:", "", ...hits].join("\n");
  }

  // A market brief.
  if (data?.regime || data?.price_usd !== undefined) {
    const money = (n: unknown) =>
      typeof n === "number"
        ? "$" + n.toLocaleString("en-US", { maximumFractionDigits: 2 })
        : String(n ?? "?");
    const out: string[] = [];
    const sym = String(data.symbol ?? "").trim();
    if (data.price_usd !== undefined) {
      const move =
        typeof data.change_24h_pct === "number"
          ? `, ${data.change_24h_pct >= 0 ? "up" : "down"} ${Math.abs(data.change_24h_pct).toFixed(2)}% in 24h`
          : "";
      out.push(`<b>${sym || "It"}</b> is at ${money(data.price_usd)}${move}.`);
    }
    if (data.regime) out.push(`The market reads as <b>${data.regime}</b>.`);
    if (data?.sentiment?.label)
      out.push(`Sentiment is ${data.sentiment.label} (${data.sentiment.value}/100).`);
    if (Array.isArray(data.why) && data.why.length) {
      out.push("", "Why:");
      for (const r of data.why.slice(0, 4)) out.push(`- ${String(r)}`);
    }
    if (data.as_of) out.push("", `As of ${String(data.as_of).replace("T", " ").slice(0, 16)} UTC.`);
    return out.join("\n");
  }

  // Something new. Flatten the scalars rather than showing braces; a shape
  // this bot has not met yet is a reason to read it, not to give up on it.
  const lines = Object.entries(data ?? {})
    .filter(([, v]) => v === null || ["string", "number", "boolean"].includes(typeof v))
    .slice(0, 10)
    .map(([k, v]) => `${k.replaceAll("_", " ")}: ${v}`);
  return lines.length
    ? lines.join("\n")
    : "The seller answered in a shape this bot has not been taught to read" +
      " yet. It is stored whole, so nothing is lost.";
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
        "<b>Knos</b>, as one agent.",
        "",
        "<b>/ask</b> something - read this machine's memory, free",
        "<b>/news</b> a topic - buy real headlines, $0.001 on Base",
        "<b>/brief</b> a symbol - buy a market brief, $0.01 on Base",
        "<b>/status</b> - what is claimed, and how full the store is",
        "<b>/jobs</b> - the jobs this agent has sold",
        "",
        "Anything bought is kept, so nobody on this machine pays for it",
        "twice.",
        "",
        "Everything answers out of one file. Work another agent has claimed",
        "is withheld here too - the bot gets no special access.",
      ].join("\n"),
    );
    return;
  }
  if (text.startsWith("/jobs")) {
    // Read the store, not this process. `/jobs` in a fresh shell must show
    // the same history the long-running bot would.
    const past = await run(config.knos, ["ask", "acp sales"]);
    if (broke(past)) return void (await say(apology(past, "read the store")));
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
    const raw = await run(config.knos, ["status"]);
    await say(broke(raw) ? apology(raw, "read the store") : statusForChat(raw));
    return;
  }
  if (text.startsWith("/ask")) {
    const question = text.slice("/ask".length).trim();
    if (!question) return void (await say("Ask something: /ask why did we drop redis"));
    const found = await run(config.knos, ["ask", question]);
    await say(broke(found) ? apology(found, "read the store") : found);
    return;
  }
  if (text.startsWith("/news")) {
    const topic = text.slice("/news".length).trim() || "bitcoin";
    // Not "buying" yet: the store is asked first and may answer for nothing.
    await say(`Looking up ${topic}. If this machine has not paid for it already, it costs $0.001 on Base.`);
    try {
      const url = `${NEWS}?q=${encodeURIComponent(topic)}`;
      await say(await payFor(config, `news: ${topic}`, url, "0.001"));
    } catch (why) {
      await say(`Could not buy it: ${why instanceof Error ? why.message : String(why)}`);
    }
    return;
  }
  if (text.startsWith("/brief")) {
    const symbol = text.slice("/brief".length).trim().toUpperCase() || "BTC";
    await say(`Looking up ${symbol}. If this machine has not paid for it already, it costs $0.01 on Base.`);
    try {
      const url = `${config.paidEndpoint ?? BRIEF}?symbol=${encodeURIComponent(symbol)}`;
      await say(await payFor(config, `market brief: ${symbol}`, url, "0.01"));
    } catch (why) {
      await say(`Could not buy it: ${why instanceof Error ? why.message : String(why)}`);
    }
    return;
  }

  // Nothing matched. This used to return silently, which is the one reply a
  // person cannot tell apart from a dead bot. A plain sentence and the list
  // of what does work costs nothing and never leaves the chat empty.
  await say(
    [
      text.startsWith("/")
        ? `I do not know <b>${text.split(/\s/)[0]}</b>.`
        : "I only answer commands.",
      "",
      "<b>/ask</b> something - read this machine's memory, free",
      "<b>/news</b> a topic - buy real headlines, $0.001 on Base",
      "<b>/brief</b> a symbol - buy a market brief, $0.01 on Base",
      "<b>/status</b> - what is claimed, and how full the store is",
      "<b>/jobs</b> - the jobs this agent has sold",
    ].join("\n"),
  );
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
        // And tell the chat. Another agent paying for an answer out of this
        // machine's memory is the most interesting thing that happens here,
        // and until now it only ever reached the terminal - so the person
        // holding the phone never saw the one moment worth seeing.
        const token = config.telegramToken;
        if (token) {
          for (const who of listening) {
            void tg(token, "sendMessage", {
              chat_id: who,
              ...chat(
                [
                  `<b>Sold an answer.</b> ${sale.priceUsdc} USDC on Base.`,
                  "",
                  `They asked: ${sale.question}`,
                  "",
                  "Answered out of this machine's memory, and the sale is now"
                    + " in it - ask /jobs.",
                ].join("\n"),
              ),
            });
          }
        }
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
            ...chat(said),
          }).then(() => undefined),
        );
      }
    } catch (why) {
      // A dropped poll is not a reason to stop answering ACP jobs.
      //
      // Say what actually went wrong. Node wraps every network failure as
      // the same "fetch failed", which is useless when it appears mid-demo:
      // a connect timeout, a DNS failure and a dropped TLS handshake all
      // read identically. The cause carries the code that tells them apart.
      const cause = (why as { cause?: { code?: string } })?.cause;
      const detail = cause?.code ? ` (${cause.code})` : "";
      console.error(
        `poll: ${why instanceof Error ? why.message : why}${detail}` +
          ` - retrying in 3s, ACP is unaffected`,
      );
      await new Promise((r) => setTimeout(r, 3000));
    }
  }
}

main().catch((why) => {
  console.error(String(why instanceof Error ? why.message : why));
  process.exit(1);
});
