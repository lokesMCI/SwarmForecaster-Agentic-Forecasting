# HANDOFF: Forecast the Future 2026, AI-only track (team-dsl / "DarkKnight")

Read this first. It is the full state of the work as of **18:45 GMT, Tue 3 Nov 2026**. Hard deadline: **22:00 GMT** for both the submission and the README email.

## 1. The event in five lines
- 25 questions. **A1–A15**: probability (whole %, 1–99) that the Democrat wins 13 races, plus House and Senate control. **B1–B10**: move from the 3 Nov close to the 4 Nov close for SPY, IWM, NVDA (%), VIX (points), US 2y/10y and UK 10y (bp), gold, WTI and Henry Hub (%).
- Part A score: Brier gain over the market (the average of the Kalshi and Polymarket mids at 22:00 GMT). Part B score: |error| / typical daily move, capped at 5.
- £200 "agent process" prize, judged from traces: agent design (weighted most), evidence quality, stability, traceability and efficiency. Integrity and substantive forecasts are pass/fail.
- Brief: https://porosfoundry.ai/ftf-2026/participants-brief · Event repo: https://github.com/poros-foundry/forecast-the-future-2026 (read `ai_only/README.md`).

## 2. Rules that can disqualify us (non-negotiable)
1. **Every model call goes through `ftf.ask()` with a role.** Use only the approved OpenRouter models. Web search only via `online=True`.
2. **Data:** only the event data pack, its scripts (`code/`, `ai_only/ftf_tools.py`), our own code, and OpenRouter. **No other APIs or datasets** (no Kaggle, FRED, yfinance outside `ftf_tools`, etc.).
3. **Integrity:** the submission must be **the last run made before 22:00**, complete (all 25 questions, research through final), and each answer must match that question's last `final` call. **After the final run starts, make NO more `ftf.ask` calls of any kind, not even tests or a different run label.**
4. **Steer, don't dictate:** never put an answer in a prompt ("set Texas to 55%"). Changing the method is fine.
5. **Commit the code before the final run.** Every call is tagged with the git commit; uncommitted changes show as "dirty". Run from inside the event repo folder.
6. The final reply for each question ends with one JSON line: `{"answer", "own_estimate", "market_reference" (Part A only), "reason"}`.

## 3. Setup on the local machine
```bash
git clone https://github.com/poros-foundry/forecast-the-future-2026 ftf && cd ftf
pip install -r requirements.txt
# copy this repo's swarm/ folder into ftf/swarm/
# create ftf/.env (never commit it); the swarm script loads it:
#   OPENROUTER_API_KEY=<team key>   TEAM_ID=team-dsl   SUBMIT_CODE=<code>
#   TEAM_NAME=DarkKnight   FTF_TEST_MODE=1
printf '\n.env\nswarm_out/\nswarm_*.log\n' >> .gitignore
git add -A && git commit -m "Add team-dsl swarm"
```
The credentials are in the organisers' email to the user; they are deliberately not in this file.
Optional: copy `run1_artifacts/` from the handoff zip into `ftf/`. It contains `.ftf/runs/team-dsl-run-1.jsonl`, `answers/` and `swarm_out/run-1/`, which you need only if you want to resubmit run 1 with `submit()` from the new machine.

## 4. What is DONE
- **Research.** Key findings that shaped the design:
  - **AIA Forecaster (arXiv 2511.07678):** an LLM alone scored Brier 0.126 against a liquid market's 0.111; a blend of about ⅔ market + ⅓ model scored 0.106. Agentic search beat one-shot search. A supervisor that reconciles the agents' *reasoning* worked better than an LLM averaging their numbers. LLMs hedge toward 50%, so Platt scaling (extremizing) helps.
  - **Metaculus FutureEval and other 2026 reviews:** 86% of winning bots ensembled, and capping extreme predictions helped.
- **Pipeline** `swarm/swarm.py` + `swarm/data_desk.py` (run: `python swarm/swarm.py --run <label> [--questions A1,B4]`):
  0. **Data desk (code only).** Market mids, the Kalshi–Polymarket gap, spread, 1-day and 7-day drift. Four control scenarios from the A14/A15 markets (Gaussian copula, ρ=0.8). For Part B: latest closes, the scorer's typical daily move, and the moves after the 2016–2024 election days.
  1. **Scouts (`research`, Gemini 3.8 Flash, online).** Five shared `general` briefs (national, senate, house, electionday, macro) plus one targeted brief per question.
  2. **Panel (`forecast`).** Sonnet 5, GPT-6 Sol and Gemini 4 Argon forecast independently. Part A forecasters are **blind to market prices**. For Part B each gives a move conditional on each scenario.
  3. **Critic (`critique`, DeepSeek V4 Pro).** An adversarial review that now sees the market.
  4. **Supervisors (`aggregate`, Opus 5).** One review across all of Part A for coherence, one across all of Part B; adjustments are bounded.
  5. **Code aggregation.**
     - **Part A:** log-odds median of the panel, ×1.25 extremize. The gap to the market is split into a **shared** part (median across races, weight 0.10) and a **race-specific** part (weight 0.33). Both are damped by 1/(1+|1-day drift|/0.05). The result is capped at ±6 points from the market.
     - **Part B:** median of the panel's scenario-mixture medians, ×0.8 shrink toward zero, **unless** at least 80% of past election-day moves share the forecast's sign.
  6. **Final (`final`, Sonnet 5, temperature 0).** One call per question; the JSON line is required.
