"""Bada Bing NBA : les matchs NBA sans spoil.

Liste des matchs par nuit, preview écrite avant le match, résumés vidéo (NBA, NBA Extra de beIN SPORTS),
journal NBA Extra du jour, et, seulement quand on le demande, le score, l'analyse et la feuille de match.
Données : API publique d'ESPN (sans clé) et YouTube (flux public, ou API YouTube si une clé est fournie).
"""
import html
import json
import logging
import math
import os
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import streamlit.components.v1 as components

APP_VERSION = "2026-10-v008"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")  # infos d'avant-match gardées (blessés, cotes, preview IA)
log = logging.getLogger("nba")

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
NY = ZoneInfo("America/New_York")  # le « jour du match » est celui de New York (calendrier d'ESPN)
ZONES = {"Paris": ZoneInfo("Europe/Paris"), "Montréal": ZoneInfo("America/Toronto")}

NBA_CHANNEL = "UCWJ2lWNubArHWmf3FIHbfcQ"    # chaîne officielle NBA
EXTRA_CHANNEL = "UCcMGbm0EYWh1SZZ8MsM75tw"  # NBA Extra - beIN SPORTS France
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
YOUTUBE_PLAYLIST_URL = "https://www.googleapis.com/youtube/v3/playlistItems"

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]

# Surnoms utilisés dans les titres YouTube, en plus du nom officiel
TEAM_ALIASES = {
    "76ers": ["76ers", "sixers"], "Trail Blazers": ["trail blazers", "blazers"], "Timberwolves": ["timberwolves", "wolves"],
    "Cavaliers": ["cavaliers", "cavs"], "Mavericks": ["mavericks", "mavs"], "Pelicans": ["pelicans", "pels"],
}
INJURY_FR = {
    "knee": "genou", "ankle": "cheville", "back": "dos", "hamstring": "ischios", "achilles": "Achille", "foot": "pied", "hip": "hanche",
    "shoulder": "épaule", "wrist": "poignet", "hand": "main", "calf": "mollet", "groin": "aine", "illness": "malade",
    "concussion": "commotion", "rest": "repos", "thumb": "pouce", "finger": "doigt", "elbow": "coude", "toe": "orteil",
    "quadriceps": "quadriceps", "quad": "quadriceps", "abdomen": "abdominaux", "neck": "cou", "eye": "œil", "personal": "raisons perso",
    "not injury related": "hors blessure", "lower leg": "jambe", "shin": "tibia", "oblique": "oblique", "chest": "poitrine",
    "rib": "côtes", "ribs": "côtes", "face": "visage", "head": "tête", "heel": "talon", "undisclosed": "non précisé",
    "lower back": "bas du dos", "leg": "jambe", "nose": "nez", "jaw": "mâchoire", "pelvis": "bassin", "adductor": "adducteurs",
}
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "Mozilla/5.0 (BadaBingNBA)"


# =========================================================================
# OUTILS
# =========================================================================
def _secret(section, key, default=""):
    """st.secrets[section][key], sinon la variable d'environnement SECTION_KEY."""
    try:
        value = st.secrets[section][key]
        if value not in (None, ""):
            return value
    except Exception:
        pass
    return os.environ.get(f"{section}_{key}".upper()) or default


def get_json(url, params=None, timeout=10):
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning("HTTP %s sur %s", r.status_code, url.split("?")[0])
    except Exception as e:
        log.warning("%s sur %s", type(e).__name__, url.split("?")[0])
    return None


