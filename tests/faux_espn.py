"""Faux ESPN pour voir le site sans connexion : une saison 2026-27 inventée (vraies équipes, scores au hasard).

Lancer :  BB_FAUX_ESPN=1 python -m streamlit run app.py --server.port 8531
(app.get_json passe alors par fake_get au lieu d'interroger ESPN). Rien de tout ça n'est utilisé en ligne.
"""
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
TEAMS = [  # id, abréviation, nom, nom complet, couleur, 2e couleur, conférence
    ("1", "ATL", "Hawks", "Atlanta Hawks", "c8102e", "fdb927", "E"), ("2", "BOS", "Celtics", "Boston Celtics", "008348", "ffffff", "E"),
    ("3", "NO", "Pelicans", "New Orleans Pelicans", "0a2240", "b4975a", "W"), ("4", "CHI", "Bulls", "Chicago Bulls", "ce1141", "000000", "E"),
    ("5", "CLE", "Cavaliers", "Cleveland Cavaliers", "860038", "bc945c", "E"), ("6", "DAL", "Mavericks", "Dallas Mavericks", "0064b1", "bbc4ca", "W"),
    ("7", "DEN", "Nuggets", "Denver Nuggets", "0e2240", "fec524", "W"), ("8", "DET", "Pistons", "Detroit Pistons", "1d428a", "c8102e", "E"),
    ("9", "GS", "Warriors", "Golden State Warriors", "fdb927", "1d428a", "W"), ("10", "HOU", "Rockets", "Houston Rockets", "ce1141", "000000", "W"),
    ("11", "IND", "Pacers", "Indiana Pacers", "002d62", "fdbb30", "E"), ("12", "LAC", "Clippers", "LA Clippers", "c8102e", "1d428a", "W"),
    ("13", "LAL", "Lakers", "Los Angeles Lakers", "552583", "fdb927", "W"), ("14", "MIA", "Heat", "Miami Heat", "98002e", "f9a01b", "E"),
    ("15", "MIL", "Bucks", "Milwaukee Bucks", "00471b", "eee1c6", "E"), ("16", "MIN", "Timberwolves", "Minnesota Timberwolves", "0c2340", "236192", "W"),
    ("17", "BKN", "Nets", "Brooklyn Nets", "000000", "ffffff", "E"), ("18", "NY", "Knicks", "New York Knicks", "1d428a", "f58426", "E"),
    ("19", "ORL", "Magic", "Orlando Magic", "0077c0", "c4ced4", "E"), ("20", "PHI", "76ers", "Philadelphia 76ers", "1d428a", "e01234", "E"),
    ("21", "PHX", "Suns", "Phoenix Suns", "1d1160", "e56020", "W"), ("22", "POR", "Trail Blazers", "Portland Trail Blazers", "e03a3e", "000000", "W"),
    ("23", "SAC", "Kings", "Sacramento Kings", "5a2d81", "63727a", "W"), ("24", "SA", "Spurs", "San Antonio Spurs", "c4ced4", "000000", "W"),
    ("25", "OKC", "Thunder", "Oklahoma City Thunder", "007ac1", "ef3b24", "W"), ("26", "UTAH", "Jazz", "Utah Jazz", "4e008e", "79a3dc", "W"),
    ("27", "WSH", "Wizards", "Washington Wizards", "002b5c", "e31837", "E"), ("28", "TOR", "Raptors", "Toronto Raptors", "ce1141", "000000", "E"),
    ("29", "MEM", "Grizzlies", "Memphis Grizzlies", "5d76a9", "12173f", "W"), ("30", "CHA", "Hornets", "Charlotte Hornets", "1d1160", "00788c", "E"),
]
BY_ID = {t[0]: t for t in TEAMS}
STRENGTH = {t[0]: random.Random(int(t[0]) * 7).uniform(-6, 6) for t in TEAMS}
OPENING = date(2026, 10, 20)
END = date(2027, 4, 11)
FIRST = ["Jalen", "Tyrese", "Luka", "Jayson", "Anthony", "Devin", "Victor", "Shai", "Donovan", "Trae", "Paolo", "Cade", "Zion",
         "Jaylen", "Kevin", "Stephen", "LaMelo", "Scottie", "Franz", "Chet"]
LAST = ["Martin", "Dubois", "Johnson", "Williams", "Brown", "Davis", "Moore", "Taylor", "Thomas", "Jackson", "White", "Harris",
        "Clark", "Lewis", "Walker", "Young", "Allen", "King", "Wright", "Scott"]