- **Test run** `test1` (A1, A13, A15, B4): $0.67. It showed the panel sitting systematically on the Republican side of the market (Texas 47 vs 72), which led to the shared/race-specific split.
- **Full run 1** (all 25 questions): 11 minutes, $3.79, dry run clean with no warnings. Answers:
  `A1 69, A2 72, A3 83, A4 73, A5 51, A6 63, A7 69, A8 71, A9 65, A10 41, A11 57, A12 58, A13 76, A14 95, A15 74, B1 -0.03, B2 -0.25, B3 -0.04, B4 -1.4, B5 -1.8, B6 -1.5, B7 -0.7, B8 0.12, B9 0.3, B10 0.18`
  Market at 15:00: A1 72, A2 72, A3 80, A4 72, A5 52, A6 63, A7 70, A8 76, A9 68, A10 40, A11 61, A12 59, A13 78, A14 94, A15 76.
- **Fixes after run 1 (committed, not yet run):**
  - (a) The model context now says races are mostly called overnight, before the 4 Nov US open. A run 1 final call wrongly assumed results would not be known by then.
  - (b) The Part B no-shrink rule for repeated election-day effects. It matters mainly for VIX: −3.5 to −6 points after 4 of the 5 past elections.
- **README for the organisers:** `team-dsl.md` (the text is also in this repo's README.md).
- Budget: **$26.21 of $30 left** at 18:30.

## 5. What is NOT done: TO DO in order
1. **Submit run 1 as a safety entry, NOW.** The cloud sandbox could not reach `porosfoundry.ai`, so nothing has been submitted yet. Option (a) sends the exact same request `submit()` makes, so it does not need a Python setup:
   - (a) `curl -sS -X POST https://porosfoundry.ai/api/ftf-2026/submit-test -H 'Content-Type: application/json' -d '{"team":"team-dsl","code":"<SUBMIT_CODE>","track":"ai-only","run":"team-dsl-run-1","team_name":"DarkKnight","answers":{"A1":69,"A2":72,"A3":83,"A4":73,"A5":51,"A6":63,"A7":69,"A8":71,"A9":65,"A10":41,"A11":57,"A12":58,"A13":76,"A14":95,"A15":74,"B1":-0.03,"B2":-0.25,"B3":-0.04,"B4":-1.4,"B5":-1.8,"B6":-1.5,"B7":-0.7,"B8":0.12,"B9":0.3,"B10":0.18}}'`. If that returns a receipt, repeat it with `/submit` in place of `/submit-test`.
   - (b) With the run 1 artifacts copied in: `FTF_TEST_MODE=0`, then `ftf.submit(ftf.answers_from_finals(1), run=1)`.
2. **Check live data works locally:** `python -c "import sys;sys.path.insert(0,'ai_only');import ftf_tools;print(ftf_tools.get_market_odds('A1',days=1)['source'])"` should print `live`. In the cloud it always fell back to the data pack, whose last row is 15:00.
3. **Optional improvements (only before about 20:45; one quick `--run test2 --questions A1,A13,B4` check, then commit):**
   - Part A: today's odds moved a lot (A13 went from 64 to 78 on 3 Nov). With live data the 1-day drift damping will work properly.
   - Consider asking the A-supervisor for an explicit seat count (Democrats need 51; list the other competitive seats) to check A15.
   - Nice to have for the stability criterion: run the final step twice with role `forecast`, then make one `final`. Do not make two `final` calls.
4. **FINAL RUN at about 21:05 GMT** (after the 21:00 US close, so Part B uses the real 3 Nov close):
   `git status` clean → `python swarm/swarm.py --run 2 > swarm_run2.log 2>&1` (about 11 minutes, about $4).
5. **Submit by about 21:25:** set `FTF_TEST_MODE=0`, then
   ```python
   import os,sys; sys.path.insert(0,'ai_only'); import ftf
   a = ftf.answers_from_finals(2); ftf.submit(a, run=2, dry_run=True); ftf.submit(a, run=2)
   ```
   Keep the receipt. If a question's answer is None, **re-run only that question under the same run label** (`--run 2 --questions A7`), never type a number in by hand.
6. **Email the README by 22:00:** `ftf.email_readme("team-dsl.md")` (subject **"FTF US Midterms README team-dsl"**) and attach the `swarm/` code. Add one line to the README saying the final run label is `run-2`.
7. **Stop.** No more model calls after the final run.

## 6. Known risks and gotchas
- Reasoning models count thinking against `max_tokens`. Calls pass `extra_body={"reasoning":{"effort":"low"}}`, and `call()` retries an empty reply twice.
- The critic stage was slow in run 1 (about 6 minutes). A full run takes about 11 minutes, so start the final run by 21:10 at the latest.
- If submission fails, `submit()` saves `answers/answers_<run>_<time>.csv`. If the server is down at the deadline, email that file to events@porosfoundry.ai with the subject "FTF US Midterms submission team-dsl".
- The API key was pasted in a chat; keep it only in `.env` (git-ignored). Tell the organisers if it may have leaked.
- Prompt for the new Claude Code session: *"Read HANDOFF.md. Do §5 in order. Respect §2 strictly. Ask before any action that sends a submission or an email."*
