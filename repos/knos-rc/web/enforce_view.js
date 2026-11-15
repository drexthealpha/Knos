// The enforcement matrix as a table (#enforcement): one row a route that can set money aside or move it, one column a
// restriction, and in each cell WHO holds it: the program, the workflow, nobody (advisory), or nothing by intent (outside).
// renderEnforcement(el, { esc, data }) draws enforce.json, which scripts/build_site.sh writes with `python -m knos.enforce
// --json`: { routes, restrictions, cells[route][restriction] = { class, by, test } }. A route or a restriction is a
// name, or an object with an id and a name. Nothing here is typed in: a cell the file does not hold is drawn empty.
// A route may name a `group`: the routes of ENTERPRISE-CONTROLLED FUNDS (money in a Squads v4 vault, whose threshold
// and spending limits the Squads program enforces) carry group "enterprise", or an id that starts with "squads"; they
// are drawn last, under a row that names the set (`groups[group]` of the file, else the words of GROUPS).
// A cell is a button: pressed (or reached with Tab and Enter), the line under the table says what holds it and names
// the test that tries to get round it. The four classes filter the table; nothing is sent anywhere. On a phone the table
// scrolls sideways: a cell reached with Tab is scrolled clear of the sticky first column and of the edge, and the answer,
// which is under the table, is brought into view when it is pressed.
const CLASSES = ["program", "workflow", "advisory", "outside"];
const SAID = { program: "The program refuses it.", workflow: "The pinned workflow refuses it.", advisory: "A file says so. Nothing stops it.", outside: "Outside the boundary, by intent." };
const STYLE = `
body[data-page="enforcement"] .mount { max-width: 1080px; }
.ke-keys { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 12px; }
.ke-keys button { margin: 0; }
.ke-keys button[aria-pressed="true"] { border-color: var(--ink); }
.ke table { border-collapse: collapse; }
.ke th, .ke td { padding: 6px 8px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--line); font-size: var(--s-1, 13px); }
.ke thead th { position: sticky; top: 0; background: var(--paper-2); font-weight: 600; }
.ke tbody th { font-weight: 600; min-width: 11em; }
.ke tbody th, .ke thead th:first-child { position: sticky; left: 0; z-index: 1; background: var(--paper-2); }
.ke thead th:first-child { z-index: 2; }
.ke tbody tr.ke-group th { position: static; padding-top: 14px; font-size: 12px; letter-spacing: .06em; text-transform: uppercase; color: var(--ink-2); background: transparent; }
.ke .k-table { container-type: inline-size; }
.ke tbody tr.ke-group th > span { position: sticky; left: 8px; display: inline-block; max-width: calc(100cqw - 16px); }   /* the set's name wraps inside what a phone shows */
@media (max-width: 520px) { .ke tbody th { min-width: 7.5em; max-width: 7.5em; } .ke th, .ke td { padding: 6px 5px; } }
.ke .ke-cell { all: unset; box-sizing: border-box; cursor: pointer; display: inline-block; padding: 2px 8px; border-radius: 999px; border: 1px solid currentColor; font-size: 12px; font-weight: 700; white-space: nowrap;
  transition: opacity var(--dur-1, 120ms) var(--ease, ease); }
.ke .ke-cell:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.ke .ke-cell[data-class="program"] { color: var(--ok); }
.ke .ke-cell[data-class="workflow"] { color: var(--accent); }
.ke .ke-cell[data-class="advisory"] { color: var(--warn); }
.ke .ke-cell[data-class="outside"] { color: var(--ink-2); border-style: dashed; }
.ke .ke-cell[aria-pressed="true"] { background: color-mix(in srgb, currentColor 14%, transparent); }
.ke[data-show] .ke-cell:not([data-on]) { opacity: .22; }
.ke-said { margin: 12px 0 0; min-height: 3.2em; display: grid; gap: 2px; }
.ke-said > * { margin: 0; overflow-wrap: anywhere; }
.ke-said .mono { word-break: normal; }          /* what holds a cell is often a sentence: broken between words, not inside one */
@media (prefers-reduced-motion: reduce) { .ke .ke-cell { transition: none; } }`;

const GROUPS = { enterprise: "Enterprise-controlled funds (Squads vault)" };
const named = (x) => (x && typeof x === "object" ? { id: String(x.id ?? x.key ?? x.name), name: String(x.name ?? x.label ?? x.title ?? x.id), group: x.group ? String(x.group) : /^squads/i.test(String(x.id ?? "")) ? "enterprise" : "" }
  : { id: String(x), name: String(x).replace(/_/g, " "), group: /^squads/i.test(String(x)) ? "enterprise" : "" });
const listOf = (v) => (Array.isArray(v) ? v.map(named) : Object.entries(v || {}).map(([id, x]) => named(typeof x === "object" && x ? { id, ...x } : { id, name: typeof x === "string" ? x : id })));

