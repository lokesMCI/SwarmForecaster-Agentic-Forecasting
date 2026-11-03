# SwarmForecaster: agentic forecasting swarm (Forecast the Future 2026, team-dsl / Darkknight)

**Setup.** Clone the event repo [poros-foundry/forecast-the-future-2026](https://github.com/poros-foundry/forecast-the-future-2026), copy `swarm/` into it, fill in `.env` from `.env.example`, then run `python swarm/swarm.py --run <n>` from the event repo folder. The data pack is not included here because the organisers ask that it not be redistributed.

**Idea.** Recent work on LLM forecasting shows LLMs alone trail liquid markets, but a market-anchored blend beats them (AIA Forecaster, arXiv 2511.07678: ≈⅔ market + ⅓ model). We are scored on Brier gain over the market, so the swarm forms an independent view and moves away from the market only by a bounded, rule-based amount. Code: `swarm/swarm.py`, `swarm/data_desk.py`; the outputs of every stage are saved under `swarm_out/run-<n>/`.

**Pipeline (all model calls go through `ftf.ask` with a role).**
1. **Data desk (code, no model calls).** Kalshi and Polymarket mids, venue gap, spread, 1-day and 7-day drift (via `ftf_tools.get_market_odds`). Four control scenarios from the House and Senate control markets, using a Gaussian copula with ρ=0.8. For Part B: latest closes, the scorer's typical daily move (median absolute change over the 60 days to 30 Oct), and each instrument's move after the 2016–2024 election days.
2. **Scouts (`research`, `online=True`, Gemini 3.8 Flash).** Five shared angle briefs tagged `general` (national environment, Senate map, House, Election Day news, macro). One targeted, dated and sourced brief per question.
3. **Panel (`forecast`).** Claude Sonnet 5, GPT-6 Sol and Gemini 4 Argon forecast independently. For Part A they are **blind to market prices**, so they don't anchor on them. For Part B each gives a move conditional on each control scenario.
4. **Critic (`critique`, DeepSeek V4 Pro).** An adversarial review that now sees the market. It flags stale facts and double counting, and judges whether the gap to the market is justified.
5. **Supervisors (`aggregate`, Claude Opus 5).** One review across all of Part A for coherence (race outcomes vs Senate and House control, shared polling error). One across Part B for consistency (risk-on/off, the yield curve, gilts vs Treasuries). Adjustments are bounded.
6. **Aggregation (code).**
   - **Part A:** log-odds median of the panel, extremized ×1.25 to correct LLM hedging. The gap to the market is split into a **shared component** (the median gap across races, weight 0.10) and a **race-specific component** (weight 0.33). Both weights are damped when the market moved sharply in the last day, because the market has fresh information. The result is capped at 6 points from the market.
   - **Part B:** median of each panelist's scenario-mixture median (absolute-error scoring rewards the median), shrunk ×0.8 toward zero, unless at least 80% of past election-day moves share its sign (a repeated effect such as the post-election VIX drop).
7. **Final (`final`, Claude Sonnet 5, temperature 0).** One call per question. It sees the whole record and the method's recommendation, and ends with the required JSON line (`own_estimate`, `market_reference`, `reason`).

**Stability.** Every constant was fixed before the scored run and the final calls use temperature 0. Aggregation is a median across three different models, and the code steps are deterministic.

**Data sources and tools.** The event data pack and its scripts (`code/`, `ai_only/ftf_tools.py`, live data with fallback to the pack's files), OpenRouter models and OpenRouter web search (`online=True`), plus our own Python (pandas). No other APIs or data. Development help: Claude (Anthropic) wrote and reviewed the code. No answers were set by hand.

---

## Status (3 Nov 2026, 19:30 GMT)

**Submitted.** Run 1 was submitted to the AI-only track at 19:12:53 GMT.

| | |
|---|---|
| `submission_id` | `05a121a0-c40a-4fd3-919e-b901cbd221e2` |
| version | 1 |
| answers | 25 / 25 |
| payload hash | `879bae30…18ad9e0` |

Receipts and the exact submitted payload are in `run1_artifacts/receipts/` and
`run1_artifacts/answers/`. The test endpoint was called first and returned the same
payload hash, so what landed is what was verified. `answers_from_finals(1)` matches
every one of the 25 last `final` calls, and `ftf`'s own run checks return no warnings.

**Run 1 answers.** `A1 69, A2 72, A3 83, A4 73, A5 51, A6 63, A7 69, A8 71, A9 65,
A10 41, A11 57, A12 58, A13 76, A14 95, A15 74, B1 -0.03, B2 -0.25, B3 -0.04, B4 -1.4,
B5 -1.8, B6 -1.5, B7 -0.7, B8 0.12, B9 0.3, B10 0.18`

**Known limitation of run 1.** It ran in a sandbox that could not reach the live odds
feed, so every Part A snapshot fell back to the data pack and is stamped
`"source": "data kit files (live download failed)", "as_of": "2026-11-03 15:00"`
(visible in `run1_artifacts/swarm_out/run-1/data_desk.json`). Two consequences:
the 1-day drift damping in `blend_a` had no fresh day to measure, and Part B was
forecasting moves from closes it had to infer rather than observe. Live data has since
been confirmed working, and the market has moved: A15 0.76 → 0.74, A14 0.94 → 0.939.

**Change made after run 1, not yet exercised in a scored run.** Run 1's Part A
supervisor did Senate seat arithmetic unprompted, and it was the sharpest step in the
trace — *"our recommended race probs imply ~3.9 expected pickups plus an 82% MI hold,
which cannot support 75"* — which moved A15 down 2 points. That was incidental, so
`senate_seat_math` is now a required field of the supervisor's output, with
`max_tokens` raised to 7000 for headroom. If it fails to parse, adjustments fall back
to 0, so it degrades safely.

**Budget.** The real OpenRouter spend is **$14.29 of $30, leaving $15.71** — not the
~$4.46 implied by summing the per-call costs `ask()` prints. The gap is most likely the
`online=True` web-search surcharge on the 30 research calls, which is not in the
per-call token price. The run log records no cost field, so there is no per-call audit
trail. A full 182-call run therefore costs roughly $12–13: affordable once, with no
room for a retry.

## Running it locally

The system Python on macOS may be too old for `pandas==3.1.0` (needs ≥ 3.11):

```bash
uv venv --python 3.13 .venv && uv pip install -r requirements.txt
```

Run from inside the event repo folder, with `swarm/` copied in and `.env` present
(`swarm.py` reads `../.env` relative to itself at import). `.env` is git-ignored and
is never committed.

## What is deliberately not in this repository

- `.env` — the OpenRouter key and submission code.
- The event **data pack** (`data/`, and the organisers' `ai_only/` and `code/`
  helpers). The organisers ask that it not be redistributed, so only our own derived
  figures appear, inside our trace files.
