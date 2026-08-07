# RPKI/ROA validation toolset results (item 8)

Captured 2026-08-07. Proves the toolset abstraction (Phase 2's done-criterion:
"a new data source can be added without touching the core loop") with a
second, genuinely independent evidence axis instead of just claiming the
abstraction supports it.

## The diff is the evidence

Per this item's own done-criterion: two new files
(`investigator/rpki.py`, `investigator/analyzers/rpki.py`) and one
`[[toolset]]` block in `toolsets.toml`. Zero changes to `engine.py`,
`cli.py`, `investigator/analyzers/__init__.py`, or the registry machinery —
`register_enabled_analyzers()` already dynamically imports whatever the
manifest lists.

## Design: fetch-once, analyze-offline, same split as `ingest.py`

`investigator/rpki.py` queries RIPE NCC's public `rpki-validation` data API
(no auth, no key) for every distinct `(prefix, origin_asn)` pair actually
observed in an incident's raw announce updates, and caches the result in
`data/rpki_cache.json`. `investigator/analyzers/rpki.py`'s `RPKIAnalyzer`
only ever reads that local cache — no network call happens during
`analyze()`, keeping it a pure, offline, deterministic `Analyzer` like every
other one in this project. An incident with nothing cached produces no
finding: silently incomplete, not a crash or a fabricated result.

```bash
python -m investigator.rpki fetch-all   # populate the cache once
investigate pakistan-youtube-2008        # RPKIAnalyzer reads the cache, offline
```

## The historical-accuracy caveat — verified as a real problem, not a hypothetical one

RIPEstat's API returns **today's** RPKI state. RPKI itself didn't exist
before ~2011, and the incident catalog goes back to 2008. Checked directly,
not assumed: neither of `pakistan-youtube-2008`'s two 2008 contenders
(AS17557, AS36561) is today's valid origin for `208.65.153.0/24` — that's
AS36040 now. Current ROA state doesn't settle who was right in 2008; it's
carried as an explicit caveat in every finding's text, not just this doc.

**A second, subtler version of the same caveat, found while fetching the
real catalog:** `google-japan-leak-2017`'s prefix comes back `invalid_asn`
for Google's own AS15169. This is a **route leak**, not a hijack — Google
legitimately originated this prefix the whole time; the mismatch is almost
certainly ROA registration drift over the intervening years (Google's IP
space and ASN usage has been reorganized repeatedly since 2017), not
evidence anyone hijacked anything. `RPKIViolation` is deliberately **not**
mapped to the `route_leak` label in `evaluate.py` for exactly this reason —
an unauthorized-origin finding says nothing about a propagation-scope
violation, which is what a route leak actually is — but the raw finding
itself would read as alarming out of context. Flagged here so nobody
mistakes an `invalid_asn` finding for an automatic hijack confirmation.

## Real-catalog measurement: detection accuracy improved

```bash
python -m investigator.rpki fetch-all
python -m investigator.evaluate
```

| | Before (MOAS/WithdrawalStorm/ASPathLoop/RouteLeak only) | After (+ RPKIViolation) |
|---|---|---|
| Detection accuracy | 4/13 | **5/13** |

`amazon-route53-mew-2018` (the real MyEtherWallet DNS-hijack-via-BGP
incident, AS10297) flips from `MISS` to `HIT`. This is genuinely new
detection power, not a heuristic paraphrase of MOAS: the captured window
apparently didn't include simultaneous announcements from Amazon's own
origin ASN (MOAS needs *both* the legitimate and anomalous origin visible
to fire), but RPKI only needs the anomalous one — AS10297 has no ROA
authorizing any of the five `205.251.19x.0/24` prefixes it announced,
full stop, independent of what else was or wasn't captured. All five
prefixes come back `invalid_asn` cleanly, no ambiguity.

## Real-catalog measurement: ACH false-assertion rate — unchanged, and why that's itself a finding

```bash
python -m investigator.evaluate --ach
```

3 correct / 1 false / 9 abstained — identical to the numbers without RPKI
enabled (item 4b's baseline). `RPKIViolation` findings *do* get fired and
*do* get turned into ACH hypotheses (`hypotheses_from_results` treats any
fired `Result` uniformly, regardless of kind), but they don't flip any
verdict. Diagnosed, not left as a flat number:

- `amazon-route53-mew-2018` and `google-japan-leak-2017` both go from
  `ABSTAIN (no analyzer findings fired)` to `ABSTAIN (even the leading
  hypothesis has more refuting than topically-relevant evidence)` — a more
  informative abstention (RPKI evidence is now being weighed), but still an
  abstention, because `rank_hypotheses()` runs `RPKIViolation`'s claim
  through the **same RFC-citation entailment check** every other
  hypothesis goes through. RFC prose can discuss RPKI/ROA *conceptually*
  ("validate against RPKI Route Origin Authorizations") but essentially
  never strictly entails a specific claim like "AS10297 announced
  205.251.192.0/24 without ROA authorization" — the same structural
  mismatch Phase 5's original 100%-abstention finding diagnosed for
  RFC-prose-vs-analyzer-claims generally, now visible for a *different*
  kind of evidence too.

**This is the honest, non-obvious finding of this item, not a footnote.**
An RPKI/ROA violation is *self-certifying* — a cryptographically-verified
ROA either does or doesn't authorize an origin, and doesn't need RFC prose
to corroborate it the way "is this a MOAS" benefits from RFC 7908's
definition. The current architecture doesn't yet give RPKI evidence that
independent weight; it routes it through the same gate as everything else.
A real follow-up (not attempted here, would be scope creep beyond this
item's done-criterion): let `RPKIViolation` hypotheses count as
strict-tier support on their own terms, without requiring RFC-citation
entailment, since the "citation" in this case is the ROA record itself,
not an RFC clause.

## What this proves and doesn't

**Proven:** the toolset abstraction genuinely supports a second data
source with a minimal diff, and that source produces a real, measured
detection-accuracy improvement (4/13 → 5/13) using a data source
completely independent of RFC prose, per this item's own goal.

**Not proven, and not attempted:** that RPKI evidence integrates cleanly
into ACH's assert/abstain reasoning. It doesn't yet, for a real,
diagnosed, architectural reason, not a bug — flagged for future work
rather than silently worked around.
