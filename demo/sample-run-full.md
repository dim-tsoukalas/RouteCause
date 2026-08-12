# Investigation: pakistan-youtube-2008
_Question: Using the reference corpus, explain why a prefix (208.65.153.0/24) being announced by two distinct origin ASNs (AS17557 and AS36561) is treated as a strong indicator of a hijack or misconfiguration, and what validation step is recommended._

## Observations (computed from evidence)
### [CRITICAL] MOAS — 208.65.153.0/24
- Prefix 208.65.153.0/24 was announced by 2 distinct origin ASNs (AS17557, AS36561). Expected a single origin; presumed legitimate origin is AS17557. _(ground in: BGP origin AS semantics and prefix hijack (MOAS))_
- Anomalous origin AS36561 advertised 208.65.153.0/24 (59 announcement(s)). _(ground in: unauthorized origination / route hijack)_
  - Evidence:
    - `rrc00@2008-02-24T20:07:25Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[3549 36561] peer=AS3549`
    - `route-views2@2008-02-24T20:07:25Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[3549 36561] peer=AS3549`
    - `route-views2@2008-02-24T20:07:25Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[3561 3549 36561] peer=AS3561`
    - `rrc00@2008-02-24T20:07:26Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[7018 3549 36561] peer=AS7018`
    - `route-views2@2008-02-24T20:07:26Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[7018 3549 36561] peer=AS7018`
    - `route-views2@2008-02-24T20:07:26Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[3549 36561] peer=AS3549`
    - `rrc00@2008-02-24T20:07:27Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[16186 21318 21318 3549 36561] peer=AS16186`
    - `route-views2@2008-02-24T20:07:29Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[3130 1239 3549 36561] peer=AS3130`
    - …and 51 more

### [WARNING] ASPathLoop — 208.65.153.0/24
- AS_PATH [1299, 3491, 3491, 17557] for 208.65.153.0/24 repeats: AS3491×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [34225, 1299, 3491, 3491, 17557] for 208.65.153.0/24 repeats: AS3491×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [16186, 21318, 21318, 3549, 3491, 17557] for 208.65.153.0/24 repeats: AS21318×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [16186, 21318, 21318, 3549, 36561] for 208.65.153.0/24 repeats: AS21318×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [7660, 2516, 3491, 17557, 17557] for 208.65.153.0/24 repeats: AS17557×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [3741, 3491, 17557, 17557] for 208.65.153.0/24 repeats: AS17557×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [13237, 3491, 17557, 17557] for 208.65.153.0/24 repeats: AS17557×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [34225, 41692, 3491, 17557, 17557] for 208.65.153.0/24 repeats: AS17557×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [5413, 3491, 17557, 17557] for 208.65.153.0/24 repeats: AS17557×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
- AS_PATH [6881, 29208, 3491, 17557, 17557] for 208.65.153.0/24 repeats: AS17557×2. RFC 4271 §9.1.2 mandates loop detection on the local AS number. _(ground in: RFC 4271 AS_PATH loop detection)_
  - Evidence:
    - `route-views2@2008-02-24T18:48:08Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[1299 3491 3491 17557] peer=AS1299`
    - `rrc00@2008-02-24T18:48:09Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[34225 1299 3491 3491 17557] peer=AS34225`
    - `rrc00@2008-02-24T18:48:27Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[16186 21318 21318 3549 3491 17557] peer=AS16186`
    - `rrc00@2008-02-24T20:07:27Z ANNOUNCE 208.65.153.0/24 origin=AS36561 path=[16186 21318 21318 3549 36561] peer=AS16186`
    - `route-views2@2008-02-24T20:51:50Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[7660 2516 3491 17557 17557] peer=AS7660`
    - `rrc00@2008-02-24T20:52:34Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[3741 3491 17557 17557] peer=AS3741`
    - `route-views2@2008-02-24T20:52:36Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[13237 3491 17557 17557] peer=AS13237`
    - `rrc00@2008-02-24T20:52:38Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[34225 41692 3491 17557 17557] peer=AS34225`
    - …and 2 more

