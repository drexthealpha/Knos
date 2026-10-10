// The verdict card: what web/share.js draws on a 1200 x 630 canvas when a reader downloads the result of a check
// (#check). The size is the one og:image of web/index.html has, so the card posts like the site's own. The colours are
// the dark tokens of web/app.css (--paper --paper-2 --ink --ink-2 --line --accent --ok --bad --warn) and the fonts are
// the site's own, served from web/fonts: nothing is fetched from anywhere else to draw it.
export const CARD = {
  width: 1200,
  height: 630,
  margin: 72,
  colour: { paper: "#07080c", paper2: "#0f1118", ink: "#e9ebef", ink2: "#a0a7b8", line: "#222634", accent: "#93a5ff", ok: "#5fd28f", bad: "#ff8a80", warn: "#e0b354" },
  font: {
    head: '"Bricolage Grotesque", "Geist", system-ui, sans-serif',
    text: '"Geist", system-ui, sans-serif',
    code: '"JetBrains Mono", ui-monospace, monospace',
  },
  // the baseline of each row, from the top
  row: { top: 112, verdict: 200, counts: 478, foot: 572 },   // the claim follows the verdict's last line
  mark: 44,                                    // the mark's height at the top left
  sign: "checked by Knos: the neutral meter",
  host: "drexthealpha.github.io/Knos",
};
