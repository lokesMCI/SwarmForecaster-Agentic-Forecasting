# SwarmForecaster: detailed README

**Forecast the Future 2026, US Midterm Election Night Edition. AI-only track, team-dsl (Darkknight).**



This document explains how the swarm reaches each of its 25 answers (A1–A15 and B1–B10): what evidence it uses, who checks it, and what limits stop any one model from pushing an answer too far. The short README is in `README.md`. This file is the detailed version.

**Final submitted run: `team-dsl-run-4`** (3 Nov 2026, 21:43–21:47 GMT), submitted at 21:47:22 GMT as version 4, team name Darkknight. All numbers in section 4 come from that run. Earlier runs are explained in section 9.

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
 stage 2   PANEL (forecast) ×4 models         blind to market prices in Part A
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
| Scouts | `research` (online) | Claude Sonnet 5 | Strong web research with dated sources; evidence quality is a judged criterion |
| Panel | `forecast` | Claude Opus 5, Claude Sonnet 5, GPT-6 Sol, Gemini 4 Argon | Four strong forecasters from three model families, so errors are less correlated and the median is robust |
| Critic | `critique` | Claude Opus 5 | The strongest reasoner for the adversarial review; replaced DeepSeek V4 Pro, whose replies were cut off and slow in earlier runs |
| Supervisors | `aggregate` | Claude Opus 5 | The strongest reasoner, used only twice per run, where cross-question coherence matters |
| Final | `final` | Claude Opus 5, temperature 0 | Reproducible; checks the record for named errors and writes the required JSON line |

Every call goes through `ftf.ask()` with a role, so the run log shows every step. Every stage's output is written to `swarm_out/run-<n>/` (`data_desk.json`, `briefs.json`, `supervisor_A.json`, `supervisor_B.json`, `state.json`).

Run 4 made 182 model calls (30 research, 100 forecast, 25 critique, 2 aggregate, 25 final), ran up to 25 calls at once per stage, took about 3½ minutes and cost about $7.65.

---

## 3. Stage by stage

### Stage 0: data desk (`swarm/data_desk.py`, code only)

