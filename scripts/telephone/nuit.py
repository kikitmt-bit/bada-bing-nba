#!/usr/bin/env python3
"""Nocturne : le « Résumé de la nuit » augmenté (NBA's Nightly Recap, ~15-20 min, chapitré).

Pour chaque résumé de la nuit :
  1. les chapitres YouTube (yt-dlp, sans télécharger) : « Knicks at Timberwolves », …, « Player of the Night »,
     « Top Plays of the Night » ; chaque chapitre de match est relié à son match ESPN ;
     publié tout de suite (le site peut déjà montrer la liste et sauter d'un match à l'autre) ;
  2. la vidéo (720p), le chrono du bandeau lu chapitre par chapitre (chrono_video : même lecture que les
     résumés de match), et le nom du « Player of the Night » lu à l'écran ;
  3. publié dans v2/nuit/<nuit NY>.json sur la branche data.

    python nuit.py <id_youtube>     # essai sur une vidéo (écrit nuit_<id>.json ici, ne publie rien)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import urllib.request
from datetime import datetime

from PIL import Image

import chrono_video as cv

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/"


def lire(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def est_recap(v):
    return v.get("c") == "nba" and "nightly recap" in (v.get("t") or "").lower()


def nuit_de(titre):
    """« NBA's Nightly Recap | November 19, 2026 » → 20261119 (la nuit, heure de New York)."""
    m = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", titre or "")
    return datetime.strptime(m.group(1), "%B %d, %Y").strftime("%Y%m%d") if m else None


def chapitres(vid):
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
    """Les joueurs de la nuit (feuilles de match ESPN), les meilleurs d'abord."""
    out = []
    for c in chs:
        if c.get("k") != "match":
            continue
        try:
            j = lire(ESPN + "summary?event=" + c["gid"])
        except Exception:
            continue
        for side in (j.get("boxscore") or {}).get("players", []):
            ab = (side.get("team") or {}).get("abbreviation", "").upper()
            st = side["statistics"][0]
            names = st.get("names", [])
            for a in st.get("athletes", []):
                if not a.get("athlete") or not a.get("stats"):
                    continue
                v = dict(zip(names, a["stats"]))
                f = lambda k: float(v.get(k) or 0) if re.match(r"^-?\d+(\.\d+)?$", str(v.get(k) or "")) else 0
                gs = f("PTS") + 1.2 * f("REB") + 1.5 * f("AST") + 2 * f("BLK") + 2 * f("STL")
                out.append({"aid": str(a["athlete"].get("id")), "n": a["athlete"].get("displayName", ""), "gs": gs, "gid": c["gid"], "ab": ab})
    out.sort(key=lambda p: -p["gs"])
    return out[:14], out  # le nom est cherché parmi les 14 grosses perfs (moins de fausses lectures) ; la liste complète sert au repli


def joueur_de_la_nuit(video, ch, cands_tous, tmp):
    """Lit le texte à l'écran pendant le chapitre « Player of the Night » (une image toutes les 2 s) et y cherche
    les noms des grosses perfs de la nuit. Le nom le plus souvent lu l'emporte (au moins 2 images)."""
    d = os.path.join(tmp, "potn")
    os.makedirs(d, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(ch["s"]), "-to", str(ch["e"]), "-i", video,
                    "-vf", "fps=1/2", os.path.join(d, "%04d.png")], check=True)
    cands, tous = cands_tous
    score = {p["aid"]: 0 for p in cands}
    sigles = {}  # sigles d'équipe lus dans le bandeau (« POR 14 1ST 4:05 19 MIL ») : le match du joueur, en repli
    for name in sorted(os.listdir(d)):
        img = Image.open(os.path.join(d, name))
        mots = set()
        for mode in ("gray", "inv"):
            for w in cv.ocr(cv.prep(img, 1, mode), 11):
                mots.add(re.sub(r"[^A-Z'-]", "", sans_accents(w["t"])))
        for ab in {p["ab"] for p in tous if p["ab"]}:
            if ab in mots:
                sigles[ab] = sigles.get(ab, 0) + 1
        for p in cands:
            parts = [x for x in re.split(r"[\s.]+", sans_accents(p["n"])) if len(x) >= 3]
            if parts and parts[-1] in mots:
                score[p["aid"]] += 2 if len(parts) > 1 and parts[0] in mots else 1
    best = max(cands, key=lambda p: (score[p["aid"]], p["gs"]), default=None)
    if best and score[best["aid"]] >= 2:
        return {"aid": best["aid"], "n": best["n"], "gid": best["gid"], "lu": score[best["aid"]]}
    # repli : le match dont les sigles reviennent le plus dans le bandeau, et sa meilleure perf
    par_match = {}
    for p in tous:
        if p["ab"]:
            par_match.setdefault(p["gid"], set()).add(p["ab"])
    gid = max(par_match, key=lambda g: sum(sigles.get(a, 0) for a in par_match[g]), default=None)
    if gid and sum(sigles.get(a, 0) for a in par_match[gid]) >= 4:
        p = max((p for p in tous if p["gid"] == gid), key=lambda p: p["gs"])
        return {"aid": p["aid"], "n": p["n"], "gid": gid, "lu": 0, "par": "bandeau"}
    return None


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
        for c in chs:
            if c["k"] != "match":
                continue
            lec, brut = cv.Lecteur(), []  # le bandeau change d'une chaîne à l'autre : nouvelle recherche à chaque match
            for k in range(c["s"], min(c["e"], len(frames) * cv.PAS), cv.PAS):
                r = lec.lire(Image.open(os.path.join(b, frames[k // cv.PAS])))
                if r:
                    brut.append((k,) + tuple(r))
            pts = cv.nettoyer(brut)
            c["pts"] = pts if len(pts) >= 8 else []
            print(f"  {c['t']} : {len(brut)} lectures, {len(c['pts'])} gardées", flush=True)
        potn = next((c for c in chs if c["k"] == "potn"), None)
        if potn:
            try:
                p = joueur_de_la_nuit(video, potn, candidats(chs), tmp)
                if p:
                    potn.update(p)
                print("  joueur de la nuit :", p, flush=True)
            except Exception as e:
                print("  joueur de la nuit illisible :", e, flush=True)
        res["fait"] = True
        if publier:
            publier(res)
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
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
