"""Un résumé ESPN arrêté en plein match (stats du 1er quart-temps seulement) ne doit pas être gardé comme définitif :
python tests/test_resume_complet.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from outils import charger_app

app = charger_app()
ok = app["summary_complete"]


def resume(pts_visiteurs, pts_domicile, derniere=None):
    box = {"1": [{"dnp": False, "stats": {"PTS": str(p)}} for p in pts_visiteurs] + [{"dnp": True, "stats": {}}],
           "2": [{"dnp": False, "stats": {"PTS": str(p)}} for p in pts_domicile]}
    plays = [(1, "0:00", 21, 19, True, "", "1")] + ([derniere] if derniere else [])
    return {"box": box, "plays": plays}


complet = resume([50, 53], [60, 50], (4, "0:00", 103, 110, False, "End of Game", None))
assert ok(complet, 110, 103), "résumé complet refusé"
assert not ok(resume([10, 11], [9, 10]), 110, 103), "résumé du 1er quart-temps accepté"
assert not ok(resume([50, 53], [60, 50]), 110, 103), "box complet mais dernière action au 1er quart-temps : accepté"
assert ok({"box": complet["box"], "plays": []}, 110, 103), "sans actions, le box score suffit"
assert not ok(None, 110, 103) and not ok({"box": {}, "plays": []}, 110, 103)
assert not ok(complet, None, None), "score final inconnu : on ne peut pas vérifier"

# final_summary : un résumé incomplet n'est pas gardé, le complet l'est (et resservi sans rappeler ESPN)
calls = []
answers = [resume([10, 11], [9, 10]), complet]
app["summary"] = lambda i, b: (calls.append(i), answers[len(calls) - 1])[1]
app["disk_get"] = lambda n: None
app["disk_put"] = lambda n, v: None
store = {}
app["_final_summaries"] = lambda: store
assert not ok(app["final_summary"]("42", 110, 103), 110, 103)
assert app["final_summary"]("42", 110, 103) is complet
assert app["final_summary"]("42", 110, 103) is complet and len(calls) == 2
print("OK : les résumés incomplets d'ESPN sont redemandés, les complets gardés.")

F = app["F"]
assert F.partial_game({"p": {str(i): [10, 12, 1, "1"] for i in range(10)}}), "match du 1er quart-temps non repéré"
assert not F.partial_game({"p": {str(i): [10, 24, 1, "1"] for i in range(20)}}), "match complet pris pour incomplet"
assert not F.partial_game({"p": {str(i): [10, 0, 1, "1"] for i in range(20)}}), "sans minutes : on ne juge pas"
print("OK : les matchs fantasy enregistrés incomplets sont repérés.")
