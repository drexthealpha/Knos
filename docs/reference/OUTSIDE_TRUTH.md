<img src="../../web/brand/mark.svg" height="40" alt="Knos">

# Outside truth: open signals against 200 past SBIR awards

**In plain words.** We asked Knos's open-signals check about 200 past research awards whose outcome is known. It did no better than a coin: 47.5% right, where always guessing one side gets 50%. We publish it as measured.

| Measure | Value |
|---|---|
| Awards | 200: 100 commercialized, 100 not |
| Accuracy | 47.5% (base rate 50%) |
| Precision / recall | 47.1% / 40.0% |
| p, binomial vs base rate | 0.78 |
| p, Fisher's exact | 0.57 |

- **Population:** Defense Department SBIR/STTR Phase I awards, 2005 to 2014, with an abstract on sbir.gov.
- **Commercialized:** a granted US patent linked to the award's contract (Zenodo, 10.5281/zenodo.17018422). **Not:** no patent and no Phase II on the same topic.
- **What Knos saw:** one phrase, the award's title or the abstract's first sentence. OPEN counts as a prediction of commercialized.
- **Why it can fail:** open signals measure public attention today, not whether a 2010 defense prototype was patented. A patent is invention, not sales.
- **Since:** the refuse list now applies to demand checks, so ideas naming weapons would be refused, not scored.

Numbers, method and sources: [outside_truth.json](outside_truth.json). Run it again: `python scripts/outside_truth.py <sample.json> --public` (the sample is built from the two public datasets above).

## Errata in the frozen plans

What the frozen plans get wrong is said here.

- [evidence_plan.md](evidence_plan.md) says the 20 tasks of `bench/idt/tasks.json` are 12 code tasks and 8 brief tasks;
  the file, unchanged since 20 Oct 2026, holds 10 of each.
- [evidence_plan.md](evidence_plan.md), section 4, names the store of the Knos record by the memory library it uses; it
  is the Knos record kept in a local store.
