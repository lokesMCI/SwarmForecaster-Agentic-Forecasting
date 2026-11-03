"""team-dsl forecasting swarm for Forecast the Future 2026 (AI-only track).

Stages (every model call goes through ftf.ask with a role, so the run is fully traced):
  0 data desk   (code)      market snapshots, scenario probabilities, instrument statistics
  1 scouts      research    shared angle research (question "general", online) + one targeted scout per question
  2 panel       forecast    3 different models, Part A forecasters are blind to market prices
  3 critic      critique    adversarial review of the panel per question
  4 supervisor  aggregate   one cross-question consistency review for Part A, one for Part B
  5 aggregate   (code)      log-odds median -> extremize -> market blend with a cap (A); scenario-mixture median (B)
  6 final       final       one call per question, ends with the required JSON line

Usage:  python swarm/swarm.py --run 1 [--questions A1,A13,B4]
"""
import argparse
import concurrent.futures as cf
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist, median

ROOT = Path(__file__).resolve().parent.parent
for line in (ROOT / ".env").read_text().splitlines():  # load team settings
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))  # KEY="value" is common
sys.path.insert(0, str(ROOT / "ai_only")); sys.path.insert(0, str(ROOT / "swarm"))
import ftf  # noqa: E402
import data_desk  # noqa: E402

M = ftf.APPROVED_MODELS
SCOUT = M["Claude Sonnet 5"]                  # cheap, online research
PANEL = [M["Claude Opus 5"], M["Claude Sonnet 5"], M["GPT-6 Sol"], M["Gemini 4 Argon"]]  # diverse forecasters
CRITIC = M["Claude Opus 5"]
SUPERVISOR = M["Claude Opus 5"]
FINAL = M["Claude Opus 5"]

# Aggregation constants (fixed method, set before seeing any of today's answers)
EXTREMIZE = 1.25      # log-odds multiplier; LLM forecasts hedge toward 50% (AIA Forecaster, Platt scaling)
MODEL_WEIGHT = 0.33   # weight on our own estimate vs market in log-odds (AIA: market ~0.67 on liquid markets)
W_IDIO = 0.33         # weight on the race-specific part of our disagreement with the market
W_SHARED = 0.10       # weight on the part shared by every race (a national-environment bet the liquid
                      # chamber markets aggregate better than we do; correlated across all 15 questions)
DRIFT_SCALE = 0.05    # a 1-day market move of 5 points halves our weight: the market has fresh information
CAP_PTS = 6           # max distance from the market, percentage points
B_SHRINK = 0.8        # shrink Part B mixture medians toward zero (daily moves are mostly noise)
RHO = 0.8             # House/Senate outcome correlation for scenario probabilities

LOW = {"reasoning": {"effort": "low"}}
# Keeps the Part A panel blind: in run 2 a stale Kalshi price reached the MI-04 panel through research.
NO_ODDS = (" Do not report prediction-market or betting prices (Kalshi, Polymarket, PredictIt or similar); "
           "the team reads those separately.")
NOW = datetime.now(timezone.utc)
CONTEXT = (f"Current time: {NOW:%A %d %B %Y, %H:%M} UTC. This is US Election Day for the 2026 midterms; "
           "polls close from 23:00 UTC on 3 Nov and most races are called overnight by AP and the networks, so "
           "results are largely known before US markets reopen at 14:30 UTC on 4 Nov (close-race and ranked-choice "
           "counts in Maine and Alaska can take days). No results are known yet.Republicans hold the White House, the "
           "Senate 53-47 (47 includes 2 independents caucusing with Democrats; VP breaks ties for Republicans) "
           "and the House 218 R - 214 D, 1 independent, 2 vacancies. Use only facts you can date; say when a "
           "fact is older than one week. Never invent numbers.")

