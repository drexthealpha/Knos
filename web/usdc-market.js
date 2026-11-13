// Round 9 U8: a claim's markets in Circle's NEAR testnet USDC, traded and backed from the visitor's own NEAR testnet
// wallet (NEAR Wallet Selector, testnet only). The visitor's wallet signs every transaction; Knos never holds a key or
// moves the visitor's funds. Markets and backers are read from NEAR itself, in this browser.
import { setupWalletSelector } from "https://esm.sh/@near-wallet-selector/core@10.1.4";
import { setupModal } from "https://esm.sh/@near-wallet-selector/modal-ui@10.1.4";
import { setupMyNearWallet } from "https://esm.sh/@near-wallet-selector/my-near-wallet@10.1.4";
import { setupMeteorWallet } from "https://esm.sh/@near-wallet-selector/meteor-wallet@10.1.4";

const box = document.getElementById("usdc");
const CFG = JSON.parse(box.dataset.cfg);   // {market, token, jobs, claim, sha256, agent, fee}
const RPC = "https://rpc.testnet.fastnear.com";
const $ = (id) => document.getElementById(id);
const usd = (u) => (Number(u) / 1e6).toFixed(2);

async function view(account, method, args) {
  const r = await fetch(RPC, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "query",
    params: { request_type: "call_function", finality: "optimistic", account_id: account, method_name: method, args_base64: btoa(JSON.stringify(args)) } }) }).then((x) => x.json());
  if (!r.result) throw new Error((r.error && (r.error.data || r.error.message)) || "no answer");
  return JSON.parse(new TextDecoder().decode(new Uint8Array(r.result.result)));
}

// this claim's two markets: the newest demand market and the open truth market whose job runs this claim's locked test
async function markets() {
  const ids = await view(CFG.market, "get_markets", {});
  const dem = ids.filter((i) => i.startsWith(`demand:${CFG.claim}:`)).sort((a, b) => +a.split(":").pop() - +b.split(":").pop()).pop();
  let truth = null;
  for (const id of ids.filter((i) => i.startsWith("job:")).reverse()) {
    const j = await view(CFG.jobs, "get_job", { id: id.slice(4) }).catch(() => null);
    if (j && j.criteria_hash === CFG.sha256) { truth = id; break; }
  }
  return { truth: truth && await view(CFG.market, "get_market", { id: truth }), demand: dem && await view(CFG.market, "get_market", { id: dem }) };
}

function price(m) {
  if (!m) return "not open yet";
  const mk = m.market;
  if (mk.outcome !== null && mk.outcome !== undefined) return `settled ${mk.outcome ? "Yes" : "No"}`;
  return `Yes ${Math.round(+m.yes_price / 10000)} cents, No ${Math.round(+m.no_price / 10000)} cents; ${mk.trades} trades, seeded ${usd(mk.pool)} test USDC`;
}

async function show() {
  try {
    const m = await markets();
    $("u-truth").textContent = price(m.truth);
    $("u-demand").textContent = price(m.demand);
    box.dataset.truth = m.truth ? m.truth.market.id : "";
    box.dataset.demand = m.demand ? m.demand.market.id : "";
    const opened = m.demand ? +m.demand.market.id.split(":").pop() : 0;
    const out = await view(CFG.market, "get_outside", { claim: CFG.claim, from: opened, until: opened + 7 * 86400 });
    $("u-behind").textContent = `${usd(out.total)} of 10.00 test USDC from outside backers (${out.count} times)`;
    const bk = await view(CFG.market, "get_backers", { claim: CFG.claim, from_index: 0, limit: 50 });
    $("u-backers").textContent = bk.length ? bk.map(([t, a, who, own]) => `${who}${own ? " (Knos)" : ""}: ${usd(a)} test USDC, ${new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ")} UTC`).join("; ") : "No one has backed it in Circle USDC yet.";
  } catch (e) { $("u-truth").textContent = $("u-demand").textContent = "NEAR testnet did not answer: " + e.message; }
}

const selector = await setupWalletSelector({ network: "testnet", modules: [setupMyNearWallet(), setupMeteorWallet()] });
const modal = setupModal(selector, { contractId: CFG.token });
async function who() {
  const s = selector.store.getState();
  const a = s.accounts && s.accounts[0];
  $("u-who").textContent = a ? `Signed in as ${a.accountId}` : "";
  $("u-connect").textContent = a ? "Sign out" : "Connect your NEAR testnet wallet";
  document.querySelectorAll("#usdc [data-act]").forEach((b) => { b.disabled = !a; });
  return a;
}
selector.store.observable.subscribe(() => who());
$("u-connect").addEventListener("click", async () => {
  if (await who()) { (await selector.wallet()).signOut(); } else { modal.show(); }
});

// every action is one ft_transfer_call of 1 test USDC to the market, signed in the visitor's own wallet
async function send(msg, what) {
  const said = $("u-said");
  said.textContent = `Asking your wallet to sign: ${what}...`;
  try {
    const w = await selector.wallet();
    const r = await w.signAndSendTransaction({ receiverId: CFG.token, actions: [{ type: "FunctionCall", params: {
      methodName: "ft_transfer_call", args: { receiver_id: CFG.market, amount: "1000000", msg: JSON.stringify(msg) }, gas: "100000000000000", deposit: "1" } }] });
    const tx = r && r.transaction && r.transaction.hash;
    said.replaceChildren(document.createTextNode(`Done on NEAR testnet: ${what}. `), Object.assign(document.createElement("a"), { href: `https://testnet.nearblocks.io/txns/${tx}`, textContent: "The transaction" }));
    show();
  } catch (e) { said.textContent = `Not sent: ${e.message || e}`; }
}
document.querySelectorAll("#usdc [data-act]").forEach((b) => b.addEventListener("click", () => {
  const act = b.dataset.act;
  if (act === "back") return send({ back: { claim: CFG.claim, to: [[CFG.agent, "900000"], [CFG.fee, "100000"]] } }, "1 test USDC behind proving this claim (0.90 to agent A, 0.10 to Knos)");
  const [kind, side] = act.split("-");
  const id = box.dataset[kind];
  if (!id) { $("u-said").textContent = "That market is not open yet."; return; }
  send({ buy: { id, side } }, `bought ${side === "yes" ? "Yes" : "No"} with 1 test USDC`);
}));
who();
show();
