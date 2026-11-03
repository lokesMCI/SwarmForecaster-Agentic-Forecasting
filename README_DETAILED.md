# SwarmForecaster: detailed README

**Forecast the Future 2026, US Midterm Election Night Edition. AI-only track, team-dsl (Darkknight).**

This document explains how the swarm reaches each of its 25 answers (A1–A15 and B1–B10): what evidence it uses, who checks it, and what limits stop any one model from pushing an answer too far. The short README is in `README.md`. This file is the detailed version.

**Final submitted run: `team-dsl-run-3`** (3 Nov 2026, 21:20–21:31 GMT), submitted at 21:31:53 GMT and resubmitted unchanged at 21:39:06 GMT (version 3, team name Darkknight). All numbers in section 4 come from that run. Earlier runs (1 and 2) are explained in section 9.

---

## 1. What we are scored on, and why it shapes the design

| Part | Score | What it rewards | Design consequence |
|---|---|---|---|
| A (15 election questions) | Brier gain over the market: `[(m − o)² − (p − o)²] × 100`, where `m` is the average of Kalshi and Polymarket at 22:00 GMT | Beating a liquid market | Start from the market and move away **only as far as evidence justifies**, with a hard cap |
| B (10 market questions) | `|forecast − actual| ÷ typical daily move`, capped at 5 | Getting the **median** move right; the benchmark is "no change" | Forecast the median, not the mean; shrink toward 0 unless a repeated historical effect says otherwise |
| Process prize | Agent design, evidence quality, stability, traceability (from the traces) | A clear plan, real reasoning, reproducibility | Separate roles, every call tagged, every intermediate result saved, deterministic code where possible |

Research on LLM forecasting finds that models alone trail liquid markets, but a market-anchored blend can beat them (AIA Forecaster, arXiv 2511.07678: about ⅔ market and ⅓ model). The swarm is built around that finding.

---

## 2. The pipeline at a glance

```
           ┌──────────────┐
 stage 0   │  DATA DESK   │  code only: market odds, drift, venue gap, control scenarios,
           │   (no LLM)   │  typical daily moves, past election-night moves
           └──────┬───────┘
                  ▼
 stage 1   SCOUTS (research, web search)      5 shared briefs + 1 targeted brief per question
                  ▼
 stage 2   PANEL (forecast) ×3 models         blind to market prices in Part A
                  ▼
 stage 3   CRITIC (critique)                  adversarial, now sees the market
                  ▼
 stage 4   SUPERVISORS (aggregate)            one for all of Part A, one for all of Part B
                  ▼
 stage 5   AGGREGATION (code, no LLM)         log-odds median, extremize, bounded market blend (A);
                  ▼                            scenario-mixture median and shrink (B)
 stage 6   FINAL (final, temperature 0)       keeps the method's answer unless there is a named error
```

| Stage | Role tag | Model | Why this model |
|---|---|---|---|
| Scouts | `research` (online) | Gemini 3.8 Flash | Cheap, fast web search; leaves budget for the panel |
| Panel | `forecast` | Claude Sonnet 5, GPT-6 Sol, Gemini 4 Argon | Three model families, so errors are less correlated and the median is robust |
| Critic | `critique` | DeepSeek V4 Pro | A different family again; an outside view on the panel |
| Supervisors | `aggregate` | Claude Opus 5 | The strongest reasoner, used only twice per run, where cross-question coherence matters |
| Final | `final` | Claude Sonnet 5, temperature 0 | Reproducible; writes the required JSON line |

Every call goes through `ftf.ask()` with a role, so the run log shows every step. Every stage's output is written to `swarm_out/run-<n>/` (`data_desk.json`, `briefs.json`, `supervisor_A.json`, `supervisor_B.json`, `state.json`).

Run 3 made 158 model calls, took about 10½ minutes and cost $2.79.

---

## 3. Stage by stage

### Stage 0: data desk (`swarm/data_desk.py`, code only)

