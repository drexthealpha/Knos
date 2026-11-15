// node tests/web/a11y.mjs <site dir>
// What can be read, and what a keyboard can do, held on a build of web/ in headless Chromium:
//   contrast  every text colour of the design contract (--ink --ink-2 --accent --ok --bad --warn) against every surface
//             it is written on (--paper --paper-2 --soft), and a button's word (--accent-fg) on --accent, computed by
//             the WCAG 2 formula from the values the browser resolves: 4.5:1 or more (AA), --ink 7:1 or more, in the
//             dark and the light palette, each reached both ways (the system's setting, and the button in the bar)
//   depth     no element that holds text is blurred (no filter: blur on it or on anything it is inside), and every
//             shadow of --depth-1..3 falls downward: one light, above
//   palette   Ctrl+K and "/" open it, "/" in a field types a slash; the roles are a combobox's (combobox, listbox,
//             option, aria-controls, aria-expanded, aria-activedescendant, aria-selected); arrows, Enter and Escape
//             work with no pointer; the page behind is inert; the focus goes back where it was; a command acts
// No browser: a failure in CI, a skip elsewhere (tests/web/overflow.mjs, `owed`).
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { join, extname } from "node:path";
import { chromiumOrSkip, TYPES } from "./overflow.mjs";

const root = process.argv[2];
if (!root || !existsSync(join(root, "index.html"))) { console.error("usage: node tests/web/a11y.mjs <site dir>"); process.exit(2); }
let fails = 0;
const check = (name, cond, detail) => { if (cond) console.log("ok  ", name); else { fails++; console.error("FAIL", name, detail === undefined ? "" : JSON.stringify(detail)); } };

const browser = await chromiumOrSkip();
const server = createServer((req, res) => {
  const path = join(root, decodeURIComponent(new URL(req.url, "http://x").pathname).replace(/\/$/, "/index.html"));
  if (!path.startsWith(root) || !existsSync(path)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[extname(path)] || "application/octet-stream" }); res.end(readFileSync(path));
});
await new Promise((r) => server.listen(0, "127.0.0.1", r));
const base = `http://127.0.0.1:${server.address().port}/`;
const world = async (o = {}) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...o });
  await ctx.route("**/*", (route) => (route.request().url().startsWith(base) ? route.continue() : route.abort()));
  return ctx;
};
const open = async (ctx, hash = "") => { const page = await ctx.newPage(); await page.goto(base + hash, { waitUntil: "load" }); await page.waitForSelector("#theme:not([hidden])"); return page; };

// ---- contrast ---------------------------------------------------------------------------------------------------------------
const TEXT = ["--ink", "--ink-2", "--accent", "--ok", "--bad", "--warn"], ON = ["--paper", "--paper-2", "--soft"];
const lum = ([r, g, b]) => { const f = (v) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05); };
// the colour a variable resolves to, as the browser paints it (so color-mix() and named colours are measured, not parsed)
const palette = (page, names) => page.evaluate((list) => {
  const c = document.createElement("canvas").getContext("2d", { willReadFrequently: true }), out = {};
  const probe = document.createElement("i"); document.body.append(probe);
  for (const n of list) { probe.style.color = `var(${n})`; c.clearRect(0, 0, 1, 1); c.fillStyle = getComputedStyle(probe).color; c.fillRect(0, 0, 1, 1); out[n] = [...c.getImageData(0, 0, 1, 1).data]; }
  probe.remove(); return out;
}, names);
const table = {};
for (const [how, scheme, theme] of [["system", "dark", null], ["system", "light", null], ["button", "light", "dark"], ["button", "dark", "light"]]) {
  const ctx = await world({ colorScheme: scheme, reducedMotion: "reduce" });
  const page = await open(ctx);
  if (theme) await page.evaluate((t) => { document.documentElement.dataset.theme = t; }, theme);
  const name = theme || scheme, seen = await palette(page, [...TEXT, ...ON, "--accent-fg", "--line"]);
  const opaque = Object.entries(seen).filter(([n, v]) => n !== "--line" && v[3] !== 255).map(([n]) => n);
  const pairs = [];
  for (const t of TEXT) for (const on of ON) pairs.push([`${t} on ${on}`, ratio(seen[t], seen[on])]);
  pairs.push(["--accent-fg on --accent", ratio(seen["--accent-fg"], seen["--accent"])]);
  const low = pairs.filter(([, r]) => r < 4.5).map(([n, r]) => `${n} ${r.toFixed(2)}`);
  check(`contrast, ${name} (by the ${how}): each of ${pairs.length} pairs of text and surface is 4.5:1 or more`, low.length === 0 && opaque.length === 0, [low, opaque]);
  check(`contrast, ${name} (by the ${how}): the text itself is 7:1 or more on every surface`, ON.every((on) => ratio(seen["--ink"], seen[on]) >= 7), ON.map((on) => ratio(seen["--ink"], seen[on]).toFixed(2)));
  if (how === "system") table[name] = Object.fromEntries(pairs.map(([n, r]) => [n, Math.round(r * 100) / 100]));
  else check(`contrast, ${name}: the button gives the same palette as the system's setting`, JSON.stringify(Object.fromEntries(pairs.map(([n, r]) => [n, Math.round(r * 100) / 100]))) === JSON.stringify(table[name]));
  if (how === "system") {
    // ---- depth ----------------------------------------------------------------------------------------------------------------
    const depth = await page.evaluate(() => {
      const blurred = [];
      for (const hash of ["#check"]) { void hash; for (const el of document.querySelectorAll("body *")) {
        const s = getComputedStyle(el);
        if (!/blur\(/.test(s.filter)) continue;
        const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        for (let n = walk.nextNode(); n; n = walk.nextNode()) if (n.textContent.trim()) { blurred.push(el.className || el.tagName); break; }
      } }
      const root = getComputedStyle(document.documentElement), up = [];
      for (const d of ["--depth-1", "--depth-2", "--depth-3"]) for (const part of root.getPropertyValue(d).split(/,(?![^(]*\))/)) {
        if (/inset/.test(part)) continue;
        const px = (part.replace(/rgba?\([^)]*\)|var\([^)]*\)/g, "").match(/-?[\d.]+(px)?/g) || []).map(parseFloat);
        if (px[0] !== 0 || px[1] <= 0) up.push(`${d}: ${part.trim()}`);
      }
      return { blurred, up };
    });
    check(`depth, ${name}: nothing that holds text is blurred`, depth.blurred.length === 0, depth.blurred);
    check(`depth, ${name}: every shadow falls straight down: one light, above`, depth.up.length === 0, depth.up);
  }
  await ctx.close();
}

