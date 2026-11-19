#!/usr/bin/env python3
"""Nocturne : lire le chrono du match dans un résumé vidéo, image par image.

Tourne sur le téléphone-serveur (Termux). Pour une vidéo : une image toutes les 2 s
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
import time

from PIL import Image, ImageOps

PAS = 2            # une image toutes les 2 s
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


def read_clock(s):
    """(secondes, variante) ; « 1:05 » peut être un « 11:05 » mal lu."""
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
    if m and int(m.group(1)) < 60:
        return int(m.group(1)) + int(m.group(2)) / 10, None
    return None


TMP = os.path.join(tempfile.gettempdir(), "nocturne_ocr.png")


def ocr(img, psm):
    img.save(TMP)
    out = subprocess.run(["tesseract", TMP, "stdout", "--psm", str(psm), "tsv"],
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


def find_clock(words, near=None):
    best = None
    for w in words:
        if near is not None and w is near:
            continue
        c = read_clock(w["t"])
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
class Lecteur:
    def __init__(self):
        self.lock = None   # (x0, y0, x1, y1) dans la bande
        self.polar = False
        self.miss = 0

    def lire(self, band):
        W, H = band.size
        if self.lock:
            x0, y0, x1, y1 = [int(v) for v in self.lock]
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
            crop = band.crop((x0, y0, x1, y1))
            scale = max(1.5, min(4, 210 / max(1, crop.height)))
            words = ocr(prep(crop, scale, "thr" if self.polar else "inv"), 6)
            q = find_quarter(words)
            k = find_clock(words, q[1] if q else None)
            if not k:
                self.polar = not self.polar
                self.miss += 1
                if self.miss >= 6:
                    self.lock, self.miss = None, 0
                return None
            self.miss = 0
            return (q[0] if q else None, k[0], k[1])
        # recherche du bandeau
        scale = max(.8, min(2.4, 2000 / W))
        words = ocr(prep(band, scale, "inv" if self.polar else "gray"), 11)
        q = find_quarter(words)
        k = find_clock(words, q[1] if q else None)
        if not q and not k:
            self.polar = not self.polar
            return None
        f = lambda w: (w["x0"] / scale, w["y0"] / scale, w["x1"] / scale, w["y1"] / scale)
        if q and k:
            a, b = f(q[1]), f(k[3])
            tw, th = a[2] - a[0], a[3] - a[1]
            x0, y0, x1, y1 = min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])
            mw, mh = (x1 - x0) * .12 + tw * .25, (y1 - y0) * .1 + th * .3
            self.lock = (x0 - mw, y0 - mh, x1 + mw, y1 + mh)
        elif q:
            a = f(q[1]); tw, th = a[2] - a[0], a[3] - a[1]
            self.lock = (a[0] - tw * 1.6, a[1] - th * 2.4, a[0] + tw * 2.6, a[1] + th * 1.4)
        else:
            b = f(k[3]); cw, ch = b[2] - b[0], b[3] - b[1]
            self.lock = (b[0] - cw * .7, b[1] - ch * .4, b[0] + cw * 1.7, b[1] + ch * 1.9)
        self.polar = False
        return (q[0], k[0], k[1]) if q and k else None


def frac(per, sec):
    return ((per - 1) * 720 + 720 - sec) / 2880 if per <= 4 else 1 + ((per - 5) * 300 + 300 - sec) / 2880


def nettoyer(lectures):
    """Plus longue suite où le match avance (un résumé est chronologique).
    Chaque lecture propose 1 ou 2 moments (« 1:05 » / « 11:05 ») : on en garde au plus un."""
    cands = []  # (i, t, per, sec, poids)
    for i, (t, per, sec, alt) in enumerate(lectures):
        for s, w in ((sec, 1.0), (alt, .9)):
            if s is not None and s <= (300 if per > 4 else 720):
                cands.append((i, t, per, s, w))
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


def analyse(video, sortie, vid=""):
    t0 = time.time()
    tmp = tempfile.mkdtemp(prefix="nocturne_")
    try:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-vf",
                        f"fps=1/{PAS},crop=iw:ih*{BANDE}:0:ih*{1 - BANDE}", os.path.join(tmp, "%05d.png")], check=True)
        frames = sorted(os.listdir(tmp))
        t1 = time.time()
        lec, brut, per_vu = Lecteur(), [], None
        for k, name in enumerate(frames):
            r = lec.lire(Image.open(os.path.join(tmp, name)))
            if not r:
                continue
            per, sec, alt = r
            per = per or per_vu
            if not per:
                continue
            per_vu = per
            brut.append((k * PAS, per, sec, alt))
        pts = nettoyer(brut)
        res = {"v": vid, "pas": PAS, "made": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "n": len(frames), "lus": len(brut), "pts": pts}
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