export function renderEnforcement(el, { esc, data } = {}) {
  if (!el || !data || !data.cells) return;
  const all = listOf(data.routes), cols = listOf(data.restrictions);
  const sets = [...new Set(all.map((r) => r.group).filter(Boolean))];
  const routes = [...all.filter((r) => !r.group), ...sets.flatMap((g) => all.filter((r) => r.group === g))];
  const setName = (g) => String(data.groups?.[g] ?? GROUPS[g] ?? g.replace(/_/g, " "));
  if (!routes.length || !cols.length) return;
  if (!document.getElementById("ke-style")) { const s = document.createElement("style"); s.id = "ke-style"; s.textContent = STYLE; document.head.append(s); }
  const cell = (r, c) => data.cells?.[r.id]?.[c.id] || null;
  const count = Object.fromEntries(CLASSES.map((k) => [k, 0]));
  for (const r of routes) for (const c of cols) { const k = cell(r, c)?.class; if (k in count) count[k] += 1; }
  el.innerHTML = `<h2>Who enforces each rule</h2>
    <p class="lede">Press a cell: what holds it, and its bypass test.</p>
    <div class="card ke" data-keep>
      <div class="ke-keys" role="group" aria-label="Show one class">${CLASSES.map((k) => `<button type="button" class="k-btn quiet ghost small" data-only="${k}" aria-pressed="false">${k} <span class="k-num">${count[k]}</span></button>`).join("")}</div>
      <div class="k-table" tabindex="0" role="region" aria-label="Enforcement matrix"><table>
        <thead><tr><th scope="col">Route</th>${cols.map((c) => `<th scope="col">${esc(c.name)}</th>`).join("")}</tr></thead>
        <tbody>${routes.map((r, i) => `${r.group && r.group !== routes[i - 1]?.group ? `<tr class="ke-group"><th scope="rowgroup" colspan="${cols.length + 1}"><span>${esc(setName(r.group))}</span></th></tr>` : ""}<tr${r.group ? ` data-group="${esc(r.group)}"` : ""}><th scope="row">${esc(r.name)}</th>${cols.map((c) => { const x = cell(r, c);
          return `<td>${x ? `<button type="button" class="ke-cell" data-class="${esc(x.class)}" data-r="${esc(r.id)}" data-c="${esc(c.id)}" aria-pressed="false" aria-label="${esc(`${r.name}, ${c.name}: ${x.class}`)}">${esc(x.class)}</button>` : ""}</td>`; }).join("")}</tr>`).join("")}</tbody>
      </table></div>
      <div class="ke-said" role="status" aria-live="polite"><p class="fine">No cell pressed yet.</p></div>
    </div>
    <p class="fine" data-keep><a href="https://github.com/drexthealpha/Knos/blob/main/docs/reference/ENFORCEMENT.md">The same matrix as a document</a></p>`;
  const box = el.querySelector(".ke"), said = el.querySelector(".ke-said"), wrap = el.querySelector(".k-table");
  box.addEventListener("focusin", (ev) => {
    const b = ev.target.closest?.(".ke-cell");
    if (!b) return;
    const w = wrap.getBoundingClientRect(), r = b.getBoundingClientRect(), pad = 6;
    const left = w.left + wrap.clientLeft + (wrap.querySelector("tbody th")?.getBoundingClientRect().width || 0), right = w.left + wrap.clientLeft + wrap.clientWidth;
    if (r.right + pad > right) wrap.scrollLeft += r.right + pad - right;
    else if (r.left - pad < left) wrap.scrollLeft -= left - (r.left - pad);
  });
  box.addEventListener("click", (ev) => {
    const key = ev.target.closest("[data-only]"), b = ev.target.closest(".ke-cell");
    if (key) {
      const on = key.getAttribute("aria-pressed") !== "true";
      for (const k of box.querySelectorAll("[data-only]")) k.setAttribute("aria-pressed", String(on && k === key));
      if (on) box.dataset.show = key.dataset.only; else delete box.dataset.show;
      for (const c of box.querySelectorAll(".ke-cell")) { if (on && c.dataset.class === key.dataset.only) c.dataset.on = ""; else delete c.dataset.on; }
      return;
    }
    if (!b) return;
    const r = routes.find((x) => x.id === b.dataset.r), c = cols.find((x) => x.id === b.dataset.c), x = cell(r, c);
    for (const o of box.querySelectorAll('.ke-cell[aria-pressed="true"]')) o.setAttribute("aria-pressed", "false");
    b.setAttribute("aria-pressed", "true");
    said.innerHTML = `<p><strong>${esc(r.name)}: ${esc(c.name)}</strong></p><p>${esc(SAID[x.class] || x.class)}</p>
      ${x.by ? `<p class="fine"><span class="mono">${esc(x.by)}</span></p>` : ""}${x.test ? `<p class="fine">Bypass test: <span class="mono">${esc(x.test)}</span></p>` : ""}`;
    const s = said.getBoundingClientRect();
    if (s.bottom > innerHeight || s.top < 0) said.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
}