def parse_dt(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def ny_day(iso):
    dt = parse_dt(iso)
    return dt.astimezone(NY).date() if dt else None


def norm(text):
    """Minuscules sans accents (pour comparer des titres)."""
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return text.lower()


def esc(text):
    return html.escape(str(text or ""))


def bucket(seconds):
    """Tranche de temps : change toutes les `seconds` secondes (sert de clé de cache)."""
    return int(time.time() // seconds)


def fr_hour(dt):
    return f"{dt.hour}h{dt.minute:02d}"


def fr_short(d):
    return f"{JOURS[d.weekday()][:3]}. {d.day}"


def fr_long(d, year=False):
    day = "1er" if d.day == 1 else str(d.day)
    return f"{JOURS[d.weekday()]} {day} {MOIS[d.month - 1]}" + (f" {d.year}" if year else "")


def fr_num(x, digits=1):
    return f"{x:.{digits}f}".replace(".", ",")


def strip_html(text):
    text = re.sub(r"<[^>]+>", "", text or "")
    return re.sub(r"[ \t]*\n[\s]*", "\n", html.unescape(text)).strip()


def season_of(d):
    """Saison NBA (année de fin) d'un jour : 2027 pour 2026-27."""
    return d.year + 1 if d.month >= 8 else d.year


def disk_get(name):
    try:
        with open(os.path.join(CACHE_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def disk_put(name, value):
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, name), "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Cache disque : %s", type(e).__name__)


# =========================================================================
# ÉQUIPES, CALENDRIER, HISTORIQUE
# =========================================================================
@st.cache_data(ttl=86400, show_spinner=False)
def teams():
    """{id: {abbr, name (« Lakers »), full, logo, color, conf (« Est »/« Ouest »)}}."""
    out = {}
    d = get_json(f"{ESPN}/teams") or {}
    for item in (((d.get("sports") or [{}])[0].get("leagues") or [{}])[0].get("teams") or []):
        t = item.get("team") or {}
        out[t["id"]] = {
            "id": t["id"], "abbr": t.get("abbreviation", ""), "name": t.get("name") or t.get("shortDisplayName", ""),
            "full": t.get("displayName", ""), "logo": ((t.get("logos") or [{}])[0]).get("href", ""),
            "color": "#" + (t.get("color") or "888888"), "alt": "#" + (t.get("alternateColor") or "888888"), "conf": "",
        }
    s = get_json(ESPN_STANDINGS) or {}
    for child in s.get("children") or []:
        conf = "Est" if "east" in norm(child.get("name")) else "Ouest"
        for e in (child.get("standings") or {}).get("entries") or []:
            tid = (e.get("team") or {}).get("id")
            if tid in out:
                out[tid]["conf"] = conf
    return out


def team(tid):
    return teams().get(tid) or {"id": tid, "abbr": "?", "name": "?", "full": "?", "logo": "", "color": "#888", "conf": ""}


@st.cache_resource(show_spinner=False)
def history():
    """Matchs des saisons passées (data/nba_history.json, construit par data/build_nba_history.py)."""
    try:
        with open(os.path.join(HERE, "data", "nba_history.json"), encoding="utf-8") as f:
            return json.load(f).get("games") or []
    except Exception:
        return []


def _team_schedule(tid, season, playoffs):
    games = []
    for code in ((2, 3) if playoffs else (2,)):
        d = get_json(f"{ESPN}/teams/{tid}/schedule", {"season": season, "seasontype": code}) or {}
        for e in d.get("events") or []:
            c = (e.get("competitions") or [{}])[0]
            sides = {t.get("homeAway"): t for t in c.get("competitors") or []}
            if "home" not in sides or "away" not in sides:
                continue
            done = bool(((c.get("status") or {}).get("type") or {}).get("completed"))
            def score(t):
                try:
                    return int((t.get("score") or {}).get("value"))
                except (TypeError, ValueError, AttributeError):
                    return None
            hs, as_ = score(sides["home"]), score(sides["away"])
            games.append({
                "id": e.get("id"), "day": ny_day(e.get("date")), "home": sides["home"]["team"]["id"], "away": sides["away"]["team"]["id"],
                "hs": hs, "as": as_, "done": done and hs is not None and as_ is not None, "kind": "R" if code == 2 else "P",
            })
    return games


@st.cache_data(ttl=3600, show_spinner=False)
def season_games(season, _bucket):
    """Tous les matchs de la saison (joués et à venir), lus équipe par équipe chez ESPN."""
    today = datetime.now(NY).date()
    playoffs = today >= date(season, 4, 10)
    with ThreadPoolExecutor(12) as pool:
        lists = list(pool.map(lambda tid: _team_schedule(tid, season, playoffs), list(teams())))
    games = {}
    for lst in lists:
        for g in lst:
            if g["id"] and g["day"]:
                games[g["id"]] = g
    return sorted(games.values(), key=lambda g: g["day"])


@st.cache_resource(show_spinner=False, max_entries=2)
def team_index(season, _bucket):
    """{id équipe: [(jour, adversaire, ses points, points adverses, à domicile, saison, R/P), ...]} trié, matchs terminés."""
    idx = defaultdict(list)
    rows = [(date.fromisoformat(g[0]), g[1], g[2], g[3], g[4], g[5], g[6]) for g in history()]
    rows += [(g["day"], g["home"], g["away"], g["hs"], g["as"], season, g["kind"]) for g in season_games(season, _bucket) if g["done"]]
    seen = set()
    for day, h, a, hs, as_, s, kind in rows:
        if (day, h, a) in seen:
            continue
        seen.add((day, h, a))
        idx[h].append((day, a, hs, as_, True, s, kind))
        idx[a].append((day, h, as_, hs, False, s, kind))
    for lst in idx.values():
        lst.sort()
    return dict(idx)


# =========================================================================
# MATCHS DU JOUR ET DÉTAIL (ESPN)
# =========================================================================
def _parse_event(e):
    c = (e.get("competitions") or [{}])[0]
    status = c.get("status") or {}
    stype = status.get("type") or {}
    sides = {t.get("homeAway"): t for t in c.get("competitors") or []}

    def side(t):
        try:
            score = int(t.get("score"))
        except (TypeError, ValueError):
            score = None
        return {"id": (t.get("team") or {}).get("id"), "score": score, "winner": bool(t.get("winner")),
                "lines": [int(float(l.get("value") or 0)) for l in t.get("linescores") or []]}

    venue = c.get("venue") or {}
    return {
        "id": e.get("id"), "utc": e.get("date"), "day": ny_day(e.get("date")),
        "state": stype.get("state", "pre"), "completed": bool(stype.get("completed")), "status": stype.get("name", ""),
        "detail": stype.get("shortDetail", ""), "period": status.get("period") or 0,
        "home": side(sides.get("home") or {}), "away": side(sides.get("away") or {}),
        "venue": venue.get("fullName", ""), "city": (venue.get("address") or {}).get("city", ""),
        "neutral": bool(c.get("neutralSite")), "notes": [n.get("headline") for n in c.get("notes") or [] if n.get("headline")],
        "season": (e.get("season") or {}).get("year") or season_of(ny_day(e.get("date")) or date.today()),
        "season_type": (e.get("season") or {}).get("type") or 2,
        "tv": ", ".join(sorted({n for b in c.get("broadcasts") or [] for n in b.get("names") or []})),
    }


@st.cache_data(ttl=3600, show_spinner=False, max_entries=200)
def scoreboard(day_iso, _bucket):
    d = get_json(f"{ESPN}/scoreboard", {"dates": day_iso.replace("-", "")})
    if d is None:
        raise ConnectionError("ESPN injoignable")  # une erreur n'est pas gardée en cache : on réessaiera au prochain affichage
    events = d.get("events") or []
    disk_put(f"sb_{day_iso}.json", events)
    return events


def day_games(day):
    """Matchs d'un jour : rafraîchis chaque minute autour d'aujourd'hui, une fois par jour pour les jours anciens.
    Si ESPN ne répond pas, on reprend la dernière version reçue (plutôt que des matchs sans score)."""
    today = datetime.now(NY).date()
    recent = abs((day - today).days) <= 1
    try:
        events = scoreboard(day.isoformat(), bucket(60) if recent else bucket(86400))
    except ConnectionError:
        events = disk_get(f"sb_{day.isoformat()}.json") or []
    games = [_parse_event(e) for e in events]
    return sorted(games, key=lambda g: (g["utc"] or "", g["id"]))


def auto_refresh(games):
    """La page Streamlit ne se met pas à jour seule : un onglet laissé ouvert garde les scores du moment où on l'a ouvert.
    On recharge donc la page quand on revient sur l'onglet après plus de 3 minutes, et toutes les 90 secondes pendant
    les matchs (sauf si un panneau est ouvert, pour ne pas le refermer sous les yeux de l'utilisateur)."""
    now = datetime.now(timezone.utc)
    live = any(g["state"] == "in" or (g["state"] == "pre" and g["status"] != "STATUS_POSTPONED" and parse_dt(g["utc"])
                                      and parse_dt(g["utc"]) - now < timedelta(minutes=15)) for g in games)
    busy = ".tg-f:checked, .tgp:checked, details[open]" if st.query_params.get("scores") == "1" else ".tg:checked, details[open]"
    components.html(f"""<script>
const P = window.parent, D = P.document;
if (P.__bbAway) D.removeEventListener('visibilitychange', P.__bbAway);
clearInterval(P.__bbTick);
P.__bbAway = () => {{
  if (D.hidden) P.__bbHiddenAt = Date.now();
  else if (P.__bbHiddenAt && Date.now() - P.__bbHiddenAt > 180000) P.location.reload();
}};
D.addEventListener('visibilitychange', P.__bbAway);
if ({'true' if live else 'false'}) P.__bbTick = setInterval(() => {{
  if (!D.hidden && !D.querySelector({json.dumps(busy)})) P.location.reload();
}}, 90000);
</script>""", height=0)


@st.cache_data(ttl=86400, show_spinner=False, max_entries=400)
def summary(event_id, _bucket):
    """Résumé ESPN d'un match, réduit à ce dont le site a besoin."""
    d = get_json(f"{ESPN}/summary", {"event": event_id}, timeout=12)
    if not d:
        return None
    out = {}
    art = d.get("article") or {}
    out["article"] = {"type": art.get("type", ""), "headline": art.get("headline", ""), "text": strip_html(art.get("story", ""))}
    out["injuries"] = {
        (t.get("team") or {}).get("id"): [
            {"name": (i.get("athlete") or {}).get("displayName", ""), "status": i.get("status", ""),
             "what": ((i.get("details") or {}).get("type") or "")}
            for i in t.get("injuries") or []
        ]
        for t in d.get("injuries") or []
    }
    pred = d.get("predictor") or {}
    try:
        out["home_pct"] = float((pred.get("homeTeam") or {}).get("gameProjection"))
    except (TypeError, ValueError):
        out["home_pct"] = None
    pick = (d.get("pickcenter") or [{}])[0]
    out["line"] = pick.get("details") or ""
    out["total"] = pick.get("overUnder")
    out["leaders"] = {}
    for t in d.get("leaders") or []:
        cats = {}
        for c in t.get("leaders") or []:
            top = (c.get("leaders") or [{}])[0]
            if top.get("athlete"):
                cats[c.get("name", "")] = (top["athlete"].get("displayName", ""), top.get("displayValue", ""))
        out["leaders"][(t.get("team") or {}).get("id")] = cats
    out["box"] = {}
    for t in (d.get("boxscore") or {}).get("players") or []:
        stat = (t.get("statistics") or [{}])[0]
        labels = stat.get("labels") or []
        rows = []
        for a in stat.get("athletes") or []:
            rows.append({
                "id": (a.get("athlete") or {}).get("id"),
                "name": (a.get("athlete") or {}).get("displayName", ""), "short": (a.get("athlete") or {}).get("shortName", ""),
                "starter": bool(a.get("starter")), "dnp": bool(a.get("didNotPlay")), "reason": a.get("reason") or "",
                "stats": dict(zip(labels, a.get("stats") or [])),
            })
        out["box"][(t.get("team") or {}).get("id")] = rows
    out["team_stats"] = {}
    for t in (d.get("boxscore") or {}).get("teams") or []:
        out["team_stats"][(t.get("team") or {}).get("id")] = {s.get("label") or s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
    out["shots"] = []
    for p in d.get("plays") or []:
        c = p.get("coordinate") or {}
        x, y = c.get("x"), c.get("y")
        if not p.get("shootingPlay") or x is None or y is None or not (-10 <= x <= 60 and -10 <= y <= 95):
            continue
        if "free throw" in norm(p.get("text")):
            continue
        aid = (((p.get("participants") or [{}])[0]).get("athlete") or {}).get("id")
        if aid:
            out["shots"].append((aid, (p.get("team") or {}).get("id"), x, y, bool(p.get("scoringPlay")),
                                 p.get("pointsAttempted") == 3 or "three point" in norm(p.get("text"))))
    out["plays"] = [
        (int((p.get("period") or {}).get("number") or 0), (p.get("clock") or {}).get("displayValue", ""), p.get("awayScore", 0),
         p.get("homeScore", 0), bool(p.get("scoringPlay")), p.get("text", ""), (p.get("team") or {}).get("id"))
        for p in d.get("plays") or []
    ]
    return out


def game_summary(g):
    if g["state"] == "post":
        b = bucket(86400 * 30)
    elif g["state"] == "in":
        b = bucket(30)
    else:
        b = bucket(1800)
    s = summary(g["id"], b)
    if s and g["state"] == "pre":
        # Garder ce qu'on sait avant le match : la preview sans spoil s'en servira une fois le match joué
        disk_put(f"pre_{g['id']}.json", {"injuries": s["injuries"], "line": s["line"], "home_pct": s["home_pct"],
                                         "leaders": s["leaders"], "article": s["article"]})
    return s


# =========================================================================
# VIDÉOS YOUTUBE
# =========================================================================
def _parse_feed(text):
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    out = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return out
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", default="", namespaces=ns)
        if vid:
            out.append({"id": vid, "title": e.findtext("a:title", default="", namespaces=ns),
                        "published": e.findtext("a:published", default="", namespaces=ns)})
    return out


def _fetch_uploads(api_key, channel_id, oldest, max_pages=40):
    """Vidéos de la chaîne jusqu'à `oldest` (API YouTube Data v3 : 1 unité de quota par page de 50)."""
    entries, token = [], None
    for _ in range(max_pages):
        params = {"part": "snippet", "playlistId": "UU" + channel_id[2:], "maxResults": 50, "key": api_key}
        if token:
            params["pageToken"] = token
        try:
            r = SESSION.get(YOUTUBE_PLAYLIST_URL, params=params, timeout=10)
        except Exception as e:
            log.warning("API YouTube indisponible (%s)", type(e).__name__)
            API_STATUS.update(ok=False, msg=f"API YouTube injoignable ({type(e).__name__})", at=time.time())
            break
        if r.status_code != 200:
            log.warning("API YouTube : HTTP %s", r.status_code)
            reason = ""
            try:
                reason = ((r.json().get("error") or {}).get("errors") or [{}])[0].get("reason", "")
            except Exception:
                pass
            API_STATUS.update(ok=False, msg=f"API YouTube refusée : HTTP {r.status_code} {reason}".strip(), at=time.time())
            break
        API_STATUS.update(ok=True, msg="API YouTube active", at=time.time())
        payload = r.json()
        page = []
        for item in payload.get("items") or []:
            snip = item.get("snippet") or {}
            vid = (snip.get("resourceId") or {}).get("videoId")
            if vid:
                page.append({"id": vid, "title": html.unescape(snip.get("title", "")), "published": snip.get("publishedAt", "")})
        entries += page
        token = payload.get("nextPageToken")
        if not token or not page or all((parse_dt(v["published"]) or oldest) < oldest for v in page[-5:]):
            break
    return entries


@st.cache_data(ttl=3600, show_spinner=False, max_entries=50)
def channel_videos(channel_id, oldest_iso, _bucket):
    """Vidéos de la chaîne publiées depuis `oldest_iso` : ce que la veille a déjà vu, flux public (15 dernières)
    et API YouTube si une clé est donnée."""
    videos = dict(video_watcher()["seen"].get(channel_id) or {})
    try:
        r = SESSION.get(YOUTUBE_FEED_URL.format(channel_id), timeout=8)
        if r.status_code == 200:
            for v in _parse_feed(r.text):
                videos[v["id"]] = v
    except Exception as e:
        log.warning("Flux YouTube indisponible (%s)", type(e).__name__)
    key = str(_secret("youtube", "api_key", ""))
    if key:
        oldest = datetime.fromisoformat(oldest_iso).replace(tzinfo=timezone.utc)
        for v in _fetch_uploads(key, channel_id, oldest):
            videos.setdefault(v["id"], v)
    return list(videos.values())


API_STATUS = {"ok": None, "msg": "", "at": 0}


@st.cache_resource(show_spinner=False)
def video_watcher():
    """Veille : relit les deux chaînes toutes les 10 minutes, même sans visiteur, et garde chaque vidéo vue (10 jours).
    Le flux public ne montre que les 15 dernières vidéos : sans cette veille, les résumés de la nuit en sortent avant le matin."""
    seen = disk_get("seen.json") or {}
    state = {"seen": seen, "last": 0}

    def tick():
        key = str(_secret("youtube", "api_key", ""))
        limit = datetime.now(timezone.utc) - timedelta(days=10)
        for ch in (NBA_CHANNEL, EXTRA_CHANNEL):
            box = seen.setdefault(ch, {})
            try:
                r = SESSION.get(YOUTUBE_FEED_URL.format(ch), timeout=8)
                found = _parse_feed(r.text) if r.status_code == 200 else []
            except Exception:
                found = []
            if key:
                found += _fetch_uploads(key, ch, datetime.now(timezone.utc) - timedelta(hours=18), max_pages=3)
            for v in found:
                box[v["id"]] = v
            for vid in [k for k, v in box.items() if (parse_dt(v.get("published")) or limit) < limit]:
                box.pop(vid, None)
        disk_put("seen.json", seen)
        state["last"] = time.time()

    def loop():
        while True:
            try:
                tick()
            except Exception as e:
                log.warning("Veille vidéos : %s", type(e).__name__)
            time.sleep(600)

    threading.Thread(target=loop, daemon=True, name="veille-videos").start()
    return state


def videos_since(day):
    oldest = (datetime.combine(day, datetime.min.time()) - timedelta(days=1)).isoformat()
    b = bucket(600)
    return channel_videos(NBA_CHANNEL, oldest, b), channel_videos(EXTRA_CHANNEL, oldest, b)


def _names(tid):
    name = team(tid)["name"]
    return TEAM_ALIASES.get(name, [name.lower()])


def _has_team(title_norm, tid):
    return any(re.search(r"\b" + re.escape(norm(n)) + r"\b", title_norm) for n in _names(tid))


def _title_date(title_norm):
    m = re.search(r"(" + "|".join(MONTHS_EN) + r")\s+(\d{1,2}),\s*(\d{4})", title_norm)
    if not m:
        return None
    try:
        return date(int(m.group(3)), MONTHS_EN.index(m.group(1)) + 1, int(m.group(2)))
    except ValueError:
        return None


def _in_window(v, pub, tip, days):
    """Vidéo publiée après le coup d'envoi et moins de `days` jours après. Les dates des résultats de recherche
    (« il y a 8 h ») sont approximatives : marge d'un jour."""
    if not pub or not tip:
        return False
    if v.get("approx"):
        return tip - timedelta(days=1) <= pub <= tip + timedelta(days=days + 1)
    return tip <= pub <= tip + timedelta(days=days)


def nba_video(videos, g):
    """Résumé officiel NBA : « KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026 »."""
    tip = parse_dt(g["utc"])
    best = None
    for v in videos:
        t = norm(v["title"])
        if "highlight" not in t or not (_has_team(t, g["home"]["id"]) and _has_team(t, g["away"]["id"])):
            continue
        if any(x in t for x in ("top 10", "top plays", "nightly", "mixtape", "best of", "every ")):
            continue
        td = _title_date(t)
        if td and td != g["day"]:
            continue
        pub = parse_dt(v["published"])
        if not _in_window(v, pub, tip, 2):
            continue
        key = (0 if "full game highlights" in t else 1, pub)
        if best is None or key < best[0]:
            best = (key, v)
    return best[1] if best else None


def extra_video(videos, g):
    """Résumé de NBA Extra : « Résumé : WARRIORS @ LAKERS, ... »."""
    tip = parse_dt(g["utc"])
    best = None
    for v in videos:
        t = norm(v["title"])
        if not t.startswith("resume") or not (_has_team(t, g["home"]["id"]) and _has_team(t, g["away"]["id"])):
            continue
        pub = parse_dt(v["published"])
        if not _in_window(v, pub, tip, 3):
            continue
        if best is None or pub < best[0]:
            best = (pub, v)
    return best[1] if best else None


def journals(videos):
    """{date du journal: vidéo} pour « REPLAY - NBA Extra (21/10) : ... »."""
    out = {}
    for v in videos:
        t = norm(v["title"])
        m = re.search(r"nba extra\s*\((\d{1,2})/(\d{1,2})\)", t)
        pub = parse_dt(v["published"])
        if not m or not pub or "short" in t:
            continue
        try:
            d = date(pub.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
        if d not in out or "replay" in t:
            out[d] = v
    return out


def nightly_recap(videos, day):
    for v in videos:
        t = norm(v["title"])
        if "nightly recap" in t and _title_date(t) == day:
            return v
    return None


def yt_url(v):
    return f"https://www.youtube.com/watch?v={v['id']}"


def yt_search_url(g):
    q = f"{team(g['away']['id'])['name']} at {team(g['home']['id'])['name']} full game highlights " \
        f"{MONTHS_EN[g['day'].month - 1].title()} {g['day'].day}, {g['day'].year}"
    return "https://www.youtube.com/results?search_query=" + requests.utils.quote(q)


# =========================================================================
# RECHERCHE YOUTUBE (filet de sécurité quand une vidéo n'est pas dans les listes des chaînes)
# =========================================================================
_REL_UNITS = {"s": 1 / 60, "sec": 1 / 60, "second": 1 / 60, "m": 1, "min": 1, "minute": 1, "h": 60, "hr": 60, "hour": 60,
              "d": 1440, "day": 1440, "w": 10080, "wk": 10080, "week": 10080, "mo": 43200, "month": 43200, "y": 525600, "yr": 525600, "year": 525600}


def _rel_time(text, now):
    """« 8h ago », « 2 days ago », « Streamed 3 hours ago » -> date approximative."""
    m = re.search(r"(\d+)\s*([a-z]+)", norm(text))
    if not m:
        return None
    unit = m.group(2) if m.group(2) in _REL_UNITS else m.group(2).rstrip("s")
    minutes = _REL_UNITS.get(unit)
    return now - timedelta(minutes=int(m.group(1)) * minutes) if minutes else None


def _walk_videos(o):
    if isinstance(o, dict):
        if "videoRenderer" in o:
            yield o["videoRenderer"]
        for x in o.values():
            yield from _walk_videos(x)
    elif isinstance(o, list):
        for x in o:
            yield from _walk_videos(x)


@st.cache_data(ttl=900, show_spinner=False, max_entries=1000)
def yt_search(query):
    """Résultats d'une recherche YouTube (page publique, sans clé) : [{id, title, published (approx.), channel, mins}]."""
    try:
        r = SESSION.get("https://www.youtube.com/results", params={"search_query": query, "hl": "en", "gl": "US"},
                        headers={"Accept-Language": "en-US,en"}, cookies={"CONSENT": "YES+1", "SOCS": "CAI"}, timeout=12)
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text)
        data = json.loads(m.group(1)) if m else {}
    except Exception as e:
        log.warning("Recherche YouTube indisponible (%s)", type(e).__name__)
        return []
    now = datetime.now(timezone.utc)
    out = []
    for v in _walk_videos(data):
        title = "".join(x.get("text", "") for x in (v.get("title") or {}).get("runs") or [])
        owner = ((v.get("ownerText") or {}).get("runs") or [{}])[0]
        channel = ((owner.get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get("browseId", "")
        pub = _rel_time((v.get("publishedTimeText") or {}).get("simpleText", ""), now)
        length = (v.get("lengthText") or {}).get("simpleText", "")
        parts = [int(x) for x in length.split(":") if x.isdigit()]
        secs = sum(x * 60 ** i for i, x in enumerate(reversed(parts)))
        if v.get("videoId") and title:
            out.append({"id": v["videoId"], "title": title, "published": pub.isoformat() if pub else "", "channel": channel,
                        "mins": max(1, round(secs / 60)) if secs else None, "approx": True})
    return out


def _from(channel, results):
    return [v for v in results if v["channel"] == channel]


@st.cache_resource(show_spinner=False)
def found_videos():
    """Vidéos déjà trouvées {clé: vidéo}, gardées en mémoire et sur disque (on ne cherche plus ce qu'on a trouvé)."""
    return disk_get("videos.json") or {}


_STORE_LOCK = threading.Lock()


def remember_video(key, v):
    store = found_videos()
    if v and store.get(key, {}).get("id") != v["id"]:
        with _STORE_LOCK:
            store[key] = {k: v.get(k) for k in ("id", "title", "published", "mins")}
            disk_put("videos.json", dict(store))


def game_videos(g, nba_vids, extra_vids):
    """(résumé NBA, résumé NBA Extra) d'un match terminé : listes des chaînes, puis mémoire, puis recherche YouTube."""
    store = found_videos()
    nba = nba_video(nba_vids, g) or store.get(f"nba_{g['id']}")
    extra = extra_video(extra_vids, g) or store.get(f"x_{g['id']}")
    if g["state"] == "post" and not nba:
        ta, th = team(g["away"]["id"])["name"], team(g["home"]["id"])["name"]
        q = f"{ta} at {th} full game highlights {MONTHS_EN[g['day'].month - 1].title()} {g['day'].day}, {g['day'].year}"
        nba = nba_video(_from(NBA_CHANNEL, yt_search(q)), g)
    tip = parse_dt(g["utc"])
    if g["state"] == "post" and not extra and tip and datetime.now(timezone.utc) - tip < timedelta(days=4):
        ta, th = team(g["away"]["id"])["name"], team(g["home"]["id"])["name"]
        extra = extra_video(_from(EXTRA_CHANNEL, yt_search(f"Résumé {ta} @ {th} NBA Extra beIN SPORTS")), g)
    remember_video(f"nba_{g['id']}", nba)
    remember_video(f"x_{g['id']}", extra)
    return nba, extra


def night_videos(day, nba_vids, extra_vids):
    """(résumé de la nuit NBA, émission NBA Extra du lendemain) : listes des chaînes, mémoire, puis recherche."""
    store = found_videos()
    show_day = day + timedelta(days=1)
    recap = nightly_recap(nba_vids, day) or store.get(f"recap_{day}")
    if not recap:
        q = f"NBA's Nightly Recap {MONTHS_EN[day.month - 1].title()} {day.day}, {day.year}"
        recap = nightly_recap(_from(NBA_CHANNEL, yt_search(q)), day)
    show = journals(extra_vids).get(show_day) or store.get(f"show_{show_day}")
    if not show and datetime.now(ZONES["Paris"]).date() >= show_day:
        show = journals(_from(EXTRA_CHANNEL, yt_search(f"NBA Extra ({show_day.day:02d}/{show_day.month:02d}) replay"))).get(show_day)
    remember_video(f"recap_{day}", recap)
    remember_video(f"show_{show_day}", show)
    return recap, show


# =========================================================================
# AVANT-MATCH (calculé sans rien savoir du résultat)
# =========================================================================
def team_form(idx, tid, day, season):
    """État d'une équipe avant le jour `day` : bilan, série, 5 derniers matchs, dos-à-dos."""
    past = [g for g in idx.get(tid, []) if g[0] < day]
    cur = [g for g in past if g[5] == season]
    reg = [g for g in cur if g[6] == "R"]
    wins = sum(1 for g in reg if g[2] > g[3])
    streak = 0
    for g in reversed(cur):
        won = g[2] > g[3]
        if streak == 0:
            streak = 1 if won else -1
        elif (streak > 0) == won:
            streak += 1 if won else -1
        else:
            break
    prev = [g for g in past if g[5] == season - 1 and g[6] == "R"]
    return {
        "w": wins, "l": len(reg) - wins, "n": len(reg), "streak": streak,
        "last": past[-5:], "season": season,
        "prev_w": sum(1 for g in prev if g[2] > g[3]), "prev_l": sum(1 for g in prev if g[2] <= g[3]),
        "b2b": any(g[0] == day - timedelta(days=1) for g in past[-2:]),
    }


def head_to_head(idx, home, away, day):
    return [g for g in idx.get(home, []) if g[1] == away and g[0] < day]


def conf_ranks(idx, day, season):
    """Rang de chaque équipe dans sa conférence avant le jour `day` (pourcentage de victoires)."""
    table = defaultdict(list)
    for tid, info in teams().items():
        reg = [g for g in idx.get(tid, []) if g[0] < day and g[5] == season and g[6] == "R"]
        w = sum(1 for g in reg if g[2] > g[3])
        table[info["conf"]].append((-(w / len(reg)) if reg else 0, -w, tid))
    ranks = {}
    for rows in table.values():
        for i, (_, _, tid) in enumerate(sorted(rows), 1):
            ranks[tid] = i
    return ranks


def injury_text(entries, keep=("out", "doubtful")):
    names = []
    for i in entries or []:
        status = norm(i.get("status"))
        if not any(k in status for k in keep):
            continue
        what = INJURY_FR.get(norm(i.get("what")), i.get("what", "").lower())
        last = i["name"].split(" ", 1)[-1] if " " in i["name"] else i["name"]
        names.append(f"{last} ({what})" if what else last)
    return names


def streak_text(s):
    if s >= 3:
        return f"{s} victoires de suite"
    if s <= -3:
        return f"{-s} défaites de suite"
    return ""


def preview_points(g, idx, pre):
    """3-5 puces courtes en français sur les enjeux, sans rien qui dépende du résultat."""
    h, a = g["home"]["id"], g["away"]["id"]
    th, ta = team(h), team(a)
    fh, fa = team_form(idx, h, g["day"], g["season"]), team_form(idx, a, g["day"], g["season"])
    points = []

    def rec(f):
        return f"{f['w']}-{f['l']}"

    # Le contexte
    playoff = g["season_type"] == 3
    if playoff:
        series = [m for m in head_to_head(idx, h, a, g["day"]) if m[5] == g["season"] and m[6] == "P"]
        wh = sum(1 for m in series if m[2] > m[3])
        wa = len(series) - wh
        if not series:
            state = "premier match de la série"
        elif wh == wa:
            state = f"série à égalité {wh}-{wa}"
        else:
            lead, n1, n2 = (th, wh, wa) if wh > wa else (ta, wa, wh)
            state = f"{lead['name']} mène {n1}-{n2}" + (" : balle de qualification" if n1 == 3 else "")
        points.append(f"🏆 Play-offs, match {len(series) + 1} : {state}.")
    elif fh["n"] == 0 and fa["n"] == 0:
        points.append(f"🏁 Premier match de la saison pour les deux équipes. La saison passée : "
                      f"{th['name']} {fh['prev_w']}-{fh['prev_l']}, {ta['name']} {fa['prev_w']}-{fa['prev_l']}.")
    else:
        ranks = conf_ranks(idx, g["day"], g["season"]) if min(fh["n"], fa["n"]) >= 8 else {}
        def label(t, f):
            r = ranks.get(t["id"])
            return f"{t['name']} ({rec(f) if f['n'] else '1er match'}" + (f", {r}e à l'{t['conf']})" if r else ")")
        same = th["conf"] and th["conf"] == ta["conf"]
        intro = f"Duel de l'{th['conf']}" if same else "Est contre Ouest"
        points.append(f"🏀 {intro} : {label(ta, fa)} chez {label(th, fh)}.")
    notes = [n for n in g["notes"] if n and "series" not in norm(n) and "leads" not in norm(n)]
    if notes or g["neutral"]:
        where = f" à {g['city']}" if g["neutral"] and g["city"] else ""
        points.append("📍 " + (" · ".join(notes) if notes else "Terrain neutre") + where + ".")

    # La forme
    form = []
    for t, f in ((ta, fa), (th, fh)):
        s = streak_text(f["streak"])
        if s:
            form.append(f"{t['name']} sur {s}")
        if f["b2b"]:
            form.append(f"{t['name']} joue son 2e match en 2 soirs")
    if form:
        points.append("📈 " + " ; ".join(form) + ".")

    # Face-à-face
    h2h = head_to_head(idx, h, a, g["day"])[-5:]
    if h2h:
        wh = sum(1 for m in h2h if m[2] > m[3])
        last = h2h[-1]
        winner = th if last[2] > last[3] else ta
        sc = f"{max(last[2], last[3])}-{min(last[2], last[3])}"
        if wh in (0, len(h2h)) and len(h2h) >= 3:
            dom = th if wh else ta
            txt = f"{dom['name']} a gagné les {len(h2h)} derniers face-à-face"
        else:
            lead, n1, n2 = (th, wh, len(h2h) - wh) if wh * 2 >= len(h2h) else (ta, len(h2h) - wh, wh)
            txt = (f"{n1}-{n2} sur les {len(h2h)} derniers face-à-face" if n1 == n2
                   else f"{lead['name']} mène {n1}-{n2} sur les {len(h2h)} derniers face-à-face")
        points.append(f"🆚 {txt} (dernier : {winner['name']} {sc}, le {last[0].day:02d}/{last[0].month:02d}/{last[0].year}).")

    # Absents
    if pre and pre.get("injuries"):
        parts = []
        for t in (ta, th):
            out = injury_text(pre["injuries"].get(t["id"]))
            if out:
                parts.append(f"{t['name']} sans {', '.join(out[:4])}" + ("…" if len(out) > 4 else ""))
        if parts:
            points.append("🩹 " + " ; ".join(parts) + ".")

    # Favori (cotes figées avant le match)
    if pre:
        m = re.match(r"([A-Z]{2,4})\s*(-[\d.]+)", pre.get("line") or "")
        fav = next((t for t in (th, ta) if m and t["abbr"] == m.group(1)), None)
        if fav:
            pct = pre.get("home_pct")
            if pct is not None and fav is ta:
                pct = 100 - pct
            points.append(f"💰 Favori : {fav['name']} ({m.group(2).replace('.', ',')} pts)"
                          + (f", {fr_num(pct, 0)} % de chances selon ESPN." if pct else "."))
        elif (pre.get("line") or "").upper() == "EVEN":
            points.append("💰 Match à pile ou face pour les bookmakers.")
        lead = pre.get("leaders") or {}
        stars = []
        for t in (ta, th):
            p = (lead.get(t["id"]) or {}).get("pointsPerGame")
            if p:
                stars.append(f"{p[0]} ({p[1].replace('.', ',')} pts/match)")
        if len(stars) == 2 and g["state"] == "pre":
            points.append(f"⭐ À suivre : {stars[0]} contre {stars[1]}.")
    return points


# =========================================================================
# APRÈS-MATCH
# =========================================================================
def _clock_secs(txt):
    try:
        if ":" in txt:
            m, s = txt.split(":")
            return int(m) * 60 + float(s)
        return float(txt)
    except ValueError:
        return 0.0


def elapsed_min(period, clock):
    length = 12 if period <= 4 else 5
    start = 12 * min(period - 1, 4) + 5 * max(period - 5, 0)
    return start + length - _clock_secs(clock) / 60


def flow(summ):
    """Écart au fil du match (+ = équipe à domicile) : [(minute, écart)], plus grosses avances, changements de leader."""
    pts, max_h, max_a, changes, last_sign = [(0.0, 0)], 0, 0, 0, 0
    for period, clock, aw, hm, scoring, _, _ in summ.get("plays") or []:
        if not period:
            continue
        diff = int(hm) - int(aw)
        pts.append((round(elapsed_min(period, clock), 2), diff))
        max_h, max_a = max(max_h, diff), max(max_a, -diff)
        sign = (diff > 0) - (diff < 0)
        if sign and last_sign and sign != last_sign:
            changes += 1
        if sign:
            last_sign = sign
    return pts, max_h, max_a, changes


def _num(stats, key):
    try:
        return int(str(stats.get(key, "")).lstrip("+"))
    except ValueError:
        return 0


def game_score(stats):
    """Note d'une performance, pensée pour ressembler à « la grosse perf » qu'on retient : les points d'abord."""
    n = lambda k: _num(stats, k)
    try:
        fgm, fga = (int(x) for x in str(stats.get("FG", "0-0")).split("-"))
    except ValueError:
        fgm, fga = 0, 0
    eff = (fgm / fga - 0.47) * fga * 0.5 if fga else 0
    return n("PTS") + 0.5 * n("REB") + 0.7 * n("AST") + n("STL") + n("BLK") - 0.5 * n("TO") + eff


def stat_line(stats):
    pts, reb, ast = _num(stats, "PTS"), _num(stats, "REB"), _num(stats, "AST")
    parts = [f"{pts} pts"]
    if reb >= 5:
        parts.append(f"{reb} rbds")
    if ast >= 5:
        parts.append(f"{ast} pds")
    for k, lab in (("STL", "int."), ("BLK", "contres")):
        if _num(stats, k) >= 4:
            parts.append(f"{_num(stats, k)} {lab}")
    fg = stats.get("FG", "")
    if fg and fg != "0-0":
        parts.append(f"{fg} au tir")
    tags = sum(1 for k in ("PTS", "REB", "AST", "STL", "BLK") if _num(stats, k) >= 10)
    label = " (triple-double)" if tags >= 3 else " (double-double)" if tags == 2 else ""
    return ", ".join(parts) + label


def recap_points(g, summ, idx):
    h, a = g["home"], g["away"]
    win, lose = (h, a) if (h["score"] or 0) > (a["score"] or 0) else (a, h)
    tw, tl = team(win["id"]), team(lose["id"])
    points = []
    _, max_h, max_a, changes = flow(summ)
    deficit = max_a if win is h else max_h
    margin = win["score"] - lose["score"]
    ot = len(win["lines"]) > 4
    how = []
    if ot:
        how.append("après prolongation" if len(win["lines"]) == 5 else f"après {len(win['lines']) - 4} prolongations")
    if deficit >= 12:
        how.append(f"en revenant de {deficit} points")
    elif margin >= 20:
        how.append("très largement")
    elif margin <= 3 and not ot:
        how.append("sur le fil")
    points.append(f"🏆 {tw['name']} bat {tl['name']} {win['score']}-{lose['score']}" + (" " + " ".join(how) if how else "") + "."
                  + (f" {changes} changements de leader." if changes >= 12 else ""))

    # Grosses perfs
    best = []
    for tid, rows in (summ.get("box") or {}).items():
        for r in rows:
            if not r["dnp"] and r["stats"]:
                best.append((game_score(r["stats"]), r, tid))
    best.sort(key=lambda x: -x[0])
    if best:
        _, r, tid = best[0]
        points.append(f"🔥 La grosse perf : {r['name']} ({team(tid)['name']}) : {stat_line(r['stats'])}.")
        other = next((x for x in best[1:] if x[2] != tid and x[0] >= 20), None)
        if other:
            points.append(f"👏 En face : {other[1]['name']} ({team(other[2])['name']}) : {stat_line(other[1]['stats'])}.")

    # Impact : bilans après le match
    impact = []
    for t, side in ((tw, win), (tl, lose)):
        f = team_form(idx, t["id"], g["day"] + timedelta(days=1), g["season"])
        if not any(m[0] == g["day"] for m in f["last"]):
            continue  # match pas encore dans le calendrier lu chez ESPN
        s = streak_text(f["streak"])
        txt = f"{t['name']} {f['w']}-{f['l']}" + (f" ({s})" if s else "")
        impact.append(txt)
    if impact and g["season_type"] != 3:
        points.append("📊 Bilans : " + " ; ".join(impact) + ".")

    # Blessures signalées dans le compte rendu AP
    story = (summ.get("article") or {}).get("text", "") if (summ.get("article") or {}).get("type") == "Recap" else ""
    hurt = [s.strip() for s in re.split(r"(?<=[.!?])\s+", story)
            if re.search(r"\b(injur|left the game|sprain|strain|did not return|helped off|limped)", s, re.I)]
    if hurt:
        points.append("🩹 Blessure (compte rendu AP, en anglais) : " + " ".join(hurt[:2]))
    return points


# =========================================================================
# CLAUDE (facultatif : seulement si une clé [anthropic] est fournie)
# =========================================================================
AI_MODEL_DEFAULT = "claude-opus-5-5"
AI_SYSTEM = ("Tu écris pour un site français qui suit la NBA. Réponds uniquement par des puces commençant par « - », "
             "en français, très courtes (20 mots au plus chacune), avec un emoji au début de chaque puce. Pas de titre, pas de conclusion.")


def ai_points(kind, g, material):
    """Puces écrites par Claude, gardées sur disque. None si pas de clé ou en cas d'erreur (le site garde alors ses propres puces)."""
    key = str(_secret("anthropic", "api_key", ""))
    if not key:
        return None
    name = f"ai_{kind}_{g['id']}.json"
    cached = disk_get(name)
    # La preview se met à jour toutes les 6 h jusqu'au match (blessés de dernière minute) ; l'analyse est faite une fois
    if cached and (kind == "recap" or g["state"] != "pre" or time.time() - cached.get("t", 0) < 6 * 3600):
        return cached.get("points")
    if kind == "preview" and g["state"] != "pre":
        return None  # jamais de preview IA écrite après le coup d'envoi (risque de spoil)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        if kind == "preview":
            ask = ("Voici les infos d'un match NBA à venir. Écris 3 puces sur les enjeux : contexte, forme ou face-à-face, absents. "
                   "Ne fais aucun pronostic de score.\n\n" + material)
        else:
            ask = ("Voici le compte rendu (en anglais) et les stats d'un match NBA terminé. Écris 3 ou 4 puces : ce qu'il faut retenir, "
                   "la grosse performance, l'impact pour les équipes, et les blessures s'il y en a eu pendant le match.\n\n" + material)
        resp = client.messages.create(
            model=str(_secret("anthropic", "model", AI_MODEL_DEFAULT)), max_tokens=4000,
            output_config={"effort": "low"}, system=AI_SYSTEM, messages=[{"role": "user", "content": ask}],
        )
        if resp.stop_reason == "refusal":
            return None
        text = "\n".join(b.text for b in resp.content if b.type == "text")
        points = [re.sub(r"^\s*[-•*]\s*", "", line).strip() for line in text.splitlines() if re.match(r"^\s*[-•*]\s+", line)]
        if points:
            disk_put(name, {"t": time.time(), "points": points})
        return points or None
    except Exception as e:
        log.warning("Claude indisponible (%s)", type(e).__name__)
        return None


# =========================================================================
# INDICE « À VOIR » (sans dire qui gagne) ET AFFICHE DE LA NUIT
# =========================================================================
# Échelle à 6 niveaux : (icône, nom, conseil). Avant le score, seuls l'icône, le nom et le conseil sont affichés.
WATCH_LEVELS = {
    3: ("🔥🔥🔥", "Immanquable", "Regarde le match en entier"),
    2: ("🔥🔥", "Très bon match", "Match complet ou long résumé"),
    1: ("🔥", "Bon match", "Le résumé vaut le coup"),
    0: ("😐", "Sans plus", "Le résumé suffit"),
    -1: ("💤", "Sans suspense", "Résumé si c'est ton équipe"),
    -2: ("⛔", "À fuir", "Passe ton chemin"),
}
WATCH_CUTS = ((58, 3), (40, 2), (26, 1), (12, 0))  # note globale -> niveau ; en dessous : 💤, ou ⛔ si plié tôt


def _clamp(x):
    return max(0.0, min(1.0, x))


def interest_parts(g, summ, idx=None):
    """Note d'intérêt d'un match terminé, faite de nombreux ingrédients qui se compensent, pour qu'une même note puisse
    venir de scénarios très différents (fin serrée, prolongation, remontée, tir au buzzer, perf XXL, festival offensif,
    enjeu...). Rien ici ne dépend du camp du vainqueur. Renvoie (ingrédients {nom: points}, pénalité « plié tôt »,
    raisons lisibles, à n'afficher qu'une fois le score révélé)."""
    pts, max_h, max_a, changes = flow(summ)
    h, a = g["home"]["score"], g["away"]["score"]
    end = max(48.0, pts[-1][0])
    n_ot = max(0, max(len(g["home"]["lines"]), len(g["away"]["lines"])) - 4)

    def diff_at(t):
        d = 0
        for m, v in pts:
            if m > t:
                break
            d = v
        return d

    grid = [i / 2 for i in range(int(end * 2) + 1)]
    series = [diff_at(t) for t in grid]
    reg = series[: 48 * 2 + 1]
    parts, why = {}, []

    # Suspense en fin de temps réglementaire
    last5 = [abs(d) for t, d in zip(grid, reg) if t >= 43]
    avg5 = sum(last5) / len(last5) if last5 else 99
    parts["fin"] = 18 * _clamp((10 - avg5) / 10) + 16 * _clamp((6 - abs(reg[-1])) / 6)
    if parts["fin"] >= 15:
        why.append("fin de match serrée")
    # Prolongation(s)
    parts["prolong"] = min(24, 12 + 6 * (n_ot - 1)) if n_ot else 0
    if n_ot:
        why.append("prolongation" if n_ot == 1 else f"{n_ot} prolongations")
    # Retournements : plus gros retard rattrapé (même par le perdant), et retard effacé par le vainqueur
    swing, lo, hi = 0, 0, 0
    for d in series:
        lo, hi = min(lo, d), max(hi, d)
        swing = max(swing, -lo - max(0, -d), hi - max(0, d))
    deficit = max_a if h > a else max_h
    parts["retournement"] = 16 * _clamp((swing - 12) / 20) + 10 * _clamp((deficit - 8) / 17)
    if deficit >= 12:
        why.append(f"retard de {deficit} points effacé")
    elif swing >= 18:
        why.append("gros retournement de situation")
    # Changements de leader et équilibre général
    parts["leader"] = 10 * _clamp(changes / 20)
    mean_gap = sum(abs(d) for d in series) / len(series)
    parts["equilibre"] = 8 * _clamp((14 - mean_gap) / 10)
    if changes >= 12:
        why.append(f"{changes} changements de leader")
    # Fin dramatique : le vainqueur passe devant pour de bon dans les 30 dernières secondes (ou au buzzer)
    final_sign = (h > a) - (h < a)
    took = 0.0
    for t, d in zip(grid, series):
        if (d > 0) - (d < 0) != final_sign:
            took = t + 0.5
    took = min(took, end)
    period_end = 48.0 if end <= 48 else end
    parts["dernier_tir"] = 14 if took >= period_end - 0.1 else 9 if took >= period_end - 0.5 else 0
    for p in summ.get("plays") or []:  # plus précis avec les actions : panier qui donne l'avance dans les 5 dernières secondes
        period, clock, aw, hm, scoring, _, _ = p
        if scoring and period >= 4 and _clock_secs(clock) <= 5 and elapsed_min(period, clock) >= period_end - 0.1:
            if (int(hm) > int(aw)) - (int(hm) < int(aw)) == final_sign and final_sign != 0:
                parts["dernier_tir"] = 14
    if parts["dernier_tir"]:
        why.append("panier décisif dans les dernières secondes")
    # Grosse performance individuelle
    best_gs, top_pts, triple, best_name = 0.0, 0, False, ""
    threes, dunks = 0, 0
    for rows in (summ.get("box") or {}).values():
        for r in rows:
            if r["dnp"] or not r["stats"]:
                continue
            gs = game_score(r["stats"])
            if gs > best_gs:
                best_gs, best_name = gs, r["name"]
            top_pts = max(top_pts, _num(r["stats"], "PTS"))
            triple = triple or sum(1 for k in ("PTS", "REB", "AST", "STL", "BLK") if _num(r["stats"], k) >= 10) >= 3
            try:
                threes += int(str(r["stats"].get("3PT", "0-0")).split("-")[0])
            except ValueError:
                pass
    parts["perf"] = min(22, 12 * _clamp((best_gs - 30) / 25) + (10 if top_pts >= 50 else 3 if top_pts >= 40 else 0) + (3 if triple else 0))
    if parts["perf"] >= 8:
        why.append(f"grosse perf de {best_name}")
    # Spectacle : festival offensif, adresse à 3 points, dunks
    dunks = sum(1 for p in summ.get("plays") or [] if p[4] and re.search(r"\b(dunk|alley oop)\b", p[5] or "", re.I))
    total = (h or 0) + (a or 0)
    parts["spectacle"] = 4 * _clamp((threes - 28) / 16) + 3 * _clamp((total - 215) / 50) + 3 * _clamp((dunks - 8) / 14)
    if parts["spectacle"] >= 5:
        why.append("festival offensif")
    # Enjeu : play-offs, deux équipes en forme
    stake = 6 if g.get("season_type") == 3 else 0
    if idx:
        good = 0
        for side in ("home", "away"):
            f = team_form(idx, g[side]["id"], g["day"], g["season"])
            if f["n"] >= 5 and f["w"] / f["n"] >= 0.6:
                good += 1
        stake += 3 if good == 2 else 0
    parts["enjeu"] = stake
    # Match plié tôt : gagné de 15 ou plus, et à partir de quand l'écart n'est plus jamais redescendu sous 12 points
    decided = None
    if abs(series[-1]) >= 15:
        sign = (series[-1] > 0) - (series[-1] < 0)
        decided = end
        for t, d in reversed(list(zip(grid, series))):
            if d * sign >= 12:
                decided = t
            else:
                break
    penalty = 20 * _clamp((40 - decided) / 28) if decided is not None else 0.0
    return parts, penalty, why


def watch_score(g, summ, idx=None):
    """Intérêt d'un match terminé, sans dire qui a gagné : (niveau -2 à 3, raisons à montrer APRÈS le score, note).
    None si on ne sait pas encore."""
    if not summ or g["state"] != "post" or not g["completed"] or g["home"]["score"] is None:
        return None
    if len(flow(summ)[0]) < 20:
        return None
    parts, penalty, why = interest_parts(g, summ, idx)
    note = sum(parts.values()) - penalty
    level = next((lv for cut, lv in WATCH_CUTS if note >= cut), None)
    if level is None:  # ⛔ seulement si le match a été plié tôt ET que rien ne le sauve (perf, spectacle)
        level = -2 if penalty >= 12 and parts["perf"] < 8 and parts["spectacle"] < 5 else -1
    return level, why, round(note, 1)


def hype(g, idx, pre):
    """Attrait d'un match à venir : bonnes équipes et match serré selon les bookmakers."""
    total = 0.0
    for side in ("home", "away"):
        f = team_form(idx, g[side]["id"], g["day"], g["season"])
        if f["n"] >= 5:
            total += f["w"] / f["n"]
        elif f["prev_w"] + f["prev_l"]:
            total += f["prev_w"] / (f["prev_w"] + f["prev_l"])
        else:
            total += 0.5
    m = re.search(r"-([\d.]+)", (pre or {}).get("line") or "")
    total += 1 - min(float(m.group(1)), 15) / 15 if m else 0.5
    return total


# =========================================================================
# VIDÉOS : DURÉES (API YouTube, si une clé est donnée)
# =========================================================================
@st.cache_data(ttl=86400, show_spinner=False, max_entries=200)
def video_durations(ids):
    key = str(_secret("youtube", "api_key", ""))
    if not key or not ids:
        return {}
    out = {}
    d = get_json("https://www.googleapis.com/youtube/v3/videos",
                 {"part": "contentDetails", "id": ",".join(ids[:50]), "key": key}) or {}
    for item in d.get("items") or []:
        m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", (item.get("contentDetails") or {}).get("duration", ""))
        if m:
            secs = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0)
            out[item["id"]] = max(1, round(secs / 60))
    return out


def dur(v, durs):
    m = (durs.get(v["id"]) or v.get("mins")) if v else None
    return f"{m} min" if m else ""


# =========================================================================
# AFFICHAGE
# =========================================================================
CSS = """
<style>
:root {
  --bg:#0b0f17; --card:#131a26; --card2:#18212f; --line:#243044; --text:#e8ecf3; --muted:#8a94a8;
  --accent:#F58426; --accent-soft:rgba(245,132,38,.14); --green:#22c55e; --red:#ef4444; --gold:#fbbf24;
}
.stApp {background: radial-gradient(1200px 500px at 50% -200px, #1a2333 0%, var(--bg) 60%) fixed;}
.block-container {padding-top: 3.6rem; padding-bottom: 4rem; max-width: 860px;}
header[data-testid="stHeader"] {background: transparent;}
h1, h2, h3 {letter-spacing:-.01em}
.bb-brand {font-size:1.35rem; font-weight:800; letter-spacing:-.02em; line-height:1.1;}
.bb-brand span {color:var(--accent);}
.bb-tag {color:var(--muted); font-size:.8rem;}

/* Bandeau de la nuit */
.night {background:linear-gradient(135deg, #182236 0%, #121a28 100%); border:1px solid var(--line); border-radius:18px; padding:16px 18px 14px; margin:.4rem 0 1rem;}
.n-kicker {color:var(--accent); font-weight:700; font-size:.78rem; text-transform:uppercase; letter-spacing:.08em;}
.n-title {font-size:1.35rem; font-weight:800; margin:.1rem 0 .1rem; line-height:1.25;}
.n-sub {color:var(--muted); font-size:.82rem;}
.n-media {display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px;}
.media {display:flex; align-items:center; gap:11px; padding:10px 12px; border-radius:13px; border:1px solid var(--line);
        background:var(--card2); color:var(--text)!important; text-decoration:none!important; min-height:58px;}
a.media:hover {border-color:var(--accent); background:#1d283a;}
.media .ic {font-size:1.45rem; width:2rem; text-align:center;}
.media b {display:block; font-size:.92rem; line-height:1.25;}
.media small {display:block; color:var(--muted); font-size:.76rem; line-height:1.3;}
.media .go {margin-left:auto; width:34px; height:34px; border-radius:50%; background:var(--accent); color:#111; display:flex;
            align-items:center; justify-content:center; font-size:.85rem; flex:none;}
.media.off {opacity:.8; border-style:dashed;}
.media.off .go {background:transparent; border:1px solid var(--line); color:var(--muted);}
.n-chips {margin-top:12px; display:flex; flex-wrap:wrap; gap:6px; align-items:center;}
.n-chips .lab {color:var(--muted); font-size:.78rem; margin-right:2px;}
.chip {font-size:.78rem; padding:3px 9px; border-radius:999px; background:var(--card2); border:1px solid var(--line); color:var(--text)!important; text-decoration:none!important; white-space:nowrap;}
a.chip:hover {border-color:var(--accent);}

/* Carte d'un match */
.g {background:var(--card); border:1px solid var(--line); border-radius:18px; padding:12px 16px 12px; margin:0 0 12px; scroll-margin-top:70px;}
.g.fav {border-color:rgba(251,191,36,.55); box-shadow:0 0 0 1px rgba(251,191,36,.15) inset;}
.g .tg {display:none;}
.g-top {display:flex; justify-content:space-between; gap:8px; align-items:center; font-size:.76rem; color:var(--muted); min-height:1.2rem;}
.g-top .tags {display:flex; gap:5px; flex-wrap:wrap; align-items:center;}
.tag {padding:1px 8px; border-radius:999px; background:var(--card2); border:1px solid var(--line); color:var(--text); font-size:.72rem; white-space:nowrap;}
.tag.hot {background:rgba(245,132,38,.16); border-color:rgba(245,132,38,.45); color:#ffc08c; font-weight:700;}
.tag.star {background:rgba(251,191,36,.12); border-color:rgba(251,191,36,.4); color:var(--gold); font-weight:700;}
.tag.live {background:rgba(239,68,68,.15); border-color:rgba(239,68,68,.5); color:#ff8a8a; font-weight:700;}
.tag.cold {opacity:.75;}
.tag.advice {background:transparent; border-color:transparent; color:var(--muted); padding-left:2px;}
.g-match {display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:8px; margin:8px 0 4px;}
.tm {display:flex; align-items:center; gap:10px; min-width:0;}
.tm.home {flex-direction:row-reverse; text-align:right;}
.tm img {width:46px; height:46px; object-fit:contain; flex:none; filter:drop-shadow(0 2px 6px rgba(0,0,0,.35));}
.tm .nm {font-weight:800; font-size:1.12rem; line-height:1.15;}
.tm .mt {color:var(--muted); font-size:.74rem; line-height:1.3; margin-top:1px;}
.tm .where {font-size:.66rem; text-transform:uppercase; letter-spacing:.06em; color:#6b7590;}
.mid {text-align:center; min-width:92px;}
.mid .time {font-size:1.35rem; font-weight:800; font-variant-numeric:tabular-nums; line-height:1.1;}
.mid .sub {color:var(--muted); font-size:.7rem; margin-top:2px;}
.mid .at {color:#5d6780; font-size:.8rem; font-weight:700;}
.mid .hid {display:inline-block; font-size:1.05rem; font-weight:800; letter-spacing:.12em; color:#5d6780; padding:2px 10px; border-radius:9px; background:var(--card2); border:1px dashed var(--line);}
.mid .real {display:none; font-size:1.45rem; font-weight:800; font-variant-numeric:tabular-nums; white-space:nowrap;}
.mid .real .w {color:var(--text);} .mid .real .l {color:#6b7590;}
.mid .state {font-size:.68rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin-top:3px;}
.mid .state.live {color:#ff6b6b; font-weight:800;}
.pts {list-style:none; padding:0; margin:8px 0 2px;}
.pts li {font-size:.88rem; line-height:1.42; margin:3px 0; color:#d5dbe6; padding-left:1.55em; text-indent:-1.55em;}
.acts {display:flex; flex-wrap:wrap; gap:6px; margin-top:10px;}
.pill {display:inline-flex; align-items:center; gap:6px; font-size:.82rem; font-weight:600; padding:6px 12px; border-radius:999px;
       background:var(--card2); border:1px solid var(--line); color:var(--text)!important; text-decoration:none!important; cursor:pointer; user-select:none; line-height:1.2;}
.pill:hover {border-color:var(--accent);}
.pill.main {background:var(--accent); border-color:var(--accent); color:#16100a!important;}
.pill.main:hover {filter:brightness(1.08);}
.pill.fr {background:#16233d; border-color:#2a3f66;}
.frf {display:inline-block; width:17px; height:12px; border-radius:2px; background:linear-gradient(90deg,#1f4bd8 0 33.3%,#f4f4f4 33.3% 66.6%,#e3263b 66.6%); box-shadow:0 0 0 1px rgba(0,0,0,.25); vertical-align:-1px;}
.frf.big {width:26px; height:18px; border-radius:3px;}
.pill.ghost {color:var(--muted)!important; border-style:dashed;}
.pill small {opacity:.7; font-weight:500;}
.pill .on {display:none;}
.panel {display:none; margin-top:10px; padding-top:10px; border-top:1px solid var(--line);}
.tg-s:checked ~ .g-match .hid {display:none;}
.tg-s:checked ~ .g-match .real {display:block;}
.tg-s:checked ~ .panel-s, .tg-f:checked ~ .panel-f {display:block;}
.tg-s:checked ~ .acts .pill-s, .tg-f:checked ~ .acts .pill-f {border-color:var(--accent); background:var(--accent-soft);}
.tg-s:checked ~ .acts .pill-s .on, .tg-f:checked ~ .acts .pill-f .on {display:inline;}
.tg-s:checked ~ .acts .pill-s .off, .tg-f:checked ~ .acts .pill-f .off {display:none;}
.sec {font-size:.72rem; font-weight:800; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin:12px 0 6px;}
.sec:first-child {margin-top:0;}
.q {border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:.85rem; margin:2px 0 4px;}
.q td, .q th {padding:3px 10px; text-align:center; border-bottom:1px solid var(--line);}
.q th {color:var(--muted); font-weight:600; font-size:.72rem;}
.q td:first-child, .q th:first-child {text-align:left; padding-left:0;}
.q td.t {font-weight:800;}
.worm {width:100%; height:auto; display:block; margin:2px 0;}
.wcap {color:var(--muted); font-size:.74rem;}
details.more {margin-top:8px; border:1px solid var(--line); border-radius:12px; background:var(--card2);}
details.more > summary {cursor:pointer; padding:8px 12px; font-size:.84rem; font-weight:700; list-style:none;}
details.more > summary::-webkit-details-marker {display:none;}
details.more > summary::before {content:"▸ "; color:var(--muted);}
details.more[open] > summary::before {content:"▾ ";}
details.more .in {padding:0 12px 10px; overflow-x:auto;}
.box {border-collapse:collapse; font-size:.78rem; font-variant-numeric:tabular-nums; width:100%; min-width:520px;}
.box th {color:var(--muted); font-weight:600; text-align:right; padding:4px 5px; border-bottom:1px solid var(--line); font-size:.7rem;}
.box td {text-align:right; padding:3px 5px; border-bottom:1px solid rgba(36,48,68,.6);}
.box td:first-child, .box th:first-child {text-align:left;}
.box tr.st td:first-child {font-weight:700;}
.box td.hi {color:var(--accent); font-weight:800;}
.box caption {text-align:left; font-weight:800; padding:6px 0 4px; font-size:.85rem;}
.dnp {color:var(--muted); font-size:.74rem; margin:4px 0 8px;}
.plays {font-size:.8rem; line-height:1.5;}
.plays .qh {font-weight:800; color:var(--muted); margin:8px 0 2px; font-size:.72rem; letter-spacing:.06em;}
.plays div.p {display:grid; grid-template-columns:3.2rem 2.6rem 1fr auto; gap:6px; border-bottom:1px solid rgba(36,48,68,.5); padding:2px 0;}
.plays .c {color:var(--muted); font-variant-numeric:tabular-nums;}
.plays .s {font-variant-numeric:tabular-nums; font-weight:700;}
.form {width:100%; border-collapse:collapse; font-size:.8rem;}
.form td {padding:4px 4px; border-bottom:1px solid var(--line); white-space:nowrap;}
.form .hd td {padding-top:8px; font-size:.84rem; white-space:normal;}
.form .w {color:var(--green); font-weight:800;} .form .l {color:var(--red); font-weight:800;}
.form .old {opacity:.4;}
.form-wrap {overflow-x:auto;}
.note {color:var(--muted); font-size:.74rem; margin:4px 0;}
.ai {color:var(--muted); font-size:.72rem;}
div[data-testid="stPopover"] button {padding:.25rem .7rem; min-height:2.2rem;}
div[data-testid="stSegmentedControl"] button p {font-size:.85rem;}
@media (max-width: 640px) {
  .block-container {padding-left:.8rem; padding-right:.8rem; padding-top:3.2rem;}
  .night {padding:13px 13px 12px; border-radius:16px;}
  .n-title {font-size:1.12rem;}
  .n-media {grid-template-columns:1fr;}
  .g {padding:11px 12px; border-radius:16px;}
  .tm {gap:7px; flex-direction:column; align-items:flex-start; text-align:left;}
  .tm.home {flex-direction:column; align-items:flex-end; text-align:right;}
  .tm img {width:38px; height:38px;}
  .tm .nm {font-size:1rem;}
  .mid {min-width:74px;}
  .g-top .vn {display:none;}
  .g-top .rt {white-space:nowrap;}
  .mid .time {font-size:1.15rem;}
  .mid .real {font-size:1.2rem;}
  .pill {font-size:.78rem; padding:6px 10px;}
}
/* Comparatif « Forme & duels » */
.cmp {background:var(--card2); border:1px solid var(--line); border-radius:14px; padding:10px 12px;}
.cmp-h {display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:8px; padding-bottom:8px; border-bottom:1px solid var(--line);}
.cmp-h > div {display:flex; align-items:center; gap:8px; font-size:.95rem;}
.cmp-h .r {justify-content:flex-end;}
.cmp-h img {width:34px; height:34px;}
.cmp-h .vs {color:var(--muted); font-size:.68rem; text-transform:uppercase; letter-spacing:.08em; justify-content:center;}
.cmp-r {display:grid; grid-template-columns:1fr minmax(120px, auto) 1fr; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid rgba(36,48,68,.6); font-size:.88rem; font-variant-numeric:tabular-nums;}
.cmp-r:last-child {border-bottom:none;}
.cmp-r .lab {color:var(--muted); font-size:.74rem; text-align:center;}
.cmp-r .r {text-align:right;}
.cmp-r .up {color:#fff; font-weight:800;}
.cmp-r .up::after {content:" ●"; color:var(--accent); font-size:.6rem; vertical-align:2px;}
.cmp-r .r.up::after {content:"";}
.cmp-r .r.up::before {content:"● "; color:var(--accent); font-size:.6rem; vertical-align:2px;}
.cmp .w {color:var(--green); font-weight:700;} .cmp .l {color:var(--red); font-weight:700;}
.dts {display:inline-flex; gap:4px;}
.dt {width:20px; height:20px; border-radius:6px; display:inline-flex; align-items:center; justify-content:center; font-size:.66rem; font-weight:800; color:#0b0f17; cursor:default;}
.cmp .dt {color:#0b0f17;} .dt.w {background:var(--green);} .dt.l {background:var(--red);} .dt.old {opacity:.35;}
.h2h-sum {display:flex; align-items:center; gap:10px; font-size:1.3rem; margin:2px 0 6px; flex-wrap:wrap;}
.h2h-sum img {width:26px; height:26px;}
.h2h-sum small {color:var(--muted); font-size:.75rem;}
.h2h-r {display:grid; grid-template-columns:4.4rem 1fr auto 1fr 4.5rem; align-items:center; gap:6px; padding:4px 0; font-size:.85rem; border-bottom:1px solid rgba(36,48,68,.6); font-variant-numeric:tabular-nums;}
.h2h-r img {width:18px; height:18px; vertical-align:-4px;}
.h2h-r .d {color:var(--muted); font-size:.72rem;}
.h2h-r span:nth-child(2) {text-align:right;}
.h2h-r .sep {color:#5d6780; font-size:.75rem;}
.h2h-r .b {font-weight:800;} .h2h-r .f {color:#6b7590;}
/* Carte de tirs */
label.pl {cursor:pointer; border-bottom:1px dotted var(--accent);}
label.pl span {font-size:.7rem;}
label.pl:hover {color:var(--accent);}
.pm {display:none; position:fixed; inset:0; z-index:1000000; align-items:center; justify-content:center; padding:14px;}
.tgp:checked + .pm {display:flex;}
.pm-bg {position:absolute; inset:0; background:rgba(4,7,12,.78); cursor:pointer;}
.pm-box {position:relative; background:var(--card); border:1px solid var(--line); border-radius:18px; width:100%; max-width:440px; max-height:92vh; overflow:auto; padding:14px; box-shadow:0 20px 60px rgba(0,0,0,.5);}
.pm-head {display:flex; align-items:center; gap:10px; margin-bottom:10px;}
.pm-head .ph {width:58px; height:44px; object-fit:cover; object-position:top; border-radius:10px; background:var(--card2);}
.pm-name {font-weight:800; font-size:1.05rem;}
.pm-sub {color:var(--muted); font-size:.76rem;}
.pm-sub img {width:16px; height:16px; vertical-align:-3px;}
.pm-x {margin-left:auto; cursor:pointer; width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:var(--card2); border:1px solid var(--line); flex:none;}
.court {width:100%; height:auto; display:block; border-radius:12px;}
.pm-leg {display:flex; flex-wrap:wrap; gap:12px; font-size:.72rem; color:var(--muted); margin:8px 0;}
.pm-leg i {display:inline-block; vertical-align:-2px; font-style:normal;}
.pm-leg .dot {width:10px; height:10px; border-radius:50%; background:var(--accent);}
.pm-leg .cross {color:#9aa4b8; font-weight:800;}
.pm-leg .sq {width:12px; height:12px; border-radius:3px;}
.pm-leg .sq.hot {background:rgba(239,68,68,.6);} .pm-leg .sq.cold {background:rgba(59,130,246,.6);} .pm-leg .sq.avg {background:rgba(234,179,8,.4);}
.court .zl {font:800 15px 'Source Sans Pro', sans-serif; fill:#fff; text-anchor:middle; dominant-baseline:middle; paint-order:stroke; stroke:#0b0f17; stroke-width:4px;}
.zones {display:grid; grid-template-columns:repeat(auto-fit, minmax(90px, 1fr)); gap:6px;}
.z {background:var(--card2); border:1px solid var(--line); border-radius:10px; padding:6px 8px; text-align:center;}
.z b {display:block; font-size:1rem;} .z span {display:block; font-size:.68rem; color:var(--muted);} .z small {font-size:.72rem;}
.z.hot {border-color:rgba(239,68,68,.6);} .z.hot small {color:#ff8a8a; font-weight:700;}
.z.cold {border-color:rgba(59,130,246,.6);} .z.cold small {color:#8ab4ff; font-weight:700;}
@media (max-width: 640px) {
  .cmp-r {grid-template-columns:1fr minmax(92px, auto) 1fr; font-size:.82rem;}
  .cmp-h > div {font-size:.85rem;}
  .h2h-r {grid-template-columns:3.6rem 1fr auto 1fr;}
  .h2h-r span:last-child {display:none;}
  .dt {width:17px; height:17px; font-size:.6rem;}
}
</style>
"""


def user_zone():
    q = st.query_params.get("tz")
    if q in ZONES:
        return q
    tz = ""
    try:
        tz = st.context.timezone or ""
    except Exception:
        pass
    return "Montréal" if tz.startswith("America/") else "Paris"


def rel_label(day, zone, today):
    return {0: ("Cette nuit", "Ce soir"), -1: ("La nuit dernière", "Hier soir"),
            1: ("La nuit prochaine", "Demain soir")}.get((day - today).days, (None, None))[0 if zone == "Paris" else 1]


def night_title(day, zone):
    """« Nuit du mardi 20 au mercredi 21 octobre » à Paris, « Soirée du mardi 20 octobre » à Montréal."""
    if zone != "Paris":
        return "Soirée du " + fr_long(day)
    nxt = day + timedelta(days=1)
    if day.month == nxt.month:
        return f"Nuit du {JOURS[day.weekday()]} {day.day} au {fr_long(nxt)}"
    return f"Nuit du {fr_long(day)} au {fr_long(nxt)}"


def pill_label(day, zone, today):
    rel = {0: ("Cette nuit", "Ce soir"), -1: ("Nuit dernière", "Hier soir"), 1: ("Nuit prochaine", "Demain")}.get((day - today).days)
    if rel:
        return rel[0 if zone == "Paris" else 1]
    if zone == "Paris":
        return f"{JOURS[day.weekday()][:3]}. {day.day}→{(day + timedelta(days=1)).day}"
    return fr_short(day)


def default_day(days, today):
    """La dernière nuit où des matchs ont commencé (celle qu'on vient de vivre), sinon la prochaine."""
    if any(g["state"] != "pre" for g in day_games(today)):
        return today
    before = [d for d in days if d < today]
    return before[-1] if before else (days[0] if days else today)


def _lum(hexcolor):
    try:
        r, g, b = (int(hexcolor[i:i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    except (ValueError, IndexError):
        return 0.5


def team_color(tid):
    t = team(tid)
    for c in (t.get("color"), t.get("alt")):
        if c and 0.12 < _lum(c) < 0.92:
            return c
    return "#9aa4b8"


def logo(tid, size=46):
    url = team(tid)["logo"]
    return f'<img src="{esc(url)}" width="{size}" height="{size}" alt="" loading="lazy">' if url else ""


def reason_fr(reason):
    """Raison d'absence d'ESPN (« INJURY/ILLNESS - LEFT KNEE; SPRAIN ») -> mot anglais reconnu par INJURY_FR, ou None."""
    r = norm(reason)
    if not r or "coach" in r:
        return None
    for key in sorted(INJURY_FR, key=len, reverse=True):
        if re.search(r"\b" + re.escape(key) + r"\b", r):
            return key
    return "undisclosed" if "injur" in r or "illness" in r else None


def pre_info(g, summ):
    """Ce qu'on savait avant le match. Après coup : ce qui a été gardé, sinon la cote (figée avant le match) et les absents
    de la feuille de match (joueurs qui n'ont pas joué pour blessure)."""
    if g["state"] == "pre":
        return summ
    kept = disk_get(f"pre_{g['id']}.json")
    if kept or not summ:
        return kept
    injuries = {}
    for tid, rows in (summ.get("box") or {}).items():
        for r in rows:
            what = reason_fr(r["reason"]) if r["dnp"] else None
            if what:
                injuries.setdefault(tid, []).append({"name": r["name"], "status": "Out", "what": what})
    return {"line": summ.get("line"), "injuries": injuries}


def quarters_html(g):
    n = max(len(g["home"]["lines"]), len(g["away"]["lines"]), 4)
    head = "".join(f"<th>{'Q' + str(i + 1) if i < 4 else 'P' + str(i - 3)}</th>" for i in range(n))
    rows = []
    for side in ("away", "home"):
        s = g[side]
        cells = "".join(f"<td>{v}</td>" for v in s["lines"]) + "<td></td>" * (n - len(s["lines"]))
        rows.append(f"<tr><td>{logo(s['id'], 18)} {esc(team(s['id'])['abbr'])}</td>{cells}<td class='t'>{s['score'] if s['score'] is not None else ''}</td></tr>")
    return f"<table class='q'><tr><th></th>{head}<th>Total</th></tr>{''.join(rows)}</table>"


def worm_svg(g, summ):
    """Écart au fil du match : au-dessus, l'équipe à domicile mène ; en dessous, les visiteurs."""
    pts, max_h, max_a, changes = flow(summ)
    if len(pts) < 5:
        return ""
    total = max(48.0, pts[-1][0])
    W, H = 600, 130
    mid = H / 2
    cap = max(10, max_h, max_a)
    sx = lambda m: m / total * W
    sy = lambda d: mid - d / cap * (mid - 10)
    path = f"M0,{mid:.1f} " + " ".join(f"L{sx(m):.1f},{sy(d):.1f}" for m, d in pts) + f" L{sx(pts[-1][0]):.1f},{mid:.1f} Z"
    line = " ".join(f"{'M' if i == 0 else 'L'}{sx(m):.1f},{sy(d):.1f}" for i, (m, d) in enumerate(pts))
    gid = g["id"]
    ch, ca = team_color(g["home"]["id"]), team_color(g["away"]["id"])
    n_ot = max(0, int(round((total - 48) / 5)))
    marks = [12, 24, 36] + [48 + 5 * k for k in range(n_ot)]
    grid = "".join(f'<line x1="{sx(m):.1f}" y1="4" x2="{sx(m):.1f}" y2="{H - 4}" stroke="#2a364b" stroke-dasharray="3 4"/>' for m in marks if m < total)
    labels = "".join(
        f'<text x="{sx(a + (b - a) / 2):.1f}" y="{H - 3}" fill="#5d6780" font-size="10" text-anchor="middle">{lab}</text>'
        for a, b, lab in [(0, 12, "Q1"), (12, 24, "Q2"), (24, 36, "Q3"), (36, 48, "Q4")] + [(48 + 5 * k, 53 + 5 * k, f"P{k + 1}") for k in range(n_ot)])
    th, ta = team(g["home"]["id"]), team(g["away"]["id"])
    return (
        f'<svg class="worm" viewBox="0 0 {W} {H}" preserveAspectRatio="none" role="img" aria-label="Écart au fil du match">'
        f'<defs><clipPath id="up{gid}"><rect x="0" y="0" width="{W}" height="{mid}"/></clipPath>'
        f'<clipPath id="dn{gid}"><rect x="0" y="{mid}" width="{W}" height="{mid}"/></clipPath></defs>'
        f'{grid}<line x1="0" y1="{mid}" x2="{W}" y2="{mid}" stroke="#3a475e"/>'
        f'<path d="{path}" fill="{ch}" fill-opacity=".55" clip-path="url(#up{gid})"/>'
        f'<path d="{path}" fill="{ca}" fill-opacity=".55" clip-path="url(#dn{gid})"/>'
        f'<path d="{line}" fill="none" stroke="#e8ecf3" stroke-width="1.2" stroke-opacity=".8"/>'
        f'<text x="4" y="14" fill="{ch}" font-size="11" font-weight="700">▲ {esc(th["abbr"])} mène</text>'
        f'<text x="4" y="{H - 16}" fill="{ca}" font-size="11" font-weight="700">▼ {esc(ta["abbr"])} mène</text>'
        f'{labels}</svg>'
        f'<div class="wcap">Plus grosse avance : {esc(th["name"])} +{max_h}, {esc(ta["name"])} +{max_a} · {changes} changements de leader</div>'
    )


def box_html(g, summ):
    """Stats des joueurs ; un clic sur un joueur ouvre sa carte de tirs (fenêtre en CSS, sans rechargement)."""
    cols = [("MIN", "MIN"), ("PTS", "PTS"), ("REB", "RBD"), ("AST", "PD"), ("FG", "TIRS"), ("3PT", "3 PTS"), ("FT", "LF"),
            ("STL", "INT"), ("BLK", "CTR"), ("TO", "BP"), ("+/-", "+/-")]
    shots = defaultdict(list)
    for aid, tid, x, y, made, three in summ.get("shots") or []:
        shots[aid].append((x, y, made, three))
    out, modals = [], []
    for side in ("away", "home"):
        tid = g[side]["id"]
        rows = (summ.get("box") or {}).get(tid) or []
        played = [r for r in rows if not r["dnp"]]
        if not played:
            continue
        top = max(_num(r["stats"], "PTS") for r in played)
        head = "".join(f"<th>{lab}</th>" for _, lab in cols)
        body = []
        for r in played:
            cells = []
            for k, _ in cols:
                v = r["stats"].get(k, "")
                hi = " class='hi'" if k == "PTS" and _num(r["stats"], "PTS") == top and top > 0 else ""
                cells.append(f"<td{hi}>{esc(v)}</td>")
            name = esc(r["short"] or r["name"])
            mid = f"p{g['id']}_{r.get('id')}"
            if r.get("id") and shots.get(r["id"]):
                name = f"<label for='{mid}' class='pl'>{name} <span>🎯</span></label>"
                modals.append(f"<input type='checkbox' class='tg tgp' id='{mid}'>" + shot_modal(g, r, tid, shots[r["id"]], mid))
            body.append(f"<tr class='{'st' if r['starter'] else ''}'><td>{name}</td>{''.join(cells)}</tr>")
        dnp = [f"{r['short'] or r['name']}" + (f" ({INJURY_FR.get(reason_fr(r['reason']), '')})" if reason_fr(r["reason"]) else "")
               for r in rows if r["dnp"]]
        out.append(f"<table class='box'><caption>{logo(tid, 18)} {esc(team(tid)['name'])}</caption><tr><th>Joueur</th>{head}</tr>{''.join(body)}</table>"
                   + (f"<div class='dnp'>N'ont pas joué : {esc(', '.join(dnp))}</div>" if dnp else ""))
    if not out:
        return "<div class='note'>Feuille de match pas encore disponible.</div>"
    return ("<div class='note'>🎯 Touche un joueur pour voir sa carte de tirs.</div>" + "".join(out)
            + "".join(modals))


# Zones de tir à la façon des « hot zones » de la NBA : 14 zones (pieds ; panier en (25, 0), coordonnées d'ESPN).
# Angle mesuré depuis le panier : 0° = dans l'axe, négatif d'un côté du terrain, positif de l'autre.
# (clé, famille, bornes d'angle, moyenne NBA de réussite)
HOT_ZONES = [
    ("rim", "rim", None, 0.64),
    ("sm_l", "mid", (-125, -30), 0.43), ("sm_c", "mid", (-30, 30), 0.43), ("sm_r", "mid", (30, 125), 0.43),
    ("lm_bl", "mid", (-125, -60), 0.41), ("lm_l", "mid", (-60, -20), 0.41), ("lm_c", "mid", (-20, 20), 0.41),
    ("lm_r", "mid", (20, 60), 0.41), ("lm_br", "mid", (60, 125), 0.41),
    ("c3_l", "three", None, 0.39), ("w3_l", "three", (-125, -25), 0.355), ("t3", "three", (-25, 25), 0.355),
    ("w3_r", "three", (25, 125), 0.355), ("c3_r", "three", None, 0.39),
]
ZONE_AVG = {k: avg for k, _, _, avg in HOT_ZONES}
FAMILIES = [("rim", "Près du cercle"), ("mid", "Mi-distance"), ("three", "À 3 points")]


def shot_zone(x, y, three):
    ang = math.degrees(math.atan2(x - 25, y))
    ang = max(-124.9, min(124.9, ang))
    if three:
        if y <= 9 and abs(x - 25) >= 20:
            return "c3_l" if x < 25 else "c3_r"
        return "w3_l" if ang < -25 else "t3" if ang <= 25 else "w3_r"
    dist = math.hypot(x - 25, y)
    if dist <= 8:
        return "rim"
    if dist <= 16:
        return "sm_l" if ang < -30 else "sm_c" if ang <= 30 else "sm_r"
    for key, _, (a1, a2), _ in HOT_ZONES[4:9]:
        if a1 <= ang <= a2:
            return key
    return "lm_c"


def zone_color(made, att, avg):
    """Rouge = zone chaude (au-dessus de la moyenne NBA de la zone), bleu = froide ; plus franc avec plus de tirs."""
    if not att:
        return "rgba(120,130,150,.06)"
    diff = made / att - avg
    strength = min(1.0, abs(diff) / 0.2 + 0.2) * min(1.0, 0.45 + 0.15 * att)
    alpha = 0.12 + 0.5 * strength
    if abs(diff) < 0.04:
        return f"rgba(234,179,8,{0.10 + 0.25 * min(1.0, 0.45 + 0.15 * att):.2f})"  # dans la moyenne : jaune pâle
    return f"rgba(239,68,68,{alpha:.2f})" if diff > 0 else f"rgba(59,130,246,{alpha:.2f})"


def court_svg(shots, uid):
    """Demi-terrain (10 px par pied, ligne de fond en haut) : 14 zones colorées selon la réussite du joueur,
    avec « réussis/tentés » dans chaque zone où il a tiré, puis chaque tir (● réussi, ✕ raté)."""
    BY = 52.5  # panier à 5,25 pieds de la ligne de fond
    stats = {k: [0, 0] for k, _, _, _ in HOT_ZONES}
    for x, y, made, three in shots:
        z = shot_zone(x, y, three)
        stats[z][1] += 1
        stats[z][0] += 1 if made else 0

    def pt(r, a):
        return 250 + r * math.sin(math.radians(a)), BY + r * math.cos(math.radians(a))

    def sector(r1, r2, a1, a2):
        x1, y1 = pt(r2, a1)
        x2, y2 = pt(r2, a2)
        x3, y3 = pt(r1, a2)
        x4, y4 = pt(r1, a1)
        big = 1 if a2 - a1 > 180 else 0
        inner = f"A{r1},{r1} 0 {big} 1 {x4:.1f},{y4:.1f}" if r1 > 0 else f"L{x4:.1f},{y4:.1f}"
        return f"M{x1:.1f},{y1:.1f} A{r2},{r2} 0 {big} 0 {x2:.1f},{y2:.1f} L{x3:.1f},{y3:.1f} {inner} Z"

    yj, r3 = 140, 237.5  # fin des coins (14 pieds de la ligne de fond), rayon de la ligne à 3 points
    arc = f"M30,0 L30,{yj} A{r3},{r3} 0 0 0 470,{yj} L470,0"
    inside = f"{arc} Z"
    outside = f"M0,{yj} L30,{yj} A{r3},{r3} 0 0 0 470,{yj} L500,{yj} L500,470 L0,470 Z"
    col = {k: zone_color(stats[k][0], stats[k][1], ZONE_AVG[k]) for k in stats}
    cin, cout = f"in{uid}", f"out{uid}"
    shapes, labels = [], []

    def label(k, x, y):
        m, a = stats[k]
        if a:
            labels.append(f'<text x="{x:.0f}" y="{y:.0f}" class="zl">{m}/{a}</text>')

    for k, fam, ang, _ in HOT_ZONES:
        if k == "rim":
            shapes.append(f'<circle cx="250" cy="{BY}" r="80" fill="{col[k]}"/>')
            label(k, 250, BY + 48)
        elif k.startswith("sm_"):
            shapes.append(f'<path d="{sector(80, 160, *ang)}" fill="{col[k]}" clip-path="url(#{cin})"/>')
            mid_a = max(-75, min(75, (ang[0] + ang[1]) / 2))
            label(k, *pt(122, mid_a))
        elif k.startswith("lm_"):
            shapes.append(f'<path d="{sector(160, 420, *ang)}" fill="{col[k]}" clip-path="url(#{cin})"/>')
            mid_a = max(-80, min(80, (ang[0] + ang[1]) / 2))
            x, y = pt(200, mid_a)
            label(k, x, max(y, 24))
        elif k in ("c3_l", "c3_r"):
            x0 = 0 if k == "c3_l" else 470
            shapes.append(f'<rect x="{x0}" y="0" width="30" height="{yj}" fill="{col[k]}"/>')
            label(k, x0 + 15, 80)
        else:
            shapes.append(f'<path d="{sector(0, 700, *ang)}" fill="{col[k]}" clip-path="url(#{cout})"/>')
            mid_a = max(-50, min(50, (ang[0] + ang[1]) / 2))
            label(k, *pt(280, mid_a))

    # séparations entre les zones (traits fins)
    seps = []
    for a in (-30, 30):
        (x1, y1), (x2, y2) = pt(80, a), pt(160, a)
        seps.append(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}")
    for a in (-60, -20, 20, 60):
        (x1, y1), (x2, y2) = pt(160, a), pt(420, a)
        seps.append(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}")
    for a in (-25, 25):
        (x1, y1), (x2, y2) = pt(r3, a), pt(700, a)
        seps.append(f"M{x1:.1f},{y1:.1f} L{x2:.1f},{y2:.1f}")
    sep_paths = (f'<path d="{" ".join(seps[:6])}" stroke="#0b0f17" stroke-width="2" clip-path="url(#{cin})"/>'
                 f'<path d="{" ".join(seps[6:])}" stroke="#0b0f17" stroke-width="2" clip-path="url(#{cout})"/>')

    parts = [
        '<svg viewBox="0 0 500 470" class="court" role="img" aria-label="Carte de tirs">',
        f'<defs><clipPath id="{cin}"><path d="{inside}"/></clipPath><clipPath id="{cout}"><path d="{outside}"/></clipPath></defs>',
        '<rect x="0" y="0" width="500" height="470" fill="#141c2a"/>',
        *shapes,
        sep_paths,
        f'<circle cx="250" cy="{BY}" r="160" fill="none" stroke="#0b0f17" stroke-width="2" clip-path="url(#{cin})"/>',
        f'<circle cx="250" cy="{BY}" r="80" fill="none" stroke="#0b0f17" stroke-width="2"/>',
        '<g fill="none" stroke="#3a4760" stroke-width="2">',
        f'<path d="{arc}"/>',
        '<rect x="170" y="0" width="160" height="190" stroke-opacity=".6"/>',
        '<circle cx="250" cy="190" r="60" stroke-opacity=".6"/>',
        '<line x1="220" y1="40" x2="280" y2="40"/>',
        f'<circle cx="250" cy="{BY}" r="7.5" stroke="#F58426"/>',
        '<path d="M190,470 A60,60 0 0 1 310,470"/>',
        '<rect x="1" y="1" width="498" height="468"/>',
        '</g>',
    ]
    for x, y, made, three in shots:
        X, Y = x * 10, BY + y * 10
        if Y > 465:
            continue
        if made:
            parts.append(f'<circle cx="{X:.0f}" cy="{Y:.0f}" r="7" fill="#F58426" stroke="#0b0f17" stroke-width="2"/>')
        else:
            parts.append(f'<path d="M{X - 5:.0f},{Y - 5:.0f} L{X + 5:.0f},{Y + 5:.0f} M{X + 5:.0f},{Y - 5:.0f} L{X - 5:.0f},{Y + 5:.0f}" '
                         f'stroke="#c3cad8" stroke-width="2.4" stroke-linecap="round"/>')
    parts += labels
    parts.append("</svg>")
    fam = {f: [0, 0] for f, _ in FAMILIES}
    for k, f, _, _ in HOT_ZONES:
        fam[f][0] += stats[k][0]
        fam[f][1] += stats[k][1]
    return "".join(parts), fam


def shot_modal(g, r, tid, shots, mid):
    svg, stats = court_svg(shots, mid)
    made = sum(1 for s in shots if s[2])
    t = team(tid)
    zones = []
    for k, label in FAMILIES:
        avg = {"rim": 0.64, "mid": 0.42, "three": 0.36}[k]
        m, a = stats[k]
        if not a:
            continue
        pct = m / a
        cls = "hot" if pct >= avg + 0.05 else "cold" if pct <= avg - 0.05 else ""
        zones.append(f"<div class='z {cls}'><b>{m}/{a}</b><span>{label}</span><small>{round(pct * 100)} %</small></div>")
    photo = f"https://a.espncdn.com/i/headshots/nba/players/full/{r['id']}.png"
    return (f"<div class='pm'><label for='{mid}' class='pm-bg'></label><div class='pm-box'>"
            f"<div class='pm-head'><img class='ph' src='{photo}' alt='' loading='lazy' onerror=\"this.style.display='none'\">"
            f"<div><div class='pm-name'>{esc(r['name'])}</div><div class='pm-sub'>{logo(tid, 16)} {esc(t['name'])} · {esc(stat_line(r['stats']))}</div></div>"
            f"<label for='{mid}' class='pm-x'>✕</label></div>"
            f"{svg}"
            f"<div class='pm-leg'><span><i class='dot'></i> réussi</span><span><i class='cross'>✕</i> raté</span>"
            f"<span><i class='sq hot'></i> chaude</span><span><i class='sq avg'></i> dans la moyenne</span><span><i class='sq cold'></i> froide</span></div>"
            f"<div class='zones'>{''.join(zones)}</div>"
            f"<div class='note'>{made} tirs réussis sur {len(shots)} (hors lancers francs) · dans chaque zone : tirs réussis / tentés, couleur comparée à la moyenne NBA de la zone.</div>"
            f"</div></div>")


def tale(idx, tid, day, season, home):
    """Fiche d'une équipe avant le match : bilan, bilan à domicile ou à l'extérieur, points, série, repos, 5 derniers."""
    past = [m for m in idx.get(tid, []) if m[0] < day]
    cur = [m for m in past if m[5] == season]
    prev = [m for m in past if m[5] == season - 1 and m[6] == "R"]
    use, old = (cur, False) if len(cur) >= 3 else (prev, True)
    w = sum(1 for m in use if m[2] > m[3])
    split = [m for m in use if m[4] == home]
    sw = sum(1 for m in split if m[2] > m[3])
    f = team_form(idx, tid, day, season)
    return {
        "old": old, "w": w, "l": len(use) - w, "pct": w / len(use) if use else 0,
        "sw": sw, "sl": len(split) - sw,
        "pf": sum(m[2] for m in use) / len(use) if use else 0, "pa": sum(m[3] for m in use) / len(use) if use else 0,
        "streak": f["streak"], "rest": (day - past[-1][0]).days - 1 if past else None, "last": past[-5:],
    }


def form_html(g, idx):
    """Comparatif des deux équipes avant le match (visiteurs à gauche, domicile à droite), puis les derniers face-à-face."""
    a, h = g["away"]["id"], g["home"]["id"]
    ta, th = tale(idx, a, g["day"], g["season"], False), tale(idx, h, g["day"], g["season"], True)

    def better(va, vh, higher=True):
        if va == vh:
            return "", ""
        return ("up", "") if (va > vh) == higher else ("", "up")

    def streak(s):
        if not s:
            return "—"
        return f"<span class='{'w' if s > 0 else 'l'}'>{abs(s)} {'victoire' if s > 0 else 'défaite'}{'s' if abs(s) > 1 else ''}</span>"

    def rest(n):
        if n is None or n > 30:
            return "—"
        if n == 0:
            return "<span class='l'>2e soir de suite</span>"
        return f"{n} jour{'s' if n > 1 else ''}"

    def dots(t):
        out = []
        for m in t["last"]:
            res = "w" if m[2] > m[3] else "l"
            tip = f"{'V' if res == 'w' else 'D'} {m[2]}-{m[3]} {'vs' if m[4] else '@'} {team(m[1])['abbr']} · {m[0].day:02d}/{m[0].month:02d}"
            out.append(f"<span class='dt {res}{' old' if m[5] != g['season'] else ''}' title='{esc(tip)}'>{'V' if res == 'w' else 'D'}</span>")
        return "".join(out) or "—"

    rows = []
    ca, ch = better(ta["pct"], th["pct"])
    season_note = " (saison passée)" if ta["old"] or th["old"] else ""
    rows.append((f"{ta['w']}-{ta['l']}", "Bilan" + season_note, f"{th['w']}-{th['l']}", ca, ch))
    ca, ch = better(ta["sw"] / max(1, ta["sw"] + ta["sl"]), th["sw"] / max(1, th["sw"] + th["sl"]))
    rows.append((f"{ta['sw']}-{ta['sl']}", "À l'extérieur · à domicile", f"{th['sw']}-{th['sl']}", ca, ch))
    ca, ch = better(round(ta["pf"], 1), round(th["pf"], 1))
    rows.append((fr_num(ta["pf"]), "Points marqués / match", fr_num(th["pf"]), ca, ch))
    ca, ch = better(round(ta["pa"], 1), round(th["pa"], 1), higher=False)
    rows.append((fr_num(ta["pa"]), "Points encaissés / match", fr_num(th["pa"]), ca, ch))
    rows.append((streak(ta["streak"]), "Série en cours", streak(th["streak"]), "", ""))
    ca, ch = better(ta["rest"], th["rest"]) if ta["rest"] is not None and th["rest"] is not None and max(ta["rest"], th["rest"]) <= 30 else ("", "")
    rows.append((rest(ta["rest"]), "Repos avant le match", rest(th["rest"]), ca, ch))
    rows.append((f"<span class='dts'>{dots(ta)}</span>", "5 derniers matchs", f"<span class='dts'>{dots(th)}</span>", "", ""))

    head = (f"<div class='cmp-h'><div>{logo(a, 34)}<b>{esc(team(a)['name'])}</b></div><div class='vs'>avant ce match</div>"
            f"<div class='r'><b>{esc(team(h)['name'])}</b>{logo(h, 34)}</div></div>")
    body = "".join(f"<div class='cmp-r'><div class='{ca}'>{va}</div><div class='lab'>{lab}</div><div class='r {ch}'>{vh}</div></div>"
                   for va, lab, vh, ca, ch in rows)
    note = "<div class='note'>5 derniers : du plus ancien au plus récent · pâle = saison passée · survole une pastille pour le score.</div>"

    # Face-à-face
    all_h2h = head_to_head(idx, h, a, g["day"])
    last = all_h2h[-5:]
    if last:
        wh = sum(1 for m in last if m[2] > m[3])
        tot_h = sum(1 for m in all_h2h if m[2] > m[3])
        lines = []
        for m in reversed(last):
            home_t, away_t = (h, a) if m[4] else (a, h)
            hs, as_ = (m[2], m[3]) if m[4] else (m[3], m[2])
            win_away = as_ > hs
            lines.append(
                f"<div class='h2h-r'><span class='d'>{m[0].day:02d}/{m[0].month:02d}/{str(m[0].year)[2:]}</span>"
                f"<span class='{'b' if win_away else 'f'}'>{logo(away_t, 18)} {esc(team(away_t)['abbr'])} {as_}</span>"
                f"<span class='sep'>@</span>"
                f"<span class='{'f' if win_away else 'b'}'>{hs} {esc(team(home_t)['abbr'])} {logo(home_t, 18)}</span>"
                f"<span class='d'>{'play-offs' if m[6] == 'P' else ''}</span></div>")
        h2h = (f"<div class='sec'>Face-à-face</div><div class='h2h-sum'>{logo(a, 26)}<b>{len(last) - wh}</b><span>–</span><b>{wh}</b>{logo(h, 26)}"
               f"<small>sur les {len(last)} derniers · {len(all_h2h) - tot_h}-{tot_h} depuis 2016</small></div>" + "".join(lines))
    else:
        h2h = "<div class='sec'>Face-à-face</div><div class='note'>Pas de face-à-face depuis 2016.</div>"
    return f"<div class='cmp'>{head}{body}</div>{note}{h2h}"


def game_card(g, ctx):
    """Une carte de match, entièrement en HTML : score et forme s'ouvrent sans recharger la page (cases à cocher cachées)."""
    gid, zone, idx = g["id"], ctx["zone"], ctx["idx"]
    h, a = g["home"], g["away"]
    th, ta = team(h["id"]), team(a["id"])
    summ = ctx["summ"].get(gid)
    pre = pre_info(g, summ)
    tip = parse_dt(g["utc"])
    local = tip.astimezone(ZONES[zone]) if tip else None
    fav = th["abbr"] in ctx["favs"] or ta["abbr"] in ctx["favs"]

    # Ligne du haut : étiquettes à gauche, heure et salle à droite
    tags = []
    if fav:
        tags.append("<span class='tag star'>⭐ Mon équipe</span>")
    w = ctx["watch"].get(gid)
    if w:
        level = w[0]
        icon, label, advice = WATCH_LEVELS[level]
        tags.append(f"<span class='tag {'hot' if level >= 2 else 'cold' if level <= -1 else ''}' title='{esc(advice)}'>{icon} {label}</span>"
                    f"<span class='tag advice'>{esc(advice)}</span>")
    if gid == ctx.get("affiche"):
        tags.append("<span class='tag star'>⭐ L'affiche de la nuit</span>")
    if g["state"] == "in":
        tags.append("<span class='tag live'>● En direct</span>")
    if g["season_type"] == 3:
        tags.append("<span class='tag'>🏆 Play-offs</span>")
    for n in g["notes"][:1]:
        if "series" not in norm(n) and "leads" not in norm(n):
            tags.append(f"<span class='tag'>{esc(n)}</span>")
    right = []
    if local and g["state"] != "pre":
        right.append(f"{fr_hour(local)}")
    if g["venue"]:
        right.append("<span class='vn'>" + (" · " if right else "") + esc(g["venue"]) + (f", {esc(g['city'])}" if g["neutral"] and g["city"] else "") + "</span>")
    top = f"<div class='g-top'><div class='tags'>{''.join(tags)}</div><div class='rt'>{''.join(right)}</div></div>"

    # Les deux équipes, visiteurs à gauche, domicile à droite
    def side_html(s, t, where):
        f = team_form(idx, s["id"], g["day"], g["season"])
        rank = ctx["ranks"].get(s["id"])
        meta = (f"{f['w']}-{f['l']}" if f["n"] else f"{f['prev_w']}-{f['prev_l']} la saison passée") + (f" · {rank}e {t['conf']}" if rank else "")
        cls = "home" if where == "Domicile" else "away"
        return (f"<div class='tm {cls}'>{logo(s['id'])}<div><div class='nm'>{esc(t['name'])}</div>"
                f"<div class='mt'>{esc(meta)}</div><div class='where'>{where}</div></div></div>")

    if g["state"] == "pre":
        if g["status"] == "STATUS_POSTPONED":
            mid = "<div class='time'>—</div><div class='state'>Reporté</div>"
        else:
            other_day = local and zone != "Paris" and local.date() != g["day"]
            mid = (f"<div class='at'>@</div><div class='time'>{fr_hour(local) if local else '?'}</div>"
                   f"<div class='sub'>{esc(g['tv']) if g['tv'] else ''}{' · ' + fr_short(local.date()) if other_day else ''}</div>")
    else:
        hs, as_ = h["score"], a["score"]
        if hs is not None and as_ is not None:
            cw = lambda me, other: "w" if g["state"] != "post" or me >= other else "l"
            real = f"<span class='{cw(as_, hs)}'>{as_}</span> – <span class='{cw(hs, as_)}'>{hs}</span>"
        else:
            real = "–"
        if g["state"] == "in":
            state = "<div class='state live'>● En direct</div>"
        else:
            state = "<div class='state'>Terminé</div>"
        mid = f"<div class='hid'>? – ?</div><div class='real'>{real}</div>{state}"
    match = (f"<div class='g-match'>{side_html(a, ta, 'Extérieur')}<div class='mid'>{mid}</div>"
             f"{side_html(h, th, 'Domicile')}</div>")

    # Les enjeux (toujours visibles, 4 lignes au plus)
    points = preview_points(g, idx, pre)
    ai = None
    if ctx["ai"] and (g["state"] == "pre" or disk_get(f"ai_preview_{gid}.json")):
        ai = ai_points("preview", g, ai_material(g, summ, points))
    shown = (ai or points)[:4]
    pts_html = "<ul class='pts'>" + "".join(f"<li>{esc(p)}</li>" for p in shown) + "</ul>" if shown else ""

    # Boutons
    acts = []
    checked = " checked" if ctx["show_all"] else ""
    if g["state"] == "post":
        v, x = ctx["vids"].get(gid, (None, None))
        if v:
            d = dur(v, ctx["durs"])
            acts.append(f"<a class='pill main' href='{yt_url(v)}' target='_blank'>▶ Résumé NBA{' <small>' + d + '</small>' if d else ''}</a>")
        else:
            acts.append(f"<a class='pill ghost' href='{yt_search_url(g)}' target='_blank' title='Pas encore trouvé : recherche sur YouTube'>🔎 Résumé NBA</a>")
        if x:
            d = dur(x, ctx["durs"])
            acts.append(f"<a class='pill fr' href='{yt_url(x)}' target='_blank'><span class='frf'></span> NBA Extra{' <small>' + d + '</small>' if d else ''}</a>")
    if g["state"] != "pre":
        acts.append(f"<label for='s{gid}' class='pill pill-s'><span class='off'>👁 Score</span><span class='on'>🙈 Cacher le score</span></label>")
    acts.append(f"<label for='f{gid}' class='pill pill-f'><span class='off'>📊 Forme & duels</span><span class='on'>📊 Fermer</span></label>")

    # Panneau du score
    panel_s = ""
    if g["state"] != "pre" and summ:
        parts = [quarters_html(g)]
        if g["state"] == "post" and g["completed"]:
            rp = recap_points(g, summ, ctx["idx"])
            ai_r = ai_points("recap", g, ai_material(g, summ, rp)) if ctx["ai"] and (summ.get("article") or {}).get("type") == "Recap" else None
            parts.append("<div class='sec'>Ce qu'il faut retenir</div><ul class='pts'>" + "".join(f"<li>{esc(p)}</li>" for p in (ai_r or rp)) + "</ul>"
                         + ("<div class='ai'>✨ Écrit par Claude d'après le compte rendu AP</div>" if ai_r else ""))
            if w and w[1]:  # les raisons de la note, seulement une fois le score révélé
                icon, label, _ = WATCH_LEVELS[w[0]]
                parts.append(f"<div class='note'>{icon} {esc(label)} : {esc(', '.join(w[1]))}.</div>")
        elif g["state"] == "in":
            parts.append(f"<div class='note'>{esc(g['detail'])}</div>")
        worm = worm_svg(g, summ)
        if worm:
            parts.append("<div class='sec'>Le match en un coup d'œil</div>" + worm)
        parts.append(f"<details class='more'><summary>🧾 Stats des joueurs</summary><div class='in'>{box_html(g, summ)}</div></details>")
        panel_s = f"<div class='panel panel-s'>{''.join(parts)}</div>"
    panel_f = f"<div class='panel panel-f'>{form_html(g, idx)}</div>"

    return (f"<div class='g{' fav' if fav else ''}' id='g{gid}'>"
            f"<input type='checkbox' class='tg tg-s' id='s{gid}'{checked}><input type='checkbox' class='tg tg-f' id='f{gid}'>"
            f"{top}{match}{pts_html}<div class='acts'>{''.join(acts)}</div>{panel_f}{panel_s}</div>")


def night_html(day, games, ctx, today):
    """En-tête de la nuit : titre clair, état des matchs, NBA Extra et résumé NBA de la nuit, matchs à voir."""
    zone = ctx["zone"]
    rel = rel_label(day, zone, today)
    n = len(games)
    states = [g["state"] for g in games]
    if not n:
        status = "Pas de match"
    elif all(s == "post" for s in states):
        status = f"{n} match{'s' if n > 1 else ''} · tous terminés"
    elif all(s == "pre" for s in states):
        first = min((parse_dt(g["utc"]) for g in games if g["utc"]), default=None)
        status = f"{n} match{'s' if n > 1 else ''} · premier coup d'envoi à {fr_hour(first.astimezone(ZONES[zone]))}" if first else f"{n} matchs"
    else:
        live = states.count("in")
        status = f"{n} matchs · {states.count('post')} terminés" + (f" · {live} en cours" if live else "")
    status += f" · heures de {zone}"

    # NBA Extra : l'émission du lendemain matin parle de cette nuit
    show_day = day + timedelta(days=1)
    show_time = datetime.combine(show_day, datetime.min.time(), ZONES["Paris"]).replace(hour=12, minute=45)
    show_local = show_time.astimezone(ZONES[zone])
    label = f"NBA Extra du {JOURS[show_day.weekday()][:3]}. {show_day.day:02d}/{show_day.month:02d}"
    v = ctx["show"]
    if v:
        d = dur(v, ctx["durs"])
        extra = (f"<a class='media' href='{yt_url(v)}' target='_blank'><div class='ic'><span class='frf big'></span></div><div><b>{label}</b>"
                 f"<small>L'émission de beIN SPORTS sur cette nuit{' · ' + d if d else ''}</small></div><div class='go'>▶</div></a>")
    else:
        now = datetime.now(ZONES["Paris"])
        if now < show_time:
            when = f"en direct à {fr_hour(show_local)}{' (heure de Montréal)' if zone != 'Paris' else ''} sur beIN SPORTS, puis replay sur YouTube"
        elif now < show_time + timedelta(hours=10):
            when = "replay YouTube en général entre 15h et 17h (heure de Paris) · le lien apparaîtra ici"
        else:
            when = "pas trouvé sur YouTube"
        extra = (f"<div class='media off'><div class='ic'><span class='frf big'></span></div><div><b>{label}</b><small>{when}</small></div>"
                 f"<div class='go'>⏳</div></div>")

    recap = ctx["recap"]
    if recap:
        d = dur(recap, ctx["durs"])
        nba = (f"<a class='media' href='{yt_url(recap)}' target='_blank'><div class='ic'>🏀</div><div><b>Le résumé de la nuit</b>"
               f"<small>NBA, en anglais · tous les matchs{' · ' + d if d else ''}</small></div><div class='go'>▶</div></a>")
    elif n and all(s == "post" for s in states):
        q = f"NBA nightly recap {MONTHS_EN[day.month - 1].title()} {day.day}, {day.year}"
        nba = (f"<a class='media off' href='https://www.youtube.com/results?search_query={requests.utils.quote(q)}' target='_blank'>"
               f"<div class='ic'>🏀</div><div><b>Le résumé de la nuit</b><small>NBA · pas encore trouvé : chercher sur YouTube</small></div><div class='go'>🔎</div></a>")
    else:
        nba = ("<div class='media off'><div class='ic'>🏀</div><div><b>Le résumé de la nuit</b>"
               "<small>NBA · publié après le dernier match</small></div><div class='go'>⏳</div></div>")

    chips = ""
    ranked = sorted(((ctx["watch"][g["id"]][0], ctx["watch"][g["id"]][2], g) for g in games if ctx["watch"].get(g["id"])), key=lambda x: -x[1])
    ranked = [(lv, g) for lv, _, g in ranked]
    top = [(lv, g) for lv, g in ranked if lv >= 2][:6]
    if top:
        chips = "<div class='n-chips'><span class='lab'>À voir en priorité :</span>" + "".join(
            f"<a class='chip' href='#g{g['id']}'>{WATCH_LEVELS[lv][0]} {esc(team(g['away']['id'])['abbr'])} @ {esc(team(g['home']['id'])['abbr'])}</a>"
            for lv, g in top) + "</div>"
    return (f"<div class='night'><div class='n-kicker'>🌙 {esc(rel) if rel else ('Nuit NBA' if zone == 'Paris' else 'Soirée NBA')}</div>"
            f"<div class='n-title'>{esc(night_title(day, zone))}</div><div class='n-sub'>{esc(status)}</div>"
            f"<div class='n-media'>{extra}{nba}</div>{chips}</div>")


def ai_material(g, summ, points):
    th, ta = team(g["home"]["id"]), team(g["away"]["id"])
    art = (summ or {}).get("article") or {}
    lines = [f"Match : {ta['full']} chez {th['full']}.", "Infos calculées :"] + [f"- {p}" for p in points]
    if art.get("text"):
        lines += ["", f"Article AP ({art.get('type')}) : {art.get('headline')}", art["text"][:6000]]
    return "\n".join(lines)


def set_cookie(name, value):
    components.html(f"<script>parent.document.cookie='{name}={value}; path=/; max-age=31536000; SameSite=Lax';</script>", height=0)


def main():
    st.set_page_config(page_title="Bada Bing NBA", page_icon="🏀", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)
    try:
        cookies = st.context.cookies
    except Exception:
        cookies = {}
    if "favs" not in st.session_state:
        st.session_state.favs = [x for x in (cookies.get("nba_fav", "") or "").split(".") if x]
    zone = user_zone()
    today = datetime.now(NY).date()
    season = season_of(today)
    show_all = st.query_params.get("scores") == "1"
    interest = st.query_params.get("indice") != "0"

    with st.spinner("Chargement du calendrier…"):
        schedule = season_games(season, bucket(3600))
        idx = team_index(season, bucket(3600))
    days = sorted({g["day"] for g in schedule})
    if "day" not in st.session_state:
        try:  # la nuit choisie est gardée dans l'adresse (?nuit=AAAA-MM-JJ) : rechargement et liens partagés tombent dessus
            st.session_state.day = date.fromisoformat(st.query_params.get("nuit", ""))
        except ValueError:
            st.session_state.day = default_day(days, today)
    day = st.session_state.day
    if st.query_params.get("nuit") != day.isoformat():
        st.query_params["nuit"] = day.isoformat()

    # En-tête : marque à gauche, réglages à droite
    c1, c2 = st.columns([5, 1.3], vertical_alignment="center")
    c1.markdown("<div class='bb-brand'>🏀 Bada Bing <span>NBA</span></div><div class='bb-tag'>Les matchs de la nuit, sans spoil.</div>",
                unsafe_allow_html=True)
    with c2.popover("⚙️ Réglages", width="stretch"):
        new_zone = st.radio("Heures affichées", list(ZONES), index=list(ZONES).index(zone), horizontal=True)
        if new_zone != zone:
            st.query_params["tz"] = new_zone
            st.rerun()
        all_teams = sorted(teams().values(), key=lambda t: t["full"])
        favs = st.multiselect("⭐ Mes équipes", [t["abbr"] for t in all_teams], default=[f for f in st.session_state.favs if f in {t["abbr"] for t in all_teams}],
                              format_func=lambda ab: next((t["full"] for t in all_teams if t["abbr"] == ab), ab),
                              help="Leurs matchs passent en tête de liste, avec une étoile.")
        if favs != st.session_state.favs:
            st.session_state.favs = favs
            st.session_state.fav_changed = True
        new_interest = st.toggle("🔥 Indice « à voir » (sans dire qui gagne)", value=interest,
                                 help="Note chaque match terminé (fin serrée, remontée, prolongation, grosse perf) et range les meilleurs en premier.")
        new_show = st.toggle("👁 Toujours montrer les scores", value=show_all)
        if new_interest != interest or new_show != show_all:
            if new_interest:
                st.query_params.pop("indice", None)
            else:
                st.query_params["indice"] = "0"
            if new_show:
                st.query_params["scores"] = "1"
            else:
                st.query_params.pop("scores", None)
            st.rerun()
        other = st.date_input("📅 Aller à une date (jour du match aux États-Unis)", value=day, format="DD/MM/YYYY", key=f"other_{day}")
        if other != day:
            st.session_state.day = other
            st.rerun()
        w = video_watcher()
        if not _secret("youtube", "api_key", ""):
            yt = "⚠️ Pas de clé YouTube : seulement les 15 dernières vidéos de chaque chaîne (+ la veille)."
        elif API_STATUS["ok"] is False:
            yt = f"⚠️ {API_STATUS['msg']}"
        else:
            yt = "✅ Clé YouTube active"
        nb = sum(len(v) for v in w["seen"].values())
        st.caption(f"{yt} · veille : {nb} vidéos gardées"
                   + (f", dernier passage à {fr_hour(datetime.fromtimestamp(w['last'], ZONES[zone]))}" if w["last"] else ""))
        st.caption(f"Version {APP_VERSION} · ESPN, YouTube")

    # Choix de la nuit
    near = [d for d in days if d < today][-3:] + [d for d in days if d >= today][:3]
    if day not in near:
        near = sorted(set(near) | {day})
    picked = st.segmented_control("Nuit", near, format_func=lambda d: pill_label(d, zone, today), default=day,
                                  key=f"days_{day}", label_visibility="collapsed", width="stretch")
    if picked and picked != day:
        st.session_state.day = picked
        st.rerun()

    games = day_games(day)
    with ThreadPoolExecutor(8) as pool:  # fiches ESPN en parallèle (gardées en cache ensuite)
        summs = dict(zip([g["id"] for g in games], pool.map(game_summary, games)))
    nba_vids, extra_vids = videos_since(min(day, today - timedelta(days=1)))
    ai_on = bool(_secret("anthropic", "api_key", ""))
    watch = {g["id"]: watch_score(g, summs.get(g["id"]), idx) for g in games} if interest else {}
    watch = {k: v for k, v in watch.items() if v}
    ranks = {}
    if games:
        f0 = team_form(idx, games[0]["home"]["id"], day, games[0]["season"])
        if f0["n"] >= 8:
            ranks = conf_ranks(idx, day, games[0]["season"])
    ctx = {"zone": zone, "idx": idx, "summ": summs, "nba_vids": nba_vids, "extra_vids": extra_vids, "show_all": show_all,
           "favs": set(st.session_state.favs), "watch": watch, "ranks": ranks, "ai": ai_on, "durs": {}}

    # Affiche de la nuit (matchs à venir) et durées des vidéos trouvées
    upcoming = [g for g in games if g["state"] == "pre"]
    if len(upcoming) >= 3:
        ctx["affiche"] = max(upcoming, key=lambda g: hype(g, idx, pre_info(g, summs.get(g["id"]))))["id"]
    with ThreadPoolExecutor(8) as pool:  # vidéos : listes des chaînes, puis recherche YouTube pour ce qui manque
        vids = pool.map(lambda g: game_videos(g, nba_vids, extra_vids) if g["state"] == "post" else (None, None), games)
        ctx["vids"] = dict(zip([g["id"] for g in games], vids))
    ctx["recap"], ctx["show"] = night_videos(day, nba_vids, extra_vids)
    found = [v for pair in ctx["vids"].values() for v in pair if v] + [v for v in (ctx["recap"], ctx["show"]) if v]
    ctx["durs"] = video_durations(tuple(sorted({v["id"] for v in found})))

    st.markdown(night_html(day, games, ctx, today), unsafe_allow_html=True)
    if not games:
        st.info("Pas de match NBA ce jour-là.")

    # Ordre : mes équipes, puis (nuit terminée) les matchs à voir d'abord, sinon l'horaire
    def order(g):
        fav = team(g["home"]["id"])["abbr"] in ctx["favs"] or team(g["away"]["id"])["abbr"] in ctx["favs"]
        sc = watch[g["id"]][2] if g["id"] in watch else -1
        return (0 if fav else 1, -sc if watch else 0, g["utc"] or "")
    for g in sorted(games, key=order):
        st.markdown(game_card(g, ctx), unsafe_allow_html=True)

    if st.session_state.pop("fav_changed", False):
        set_cookie("nba_fav", ".".join(st.session_state.favs))
    auto_refresh(games)


if __name__ == "__main__":
    main()
