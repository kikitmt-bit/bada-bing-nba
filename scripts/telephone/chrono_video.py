#!/usr/bin/env python3
"""Nocturne : lire le chrono du match dans un résumé vidéo, image par image.

Tourne sur le téléphone-serveur (Termux). Pour une vidéo : une image par seconde
(bas de l'écran seulement), lecture du bandeau du match (quart-temps + chrono) avec
tesseract, nettoyage (le match avance toujours dans un résumé), puis une table
« seconde de la vidéo -> moment du match » que le site suit en direct.

    python chrono_video.py analyse video.mp4 sortie.json [id_youtube]
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter

from PIL import Image, ImageOps

PAS = 1            # une image par seconde (choix de Kiki, 19/11)
BANDE = 0.30       # on ne garde que le bas de l'image (le bandeau du match)

# ---------- lecture du texte ----------
QRX = re.compile(r"^(?:([1lIi|!])[sS58][tT7]|(2)[nN][dD0]|(3)[rR][dD0]|(4)[tT][hH]|([0O]T|2[0O]T|3[0O]T))")


def read_quarter(s):
    m = QRX.match(s)
    if not m:
        return 0
    for i, per in ((1, 1), (2, 2), (3, 3), (4, 4)):
        if m.group(i):
            return per
    ot = m.group(5)
    return 4 + (int(ot[0]) if ot[0].isdigit() and int(ot[0]) > 1 else 1)


def read_clock(s, dixiemes=True):
    """(secondes, variante) ; « 1:05 » peut être un « 11:05 » mal lu. Les « 45.3 » (dernière minute) seulement
    si dixiemes : pendant la recherche, un bilan « 4-9 » lu « 4.9 » passerait sinon pour un chrono."""
    s = s.replace("o", "0").replace("O", "0")
    for c in "lI|!":
        s = s.replace(c, "1")
    m = re.search(r"(?:^|[^\d])(n|\d{1,2})[:;](\d{2})(?!\d)", " " + s)
    if m:
        mm = 11 if m.group(1) == "n" else int(m.group(1))
        ss = int(m.group(2))
        if mm <= 12 and ss < 60 and mm * 60 + ss <= 720:
            alt = (mm + 10) * 60 + ss if len(m.group(1)) == 1 and mm <= 2 else None
            return mm * 60 + ss, alt
    m = re.match(r"^(\d{1,2})\.(\d)$", s)  # dernière minute : « 45.3 »
    if dixiemes and m and int(m.group(1)) < 60:
        return int(m.group(1)) + int(m.group(2)) / 10, None
    return None


def _tmp():
    # un fichier par fil d'exécution : boucle.py lance plusieurs analyses en même temps
    return os.path.join(tempfile.gettempdir(), "nocturne_ocr_%d.png" % threading.get_ident())


def ocr(img, psm):
    tmp = _tmp()
    img.save(tmp)
    out = subprocess.run(["tesseract", tmp, "stdout", "--psm", str(psm), "tsv"],
                         capture_output=True, text=True).stdout
    words = []
    for line in out.splitlines()[1:]:
        p = line.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        x, y, w, h = map(int, p[6:10])
        words.append({"t": p[11].strip(), "c": float(p[10]), "x0": x, "y0": y, "x1": x + w, "y1": y + h})
    return words


def prep(img, scale, mode):
    g = ImageOps.grayscale(img)
    if scale != 1:
        g = g.resize((max(8, int(g.width * scale)), max(8, int(g.height * scale))), Image.LANCZOS)
    if mode == "inv":
        g = g.point(lambda v: 0 if v > 150 else 255)
    elif mode == "thr":
        g = g.point(lambda v: 255 if v > 150 else 0)
    return g


def find_quarter(words):
    q = None
    for w in words:
        per = read_quarter(w["t"])
        if per and (q is None or w["c"] > q[1]["c"]):
            q = (per, w)
    return q


def find_clock(words, near=None, dixiemes=True):
    best = None
    for w in words:
        if near is not None and w is near:
            continue
        c = read_clock(w["t"], dixiemes)
        if not c:
            continue
        d = 0
        if near is not None:
            h = max(6, near["y1"] - near["y0"])
            dx = (w["x0"] + w["x1"] - near["x0"] - near["x1"]) / 2
            dy = (w["y0"] + w["y1"] - near["y0"] - near["y1"]) / 2
            d = (dx * dx + (dy * 1.5) ** 2) ** .5
            if d > h * 10:
                continue
        if best is None or d < best[2]:
            best = (c[0], c[1], d, w)
    return best


# ---------- une vidéo ----------
def quarter_near(words, k):
    """Quart-temps écrit à côté du chrono : « 2ND », « 1st »… ou, chez ESPN, un gros « 2 » suivi d'un petit « ND »."""
    q = find_quarter(words)
    if q:
        return q[0]
    if not k:
        return None
    cw = k[3]
    h = max(6, cw["y1"] - cw["y0"])
    best = None
    for w in words:
        t = w["t"].strip("|[](){}.,")
        if re.match(r"^[1-4][A-Za-z]{0,3}$", t) and abs((w["y0"] + w["y1"]) - (cw["y0"] + cw["y1"])) / 2 < h:
            gap = cw["x0"] - w["x1"]
            if -h < gap < h * 3 and (best is None or gap < best[0]):
                best = (gap, int(t[0]))
    return best[1] if best else None


