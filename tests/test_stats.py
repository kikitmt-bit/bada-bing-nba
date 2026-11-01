"""Statistiques de visite (page admin) : lecture des cookies, visites, activité par nuit. python tests/test_stats.py"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import stats as S

t0 = 1_793_000_000


def _b36(n):
    s = ""
    while n:
        n, r = divmod(n, 36)
        s = "0123456789abcdefghijklmnopqrstuvwxyz"[r] + s
    return s or "0"


raw = "-".join([f"{_b36(t0)}.v.401.261031", f"{_b36(t0 + 5)}.s.402.261031", f"{_b36(t0 + 9)}.n..261031",
                "abîmé", f"{_b36(t0)}.Z.1.261031", f"{_b36(t0 + 20)}.R..261031"])
ev = S.parse_client(raw)
assert [e["k"] for _, e in ev] == ["v", "s", "n", "R"], ev
assert ev[0][1] == {"t": t0, "k": "v", "g": "401", "d": "2026-10-31"}
assert S.parse_hb(f"{_b36(t0)}.{_b36(t0 + 600)}") == (t0, t0 + 600) and S.parse_hb("x") is None and S.parse_hb("") is None
print("OK cookies")

evs = [{"t": t0 - 10, "u": "a", "k": "open", "d": "2026-10-31", "x": "nuit"}]
evs += [dict(e, u="a") for _, e in ev] + [dict(ev[0][1], u="a")]               # un clic relu deux fois
evs += [{"t": t0 + 900, "s": t0 - 10, "u": "a", "k": "hb"}]                    # page affichée 15 min
evs += [{"t": t0 + 9000, "u": "a", "k": "open", "d": "2026-11-01", "x": "nuit"}]  # 2 h 30 après : autre visite
evs += [{"t": t0 + 50, "u": "b", "k": "open", "d": "2026-10-31", "x": "semaine"}, {"t": t0 + 60, "k": "err", "x": "HTTP 500"}]
evs = S.dedupe(evs)
assert sum(1 for e in evs if e.get("k") == "v") == 1
vis = S.visits(evs)
assert [(v["u"], v["end"] - v["start"]) for v in vis] == [("a", 910), ("b", 0), ("a", 0)], [(v["u"], v["end"] - v["start"]) for v in vis]
print("OK visites :", S.fmt_dur(910))

acts = S.night_activity(evs)
a = acts[("a", "2026-10-31")]
assert a["v"] == {"401"} and a["s"] == {"402"} and a["n"] and a["R"] and not a["X"] and a["vu"]
assert not acts[("b", "2026-10-31")]["vu"]              # vue Semaine : pas « venu sur la nuit »
print("OK activité par nuit")
assert S.device("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile") == "Téléphone · iOS"
assert S.device("Mozilla/5.0 (Windows NT 10.0; Win64; x64)") == "PC · Windows"
print("OK appareils")
