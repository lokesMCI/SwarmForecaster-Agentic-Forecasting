# SwarmForecaster: detailed README

**Forecast the Future 2026, US Midterm Election Night Edition. AI-only track, team-dsl (DarkKnight).**

This document explains how the swarm reaches each of its 25 answers (A1–A15 and B1–B10): what evidence it uses, who checks it, and what limits stop any one model from pushing an answer too far. The short README is in `README.md`. This file is the detailed version.

The worked numbers come from **run 2 (3 Nov 2026, about 18:53 GMT)**. The scored run is the last one before 22:00 GMT, so its numbers will differ slightly as the markets move. The method doesn't change.

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

A full run is about 165 model calls, takes about 5½ minutes and costs about $3.20.

---

## 3. Stage by stage

### Stage 0: data desk (`swarm/data_desk.py`, code only)

For every Part A question:
- **Kalshi mid and Polymarket price**, and their average (the scorer's benchmark `m`).
- **Venue gap** (Kalshi minus Polymarket), **Kalshi spread** (liquidity) and **7-day drift**, so later stages know whether the market has just moved on fresh news.
- **Daily mids** for the past 8 days, from which the 1-day drift is computed.

Across Part A, it also builds **four control scenarios** from the House (A14) and Senate (A15) control markets, using a Gaussian copula with correlation ρ = 0.8. The two chambers move together in a wave, so treating them as independent would be wrong. Run 2 gave:

| D sweep | D House / R Senate | R sweep | R House / D Senate |
|---|---|---|---|
| 72.3% | 21.3% | 5.9% | 0.5% |

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
   - **Shared part**: the median gap across all races. The blind panel leans the same way in almost every race (in run 2 it sat below the market in 13 of 15), and that's a national-level bet. The House and Senate control markets aggregate the national picture better than we do, so it gets a **small weight (0.10)**.
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

## 4. How each question is answered

The tables show run 2's numbers.
- **Panel** is the three blind forecasts (Sonnet 5, GPT-6 Sol, Gemini 4 Argon).
- **Own** is our own estimate after extremizing and the supervisor's adjustment.
- **Method** is stage 5's answer (shown with the no-crossing rule applied).
- **Final** is what run 2's final call submitted, which in some races differs from the method. This is the problem the stricter final prompt now fixes (see section 6).

### Part A: Senate races (A1–A7)

| Q | Race | Market (Kalshi / Poly) | Panel | Own | Method | Final (run 2) |
|---|---|---|---|---|---|---|
| A1 | Texas | 72.0 (71.5 / 72.5) | 40, 63, 57 | 56.7 | 71 | 71 |
| A2 | Maine | 69.0 (67.5 / 70.5) | 55, 62, 56 | 55.5 | 69 | 63 |
| A3 | Michigan | 77.0 (76.5 / 77.5) | 72, 82, 76 | 80.9 | 80 | 80 |
| A4 | Ohio (special) | 72.0 (71.5 / 72.5) | 33, 38, 34 | 27.4 | 66 | 68 |
| A5 | Iowa | 50.0 (49.5 / 50.5) | 45, 46, 46 | 45.0 | 50 | 47 |
| A6 | Kansas | 63.0 (61.5 / 64.5) | 38, 53, 48 | 45.5 | 61 | 61 |
| A7 | Alaska | 70.5 (70.5 / 70.5) | 45, 57, 54 | 55.0 | 69 | 69 |

What makes each one different:

- **A1 Texas.** The widest panel split in the Senate set (40 to 63). The critic argued with high confidence that the market overweights narrow polling leads in an R+14 state with a history of polls understating Republicans. The supervisor took off 2 points for correlated red-state error, keeping A1 consistent with A15. Because most of the gap is the shared national bet, the method stays close to the market (71).
- **A2 Maine.** A late-substituted Democratic nominee against Susan Collins, who has a record of beating her polls. The critic flagged that every poll was more than a week old and that the national mood was double counted. The market's 7-day drift (+7.5 points) cut our weight to 0.59 of normal, because the market had moved on news our scouts lacked. The method returns the market (69). Run 2's final went to 63 by splitting the difference, which the stricter final prompt now forbids.
- **A3 Michigan.** The one race where the blind panel sat **above** the market (own 80.9 against 77). The supervisor confirmed that a 3 Nov cross-endorsement was a real, dated fact. The method moves up 3 points to 80, in the direction of our own evidence.
- **A4 Ohio special.** The largest disagreement in Part A: the panel said 33–38% in an R+10 state, against a market of 72%. The critic warned that the panel leaned on stale ratings and ignored the effect of a wave on an appointed incumbent. The supervisor called it the weakest link in the Senate ladder. The method moves 6 points, the cap, to 66. The no-crossing rule and the cap stop a big model bet against a liquid market.
- **A5 Iowa.** A true toss-up market (50). The panel was unanimous at 45–46. Before the no-crossing fix, the shared-gap arithmetic pushed the answer **above** the market to 52, against our own view. The fix holds it at the market (50), and the run 2 final correctly spotted the original problem. The critic also caught an invented "D+8.5 wave" figure and a misread fundraising edge.
- **A6 Kansas.** No Democrat has won a Kansas Senate race since 1932. The critic made that base-rate case, and the supervisor took off 2 points ("tied polls do not imply 63%"). The 7-day drift (+22 points) is large, so the method moves only 2 points below the market, to 61.
- **A7 Alaska.** Ranked-choice voting, and both venues exactly agree (70.5). The supervisor noted that the count may take days; questions not called by 9 Nov are dropped. The method sits 1.5 points below the market, at 69.

### Part A: House races (A8–A13)

| Q | District | Market (Kalshi / Poly) | Panel | Own | Method | Final (run 2) |
|---|---|---|---|---|---|---|
| A8 | FL-14 | 73.0 (71.5 / 74.5) | 55, 53, 53 | 51.7 | 71 | 65 |
| A9 | FL-22 | 64.5 (63.5 / 65.5) | 52, 48, 48 | 45.5 | 64 | 58 |
| A10 | ME-02 | 40.8 (42.0 / 39.5) | 38, 42, 35 | 35.2 | 41 | 42 |
| A11 | MI-04 | 60.5 (61.5 / 59.5) | 42, 44, 42 | 40.0 | 58 | 58 |
| A12 | MT-01 | 59.2 (59.0 / 59.5) | 52, 58, 52 | 52.5 | 59 | 60 |
| A13 | VA-01 | 80.0 (80.5 / 79.5) | 52, 52, 48 | 50.5 | 79 | 79 |

- **A8 FL-14.** A redrawn Trump+10.5 district with no district polling. The critic said with high confidence that the market prices a generic wave. The method moves 2 points (71). Run 2's final went to 65, an override the new prompt removes.
- **A9 FL-22.** R+4 PVI, Trump+11, Tilt R rating, and a Republican fundraising lead. The market had a **negative** 7-day drift, and its 1-day move cut our weight to 0.34. The method moves only half a point (64).
- **A10 ME-02.** The only House race priced **below 50%**, and the one with the largest venue gap (Kalshi 2.5 points above Polymarket) and a 2-cent spread, the thinnest market here. Ranked-choice voting applies. The panel agreed with the market's direction (35). The no-crossing rule keeps the method at 41: our view is below the market, so the answer can't sit above it.
- **A11 MI-04.** The critic found that the panel had anchored on a **stale Kalshi figure of about 40%** that had leaked into the research, while the live market is 60.5. It is a clear case of the critic protecting the blind panel's independence. The method stays 2.5 points below the market (58).
- **A12 MT-01.** A late Montana State University poll and a Libertarian spoiler, plus a +14 point 7-day drift. The critic said the panel was slow to react. The method stays at the market (59).
- **A13 VA-01.** The market moved **+16.7 points in 7 days** to 80%, and the 1-day drift cut our weight to 0.24, the smallest of any race. The panel (about 50%) hadn't seen whatever moved the market. The method sits 1 point below the market (79). This is the drift damping doing exactly its job.

### Part A: chamber control (A14–A15)

| Q | Chamber | Market (Kalshi / Poly) | Panel | Own | Method | Final (run 2) |
|---|---|---|---|---|---|---|
| A14 | House (218+) | 93.7 (92.95 / 94.5) | 92, 94, 91 | 95.5 | 95 | 95 |
| A15 | Senate (51+) | 73.0 (72.5 / 73.5) | 55, 55, 68 | 54.2 | 71 | 71 |

- **A14 House.** The most liquid market (0.1-cent spread) and the closest agreement with the panel. Extremizing the panel median (92) gives 95.5. The supervisor checked it against the scenario probabilities (D House = 93.6%). The method answer is 95.
- **A15 Senate.** The supervisor checked it against the race answers as a seat ladder. Expected Democratic flips are about 4.5 against 4 needed. Michigan hold risk and the correlated overpricing of red states justify sitting slightly under the market. The method answer is 71. It's consistent with the race answers, which mostly sit 1–3 points under their markets.

### Part B: market questions (B1–B10)

| Q | Instrument | Unit | Typical move | Past election nights (2016, 2018, 2020, 2022, 2024) | Panel mixture medians | Own | Shrink | Answer |
|---|---|---|---|---|---|---|---|---|
| B1 | SPY | % | 0.45 | +1.1, +2.1, +2.2, −2.1, +2.5 | −0.63, +0.43, +0.58 | +0.43 | none (4 of 5 up) | +0.28 |
| B2 | IWM | % | 0.52 | +3.1, +1.8, +0.1, −2.8, +5.8 | −0.99, −0.20, −0.04 | −0.20 | ×0.8 | −0.03 |
| B3 | NVDA | % | 1.36 | −1.7, +1.3, +6.0, −5.7, +4.1 | −1.33, −0.06, +0.71 | −0.06 | ×0.8 | +0.03 |
| B4 | VIX | points | 0.64 | −4.4, −3.6, −6.0, +0.6, −4.2 | +1.42, −2.69, −1.66 | −1.7 | none (4 of 5 down) | −1.4 |
| B5 | US 2-year | bp | 3.0 | +3, +3, −3, −6, +8 | −4.3, −0.8, −1.3 | −1.3 | ×0.8 | −1.0 |
| B6 | US 10-year | bp | 4.0 | +19, 0, −12, −2, +16 | −5.2, −1.4, −1.4 | −1.4 | ×0.8 | −1.3 |
| B7 | UK 10-year gilt | bp | 2.76 | +0.4, +0.1, −6.1, −10.3, −1.2 | −2.5, −0.4, −0.9 | −0.9 | ×0.8 | −0.8 |
| B8 | Gold (Dec 26) | % | 0.67 | −0.1, +0.2, −0.7, −0.1, −2.7 | +0.32, +0.18, +0.15 | +0.18 | ×0.8 | +0.14 |
| B9 | WTI (Dec 26) | % | 1.87 | +0.6, −0.9, +4.0, −3.5, −0.4 | +0.97, +0.10, +0.22 | +0.22 | ×0.8 | +0.18 |
| B10 | Henry Hub (Dec 26) | % | 1.81 | +2.2, 0.0, −0.4, −4.5, +2.9 | +0.45, +0.11, +0.18 | +0.18 | ×0.8 | +0.14 |

Run 2's final calls kept the method's answer for all ten Part B questions.

- **B1 SPY.** Equities rose after 4 of the last 5 elections, so there was no shrink. The supervisor trimmed +0.43 to +0.28 because a gain of nearly one typical move doesn't fit flat or negative IWM and NVDA forecasts. That's the cross-question consistency check at work.
- **B2 IWM.** Small caps are the most sensitive to policy. The panel's D sweep moves ranged from −1.3 to −0.35. The critic called −1.3 double counting of tax fears for an outcome already 72% priced, and the supervisor lifted the answer to about 0.
- **B3 NVDA.** The highest-volatility instrument (typical move 1.36%). The panel straddled zero. The critic noted that NVDA's 7% slide before the election had already priced some risk. The answer is essentially flat (+0.03).
- **B4 VIX.** The clearest repeated effect: the VIX fell after 4 of the last 5 elections as uncertainty resolved, so there was no shrink. One panellist predicted a spike on a D sweep, and the critic rejected it against that base rate. The supervisor softened −1.7 to −1.4, so it matches the trimmed equity gain and allows for Maine and Alaska ranked-choice counts leaving the Senate uncalled.
- **B5 and B6, Treasuries.** The answer is a mild bull flattening (2-year −1.0, 10-year −1.3), consistent with gridlock-style outcomes and with no FOMC meeting before 8–9 Dec. The critic flagged one panellist's −6 and −4bp as ignoring 2018's 0bp after an expected midterm result.
- **B7 UK gilt.** Kept at about 0.6× the move in Treasuries (−0.8bp), with no UK event until the 5 Nov MPC.
- **B8 Gold.** A small gain (+0.14%) that fits lower real yields and a softer dollar. The critic caught a stale intraday quote.
- **B9 WTI.** The critic flagged a stale price and noted that 2018 (a divided Congress) argues against a strong positive move. Shrinking gives +0.18%, well within the noise (typical move 1.87%).
- **B10 Henry Hub.** Mostly driven by weather, so the supervisor applied no cross-market constraint. The answer is a small +0.14%.

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
5. **Ignore swarm outputs in git.** `swarm_out/` and `swarm_*.log` were added to `.gitignore`, so later runs aren't flagged as having uncommitted changes.

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