class Lecteur:
    """La zone du bandeau, une fois trouvée, est gardée pour toute la vidéo (le bandeau ne bouge pas) ;
    on ne la recherche qu'après une série d'échecs, sans perdre l'ancienne si la recherche échoue."""

    MODES = (("inv", 6), ("inv", 11), ("thr", 11), ("gray", 11))

    def __init__(self):
        self.lock = None   # (x0, y0, x1, y1) dans la bande
        self.miss = 0
        self.ordre = list(self.MODES)  # le réglage qui a marché passe en tête

    def ligne(self, band):
        """Les mots de toute la ligne du bandeau (à la hauteur du chrono) : les deux scores, les sigles des équipes."""
        if self.lock is None or getattr(self, "vus", None) is not None:
            vus, self.vus = getattr(self, "vus", None) or [], None
            if self.lock is None or vus:
                return vus  # la recherche vient de lire toute la bande : ses mots suffisent
        W, H = band.size
        y0, y1 = self.lock[1], self.lock[3]
        h = y1 - y0
        crop = band.crop((0, max(0, int(y0 - h * .35)), W, min(H, int(y1 + h * .35))))
        scale = max(1, min(3, 120 / max(1, crop.height)))
        mots = []
        for mode in ("gray", "inv"):
            mots += [w["t"] for w in ocr(prep(crop, scale, mode), 11)]
        return mots

    def lire_zone(self, band):
        W, H = band.size
        x0, y0, x1, y1 = [int(v) for v in self.lock]
        crop = band.crop((max(0, x0), max(0, y0), min(W, x1), min(H, y1)))
        scale = max(1.5, min(4, 210 / max(1, crop.height)))
        for i, (mode, psm) in enumerate(self.ordre):
            words = ocr(prep(crop, scale, mode), psm)
            k = find_clock(words, None)
            if k:
                if i:
                    self.ordre.insert(0, self.ordre.pop(i))
                return quarter_near(words, k), k[0], k[1]
        return None

    def chercher(self, band):
        W, H = band.size
        # 1) toute la bande, agrandie modérément : quart-temps + chrono
        scale = max(.8, min(2.4, 2000 / W))
        self.vus = []
        for mode in ("gray", "inv"):
            words = ocr(prep(band, scale, mode), 11)
            self.vus += [w["t"] for w in words]  # gardés pour ligne() : les scores se lisent parfois sans le chrono
            q = find_quarter(words)
            k = find_clock(words, q[1] if q else None, dixiemes=False)
            if k:
                b = [v / scale for v in (k[3]["x0"], k[3]["y0"], k[3]["x1"], k[3]["y1"])]
                return self._caler(b, q and [v / scale for v in (q[1]["x0"], q[1]["y0"], q[1]["x1"], q[1]["y1"])])
        # 2) la moitié basse de la bande, très agrandie (petits bandeaux, chrono sur fond clair)
        y0 = int(H * .45)
        strip = band.crop((0, y0, W, H))
        for mode in ("inv", "gray"):
            words = ocr(prep(strip, 3, mode), 11)
            k = find_clock(words, None, dixiemes=False)
            if k:
                b = [k[3]["x0"] / 3, k[3]["y0"] / 3 + y0, k[3]["x1"] / 3, k[3]["y1"] / 3 + y0]
                return self._caler(b, None)
        return False

    def _caler(self, b, qb):
        cw, ch = b[2] - b[0], b[3] - b[1]
        x0, y0, x1, y1 = b
        if qb:  # le quart-temps lu : la zone couvre les deux
            x0, y0, x1, y1 = min(x0, qb[0]), min(y0, qb[1]), max(x1, qb[2]), max(y1, qb[3])
            mw, mh = (x1 - x0) * .12 + cw * .1, (y1 - y0) * .1 + ch * .25
            self.lock = (x0 - mw, y0 - mh, x1 + mw, y1 + mh)
        else:   # chrono seul : le quart-temps est à gauche (ESPN) ou dessous (NBC, TNT)
            self.lock = (x0 - cw * 1.6, y0 - ch * .5, x1 + cw * .5, y1 + ch * 1.3)
        return True

    def lire(self, band):
        if self.lock is None or self.miss >= 8:
            old = self.lock
            if not self.chercher(band):
                self.lock = old
                self.miss = 0 if old else self.miss
                return None
            self.miss = 0
        r = self.lire_zone(band)
        if not r:
            self.miss += 1
            return None
        self.miss = 0
        return r


