// The story page (web/story.js): node tests/web/story.mjs
// No browser: the eight steps and their evidence against docs/STORY.md, the number against docs/backtest.json, the
// 12-word budget, the order the steps play in on a made-up clock, and the page as a reader who asked for no movement gets it.
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), root = join(here, "../.."), web = join(root, "web");
globalThis.matchMedia = () => ({ matches: false });
const { STEPS, ASK, MERGED, FAILED, SENTENCE, REPO, FRONT, storyHtml, play, linkOf, renderStory } = await import(pathToFileURL(join(web, "story.js")).href);

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const words = (s) => (s.match(/[A-Za-z0-9][\w'%.,/-]*/g) || []).length;

const bt = JSON.parse(readFileSync(join(root, "docs/backtest.json"), "utf8")).sample.merged.overall;
ok("the number is the backtest's", MERGED === bt.prs && FAILED === bt.any_check_failed.prs, [MERGED, FAILED]);

const story = readFileSync(join(root, "docs/STORY.md"), "utf8");
const told = [...story.matchAll(/^(\d)\. \*\*(.+?)\*\* (.+)\n {3}Evidence: \[([^\]]+)\]\(([^)]+)\)/gm)].map((m) => ({ title: m[2], says: m[3], evidence: m[4], link: m[5] }));
ok("eight steps, and the document tells the same eight", STEPS.length === 8 && told.length === 8 && STEPS.every((s, i) => s.title === told[i].title && s.says === told[i].says && s.evidence === told[i].evidence));
ok("each step's evidence is the document's: the same transaction, the same file", STEPS.every((s, i) => (s.url ? told[i].link === s.url : join("docs", told[i].link).replace(/\\/g, "/") === join("docs", "..", s.path).replace(/\\/g, "/") || join(root, "docs", told[i].link) === join(root, s.path))), told.map((t) => t.link));
ok("every file named as evidence is in the repository", STEPS.filter((s) => s.path).every((s) => existsSync(join(root, s.path))));
ok("a step says 12 words at most", STEPS.every((s) => words(`${s.title} ${s.says}`) <= 12), STEPS.map((s) => words(`${s.title} ${s.says}`)));
ok("the last step is the reader's invoice, links to the front door, and quotes nobody", STEPS[7].title === "Your invoice next." && STEPS[7].url === FRONT && linkOf(STEPS[7]) === FRONT && !/customer|pilot|"/i.test(STEPS[7].says) && /Nobody has paid/.test(STEPS[7].says));
ok("the ask is three needs, 12 words at most each, and the document's", ASK.length === 3 && ASK.every((a) => a.startsWith("Needed: ") && words(a) <= 12 && story.includes(a)), ASK.map(words));
ok("the document opens with the sentence and the number", story.includes(`**${SENTENCE}**`) && story.includes(`Of ${MERGED} merged agent pull requests that claimed passing tests, ${FAILED} had a failed check.`));

const html = storyHtml();
ok("the page has eight .k-step cards, idle until they play, each with one link", (html.match(/class="k-step"/g) || []).length === 8 && (html.match(/data-state="idle"/g) || []).length === 8 && STEPS.every((s) => html.includes(`href="${linkOf(s).replace(/&/g, "&amp;")}"`)));
ok("the number leads it", html.indexOf(`>${MERGED}</strong> merged agent “tests pass” pull requests: <strong class="k-num">${FAILED}</strong> had a failed check.`) > 0 && html.indexOf(`>${MERGED}</strong>`) < html.indexOf("k-step"));
ok("evidence in the repository opens on GitHub; nothing else is linked", [...html.matchAll(/href="([^"]+)"/g)].every((m) => m[1].startsWith(REPO) || m[1].startsWith("https://explorer.solana.com/tx/") || m[1] === FRONT));
ok("no script, image, frame or style asks any host for anything", !/<(script|img|iframe|link|style)\b/i.test(html) && !/url\(/.test(html));
const still = storyHtml({ reduced: true });
ok("reduced motion: all eight are in their last state, and there is nothing to play", STEPS.every((s, i) => still.includes(`data-step="${i + 1}" data-ends="${s.ends}" data-state="${s.ends}"`)) && still.includes("story-play\" hidden"));
ok("a caller's own numbers and addresses are used", />9<\/strong> merged agent .*>2<\/strong> had a failed check/.test(storyHtml({ merged: 9, failed: 2, repo: "/r/", front: "/#front" })) && storyHtml({ repo: "/r/" }).includes('href="/r/docs/TAMPER.md"') && storyHtml({ front: "/#front" }).includes('href="/#front"'));

// playing: a made-up page and a made-up clock
const lis = STEPS.map((s) => ({ dataset: { ends: s.ends, state: "idle" } }));
const page = { querySelectorAll: () => lis };
const seen = [];
const done = await play(page, { wait: async () => { seen.push(lis.map((l) => l.dataset.state).join(",")); } });
ok("the steps play in order, one live at a time", done === true && seen.length === 7 && seen.every((row, i) => { const st = row.split(","); return st[i] === "live" && st.filter((x) => x === "live").length === 1 && st.slice(i + 1).every((x) => x === "idle") && st.slice(0, i).every((x, j) => x === STEPS[j].ends); }), seen);
ok("they rest as: seven settled, the tampered one refused, the last one open", lis.map((l) => l.dataset.state).join() === "done,done,done,bad,done,done,done,live");
let n = 0;
const first = play(page, { wait: async () => { if (++n === 2) await play(page, { wait: async () => {} }); } });
ok("playing again takes over from a run in progress", (await first) === false && lis.map((l) => l.dataset.state).join() === "done,done,done,bad,done,done,done,live");

// a reader who asked for no movement: drawn once, at rest, with no listener and no timer
const el = { innerHTML: "", querySelector: () => { throw new Error("nothing is wired under reduced motion"); } };
globalThis.matchMedia = () => ({ matches: true });
ok("renderStory under reduced motion draws the resting page and wires nothing", renderStory(el) === el && el.innerHTML === storyHtml({ reduced: true }) && renderStory(null) === null);

console.log(failed ? `${failed} failed` : "all ok");
process.exit(failed ? 1 : 0);
