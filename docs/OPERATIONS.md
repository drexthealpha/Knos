# Operations

Whether Knos is working, from the public record. This page is written by `scripts/pages_data.py` from `operations.json`, which is published beside it on the site (`https://drexthealpha.github.io/Knos/operations.json`); nothing here is typed by hand.

No measurement has been made yet: this is the page as it is committed, and the live page on the site replaces it.

## The canary

The canary is the scheduled workflow `canary.yml` of `drexthealpha/Knos`, meant to run every 30 minutes. These are its runs as GitHub lists them.

No runs to show. No canary run has been read: GitHub was not asked, or the canary workflow has not run.

## Answers to outside issues and pull requests

No outside issue or pull request to show. Not measured: GitHub was not asked.

## How these are counted

- **success_rate**: successful runs of the canary over its finished runs (failure, timed out and startup failure are failures; cancelled runs are not counted), with the 95% Wilson interval
- **incident**: a finished canary run that did not succeed, with its run's link
- **response**: from an outside issue or pull request being opened to the first comment of a team member who is not its author, over the newest 200 of the repository
