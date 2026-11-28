#!/usr/bin/env python3
"""Nocturne : le « Résumé de la nuit » augmenté (NBA's Nightly Recap, ~15-20 min, chapitré).

Pour chaque résumé de la nuit :
  1. les chapitres YouTube (yt-dlp, sans télécharger) : « Knicks at Timberwolves », …, « Player of the Night »,
     « Top Plays of the Night » ; chaque chapitre de match est relié à son match ESPN ;
     publié tout de suite (le site peut déjà montrer la liste et sauter d'un match à l'autre) ;
  2. la vidéo (720p), le chrono du bandeau lu chapitre par chapitre (chrono_video : même lecture que les
     résumés de match), puis la fin du résumé (fin()) : le joueur de la nuit, les plus belles actions, le classement,
     repérés À L'IMAGE (les chapitres YouTube sont décalés de 2 à 10 s) ;
  3. publié dans v2/nuit/<nuit NY>.json sur la branche data.

    python nuit.py <id_youtube>     # essai sur une vidéo (écrit nuit_<id>.json ici, ne publie rien)
    python nuit.py --fin <nuit.json> <video> [seconde du début de la vidéo]   # refait seulement la fin d'une nuit (remplace le .json)
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
from datetime import datetime

from PIL import Image

import chrono_video as cv

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"


def lire(url, essais=5):
    """ESPN, avec de nouvelles tentatives : le wifi du téléphone a des trous (DNS, réseau injoignable)."""
    for k in range(essais):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except Exception:
            if k == essais - 1:
                raise
            time.sleep(20 * (k + 1))


def est_recap(v):
    return v.get("c") == "nba" and "nightly recap" in (v.get("t") or "").lower()


def nuit_de(titre):
    """« NBA's Nightly Recap | November 19, 2026 » → 20261119 (la nuit, heure de New York)."""
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", titre or "")
    return datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y%m%d") if m else None


_CHAPITRES = {}  # 28/11 : analyse() est appelée 2 fois (chapitres, puis vidéo) : une seule demande à YouTube


def chapitres(vid):
    if vid not in _CHAPITRES:
        _CHAPITRES[vid] = _chapitres(vid)
    return _CHAPITRES[vid]


