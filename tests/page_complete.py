"""Exécute toute la page (vues Nuit et Semaine) avec un faux Streamlit et des matchs inventés : python tests/page_complete.py"""
import sys, types, contextlib
import os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outils import charger_app, match
from datetime import date, timedelta
app = charger_app()
st = sys.modules["streamlit"]
class SS(dict):
    __getattr__ = dict.get
    def __setattr__(self, k, v): self[k] = v
st.session_state = SS(); st.query_params = {}
out = []
class W:
    def __getattr__(self, name):
        def f(*a, **k):
            if name == "markdown": out.append(a[0])
            if name in ("button",): return False
            if name == "segmented_control": return k.get("default")
            if name == "date_input": return k.get("value")
            if name == "radio": return a[1][k.get("index", 0)]
            if name == "multiselect": return k.get("default")
            if name == "toggle": return k.get("value")
            if name in ("popover", "container", "spinner"): return contextlib.nullcontext()
            if name == "columns": n = a[0] if isinstance(a[0], int) else len(a[0]); return [W() for _ in range(n)]
            return None
        return f
    def __enter__(self): return self
    def __exit__(self, *a): return False
w = W()
for n in ("set_page_config", "markdown", "columns", "popover", "radio", "multiselect", "toggle", "caption", "date_input", "button",
          "segmented_control", "spinner", "info", "container"):
    setattr(st, n, getattr(w, n))
st.rerun = lambda: (_ for _ in ()).throw(RuntimeError("rerun"))
st.context = types.SimpleNamespace(cookies={"nba_vues": "261021.261024"}, timezone="Europe/Paris")
today = app["datetime"].now(app["NY"]).date()
g1, s1 = match(app, [(0, 0), (12, 4), (24, -3), (36, 5), (45, -2), (47, 1), (48, 2)])
g2, s2 = match(app, [(0, 0), (10, 22), (24, 28), (36, 32), (48, 30)]); g2 = dict(g2, id="998")
g3 = dict(g1, id="997", state="pre", completed=False, utc="2026-10-27T23:30Z")
D = today - timedelta(days=1)
for g in (g1, g2): g["day"] = D
g3["day"] = today
sched = [{"id": g["id"], "day": g["day"], "home": "2", "away": "1", "hs": 1, "as": 0, "done": True, "kind": "R"} for g in (g1, g2, g3)]
sched.append({"id": "1", "day": today - timedelta(days=6), "home": "2", "away": "1", "hs": 1, "as": 0, "done": True, "kind": "R"})
app["season_games"] = lambda season, b: sched
app["team_index"] = lambda season, b: {}
app["day_games"] = lambda d: [g1, g2] if d == D else ([g3] if d == today else [])
summs = {"999": s1, "998": s2}
app["game_summary"] = lambda g: summs.get(g["id"])
app["videos_since"] = lambda d: ([], [])
app["video_watcher"] = lambda: {"seen": {}, "last": 0}
app["game_videos"] = lambda g, a, b: (None, None)
app["night_videos"] = lambda d, a, b: (None, None)
app["video_durations"] = lambda ids: {}
app["set_cookie"] = lambda n, v: out.append(f"COOKIE {n}={v}")
app["auto_refresh"] = lambda games: out.append("AUTO")
for vue in ("nuit", "semaine"):
    out.clear(); st.session_state.clear(); st.query_params.clear()
    if vue == "semaine": st.query_params["vue"] = "semaine"
    app["main"]()
    html = "\n".join(o for o in out if isinstance(o, str))
    print(vue, "OK", len(html), "car. ·", [o for o in out if str(o).startswith("COOKIE")], "· carte(s):", html.count("class='gc'"),
          "· semaine:", "meilleurs matchs de la semaine" in html, "· barre de nuit:", "nbar" in html)
