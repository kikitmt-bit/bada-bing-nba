#!/usr/bin/env python3
"""Test de la lecture des cases de score sur des images de référence (nuit du 19/11)."""
import os, subprocess, sys, tempfile
from PIL import Image
import chrono_video as cv

V = sys.argv[1]
REF = (("401910020", 605, {612: (63, 63), 630: (82, 75)}),
       ("401910021", 14, {16: (2, 5), 34: (14, 7), 63: (37, 30), 102: (71, 57), 140: (97, 90)}))
ok = n = 0
for gid, de, ts in REF:
    d = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(de), "-i", V, "-t", str(max(ts) - de + 1), "-vf",
                    "fps=1,crop=iw:ih*0.3:0:ih*0.7", d + "/%03d.png"], check=True)
    T = cv.Tableau(cv.deroule(gid))
    for name in sorted(os.listdir(d)):
        t = de - 1 + int(name[:3])
        r = T.lire(Image.open(d + "/" + name))
        if t in ts:
            n += 1
            bon = bool(r) and max(r[0], key=r[0].get) == ts[t][0] and max(r[1], key=r[1].get) == ts[t][1]
            ok += bon
            print(gid, t, "attendu", ts[t], "lu", r, "OK" if bon else "", flush=True)
print("RÉSULTAT", ok, "/", n, flush=True)
