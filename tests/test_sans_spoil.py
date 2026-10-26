"""Test anti-spoil : une carte au score caché ne doit rien trahir du match.
Lancer : python tests/test_sans_spoil.py (ou pytest). À passer avant chaque envoi qui touche aux cartes ou à l'indice."""
import re

from outils import charger_app, match
from scenarios import SCENARIOS

MOTS_INTERDITS = ["prolongation", "remontée", "serrée", "retard", "décisif", "buzzer", "perf", "retournement", "festival",
                  "changements de leader", "rebondissement", "bat ", "victoire", "défaite", "mène", "a gagné"]


def partie_visible(html):
    """Ce que voit quelqu'un qui n'a rien révélé : sans le panneau du score, le score réel ni l'essentiel caché."""
    html = re.sub(r"<div class='fiche post'>.*$", "", html, flags=re.S)  # fiche d'un match joué : l'ouvrir = demander le score
    html = re.sub(r"<span class='sc-real[^']*'>(?:<span[^>]*>[^<]*</span>|[^<])*</span>", "", html)
    return re.sub(r"<div class='ess-hid'>.*?<!--fin-ess-->", "", html, flags=re.S)


def verifier(app, nom, cles, **extra):
    g, summ = match(app, cles, **extra)
    w = app["watch_score"](g, summ)
    ctx = {"zone": "Paris", "idx": {}, "summ": {g["id"]: summ}, "watch": {g["id"]: w}, "vids": {g["id"]: (None, None)}, "durs": {},
           "favs": set(), "ranks": {}, "ai": False, "show_all": False, "nba_vids": [], "extra_vids": [], "recap": None, "show": None}
    ctx["summ"][g["id"]] = summ
    vue = (partie_visible(app["game_card"](g, ctx)) + partie_visible(app["game_card"](g, ctx, hero=True)) + partie_visible(app["night_html"](g["day"], [g], ctx, g["day"]))
           + partie_visible(app["week_html"]([g["day"]], {g["day"]: [g]}, ctx["summ"], ctx["watch"], ctx)))
    assert "infos de la nuit" in vue.lower() and "meilleurs matchs de la semaine" in vue.lower(), f"{nom} : en-tête ou semaine absents"
    texte = re.sub(r"<[^>]+>", " ", vue).lower()
    for mot in MOTS_INTERDITS:
        assert mot not in texte, f"{nom} : le mot « {mot} » est visible avant le score"
    for score in (g["home"]["score"], g["away"]["score"]):
        assert not re.search(rf"\b{score}\b", texte), f"{nom} : le score {score} est visible avant le score"
    # Une fois le score révélé, les raisons de la note sont bien là
    if w and w[1]:
        assert w[1][0] in app["game_card"](g, ctx), f"{nom} : raisons absentes du panneau du score"
    # Et l'essentiel de la nuit révélé contient bien les résultats
    assert str(g["home"]["score"]) in app["night_html"](g["day"], [g], ctx, g["day"]), f"{nom} : résultats absents de l'essentiel"


def test_aucun_spoil():
    app = charger_app()
    for nom, cles in SCENARIOS.items():
        extra = {"star_pts": 55, "star_reb": 8, "star_ast": 6} if "55" in nom else {}
        verifier(app, nom, cles, **extra)


if __name__ == "__main__":
    test_aucun_spoil()
    print(f"OK : {len(SCENARIOS)} matchs vérifiés, rien n'est trahi avant le score.")
