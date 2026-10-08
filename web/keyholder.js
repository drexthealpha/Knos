// Hold a key: how someone outside Knos becomes a member of the multisig that approves program upgrades.
//
//   renderKeyholder(el[, ctx])    the page: how many outside key holders there are today (keyholders.json, beside this
//                                 file), what a key can and cannot do, and three steps: make a key, keep its file, ask
//   makeKey(subtle)               a new Ed25519 keypair from the browser's own WebCrypto: { address, file }. `address` is
//                                 the public key as Solana prints it; `file` is the 64 numbers of a Solana keypair file
//                                 (what `solana-keygen new` writes, and what scripts/governance.mjs --member reads)
//   canMakeKey(subtle)            whether this browser can: Ed25519 in WebCrypto is in Chrome and Edge 137, Firefox 129 and
//                                 Safari 17 and later (https://caniuse.com/mdn-api_subtlecrypto_generatekey_ed25519)
//   issueUrl(repo, request)       the "Key holder request" issue, filled in: public key, name or handle, how to reach them
//   base58(bytes)                 Bitcoin's alphabet, as Solana writes an address
//
// The key is made in this page and goes nowhere: no request carries it, nothing is stored, and the page forgets the
// private half once the file has been saved. The only request the page makes is for keyholders.json, to this site. The
// issue carries the PUBLIC key and what the person typed, and is opened by the person, on GitHub, in a new tab.
// docs/KEYHOLDER.md is this page at length; docs/GOVERNANCE.md says what the multisig is today.
export const REPO = "drexthealpha/Knos";
export const ISSUE_TITLE = "Key holder request";
export const KEY_FILE = "knos-member.json";
export const COMMAND = `solana-keygen new --outfile ${KEY_FILE}\nsolana-keygen pubkey ${KEY_FILE}`;
export const NEEDS = "Chrome or Edge 137, Firefox 129, Safari 17, or later";
const DOCS = `https://github.com/${REPO}/blob/main/docs`;
const ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export function base58(bytes) {
  let n = 0n, out = "";
  for (const b of bytes) n = (n << 8n) | BigInt(b);
  for (; n > 0n; n /= 58n) out = ALPHABET[Number(n % 58n)] + out;
  for (const b of bytes) { if (b !== 0) break; out = "1" + out; }
  return out;
}

/** Whether this WebCrypto makes Ed25519 keys. Asked by making one: there is no other way to know. */
export async function canMakeKey(subtle = globalThis.crypto?.subtle) {
  if (!subtle) return false;
  try { await subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]); return true; } catch { return false; }
}

/** A new keypair. The private half leaves WebCrypto once, as PKCS#8, whose last 32 bytes are the Ed25519 seed (RFC 8410). */
export async function makeKey(subtle = globalThis.crypto?.subtle) {
  if (!subtle) throw new Error("no WebCrypto");
  const pair = await subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const pkcs8 = new Uint8Array(await subtle.exportKey("pkcs8", pair.privateKey)), pub = new Uint8Array(await subtle.exportKey("raw", pair.publicKey));
  if (pkcs8.length !== 48 || pub.length !== 32) throw new Error("not an Ed25519 key as RFC 8410 writes it");
  const file = [...pkcs8.subarray(16), ...pub];
  pkcs8.fill(0);
  return { address: base58(pub), file };
}

/** An address as Solana prints one: 32 bytes in base58. Only its shape is checked here. */
export const looksLikeAddress = (text) => /^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(text);

export function issueBody({ address = "", name = "", reach = "" } = {}) {
  return ["Public key (never the private key or its file):", address, "", "Name or handle:", name, "", "How to reach me:", reach, "",
          "I made this key on my own machine. Nobody else has its file."].join("\n");
}

export function issueUrl(repo = REPO, request = {}) {
  const q = new URLSearchParams({ template: "key_holder.md", title: ISSUE_TITLE, labels: "key-holder", body: issueBody(request) });
  return `https://github.com/${repo}/issues/new?${q}`;
}

const STYLE = `
.kh { display: grid; gap: 16px; }
.kh h2, .kh h3 { margin: 0; }
.kh ul { margin: 0; padding-left: 20px; }
.kh .kh-two { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 260px), 1fr)); }
.kh pre, .kh code { overflow-wrap: anywhere; white-space: pre-wrap; }
.kh pre { margin: 6px 0; padding: 10px 12px; border: 1px solid var(--line); border-radius: var(--radius); background: var(--paper-2); }
.kh .kh-key { font: 600 15px/1.4 var(--mono, ui-monospace, monospace); overflow-wrap: anywhere; }
.kh label { display: grid; gap: 4px; margin: 8px 0; }
.kh input { max-width: 100%; min-width: 0; }
.kh .kh-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
.kh ol { margin: 0; padding: 0; }
`;

