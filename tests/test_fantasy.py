"""Tests des règles du « 5 de la semaine » : python tests/test_fantasy.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fantasy as F  # noqa: E402


def row(pid, pts=10, reb=5, ast=3, mins="30", starter=True, dnp=False):
    return {"id": pid, "starter": starter, "dnp": dnp, "stats": {"MIN": mins, "PTS": str(pts), "REB": str(reb), "AST": str(ast),
                                                                  "STL": "1", "BLK": "0", "TO": "2"}}


def test_points():
    assert F.fantasy_points({"PTS": "6", "REB": "2", "AST": "1"}) == 9.9          # l'exemple de Kiki
    assert F.positions("PG") == {"G"} and F.positions("G-F") == {"G", "F"} and F.positions("C") == {"C"}


def test_moyenne_et_sixieme_homme():
    mon = date(2026, 10, 26)
    log = {}
    # LeBron (L) : 1 match à 48 ; A : 40, 30, 50 ; X : blessé toute la semaine ; S (6e homme) : 20 et 30
    F.log_game(log, 1, date(2026, 10, 27), {"box": {"t": [row("L", pts=30, reb=10, ast=5), row("A", pts=25), row("S", pts=12)]}})
    F.log_game(log, 2, date(2026, 10, 29), {"box": {"t": [row("A", pts=15), row("S", pts=20), row("X", dnp=True), row("L", mins="0")]}})
    F.log_game(log, 3, date(2026, 10, 31), {"box": {"t": [row("A", pts=35, reb=0, ast=0), row("Z", pts=4, reb=1, ast=0, mins="3")]}})
    pts = F.week_points(log, mon)
    assert len(pts["L"]) == 1 and len(pts["A"]) == 3 and "X" not in pts           # 0 minute ou « n'a pas joué » = pas de match
    assert len(pts["Z"]) == 1                                                       # 3 minutes = un match joué (règle de Kiki)
    team = {"five": ["L", "A", "X", "B", "C"], "six": "S", "coeur": None}
    total, detail = F.score_team(team, pts)
    assert detail[0][1] == round(pts["L"][0], 1)                                    # LeBron : son seul match
    assert detail[1][1] == round(sum(pts["A"]) / 3, 1)                              # moyenne sur 3 matchs
    assert detail[2][0] == "S" and detail[2][3].startswith("remplacé")              # X n'a pas joué : 6e homme
    assert detail[3][1] == 0                                                        # B non plus : un seul remplacement
    team["coeur"] = "A"
    assert F.score_team(team, pts)[1][1][1] == round(2 * sum(pts["A"]) / 3, 1)     # coup de cœur ×2


def test_validation():
    prices = {"g1": 40000, "g2": 9000, "f1": 20000, "f2": 15000, "c1": 10000, "s": 5000, "g3": 30000}
    pos = {"g1": {"G"}, "g2": {"G"}, "g3": {"G"}, "f1": {"F"}, "f2": {"F"}, "c1": {"C"}, "s": {"F"}}.get
    ok = {"five": ["g1", "g2", "f1", "f2", "c1"], "six": "s", "coeur": "g2"}
    assert F.validate(ok, prices, pos) == []
    assert any("Budget" in e for e in F.validate(dict(ok, five=["g1", "g3", "f1", "f2", "c1"]), prices, pos))
    assert any("Poste" in e for e in F.validate(dict(ok, five=["g1", "f1", "g2", "f2", "c1"]), prices, pos))
    assert any("cœur" in e for e in F.validate(dict(ok, coeur="g1"), prices, pos))
    assert any("deux fois" in e for e in F.validate(dict(ok, six="g1"), prices, pos))


def test_prix():
    assert 46000 <= F.raw_price(60) <= 50000 and 18000 <= F.raw_price(30) <= 22000 and F.raw_price(8) <= 8000
    log = {}
    F.log_game(log, 1, date(2026, 10, 20), {"box": {"t": [row("p", pts=40, reb=10, ast=10)]}})
    p1 = F.week_prices(log, date(2026, 10, 26))["p"]
    F.log_game(log, 2, date(2026, 10, 28), {"box": {"t": [row("p", pts=60, reb=15, ast=10)]}})
    p2 = F.week_prices(log, date(2026, 11, 2), {"p": p1})["p"]
    assert p2 <= p1 * 1.2 + 1                                                       # variation limitée à +20 %


def test_equipe_parfaite_et_robot():
    import random
    random.seed(1)
    prices, pos, pts = {}, {}, {}
    for i in range(40):
        pid = f"p{i}"
        prices[pid] = random.choice([5000, 8000, 12000, 20000, 30000, 45000])
        pos[pid] = {random.choice("GFC")}
        pts[pid] = [prices[pid] / 1000 + random.uniform(-5, 15)]
    best = F.perfect_team(pts, prices, pos.get)
    assert best and F.validate(dict(best[0], six="p39" if "p39" not in best[0]["five"] else "p38"), prices, pos.get) == [] or \
        sum(prices[p] for p in best[0]["five"]) <= F.BUDGET
    log = {}
    F.log_game(log, 1, date(2026, 10, 20), {"box": {"t": [row(p, pts=int(v[0])) for p, v in pts.items()]}})
    rob = F.robot_team(log, date(2026, 10, 26), prices, pos.get)
    assert rob and F.validate(rob, prices, pos.get) == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK", name)
