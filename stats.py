"""Statistiques de visite anonymes, pour la page admin (lien secret ?admin=<code>).

Pas d'adresse IP, pas de compte : chaque appareil a un numéro tiré au hasard (cookie nba_id).
Événements enregistrés (une ligne = un dict compact) :
  t  : heure (secondes depuis 1970, UTC)      u  : numéro de l'appareil
  k  : type (voir KINDS)                       d  : nuit concernée (AAAA-MM-JJ, jour du match ESPN) ou ""
  g  : match (id ESPN) ou ""                   x  : précision (vue, réglage, message d'erreur…)
  z  : fuseau du navigateur                    dev: appareil (Téléphone / Tablette / PC)
  me : 1 = un appareil de l'admin (exclu par défaut des chiffres)
Les clics faits dans la page (vidéos, stats, récap…) ne passent pas par le serveur : un petit script les note dans le
cookie nba_ev (« t36.k.g.AAMMJJ » séparés par des tirets), relu au chargement suivant. Le cookie nba_hb (« début.dernier »
en base 36) dit combien de temps la page est restée affichée.
"""
import logging
import random
import string
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timezone

KINDS = {
    "open": "Arrivée sur le site", "nav": "Changement de nuit / de vue", "set": "Réglage modifié",
    "v": "Résumé vidéo d'un match", "x": "NBA Extra d'un match", "q": "Recherche d'un résumé",
    "R": "Résumé de la nuit (vidéo)", "X": "NBA Extra (émission)", "s": "Stats d'un match",
    "p": "Carte de tirs d'un joueur", "n": "Récap de la nuit révélé", "r": "Score révélé", "w": "Bilan de la semaine révélé",
    "hb": "Présence", "err": "Erreur",
}
CLIENT_KINDS = set("vxqRXspnrw")
VISIT_GAP = 30 * 60          # 30 min sans rien = nouvelle visite
log = logging.getLogger("nba")

# Tampon partagé par toutes les visites (ce module reste chargé d'un passage à l'autre de Streamlit) :
# les événements sont envoyés sur GitHub toutes les 5 minutes, groupés par mois (stats/AAAA-MM.json).
BUFFER = []
LOCK = threading.Lock()
_ERRS = {}


def add(event):
    with LOCK:
        BUFFER.append(event)


def add_error(msg):
    """Erreur du site (ESPN ou YouTube qui ne répond pas, plantage) : une seule fois par 10 minutes pour le même message."""
    now = time.time()
    with LOCK:
        if now - _ERRS.get(msg, 0) < 600:
            return
        _ERRS[msg] = now
        BUFFER.append({"t": int(now), "k": "err", "x": msg[:300]})


def flush(store):
    """Envoie le tampon (un fichier par mois). En cas d'échec, les événements restent pour le prochain passage."""
    with LOCK:
        events = BUFFER[:]
        BUFFER.clear()
    by_month = defaultdict(list)
    for e in events:
        by_month[month_of(e["t"])].append(e)
    for m, evs in by_month.items():
        try:
            ok = store.update(f"{m}.json", [], lambda data, evs=evs: data.extend(evs), "Statistiques de visite") is not None
        except Exception as e:
            log.warning("Statistiques : %s", type(e).__name__)
            ok = False
        if not ok:
            with LOCK:
                BUFFER[:0] = evs


def start_flusher(store, every=300):
    if any(t.name == "stats-envoi" for t in threading.enumerate()):
        return

    def loop():
        while True:
            time.sleep(every)
            flush(store)
    threading.Thread(target=loop, daemon=True, name="stats-envoi").start()


def new_id():
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=10))


def device(ua):
    ua = ua or ""
    if "iPad" in ua or ("Android" in ua and "Mobile" not in ua):
        kind = "Tablette"
    elif any(x in ua for x in ("Mobi", "iPhone", "Android")):
        kind = "Téléphone"
    else:
        kind = "PC"
    os_ = next((n for k, n in (("iPhone", "iOS"), ("iPad", "iPadOS"), ("Android", "Android"), ("Windows", "Windows"),
                               ("Mac OS", "Mac"), ("CrOS", "ChromeOS"), ("Linux", "Linux")) if k in ua), "")
    return f"{kind} · {os_}" if os_ else kind


