"""Outils de test : charge app.py sans Streamlit (faux module) et fabrique des matchs inventés."""
import os
import sys
import types
from datetime import date

ICI = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(ICI, "..", "app.py")


def charger_app():
    if os.path.dirname(APP) not in sys.path:
        sys.path.insert(0, os.path.dirname(APP))        # pour « import fantasy »
    st = types.ModuleType("streamlit")
    st.cache_data = lambda *a, **k: (lambda f: f)
    st.cache_resource = lambda *a, **k: (lambda f: f)
    st.query_params = {}
    comp = types.ModuleType("streamlit.components.v1")
    comp.html = lambda *a, **k: None
    pkg = types.ModuleType("streamlit.components")
    pkg.v1 = comp
    st.components = pkg
    sys.modules.update({"streamlit": st, "streamlit.components": pkg, "streamlit.components.v1": comp})
    src = open(APP, encoding="utf-8").read().split('if __name__ == "__main__":')[0]
    ns = {"__name__": "app_test", "__file__": APP}
    exec(compile(src, APP, "exec"), ns)
    ns["teams"] = lambda: {"1": {"id": "1", "abbr": "AAA", "name": "Visiteurs", "full": "Visiteurs", "logo": "", "color": "#336699", "alt": "#ffcc00", "conf": "Est"},
                           "2": {"id": "2", "abbr": "BBB", "name": "Locaux", "full": "Locaux", "logo": "", "color": "#993333", "alt": "#ffffff", "conf": "Est"}}
    ns["CACHE_DIR"] = os.path.join(ICI, ".cache_test")
    return ns


def match(app, cles, star_pts=26, star_reb=6, star_ast=5, threes=24, dunks=4):
    """cles : [(minute, écart domicile - visiteurs)] ; le match dure jusqu'à la dernière minute donnée."""
    end = cles[-1][0]

    def ecart(t):
        for (m1, d1), (m2, d2) in zip(cles, cles[1:]):
            if m1 <= t <= m2:
                return round(d1 + (d2 - d1) * (t - m1) / (m2 - m1)) if m2 > m1 else d2
        return cles[-1][1]

    plays, t = [], 0.0
    while t < end - 1e-9:
        t = min(round(t + 0.5, 2), end)
        total = round(4.6 * t)
        d = ecart(t)
        hm, aw = (total + d) // 2, (total - d) // 2
        hm = aw + d
        period = int(t // 12) + 1 if t <= 48 else 5 + int((t - 48 - 1e-9) // 5)
        p_end = 12 * period if period <= 4 else 48 + 5 * (period - 4)
        rest = max(0.0, p_end - t) * 60
        clock = f"{int(rest // 60)}:{int(rest % 60):02d}"
        txt = "makes driving dunk" if len(plays) % max(1, int(end * 2 / max(dunks, 1))) == 0 and dunks else "makes jumper"
        plays.append((period, clock, aw, hm, True, txt, "2"))
    hs, as_ = plays[-1][3], plays[-1][2]
    n_ot = max(0, int(round((end - 48) / 5)))
    lines = lambda s: [s // (4 + n_ot)] * (4 + n_ot)
    star = {"PTS": str(star_pts), "REB": str(star_reb), "AST": str(star_ast), "FG": f"{star_pts // 2 - 2}-{star_pts // 2 + 6}",
            "3PT": f"{threes // 2}-{threes}", "STL": "1", "BLK": "0", "TO": "2"}
    other = {"PTS": "12", "REB": "4", "AST": "3", "FG": "5-11", "3PT": f"{threes - threes // 2}-{threes}", "STL": "1", "BLK": "0", "TO": "1"}
    box = {"2": [{"id": "s", "name": "Star Domicile", "short": "S. Dom", "starter": True, "dnp": False, "reason": "", "stats": star}],
           "1": [{"id": "o", "name": "Autre Joueur", "short": "A. Joueur", "starter": True, "dnp": False, "reason": "", "stats": other}]}
    g = {"id": "999", "utc": "2026-10-25T23:30Z", "day": date(2026, 10, 25), "state": "post", "completed": True, "status": "STATUS_FINAL",
         "detail": "Final", "period": 4 + n_ot, "home": {"id": "2", "score": hs, "winner": hs > as_, "lines": lines(hs)},
         "away": {"id": "1", "score": as_, "winner": as_ > hs, "lines": lines(as_)}, "venue": "Salle", "city": "", "neutral": False,
         "notes": [], "season": 2027, "season_type": 2, "tv": ""}
    summ = {"article": {}, "injuries": {}, "home_pct": None, "line": "", "total": None, "leaders": {}, "box": box, "team_stats": {},
            "shots": [], "plays": plays}
    return g, summ
