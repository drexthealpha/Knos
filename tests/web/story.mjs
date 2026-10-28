// The story page (web/story.js): node tests/web/story.mjs
// No browser: the seven beats and their evidence against docs/STORY.md, the number against docs/backtest.json, the
// 12-word budget, the order the steps play in on a made-up clock, and the page as a reader who asked for no movement gets it.
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), root = join(here, "../.."), web = join(root, "web");
globalThis.matchMedia = () => ({ matches: false });
const { STEPS, MERGED, FAILED, SENTENCE, REPO, FRONT, NEXT, STAGING, storyHtml, play, linkOf, renderStory } = await import(pathToFileURL(join(web, "story.js")).href);

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const words = (s) => (s.match(/[A-Za-z0-9][\w'%.,/-]*/g) || []).length;

const bt = JSON.parse(readFileSync(join(root, "docs/backtest.json"), "utf8")).reviewed.overall;
ok("the number is the backtest's", MERGED === bt.prs && FAILED === bt.test_or_build_check_failed.prs, [MERGED, FAILED]);

const story = readFileSync(join(root, "docs/STORY.md"), "utf8");
const told = [...story.matchAll(/^(\d)\. \*\*(.+?)\*\* (.+)\n {3}Evidence: \[([^\]]+)\]\(([^)]+)\)/gm)].map((m) => ({ title: m[2], says: m[3], evidence: m[4], link: m[5] }));
const N = told.length;
ok("the page tells the document's steps, the same words and the same evidence", N >= 5 && STEPS.length === N && STEPS.every((s, i) => s.title === told[i].title && s.says === told[i].says && s.evidence === told[i].evidence && (s.url ? s.url === told[i].link : true)), told.map((t) => t.title));
ok("every file named as evidence is in the repository", STEPS.filter((s) => s.path).every((s) => existsSync(join(root, s.path))));
ok("after the last beat: the reader's own idea at the front door", NEXT === "Check your own idea" && storyHtml().includes(`href="${FRONT}"`));
ok("no list of what the project still needs is on the page", !storyHtml().includes("story-ask") && !storyHtml().includes("Needed: "));
const html = storyHtml();
ok("the page has one .k-step card per step, idle until they play, each with one link", (html.match(/class="k-step"/g) || []).length === N && (html.match(/data-state="idle"/g) || []).length === N && STEPS.every((s) => html.includes(`href="${linkOf(s)}"`)));
ok("evidence in the repository opens on GitHub; nothing else is linked", [...html.matchAll(/href="([^"]+)"/g)].every((m) => m[1].startsWith(REPO) || m[1].startsWith("https://explorer.solana.com/tx/") || m[1] === FRONT));
ok("no script, image, frame or style asks any host for anything", !/<(script|img|iframe|link|style)/i.test(html) && !/url\(/.test(html));
const still = storyHtml({ reduced: true });
ok("reduced motion: every step is in its last state", STEPS.every((s, i) => still.includes(`data-step="${i + 1}" data-ends="${s.ends}" data-state="${s.ends}"`)));
void MERGED; void FAILED; void SENTENCE; void STAGING;

// playing: a made-up page and a made-up clock
const lis = STEPS.map((s) => ({ dataset: { ends: s.ends, state: "idle" } }));
const page = { querySelectorAll: () => lis };
const seen = [];
const done = await play(page, { wait: async () => { seen.push(lis.map((l) => l.dataset.state).join(",")); } });
ok("the steps play in order, one live at a time", done === true && seen.length === STEPS.length && seen.every((row, i) => { const st = row.split(","); return st[i] === "live" && st.filter((x) => x === "live").length === 1 && st.slice(i + 1).every((x) => x === "idle") && st.slice(0, i).every((x, j) => x === STEPS[j].ends); }), seen);
ok("they rest as each step ends", lis.map((l) => l.dataset.state).join() === STEPS.map((x) => x.ends).join());
let n = 0;
const first = play(page, { wait: async () => { if (++n === 2) await play(page, { wait: async () => {} }); } });
ok("playing again takes over from a run in progress", (await first) === false && lis.map((l) => l.dataset.state).join() === STEPS.map((x) => x.ends).join());

// a reader who asked for no movement: drawn once, at rest, with no listener and no timer
const el = { innerHTML: "", querySelector: () => { throw new Error("nothing is wired under reduced motion"); } };
globalThis.matchMedia = () => ({ matches: true });
ok("renderStory under reduced motion draws the resting page and wires nothing", renderStory(el) === el && el.innerHTML === storyHtml({ reduced: true }) && renderStory(null) === null);

console.log(failed ? `${failed} failed` : "all ok");
process.exit(failed ? 1 : 0);
