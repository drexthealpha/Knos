// The four screens of Round 13 part H3, served for a browser test: the front door and the pricing page from a build of
// the site (as GitHub Pages serves them, under /Knos/, gzip when asked, as Pages does), and the server's tool page
// /t/limit-check/ and one result page /r/<id>/, written by the server's own code (apps/wanted/knos_wanted/tool_page.py)
// in every language and served by the language the request asks for (?lang=, else Accept-Language), with
// Vary: Accept-Language as the server sends it. The hosted API is a stand-in that keeps SPEC2's answer.
//   import { serveScreens } from "./test_h3_common.mjs"
import { createServer } from "node:http";
import { readFileSync, existsSync, statSync, mkdtempSync, rmSync, cpSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, extname, dirname, resolve } from "node:path";
import { tmpdir } from "node:os";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import { TYPES } from "./overflow.mjs";

export const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
export const LANGS = ["en", "ar", "hi", "es", "fr", "pt", "zh-Hans", "id", "sw", "ru"];
export const RID = "H3resultAAAA";
export const RESULT = "Failed at row 136: 1.399 is not above 1.4. It passed for the 135 rows before that.";
const PY = process.env.PYTHON || "python3";

// the server's pages, in every language, by its own code (a result made from the sample, as /api/run would store it)
const WRITE = String.raw`
import json, sys
from pathlib import Path
from knos_wanted import tool_page, tool_run
out, base, rid, sentence = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
t = tool_run.tool("limit-check")
vals = [float(r.split(",")[1]) for r in t["sample"].splitlines()[1:]]
res = {"id": rid, "mode": "sample", "result": sentence, "first_failing_row": 136, "rows": 135, "skipped": 0,
       "shown_by": tool_run.SHOWN_BY, "link": f"{base}/r/{rid}/", "column": "capacity_ah", "rule": "above", "limit": 1.4,
       "chart": {"points": [[i + 1, v] for i, v in enumerate(vals)], "fail": [136, vals[135]], "limit": 1.4, "rule": "above", "n": len(vals)},
       "input": t["sample"], "lines": len(vals), "cut": False, "shown_lines": len(vals)}
for lang in tool_page.LANGS:
    (out / f"t.{lang}.html").write_text(tool_page.page(t, base, front=base + "/Knos/", lang=lang), encoding="utf-8")
    (out / f"r.{lang}.html").write_text(tool_page.page(t, base, res, front=base + "/Knos/", lang=lang), encoding="utf-8")
`;

const pick = (q, accept) => {
  const m = (tag) => { const t = String(tag || "").trim().toLowerCase(); if (!t) return null; for (const l of LANGS) if (l.toLowerCase() === t) return l;
    const b = t.split(/[-_]/)[0]; return b === "zh" ? "zh-Hans" : LANGS.includes(b) ? b : null; };
  return m(q) || String(accept || "").split(",").map((p) => p.split(";")[0]).map(m).find(Boolean) || "en";
};

// the stand-in for POST /api/run: the sample's answer, or file-of-the-test answers given by `answer`
export function apiAnswer(body, base) {
  return { id: RID, mode: body.mode || "sample", result: RESULT, first_failing_row: 136, rows: 135, skipped: 0, shown_by: "Checked by a test of 7 files with known answers.",
    link: `${base}/r/${RID}/`, limits: { max_rows: 100000, max_seconds: 20 }, chart: { points: [[1, 1.86], [136, 1.399], [168, 1.29]], fail: [136, 1.399], limit: body.limit, rule: body.rule, n: 168 },
    runs_left: null, free_left: null, paid_left: null };
}