def parse_client(raw):
    """Cookie nba_ev → [(jeton, événement)] (les jetons servent à les retirer du cookie une fois enregistrés)."""
    out = []
    for tok in (raw or "").split("-"):
        parts = tok.split(".")
        if len(parts) != 4 or parts[1] not in CLIENT_KINDS:
            continue
        try:
            t = int(parts[0], 36)
            d = date(2000 + int(parts[3][:2]), int(parts[3][2:4]), int(parts[3][4:6])).isoformat() if parts[3] else ""
        except ValueError:
            continue
        g = parts[2] if parts[2].isdigit() else ""
        out.append((tok, {"t": t, "k": parts[1], "g": g, "d": d}))
    return out


def parse_hb(raw):
    """Cookie nba_hb → (début, dernier signe de vie) de la dernière visite, ou None."""
    try:
        s, l = (int(x, 36) for x in (raw or "").split("."))
        return (s, l) if 0 < s <= l else None
    except ValueError:
        return None


def month_of(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m")


def dedupe(events):
    """Un clic peut être relu deux fois (page rechargée avant d'effacer le cookie) : on garde un exemplaire."""
    seen, out = set(), []
    for e in sorted(events, key=lambda e: e.get("t", 0)):
        key = (e.get("u"), e.get("k"), e.get("g"), e.get("t"), e.get("d"), e.get("s")) if e.get("k") != "err" else id(e)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def visits(events):
    """Regroupe les événements de chaque appareil en visites (30 min sans rien = nouvelle visite).
    Renvoie [{u, start, end, n, events}] ; la durée tient compte des signes de vie (hb)."""
    by_u = defaultdict(list)
    for e in events:
        if not e.get("u") or e.get("k") == "err":
            continue
        if e["k"] == "hb":
            by_u[e["u"]] += [(e["s"], e), (e["t"], e)]
        else:
            by_u[e["u"]].append((e["t"], e))
    out = []
    for u, pts in by_u.items():
        pts.sort(key=lambda p: p[0])
        cur = None
        for t, e in pts:
            if cur is None or t - cur["end"] > VISIT_GAP:
                cur = {"u": u, "start": t, "end": t, "events": []}
                out.append(cur)
            cur["end"] = max(cur["end"], t)
            if e["k"] != "hb" and (not cur["events"] or cur["events"][-1] is not e):
                cur["events"].append(e)
    return sorted(out, key=lambda v: v["start"])


def night_activity(events):
    """Par (appareil, nuit) : ce qui a été ouvert. Les vidéos et stats comptent les matchs DIFFÉRENTS."""
    acc = defaultdict(lambda: {"vu": False, "v": set(), "x": set(), "q": set(), "s": set(), "p": 0, "r": set(),
                               "R": False, "X": False, "n": False, "first": None, "last": None})
    for e in events:
        if not e.get("u") or not e.get("d") or e["k"] in ("hb", "err", "set"):
            continue
        a = acc[(e["u"], e["d"])]
        a["first"] = e["t"] if a["first"] is None else min(a["first"], e["t"])
        a["last"] = e["t"] if a["last"] is None else max(a["last"], e["t"])
        k = e["k"]
        if k in ("open", "nav") and e.get("x", "nuit") == "nuit":
            a["vu"] = True
        elif k in ("v", "x", "q", "s", "r"):
            a[k].add(e.get("g") or "?")
            a["vu"] = True
        elif k == "p":
            a["p"] += 1
        elif k in ("R", "X", "n"):
            a[k] = True
            a["vu"] = True
    return acc


def fmt_dur(secs):
    secs = int(max(0, secs))
    if secs < 60:
        return "< 1 min"
    h, m = divmod(secs // 60, 60)
    return f"{h} h {m:02d}" if h else f"{m} min"
