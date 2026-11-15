// node tests/web/verifier.mjs [web dir]
// web/verifier.js, the builders' page of the verifier. First with no browser: what `decode` says of a pasted token, and that the
// page's issuer table is the one of examples/issuers/issuers.json. Then in headless Chromium, on a page that holds nothing but the
// site's stylesheet and this module: the sentence, the three calls and their Copy buttons, the table, the tool. It asks no host but
// the one that served it, sends a pasted token nowhere, keeps nothing, says "Decoded, not verified", holds every statement to twelve
// words and never scrolls sideways. Needs the `playwright` package, as tests/web/site.mjs does; without it or a browser it says SKIP.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = process.argv[2] || join(here, "..", "..", "web");
const check = (name, cond, detail) => { if (!cond) { console.error("FAIL", name, detail === undefined ? "" : detail); process.exitCode = 1; } else console.log("ok  ", name); };
const NOW = 1_790_000_000;
const b64 = (s) => Buffer.from(s).toString("base64url");
const token = (header, claims, sigBytes) => `${b64(JSON.stringify(header))}.${b64(typeof claims === "string" ? claims : JSON.stringify(claims))}.${b64(Buffer.alloc(sigBytes, 7))}`;
const words = (s) => s.trim().split(/\s+/).filter(Boolean).length;

