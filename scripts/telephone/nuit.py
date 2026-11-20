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


# ---------- les plus belles actions : pour chacune, le match (sigles du bandeau), le moment (chrono, score), le joueur ----------
ALIAS = {"NY": ["NYK", "NY"], "GS": ["GSW", "GS"], "SA": ["SAS", "SA"], "NO": ["NOP", "NO"], "UTAH": ["UTA", "UTAH"],
         "WSH": ["WAS", "WSH"], "PHX": ["PHX", "PHO"], "BKN": ["BKN", "BRK"], "CHA": ["CHA", "CHO"]}


def sigles(ab):
    return ALIAS.get(ab, [ab])


def noms(gid):
    j = lire(ESPN + "summary?event=" + str(gid))
    out = {}
    for side in (j.get("boxscore") or {}).get("players", []):
        for a in side["statistics"][0].get("athletes", []):
            if a.get("athlete"):
                out[str(a["athlete"].get("id"))] = a["athlete"].get("displayName", "")
    return out


def carton(img):
    """Les cartons « 5 », « 4 »… entre deux actions du top : une image presque toute bleue (ou le classement qui suit)."""
    small = img.convert("RGB").resize((32, 12))
    px = list(small.getdata())
    r = sum(p[0] for p in px) / len(px)
    g = sum(p[1] for p in px) / len(px)
    b = sum(p[2] for p in px) / len(px)
    return b > 70 and r < 60 and b > r + 40  # mesuré : cartons b 76-93 / r 15-36 ; classement qui suit b 72 / r 35 (exclu)


def actions(frames_dir, frames, ch, Ds):
    """Le top 5 : les cartons bleus découpent les actions ; dans chacune, le bandeau (sigles, chrono, score) donne le match
    et le moment, et l'action est le prochain panier ESPN de ce match (le bandeau se voit juste avant le geste)."""
    ts = list(range(ch["s"], min(ch["e"], len(frames) * cv.PAS), cv.PAS))
    imgs = {t: Image.open(os.path.join(frames_dir, frames[t // cv.PAS])) for t in ts}
    bleu = {t: carton(imgs[t]) for t in ts}
    # les actions : ce qui suit chaque carton, jusqu'au carton suivant
    seg, cur = [], None
    for t in ts:
        if bleu[t]:
            if cur and cur["t"]:
                seg.append(cur)
            cur = {"s": t, "t": []}
        elif cur is not None:
            cur["t"].append(t)
    if cur and cur["t"]:
        seg.append(cur)
    seg = [x for x in seg if len(x["t"]) >= 4][:5]
    out = []
    for n, x in enumerate(seg):
        a = {"s": x["s"], "e": seg[n + 1]["s"] if n + 1 < len(seg) else (x["t"][-1] + 1), "r": len(seg) - n}
        lect = []  # (t, gid, quart lu ou None, [chronos possibles], nombres)
        for t in x["t"][:12]:  # le bandeau apparaît au début de l'action
            words = []
            scale = max(.8, min(2.4, 2000 / imgs[t].width))
            for mode in ("gray", "inv"):
                words += cv.ocr(cv.prep(imgs[t], scale, mode), 11)
            txt = {re.sub(r"[^A-Z]", "", w["t"].upper()) for w in words}
            best = None
            for gid, D in Ds.items():
                hits = sum(any(z in txt for z in sigles(D["ab"][k])) for k in ("away", "home"))
                if hits and (best is None or hits > best[0]):
                    best = (hits, gid)
            if not best:
                continue
            q = cv.find_quarter(words)
            horl = set()
            for w in words:  # « 6:27 » (pas de « 627 » : les bilans « 12-3 » se lisent « 123 »)
                m = re.search(r"(\d{1,2})[:;](\d{2})(?!\d)", w["t"])
                if m and int(m.group(2)) < 60 and int(m.group(1)) <= 12:
                    horl.add(int(m.group(1)) * 60 + int(m.group(2)))
            lect.append((t, best[1], q[0] if q else None, horl, cv.nombres([w["t"] for w in words])))
        if lect:
            gid = max({r[1] for r in lect}, key=lambda g: sum(1 for r in lect if r[1] == g))
            D, L = Ds[gid], [r for r in lect if r[1] == gid]
            a["gid"] = gid
            E, P = D["etats"], D["plays"]
            nums = {}
            for r in L:
                for v, c in r[4].items():
                    nums[v] = nums.get(v, 0) + c
            quarts = {r[2] for r in L if r[2]}
            cands = []  # (soutien, quart lu ?, temps de jeu) : le moment du bandeau
            for r in L:
                for sec in r[3]:
                    for per in (quarts or {1, 2, 3, 4}):
                        el = cv.ecoule(per, sec) + cv.RETARD
                        k = max(i for i, e in enumerate(E) if e["el"] <= el)
                        sout = sum(1 for v in (E[k]["as"], E[k]["hs"]) if v >= 10 and nums.get(v))
                        cands.append((sout, per in quarts, el))
            jeu = None
            if cands:
                sout, lu, el = max(cands)
                if sout or lu:
                    # l'action : le panier suivant dans ce match (ni lancer franc), dans la minute
                    for p in P:
                        if p["pts"] and p["a0"] and p["el"] >= el - 2 and not re.search(r"free throw", p["tx"], re.I):
                            if p["el"] - el <= 60:
                                jeu = p
                            break
            if jeu:
                a.update(aid=str(jeu["a0"]), per=jeu["per"], sec=jeu["sec"], tx=jeu["tx"])
                try:
                    a["n"] = D.setdefault("noms", noms(gid)).get(str(jeu["a0"]), "")
                except Exception:
                    pass
        out.append(a)
    return out


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
        potn = next((c for c in chs if c["k"] == "potn"), None)
        if potn:
            try:
                p = joueur_de_la_nuit(video, potn, candidats(chs), tmp)
                if p:
                    potn.update(p)
                    if p["gid"] not in Ds:
                        Ds[p["gid"]] = cv.deroule(p["gid"])
                    pts, BRUT["potn"] = cv.lire_plage(b, frames, potn["s"], potn["e"], Ds[p["gid"]])  # ses actions, calées sur son match
                    potn["pts"] = pts
                print("  joueur de la nuit :", p, len(potn.get("pts") or []), "points", flush=True)
            except Exception as e:
                print("  joueur de la nuit illisible :", e, flush=True)
        top = next((c for c in chs if c["k"] == "top"), None)
        if top and Ds:
            try:
                top["plays"] = actions(b, frames, top, Ds)
                print("  plus belles actions :", [(a.get("n"), a["s"]) for a in top["plays"]], flush=True)
            except Exception as e:
                print("  plus belles actions illisibles :", e, flush=True)
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