For every Part A question:
- **Kalshi mid and Polymarket price**, and their average (the scorer's benchmark `m`).
- **Venue gap** (Kalshi minus Polymarket), **Kalshi spread** (liquidity) and **7-day drift**, so later stages know whether the market has just moved on fresh news.
- **Daily mids** for the past 8 days, from which the 1-day drift is computed.

Across Part A, it also builds **four control scenarios** from the House (A14) and Senate (A15) control markets, using a Gaussian copula with correlation ρ = 0.8. The two chambers move together in a wave, so treating them as independent would be wrong. Run 4 gave:

| D sweep | D House / R Senate | R sweep | R House / D Senate |
|---|---|---|---|
| 75.2% | 18.7% | 5.5% | 0.5% |

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

Claude Opus 5 reviews each question. **It is shown the market**, unlike the panel. It looks for:
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

1. **Own estimate** = the median of the four panellists in log-odds, **extremized ×1.25**. LLM forecasts hedge toward 50%, and this is the standard correction. Then add the supervisor's bounded adjustment.
2. **Split our disagreement with the market into two parts.**
   - **Shared part**: the median gap across all races. The blind panel leans the same way in almost every race (in runs 2 and 3 it sat below the market in most of the 15), and that's a national-level bet. The House and Senate control markets aggregate the national picture better than we do, so it gets a **small weight (0.10)**.
   - **Race-specific part**: this race's gap minus the shared gap. This is where race-level research can genuinely add information, so it gets a **larger weight (0.33)**.
3. **Respect fresh market moves.** Both weights shrink by `1 / (1 + |1-day drift| / 0.05)`. A market that moved 5 points in a day has fresh information, so our weight is halved.
4. **Hard cap**: never more than **6 points** from the market.
5. **No crossing**: the answer never lands on the other side of the market from our own estimate. If our view is below the market, the answer is at or below the market.

**Part B**

1. For each panellist, take the **median of the mixture distribution**: four normal distributions centred on its four conditional moves, weighted by the scenario probabilities, each with spread 1.2 × the typical daily move. The median, not the mean, minimises absolute error.
2. **Own estimate** = the median across the four panellists, plus the supervisor's bounded adjustment.
3. **Shrink ×0.8 toward zero**, because daily moves are mostly noise. The exception is when **at least 80% of past election-night moves share the forecast's sign**, a repeated effect such as the VIX falling once election uncertainty resolves.

### Stage 6: final (final, temperature 0)

Claude Sonnet 5 sees the whole record for the question: the panel, the critic, the supervisor, the aggregation numbers and the market. It's told that the method's answer is the answer, and that it may deviate only for a **concrete, named error** (a wrong fact or a miscalculation), **never to re-weigh the evidence or split the difference**. It writes 2–4 sentences of reasoning, then the required JSON line, with `own_estimate` and, for Part A, `market_reference`.

---

## 4. How each question is answered (final run 4)

These numbers are from **run 4, the submitted run** (`team-dsl-run-4`). Its market snapshot was taken at about 21:43 GMT, after the US close. Control scenarios from the chamber markets: D sweep 75.2%, D House / R Senate 18.7%, R sweep 5.5%, R House / D Senate 0.5%.

- **Panel** is the four blind forecasts (Opus 5, Sonnet 5, GPT-6 Sol, Gemini 4 Argon).
- **Own** is our own estimate after extremizing and the supervisor's adjustment.
- **Method** is stage 5's answer. **Final** is the submitted answer.

The final call kept the method's answer for every question except B4. For B4 it moved −1.3 to −1.2, citing a rounding error. Its arithmetic overlooked that the supervisor's +0.7 is capped at one typical move (0.64), so the method's −1.3 was right. The 0.1-point difference is negligible for scoring.

The bullets quote each question's critic and supervisor. Numbers inside a supervisor note refer to the recommendation it reviewed, before its bounded adjustment and the final market blend.

### Part A: Senate races

| Q | Race | Market (Kalshi / Poly) | Panel | Own | Weight damping | Method | Final |
|---|---|---|---|---|---|---|---|
| A1 | Texas Senate | 75.0 (74.5 / 75.5) | 57, 45, 60, 61 | 60.6 | 0.71 | 73 | **73** |
| A2 | Maine Senate | 70.0 (69.5 / 70.5) | 78, 72, 78, 72 | 79.9 | 0.67 | 74 | **74** |
| A3 | Michigan Senate | 76.0 (75.5 / 76.5) | 87, 88, 85, 73 | 90.7 | 0.67 | 81 | **81** |
| A4 | Ohio Senate (special) | 72.5 (72.5 / 72.5) | 72, 68, 76, 67 | 74.3 | 0.71 | 74 | **74** |
| A5 | Iowa Senate | 50.2 (49.5 / 51) | 40, 37, 40, 43 | 39.6 | 0.86 | 49 | **49** |
| A6 | Kansas Senate | 64.5 (64.5 / 64.5) | 56, 55, 58, 54 | 56.9 | 0.67 | 64 | **64** |
| A7 | Alaska Senate | 69.5 (68.5 / 70.5) | 60, 55, 58, 62 | 61.2 | 0.71 | 69 | **69** |

- **A1 Texas Senate.** Critic (toward_market, medium confidence): double-counted national environment plus GOP-polling-error haircut; stale Cook/DDHQ ratings; market drift suggests unpriced early-vote info panel lacks Supervisor (+0): Coherent at 71; environment-plus-haircut double count already unwound by recommendation.
- **A2 Maine Senate.** Critic (toward_market, medium confidence): stale October polls weighted as fresh; 2020 Maine error double-counted/under-applied; incumbent base rate ignored; early-vote composition overread Supervisor (+0): 74 fine; Collins incumbency vs 2020 Maine polling error roughly offset. Watch RCV call delay.
- **A3 Michigan Senate.** Critic (toward_market, medium confidence): single-poll anchoring on Siena D+11; environment double-counted with poll; Cook toss-up and MI's sub-1pt base rates discounted; drift_7d shows market already priced the poll Supervisor (+0): 82 fine as a HOLD, not a pickup; it is the binding constraint on A15.
- **A4 Ohio Senate (special).** Critic (hold, medium confidence): undated national-environment numbers; double counting of environment/fundraising already in polls; GPT-6's 0.76 ignores Ohio GOP polling-error base rate; stale toss-up ratings Supervisor (+0): Hold at 73; panel and market agree.
- **A5 Iowa Senate.** Critic (toward_market, medium confidence): Selzer-specific 2024 error overgeneralized to all Iowa polling; R-lean penalty triple-counted via ratings; presidential rather than midterm base rate; no private information to justify 10pt discount vs tight liquid market drifting D Supervisor (+2): Up 2 to 48: panel's 37.6 is incoherent with KS(62)/AK(67) given Turek +1 in the same Nov 2 polling; Selzer error is a single-pollster presidential artifact.
- **A6 Kansas Senate.** Critic (toward_market, medium confidence): phantom NYT/Siena poll cited by 3 panelists; ratings+aggregators double-counted; 7d market drift of +23.5 ignored; red-state polling-error haircut unquantified Supervisor (+0): 62 fine; note 3 panelists leaned on one NYT/Siena number, so treat as single-source not confirmed.
- **A7 Alaska Senate.** Critic (toward_market, medium confidence): directionally unjustified polling-error haircut; double-counted state lean/incumbency; ignored ~75-80% base rate for +2-3 final-average leads; spoiler asymmetry and 49.5% primary share under-weighted Supervisor (+0): 67 fine; RCV counting may delay final call by days.

### Part A: House races

| Q | Race | Market (Kalshi / Poly) | Panel | Own | Weight damping | Method | Final |
|---|---|---|---|---|---|---|---|
| A8 | FL-14 | 73.0 (71.5 / 74.5) | 55, 55, 54, 52 | 55.6 | 0.59 | 71 | **71** |
| A9 | FL-22 | 67.5 (67.5 / 67.5) | 54, 47, 48, 46 | 46.9 | 0.43 | 66 | **66** |
| A10 | ME-02 | 39.0 (40.5 / 37.5) | 28, 30, 38, 30 | 25.7 | 0.65 | 37 | **37** |
| A11 | MI-04 | 60.5 (61.5 / 59.5) | 52, 52, 48, 46 | 50.0 | 0.83 | 60 | **60** |
| A12 | MT-01 | 60.0 (60.5 / 59.5) | 44, 45, 48, 46 | 43.4 | 0.71 | 58 | **58** |
| A13 | VA-01 | 74.5 (74.5 / 74.5) | 58, 55, 58, 54 | 58.1 | 0.32 | 74 | **74** |

- **A8 FL-14.** Critic (toward_market, medium confidence): panel anchored to 9-week-old ratings and a July poll; ignores incumbency base rate and 7d market drift; redraw lean double-counted with FL trend; no recent polling cuts both ways but market likely has private data Supervisor (+0): 68 fine; no recent polling, market likely holds private data.
- **A9 FL-22.** Critic (toward_market, medium confidence): duplicate poll counted twice; obsolete pre-redistricting Frankel margin; underweighted Askar cash collapse and unidirectional Cook/Sabato shifts; ratings anchoring; markets stable at 0.675 across venues Supervisor (+0): 62 fine; duplicate-poll and pre-redraw margin issues already corrected toward market.
- **A10 ME-02.** Critic (toward_market, medium confidence): triple-counting one thin poll pool; conflicting averages (R+1.9 vs R+7.2) resolved pessimistically; stale June fundraising; undated generic-ballot claims; Likely-R base rate implies ~20-30% floor plus wave premium Supervisor (+0): 34 fine; Likely-R with wave premium.
- **A11 MI-04.** Critic (toward_market, medium confidence): stale Sept campaign internal double-counted as independent poll; ignored toss-up base rate favoring wave party; lagging ratings treated as static despite Cook's Lean R-to-Toss-up shift; stale 9/30 fundraising framed as R edge; uniform-swing math contradicts… Supervisor (+0): 57 fine; Cook Lean R to Toss-up shift supports market side.
- **A12 MT-01.** Critic (toward_market, medium confidence): PVI/Trump-margin/Zinke-margin triple-counted as one fact; reliance on stale 11-day-old D-sponsored poll; Cook's one-way rating trajectory ignored; unexplained +15pt market drift suggests unpriced late info panel didn't research; open-seat wave-year flip base… Supervisor (-1): Down 1 to 54: +15pt drift unexamined, so weak two-sided evidence; Trump+~20 fundamentals real.
- **A13 VA-01.** Critic (toward_market, medium confidence): Panel ignores +11pt 7-day market drift; double-counts correlated partisan polls; misapplies GOP-underestimate base rate against 2025 VA evidence; stale fundraising; unverified Cook rating Supervisor (+0): 70 fine; 2025 VA results argue against a GOP-underestimate haircut here.

### Part A: chamber control

| Q | Race | Market (Kalshi / Poly) | Panel | Own | Weight damping | Method | Final |
|---|---|---|---|---|---|---|---|
| A14 | House control (218+) | 94.0 (93.55 / 94.5) | 97, 95, 95, 94 | 97.5 | 0.96 | 96 | **96** |
| A15 | Senate control (51+) | 76.0 (75.5 / 76.5) | 78, 68, 70, 75 | 77.1 | 0.91 | 78 | **78** |

- **A14 House control (218+).** Critic (toward_market, medium confidence): fabricated DDHQ/Cook seat figures and unsourced approval levels; stale Sept Cook estimate contradicts bullish framing; model probabilities double-count the generic ballot; pro-GOP polling-error tail underweighted; gap to market within friction Supervisor (+0): 96 vs market 94 is within friction; Sabato 239D and DDHQ 241D final ratings (Nov 3) support. No change.
- **A15 Senate control (51+).** Critic (toward_market, medium confidence): Opus/Gemini cite undated, unsourced poll margins and generic-ballot numbers; Sonnet double-discounts correlated polling error already in rater/forecast baselines; TX poll is a month stale and predates $239M pro-Paxton spending; rater average and 'dedicated… Supervisor (+0): No change: explicit seat math yields 0.75-0.78, matching 76 and market-implied 0.757; panel's 77.1 top end double-counts ratings as evidence.

### Part B: market questions

| Q | Instrument | Unit | Typical move | Past election nights (2016, 2018, 2020, 2022, 2024) | Panel mixture medians | Own | Shrink | Method | Final |
|---|---|---|---|---|---|---|---|---|---|
| B1 | SPY | % | 0.452 | +1.06, +2.14, +2.23, -2.06, +2.49 | +0.34, -0.12, -0.04, +0.30 | +0.2 | none | +0.2 | **+0.2** |
| B2 | IWM | % | 0.522 | +3.08, +1.79, +0.11, -2.75, +5.79 | +0.38, -1.14, -0.55, -0.19 | -0.13 | ×0.8 | -0.1 | **-0.1** |
| B3 | NVDA | % | 1.36 | -1.69, +1.29, +5.95, -5.66, +4.07 | +0.54, -0.89, -0.33, -0.27 | -0.06 | ×0.8 | -0.05 | **-0.05** |
| B4 | VIX | points | 0.64 | -4.36, -3.55, -5.98, +0.55, -4.22 | -2.04, -2.58, -1.77, -1.65 | -1.3 | none | -1.3 | **-1.2** |
| B5 | US 2-year | bp | 3.0 | +3, +3, -3, -6, +8 | -0.38, -1.39, -1.98, -0.48 | -0.9 | ×0.8 | -0.7 | **-0.7** |
| B6 | US 10-year | bp | 4.0 | +19, +0, -12, -2, +16 | -1.04, -2.29, -1.90, -2.25 | -1.8 | ×0.8 | -1.4 | **-1.4** |
| B7 | UK 10-year gilt | bp | 2.76 | +0.43, +0.06, -6.08, -10.25, -1.19 | +1.30, -1.54, -0.18, -0.04 | -0.3 | ×0.8 | -0.2 | **-0.2** |
| B8 | Gold (Dec 26) | % | 0.669 | -0.06, +0.2, -0.74, -0.13, -2.67 | +0.09, +0.49, +0.28, +0.18 | +0.23 | ×0.8 | +0.18 | **+0.18** |
| B9 | WTI (Dec 26) | % | 1.87 | +0.64, -0.87, +3.96, -3.46, -0.42 | -0.25, -0.69, -0.23, -0.41 | -0.33 | ×0.8 | -0.26 | **-0.26** |
| B10 | Henry Hub (Dec 26) | % | 1.81 | +2.16, +0, -0.42, -4.45, +2.88 | -0.57, -0.29, -0.60, -0.13 | -0.43 | ×0.8 | -0.34 | **-0.34** |

- **B1 SPY.** Critic (toward_market): unsourced VIX/yield/odds figures; 'priced-in' double counted; midterm base-rate magnitude (~2%) ignored; presidential-election scaling misapplied to R sweep; downside tail missing; AMD earnings post-close irrelevant Supervisor (+0.07): +0.07pp to +0.20%: required to stay coherent with a still-sizeable VIX decline and positive-beta IWM/NVDA.
- **B2 IWM.** Critic (toward_market): price inconsistency ($279.14 vs $279.79); unsourced prediction-market odds; VIX-relief and surprise double-counted; macro data (ADP/ISM) underweighted; magnitudes exceed 0.52% base rate Supervisor (+0.24): +0.24pp to -0.05%: cannot be risk-off while B1 is positive and VIX craters; brings to ~flat, well inside 0.52% typical.
- **B3 NVDA.** Critic (toward_market): unsourced '75% priced' figure repeated across panel; election effect double-counted with macro/AMD/oversold-bounce drivers; two-observation midterm base rate shows no party-sign relationship; R-sweep probability and payoff both overstated; export-control risk… Supervisor (+0.24): +0.24pp to 0.00%: highest-beta name should not be negative on a vol-crush day; 3 Nov tape was an AI-trade rebound. Keeps NVDA >= IWM.
- **B4 VIX.** Critic (toward_market): 20.51 vs 20.83 close conflict unresolved; '75% priced' unsourced; tech-correction vol double-counted as election premium; 2022 (+0.55) base rate underweighted; Sonnet's D-sweep logic inverted Supervisor (+0.7): +0.7pt to -1.2: -1.9 is ~3x typical daily move and implies SPY +0.6-1.0%, contradicting the panel's own IWM/NVDA. Close unverified (20.51 vs 20.83) and 2022 midterm was +0.55.
- **B5 US 2-year.** Critic (toward_market): Panel's '75% priced D sweep' is a misread of the December Fed hike probability — no election odds are sourced; D sweep implausible from 53-47 Senate; R-sweep fiscal effect double-counted with relief rally despite being a long-end story; midterm base rate (+3,… Supervisor (+0): No change: no Fed speakers, no auctions, payrolls Friday; -0.8bp is modest and well inside 3bp typical.
- **B6 US 10-year.** Critic (toward_market): unsourced 75% priced figure; presidential analogues misapplied to midterms where incumbency unchanged; R-sweep = status quo not new fiscal expansion; gridlock+risk-off double-counted; ADP/ISM likely dominate a 4bp-vol day Supervisor (+0.3): +0.3bp to -1.4bp: trims bull-flattening that over-rallies the long end against a risk-on/vol-crush day; gridlock long-end story still justifies 10y leading 2y.
- **B7 UK 10-year gilt.** Critic (toward_market): 3 Nov close unverified (last data 30 Oct); BoE hike double-counted as drift though already priced; Opus's all-positive grid ignores negative-skewed base rate; +3bp R sweep exceeds all scaled precedents; breadth claim contradicts 'multi-week lows' Supervisor (-0.2): -0.2bp to -0.3bp: -0.1 implies only ~6% Treasury pass-through vs typical 0.4-0.6 beta; partly offset by the widely expected 5 Nov BoE hike (Sept CPI 3.5%), so only a small shift. 3 Nov gilt close unverified (last data…
- **B8 Gold (Dec 26).** Critic (toward_market): likely wrong 'December hike' probability inherited panel-wide; undated 75% D-sweep pricing; presidential-election magnitudes applied to midterms; double-counted uncertainty premium; R-sweep downside overstated Supervisor (+0): No change: +0.19% is consistent with 1-2bp lower yields and sits inside 0.67% typical.
- **B9 WTI (Dec 26).** Critic (toward_market): mis-stated 3 Nov move (+0.39% not +2.1%); unsourced '75% priced' claim used both to justify and negate reaction; Gemini double-counts 2018 analog with Iran channel; weak congressional transmission to strike policy; EIA inventory print likely dominates and is… Supervisor (+0): No change: mild decline alongside positive equities is coherent given the Iran peace-talk channel and an election-orthogonal EIA print; note 3 Nov was ~+0.39%, not +2.1%.
- **B10 Henry Hub (Dec 26).** Critic (toward_market): contract/price inconsistency ($2.89/$2.95/$3.39) unresolved; stale COT and storage data presented as current; presidential analogs over-weighted vs 2018 midterm base rate of 0.00%; executive permitting authority unchanged by Congress, so R-sweep premium… Supervisor (+0): No change: weather-driven, 1.81% typical move swamps any election signal; no cross-asset constraint binds.

---

## 5. Safeguards: where a bad model output gets caught

| Risk | Safeguard |
|---|---|
| The panel anchors on the market | Market prices are withheld from the panel; the critic flags any that leak into the research (MI-04) |
| One model is wrong or invents a fact | Median of four forecasters from three model families; the critic flags unsourced figures (an invented "D+8.5 wave"); the supervisor confirms or refutes them |
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
8. **Stronger models for the final run (run 4).** Claude Sonnet 5 scouts instead of Gemini 3.8 Flash, Claude Opus 5 added to the panel, and Claude Opus 5 as critic and final. Up to 25 parallel calls per stage. The constants are unchanged.
9. **Ignore swarm outputs in git.** `swarm_out/` and `swarm_*.log` were added to `.gitignore`, so later runs aren't flagged as having uncommitted changes.

The constants (`EXTREMIZE`, `MODEL_WEIGHT`, `W_IDIO`, `W_SHARED`, `DRIFT_SCALE`, `CAP_PTS`, `B_SHRINK`, `RHO`) didn't change, and none was tuned against today's answers.

---

## 7. Running it

```bash
# from the event repo folder (poros-foundry/forecast-the-future-2026) with swarm/ copied in
pip install -r requirements.txt
cp .env.example .env                                   # fill in OPENROUTER_API_KEY, TEAM_ID, SUBMIT_CODE, TEAM_NAME
git add swarm && git commit -m "swarm"                 # calls are tagged with the commit
python swarm/swarm.py --run test --questions A2,A6,B4  # cheap test (~$0.70)
python swarm/swarm.py --run 4                          # full run (~$7.65, ~3.5 min)
```

```python
import sys; sys.path.insert(0, "ai_only"); import ftf
answers = ftf.answers_from_finals(run=3)
ftf.submit(answers, run=3, dry_run=True)   # checks only
ftf.submit(answers, run=3)                 # the real submission
```

## 8. Data sources and tools

- The event data pack and its scripts: `code/`, `ai_only/ftf.py`, `ai_only/ftf_tools.py`. These fetch live Kalshi, Polymarket, US Treasury, Bank of England and Yahoo Finance data, falling back to the pack's files.
- OpenRouter models in the final run: Claude Sonnet 5, Claude Opus 5, GPT-6 Sol and Gemini 4 Argon (earlier runs also used Gemini 3.8 Flash and DeepSeek V4 Pro). Web search through OpenRouter (`online=True`).
- Our own Python (pandas and the standard library).
- No other APIs or data sources. Claude (Anthropic) helped write and review the code. No answer was set by hand.

## 9. Submission and run history

| | |
|---|---|
| **Final run** | `team-dsl-run-4`: one complete run of the pipeline above, from research to final, for all 25 questions |
| **Code** | git commit `8b781cf`, no uncommitted changes (recorded in `swarm_out/run-4/data_desk.json`) |
| **Submitted** | 21:47:22 GMT on 3 Nov 2026, submission `aebc7e4e-c54d-4545-9996-05470fb8bdfd`, **version 4**, team name Darkknight |
| **Answers** | Equal to the last final call of each question in run 4; the dry run raised no warnings |
| **After the run** | No model calls were made by any team machine |

Our team worked from two machines that shared one team key, so the earlier run labels overlap:
- **`run-1`** holds a swarm run from one machine (18:13–18:23 GMT, submitted at 19:12 as version 1) and a simpler two-model prototype (`ai_only/agent.py`) from the other (18:30–18:37 GMT).
- **`run-2`** is a swarm run (18:53–18:58 GMT) whose results led to the fixes in section 6.
- **`run-3`** is the fixed swarm with the original models (21:20–21:31 GMT). It was submitted as version 2, then as version 3 with the same answers and the team name Darkknight.
- **`test` and `swarm-test`** were small tests.

Run 4 replaces all of them.
