# team-dsl (Darkknight): a market-anchored forecasting swarm

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