def _chapitres(vid):
    out = subprocess.run(["yt-dlp", "-J", "--no-warnings", "--skip-download", "https://www.youtube.com/watch?v=" + vid],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    return int(d.get("duration") or 0), [{"s": int(c["start_time"]), "e": int(c["end_time"]), "t": c["title"].strip()}
                                         for c in d.get("chapters") or []]


def surnoms(c):
    n = (c.get("team", {}).get("name") or "").lower()
    return {"76ers": ["76ers", "sixers"], "trail blazers": ["trail blazers", "blazers"]}.get(n, [n])


def relier(chs, jour):
    """Chaque chapitre : un match (gid), le joueur de la nuit (potn) ou les plus belles actions (top)."""
    evs = lire(ESPN + "scoreboard?dates=" + jour).get("events", [])
    for c in chs:
        t = c["t"].lower()
        if "player of the night" in t or "player of the game" in t:
            c["k"] = "potn"
        elif "top" in t and "play" in t:
            c["k"] = "top"
        else:
            for ev in evs:
                cs = ev["competitions"][0].get("competitors", [])
                if len(cs) == 2 and all(any(n and n in t for n in surnoms(x)) for x in cs):
                    c["k"], c["gid"] = "match", ev["id"]
                    break
            else:
                c["k"] = "autre"
    return evs


def sans_accents(s):
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn").upper()


def candidats(chs):
    """Tous les joueurs de la nuit (feuilles de match ESPN), avec leurs points, rebonds et passes."""
    out = []
    for c in chs:
        if c.get("k") != "match":
            continue
        try:
            j = lire(ESPN + "summary?event=" + c["gid"])
        except Exception:
            continue
        for side in (j.get("boxscore") or {}).get("players", []):
            st = side["statistics"][0]
            names = st.get("names", [])
            for a in st.get("athletes", []):
                if not a.get("athlete") or not a.get("stats"):
                    continue
                v = dict(zip(names, a["stats"]))
                f = lambda k: int(v[k]) if str(v.get(k) or "").isdigit() else 0
                out.append({"aid": str(a["athlete"].get("id")), "n": a["athlete"].get("displayName", ""), "gid": c["gid"],
                            "pts": f("PTS"), "reb": f("REB"), "ast": f("AST")})
    return out


# ---------- la fin du résumé : joueur de la nuit, plus belles actions, classement ----------
# Même habillage tous les soirs (vérifié du 20 au 24/11) : un carton = un disque bleu sur fond noir (« PLAYER OF THE NIGHT »,
# puis « 10 »… « 1 ») ; le nom du joueur dans une plaque en bas à gauche, juste après son carton ; le classement = images presque fixes, jusqu'à la fin.
def carton(img):
    s = img.convert("RGB").resize((64, 36))
    bleu = all(b > 80 and r < 30 and g < 80 and b > r + 60 for r, g, b in (s.getpixel((x, 18)) for x in (24, 40)))
    return bleu and all(max(s.getpixel(q)) < 50 for q in ((2, 1), (62, 1)))


def suites(vrais, trou=1.0):
    """[(t, vrai ?)] → les plages [début, fin] où c'est vrai (les trous de `trou` s ou moins sont comblés)."""
    out = []
    for t, v in vrais:
        if v:
            if out and t - out[-1][1] <= trou:
                out[-1][1] = t
            else:
                out.append([t, t])
    return out


def ecart(a, b):
    return sum(abs(x - y) for x, y in zip(a.tobytes(), b.tobytes())) / (a.width * a.height)


def plaque(img):
    """Les lectures de la plaque (toujours au même endroit : x 57-660, y 565-685 sur 1280×720) : la ligne du nom, puis tout."""
    k = img.width / 1280
    zone = lambda *q: img.crop(tuple(int(v * k) for v in q))
    out = []
    for q, sc, psm in (((62, 568, 380, 640), 2, 7), ((62, 568, 520, 640), 2, 7), ((40, 555, 660, 692), 1, 11), ((40, 555, 660, 692), 2, 11)):
        for mode in ("gray", "inv"):
            out.append(sans_accents(" ".join(w["t"] for w in cv.ocr(cv.prep(zone(*q), sc / k, mode), psm))))
    return out


def nom_lu(images, cands):
    """Le joueur écrit sur la plaque (« JAYSON TATUM / 41 PTS, 6 REB, 8 AST VS. WAS »). images = les lectures de chaque image.
    Le nom exact compte 3, presque exact 1 (« JAVSON »), le nom de famille seul 1, ses stats 1. Rien de sûr = personne
    (24/11 : une devinette avait donné Flagg au lieu de Tatum)."""
    best = []
    for p in cands:
        parts = [re.sub(r"[^A-Z]", "", x) for x in sans_accents(p["n"]).split()]
        if len(parts) > 2 and parts[-1] in ("JR", "SR", "II", "III", "IV"):
            parts = parts[:-1]
        nom, sc, n = "".join(parts), 0, 0
        for textes in images:
            v = 0
            for tx in textes:
                lettres = re.sub(r"[^A-Z]", "", tx)
                if len(nom) >= 6 and nom in lettres:
                    v = max(v, 3)
                elif difflib.SequenceMatcher(None, nom, lettres).ratio() >= .8 or (
                        len(parts[-1]) >= 4 and re.search(r"(?<![A-Z])%s(?![A-Z])" % parts[-1], tx)):
                    v = max(v, 1)
            lus = {k: {x for tx in textes for x in re.findall(r"(\d+)\s*" + k, tx)} for k in ("PTS", "REB", "AST")}
            if v and str(p["pts"]) in lus["PTS"] and (str(p["reb"]) in lus["REB"] or str(p["ast"]) in lus["AST"]):
                v += 1
            sc += v
            n += v > 0
        if n >= 2 and sc >= 4:
            best.append((sc, p["pts"], p))
    best.sort(key=lambda b: b[:2], reverse=True)
    if not best or (len(best) > 1 and best[1][0] > best[0][0] * .75):
        return None
    return {"aid": best[0][2]["aid"], "n": best[0][2]["n"], "gid": best[0][2]["gid"], "lu": best[0][0]}


def fin(chs, video, decal=0):
    """Remet à leur vraie place les chapitres de la fin (cartons, image fixe du classement), lit le joueur de la nuit et
    découpe les plus belles actions. decal = la seconde du résumé où commence le fichier vidéo (0 = vidéo entière)."""
    hors = [c for c in chs if c["k"] != "match"]
    if not hors:
        return
    deb = max(decal, hors[0]["s"] - 20)
    tmp = tempfile.mkdtemp(prefix="nocturne_fin_")
    try:
        vues = os.path.join(tmp, "vues")
        os.makedirs(vues)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(deb - decal), "-i", video, "-vf", "fps=2,scale=320:180",
                        "-q:v", "3", os.path.join(vues, "%05d.jpg")], check=True)
        cartes, gris = [], []
        for k, name in enumerate(sorted(os.listdir(vues))):
            img = Image.open(os.path.join(vues, name))
            cartes.append((deb + k / 2, carton(img)))
            gris.append(img.convert("L").resize((80, 45)))
        cartes = suites(cartes)
        potn = next((c for c in chs if c["k"] == "potn"), None)
        top = next((c for c in chs if c["k"] == "top"), None)
        lim = top["s"] - 12 if top else 1e9
        # le joueur de la nuit : son carton, puis la plaque à son nom dans les 14 s qui suivent
        pot = [g for g in cartes if potn and potn["s"] - 15 <= g[0] <= min(potn["s"] + 15, lim)][:1]
        if potn:
            t0 = pot[0][1] if pot else potn["s"] - 6
            if pot:
                potn["s"] = int(pot[0][0])
            d = os.path.join(tmp, "plaque")
            os.makedirs(d)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(max(0, t0 - decal)), "-t", "14", "-i", video,
                            "-vf", "fps=2", os.path.join(d, "%03d.png")], check=True)
            textes = [plaque(Image.open(os.path.join(d, name))) for name in sorted(os.listdir(d))]
            for k in ("aid", "n", "gid", "lu", "par", "pts"):
                potn.pop(k, None)
            BRUT["plaque"] = textes
            p = nom_lu(textes, candidats(chs))
            if p:
                potn.update(p)
            print("  joueur de la nuit :", p, "à", potn["s"], flush=True)
        # les plus belles actions : un carton par action, du dernier rang au n° 1
        if top:
            m = re.search(r"top (\d+)", top["t"].lower())
            prevu = int(m.group(1)) if m else 10
            g = [x for x in cartes if x[0] >= top["s"] - 12 and x not in pot][-prevu:]
            if len(g) >= 3:
                top["s"] = int(g[0][0])
                top["plays"] = [{"s": x[0], "e": g[k + 1][0] if k + 1 < len(g) else top["e"], "r": len(g) - k} for k, x in enumerate(g)]
            else:
                top["plays"] = []
            print("  plus belles actions :", len(g), "cartons", [x[0] for x in g], flush=True)
        # le classement : les images presque fixes (léger zoom au plus) qui s'enchaînent jusqu'à la fin de la vidéo
        der = cartes[-1][1] + 3 if cartes else deb
        bouts = suites([(deb + k / 2, deb + k / 2 > der and ecart(gris[k], gris[k - 1]) < 4.5) for k in range(1, len(gris))], .5)
        fixe, suite = [], deb + len(gris) / 2
        for x in reversed([x for x in bouts if x[1] - x[0] >= 5]):
            if suite - x[1] > 4:
                break
            fixe.insert(0, x)
            suite = x[0]
        cl = [c for c in chs if "standings" in c["t"].lower()]
        for c, x in zip(cl, fixe if len(fixe) >= len(cl) else []):
            c["s"] = int(x[0] - (1.5 if c is cl[0] else .5))  # l'animation qui l'amène
        print("  classement :", [(c["t"], c["s"]) for c in cl], fixe, flush=True)
        for a, b in zip(chs, chs[1:]):
            a["e"] = b["s"]
        if top and top.get("plays"):
            top["plays"][-1]["e"] = top["e"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


BRUT = {}


def analyse(vid, titre, video=None, publier=None):
    """Tout le travail pour un résumé de la nuit. publier(dict) est appelé avec les chapitres seuls, puis complet."""
    jour = nuit_de(titre)
    duree, chs = chapitres(vid)
    if not jour or len(chs) < 2:
        return None
    relier(chs, jour)
    res = {"v": vid, "t": titre, "nuit": jour, "d": duree, "ch": chs, "fait": False}
    if publier:
        publier(dict(res))
    if not video:
        return res
    tmp = tempfile.mkdtemp(prefix="nocturne_nuit_")
    try:
        # le bandeau (bas de l'image), une image par seconde, pour toute la vidéo
        b = os.path.join(tmp, "b")
        os.makedirs(b)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-vf",
                        f"fps=1/{cv.PAS},crop=iw:ih*{cv.BANDE}:0:ih*{1 - cv.BANDE}", os.path.join(b, "%05d.png")], check=True)
        frames = sorted(os.listdir(b))
        Ds = {}  # le déroulé ESPN de chaque match (les scores successifs servent à caler la vidéo)
        for c in chs:
            if c.get("gid") and c["gid"] not in Ds:
                try:
                    Ds[c["gid"]] = cv.deroule(c["gid"])
                except Exception as e:
                    print("  déroulé illisible", c["gid"], e, flush=True)
        for c in chs:
            if c["k"] != "match":
                continue
            # le bandeau change d'une chaîne à l'autre : nouvelle recherche à chaque match ; chrono + scores lus à l'écran
            pts, brut = cv.lire_plage(b, frames, c["s"], c["e"], Ds.get(c["gid"]))
            c["pts"] = pts if len(pts) >= 8 else []
            BRUT[c["t"]] = brut
            print(f"  {c['t']} : {len(brut)} lectures, {len(c['pts'])} gardées", flush=True)
            if publier and c["pts"]:  # au fil de l'eau : les stats d'un match sont en ligne dès qu'il est lu
                try:
                    publier(dict(res))
                except Exception as e:
                    print("  publication intermédiaire ratée :", e, flush=True)
        try:
            fin(chs, video)
        except Exception as e:
            print("  fin du résumé illisible :", e, flush=True)
        res["fait"] = True
        try:  # les lectures brutes, à côté (pour recaler sans relire la vidéo)
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "brut_%s.json" % vid), "w") as f:
                json.dump(BRUT, f)
        except Exception:
            pass
        if publier:
            publier(res)
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit()
    if sys.argv[1] == "--fin":
        with open(sys.argv[2]) as f:
            r = json.load(f)
        fin(r["ch"], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 0)
        with open(sys.argv[2], "w") as f:
            json.dump(r, f, separators=(",", ":"))
        sys.exit()
    vid = sys.argv[1]
    titre = json.loads(subprocess.run(["yt-dlp", "-J", "--no-warnings", "--skip-download", "https://www.youtube.com/watch?v=" + vid],
                                      capture_output=True, text=True).stdout).get("title", "")
    video = os.path.join(tempfile.gettempdir(), vid + ".mp4")
    if not os.path.exists(video):
        subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "bv*[height=720][vcodec^=avc1]/bv*[height=720][vcodec^=vp]/bv*[height=720]/bv*[height<=720]",
                        "-o", video, "https://www.youtube.com/watch?v=" + vid], check=True)
    r = analyse(vid, titre, video)
    with open("nuit_%s.json" % vid, "w") as f:
        json.dump(r, f, separators=(",", ":"))
    print("écrit nuit_%s.json" % vid)
