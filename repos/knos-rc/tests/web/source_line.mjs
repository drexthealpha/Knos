// node tests/web/source_line.mjs <site dir>
// The line under a record or a statement that says which file it was read from (web/records.js sourceHtml): the file
// and its time are one sentence of twelve words at most, and what the file was made from is a shut fold under it. On
// the Pages build that summary is some thirty words (the chain's log lines, the relay log, GitHub, the Index's root);
// the staging build of 7 Oct said it in one 33-word sentence on the Records page. No browser needed.
// (on a build of knos-rc 6a24688e, before the fold, the first three checks fail)
import { existsSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const root = process.argv[2];             // a build of the site (scripts/build_site.sh): records.js imports settle.js from there
if (!root || !existsSync(join(root, "records.js"))) { console.error("usage: node tests/web/source_line.mjs <site dir>"); process.exit(2); }
const { sourceHtml } = await import(pathToFileURL(join(root, "records.js")).href);
let failed = 0;
const ok = (what, cond, detail) => { if (!cond) failed++; console.log(`${cond ? "ok  " : "FAIL"} ${what}${cond || detail === undefined ? "" : `: ${JSON.stringify(detail)}`}`); };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const summary = "206 log lines of the escrows' history on devnet, 149 lines of the relay log, GitHub, the Agent PR Index of 2026-10-04 (root c55374454d04)";
const html = sourceHtml(esc, { generated: "2026-10-07T03:24:00Z", source: { summary } }, "records.json");
const open = html.replace(/<details[\s\S]*?<\/details>/g, " ").replace(/<a [^>]*>|<\/a>/g, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
const words = (s) => s.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w)).length;
ok("outside the fold: the file and when, one sentence of 12 words at most", open.startsWith("Read from records.json, made ") && open.split(/(?<=\.)\s+/).every((s) => words(s) <= 12), open);
ok("what it was made from is in a shut fold that says so", /<details class="k-more"><summary>What it was made from<\/summary><p>206 log lines/.test(html) && !/<details[^>]* open/.test(html), html);
ok("the line keeps its id and its link to the file", html.startsWith('<div class="fine" id="rec-source">') && html.includes('<a href="records.json">records.json</a>'));
ok("a file that names no source says so", sourceHtml(esc, { generated: "2026-10-07T03:24:00Z" }, "u/a.json", "x").includes("a source the file does not name."));
console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
