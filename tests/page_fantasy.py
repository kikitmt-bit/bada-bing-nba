"""Exécute la page « Le 5 de la semaine » avec un faux Streamlit et une saison inventée : python tests/page_fantasy.py"""
import contextlib
import os
import random
import shutil
import sys
import types
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outils import charger_app  # noqa: E402

app = charger_app()
st = sys.modules["streamlit"]
out = []


class SS(dict):
    __getattr__ = dict.get

    def __setattr__(self, k, v):
        self[k] = v


class W:
    def __getattr__(self, name):
        def f(*a, **k):
            if name in ("markdown", "caption", "info", "warning", "success", "error"):
                out.append((name, a[0] if a else ""))
            if name == "dataframe":
                out.append(("dataframe", a[0]))
            if name == "button":
                return False
            if name in ("selectbox",):
                return a[1][k.get("index", 0)] if len(a) > 1 else None
            if name == "toggle":
                return True
            if name == "text_input":
                return ""
            if name in ("popover", "container", "spinner", "expander"):
                return contextlib.nullcontext()
            if name == "tabs":
                return [contextlib.nullcontext() for _ in a[0]]
            if name == "columns":
                n = a[0] if isinstance(a[0], int) else len(a[0])
                return [W() for _ in range(n)]
            return None
        return f

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


w = W()
for n in ("markdown", "caption", "info", "warning", "success", "error", "dataframe", "button", "selectbox", "toggle", "text_input",
          "popover", "container", "spinner", "tabs", "columns", "progress"):
    setattr(st, n, getattr(w, n))
st.session_state = SS()
st.context = types.SimpleNamespace(cookies={}, timezone="Europe/Paris")
st.rerun = lambda: None

# Une saison inventée : 6 équipes, 60 joueurs, des matchs du 20 au 25 octobre
random.seed(4)
teams = {str(i): {"id": str(i), "abbr": f"T{i}", "name": f"Team{i}", "full": f"City Team{i}", "logo": "", "color": "#336699", "alt": "#ffcc00", "conf": "Est"} for i in range(6)}
app["teams"] = lambda: teams
roster = {}
for t in teams:
    for j, pos in enumerate(["PG", "SG", "G", "SF", "PF", "F", "C", "C", "G-F", "F-C"]):
        roster[f"{t}{j}"] = {"name": f"Joueur {t}{j}", "short": f"J{t}{j}", "team": t, "abbr": f"T{t}", "pos": sorted(app["F"].positions(pos)),
                             "pos_txt": pos, "inj": "Out" if j == 9 and t == "0" else "", "photo": ""}
app["rosters"] = lambda: roster
level = {p: random.uniform(5, 30) for p in roster}
schedule, summaries = [], {}
gid = 100
for d in range(20, 26):
    day = date(2026, 10, d)
    for a, h in (("0", "1"), ("2", "3"), ("4", "5")):
        gid += 1
        box = {t: [{"id": p, "name": roster[p]["name"], "short": "", "starter": int(p[-1]) < 5, "dnp": False, "reason": "",
                    "stats": {"MIN": str(random.randint(20, 28)), "PTS": str(int(level[p] * random.uniform(.5, 1.5))), "REB": "4", "AST": "3",
                              "STL": "1", "BLK": "0", "TO": "2"}} for p in roster if roster[p]["team"] == t] for t in (a, h)}
        summaries[gid] = {"box": box}
        pts = {t: sum(int(r["stats"]["PTS"]) for r in box[t]) for t in (a, h)}   # score final = total du box score (résumé complet)
        schedule.append({"id": str(gid), "day": day, "home": h, "away": a, "hs": pts[h], "as": pts[a], "done": True, "kind": "R"})
app["summary"] = lambda i, b: summaries.get(int(i))
shutil.rmtree(os.path.join(os.path.dirname(__file__), ".cache_test"), ignore_errors=True)


def run(label, lock_in_hours, today):
    out.clear()
    app["_fx_memory"]().update(log=None, data=None, t=0)
    tip = (datetime.now(timezone.utc) + timedelta(hours=lock_in_hours)).isoformat()
    app["day_games"] = lambda d: [{"utc": tip}] if d.weekday() == 0 else []
    app["fantasy_page"](schedule, {}, date(2026, 10, 20), today, "Paris", False)
    errs = [m for k, m in out if k == "error"]
    frames = [m for k, m in out if k == "dataframe"]
    print(f"{label} : OK · {len(frames)} tableau(x) · prix : {len(frames[-1]) if frames else 0} joueurs · erreurs : {errs}")
    return frames


st.session_state.fx_user = "Kiki"
f = run("Composition ouverte", 3, date(2026, 10, 26))
print("   le plus cher :", f[-1][0]["Joueur"], f[-1][0]["Prix (€)"], "€ · le moins cher :", f[-1][-1]["Prix (€)"], "€")
data = app["fantasy_data"]()
print("   robot :", data["weeks"]["2026-10-26"]["teams"].get("Robot"))
run("Semaine en cours (verrouillée)", -3, date(2026, 10, 28))