export function renderKeyholder(el, ctx = {}) {
  const doc = el.ownerDocument, esc = ctx.esc || escHtml, repo = ctx.repo || REPO, subtle = ctx.subtle ?? globalThis.crypto?.subtle;
  const fetchFn = ctx.fetch || ((...a) => globalThis.fetch(...a));
  if (!doc.getElementById("keyholder-style")) { const s = doc.createElement("style"); s.id = "keyholder-style"; s.textContent = STYLE; doc.head.appendChild(s); }
  el.innerHTML = `<section class="kh k-card">
    <p class="k-kicker" data-kh="count">Outside key holders today: reading…</p>
    <h2>Hold a key</h2>
    <p>Vote on a program upgrade. Check its build first.</p>
    <details class="k-more"><summary>What your key can and cannot do</summary>
    <div class="kh-two">
      <div><h3>Your key can</h3><ul>
        <li>Cast one vote on a program upgrade.</li>
        <li>Vote to cancel an upgrade during its 48 hours.</li>
        <li>Compare the proposed build with your own build.</li>
      </ul></div>
      <div><h3>Your key cannot</h3><ul>
        <li>Move an order's money. No instruction takes your key.</li>
        <li>Change an order's terms. The program has no such instruction.</li>
        <li>Block a refund. A refund needs no key.</li>
        <li>Approve an upgrade alone. Two votes are needed.</li>
        <li>Block an upgrade alone. The founder holds two keys.</li>
      </ul></div>
    </div>
    <p class="fine">Pay nothing: this is devnet. Check four things per upgrade.
      <a href="${esc(`${DOCS}/KEYHOLDER.md`)}" target="_blank" rel="noopener">Read the page</a></p></details>
    <ol>
      <li class="k-step" data-kh="s1" data-state="live"><h3>Make a key</h3>
        <p class="kh-row"><button type="button" class="k-btn" data-kh="make">Make a key here</button></p>
        <p class="fine" data-kh="how">Stays in this page. Sends nothing.</p>
        <details class="k-more"><summary>Use a command instead</summary><pre>${esc(COMMAND)}</pre>
          <label>Paste the public key it prints<input type="text" data-kh="paste" spellcheck="false" autocomplete="off"></label></details>
        <p data-kh="said" role="status" aria-live="polite"></p></li>
      <li class="k-step" data-kh="s2" data-state="idle"><h3>Keep the private key file</h3>
        <p class="kh-key" data-kh="address"></p>
        <p class="kh-row"><button type="button" class="k-btn" data-kh="save" disabled>Save ${esc(KEY_FILE)}</button></p>
        <p class="fine">Show it to nobody.</p></li>
      <li class="k-step" data-kh="s3" data-state="idle"><h3>Ask to join</h3>
        <label>Name or handle<input type="text" data-kh="name" autocomplete="off"></label>
        <label>How to reach you<input type="text" data-kh="reach" autocomplete="off"></label>
        <p class="kh-row"><a class="k-btn" data-kh="ask" aria-disabled="true" target="_blank" rel="noopener">Open the request</a></p>
        <p class="fine">Opens a public issue on GitHub. Carries the public key only.</p></li>
    </ol>
  </section>`;
  const $ = (name) => el.querySelector(`[data-kh="${name}"]`);
  let key = null, address = "";
  const state = (n, s) => $(n).setAttribute("data-state", s);
  const draw = () => {
    $("address").textContent = address ? `Public key: ${address}` : "";
    $("save").disabled = !key;
    const ask = $("ask");
    if (address) { ask.href = issueUrl(repo, { address, name: $("name").value.trim(), reach: $("reach").value.trim() }); ask.removeAttribute("aria-disabled"); }
    else { ask.removeAttribute("href"); ask.setAttribute("aria-disabled", "true"); }
    state("s1", address ? "done" : "live");
    state("s2", !address ? "idle" : key ? "live" : "done");
    state("s3", address && !key ? "live" : "idle");
  };
  $("make").addEventListener("click", async () => {
    $("said").textContent = "Making the key…";
    try {
      const made = await makeKey(subtle);
      key = made.file; address = made.address;
      $("said").textContent = "Made. Save the file next.";
    } catch {
      key = null;
      state("s1", "bad");
      $("said").textContent = "This browser cannot make the key. Use the command below.";
      $("how").textContent = `Needs ${NEEDS}.`;
      el.querySelector('[data-kh="s1"] details.k-more').open = true;
      return;
    }
    draw();
  });
  $("save").addEventListener("click", () => {
    if (!key) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(key)], { type: "application/json" })), a = doc.createElement("a");
    a.href = url; a.download = KEY_FILE; doc.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    key.fill(0); key = null;                    // the page keeps the public key and forgets the private one
    $("said").textContent = "Saved. This page has forgotten the private key.";
    draw();
  });
  $("paste").addEventListener("input", () => {
    const text = $("paste").value.trim();
    key = null; address = looksLikeAddress(text) ? text : "";
    $("said").textContent = !text ? "" : address ? "Read. Ask to join next." : "Paste the public key: 32 to 44 letters and digits.";
    draw();
  });
  for (const n of ["name", "reach"]) $(n).addEventListener("input", draw);
  $("ask").addEventListener("click", (e) => { if (!address) e.preventDefault(); });
  draw();
  // how many there are today, from the file the build publishes; said as unread when it cannot be read
  const counted = ctx.holders ? Promise.resolve(ctx.holders) : Promise.resolve().then(() => fetchFn("keyholders.json", { cache: "no-cache" })).then((r) => (r.ok ? r.json() : null));
  return counted.then((h) => { $("count").textContent = Array.isArray(h?.outside) ? `Outside key holders today: ${h.outside.length}` : "Outside key holders today: not read"; },
                      () => { $("count").textContent = "Outside key holders today: not read"; });
}
