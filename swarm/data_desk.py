"""Data desk: deterministic facts for every question, built only from the event data pack
and its live-with-fallback tools (ftf_tools). No model calls here."""
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ai_only"))
import ftf_tools  # noqa: E402

# Part B instrument map: question -> (source, column/instrument, unit)
B_MAP = {
    "B1": ("price", "spy", "%"), "B2": ("price", "iwm", "%"), "B3": ("price", "nvda", "%"),
    "B4": ("price", "vix", "points"),
    "B5": ("yield", "us_2y", "bp"), "B6": ("yield", "us_10y", "bp"), "B7": ("yield", "uk_10y", "bp"),
    "B8": ("price", "gold_front_month", "%"), "B9": ("price", "wti_front_month", "%"),
    "B10": ("price", "henry_hub_front_month", "%"),
}
# Day after each recent US federal election (election day, next day)
ELECTIONS = [("2016-11-08", "2016-11-09", "2016 presidential (Trump win, R sweep, surprise)"),
             ("2018-11-06", "2018-11-07", "2018 midterm (D took House, R kept Senate, as expected)"),
             ("2020-11-03", "2020-11-04", "2020 presidential (Biden, count unresolved next day)"),
             ("2022-11-08", "2022-11-09", "2022 midterm (red wave failed to appear; R narrow House)"),
             ("2024-11-05", "2024-11-06", "2024 presidential (Trump win, R sweep)")]


def _logit(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def market_snapshot(qid):
    """Latest Kalshi/Polymarket mids, venue gap, liquidity and drift for one Part A question."""
    o = ftf_tools.get_market_odds(qid, days=8)
    latest = o["latest"] or {}
    k, pm = latest.get("kalshi_yes_mid"), latest.get("polymarket_price")
    vals = [v for v in (k, pm) if v is not None]
    m = sum(vals) / len(vals) if vals else None
    daily = o.get("daily_last_hour", [])
    def mid(row):
        v = [x for x in (row.get("kalshi_yes_mid"), row.get("polymarket_price")) if x is not None]
        return sum(v) / len(v) if v else None
    drift7 = None
    if len(daily) >= 7 and m is not None and mid(daily[-7]) is not None:
        drift7 = m - mid(daily[-7])
    return {"question_id": qid, "source": o["source"], "as_of": latest.get("timestamp_utc"),
            "kalshi_mid": k, "polymarket": pm, "market_avg": m,
            "venue_gap": None if k is None or pm is None else round(k - pm, 3),
            "kalshi_spread": latest.get("kalshi_spread"),
            "drift_7d": None if drift7 is None else round(drift7, 3),
            "daily_mid": [(r["date"], None if mid(r) is None else round(mid(r), 3)) for r in daily]}


def scenario_probs(p_house, p_senate, rho=0.8, n=200_000, seed=7):
    """Four control scenarios from the two chamber markets via a Gaussian copula (rho = correlation)."""
    import random
    rnd = random.Random(seed)
    from statistics import NormalDist
    nd = NormalDist()
    th, ts = nd.inv_cdf(p_house), nd.inv_cdf(p_senate)
    c = {"D sweep": 0, "D House / R Senate": 0, "R sweep": 0, "R House / D Senate": 0}
    for _ in range(n):
        z1 = rnd.gauss(0, 1); z2 = rho * z1 + math.sqrt(1 - rho * rho) * rnd.gauss(0, 1)
        h, s = z1 < th, z2 < ts
        key = "D sweep" if h and s else "D House / R Senate" if h else "R House / D Senate" if s else "R sweep"
        c[key] += 1
    return {k: round(v / n, 3) for k, v in c.items()}


def _series(kind, name):
    if kind == "yield":
        df = pd.read_csv(ROOT / "data" / "government_bond_yields_daily.csv", parse_dates=["date"])
        s = df.set_index("date")[name].dropna()
    else:
        df = pd.read_csv(ROOT / "data" / "yahoo_prices_daily.csv", parse_dates=["date"])
        s = df[df.instrument == name].set_index("date").close.dropna()
    return s


def _change(a, b, unit):
    if unit == "%":
        return 100 * (b / a - 1)
    if unit == "bp":
        return 100 * (b - a)
    return b - a  # points


def market_facts(qid):
    """Latest levels, the scorer's typical daily move, and the same instrument's moves after past elections."""
    kind, name, unit = B_MAP[qid]
    s = _series(kind, name)
    # Live (or fallback) latest rows for the most recent closes, incl. 3 Nov if published
    live_rows, live_source = [], "data pack"
    try:
        if kind == "yield":
            r = ftf_tools.get_yields(days=10); live_source = r["source"]
            live_rows = [(x["date"], x.get(name)) for x in r["daily"] if x.get(name) is not None]
        else:
            r = ftf_tools.get_prices(name, days=10); live_source = r["source"]
            live_rows = [(x["time_utc"], x["close"]) for x in r["rows"] if x.get("close") is not None]
    except Exception as e:  # noqa: BLE001
        live_source = f"live failed ({e.__class__.__name__}); data pack"
    for d, v in live_rows:
        s.loc[pd.Timestamp(d)] = v
    s = s[~s.index.duplicated(keep="last")].sort_index()
    ch = pd.Series([_change(a, b, unit) for a, b in zip(s.values[:-1], s.values[1:])], index=s.index[1:])
    window = ch[ch.index <= "2026-10-30"].tail(60)
    typical = float(window.abs().median())
    hist = []
    for d0, d1, label in ELECTIONS:
        if pd.Timestamp(d0) in s.index and pd.Timestamp(d1) in s.index:
            mv = _change(s[d0], s[d1], unit)
            hist.append({"date": d1, "event": label, "move": round(float(mv), 2),
                         "scaled": round(float(mv) / float(ch[ch.index < d0].tail(60).abs().median()), 2)})
    return {"question_id": qid, "instrument": name, "unit": unit, "source": live_source,
            "last_closes": [(str(d.date()), round(float(v), 4)) for d, v in s.tail(6).items()],
            "last_5_moves": [round(float(x), 2) for x in ch.tail(5)],
            "typical_daily_move": round(typical, 3),
            "election_day_after_moves": hist}
