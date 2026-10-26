"""Affiche la note d'intérêt de matchs inventés : python tests/scenarios.py"""
from outils import charger_app, match

app = None
SCENARIOS = {
    "Prolongation après -15 au 1er QT": [(0, 0), (10, -15), (30, -4), (44, 2), (48, 0), (53, 3)],
    "Fin serrée, +2": [(0, 0), (12, 4), (24, -3), (36, 5), (45, -2), (47, 1), (48, 2)],
    "Panier au buzzer, +1": [(0, 0), (12, 6), (24, 9), (36, 4), (44, 3), (47.9, -1), (48, 1)],
    "Match normal, +9": [(0, 0), (12, 3), (24, 6), (36, 5), (42, 4), (48, 9)],
    "Écart de 12-15 en 2e mi-temps": [(0, 0), (12, 6), (24, 12), (36, 15), (48, 14)],
    "Plié à la 10e minute, +30": [(0, 0), (10, 22), (24, 28), (36, 32), (48, 30)],
    "Plié tôt mais 55 pts d'un joueur": [(0, 0), (12, 14), (24, 20), (36, 22), (48, 19)],
    "Remontée de 25 pts mais perdue de 6": [(0, 0), (18, -25), (36, -10), (44, -3), (48, -6)],
}
def afficher():
  global app
  app = charger_app()
  for name, cles in SCENARIOS.items():
      extra = {"star_pts": 55, "star_reb": 8, "star_ast": 6} if "55" in name else {}
      g, summ = match(app, cles, **extra)
      lv, why, note = app["watch_score"](g, summ)
      icon, label, _ = app["WATCH_LEVELS"][lv]
      print(f"{icon:8} {label:15} note {note:6}  {name}   [{', '.join(why)}]")


if __name__ == "__main__":
    afficher()
