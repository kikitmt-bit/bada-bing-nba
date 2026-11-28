#!/usr/bin/env python3
"""Nocturne : la boucle du téléphone-serveur.

Toutes les 20 minutes : met à jour la liste des résumés (v2/videos.json, flux RSS des chaînes),
analyse chaque nouveau résumé de match (chrono_video.py) et publie la table sur la branche
data du dépôt (v2/chrono/<id>.json + v2/chrono/index.json), que le site lit directement.

    python boucle.py          # tourne sans fin (lancé au démarrage du téléphone)
    python boucle.py --une    # un seul passage (tests)
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import chrono_video
import nuit

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # scripts/ en local ; sur le téléphone, v2_videos.py est copié à côté
import v2_videos  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))
DEPOT = os.path.join(ICI, "depot")          # clone léger de la branche data
TRAVAIL = os.path.join(ICI, "travail")
ETAT = os.path.join(ICI, "etat.json")       # vidéos déjà traitées (ou ratées)
LISTE = "https://raw.githubusercontent.com/kikitmt-bit/bada-bing-nba/data/v2/videos.json"
REMOTE = "git@github.com:kikitmt-bit/bada-bing-nba.git"
JOURS = 3          # on ne regarde que les résumés des 3 derniers jours
DEPUIS = os.path.join(ICI, "depuis.txt")  # date ISO : rien avant (créée au 1er lancement : seulement les nouvelles soirées)
ESSAIS = 4         # au-delà, on abandonne une vidéo
ATTENTE = (300, 1800, 5400)  # après le 1er, 2e, 3e échec : 5 min, 30 min, 1 h 30 (24/11 : 3 essais en 15 min = 5 matchs perdus)
PAUSE = (1800, 3600, 7200)   # YouTube refuse (« not a bot ») : on ne lui demande plus rien pendant 30 min, 1 h, puis 2 h


def log(*a):
    print(time.strftime("%d/%m %H:%M:%S"), *a, flush=True)


def sh(*cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def charger(path, defaut):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return defaut


def erreur(ex):
    """Le texte utile d'un échec : les lignes ERROR de yt-dlp, sinon la fin du message."""
    t = getattr(ex, "stderr", "") or str(ex)
    i = t.find("ERROR")
    return t[i:i + 300].strip() if i >= 0 else t[-300:].strip()


def genre(ex):
    """« youtube » (il nous refuse : tout le monde attend), « reseau » (coupure internet) ou « echec » (la vidéo elle-même)."""
    t = (getattr(ex, "stderr", "") or str(ex)).lower()
    if any(m in t for m in ("not a bot", "http error 429", "rate-limited")):
        return "youtube"
    if any(m in t for m in ("network is unreachable", "no address associated", "could not resolve", "failed to resolve",
                            "name resolution", "timed out", "connection reset", "connection abort", "urlopen error")):
        return "reseau"
    return "echec"


def en_pause(etat):
    return etat.get("pause", {}).get("fin", 0) > time.time()


