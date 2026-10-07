// The story page (web/story.js): node tests/web/story.mjs
// No browser: the six beats and their evidence against docs/STORY.md and the demonstration's script, the number against docs/backtest.json, the
// 12-word budget, the order the steps play in on a made-up clock, and the page as a reader who asked for no movement gets it.
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)), root = join(here, "../.."), web = join(root, "web");
globalThis.matchMedia = () => ({ matches: false });
const { STEPS, ASK, MERGED, FAILED, SENTENCE, REPO, FRONT, NEXT, STAGING, storyHtml, play, linkOf, renderStory } = await import(pathToFileURL(join(web, "story.js")).href);

let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const words = (s) => (s.match(/[A-Za-z0-9][\w'%.,/-]*/g) || []).length;

const bt = JSON.parse(readFileSync(join(root, "docs/backtest.json"), "utf8")).sample.merged.overall;
ok("the number is the backtest's", MERGED === bt.prs && FAILED === bt.any_check_failed.prs, [MERGED, FAILED]);

const story = readFileSync(join(root, "docs/STORY.md"), "utf8");
const told = [...story.matchAll(/^(\d)\. \*\*(.+?)\*\* (.+)\n {3}Evidence: \[([^\]]+)\]\(([^)]+)\)/gm)].map((m) => ({ title: m[2], says: m[3], evidence: m[4], link: m[5] }));
ok("six beats, and the document tells the same six", STEPS.length === 6 && told.length === 6 && STEPS.every((s, i) => s.title === told[i].title && s.says === told[i].says && s.evidence === told[i].evidence));
ok("each step's evidence is the document's: the same transaction, the same file", STEPS.every((s, i) => (s.url ? told[i].link === s.url : join("docs", told[i].link).replace(/\\/g, "/") === join("docs", "..", s.path).replace(/\\/g, "/") || join(root, "docs", told[i].link) === join(root, s.path))), told.map((t) => t.link));
ok("every file named as evidence is in the repository", STEPS.filter((s) => s.path).every((s) => existsSync(join(root, s.path))));
ok("a step says 12 words at most", STEPS.every((s) => words(`${s.title} ${s.says}`) <= 12), STEPS.map((s) => words(`${s.title} ${s.says}`)));
const demo = readFileSync(join(root, "docs/submission/demo_script.md"), "utf8");
const timed = [...demo.matchAll(/^\| (\w+) \| \((\d:\d\d)\) \| \((\d:\d\d)\) \|/gm)];
ok("the demonstration's script times the same six, from 0:00 to 3:00", timed.length === STEPS.length && timed[0][2] === "0:00" && timed[5][3] === "3:00", timed.map((m) => m[1]));
ok("a beat whose evidence ran on staging program ids is labelled so, and only such a beat", STEPS.every((s) => !!s.staging === /staging program ids/.test(s.evidence)) && STEPS.filter((s) => s.staging).length === (storyHtml().match(/class="story-staging"/g) || []).length && storyHtml().includes(`<small class="story-staging">${STAGING}</small>`) && /\*\*Staging program ids\.\*\* The transactions of beats 2 and 4/.test(story), STEPS.map((s) => !!s.staging));
ok("after the last beat: the reader's invoice at the front door, and no customer is quoted", NEXT === "Check your own invoice" && storyHtml().includes(`<a class="k-btn story-next" href="${FRONT}">${NEXT}</a>`) && story.includes(`[check it](${FRONT}). Nobody has paid for this yet.`) && STEPS.every((s) => !/customer|pilot|"/i.test(s.says)));
ok("the ask is three needs, 12 words at most each, and the document's", ASK.length === 3 && ASK.every((a) => a.startsWith("Needed: ") && words(a) <= 12 && story.includes(a)), ASK.map(words));
ok("the document opens with the sentence and the number", story.includes(`**${SENTENCE}**`) && story.includes(`Of ${MERGED} merged agent pull requests that claimed passing tests, ${FAILED} had a failed check.`));

const html = storyHtml();
ok("the page has six .k-step cards, idle until they play, each with one link", (html.match(/class="k-step"/g) || []).length === 6 && (html.match(/data-state="idle"/g) || []).length === 6 && STEPS.every((s) => html.includes(`href="${linkOf(s).replace(/&/g, "&amp;")}"`)));
ok("the number leads it", html.indexOf(`>${MERGED}</strong> merged agent “tests pass” pull requests: <strong class="k-num">${FAILED}</strong> had a failed check.`) > 0 && html.indexOf(`>${MERGED}</strong>`) < html.indexOf("k-step"));
ok("evidence in the repository opens on GitHub; nothing else is linked", [...html.matchAll(/href="([^"]+)"/g)].every((m) => m[1].startsWith(REPO) || m[1].startsWith("https://explorer.solana.com/tx/") || m[1] === FRONT));
ok("no script, image, frame or style asks any host for anything", !/<(script|img|iframe|link|style)\b/i.test(html) && !/url\(/.test(html));
const still = storyHtml({ reduced: true });
ok("reduced motion: all six are in their last state, and there is nothing to play", STEPS.every((s, i) => still.includes(`data-step="${i + 1}" data-ends="${s.ends}" data-state="${s.ends}"`)) && still.includes("story-play\" hidden"));
ok("a caller's own numbers and addresses are used", />9<\/strong> merged agent .*>2<\/strong> had a failed check/.test(storyHtml({ merged: 9, failed: 2, repo: "/r/", front: "/#front" })) && storyHtml({ repo: "/r/" }).includes('href="/r/docs/TAMPER.md"') && storyHtml({ front: "/#front" }).includes('href="/#front"'));

// playing: a made-up page and a made-up clock
const lis = STEPS.map((s) => ({ dataset: { ends: s.ends, state: "idle" } }));
const page = { querySelectorAll: () => lis };
const seen = [];
const done = await play(page, { wait: async () => { seen.push(lis.map((l) => l.dataset.state).join(",")); } });
ok("the steps play in order, one live at a time", done === true && seen.length === 6 && seen.every((row, i) => { const st = row.split(","); return st[i] === "live" && st.filter((x) => x === "live").length === 1 && st.slice(i + 1).every((x) => x === "idle") && st.slice(0, i).every((x, j) => x === STEPS[j].ends); }), seen);
ok("they rest as: five settled and the tampered one refused", lis.map((l) => l.dataset.state).join() === "done,done,bad,done,done,done");
let n = 0;
const first = play(page, { wait: async () => { if (++n === 2) await play(page, { wait: async () => {} }); } });
ok("playing again takes over from a run in progress", (await first) === false && lis.map((l) => l.dataset.state).join() === "done,done,bad,done,done,done");

// a reader who asked for no movement: drawn once, at rest, with no listener and no timer
const el = { innerHTML: "", querySelector: () => { throw new Error("nothing is wired under reduced motion"); } };
globalThis.matchMedia = () => ({ matches: true });
ok("renderStory under reduced motion draws the resting page and wires nothing", renderStory(el) === el && el.innerHTML === storyHtml({ reduced: true }) && renderStory(null) === null);

console.log(failed ? `${failed} failed` : "all ok");
process.exit(failed ? 1 : 0);
