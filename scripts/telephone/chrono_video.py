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


def nettoyer(lectures, nper=5):
    """Plus longue suite où le match avance (un résumé est chronologique).
    Chaque lecture propose 1 ou 2 moments (« 1:05 » / « 11:05 ») : on en garde au plus un.
    nper : le nombre de périodes du match (une lecture au-delà est un quart-temps mal lu)."""
    cands = []  # (i, t, per, sec, poids)
    for i, (t, per, sec, alt) in enumerate(lectures):
        pers = [(per, 1.0)] if per and per <= nper else [(p, .85 - .01 * p) for p in range(1, nper + 1)]  # quart illisible : la chronologie tranche
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


# ---------- les cases de score du bandeau (22/11) ----------
# Le bandeau montre les sigles des deux équipes ; chaque score est dans une case collée à son sigle (côté centre quand les
# équipes sont côte à côte, à droite quand elles sont l'une sous l'autre). On repère les sigles une fois, puis on lit
# chaque case seule, avec un seuil adapté à SON fond (chiffres blancs sur fond sombre, ou noirs sur fond blanc).
ALIAS = {"NY": ["NYK", "NY"], "GS": ["GSW", "GS"], "SA": ["SAS", "SA"], "NO": ["NOP", "NO"], "UTAH": ["UTA", "UTAH"],
         "WSH": ["WAS", "WSH"], "PHX": ["PHX", "PHO"], "BKN": ["BKN", "BRK"], "CHA": ["CHA", "CHO"]}


def _binaire(g, thr, clairs_minoritaires):
    b = g.point(lambda v: 0 if v > thr else 255) if clairs_minoritaires else g.point(lambda v: 255 if v > thr else 0)
    # les bords de la case (traits qui la traversent de part en part) ne sont pas des chiffres : on les efface
    W, H = b.size
    px = b.load()
    for y in range(H):
        if sum(1 for x in range(W) if px[x, y] == 0) > W * .8:
            for x in range(W):
                px[x, y] = 255
    for x in range(W):
        if sum(1 for y in range(H) if px[x, y] == 0) > H * .85:
            for y in range(H):
                px[x, y] = 255
    # ce qui touche un bord de la case et n'est pas un chiffre : bord du panneau voisin (trait fin ou aplat plein),
    # traits horizontaux du cadre en haut ou en bas
    seen = set()
    depart = [(x, y) for x in (0, W - 1) for y in range(H)] + [(x, y) for y in (0, H - 1) for x in range(W)]
    for x0, y0 in depart:
        if px[x0, y0] != 0 or (x0, y0) in seen:
            continue
        comp, pile = [], [(x0, y0)]
        seen.add((x0, y0))
        while pile:
            cx, cy2 = pile.pop()
            comp.append((cx, cy2))
            for nx, ny in ((cx + 1, cy2), (cx - 1, cy2), (cx, cy2 + 1), (cx, cy2 - 1)):
                if 0 <= nx < W and 0 <= ny < H and (nx, ny) not in seen and px[nx, ny] == 0:
                    seen.add((nx, ny))
                    pile.append((nx, ny))
        xs = [c[0] for c in comp]
        ys = [c[1] for c in comp]
        bw, bh = max(xs) - min(xs) + 1, max(ys) - min(ys) + 1
        cote = min(xs) == 0 or max(xs) == W - 1
        if (cote and (bw < W * .1 or bh > H * .85)) or (not cote and bh < H * .1 and bw > W * .3):
            for c in comp:
                px[c[0], c[1]] = 255
    return ImageOps.expand(b, 24, 255)


