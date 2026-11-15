// When a data file of this site does not load (the network dropped, or the host answered 500 or worse), every page says
// so in one line at the foot of the window, with a button that loads the page again: never a blank page or a stack.
// A file that is not there (404) is not a failure: each page already says what an absent file means (no record, no
// table in this build). Loaded from <head> before web/front.js, so it sees every read the pages make. It changes no
// answer: the response, or the error, goes back to the page as it came.
const failed = new Set();
let box = null;

// the site's own .json file a request names, as a path inside the site ("stats.json", "records/codex.json"), or null
const own = (input) => {
  try {
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url, location.href);
    const home = new URL(".", location.href).pathname;
    return url.origin === location.origin && url.pathname.endsWith(".json") && url.pathname.startsWith(home) ? url.pathname.slice(home.length) : null;
  } catch { return null; }
};

function show() {
  if (!failed.size) { box?.remove(); box = null; return; }
  if (!box) {
    box = document.createElement("div");
    box.className = "k-toasts"; box.id = "k-retry";
    box.setAttribute("role", "status"); box.setAttribute("aria-live", "polite");
    const line = document.createElement("p");
    line.className = "k-toast k-enter"; line.dataset.kind = "bad"; line.style.pointerEvents = "auto";
    const words = document.createElement("span");
    const again = document.createElement("button");
    again.type = "button"; again.textContent = "Reload";
    again.style.cssText = "font:inherit;color:inherit;background:none;border:0;padding:0 0 0 8px;text-decoration:underline;cursor:pointer";
    again.addEventListener("click", () => location.reload());
    line.append(words, again);
    box.append(line);
    document.body.append(box);
  }
  const names = [...failed];
  box.querySelector("span").textContent = names.length === 1 ? `Try again: ${names[0]} did not load.` : `Try again: ${names.length} files did not load.`;
}

const real = globalThis.fetch?.bind(globalThis);
if (real) {
  globalThis.fetch = async (input, init) => {
    const name = own(input);
    let answer;
    try { answer = await real(input, init); } catch (e) {
      if (name && e?.name !== "AbortError") { failed.add(name); show(); }
      throw e;
    }
    if (name && answer.status >= 500) { failed.add(name); show(); }
    else if (name && failed.delete(name)) show();
    return answer;
  };
}