def frac(per, sec):
    return ((per - 1) * 720 + 720 - sec) / 2880 if per <= 4 else 1 + ((per - 5) * 300 + 300 - sec) / 2880


def nettoyer(lectures):
    """Plus longue suite où le match avance (un résumé est chronologique).
    Chaque lecture propose 1 ou 2 moments (« 1:05 » / « 11:05 ») : on en garde au plus un."""
    cands = []  # (i, t, per, sec, poids)
    for i, (t, per, sec, alt) in enumerate(lectures):
        pers = [(per, 1.0)] if per else [(p, .85 - .01 * p) for p in range(1, 6)]  # quart illisible : la chronologie tranche
        for pp, wp in pers:
            for s, w in ((sec, 1.0), (alt, .9)):
                if s is not None and s <= (300 if pp > 4 else 720):
                    cands.append((i, t, pp, s, w * wp))
    n = len(cands)
    best, prev = [0.0] * n, [-1] * n
    for a in range(n):
        ia, ta, pa, sa, wa = cands[a]
        best[a] = wa
        ga = frac(pa, sa)
        for b in range(a):
            ib, tb, pb, sb, wb = cands[b]
            if ib >= ia:
                continue
            gb = frac(pb, sb)
            # le match avance, mais pas plus vite que la vidéo ne le permet (marge large : montage)
            if gb <= ga + 2 / 2880 and best[b] + wa > best[a]:
                best[a], prev[a] = best[b] + wa, b
    if not n:
        return []
    a = max(range(n), key=lambda k: best[k])
    out = []
    while a >= 0:
        _, t, per, sec, _ = cands[a]
        out.append([t, per, round(sec, 1)])
        a = prev[a]
    return out[::-1]


