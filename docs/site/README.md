# The product site

`docs/site/index.html` is the product demonstration page. It is one static
HTML file with its CSS and JavaScript inline: no build step, no framework,
no dependency beyond one Google Font, and no backend anywhere.

It sits beside the evidence page rather than replacing it:

| | URL once deployed | What it is for |
|---|---|---|
| `docs/index.html` | `drexthealpha.github.io/Knos/` | A page *about* the product: every number, read live from JSON |
| `docs/site/index.html` | `drexthealpha.github.io/Knos/site/` | The product itself, for somebody who has sixty seconds |

Both are served by the GitHub Pages workflow that already publishes `docs/`.
Nothing about deployment changes: commit the file and the page is live at
`/site/` on the next Pages build. There is no step two.

## What it shows, and where each claim comes from

The page makes no claim the repository does not already make, and it does not
hold a copy of any figure.

- **The terminal replay** in the hero is a transcript. Every line is text that
  `knos demo`, the MCP server, the guard hook or the bot actually prints; the
  strings are the ones in `src/knos/demo.py`, `src/knos/answer.py` and
  `src/knos/guard.py`. It is played back on the page so the site needs no
  server - the caption under it says so, and says there is no hosted Knos.
- **The proof cards** are fetched from `../evidence/*.json` at load, the same
  files the evidence page reads and the same files the daily
  `evidence.yml` workflow regenerates on a clean machine. If a figure changes
  in the JSON, it changes here. If a file cannot be read, the card says so
  rather than showing a stale number.
- **The one hand-typed figure** is `12 of 12` receipts, which is the length of
  `RECEIPTS` in `src/knos/receipts.py` plus the live-gate row - the same count
  `knos receipts` prints.
- **The demo video** linked from the hero, the replay caption and the footer is
  the one public recording: https://x.com/getknos/status/2098167698119102596
- **The install commands** are copied from the README, not paraphrased.
- **The honest part** stays on the page: no retained users, a live money run of
  thirty rounds and cents, and a link to `docs/PMF.md` including the 34 pull
  requests that were the wrong idea.

## The share image

`og.png` is the 1200x630 card that X, Slack, Discord and the rest show when
the URL is pasted. It is drawn by `og.py` from the same palette and copy as
the page - no design tool, no external service. To change it, edit the
strings in `og.py` and run:

```bash
python docs/site/og.py
```

The `og:image` and `twitter:image` tags in `index.html` point at the absolute
URL, because crawlers do not resolve relative paths.

## Design decisions

- **Palette and type tokens are the evidence page's**, so the two pages read
  as one site. JetBrains Mono is added for headings and the terminal; body
  copy stays in a system sans, because paragraphs of monospace on a marketing
  page cost more in readability than they buy in mood.
- **Light and dark** both work via `prefers-color-scheme`. Contrast was checked
  against WCAG AA in both.
- **Motion respects `prefers-reduced-motion`**: the replay renders fully and
  instantly instead of line by line.
- **Touch targets** are 44 px or larger for every button and nav item.
- **No emoji as icons.** The three cards and the copy button use inline SVG.
- **No horizontal scroll** at 375, 768, 1024 or 1440 px; code blocks scroll
  inside their own box.

## Checking it locally

Any static server that serves `docs/` at the root will do, because the page
reaches its data at `../evidence/`:

```bash
python -m http.server 8731 --directory docs
# then open http://localhost:8731/site/
```

Opening the file directly (`file://`) shows the layout but the proof cards
will read "could not read evidence/…json" - browsers block `fetch` from
`file://`. That is the page behaving as designed, not a bug.

## Changing it

It is one file. There is no generator to re-run. Keep three things true when
editing:

1. Do not type a number into the HTML that lives in `docs/evidence/`. Read it.
2. Do not add a claim the README does not make.
3. Do not add a backend. The read path of the product opens no socket, and the
   page that sells it should not either.