### [WARNING] RouteLeak — 208.65.153.0/24
- AS17557 newly appears as a transit hop for 208.65.153.0/24 across 6 distinct peer(s) partway through the observed window, with the origin AS unchanged -- consistent with a route leak (RFC 7908) rather than a hijack. _(ground in: RFC 7908 route leak definition (scope violation, not origin change))_
  - Evidence:
    - `route-views2@2008-02-24T20:51:50Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[7660 2516 3491 17557 17557] peer=AS7660`
    - `rrc00@2008-02-24T20:52:34Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[3741 3491 17557 17557] peer=AS3741`
    - `route-views2@2008-02-24T20:52:36Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[13237 3491 17557 17557] peer=AS13237`
    - `rrc00@2008-02-24T20:52:38Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[34225 41692 3491 17557 17557] peer=AS34225`
    - `route-views2@2008-02-24T20:52:59Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[5413 3491 17557 17557] peer=AS5413`
    - `rrc00@2008-02-24T20:54:22Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[6881 29208 3491 17557 17557] peer=AS6881`

### [CRITICAL] RPKIViolation — 208.65.153.0/24
- AS17557 announced 208.65.153.0/24, but current RPKI ROA data does not authorize that origin for this prefix (validity: invalid_asn, 4 covering ROA(s) found for a different origin). Reflects today's RPKI registration, not necessarily the state at the time of this incident. _(ground in: RPKI Route Origin Validation (ROV) / ROA authorization)_
- AS36561 announced 208.65.153.0/24, but current RPKI ROA data does not authorize that origin for this prefix (validity: invalid_asn, 4 covering ROA(s) found for a different origin). Reflects today's RPKI registration, not necessarily the state at the time of this incident. _(ground in: RPKI Route Origin Validation (ROV) / ROA authorization)_
  - Evidence:
    - `rrc00@2008-02-24T18:47:57Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[3333 12859 6461 3491 17557] peer=AS3333`
    - `rrc00@2008-02-24T18:47:57Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[3333 12859 2914 3491 17557] peer=AS3333`
    - `route-views2@2008-02-24T18:47:57Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[1280 6461 3491 17557] peer=AS1280`
    - `route-views2@2008-02-24T18:47:57Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[12956 3491 17557] peer=AS12956`
    - `route-views2@2008-02-24T18:47:57Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[1280 6939 3491 17557] peer=AS1280`
    - `route-views2@2008-02-24T18:47:57Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[6939 3491 17557] peer=AS6939`
    - `route-views2@2008-02-24T18:47:57Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[2914 3491 17557] peer=AS2914`
    - `rrc00@2008-02-24T18:47:58Z ANNOUNCE 208.65.153.0/24 origin=AS17557 path=[3549 3491 17557] peer=AS3549`
    - …and 164 more

## Explanation (grounded in reference docs)
According to [1], a BGPsec speaker should only originate a BGPsec UPDATE message advertising a route for a given prefix if there exists a valid ROA authorizing the BGPsec speaker's AS to originate routes to this prefix. If two distinct origin ASNs (AS17557 and AS36561) are announcing the same prefix (208.65.153.0/24), it indicates that at least one of them does not have a valid ROA, which is a strong indicator of a hijack or misconfiguration. The recommended validation step is to check the prefix against the RPKI data set, as described in [2], to verify if a corresponding ROA is found and is valid. If the ROA is found and is INVALID, or if a ROA is not found, the prefix should be treated with caution, as it may be a sign of a hijack or misconfiguration.

Sources:
  [1] RFC 8205 §4.1
  [2] RFC 7454 §6.1.2.2.2
  [3] RFC 8206 §3.1
  [4] RFC 8205 §8.1

Investigation trace:
  - Searched RFCs for "Using the reference corpus, explain why a prefix (208.65.153.0/24) being announced by two distinct origin ASNs (AS17557 and AS36561) is treated as a strong indicator of a hijack or misconfiguration, and what validation step is recommended. (BGP origin AS semantics and prefix hijack (MOAS); unauthorized origination / route hijack; RFC 4271 AS_PATH loop detection; RFC 7908 route leak definition (scope violation, not origin change); RPKI Route Origin Validation (ROV) / ROA authorization)" -> 4 source(s) (4 new)