def logo_uri(tid):
    _, abbr, _, _, c, a, _ = BY_ID[tid]
    svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='46' fill='%23{c}' "
           f"stroke='%23{a}' stroke-width='7'/><text x='50' y='60' font-family='Arial' font-weight='bold' font-size='30' "
           f"text-anchor='middle' fill='%23{a if a != c else 'ffffff'}'>{abbr}</text></svg>")
    return "data:image/svg+xml;utf8," + svg.replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")


def _schedule():
    rnd = random.Random(2027)
    games, last = [], {}
    d, n = OPENING, 0
    while d <= END:
        free = [t[0] for t in TEAMS if last.get(t[0]) != d - timedelta(days=1) or rnd.random() < .25]
        rnd.shuffle(free)
        k = min(len(free) // 2, rnd.choice([4, 5, 6, 7, 8, 9, 10, 11]))
        for i in range(k):
            h, a = free[2 * i], free[2 * i + 1]
            n += 1
            hour = rnd.choice([19, 19, 19.5, 20, 20, 21, 22, 22.5])
            local = datetime(d.year, d.month, d.day, int(hour), int((hour % 1) * 60), tzinfo=NY)
            games.append({"id": str(401800000 + n), "day": d, "home": h, "away": a, "utc": local.astimezone(timezone.utc)})
            last[h] = last[a] = d
        d += timedelta(days=1)
    return games


GAMES = _schedule()
BY_GAME = {g["id"]: g for g in GAMES}


def _result(g):
    rnd = random.Random(int(g["id"]))
    diff = STRENGTH[g["home"]] - STRENGTH[g["away"]] + 2.5 + rnd.gauss(0, 12)
    base = rnd.randint(100, 122)
    hs, as_ = base + max(0, round(diff / 2)), base - min(0, round(diff / 2))
    if hs == as_:
        hs += 3
    q = lambda total: [total // 4 + rnd.randint(-5, 5) for _ in range(3)]
    hq, aq = q(hs), q(as_)
    return hs, as_, hq + [hs - sum(hq)], aq + [as_ - sum(aq)]


def _state(g):
    now = datetime.now(timezone.utc)
    if now < g["utc"]:
        return "pre"
    if now < g["utc"] + timedelta(hours=2, minutes=20):
        return "in"
    return "post"


def _competitor(g, side, full):
    tid = g[side]
    st = _state(g)
    c = {"homeAway": side, "team": {"id": tid}}
    if st != "pre":
        hs, as_, hq, aq = _result(g)
        score = hs if side == "home" else as_
        if full:
            c.update(score=str(score), winner=st == "post" and score == max(hs, as_),
                     linescores=[{"value": v} for v in (hq if side == "home" else aq)])
        else:
            c["score"] = {"value": float(score)}
    return c


def _event(g, full=True):
    st = _state(g)
    status = {"type": {"state": st, "completed": st == "post", "name": {"pre": "STATUS_SCHEDULED", "in": "STATUS_IN_PROGRESS",
                                                                      "post": "STATUS_FINAL"}[st],
                       "shortDetail": {"pre": "", "in": "Q3 4:12", "post": "Final"}[st]}, "period": 3 if st == "in" else 4}
    comp = {"competitors": [_competitor(g, "home", full), _competitor(g, "away", full)], "status": status}
    if full:
        h = BY_ID[g["home"]]
        comp.update(venue={"fullName": f"{h[2]} Arena", "address": {"city": h[3].rsplit(' ', 1)[0]}},
                    broadcasts=[{"names": [random.Random(int(g["id"])).choice(["ESPN", "TNT", "NBA TV", "Prime Video", "NBC", "League Pass"])]}])
    return {"id": g["id"], "date": g["utc"].strftime("%Y-%m-%dT%H:%MZ"), "season": {"year": 2027, "type": 2}, "competitions": [comp]}


def _player(tid, i):
    rnd = random.Random(int(tid) * 100 + i)
    return f"{rnd.choice(FIRST)} {rnd.choice(LAST)}"


def _summary(gid):
    g = BY_GAME.get(gid)
    if not g:
        return {}
    out = {"injuries": [], "leaders": [], "boxscore": {"players": [], "teams": []}, "plays": [], "article": {}}
    for tid in (g["home"], g["away"]):
        rnd = random.Random(int(gid) + int(tid))
        inj = [{"athlete": {"displayName": _player(tid, j)}, "status": rnd.choice(["Out", "Day-To-Day", "Questionable"]),
                "details": {"type": rnd.choice(["Knee", "Ankle", "Hamstring", "Back"])}} for j in rnd.sample(range(8, 13), rnd.randint(0, 2))]
        out["injuries"].append({"team": {"id": tid}, "injuries": inj})
        out["leaders"].append({"team": {"id": tid}, "leaders": [
            {"name": "points", "leaders": [{"athlete": {"displayName": _player(tid, 0)}, "displayValue": f"{rnd.uniform(18, 31):.1f}"}]},
            {"name": "rebounds", "leaders": [{"athlete": {"displayName": _player(tid, 4)}, "displayValue": f"{rnd.uniform(7, 13):.1f}"}]},
            {"name": "assists", "leaders": [{"athlete": {"displayName": _player(tid, 1)}, "displayValue": f"{rnd.uniform(5, 10):.1f}"}]}]})
        if _state(g) != "pre":
            labels = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "TO", "FG", "3PT", "FT", "+/-"]
            ath = []
            for j in range(10):
                p = rnd.randint(2, 34)
                ath.append({"athlete": {"id": str(int(tid) * 1000 + j), "displayName": _player(tid, j), "shortName": _player(tid, j)},
                            "starter": j < 5, "stats": [str(rnd.randint(12, 38)), str(p), str(rnd.randint(1, 12)), str(rnd.randint(0, 9)),
                                                         "1", "0", "2", f"{p // 2}-{p // 2 + 6}", "2-5", "2-2", "+3"]})
            out["boxscore"]["players"].append({"team": {"id": tid}, "statistics": [{"labels": labels, "athletes": ath}]})
    return out


def _news(tid=None):
    teams_ = [BY_ID[tid]] if tid else [BY_ID[str(i)] for i in (13, 2, 9, 18, 25, 7)]
    arts = []
    for i, t in enumerate(teams_ * (3 if tid else 1)):
        arts.append({"headline": f"{t[3]} : {['ce qu’il faut retenir du début de saison', 'le point sur l’infirmerie', 'la rotation se précise'][i % 3]}",
                     "description": "Article inventé pour tester le site sans connexion.", "published": (datetime.now(timezone.utc) - timedelta(hours=5 * i + 2)).isoformat(),
                     "links": {"web": {"href": "https://www.espn.com/nba/"}}, "images": []})
    return {"articles": arts}


def fake_get(url, params=None):
    params = params or {}
    path = url.split("/nba", 1)[-1]
    if path == "/teams":
        return {"sports": [{"leagues": [{"teams": [{"team": {"id": t[0], "abbreviation": t[1], "name": t[2], "displayName": t[3],
                                                             "shortDisplayName": t[2], "color": t[4], "alternateColor": t[5],
                                                             "logos": [{"href": logo_uri(t[0])}]}} for t in TEAMS]}]}]}
    if path == "/standings":
        return {"children": [{"name": f"{'Eastern' if c == 'E' else 'Western'} Conference",
                              "standings": {"entries": [{"team": {"id": t[0]}} for t in TEAMS if t[6] == c]}} for c in "EW"]}
    if path.endswith("/schedule"):
        tid = path.split("/")[2]
        if str(params.get("seasontype")) != "2":
            return {"events": []}
        return {"events": [_event(g, full=False) for g in GAMES if tid in (g["home"], g["away"])]}
    if path == "/scoreboard":
        d = datetime.strptime(params["dates"], "%Y%m%d").date()
        return {"events": [_event(g) for g in GAMES if g["day"] == d]}
    if path == "/summary":
        return _summary(params.get("event"))
    if path.endswith("/roster"):
        tid = path.split("/")[2]
        pos = ["G", "G", "F", "F", "C", "G", "F", "C", "G", "F", "F", "G", "C"]
        return {"athletes": [{"id": str(int(tid) * 1000 + j), "displayName": _player(tid, j), "shortName": _player(tid, j),
                              "position": {"abbreviation": pos[j]}, "jersey": str((j * 7 + int(tid)) % 40),
                              "injuries": [{"status": "Out"}] if j == 9 else []} for j in range(13)]}
    if path == "/news":
        return _news(params.get("team"))
    return None