def rater(etat, e, ex):
    """Note un échec : un refus de YouTube ou une coupure internet ne compte pas comme un essai, le reste est réessayé
    de plus en plus tard."""
    g = genre(ex)
    if g == "echec":
        e["apres"] = time.time() + ATTENTE[min(e["essais"], len(ATTENTE)) - 1]
        return
    e["essais"] -= 1
    if g == "youtube" and not en_pause(etat):  # plusieurs analyses refusées ensemble = un seul refus
        n = etat.get("pause", {}).get("n", 0)
        d = PAUSE[min(n, len(PAUSE) - 1)]
        etat["pause"] = {"n": n + 1, "fin": time.time() + d}
        log("YouTube refuse : pause de %d min" % (d // 60))


def a_essayer(e):
    return e.get("ok") is None and e.get("essais", 0) < ESSAIS and e.get("apres", 0) <= time.time()


# ---------- la note « à voir » : LA MÊME que le site (docs/note.js, sur le déroulé ESPN), lancée avec Node.js ----------
# 28/11 (choix de Kiki) : le résumé de la nuit d'abord, puis les matchs du meilleur au moins bon, et plus de Replay +
# pour les matchs « Sans plus », « Bof » et « À fuir » (niveaux 2, 1, 0) : seulement Sympa (3), Génial (4), Immanquable (5).
SEUIL = 3
NOTEJS = next((c for c in (os.path.join(os.path.dirname(os.path.abspath(__file__)), "note.js"),
                           os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "note.js")) if os.path.exists(c)), None)
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="
EN_MEME_TEMPS = 3  # analyses en parallèle (le téléphone a 8 cœurs, une analyse n'en prend qu'un)
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates="
_SB = {}


def scoreboard(jour):
    if jour not in _SB:
        with urllib.request.urlopen(ESPN + jour, timeout=30) as r:
            _SB[jour] = json.load(r).get("events", [])
    return _SB[jour]


def winpct(rec):
    m = re.match(r"^(\d+)-(\d+)", rec or "")
    if not m:
        return .5
    w, l = int(m.group(1)), int(m.group(2))
    return w / (w + l) if w + l else .5


def jitter(gid):
    x = 0
    for c in str(gid):
        x = (x * 31 + ord(c)) % 997
    return (x / 997 - .5) * .7


def note_fine(ev):
    """(note continue, niveau 0 à 5) du site (docs/note.js sur le déroulé ESPN) ; sans Node ou sans déroulé : l'ancienne formule."""
    if NOTEJS:
        try:
            j = None
            for k in range(5):  # le wifi du téléphone a des trous
                try:
                    with urllib.request.urlopen(SUMMARY + str(ev["id"]), timeout=30) as r:
                        j = r.read()
                    break
                except Exception:
                    if k == 4:
                        raise
                    time.sleep(3)
            code = ("const N=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
                    "const r=N.rate(JSON.parse(s));console.log(JSON.stringify(r?[r.s,r.lvl]:null))})")
            out = subprocess.run(["node", "-e", code, NOTEJS], input=j, capture_output=True, timeout=60).stdout
            r = json.loads(out or b"null")
            if r:
                return float(r[0]), int(r[1])
        except Exception as ex:
            log("note fine impossible (%s), ancienne formule :" % ev.get("id"), str(ex)[-120:])
    n = note(ev)
    return float(n), n


def note(ev):
    """0 à 5 barres, l'ancienne formule sur le score final (secours)."""
    comp = ev["competitions"][0]
    sides, top = {}, 0
    for c in comp.get("competitors", []):
        rec = next((r.get("summary", "") for r in c.get("records", []) if r.get("type") == "total" or r.get("name") == "overall"), "")
        sides[c.get("homeAway")] = (int(c.get("score") or 0), rec)
        for L in c.get("leaders", []):
            if L.get("name") == "pointsLeader" or L.get("abbreviation") == "PTS":
                for l in L.get("leaders", []):
                    top = max(top, float(l.get("value") or 0))
    (hs, hr), (as_, ar) = sides.get("home", (0, "")), sides.get("away", (0, ""))
    st = comp.get("status") or ev.get("status") or {}
    ot = (st.get("type", {}).get("state") == "post") and (st.get("period") or 0) > 4
    marge = abs(hs - as_)
    n = 3 if marge <= 3 else 2.2 if marge <= 6 else 1.4 if marge <= 10 else .7 if marge <= 15 else 0
    if marge >= 25:
        n -= 1
    if ot:
        n += 1.4
    n += 1.2 if top >= 45 else .7 if top >= 38 else .3 if top >= 32 else 0
    if hs + as_ >= 245:
        n += .4
    n += (winpct(ar) + winpct(hr) - 1) * 1.2
    n += jitter(ev["id"])
    return max(0, min(5, int(n * 5 / 4.6 + .5)))


def surnoms(c):
    n = (c.get("team", {}).get("name") or "").lower()
    return {"76ers": ["76ers", "sixers"], "trail blazers": ["trail blazers", "blazers"]}.get(n, [n])


def match_de(v):
    """Le match ESPN d'un résumé : les deux surnoms dans le titre, joué la veille ou le jour de la publication (heure de New York)."""
    t = (v.get("t") or "").lower()
    try:
        pub = datetime.fromisoformat(v["p"].replace("Z", "+00:00"))
    except Exception:
        return None
    for d in (1, 0, 2):
        jour = (pub - timedelta(hours=5) - timedelta(days=d)).strftime("%Y%m%d")
        for ev in scoreboard(jour):
            comp = ev["competitions"][0]
            if (comp.get("status") or ev.get("status") or {}).get("type", {}).get("state") != "post":
                continue
            cs = comp.get("competitors", [])
            if len(cs) == 2 and all(any(n and n in t for n in surnoms(c)) for c in cs):
                return ev
    return None


def liste_videos():
    """Met à jour v2/videos.json (flux RSS des chaînes) : le robot GitHub planifié « toutes les 20 min » n'est lancé
    par GitHub que toutes les 6 à 9 h, trop tard pour les résumés du matin. Le téléphone le fait donc à chaque passage."""
    chemin = os.path.join(DEPOT, "v2", "videos.json")
    data = v2_videos.refresh(charger(chemin, {}))
    if data["videos"]:
        publier_fichiers({"v2/videos.json": data}, "vidéos v2 : mise à jour par le téléphone")
    return data["videos"]


def resumes(vids=None):
    """Les résumés de match récents de GameTime (celui que le site ouvre en premier). Pas ceux de la chaîne NBA : tous
    bloqués en France (50 essais, 0 réussi au 24/11), ils ne faisaient que multiplier les demandes à YouTube."""
    if vids is None:
        with urllib.request.urlopen(LISTE + "?t=%d" % time.time(), timeout=30) as r:
            vids = json.load(r).get("videos", [])
    lim = datetime.now(timezone.utc) - timedelta(days=JOURS)
    if not os.path.exists(DEPUIS):
        with open(DEPUIS, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
    lim = max(lim, datetime.fromisoformat(open(DEPUIS).read().strip()))
    out = []
    for v in vids:
        t = (v.get("t") or "").lower()
        if v.get("c") != "gt" or "highlight" not in t or "recap" in t:
            continue
        if " vs " not in t and " at " not in t and " vs. " not in t:
            continue
        try:
            if datetime.fromisoformat(v["p"].replace("Z", "+00:00")) < lim:
                continue
        except Exception:
            pass
        out.append(v)
    out.sort(key=lambda v: v.get("p", ""), reverse=True)   # les plus récents d'abord
    # un seul résumé par match, et seulement les matchs à SEUIL barres ou plus
    gardes, vus = [], set()
    for v in out:
        try:
            ev = match_de(v)
        except Exception as e:
            log("ESPN illisible :", e)
            continue
        if not ev or ev["id"] in vus:
            continue
        vus.add(ev["id"])
        v["gid"] = ev["id"]  # le déroulé ESPN de ce match sert à caler la vidéo sur les scores lus à l'écran
        v["score"], v["note"] = note_fine(ev)
        if v["note"] >= SEUIL:
            gardes.append(v)
        else:
            log("pas de Replay + (%s) :" % ["À fuir", "Bof", "Sans plus"][v["note"]], v.get("t", ""))
    gardes.sort(key=lambda v: -v["score"])                 # les meilleurs matchs d'abord (le match de la nuit en tête)
    return gardes


def depot_pret():
    if not os.path.isdir(os.path.join(DEPOT, ".git")):
        sh("git", "clone", "--depth", "1", "--branch", "data", "--single-branch", REMOTE, DEPOT)
        sh("git", "config", "user.name", "telephone-nocturne", cwd=DEPOT)
        sh("git", "config", "user.email", "telephone@nocturne.local", cwd=DEPOT)
    sh("git", "fetch", "--depth", "1", "origin", "data", cwd=DEPOT)
    sh("git", "reset", "--hard", "origin/data", cwd=DEPOT)


def publier(nouveaux):
    """Ajoute les tables et l'index sur la branche data (en se recalant si le robot vidéo a poussé entre-temps)."""
    for essai in range(4):
        try:
            depot_pret()
            dossier = os.path.join(DEPOT, "v2", "chrono")
            os.makedirs(dossier, exist_ok=True)
            for vid, res in nouveaux.items():
                with open(os.path.join(dossier, vid + ".json"), "w") as f:
                    json.dump(res, f, separators=(",", ":"))
            ids = sorted(n[:-5] for n in os.listdir(dossier) if n.endswith(".json") and n != "index.json")
            with open(os.path.join(dossier, "index.json"), "w") as f:
                json.dump({"maj": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "v": ids}, f, separators=(",", ":"))
            sh("git", "add", "v2/chrono", cwd=DEPOT)
            if not sh("git", "status", "--porcelain", cwd=DEPOT).stdout.strip():
                return True
            sh("git", "commit", "-m", "chrono : %d résumé(s) analysé(s) par le téléphone" % len(nouveaux), cwd=DEPOT)
            sh("git", "push", "origin", "HEAD:data", cwd=DEPOT)
            return True
        except subprocess.CalledProcessError as e:
            log("publication ratée (%d) : %s" % (essai + 1, (e.stderr or "").strip()[-200:]))
            time.sleep(20)
    return False


# ---------- la « photo » d'avant-match : ce qu'ESPN dit AVANT le coup d'envoi (après, il le remplace par le match) ----------
INJURIES = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"


def lire(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def cote(c, injs):
    recs = {r.get("type"): r.get("summary", "") for r in c.get("records", [])}
    d = {"record": recs.get("total", ""), "recHome": recs.get("home", ""), "recRoad": recs.get("road", ""),
         "top": None, "star": None, "out": injs.get(int(c["team"]["id"]), [])}
    for L in c.get("leaders", []):
        l = (L.get("leaders") or [None])[0]
        if not l or not l.get("athlete"):
            continue
        if L.get("name") == "pointsPerGame":
            d["top"] = {"n": l["athlete"].get("shortName", ""), "ppg": float(l.get("value") or 0)}
        if L.get("name") == "rating":
            d["star"] = l["athlete"].get("shortName", "")
    return d


def photo_avant():
    """Pour chaque match pas encore commencé (nuits d'aujourd'hui et de demain, heure de New York) : bilans, meilleur
    marqueur et star de la saison, blessés. Publié dans v2/avant/<nuit>.json ; le site s'en sert après le match (sans spoil)."""
    ny = datetime.now(timezone.utc) - timedelta(hours=5)
    jours = [(ny + timedelta(days=d)).strftime("%Y%m%d") for d in (0, 1)]
    evs = {j: lire(ESPN + j).get("events", []) for j in jours}
    if not any((e["competitions"][0].get("status") or {}).get("type", {}).get("state") == "pre" for j in jours for e in evs[j]):
        return
    injs = {}
    for t in lire(INJURIES).get("injuries", []):
        injs[int(t["id"])] = [{"n": (i.get("athlete") or {}).get("shortName", ""), "st": i.get("status", ""),
                               "ty": (i.get("details") or {}).get("type", "")} for i in t.get("injuries", [])]
    fichiers = {}
    for j in jours:
        chemin = os.path.join(DEPOT, "v2", "avant", j + ".json")
        ancien = charger(chemin, {})
        neuf = dict(ancien)
        for e in evs[j]:
            comp = e["competitions"][0]
            if (comp.get("status") or {}).get("type", {}).get("state") != "pre":
                continue  # commencé : on garde la dernière photo prise avant
            cs = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            if "home" in cs and "away" in cs:
                neuf[e["id"]] = {"a": cote(cs["away"], injs), "h": cote(cs["home"], injs)}
        if neuf != ancien:
            fichiers["v2/avant/" + j + ".json"] = neuf
    if fichiers:
        publier_fichiers(fichiers, "avant-match : photo de %d nuit(s)" % len(fichiers))


def publier_fichiers(fichiers, message):
    for essai in range(4):
        try:
            depot_pret()
            for rel, obj in fichiers.items():
                chemin = os.path.join(DEPOT, rel)
                os.makedirs(os.path.dirname(chemin), exist_ok=True)
                with open(chemin, "w") as f:
                    json.dump(obj, f, separators=(",", ":"))
            sh("git", "add", *fichiers.keys(), cwd=DEPOT)
            if not sh("git", "status", "--porcelain", cwd=DEPOT).stdout.strip():
                return True
            sh("git", "commit", "-m", message, cwd=DEPOT)
            sh("git", "push", "origin", "HEAD:data", cwd=DEPOT)
            return True
        except subprocess.CalledProcessError as e:
            log("publication ratée (%d) : %s" % (essai + 1, (e.stderr or "").strip()[-200:]))
            time.sleep(20)
    return False


SUIVI = "v2/suivi.json"   # chronologie de chaque Replay + (sortie YouTube → téléchargé → en ligne), 30 derniers jours


def heure(t=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t))


def suivre(ligne):
    """Ajoute une ligne au suivi publié sur la branche data (appelé sous le verrou)."""
    chemin = os.path.join(DEPOT, SUIVI)
    lignes = [l for l in charger(chemin, {}).get("l", []) if l.get("fin", "") >= heure(time.time() - 30 * 86400)]
    lignes.append(ligne)
    publier_fichiers({SUIVI: {"l": lignes}}, "suivi : " + ligne.get("etat", ""))


def recaps(vids, etat):
    """Les résumés de la nuit (2 derniers jours) encore à faire, le plus récent d'abord."""
    lim = datetime.now(timezone.utc) - timedelta(days=2)
    out = []
    for v in vids or []:
        if not nuit.est_recap(v):
            continue
        try:
            if datetime.fromisoformat(v["p"].replace("Z", "+00:00")) < lim:
                continue
        except Exception:
            continue
        if a_essayer(etat.get("nuit:" + v["id"], {})):
            out.append(dict(v, nuit=True))
    out.sort(key=lambda v: v.get("p", ""), reverse=True)
    return out


def traiter_nuit(v, etat, verrou):
    """Le résumé de la nuit augmenté (nuit.py) : chapitres publiés tout de suite, puis chrono + joueur de la nuit."""
    with verrou:
        if en_pause(etat):
            return
        e = etat.setdefault("nuit:" + v["id"], {"essais": 0})
        e["essais"] += 1
    jour = nuit.nuit_de(v.get("t", ""))
    video = os.path.join(TRAVAIL, v["id"] + ".mp4")
    try:
        def pub(res):
            with verrou:
                publier_fichiers({"v2/nuit/%s.json" % res["nuit"]: res}, "résumé de la nuit %s : %s" % (res["nuit"], "complet" if res["fait"] else "chapitres"))
        nuit.analyse(v["id"], v.get("t", ""), None, pub)  # les chapitres d'abord (quelques secondes)
        sh("yt-dlp", "-q", "--no-warnings", "-f", "bv*[height=720][vcodec^=avc1]/bv*[height=720][vcodec^=vp]/bv*[height=720]/bv*[height<=720]",
           "-o", video, "https://www.youtube.com/watch?v=" + v["id"])
        with verrou:
            etat.pop("pause", None)
        res = nuit.analyse(v["id"], v.get("t", ""), video, pub)
        if res and res.get("fait"):
            e["ok"] = True
            log("résumé de la nuit publié :", jour)
    except Exception as ex:
        log("résumé de la nuit raté", v["id"], erreur(ex))
        with verrou:
            rater(etat, e, ex)
    finally:
        for f in (video, video + ".part"):
            if os.path.exists(f):
                os.remove(f)
        with verrou:
            with open(ETAT, "w") as f:
                json.dump(etat, f)


def passage():
    _SB.clear()  # les scoreboards ESPN changent (un match « à venir » finit par être « terminé ») : on relit à chaque passage
    try:
        depot_pret()
        photo_avant()
    except Exception as e:
        log("photo d'avant-match ratée :", str(e)[-200:])
    vids = None
    try:
        vids = liste_videos()
    except Exception as e:
        log("mise à jour de la liste des vidéos ratée :", str(e)[-200:])
    etat = charger(ETAT, {})
    if en_pause(etat):
        return
    try:
        liste = resumes(vids)
    except Exception as e:
        log("liste des vidéos illisible :", e)
        return
    # l'ordre de passage (28/11, choix de Kiki) : le résumé de la nuit dès qu'il est sorti, puis les matchs du meilleur au moins bon
    a_faire = recaps(vids, etat) + [v for v in liste if a_essayer(etat.get(v["id"], {}))]
    if not a_faire:
        return
    log("%d vidéo(s) à analyser, %d à la fois : %s" % (len(a_faire), EN_MEME_TEMPS,
        " · ".join("NUIT" if v.get("nuit") else "%.1f" % v["score"] for v in a_faire)))
    os.makedirs(TRAVAIL, exist_ok=True)
    verrou = threading.Lock()  # l'état et la publication git : un seul fil à la fois

    def traiter(v):
        if v.get("nuit"):
            return traiter_nuit(v, etat, verrou)
        vid = v["id"]
        with verrou:
            if en_pause(etat):
                return  # refusé pendant ce passage : on ne demande plus rien
            e = etat.setdefault(vid, {"essais": 0})
            e["essais"] += 1
        video = os.path.join(TRAVAIL, vid + ".mp4")
        suivi = {"v": vid, "t": v.get("t", ""), "note": v.get("note"), "yt": v.get("p", ""), "debut": heure(),
                 "fils": EN_MEME_TEMPS, "etat": "échec"}
        try:
            if os.path.exists(video):
                os.remove(video)
            # 720p obligatoire (en 480p le bandeau est illisible) ; H.264 puis VP9 avant l'AV1, qui fait planter le décodeur du téléphone
            sh("yt-dlp", "-q", "--no-warnings", "-f", "bv*[height=720][vcodec^=avc1]/bv*[height=720][vcodec^=vp]/bv*[height=720]/bv*[height<=720]",
               "-o", video, "https://www.youtube.com/watch?v=" + vid)
            suivi["telecharge"] = heure()
            with verrou:
                etat.pop("pause", None)  # YouTube répond
            res = chrono_video.analyse(video, os.path.join(TRAVAIL, vid + ".json"), vid, v.get("gid"))
            res["t"] = v.get("t", "")
            pts = res["pts"]
            bon = len(pts) >= 40 and max(p[1] for p in pts) >= 4  # un résumé complet va jusqu'au 4e quart-temps
            with verrou:
                suivi.update(images=res.get("n"), extraction=res.get("ti"), lecture=res.get("tl"), etat="non publié")
                if bon and publier({vid: res}):
                    e["ok"] = True
                    suivi["etat"] = "en ligne"
                    log("publié :", v.get("t", vid))
                else:
                    log("table pas assez sûre, non publiée :", v.get("t", vid), len(pts), "points")
                    if not bon and res["n"] > 120:
                        e["essais"] = ESSAIS  # vidéo entière lue mais bandeau illisible : inutile de réessayer
        except Exception as ex:
            log("échec", vid, erreur(ex))
            with verrou:
                rater(etat, e, ex)
        finally:
            for f in (video, video + ".part"):
                if os.path.exists(f):
                    os.remove(f)
            with verrou:
                with open(ETAT, "w") as f:
                    json.dump(etat, f)
                suivi["fin"] = heure()
                try:
                    suivre(suivi)
                except Exception as ex:
                    log("suivi non publié :", str(ex)[-200:])

    with ThreadPoolExecutor(EN_MEME_TEMPS) as pool:  # les tâches partent dans l'ordre de la liste
        list(pool.map(traiter, a_faire))


if __name__ == "__main__":
    if "--une" in sys.argv:
        passage()
    else:
        log("boucle démarrée")
        while True:
            try:
                sh("pip", "install", "-q", "-U", "yt-dlp", check=False) if time.localtime().tm_hour == 15 and time.localtime().tm_min < 20 else None
                passage()
            except Exception as ex:
                log("erreur :", ex)
            # de 2h à 10h (heure du téléphone, Paris) les résumés tombent : on repasse toutes les 5 min pour les avoir
            # au petit déjeuner ; le reste du temps, toutes les 20 min suffit
            time.sleep(300 if 2 <= time.localtime().tm_hour < 10 else 1200)
