"""Robot vidéos du site v2 (Nocturne).

Lit les flux RSS publics des chaînes YouTube (15 dernières vidéos chacune,
aucune clé nécessaire) et accumule le tout dans v2/videos.json (branche data).
En tournant toutes les 20 minutes, on garde la trace de toutes les vidéos
même quand une chaîne en publie plus de 15 dans la nuit.

Usage : python scripts/v2_videos.py <chemin/videos.json>
"""
import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

CHANNELS = {
    "UC0LrZO9wORIqn_aRJtKdgfA": "gt",    # GAMETIME HIGHLIGHTS (source principale, choix de Kiki)
    "UCWJ2lWNubArHWmf3FIHbfcQ": "nba",   # chaîne officielle NBA
    "UCcMGbm0EYWh1SZZ8MsM75tw": "bein",  # NBA Extra — beIN SPORTS France
}
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
KEEP_DAYS = 10


def feed_videos(channel_id):
    req = urllib.request.Request(FEED.format(channel_id), headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    out = []
    for e in root.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", "", NS)
        title = e.findtext("a:title", "", NS)
        pub = e.findtext("a:published", "", NS)
        if vid and title:
            out.append({"id": vid, "t": title, "c": CHANNELS[channel_id], "p": pub})
    return out


def main(path):
    try:
        with open(path, encoding="utf-8") as f:
            old = {v["id"]: v for v in json.load(f).get("videos", [])}
    except (OSError, json.JSONDecodeError):
        old = {}
    for ch in CHANNELS:
        try:
            for v in feed_videos(ch):
                old[v["id"]] = v
        except Exception as e:  # une chaîne qui rate ne doit pas bloquer les autres
            print(f"[avert.] {ch} : {e}", file=sys.stderr)
        time.sleep(1)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    videos = sorted((v for v in old.values() if v.get("p", "") >= cutoff),
                    key=lambda v: v.get("p", ""), reverse=True)
    data = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "videos": videos}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(videos)} vidéos gardées ({KEEP_DAYS} jours)")


if __name__ == "__main__":
    main(sys.argv[1])