# ---------- les scores lus à l'écran, recoupés avec la suite des scores ESPN (22/11) ----------
# Le chrono seul ne suffit pas : le minutage ESPN des paniers ne colle pas toujours au bandeau, et bien des images n'ont
# pas de chrono lisible. Le score affiché, lui, se lit bien et ne peut prendre que les valeurs successives du match.
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event="


def secs(d):
    m = re.match(r"^(\d+):(\d+)", d or "")
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    try:
        return float(d)
    except Exception:
        return 0.0


def ecoule(per, sec):
    return (per - 1) * 720 + 720 - sec if per <= 4 else 2880 + (per - 5) * 300 + 300 - sec


def moment(el):
    if el < 2880:
        per = min(4, int(el // 720) + 1)
        return per, round(720 - (el - (per - 1) * 720), 2)
    per = 5 + int((el - 2880) // 300)
    return per, round(300 - (el - 2880 - (per - 5) * 300), 2)


def deroule(gid):
    for k in range(5):  # le wifi du téléphone a des trous : on réessaie
        try:
            with urllib.request.urlopen(SUMMARY + str(gid), timeout=30) as r:
                j = json.load(r)
            break
        except Exception:
            if k == 4:
                raise
            time.sleep(20 * (k + 1))
    cs = {c["homeAway"]: c for c in j["header"]["competitions"][0]["competitors"]}
    plays = []
    for p in j.get("plays", []):
        per = (p.get("period") or {}).get("number") or 1
        sec = secs((p.get("clock") or {}).get("displayValue"))
        pa = [(x.get("athlete") or {}).get("id") for x in p.get("participants") or []]
        plays.append({"per": per, "sec": sec, "el": ecoule(per, sec), "as": int(p.get("awayScore") or 0), "hs": int(p.get("homeScore") or 0),
                      "pts": bool(p.get("scoringPlay")), "a0": pa[0] if pa else None, "tid": str((p.get("team") or {}).get("id") or ""),
                      "tx": p.get("text", ""), "tt": (p.get("type") or {}).get("text", "")})
    etats = [{"as": 0, "hs": 0, "el": 0.0, "i": -1}]  # les scores successifs du match
    for i, p in enumerate(plays):
        if (p["as"], p["hs"]) != (etats[-1]["as"], etats[-1]["hs"]):
            etats.append({"as": p["as"], "hs": p["hs"], "el": p["el"], "i": i})
    ab = {k: cs[k]["team"].get("abbreviation", "") for k in ("away", "home")}
    return {"plays": plays, "etats": etats, "ab": ab, "gid": str(gid),
            "ids": {k: str(cs[k]["team"]["id"]) for k in ("away", "home")}}


def nombres(mots):
    out = []
    for w in mots:
        w = w.strip("|[](){}.,:;'\"")
        if re.fullmatch(r"[0-9OoIl|]{1,3}", w) and sum(ch.isdigit() for ch in w) >= max(1, len(w) - 1):
            w = w.replace("O", "0").replace("o", "0").replace("I", "1").replace("l", "1").replace("|", "1")
            out.append(int(w))
    return Counter(out)


def soutenus(D, nums):
    """Les scores du match dont les deux nombres sont à l'écran."""
    out = []
    for k, e in enumerate(D["etats"]):
        a, h = e["as"], e["hs"]
        if (a == h and nums.get(a, 0) >= 2) or (a != h and nums.get(a) and nums.get(h)):
            out.append(k)
    return out


def caler(lectures, D):
    """lectures : [(t, quart|None, secondes|None, variante, mots)]. Renvoie [[t, quart, secondes, score visiteurs, score domicile]] :
    le score est TOUJOURS celui vu à l'écran (ou le dernier vu), et le moment du match reste à l'intérieur de ce score."""
    E = D["etats"]
    K = {p[0]: (p[1], p[2]) for p in nettoyer([l[:4] for l in lectures if l[2] is not None])}
    items = []  # (t, score possible, poids) : plus sûr s'il colle au chrono lu
    for t, _, _, _, mots in lectures:
        nums = nombres(mots)
        for k in soutenus(D, nums):
            a, h = E[k]["as"], E[k]["hs"]
            w = 1.0
            if t in K:
                el = ecoule(*K[t])
                fin = E[k + 1]["el"] if k + 1 < len(E) else 1e9
                if E[k]["el"] - 20 <= el <= fin + 20:
                    w = 3.0
                elif abs(E[k]["el"] - el) > 240:
                    continue
            elif max(a, h) < 4:
                w = .6  # tout petits nombres sans chrono (chrono des tirs, fautes…) : peu sûr
            items.append((t, k, w))
    items.sort()
    n = len(items)  # plus longue suite chronologique : le score ne recule jamais
    best, prev = [0.0] * n, [-1] * n
    for i in range(n):
        ti, ki, wi = items[i]
        best[i] = wi
        for j in range(i):
            tj, kj, wj = items[j]
            if tj < ti and kj <= ki and best[j] + wi > best[i]:
                best[i], prev[i] = best[j] + wi, j
    vu = {}
    if n:
        i = max(range(n), key=lambda x: best[x])
        while i >= 0:
            vu[items[i][0]] = items[i][1]
            i = prev[i]
    out, k = [], None
    for t in sorted(set(K) | set(vu)):
        if t in vu:
            k = vu[t]
        elif k is None:
            # chrono lu avant tout score vu : seulement si on est encore à 0-0
            if len(E) > 1 and ecoule(*K[t]) < E[1]["el"]:
                k = 0
            else:
                continue
        deb = E[k]["el"] + .01
        fin = (E[k + 1]["el"] - .3) if k + 1 < len(E) else 1e9
        el = min(max(ecoule(*K[t]), deb), fin) if t in K else deb
        per, sec = moment(el)
        out.append([t, per, sec, E[k]["as"], E[k]["hs"]])
    res, last = [], -1  # le moment du match ne recule jamais non plus
    for p in out:
        el = ecoule(p[1], p[2])
        if el + .001 >= last:
            res.append(p)
            last = el
    return res


def lire_plage(frames_dir, frames, t0, t1, D):
    """Lit les images [t0, t1) (une par seconde) : chrono + ligne du bandeau, puis calage sur les scores ESPN."""
    lec, brut = Lecteur(), []
    for t in range(t0, min(t1, len(frames) * PAS), PAS):
        band = Image.open(os.path.join(frames_dir, frames[t // PAS]))
        r = lec.lire(band)
        mots = lec.ligne(band) if D else []
        if r or mots:
            brut.append((t,) + (tuple(r) if r else (None, None, None)) + (mots,))
    return caler(brut, D) if D else nettoyer([b[:4] for b in brut if b[2] is not None]), brut


def analyse(video, sortie, vid="", gid=None):
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="nocturne_")
    try:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-vf",
                        f"fps=1/{PAS},crop=iw:ih*{BANDE}:0:ih*{1 - BANDE}", os.path.join(tmp, "%05d.png")], check=True)
        frames = sorted(os.listdir(tmp))
        t1 = time.time()
        D = None
        if gid:
            try:
                D = deroule(gid)
            except Exception as e:
                print("déroulé ESPN illisible :", e)
        pts, brut = lire_plage(tmp, frames, 0, len(frames) * PAS, D)
        brut = [b for b in brut if b[2] is not None]
        res = {"v": vid, "pas": PAS, "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "n": len(frames), "lus": len(brut), "pts": pts,
               "ti": round(t1 - t0), "tl": round(time.time() - t1)}  # durées (s) : extraction des images, lecture du chrono
        with open(sortie, "w") as f:
            json.dump(res, f, separators=(",", ":"))
        print(f"{vid} : {len(frames)} images, {len(brut)} lectures, {len(pts)} gardées "
              f"(images {t1 - t0:.0f} s, lecture {time.time() - t1:.0f} s)")
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "analyse":
        analyse(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
    else:
        print(__doc__)
