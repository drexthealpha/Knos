// First visit -> passkey wallet -> gas -> test USDC -> funded bounty, timed (web/#bounty against devnet). A CDP virtual
// authenticator stands in for the passkey. Serve web/ statically (python -m http.server 8799 -d web), then:
//   PW_DIR=<dir with node_modules/playwright> node tests/playwright/bounty.mjs "http://127.0.0.1:8799/?api=<api>" owner/repo 42 5
// Prints per-step timings and the total; exit 1 on a failed step. Not part of pytest (needs devnet and a browser).
import { createRequire } from "node:module";

const require = createRequire((process.env.PW_DIR || process.cwd()).replace(/\/?$/, "/") + "x.js");
const { chromium } = require("playwright");
const [url = "http://127.0.0.1:8799/", repo = "drexthealpha/Knos", issue = "1", amount = "0"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
const cdp = await page.context().newCDPSession(page);
await cdp.send("WebAuthn.enable");
await cdp.send("WebAuthn.addVirtualAuthenticator", { options: { protocol: "ctap2", transport: "internal",
  hasResidentKey: true, hasUserVerification: true, isUserVerified: true, hasPrf: true } });
page.on("console", (m) => m.type() === "error" && console.error("page:", m.text()));

const t0 = Date.now(), marks = {};
const lap = (k) => { marks[k] = (Date.now() - t0) / 1000; console.log(`${k}: ${marks[k].toFixed(1)} s`); };
const until = (re, ms = 45000) => page.waitForFunction((src) => {
  const s = document.getElementById("bw-status");
  if (s.className.includes("err")) throw new Error(s.textContent);
  return new RegExp(src).test(s.textContent);
}, re.source, { timeout: ms, polling: 200 });
try {
  await page.goto(url.replace(/#.*$/, "") + "#bounty");
  lap("page");
  await page.click("#bw-create"); await until(/Wallet ready, with gas/); lap("wallet+gas");
  await page.click("#bw-usdc"); await until(/Test USDC received/); lap("test USDC");
  await page.fill("#bw-repo", repo); await page.fill("#bw-issue", issue); await page.fill("#bw-amount", amount);
  await page.click("#bw-fund"); await until(/Bounty funded/); lap("bounty funded");
  console.log(`TOTAL first visit -> funded bounty: ${marks["bounty funded"].toFixed(1)} s (target <= 30 s)`);
} catch (e) {
  console.error("FAILED after", ((Date.now() - t0) / 1000).toFixed(1), "s:", e.message.split("\n")[0]);
  console.error("status:", await page.textContent("#bw-status").catch(() => "?"));
  process.exitCode = 1;
}
await browser.close();