ANGLES = {
    "national": "National environment for the 2026 US midterms as of today: final generic-ballot averages, "
                "presidential approval, final forecasts from major modelers (e.g. Silver Bulletin, Cook, Sabato, "
                "Split Ticket, Economist), and how polls missed in 2018, 2020, 2022 and 2024.",
    "senate": "2026 US Senate battlegrounds as of today: latest polling averages and ratings for Texas, Maine, "
              "Michigan, Ohio (special), Iowa, Kansas, Alaska, and every OTHER competitive Senate race (list "
              "them, e.g. NC, GA, NH, NE, FL special). Which seats must Democrats flip to reach 51?",
    "house": "2026 US House battlegrounds as of today: forecast seat ranges, toss-up list, and the latest "
             "polls or ratings for FL-14, FL-22, ME-02, MI-04, MT-01 and VA-01. Note redistricting changes.",
    "electionday": "Election Day 3 Nov 2026 news so far: early vote and turnout reporting by state, any late "
                   "scandals, court rulings, weather or voting problems, and expected timing of results/calls "
                   "(including ranked-choice tabulation in Maine and Alaska).",
    "macro": "Financial markets on 3 Nov 2026: today's moves in US stocks, VIX, Treasuries, gilts, gold, oil and "
             "natural gas; scheduled data or Fed/BoE events on 4 Nov 2026; and analyst expectations for market "
             "reactions under each midterm outcome (D sweep, split, R sweep).",
}


def clip(p, lo=0.01, hi=0.99):
    return min(max(p, lo), hi)


def logit(p):
    p = clip(p, 1e-3, 1 - 1e-3); return math.log(p / (1 - p))


def inv(x):
    return 1 / (1 + math.exp(-x))


def last_json(text):
    """Last {...} object in a reply (panel and supervisor replies end with one)."""
    for m in reversed(list(re.finditer(r"\{[^{}]*(\{[^{}]*\}[^{}]*)*\}", text or "", re.S))):
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
    return None


def call(qid, role, prompt, model, run, online=False, max_tokens=2500, retries=2, check=None, **kw):
    """One traced model call. Retries on errors, empty replies and replies that fail `check` (usually a
    reply cut off by max_tokens before its JSON line: reasoning tokens count against it, which hit the
    DeepSeek critic); each retry doubles the token budget. Returns the last reply, even if it failed."""
    out = ""
    for attempt in range(retries + 1):
        try:
            out = ftf.ask(qid, role, [{"role": "system", "content": CONTEXT}, {"role": "user", "content": prompt}],
                          model, run, online=online, max_tokens=max_tokens, extra_body=dict(LOW), **kw) or ""
            if out.strip() and (check is None or check(out)):
                return out
            print(f"  {qid} {role} {model}: reply unusable (empty or no valid JSON), retrying")
        except Exception as e:  # noqa: BLE001
            print(f"  {qid} {role} {model} failed: {e}")
        if attempt < retries:
            max_tokens = min(2 * max_tokens, 12000)
            time.sleep(3 * (attempt + 1))
    return out


def has_keys(*keys):
    """check= for call(): the reply's last JSON object has every key."""
    return lambda txt: all(k in (last_json(txt) or {}) for k in keys)


