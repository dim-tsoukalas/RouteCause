# Baseline: detection + ACH harness against the 2-RFC corpus

Captured 2026-08-06, immediately before the RFC corpus expansion
([alignment-plan.md](alignment-plan.md) item 4). This is the "before" half of
that item's before/after delta — captured now because it can't be
reconstructed after the corpus changes.

Corpus at capture time: `data/rfcs/` — 2 hand-picked excerpts, 3,526 chars
total.

- `rfc4271_bgp4_excerpt.txt` — 1,902 chars, 34 lines
- `rfc7908_route_leaks_excerpt.txt` — 1,624 chars, 27 lines

## Detection accuracy

```bash
python -m investigator.evaluate
```

| Incident | Expected | Detected | Verdict |
|---|---|---|---|
| cloudflare-verizon-2019 | route_leak | ASPathLoop, WithdrawalStorm | MISS |
| pakistan-youtube-2008 | prefix_hijack | ASPathLoop, MOAS, RouteLeak | HIT |
| amazon-route53-mew-2018 | prefix_hijack | WithdrawalStorm | MISS |
| twitter-rtcomm-2022 | prefix_hijack | ASPathLoop | MISS |
| indosat-2014 | prefix_hijack | ASPathLoop, MOAS, WithdrawalStorm | HIT |
| celer-cbridge-aws-2022 | prefix_hijack | (none) | MISS |
| klayswap-2022 | prefix_hijack | ASPathLoop, WithdrawalStorm | MISS |
| rostelecom-2020 | prefix_hijack | ASPathLoop, RouteLeak, WithdrawalStorm | MISS |
| mainone-google-2018 | route_leak | (none) | MISS |
| telekom-malaysia-2015 | route_leak | (none) | MISS |
| google-japan-leak-2017 | route_leak | (none) | MISS |
| china-telecom-18min-2010 | prefix_hijack | ASPathLoop, MOAS, RouteLeak | HIT |
| level3-comcast-2017 | route_leak | ASPathLoop, RouteLeak, WithdrawalStorm | HIT |

**4/13 correct.** This number is orthogonal to the corpus — it's the
deterministic analyzers matching the catalog's expected label, no RFC text or
LLM involved. Expect it to be unchanged by the corpus expansion; it's
recorded here only so an unexpected change in *this* number after 4b would be
a signal something else broke, not the corpus doing its job.

## ACH (competing-hypothesis) false-assertion rate

```bash
python -m investigator.evaluate --ach
```

| Incident | Expected | ACH Verdict | Outcome |
|---|---|---|---|
| cloudflare-verizon-2019 | route_leak | ABSTAIN (no hypothesis found any genuine supporting evidence in the corpus) | abstained |
| pakistan-youtube-2008 | prefix_hijack | [MOAS] | correct |
| amazon-route53-mew-2018 | prefix_hijack | ABSTAIN (no hypothesis found any genuine supporting evidence in the corpus) | abstained |
| twitter-rtcomm-2022 | prefix_hijack | ABSTAIN (no hypothesis found any genuine supporting evidence in the corpus) | abstained |
| indosat-2014 | prefix_hijack | [MOAS] | correct |
| celer-cbridge-aws-2022 | prefix_hijack | ABSTAIN (no analyzer findings fired) | abstained |
| klayswap-2022 | prefix_hijack | ABSTAIN (no hypothesis found any genuine supporting evidence in the corpus) | abstained |
| rostelecom-2020 | prefix_hijack | ABSTAIN (no hypothesis found any genuine supporting evidence in the corpus) | abstained |
| mainone-google-2018 | route_leak | ABSTAIN (no analyzer findings fired) | abstained |
| telekom-malaysia-2015 | route_leak | ABSTAIN (no analyzer findings fired) | abstained |
| google-japan-leak-2017 | route_leak | ABSTAIN (no analyzer findings fired) | abstained |
| china-telecom-18min-2010 | prefix_hijack | [MOAS] | correct |
| level3-comcast-2017 | route_leak | ABSTAIN (no hypothesis found any genuine supporting evidence in the corpus) | abstained |

**false-assertion rate: 0/3 (0%), 3 correct assertion(s), 10 abstained.**

This is the number the corpus expansion is actually meant to move. 4 of the
10 abstentions are `ABSTAIN (no analyzer findings fired)`
(`celer-cbridge-aws-2022`, `mainone-google-2018`, `telekom-malaysia-2015`,
`google-japan-leak-2017`) — no RFC corpus can fix those, the deterministic
layer never fired on that incident's raw MRT data in the first place. The
remaining 6 are
`ABSTAIN (no hypothesis found any genuine supporting evidence in the corpus)`
(`cloudflare-verizon-2019`, `amazon-route53-mew-2018`, `twitter-rtcomm-2022`,
`klayswap-2022`, `rostelecom-2020`, `level3-comcast-2017`) — a real analyzer
finding with nothing in the 2-file corpus topically close enough to clear
even the relevance tier. Those 6 are the ones worth re-checking after the
corpus expansion; a flip from abstain to correct on any of them is the real
signal, not the raw count.

## How to compare after item 4b

Re-run both commands with the exact same catalog and command line, diff
against the tables above. Report, per the plan's own instruction, whichever
way it goes — the honest outcome (more abstentions convert, or they don't
and that's informative about whether RFC prose was ever going to be specific
enough) is the deliverable, not a target number.
