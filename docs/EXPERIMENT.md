## VERDICT

The claim splits into three assertions. **One is false, one is true for the wrong reason, and one is true and strongly supported.** All numbers below are measured on this machine; ~12M simulated captures across 12 sweeps.

**Code** (all in `D:\temp\claude\D--My-apps-Cyber-Flip--claude-worktrees-assemblyai-voice-agent-hackathon-291762\c09d90d9-a412-4614-b967-92de40b55905\scratchpad\`):
`fastval.py` (O(1)-update ISO 6346 + IBAN mod-97, verified against reference: 616 IBAN strings / 651 ISO strings, 0 disagreements) · `accent.py` (8 accent-conditioned confusion tables) · `xp.py` (harness, 6 conditions) · `sanity.py` · `blindness.py` · `examples.py` · `qstrat.py` · `guardhole.py` · `cands.py` · `residual.py` · `knee.py` · `tolerance.py` / `summary.py` / `summary2.py` / `an.py` · `results_*.json` (12 sweeps).

**Design.** 8 accents (en-US, en-GB, en-AU, en-GB-scot, en-US-south, en-IN, es-L1, zh-L1), each with a phonologically-motivated confusion table *and* an ASR error-rate multiplier (1.0–2.0×). The solver **never knows the accent**. 6 conditions, paired on identical corruptions: NAIVE → SLOT (slot-typing only) → CKSUM (checksum + max-entropy questioning, uniform prior, no confusion model) → FULL-US (American table) → FULL-BL (blended) → ORACLE (accent-matched, upper bound). 17% of generated error mass sits on pairs absent from the solver's table.

---

### 1. "Many acoustic realisations collapse onto the same single valid string" — **FALSE**

Conditioned on the checksum actually failing (`cands.py`, N=4000/cell):

| format | 0 candidates | **exactly 1** | 2+ | mean when 2+ | truth in set (p_eff .05) |
|---|---|---|---|---|---|
| ISO 6346 | 0.0% | **0.0%** | 100% | **13.7** | 85.4% |
| IBAN-GB | 0.4–1.5% | 4.0–7.8% | ~94% | **3.6** | 70.0% |

Across every error rate, ISO 6346's check digit returned exactly one repair **zero times in 24,000 trials**. It narrows 26→13.7; it does not collapse. What collapses the candidate set is the acoustic posterior — which is why the confusion model matters (§4).

### 2. "Accent robustness comes from constraining the output space" — **TRUE, but not by that mechanism**

The shape-only control (every accent at the *same* effective error rate, so only the confusion shape differs) is decisive. Across **216 cells**, spread ÷ that condition's own binomial noise floor: **median 1.01, p95 1.42, max 2.02, only 3.7% above 1.5×.**

Accent *shape* has no detectable effect on capture accuracy — **for any condition, including the uncorrected baseline.** That is not a property of constraint; exact-match accuracy is `(1−p)^L`, a function of how many characters are wrong, never which. The important half of this finding is that the **mismatched confusion table introduces no new accent sensitivity either.**

What accents actually differ in is error *rate*, and that is what constraint buys (`tolerance.py`, N=3000/cell, fixed questioner). Per-character error rate absorbed while still capturing 95% exactly:

| format | analytic NAIVE | constrained (mean) | per-accent range | **gain** |
|---|---|---|---|---|
| ISO 6346 (L=11) | 0.0047 | **0.0692** | 0.0651–0.0737 (1.13×) | **14.9×** |
| IBAN-GB (L=22) | 0.0023 | **0.0399** | 0.0376–0.0428 (1.14×) | **17.1×** |

**That is the real mechanism, and it proves the claim operationally:** the tolerance budget is identical across accents to within 14%, while accents differ in ASR error rate by up to 2×. A 15× budget absorbs a 2× accent penalty with an order of magnitude to spare.

Realistic setting (accents differ in both shape and rate), ISO at p=0.02: NAIVE spread across accents **0.178 → 0.019** with constraint (9.6×), mean 0.735 → 0.984. Caution: absolute spread is *not* scale-free — at p=0.30 NAIVE spread is small only because every accent is pinned near zero, and the *relative* miss-rate ratio actually **rises** (1.60→2.68), because constraint removes the generic errors uniformly and what survives is the residual.

### 3. "You don't need to fine-tune" — **TRUE, decisively**

| | ISO 6346 | IBAN-GB |
|---|---|---|
| ORACLE − FULL-BL (value of knowing the accent) | **−0.001 to +0.002** | **−0.002 to +0.001** |
| FULL-US − FULL-BL (cost of an American-only table) | **−0.002 to +0.000** | **−0.002 to +0.000** |

Zero at every error rate, both formats, N=2000 (SE ≈ 0.005). **Do not build accent detection. Do not bother blending the table.**

---

### 4. Does the confusion model add anything over a plain checksum retry?

**Yes — decisively on ISO, modestly on IBAN**, and the gap is explained structurally by candidate count (13.7 vs 3.6). FULL-BL − CKSUM, where CKSUM already gets slot typing *and* the same max-entropy questioner under a uniform prior:

| p | ISO 6346 | IBAN-GB |
|---|---|---|
| 0.02 | **+0.096** | +0.084 |
| 0.05 | **+0.208** | +0.185 |
| 0.10 | **+0.321** | +0.213 |
| 0.15 | **+0.347** | +0.169 |

**The value of the acoustic model is inversely proportional to the strength of the checksum.** Same reason confidence matters more on ISO: flat `words[].confidence` costs ISO −11.9 points at p=0.05 but IBAN only −3.4 at p=0.02.

---

### 5. Two algorithm defects found by measurement

**(a) The doubt-budget guard is silently defeated.** `argmax_i H(marginal_i)` is *identically zero at every position* when there is one valid candidate — exactly the case the guard fires for. Any implementation treating "no entropy to gain" as "nothing to ask" falls straight through to a silent accept (`guardhole.py`, N=6000/cell):

| | guard fires w/ zero entropy | of those, written **wrong and silently** |
|---|---|---|
| ISO p=0.05 | 56.3% of identifiers | 2.0% |
| ISO p=0.15 | 33.2% | 10.3% |
| IBAN p=0.10 | 28.9% | 17.4% |
| IBAN p=0.15 | 19.3% | **41.8%** |

**Fix:** when the guard fires, ask at `argmax` *unexplained doubt*, not entropy. Marginal entropy measures disagreement *among candidates* (disambiguation); the guard fires when the suspicion is a *second error the checksum already absorbed* (detection). Result: **silently-wrong goes to 0.000 in every cell**, and accuracy rises (ISO p=0.10: 0.828→0.859; IBAN p=0.05: 0.769→0.867).

**(b) `DOUBT_T = 0.25` is badly tuned** — it sits on a cliff. `knee.py`, ISO p=0.02:

| DOUBT_T | accuracy | silent | sil.wrong | q/id | handover |
|---|---|---|---|---|---|
| 0.25 (spec) | 0.983 | 0.202 | 0.0003 | 1.26 | 0.198 |
| **0.40** | **0.982** | **0.636** | 0.0008 | **0.45** | **0.028** |
| 1.01 (off) | 0.977 | 0.849 | 0.0057 | 0.19 | 0.022 |

**0.40 dominates 0.25 on every axis** except +0.0005 silent error: 3× the silence, 1/3 the questions, 1/7 the handovers, same accuracy. This resolves the tension the fix creates with the ambient promise.

---

### 6. Where it breaks — structural, not statistical

ISO 6346 is `Σ value(c)·2^i mod 11`, so characters congruent mod 11 are **mathematically invisible** to it. The collision classes are perfectly regular: `{B,L,V,1} {C,M,W,2} {D,N,X,3} {E,O,Y,4} {F,P,Z,5} {G,Q,6} {H,R,7} {I,S,8} {J,T,9} {A,K,U}` — **45 blind pairs**, including:

- **B/V** — the categorical Spanish `/b/-/v/` merger, the single strongest accent-specific confusion in the set
- **F/P** — Indian English `/p/-/f/`
- **P/Z** — "pee"/"zee", both E-set · **A/K** — "ay"/"kay", both A-set

Demonstrated concretely in `examples.py`: `BMMU9233219` heard as `VMMU9233219` **passes the check digit** and is written silently and wrongly. 2.8–4.7% of erroneous ISO hypotheses are undetectable this way. **IBAN-GB has ZERO blind pairs** — mod 97 over a decimal expansion where letters occupy two digit positions makes every single substitution detectable.

I tested whether the residual accent gap is *caused* by blind pairs. **It is not** — only 2–4% of misses involve one, and IBAN shows a *larger* accent gap (0.078 vs 0.237) with zero blind pairs. The residual gap is error-rate, not shape. My hypothesis was wrong.

---

### What this does not establish

The ASR layer is simulated. The accent amplifiers are **phonological priors, not measured ASR outputs** — they are hypotheses about *which* pairs move; magnitudes are guesses. Two things would change the numbers materially: (1) if real accent-specific confusions are *stronger* than modelled, the shape-only null could break; (2) the simulated confidence is informative but imperfectly calibrated (conf 0.5 → 21% actual) — I bracketed this with weak/flat regimes, and flat costs ISO −11.9 points. **The day-3 measurement of `words[].confidence` on spelled alphanumerics remains the load-bearing unknown.** Also note ~41% of generated error mass is cross-type (killed free by slot typing); I ran a within-type hard case where slot typing contributes nothing and the conclusions hold (ISO 0.906 at p=0.05, accent spread still at noise).

**Bottom line for the product:** lead with IBAN, not containers — mod 97 is a complete single-substitution detector and ISO 6346 is not. Ship one confusion table and no accent detection. Fix the questioner before the demo. Set `DOUBT_T = 0.40`.