// ---- with no browser ------------------------------------------------------------------------------------------------------------
const lib = await import(pathToFileURL(join(root, "verifier.js")).href);
const book = JSON.parse(readFileSync(join(here, "..", "..", "examples", "issuers", "issuers.json"), "utf8"));
{
  check("the page's table is the examples' table: the same issuers, in the same order, on the same day",
    JSON.stringify(lib.ISSUERS.map((i) => [i.id, i.name, i.source])) === JSON.stringify(book.issuers.map((i) => [i.id, i.name, i.source])) && lib.CHECKED === book.checked);
  check("  the same claims to gate on, the same claims not read, and the same answer to 'is it verified'",
    lib.ISSUERS.every((i, n) => JSON.stringify([i.gate, i.unread, i.verified === "yes"]) === JSON.stringify([book.issuers[n].gate, book.issuers[n].unreadable, book.issuers[n].supported === "yes"])));
  check("  an issuer verified in part says in a few words what to do", lib.ISSUERS.filter((i) => i.verified !== "yes").every((i) => i.part && words(i.part) <= 12));
  check("  every issuer's RS256 is accepted today; an algorithm the verifier does not take is 'not yet', and only an issuer verified in part has one",
    lib.ISSUERS.every((i) => lib.today(i)[0].alg === "RS256" && lib.today(i)[0].today && lib.today(i).slice(1).every((a) => !a.today && ["ES256", "ES384", "ES512", "PS256", "EdDSA"].includes(a.alg))
      && (lib.today(i).length > 1) === (i.verified !== "yes" && /ES|ECDSA/.test(i.signs))));
  check("  the discovery documents that were read list RS256, as the table says", book.issuers.filter((i) => i.discovery.read).every((i) => i.discovery.algs.join() === "RS256" && i.supported === "yes")
    && book.issuers.filter((i) => !i.discovery.read).every((i) => i.discovery.why));
  check("  what the program takes is what the table of examples says it takes",
    lib.MAX_JWT === book.accepts.max_token_bytes && JSON.stringify(lib.KEY_BITS) === JSON.stringify(book.accepts.key_bits));
  for (const i of book.issuers) {
    const d = lib.decode(token({ alg: "RS256", typ: "JWT" }, { ...i.claims, iat: NOW, exp: NOW + 300 }, 256), NOW);
    const read = d.rows.filter((r) => r.read).map((r) => r.name), unread = d.rows.filter((r) => !r.read).map((r) => r.name);
    check(`  ${i.id}: a token of its documented shape is named, and its claims are read or not as the table says`,
      d.ok && d.takes && d.issuer?.id === i.id && i.gate.every((g) => read.includes(g)) && JSON.stringify(unread) === JSON.stringify(Object.keys(i.claims).filter((k) => i.unreadable.includes(k)))
      && d.rows.filter((r) => r.known).map((r) => r.name).sort().join() === [...i.gate].sort().join(), JSON.stringify([d.issuer?.id, unread]));
  }
  const claims = { iss: "https://accounts.google.com", sub: "1", aud: "x", exp: NOW + 300 };
  const says = (d) => d.lines.map((l) => `${l.ok ? "+" : "-"}${l.text}`);
  const rs = lib.decode(token({ alg: "RS256" }, claims, 256), NOW);
  check("decode: RS256 under a 2048-bit key is a token the verifier takes", rs.takes && rs.bits === 2048 && says(rs)[0] === "+Signed RS256: the verifier takes it." && says(rs)[1] === "+Signed by a 2048-bit key: the verifier takes it.");
  check("  and under a 4096-bit key", lib.decode(token({ alg: "RS256" }, claims, 512), NOW).takes);
  for (const [bytes, bits] of [[128, 1024], [384, 3072]]) {
    const d = lib.decode(token({ alg: "RS256" }, claims, bytes), NOW);
    check(`  an RS256 key of ${bits} bits is said to be refused`, !d.takes && !d.bitsOk && says(d)[1] === `-Signed by a ${bits}-bit key: the verifier takes 2048 or 4096.`);
  }
  for (const [alg, bytes] of [["ES256", 64], ["ES384", 96], ["PS256", 256], ["HS256", 32], ["EdDSA", 64], ["none", 0]]) {
    const d = lib.decode(token({ alg }, claims, bytes), NOW);
    check(`  ${alg} is said to be refused, and no key size is claimed for it`, d.ok && !d.takes && says(d)[0] === `-Signed ${alg}: the verifier does not take it.` && !says(d).some((l) => l.includes("-bit key")));
  }
  const exp = (over) => lib.decode(token({ alg: "RS256" }, { ...claims, ...over }, 256), NOW);
  check("  exp: a day ahead at most, a number, and read until an hour after it",
    exp({ exp: NOW + 86_400 }).takes && !exp({ exp: NOW + 86_401 }).takes && exp({ exp: NOW + 86_401 }).exp.state === "ahead" && !exp({ exp: String(NOW + 300) }).takes
    && exp({ exp: undefined }).exp.state === "missing" && exp({ exp: NOW - 3599 }).exp.state === "ok" && exp({ exp: NOW - 3600 }).exp.state === "late");
  check("  an issuer that is not an https URL is said to be refused; one the table lacks is to be registered",
    !exp({ iss: "accounts.google.com" }).takes && !exp({ iss: 7 }).takes && exp({ iss: "https://id.example.com" }).takes && exp({ iss: "https://id.example.com" }).issuer === null
    && says(exp({ iss: "https://id.example.com" })).includes("+Names an issuer the table lacks: register its key."));
  check("  a look-alike of an issuer's URL is not named as that issuer",
    ["https://accounts.google.com.evil.example", "https://accounts.google.com/", "https://agent.buildkite.com.x.io", "https://evil.example/https://gitlab.com"].every((iss) => exp({ iss }).issuer === null));
  const big = lib.decode(token({ alg: "RS256" }, { ...claims, pad: "x".repeat(9000) }, 256), NOW);
  check("  a token over 8,192 bytes is said to be too long", !big.takes && !big.sizeOk && says(big).some((l) => /^-Holds [\d,]+ bytes: the verifier takes 8,192\.$/.test(l)));
  check("  what a program can gate on: text and whole numbers at the top level, nothing else",
    JSON.stringify([ "a", 0, 7, 10 ** 17, -1, 1.5, true, null, ["a"], { a: 1 }, "a\nb" ].map((v) => lib.readable(v).read)) === "[true,true,true,true,false,false,false,false,false,false,false]");
  check("  text that is not a JWT is said so, and nothing is said of nothing",
    lib.decode("", NOW).error === "" && lib.decode("hello", NOW).error.startsWith("Paste a signed JWT") && lib.decode("a.b.c", NOW).error.startsWith("Paste a signed JWT")
    && lib.decode(token({ alg: "RS256" }, '["iss"]', 256), NOW).ok === false && lib.decode(`Bearer ${token({ alg: "RS256" }, claims, 256)}`, NOW).takes);
  check("  every line the tool can say is twelve words at most",
    [rs, big, exp({ exp: NOW + 10 ** 6 }), exp({ exp: 1 }), exp({ exp: "x" }), exp({ iss: 1 }), lib.decode(token({ alg: "ES384" }, claims, 96), NOW),
      ...book.issuers.map((i) => lib.decode(token({ alg: "RS256" }, { ...i.claims, exp: NOW + 300 }, 384), NOW))].every((d) => d.lines.every((l) => words(l.text) <= 12)));
  const s = lib.decode(lib.sample(NOW), NOW);
  check("  the sample is a Buildkite token of the documented shape, and its signature is 256 bytes of nothing", s.takes && s.issuer.id === "buildkite" && s.bits === 2048);
  check("the sentence and each call's title are twelve words at most", words(lib.SENTENCE) <= 12 && lib.CALLS.length === 3 && lib.CALLS.every((c) => words(c.title) <= 12));
  const sdk = readFileSync(join(here, "..", "..", "sdk", "settle", "index.js"), "utf8"), crate = readFileSync(join(here, "..", "..", "crates", "knos-oidc-interface", "src", "lib.rs"), "utf8");
  const js = lib.CALLS.filter((c) => c.lang === "js").map((c) => c.code).join("\n"), rust = lib.CALLS.find((c) => c.lang === "rust").code;
  check("  every call the blocks show is one the JavaScript client and the interface crate have",
    ["registerIssuerKeyIx", "registerPrivateKeyIx", "keyParamsIx", "writeIxs", "keyPda", "stepIx", "tokenPda"].every((f) => js.includes(`oidc.${f}(`) && new RegExp(`\\b${f}\\b`).test(sdk))
    && ["export function verifier(", "export const tokenId", "export const stepPlan"].every((f) => sdk.includes(f))
    && ["pub fn read(", "pub fn check_key(", "pub fn issuer(", "pub fn issuer_hash(", "pub fn claim(", "pub fn audience(", "pub fn starts_with(", "pub const ISSUER_OTHER"].every((f) => crate.includes(f))
    && ["Token::read(", ".check_key(", ".issuer()", ".issuer_hash()", '.claim("sub")', ".audience()"].every((f) => rust.includes(f)));
  const ids = JSON.parse(readFileSync(join(here, "..", "..", "programs-v2", "program_ids.json"), "utf8"));
  check("  the program id is the second deployment's", lib.PROGRAM === ids.knos_oidc);
  check("the module makes no request and keeps nothing: no fetch, no storage, no import of another module",
    !/\bfetch\(|XMLHttpRequest|WebSocket|sendBeacon|localStorage|sessionStorage|indexedDB|document\.cookie|\bimport\(|^import /m.test(readFileSync(join(root, "verifier.js"), "utf8").replace(/^\/\/.*$/gm, "").replace(/code: `[^`]*`/g, "")));
}

// ---- in a browser ---------------------------------------------------------------------------------------------------------------
let chromium;
try { ({ chromium } = (await import("playwright")).default); } catch { console.log("SKIP the playwright package is not installed"); process.exit(process.exitCode || 0); }
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json", ".woff2": "font/woff2" };
const HARNESS = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>verifier</title>
<link rel="stylesheet" href="app.css"></head><body><main><section id="verifier"></section></main>
<script type="module">import { renderVerifier } from "./verifier.js"; import { renderVerified } from "./badge.js"; renderVerifier(document.getElementById("verifier"), { now: () => ${NOW}, badge: renderVerified }); window.ready = true;</script></body></html>`;
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
  if (path === "/verifier-harness.html") { res.writeHead(200, { "content-type": "text/html" }); return res.end(HARNESS); }
  const file = join(root, path);
  if (!file.startsWith(root) || !existsSync(file) || extname(file) === "") { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream" });
  res.end(readFileSync(file));
});
await new Promise((ok) => server.listen(0, "127.0.0.1", ok));
const base = `http://127.0.0.1:${server.address().port}/`;
let browser;
try { browser = await chromium.launch(); } catch (e) { console.log(`SKIP no browser: ${String(e.message).split("\n")[0]}`); server.close(); process.exit(process.exitCode || 0); }
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, permissions: ["clipboard-read", "clipboard-write"] });
const asked = [], errors = [];
await ctx.route("**/*", (route) => { asked.push(route.request().url()); return route.request().url().startsWith(base) ? route.continue() : route.abort(); });
const page = await ctx.newPage();
page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(`${base}verifier-harness.html`);
await page.waitForFunction(() => window.ready === true);
const text = async (sel) => ((await page.textContent(sel)) || "").replace(/\s+/g, " ").trim();
const cells = async (sel) => (await page.locator(sel).innerText()).replace(/\s+/g, " ").trim();      // a table as it reads: a space between cells
const sideways = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
// every statement on the page: a heading, a paragraph, a list item, a caption, a column's name, a button, a cell of words
const statements = () => page.evaluate(() => [...document.querySelectorAll("#verifier h2, #verifier h3, #verifier p, #verifier li, #verifier caption, #verifier thead th, #verifier button, #verifier label, #verifier tbody td")]
  .filter((e) => !e.querySelector("code") || e.matches("p")).map((e) => e.textContent.replace(/\s+/g, " ").trim()).filter(Boolean));

check("the page: the one sentence, and that no outside program reads the verifier yet", await text("#vf-sentence") === lib.SENTENCE && await text("#vf-who") === "No outside program reads it yet.");
check("  the program id on devnet", await text("#vf-program") === lib.PROGRAM);
check("  the three calls, each a block to copy", await page.locator(".vf-call").count() === 3 && await page.locator(".vf-call pre code").count() === 3
  && JSON.stringify(await page.locator(".vf-call h3").allTextContents()) === JSON.stringify(lib.CALLS.map((c) => c.title)));
await page.click('[data-copy="call-0"]');
check("  Copy puts the block on the clipboard, whole", await page.evaluate(() => navigator.clipboard.readText()) === lib.CALLS[0].code && await text('[data-copy="call-0"]') === "Copied");
await page.click('[data-copy="program"]');
check("  and the program id", await page.evaluate(() => navigator.clipboard.readText()) === lib.PROGRAM);
check("  the issuers are a table that scrolls inside itself: one row each, with what to gate on",
  await page.locator(".k-table").first().locator("tbody tr").count() === book.issuers.length
  && (await page.locator(".k-table").first().locator("tbody tr").nth(2).textContent()).includes("email_verified")
  && await page.locator(".k-table").first().evaluate((e) => getComputedStyle(e).overflowX === "auto"));
check("  the table is the page: it comes before the calls and the tool, and counts what is accepted today",
  await page.evaluate(() => { const t = document.querySelector("#verifier .k-table"), c = document.querySelector("#vf-calls"), tool = document.querySelector("#vf-tool");
    return !!(t.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) && !!(t.compareDocumentPosition(tool) & Node.DOCUMENT_POSITION_FOLLOWING); })
  && await text("#vf-count") === `${book.issuers.length} issuers: ${book.issuers.filter((i) => i.supported === "yes").length} accepted today, ${book.issuers.filter((i) => i.supported !== "yes").length} in part.`);
check("  each row says per algorithm: accepted today, or not yet",
  (await cells('tr[data-issuer="google"]')).includes("RS256: accepted today.") && !(await cells('tr[data-issuer="google"]')).includes("not yet")
  && (await cells('tr[data-issuer="aws"]')).includes("RS256: accepted today. ES384: not yet. Ask for RS256.")
  && (await cells('tr[data-issuer="kubernetes"]')).includes("RS256: accepted today. ES256, ES384, ES512: not yet. Gate on sub only.")
  && (await cells('tr[data-issuer="vercel"]')).includes("RS256: accepted today.") && await text("#vf-notyet") === "Not yet: ES256, ES384, ES512, PS256, EdDSA.");
check("  each issuer's name links to the page its claims were read from", JSON.stringify(await page.locator(".k-table").first().locator("tbody th a").evaluateAll((a) => a.map((x) => x.href))) === JSON.stringify(book.issuers.map((i) => i.source)));
check("  nothing is said of a token before one is pasted", await text("#vf-out") === "");

const before = asked.length;
await page.click("#vf-sample");
check("the tool: a sample token is decoded in the page, and the first thing said is that nothing was verified", await text("#vf-verdict") === "Decoded, not verified.");
check("  it says the algorithm and the key size are ones the verifier takes, and names the issuer",
  JSON.stringify(await page.locator("#vf-lines li").allTextContents()) === JSON.stringify(["Signed RS256: the verifier takes it.", "Signed by a 2048-bit key: the verifier takes it.", "Names Buildkite as its issuer.", "Expires in time: a program can still read it."]));
check("  and which claims a program could gate on", (await cells("#vf-claims")).includes("organization_id 0184990a-477b-4fa8-9968-496074483cec Yes: gate on it") && (await cells("#vf-claims")).includes("build_number 1 Yes"));
const hostile = token({ alg: "ES384", typ: "JWT", kid: "<b>k</b>" }, { iss: "https://abc.tokens.sts.global.api.aws", sub: "<img src=x onerror=\"window.pwned=1\">", aud: ["a"], exp: NOW + 300,
  "https://sts.amazonaws.com/": { aws_account: "123456789012" }, ok: true }, 96);
await page.fill("#vf-jwt", hostile);
check("  an ES384 token from AWS: decoded, not verified, and said to be refused",
  await text("#vf-verdict") === "Decoded, not verified." && (await page.locator("#vf-lines li").allTextContents())[0] === "Signed ES384: the verifier does not take it."
  && await page.locator('#vf-lines li[data-state="bad"]').count() === 1 && (await text("#vf-lines")).includes("Names AWS (IAM outbound identity federation) as its issuer."));
check("  a list, an object and a boolean are said not to be read", (await cells("#vf-claims")).includes('aud ["a"] No: a list')
  && (await cells("#vf-claims")).includes("No: nested") && (await cells("#vf-claims")).includes("ok true No: true or false"));
check("  what a token says is shown as text, never run", await page.evaluate(() => window.pwned === undefined && !document.querySelector("#vf-out img, #vf-out b")) && (await cells("#vf-claims")).includes("<img src=x"));
await page.fill("#vf-jwt", "not a token");
check("  text that is not a JWT is said so", (await text("#vf-out")).startsWith("Paste a signed JWT"));
await page.fill("#vf-jwt", hostile);
check("  pasting a token asked nothing of any host, and the page kept nothing", asked.length === before && await page.evaluate(() => localStorage.length + sessionStorage.length + document.cookie.length) === 0, asked.slice(before));
check("no request went anywhere but to the site itself", asked.length > 0 && asked.every((u) => u.startsWith(base)), asked.filter((u) => !u.startsWith(base)));

for (const filled of [false, true]) {
  if (!filled) await page.click("#vf-clear");
  else await page.fill("#vf-jwt", token({ alg: "RS256", typ: "JWT" }, { ...book.issuers.find((i) => i.id === "circleci").claims, exp: NOW + 300, long: "x".repeat(400) }, 384));
  const said = await statements(), over = said.filter((s) => words(s) > 12);
  check(`every statement is twelve words at most (${filled ? "with a token decoded" : "as the page opens"}: ${said.length} of them)`, said.length > 20 && over.length === 0, over);
  for (const width of [320, 360, 414, 768, 1024, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    check(`  no sideways scroll at ${width} px`, await sideways() <= 0, await sideways());
  }
}
await page.click("#vf-clear");
check("  Clear leaves nothing of the token on the page", await text("#vf-out") === "" && await page.inputValue("#vf-jwt") === "");
// the badge of a receipt that checks (web/badge.js renderVerified, mounted here): drawn only when the receipt hashes to the digest named
{
  const receipt = { version: 2, order: "x", cluster: "devnet" }, digest = await page.evaluate(async (r) => (await import("./badge.js")).receiptDigest(r), receipt);
  const v = { issued: true, verdict: "accepted", words: "accepted", why: "", digest, pull_request: 12, commit: "c".repeat(40), evidence: [], note: "" };
  const paste = async (doc) => { await page.fill("#vf-receipt", JSON.stringify(doc)); await page.waitForSelector("#vf-badge-out [data-verified]"); return page.getAttribute("#vf-badge-out [data-verified]", "data-verified"); };
  check("the badge: a receipt that hashes to its digest, verdict accepted, is drawn as Knos-verified", (await paste({ verified: v, receipt })) === "yes" && (await page.textContent("#vf-badge-out svg")).includes("Knos-verified") && (await text("#vf-badge-out")).includes(digest));
  check("  an edited receipt gets no badge, and the reason", (await paste({ verified: v, receipt: { ...receipt, order: "y" } })) === "no" && (await text("#vf-badge-out")).includes("does not hash to the digest"));
  check("  a verdict that is not accepted gets none", (await paste({ ...v, verdict: "rejected", issued: false, why: "the checks failed" })) === "no" && (await text("#vf-badge-out")).includes("the checks failed"));
  await page.fill("#vf-receipt", "not json"); await page.waitForSelector('#vf-badge-out [data-verified="unread"]');
  check("  what is not JSON is said to be that, and nothing is asked of anyone", (await text("#vf-badge-out")) === "Not JSON. Paste the whole file." && asked.every((u) => u.startsWith(base)));
  await page.fill("#vf-receipt", "");
}
// a receipt in five parts (receiptParts, held to knos.receipt.parts by tests/web/receipt_parts.mjs): five rows, each one line, each a fold
{
  const { cases } = JSON.parse(readFileSync(join(here, "..", "data", "receipt_parts.json"), "utf8"));
  const weak = cases.find((c) => c.name.startsWith("reported: version 4's first")), strong = cases.find((c) => c.name.startsWith("a suite decided and two evaluators"));
  const before = asked.length;
  const paste = async (doc) => { await page.fill("#vf-five-in", typeof doc === "string" ? doc : JSON.stringify(doc)); await page.waitForSelector("#vf-five-out [data-parts]"); return page.getAttribute("#vf-five-out [data-parts]", "data-parts"); };
  const rows = () => page.evaluate(() => [...document.querySelectorAll("#vf-parts details")].map((d) => [d.dataset.part, d.open, d.querySelector("summary strong").textContent, d.querySelector("summary span").textContent]));
  check("five parts: a valid, signed, paid receipt whose test is weak reads as weak", (await paste(weak.receipt)) === "weak" && (await text("#vf-five-out")).startsWith("Read: a weak acceptance. Verdict: accepted."));
  const got = await rows();
  check("  five rows in order, each shut and one line: Identity, Execution, Acceptance, Consequence, Assurance",
    JSON.stringify(got.map((r) => [r[0], r[1], r[2]])) === JSON.stringify(lib.FIVE.map((id, n) => [id, false, ["Identity", "Execution", "Acceptance", "Consequence", "Assurance"][n]]))
    && JSON.stringify(got.map((r) => r[3])) === JSON.stringify(weak.parts.parts.map((x) => x.line)), got);
  check("  the assurance row starts with WEAK and is marked", got[4][3].startsWith("WEAK (reported): ") && await page.getAttribute('#vf-parts details[data-part="assurance"]', "data-weak") === "yes");
  await page.click('#vf-parts details[data-part="assurance"] summary');
  check("  a row opens to what stands behind it", await page.evaluate(() => document.querySelector('#vf-parts details[data-part="assurance"]').open)
    && (await text('#vf-parts details[data-part="assurance"]')).includes("Outside the evaluation: The workflow file decides what it reads"));
  for (const width of [320, 414, 1280]) {
    await page.setViewportSize({ width, height: 800 });
    check(`  no sideways scroll at ${width} px with the five parts shown and one open`, await sideways() <= 0, await sideways());
  }
  check("  a suite two outside evaluators ran again is not weak, and still says what stayed outside", (await paste({ receipt: strong.receipt })) === "read"
    && (await rows())[4][3].startsWith("Agreed: two evaluators with different owners each ran the suite and agree.") && (await text("#vf-five-out")).startsWith("Read, not verified."));
  check("  a file that is not a receipt is said to be that, in a few words", (await paste({ type: "x" })) === "unread" && (await paste("not json")) === "unread" && (await text("#vf-five-out")) === "Not JSON. Paste the whole file.");
  check("  what a receipt says is shown as text, never run", (await paste({ ...weak.receipt, order: "<img src=x onerror=window.pwned=1>" })) === "weak" && await page.evaluate(() => window.pwned === undefined && !document.querySelector("#vf-five-out img")));
  check("  reading a receipt asked nothing of any host, and the page kept nothing", asked.length === before && await page.evaluate(() => localStorage.length + sessionStorage.length + document.cookie.length) === 0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  check("  reduced motion: the rows' handles do not turn", await page.evaluate(() => [...document.querySelectorAll("#vf-parts summary")].every((e) => parseFloat(getComputedStyle(e, "::before").transitionDuration) <= 0.001)),
    await page.evaluate(() => getComputedStyle(document.querySelector("#vf-parts summary"), "::before").transitionDuration));
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.fill("#vf-five-in", "");
  check("  an emptied box leaves nothing of the receipt on the page", await text("#vf-five-out") === "");
}
check("no error in the page", errors.length === 0, errors);
await browser.close();
server.close();
console.log(process.exitCode ? "FAILED" : "all passed");