export async function serveScreens(given) {
  if (!given || !existsSync(join(given, "index.html"))) throw new Error("usage: node <test> <site dir>");
  const made = mkdtempSync(join(tmpdir(), "knos-h3-")), site = resolve(made, "site"), pages = resolve(made, "pages");
  cpSync(given, site, { recursive: true });
  if (!readFileSync(join(site, "index.html"), "utf8").includes('id="list"'))   // a build for the earlier one-page app: compose the front door
    execFileSync(PY, [join(ROOT, "scripts", "site_pages.py"), site], { stdio: "ignore" });
  let base = "";
  const server = createServer((req, res) => {
    const u = new URL(req.url, "http://x"), path = decodeURIComponent(u.pathname), gz = /gzip/.test(req.headers["accept-encoding"] || "");
    const send = (code, type, body, extra, plain) => {   // the Knos server sends its pages uncompressed: `plain`
      const b = gz && !plain && /text|json|javascript|svg/.test(type) ? gzipSync(body) : body;
      res.writeHead(code, { "content-type": type, ...(gz && b !== body ? { "content-encoding": "gzip" } : {}), ...(extra || {}) }); res.end(b);
    };
    if (path === "/api/run" || path === "/api/pay" || path === "/api/tools") {
      let raw = ""; req.on("data", (c) => { raw += c; }); req.on("end", () => {
        let body = {}; try { body = JSON.parse(raw || "{}"); } catch { /* not JSON */ }
        const out = path === "/api/run" ? apiAnswer(body, base) : path === "/api/pay" ? { runs_left: 20, recorded: "test" } : { tools: [] };
        send(200, "application/json", Buffer.from(JSON.stringify(out)), { "access-control-allow-origin": "*" });
      }); return;
    }
    let m = /^\/(t)\/limit-check\/$/.exec(path) || (path === `/r/${RID}/` ? [0, "r"] : null);
    if (m) {
      const lang = pick(u.searchParams.get("lang"), req.headers["accept-language"]);
      return send(200, "text/html; charset=utf-8", readFileSync(join(pages, `${m[1]}.${lang}.html`)), { vary: "Accept-Language", "content-language": lang }, true);
    }
    if (path.startsWith("/Knos/")) {
      const file = join(site, path.slice(6) || "index.html");
      const hit = existsSync(file) && statSync(file).isFile() ? file : existsSync(join(file, "index.html")) ? join(file, "index.html") : null;
      if (hit) return send(200, TYPES[extname(hit)] || "application/octet-stream", readFileSync(hit));
    }
    if (path === "/favicon.ico") return send(200, "image/x-icon", readFileSync(join(site, "favicon.ico")));
    send(404, "text/html", Buffer.from("<!doctype html><title>404</title>"));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  base = `http://127.0.0.1:${server.address().port}`;
  const env = { ...process.env, PYTHONPATH: [join(ROOT, "apps", "wanted"), join(ROOT, "src")].join(process.platform === "win32" ? ";" : ":"), PYTHONIOENCODING: "utf-8" };
  execFileSync("node", ["-e", "require('fs').mkdirSync(process.argv[1],{recursive:true})", pages]);
  execFileSync(PY, ["-c", WRITE, pages, base, RID, RESULT], { env, stdio: ["ignore", "ignore", "inherit"] });
  writeFileSync(join(made, "base.txt"), base);
  return {
    base,
    screens: { door: `${base}/Knos/`, tool: `${base}/t/limit-check/`, result: `${base}/r/${RID}/`, price: `${base}/Knos/pricing/` },
    en: JSON.parse(readFileSync(join(ROOT, "web", "i18n", "en.json"), "utf8")).strings,
    file: (lang) => JSON.parse(readFileSync(join(ROOT, "web", "i18n", `${lang}.json`), "utf8")),
    // the front door's own calls to the hosted server go to this stand-in instead
    route: async (ctx) => {
      await ctx.route(/^https:\/\/knos\.onrender\.com\/api\/(tools|run|pay)/, async (r) => {
        const u = new URL(r.request().url()); let body = {}; try { body = JSON.parse(r.request().postData() || "{}"); } catch { /* none */ }
        const out = u.pathname === "/api/run" ? apiAnswer(body, "https://knos.onrender.com") : u.pathname === "/api/pay" ? { runs_left: 20 } : { tools: [] };
        return r.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(out) });
      });
      await ctx.route(/^https:\/\/(knos\.onrender\.com\/api\/(near|visit)|rpc\.testnet|raw\.githubusercontent)/, (r) => r.abort());
    },
    close: () => { server.close(); rmSync(made, { recursive: true, force: true }); },
  };
}