## Suggested next checks
- Confirm the legitimate origin AS against RPKI ROAs / IRR objects.
- Check whether the anomalous origin is an upstream leak or a hijack.
- Inspect route-maps/prepending config on the ASes repeated in AS_PATH.
- Confirm with the newly-appearing transit AS's operator whether this was an intentional customer/peer/provider relationship change or a leak.

---
_Citation-correctness scoring (`--score-citations`), adversarial counter-evidence retrieval, and competing-hypothesis (ACH) ranking are all available now via `--seek-contradictions` -- see investigator/evaluation/, investigator/retrieval/contradiction.py, and investigator/ach.py._

Citation-correctness scorecard (checker: lexical_overlap):
  claims: 4
  citation precision: 100%
  citation recall: 25%
  retriever errors (no corpus support found): 1
  generator errors (corpus had support, not cited): 2
  [OK] [1] According to , a BGPsec speaker should only originate a BGPsec UPDATE message advertising a route for a given prefix if there exists a valid ROA authorizing the BGPsec speaker's AS to originate routes to this prefix.
  [MISS] (uncited) If two distinct origin ASNs (AS17557 and AS36561) are announcing the same prefix (208.65.153.0/24), it indicates that at least one of them does not have a valid ROA, which is a strong indicator of a hijack or misconfiguration.
        -> retriever error
  [MISS] [2] The recommended validation step is to check the prefix against the RPKI data set, as described in , to verify if a corresponding ROA is found and is valid.
        -> generator error
  [MISS] (uncited) If the ROA is found and is INVALID, or if a ROA is not found, the prefix should be treated with caution, as it may be a sign of a hijack or misconfiguration.
        -> generator error

Competing considerations (verified counter-evidence, not asserted):

[MOAS] 2 origin ASNs observed for a single prefix.
  Counter-evidence found (verified by entailment checker):
    - RFC 8206 §1.2
    - RFC 8206 §3
  Supporting evidence (strict entailment):
    - RFC 6811 §2.1
    - RFC 7454 §6.1.2.2

[ASPathLoop] 10 announcement(s) with a repeated ASN in AS_PATH.
  Counter-evidence found (verified by entailment checker):
    - RFC 8207 §7
    - RFC 7908 §3.1
    - RFC 8206 §5.4
  Supporting evidence (strict entailment):
    - RFC 6811 §2

[RouteLeak] 1 new transit AS(es) appeared mid-window across >= 2 peers each, origin unchanged.
  Counter-evidence found (verified by entailment checker):
    - RFC 7454 §6.2.1.1.2
    - RFC 7454 §6.2.3.2
    - RFC 8206 §5.2
    - RFC 7908 §3.2

[RPKIViolation] 2 observed origin(s) not authorized by current RPKI ROA data.
  Counter-evidence found (verified by entailment checker):
    - RFC 8205 §7.5
    - RFC 6480 §3.2
    - RFC 8205 §4.1
  Supporting evidence (strict entailment):
    - RFC 7454 §6.1.2.2.2

ACH ranking (least-refuted first):
  1. [MOAS] 2 origin ASNs observed for a single prefix. -- 2 topically-relevant (2 strictly entailed), 2 contradicting
  2. [ASPathLoop] 10 announcement(s) with a repeated ASN in AS_PATH. -- 1 topically-relevant (1 strictly entailed), 3 contradicting
  3. [RPKIViolation] 2 observed origin(s) not authorized by current RPKI ROA data. -- 1 topically-relevant (1 strictly entailed), 3 contradicting
  4. [RouteLeak] 1 new transit AS(es) appeared mid-window across >= 2 peers each, origin unchanged. -- 0 topically-relevant (0 strictly entailed), 4 contradicting
Verdict: leading hypothesis is [MOAS] 2 origin ASNs observed for a single prefix. (asserted on relevance-tier evidence: 2 vs 2 contradicting; conservative strict-entailment count: 2)
