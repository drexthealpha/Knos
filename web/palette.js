// The command palette: Ctrl/Cmd+K, or "/" when no field has the focus (web/motion.js listens and fetches this file on
// first use; a click on any [data-palette] opens it too). Type, arrow, Enter: go to a page, check an invoice, open the
// playground, verify a receipt, copy the install command, switch light and dark, or open a document by its title.
// It is a modal <dialog>: the page behind is inert, Escape closes it, and the focus goes back to where it was.
// Roles are those of a combobox with a list (WAI-ARIA Authoring Practices): the field is role=combobox with
// aria-controls, aria-expanded and aria-activedescendant; the list is role=listbox; a row is role=option with
// aria-selected. The focus never leaves the field. The pages are read from the bar, so a page the bar does not offer
// is not offered here. The documents are docs_index.json ([{ "title", "file" }], which scripts/docs_index.py writes
// into the build); with no such file the palette has every command and no documents.
import { morph, toast } from "./motion.js";

export const INSTALL = "pipx install knos";
const DOCS = "https://github.com/drexthealpha/Knos/blob/main/docs/";
let dlg, field, list, count, shown = [], at = 0, back = null, docs = null;

// a change of page, as a link in the bar makes it
const go = (hash) => (location.hash === hash ? Promise.resolve() : morph(() => import("./front.js").then((m) => m.go(hash))));

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast("Copied"); } catch { toast("Not copied: select it by hand", "bad"); }
}

// the front door of the first screen (#front-door) where the page has one, the Check an invoice page elsewhere
async function invoice() {
  const find = () => [...document.querySelectorAll("#front-door textarea, #front-door input:not([type=file]), [data-invoice], #shadow textarea, #shadow input")].find((e) => e.checkVisibility?.());
  let box = find();
  if (!box) { await go(document.getElementById("front-door") ? "#check" : "#shadow"); box = find(); }
  box?.focus();
}

export function commands() {
  const out = [], have = new Set();
  const add = (label, kind, run, more = "") => { const key = (kind === "Docs" ? "d:" : "") + label; if (label && !have.has(key)) { have.add(key); out.push({ label, kind, run, more }); } };   // a document may share a page's name
  add("Check an invoice", "Do", invoice);
  add("Open the playground", "Do", () => go("#playground"));
  add("Verify a receipt", "Do", () => go("#verifier"));
  add("Copy the install command", "Do", () => copy(INSTALL), INSTALL);
  if (document.getElementById("theme")) add("Switch light or dark", "Do", () => document.getElementById("theme").click());
  for (const a of document.querySelectorAll("header nav a[href]")) {
    const to = a.getAttribute("href");
    if (!a.hidden) add(a.textContent.trim(), "Go to", () => (to.startsWith("#") ? go(to) : location.assign(a.href)));
  }
  for (const d of docs || []) add(d.title, "Docs", () => { window.open(DOCS + d.file, "_blank", "noopener"); }, d.file);
  return out;
}

// every word typed is somewhere in the row; a row that starts with what was typed comes first; documents wait for a word
export function match(all, typed) {
  const words = typed.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return all.filter((c) => c.kind !== "Docs");
  const rank = (c) => { const l = c.label.toLowerCase(); return l.startsWith(words[0]) ? 0 : l.includes(words[0]) ? 1 : 2; };
  return all.filter((c) => words.every((w) => `${c.label} ${c.kind} ${c.more}`.toLowerCase().includes(w)))
    .map((c, i) => [rank(c), i, c]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((r) => r[2]).slice(0, 12);
}

function pick(i) {
  at = shown.length ? (i + shown.length) % shown.length : 0;
  [...list.children].forEach((li, k) => li.setAttribute("aria-selected", String(k === at)));
  const on = list.children[at];
  if (on) { field.setAttribute("aria-activedescendant", on.id); on.scrollIntoView({ block: "nearest" }); } else field.removeAttribute("aria-activedescendant");
}

function draw() {
  shown = match(commands(), field.value);
  list.replaceChildren(...shown.map((c, i) => {
    const li = document.createElement("li"), a = document.createElement("span"), b = document.createElement("small");
    li.id = `k-pal-${i}`; li.setAttribute("role", "option"); a.textContent = c.label; b.textContent = c.kind;
    li.append(a, b);
    return li;
  }));
  count.textContent = shown.length ? `${shown.length} ${shown.length === 1 ? "result" : "results"}` : "Nothing matches";
  pick(0);
}

function close() { if (dlg?.open) dlg.close(); }
async function run(i) {
  const c = shown[i];
  if (!c) return;
  close();                                                       // the focus is back where it was before the command acts
  try { await c.run(); } catch { /* a command that cannot act changes nothing */ }
}

function build() {
  dlg = document.createElement("dialog");
  dlg.className = "k-pal";
  dlg.setAttribute("aria-label", "Commands");
  dlg.innerHTML = `<input type="text" role="combobox" aria-label="Search pages, actions and documents" aria-autocomplete="list" aria-expanded="true" aria-controls="k-pal-list"
      autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="go" placeholder="Go to a page, or do something">
    <ul id="k-pal-list" role="listbox" aria-label="Commands"></ul>
    <p><span role="status" aria-live="polite"></span><span aria-hidden="true"> · arrows: move · Enter: open · Esc: close</span></p>`;
  field = dlg.querySelector("input"); list = dlg.querySelector("ul"); count = dlg.querySelector("[role=status]");
  field.addEventListener("input", draw);
  field.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); pick(at + 1); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); pick(at - 1); }
    else if (ev.key === "PageDown") { ev.preventDefault(); pick(shown.length - 1); }
    else if (ev.key === "PageUp") { ev.preventDefault(); pick(0); }
    else if (ev.key === "Enter") { ev.preventDefault(); run(at); }
    else if (ev.key === "Tab") ev.preventDefault();                 // the field is the only stop: the focus stays in the dialog
  });
  list.addEventListener("pointermove", (ev) => { const li = ev.target.closest("li"); if (li && li.getAttribute("aria-selected") !== "true") pick([...list.children].indexOf(li)); });
  list.addEventListener("click", (ev) => { const li = ev.target.closest("li"); if (li) run([...list.children].indexOf(li)); });
  dlg.addEventListener("click", (ev) => { if (ev.target === dlg) close(); });          // a press on the dimmed page
  dlg.addEventListener("cancel", () => field.setAttribute("aria-expanded", "false"));
  dlg.addEventListener("close", () => { field.setAttribute("aria-expanded", "false"); const to = back; back = null; if (to?.isConnected) to.focus({ preventScroll: true }); });
  document.body.append(dlg);
}

export function open() {
  if (!dlg) build();
  if (dlg.open) return dlg;
  back = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
  field.value = "";
  field.setAttribute("aria-expanded", "true");
  if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  draw();
  field.focus();
  if (docs === null) {
    docs = [];
    fetch(new URL("./docs_index.json", import.meta.url)).then((r) => (r.ok ? r.json() : [])).then((d) => { docs = Array.isArray(d) ? d.filter((x) => x && x.title && /^[\w.-]+$/.test(x.file || "")) : []; if (dlg.open && field.value) draw(); }).catch(() => {});
  }
  return dlg;
}
