// #apps: the Knos app for research products (apps/wanted, hosted at knos.onrender.com), added by name in web/views.js.
// The app runs on a free instance that sleeps. Nothing is asked of it until the link is pressed (this site asks no
// host but GitHub and Solana on its own); then, if the app answers within a moment, the press goes straight to it, and
// otherwise to the wake page (wanted.html), which waits for it and forwards.
const APP = "https://knos.onrender.com/app/";

export function renderApps(el) {
  el.innerHTML = `<h2>Back proven research products</h2>
    <p>The earlier demand check, on the Knos app.</p>
    <div class="actions"><a class="k-btn" id="apps-go" href="wanted.html">Open the app →</a></div>
    <p class="devnet">Solana devnet test money: worth nothing.</p>`;
  const go = el.querySelector("#apps-go");
  go.addEventListener("click", (ev) => {
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;      // a new tab keeps the wake page
    ev.preventDefault();
    go.textContent = "Opening…";
    const late = new Promise((res) => setTimeout(() => res(false), 2000));
    const ping = fetch(APP + "healthz", { mode: "no-cors", cache: "no-store" }).then(() => true, () => false);
    Promise.race([ping, late]).then((awake) => { location.href = awake ? APP : "wanted.html"; });
  });
}
