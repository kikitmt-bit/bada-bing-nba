"""Construit data/nba_history.json : tous les matchs NBA (saison régulière + play-offs) des saisons passées, d'après ESPN.

À relancer une fois par an, avant la saison :  python data/build_nba_history.py
La saison en cours n'y est pas : le site la lit en direct chez ESPN.

Format : {"seasons": [2016, ...], "games": [[date, id_dom, id_ext, score_dom, score_ext, saison, "R"|"P"], ...]}
(date = jour du match à New York, AAAA-MM-JJ ; id = identifiant ESPN de l'équipe, stable même si l'abréviation change ;
saison = année de la fin de saison, 2026 pour 2025-26.)
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
FIRST_SEASON = 2016
HERE = os.path.dirname(os.path.abspath(__file__))


def current_season():
    now = datetime.now(timezone.utc)
    return now.year + 1 if now.month >= 8 else now.year


def get(url, params=None):
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1 + attempt * 2)
    return None


def ny_day(iso):
    # ESPN donne l'heure en UTC ; le « jour du match » est celui de New York (UTC-4 / UTC-5 : -5 h suffit pour le jour)
    dt = datetime.strptime(iso[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    return (dt - timedelta(hours=5)).strftime("%Y-%m-%d")


def main():
    last = current_season() - 1
    teams = get(f"{BASE}/teams")["sports"][0]["leagues"][0]["teams"]
    ids = [t["team"]["id"] for t in teams]
    games = {}
    for season in range(FIRST_SEASON, last + 1):
        for kind, code in (("R", 2), ("P", 3)):
            for tid in ids:
                d = get(f"{BASE}/teams/{tid}/schedule", {"season": season, "seasontype": code})
                for e in (d or {}).get("events", []):
                    c = (e.get("competitions") or [{}])[0]
                    if not ((c.get("status") or {}).get("type") or {}).get("completed"):
                        continue
                    home = next((t for t in c.get("competitors", []) if t.get("homeAway") == "home"), None)
                    away = next((t for t in c.get("competitors", []) if t.get("homeAway") == "away"), None)
                    if not home or not away:
                        continue
                    try:
                        hs, as_ = int((home.get("score") or {}).get("value")), int((away.get("score") or {}).get("value"))
                    except (TypeError, ValueError):
                        continue
                    games[e["id"]] = [ny_day(e["date"]), home["team"]["id"], away["team"]["id"], hs, as_, season, kind]
            print(season, kind, len(games), file=sys.stderr)
    out = {"seasons": [FIRST_SEASON, last], "games": sorted(games.values())}
    with open(os.path.join(HERE, "nba_history.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{len(games)} matchs écrits", file=sys.stderr)


if __name__ == "__main__":
    main()