class Swarm:
    def __init__(self, run, qids):
        self.run, self.qids = run, qids
        self.q = {q["id"]: q for q in ftf.load_questions()}
        self.out = ROOT / "swarm_out" / f"run-{run}"; self.out.mkdir(parents=True, exist_ok=True)
        self.state = {qid: {"question": self.q[qid]["text"]} for qid in qids}

    def save(self, name, obj):
        (self.out / name).write_text(json.dumps(obj, indent=2, default=str))

    # ---- stage 0: data desk ------------------------------------------------------------
    def data_desk(self):
        a_all = [f"A{i}" for i in range(1, 16)]
        with cf.ThreadPoolExecutor(8) as ex:
            snaps = dict(zip(a_all, ex.map(data_desk.market_snapshot, a_all)))
        self.snaps = snaps
        self.scen = data_desk.scenario_probs(snaps["A14"]["market_avg"], snaps["A15"]["market_avg"], RHO)
        for qid in self.qids:
            if qid.startswith("A"):
                self.state[qid]["market"] = snaps[qid]
            else:
                self.state[qid]["facts"] = data_desk.market_facts(qid)
        method = {"git_commit": ftf.GIT_COMMIT, "git_dirty": ftf.GIT_DIRTY, "started_utc": NOW.isoformat(),
                  "models": {"scout": SCOUT, "panel": PANEL, "critic": CRITIC, "supervisor": SUPERVISOR,
                             "final": FINAL},
                  "constants": {"EXTREMIZE": EXTREMIZE, "W_IDIO": W_IDIO, "W_SHARED": W_SHARED,
                                "DRIFT_SCALE": DRIFT_SCALE, "CAP_PTS": CAP_PTS, "B_SHRINK": B_SHRINK, "RHO": RHO}}
        if ftf.GIT_DIRTY:
            print("WARNING: uncommitted changes; every call in this run is tagged git_dirty. Commit first.")
        self.save("data_desk.json", {"method": method, "snapshots": snaps, "scenarios": self.scen,
                                     "facts": {q: s.get("facts") for q, s in self.state.items()}})
        print("scenario probabilities from chamber markets:", self.scen)

    # ---- stage 1: scouts -----------------------------------------------------------------
    def scouts(self):
        def angle(item):
            name, brief = item
            return name, call("general", "research", brief + "\nReturn a dense, dated, sourced brief "
                              "(bullet points, each with date and source URL), max 450 words." + NO_ODDS, SCOUT,
                              self.run, online=True, max_tokens=3000)
        with cf.ThreadPoolExecutor(5) as ex:
            self.briefs = dict(ex.map(angle, ANGLES.items()))
        self.save("briefs.json", self.briefs)

        def targeted(qid):
            text = self.q[qid]["text"]
            if qid.startswith("A"):
                ask = (f"Research this 2026 US election question: '{text}'. Identify both major candidates "
                       "(and any independent who matters), all polls from the last 3 weeks with dates and "
                       "pollsters, ratings from Cook/Sabato/Inside Elections, fundraising, district/state "
                       "partisan lean and past results, and any Election Day news. Max 400 words, bullet "
                       "points, each with a date and source URL." + NO_ODDS)
            else:
                f = self.state[qid]["facts"]
                ask = (f"Research what will drive '{text}' from the 3 Nov 2026 close to the 4 Nov 2026 close "
                       f"(instrument: {f['instrument']}). Cover today's price action, scheduled events on 4 Nov "
                       "(data releases, earnings, OPEC, inventories, central banks), and how this instrument is "
                       "expected to react to each US midterm outcome. Max 350 words, dated, sourced.")
            return qid, call(qid, "research", ask, SCOUT, self.run, online=True, max_tokens=3000)
        with cf.ThreadPoolExecutor(25) as ex:
            for qid, notes in ex.map(targeted, self.qids):
                self.state[qid]["research"] = notes

    def digest(self, qid):
        keys = ["national", "electionday"] + (["senate"] if qid in [f"A{i}" for i in range(1, 8)] + ["A15"]
                                              else ["house"] if qid.startswith("A") else ["macro"])
        return "\n\n".join(f"## Shared brief: {k}\n{self.briefs.get(k, '')}" for k in keys)

    # ---- stage 2: panel ------------------------------------------------------------------
    def panel_prompt(self, qid):
        s = self.state[qid]
        base = f"{self.digest(qid)}\n\n## Targeted research for {qid}\n{s['research']}\n\n"
        if qid.startswith("A"):
            return base + (
                f"QUESTION {qid}: {s['question']}.\nForm your OWN probability from polls, fundamentals, "
                "ratings and history. Prediction-market prices are deliberately withheld from you; ignore any "
                "you saw in the research. Reason briefly: base rate (state/district lean, midterm penalty for "
                "the president's party), polling average and its likely error, candidate quality, late news. "
                "Then end with ONE JSON line: {\"p_dem\": <0-1>, \"key_reasons\": \"...\"}")
        f = s["facts"]
        return base + (
            f"## Data desk for {qid}\n{json.dumps(f)}\n\nScenario probabilities implied by the House and Senate "
            f"control markets: {json.dumps(self.scen)}\n\nQUESTION {qid}: forecast {s['question']} in "
            f"{f['unit']}. The 3 Nov close is set BEFORE any results (US close 21:00 UTC, polls close later), so "
            "the 4 Nov move is the reaction to the outcome relative to what was priced, plus removal of event "
            "uncertainty, plus unrelated news on 4 Nov. Give a conditional move for each scenario, using the "
            "past election-day moves and typical daily move as scale. End with ONE JSON line: "
            "{\"moves\": {\"D sweep\": x, \"D House / R Senate\": x, \"R sweep\": x, \"R House / D Senate\": x}, "
            "\"key_reasons\": \"...\"}")

    def panel_ok(self, qid):
        """check= for a panel reply: a numeric p_dem (A), or a numeric move for every scenario (B)."""
        def ok(txt):
            js = last_json(txt) or {}
            if qid.startswith("A"):
                return isinstance(js.get("p_dem"), (int, float))
            moves = js.get("moves") or {}
            return all(isinstance(moves.get(k), (int, float)) for k in self.scen)
        return ok

    def panel(self):
        jobs = [(qid, m) for qid in self.qids for m in PANEL]

        def one(job):
            qid, m = job
            txt = call(qid, "forecast", self.panel_prompt(qid), m, self.run, max_tokens=3000, temperature=0.2,
                       check=self.panel_ok(qid))
            return qid, m, txt, last_json(txt)
        with cf.ThreadPoolExecutor(25) as ex:
            for qid, m, txt, js in ex.map(one, jobs):
                self.state[qid].setdefault("panel", []).append({"model": m, "parsed": js, "text": txt[-1500:]})

    # ---- stage 3: critic -----------------------------------------------------------------
    def critic(self):
        def one(qid):
            s = self.state[qid]
            views = "\n".join(f"- {p['model']}: {json.dumps(p['parsed'])}" for p in s["panel"])
            extra = (f"Market snapshot (now revealed for the review): {json.dumps({k: v for k, v in s['market'].items() if k != 'daily_mid'})}"
                     if qid.startswith("A") else f"Data desk: {json.dumps(s['facts'])}")
            prompt = (f"QUESTION {qid}: {s['question']}\nTargeted research:\n{s['research']}\n\nPanel forecasts:\n"
                      f"{views}\n\n{extra}\n\nAct as an adversarial reviewer. Identify: stale or unsupported "
                      "facts, double counting, ignored base rates, places the panel disagrees and who is more "
                      "convincing, and (Part A) whether the gap between panel and market is justified by evidence "
                      "the market may not have priced. Max 200 words. End with ONE JSON line: "
                      "{\"direction\": \"toward_market|away_from_market|hold\", \"confidence\": \"low|medium|high\", "
                      "\"issues\": \"...\"}")
            # 2500 tokens cut off 6 of 25 DeepSeek critiques in run 2 before their JSON line
            return qid, call(qid, "critique", prompt, CRITIC, self.run, max_tokens=6000,
                             check=has_keys("direction", "issues"))
        with cf.ThreadPoolExecutor(25) as ex:
            for qid, txt in ex.map(one, self.qids):
                self.state[qid]["critic"] = {"text": txt[-1500:], "parsed": last_json(txt)}

    # ---- stage 5 (part): code aggregation ----------------------------------------------
    def aggregate_a(self, qid):
        s = self.state[qid]
        ps = [float(p["parsed"]["p_dem"]) for p in s["panel"]
              if p["parsed"] and isinstance(p["parsed"].get("p_dem"), (int, float))]
        ps = [clip(p / 100 if p > 1 else p) for p in ps]  # a reply of 62 means 62%, not 0.99
        if not ps:
            return None
        own = inv(EXTREMIZE * median(logit(p) for p in ps))
        m = s["market"]["market_avg"]
        blend = inv(logit(m) + MODEL_WEIGHT * (logit(own) - logit(m)))
        blend = min(max(blend, m - CAP_PTS / 100), m + CAP_PTS / 100)
        return {"panel_ps": [round(p, 3) for p in ps], "panel_spread": round(max(ps) - min(ps), 3),
                "own_estimate": round(100 * own, 1), "market": round(100 * m, 1),
                "recommended": int(round(100 * clip(blend)))}

    def aggregate_b(self, qid):
        s, unit = self.state[qid], self.state[qid]["facts"]["unit"]
        sd = max(s["facts"]["typical_daily_move"] * 1.2, 1e-3)
        meds = []
        for p in s["panel"]:
            mv = (p["parsed"] or {}).get("moves") or {}
            if not all(isinstance(mv.get(k), (int, float)) for k in self.scen):
                continue
            meds.append(mixture_median(self.scen, mv, sd))
        if not meds:
            return None
        own = median(meds)
        nd = 2 if unit == "%" else 1
        return {"panel_mixture_medians": [round(x, 3) for x in meds], "own_estimate": round(own, nd),
                "shrink": self.b_shrink(qid, own),
                "recommended": round(self.b_shrink(qid, own) * own, nd),
                "typical_daily_move": s["facts"]["typical_daily_move"]}

    def b_shrink(self, qid, own):
        """No shrink when at least 80% of past election-day moves share our forecast's sign (a repeated effect)."""
        hist = [h["move"] for h in self.state[qid]["facts"]["election_day_after_moves"]]
        agree = sum(1 for h in hist if h * own > 0) / len(hist) if hist and own else 0
        return 1.0 if agree >= 0.8 else B_SHRINK

    # ---- stage 4: supervisors ------------------------------------------------------------
    def supervise(self):
        for part in ("A", "B"):
            qs = [q for q in self.qids if q.startswith(part)]
            if not qs:
                continue
            rows = {}
            for q in qs:
                agg = self.aggregate_a(q) if part == "A" else self.aggregate_b(q)
                self.state[q]["agg"] = agg
                rows[q] = {"question": self.state[q]["question"], "agg": agg,
                           "critic": (self.state[q]["critic"]["parsed"] or {})}
            if part == "A":
                task = ("You supervise a forecasting swarm. Review ALL Part A questions together for coherence: "
                        "race outcomes are correlated through a shared national polling error; Senate control "
                        "(A15) must be consistent with the Senate races (Democrats need a net +4 from 47, i.e. "
                        "51 seats, and must hold their own seats too) and House control (A14) with the House "
                        "environment. Before judging A15, do the seat arithmetic explicitly in senate_seat_math: "
                        "start from the Democratic seats not up or safe this cycle, add the expected pickups implied "
                        "by our own estimates for A1-A7, name any Senate race outside A1-A7 that is still in play, "
                        "and say what probability of 51+ seats that implies once correlation is allowed for. "
                        "Market scenario probabilities: " + json.dumps(self.scen) +
                        ". For each question, flag incoherence or a critic issue strong enough to move our own "
                        "estimate, and say by how much in percentage points (0 if fine; keep adjustments small).")
                schema = ('{"senate_seat_math": "...", "adjust": {"A1": 0, ...}, '
                          '"notes": {"A1": "...", ...}}')
            else:
                task = ("You supervise a forecasting swarm. Review ALL Part B market forecasts together for "
                        "consistency: risk-on vs risk-off direction across SPY, IWM, NVDA and VIX; 2y vs 10y "
                        "yields (curve), gilts following Treasuries partially; gold vs yields; oil vs equities. "
                        "Flag inconsistencies and suggest small adjustments in each question's unit (0 if fine).")
                schema = '{"adjust": {"B1": 0, ...}, "notes": {"B1": "...", ...}}'
            prompt = (f"{task}\n\nShared briefs:\n" + "\n".join(f"### {k}\n{v[:1800]}" for k, v in self.briefs.items()) +
                      f"\n\nSwarm state:\n{json.dumps(rows, indent=1)}\n\nEnd with ONE JSON line: {schema}")
            txt = call("general", "aggregate", prompt, SUPERVISOR, self.run,
                       max_tokens=7000 if part == "A" else 5000, check=has_keys("adjust", "notes"))
            sup = last_json(txt) or {}
            for q in qs:
                self.state[q]["supervisor"] = {"adjust": (sup.get("adjust") or {}).get(q, 0),
                                              "note": (sup.get("notes") or {}).get(q, "")}
            self.save(f"supervisor_{part}.json", {"text": txt, "parsed": sup})
        # apply bounded supervisor adjustments to our own estimate, then re-blend
        for q in self.qids:
            agg, sup = self.state[q].get("agg"), self.state[q].get("supervisor", {})
            if not agg:
                continue
            try:
                adj = float(sup.get("adjust") or 0)
            except (TypeError, ValueError):
                adj = 0.0
            if q.startswith("A"):
                adj = max(min(adj, 5), -5)
                agg.update(own_after_supervisor=round(100 * clip((agg["own_estimate"] + adj) / 100), 1))
            else:
                t = self.state[q]["facts"]["typical_daily_move"]
                adj = max(min(adj, t), -t)
                nd = 2 if self.state[q]["facts"]["unit"] == "%" else 1
                own = agg["own_estimate"] + adj
                agg.update(own_after_supervisor=round(own, nd), shrink=self.b_shrink(q, own),
                           recommended=round(self.b_shrink(q, own) * own, nd))
        self.blend_a()

    def blend_a(self):
        """Market blend for Part A: split our disagreement into a shared (national) and a race-specific part."""
        qs = [q for q in self.qids if q.startswith("A") and self.state[q].get("agg")]
        if not qs:
            return
        d = {q: logit(self.state[q]["agg"]["own_after_supervisor"] / 100) - logit(self.state[q]["agg"]["market"] / 100)
             for q in qs}
        shared = median(d.values()) if len(qs) >= 5 else 0.0  # needs enough races to estimate
        for q in qs:
            agg, mk = self.state[q]["agg"], self.state[q]["market"]
            m = agg["market"] / 100
            daily = [v for _, v in mk.get("daily_mid", []) if v is not None]
            drift_1d = abs(m - daily[-2]) if len(daily) >= 2 else 0.0
            damp = 1 / (1 + drift_1d / DRIFT_SCALE)
            x = logit(m) + damp * (W_SHARED * shared + W_IDIO * (d[q] - shared))
            blend = min(max(inv(x), m - CAP_PTS / 100), m + CAP_PTS / 100)
            if d[q] * (blend - m) < 0:  # never cross to the other side of the market from our own view
                blend = m
            agg.update(shared_gap_logit=round(shared, 3), race_gap_logit=round(d[q] - shared, 3),
                       drift_1d=round(drift_1d, 3), weight_damping=round(damp, 2),
                       recommended=int(round(100 * clip(blend))))

    # ---- stage 6: final ------------------------------------------------------------------
    def final(self):
        def one(qid):
            s, agg = self.state[qid], self.state[qid].get("agg")
            if not agg:
                print(f"  {qid}: no aggregate, skipping final"); return qid, ""
            if qid.startswith("A"):
                rule = (f"Method: own estimate = log-odds median of the panel x {EXTREMIZE} (corrects LLM hedging), "
                        "plus the supervisor's coherence adjustment. Our gap to the market is split into the part "
                        f"shared by all races (weight {W_SHARED}: a national bet the chamber markets price better) and "
                        f"the race-specific part (weight {W_IDIO}); both weights shrink when the market moved sharply "
                        f"in the last day (fresh information); capped at {CAP_PTS} points from the market. Scoring is "
                        "Brier gain over the market, so only move away from the market with evidence.\n"
                        f"Numbers: market {agg['market']}%, our own estimate {agg.get('own_after_supervisor')}%, "
                        f"recommended {agg['recommended']}% ("
                        f"{'below' if agg['recommended'] < agg['market'] else 'above' if agg['recommended'] > agg['market'] else 'at'}"
                        " the market).")
                line = ('{"answer": <whole number 1-99>, "own_estimate": <our own estimate, %>, '
                        '"market_reference": <market %, average of Kalshi and Polymarket>, "reason": "<one or two sentences>"}')
            else:
                rule = (f"Method: own estimate = median across panel of the scenario-mixture median (absolute-error "
                        f"scoring is minimised by the median), plus the supervisor's adjustment; answer = {B_SHRINK} x own "
                        "estimate (shrink toward zero because daily moves are mostly noise), except no shrink when at "
                        "least 80% of past election-day moves share the forecast's sign. Results are largely known "
                        "before the 4 Nov US open, so the 4 Nov close reflects the outcome.")
                line = '{"answer": <number in the unit>, "own_estimate": <number>, "reason": "<one or two sentences>"}'
            payload = {k: v for k, v in s.items() if k in ("question", "agg", "supervisor")}
            payload["critic"] = s.get("critic", {}).get("parsed")
            payload["panel"] = [{"model": p["model"], "view": p["parsed"]} for p in s["panel"]]
            if qid.startswith("A"):
                payload["market"] = {k: v for k, v in s["market"].items() if k != "daily_mid"}
            else:
                payload["facts"] = s["facts"]
            prompt = (f"You make the final call for {qid}: {s['question']}.\nSwarm record:\n{json.dumps(payload, indent=1)}\n\n"
                      f"{rule}\nThe recommended answer from this method is {agg['recommended']}. The method already weighs "
                      "the panel, critic, supervisor and market, so use it as the answer. Deviate only for a concrete, "
                      "named error in the record (a wrong fact or a miscalculation), never to re-weigh or split the "
                      "difference. Write 2-4 sentences of reasoning, then end with exactly "
                      f"one JSON line and nothing after it:\n{line}")
            # a final without a readable answer would leave the run incomplete, so it is retried too
            return qid, call(qid, "final", prompt, FINAL, self.run, max_tokens=2000, temperature=0,
                             check=lambda txt: final_answer(txt, qid) is not None)
        with cf.ThreadPoolExecutor(25) as ex:
            for qid, txt in ex.map(one, self.qids):
                self.state[qid]["final"] = {"text": txt, "parsed": ftf.parse_final(txt, qid)}

    def go(self):
        t0 = time.time()
        for name in ("data_desk", "scouts", "panel", "critic", "supervise", "final"):
            print(f"\n=== stage: {name} ({time.time() - t0:.0f}s) ===")
            getattr(self, name)()
            self.save("state.json", self.state)
        rows = []
        for q in self.qids:
            s = self.state[q]; f = (s.get("final") or {}).get("parsed") or {}
            rows.append((q, (s.get("agg") or {}).get("market"), (s.get("agg") or {}).get("own_estimate"),
                         (s.get("agg") or {}).get("recommended"), f.get("answer")))
        print("\nqid  market  own  recommended  final")
        for r in rows:
            print("  ".join(str(x) for x in r))
        missing = [q for q, *_, ans in rows if ans is None]
        overridden = [f"{q} ({rec} -> {ans})" for q, _, _, rec, ans in rows
                      if ans is not None and rec is not None and abs(float(ans) - float(rec)) > 1e-9]
        if missing:
            print(f"\nINCOMPLETE: no final answer for {', '.join(missing)}. Rerun them with --questions under "
                  f"the SAME --run label before submitting; never fill them in by hand.")
        if overridden:
            print(f"Final call departed from the method for: {', '.join(overridden)}. Check its stated error.")
        print(f"done in {time.time() - t0:.0f}s; credit left:"); ftf.credit_left()


def final_answer(txt, qid):
    """The numeric answer in a final reply's JSON line, or None (quietly: ftf.ask already warns)."""
    lines = [l.strip().strip("`").strip() for l in (txt or "").splitlines()]
    lines = [l for l in lines if l and l.lower() != "json"]
    try:
        value = json.loads(lines[-1]).get("answer") if lines else None
    except (json.JSONDecodeError, AttributeError):
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def mixture_median(probs, moves, sd):
    nd = NormalDist()
    def cdf(x):
        return sum(p * nd.cdf((x - moves[k]) / sd) for k, p in probs.items())
    lo, hi = min(moves.values()) - 5 * sd, max(moves.values()) + 5 * sd
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < 0.5 else (lo, mid)
    return (lo + hi) / 2


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--questions", default=",".join(ftf.QUESTION_IDS))
    a = ap.parse_args()
    Swarm(a.run, a.questions.split(",")).go()
