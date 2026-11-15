# Sharing a check

The check on the site (`#check`) reads a public pull request from GitHub in your browser and says whether its
description's "tests pass" meets the checks at its head commit. Its result can be shared four ways (web/share.js).
Nothing is posted, sent or stored by the site: each way is a thing the reader does.

| Way | What it is |
| --- | --- |
| The link | `https://drexthealpha.github.io/Knos/#check=owner/repo/123`. Opening it checks the pull request again, from GitHub as it is then; the address bar holds it as soon as a result is shown. |
| Copy the result | The verdict, the sentence that claimed the tests pass, the failed checks by class, and the link, as text. |
| Post on X | Opens X's own compose box ([web intent](https://docs.x.com/x-for-websites/post-button/guides/web-intent)) with those words and the link, within X's 280 characters. The reader posts it, or not. |
| Download the card | A 1200 x 630 PNG drawn in the browser from web/brand/card.js: the pull request, the verdict, the claim, the counts and "checked by Knos: the neutral meter". |

**Link previews show the site's card, not the verdict.** X, Slack and other sites draw a preview from a page's
`og:image` without running its script, and the part after `#` never reaches a server, so every shared link previews as
`brand/card.png`. Attach the downloaded card to show the verdict itself.

## A badge for a repository

`brand/checked.svg` is a static file of the site ("agent PR claims | checked by Knos"); no server draws it and it
counts nothing. Its Markdown links to `#check=owner/repo`, the check for that repository's pull requests:

```markdown
[![agent PR claims checked by Knos](https://drexthealpha.github.io/Knos/brand/checked.svg)](https://drexthealpha.github.io/Knos/#check=owner/repo)
```

The site offers it only for a repository that merged a pull request in the last 30 days: one read of GitHub's public
API (no token; 60 reads an hour per address), at most one, made only when the reader opens "Badge for owner/repo".
