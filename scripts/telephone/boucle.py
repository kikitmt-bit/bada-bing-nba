#!/usr/bin/env python3
"""Nocturne : la boucle du téléphone-serveur.

Toutes les 20 minutes : lit la liste des résumés tenue par le robot GitHub (v2/videos.json),
analyse chaque nouveau résumé de match (chrono_video.py) et publie la table sur la branche
data du dépôt (v2/chrono/<id>.json + v2/chrono/index.json), que le site lit directement.

    python boucle.py          # tourne sans fin (lancé au démarrage du téléphone)
    python boucle.py --une    # un seul passage (tests)
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import chrono_video

ICI = os.path.dirname(os.path.abspath(__file__))
DEPOT = os.path.join(ICI, "depot")          # clone léger de la branche data
TRAVAIL = os.path.join(ICI, "travail")
ETAT = os.path.join(ICI, "etat.json")       # vidéos déjà traitées (ou ratées)
LISTE = "https://raw.githubusercontent.com/kikitmt-bit/bada-bing-nba/data/v2/videos.json"
REMOTE = "git@github.com:kikitmt-bit/bada-bing-nba.git"
JOURS = 3          # on ne regarde que les résumés des 3 derniers jours
ESSAIS = 3         # au-delà, on abandonne une vidéo


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


def resumes():
    """Les résumés de match récents, GameTime d'abord (c'est celui que le site ouvre en premier)."""
    with urllib.request.urlopen(LISTE + "?t=%d" % time.time(), timeout=30) as r:
        vids = json.load(r).get("videos", [])
    lim = datetime.now(timezone.utc) - timedelta(days=JOURS)
    out = []
    for v in vids:
        t = (v.get("t") or "").lower()
        if v.get("c") not in ("gt", "nba") or "highlight" not in t or "recap" in t:
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
    out.sort(key=lambda v: v.get("c") != "gt")             # GameTime avant NBA (tri stable)
    return out


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


def passage():
    etat = charger(ETAT, {})
    try:
        liste = resumes()
    except Exception as e:
        log("liste des vidéos illisible :", e)
        return
    a_faire = [v for v in liste if etat.get(v["id"], {}).get("ok") is None and etat.get(v["id"], {}).get("essais", 0) < ESSAIS]
    if not a_faire:
        return
    log("%d résumé(s) à analyser" % len(a_faire))
    os.makedirs(TRAVAIL, exist_ok=True)
    for v in a_faire:
        vid, e = v["id"], etat.setdefault(v["id"], {"essais": 0})
        e["essais"] += 1
        video = os.path.join(TRAVAIL, "v.mp4")
        try:
            if os.path.exists(video):
                os.remove(video)
            # 720p obligatoire (en 480p le bandeau est illisible) ; H.264 puis VP9 avant l'AV1, qui fait planter le décodeur du téléphone
            sh("yt-dlp", "-q", "--no-warnings", "-f", "bv*[height=720][vcodec^=avc1]/bv*[height=720][vcodec^=vp]/bv*[height=720]/bv*[height<=720]",
               "-o", video, "https://www.youtube.com/watch?v=" + vid)
            res = chrono_video.analyse(video, os.path.join(TRAVAIL, vid + ".json"), vid)
            res["t"] = v.get("t", "")
            pts = res["pts"]
            bon = len(pts) >= 40 and max(p[1] for p in pts) >= 4  # un résumé complet va jusqu'au 4e quart-temps
            if bon and publier({vid: res}):
                e["ok"] = True
                log("publié :", v.get("t", vid))
            else:
                log("table pas assez sûre, non publiée :", v.get("t", vid), len(pts), "points")
                if not bon and res["n"] > 120:
                    e["essais"] = ESSAIS  # vidéo entière lue mais bandeau illisible : inutile de réessayer
        except Exception as ex:
            log("échec", vid, (getattr(ex, "stderr", "") or str(ex))[-300:])
        finally:
            if os.path.exists(video):
                os.remove(video)
            with open(ETAT, "w") as f:
                json.dump(etat, f)


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
            time.sleep(1200)
