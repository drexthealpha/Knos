// Pay with any wallet: one script tag puts the button on any page.
//   <script src="http://127.0.0.1:8790/pay.js" data-bid="1000"></script>
// The button shows a NEAR Intents 1Click quote for paying the bid in USDC from Base (dry: a quote only, no deposit
// address, nothing spent), then pays the bid on NEAR testnet in test units, which opens a Knos job. The server is
// near/web/serve.py on this machine; it signs the testnet transaction, the page holds no key.
(() => {
  const me = document.currentScript;
  const base = new URL(me.src).origin;
  const bid = Number(me.dataset.bid || 1000);
  const host = document.createElement("div");
  me.after(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `<style>
    :host { all: initial; font: 400 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; color: CanvasText; }
    .box { display: inline-grid; gap: 8px; padding: 14px; border: 1px solid GrayText; border-radius: 14px; max-width: 360px; }
    button { min-height: 44px; padding: 10px 16px; border-radius: 12px; border: 1px solid ButtonBorder; font: 600 14px/1.2 inherit; cursor: pointer; }
    button.go { background: LinkText; color: Canvas; border-color: LinkText; }
    .fine { font-size: 13px; color: GrayText; }
    a { color: LinkText; }
  </style>
  <div class="box" role="group" aria-label="Pay with any wallet">
    <button class="go" type="button" part="button">Pay with any wallet</button>
    <p class="fine" data-out aria-live="polite"></p>
  </div>`;
  const btn = root.querySelector("button"), out = root.querySelector("[data-out]");
  const post = (path, body) => fetch(base + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
    .then((r) => r.json());
  let quoted = null;
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      if (!quoted) {
        out.textContent = "Asking NEAR Intents for a quote.";
        const q = await post("/api/job/quote", { usdc_units: 1000000 });
        if (!q.ok) { out.textContent = `No quote: ${q.why}. Try again.`; return; }
        quoted = q;
        out.textContent = `1 USDC on Base arrives as ${q.quote.amountOutFormatted} USDC on NEAR, in about ${q.quote.timeEstimate} s. A quote only: nothing was spent.`;
        btn.textContent = `Pay ${bid} test units on testnet`;
        return;
      }
      out.textContent = "Paying the bid on NEAR testnet.";
      const p = await post("/api/job/pay", { bid, minutes: 15 });
      out.replaceChildren(p.ok ? `Paid ${bid} test units on testnet, job ${p.id}: ` : `Not paid: ${p.why || "refused"}. `,
        Object.assign(document.createElement("a"), { href: `https://testnet.nearblocks.io/txns/${p.tx}`, textContent: "transaction", target: "_blank", rel: "noopener" }));
      btn.textContent = "Paid";
    } catch (e) {
      out.textContent = `The Knos server did not answer (${base}). Start it with: python near/web/serve.py`;
    } finally {
      btn.disabled = btn.textContent === "Paid";
    }
  });
})();
