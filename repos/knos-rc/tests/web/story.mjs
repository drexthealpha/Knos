// The story page (web/story.js): node tests/web/story.mjs
// No browser: the seven beats and their evidence against docs/STORY.md, the number against docs/backtest.json, the
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

const bt = JSON.parse(readFileSync(join(root, "docs/backtest.json"), "utf8")).reviewed.overall;
ok("the number is the backtest's", MERGED === bt.prs && FAILED === bt.test_or_build_check_failed.prs, [MERGED, FAILED]);

const story = readFileSync(join(root, "docs/STORY.md"), "utf8");
const told = [...story.matchAll(/^(\d)\. \*\*(.+?)\*\* (.+)\n {3}Evidence: \[([^\]]+)\]\(([^)]+)\)/gm)].map((m) => ({ title: m[2], says: m[3], evidence: m[4], link: m[5] }));
ok("seven beats, and the document tells the same seven", STEPS.length === 7 && told.length === 7 && STEPS.every((s, i) => s.title === told[i].title && s.says === told[i].says && s.evidence === told[i].evidence));
ok("each step's evidence is the document's: the same transaction, the same file", STEPS.every((s, i) => (s.url ? told[i].link === s.url : join("docs", told[i].link).replace(/\\/g, "/") === join("docs", "..", s.path).replace(/\\/g, "/") || join(root, "docs", told[i].link) === join(root, s.path))), told.map((t) => t.link));
ok("every file named as evidence is in the repository", STEPS.filter((s) => s.path).every((s) => existsSync(join(root, s.path))));
ok("a step says 12 words at most", STEPS.every((s) => words(`${s.title} ${s.says}`) <= 12), STEPS.map((s) => words(`${s.title} ${s.says}`)));
// the story and the site's round (web/demo.js) tell one transaction in the same seven beats
const NAMES = ["Agree", "Fails", "Passes", "Statement", "Replay", "Pay", "Verify"];
ok("the site's round plays the same seven, by name, and the document names them in that order", readFileSync(join(web, "demo.js"), "utf8").includes(`const STEPS = ${JSON.stringify(NAMES).replace(/,/g, ", ")};`) && story.includes(`${NAMES.join(", ")})`));
ok("a step whose evidence ran on staging program ids is labelled so, and only such a step; today none does", STEPS.every((s) => !!s.staging === /staging program ids/.test(s.evidence)) && STEPS.filter((s) => s.staging).length === (storyHtml().match(/class="story-staging"/g) || []).length && /\*\*Public program ids\.\*\* The transactions of steps 1, 5 and 6/.test(story), STEPS.map((s) => !!s.staging));
const round = JSON.parse(readFileSync(join(web, "demo_data.json"), "utf8"));
ok("the three transactions are the public round's, as the demo's data file has them", round.ids === "public" && [[0, round.fund.tx], [5, round.paid.tx], [4, round.replay.tx]].every(([n, tx]) => STEPS[n].url === `https://explorer.solana.com/tx/${tx}?cluster=devnet` && /public program ids/.test(STEPS[n].evidence)), round.ids);
ok("the refusal is step two, and the last step is the deployment identity", STEPS[1].ends === "bad" && STEPS.filter((s) => s.ends === "bad").length === 1 && STEPS[6].path === "docs/reference/MANIFEST.md");
ok("after the last beat: the reader's invoice at the front door, and no customer is quoted", NEXT === "Check your own invoice" && storyHtml().includes(`<a class="k-btn story-next" href="${FRONT}">${NEXT}</a>`) && story.includes(`[check it](${FRONT}). Nobody has paid for this yet.`) && STEPS.every((s) => !/customer|pilot|"/i.test(s.says)));
ok("the ask is three needs, 12 words at most each, and the document's", ASK.length === 3 && ASK.every((a) => a.startsWith("Needed: ") && words(a) <= 12 && story.includes(a)), ASK.map(words));
ok("the document opens with the sentence and the number", story.includes(`**${SENTENCE}**`) && story.includes(`Of ${MERGED} merged agent pull requests claiming passing tests, ${FAILED} failed a test, build, lint or type check.`));

const html = storyHtml();
ok("the page has seven .k-step cards, idle until they play, each with one link", (html.match(/class="k-step"/g) || []).length === 7 && (html.match(/data-state="idle"/g) || []).length === 7 && STEPS.every((s) => html.includes(`href="${linkOf(s).replace(/&/g, "&amp;")}"`)));
ok("the number leads it", html.indexOf(`>${MERGED}</strong> merged agent “tests pass” pull requests: <strong class="k-num">${FAILED}</strong> failed a test, build, lint or type check.`) > 0 && html.indexOf(`>${MERGED}</strong>`) < html.indexOf("k-step"));
ok("evidence in the repository opens on GitHub; nothing else is linked", [...html.matchAll(/href="([^"]+)"/g)].every((m) => m[1].startsWith(REPO) || m[1].startsWith("https://explorer.solana.com/tx/") || m[1] === FRONT));
ok("no script, image, frame or style asks any host for anything", !/<(script|img|iframe|link|style)\b/i.test(html) && !/url\(/.test(html));
const still = storyHtml({ reduced: true });
ok("reduced motion: all seven are in their last state, and there is nothing to play", STEPS.every((s, i) => still.includes(`data-step="${i + 1}" data-ends="${s.ends}" data-state="${s.ends}"`)) && still.includes("story-play\" hidden"));
ok("a caller's own numbers and addresses are used", />9<\/strong> merged agent .*>2<\/strong> failed a test, build, lint or type check/.test(storyHtml({ merged: 9, failed: 2, repo: "/r/", front: "/#front" })) && storyHtml({ repo: "/r/" }).includes('href="/r/docs/reference/TAMPER.md"') && storyHtml({ front: "/#front" }).includes('href="/#front"'));

// playing: a made-up page and a made-up clock
const lis = STEPS.map((s) => ({ dataset: { ends: s.ends, state: "idle" } }));
const page = { querySelectorAll: () => lis };
const seen = [];
const done = await play(page, { wait: async () => { seen.push(lis.map((l) => l.dataset.state).join(",")); } });
ok("the steps play in order, one live at a time", done === true && seen.length === 7 && seen.every((row, i) => { const st = row.split(","); return st[i] === "live" && st.filter((x) => x === "live").length === 1 && st.slice(i + 1).every((x) => x === "idle") && st.slice(0, i).every((x, j) => x === STEPS[j].ends); }), seen);
ok("they rest as: six settled and the claimed success refused", lis.map((l) => l.dataset.state).join() === "done,bad,done,done,done,done,done");
let n = 0;
const first = play(page, { wait: async () => { if (++n === 2) await play(page, { wait: async () => {} }); } });
ok("playing again takes over from a run in progress", (await first) === false && lis.map((l) => l.dataset.state).join() === "done,bad,done,done,done,done,done");

// a reader who asked for no movement: drawn once, at rest, with no listener and no timer
const el = { innerHTML: "", querySelector: () => { throw new Error("nothing is wired under reduced motion"); } };
globalThis.matchMedia = () => ({ matches: true });
ok("renderStory under reduced motion draws the resting page and wires nothing", renderStory(el) === el && el.innerHTML === storyHtml({ reduced: true }) && renderStory(null) === null);

console.log(failed ? `${failed} failed` : "all ok");
process.exit(failed ? 1 : 0);
