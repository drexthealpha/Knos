// The Knos game page: reads /api/state, joins as a person, submits the editable file, shows the referee's answers.
// Text from the server is always set with textContent (names, labels and the goal are players' and researchers' words).
"use strict";
const $ = (id) => document.getElementById(id);
const store = {
  get() { try { return JSON.parse(localStorage.getItem("knos-game") || "null"); } catch (e) { return null; } },
  set(v) { try { localStorage.setItem("knos-game", JSON.stringify(v)); } catch (e) { /* private window: kept for this page only */ } },
};
let me = null;
let state = null;

function cell(tr, text, cls) { const td = document.createElement("td"); td.textContent = text == null ? "-" : String(text); if (cls) td.className = cls; tr.appendChild(td); return td; }
function usdc(units) { return (units / 1e6).toFixed(2); }

async function api(path, body) {
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const ct = r.headers.get("Content-Type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || ("HTTP " + r.status));
  return data;
}

function render() {
  const s = state;
  $("title").textContent = s.title;
  $("meta").textContent = `Field: ${s.field}. Round ${s.round} of ${s.rules.rounds}, ${s.rules.per_round} attempts a round. Metric: ${s.metric} (${s.direction}). `
    + `To be paid, an attempt must beat the baseline by ${s.min_lift} on the final sealed set, and the player's GitHub or ORCID identity must be bound to a wallet on chain. Status: ${s.status}. Spec ${s.spec_hash.slice(0, 16)}.`;
  $("program").textContent = s.program;
  $("idea").textContent = s.idea;
  $("synthetic").hidden = !s.synthetic;
  $("editable").textContent = s.editable;
  const tb = $("board").querySelector("tbody");
  tb.textContent = "";
  s.board.forEach((r, i) => {
    const tr = document.createElement("tr");
    cell(tr, i + 1);
    const td = cell(tr, r.name, r.out ? "out" : "");
    if (r.label) { const sp = document.createElement("span"); sp.className = "label"; sp.textContent = r.label; td.appendChild(sp); }
    cell(tr, r.kind); cell(tr, r.shown); cell(tr, r.attempts); cell(tr, r.refused + (r.out ? " (out)" : ""));
    tb.appendChild(tr);
  });
  $("pot").textContent = `Pooled: ${usdc(s.pot.total)} test units in ${s.pot.pledges.length} pledge(s), split by the referee's final verdicts.`;
  const ul = $("pledges"); ul.textContent = "";
  s.pot.pledges.forEach((p) => { const li = document.createElement("li"); li.textContent = `${p.funder}: ${usdc(p.amount)} (${p.cluster}${p.label ? ", " + p.label : ""})${p.order ? " order " + p.order : ""}`; ul.appendChild(li); });
  if (s.final) {
    $("final-box").hidden = false;
    const fb = $("final").querySelector("tbody"); fb.textContent = "";
    s.final.verdicts.slice().sort((a, b) => (a.rank || 99) - (b.rank || 99)).forEach((v) => {
      const tr = document.createElement("tr");
      cell(tr, v.rank || "-"); cell(tr, v.name + (v.label ? " (" + v.label + ")" : ""));
      cell(tr, v.passed ? "passed" : "no", v.passed ? "passed" : "refused");
      cell(tr, (v.lift_per_seed || []).join(" / ")); cell(tr, (v.reasons || []).join("; "));
      fb.appendChild(tr);
    });
  }
}

async function refresh() {
  state = await api("/api/state");
  render();
  if (me) await mine();
}

async function mine() {
  const got = await api("/api/mine", { player: me.player, key: me.key });
  const tb = $("mine").querySelector("tbody"); tb.textContent = "";
  got.attempts.slice().reverse().forEach((a) => {
    const tr = document.createElement("tr");
    cell(tr, a.n); cell(tr, a.round); cell(tr, a.decision, a.decision === "refused" ? "refused" : ""); cell(tr, a.shown); cell(tr, (a.rules || []).join(", "));
    tb.appendChild(tr);
  });
}

function showMe() {
  $("join-box").hidden = true; $("me").hidden = false; $("me-name").textContent = me.name;
}

$("join").addEventListener("click", async () => {
  const name = $("name").value.trim();
  if (!name) { $("name").focus(); return; }
  $("join").disabled = true;
  try {
    const got = await api("/api/join", { name, payee: $("payee").value.trim() || undefined, kind: "human" });
    me = { player: got.player, key: got.key, name, game: state.id };
    store.set(me); showMe(); await refresh();
  } catch (e) { alert(e.message); } finally { $("join").disabled = false; }
});

$("load-baseline").addEventListener("click", async () => { $("file").value = await api("/api/baseline"); });

$("submit").addEventListener("click", async () => {
  $("submit").disabled = true; $("answer").textContent = "The referee is judging your attempt on sealed data...";
  try {
    const a = await api("/api/submit", { player: me.player, key: me.key, file: $("file").value });
    $("answer").textContent = `#${a.n}: ${a.decision}. ${a.said}` + (a.rules && a.rules.length ? ` Rules: ${a.rules.join(", ")}.` : "") + (a.reasons && a.reasons.length ? ` ${a.reasons.join("; ")}` : "");
    await refresh();
  } catch (e) { $("answer").textContent = e.message; } finally { $("submit").disabled = false; }
});

(async () => {
  await refresh();
  const saved = store.get();
  if (saved && saved.game === state.id) { me = saved; showMe(); await mine(); }
  setInterval(() => { refresh().catch(() => {}); }, 15000);
})();
