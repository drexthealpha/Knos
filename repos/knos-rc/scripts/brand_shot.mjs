// The pictures scripts/brand.py cannot draw itself: headless Chromium (the `playwright` package) draws them.
//   node scripts/brand_shot.mjs page <file.html> <width> <height> <out.png>     a page as a PNG of exactly that size
//   node scripts/brand_shot.mjs diff <a.svg> <b.svg> <size> <out prefix>         both drawn <size> px wide in black on white;
//        writes <prefix>-a.png, <prefix>-b.png and <prefix>-diff.png (b, with every pixel that differs clearly in red)
//        and prints { pixels, differ (by more than 64 of 255), worst, edge (pixels of a that are neither black nor white) }
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

async function chromium() {
  let pw;
  try { pw = await import("playwright"); } catch {
    const paths = (process.env.NODE_PATH || "").split(":").filter(Boolean);       // an install outside this tree
    pw = createRequire(import.meta.url)(createRequire(import.meta.url).resolve("playwright", { paths }));
  }
  return (pw.default || pw).chromium.launch();
}

const [mode, ...args] = process.argv.slice(2);
const browser = await chromium();
try {
  if (mode === "page") {
    const [file, width, height, out] = args;
    const page = await browser.newPage({ viewport: { width: Number(width), height: Number(height) }, deviceScaleFactor: 1 });
    await page.route("**/*", (route) => (route.request().url().startsWith("file:") ? route.continue() : route.abort()));
    await page.goto(pathToFileURL(file).href);
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: out });
  } else if (mode === "diff") {
    const [a, b, size, prefix] = args;
    const page = await browser.newPage();
    const uri = (f) => `data:image/svg+xml;base64,${readFileSync(f).toString("base64")}`;
    const got = await page.evaluate(async ({ a, b, size }) => {
      const draw = async (src) => {
        const img = new Image(); img.src = src; await img.decode();
        const c = document.createElement("canvas"); c.width = size; c.height = Math.round(size * img.naturalHeight / img.naturalWidth);
        const g = c.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height); g.drawImage(img, 0, 0, c.width, c.height);
        return c;
      };
      const ca = await draw(a), cb = await draw(b);
      const da = ca.getContext("2d").getImageData(0, 0, ca.width, ca.height).data, gb = cb.getContext("2d"), ib = gb.getImageData(0, 0, cb.width, cb.height);
      let differ = 0, worst = 0, edge = 0;
      for (let i = 0; i < da.length; i += 4) {
        const d = Math.abs(da[i] - ib.data[i]);
        if (da[i] > 8 && da[i] < 247) edge++;
        if (d > worst) worst = d;
        if (d > 64) { differ++; ib.data[i] = 255; ib.data[i + 1] = 0; ib.data[i + 2] = 0; }
      }
      const cd = document.createElement("canvas"); cd.width = cb.width; cd.height = cb.height; cd.getContext("2d").putImageData(ib, 0, 0);
      return { stats: { pixels: da.length / 4, differ, worst, edge }, a: ca.toDataURL(), b: cb.toDataURL(), diff: cd.toDataURL() };
    }, { a: uri(a), b: uri(b), size: Number(size) });
    for (const k of ["a", "b", "diff"]) writeFileSync(`${prefix}-${k}.png`, Buffer.from(got[k].split(",")[1], "base64"));
    console.log(JSON.stringify(got.stats));
  } else { console.error("page or diff"); process.exitCode = 2; }
} finally { await browser.close(); }