For every Part A question:
- **Kalshi mid and Polymarket price**, and their average (the scorer's benchmark `m`).
- **Venue gap** (Kalshi minus Polymarket), **Kalshi spread** (liquidity) and **7-day drift**, so later stages know whether the market has just moved on fresh news.
- **Daily mids** for the past 8 days, from which the 1-day drift is computed.

Across Part A, it also builds **four control scenarios** from the House (A14) and Senate (A15) control markets, using a Gaussian copula with correlation ρ = 0.8. The two chambers move together in a wave, so treating them as independent would be wrong. Run 3 gave:

| D sweep | D House / R Senate | R sweep | R House / D Senate |
|---|---|---|---|
| 73.8% | 20.3% | 5.4% | 0.4% |

For every Part B question:
- The latest closes (live, falling back to the data pack).
- **The scorer's typical daily move**: the median absolute daily change over the 60 trading days to 30 Oct, exactly as the brief defines it.
- **The same instrument's move after each of the last five US federal elections** (2016, 2018, 2020, 2022 and 2024), with a note on each outcome.

### Stage 1: scouts (research)

- **Five shared briefs**, tagged `general`: the national environment, the Senate map (including races outside the question set that decide control), House battlegrounds, Election Day news, and macro and markets. Each is asked to be dense, dated and sourced, with a URL for each fact.
- **One targeted brief per question**. Part A briefs cover the candidates, polls from the last 3 weeks, ratings, fundraising, partisan lean and past results. Part B briefs cover today's price action, events scheduled for 4 Nov, and the expected reaction under each outcome.
- The system prompt tells every model to use only facts it can date, to flag anything more than a week old, and never to invent numbers.

### Stage 2: the panel (forecast), the heart of the swarm

- **Part A: the panel never sees market prices.** It's told they're deliberately withheld, and to ignore any it meets in the research. Each panellist reasons from the base rate (state or district lean, the midterm penalty for the president's party), the polling average and its likely error, candidate quality and late news, then returns `p_dem`. This makes the "own estimate" genuinely independent, which the rules require and which is the only way an estimate can add information to the market.
- **Part B: each panellist gives four conditional moves**, one per control scenario, instead of a single guess. The market-implied probabilities from stage 0 then weight them. This separates two different judgements: how the market reacts to each outcome, and how likely each outcome is.

### Stage 3: the critic (critique)

DeepSeek V4 Pro reviews each question. **It is shown the market**, unlike the panel. It looks for:
- stale or unsupported facts, such as an unsourced generic-ballot figure;
- double counting, for example the national environment counted once in polls and again as a "wave";
- ignored base rates;
- which panellist is more convincing where they disagree;
- for Part A, whether the gap between the panel and the market is justified by evidence the market may not have priced in.

It returns `direction` (toward the market, away from it, or hold), `confidence` and `issues`.

### Stage 4: supervisors (aggregate)

Claude Opus 5 runs twice per run, once over **all** of Part A and once over **all** of Part B:
- **Part A coherence.** Races share one national polling error. House control (A14) must fit the House environment and the scenario probabilities. Senate control (A15) must fit the Senate races: Democrats need a net gain of four to reach 51, and must hold their own seats. Before judging A15, the supervisor writes out the **seat arithmetic** in a `senate_seat_math` field: Democratic seats not up or safe, plus the pickups our own A1–A7 estimates imply, plus any Senate race outside A1–A7 still in play. It then states the probability of 51+ seats this implies, allowing for correlation.
- **Part B consistency.** Risk-on or risk-off direction across SPY, IWM, NVDA and the VIX; the shape of the 2-year versus 10-year curve; gilts following Treasuries only partly; gold against yields; oil against equities.
- Its adjustments are **bounded in code**: at most ±5 points for Part A, and at most ±1 typical daily move for Part B.

### Stage 5: aggregation (code, deterministic)

**Part A**

1. **Own estimate** = the median of the three panellists in log-odds, **extremized ×1.25**. LLM forecasts hedge toward 50%, and this is the standard correction. Then add the supervisor's bounded adjustment.
2. **Split our disagreement with the market into two parts.**
   - **Shared part**: the median gap across all races. The blind panel leans the same way in almost every race (in runs 2 and 3 it sat below the market in most of the 15), and that's a national-level bet. The House and Senate control markets aggregate the national picture better than we do, so it gets a **small weight (0.10)**.
   - **Race-specific part**: this race's gap minus the shared gap. This is where race-level research can genuinely add information, so it gets a **larger weight (0.33)**.
3. **Respect fresh market moves.** Both weights shrink by `1 / (1 + |1-day drift| / 0.05)`. A market that moved 5 points in a day has fresh information, so our weight is halved.
4. **Hard cap**: never more than **6 points** from the market.
5. **No crossing**: the answer never lands on the other side of the market from our own estimate. If our view is below the market, the answer is at or below the market.

**Part B**

1. For each panellist, take the **median of the mixture distribution**: four normal distributions centred on its four conditional moves, weighted by the scenario probabilities, each with spread 1.2 × the typical daily move. The median, not the mean, minimises absolute error.
2. **Own estimate** = the median across the three panellists, plus the supervisor's bounded adjustment.
3. **Shrink ×0.8 toward zero**, because daily moves are mostly noise. The exception is when **at least 80% of past election-night moves share the forecast's sign**, a repeated effect such as the VIX falling once election uncertainty resolves.

### Stage 6: final (final, temperature 0)

Claude Sonnet 5 sees the whole record for the question: the panel, the critic, the supervisor, the aggregation numbers and the market. It's told that the method's answer is the answer, and that it may deviate only for a **concrete, named error** (a wrong fact or a miscalculation), **never to re-weigh the evidence or split the difference**. It writes 2–4 sentences of reasoning, then the required JSON line, with `own_estimate` and, for Part A, `market_reference`.

---

## 4. How each question is answered (final run 3)

These numbers are from **run 3, the submitted run** (`team-dsl-run-3`). Its market snapshot was taken at about 21:20 GMT, after the US close. Control scenarios from the chamber markets: D sweep 73.8%, D House / R Senate 20.3%, R sweep 5.4%, R House / D Senate 0.4%.

- **Panel** is the three blind forecasts (Sonnet 5, GPT-6 Sol, Gemini 4 Argon).
- **Own** is our own estimate after extremizing and the supervisor's adjustment.
- **Method** is stage 5's answer. **Final** is the submitted answer.

In run 3, **every final call kept the method's answer**. The bullets quote each question's critic and supervisor. Numbers inside a supervisor note (such as "hold 62") refer to the recommendation it reviewed, before its bounded adjustment and the final market blend.

### Part A: Senate races

| Q | Race | Market (Kalshi / Poly) | Panel | Own | Weight damping | Method | Final |
|---|---|---|---|---|---|---|---|
| A1 | Texas Senate | 75.0 (74.5 / 75.5) | 38, 67, 58 | 60.0 | 0.71 | 73 | **73** |
| A2 | Maine Senate | 70.0 (69.5 / 70.5) | 72, 70, 62 | 74.3 | 0.67 | 72 | **72** |
| A3 | Michigan Senate | 75.5 (75.5 / 75.5) | 90, 91, 82 | 95.0 | 0.62 | 82 | **82** |
| A4 | Ohio Senate (special) | 72.5 (72.5 / 72.5) | 55, 62, 62 | 64.8 | 0.71 | 72 | **72** |
| A5 | Iowa Senate | 50.0 (49.5 / 50.5) | 42, 48, 46 | 45.0 | 0.83 | 50 | **50** |
| A6 | Kansas Senate | 64.5 (64.5 / 64.5) | 55, 65, 54 | 56.2 | 0.67 | 64 | **64** |
| A7 | Alaska Senate | 69.5 (68.5 / 70.5) | 57, 65, 58 | 60.0 | 0.71 | 69 | **69** |

- **A1 Texas Senate.** Critic (away_from_market, high confidence): Market likely underappreciates Texas's strong Republican baseline, history of polling misses underestimating GOP turnout, and the absence of concrete data for a D+9 wave. Panel's caution better reflects structural partisan lean. Supervisor (+0): Critic direction conflicts with recommended 70 > own 60; keep 70 for seat-math coherence.
- **A2 Maine Senate.** Critic (hold, medium confidence): Panel average is near market; Gemini is more convincing than the higher forecasts. Key unsupported claims: D+9 generic ballot, Jackson late entry. Single-incumbent overperformance may be overweighted; polling average is only about +1. Supervisor (+0): Coherent; hold.
- **A3 Michigan Senate.** Critic (toward_market, high confidence): Panel systematically double-counts overlapping signals: Cook/Inside Elections ratings are downstream of the same polls already cited. Historical 'every Senate race since 1994' is not independent of recent swing-state closeness (Slotkin won by 0.3%, Trump by… Supervisor (+1): Pivotal defense; 11-pt Siena lead with no contrary data supports small nudge up to ~83.
- **A4 Ohio Senate (special).** Critic (away_from_market, medium confidence): Unsupported national-wave claims; double counting of polls/ratings; market underweights Ohio GOP baseline and poll error; gap not explained by unpriced evidence. Supervisor (+0): Fine at 70.
- **A5 Iowa Senate.** Critic (toward_market, medium confidence): Panel average (0.45) underweights tied polls and treats partisan lean as more predictive than the midterm wave; Claude’s 0.42 relies on an unsupported claim about GOP-favoring polling errors; market at 0.50 better reflects genuine toss-up uncertainty given… Supervisor (+0): Genuine toss-up; hold 48.
- **A6 Kansas Senate.** Critic (away_from_market, medium confidence): Polls with documented Democratic nonresponse bias (WaPo) and within-margin leads (CNN) overstate Hamilton's edge; market heavily underweights Kansas's R+10 PVI, 94-year Democratic Senate drought, and Trump's 15+ point margin, suggesting an overcorrection to… Supervisor (+0): Hold 62.
- **A7 Alaska Senate.** Critic (away_from_market, medium confidence): Market overweights a single +7 Siena poll and underweights Alaska’s strong GOP baseline and incumbency. Panel correctly caps probability near 0.60 given history, RCV uncertainty, and polling error risk. Supervisor (+0): Hold 66; RCV count may take days.

### Part A: House races

| Q | Race | Market (Kalshi / Poly) | Panel | Own | Weight damping | Method | Final |
|---|---|---|---|---|---|---|---|
| A8 | FL-14 | 73.0 (71.5 / 74.5) | 52, 57, 58 | 58.7 | 0.59 | 72 | **72** |
| A9 | FL-22 | 63.0 (62.5 / 63.5) | 47, 49, 45 | 46.3 | 0.31 | 62 | **62** |
| A10 | ME-02 | 39.0 (40.5 / 37.5) | 35, 38, 32 | 31.6 | 0.65 | 39 | **39** |
| A11 | MI-04 | 60.5 (61.5 / 59.5) | 45, 51, 51 | 51.2 | 0.83 | 60 | **60** |
| A12 | MT-01 | 60.0 (60.5 / 59.5) | 40, 62, 48 | 47.5 | 0.71 | 59 | **59** |
| A13 | VA-01 | 74.5 (74.5 / 74.5) | 48, 55, 47 | 47.5 | 0.32 | 73 | **73** |

- **A8 FL-14.** Critic (away_from_market, high confidence): Market overestimates Dem chance; Trump+11 baseline implies even D+9 wave yields R+3.5 district, inconsistent with 0.73. Polls are small/stale; incumbency and fundraising do not overcome fundamental lean. Panel avg ~0.55 better reflects fundamentals. Supervisor (+0): Below market but consistent with Trump+11 baseline under D+9 wave; hold.
- **A9 FL-22.** Critic (away_from_market, medium confidence): Stale tied poll; PVI and Trump margin double counted; no fresh results; market premium unsupported by cited evidence. Supervisor (+0): Hold 58.
- **A10 ME-02.** Critic (hold, medium confidence): Double counting of PVI/Trump/ratings; D internal stale and partisan; D+9 ballot unsupported; RCV over-weighted; Gemini more credible than GPT. Supervisor (+0): Hold 36.
- **A11 MI-04.** Critic (away_from_market, medium confidence): Market overweighting generic-ballot wave; stale PVI trivialised; no independent polls; double-counting toss-up shift as fundaments move; ignoring incumbency base rate. Supervisor (+0): Hold 57.
- **A12 MT-01.** Critic (away_from_market, medium confidence): Stale outlier poll (MSU) and overreliance on fundraising/ midterm waves without proper reversion to R+6 base rate; market likely overweighting late Democratic drift with no new decisive data. Supervisor (+0): Hold 56.
- **A13 VA-01.** Critic (toward_market, medium confidence): Panel fabricates unsourced national environment numbers (D+8-9 generic ballot, Trump approval) and fails to reconcile them with its own low probabilities. Wittman’s incumbency advantage is already public and priced; no overlooked evidence justifies the wide… Supervisor (+0): Panel inconsistency already corrected toward market; hold 68.

### Part A: chamber control

| Q | Race | Market (Kalshi / Poly) | Panel | Own | Weight damping | Method | Final |
|---|---|---|---|---|---|---|---|
| A14 | House control (218+) | 94.2 (93.85 / 94.5) | 93, 96, 93 | 96.2 | 1.0 | 95 | **95** |
| A15 | Senate control (51+) | 74.5 (73.5 / 75.5) | 35, 43, 56 | 43.3 | 0.83 | 68 | **68** |

- **A14 House control (218+).** Critic (hold, high confidence): Double counting of same polling signal via multiple ratings; 0.96 estimate slightly overconfident relative to historical polling error risk; no gap between panel consensus and market. Supervisor (+0): Coherent with D+9 ballot and Sabato 239 D; hold 95.
- **A15 Senate control (51+).** Critic (away_from_market, medium confidence): Market likely overweights a uniform wave narrative; panel appropriately discounts polling leads based on historical overstatement of Democratic support in red states and structural barriers to a net +4 seat flip. Supervisor (+2): Own 41.3 incoherent with A1-A7 seat math (~4.7 expected flips) and with A14; critic double-counts poll-error discount. Move to ~70.

### Part B: market questions

| Q | Instrument | Unit | Typical move | Past election nights (2016, 2018, 2020, 2022, 2024) | Panel mixture medians | Own | Shrink | Final |
|---|---|---|---|---|---|---|---|---|
| B1 | SPY | % | 0.452 | +1.06, +2.14, +2.23, -2.06, +2.49 | +0.28, -0.07, +0.42 | +0.28 | none | **+0.28** |
| B2 | IWM | % | 0.522 | +3.08, +1.79, +0.11, -2.75, +5.79 | -1.01, -0.51, -0.07 | -0.16 | ×0.8 | **-0.13** |
| B3 | NVDA | % | 1.36 | -1.69, +1.29, +5.95, -5.66, +4.07 | -1.59, -0.30, -0.24 | -0.1 | ×0.8 | **-0.08** |
| B4 | VIX | points | 0.64 | -4.36, -3.55, -5.98, +0.55, -4.22 | -1.85, -3.19, -1.55 | -1.9 | none | **-1.9** |
| B5 | US 2-year | bp | 3.0 | +3, +3, -3, -6, +8 | -4.51, -0.93, -2.52 | -1.5 | ×0.8 | **-1.2** |
| B6 | US 10-year | bp | 4.0 | +19, +0, -12, -2, +16 | -3.08, +0.52, -0.89 | -0.9 | ×0.8 | **-0.7** |
| B7 | UK 10-year gilt | bp | 2.76 | +0.43, +0.06, -6.08, -10.25, -1.19 | -4.95, -0.74, -1.36 | -1 | ×0.8 | **-0.8** |
| B8 | Gold (Dec 26) | % | 0.669 | -0.06, +0.2, -0.74, -0.13, -2.67 | +0.49, +0.12, +0.11 | +0.12 | ×0.8 | **+0.1** |
| B9 | WTI (Dec 26) | % | 1.87 | +0.64, -0.87, +3.96, -3.46, -0.42 | +0.48, +0.15, +0.05 | +0.15 | ×0.8 | **+0.12** |
| B10 | Henry Hub (Dec 26) | % | 1.81 | +2.16, +0, -0.42, -4.45, +2.88 | +0.31, +0.18, +0.19 | +0.19 | ×0.8 | **+0.15** |

- **B1 SPY.** Critic (toward_market): Stale intraday price; ignores base rate of large historical post-election moves (avg >±1%) and omits contested/delayed scenario; panel disagrees on D sweep and R House/D Senate with weak justification for subdued moves; market likely prices higher move given… Supervisor (+0): Anchor of the risk-on state; +0.28% is modest vs 0.45% typical daily move and consistent with a VIX crush. Hold.
- **B2 IWM.** Critic (away_from_market): Unverified 74% D-sweep probability; underweighted 2018 base-rate move of +1.79% for split Congress; panel D-sweep estimates too disparate (Claude -1.3% vs Gemini -0.35%); overall expected panel move slightly negative, possibly too cautious versus historical… Supervisor (+0.35): Raise to ~-0.06%: IWM cannot be down 0.4% while SPY is up and VIX falls 1.9 pts; 2018 split-Congress analogue was IWM +1.8%. Sector headwinds are relative, not absolute.
- **B3 NVDA.** Critic (hold): Claude mislabels the baseline 74% D sweep as tail risk and assigns a -2.2% move detached from base rates for expected outcomes; Gemini contradicts provided research by calling R sweep bullish. Weighted panel spread (-1.4% to -0.2%) reflects those divergences,… Supervisor (+0.2): Raise to ~-0.04%: high-beta megacap should not be negative in a risk-on/vol-crush state; critic already flags the -2.2% panel leg as detached from base rates.
- **B4 VIX.** Critic (hold): No market data to assess gap; historical base rates strongly favor declines nearer -3 to -4 for resolved D-House/R-Senate; R-House/D-Senate spike plausible but contingent on prolonged uncertainty; 4 Nov macro/earnings noise ignored; hedging claim unsupported. Supervisor (+0): -1.9 is ~3x typical daily move but defensible for event resolution; keep as the risk-on anchor. Note RCV delays in ME/AK cap how much vol can crush.
- **B5 US 2-year.** Critic (hold): Panel disagrees on priced baseline: Claude/Gemini see divided government largely priced, while GPT-6-sol assumes D sweep is priced, producing a reversal sign for split Congress (+2 bp). GPT-6-sol's rationale contradicts gridlock logic and is unsubstantiated.… Supervisor (+1): Raise to ~-1.0 bp: a 2 bp front-end rally conflicts with equities up/VIX down and no FOMC until 8-9 Dec; keeps the bull steepener but smaller.
- **B6 US 10-year.** Critic (toward_market): 2018 midterm (D House/R Senate) base rate of 0 bp ignored, making split‑Congress rally forecasts unsupported; heavily priced D sweep should yield moves near zero per past midterms, so panel’s -3 to +1 range is too wide and overly skewed to a decline. Supervisor (+0): -0.7 bp vs 2y -1.0 bp preserves modest steepening consistent with long-end fiscal friction under divided government. Hold.
- **B7 UK 10-year gilt.** Critic (hold): Claude’s –6 bp D sweep move contradicts its own assertion that the outcome is heavily priced. Historical base rate from similar expected outcomes (2018 midterm) shows near-zero yield change. Panel consensus of –2.5 bp down is slightly dovish but justifiable… Supervisor (+0.4): Raise to ~-0.7 bp: gilt beta to a US-specific catalyst must be <1 vs the 10y Treasury's -0.7 bp; BoE lands 5 Nov, not 4 Nov, so no extra dovish impulse on the day.
- **B8 Gold (Dec 26).** Critic (away_from_market): Stale, unsourced probabilities; historical base rates show much smaller election-day reactions; R-sweep conditionals likely overstated; Anthropic more convincing on split Congress; no evidence of unpriced information. Supervisor (+0): +0.1% coherent with slightly lower yields offset by safe-haven unwind; well inside 0.67% typical move. Hold.
- **B9 WTI (Dec 26).** Critic (hold): Conflicting 3 Nov close; double-counted USD/regulatory and inventory channels; weak use of post-election base rates; Claude split-Congress sign unconvincing vs GPT/Gemini; no clear unpriced information justifies moving away from market. Supervisor (+0): +0.12% consistent with mildly positive equities and no oil-specific catalyst; far inside 1.87% typical move. Hold.
- **B10 Henry Hub (Dec 26).** Critic (hold): Minor data conflict (close $2.895 vs $2.905). Panel splits on R sweep magnitude; GPT's larger -1.1% is more consistent with historical election-surprise moves. Expected panel move ~+0.2% appears largely priced given high D-sweep probability, limiting any gap. Supervisor (+0): +0.15% is noise-level and directionally consistent with oil; data conflict on the 3 Nov close ($2.895 vs $2.905) is immaterial at this magnitude. Hold.

---

## 5. Safeguards: where a bad model output gets caught

| Risk | Safeguard |
|---|---|
| The panel anchors on the market | Market prices are withheld from the panel; the critic flags any that leak into the research (MI-04) |
| One model is wrong or invents a fact | Median of three model families; the critic flags unsourced figures (an invented "D+8.5 wave"); the supervisor confirms or refutes them |
| A shared national bias repeated across 15 races | The shared and race-specific gaps are split, and the shared part gets weight 0.10 |
| The market has fresh news we don't | Drift damping (VA-01's weight fell to 0.24) |
| A large model bet against a liquid market | 6-point cap (Ohio) |
| An answer that contradicts our own view | No-crossing rule (Iowa, ME-02) |
| Inconsistent related answers | Supervisors over all of Part A and all of Part B; A15 checked against the seat ladder |
| Noise mistaken for signal in Part B | Median of a scenario mixture; shrink ×0.8 unless 80% of history agrees |
| The final call re-deciding the answer | Temperature 0; may deviate only for a named factual or calculation error |
| An unreadable reply | Each call retries with backoff; a JSON parser tolerant of nesting; `ftf.parse_final` checks every final |

---

## 6. Changes made before the scored run

These were found by testing in the event repo on 3 Nov. The copy in the event repo has them, and the scored run uses that copy.

1. **Quoted `.env` values.** Team settings written as `KEY="value"` kept their quotes, so every call failed authentication and the team tag became `"team-dsl"`, quotes included. The loader now strips quotes.
2. **Percent answers from panellists.** A `p_dem` of `62` (meaning 62%) was clipped to 0.99 before the divide-by-100 check could run. It's now converted first.
3. **No crossing the market.** Added after run 2 showed Iowa's answer (52) landing above the market (50) when our own view was 45.
4. **Stricter final prompt.** Added after run 2's final calls overrode the method by 6–8 points in Maine, FL-14 and FL-22 just to split the difference. The final call may now deviate only for a named error.
5. **Retry cut-off and unreadable replies.** Reasoning tokens count against `max_tokens`, and in run 2 that cut off **6 of 25 DeepSeek critiques** before their JSON verdict (A3, A7, A10, B1, B5 and B7), so their reviews were silently lost. The critic now gets 6,000 tokens. Every stage checks its reply: the panel needs `p_dem` or all four scenario moves, the critic `direction` and `issues`, the supervisors `adjust` and `notes`, and each final a readable `answer`. A reply that fails is retried with double the token budget (at most 12,000), and every retry is traced.
6. **Research never reports market odds.** In run 2, a stale Kalshi price reached the blind MI-04 panel through the research. Scouts are now told not to report prediction-market or betting prices.
7. **Run manifest and completeness report.** `data_desk.json` now records the git commit, the models and the constants. At the end, the run lists any question without a final answer (rerun it under the same label, never by hand) and any final that departed from the method. It also warns if the code has uncommitted changes.
8. **Ignore swarm outputs in git.** `swarm_out/` and `swarm_*.log` were added to `.gitignore`, so later runs aren't flagged as having uncommitted changes.

The constants (`EXTREMIZE`, `MODEL_WEIGHT`, `W_IDIO`, `W_SHARED`, `DRIFT_SCALE`, `CAP_PTS`, `B_SHRINK`, `RHO`) didn't change, and none was tuned against today's answers.

---

## 7. Running it

```bash
# from the event repo folder (poros-foundry/forecast-the-future-2026) with swarm/ copied in
pip install -r requirements.txt
cp .env.example .env                                   # fill in OPENROUTER_API_KEY, TEAM_ID, SUBMIT_CODE, TEAM_NAME
git add swarm && git commit -m "swarm"                 # calls are tagged with the commit
python swarm/swarm.py --run test --questions A2,A6,B4  # cheap test (~$0.70)
python swarm/swarm.py --run 3                          # full run (~$3.20, ~5.5 min)
```

```python
import sys; sys.path.insert(0, "ai_only"); import ftf
answers = ftf.answers_from_finals(run=3)
ftf.submit(answers, run=3, dry_run=True)   # checks only
ftf.submit(answers, run=3)                 # the real submission
```

## 8. Data sources and tools

- The event data pack and its scripts: `code/`, `ai_only/ftf.py`, `ai_only/ftf_tools.py`. These fetch live Kalshi, Polymarket, US Treasury, Bank of England and Yahoo Finance data, falling back to the pack's files.
- OpenRouter models: Gemini 3.8 Flash, Claude Sonnet 5, GPT-6 Sol, Gemini 4 Argon, DeepSeek V4 Pro and Claude Opus 5. Web search through OpenRouter (`online=True`).
- Our own Python (pandas and the standard library).
- No other APIs or data sources. Claude (Anthropic) helped write and review the code. No answer was set by hand.

## 9. Submission and run history

| | |
|---|---|
| **Final run** | `team-dsl-run-3`: one complete run of the pipeline above, from research to final, for all 25 questions |
| **Code** | git commit `6d9c2ee`, no uncommitted changes (recorded in `swarm_out/run-3/data_desk.json`) |
| **Submitted** | 21:31:53 GMT on 3 Nov 2026 (submission `0995fa7e-9c01-4588-8fc6-d3330b9d1c43`, version 2), then resubmitted at 21:39:06 GMT with the identical answers (same hash `d2c4ed06…`) to set the team name to Darkknight: submission `b89938f0-b75e-4746-beba-bf4aec1c634d`, **version 3** |
| **Answers** | Equal to the last final call of each question in run 3; the dry run raised no warnings |
| **After the run** | No model calls were made by any team machine |

Our team worked from two machines that shared one team key, so the labels of the earlier runs overlap:
- **`run-1`** holds a swarm run from one machine (18:13–18:23 GMT, submitted at 19:12 as version 1) and a simpler two-model prototype (`ai_only/agent.py`) from the other (18:30–18:37 GMT).
- **`run-2`** is a swarm run (18:53–18:58 GMT) whose results led to the fixes in section 6.
- **`test` and `swarm-test`** were small tests.

Run 3 replaces all of them.