// ---- the palette, by keyboard alone ----------------------------------------------------------------------------------------
{
  const ctx = await world({ colorScheme: "dark", permissions: ["clipboard-read", "clipboard-write"] });
  const page = await open(ctx);
  const asked = []; page.on("request", (r) => asked.push(r.url().replace(base, "")));
  const errors = []; page.on("pageerror", (e) => errors.push(e.message));
  check("palette: not asked for before it is opened", !asked.includes("palette.js") && (await page.evaluate(() => performance.getEntriesByType("resource").some((r) => r.name.endsWith("/palette.js")))) === false);
  await page.focus("#theme");
  await page.keyboard.press("Control+k");
  await page.waitForSelector("dialog.k-pal[open]");
  const roles = await page.evaluate(() => {
    const d = document.querySelector("dialog.k-pal"), f = d.querySelector("input"), l = d.querySelector("ul"), opts = [...l.children];
    return { modal: d.matches(":modal"), name: d.getAttribute("aria-label"), field: [f.getAttribute("role"), f.getAttribute("aria-controls") === l.id, f.getAttribute("aria-expanded"), f.getAttribute("aria-autocomplete"), !!f.getAttribute("aria-label")],
      list: [l.getAttribute("role"), !!l.getAttribute("aria-label")], options: opts.length, allOptions: opts.every((o) => o.getAttribute("role") === "option" && o.id), selected: opts.filter((o) => o.getAttribute("aria-selected") === "true").length,
      active: f.getAttribute("aria-activedescendant") === opts[0].id, focus: document.activeElement === f, labels: opts.map((o) => o.firstChild.textContent),
      inert: (() => { const b = document.getElementById("theme"); b.focus(); return document.activeElement !== b; })(), ring: (() => { f.focus(); const s = getComputedStyle(f); return s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2; })(),
      box: (() => { const r = d.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight; })() };
  });
  check("palette: Ctrl+K opens a modal dialog with the focus in its field; the page behind is inert", roles.modal && roles.focus && roles.inert && roles.name === "Commands" && roles.box, roles);
  check("palette: the roles are a combobox's: combobox with aria-controls, aria-expanded, aria-autocomplete, aria-activedescendant; listbox; options, one selected", roles.field.join() === "combobox,true,true,list,true" && roles.list.join() === "listbox,true"
    && roles.options >= 8 && roles.allOptions && roles.selected === 1 && roles.active && roles.ring, roles);
  check("palette: it offers the four actions, the copy of the install command, and every page of the bar", ["Check an invoice", "Open the playground", "Verify a receipt", "Copy the install command", "Switch light or dark", "Pricing", "Docs"].every((l) => roles.labels.includes(l))
    && new Set(roles.labels).size === roles.labels.length, roles.labels);
  await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowDown"); await page.keyboard.press("ArrowUp");
  const moved = await page.evaluate(() => { const f = document.querySelector(".k-pal input"), on = document.querySelector('.k-pal [aria-selected="true"]'); return [on.id, f.getAttribute("aria-activedescendant"), document.activeElement === f, document.querySelectorAll('.k-pal [aria-selected="true"]').length]; });
  check("palette: the arrows move the selection, the focus stays in the field", moved.join() === "k-pal-1,k-pal-1,true,1", moved);
  await page.keyboard.press("ArrowUp"); await page.keyboard.press("ArrowUp");
  check("palette: the arrows wrap", await page.evaluate(() => document.querySelector('.k-pal [aria-selected="true"]') === document.querySelector(".k-pal ul").lastElementChild));
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => !document.querySelector("dialog.k-pal").open);
  const backTo = await page.evaluate(() => [document.querySelector("dialog.k-pal").open, document.activeElement.id || document.activeElement.tagName, document.querySelector(".k-pal input").getAttribute("aria-expanded")]);
  check("palette: Escape closes it, and the focus is back on the button it was opened from", backTo.join() === "false,theme,false", backTo);
  await page.keyboard.press("/");
  await page.waitForSelector("dialog.k-pal[open]");
  await page.keyboard.type("pric");
  const found = await page.evaluate(() => ({ labels: [...document.querySelectorAll(".k-pal li")].map((o) => o.firstChild.textContent), says: document.querySelector(".k-pal [role=status]").textContent, typed: document.querySelector(".k-pal input").value }));
  check("palette: \"/\" opens it too, empty; typing narrows the list, and the count is said", found.typed === "pric" && found.labels[0] === "Pricing" && found.labels.length < roles.options && /^\d+ results?$/.test(found.says), found);
  await page.keyboard.press("Enter");
  await page.waitForFunction(() => location.hash === "#pricing" && !document.getElementById("view-pricing").hidden);
  // a change of page moves the focus as a link to it does (the browser's own rule for a fragment): it is not left in the dialog
  check("palette: Enter goes to the page and closes", await page.evaluate(() => !document.querySelector("dialog.k-pal").open && !document.activeElement.closest(".k-pal")));
  await page.keyboard.press("Control+k"); await page.waitForSelector("dialog.k-pal[open]");
  await page.keyboard.type("zzzz");
  check("palette: with nothing to offer it says so", await page.evaluate(() => document.querySelectorAll(".k-pal li").length === 0 && document.querySelector(".k-pal [role=status]").textContent === "Nothing matches" && !document.querySelector(".k-pal input").hasAttribute("aria-activedescendant")));
  await page.keyboard.press("Escape");
  // a document by its title, when the build carries the list
  if (existsSync(join(root, "docs_index.json"))) {
    await page.keyboard.press("Control+k"); await page.waitForSelector("dialog.k-pal[open]");
    await page.waitForFunction(() => performance.getEntriesByType("resource").some((r) => r.name.endsWith("/docs_index.json")));
    await page.keyboard.type("capabilities");
    await page.waitForFunction(() => [...document.querySelectorAll(".k-pal li small")].some((s) => s.textContent === "Docs"));
    check("palette: a document is found by its title", true);
    await page.keyboard.press("Escape");
  } else console.log("ok   palette: this build carries no docs_index.json; the palette has its commands and no documents");
  // "/" in a field is a slash
  await page.goto(base); await page.waitForSelector("#theme:not([hidden])");
  const field = await page.evaluateHandle(() => [...document.querySelectorAll("main input[type=text], main textarea")].find((e) => e.checkVisibility() && !e.readOnly));
  await field.asElement().focus(); await page.keyboard.type("a/b");
  check("palette: \"/\" typed in a field is a slash, and opens nothing", await page.evaluate(() => document.activeElement.value.endsWith("a/b") && !document.querySelector("dialog.k-pal[open]")));
  await page.keyboard.press("Control+k"); await page.waitForSelector("dialog.k-pal[open]");
  await page.keyboard.type("copy install"); await page.keyboard.press("Enter");
  await page.waitForSelector(".k-toast");
  const copied = await page.evaluate(async () => [await navigator.clipboard.readText(), document.querySelector(".k-toast").textContent, document.querySelector(".k-toasts").getAttribute("role"), document.activeElement.tagName]);
  check("palette: Copy the install command copies it, says Copied, and the focus is back in the field it left", copied[0] === "pipx install knos" && copied[1] === "Copied" && copied[2] === "status" && /INPUT|TEXTAREA/.test(copied[3]), copied);
  check("palette: the page shows that same install command", readFileSync(join(root, "index.html"), "utf8").includes("<code>pipx install knos</code>") || !/pipx? install/.test(readFileSync(join(root, "index.html"), "utf8")));
  check("palette: no page error", errors.length === 0, errors);
  await ctx.close();
}

await browser.close(); server.close();
console.log(fails ? `${fails} checks failed` : "a11y: every check held");
process.exit(fails ? 1 : 0);
