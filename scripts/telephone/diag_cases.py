#!/usr/bin/env python3
"""Diagnostic : python diag_cases.py <video> <gid> <de> <à> t:score …  (lecture + calage, comparés aux scores attendus)"""
import os, subprocess, sys, tempfile, time
import chrono_video as cv

video, gid, de, a = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
att = dict(x.split(":") for x in sys.argv[5:])
D = cv.deroule(gid)
d = tempfile.mkdtemp()
subprocess.run(["ffmpeg", "-loglevel", "error", "-i", video, "-vf",
                f"fps=1,crop=iw:ih*{cv.BANDE}:0:ih*{1 - cv.BANDE}", "-ss", "0", "-t", str(a), os.path.join(d, "%05d.png")], check=True)
fr = sorted(os.listdir(d))
t0 = time.time()
pts, brut = cv.lire_plage(d, fr, de, a, D)
print("%.1f s par image" % ((time.time() - t0) / (a - de)))
P = {p[0]: p for p in pts}
ok = 0
for t, s in att.items():
    near = [p for p in pts if p[0] <= int(t)][-1:] or [None]
    p = near[0]
    lu = "%d-%d" % (p[3], p[4]) if p and len(p) == 5 else "(chrono seul)" if p else "rien"
    ok += lu == s
    print(t, "écran", s, "site", lu, p)
print(ok, "/", len(att), "—", len(pts), "points dont", sum(1 for p in pts if len(p) == 5), "avec score")