def chiffres(img):
    """Les lectures possibles d'une case de score, avec leurs voix : {valeur: voix} (vide si illisible).
    Plusieurs seuils × plusieurs réglages de tesseract : un « 2 » lu « 9 » une fois sur six ne l'emporte pas."""
    g = ImageOps.grayscale(img)
    g = g.resize((max(8, g.width * 3), max(8, g.height * 3)), Image.LANCZOS)
    h = g.histogram()
    tot = sum(h)
    acc, lo, hi = 0, 0, 255
    for v in range(256):
        acc += h[v]
        if acc >= tot * .05:
            lo = v
            break
    acc = 0
    for v in range(255, -1, -1):
        acc += h[v]
        if acc >= tot * .05:
            hi = v
            break
    if hi - lo < 60:
        return {}  # case unie : pas de chiffre
    # la couleur du fond : les bords haut et bas de la case, au milieu (le texte est de l'autre couleur)
    W, H = g.size
    px = g.load()
    bords = [px[x, y] for y in (1, 2, H - 3, H - 2) for x in range(W // 4, W * 3 // 4)]
    fond = sorted(bords)[len(bords) // 2]
    votes = Counter()
    tmp = _tmp()
    for f in (.4, .5, .6):
        thr = lo + (hi - lo) * f
        _binaire(g, thr, fond <= thr).save(tmp)  # fond sombre : le texte clair passe en noir
        for psm in (7, 8, 13):
            out = subprocess.run(["tesseract", tmp, "stdout", "--psm", str(psm), "-c", "tessedit_char_whitelist=0123456789"],
                                 capture_output=True, text=True).stdout.strip()
            if re.fullmatch(r"\d{1,3}", out):
                votes[int(out)] += 1
        if f == .4 and len(votes) == 1 and sum(votes.values()) == 3:
            return {k: v * 3 for k, v in votes.items()}  # unanimes du premier coup : inutile d'insister
    return dict(votes)


def panneaux(row, hmin):
    """Découpe une ligne du bandeau en panneaux de couleur unie (fond de chaque case) : [(x0, x1)]."""
    W, H = row.size
    px = row.load()
    ys = [int(H * f) for f in (.12, .2, .8, .88)]  # bords haut/bas des cases : le fond, pas les chiffres
    cols = []
    for x in range(W):
        cs = [px[x, y] for y in ys]
        cols.append(tuple(sorted(c[k] for c in cs)[1] for k in range(3)))
    dist = lambda a, b: abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])
    cuts = [0]
    x = 3
    while x < W - 3:
        g = [sum(cols[x - 3 + i][k] for i in range(3)) / 3 for k in range(3)]
        d = [sum(cols[x + i][k] for i in range(3)) / 3 for k in range(3)]
        if dist(g, d) > 70:
            cuts.append(x)
            x += 4
        else:
            x += 1
    cuts.append(W)
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b - a >= hmin]


