<img src="../web/brand/mark.svg" height="40" alt="Knos">

# Search engines and shared links

What a search engine reads of the site, what the site does not do, and what only the founder can do.
Search engines and link previews read files; nothing here runs a tracker or asks another site for anything.

## What the site gives a search engine

- **Four pages.** The first screen, [the questions](../web/faq.html), [the ten-second check](../web/check/index.html)
  and privacy. Each has its own title, description and address. The app's other pages are `#` addresses, which a
  search engine reads as one page.
- **A sitemap** (a list of pages for search engines): [web/sitemap.xml](../web/sitemap.xml). Each date is the build's.
  A sitemap at `/Knos/` may list only addresses under `/Knos/` ([sitemaps.org](https://www.sitemaps.org/protocol.html)).
- **A plain-text summary of the site:** [web/llms.txt](../web/llms.txt), in the shape [llmstxt.org](https://llmstxt.org/) proposes.
- **Facts in JSON-LD** (a block of facts a search engine reads): the app on the first screen, the questions on theirs.
- **"Last updated"** on each new page: the date of the commit the site is built from. Nobody types it.

[tests/test_seo.py](../tests/test_seo.py) and [tests/web/seo.mjs](../tests/web/seo.mjs) hold all of this.

## What the site does not do, and why

- **No robots.txt.** Google reads one only at the root of a host
  ([Google](https://developers.google.com/crawling/docs/robots-txt/create-robots-txt)). This site lives at
  `drexthealpha.github.io/Knos/`, so only a site at `drexthealpha.github.io` could serve one. Nothing blocks a
  crawler today. Only the page for a missing address asks not to be listed.
- **No star rating.** Google shows an app's rich result only with a rating or a review
  ([Google](https://developers.google.com/search/docs/appearance/structured-data/software-app)). None exists, so none is
  claimed.
- **No FAQ rich result.** Google stopped showing them in 2026
  ([Google](https://developers.google.com/search/docs/appearance/structured-data/faqpage)). The FAQPage stays: the
  same answers are on the page.
- **The share card stays PNG.** It is 37 KB. In one test of 11 sites, all showed WebP cards and only 4 showed AVIF
  ([Joost de Valk, December 2024](https://joost.blog/use-avif-webp-share-images/)). PNG shows everywhere, and a
  smaller file would save little.

## What only the founder can do

1. In [Google Search Console](https://search.google.com/search-console), add the address
   `https://drexthealpha.github.io/Knos/`. Prove you own it with the HTML tag or file Google gives
   ([Google's steps](https://support.google.com/webmasters/answer/9008080)). Then submit `sitemap.xml`.
2. Share the link on X, LinkedIn and Reddit.
