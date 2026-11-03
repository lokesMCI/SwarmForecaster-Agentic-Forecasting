# SwarmForecaster: team-dsl (Darkknight), FTF 2026 AI-only track

**Final run: `team-dsl-run-4`.** Our submission is run 4, the last run made before 22:00 GMT on 3 Nov. It is one complete run of the pipeline below, covering all 25 questions from research to final. Code: `swarm/swarm.py` and `swarm/data_desk.py`, run with `python swarm/swarm.py --run 4` (repo: github.com/lokesMCI/SwarmForecaster-Agentic-Forecasting). Two team machines shared one team key, so the earlier labels `run-1` and `run-2` mix calls from both machines. Run 4 replaces every earlier run.

**Idea.** LLMs alone trail liquid markets, but a market-anchored blend beats them (AIA Forecaster, arXiv 2511.07678). We are scored on Brier gain over the market, so the swarm forms an independent view and moves away from the market only by a bounded, rule-based amount.

**Pipeline (every call goes through `ftf.ask` with a role).**
1. **Data desk (code).** Kalshi and Polymarket odds, venue gap, spread and drift; four House/Senate control scenarios from the chamber markets (Gaussian copula); for Part B, the typical daily move and moves after the 2016–2024 elections.
2. **Scouts (`research`, Claude Sonnet 5 with web search).** Five shared briefs plus one dated, sourced brief per question. They never report market odds, so the panel stays blind.
3. **Panel (`forecast`).** Claude Opus 5, Claude Sonnet 5, GPT-6 Sol and Gemini 4 Argon. In Part A they are blind to market prices; in Part B each gives a move for each control scenario.
4. **Critic (`critique`, Claude Opus 5).** An adversarial review that sees the market. It flags stale facts and double counting, and judges whether the gap to the market is justified.
5. **Supervisors (`aggregate`, Claude Opus 5).** Coherence across all of Part A (including the Senate seat arithmetic) and consistency across all of Part B, with bounded adjustments.
6. **Aggregation (code).** Part A: the panel's log-odds median, extremized ×1.25. The gap to the market is split into a shared part (weight 0.10) and a race-specific part (weight 0.33), damped after sharp market moves, capped at 6 points, and never crossing the market against our own view. Part B: the median of the scenario-mixture medians, shrunk ×0.8 unless 80% of past election moves share its sign.
7. **Final (`final`, Claude Opus 5, temperature 0).** Keeps the method's answer unless there is a named error, and ends with the required JSON line.

Replies that come back cut off or without their JSON are retried with a larger token budget, and every retry is traced. `swarm_out/run-4/` records the commit, models and constants.

**Data sources and tools.** The event data pack and its scripts (`code/`, `ai_only/ftf.py`, `ai_only/ftf_tools.py`); OpenRouter models and OpenRouter web search (`online=True`); our own Python (pandas). No other APIs or data. Claude (Anthropic) helped write and review the code. No answers were set by hand. Full details are in `README_DETAILED.md`.