def bordure(c):
    """Couleur moyenne des bords haut et bas d'une case (son fond)."""
    c = c.convert("RGB")
    W, H = c.size
    px = [c.getpixel((x, y)) for y in (1, 2, H - 3, H - 2) for x in range(0, W, max(1, W // 12))]
    return tuple(sum(p[i] for p in px) / len(px) for i in range(3))


class Tableau:
    """Lit les deux scores du bandeau d'un match (D = déroulé ESPN : les sigles des équipes).
    Le bandeau ne bouge pas pendant un match : on repère les deux sigles (sur une ou plusieurs images : le sigle noir sur
    fond blanc se lit moins bien), et chaque score est dans la case collée à son sigle, côté chrono (visiteurs à gauche)."""

    def __init__(self, D):
        self.sig = {k: set(ALIAS.get(D["ab"][k], [D["ab"][k]])) for k in ("away", "home")}
        self.vu = {"away": [], "home": []}   # positions des sigles du tableau, image après image
        self.box = None
        self.miss = 0
        self.n = 0
        self.fond = {}   # couleur des bords de chaque case quand elle porte un score
        self.memo = {}   # la dernière image de chaque case et sa lecture : une case ne change qu'à chaque panier

    def chercher(self, band):
        W, H = band.size
        scale = max(.8, min(2.4, 2000 / W))
        best = {}
        for mode in ("gray", "inv"):
            for w in ocr(prep(band, scale, mode), 11):
                t = re.sub(r"[^A-Z]", "", w["t"].upper())
                for k in ("away", "home"):
                    if t in self.sig[k]:
                        b = (w["x0"] / scale, w["y0"] / scale, w["x1"] / scale, w["y1"] / scale)
                        if k not in best or b[3] - b[1] > best[k][3] - best[k][1]:
                            best[k] = b  # le plus gros : celui du tableau (pas du petit bandeau « NYK 12-0 RUN »)
        for k, b in best.items():
            self.vu[k].append(b)
        self.caler()

    def caler(self):
        if not self.vu["away"] or not self.vu["home"]:
            return
        med = lambda xs: sorted(xs)[len(xs) // 2]
        A = [med([b[i] for b in self.vu["away"]]) for i in range(4)]
        Hm = [med([b[i] for b in self.vu["home"]]) for i in range(4)]
        h = min(A[3] - A[1], Hm[3] - Hm[1])  # la hauteur du texte du sigle (la boîte d'un sigle avalant son logo est plus haute)
        cyA, cyH = (A[1] + A[3]) / 2, (Hm[1] + Hm[3]) / 2
        if abs(cyA - cyH) > h * 2.5:
            return
        def case(b, cy, droite):
            y0, y1 = cy - h * .58, cy + h * .58  # serré : la ligne « FOULS | 1 » sous certains tableaux se collerait au score
            return (b[2] + h * .15, y0, b[2] + h * 2.2, y1) if droite else (b[0] - h * 2.2, y0, b[0] - h * .15, y1)
        self.h = h
        if abs(cyA - cyH) > h * .8:            # l'une sous l'autre : les scores à droite des sigles
            self.box = {"away": case(A, cyA, True), "home": case(Hm, cyH, True)}
            self.cote = {"away": "gauche", "home": "gauche"}
        else:  # côte à côte : les scores vers le centre, sur la même ligne (celle du sigle le mieux cadré)
            cy = cyA if A[3] - A[1] <= Hm[3] - Hm[1] else cyH
            gA = A[0] < Hm[0]
            self.box = {"away": case(A, cy, gA), "home": case(Hm, cy, not gA)}
            self.cote = {"away": "gauche" if gA else "droite", "home": "droite" if gA else "gauche"}
        self.a_affiner = True

    def affiner(self, band):
        """Bord extérieur de chaque case : là où la couleur du fond change (le panneau voisin), pour ne pas l'attraper."""
        rgb = band.convert("RGB")
        W, H = rgb.size
        h = getattr(self, "h", 20)
        for k, (x0, y0, x1, y1) in list(self.box.items()):
            ys = [int(y0) + 1, int(y0) + 3, int(y1) - 4, int(y1) - 2]
            col = lambda x: tuple(sorted(rgb.getpixel((x, y))[i] for y in ys)[len(ys) // 2] for i in range(3))
            dist = lambda a, b: sum(abs(a[i] - b[i]) for i in range(3))
            # on part du côté du sigle et on avance ; le bord = un changement de couleur qui DURE (un trait de chiffre ne dure pas)
            vers_droite = self.cote.get(k) == "gauche"  # la case est à droite de son sigle
            xa = int(x0 + h * .1) if vers_droite else int(x1 - h * .1)
            ref = col(xa)
            pas = 1 if vers_droite else -1
            lim = min(W - 13, int(x1 + h)) if vers_droite else max(12, int(x0 - h))
            x, bord = xa, None
            while (x < lim) if vers_droite else (x > lim):
                if all(dist(col(x + pas * d), ref) > 80 for d in range(0, 12, 3)):
                    bord = x
                    break
                x += pas
            if bord is not None and abs(bord - xa) > h * 1.5:  # une case de score est au moins aussi large que 1,5 fois le sigle
                if vers_droite:
                    x1 = min(x1, bord - 2)
                else:
                    x0 = max(x0, bord + 2)
            self.box[k] = (x0, y0, x1, y1)

    def lire(self, band, horloge=None):
        self.n += 1
        if self.box is None or self.miss >= 12:
            if self.miss >= 12:  # le bandeau a changé (autre chaîne, autre plan) : on repart de zéro
                self.vu, self.box, self.miss, self.memo, self.fond = {"away": [], "home": []}, None, 0, {}, {}
            if self.n % 2 == 1:  # la recherche coûte : une image sur deux
                self.chercher(band)
        if self.box is None:
            return None
        if getattr(self, "a_affiner", False):
            self.affiner(band)
            self.a_affiner = False
        W, H = band.size
        out = []
        for k in ("away", "home"):
            x0, y0, x1, y1 = self.box[k]
            c = band.crop((max(0, int(x0)), max(0, int(y0)), min(W, int(x1)), min(H, int(y1))))
            if c.width < 6 or c.height < 6:
                out.append({})
                continue
            bord = bordure(c)
            ref = self.fond.get(k)
            if ref and sum(abs(x - y) for x, y in zip(bord, ref)) > 90:
                out.append({})  # le fond de la case n'est plus celui du tableau : gros plan, ralenti, autre image
                continue
            vig = list(ImageOps.grayscale(c).resize((24, 12)).getdata())
            m = self.memo.get(k)
            if m and m[0] and sum(abs(x - y) for x, y in zip(vig, m[0])) / len(vig) < 5:
                out.append(m[1])  # case inchangée : même lecture, sans relancer tesseract
                continue
            r = chiffres(c)
            self.memo[k] = (vig, r)
            if r and k not in self.fond:
                self.fond[k] = bord  # la couleur du fond de la case, la première fois qu'elle est lue
            out.append(r)
        if not out[0] or not out[1]:
            self.miss += 1
            return None
        self.miss = 0
        return tuple(out)  # ({valeur: voix} visiteurs, {valeur: voix} domicile)


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


FIN = .01  # chrono « -0.01 » = période terminée (le panier à 0.0 est compris), sans basculer sur la prolongation suivante


def moment(el):
    if el < 2880 + 2 * FIN:
        per = min(4, int(el // 720) + 1)
        return per, round(720 - (el - (per - 1) * 720), 2)
    per = 5 + int((el - 2880 - 2 * FIN) // 300)
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
    return {"plays": plays, "etats": etats, "nper": max([4] + [p["per"] for p in plays]), "ab": ab, "gid": str(gid),
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


RETARD = 3.5  # le bandeau change de score ~2 s (de chrono) avant l'horaire noté par ESPN (vérifié : 14-7 à l'écran à 6:25, ESPN 6:24)


def apres(per, sec):
    """Le moment du chrono lu, RETARD compris ; à partir du 4e quart-temps, jamais au-delà de la période (24/11 : les 3,5 s
    débordaient sur une prolongation fictive à la fin du match)."""
    el = ecoule(per, sec) + RETARD
    return min(el, ecoule(per, 0) + FIN) if per >= 4 else el


def etendre(votes):
    """Les confusions courantes de lecture : un nombre à 3 chiffres est souvent un score collé à un autre chiffre
    (« 907 » = 90 + chrono des tirs) : on essaie aussi ses deux moitiés, à demi-voix."""
    out = dict(votes)
    for v, n in votes.items():
        if v >= 100:
            for w in (v // 10, v % 100):
                out[w] = out.get(w, 0) + n / 2
    return out


def caler(lectures, D):
    """lectures : [(t, quart|None, secondes|None, variante, mots, cases)] ; cases = ({visiteurs: voix}, {domicile: voix}) ou None.
    Renvoie [t, quart, secondes(, visiteurs, domicile)] : le score affiché est CELUI DE L'ÉCRAN quand les cases sont lues
    (validé par la suite des scores ESPN : exact, ou à 3 points près quand ESPN a corrigé un panier après coup), et le
    moment du match (chrono lu + RETARD) reste à l'intérieur de ce score."""
    E = D["etats"]
    K = {p[0]: (p[1], p[2]) for p in nettoyer([l[:4] for l in lectures if l[2] is not None], D["nper"])}
    Kt = sorted(K)
    items = []  # (t, état ESPN, poids, score de l'écran)
    for lec in lectures:
        t, cases = lec[0], (lec[5] if len(lec) > 5 else None)
        if not cases:
            continue
        A, Hm = (etendre({int(k): v for k, v in c.items()}) for c in cases)  # (relu depuis un JSON : clés en texte)
        ta, th = sum(A.values()) or 1, sum(Hm.values()) or 1
        for a, va in A.items():
            for h, vh in Hm.items():
                conf = (va / ta) * (vh / th)  # la part des voix de cette lecture
                ex = [k for k, e in enumerate(E) if e["as"] == a and e["hs"] == h]
                if ex:
                    k, w = ex[0], 2 + 2 * conf
                else:
                    near = [(abs(e["as"] - a) + abs(e["hs"] - h), k) for k, e in enumerate(E)]
                    dmin, k = min(near)
                    if dmin > 3 or conf < .2:
                        continue
                    w = .8 * conf
                fin = E[k + 1]["el"] if k + 1 < len(E) else 1e9
                if t in K:
                    el = apres(*K[t])
                    if not (E[k]["el"] - 25 <= el <= fin + 25):
                        continue
                    w += 1
                else:
                    av = [x for x in Kt if x < t][-1:]
                    ap = [x for x in Kt if x > t][:1]
                    if av and fin < apres(*K[av[0]]) - 30:
                        continue
                    if ap and E[k]["el"] > apres(*K[ap[0]]) + 30:
                        continue
                items.append((t, k, w, (a, h)))
    items.sort()
    n = len(items)  # plus longue suite chronologique : le score ne recule jamais
    best, prev = [0.0] * n, [-1] * n
    for i in range(n):
        ti, ki, wi, _ = items[i]
        best[i] = wi
        for j in range(i):
            tj, kj, wj, _ = items[j]
            if tj < ti and kj <= ki and best[j] + wi > best[i]:
                best[i], prev[i] = best[j] + wi, j
    vu = {}
    if n:
        i = max(range(n), key=lambda x: best[x])
        while i >= 0:
            vu[items[i][0]] = (items[i][1], items[i][3])
            i = prev[i]
    pts = []
    for t in sorted(set(K) | set(vu)):
        if t in vu:
            k, sc = vu[t]
            deb = E[k]["el"] + .01
            fin = (E[k + 1]["el"] - .3) if k + 1 < len(E) else 1e9
            el = min(max(apres(*K[t]), deb), fin) if t in K else deb
            pts.append((t, el, k, sc))
        else:
            pts.append((t, apres(*K[t]), None, None))
    vus = [p for p in pts if p[2] is not None]
    res, last = [], -1.0
    for t, el, k, sc in pts:
        if k is None:  # chrono seul : il ne doit pas contredire les scores vus juste avant / après
            av = [v for v in vus if v[0] < t]
            ap = [v for v in vus if v[0] > t]
            if av and el < av[-1][1]:
                continue
            if ap and el >= ap[0][1] + 30:
                continue
        if k is None:  # chrono seul : on garde le dernier score vu à l'écran, le moment reste dans ce score
            av = [v for v in vus if v[0] < t]
            if av:
                k2 = av[-1][2]
                fin = (E[k2 + 1]["el"] - .3) if k2 + 1 < len(E) else 1e9
                if el <= fin + 20:  # le chrono reste dans ce score (ou juste après) : on garde le score vu
                    k, sc, el = k2, av[-1][3], min(el, fin)
                # sinon le match a bien avancé sans qu'on lise le tableau : le chrono seul (score ESPN)
        if el + .001 < last:
            continue
        last = el
        per, sec = moment(el)
        res.append([t, per, sec, sc[0], sc[1]] if sc else [t, per, sec])
    return res


def lire_plage(frames_dir, frames, t0, t1, D):
    """Lit les images [t0, t1) (une par seconde) : le chrono (Lecteur) et les deux cases de score (Tableau), puis calage."""
    lec, tab, brut = Lecteur(), (Tableau(D) if D else None), []
    for t in range(t0, min(t1, len(frames) * PAS), PAS):
        band = Image.open(os.path.join(frames_dir, frames[t // PAS]))
        r = lec.lire(band)
        cases = tab.lire(band) if tab else None
        if r or cases:
            brut.append((t,) + (tuple(r) if r else (None, None, None)) + ([], cases))
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
