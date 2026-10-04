// The capability manifest as a table, with a filter by stage.
// The data is docs/capabilities.json (scripts/capabilities.py checks its evidence and renders the same rows into
// README.md). A stage is the highest of five that has evidence: a source file, a test, the on-chain version that
// carries it, a devnet transaction, someone else's run. Nothing here asks the chain: the page says what the manifest
// says, and the manifest is held to devnet when a release runs `python scripts/capabilities.py check --rpc`.
export const STAGES = ["implemented", "tested", "deployed", "exercised", "reproduced"];
export const STAGE_WORDS = { none: "not built", implemented: "implemented", tested: "tested locally", deployed: "deployed on devnet",
  exercised: "exercised on devnet", reproduced: "reproduced by someone else" };
const REPO = "https://github.com/drexthealpha/Knos/blob/main/";
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PATH = /^[A-Za-z0-9._/-]+$/, SIG = /^[1-9A-HJ-NP-Za-km-z]{86,88}$/;
const file = (p) => (PATH.test(p || "") && !p.includes("..") ? `<a href="${REPO}${esc(p)}" target="_blank" rel="noopener"><code>${esc(p)}</code></a>` : `<code>${esc(p)}</code>`);

export const stageOf = (c) => (STAGES.includes(c.stage) ? c.stage : "none");
// how many capabilities are at each stage, in the order of the stages, "not built" last
export function counts(data) {
  const out = Object.fromEntries([...STAGES, "none"].map((s) => [s, 0]));
  for (const c of data?.capabilities || []) out[stageOf(c)]++;
  return out;
}
// "all", or one stage: exactly that stage, not "at least"
export const filtered = (data, stage) => (data?.capabilities || []).filter((c) => stage === "all" || stageOf(c) === stage);

export function evidenceHtml(c) {
  const ev = c.evidence || {}, said = [];
  if (ev.implemented) said.push(file(ev.implemented.path));
  if (ev.tested) said.push(file(ev.tested.test));
  if (ev.deployed) said.push(`<code>${esc(ev.deployed.program)} ${esc(ev.deployed.version)}</code>`);
  if (ev.exercised && SIG.test(ev.exercised.signature || "")) {
    said.push(`<a href="https://explorer.solana.com/tx/${esc(ev.exercised.signature)}?cluster=devnet" target="_blank" rel="noopener">${esc(ev.exercised.signature.slice(0, 8))}...</a>`);
  }
  if (ev.reproduced && /^https:\/\//.test(ev.reproduced.url || "")) said.push(`<a href="${esc(ev.reproduced.url)}" target="_blank" rel="noopener">outside run</a>`);
  return said.join(", ") + (c.note ? `${said.length ? ". " : ""}${esc(c.note)}` : "");
}

export function tableHtml(data, stage = "all") {
  const rows = filtered(data, stage).map((c) => `<tr data-stage="${esc(stageOf(c))}"><td>${esc(c.what)}</td><td>${esc(STAGE_WORDS[stageOf(c)])}</td><td>${evidenceHtml(c)}</td></tr>`);
  return `<div class="table-wrap"><table class="capabilities"><tr><th>Capability</th><th>Stage</th><th>Evidence</th></tr>${rows.join("")
    || '<tr><td colspan="3">Nothing is at this stage yet.</td></tr>'}</table></div>`;
}

// Mount the table and its filter in `el`. `data` is docs/capabilities.json, parsed.
export function renderCapabilities(el, data) {
  const n = counts(data), total = (data?.capabilities || []).length;
  const options = [["all", `Every stage (${total})`], ...[...STAGES, "none"].map((s) => [s, `${STAGE_WORDS[s]} (${n[s]})`])];
  el.innerHTML = `<p><label>Show <select class="capabilities-stage">${options.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("")}</select></label></p>
    <div class="capabilities-table">${tableHtml(data, "all")}</div>
    <p class="fine">A stage is the highest one with evidence, and needs the ones below it: a source file, a test, the on-chain version that carries it,
      a transaction on devnet, someone else's run. Everything is on Solana devnet, in test USDC.</p>`;
  const select = el.querySelector(".capabilities-stage"), table = el.querySelector(".capabilities-table");
  select.onchange = () => { table.innerHTML = tableHtml(data, select.value); };
  return el;
}
