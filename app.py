"""Bada Bing NBA : les matchs NBA sans spoil.

Liste des matchs par nuit, preview écrite avant le match, résumés vidéo (NBA, NBA Extra de beIN SPORTS),
journal NBA Extra du jour, et, seulement quand on le demande, le score, l'analyse et la feuille de match.
Données : API publique d'ESPN (sans clé) et YouTube (flux public, ou API YouTube si une clé est fournie).
"""
import hmac
import html
import json
import logging
import math
import os
import re
import threading
import time
import traceback
import unicodedata
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st
import streamlit.components.v1 as components

import fantasy as F
import stats as S

APP_VERSION = "2026-11-v025"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, ".cache")  # infos d'avant-match gardées (blessés, cotes, preview IA)
log = logging.getLogger("nba")

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
ESPN_STANDINGS = "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings"
NY = ZoneInfo("America/New_York")  # le « jour du match » est celui de New York (calendrier d'ESPN)
ZONES = {"Paris": ZoneInfo("Europe/Paris"), "Montréal": ZoneInfo("America/Toronto")}

NBA_CHANNEL = "UCWJ2lWNubArHWmf3FIHbfcQ"    # chaîne officielle NBA
EXTRA_CHANNEL = "UCcMGbm0EYWh1SZZ8MsM75tw"  # NBA Extra - beIN SPORTS France
GT_CHANNEL = "UC0LrZO9wORIqn_aRJtKdgfA"     # GAMETIME HIGHLIGHTS (@thegametimehighlights) : source principale des résumés (choix de Kiki, 26/10)
YOUTUBE_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
YOUTUBE_PLAYLIST_URL = "https://www.googleapis.com/youtube/v3/playlistItems"

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
MOIS_COURT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
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


if os.environ.get("BB_FAUX_ESPN"):  # essais sans connexion : saison inventée (tests/faux_espn.py)
    from tests.faux_espn import fake_get as _FAKE
else:
    _FAKE = None


def get_json(url, params=None, timeout=10):
    if _FAKE and ("espn.com" in url or "nba.com" in url):
        return _FAKE(url, params)
    try:
        r = SESSION.get(url, params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        log.warning("HTTP %s sur %s", r.status_code, url.split("?")[0])
        S.add_error(f"HTTP {r.status_code} sur {_short_url(url)}")
    except Exception as e:
        log.warning("%s sur %s", type(e).__name__, url.split("?")[0])
        S.add_error(f"{type(e).__name__} sur {_short_url(url)}")
    return None


def _short_url(url):
    """Adresse sans paramètres ni nom de domaine, pour le journal des erreurs (la clé YouTube n'y figure jamais)."""
    return re.sub(r"^https?://[^/]+", "", url.split("?")[0])[-80:]


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
                "id": e.get("id"), "day": ny_day(e.get("date")), "utc": e.get("date") or "",
                "home": sides["home"]["team"]["id"], "away": sides["away"]["team"]["id"],
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
        "tv_all": sorted({n for b in c.get("broadcasts") or [] for n in b.get("names") or []}
                         | {((b.get("media") or {}).get("shortName") or "") for b in c.get("geoBroadcasts") or []} - {""}),
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


def auto_refresh(games, show_all=False):
    """La page Streamlit ne se met pas à jour seule : un onglet laissé ouvert garde les scores du moment où on l'a ouvert.
    On recharge donc la page quand on revient sur l'onglet après plus de 3 minutes, et toutes les 90 secondes pendant
    les matchs (sauf si un panneau est ouvert, pour ne pas le refermer sous les yeux de l'utilisateur)."""
    now = datetime.now(timezone.utc)
    live = any(g["state"] == "in" or (g["state"] == "pre" and g["status"] != "STATUS_POSTPONED" and parse_dt(g["utc"])
                                      and parse_dt(g["utc"]) - now < timedelta(minutes=15)) for g in games)
    busy = ".tg-f:checked, .tgp:checked, details[open]" if show_all else ".tg:checked, details[open]"
    run_js(f"""<script>
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
</script>""")


@st.cache_data(ttl=86400, show_spinner=False, max_entries=400)
def summary(event_id, _bucket):
    """Résumé ESPN d'un match, réduit à ce dont le site a besoin."""
    return summary_raw(event_id)


def summary_raw(event_id):
    """Comme summary, sans cache Streamlit (utilisable depuis un fil d'exécution de fond)."""
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
        remember_outs(g, s)
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
            S.add_error(API_STATUS["msg"])
            break
        if r.status_code != 200:
            log.warning("API YouTube : HTTP %s", r.status_code)
            reason = ""
            try:
                reason = ((r.json().get("error") or {}).get("errors") or [{}])[0].get("reason", "")
            except Exception:
                pass
            API_STATUS.update(ok=False, msg=f"API YouTube refusée : HTTP {r.status_code} {reason}".strip(), at=time.time())
            S.add_error(API_STATUS["msg"])
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
        for ch in (NBA_CHANNEL, EXTRA_CHANNEL, GT_CHANNEL):
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
    """(vidéos NBA, vidéos NBA Extra) ; les vidéos GAMETIME HIGHLIGHTS sont rangées avec celles de la NBA, marquées « gt »."""
    oldest = (datetime.combine(day, datetime.min.time()) - timedelta(days=1)).isoformat()
    b = bucket(600)
    gt = [dict(v, gt=True) for v in channel_videos(GT_CHANNEL, oldest, b)]
    return channel_videos(NBA_CHANNEL, oldest, b) + gt, channel_videos(EXTRA_CHANNEL, oldest, b)


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
    """Résumé du match : GAMETIME HIGHLIGHTS d'abord (« Utah Jazz vs New Orleans Pelicans Full Game Highlights - October 23, 2026 |
    NBA Season »), sinon le résumé officiel NBA (« KINGS at CLIPPERS | FULL GAME HIGHLIGHTS | October 21, 2026 »)."""
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
        key = (0 if v.get("gt") else 1, 0 if "full game highlights" in t else 1, pub)
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
    nba = nba_video(nba_vids, g)
    if not (nba and nba.get("gt")) and store.get(f"gt_{g['id']}"):
        nba = dict(store[f"gt_{g['id']}"], gt=True)
    nba = nba or store.get(f"nba_{g['id']}")
    extra = extra_video(extra_vids, g) or store.get(f"x_{g['id']}")
    when = f"{MONTHS_EN[g['day'].month - 1].title()} {g['day'].day}, {g['day'].year}"
    if g["state"] == "post" and not (nba and nba.get("gt")):
        tfa, tfh = team(g["away"]["id"])["full"], team(g["home"]["id"])["full"]
        found = [dict(v, gt=True) for v in _from(GT_CHANNEL, yt_search(f"{tfa} vs {tfh} Full Game Highlights {when} GAMETIME HIGHLIGHTS"))]
        nba = nba_video(found, g) or nba
    if g["state"] == "post" and not nba:
        ta, th = team(g["away"]["id"])["name"], team(g["home"]["id"])["name"]
        nba = nba_video(_from(NBA_CHANNEL, yt_search(f"{ta} at {th} full game highlights {when}")), g)
    if nba and nba.get("gt"):
        remember_video(f"gt_{g['id']}", nba)
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
    # (v017 : plus de phrase « Duel de l'Ouest : X (2-0) chez Y (2-0) », jugée inutile : le bilan est à côté du nom)
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


def team_record(idx, tid, day, season):
    """Bilan AVANT le jour du match (« 2-0 »), vide avant le 1er match de la saison."""
    f = team_form(idx, tid, day, season)
    return f"{f['w']}-{f['l']}" if f["n"] else ""


def remember_outs(g, pre):
    """Garde, équipe par équipe, qui était absent avant chaque match : sert à repérer un retour de blessure."""
    for side in ("home", "away"):
        tid = g[side]["id"]
        out = [i["name"] for i in (pre.get("injuries") or {}).get(tid) or [] if "out" in norm(i.get("status"))]
        mem = disk_get(f"outs_{tid}.json") or {}
        if mem.get(g["day"].isoformat()) == out:
            continue
        mem[g["day"].isoformat()] = out
        disk_put(f"outs_{tid}.json", dict(sorted(mem.items())[-12:]))


KF_TOPIC = {"🔥": "📈", "🧊": "📈", "📉": "📈", "😮": "📈", "🔁": "🆚", "🎲": "💰", "⚠": "🩹", "💪": "🩹"}


def same_topic(point, fact):
    """Vrai si une puce de l'avant-match parle du même sujet que l'info clé (pour ne pas la répéter juste en dessous)."""
    if not fact:
        return False
    def topic(t):
        c = t[:1]
        return KF_TOPIC.get(c, c)
    return topic(point) == topic(fact)


def key_fact(g, idx, pre):
    """L'info d'avant-match la plus importante à connaître (une seule), choisie parmi : play-offs, star absente, retour de
    blessure, joueur incertain, série en cours, choc au sommet, revanche, face-à-face, fatigue, favori… Rien qui dépende du résultat."""
    h, a = g["home"]["id"], g["away"]["id"]
    th, ta = team(h), team(a)
    day, season = g["day"], g["season"]
    fh, fa = team_form(idx, h, day, season), team_form(idx, a, day, season)
    cands = []  # (importance, texte)

    def last(name):
        return name.split(" ", 1)[-1] if " " in name else name

    # Play-offs : l'état de la série prime sur tout
    if g["season_type"] == 3:
        series = [m for m in head_to_head(idx, h, a, day) if m[5] == season and m[6] == "P"]
        wh = sum(1 for m in series if m[2] > m[3])
        wa = len(series) - wh
        if not series:
            txt = "Match 1 de la série"
        elif wh == wa:
            txt = f"Match {len(series) + 1}, série à égalité {wh}-{wa}"
        else:
            lead, n1, n2 = (th, wh, wa) if wh > wa else (ta, wa, wh)
            txt = f"Match {len(series) + 1} : {lead['name']} à {n1}-{n2}" + (" et une balle de qualification" if n1 == 3 else "")
            if n1 == 3 and n2 == 3:
                txt = "Match 7 : qualification ou élimination"
        cands.append((100 if max(wh, wa) == 3 else 95, f"🏆 {txt}"))
    notes = [n for n in g["notes"] if n and "series" not in norm(n) and "leads" not in norm(n)]
    if notes:
        cands.append((70, f"📍 {notes[0]}"))
    if fh["n"] == 0 and fa["n"] == 0 and g["season_type"] != 3:
        cands.append((60, "🏁 Premier match de la saison pour les deux équipes"))

    # Joueurs : absents, retours, incertains (les « stars » = meneurs de l'équipe en points, rebonds ou passes)
    if pre:
        lead = pre.get("leaders") or {}
        for t in (ta, th):
            stars = {v[0] for v in (lead.get(t["id"]) or {}).values() if v and v[0]}
            inj = (pre.get("injuries") or {}).get(t["id"]) or []
            out = [i for i in inj if any(k in norm(i.get("status")) for k in ("out", "doubtful"))]
            unsure = [i for i in inj if any(k in norm(i.get("status")) for k in ("questionable", "day-to-day", "day to day"))]

            def what(i):
                w = INJURY_FR.get(norm(i.get("what")), (i.get("what") or "").lower())
                return f" ({w})" if w else ""
            big = [i for i in out if i["name"] in stars]
            if big:
                cands.append((92, f"🩹 {t['name']} sans {' ni '.join(last(i['name']) + what(i) for i in big[:2])}"))
            elif len(out) >= 3:
                cands.append((55, f"🩹 {t['name']} privés de {len(out)} joueurs ({', '.join(last(i['name']) for i in out[:3])})"))
            elif out:
                cands.append((35, f"🩹 {t['name']} sans {', '.join(last(i['name']) for i in out[:2])}"))
            shaky = [i for i in unsure if i["name"] in stars]
            if shaky:
                cands.append((72, f"⚠️ {last(shaky[0]['name'])} incertain{what(shaky[0])} côté {t['name']}"))
            # Retour : absent au match précédent de l'équipe (si le site l'a vu), plus dans la liste aujourd'hui
            mem = disk_get(f"outs_{t['id']}.json") or {}
            past = [d for d in mem if d < day.isoformat()]
            prev_games = [m for m in idx.get(t["id"], []) if m[0] < day]
            if past and prev_games and max(past) == prev_games[-1][0].isoformat():
                now_out = {i["name"] for i in inj}
                back = [n for n in mem[max(past)] if n not in now_out]
                if back:
                    star = [n for n in back if n in stars]
                    cands.append((90 if star else 64, f"💪 Retour de {last((star or back)[0])} côté {t['name']}"))

    # Séries en cours, invaincus, toujours sans succès
    for t, f in ((ta, fa), (th, fh)):
        s = f["streak"]
        if f["n"] >= 3 and f["l"] == 0:
            cands.append((84, f"🔥 {t['name']} encore invaincus ({f['w']}-0)"))
        elif f["n"] >= 4 and f["w"] == 0:
            cands.append((68, f"🧊 {t['name']} toujours sans succès cette saison (0-{f['l']})"))
        elif abs(s) >= 3:
            n = abs(s)
            imp = 88 if n >= 8 else 80 if n >= 5 else 56
            cands.append((imp, f"{'📈' if s > 0 else '📉'} {t['name']} sur {n} {'succès' if s > 0 else 'revers'} de suite"))
    # Choc au sommet
    if min(fh["n"], fa["n"]) >= 8:
        ranks = conf_ranks(idx, day, season)
        rh, ra = ranks.get(h), ranks.get(a)
        if rh and ra and th["conf"] == ta["conf"] and max(rh, ra) <= 3:
            cands.append((78, f"⚔️ Choc au sommet de l'{th['conf']} : {min(rh, ra)}{'er' if min(rh, ra) == 1 else 'e'} contre {max(rh, ra)}e"))
        elif rh == 1 and ra == 1:
            cands.append((82, "⚔️ Les deux premiers de chaque conférence"))
    # Fatigue : 2e match en 2 soirs face à une équipe reposée
    for t, f, o in ((ta, fa, fh), (th, fh, fa)):
        if f["b2b"] and not o["b2b"]:
            cands.append((42, f"😮‍💨 {t['name']} jouent leur 2e match en 2 soirs"))
    # Face-à-face : revanche des play-offs, domination, ou simple bilan
    h2h = head_to_head(idx, h, a, day)
    po = [m for m in h2h if m[5] == season - 1 and m[6] == "P"]
    if po and g["season_type"] != 3:
        wh = sum(1 for m in po if m[2] > m[3])
        winner, loser = (th, ta) if wh * 2 > len(po) else (ta, th)
        cands.append((74, f"🔁 Revanche : les {winner['name']} avaient sorti les {loser['name']} en play-offs l'an dernier"))
    recent = h2h[-5:]
    if recent:
        wh = sum(1 for m in recent if m[2] > m[3])
        n = len(recent)
        if n >= 4 and wh in (0, n):
            dom, other = (th, ta) if wh else (ta, th)
            cands.append((62, f"🆚 {dom['name']} : {n} succès de suite contre les {other['name']}"))
        else:
            lead, n1, n2 = (th, wh, n - wh) if wh * 2 >= n else (ta, n - wh, wh)
            txt = f"{n1}-{n2} sur les {n} derniers face-à-face" if n1 == n2 else f"{n1}-{n2} pour les {lead['name']} sur les {n} derniers face-à-face"
            cands.append((45, f"🆚 {txt}"))
    # Cote figée avant le match
    if pre:
        pct = pre.get("home_pct")
        if (pre.get("line") or "").upper() == "EVEN" or (pct is not None and 46 <= pct <= 54):
            cands.append((48, "🎲 Pile ou face selon les pronostics"))
        elif pct is not None and (pct >= 82 or pct <= 18):
            fav = th if pct >= 82 else ta
            cands.append((40, f"💰 {fav['name']} grands favoris ({fr_num(max(pct, 100 - pct), 0)} %)"))
    if not cands:
        return ""
    return max(cands, key=lambda c: c[0])[1]


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
@st.cache_data(ttl=21600, show_spinner=False, max_entries=300)
def video_info(ids):
    """{id: {"mins", "blocked", "allowed"}} via l'API YouTube (1 unité de quota pour 50 vidéos) : durée et pays où la vidéo
    est bloquée. Sans clé YouTube : {} (impossible de savoir si une vidéo est bloquée en France)."""
    key = str(_secret("youtube", "api_key", ""))
    if not key or not ids:
        return {}
    out = {}
    for i in range(0, len(ids), 50):
        d = get_json("https://www.googleapis.com/youtube/v3/videos",
                     {"part": "contentDetails,status", "id": ",".join(ids[i:i + 50]), "key": key}) or {}
        for item in d.get("items") or []:
            cd = item.get("contentDetails") or {}
            m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", cd.get("duration", ""))
            secs = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60 + int(m.group(3) or 0) if m else 0
            rr = cd.get("regionRestriction") or {}
            out[item["id"]] = {"mins": max(1, round(secs / 60)) if secs else None, "blocked": set(rr.get("blocked") or []),
                               "allowed": set(rr["allowed"]) if "allowed" in rr else None,
                               "embed": bool((item.get("status") or {}).get("embeddable", True))}
    return out


def video_durations(ids):
    return {k: v["mins"] for k, v in video_info(ids).items() if v["mins"]}


def playable(v, info, country):
    """La vidéo passe-t-elle dans ce pays ? (inconnu = on suppose que oui)"""
    i = info.get(v["id"]) if v else None
    if not v:
        return False
    if not i:
        return True
    return country not in i["blocked"] and (i["allowed"] is None or country in i["allowed"])


def alt_video(g, exclude):
    """Autre résumé du match (autre chaîne que la NBA), trouvé par une recherche YouTube : candidats dans l'ordre."""
    ta, th = team(g["away"]["id"])["name"], team(g["home"]["id"])["name"]
    when = f"{MONTHS_EN[g['day'].month - 1].title()} {g['day'].day}, {g['day'].year}"
    tip = parse_dt(g["utc"])
    out = []
    for q in (f"{ta} vs {th} highlights {when}", f"{ta} {th} full game highlights {when}"):
        for v in yt_search(q):
            t = norm(v["title"])
            if v["id"] in exclude or v["channel"] == NBA_CHANNEL or v in out:
                continue
            if "highlight" not in t and "resume" not in t and "recap" not in t:
                continue
            if not (_has_team(t, g["home"]["id"]) and _has_team(t, g["away"]["id"])):
                continue
            if any(x in t for x in ("top 10", "reaction", "react", "live", "prediction", "preview", "2k", "every ")):
                continue
            td = _title_date(t)
            if td and td != g["day"]:
                continue
            if not _in_window(v, parse_dt(v["published"]), tip, 4) or (v.get("mins") and v["mins"] < 3):
                continue
            out.append(v)
    return out[:6]


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
div[data-testid="stElementContainer"]:has(iframe[height="0"]), div[data-testid="stElementContainer"]:has(iframe[height="1"]) {position:absolute; width:0; height:0; overflow:hidden; margin:0;}
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {display: none !important;}  /* barre Streamlit (partager, étoile, crayon, ⋮) cachée */
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


/* ===== Design v011 : cartes à collectionner, afficheur « play clock », raretés ===== */
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Barlow:wght@400;500;600;700&family=Orbitron:wght@700;800&display=swap');
.block-container {max-width:1240px; padding-top:2.6rem;}
.stApp, .stApp p, .stApp li, .stApp label, .stApp button {font-family:'Barlow', 'Source Sans Pro', sans-serif;}
.bb-brand {font-family:'Barlow Condensed', sans-serif; font-size:1.9rem; font-weight:800; text-transform:uppercase; letter-spacing:.02em; line-height:1;}
.bb-brand span {color:#ffc75a;}

/* En-tête : marque | 📅 | ⚙️ */
.st-key-hdr [data-testid="stHorizontalBlock"] {flex-wrap:nowrap; align-items:center; gap:8px;}
.st-key-hdr [data-testid="stColumn"] {width:auto !important; flex:0 0 auto !important; min-width:0 !important;}
.st-key-hdr [data-testid="stColumn"]:first-child {flex:1 1 auto !important;}
.st-key-hdr button {min-height:42px; min-width:46px; border-radius:12px;}

/* Bandeau sur une ligne : ‹ | Semaine | 7 nuits | › */
.st-key-nav [data-testid="stHorizontalBlock"] {flex-wrap:nowrap; overflow-x:auto; gap:6px; align-items:stretch; padding-bottom:4px; scrollbar-width:thin;}
.st-key-nav [data-testid="stColumn"] {flex:1 0 104px !important; min-width:104px !important;}
.st-key-nav [data-testid="stColumn"]:first-child, .st-key-nav [data-testid="stColumn"]:last-child {flex:0 0 42px !important; min-width:42px !important;}
.st-key-nav button {min-height:46px; height:100%; border-radius:12px; position:relative; padding:4px 6px;}
.st-key-nav button p {font-family:'Barlow Condensed', sans-serif; font-weight:700; font-size:1.02rem; white-space:nowrap; overflow:visible;}
.st-key-nav button[kind="primary"], .st-key-nav button[data-testid="stBaseButton-primary"] {background:#ffc75a; border-color:#ffc75a;}
.st-key-nav button[kind="primary"] p, .st-key-nav button[data-testid="stBaseButton-primary"] p {color:#1a1205;}

/* Barre de la nuit */
.nbar {margin:.5rem 0 1.1rem; padding:12px 16px; border-radius:16px; background:#10141e; border:1px solid #1e2533;}
.nbar .tg {display:none;}
.nb-row {display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap;}
.nb-t {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.45rem; text-transform:uppercase; line-height:1.05;}
.nb-s {font-size:.82rem; font-weight:600; color:#6ee7a0; margin-top:2px;}
.nb-s.k-live {color:#ff8a8a;} .nb-s.k-next, .nb-s.k-none {color:var(--muted);}
.nb-r {display:flex; gap:6px; flex-wrap:wrap;}
.ess-hid {display:none; margin-top:10px; padding-top:10px; border-top:1px solid #1e2533;}
.tg-n:checked ~ .ess-hid {display:block;}
.tg-n:checked ~ * .pill-n {border-color:#ffc75a; background:rgba(255,199,90,.12);}
.tg-n:checked ~ * .pill-n .on {display:inline;} .tg-n:checked ~ * .pill-n .off {display:none;}

/* Boutons discrets */
.cbtn {display:inline-flex; align-items:center; justify-content:center; gap:6px; min-height:34px; padding:0 12px; border-radius:9px;
       border:1px solid #2f3848; background:rgba(15,19,28,.6); color:#eef1f6 !important; text-decoration:none !important; font-weight:600; font-size:.82rem; cursor:pointer; user-select:none; white-space:nowrap;}
.cbtn:hover {border-color:#ffc75a;}
.cbtn.main {background:#ffc75a; border-color:#ffc75a; color:#1a1205 !important; font-weight:700;}
.cbtn.ghost {color:#9aa3b5 !important; border-style:dashed;}
.cbtn.fr {background:#16233d; border-color:#2a3f66;}
.cbtn.off {opacity:.55; cursor:default; border-style:dashed;}
.cbtn .on {display:none;}

/* Grille de cartes */
.cards {display:grid; grid-template-columns:repeat(auto-fill, minmax(330px, 1fr)); gap:22px; margin-bottom:2rem;}
.gc {position:relative; scroll-margin-top:80px;}
.gc .tg {display:none;}
.card {padding:5px; border-radius:20px; height:100%; box-sizing:border-box; background:#2a3242; box-shadow:0 14px 30px rgba(0,0,0,.35);}
/* Raretés (même largeur de cadre partout) : gris très foncé → gris clair → ardoise → cuivre → argent → or légendaire */
.card.Lm2 {background:#1b1d21; box-shadow:inset 0 0 0 1px #2a2d33, 0 14px 30px rgba(0,0,0,.35);}
.card.Lm1 {background:#7c838d;}
.card.L0 {background:#4b5a6e;}
.card.L1 {background:linear-gradient(135deg, #6e3417, #c4743f 30%, #f0b58a 50%, #b0602d 70%, #6e3417); box-shadow:0 0 16px rgba(196,116,63,.28), 0 14px 30px rgba(0,0,0,.35);}
.card.L2 {background:linear-gradient(115deg, #7d8894, #e9eef3, #b9c2cc, #ffffff, #8e99a5, #dfe5ec, #7d8894); background-size:300% 100%;
          animation:holo 9s linear infinite; box-shadow:0 0 0 1px rgba(235,240,245,.45), 0 0 26px rgba(220,230,240,.25), 0 14px 30px rgba(0,0,0,.35);}
.card.L3 {background:linear-gradient(115deg, #b8860b, #ffe9a3, #f7c948, #fff8dc, #d4a017, #9fdcff, #f5b8ff, #ffe9a3, #b8860b); background-size:300% 100%;
          animation:holo 6s linear infinite; box-shadow:0 0 0 1px rgba(255,220,130,.6), 0 0 34px rgba(247,200,80,.35), 0 14px 30px rgba(0,0,0,.35);}
.card.Laff {background:linear-gradient(135deg, #a8781f, #ffd770 50%, #a8781f);}
.card.Llive {background:linear-gradient(135deg, #b91c1c, #ff6b6b 50%, #b91c1c);}
@keyframes holo {to {background-position:300% 0;}}
@media (prefers-reduced-motion: reduce) {.card.L3, .card.L2 {animation:none;}}
.ci {height:100%; border-radius:15px; overflow:hidden; display:flex; flex-direction:column;
     background:repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 2px, transparent 2px 10px), linear-gradient(115deg, var(--ca) 0%, var(--ca) 49%, var(--ch) 51%, var(--ch) 100%);}
.ctop {display:flex; justify-content:space-between; align-items:center; gap:6px; padding:11px 11px 0; min-height:26px;}
.chips {display:flex; gap:5px; flex-wrap:wrap;}
.lvl {display:inline-flex; align-items:center; gap:4px; padding:3px 10px; border-radius:999px; background:rgba(8,10,16,.8); color:#fff; font-weight:700; font-size:.8rem; white-space:nowrap;}
.L3 .lvl {background:linear-gradient(135deg, #f7c948, #fff4c2, #d4a017); color:#2a1e00;}
.L2 .lvl {background:linear-gradient(135deg, #dfe5ec, #ffffff, #aeb8c3); color:#16191d;}
.L1 .lvl {background:linear-gradient(135deg, #b0602d, #f0b58a); color:#2a1206;}
.L0 .lvl {background:#4b5a6e; color:#fff;}
.Lm1 .lvl {background:#7c838d; color:#fff;}
.Lm2 .lvl {background:#1b1d21; color:#c3c8cf; box-shadow:inset 0 0 0 1px #3a3e45;}
.Llive .lvl {background:#d93636;}
.Laff .lvl {background:#ffd770; color:#2a1e00;}
.cpill {display:inline-flex; align-items:center; padding:3px 9px; border-radius:999px; background:rgba(8,10,16,.75); color:#eef1f6; font-weight:700; font-size:.8rem; white-space:nowrap;}
.cpill.star {color:#ffc75a;}
.cart {position:relative; display:block; height:150px; flex:none;}
label.cart {cursor:pointer;}
.disc {width:96px; height:96px; border-radius:50%; background:rgba(8,10,16,.5); box-shadow:0 10px 24px rgba(0,0,0,.45), inset 0 0 0 2px rgba(255,255,255,.2); display:flex; align-items:center; justify-content:center;}
.disc img {width:72px; height:72px; object-fit:contain; filter:drop-shadow(0 2px 4px rgba(0,0,0,.45));}
.disc b {font-family:'Barlow Condensed', sans-serif; font-size:1.3rem; color:#fff;}
.cart .da {position:absolute; left:24px; top:8px;}
.cart .dh {position:absolute; right:24px; bottom:4px;}
.cart .at {position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); width:38px; height:38px; border-radius:50%; background:rgba(8,10,16,.85); color:#eef1f6; display:flex; align-items:center; justify-content:center; font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.1rem; box-shadow:0 0 0 3px rgba(255,255,255,.18);}
/* Noms + afficheur */
.cname {display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:8px; padding:8px 12px; background:linear-gradient(180deg, rgba(8,10,16,.0), rgba(8,10,16,.55));}
.cname b {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.2rem; line-height:1; text-transform:uppercase; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; text-shadow:0 2px 6px rgba(0,0,0,.6);}
.cname b.r {text-align:right;}
.cname b.sm {font-size:1.02rem;} .cname b.xs {font-size:.9rem; letter-spacing:-.01em;}
.clock {display:flex; flex-direction:column; align-items:center; gap:2px; padding:5px 10px 6px; border-radius:9px; background:#050505;
        box-shadow:inset 0 0 0 1px #2b2b2b, inset 0 0 12px rgba(0,0,0,.9), 0 4px 12px rgba(0,0,0,.5); min-width:86px;}
.clock.tap {cursor:pointer;}
.ck-l {font-size:.6rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:#ff4d3d; white-space:nowrap;}
.ck-l i {font-style:normal; letter-spacing:0;}
.ck-d {font-family:'Orbitron', 'Barlow Condensed', monospace; font-weight:800; font-size:1.15rem; color:#ffb000; letter-spacing:.06em;
       text-shadow:0 0 6px rgba(255,176,0,.75), 0 0 14px rgba(255,120,0,.35); white-space:nowrap; line-height:1.1;}
.clock.tap:hover {box-shadow:inset 0 0 0 1px #ffb000, 0 0 14px rgba(255,176,0,.35);}
.sc-real {display:none;}
.tg-s:checked ~ * .sc-hid {display:none;} .tg-s:checked ~ * .sc-real {display:inline;}
.tg-s:checked ~ * .ck-l i {display:none;}
.clock.big {padding:8px 16px 10px; min-width:150px;} .clock.big .ck-d {font-size:2rem;} .clock.big .ck-l {font-size:.7rem;}
/* Avant-match et pied */
.info {flex:1; padding:10px 12px 11px; background:linear-gradient(180deg, rgba(10,13,20,.86), rgba(10,13,20,.95)); border-top:1px solid rgba(255,255,255,.08);
       display:flex; flex-direction:column; gap:8px; backdrop-filter:blur(6px);}
.cprev {list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:4px;}
.cprev li {font-size:.82rem; line-height:1.3; color:#d3d9e3; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;}
.cfoot {display:flex; align-items:center; gap:6px; flex-wrap:wrap;}
.lnk {margin-left:auto; cursor:pointer; font-size:.86rem; font-weight:700; color:#ffc75a; padding:6px 2px; white-space:nowrap;}
.lnk:hover {text-decoration:underline;}

/* Fiche du match */
.fiche {display:none; position:fixed; inset:0; z-index:999990; justify-content:center; align-items:flex-start; padding:3vh 14px; overflow-y:auto; box-sizing:border-box;}
.tg-o:checked ~ .fiche {display:flex;}
.fbg {position:fixed; inset:0; background:rgba(4,7,12,.86); cursor:pointer;}
.fbox {position:relative; width:100%; max-width:980px; background:#0f131c; border:1px solid #232b3a; border-radius:20px; overflow:hidden; box-shadow:0 30px 80px rgba(0,0,0,.6); margin-bottom:3vh;}
.fhead {position:relative; padding:22px 22px 16px; background:repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 2px, transparent 2px 10px), linear-gradient(115deg, var(--ca) 0%, var(--ca) 49%, var(--ch) 51%, var(--ch) 100%);}
.fx {position:absolute; right:14px; top:14px; width:44px; height:44px; border-radius:50%; background:rgba(8,10,16,.75); border:1px solid rgba(255,255,255,.3); color:#fff; display:flex; align-items:center; justify-content:center; cursor:pointer; font-size:1.1rem; z-index:2;}
.frow {display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:12px; padding-right:44px;}
.fteam {display:flex; align-items:center; gap:14px; min-width:0;}
.fteam.r {justify-content:flex-end; text-align:right;}
.fteam b {display:block; font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:2.1rem; line-height:1; text-transform:uppercase; text-shadow:0 2px 6px rgba(0,0,0,.5);}
.fteam small {display:inline-block; color:#eef1f6; font-size:.8rem; margin-top:5px; background:rgba(8,10,16,.55); padding:2px 8px; border-radius:999px;}
.disc.fd {width:84px; height:84px; flex:none;} .disc.fd img {width:62px; height:62px;}
.fchips {display:flex; flex-wrap:wrap; gap:6px; margin-top:14px;}
.fbody {padding:16px 22px 24px;}
.facts {display:flex; flex-wrap:wrap; gap:8px; margin-bottom:6px;}
.facts .cbtn {min-height:42px; font-size:.9rem;}
.fbody .in {overflow-x:auto;}
.pf {margin-top:8px;}

/* Vue Semaine */
.wk {display:grid; grid-template-columns:repeat(auto-fit, minmax(340px, 1fr)); gap:18px; margin:.6rem 0 2rem;}
.wbox {background:#10141e; border:1px solid #1e2533; border-radius:18px; padding:16px 18px;}
.wbox h3 {margin:0 0 10px; font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.4rem; text-transform:uppercase;}
.wrow {display:grid; grid-template-columns:110px minmax(0,1fr) auto; align-items:center; gap:10px; padding:8px 0; border-top:1px solid #1e2533; font-size:.9rem;}
.wrow:first-of-type {border-top:none;}
.wrow .d {color:var(--muted); font-size:.8rem;}
.wrow .m {display:flex; align-items:center; gap:6px; font-weight:700; min-width:0;}
.wrow .m img {width:24px; height:24px;}
.wbox .tg {display:none;}
.ess-head {display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap;}
.tg-w:checked ~ .ess-hid {display:block; border-top:none; padding-top:0;}
.tg-w:checked ~ * .pill-n .on {display:inline;} .tg-w:checked ~ * .pill-n .off {display:none;}

@media (max-width: 640px) {
  .block-container {padding-top:2.2rem;}
  .bb-brand {font-size:1.5rem;}
  .st-key-nav [data-testid="stColumn"] {flex:1 0 108px !important; min-width:108px !important;}
  .nb-t {font-size:1.2rem;}
  .cards {grid-template-columns:1fr; gap:16px;}
  .cart {height:132px;} .disc {width:84px; height:84px;} .disc img {width:62px; height:62px;}
  .fiche {padding:0;} .fbox {border-radius:0; min-height:100vh; margin:0;}
  .fhead {padding:16px 14px 12px;} .fbody {padding:12px 14px 20px;}
  .frow {grid-template-columns:1fr; gap:8px; padding-right:44px;}
  .fteam b {font-size:1.6rem;} .fteam.r {justify-content:flex-start; flex-direction:row-reverse; text-align:left;}
  .frow .clock {justify-self:start;}
}

/* ===== v013 : tableau des scores + carte de la nuit ===== */
.rows {display:grid; grid-template-columns:repeat(auto-fill, minmax(540px, 1fr)); gap:12px; margin-bottom:2rem;}
.mrow {display:grid; grid-template-columns:7px minmax(0,1fr); border-radius:14px; overflow:hidden; border:1px solid #1e2533; height:100%; box-sizing:border-box;
       background:linear-gradient(90deg, var(--ta) 0%, #121722 34%, #121722 66%, var(--th) 100%);}
.mrow .strip {background:#2a3242;}
.mrow.L3 {border-color:rgba(255,220,130,.45); box-shadow:0 0 22px rgba(247,200,80,.16);}
.mrow.L2 {border-color:rgba(235,240,245,.28);}
.mrow.L3 .strip {background:linear-gradient(180deg, #b8860b, #ffe9a3, #f7c948, #fff8dc, #d4a017, #ffe9a3, #b8860b); background-size:100% 300%; animation:holo2 6s linear infinite;}
.mrow.L2 .strip {background:linear-gradient(180deg, #7d8894, #e9eef3, #b9c2cc, #ffffff, #8e99a5, #dfe5ec, #7d8894); background-size:100% 300%; animation:holo2 9s linear infinite;}
.mrow.L1 .strip {background:linear-gradient(180deg, #6e3417, #c4743f, #f0b58a, #b0602d, #6e3417);}
.mrow.L0 .strip {background:#4b5a6e;} .mrow.Lm1 .strip {background:#7c838d;} .mrow.Lm2 .strip {background:#2a2d33;}
.mrow.Laff .strip {background:linear-gradient(180deg, #a8781f, #ffd770, #a8781f);} .mrow.Llive .strip {background:#e03b3b;}
@keyframes holo2 {to {background-position:0 300%;}}
@media (prefers-reduced-motion: reduce) {.mrow .strip {animation:none !important;}}
.mr-in {display:flex; flex-direction:column; gap:8px; padding:10px 14px 10px 12px; min-width:0;}
.mr-top {display:flex; align-items:center; justify-content:space-between; gap:8px; min-height:22px;}
.mr-t {font-size:.8rem; font-weight:600; color:#9aa3b5; white-space:nowrap;}
.mrow .lvl {font-size:.76rem; padding:2px 9px;}
.mrow.L3 .lvl {background:linear-gradient(135deg, #f7c948, #fff4c2, #d4a017); color:#2a1e00;}
.mrow.L2 .lvl {background:linear-gradient(135deg, #dfe5ec, #ffffff, #aeb8c3); color:#16191d;}
.mrow.L1 .lvl {background:linear-gradient(135deg, #b0602d, #f0b58a); color:#2a1206;}
.mrow.L0 .lvl {background:#4b5a6e;} .mrow.Lm1 .lvl {background:#7c838d;} .mrow.Lm2 .lvl {background:#1b1d21; color:#c3c8cf; box-shadow:inset 0 0 0 1px #3a3e45;}
.mrow.Laff .lvl {background:#ffd770; color:#2a1e00;} .mrow.Llive .lvl {background:#d93636;}
.mr-main {display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); grid-template-areas:"a c h"; align-items:center; gap:12px;}
.mr-main .a {grid-area:a;} .mr-main .clock {grid-area:c;} .mr-main .h {grid-area:h; flex-direction:row-reverse; text-align:right;}
.mt {display:flex; align-items:center; gap:12px; min-width:0;}
label.mt {cursor:pointer;}
.mt-n {min-width:0;}
.mt-n small {display:block; font-size:.68rem; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:#9aa3b5; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.mt-n b {display:block; font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.5rem; line-height:1; text-transform:uppercase; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.mt-n b.sm {font-size:1.3rem;} .mt-n b.xs {font-size:1.12rem;}
.mt-l {display:flex; flex-wrap:wrap; align-items:baseline; column-gap:6px; row-gap:1px; min-width:0;} .mt-l b {flex:0 0 auto; min-width:0; max-width:100%;} .mr-main .mt-n {flex:1 1 auto;}
.mt-n .rec, .hero-t .rec {flex:none; font-style:normal; font-family:'Barlow Condensed', sans-serif; font-weight:600; font-size:1rem; color:#9aa3b5; letter-spacing:.02em;}
.hero-t .rec {font-size:.8em;}
.mr-prev.kf {color:#e6e9ef; font-weight:500;}
.disc.dr {width:58px; height:58px; flex:none; background:var(--c, rgba(8,10,16,.5));}
.mt.a .disc.dr {background:var(--ca); box-shadow:0 0 0 3px rgba(255,255,255,.12), 0 0 26px var(--ta), 0 0 34px var(--ta);}
.mt.h .disc.dr {background:var(--ch); box-shadow:0 0 0 3px rgba(255,255,255,.12), 0 0 26px var(--th), 0 0 34px var(--th);}
.disc.dr img {width:42px; height:42px;}
.disc.dr b {font-size:1rem;}
.mr-main .clock {min-width:92px;}
.mr-foot {display:flex; align-items:center; gap:10px; padding-top:8px; border-top:1px solid rgba(255,255,255,.07);}
.mr-prev {flex:1; min-width:0; font-size:.84rem; color:#c3cad6; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.mr-foot .cbtn {flex:none; min-height:30px; padding:0 10px; font-size:.8rem; border-radius:8px;}
.mr-foot .lnk {margin-left:0;}
/* Carte de la nuit */
.hero {display:grid; grid-template-columns:400px minmax(0,1fr); gap:26px; align-items:center; margin:0 0 18px; padding:18px; border-radius:20px;
       background:radial-gradient(600px 220px at 20% 0%, rgba(247,200,80,.10), transparent 70%), #10141e; border:1px solid #1e2533;}
.hero-card .card {height:auto;} .hero-card .ci {height:auto;}
.hero-card .cname {padding-bottom:14px;}
.hero-k {font-size:.78rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:#ffc75a;}
.hero-t {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:2.1rem; line-height:1.05; text-transform:uppercase; margin:4px 0 6px;}
.hero-t span {color:#6f7a8f; font-size:1.5rem;}
.hero-a {font-weight:700; color:#fff; margin-bottom:6px;}
.hero .pts li {font-size:.92rem;}
.hero .cfoot {margin-top:10px;} .hero .cfoot .lnk {margin-left:auto;}
/* Bandeau des nuits : un seul bloc, boutons discrets, nuit choisie en doré */
.st-key-nav {background:#10141e; border:1px solid #1e2533; border-radius:16px; padding:6px;}
.st-key-nav [data-testid="stHorizontalBlock"] {padding-bottom:0;}
.st-key-nav button {background:transparent; border-color:transparent; min-height:44px;}
.st-key-nav button:hover {border-color:#2f3848; background:#161c29;}
.st-key-wk_view button {border-color:#2a3242 !important; background:#161c29 !important;}
.st-key-nav button p {font-size:1.05rem;}
@media (max-width: 760px) {
  .rows {grid-template-columns:1fr;}
  .mr-main {grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"a c" "h c"; gap:6px 10px;}
  .mr-main .h {flex-direction:row; text-align:left;}
  .disc.dr {width:42px; height:42px;} .disc.dr img {width:30px; height:30px;}
  .mt {gap:10px;} .mt-n small {display:none;} .mt-n b {font-size:1.25rem;} .mt-n b.sm {font-size:1.15rem;} .mt-n b.xs {font-size:1.05rem;}
  .mr-prev {white-space:normal; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;}
  .mr-foot {flex-wrap:wrap;}
  .hero {grid-template-columns:1fr; gap:14px; padding:12px;}
  .hero-t {font-size:1.5rem;}
  .disc.dr b {font-size:.72rem;}
  .hero-card .cname b {font-size:1.02rem;} .hero-card .cname b.sm, .hero-card .cname b.xs {font-size:.88rem;}
}

/* ===== Le 5 de la semaine ===== */
.fx-h {margin:.4rem 0 .8rem; padding:18px 20px; border-radius:18px; border:1px solid #1e2533;
       background:radial-gradient(500px 200px at 15% 0%, rgba(247,200,80,.14), transparent 70%), #10141e;}
.fx-k {font-size:.76rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:#ffc75a;}
.fx-t {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:2.2rem; text-transform:uppercase; line-height:1.05;}
.fx-s {color:#c3cad6; font-size:.95rem; margin-top:4px;}
.st-key-fx_go button, .st-key-fx_back button {border-color:#ffc75a; color:#ffc75a;}

/* ===== v016 : le score en grands chiffres, la carte du joueur ===== */
.sn {display:flex; align-items:center; justify-content:center; min-width:62px; height:54px; padding:0 6px; box-sizing:border-box; cursor:pointer;
     font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:2.5rem; line-height:1; letter-spacing:-.01em; color:#fff;
     font-variant-numeric:tabular-nums;}
.sn.empty {cursor:default;}
.sn .sc-hid {display:flex; align-items:center; justify-content:center; width:58px; height:50px; border-radius:12px; color:rgba(255,255,255,.55); font-size:1.9rem;
             background:repeating-linear-gradient(135deg, rgba(255,255,255,.07) 0 6px, rgba(255,255,255,.02) 6px 12px); border:1px solid rgba(255,255,255,.16);
             box-shadow:inset 0 1px 0 rgba(255,255,255,.08); transition:border-color .15s, color .15s;}
.sn:hover .sc-hid, .smid:hover ~ .sn .sc-hid {border-color:#ffc75a; color:#ffc75a;}
.sc-real.l {color:rgba(255,255,255,.42);}
.smid {display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; min-width:70px; cursor:pointer; text-align:center;}
.smid small {font-size:.66rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:#9aa3b5; white-space:nowrap;}
.smid.live small {color:#ff6b6b;}
.smid .sc-tip {font-size:.7rem; font-weight:700; color:#ffc75a; white-space:nowrap; margin:0;}
.smid.pre {cursor:default;} .smid.pre b {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.7rem; line-height:1; color:#fff;}
.smid.pre small {letter-spacing:.06em; text-transform:none; font-weight:600;}
.tg-s:checked ~ * .sc-tip {display:none;}
.mr-main {grid-template-columns:minmax(0,1fr) auto auto auto minmax(0,1fr); grid-template-areas:"a sa sm sh h"; gap:8px;}
.mr-main .sn.a {grid-area:sa;} .mr-main .smid {grid-area:sm;} .mr-main .sn.h {grid-area:sh;}
.cname .score {display:flex; align-items:center; gap:2px; background:rgba(8,10,16,.72); border-radius:14px; padding:2px 4px;}
.cname .score .sn {min-width:48px; height:46px; font-size:2rem;} .cname .score .sn .sc-hid {width:44px; height:40px; font-size:1.5rem;}
.cname .score .smid {min-width:56px;}
.fsc {display:flex; align-items:center; gap:6px; padding:6px 14px; border-radius:16px; background:rgba(8,10,16,.82);}
.fsc .sn {font-size:3.3rem; height:64px; min-width:76px; cursor:default;} .fsc .sc-real {display:inline;}
@media (max-width: 760px) {
  .mr-main {grid-template-columns:minmax(0,1fr) auto; grid-template-areas:"a sa" "h sh"; gap:6px 10px;}
  .mr-main .smid {display:none;}
  .sn {height:44px; min-width:54px; font-size:2rem;} .sn .sc-hid {width:50px; height:40px; font-size:1.5rem;}
  .fsc .sn {font-size:2.4rem; height:52px; min-width:60px;}
  .cname .score .smid {display:none;}
}
/* Carte du joueur (zones chaudes) */
.pm {display:none; position:fixed; inset:0; z-index:1000000; align-items:flex-start; justify-content:center; padding:4vh 14px; overflow-y:auto; box-sizing:border-box;}
.tgp:checked + .pm {display:flex;}
.pm-bg {position:fixed; inset:0; background:rgba(4,7,12,.86); cursor:pointer;}
.pm-box {position:relative; width:100%; max-width:480px; max-height:none; overflow:hidden; padding:0; border-radius:22px; background:#0f131c;
         border:1px solid rgba(255,255,255,.1); box-shadow:0 30px 80px rgba(0,0,0,.6), 0 0 0 4px var(--tk);}
.pm-top {position:relative; display:flex; align-items:center; gap:14px; padding:18px 18px 16px;
         background:radial-gradient(260px 160px at 85% 0%, rgba(255,255,255,.18), transparent 70%), linear-gradient(150deg, var(--tk), #0f131c 115%);}
.pm-x {position:absolute; right:12px; top:12px; width:40px; height:40px; border-radius:50%; display:flex; align-items:center; justify-content:center;
       background:rgba(8,10,16,.55); border:1px solid rgba(255,255,255,.3); color:#fff; cursor:pointer; margin:0;}
.pm-ph {flex:none; width:88px; height:88px; border-radius:50%; overflow:hidden; background:rgba(8,10,16,.4); border:3px solid rgba(255,255,255,.85); display:flex; align-items:flex-end; justify-content:center;}
.pm-ph img {width:120%; height:auto;}
.pm-id {min-width:0; padding-right:40px;}
.pm-team {display:flex; align-items:center; gap:6px; font-size:.78rem; font-weight:700; color:rgba(255,255,255,.85); text-transform:uppercase; letter-spacing:.06em;}
.pm-team img {width:18px; height:18px;}
.pm-name {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:2.1rem; line-height:.95; text-transform:uppercase; color:#fff; margin-top:4px;}
.pm-min {font-size:.82rem; color:rgba(255,255,255,.75); margin-top:4px;}
.pm-tiles {display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:8px; padding:14px 16px 4px;}
.pm-tiles div {text-align:center; padding:8px 4px; border-radius:12px; background:#171c28; border:1px solid #232b3a;}
.pm-tiles b {display:block; font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.9rem; line-height:1; color:#fff;}
.pm-tiles div:first-child b {color:#ffc75a;}
.pm-tiles span {font-size:.68rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:#9aa3b5;}
.pm-sec {display:flex; align-items:baseline; justify-content:space-between; gap:8px; padding:14px 16px 8px;}
.pm-sec span {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.25rem; text-transform:uppercase;}
.pm-sec small {color:#9aa3b5; font-size:.76rem;}
.pm-court {padding:0 16px;}
.court {width:100%; height:auto; display:block; border-radius:14px; box-shadow:0 8px 24px rgba(0,0,0,.35);}
.court .zp {font:800 21px 'Barlow Condensed', sans-serif; fill:#fff; text-anchor:middle; paint-order:stroke; stroke:rgba(20,12,4,.6); stroke-width:4px;}
.court .zm {font:700 13px 'Barlow Condensed', sans-serif; fill:#fff; text-anchor:middle; paint-order:stroke; stroke:rgba(20,12,4,.6); stroke-width:3.5px;}
.pm-leg {display:flex; flex-wrap:wrap; gap:6px 12px; padding:10px 16px 2px; font-size:.74rem; color:#c3cad6; margin:0;}
.pm-leg span {display:inline-flex; align-items:center; gap:5px;}
.pm-leg i {display:inline-block; font-style:normal;}
.pm-leg .dot {width:10px; height:10px; border-radius:50%; background:#1d1a16; box-shadow:0 0 0 2px #fffaf0;}
.pm-leg .x {font-weight:800; color:#c3cad6;}
.pm-leg .sq {width:12px; height:12px; border-radius:3px;}
.pm-leg .sq.hot {background:rgba(214,78,40,.85);} .pm-leg .sq.cold {background:rgba(58,104,186,.85);} .pm-leg .sq.low {background:#b9a888;}
.pm-bars {display:flex; flex-direction:column; gap:10px; padding:14px 16px 18px;}
.pb {display:grid; grid-template-columns:110px minmax(0,1fr) 78px; align-items:center; gap:10px; font-size:.86rem;}
.pb-l {color:#c3cad6;}
.pb-t {position:relative; height:12px; border-radius:6px; background:#1c2230;}
.pb-t i {position:absolute; left:0; top:0; bottom:0; border-radius:6px; background:#d9aa3c;}
.pb-t i.hot {background:#e0562c;} .pb-t i.cold {background:#4a78c2;}
.pb-t b {position:absolute; top:-3px; bottom:-3px; width:2px; background:#fff; border-radius:1px;}
.pb-v {text-align:right; font-weight:800; font-variant-numeric:tabular-nums;} .pb-v small {display:block; font-weight:500; color:#9aa3b5; font-size:.72rem;}
.pb-v.hot {color:#ff9a73;} .pb-v.cold {color:#8ab4ff;}
.pm-note {font-size:.72rem; color:#6f7a8f;}
@media (max-width: 640px) {
  .pm {padding:0;} .pm-box {border-radius:0; min-height:100vh; box-shadow:none;}
  .pm-name {font-size:1.7rem;} .pm-ph {width:72px; height:72px;}
}

/* v016 : place pour les noms */
.cname.two {grid-template-columns:minmax(0,1fr) minmax(0,1fr); padding-bottom:4px;}
.cscore {display:flex; justify-content:center; padding:0 12px 12px; background:rgba(8,10,16,.55);}
.cscore .score {display:flex; align-items:center; gap:4px; background:rgba(8,10,16,.75); border-radius:14px; padding:3px 6px;}
.mr-main {gap:6px;}
.mr-main .disc.dr {width:48px; height:48px;} .mr-main .disc.dr img {width:36px; height:36px;}
.mr-main .mt {gap:9px;}
.mr-main .mt-n b {font-size:1.32rem;} .mr-main .mt-n b.sm {font-size:1.16rem;} .mr-main .mt-n b.xs {font-size:.92rem; letter-spacing:-.02em;}
.mr-main .sn {min-width:52px;} .mr-main .sn .sc-hid {width:50px;}
.mr-main .smid {min-width:58px;}
@media (max-width: 760px) {.mr-main .mt-n b {font-size:1.25rem;} .mr-main .disc.dr {width:42px; height:42px;}
  .mr-main .smid.pre {display:flex; grid-area:sa; grid-row:1 / span 2; align-self:center;} .mr-main .sn.empty {display:none;}}
/* ===== v018 : le récap de la nuit mis en avant ===== */
.nrec {position:relative; margin:.5rem 0 1.2rem; padding:18px 20px; border-radius:20px; overflow:hidden;
       background:radial-gradient(520px 200px at 0% 0%, rgba(247,200,80,.16), transparent 70%),
                  radial-gradient(520px 220px at 100% 100%, rgba(90,130,255,.14), transparent 70%),
                  repeating-linear-gradient(115deg, rgba(255,255,255,.025) 0 2px, transparent 2px 10px), #0f1320;
       border:1px solid rgba(255,215,120,.22); box-shadow:0 14px 34px rgba(0,0,0,.35);}
.nrec .tg {display:none;}
.nr-head {display:flex; align-items:flex-end; justify-content:space-between; gap:14px; flex-wrap:wrap;}
.nr-k {font-size:.76rem; font-weight:800; letter-spacing:.16em; text-transform:uppercase; color:#ffc75a;}
.nr-t {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:2.05rem; line-height:1; text-transform:uppercase; margin:4px 0 8px; color:#fff;}
.nr-s {display:flex; gap:8px; align-items:center; flex-wrap:wrap;}
.nst {display:inline-flex; align-items:center; padding:3px 11px; border-radius:999px; font-size:.78rem; font-weight:800; letter-spacing:.04em; text-transform:uppercase;
      background:rgba(255,255,255,.1); color:#eef1f6; box-shadow:inset 0 0 0 1px rgba(255,255,255,.16);}
.nst.k-live {background:#d93636; color:#fff; box-shadow:none; animation:pulse 2s ease-in-out infinite;}
.nst.k-next {background:rgba(255,199,90,.14); color:#ffd98a; box-shadow:inset 0 0 0 1px rgba(255,199,90,.35);}
@keyframes pulse {50% {opacity:.65;}}
.nr-n {font-size:.86rem; font-weight:600; color:#aab3c4;}
.nr-v {display:flex; gap:8px; flex-wrap:wrap;}
.nr-v .cbtn {min-height:42px; padding:0 16px; font-size:.9rem; font-weight:700; border-radius:12px; color:#fff;
             background:linear-gradient(180deg, rgba(255,255,255,.12), rgba(255,255,255,.04)); border:1px solid rgba(255,255,255,.18);}
.nr-v a.cbtn:not(.fr):not(.ghost) {background:linear-gradient(180deg, #ffd56e, #f0a92e); border-color:#ffd56e; color:#1a1205 !important;}
.nr-v .cbtn.fr {background:linear-gradient(90deg, rgba(0,85,164,.55), rgba(255,255,255,.08) 50%, rgba(239,65,53,.5)); border-color:rgba(255,255,255,.25);}
.nr-v .cbtn.off {opacity:.6;}
.nr-rev {display:inline-flex; align-items:center; gap:10px; margin-top:14px; padding:8px 16px; border-radius:999px; cursor:pointer;
         background:rgba(255,199,90,.08); border:1px solid #6b5520; color:#ffd98a; font-weight:700; font-size:.92rem;}
.nr-rev:hover {background:rgba(255,199,90,.16);}
.nr-rev small {font-weight:500; font-size:.8rem; color:#a8926a; margin-left:4px;}
.nr-rev .on {display:none;}
.tg-n:checked ~ .nr-rev {background:transparent; border-color:#2a3344; color:#c3cad6;}
.tg-n:checked ~ .nr-rev .on {display:inline;} .tg-n:checked ~ .nr-rev .off {display:none;}
.nrec .ess-hid {border-top:none; padding-top:0; margin-top:14px;}
.nt-grid {display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:10px;}
.nt {display:flex; gap:12px; align-items:flex-start; padding:12px 14px; border-radius:14px; background:rgba(8,10,16,.55); border:1px solid rgba(255,255,255,.08);}
.nt-i {font-size:1.6rem; line-height:1; flex:none;}
.nt-k {font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.05rem; text-transform:uppercase; letter-spacing:.03em; color:#ffc75a;}
.nt-b {font-size:.9rem; color:#e6e9ef; line-height:1.4; margin-top:2px;}
.nr-sec {font-size:.76rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; color:#9aa3b5; margin:16px 0 8px;}
.rs-grid {display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:8px;}
.rs {display:flex; flex-direction:column; gap:2px; padding:8px 10px; border-radius:12px; background:rgba(8,10,16,.55); border:1px solid rgba(255,255,255,.08);}
.rs-t {display:flex; align-items:center; gap:8px; color:#8a93a5;}
.rs-t img {width:22px; height:22px; object-fit:contain;}
.rs-t b {font-family:'Barlow Condensed', sans-serif; font-weight:700; font-size:1.05rem; flex:1;}
.rs-t em {font-style:normal; font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.25rem; font-variant-numeric:tabular-nums;}
.rs-t.w {color:#fff;}
@media (max-width: 760px) {
  .nrec {padding:14px;} .nr-t {font-size:1.45rem;} .nr-v {width:100%;} .nr-v .cbtn {flex:1 1 auto; min-height:40px; padding:0 10px; font-size:.84rem;}
  .mr-foot .mr-prev {flex:1 1 100%; -webkit-line-clamp:3;}
  .nt-grid {grid-template-columns:1fr;} .rs-grid {grid-template-columns:repeat(2, minmax(0,1fr));}
}

/* ===== v018 : lignes de match aux couleurs des équipes, comme le match de la nuit ===== */
.mr-main .h .mt-l {justify-content:flex-end;}
@media (max-width: 760px) {.mr-main .h .mt-l {justify-content:flex-start;}}
.mrow {background:linear-gradient(rgba(10,13,20,.52), rgba(10,13,20,.52)),
                  repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 2px, transparent 2px 10px),
                  linear-gradient(105deg, var(--ca) 0%, var(--ca) 49.5%, var(--ch) 50.5%, var(--ch) 100%);
       border-color:rgba(255,255,255,.1); box-shadow:0 10px 24px rgba(0,0,0,.3);}
.mrow .mr-foot {margin:2px -14px -10px -12px; padding:9px 14px 10px 12px; background:rgba(8,10,16,.55); border-top:1px solid rgba(255,255,255,.08);}
.mrow .mt-n small {color:rgba(255,255,255,.7);}
.mrow .mt-n .rec {color:rgba(255,255,255,.72);}
.mrow .mr-t {color:rgba(255,255,255,.75);}
.mrow .disc.dr {box-shadow:0 6px 16px rgba(0,0,0,.45), inset 0 0 0 2px rgba(255,255,255,.25) !important;}
.mrow .sn .sc-hid {background-color:rgba(8,10,16,.55);}
.mrow.L3 {border-color:rgba(255,220,130,.6);} .mrow.L2 {border-color:rgba(235,240,245,.4);} .mrow.L1 {border-color:rgba(196,116,63,.55);}
@media (max-width: 760px) {
  .mrow {background:linear-gradient(rgba(10,13,20,.52), rgba(10,13,20,.52)),
                    repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 2px, transparent 2px 10px),
                    linear-gradient(172deg, var(--ca) 0%, var(--ca) 44%, var(--ch) 46%, var(--ch) 100%);}
}
</style>
"""


def user_zone():
    """Fuseau deviné du navigateur (plus de réglage : ?tz= des anciens liens ignoré)."""
    st.query_params.pop("tz", None)
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
    """Couleur d'équipe lisible sur fond sombre : la principale, éclaircie si elle est trop foncée (violet Lakers...)."""
    t = team(tid)
    for c in (t.get("color"), t.get("alt")):
        if c and 0.12 < _lum(c) < 0.92:
            if _lum(c) < 0.32:
                r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
                k = 0.45
                c = "#%02x%02x%02x" % (round(r + (255 - r) * k), round(g + (255 - g) * k), round(b + (255 - b) * k))
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


# Zones de tir (v018) : 10 zones calées sur les lignes du terrain, faciles à lire (pieds ; panier en (25, 0), coordonnées d'ESPN).
# Raquette = x de 17 à 33 pieds, jusqu'à 13,75 pieds devant le panier ; ligne à 3 points : coins jusqu'à 8,75 pieds, arc de 23,75 pieds.
# (clé, famille, moyenne NBA de réussite)
HOT_ZONES = [
    ("rim", "rim", 0.64), ("paint", "paint", 0.44),
    ("m_l", "mid", 0.41), ("m_c", "mid", 0.42), ("m_r", "mid", 0.41),
    ("c3_l", "three", 0.39), ("w3_l", "three", 0.355), ("t3", "three", 0.355), ("w3_r", "three", 0.355), ("c3_r", "three", 0.39),
]
ZONE_AVG = {k: avg for k, _, avg in HOT_ZONES}
FAMILIES = [("rim", "Près du cercle", 0.64), ("paint", "Raquette", 0.44), ("mid", "Mi-distance", 0.41), ("three", "À 3 points", 0.36)]


def shot_zone(x, y, three):
    if three:
        if y <= 9 and abs(x - 25) >= 20:
            return "c3_l" if x < 25 else "c3_r"
        return "w3_l" if x < 17 else "w3_r" if x > 33 else "t3"
    if math.hypot(x - 25, y) <= 8:
        return "rim"
    if 17 <= x <= 33 and y <= 13.75:
        return "paint"
    return "m_l" if x < 17 else "m_r" if x > 33 else "m_c"


def zone_color(made, att, avg):
    """Couleur d'une zone : rouge = au-dessus de la moyenne NBA de la zone, bleu = en dessous, ocre = dans la moyenne.
    Moins de 3 tirs : pas de couleur (trop peu pour juger)."""
    if att < 3:
        return "rgba(110,95,70,0.10)"
    diff = made / att - avg
    if abs(diff) < 0.04:
        return "rgba(217,170,60,0.42)"
    s = min(1.0, abs(diff) / 0.25)
    return f"rgba(214,78,40,{0.30 + 0.42 * s:.2f})" if diff > 0 else f"rgba(58,104,186,{0.30 + 0.42 * s:.2f})"


def court_svg(shots, uid):
    """Demi-terrain façon parquet clair (10 px par pied, ligne de fond en haut) : 10 zones calées sur les lignes du terrain
    (cercle, raquette, mi-distance gauche/centre/droite, 3 points coin/aile/axe), colorées seulement à partir de 3 tirs,
    pourcentage + réussis/tentés dans chaque zone, et chaque tir (● réussi, ✕ raté) pour voir où le joueur tire."""
    BY, H = 52.5, 400
    stats = {k: [0, 0] for k, _, _ in HOT_ZONES}
    for x, y, made, three in shots:
        z = shot_zone(x, y, three)
        stats[z][1] += 1
        stats[z][0] += 1 if made else 0
    yj, r3 = 140, 237.5
    arc = f"M30,0 L30,{yj} A{r3},{r3} 0 0 0 470,{yj} L470,0"
    cin, cout = f"in{uid}", f"out{uid}"
    # Formes de chaque zone : (svg, découpe éventuelle, position de l'étiquette)
    rim = f'<circle cx="250" cy="{BY}" r="80" fill="{{c}}"/>'
    shapes_def = {
        "rim": (rim, None, (250, BY + 48)),
        "paint": (f'<path d="M170,0 H330 V190 H170 Z M170,{BY} a80,80 0 1 0 160,0 a80,80 0 1 0 -160,0 Z" fill-rule="evenodd" fill="{{c}}"/>', None, (250, 165)),
        "m_l": (f'<rect x="0" y="0" width="170" height="{H}" fill="{{c}}"/>', cin, (100, 120)),
        "m_c": (f'<rect x="170" y="190" width="160" height="{H}" fill="{{c}}"/>', cin, (250, 238)),
        "m_r": (f'<rect x="330" y="0" width="170" height="{H}" fill="{{c}}"/>', cin, (400, 120)),
        "c3_l": (f'<rect x="0" y="0" width="30" height="{yj}" fill="{{c}}"/>', None, None),
        "c3_r": (f'<rect x="470" y="0" width="30" height="{yj}" fill="{{c}}"/>', None, None),
        "w3_l": (f'<rect x="0" y="0" width="170" height="{H}" fill="{{c}}"/>', cout, (72, 300)),
        "t3": (f'<rect x="170" y="0" width="160" height="{H}" fill="{{c}}"/>', cout, (250, 350)),
        "w3_r": (f'<rect x="330" y="0" width="170" height="{H}" fill="{{c}}"/>', cout, (428, 300)),
    }
    shapes, labels = [], []
    for k, _, avg in HOT_ZONES:
        shape, clip, pos = shapes_def[k]
        m, a = stats[k]
        shape = shape.replace("{c}", zone_color(m, a, avg))
        shapes.append(f'<g clip-path="url(#{clip})">{shape}</g>' if clip else shape)
        if not a:
            continue
        if pos is None:  # coins : étiquette verticale
            x0 = 15 if k == "c3_l" else 485
            labels.append(f'<text x="{x0}" y="70" class="zm" transform="rotate(-90 {x0} 70)">{m}/{a}</text>')
        elif a >= 3:
            labels.append(f'<text x="{pos[0]}" y="{pos[1] - 3:.0f}" class="zp">{round(m / a * 100)}%</text>'
                          f'<text x="{pos[0]}" y="{pos[1] + 13:.0f}" class="zm">{m}/{a}</text>')
        else:
            labels.append(f'<text x="{pos[0]}" y="{pos[1] + 5:.0f}" class="zm">{m}/{a}</text>')
    marks = []
    for x, y, made, three in shots:
        X, Y = x * 10, BY + y * 10
        if Y > H - 6:
            continue
        if made:
            marks.append(f'<circle cx="{X:.0f}" cy="{Y:.0f}" r="6.5" fill="#1d1a16" stroke="#fffaf0" stroke-width="2"/>')
        else:
            marks.append(f'<path d="M{X - 5:.0f},{Y - 5:.0f} L{X + 5:.0f},{Y + 5:.0f} M{X + 5:.0f},{Y - 5:.0f} L{X - 5:.0f},{Y + 5:.0f}" '
                         f'stroke="#3b2f22" stroke-width="2.6" stroke-linecap="round"/>')
    # Seuls traits ajoutés aux lignes du terrain : le prolongement des côtés de la raquette (séparation gauche / centre / droite)
    seps = f'<path d="M170,190 V{H} M330,190 V{H}" stroke="#fffaf0" stroke-width="1.5" stroke-dasharray="5 5" stroke-opacity=".7"/>'
    svg = (f'<svg viewBox="0 0 500 {H}" class="court" role="img" aria-label="Carte de tirs : 10 zones et chaque tir">'
           f'<defs><clipPath id="{cin}"><path d="{arc} Z"/></clipPath>'
           f'<clipPath id="{cout}"><path d="M0,{yj} L30,{yj} A{r3},{r3} 0 0 0 470,{yj} L500,{yj} L500,{H} L0,{H} Z"/></clipPath>'
           f'<pattern id="pq{uid}" width="500" height="40" patternUnits="userSpaceOnUse"><rect width="500" height="40" fill="#ead3a6"/>'
           f'<rect y="20" width="500" height="20" fill="#e4cb9b"/></pattern></defs>'
           f'<rect x="0" y="0" width="500" height="{H}" fill="url(#pq{uid})"/>'
           + "".join(shapes) + seps
           + f'<g fill="none" stroke="#fffaf0" stroke-width="3"><path d="{arc}"/><rect x="170" y="0" width="160" height="190"/>'
           f'<circle cx="250" cy="{BY}" r="80" stroke-width="2"/>'
           f'<path d="M190,190 A60,60 0 0 0 310,190"/><line x1="220" y1="40" x2="280" y2="40"/><rect x="1.5" y="1.5" width="497" height="{H - 3}"/></g>'
           f'<circle cx="250" cy="{BY}" r="7.5" fill="none" stroke="#c4461a" stroke-width="3"/>'
           + "".join(marks) + "".join(labels) + "</svg>")
    fam = {f: [0, 0] for f, _, _ in FAMILIES}
    for k, f, _ in HOT_ZONES:
        fam[f][0] += stats[k][0]
        fam[f][1] += stats[k][1]
    return svg, fam


def shot_modal(g, r, tid, shots, mid):
    """Carte du joueur : en-tête aux couleurs de l'équipe, grosses stats, carte de tirs, barres comparées à la moyenne NBA."""
    svg, fam = court_svg(shots, mid)
    t = team(tid)
    st_ = r["stats"]
    tiles = [(st_.get("PTS", "0"), "Points"), (st_.get("REB", "0"), "Rebonds"), (st_.get("AST", "0"), "Passes"),
             (st_.get("FG", "0-0").replace("-", "/"), "Au tir")]
    bars = []
    for k, label, avg in FAMILIES:
        m, a = fam[k]
        if not a:
            continue
        p = m / a
        cls = "hot" if p >= avg + 0.05 else "cold" if p <= avg - 0.05 else ""
        bars.append(f"<div class='pb'><span class='pb-l'>{label}</span><span class='pb-t'><i class='{cls}' style='width:{max(p * 100, 2):.0f}%'></i>"
                    f"<b style='left:{avg * 100:.0f}%' title='Moyenne NBA {round(avg * 100)} %'></b></span>"
                    f"<span class='pb-v {cls}'>{round(p * 100)} %<small>{m}/{a}</small></span></div>")
    photo = f"https://a.espncdn.com/i/headshots/nba/players/full/{r['id']}.png"
    made = sum(1 for s in shots if s[2])
    return (f"<div class='pm'><label for='{mid}' class='pm-bg'></label><div class='pm-box' style='--tc:{esc(team_color(tid))};--tk:{esc(t['color'])}'>"
            f"<div class='pm-top'><label for='{mid}' class='pm-x' title='Fermer'>✕</label>"
            f"<div class='pm-ph'><img src='{photo}' alt='' loading='lazy' onerror=\"this.style.display='none'\"></div>"
            f"<div class='pm-id'><div class='pm-team'>{logo(tid, 18)} {esc(t['full'] or t['name'])}{' · titulaire' if r.get('starter') else ''}</div>"
            f"<div class='pm-name'>{esc(r['name'])}</div><div class='pm-min'>{esc(st_.get('MIN', ''))} minutes</div></div></div>"
            "<div class='pm-tiles'>" + "".join(f"<div><b>{esc(v)}</b><span>{lab}</span></div>" for v, lab in tiles) + "</div>"
            f"<div class='pm-sec'><span>Carte de tirs</span><small>{made}/{len(shots)} hors lancers francs · 10 zones</small></div>"
            f"<div class='pm-court'>{svg}</div>"
            "<div class='pm-leg'><span><i class='dot'></i>Réussi</span><span><i class='x'>✕</i>Raté</span>"
            "<span><i class='sq hot'></i>Au-dessus de la moyenne NBA</span><span><i class='sq cold'></i>En dessous</span>"
            "<span><i class='sq low'></i>Moins de 3 tirs</span></div>"
            f"<div class='pm-bars'>{''.join(bars)}<div class='pm-note'>Trait blanc : moyenne NBA de la zone.</div></div>"
            "</div></div>")


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


RARITY = {3: "L3", 2: "L2", 1: "L1", 0: "L0", -1: "Lm1", -2: "Lm2"}


def _rgb(c):
    try:
        return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
    except (ValueError, TypeError, IndexError):
        return (128, 128, 128)


def _dist(c1, c2):
    return sum((x - y) ** 2 for x, y in zip(_rgb(c1), _rgb(c2))) ** 0.5


def _shade(c, k):
    """Assombrit (k < 0) ou éclaircit (k > 0) une couleur."""
    return "#%02x%02x%02x" % tuple(round(x + (255 - x) * k) if k > 0 else round(x * (1 + k)) for x in _rgb(c))


def card_colors(ta, th):
    """Couleurs des deux moitiés de la carte. Si les deux équipes ont des couleurs trop proches (deux rouges, deux noirs...),
    l'équipe à l'extérieur prend sa 2e couleur, sinon l'équipe à domicile, sinon on assombrit nettement les visiteurs."""
    ca, ch = ta["color"], th["color"]
    if _dist(ca, ch) >= 110:
        return ca, ch
    for alt_a, alt_h in ((ta.get("alt"), ch), (ca, th.get("alt"))):
        if _dist(alt_a or "", alt_h or "") >= 110 and 0.06 < _lum(alt_a or "#808080") < 0.8 and 0.06 < _lum(alt_h or "#808080") < 0.8:
            return alt_a, alt_h
    return _shade(ca, -0.55) if _lum(ca) > 0.2 else _shade(ca, 0.35), ch


def name_cls(t):
    """Taille du nom sur la carte : les noms longs (Timberwolves, Trail Blazers) en plus petit, pour tenir en entier."""
    n = len(t["name"])
    return "xs" if n >= 12 else "sm" if n >= 9 else ""


def card_point(points):
    """La phrase d'avant-match la plus parlante (favori ou star), sinon la première."""
    for p in points:
        if p.startswith(("💰", "⭐", "🏆")):
            return p
    return points[0] if points else ""


def game_card(g, ctx, hero=False):
    """Une carte de match façon carte à collectionner (HTML pur).
    Face : grands logos en diagonale sur les couleurs des équipes, noms, afficheur façon « play clock » (clic = score), avant-match.
    Cadre = rareté selon la note (gris → légendaire doré). « Stats et détails » ouvre la fiche avec le score."""
    gid, zone, idx = g["id"], ctx["zone"], ctx["idx"]
    h, a = g["home"], g["away"]
    th, ta = team(h["id"]), team(a["id"])
    summ = ctx["summ"].get(gid)
    pre = pre_info(g, summ)
    tip = parse_dt(g["utc"])
    local = tip.astimezone(ZONES[zone]) if tip else None
    fav = th["abbr"] in ctx["favs"] or ta["abbr"] in ctx["favs"]
    w = ctx["watch"].get(gid)
    played = g["state"] != "pre"
    ca, ch = card_colors(ta, th)

    if w:
        rar = RARITY[w[0]]
    elif g["state"] == "in":
        rar = "Llive"
    elif gid == ctx.get("affiche"):
        rar = "Laff"
    else:
        rar = "Lpre"

    chips = []
    if w:
        icon, label, _ = WATCH_LEVELS[w[0]]
        chips.append(f"<span class='lvl'>{icon} {esc(label)}</span>")
    elif gid == ctx.get("affiche"):
        chips.append("<span class='lvl'>⭐ L'affiche</span>")
    if g["state"] == "in":
        chips.append("<span class='lvl'>● En direct</span>")
    if g["season_type"] == 3:
        chips.append("<span class='cpill'>🏆 Play-offs</span>")
    if fav:
        chips.append("<span class='cpill star'>⭐</span>")
    when = fr_hour(local) if local else ""
    if local and zone != "Paris" and local.date() != g["day"]:
        when += " · " + fr_short(local.date())

    # Le score : un grand chiffre à côté de chaque équipe. Caché, c'est une case « ? » qu'on touche pour le révéler.
    hs, as_ = h["score"], a["score"]
    if not played:
        sa = sh = "<span class='sn empty'></span>"
        sm = ("<span class='smid'><b>Reporté</b></span>" if g["status"] == "STATUS_POSTPONED"
              else f"<span class='smid pre'><b>{esc(fr_hour(local)) if local else '?'}</b><small>{esc(watch_on(g, ctx.get('pays', 'FR'))[0])}</small></span>")
        real_big = ""
    else:
        live = g["state"] == "in"
        lab = "● En direct" if live else "Final"
        win_a = (as_ or 0) > (hs or 0)

        def num(v, won, cls):
            v = "–" if v is None else v
            dim = " l" if not live and not won else ""
            return (f"<label for='s{gid}' class='sn {cls}' title='Voir / cacher le score'><span class='sc-hid'>?</span>"
                    f"<span class='sc-real{dim}'>{v}</span></label>")
        sa, sh = num(as_, win_a, "a"), num(hs, not win_a, "h")
        sm = (f"<label for='s{gid}' class='smid{' live' if live else ''}'><small>{lab}</small>"
              f"<span class='sc-tip'>👁 voir le score</span></label>")
        real_big = (f"<div class='fsc'><span class='sn a'><span class='sc-real{'' if live or win_a else ' l'}'>{'–' if as_ is None else as_}</span></span>"
                    f"<span class='smid'><small>{lab}</small></span>"
                    f"<span class='sn h'><span class='sc-real{'' if live or not win_a else ' l'}'>{'–' if hs is None else hs}</span></span></div>")
    clock = f"<div class='score'>{sa}{sm}{sh}</div>"

    def disc(tid, cls):
        url = team(tid)["logo"]
        img = f"<img src='{esc(url)}' alt='{esc(team(tid)['name'])}' loading='lazy'>" if url else f"<b>{esc(team(tid)['abbr'])}</b>"
        return f"<div class='disc {cls}'>{img}</div>"

    # Avant-match : sans spoil, donc sur la carte
    points = preview_points(g, idx, pre)
    ai = None
    if ctx["ai"] and (g["state"] == "pre" or disk_get(f"ai_preview_{gid}.json")):
        ai = ai_points("preview", g, ai_material(g, summ, points))
    shown = (ai or points)[:5]

    # Vidéos
    vid_btns = []
    if g["state"] == "post":
        v, x = ctx["vids"].get(gid, (None, None))
        if v:
            d = dur(v, ctx["durs"])
            vid_btns.append(f"<a class='cbtn main' href='{yt_url(v)}' target='_blank'>▶ Résumé{' · ' + d if d else ''}</a>")
        else:
            vid_btns.append(f"<a class='cbtn ghost' href='{yt_search_url(g)}' target='_blank' title='Pas de résumé visible dans ton pays pour l’instant : recherche sur YouTube'>🔎 Chercher un résumé</a>")
        if x:
            d = dur(x, ctx["durs"])
            vid_btns.append(f"<a class='cbtn fr' href='{yt_url(x)}' target='_blank'><span class='frf'></span> NBA Extra{' · ' + d if d else ''}</a>")

    art = f"{disc(a['id'], 'da')}<div class='at'>@</div>{disc(h['id'], 'dh')}"
    art = f"<label for='o{gid}' class='cart' title='Avant-match complet'>{art}</label>" if not played else f"<div class='cart'>{art}</div>"
    prev = "<ul class='cprev'>" + "".join(f"<li>{esc(p)}</li>" for p in shown[:3]) + "</ul>" if shown else ""
    more = "Stats et détails ›" if played else "Avant-match complet ›"
    face_head = (f"<div class='card {rar}'><div class='ci' style='--ca:{esc(ca)};--ch:{esc(ch)}'>"
                 f"<div class='ctop'><div class='chips'>{''.join(chips)}</div>"
                 + (f"<span class='cpill'>{esc(when)}</span>" if played and when else "") + "</div>"
                 f"{art}"
                 f"<div class='cname two'><b class='{name_cls(ta)}'>{esc(ta['name'])}</b><b class='r {name_cls(th)}'>{esc(th['name'])}</b></div>"
                 f"<div class='cscore'>{clock}</div>")

    # Ligne du tableau des scores : bandeau de rareté, logos avec halo, ville + nom, afficheur, avant-match, résumé, stats
    def city(t):
        full, name = t.get("full") or "", t["name"]
        return full[: -len(name)].strip() if full.endswith(name) and full != name else ""

    def rgba(c, al):
        r, g_, b = _rgb(c)
        return f"rgba({r},{g_},{b},{al})"

    recs = {s_["id"]: team_record(idx, s_["id"], g["day"], g["season"]) for s_ in (a, h)}

    def side(s_, t, cls):
        r = recs[s_["id"]]
        rec_html = f"<i class='rec'>({esc(r)})</i>" if r else ""
        inner = (f"{disc(s_['id'], 'dr')}<div class='mt-n'><small>{esc(city(t))}</small>"
                 f"<span class='mt-l'><b class='{name_cls(t)}'>{esc(t['name'])}</b>{rec_html}</span></div>")
        return (f"<label for='o{gid}' class='mt {cls}' title='Avant-match complet'>{inner}</label>" if not played
                else f"<div class='mt {cls}'>{inner}</div>")
    short = key_fact(g, idx, pre)
    row = (f"<div class='mrow {rar}' style='--ta:{rgba(ca, .3)};--th:{rgba(ch, .3)};--ca:{esc(ca)};--ch:{esc(ch)}'><div class='strip'></div><div class='mr-in'>"
           f"<div class='mr-top'><div class='chips'>{''.join(chips)}</div><span class='mr-t'>{esc(when) if played else esc(watch_on(g, ctx.get('pays', 'FR'))[0])}</span></div>"
           f"<div class='mr-main'>{side(a, ta, 'a')}{sa}{sm}{sh}{side(h, th, 'h')}</div>"
           f"<div class='mr-foot'><span class='mr-prev kf' title='{esc(short)}'>{esc(short)}</span>{''.join(vid_btns[:1])}"
           f"<label for='o{gid}' class='lnk'>{'Stats ›' if played else 'Avant-match ›'}</label></div></div></div>")

    # « Le match de la nuit » : le meilleur match en grande carte (ou l'affiche avant les matchs)
    hero_html = ""
    if hero:
        def hrec(s_):
            return f" <i class='rec'>({esc(recs[s_['id']])})</i>" if recs[s_["id"]] else ""
        kick = "Le match de la nuit" if w else "L'affiche de la nuit"
        sub = WATCH_LEVELS[w[0]][2] if w else card_point(shown)
        hero_html = (f"<div class='hero'><div class='hero-card'>{face_head}</div></div></div>"
                     f"<div class='hero-txt'><div class='hero-k'>{kick}</div>"
                     f"<div class='hero-t'>{esc(ta['full'] or ta['name'])}{hrec(a)} <span>@</span> {esc(th['full'] or th['name'])}{hrec(h)}</div>"
                     f"<div class='hero-a'>{esc(sub)}</div><ul class='pts'>" + "".join(f"<li>{esc(p)}</li>" for p in ([short] if short else []) + [p for p in shown if not same_topic(p, short)][:3]) + "</ul>"
                     f"<div class='cfoot'>{''.join(vid_btns)}<label for='o{gid}' class='lnk'>{'Stats et détails ›' if played else 'Avant-match complet ›'}</label></div></div></div>")

    # Fiche du match. Après le match, l'ouvrir = vouloir le score : il y est directement.
    def rec(s):
        f = team_form(idx, s["id"], g["day"], g["season"])
        rank = ctx["ranks"].get(s["id"])
        return (f"{f['w']}-{f['l']}" if f["n"] else f"{f['prev_w']}-{f['prev_l']} en 2025-26") + (f", {rank}e de conf." if rank else "")

    pts_html = "<ul class='pts'>" + "".join(f"<li>{esc(p)}</li>" for p in shown) + "</ul>" if shown else ""
    venue = esc(g["venue"]) + (f", {esc(g['city'])}" if g["neutral"] and g["city"] else "")
    stats = ""
    if played and summ:
        parts = [quarters_html(g)]
        if g["state"] == "post" and g["completed"]:
            rp = recap_points(g, summ, ctx["idx"])
            ai_r = ai_points("recap", g, ai_material(g, summ, rp)) if ctx["ai"] and (summ.get("article") or {}).get("type") == "Recap" else None
            parts.append("<div class='sec'>Ce qu'il faut retenir</div><ul class='pts'>" + "".join(f"<li>{esc(p)}</li>" for p in (ai_r or rp)) + "</ul>"
                         + ("<div class='ai'>✨ Écrit par Claude d'après le compte rendu AP</div>" if ai_r else ""))
            if w and w[1]:
                icon, label, _ = WATCH_LEVELS[w[0]]
                parts.append(f"<div class='note'>{icon} {esc(label)} : {esc(', '.join(w[1]))}.</div>")
        elif g["state"] == "in":
            parts.append(f"<div class='note'>{esc(g['detail'])}</div>")
        worm = worm_svg(g, summ)
        if worm:
            parts.append("<div class='sec'>Le match en un coup d'œil</div>" + worm)
        parts.append(f"<div class='sec'>Feuille de match</div><div class='in'>{box_html(g, summ)}</div>")
        stats = f"<div class='panel-s'>{''.join(parts)}</div>"
    fiche = (f"<div class='fiche{' post' if played else ''}'><label for='o{gid}' class='fbg' title='Fermer'></label><div class='fbox'>"
             f"<div class='fhead {rar}' style='--ca:{esc(ca)};--ch:{esc(ch)}'>"
             f"<label for='o{gid}' class='fx' title='Fermer'>✕</label>"
             f"<div class='frow'><div class='fteam'>{disc(a['id'], 'fd')}<div><b>{esc(ta['name'])}</b><small>{esc(rec(a))} · extérieur</small></div></div>"
             f"{real_big or clock}"
             f"<div class='fteam r'><div><b>{esc(th['name'])}</b><small>domicile · {esc(rec(h))}</small></div>{disc(h['id'], 'fd')}</div></div>"
             f"<div class='fchips'>{''.join(chips)}<span class='cpill'>{esc(when)}{' · ' + venue if venue else ''}</span></div></div>"
             f"<div class='fbody'>" + (f"<div class='facts'>{''.join(vid_btns)}</div>" if vid_btns else "")
             + f"{stats}<div class='sec'>Avant le match</div>{pts_html}<div class='pf'>{form_html(g, idx)}</div></div></div></div>")

    checked = " checked" if ctx["show_all"] else ""
    return (f"<div class='gc{' gh' if hero else ''}' id='g{gid}'>"
            f"<input type='checkbox' class='tg tg-s' id='s{gid}'{checked}><input type='checkbox' class='tg tg-o' id='o{gid}'{' checked' if ctx.get('open') == gid else ''}>"
            f"{hero_html or row}{fiche}</div>")


def night_state(games, zone, now=None):
    """État d'une nuit : (clé, texte). clé = none / done / live / next."""
    if not games:
        return "none", "Pas de match"
    states = [g["state"] for g in games]
    n = len(games)
    if all(s == "post" for s in states):
        return "done", "Terminée"
    if all(s == "pre" for s in states):
        if all(g["status"] == "STATUS_POSTPONED" for g in games):
            return "done", "Reportée"
        first = min((parse_dt(g["utc"]) for g in games if g["utc"]), default=None)
        now = now or datetime.now(timezone.utc)
        if first and first - now < timedelta(hours=20):
            return "next", f"À venir · {fr_hour(first.astimezone(ZONES[zone]))}"
        return "next", f"{n} match{'s' if n > 1 else ''}"
    return "live", f"En cours · {states.count('post')}/{n} terminés"


def night_essentials(day, games, ctx):
    """L'essentiel de la nuit : (partie sans spoil, liste des infos clés à cacher tant que les scores sont cachés)."""
    watch, summs, idx = ctx["watch"], ctx["summ"], ctx["idx"]
    done = [g for g in games if g["state"] == "post" and g["completed"] and g["home"]["score"] is not None]
    # Sans spoil : combien de matchs de chaque niveau
    counts = defaultdict(int)
    for g in done:
        if watch.get(g["id"]):
            counts[watch[g["id"]][0]] += 1
    safe = " · ".join(f"{counts[lv]} {WATCH_LEVELS[lv][0]}" for lv in sorted(counts, reverse=True))
    facts = []
    if not done:
        return safe, facts
    name = lambda tid: team(tid)["name"]

    def res(g):
        h, a = g["home"], g["away"]
        win, lose = (h, a) if h["score"] > a["score"] else (a, h)
        return win, lose
    # Grosses perfs de la nuit
    perfs = []
    for g in done:
        for tid, rows in ((summs.get(g["id"]) or {}).get("box") or {}).items():
            for r in rows:
                if not r["dnp"] and r["stats"]:
                    perfs.append((game_score(r["stats"]), r, tid))
    perfs.sort(key=lambda x: -x[0])
    if perfs:
        facts.append("🔥 Les grosses perfs : " + " ; ".join(f"{r['name']} ({name(tid)}) {stat_line(r['stats'])}" for _, r, tid in perfs[:3]) + ".")
    # La surprise : le favori le plus net qui a perdu
    upsets = []
    for g in done:
        pre = pre_info(g, summs.get(g["id"])) or {}
        m = re.match(r"([A-Z]{2,4})\s*-([\d.]+)", pre.get("line") or "")
        if m:
            win, lose = res(g)
            if team(lose["id"])["abbr"] == m.group(1):
                upsets.append((float(m.group(2)), win, lose))
    if upsets:
        sp, win, lose = max(upsets, key=lambda x: x[0])
        facts.append(f"😮 La surprise : {name(win['id'])} bat {name(lose['id'])} {win['score']}-{lose['score']}, alors que {name(lose['id'])} était favori de {fr_num(sp)} pts.")
    # Le plus serré, prolongations, la plus belle remontée, le plus gros écart
    ots = [g for g in done if max(len(g["home"]["lines"]), len(g["away"]["lines"])) > 4]
    tight = min(done, key=lambda g: abs(g["home"]["score"] - g["away"]["score"]))
    win, lose = res(tight)
    if ots:
        facts.append("⏱️ Prolongation : " + " ; ".join(f"{name(res(g)[0]['id'])} bat {name(res(g)[1]['id'])} {res(g)[0]['score']}-{res(g)[1]['score']}" for g in ots) + ".")
    elif win["score"] - lose["score"] <= 5:
        facts.append(f"🎯 Le plus serré : {name(win['id'])} bat {name(lose['id'])} {win['score']}-{lose['score']}.")
    comebacks = []
    for g in done:
        s = summs.get(g["id"])
        if s:
            _, max_h, max_a, _ = flow(s)
            win, lose = res(g)
            comebacks.append((max_a if win is g["home"] else max_h, win, lose))
    if comebacks:
        deficit, win, lose = max(comebacks, key=lambda x: x[0])
        if deficit >= 12:
            facts.append(f"🔄 La remontée : {name(win['id'])} revient de {deficit} points et bat {name(lose['id'])} {win['score']}-{lose['score']}.")
    big = max(done, key=lambda g: abs(g["home"]["score"] - g["away"]["score"]))
    win, lose = res(big)
    if win["score"] - lose["score"] >= 20:
        facts.append(f"💥 La correction : {name(win['id'])} écrase {name(lose['id'])} {win['score']}-{lose['score']}.")
    # Séries en cours après la nuit
    streaks = []
    for g in done:
        for side in ("home", "away"):
            f = team_form(idx, g[side]["id"], day + timedelta(days=1), g["season"])
            if any(m[0] == day for m in f["last"]) and abs(f["streak"]) >= 4:
                streaks.append(f"{name(g[side]['id'])} {streak_text(f['streak'])}")
    if streaks:
        facts.append("📈 Les séries : " + " ; ".join(streaks[:4]) + ".")
    # Tous les résultats
    facts.append("📋 Les résultats : " + " · ".join(f"{team(g['away']['id'])['abbr']} {g['away']['score']}-{g['home']['score']} {team(g['home']['id'])['abbr']}" for g in done) + ".")
    return safe, facts[:7]


def night_short_title(day, zone):
    """« Nuit du sam. 24 au dim. 25 oct. » (Paris) ou « Samedi 24 octobre » (Montréal)."""
    if zone != "Paris":
        return fr_long(day).capitalize()
    nxt = day + timedelta(days=1)
    return f"Nuit du {JOURS[day.weekday()][:3]}. {'1er' if day.day == 1 else day.day} au {JOURS[nxt.weekday()][:3]}. {'1er' if nxt.day == 1 else nxt.day} {MOIS_COURT[nxt.month - 1]}"


def night_html(day, games, ctx, today):
    """Barre fine de la nuit : titre et état à gauche ; vidéos de la nuit et « Infos de la nuit » (cachées) à droite."""
    zone = ctx["zone"]
    key, state = night_state(games, zone)
    n = len(games)

    pills = []
    show_day = day + timedelta(days=1)
    show_time = datetime.combine(show_day, datetime.min.time(), ZONES["Paris"]).replace(hour=12, minute=45)
    v = ctx["show"]
    if v:
        d = dur(v, ctx["durs"])
        pills.append(f"<a class='cbtn fr' href='{yt_url(v)}' target='_blank' title=\"L'émission de beIN SPORTS sur cette nuit\"><span class='frf'></span> NBA Extra{' · ' + d if d else ''}</a>")
    elif key != "none":
        now = datetime.now(ZONES["Paris"])
        tipx = (f"En direct à {fr_hour(show_time.astimezone(ZONES[zone]))} sur beIN SPORTS, replay vers 15h-17h (Paris)" if now < show_time
                else "Replay YouTube en général entre 15h et 17h (Paris)" if now < show_time + timedelta(hours=10) else "Pas trouvé sur YouTube")
        pills.append(f"<span class='cbtn off' title='{esc(tipx)}'><span class='frf'></span> NBA Extra · bientôt</span>")
    recap = ctx["recap"]
    if recap:
        d = dur(recap, ctx["durs"])
        pills.append(f"<a class='cbtn' href='{yt_url(recap)}' target='_blank' title='Tous les matchs, NBA, en anglais'>▶ Résumé de la nuit{' · ' + d if d else ''}</a>")
    elif key == "done":
        q = f"NBA nightly recap {MONTHS_EN[day.month - 1].title()} {day.day}, {day.year}"
        pills.append(f"<a class='cbtn ghost' href='https://www.youtube.com/results?search_query={requests.utils.quote(q)}' target='_blank'>🔎 Résumé de la nuit</a>")

    _, facts = night_essentials(day, games, ctx)
    nid = f"n{day.isoformat()}"
    checked = " checked" if ctx["show_all"] else ""
    st_cls = {"done": "Terminée", "live": "En cours", "next": "À venir", "none": "Pas de match"}[key]
    detail = {"done": f"{n} match{'s' if n > 1 else ''}", "live": state.replace("En cours · ", ""),
              "next": f"{n} match{'s' if n > 1 else ''}" + (f" · 1er à {state.split('· ')[-1]}" if state.startswith("À venir ·") else ""),
              "none": ""}[key]
    head = (f"<div class='nr-head'><div class='nr-l'><div class='nr-k'>{'Le récap de la nuit' if facts else 'La nuit'}</div>"
            f"<div class='nr-t'>{esc(night_short_title(day, zone))}</div>"
            f"<div class='nr-s'><span class='nst k-{key}'>{'● ' if key == 'live' else '✓ ' if key == 'done' else ''}{st_cls}</span>"
            + (f"<span class='nr-n'>{esc(detail)}</span>" if detail else "") + "</div></div>"
            f"<div class='nr-v'>{''.join(pills)}</div></div>")
    if not facts:
        return f"<div class='nrec'>{head}</div>"

    # Le récap caché : une tuile par info, les résultats en petits tableaux de score
    tiles = []
    for f in facts:
        if f.startswith("📋"):
            continue
        m = re.match(r"^(\S+)\s+(.*?)\s:\s(.*)$", f)
        ico, title, body = (m.group(1), m.group(2), m.group(3)) if m else ("•", "", f)
        tiles.append(f"<div class='nt'><div class='nt-i'>{ico}</div><div><div class='nt-k'>{esc(title)}</div><div class='nt-b'>{esc(body)}</div></div></div>")
    done = [g for g in games if g["state"] == "post" and g["home"]["score"] is not None]
    res = []
    for g in done:
        a, h = g["away"], g["home"]
        wa = (a["score"] or 0) > (h["score"] or 0)
        def tm(s_, won):
            t = team(s_["id"])
            img = f"<img src='{esc(t['logo'])}' alt=''>" if t["logo"] else ""
            return f"<span class='rs-t{' w' if won else ''}'>{img}<b>{esc(t['abbr'])}</b><em>{s_['score']}</em></span>"
        res.append(f"<div class='rs'>{tm(a, wa)}{tm(h, not wa)}</div>")
    results = (f"<div class='nr-sec'>Les résultats</div><div class='rs-grid'>{''.join(res)}</div>") if res else ""
    hidden = (f"<div class='ess-hid'><div class='nt-grid'>{''.join(tiles)}</div>{results}</div><!--fin-ess-->")
    reveal = (f"<label for='{nid}' class='nr-rev'><span class='off'>👁 Révéler le récap de la nuit<small>Résultats, joueurs en feu, surprises, séries</small></span>"
              f"<span class='on'>🙈 Cacher le récap</span></label>")
    return f"<div class='nrec'><input type='checkbox' class='tg tg-n' id='{nid}'{checked}>{head}{reveal}{hidden}</div>"


def ai_material(g, summ, points):
    th, ta = team(g["home"]["id"]), team(g["away"]["id"])
    art = (summ or {}).get("article") or {}
    lines = [f"Match : {ta['full']} chez {th['full']}.", "Infos calculées :"] + [f"- {p}" for p in points]
    if art.get("text"):
        lines += ["", f"Article AP ({art.get('type')}) : {art.get('headline')}", art["text"][:6000]]
    return "\n".join(lines)


KEEP = ("nba_fav", "nba_opt", "nba_hello", "nba_id")  # réglages aussi copiés dans le stockage du navigateur (restaurés si le cookie saute)


def set_cookie(name, value):
    """Écrit un cookie (et une copie dans localStorage pour les réglages). L'ordre est gardé pour toute la visite et réécrit
    à chaque fin de page (`finish_run`) : s'il a été coupé par un changement de page, il passe au tour suivant."""
    keep = f"try {{ parent.localStorage.setItem('{name}', '{value}'); }} catch (e) {{}}" if name in KEEP else ""
    run_js(f"<script>parent.document.cookie='{name}={value}; path=/; max-age=31536000; SameSite=Lax';{keep}</script>")
    try:
        st.session_state.setdefault("_cookies", {})[name] = value
    except Exception:
        pass


def run_js(code):
    """Petit script invisible (cookies, rechargement, clics). st.iframe remplace components.html dans les Streamlit récents."""
    if hasattr(st, "iframe"):
        st.iframe(code, height=1)
    else:
        components.html(code, height=0)


def season_opening(schedule):
    """Premier jour de la saison régulière (début de la semaine 1)."""
    reg = [g["day"] for g in schedule if g.get("kind") == "R"]
    return min(reg) if reg else None


def week_of(d, opening):
    """Semaine NBA (lundi → dimanche, comme pour le joueur de la semaine) : (lundi, numéro ou None)."""
    monday = d - timedelta(days=d.weekday())
    if not opening or d < opening:
        return monday, None
    return monday, (monday - (opening - timedelta(days=opening.weekday()))).days // 7 + 1


def night_label(d, zone):
    """« Dim. 25 → 26 » à Paris (la nuit du dimanche au lundi), « Dim. 25 » à Montréal (le soir) : court, pour tenir dans le bouton."""
    j = JOURS[d.weekday()][:3].capitalize()
    if zone != "Paris":
        return f"{j}. {d.day}"
    nxt = d + timedelta(days=1)
    return f"{j}. {d.day} → {'1er' if nxt.day == 1 else nxt.day}"


def short_date(d):
    return f"{JOURS[d.weekday()][:3]}. {'1er' if d.day == 1 else d.day} {MOIS_COURT[d.month - 1]}"


def read_seen(cookies):
    """Nuits déjà ouvertes (cookie nba_vues : AAMMJJ séparés par des points)."""
    out = set()
    for x in (cookies.get("nba_vues", "") or "").split("."):
        try:
            out.add(date(2000 + int(x[:2]), int(x[2:4]), int(x[4:6])))
        except (ValueError, IndexError):
            pass
    return out


def write_seen(seen):
    keep = sorted(seen)[-150:]
    set_cookie("nba_vues", ".".join(d.strftime("%y%m%d") for d in keep))


def week_html(week_days, games_by_day, summs, watch, ctx):
    """Vue Semaine : les meilleurs matchs (sans spoil), puis, cachés, les perfs, l'équipe et notre joueur de la semaine."""
    zone = ctx["zone"]
    done = [(d, g) for d in week_days for g in games_by_day.get(d, []) if g["state"] == "post" and g["completed"] and g["home"]["score"] is not None]
    rows = []
    best = sorted(((watch[g["id"]], d, g) for d, g in done if watch.get(g["id"])), key=lambda x: -x[0][2])
    def go_btns(g, d):
        nba = (ctx.get("wv") or {}).get(g["id"])
        vid = f"<a class='cbtn main' href='{yt_url(nba)}' target='_blank'>▶ Résumé</a>" if nba else ""
        return f"<span class='wgo'>{vid}{link('/?nuit=' + d.isoformat() + '&open=' + g['id'], 'Stats ›', 'lk')}</span>"
    for (lv, _, _), d, g in best[:10]:
        icon, label, advice = WATCH_LEVELS[lv]
        rows.append(f"<div class='wrow'><span class='d'>{esc(night_label(d, zone))}</span>"
                    f"<span class='m'>{logo(g['away']['id'], 24)} {esc(team(g['away']['id'])['name'])} @ {esc(team(g['home']['id'])['name'])} {logo(g['home']['id'], 24)}</span>"
                    f"<span class='lvl' title='{esc(advice)}'>{icon} {esc(label)}</span>{go_btns(g, d)}</div>")
    if not rows and done:  # sans note (indice coupé, fiches pas encore là) : les matchs joués, dans l'ordre, sans rien dévoiler
        for d, g in done[-12:]:
            rows.append(f"<div class='wrow'><span class='d'>{esc(night_label(d, zone))}</span>"
                        f"<span class='m'>{logo(g['away']['id'], 24)} {esc(team(g['away']['id'])['name'])} @ {esc(team(g['home']['id'])['name'])} {logo(g['home']['id'], 24)}</span>"
                        f"{go_btns(g, d)}</div>")
    title = "Les meilleurs matchs de la semaine" if best else "Les matchs de la semaine"
    left = (f"<div class='wbox'><h3>{title}</h3>"
            + ("".join(rows) if rows else "<div class='note'>Pas encore de match terminé cette semaine.</div>")
            + "<div class='note'>Sans spoil. Choisis la nuit dans le bandeau pour ouvrir ses cartes.</div></div>")

    facts = []
    if done:
        name = lambda tid: team(tid)["name"]
        perfs, per_player, record = [], defaultdict(list), defaultdict(lambda: [0, 0, 0])
        upsets = []
        for d, g in done:
            s = summs.get(g["id"]) or {}
            for tid, rws in (s.get("box") or {}).items():
                for r in rws:
                    if not r["dnp"] and r["stats"]:
                        gs = game_score(r["stats"])
                        perfs.append((gs, r, tid, d))
                        per_player[(r["name"], tid)].append((gs, _num(r["stats"], "PTS")))
            h, a = g["home"], g["away"]
            for me, other in ((h, a), (a, h)):
                rec = record[me["id"]]
                rec[0 if me["score"] > other["score"] else 1] += 1
                rec[2] += me["score"] - other["score"]
            pre = pre_info(g, s) or {}
            m = re.match(r"([A-Z]{2,4})\s*-([\d.]+)", pre.get("line") or "")
            win, lose = (h, a) if h["score"] > a["score"] else (a, h)
            if m and team(lose["id"])["abbr"] == m.group(1):
                upsets.append((float(m.group(2)), win, lose, d))
        perfs.sort(key=lambda x: -x[0])
        if perfs:
            facts.append("🔥 Les perfs de la semaine : " + " ; ".join(
                f"{r['name']} ({name(tid)}, {short_date(d)}) {stat_line(r['stats'])}" for _, r, tid, d in perfs[:4]) + ".")
        cands = [(sum(x[0] for x in v) / len(v), k, v) for k, v in per_player.items() if len(v) >= 2]
        if cands:
            _, (pname, tid), v = max(cands)
            facts.append(f"⭐ Notre joueur de la semaine : {pname} ({name(tid)}), {fr_num(sum(x[1] for x in v) / len(v))} pts de moyenne sur {len(v)} matchs (calcul maison).")
        teams_ok = [(w / (w + l), diff, tid, w, l) for tid, (w, l, diff) in record.items() if w + l >= 2]
        if teams_ok:
            _, diff, tid, w, l = max(teams_ok)
            facts.append(f"🏆 L'équipe de la semaine : {name(tid)}, {w}-{l} ({'+' if diff >= 0 else ''}{diff} pts au total).")
        if upsets:
            sp, win, lose, d = max(upsets, key=lambda x: x[0])
            facts.append(f"😮 La surprise : {name(win['id'])} bat {name(lose['id'])} {win['score']}-{lose['score']} ({short_date(d)}), {name(lose['id'])} était favori de {fr_num(sp)} pts.")
        if best:
            (lv, _, _), d, g = best[0]
            win, lose = (g["home"], g["away"]) if g["home"]["score"] > g["away"]["score"] else (g["away"], g["home"])
            facts.append(f"🎬 Le match le plus fou : {name(win['id'])} bat {name(lose['id'])} {win['score']}-{lose['score']} ({short_date(d)}).")
    checked = " checked" if ctx["show_all"] else ""
    right = ("<div class='wbox'><input type='checkbox' class='tg tg-w' id='wkfacts'" + checked + ">"
             "<div class='ess-head'><h3>Le bilan de la semaine</h3>"
             + ("<label for='wkfacts' class='cbtn pill-n'><span class='off'>👁 Révéler</span><span class='on'>🙈 Cacher</span></label>" if facts else "")
             + "</div>"
             + (("<div class='ess-hid'><ul class='pts'>" + "".join(f"<li>{esc(f)}</li>" for f in facts) + "</ul></div><!--fin-ess-->") if facts
                else "<div class='note'>Le bilan arrive avec les premiers matchs terminés.</div>")
             + "<div class='note'>Le joueur officiel de la semaine est annoncé par la NBA le lundi.</div></div>")
    return f"<div class='wk'>{left}{right}</div>"


# =========================================================================
# « LE 5 DE LA SEMAINE » : la fantasy (règles et calculs dans fantasy.py)
# =========================================================================
@st.cache_resource(show_spinner=False)
def fantasy_store():
    """Sauvegarde des équipes : fichier JSON sur GitHub ([github] token / repo / branch, branche « data » par défaut),
    sinon sur le disque du serveur (perdu au redémarrage de Streamlit Cloud)."""
    return F.Store(SESSION, str(_secret("github", "token", "")), str(_secret("github", "repo", "")),
                   str(_secret("github", "branch", "data")), CACHE_DIR)


@st.cache_data(ttl=86400, show_spinner=False)
def rosters():
    """{id joueur: {name, short, team, abbr, pos (liste G/F/C), pos_txt, inj, photo}} pour les 30 effectifs (ESPN)."""
    def one(tid):
        d = get_json(f"{ESPN}/teams/{tid}/roster") or {}
        items = d.get("athletes") or []
        if items and isinstance(items[0], dict) and "items" in items[0]:      # format groupé par poste
            items = [a for grp in items for a in grp.get("items") or []]
        out = {}
        for a in items:
            pos = (a.get("position") or {}).get("abbreviation", "")
            inj = ""
            for i in a.get("injuries") or []:
                inj = i.get("status") or (i.get("type") or {}).get("description") or inj
            out[str(a.get("id"))] = {"name": a.get("displayName", ""), "short": a.get("shortName") or a.get("displayName", ""),
                                     "team": tid, "abbr": team(tid)["abbr"], "pos": sorted(F.positions(pos)), "pos_txt": pos,
                                     "inj": inj, "photo": (a.get("headshot") or {}).get("href", "")}
        return out
    res = {}
    with ThreadPoolExecutor(10) as pool:
        for part in pool.map(one, list(teams())):
            res.update(part)
    return res


@st.cache_resource(show_spinner=False)
def _fx_memory():
    return {"log": None, "data": None, "t": 0}


def fantasy_log(schedule, today):
    """Journal des points fantasy de tous les matchs terminés de la saison (complété au fil de l'eau, gardé sur GitHub)."""
    mem, store = _fx_memory(), fantasy_store()
    if mem["log"] is None or time.time() - mem["t"] > 600:
        mem["log"], mem["t"] = store.load("log.json", {}), time.time()
    log = mem["log"]
    todo = [g for g in schedule if g["done"] and g["kind"] == "R" and str(g["id"]) not in log and g["day"] < today][:90]
    if todo:
        with ThreadPoolExecutor(8) as pool:
            summs = list(pool.map(lambda g: summary(g["id"], bucket(86400 * 30)), todo))
        added = sum(F.log_game(log, g["id"], g["day"], s) for g, s in zip(todo, summs) if s)
        if added:
            store.save("log.json", log, f"Fantasy : {added} matchs ajoutés au journal")
    return log


def fantasy_data(force=False):
    mem = _fx_memory()
    if force or mem["data"] is None or time.time() - mem.get("td", 0) > 120:
        mem["data"], mem["td"] = fantasy_store().load("data.json", {"users": {}, "weeks": {}}), time.time()
    return mem["data"]


def first_tip(days_):
    """Coup d'envoi du premier match d'une liste de jours (verrouillage de la semaine)."""
    for d in days_:
        tips = [parse_dt(g["utc"]) for g in day_games(d) if g["utc"]]
        if tips:
            return min(tips)
    return None


def fx_money(x):
    return f"{int(x):,} €".replace(",", " ")


def fantasy_week_state(schedule, today):
    """(lundi de la semaine qu'on compose, verrouillage, lundi de la semaine en cours ou None, semaine en cours finie ?)."""
    now = datetime.now(timezone.utc)
    mon = F.monday_of(today)
    lock = first_tip(F.week_days(mon))
    if lock and now < lock:
        return mon, lock, None
    days_cur = set(F.week_days(mon))
    finished = all(g["done"] for g in schedule if g["day"] in days_cur)
    nxt = mon + timedelta(days=7)
    if finished:
        return nxt, first_tip(F.week_days(nxt)), mon
    return None, None, mon


def ensure_week(data, log, monday, pos_of):
    """Prix figés de la semaine (calculés une fois, à partir des matchs d'avant) et équipe robot."""
    key = monday.isoformat()
    w = data["weeks"].get(key)
    if w and w.get("prices"):
        return w
    prev = (data["weeks"].get((monday - timedelta(days=7)).isoformat()) or {}).get("prices")
    prices = F.week_prices(log, monday, prev)

    def change(d):
        wk = d["weeks"].setdefault(key, {"teams": {}})
        if not wk.get("prices"):
            wk["prices"] = prices
            rob = F.robot_team(log, monday, {p: v for p, v in prices.items() if pos_of(p)}, pos_of)
            if rob:
                wk["teams"][F.ROBOT] = rob
    new = fantasy_store().update("data.json", {"users": {}, "weeks": {}}, change, f"Fantasy : prix de la semaine du {key}")
    if new:
        _fx_memory()["data"] = new
        return new["weeks"][key]
    change(data)
    return data["weeks"][key]


def fantasy_page(schedule, idx, opening, today, zone, show_all):
    roster = rosters()
    pos_of = lambda pid: set((roster.get(pid) or {}).get("pos") or [])
    store = fantasy_store()
    with st.spinner("Mise à jour des statistiques des joueurs…"):
        log = fantasy_log(schedule, today)
    data = fantasy_data()
    compose_mon, lock, cur_mon = fantasy_week_state(schedule, today)
    wnum = lambda m: week_of(m, opening)[1]

    st.markdown("<div class='fx-h'><div class='fx-k'>Le jeu de Bada Bing</div><div class='fx-t'>Le 5 de la semaine</div>"
                "<div class='fx-s'>5 joueurs, 100 000 €, une semaine NBA : chaque joueur rapporte sa moyenne de points par match joué.</div></div>",
                unsafe_allow_html=True)
    if not store.remote:
        st.warning("Les équipes sont enregistrées seulement sur le serveur : elles seront perdues au prochain redémarrage du site. "
                   "Pour les garder, ajoute une clé GitHub dans les réglages Streamlit (section [github] : token, repo).")

    # Connexion : pseudo + code (pas de mot de passe en clair : seule une empreinte est gardée)
    try:
        cookie = (st.context.cookies.get("nba_fx", "") or "")
    except Exception:
        cookie = ""
    if "fx_user" not in st.session_state and ":" in cookie:
        p, h = cookie.rsplit(":", 1)
        p = requests.utils.unquote(p)
        if data["users"].get(p) == h:
            st.session_state.fx_user = p
    user = st.session_state.get("fx_user")
    if not user:
        with st.container(border=True):
            st.markdown("**Entre dans le jeu** : choisis un pseudo et un code (au moins 4 caractères). "
                        "Nouveau pseudo = nouveau joueur ; pseudo existant = connexion.")
            c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
            pseudo = c1.text_input("Pseudo", max_chars=20).strip()
            code = c2.text_input("Code", type="password", max_chars=20)
            if c3.button("Entrer", type="primary", width="stretch"):
                if len(pseudo) < 2 or len(code) < 4 or pseudo.lower() == F.ROBOT.lower():
                    st.error("Pseudo d'au moins 2 caractères et code d'au moins 4 caractères.")
                else:
                    h = F.code_hash(pseudo, code)
                    known = fantasy_data(force=True)["users"].get(pseudo)
                    if known and known != h:
                        st.error("Ce pseudo existe déjà avec un autre code.")
                    else:
                        if not known:
                            new = store.update("data.json", {"users": {}, "weeks": {}}, lambda d: d["users"].__setitem__(pseudo, h),
                                               f"Fantasy : nouveau joueur {pseudo}")
                            if new:
                                _fx_memory()["data"] = new
                        st.session_state.fx_user = pseudo
                        set_cookie("nba_fx", f"{requests.utils.quote(pseudo)}:{h}")
                        st.rerun()

    tab_team, tab_rank, tab_prices, tab_rules = st.tabs(["Mon équipe", "Classement", "Tous les prix", "Règles"])

    # Semaine qu'on compose
    wk = ensure_week(data, log, compose_mon, pos_of) if compose_mon else None
    prices = (wk or {}).get("prices") or {}
    week_games = defaultdict(int)
    if compose_mon:
        days_c = set(F.week_days(compose_mon))
        for g in schedule:
            if g["day"] in days_c:
                week_games[g["home"]] += 1
                week_games[g["away"]] += 1

    games_before = F.player_games(log, until=compose_mon or today)
    infos = {}

    def info(pid):
        if pid not in infos:
            infos[pid] = F.player_info(log, pid, compose_mon or today, games_before)
        return infos[pid]

    def label(pid):
        r, i = roster.get(pid) or {}, info(pid)
        flags = []
        if r.get("inj"):
            flags.append(f"⚠ {r['inj']}")
        if i["n"] and i["mpg"] < 15:
            flags.append("joue peu")
        return (f"{r.get('name', pid)} ({r.get('abbr', '?')}) · {fx_money(prices.get(pid, 0))} · {fr_num(i['form'])} pts/m · "
                f"{fr_num(i['mpg'], 0)} min · {'titulaire' if i['starter'] else 'remplaçant'} · {week_games.get(r.get('team'), 0)} m. cette sem."
                + (" · " + " · ".join(flags) if flags else ""))

    with tab_team:
        if not compose_mon:
            st.info(f"La semaine {wnum(cur_mon)} est en cours : les équipes sont verrouillées. "
                    f"La composition de la semaine {wnum(cur_mon + timedelta(days=7))} ouvre dès que tous les matchs de cette semaine sont finis.")
        elif not user:
            st.info("Connecte-toi au-dessus pour composer ton équipe.")
        else:
            lock_txt = f"jusqu'au {short_date(lock.astimezone(ZONES[zone]).date())} à {fr_hour(lock.astimezone(ZONES[zone]))}" if lock else ""
            st.markdown(f"**Semaine {wnum(compose_mon)}** : composition ouverte {lock_txt} "
                        f"(premier match de la semaine). Tu peux modifier ton équipe autant que tu veux d'ici là.")
            saved = (wk.get("teams") or {}).get(user) or {}
            avail = [p for p in prices if p in roster]
            choice = {}
            cols = st.columns(2)
            slots = list(F.SLOTS) + [(None, "6e homme")]
            for i, (need, lab) in enumerate(slots):
                opts = sorted([p for p in avail if need is None or need in pos_of(p)], key=lambda p: -prices[p])
                pre = (saved.get("five") or [None] * 5)[i] if i < 5 else saved.get("six")
                with cols[i % 2]:
                    choice[i] = st.selectbox(f"{lab}{' (remplace un joueur qui ne joue pas de la semaine)' if need is None else ''}",
                                             [None] + opts, index=([None] + opts).index(pre) if pre in opts else 0,
                                             format_func=lambda p: "— Choisir —" if p is None else label(p), key=f"fx_{compose_mon}_{i}")
            five, six = [choice[i] for i in range(5)], choice[5]
            cheap = [p for p in five if p and prices.get(p, 0) <= F.COEUR_MAX]
            coeur = st.selectbox(f"💘 Coup de cœur (un des 5 à {fx_money(F.COEUR_MAX)} ou moins : ses points comptent double)",
                                 [None] + cheap, index=([None] + cheap).index(saved.get("coeur")) if saved.get("coeur") in cheap else 0,
                                 format_func=lambda p: "Aucun" if p is None else label(p), key=f"fx_{compose_mon}_c")
            cost = sum(prices.get(p, 0) for p in five + [six] if p)
            left = F.BUDGET - cost
            st.progress(min(1.0, cost / F.BUDGET), text=f"Budget : {fx_money(cost)} dépensés · {'reste ' + fx_money(left) if left >= 0 else 'DÉPASSÉ de ' + fx_money(-left)}")
            for p in five + [six]:
                if not p:
                    continue
                r, i = roster.get(p) or {}, info(p)
                if r.get("inj") and norm(r["inj"]) in ("out", "suspension", "suspended"):
                    st.warning(f"Attention : {r['name']} est annoncé absent ({r['inj']}).")
                elif r.get("inj"):
                    st.warning(f"Attention : {r['name']} est incertain ({r['inj']}).")
                if i["n"] and i["mpg"] < 15:
                    st.warning(f"Attention : {r['name']} joue peu ({fr_num(i['mpg'], 0)} min par match).")
                if week_games.get(r.get("team"), 0) == 0:
                    st.warning(f"Attention : l'équipe de {r['name']} ne joue pas cette semaine.")
            team_new = {"five": five, "six": six, "coeur": coeur}
            errs = F.validate(team_new, prices, pos_of)
            if st.button("Enregistrer mon équipe", type="primary", disabled=bool(errs) or (lock and datetime.now(timezone.utc) >= lock)):
                team_new["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                key = compose_mon.isoformat()
                new = store.update("data.json", {"users": {}, "weeks": {}},
                                   lambda d: d["weeks"].setdefault(key, {"teams": {}, "prices": prices}).setdefault("teams", {}).__setitem__(user, team_new),
                                   f"Fantasy : équipe de {user}, semaine du {key}")
                if new:
                    _fx_memory()["data"] = new
                    st.success("Équipe enregistrée ✓")
                else:
                    st.error("L'enregistrement a échoué. Réessaie dans un instant.")
            elif errs and any(five) and six:
                for e in errs:
                    st.caption("⛔ " + e)

        # Équipe de la semaine en cours (verrouillée)
        if cur_mon and user:
            mine = ((data["weeks"].get(cur_mon.isoformat()) or {}).get("teams") or {}).get(user)
            st.markdown(f"#### Ton équipe de la semaine {wnum(cur_mon)}")
            if not mine:
                st.caption("Tu n'avais pas d'équipe cette semaine.")
            else:
                pts = F.week_points(log, cur_mon)
                total, detail = F.score_team(mine, pts)
                reveal = st.toggle("Voir mes points (dévoile des performances de la semaine)", value=show_all, key="fx_rev_me")
                rows = []
                for (pid, avg, n, role), (_, lab) in zip(detail, F.SLOTS):
                    r = roster.get(pid) or {}
                    rows.append({"Poste": lab, "Joueur": r.get("name", pid), "Équipe": r.get("abbr", ""),
                                 "Matchs joués": n if reveal else "?", "Points comptés": avg if reveal else "?", "": role if reveal else ""})
                st.dataframe(rows, hide_index=True, width="stretch")
                if reveal:
                    st.markdown(f"**Total provisoire : {fr_num(total)} points**")

    with tab_rank:
        weeks_done = sorted(k for k, w in data["weeks"].items() if w.get("teams") and (date.fromisoformat(k) + timedelta(days=7) <= today
                            and all(g["done"] for g in schedule if g["day"] in set(F.week_days(date.fromisoformat(k))))))
        reveal = st.toggle("Voir les classements (dévoile des performances)", value=show_all, key="fx_rev_rank")
        if not reveal:
            st.caption("Caché pour ne rien spoiler. Le résultat officiel d'une semaine tombe quand tous ses matchs sont joués.")
        else:
            if cur_mon and cur_mon.isoformat() in data["weeks"]:
                pts = F.week_points(log, cur_mon)
                live = sorted(((F.score_team(t, pts)[0], u) for u, t in data["weeks"][cur_mon.isoformat()].get("teams", {}).items()), reverse=True)
                st.markdown(f"#### Semaine {wnum(cur_mon)} · en cours")
                st.dataframe([{"Rang": i + 1, "Joueur": ("🤖 " if u == F.ROBOT else "") + u, "Points": s} for i, (s, u) in enumerate(live)],
                             hide_index=True, width="stretch")
            season, wins = defaultdict(float), defaultdict(int)
            for k in weeks_done:
                m = date.fromisoformat(k)
                pts = F.week_points(log, m)
                scores = {u: F.score_team(t, pts)[0] for u, t in data["weeks"][k]["teams"].items()}
                for u, s in scores.items():
                    season[u] += s
                if scores:
                    wins[max(scores, key=scores.get)] += 1
            if weeks_done:
                last = date.fromisoformat(weeks_done[-1])
                wkd = data["weeks"][weeks_done[-1]]
                pts = F.week_points(log, last)
                res = sorted(((F.score_team(t, pts)[0], u) for u, t in wkd["teams"].items()), reverse=True)
                st.markdown(f"#### Semaine {wnum(last)} · résultat officiel")
                perfect = F.perfect_team(pts, wkd["prices"], pos_of)
                best = perfect[1] if perfect else None
                st.dataframe([{"Rang": i + 1, "Joueur": ("🤖 " if u == F.ROBOT else "") + u, "Points": s,
                               "% de l'équipe parfaite": f"{round(100 * s / best)} %" if best else "–"} for i, (s, u) in enumerate(res)],
                             hide_index=True, width="stretch")
                if perfect:
                    names = " · ".join(f"{(roster.get(p) or {}).get('name', p)}{' 💘' if p == perfect[0]['coeur'] else ''}" for p in perfect[0]["five"])
                    st.caption(f"⭐ L'équipe parfaite ({fr_num(best)} points, {fx_money(sum(wkd['prices'][p] for p in perfect[0]['five']))}) : {names}")
                st.markdown("#### Saison")
                st.dataframe([{"Rang": i + 1, "Joueur": ("🤖 " if u == F.ROBOT else "") + u, "Points": round(s, 1), "Semaines gagnées": wins[u]}
                              for i, (u, s) in enumerate(sorted(season.items(), key=lambda x: -x[1]))], hide_index=True, width="stretch")
            elif not cur_mon:
                st.caption("Pas encore de semaine jouée.")

    with tab_prices:
        if not prices:
            st.caption("Les prix de la prochaine semaine apparaîtront à l'ouverture de la composition.")
        else:
            prev = (data["weeks"].get((compose_mon - timedelta(days=7)).isoformat()) or {}).get("prices") or {}
            rows = []
            for pid, p in sorted(prices.items(), key=lambda x: -x[1]):
                r = roster.get(pid)
                if not r:
                    continue
                i = info(pid)
                d = p - prev[pid] if pid in prev else 0
                rows.append({"Joueur": r["name"], "Équipe": r["abbr"], "Poste": "/".join({"G": "Arr.", "F": "Ail.", "C": "Piv."}[x] for x in r["pos"]),
                             "Prix (€)": p, "Évol.": (f"▲ {d:,}" if d > 0 else f"▼ {-d:,}" if d < 0 else "=").replace(",", " "),
                             "Forme (pts/m)": i["form"], "Min/m": i["mpg"], "Titulaire": "oui" if i["starter"] else "non",
                             "Matchs cette sem.": week_games.get(r["team"], 0), "Statut": r["inj"] or ""})
            st.caption(f"Semaine {wnum(compose_mon)} · {len(rows)} joueurs · prix figés pour la semaine.")
            st.dataframe(rows, hide_index=True, width="stretch", height=560)

    with tab_rules:
        st.markdown(f"""
- **Une équipe par semaine NBA** (du lundi au dimanche), modifiable jusqu'au premier match de la semaine, puis verrouillée.
- **Le 5 de départ** : 2 arrières, 2 ailiers, 1 pivot, plus un **6e homme** de n'importe quel poste. **Budget : {fx_money(F.BUDGET)}.**
- **Points d'un match** : 1 par point, 1,2 par rebond, 1,5 par passe, 3 par interception, 3 par contre, −1 par balle perdue.
- **Un joueur rapporte sa moyenne** sur les matchs qu'il a joués dans la semaine : le calendrier et le repos ne pénalisent personne.
  Toute apparition compte, même s'il se blesse au bout de 3 minutes.
- **Le 6e homme** remplace un des 5 qui n'a joué **aucun** match de la semaine (un seul remplacement).
- **Coup de cœur 💘** : un des 5 coûtant {fx_money(F.COEUR_MAX)} ou moins ; ses points comptent double.
- **Les prix** sont recalculés chaque semaine d'après la forme (10 derniers matchs 70 %, saison 30 %), avec au plus ±20 % de variation.
- **Résultat officiel** quand tous les matchs de la semaine sont joués ; **l'équipe parfaite** te dit quel pourcentage du maximum tu as fait ;
  **l'équipe robot 🤖** prend simplement les meilleurs joueurs en forme que le budget permet.
- Les points et classements sont cachés par défaut, pour ne pas spoiler les matchs.
""")


# =========================================================================
# NAVIGATION, PROGRAMME, CLASSEMENT, PAGE ÉQUIPE (v023)
# =========================================================================

# Où regarder : chaîne du pays choisi (beIN SPORTS en France ; TSN, Sportsnet, RDS, TVA Sports au Canada), sinon NBA League Pass.
# Sources : les diffuseurs donnés par ESPN (broadcasts + geoBroadcasts) et le calendrier officiel de la NBA (cdn.nba.com).
NBA_CDN_SCHEDULE = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
NBA_TRI = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}
TV_RE = {"FR": re.compile(r"bein", re.I),
         "CA": re.compile(r"\b(TSN\d?|SN\d?|SN ?NOW|Sportsnet[\w ]*|RDS\d?|TVA ?Sports?\d?)\b", re.I)}


@st.cache_data(ttl=21600, show_spinner=False)
def nba_schedule_tv():
    """{« AAAA-MM-JJ|domicile|visiteur » (sigles NBA) : [diffuseurs]} d'après le calendrier officiel de la NBA."""
    d = get_json(NBA_CDN_SCHEDULE, timeout=15) or {}
    out = {}
    for gd in (d.get("leagueSchedule") or {}).get("gameDates") or []:
        for g in gd.get("games") or []:
            h, a = (g.get("homeTeam") or {}).get("teamTricode"), (g.get("awayTeam") or {}).get("teamTricode")
            day = (g.get("gameDateEst") or "")[:10]
            names = set()
            for lst in (g.get("broadcasters") or {}).values():
                for b in lst if isinstance(lst, list) else []:
                    n = b.get("broadcasterDisplay") or b.get("broadcasterAbbreviation")
                    if n:
                        names.add(n)
            if h and a and day:
                out[f"{day}|{h}|{a}"] = sorted(names)
    return out


def watch_on(g, pays):
    """(texte, chaîne du pays connue ?) : « beIN SPORTS », « TSN · RDS »… sinon « NBA League Pass »."""
    names = set(g.get("tv_all") or [])
    ta, th = team(g["away"]["id"])["abbr"], team(g["home"]["id"])["abbr"]
    if g.get("day"):
        names |= set(nba_schedule_tv().get(f"{g['day'].isoformat()}|{NBA_TRI.get(th, th)}|{NBA_TRI.get(ta, ta)}", []))
    found = sorted(n for n in names if TV_RE.get(pays, TV_RE["FR"]).search(n))
    return (" · ".join(found), True) if found else ("NBA League Pass", False)


def watch_badge(g, pays, short=False):
    txt, sure = watch_on(g, pays)
    return f"<span class='wt{' ok' if sure else ''}' title='Où regarder en {'France' if pays == 'FR' else 'au Canada'}'>📺 {esc(txt)}</span>"

VIEWS = ("nuit", "brief", "programme", "classement", "equipe", "joueurs", "semaine", "fantasy")
TABS = [("brief", "Le brief", ":material/coffee:"), ("nuit", "Matchs", ":material/sports_basketball:"),
        ("programme", "Programme", ":material/calendar_month:"), ("classement", "Classement", ":material/leaderboard:"),
        ("equipe", "Équipes", ":material/shield:"), ("joueurs", "Joueurs", ":material/person:")]
J3 = ["Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim."]


def team_by_abbr(abbr):
    return next((tid for tid, t in teams().items() if abbr and t["abbr"] == abbr), None)


def fav_ids():
    return {tid for tid, t in teams().items() if t["abbr"] in set(st.session_state.get("favs") or [])}


def chip_text(d, zone, today):
    """Bouton d'une nuit : (petit texte au-dessus, grand texte). Jamais coupé : « Sam. → Dim. » / « 31 → 1 »."""
    paris = zone == "Paris"
    rel = {0: ("Cette nuit", "Ce soir"), -1: ("Nuit dernière", "Hier soir"), 1: ("Nuit prochaine", "Demain soir")}.get((d - today).days)
    nxt = d + timedelta(days=1)
    top = rel[0 if paris else 1] if rel else (f"{J3[d.weekday()]} → {J3[nxt.weekday()]}" if paris else J3[d.weekday()])
    big = f"{d.day} → {nxt.day}" if paris else f"{d.day} {MOIS_COURT[d.month - 1]}"
    return top, big


def spoil_cut(days, today, seen, show_all):
    """Jusqu'où les bilans et classements peuvent aller sans rien dévoiler : (jour de coupure, dernière nuit jouée).
    On compte les matchs AVANT la coupure. Si la dernière nuit a déjà été ouverte (ou si on montre les scores), tout compte."""
    last = default_day(days, today)
    if show_all or last in seen or last > today:
        return today + timedelta(days=1), last
    return last, last


def settings_panel(interest, show_all):
    all_teams = sorted(teams().values(), key=lambda t: t["full"])
    abbrs = [""] + [t["abbr"] for t in all_teams]
    cur = (st.session_state.favs or [""])[0]
    fav = st.selectbox("⭐ Mon équipe", abbrs, index=abbrs.index(cur) if cur in abbrs else 0,
                       format_func=lambda ab: next((t["full"] for t in all_teams if t["abbr"] == ab), "Aucune"),
                       help="Ses matchs passent en tête partout, et l'onglet « Équipes » s'ouvre sur elle.")
    if [fav] != st.session_state.favs and (fav or st.session_state.favs):
        st.session_state.favs = [fav] if fav else []
        st.session_state.fav_changed = True
        if fav:
            st.session_state.team = team_by_abbr(fav)
        track("set", x="équipe:" + fav)
    opts = st.session_state.opts
    pays = st.radio("📺 Je regarde la NBA depuis", ["FR", "CA"], index=0 if opts.get("pays", "FR") == "FR" else 1, horizontal=True,
                    format_func=lambda c: {"FR": "🇫🇷 France", "CA": "🇨🇦 Canada"}[c],
                    help="Pour afficher la bonne chaîne (beIN SPORTS, TSN, Sportsnet…) et « nos joueurs » (Français ou Canadiens).")
    new_interest = st.toggle("🔥 Indice « à voir » (sans dire qui gagne)", value=interest,
                             help="Note chaque match terminé, de 🔥🔥🔥 à ⛔, et range les meilleurs en premier.")
    new_show = st.toggle("👁 Toujours montrer les scores", value=show_all,
                         help="Les scores, bilans et classements sont alors à jour partout, sans clic.")
    if new_interest != interest or new_show != show_all or pays != opts.get("pays", "FR"):
        st.session_state.opts = {"indice": new_interest, "scores": new_show, "pays": pays}
        st.session_state.opt_changed = True
        track("set", x=f"indice:{new_interest} scores:{new_show} pays:{pays}")
        st.rerun()
    st.caption("Tes réglages restent sur cet appareil.")


def welcome(cookies):
    """Première visite : en deux lignes, ce que fait le site (fermé pour de bon avec « C'est parti »)."""
    if cookies.get("nba_hello") or st.session_state.get("hello_done"):
        return
    with st.container(key="hello"):
        st.markdown("<div class='hello'><b>Bienvenue sur Bada Bing NBA 👋</b>"
                    "<p>Chaque nuit de NBA, en français et <b>sans spoil</b> : aucun score ne s'affiche tant que tu ne cliques pas dessus. "
                    "Résumés vidéo, stats, avant-match, programme, classement…</p>"
                    "<p>Astuce : choisis ton équipe dans <b>⭐ Mon équipe</b>, ses matchs passeront toujours en premier.</p></div>",
                    unsafe_allow_html=True)
        if st.button("C'est parti", key="hello_ok", icon=":material/check:"):
            st.session_state.hello_done = True
            st.session_state.hello_cookie = True
            st.rerun()


def page_head(title, sub="", kicker=""):
    st.markdown(f"<div class='pg-head'>{f'<div class=pg-k>{esc(kicker)}</div>' if kicker else ''}<h1>{esc(title)}</h1>"
                f"{f'<p>{sub}</p>' if sub else ''}</div>", unsafe_allow_html=True)


def page_footer():
    st.markdown(f"<div class='pg-foot'>Bada Bing NBA · la NBA en français, sans spoil · données ESPN, vidéos YouTube · "
                f"site de fans, non affilié à la NBA · statistiques de visite anonymes · v{APP_VERSION[-3:]}</div>", unsafe_allow_html=True)


def link(href, text, cls="lk", title=""):
    """Lien interne (« /?nuit=…&vue=… ») : sur Streamlit Cloud, une page dans un cadre ne peut pas changer l'adresse de la
    fenêtre ; le clic est donc intercepté (`click_tracker`) et passe par le champ caché « go_to », sans recharger la page."""
    t = f" title='{esc(title)}'" if title else ""
    query = href.split("?", 1)[-1]
    return f"<a class='{cls}' href='#go?{esc(query)}'{t}>{text}</a>"


def apply_go(cmd):
    """Applique un lien interne reçu par le champ caché : nuit, vue, équipe, joueur, match à ouvrir."""
    from urllib.parse import parse_qsl
    q = dict(parse_qsl(cmd))
    ss = st.session_state
    if q.get("nuit"):
        try:
            ss.day = date.fromisoformat(q["nuit"])
        except ValueError:
            pass
    if q.get("eq") and team_by_abbr(q["eq"]):
        ss.team = team_by_abbr(q["eq"])
    if q.get("joueur"):
        ss.player = q["joueur"]
        ss.psec = "fiche"
    if q.get("rub") in ("fiche", "meilleurs", "nous", "infirmerie"):
        ss.psec = q["rub"]
    ss.open_game = q.get("open") or None
    ss.view = q.get("vue") if q.get("vue") in VIEWS else "nuit"
    track("nav", d=ss.day.isoformat() if ss.get("day") else "", x="lien:" + ss.view)


def team_link(tid, text=None):
    t = team(tid)
    return link(f"/?vue=equipe&eq={t['abbr']}", esc(text or t["name"]), "tl", f"Page des {t['name']}")


def mini_logo(tid, size=26):
    url = team(tid)["logo"]
    return f"<img class='ml' src='{esc(url)}' width='{size}' height='{size}' alt='' loading='lazy'>" if url else ""


def season_rows(idx, tid, season, cut):
    """Matchs de saison régulière terminés d'une équipe avant le jour `cut`."""
    return [g for g in idx.get(tid, []) if g[5] == season and g[6] == "R" and g[0] < cut]


def standings(idx, season, cut):
    """{conférence: [ligne]} triées : V, D, %, écart, dom., ext., 10 derniers, série, points pour/contre par match."""
    out = defaultdict(list)
    for tid, t in teams().items():
        rows = season_rows(idx, tid, season, cut)
        w = sum(1 for g in rows if g[2] > g[3])
        n = len(rows)
        hw = sum(1 for g in rows if g[4] and g[2] > g[3])
        hn = sum(1 for g in rows if g[4])
        aw = sum(1 for g in rows if not g[4] and g[2] > g[3])
        last10 = rows[-10:]
        streak = 0
        for g in reversed(rows):
            won = g[2] > g[3]
            if streak == 0:
                streak = 1 if won else -1
            elif (streak > 0) == won:
                streak += 1 if won else -1
            else:
                break
        out[t["conf"] or "?"].append({
            "tid": tid, "w": w, "l": n - w, "n": n, "pct": w / n if n else 0, "home": f"{hw}-{hn - hw}", "away": f"{aw}-{n - hn - aw}",
            "l10": f"{sum(1 for g in last10 if g[2] > g[3])}-{sum(1 for g in last10 if g[2] <= g[3])}", "streak": streak,
            "pf": sum(g[2] for g in rows) / n if n else 0, "pa": sum(g[3] for g in rows) / n if n else 0,
        })
    for conf, rows in out.items():
        rows.sort(key=lambda r: (-r["pct"], -r["w"], r["l"], team(r["tid"])["name"]))
        if rows:
            lead = rows[0]
            for i, r in enumerate(rows, 1):
                r["rank"] = i
                r["gb"] = ((lead["w"] - r["w"]) + (r["l"] - lead["l"])) / 2
    return dict(out)


def streak_badge(s):
    if not s:
        return ""
    return f"<span class='stk {'w' if s > 0 else 'l'}'>{'V' if s > 0 else 'D'}{abs(s)}</span>"


def cut_note(cut, last, zone, today):
    """Phrase qui dit jusqu'où vont les chiffres affichés."""
    if cut > today:
        return "À jour, nuit dernière comprise."
    return f"Avant la {night_short_title(last, zone)[0].lower() + night_short_title(last, zone)[1:]}, que tu n'as pas encore ouverte (pas de spoil)."


def reveal_toggle(cut, last, zone, today, key):
    """Interrupteur « inclure la dernière nuit » : renvoie la nouvelle coupure."""
    if cut > today:
        return cut
    if st.toggle(f"Inclure la dernière nuit ({night_label(last, zone)}) : montre ses résultats", key=key):
        return today + timedelta(days=1)
    return cut


def standings_page(idx, season, cut, days, today, zone):
    page_head("Classement", kicker="Saison régulière")
    last = default_day(days, today)
    if cut <= today:
        st.markdown(f"<p class='pg-note'>{esc(cut_note(cut, last, zone, today))}</p>", unsafe_allow_html=True)
    cut = reveal_toggle(cut, last, zone, today, "st_rev")
    table = standings(idx, season, cut)
    favs = fav_ids()
    blocks = []
    for conf in ("Est", "Ouest"):
        rows = table.get(conf) or []
        body = []
        for r in rows:
            zone_cls = "z1" if r["rank"] <= 6 else ("z2" if r["rank"] <= 10 else "z3")
            fav = " fav" if r["tid"] in favs else ""
            body.append(
                f"<tr class='{zone_cls}{fav}'><td class='rk'>{r['rank']}</td>"
                f"<td class='tmc'>{mini_logo(r['tid'])}{team_link(r['tid'])}{' <span class=star>★</span>' if fav else ''}</td>"
                f"<td><b>{r['w']}</b></td><td>{r['l']}</td><td class='pc'>{('%.3f' % r['pct']).lstrip('0') if r['n'] else '–'}</td>"
                f"<td class='hide-s'>{'–' if r['gb'] == 0 else fr_num(r['gb']).replace(',0', '')}</td>"
                f"<td class='hide-s'>{r['home']}</td><td class='hide-s'>{r['away']}</td><td class='hide-s'>{r['l10']}</td>"
                f"<td>{streak_badge(r['streak'])}</td></tr>")
        blocks.append(f"<div class='stand'><div class='stand-h'>Conférence {conf}</div><table class='stt'><thead><tr>"
                      "<th class='rk'>#</th><th class='tmc'>Équipe</th><th>V</th><th>D</th><th>%</th><th class='hide-s' title='Retard sur le 1er'>Écart</th>"
                      "<th class='hide-s'>Dom.</th><th class='hide-s'>Ext.</th><th class='hide-s'>10 der.</th><th>Série</th></tr></thead>"
                      f"<tbody>{''.join(body)}</tbody></table></div>")
    st.markdown(f"<div class='stands'>{''.join(blocks)}</div>"
                "<div class='legend'><span class='lg z1'></span>1 à 6 : qualifiés pour les play-offs "
                "<span class='lg z2'></span>7 à 10 : play-in (barrages) <span class='lg z3'></span>éliminés</div>",
                unsafe_allow_html=True)


def quick_hype(idx, g, season, cut):
    """Affiche d'une nuit à venir, sans spoil : deux équipes qui gagnent (bilans avant la coupure)."""
    pcts = []
    for tid in (g["home"]["id"], g["away"]["id"]):
        rows = season_rows(idx, tid, season, min(cut, g["day"]))
        if len(rows) < 3:
            return 0
        pcts.append(sum(1 for r in rows if r[2] > r[3]) / len(rows))
    return min(pcts) + 0.3 * sum(pcts)


def record_txt(idx, tid, season, cut):
    rows = season_rows(idx, tid, season, cut)
    w = sum(1 for g in rows if g[2] > g[3])
    return f"{w}-{len(rows) - w}" if rows else ""


def programme_page(today, zone, idx, season, cut):
    page_head("Programme", f"Les 7 prochaines {'nuits' if zone == 'Paris' else 'soirées'}, à l'heure de {zone}.", "À venir")
    favs = fav_ids()
    only = st.segmented_control("Matchs", ["Tous les matchs", "Mon équipe"], key="prog_f", label_visibility="collapsed",
                                default="Mon équipe" if favs and st.session_state.get("prog_mine") else "Tous les matchs")
    start = today if any(g["state"] != "post" for g in day_games(today)) else today + timedelta(days=1)
    days7 = [start + timedelta(days=i) for i in range(7)]
    with ThreadPoolExecutor(7) as pool:
        lists = list(pool.map(day_games, days7))
    tz = ZONES[zone]
    out = []
    for d, games in zip(days7, lists):
        if only == "Mon équipe":
            games = [g for g in games if {g["home"]["id"], g["away"]["id"]} & favs]
        if not games:
            continue
        hy = {g["id"]: quick_hype(idx, g, season, cut) for g in games if g["state"] == "pre"}
        top = max(hy, key=hy.get) if hy and max(hy.values()) >= 0.85 else None
        rows = []
        for g in sorted(games, key=lambda g: (0 if {g["home"]["id"], g["away"]["id"]} & favs else 1, g["utc"] or "")):
            tip = parse_dt(g["utc"])
            when = fr_hour(tip.astimezone(tz)) if tip else "?"
            if g["state"] == "in":
                when = "<span class='live'>● En direct</span>"
            elif g["state"] == "post":
                when = "Terminé"
            a, h = g["away"]["id"], g["home"]["id"]
            badges = []
            tv = watch_badge(g, st.session_state.opts.get("pays", "FR"))
            if {a, h} & favs:
                badges.append("<span class='bdg fav'>★ Mon équipe</span>")
            if g["id"] == top:
                badges.append("<span class='bdg hot'>🔥 L'affiche</span>")
            if g["status"] == "STATUS_POSTPONED":
                badges.append("<span class='bdg'>Reporté</span>")
            rows.append(
                f"<div class='pr{' f' if {a, h} & favs else ''}'><div class='pr-t'>{when}</div>"
                f"<div class='pr-m'><span class='side'>{mini_logo(a, 30)}<span>{team_link(a)} <small>{record_txt(idx, a, season, cut)}</small></span></span>"
                f"<span class='at'>@</span>"
                f"<span class='side'>{mini_logo(h, 30)}<span>{team_link(h)} <small>{record_txt(idx, h, season, cut)}</small></span></span></div>"
                f"<div class='pr-x'>{''.join(badges)}{tv}</div></div>")
        rel = rel_label(d, zone, today)
        title = night_short_title(d, zone)
        go_link = link(f"/?nuit={d.isoformat()}", "Voir la nuit ›", "pd-go")
        count = f"{len(games)} match{'s' if len(games) > 1 else ''}"
        kick = f"<i>{esc(rel)}</i>" if rel else ""
        out.append(f"<section class='pd'><div class='pd-h'><div>{kick}<b>{esc(title)}</b><span>{count}</span></div>{go_link}</div>{''.join(rows)}</section>")
    if not out:
        st.info("Aucun match de ton équipe dans les 7 prochains jours." if only == "Mon équipe" else "Pas de match NBA dans les 7 prochains jours.")
    st.markdown("".join(out), unsafe_allow_html=True)
    st.caption("📺 En doré : la chaîne qui diffuse le match dans ton pays (à choisir dans ⚙️ Réglages). Sinon, tous les matchs sont "
               "sur NBA League Pass. Bilans arrêtés avant la dernière nuit tant que tu ne l'as pas ouverte.")
    if favs:
        agenda_button(sorted(favs, key=lambda t: team(t)["name"]), "prog")


def ics_calendar(tids, schedule_games):
    """Fichier agenda (.ics) des matchs à venir des équipes choisies (heures en UTC : chaque agenda les met à l'heure locale)."""
    now = datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Bada Bing NBA//FR", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:NBA · {' / '.join(team(t)['name'] for t in tids)}"]
    for g in schedule_games:
        tip = parse_dt(g.get("utc"))
        if not tip or tip < now or not ({g["home"], g["away"]} & set(tids)):
            continue
        lines += ["BEGIN:VEVENT", f"UID:{g['id']}@badabingnba", f"DTSTAMP:{now:%Y%m%dT%H%M%SZ}", f"DTSTART:{tip:%Y%m%dT%H%M%SZ}",
                  "DURATION:PT2H30M", f"SUMMARY:🏀 {team(g['away'])['name']} @ {team(g['home'])['name']}",
                  "DESCRIPTION:Résumé et stats sans spoil sur Bada Bing NBA", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def agenda_button(tids, key):
    sched = st.session_state.get("_schedule") or []
    names = " et ".join(team(t)["name"] for t in tids)
    st.download_button(f"Ajouter les matchs des {names} à mon agenda", ics_calendar(tids, sched),
                       file_name=f"nba-{'-'.join(team(t)['abbr'].lower() for t in tids)}.ics", mime="text/calendar",
                       icon=":material/event:", key=f"ics_{key}", help="Un fichier à ouvrir avec ton agenda (téléphone, Google, Outlook…).")


@st.cache_data(ttl=86400, show_spinner=False, max_entries=40)
def team_roster(tid):
    """Effectif ESPN : identité, poste, numéro, blessure (statut, type, retour prévu), et la bio (âge, taille, pays…)."""
    d = get_json(f"{ESPN}/teams/{tid}/roster") or {}
    items = d.get("athletes") or []
    if items and isinstance(items[0], dict) and "items" in items[0]:
        items = [a for grp in items for a in grp.get("items") or []]
    out = []
    for a in items:
        inj, inj_type, inj_back = "", "", ""
        for i in a.get("injuries") or []:
            inj = i.get("status") or (i.get("type") or {}).get("description") or inj
            det = i.get("details") or {}
            inj_type = det.get("type") or inj_type
            inj_back = det.get("returnDate") or inj_back
        def num(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None
        h, w = num(a.get("height")), num(a.get("weight"))
        out.append({"id": str(a.get("id") or ""), "name": a.get("displayName", ""), "pos": (a.get("position") or {}).get("abbreviation", ""),
                    "num": a.get("jersey") or "", "inj": inj, "inj_type": inj_type, "inj_back": inj_back, "team": tid,
                    "age": a.get("age"), "cm": round(h * 2.54) if h else None, "kg": round(w * 0.4536) if w else None,
                    "country": ((a.get("birthPlace") or {}).get("country") or ""), "city": ((a.get("birthPlace") or {}).get("city") or ""),
                    "exp": (a.get("experience") or {}).get("years"), "college": (a.get("college") or {}).get("name", ""),
                    "photo": (a.get("headshot") or {}).get("href") or (f"https://a.espncdn.com/i/headshots/nba/players/full/{a.get('id')}.png" if a.get("id") else "")})
    return out


@st.cache_data(ttl=1800, show_spinner=False, max_entries=40)
def team_news(tid):
    d = get_json(f"{ESPN}/news", {"team": tid, "limit": 8}) or {}
    out = []
    for a in d.get("articles") or []:
        href = ((a.get("links") or {}).get("web") or {}).get("href", "")
        if a.get("headline") and href:
            out.append({"title": a["headline"], "desc": a.get("description", ""), "href": href, "when": parse_dt(a.get("published"))})
    return out


POS_FR = {"G": "Arrière", "PG": "Meneur", "SG": "Arrière", "F": "Ailier", "SF": "Ailier", "PF": "Ailier fort", "C": "Pivot",
          "G-F": "Arrière-ailier", "F-G": "Ailier-arrière", "F-C": "Ailier-pivot", "C-F": "Pivot-ailier"}
STATUS_FR = {"out": "Absent", "day-to-day": "Incertain", "questionable": "Incertain", "doubtful": "Peu probable", "probable": "Probable",
             "suspension": "Suspendu", "injured reserve": "Longue absence"}


def status_fr(s):
    n = norm(s)
    return next((v for k, v in STATUS_FR.items() if k in n), s or "")


def team_picker(key):
    """Grille des 30 équipes (par conférence) : un clic ouvre sa page."""
    for conf in ("Est", "Ouest"):
        st.markdown(f"<div class='pick-h'>Conférence {conf}</div>", unsafe_allow_html=True)
        ts = sorted([t for t in teams().values() if t["conf"] == conf], key=lambda t: t["name"])
        with st.container(key=f"pick_{key}_{conf}"):
            cols = st.columns(5)
            for i, t in enumerate(ts):
                if cols[i % 5].button(t["name"], key=f"pk_{key}_{t['id']}", width="stretch"):
                    st.session_state.team = t["id"]
                    st.rerun()
        st.markdown("<style>" + "".join(f".st-key-pk_{key}_{t['id']} button {{border-left:5px solid {team_color(t['id'])};}}" for t in ts)
                    + "</style>", unsafe_allow_html=True)


def team_page(schedule, idx, season, cut, days, today, zone, show_all):
    favs = [tid for tid in (team_by_abbr(a) for a in st.session_state.favs) if tid]
    tid = st.session_state.get("team")
    if not tid or tid not in teams():
        page_head("Mon équipe", "Choisis ton équipe : son calendrier, son bilan, ses blessés, son effectif et ses actus, au même endroit.", "Ton équipe")
        team_picker("first")
        return
    t = team(tid)
    last = default_day(days, today)
    if st.session_state.get(f"tm_rev_{tid}"):
        cut = today + timedelta(days=1)
    table = standings(idx, season, cut)
    row = next((r for r in table.get(t["conf"], []) if r["tid"] == tid), None)
    league = [r for rows in table.values() for r in rows if r["n"]]
    off_rank = 1 + sum(1 for r in league if r["pf"] > row["pf"]) if row and row["n"] else None
    def_rank = 1 + sum(1 for r in league if r["pa"] < row["pa"]) if row and row["n"] else None
    mine = [g for g in schedule if tid in (g["home"], g["away"])]
    upcoming = [g for g in mine if not g["done"] and g["day"] >= today]
    past = [g for g in mine if g["done"] and g["day"] < cut]
    tz = ZONES[zone]
    c, alt = t.get("color", "#333"), t.get("alt", "#555")
    is_fav = tid in favs

    # Bandeau de l'équipe, puis ses chiffres (arrêtés avant la dernière nuit tant qu'elle n'est pas ouverte)
    conf_txt = "l'Est" if t["conf"] == "Est" else "l'Ouest"
    rank_txt = f"{row['rank']}{'er' if row['rank'] == 1 else 'e'} de {conf_txt}" if row and row["n"] else "Début de saison"
    stats = []
    if row and row["n"]:
        rk = lambda n: f"{n}{'er' if n == 1 else 'e'} de la NBA"
        stats = [("Bilan", f"{row['w']}-{row['l']}", rank_txt), ("Série", streak_badge(row["streak"]) or "–", "en cours"),
                 ("10 derniers", row["l10"], "victoires-défaites"), ("Domicile", row["home"], "à la maison"),
                 ("Extérieur", row["away"], "en déplacement"), ("Attaque", fr_num(row["pf"]), f"pts marqués · {rk(off_rank)}"),
                 ("Défense", fr_num(row["pa"]), f"pts encaissés · {rk(def_rank)}")]
    st.markdown(
        f"<div class='th' style='--c:{c}; --c2:{alt}'><div class='th-logo'>{logo(tid, 92)}</div><div class='th-main'>"
        f"<div class='th-k'>Conférence {esc(t['conf'])}{' · ★ mon équipe' if is_fav else ''}</div>"
        f"<h1>{esc(t['full'])}</h1><div class='th-sub'>{esc(rank_txt)}{' · ' + row['l10'] + ' sur les 10 derniers' if row and row['n'] >= 10 else ''}</div></div></div>"
        + (f"<div class='tstats'>{''.join(f'<div><small>{k}</small><b>{v}</b><i>{sub}</i></div>' for k, v, sub in stats)}</div>" if stats else ""),
        unsafe_allow_html=True)
    with st.container(key="tm_bar"):
        c1, c2, c3 = st.columns([3, 2, 2], vertical_alignment="center")
        c1.markdown(f"<p class='pg-note'>{esc(cut_note(cut, last, zone, today))}</p>", unsafe_allow_html=True)
        if cut <= today:
            c1.toggle(f"Inclure la dernière nuit ({night_label(last, zone)})", key=f"tm_rev_{tid}", help="Montre ses résultats dans les chiffres.")
        if favs and not is_fav:
            if c2.button(f"Revenir aux {team(favs[0])['name']}", icon=":material/star:", key=f"fav_back_{tid}", width="stretch"):
                st.session_state.team = favs[0]
                st.rerun()
        elif not is_fav:
            if c2.button(f"Choisir les {t['name']} comme mon équipe", icon=":material/star:", key=f"fav_add_{tid}", width="stretch",
                         help="Leurs matchs passeront en tête partout sur le site."):
                st.session_state.favs = [t["abbr"]]
                st.session_state.fav_changed = True
                track("set", x="équipe:" + t["abbr"])
                st.rerun()
        all_ids = sorted(teams(), key=lambda x: team(x)["name"])
        other = c3.selectbox("Voir une autre équipe", all_ids, index=all_ids.index(tid), format_func=lambda x: "Autre équipe : " + team(x)["full"],
                             key=f"tm_o_{tid}", label_visibility="collapsed")
        if other != tid:
            st.session_state.team = other
            st.rerun()

    # Prochain match (avec blessés et meneurs donnés par ESPN avant le match)
    nxt = upcoming[0] if upcoming else None
    left, right = st.columns([3, 2])
    if nxt:
        opp = nxt["away"] if nxt["home"] == tid else nxt["home"]
        tip = parse_dt(nxt.get("utc"))
        when = f"{rel_label(nxt['day'], zone, today) or night_short_title(nxt['day'], zone)}" + (f" · {fr_hour(tip.astimezone(tz))}" if tip else "")
        b2b = any(g["day"] == nxt["day"] - timedelta(days=1) for g in mine)
        live = next((g for g in day_games(nxt["day"]) if g["id"] == nxt["id"]), None)
        tv = watch_on(live, st.session_state.opts.get("pays", "FR"))[0] if live else ""
        left.markdown(
            f"<div class='nx'><div class='nx-k'>Prochain match</div><div class='nx-w'>{esc(when)}</div>"
            f"<div class='nx-m'>{mini_logo(tid, 44)}<b>{esc(t['name'])}</b><span>{'reçoivent' if nxt['home'] == tid else 'à'}</span>"
            f"{mini_logo(opp, 44)}<b>{team_link(opp)}</b><small>{record_txt(idx, opp, season, cut)}</small></div>"
            f"<div class='nx-x'>{'🏠 À domicile' if nxt['home'] == tid else '✈️ À l’extérieur'}"
            f"{' · 😴 2e match en 2 soirs' if b2b else ''}{' · 📺 ' + esc(tv) if tv else ''}</div>"
            f"{link('/?nuit=' + nxt['day'].isoformat(), 'Avant-match et vidéos ›', 'pd-go')}</div>", unsafe_allow_html=True)
        summ = summary(nxt["id"], bucket(1800)) or {}
        inj = (summ.get("injuries") or {}).get(tid) or []
        lead = (summ.get("leaders") or {}).get(tid) or {}
        cats = [("points", "Points"), ("rebounds", "Rebonds"), ("assists", "Passes")]
        by_name = {norm(p["name"]): p["id"] for p in team_roster(tid)}
        lead_html = "".join(f"<li><span>{lab}</span><b>{player_link(by_name.get(norm(lead[k][0]), ''), lead[k][0])}</b><i>{esc(lead[k][1])}</i></li>"
                            for k, lab in cats if k in lead)
        inj_html = "".join(f"<li><b>{esc(i['name'])}</b><span class='inj {'o' if 'out' in norm(i['status']) else 'q'}'>{esc(status_fr(i['status']))}</span>"
                           f"<i>{esc(INJURY_FR.get(norm(i.get('what')), i.get('what', '')))}</i></li>" for i in inj)
        right.markdown(f"<div class='tbox'><div class='tbox-h'>🩹 Infirmerie</div><ul class='inj-l'>{inj_html or '<li class=ok>Personne à l’infirmerie 💪</li>'}</ul></div>"
                       + (f"<div class='tbox'><div class='tbox-h'>⭐ Meneurs de la saison</div><ul class='lead-l'>{lead_html}</ul></div>" if lead_html else ""),
                       unsafe_allow_html=True)
    else:
        left.info("Plus de match prévu pour l'instant.")

    # Calendrier et derniers matchs
    cal, res = st.columns(2)
    rows = []
    for g in upcoming[:10]:
        home = g["home"] == tid
        opp = g["away"] if home else g["home"]
        tip = parse_dt(g.get("utc"))
        b2b = any(x["day"] == g["day"] - timedelta(days=1) for x in mine)
        rows.append(f"<li><span class='d'>{esc(short_date(g['day']))}</span><span class='h'>{'vs' if home else '@'}</span>"
                    f"{mini_logo(opp, 24)}{team_link(opp)}<span class='r'>{fr_hour(tip.astimezone(tz)) if tip else ''}{' 😴' if b2b else ''}</span></li>")
    cal.markdown(f"<div class='tbox'><div class='tbox-h'>📅 Les 10 prochains matchs</div><ul class='cal-l'>{''.join(rows) or '<li>Rien de prévu.</li>'}</ul></div>",
                 unsafe_allow_html=True)
    with cal:
        agenda_button([tid], f"t{tid}")
    rows = []
    for g in reversed(past[-10:]):
        home = g["home"] == tid
        opp = g["away"] if home else g["home"]
        us, them = (g["hs"], g["as"]) if home else (g["as"], g["hs"])
        won = us > them
        rows.append(f"<li><span class='d'>{esc(short_date(g['day']))}</span><span class='h'>{'vs' if home else '@'}</span>{mini_logo(opp, 24)}"
                    f"{team_link(opp)}{link('/?nuit=' + g['day'].isoformat(), '▶', 'rv', 'Résumé et stats')}"
                    f"<span class='r res'><span class='wl {'w' if won else 'l'}'>{'V' if won else 'D'}</span> {us}-{them}</span>"
                    f"<span class='r hid'>? – ?</span></li>")
    checked = " checked" if show_all else ""
    res.markdown(f"<div class='tbox rbox'><input type='checkbox' class='tg tg-r' id='rv{tid}'{checked}>"
                 f"<div class='tbox-h'>🏀 Les derniers matchs <label for='rv{tid}' class='cbtn pill-n'><span class='off'>👁 Voir les résultats</span>"
                 f"<span class='on'>🙈 Cacher</span></label></div><ul class='cal-l'>{''.join(rows) or '<li>Pas encore de match joué.</li>'}</ul></div>",
                 unsafe_allow_html=True)

    # Effectif
    roster = team_roster(tid)
    if roster:
        order = {"G": 0, "PG": 0, "SG": 1, "G-F": 2, "F": 3, "SF": 3, "F-G": 3, "PF": 4, "F-C": 5, "C-F": 6, "C": 7}
        def card(p):
            photo = f"<img src='{esc(p['photo'])}' alt='' loading='lazy'>" if p["photo"] else ""
            inj = f"<span class='inj-b'>🩹 {esc(status_fr(p['inj']))}</span>" if p["inj"] else ""
            return (f"<div class='pl-c{' out' if p['inj'] else ''}'><div class='pl-ph' style='--c:{c}'>{photo}"
                    f"<span class='no'>{esc(p['num'])}</span></div><b>{player_link(p['id'], p['name'])}</b><small>{esc(POS_FR.get(p['pos'], p['pos']))}</small>{inj}</div>")
        cards = "".join(card(p) for p in sorted(roster, key=lambda p: (order.get(p["pos"], 9), p["name"])))
        st.markdown(f"<div class='sec-h'>👥 L'effectif <span>{len(roster)} joueurs</span></div><div class='roster'>{cards}</div>",
                    unsafe_allow_html=True)

    # Actus (peuvent contenir des résultats : repliées)
    news = team_news(tid)
    if news:
        items = "".join(f"<li><a href='{esc(n['href'])}' target='_blank' rel='noopener'><b>{esc(n['title'])}</b>"
                        f"<small>{esc(n['desc'])}</small></a><i>{esc(short_date(n['when'].astimezone(tz).date())) if n['when'] else ''}</i></li>"
                        for n in news)
        st.markdown(f"<details class='news'><summary>📰 Les dernières actus <span>(en anglais, ESPN · peuvent dévoiler des résultats)</span></summary>"
                    f"<ul>{items}</ul></details>", unsafe_allow_html=True)


PAGES_CSS = """
<style>
/* ---- v023 : en-tête, onglets, bande des nuits ---- */
.block-container {padding-top: 1.2rem !important;}
.st-key-gobox {position:absolute !important; left:-9999px; top:0; width:1px; height:1px; overflow:hidden;}
.st-key-hdr [data-testid="stHorizontalBlock"] {flex-wrap:nowrap; align-items:center;}
.st-key-hdr [data-testid="stColumn"]:last-child {flex:0 0 auto !important; width:auto !important; min-width:0 !important;}
.bb-brand small {display:inline-block; margin-left:10px; font-family:'Barlow', sans-serif; font-size:.72rem; font-weight:700; letter-spacing:.08em;
  color:#c3cad6; border:1px solid #2a3344; border-radius:999px; padding:3px 9px; vertical-align:middle; text-transform:uppercase;}
.st-key-tabs {position:sticky; top:0; z-index:50; background:rgba(11,15,23,.92); backdrop-filter:blur(10px); padding:6px 0 8px; margin:-4px 0 4px;}
.st-key-tabs [data-testid="stHorizontalBlock"] {flex-wrap:nowrap; gap:6px;}
.st-key-tabs [data-testid="stColumn"] {min-width:0 !important; flex:1 1 0 !important; width:auto !important;}
.st-key-tabs button {min-height:48px; border-radius:14px; border:1px solid #222b3b; background:#10151f; padding:4px 6px;}
.st-key-tabs button:hover {border-color:#3a465c; background:#161d2b;}
.st-key-tabs button p {font-weight:700; font-size:.98rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.st-key-tabs button[kind="primary"], .st-key-tabs button[data-testid="stBaseButton-primary"] {background:#ffc75a; border-color:#ffc75a; color:#1a1205;}
.st-key-tabs button[kind="primary"] p, .st-key-tabs button[data-testid="stBaseButton-primary"] p,
.st-key-tabs button[data-testid="stBaseButton-primary"] span {color:#1a1205 !important;}
@media (max-width: 760px) {
  .st-key-tabs button {min-height:58px; padding:4px 2px;}
  .st-key-tabs button span[data-has-shortcut] {display:flex; flex-direction:column; align-items:center; gap:2px;}
  .st-key-tabs button .stMarkdownEllipsis {overflow:visible;}
  .st-key-tabs button p {font-size:.68rem; letter-spacing:-.02em;}
  .st-key-tabs [data-testid="stHorizontalBlock"] {gap:3px !important;} .st-key-tabs button {padding:4px 0 !important;}
  .bb-brand small {display:none;}
  .st-key-tabs button span[data-testid="stIconMaterial"] {font-size:1.35rem;}
  .st-key-tabs [data-testid="stHorizontalBlock"] {gap:4px;}
  .st-key-hdr button p {display:none;}
}
/* bande des nuits : petit texte (jour) au-dessus, dates en grand, jamais coupées */
.st-key-nav [data-testid="stColumn"] {flex:1 0 92px !important; min-width:92px !important;}
.st-key-nav [data-testid="stColumn"]:first-child, .st-key-nav [data-testid="stColumn"]:nth-last-child(2), .st-key-nav [data-testid="stColumn"]:nth-last-child(3),
.st-key-nav [data-testid="stColumn"]:last-child {flex:0 0 44px !important; min-width:44px !important;}
.st-key-nav button {flex-direction:column; min-height:58px !important; padding:6px 4px !important;}
.st-key-nav button::before {display:block; font-family:'Barlow', sans-serif; font-size:.72rem; font-weight:600; letter-spacing:.01em;
  color:#9aa4b8; line-height:1.1; white-space:nowrap;}
.st-key-nav button[data-testid="stBaseButton-primary"]::before {color:#4a3510;}
.st-key-nav button p {font-size:1.22rem !important; line-height:1.05; white-space:nowrap;}
.st-key-nav button::after {content:''; position:absolute; top:7px; right:7px; width:9px; height:9px; border-radius:50%; background:transparent;}
.st-key-nav button:disabled {opacity:.35;}
.st-key-nav [data-testid="stPopover"] button, .st-key-nav [data-testid="stPopoverButton"] {min-height:58px !important;}
.st-key-navw {background:#10141e; border:1px solid #1e2533; border-radius:16px; padding:6px;}
.st-key-navw [data-testid="stHorizontalBlock"] {flex-wrap:nowrap; align-items:center;}
.st-key-navw [data-testid="stColumn"]:first-child, .st-key-navw [data-testid="stColumn"]:last-child {flex:0 0 48px !important; min-width:48px !important;}
.st-key-navw [data-testid="stColumn"]:nth-child(2) {flex:1 1 auto !important; min-width:0 !important;}
.st-key-navw button {min-height:52px; background:transparent; border-color:transparent;}
.wrow {grid-template-columns:96px minmax(0,1fr) auto auto !important;} .wrow .wgo {display:flex; gap:6px; align-items:center; justify-content:flex-end;}
.wrow .wgo .cbtn {padding:4px 10px; font-size:.82rem;}
@media (max-width: 760px) {.wrow {grid-template-columns:minmax(0,1fr) auto !important;} .wrow .d {grid-column:1 / -1;} .wrow .wgo {grid-column:1 / -1; justify-content:flex-start;}}
.wk-t {text-align:center; line-height:1.15; padding:6px 0;} .wk-t b {display:block; font-family:'Barlow Condensed', sans-serif; font-size:1.5rem; text-transform:uppercase;}
.wk-t span {color:#9aa4b8; font-size:.85rem;}
/* focus clavier visible, cibles tactiles */
button:focus-visible, a:focus-visible, summary:focus-visible, label:focus-visible {outline:3px solid #ffc75a !important; outline-offset:2px;}
.hello {background:linear-gradient(135deg, rgba(255,199,90,.14), rgba(255,199,90,.04)); border:1px solid rgba(255,199,90,.35); border-radius:16px; padding:14px 18px; margin:4px 0 6px;}
.hello b {color:#ffd98a;} .hello p {margin:.35rem 0 0; color:#d5dbe6; font-size:.95rem;}
/* pages */
.pg-head {margin:10px 0 6px;} .pg-head h1 {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-size:2.1rem; margin:0; padding:0; line-height:1.05;}
.pg-head p {color:#9aa4b8; margin:.2rem 0 0;} .pg-k {color:#ffc75a; font-weight:700; font-size:.75rem; letter-spacing:.12em; text-transform:uppercase;}
.pg-note {color:#9aa4b8; font-size:.86rem; margin:.3rem 0 .6rem;}
.pg-foot {margin:42px 0 0; padding:16px 0 4px; border-top:1px solid #1e2533; color:#6f7a8f; font-size:.8rem; text-align:center; line-height:1.6;}
a.tl {color:inherit !important; text-decoration:none !important; font-weight:700;} a.tl:hover {text-decoration:underline !important; text-decoration-color:#ffc75a !important;}
img.ml {vertical-align:middle; border-radius:50%; flex:none;}
a.pd-go, a.lk {color:#ffc75a !important; text-decoration:none !important; font-weight:700; font-size:.9rem; white-space:nowrap;}
a.pd-go:hover {text-decoration:underline !important;}
/* programme */
.pd {background:#10151f; border:1px solid #1f2736; border-radius:18px; padding:6px 14px 8px; margin:0 0 14px;}
.pd-h {display:flex; align-items:center; gap:10px; padding:8px 0 8px; border-bottom:1px solid #1d2432;}
.pd-h i {display:block; font-style:normal; color:#ffc75a; font-weight:700; font-size:.72rem; letter-spacing:.1em; text-transform:uppercase;}
.pd-h b {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-size:1.25rem; letter-spacing:.01em; margin-right:8px;}
.pd-h span {color:#8a94a8; font-size:.85rem; white-space:nowrap;} .pd-h a {margin-left:auto;}
.pr {display:grid; grid-template-columns:70px 1fr auto; align-items:center; gap:12px; padding:10px 0; border-bottom:1px solid #171d29;}
.pr:last-child {border-bottom:none;} .pr.f {background:linear-gradient(90deg, rgba(255,199,90,.07), transparent 60%); margin:0 -14px; padding:10px 14px;}
.pr-t {font-family:'Barlow Condensed', sans-serif; font-weight:700; font-size:1.3rem; color:#e8ecf3;} .pr-t .live {color:#ff6b6b; font-size:1rem;}
.pr-m {display:flex; align-items:center; gap:12px; flex-wrap:wrap; min-width:0;}
.pr-m .side {display:flex; align-items:center; gap:8px; min-width:0;} .pr-m small {color:#8a94a8; font-weight:600; margin-left:3px;}
.pr-m .at {color:#5d6880; font-weight:700;}
.pr-x {display:flex; gap:6px; flex-wrap:wrap; justify-content:flex-end;}
.bdg {font-size:.75rem; font-weight:700; padding:3px 8px; border-radius:999px; background:#1c2433; color:#c3cad6; white-space:nowrap;}
.bdg.fav {background:rgba(255,199,90,.16); color:#ffd98a;} .bdg.hot {background:rgba(245,132,38,.18); color:#ffb070;}
.tv, .wt {font-size:.78rem; color:#8a94a8; white-space:nowrap;}
.wt.ok {color:#ffd98a; font-weight:700; background:rgba(255,199,90,.12); padding:3px 8px; border-radius:999px;}
@media (max-width: 760px) {
  .pr {grid-template-columns:52px 1fr; gap:8px;} .pr-x {grid-column:2; justify-content:flex-start;}
  .pr-m {flex-direction:column; align-items:flex-start; gap:4px;} .pr-m .at {display:none;} .pr-t {font-size:1.1rem;}
}
/* classement */
.stands {display:grid; grid-template-columns:1fr 1fr; gap:16px;}
@media (max-width: 900px) {.stands {grid-template-columns:1fr;}}
.stand {background:#10151f; border:1px solid #1f2736; border-radius:18px; padding:10px 6px 6px; overflow-x:auto;}
.stand-h {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-weight:700; font-size:1.2rem; padding:2px 10px 8px;}
table.stt {width:100%; border-collapse:collapse; font-size:.9rem;}
.stt th {color:#7c879b; font-weight:600; font-size:.75rem; text-transform:uppercase; padding:6px 6px; text-align:center; border-bottom:1px solid #1d2432;}
.stt td {padding:7px 6px; text-align:center; border:none; border-bottom:1px solid #161c27; white-space:nowrap;}
.stt th {border:none; border-bottom:1px solid #1d2432;} .stt tr {border:none; background:transparent;}
.stt .tmc {text-align:left;} .stt td.tmc {display:flex; align-items:center; gap:8px;} .stt .rk {width:28px; color:#8a94a8; font-weight:700;}
.stt tr td:first-child {border-left:4px solid transparent;} .stt tr.z1 td:first-child {border-left-color:#22c55e;}
.stt tr.z2 td:first-child {border-left-color:#f5a524;} .stt tr.z3 td:first-child {border-left-color:#3a4356;}
.stt tr.z2:first-of-type td, .stt tr.z1 + tr.z2 td {border-top:2px dashed #2b3445;} .stt tr.z2 + tr.z3 td {border-top:2px dashed #2b3445;}
.stt tr.fav {background:rgba(255,199,90,.08);} .stt .star {color:#ffc75a;} .stt .pc {color:#9aa4b8;}
.stk {font-weight:800; font-size:.8rem; padding:2px 7px; border-radius:7px;} .stk.w {background:rgba(34,197,94,.16); color:#4ade80;}
.stk.l {background:rgba(239,68,68,.15); color:#f87171;}
.legend {color:#8a94a8; font-size:.8rem; margin:10px 2px; display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center;}
.lg {display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:-8px; vertical-align:middle;} .lg.z1 {background:#22c55e;}
.lg.z2 {background:#f5a524;} .lg.z3 {background:#3a4356;}
@media (max-width: 640px) {.hide-s {display:none;}}
/* page équipe */
.th {display:flex; align-items:center; gap:20px; padding:22px 24px; border-radius:22px; margin:10px 0 0; position:relative; overflow:hidden;
  background:linear-gradient(rgba(8,10,16,.45), rgba(8,10,16,.55)), repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 2px, transparent 2px 11px),
  linear-gradient(120deg, var(--c) 0%, var(--c) 58%, var(--c2) 58.5%, var(--c2) 100%); border:1px solid rgba(255,255,255,.12);}
.th-logo img {filter:drop-shadow(0 8px 18px rgba(0,0,0,.5)); background:rgba(255,255,255,.08); border-radius:50%; padding:6px;}
.th h1 {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-size:2.6rem; line-height:1; margin:2px 0; padding:0; color:#fff;}
.th-k {color:rgba(255,255,255,.8); font-size:.78rem; font-weight:700; letter-spacing:.1em; text-transform:uppercase;}
.th-sub {color:#fff; font-weight:600; opacity:.9;}
.tstats {display:grid; grid-template-columns:repeat(7, 1fr); gap:8px; margin:10px 0 0;}
.tstats > div {background:#10151f; border:1px solid #1f2736; border-radius:14px; padding:9px 12px; min-width:0;}
.tstats small {display:block; color:#8a94a8; font-size:.72rem; text-transform:uppercase; letter-spacing:.05em; font-weight:700;}
.tstats b {display:block; font-family:'Barlow Condensed', sans-serif; font-size:1.65rem; line-height:1.15;}
.tstats b .stk {font-size:1.1rem; padding:1px 9px;}
.tstats i {display:block; color:#7c879b; font-style:normal; font-size:.74rem; line-height:1.25;}
.st-key-tm_bar {margin-top:4px;} .st-key-tm_bar .pg-note {margin:0;}
@media (max-width: 640px) {.tstats {grid-template-columns:repeat(3, 1fr) !important;} .tstats b {font-size:1.35rem;} .tstats i {font-size:.68rem;}}
@media (max-width: 900px) {.tstats {grid-template-columns:repeat(4, 1fr);} .th h1 {font-size:2rem;} .th {padding:16px; gap:14px;} .th-logo img {width:64px; height:64px;}}
.nx {background:#10151f; border:1px solid #1f2736; border-radius:18px; padding:14px 16px; margin:6px 0 12px;}
.nx-k, .tbox-h {color:#ffc75a; font-weight:700; font-size:.78rem; letter-spacing:.1em; text-transform:uppercase;}
.nx-w {font-family:'Barlow Condensed', sans-serif; font-size:1.5rem; font-weight:700; text-transform:uppercase; margin:2px 0 8px;}
.nx-m {display:flex; align-items:center; gap:10px; flex-wrap:wrap; font-size:1.15rem;} .nx-m span {color:#8a94a8; font-size:.95rem;}
.nx-m small {color:#8a94a8;} .nx-x {color:#c3cad6; font-size:.9rem; margin:10px 0;}
.tbox {background:#10151f; border:1px solid #1f2736; border-radius:18px; padding:12px 16px; margin:6px 0 12px;}
.tbox ul {list-style:none; margin:6px 0 0; padding:0;} .tbox li {display:flex; align-items:center; gap:8px; padding:7px 0; border-bottom:1px solid #171d29; flex-wrap:wrap;}
.tbox li:last-child {border-bottom:none;} .tbox li i {color:#8a94a8; font-style:normal; font-size:.85rem; margin-left:auto;}
.lead-l li span {color:#8a94a8; width:70px; font-size:.85rem;} .lead-l li i {font-family:'Barlow Condensed', sans-serif; font-size:1.15rem; color:#e8ecf3 !important;}
.inj {font-size:.75rem; font-weight:700; padding:2px 8px; border-radius:999px;} .inj.o {background:rgba(239,68,68,.16); color:#f87171;}
.inj.q {background:rgba(245,165,36,.16); color:#fbbf24;} .ok {color:#9aa4b8;}
.rbox .tg {display:none;}
.cal-l .d {width:100px; white-space:nowrap; color:#c3cad6; font-weight:600; font-size:.9rem;} .cal-l .h {width:22px; color:#6f7a8f; font-weight:700; font-size:.8rem;}
.cal-l .r {margin-left:auto; color:#c3cad6; font-family:'Barlow Condensed', sans-serif; font-weight:700; font-size:1.05rem;}
.cal-l a.rv {color:#ffc75a !important; text-decoration:none !important; font-size:.8rem; padding:2px 6px; border:1px solid #3a3320; border-radius:7px;}
.rbox .tbox-h {display:flex; align-items:center; gap:8px;} .rbox .tbox-h label {margin-left:auto; text-transform:none; letter-spacing:0;}
.rbox .res {display:none;} .rbox .hid {color:#5d6880;}
.tg-r:checked ~ ul .res {display:inline;} .tg-r:checked ~ ul .hid {display:none;}
.tg-r:checked ~ .tbox-h .pill-n .on {display:inline;} .tg-r:checked ~ .tbox-h .pill-n .off {display:none;}
.rbox .pill-n .on {display:none;}
.wl {display:inline-block; width:22px; text-align:center; border-radius:6px; font-size:.85rem;} .wl.w {background:rgba(34,197,94,.18); color:#4ade80;}
.wl.l {background:rgba(239,68,68,.16); color:#f87171;}
.sec-h {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-weight:700; font-size:1.35rem; margin:14px 0 8px;}
.sec-h span {color:#8a94a8; font-family:'Barlow', sans-serif; font-size:.85rem; text-transform:none; font-weight:500;}
.roster {display:grid; grid-template-columns:repeat(auto-fill, minmax(132px, 1fr)); gap:10px;}
.pl-c {background:#10151f; border:1px solid #1f2736; border-radius:16px; padding:10px; text-align:center; position:relative;}
.pl-c.out {opacity:.75;} .pl-c b {display:block; font-size:.92rem; line-height:1.2; margin-top:6px;} .pl-c small {color:#8a94a8;}
.pl-ph {height:84px; border-radius:12px; background:linear-gradient(160deg, var(--c), #10151f); position:relative; overflow:hidden; display:flex; align-items:flex-end; justify-content:center;}
.pl-ph img {height:84px; width:auto;} .pl-ph .no {position:absolute; top:4px; left:8px; font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.3rem; color:rgba(255,255,255,.85);}
.inj-b {display:inline-block; margin-top:4px; font-size:.72rem; font-weight:700; color:#f87171;}
details.news {background:#10151f; border:1px solid #1f2736; border-radius:18px; padding:12px 16px; margin:16px 0;}
details.news summary {cursor:pointer; font-weight:700; font-size:1.05rem;} details.news summary span {color:#8a94a8; font-weight:500; font-size:.82rem;}
details.news ul {list-style:none; padding:0; margin:8px 0 0;} details.news li {display:flex; gap:10px; padding:9px 0; border-bottom:1px solid #171d29;}
details.news a {color:#e8ecf3 !important; text-decoration:none !important; flex:1;} details.news a small {display:block; color:#8a94a8;}
details.news li i {color:#6f7a8f; font-style:normal; font-size:.8rem; white-space:nowrap;}
.pick-h {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-weight:700; font-size:1.2rem; margin:14px 0 6px;}
[class*="st-key-pick_"] button {min-height:48px; justify-content:flex-start; text-align:left; font-weight:700;}
@media (max-width: 640px) {[class*="st-key-pick_"] [data-testid="stHorizontalBlock"] {flex-wrap:wrap;}
  [class*="st-key-pick_"] [data-testid="stColumn"] {flex:1 1 45% !important; min-width:45% !important;}}
@media (prefers-reduced-motion: reduce) {*, *::before, *::after {animation-duration:.01ms !important; animation-iteration-count:1 !important; transition:none !important;}}
</style>
"""


# =========================================================================
# JOUEURS (v024) : journal des feuilles de match, fiches, meilleurs, nos joueurs, infirmerie de la ligue
# =========================================================================
def _box_line(stats):
    """Ligne de stats ESPN → [min, pts, reb, pas, int, ctr, bp, tirs réussis, tentés, 3 pts réussis, tentés, LF réussis, tentés]."""
    def n(k):
        try:
            return float(str(stats.get(k, "0")).split(":")[0].lstrip("+") or 0)
        except ValueError:
            return 0.0

    def pair(k):
        try:
            a, b = str(stats.get(k, "")).split("-")
            return int(a), int(b)
        except ValueError:
            return 0, 0
    fgm, fga = pair("FG")
    tpm, tpa = pair("3PT")
    ftm, fta = pair("FT")
    return [n("MIN"), n("PTS"), n("REB"), n("AST"), n("STL"), n("BLK"), n("TO"), fgm, fga, tpm, tpa, ftm, fta]


def _players_tick(db):
    """Ajoute au journal les matchs terminés pas encore lus (au plus 120 par passage)."""
    log = db["log"]
    today = datetime.now(NY).date()
    season = season_of(today)
    done_days = set(log["days"])
    added = 0
    d = date(season - 1, 10, 1)
    while d < today and added < 120:
        if d.isoformat() in done_days:
            d += timedelta(days=1)
            continue
        data = get_json(f"{ESPN}/scoreboard", {"dates": d.strftime("%Y%m%d")})
        if data is None:
            break
        complete = True
        for e in data.get("events") or []:
            g = _parse_event(e)
            if g["season_type"] not in (2, 3):
                continue
            if not g["completed"]:
                complete = False
                continue
            if g["id"] in log["g"]:
                continue
            s = summary_raw(g["id"])
            if not s or not s.get("box"):
                complete = False
                continue
            rows = {}
            for tid, players in s["box"].items():
                for r in players:
                    line = _box_line(r["stats"])
                    if r.get("id") and not r.get("dnp") and line[0] > 0:
                        rows[r["id"]] = [tid, 1 if r.get("starter") else 0] + line
                        log["n"][r["id"]] = r["name"]
            log["g"][g["id"]] = {"d": d.isoformat(), "h": g["home"]["id"], "a": g["away"]["id"], "t": g["season_type"], "p": rows}
            added += 1
        if complete and d < today - timedelta(days=1):
            done_days.add(d.isoformat())
        d += timedelta(days=1)
    log["days"] = sorted(done_days)
    if added:
        db["v"] += 1
        db["store"].save("log.json", log, f"Joueurs : {added} matchs ajoutés")
    return added


@st.cache_resource(show_spinner=False)
def players_db():
    """Journal de toutes les feuilles de match de la saison (stats de chaque joueur), complété par un fil de fond toutes les
    15 minutes et gardé sur GitHub (joueurs/log.json, branche data), comme les statistiques de visite."""
    store = F.Store(SESSION, str(_secret("github", "token", "")), str(_secret("github", "repo", "")),
                    str(_secret("github", "branch", "data")), CACHE_DIR, folder="joueurs")
    log = store.load("log.json", {}) or {}
    for k, v in (("g", {}), ("n", {}), ("days", [])):
        log.setdefault(k, v)
    db = {"log": log, "v": 1, "store": store, "memo": {}}

    def loop():
        while True:
            try:
                while _players_tick(db) >= 120:   # rattrapage du début de saison : on enchaîne
                    pass
            except Exception as e:
                log_warn = f"Journal des joueurs : {type(e).__name__}"
                log.setdefault("err", log_warn)
                S.add_error(log_warn)
            time.sleep(900)
    if not any(t.name == "joueurs" for t in threading.enumerate()):
        threading.Thread(target=loop, daemon=True, name="joueurs").start()
    return db


def player_games(db, pid, cut=None):
    """Matchs (saison régulière et play-offs) d'un joueur avant le jour `cut`, dans l'ordre."""
    out = []
    lim = cut.isoformat() if cut else "9999"
    for gid, g in list(db["log"]["g"].items()):
        r = g["p"].get(pid)
        if r and g["d"] < lim:
            tid = r[0]
            out.append({"gid": gid, "d": date.fromisoformat(g["d"]), "tid": tid, "opp": g["a"] if g["h"] == tid else g["h"],
                        "home": g["h"] == tid, "st": r[1], "l": r[2:], "t": g.get("t", 2)})
    return sorted(out, key=lambda x: x["d"])


def averages(games):
    """Moyennes d'une liste de matchs (lignes `_box_line`)."""
    n = len(games)
    if not n:
        return None
    tot = [sum(g["l"][i] for g in games) for i in range(13)]
    pct = lambda m, a: (m / a * 100) if a else None
    return {"gp": n, "min": tot[0] / n, "pts": tot[1] / n, "reb": tot[2] / n, "ast": tot[3] / n, "stl": tot[4] / n, "blk": tot[5] / n,
            "to": tot[6] / n, "fg": pct(tot[7], tot[8]), "3pm": tot[9] / n, "3p": pct(tot[9], tot[10]), "ft": pct(tot[11], tot[12]),
            "fga": tot[8] / n, "3pa": tot[10] / n, "gs": sum(g["st"] for g in games)}


def season_table(db, cut):
    """{id joueur: moyennes de la saison régulière + équipe + 5 derniers} avant `cut` (mémorisé par version du journal)."""
    key = (db["v"], cut.isoformat() if cut else "")
    if key in db["memo"]:
        return db["memo"][key]
    lim = cut.isoformat() if cut else "9999"
    per = defaultdict(list)
    for gid, g in list(db["log"]["g"].items()):
        if g["d"] >= lim or g.get("t", 2) != 2:
            continue
        for pid, r in g["p"].items():
            per[pid].append({"d": g["d"], "tid": r[0], "st": r[1], "l": r[2:]})
    out = {}
    for pid, games in per.items():
        games.sort(key=lambda x: x["d"])
        a = averages(games)
        last5 = averages(games[-5:])
        a.update(tid=games[-1]["tid"], last5=last5["pts"], name=db["log"]["n"].get(pid, "?"))
        out[pid] = a
    db["memo"] = {key: out}
    return out


@st.cache_data(ttl=86400, show_spinner=False)
def league_players():
    """{id joueur: fiche d'effectif} pour les 30 équipes."""
    with ThreadPoolExecutor(10) as pool:
        lists = list(pool.map(team_roster, list(teams())))
    return {p["id"]: p for lst in lists for p in lst if p["id"]}


@st.cache_data(ttl=1800, show_spinner=False)
def league_injuries():
    """Infirmerie de la ligue : ESPN (page des blessés), sinon les effectifs. [{tid, pid, name, status, type, back, note}]."""
    players = league_players()
    by_name = {norm(p["name"]): p for p in players.values()}
    out = []
    d = get_json(f"{ESPN}/injuries") or {}
    for blk in d.get("injuries") or []:
        tid = str(blk.get("id") or "")
        if tid not in teams():
            tid = next((t for t, x in teams().items() if norm(x["full"]) == norm(blk.get("displayName"))), "")
        for i in blk.get("injuries") or []:
            ath = i.get("athlete") or {}
            p = players.get(str(ath.get("id") or "")) or by_name.get(norm(ath.get("displayName")))
            det = i.get("details") or {}
            out.append({"tid": tid or (p or {}).get("team", ""), "pid": (p or {}).get("id", ""), "name": ath.get("displayName", ""),
                        "status": i.get("status", ""), "type": det.get("type") or (i.get("type") or {}).get("description", ""),
                        "back": det.get("returnDate", ""), "note": i.get("shortComment", ""), "date": i.get("date", "")})
    if not out:
        out = [{"tid": p["team"], "pid": p["id"], "name": p["name"], "status": p["inj"], "type": p.get("inj_type", ""),
                "back": p.get("inj_back", ""), "note": "", "date": ""} for p in players.values() if p["inj"]]
    return out


COUNTRY = {"FR": ("France", "🇫🇷", "Les Français de la NBA"), "CA": ("Canada", "🇨🇦", "Les Canadiens de la NBA")}
INJ_ORDER = {"Absent": 0, "Longue absence": 0, "Suspendu": 1, "Peu probable": 2, "Incertain": 3, "Probable": 4}


def fr_date_iso(iso):
    try:
        d = date.fromisoformat(str(iso)[:10])
        return f"{'1er' if d.day == 1 else d.day} {MOIS_COURT[d.month - 1]}"
    except ValueError:
        return ""


def player_link(pid, name):
    return link(f"/?vue=joueurs&joueur={pid}", esc(name), "tl", "Fiche du joueur") if pid else esc(name)


def headshot(p, size=56):
    url = (p or {}).get("photo") or ""
    return f"<img class='hs' src='{esc(url)}' width='{size}' height='{size}' alt='' loading='lazy'>" if url else "<span class='hs'></span>"


def f1(x):
    return "–" if x is None else fr_num(x)


def pct(x):
    return "–" if x is None else f"{fr_num(x)} %"


def next_game_of(schedule, tid, today):
    return next((g for g in schedule if tid in (g["home"], g["away"]) and not g["done"] and g["day"] >= today), None)


def player_page(pid, schedule, cut, today, zone):
    db = players_db()
    info = league_players().get(pid) or {}
    games = [g for g in player_games(db, pid, cut) if g["t"] == 2]
    tid = info.get("team") or (games[-1]["tid"] if games else "")
    name = info.get("name") or db["log"]["n"].get(pid, "Joueur")
    t = team(tid) if tid else {"color": "#333", "alt": "#555", "name": "", "full": ""}
    a = averages(games)
    table = season_table(db, cut)
    ranks = {}
    if a:
        qual = [x for x in table.values() if x["gp"] >= max(3, a["gp"] // 2)]
        for k in ("pts", "reb", "ast"):
            ranks[k] = 1 + sum(1 for x in qual if x[k] > a[k])
    flag = next((f for c, (country, f, _) in COUNTRY.items() if country == info.get("country")), "")
    bio = [x for x in (POS_FR.get(info.get("pos", ""), info.get("pos", "")),
                       f"{info['age']} ans" if info.get("age") else "",
                       f"{info['cm'] / 100:.2f} m".replace(".", ",") if info.get("cm") else "",
                       f"{info['kg']} kg" if info.get("kg") else "",
                       f"né à {info['city']}" + (f" ({info['country']})" if info.get("country") else "") if info.get("city") else "",
                       ("rookie" if info.get("exp") == 0 else f"{info['exp']}e saison en NBA") if info.get("exp") is not None else "",
                       info.get("college", "")) if x]
    inj = ""
    if info.get("inj"):
        inj = (f"<span class='inj o'>🩹 {esc(status_fr(info['inj']))}</span> {esc(INJURY_FR.get(norm(info.get('inj_type')), info.get('inj_type', '')))}"
               + (f" · retour prévu vers le {fr_date_iso(info['inj_back'])}" if info.get("inj_back") else ""))
    team_txt = team_link(tid, t["full"]) if tid else ""
    st.markdown(
        f"<div class='ph' style='--c:{t.get('color', '#333')}; --c2:{t.get('alt', '#555')}'>{headshot(info, 132)}<div>"
        f"<div class='th-k'>{team_txt}{' · n°' + esc(info['num']) if info.get('num') else ''}</div>"
        f"<h1>{flag + ' ' if flag else ''}{esc(name)}</h1><div class='ph-bio'>{esc(' · '.join(bio))}</div>"
        f"{f'<div class=ph-inj>{inj}</div>' if inj else ''}</div></div>", unsafe_allow_html=True)
    if not a:
        st.info("Pas encore de match joué cette saison (ou le journal des matchs se remplit : reviens dans quelques minutes).")
        return
    rk = lambda k: f"{ranks[k]}e de la NBA" if ranks.get(k) and ranks[k] <= 50 else ""
    tiles = [("Points", f1(a["pts"]), rk("pts")), ("Rebonds", f1(a["reb"]), rk("reb")), ("Passes", f1(a["ast"]), rk("ast")),
             ("Minutes", f1(a["min"]), f"{a['gp']} matchs · {a['gs']} titulaire"), ("Tirs", pct(a["fg"]), f"{f1(a['fga'])} tentés"),
             ("À 3 points", pct(a["3p"]), f"{f1(a['3pm'])} réussis / match"), ("Lancers francs", pct(a["ft"]), ""),
             ("Interceptions", f1(a["stl"]), f"{f1(a['blk'])} contres")]
    st.markdown("<div class='tstats ps'>" + "".join(f"<div><small>{k}</small><b>{v}</b><i>{sub}</i></div>" for k, v, sub in tiles) + "</div>"
                + f"<p class='pg-note'>Moyennes de la saison régulière. {esc(cut_note(cut, default_day(sorted({g['day'] for g in schedule}), today), zone, today))}</p>",
                unsafe_allow_html=True)
    left, right = st.columns([3, 2])
    pts = [g["l"][1] for g in games]
    if len(pts) >= 2:
        w, h, mx = 520, 120, max(pts + [10])
        step = w / max(1, len(pts) - 1)
        line = " ".join(f"{i * step:.1f},{h - p / mx * (h - 12) - 4:.1f}" for i, p in enumerate(pts))
        avg_y = h - a["pts"] / mx * (h - 12) - 4
        best = max(games, key=lambda g: g["l"][1])
        left.markdown(
            f"<div class='tbox'><div class='tbox-h'>📈 Points match après match</div>"
            f"<svg viewBox='-6 -6 {w + 12} {h + 12}' class='spark' role='img' aria-label='Points par match'>"
            f"<line x1='0' x2='{w}' y1='{avg_y:.1f}' y2='{avg_y:.1f}' class='avg'/><polyline points='{line}' style='stroke:{team_color(tid) if tid else '#ffc75a'}'/>"
            + "".join(f"<circle cx='{i * step:.1f}' cy='{h - p / mx * (h - 12) - 4:.1f}' r='3.2'/>" for i, p in enumerate(pts)) + "</svg>"
            f"<div class='spark-l'>Pointillés : sa moyenne ({f1(a['pts'])}). Record de la saison : <b>{int(best['l'][1])} points</b> "
            f"contre les {esc(team(best['opp'])['name'])} ({esc(short_date(best['d']))}).</div></div>", unsafe_allow_html=True)
    nxt = next_game_of(schedule, tid, today) if tid else None
    if nxt:
        opp = nxt["away"] if nxt["home"] == tid else nxt["home"]
        tip = parse_dt(nxt.get("utc"))
        when = (rel_label(nxt["day"], zone, today) or night_short_title(nxt["day"], zone)) + (f" · {fr_hour(tip.astimezone(ZONES[zone]))}" if tip else "")
        right.markdown(f"<div class='nx'><div class='nx-k'>Son prochain match</div><div class='nx-w'>{esc(when)}</div>"
                       f"<div class='nx-m'>{'vs' if nxt['home'] == tid else '@'} {mini_logo(opp, 36)}<b>{team_link(opp)}</b></div>"
                       f"{link('/?nuit=' + nxt['day'].isoformat(), 'Voir la nuit ›', 'pd-go')}</div>", unsafe_allow_html=True)
    l5 = avg5 = averages(games[-5:])
    trend = (avg5["pts"] - a["pts"]) if a["gp"] >= 8 else 0
    if trend >= 4:
        right.markdown(f"<div class='tbox'><div class='tbox-h'>🔥 En feu</div><p class='pg-note'>{f1(l5['pts'])} points de moyenne sur ses 5 derniers matchs, "
                       f"{f1(trend)} de plus que sur la saison.</p></div>", unsafe_allow_html=True)
    elif trend <= -4:
        right.markdown(f"<div class='tbox'><div class='tbox-h'>🧊 En petite forme</div><p class='pg-note'>{f1(l5['pts'])} points de moyenne sur ses 5 derniers "
                       f"matchs, {f1(-trend)} de moins que sur la saison.</p></div>", unsafe_allow_html=True)
    rows = "".join(
        f"<tr><td class='dt'>{esc(short_date(g['d']))}</td><td class='op'>{'vs' if g['home'] else '@'} {mini_logo(g['opp'], 20)}{esc(team(g['opp'])['abbr'])}</td>"
        f"<td>{int(g['l'][0])}</td><td><b>{int(g['l'][1])}</b></td><td>{int(g['l'][2])}</td><td>{int(g['l'][3])}</td>"
        f"<td class='hide-s'>{int(g['l'][4])}</td><td class='hide-s'>{int(g['l'][5])}</td><td>{g['l'][7]}/{g['l'][8]}</td><td class='hide-s'>{g['l'][9]}/{g['l'][10]}</td>"
        f"<td>{link('/?nuit=' + g['d'].isoformat() + '&open=' + g['gid'], '▶', 'rv', 'Résumé et feuille de match')}</td></tr>"
        for g in reversed(games[-10:]))
    st.markdown("<div class='tbox'><div class='tbox-h'>🏀 Ses 10 derniers matchs</div><div class='tscroll'><table class='stt pl'><thead><tr>"
                "<th>Date</th><th>Adv.</th><th>Min</th><th>Pts</th><th>Reb</th><th>Pas</th><th class='hide-s'>Int</th><th class='hide-s'>Ctr</th>"
                f"<th>Tirs</th><th class='hide-s'>3 pts</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>", unsafe_allow_html=True)


def leaders_html(table, players, favs, title, key, fmt=f1, n=10, min_gp=3):
    rows = sorted(((pid, x) for pid, x in table.items() if x["gp"] >= min_gp and x.get(key) is not None), key=lambda kv: -kv[1][key])[:n]
    body = "".join(
        f"<li class='{'fav' if x['tid'] in favs else ''}'><span class='rk'>{i}</span>{headshot(players.get(pid), 34)}"
        f"<span class='nm'>{player_link(pid, x['name'])}<small>{mini_logo(x['tid'], 16)} {esc(team(x['tid'])['name'])}</small></span>"
        f"<b>{fmt(x[key])}</b></li>" for i, (pid, x) in enumerate(rows, 1))
    return f"<div class='tbox ld'><div class='tbox-h'>{title}</div><ol>{body or '<li>Pas encore assez de matchs.</li>'}</ol></div>"


def players_page(schedule, idx, season, cut, days, today, zone):
    ss = st.session_state
    pays = ss.opts.get("pays", "FR")
    country, flag, ours = COUNTRY[pays]
    sections = ["fiche", "meilleurs", "nous", "infirmerie"]
    labels = {"fiche": "🔎 Fiches", "meilleurs": "🏆 Les meilleurs", "nous": f"{flag} {ours.split(' de ')[0]}", "infirmerie": "🩹 Infirmerie"}
    sec = st.segmented_control("Rubrique", sections, format_func=labels.get, key="psec", label_visibility="collapsed",
                               default=ss.get("psec") or "meilleurs") or "meilleurs"
    db = players_db()
    players = league_players()
    favs = fav_ids()
    last = default_day(days, today)
    if sec in ("meilleurs", "nous", "fiche") and cut <= today and st.toggle(
            f"Inclure la dernière nuit ({night_label(last, zone)}) : montre ses stats", key="pl_rev"):
        cut = today + timedelta(days=1)
    table = season_table(db, cut)
    if not db["log"]["g"]:
        st.info("Le journal des matchs se remplit (toutes les feuilles de match de la saison) : les stats arrivent dans quelques minutes.")
    if sec == "fiche":
        ids = sorted(players, key=lambda p: players[p]["name"])
        cur = ss.get("player") if ss.get("player") in players else None
        pick = st.selectbox("Chercher un joueur", [""] + ids, index=(ids.index(cur) + 1) if cur else 0, key=f"pl_pick_{cur}",
                            format_func=lambda p: "Tape un nom…" if not p else f"{players[p]['name']} · {team(players[p]['team'])['name']}",
                            label_visibility="collapsed")
        if pick and pick != cur:
            ss.player = pick
            st.rerun()
        if cur:
            player_page(cur, schedule, cut, today, zone)
        else:
            page_head("Les joueurs", "Cherche un joueur ci-dessus, ou clique sur un nom partout sur le site.", "Fiches")
            st.markdown(leaders_html(table, players, favs, "🔥 Les plus en forme (5 derniers matchs)", "last5", min_gp=5), unsafe_allow_html=True)
    elif sec == "meilleurs":
        page_head("Les meilleurs", "Moyennes par match en saison régulière (3 matchs joués au minimum).", "Saison " + f"{season - 1}-{str(season)[2:]}")
        cols = st.columns(3)
        for col, (title, key, fmt) in zip(cols * 2, [("Points", "pts", f1), ("Rebonds", "reb", f1), ("Passes", "ast", f1),
                                                      ("Paniers à 3 points", "3pm", f1), ("Interceptions", "stl", f1), ("Contres", "blk", f1)]):
            col.markdown(leaders_html(table, players, favs, title, key, fmt), unsafe_allow_html=True)
    elif sec == "nous":
        ours_ids = [p for p in players if players[p]["country"] == country]
        page_head(ours, f"Les joueurs nés {'en France' if pays == 'FR' else 'au Canada'}, leur saison et leur prochain match.", flag + " Nos joueurs")
        cards = []
        for pid in sorted(ours_ids, key=lambda p: -(table.get(p) or {}).get("pts", -1)):
            p, x = players[pid], table.get(pid)
            nxt = next_game_of(schedule, p["team"], today)
            nx_txt = ""
            if nxt:
                opp = nxt["away"] if nxt["home"] == p["team"] else nxt["home"]
                nx_txt = f"{'vs' if nxt['home'] == p['team'] else '@'} {esc(team(opp)['name'])} · {esc(rel_label(nxt['day'], zone, today) or short_date(nxt['day']))}"
            line = (f"<b>{f1(x['pts'])}</b> pts · <b>{f1(x['reb'])}</b> reb · <b>{f1(x['ast'])}</b> pas <small>({x['gp']} matchs)</small>"
                    if x else "<small>Pas encore joué cette saison</small>")
            inj = f"<span class='inj o'>🩹 {esc(status_fr(p['inj']))}</span>" if p["inj"] else ""
            cards.append(f"<div class='fr-c' style='--c:{team_color(p['team'])}'>{headshot(p, 64)}<div><div class='nm'>{player_link(pid, p['name'])} {inj}</div>"
                         f"<small>{mini_logo(p['team'], 16)} {esc(team(p['team'])['name'])} · {esc(POS_FR.get(p['pos'], p['pos']))}</small>"
                         f"<div class='ln'>{line}</div><small class='nx2'>{'Prochain match : ' + nx_txt if nx_txt else ''}</small></div></div>")
        st.markdown(f"<div class='fr-g'>{''.join(cards) or '<p>Aucun joueur trouvé dans les effectifs.</p>'}</div>", unsafe_allow_html=True)
    else:
        injuries_section(players, table, favs)


def injuries_section(players, table, favs):
    page_head("L'infirmerie de la NBA", "Tous les joueurs blessés ou incertains, équipe par équipe (ESPN).", "Infirmerie")
    inj = league_injuries()
    c1, c2 = st.columns([2, 3])
    only_out = c1.toggle("Seulement les absents", key="inj_out")
    mine = c2.toggle("Mon équipe d'abord", value=True, key="inj_fav")
    stars = sorted((i for i in inj if i["pid"] and (table.get(i["pid"]) or {}).get("pts", 0) >= 16 and "out" in norm(i["status"])),
                   key=lambda i: -table[i["pid"]]["pts"])
    if stars:
        st.markdown("<div class='tbox'><div class='tbox-h'>⭐ Les grosses absences</div><div class='stars'>" + "".join(
            f"<div>{headshot(players.get(i['pid']), 44)}<span>{player_link(i['pid'], i['name'])}<small>{esc(team(i['tid'])['name'])} · "
            f"{f1(table[i['pid']]['pts'])} pts/m</small></span></div>" for i in stars[:8]) + "</div></div>", unsafe_allow_html=True)
    by_team = defaultdict(list)
    for i in inj:
        st_fr = status_fr(i["status"])
        if only_out and INJ_ORDER.get(st_fr, 5) > 1:
            continue
        by_team[i["tid"]].append(dict(i, st_fr=st_fr))
    order = sorted(by_team, key=lambda t: (0 if mine and t in favs else 1, team(t)["name"]))
    blocks = []
    for tid in order:
        rows = "".join(
            f"<li>{headshot(players.get(i['pid']), 30)}<span class='nm'><span>{player_link(i['pid'], i['name'])}"
            f"{' <span class=star>⭐</span>' if (table.get(i['pid']) or {}).get('pts', 0) >= 16 else ''}</span>"
            f"<small>{esc(INJURY_FR.get(norm(i['type']), i['type']))}{' · retour vers le ' + fr_date_iso(i['back']) if i['back'] else ''}</small></span>"
            f"<span class='inj {'o' if INJ_ORDER.get(i['st_fr'], 5) <= 1 else 'q'}'>{esc(i['st_fr'])}</span></li>"
            for i in sorted(by_team[tid], key=lambda i: (INJ_ORDER.get(i["st_fr"], 5), i["name"])))
        blocks.append(f"<div class='tbox ij{' fav' if tid in favs else ''}'><div class='tbox-h'>{mini_logo(tid, 22)} {team_link(tid) if tid else 'Autres'}"
                      f"<span>{len(by_team[tid])}</span></div><ul>{rows}</ul></div>")
    st.markdown(f"<div class='ij-g'>{''.join(blocks) or '<p>Personne à l’infirmerie : rare !</p>'}</div>", unsafe_allow_html=True)


PLAYERS_CSS = """
<style>
img.hs, span.hs {border-radius:50%; object-fit:cover; background:#1a2130; flex:none; display:inline-block;}
.ph {display:flex; align-items:center; gap:22px; padding:18px 24px; border-radius:22px; margin:10px 0 0; border:1px solid rgba(255,255,255,.12);
  background:linear-gradient(rgba(8,10,16,.4), rgba(8,10,16,.6)), repeating-linear-gradient(115deg, rgba(255,255,255,.05) 0 2px, transparent 2px 11px),
  linear-gradient(120deg, var(--c) 0%, var(--c) 62%, var(--c2) 62.5%, var(--c2) 100%);}
.ph img.hs {background:rgba(255,255,255,.1); border:3px solid rgba(255,255,255,.25);}
.ph h1 {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-size:2.5rem; line-height:1; margin:4px 0; padding:0; color:#fff;}
.ph .th-k a.tl {color:#fff !important;} .ph-bio {color:rgba(255,255,255,.9); font-size:.92rem;} .ph-inj {margin-top:8px; color:#fff;}
@media (max-width: 640px) {.ph {padding:14px; gap:12px;} .ph img.hs {width:84px; height:84px;} .ph h1 {font-size:1.8rem;}}
.tstats.ps {grid-template-columns:repeat(8, 1fr);}
@media (max-width: 900px) {.tstats.ps {grid-template-columns:repeat(4, 1fr);}}
svg.spark {width:100%; height:auto; display:block; margin:8px 0 4px;} .spark polyline {fill:none; stroke-width:3; stroke-linejoin:round;}
.spark circle {fill:#e8ecf3;} .spark .avg {stroke:#5d6880; stroke-dasharray:5 5; stroke-width:1.5;}
.spark-l {color:#9aa4b8; font-size:.85rem;}
.tscroll {overflow-x:auto;} table.stt.pl td {padding:6px 7px;} .stt.pl .dt {text-align:left; color:#c3cad6;} .stt.pl .op {text-align:left;}
.ld ol {list-style:none; margin:6px 0 0; padding:0;} .ld li {display:flex; align-items:center; gap:9px; padding:6px 0; border-bottom:1px solid #171d29;}
.ld li:last-child {border-bottom:none;} .ld li.fav {background:rgba(255,199,90,.07);} .ld .rk {width:20px; color:#8a94a8; font-weight:700; text-align:right;}
.ld .nm {display:flex; flex-direction:column; min-width:0; flex:1; line-height:1.2;} .ld .nm small {color:#8a94a8; font-size:.75rem;}
.ld li b {font-family:'Barlow Condensed', sans-serif; font-size:1.3rem;}
.fr-g {display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:10px;}
.fr-c {display:flex; gap:12px; align-items:center; background:#10151f; border:1px solid #1f2736; border-left:5px solid var(--c); border-radius:16px; padding:12px;}
.fr-c .nm {font-weight:700; font-size:1.05rem;} .fr-c small {color:#8a94a8;} .fr-c .ln {margin:4px 0 2px; color:#c3cad6;} .fr-c .ln b {color:#fff;}
.fr-c .nx2 {display:block;}
.ij-g {display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr)); gap:10px;}
.ij .tbox-h {display:flex; align-items:center; gap:8px; text-transform:none; letter-spacing:0; font-size:1rem; color:#e8ecf3;}
.ij .tbox-h span {margin-left:auto; color:#8a94a8; font-size:.8rem;} .ij.fav {border-color:rgba(255,199,90,.45);}
.ij li .nm {display:flex; flex-direction:column; flex:1; min-width:0; line-height:1.25;} .ij li .nm small {color:#8a94a8;}
.stars {display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:8px; margin-top:8px;}
.stars > div {display:flex; gap:10px; align-items:center;} .stars > div > span {display:flex; flex-direction:column; align-items:flex-start; line-height:1.25;} .stars small {color:#8a94a8;}
</style>
"""


# =========================================================================
# LE BRIEF DU MATIN (v024) : ce qu'il faut savoir de la dernière nuit, sans spoil tant qu'on ne révèle pas
# =========================================================================
def brief_page(schedule, idx, season, days, today, zone, show_all, interest):
    """La page d'accueil : la dernière nuit en un coup d'œil. Tout ce qui dévoile un résultat est caché tant qu'on ne clique pas :
    « Tout révéler » en haut, ou rubrique par rubrique, ou match par match (clic sur les « ? »)."""
    ss = st.session_state
    pays = ss.opts.get("pays", "FR")
    favs = fav_ids()
    last = default_day(days, today)
    games = day_games(last)
    done = [g for g in games if g["state"] == "post"]
    key, state_txt = night_state(games, zone)
    tz = ZONES[zone]
    with ThreadPoolExecutor(8) as pool:
        summs = dict(zip([g["id"] for g in games], pool.map(game_summary, games)))
    watch = {g["id"]: watch_score(g, summs.get(g["id"]), idx) for g in done} if interest else {}
    watch = {k: v for k, v in watch.items() if v}
    nba_vids, extra_vids = videos_since(last)
    with ThreadPoolExecutor(8) as pool:
        vids = dict(zip([g["id"] for g in done], pool.map(lambda g: game_videos(g, nba_vids, extra_vids), done)))
    players = league_players()

    # Bandeau : titre, état de la nuit, mon équipe, « Tout révéler »
    me_html = ""
    for tid in favs:
        nxt = next((g for g in schedule if tid in (g["home"], g["away"]) and not g["done"] and g["day"] > last), None)
        if nxt:
            opp = nxt["away"] if nxt["home"] == tid else nxt["home"]
            tip = parse_dt(nxt.get("utc"))
            rel = rel_label(nxt["day"], zone, today)
            when = (rel.lower() if rel else short_date(nxt["day"])) + (f" à {fr_hour(tip.astimezone(tz))}" if tip else "")
            live = next((g for g in day_games(nxt["day"]) if g["id"] == nxt["id"]), None)
            me_html = (f"<div class='bf-me'>{mini_logo(tid, 22)}<span><b>{esc(team(tid)['name'])}</b> · prochain match {esc(when)}, "
                       f"{'contre' if nxt['home'] == tid else 'chez'} les {team_link(opp)}</span>{watch_badge(live, pays) if live else ''}</div>")

    def tile(g):
        a, h = g["away"], g["home"]
        ta, th = team(a["id"]), team(h["id"])
        played = g["state"] != "pre"
        tip = parse_dt(g["utc"])
        status = ("Final" if g["state"] == "post" else ("<span class='live'>● En direct</span>" if g["state"] == "in" else
                  (fr_hour(tip.astimezone(tz)) if tip else "")))
        lv = watch.get(g["id"])
        badge = ""
        if lv:
            icon, label, advice = WATCH_LEVELS[lv[0]]
            badge = f"<span class='lvl L{lv[0]}' title='{esc(advice)}'>{icon} {esc(label)}</span>"
        win = None
        if g["state"] == "post" and a["score"] is not None and h["score"] is not None:
            win = "a" if a["score"] > h["score"] else "h"
        gid = g["id"]

        def row(s_, t, side):
            rec = team_record(idx, s_["id"], g["day"], g["season"])
            score = ""
            if played and s_["score"] is not None:
                cls = "w" if win == side else ("l" if win else "")
                score = (f"<label for='bt{gid}' class='sq' title='Voir le score'><span class='q'>?</span>"
                         f"<span class='sc-r {cls}'>{s_['score']}</span></label>")
            return (f"<div class='bt-row'>{mini_logo(s_['id'], 30)}<span class='nm'>{team_link(s_['id'])}"
                    f"{f' <i>({esc(rec)})</i>' if rec else ''}</span>{score}</div>")
        pre = pre_info(g, summs.get(gid))
        fact = key_fact(g, idx, pre) or ""
        nba, extra = vids.get(gid) or (None, None)
        btns = []
        if nba:
            btns.append(f"<a class='cbtn main' href='{yt_url(nba)}' target='_blank'>▶ Résumé</a>")
        elif g["state"] == "post":
            btns.append(f"<a class='cbtn ghost' href='{yt_search_url(g)}' target='_blank'>🔎 Résumé</a>")
        if extra and pays == "FR":
            btns.append(f"<a class='cbtn fr' href='{yt_url(extra)}' target='_blank'><span class='frf'></span> NBA Extra</a>")
        if not played:
            btns.append(watch_badge(g, pays))
        btns.append(link(f"/?nuit={g['day'].isoformat()}&open={gid}", "Stats ›" if played else "Avant-match ›", "lk"))
        fav = " fav" if {a["id"], h["id"]} & favs else ""
        return (f"<div class='bt{fav}' id='g{gid}' style='--ca:{team_color(a['id'])}; --ch:{team_color(h['id'])}'>"
                f"<input type='checkbox' class='tg tg-t' id='bt{gid}'>"
                f"<div class='bt-top'>{badge or '<span></span>'}<span class='bt-st'>{status}</span></div>"
                f"{row(a, ta, 'a')}{row(h, th, 'h')}"
                f"<div class='bt-kf' title='{esc(fact)}'>{esc(fact) or '&nbsp;'}</div>"
                f"<div class='bt-b'>{''.join(btns)}</div></div>")

    order = sorted(games, key=lambda g: (0 if {g["home"]["id"], g["away"]["id"]} & favs else 1,
                                         -(watch.get(g["id"]) or (0, 0, -99))[2] if watch else 0, g["utc"] or ""))
    tiles = "".join(tile(g) for g in order)

    # Rubriques cachées : grosses perfs, classement, nos joueurs
    perfs, ours = [], []
    country = COUNTRY[pays][0]
    for g in done:
        for tid, prows in ((summs.get(g["id"]) or {}).get("box") or {}).items():
            for r in prows:
                if r.get("dnp"):
                    continue
                item = (game_score(r["stats"]), r, tid, stat_line(r["stats"]))
                perfs.append(item)
                if (players.get(str(r.get("id"))) or {}).get("country") == country:
                    ours.append(item)
    perfs.sort(key=lambda x: -x[0])
    ours.sort(key=lambda x: -x[0])

    def plist(items):
        return "".join(f"<li>{headshot(players.get(str(r.get('id'))), 30)}<span class='nm'>{player_link(str(r.get('id') or ''), r['name'])}"
                       f"<small>{mini_logo(tid, 14)} {esc(team(tid)['name'])}</small></span><span class='sl'>{esc(line)}</span></li>" for _, r, tid, line in items)
    before, after = standings(idx, season, last), standings(idx, season, last + timedelta(days=1))
    moves = []
    for conf in ("Est", "Ouest"):
        rb = {r["tid"]: r["rank"] for r in before.get(conf, [])}
        for r in after.get(conf, []):
            old = rb.get(r["tid"])
            if old and old != r["rank"] and (abs(old - r["rank"]) >= 2 or {old, r["rank"]} & {6, 7, 10, 11}):
                moves.append((abs(old - r["rank"]), conf, r["tid"], old, r["rank"]))
    moves.sort(key=lambda m: -m[0])
    move_html = "".join(f"<li>{mini_logo(t, 22)}<span class='nm'>{team_link(t)}<small>{'Est' if c == 'Est' else 'Ouest'}</small></span>"
                        f"<span class='mv {'up' if new < old else 'dn'}'>{'▲' if new < old else '▼'} {old}e → {new}e</span></li>" for _, c, t, old, new in moves[:8])
    flag, ours_title = COUNTRY[pays][1], COUNTRY[pays][2]

    def section(sid, title, body, empty):
        return (f"<div class='bs'><input type='checkbox' class='tg tg-x' id='bs-{sid}'>"
                f"<div class='bs-h'><span>{title}</span><label for='bs-{sid}' class='pill'><span class='off'>👁 Voir</span><span class='on'>🙈 Cacher</span></label></div>"
                f"<div class='bs-c'><ul>{body or f'<li class=ok>{empty}</li>'}</ul></div><div class='bs-hid'>Caché pour ne rien dévoiler.</div></div>")
    secs = ""
    if done:
        secs = ("<div class='bsecs'>" + section("perf", "💥 Les grosses perfs", plist(perfs[:6]), "Pas de feuille de match pour l’instant.")
                + section("cls", "📊 Ce qui a bougé au classement", move_html, "Rien de notable.")
                + section("nous", f"{flag} Nos {'Français' if pays == 'FR' else 'Canadiens'} cette nuit", plist(ours), "Aucun n’a joué cette nuit.") + "</div>")
    reveal = "" if show_all or not done else (
        "<label for='b-all' class='pill big'><span class='off'>👁 Tout révéler</span><span class='on'>🙈 Tout cacher</span></label>")
    st.markdown(
        f"<div class='bf{' all' if show_all else ''}'><input type='checkbox' class='tg tg-all' id='b-all'>"
        f"<div class='bf-bar'><div><div class='pg-k'>☕ Le brief · {esc(rel_label(last, zone, today) or 'la dernière nuit')}</div>"
        f"<h1>{esc(night_short_title(last, zone))}</h1><p>{len(games)} matchs · {esc(state_txt.lower())} · tout est caché tant que tu ne cliques pas</p></div>{reveal}</div>"
        f"{me_html}<div class='bt-grid'>{tiles or '<p>Pas de match cette nuit.</p>'}</div>{secs}</div>", unsafe_allow_html=True)

    # Infirmerie : les grosses absences (rien n'y dévoile un résultat)
    table = season_table(players_db(), last)
    inj = [i for i in league_injuries() if i["pid"] and (table.get(i["pid"]) or {}).get("pts", 0) >= 15 and INJ_ORDER.get(status_fr(i["status"]), 5) <= 3]
    inj.sort(key=lambda i: -table[i["pid"]]["pts"])
    if inj:
        st.markdown("<div class='sec-h'>🩹 Les grosses absences <span>15 points ou plus de moyenne · "
                    + link("/?vue=joueurs&rub=infirmerie", "toute l'infirmerie ›", "lk") + "</span></div><div class='tbox'><div class='stars'>"
                    + "".join(f"<div>{headshot(players.get(i['pid']), 40)}<span>{player_link(i['pid'], i['name'])}<small>{esc(team(i['tid'])['name'])} · "
                              f"<span class='inj {'o' if INJ_ORDER.get(status_fr(i['status']), 5) <= 1 else 'q'}'>{esc(status_fr(i['status']))}</span></small></span></div>"
                              for i in inj[:8]) + "</div></div>", unsafe_allow_html=True)

    # La nuit prochaine
    nxt_day = next((d for d in days if d > last), None)
    tonight = [g for g in day_games(nxt_day) if g["state"] == "pre"] if nxt_day else []
    if tonight:
        cut = spoil_cut(days, today, ss.seen, show_all)[0]
        best = max(tonight, key=lambda g: quick_hype(idx, g, season, cut))
        tips = [parse_dt(g["utc"]) for g in tonight if parse_dt(g["utc"])]
        first = fr_hour(min(tips).astimezone(tz)) if tips else "?"
        lines = "".join(f"<li class='{'fav' if {g['home']['id'], g['away']['id']} & favs else ''}'><span class='t'>{fr_hour(parse_dt(g['utc']).astimezone(tz)) if parse_dt(g['utc']) else '?'}</span>"
                        f"{mini_logo(g['away']['id'], 22)} {team_link(g['away']['id'])} <span class='at'>@</span> {team_link(g['home']['id'])} {mini_logo(g['home']['id'], 22)}"
                        f"{'<span class=bdg>🔥 L’affiche</span>' if g is best else ''}{watch_badge(g, pays)}</li>" for g in tonight)
        st.markdown(f"<div class='sec-h'>🌙 {esc(rel_label(nxt_day, zone, today) or night_short_title(nxt_day, zone))} "
                    f"<span>{len(tonight)} matchs, premier coup d'envoi à {first} · {link('/?vue=programme', 'tout le programme ›', 'lk')}</span></div>"
                    f"<div class='tbox'><ul class='tn-l'>{lines}</ul></div>", unsafe_allow_html=True)


BRIEF_CSS = """
<style>
.bf {margin-top:6px;} .bf .tg {display:none;}
.bf-bar {display:flex; align-items:flex-end; gap:16px; justify-content:space-between; flex-wrap:wrap; margin:6px 0 10px;}
.bf-bar h1 {font-family:'Barlow Condensed', sans-serif; text-transform:uppercase; font-size:2rem; margin:0; padding:0; line-height:1.05;}
.bf-bar p {color:#8a94a8; margin:.15rem 0 0; font-size:.9rem;}
.pill {display:inline-flex; align-items:center; gap:6px; cursor:pointer; user-select:none; border:1px solid #3a3320; color:#ffd98a; background:rgba(255,199,90,.08);
  border-radius:999px; padding:5px 12px; font-weight:700; font-size:.85rem; white-space:nowrap;}
.pill:hover {background:rgba(255,199,90,.16); border-color:#6b5520;} .pill .on {display:none;}
.pill.big {padding:9px 18px; font-size:.95rem;}
.tg-all:checked ~ .bf-bar .pill .on {display:inline;} .tg-all:checked ~ .bf-bar .pill .off {display:none;}
.bf-me {display:flex; align-items:center; gap:10px; flex-wrap:wrap; background:#10151f; border:1px solid rgba(255,199,90,.35); border-radius:14px;
  padding:9px 14px; margin:0 0 12px; color:#d5dbe6; font-size:.92rem;} .bf-me .wt {margin-left:auto;}
.bf-me > span:not(.wt) {flex:1 1 220px; min-width:0;} .bf-me img.ml {align-self:flex-start; margin-top:2px;}
@media (max-width: 640px) {.bt {gap:4px; padding:8px 10px 8px 12px;} .bt-row {min-height:32px;} .bf-me {font-size:.88rem;}}
/* tuiles des matchs : toutes de la même taille */
.bt-grid {display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:10px; grid-auto-rows:1fr;}
.bt {position:relative; display:flex; flex-direction:column; gap:6px; padding:10px 12px 10px 14px; border-radius:16px; border:1px solid #1f2736; overflow:hidden;
  background:linear-gradient(rgba(12,15,22,.86), rgba(12,15,22,.9)), linear-gradient(105deg, var(--ca) 0%, var(--ca) 49.5%, var(--ch) 50.5%, var(--ch) 100%);}
.bt::before {content:''; position:absolute; left:0; top:0; bottom:0; width:4px; background:linear-gradient(var(--ca), var(--ch));}
.bt.fav {border-color:rgba(255,199,90,.55);}
.bt-top {display:flex; justify-content:space-between; align-items:center; min-height:24px;}
.bt-st {color:#8a94a8; font-size:.78rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em;} .bt-st .live {color:#ff6b6b;}
.bt .lvl {font-size:.78rem; padding:3px 9px;}
.bt-row {display:flex; align-items:center; gap:9px; min-height:36px;}
.bt-row .nm {flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-size:1.02rem;}
.bt-row .nm i {color:#8a94a8; font-style:normal; font-size:.85rem;}
.sq {min-width:46px; height:32px; display:inline-flex; align-items:center; justify-content:center; border-radius:9px; cursor:pointer;
  background:repeating-linear-gradient(135deg, rgba(255,255,255,.07) 0 4px, rgba(255,255,255,.02) 4px 8px); border:1px solid #2a3344;
  font-family:'Barlow Condensed', sans-serif; font-weight:800; font-size:1.35rem; color:#5d6880;}
.sq .sc-r {display:none; color:#fff;} .sq .sc-r.l {color:#7c879b;}
.tg-t:checked ~ .bt-row .sq .q, .tg-all:checked ~ .bt-grid .sq .q, .bf.all .sq .q {display:none;}
.tg-t:checked ~ .bt-row .sq .sc-r, .tg-all:checked ~ .bt-grid .sq .sc-r, .bf.all .sq .sc-r {display:inline;}
.tg-t:checked ~ .bt-row .sq, .tg-all:checked ~ .bt-grid .sq, .bf.all .sq {background:rgba(8,10,16,.55); border-color:transparent;}
.bt-kf {color:#c3cad6; font-size:.82rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-height:1.2em;}
.bt-b {display:flex; align-items:center; gap:6px; margin-top:auto; padding-top:6px; border-top:1px solid rgba(255,255,255,.07); flex-wrap:nowrap; overflow:hidden;}
.bt-b .cbtn {padding:4px 10px; font-size:.8rem; white-space:nowrap;} .bt-b a.lk {margin-left:auto; font-size:.85rem;} .bt-b .wt {font-size:.74rem;}
/* rubriques cachées */
.bsecs {display:grid; grid-template-columns:repeat(3, 1fr); gap:10px; margin-top:12px;}
@media (max-width: 1000px) {.bsecs {grid-template-columns:1fr;}}
.bs {background:#10151f; border:1px solid #1f2736; border-radius:16px; padding:10px 14px;}
.bs-h {display:flex; align-items:center; justify-content:space-between; gap:8px; font-weight:700;}
.bs-c {display:none;} .bs-hid {color:#5d6880; font-size:.85rem; padding:8px 0 2px;}
.tg-x:checked ~ .bs-c, .tg-all:checked ~ .bsecs .bs-c, .bf.all .bs-c {display:block;}
.tg-x:checked ~ .bs-hid, .tg-all:checked ~ .bsecs .bs-hid, .bf.all .bs-hid {display:none;}
.tg-x:checked ~ .bs-h .pill .on {display:inline;} .tg-x:checked ~ .bs-h .pill .off {display:none;}
.tg-all:checked ~ .bsecs .bs-h .pill, .bf.all .bs-h .pill {display:none;}
.bs ul {list-style:none; margin:6px 0 0; padding:0;} .bs li {display:flex; align-items:center; gap:8px; padding:6px 0; border-bottom:1px solid #171d29;}
.bs li:last-child {border-bottom:none;} .bs .nm {display:flex; flex-direction:column; flex:1; min-width:0; line-height:1.2;} .bs .nm small {color:#8a94a8;}
.bs .sl {color:#e8ecf3; font-size:.8rem; text-align:right; max-width:52%;} .bs .ok {color:#8a94a8;}
.mv {font-weight:800; font-size:.8rem; padding:2px 8px; border-radius:7px; white-space:nowrap;} .mv.up {background:rgba(34,197,94,.16); color:#4ade80;}
.mv.dn {background:rgba(239,68,68,.15); color:#f87171;}
.tn-l li.fav {background:rgba(255,199,90,.07);} .tn-l .t {width:52px; font-family:'Barlow Condensed', sans-serif; font-weight:700; font-size:1.15rem;}
.tn-l .at {color:#5d6880;} .tn-l .wt {margin-left:auto;} .tn-l .bdg {margin-left:6px;}
.lvl {font-weight:800; font-size:.85rem; padding:4px 10px; border-radius:999px; background:rgba(8,10,16,.55); color:#ffd98a; white-space:nowrap;}
@media (max-width: 640px) {.bt-grid {grid-template-columns:1fr; grid-auto-rows:auto;} .bf-bar h1 {font-size:1.6rem;}}
</style>
"""


# =========================================================================
# STATISTIQUES DE VISITE (anonymes) ET PAGE ADMIN (lien secret ?admin=<code>)
# =========================================================================
@st.cache_resource(show_spinner=False)
def stats_store():
    """Statistiques : stats/AAAA-MM.json sur GitHub (mêmes réglages [github] que le jeu), sinon sur le disque."""
    store = F.Store(SESSION, str(_secret("github", "token", "")), str(_secret("github", "repo", "")),
                    str(_secret("github", "branch", "data")), CACHE_DIR, folder="stats")
    S.start_flusher(store)
    return store


def start_tracking(cookies):
    """Au premier passage d'une visite : numéro de l'appareil (cookie nba_id), puis clics et durée laissés par la visite
    précédente dans les cookies nba_ev / nba_hb (le navigateur ne peut pas les envoyer avant)."""
    trk = st.session_state.get("trk")
    if trk:
        return trk
    uid = cookies.get("nba_id", "") or ""
    new = not re.fullmatch(r"[a-z0-9]{10}", uid)
    try:
        ua = (st.context.headers or {}).get("User-Agent", "")
        tz = st.context.timezone or ""
    except Exception:
        ua, tz = "", ""
    trk = {"u": S.new_id() if new else uid, "new": new, "me": cookies.get("nba_me") == "1", "z": tz, "dev": S.device(ua), "done": []}
    st.session_state.trk = trk
    stats_store()
    for tok, e in S.parse_client(cookies.get("nba_ev")):
        S.add(dict(e, u=trk["u"], **({"me": 1} if trk["me"] else {})))
        trk["done"].append(tok)
    hb = S.parse_hb(cookies.get("nba_hb"))
    if hb:
        S.add({"t": hb[1], "s": hb[0], "u": trk["u"], "k": "hb", **({"me": 1} if trk["me"] else {})})
    return trk


def track(kind, **fields):
    trk = st.session_state.get("trk")
    if not trk:
        return
    e = {"t": int(time.time()), "u": trk["u"], "k": kind, **{k: v for k, v in fields.items() if v not in (None, "")}}
    if trk.get("me"):
        e["me"] = 1
    S.add(e)


def finish_run(day):
    """Fin de page : cookies à écrire (équipes, réglages, numéro de l'appareil) et petit script qui note les clics."""
    ss = st.session_state
    if ss.pop("fav_changed", False):
        set_cookie("nba_fav", ".".join(ss.favs))
    if ss.pop("hello_cookie", False):
        set_cookie("nba_hello", "1")
    if ss.pop("opt_changed", False):
        set_cookie("nba_opt", ("i1" if ss.opts["indice"] else "i0") + ("s1" if ss.opts["scores"] else "s0") + "c" + ss.opts.get("pays", "FR"))
    pend = {k: v for k, v in (ss.get("_cookies") or {}).items() if k in KEEP}
    if pend:  # même contenu d'un passage à l'autre : le cadre n'est pas recréé, l'écriture est seulement assurée
        run_js("<script>" + "".join(f"parent.document.cookie='{k}={v}; path=/; max-age=31536000; SameSite=Lax';"
                                    f"try {{ parent.localStorage.setItem('{k}', '{v}'); }} catch (e) {{}}" for k, v in sorted(pend.items())) + "</script>")
    trk = ss.get("trk")
    if not trk:
        return
    if trk.get("pending"):  # arrivée comptée seulement quand la page s'est affichée en entier
        S.add(trk.pop("pending"))
    click_tracker(day, trk["done"])


def click_tracker(day, done):
    """Les vidéos, stats et récaps s'ouvrent dans la page, sans passer par le serveur : on note chaque clic dans le cookie
    nba_ev (relu au chargement suivant) et, toutes les 30 s tant que la page est affichée, l'heure dans nba_hb (durée)."""
    run_js(f"""<script>
const P = window.parent, D = P.document;
D.documentElement.lang = 'fr';
try {{  // réglages perdus (cookie effacé) mais gardés dans le navigateur : on les remet, puis on recharge une seule fois
  const lost = {json.dumps(list(KEEP))}.filter(n => !D.cookie.split('; ').some(c => c.startsWith(n + '=')) && P.localStorage.getItem(n));
  lost.forEach(n => {{ D.cookie = n + '=' + P.localStorage.getItem(n) + '; path=/; max-age=31536000; SameSite=Lax'; }});
  if (lost.includes('nba_fav') || lost.includes('nba_opt')) {{
    if (!P.sessionStorage.getItem('bb_restored')) {{ P.sessionStorage.setItem('bb_restored', '1'); P.location.reload(); }}
  }}
}} catch (e) {{}}
const center = () => {{  // bande des nuits (téléphone) : la nuit affichée au milieu
  const act = D.querySelector('.st-key-nav button[data-testid="stBaseButton-primary"]');
  const row = act && act.closest('[data-testid="stHorizontalBlock"]');
  if (!row || row.scrollWidth <= row.clientWidth) return;
  const col = act.closest('[data-testid="stColumn"]');
  row.scrollLeft = col.offsetLeft - row.offsetLeft - (row.clientWidth - col.offsetWidth) / 2;
}};
if (P.__bbCentered !== {json.dumps(day.isoformat())}) {{ P.__bbCentered = {json.dumps(day.isoformat())}; setTimeout(center, 300); setTimeout(center, 1200); }}
P.__bbDay = {json.dumps(day.strftime("%y%m%d"))};
const C = n => (D.cookie.split('; ').find(c => c.startsWith(n + '=')) || '').slice(n.length + 1);
const W = (n, v) => {{ D.cookie = n + '=' + v + '; path=/; max-age=31536000; SameSite=Lax'; }};
const done = {json.dumps(done)};
if (done.length) W('nba_ev', C('nba_ev').split('-').filter(x => x && !done.includes(x)).join('-'));
const now = () => Math.floor(Date.now() / 1000);
const add = (k, g) => {{
  const q = C('nba_ev').split('-').filter(Boolean);
  q.push([now().toString(36), k, g || '', P.__bbDay].join('.'));
  while (q.join('-').length > 3000) q.shift();
  W('nba_ev', q.join('-'));
}};
const gid = el => {{ const c = el.closest('.gc'); return c ? c.id.slice(1) : ''; }};
if (P.__bbClick) D.removeEventListener('click', P.__bbClick, true);
if (P.__bbChange) D.removeEventListener('change', P.__bbChange, true);
P.__bbClick = e => {{
  const g = e.target.closest && e.target.closest('a[href^="#go?"]');
  if (g) {{  // lien interne : on passe par le champ caché (la page est dans un cadre sur Streamlit Cloud)
    e.preventDefault();
    const inp = D.querySelector('.st-key-go_to input');
    if (!inp) return;
    const setter = Object.getOwnPropertyDescriptor(P.HTMLInputElement.prototype, 'value').set;
    inp.focus();
    setter.call(inp, g.getAttribute('href').slice(4) + '&_=' + Date.now());
    inp.dispatchEvent(new P.Event('input', {{bubbles: true}}));
    inp.dispatchEvent(new P.KeyboardEvent('keydown', {{key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true}}));
    inp.blur();
    P.scrollTo && D.querySelector('[data-testid="stMain"]')?.scrollTo({{top: 0}});
    return;
  }}
  const a = e.target.closest && e.target.closest('a.cbtn');
  if (!a) return;
  if (a.closest('.nrec')) add(a.classList.contains('fr') ? 'X' : 'R', '');
  else add(a.classList.contains('fr') ? 'x' : a.classList.contains('ghost') ? 'q' : 'v', gid(a));
}};
P.__bbChange = e => {{
  const i = e.target;
  if (!i.checked || !i.classList) return;
  if (i.classList.contains('tg-o')) add('s', i.id.slice(1));
  else if (i.classList.contains('tg-s')) add('r', i.id.slice(1));
  else if (i.classList.contains('tg-n')) add('n', '');
  else if (i.classList.contains('tg-w')) add('w', '');
  else if (i.classList.contains('tgp')) add('p', gid(i));
}};
D.addEventListener('click', P.__bbClick, true);
D.addEventListener('change', P.__bbChange, true);
const beat = () => {{
  if (D.hidden) return;
  const [s, l] = C('nba_hb').split('.').map(x => parseInt(x, 36));
  const t = now();
  W('nba_hb', ((s && l && t - l < 1800) ? s : t).toString(36) + '.' + t.toString(36));
}};
clearInterval(P.__bbBeat);
beat();
P.__bbBeat = setInterval(beat, 30000);
</script>""")


def admin_page(zone):
    """Statistiques de visite : qui vient, quand, combien de temps, et ce qui est ouvert, nuit par nuit."""
    import pandas as pd
    store = stats_store()
    S.flush(store)
    tz = ZONES[zone]
    st.markdown("<div class='bb-brand'>Bada Bing <span>NBA</span> · admin</div>", unsafe_allow_html=True)
    c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
    period = c1.segmented_control("Période", [1, 7, 30, 90], default=7, key="adm_p",
                                  format_func=lambda n: "Aujourd'hui" if n == 1 else f"{n} jours") or 7
    mine = c2.toggle("Compter mes appareils", value=False,
                     help="Un appareil qui ouvre cette page est reconnu comme le tien. Tu peux en marquer d'autres plus bas.")
    now = time.time()
    since = now - period * 86400
    months = sorted({S.month_of(since + i * 86400) for i in range(period + 1)} | {S.month_of(now)})
    raw = S.dedupe([e for m in months for e in (store.load(f"{m}.json", []) or []) if e.get("t", 0) >= since])
    names = store.load("names.json", {}) or {}
    me_trk = st.session_state.get("trk") or {}
    if me_trk.get("u") and me_trk["u"] not in names.get("_moi", []):  # l'appareil qui ouvre cette page est à toi
        names = store.update("names.json", {}, lambda d: d.setdefault("_moi", []).append(me_trk["u"]),
                             "Statistiques : un appareil de l'admin") or names
    moi = set(names.get("_moi", []))
    errs = [e for e in raw if e["k"] == "err"]
    # Un même nom donné à plusieurs numéros (téléphone + PC, navigation privée…) = une seule personne
    evs = [dict(e, u=names.get(e["u"]) or e["u"]) if e.get("u") else e
           for e in raw if e["k"] != "err" and (mine or not (e.get("me") or e.get("u") in moi))]
    info = {}
    for e in evs:
        if e["k"] == "open":
            i = info.setdefault(e["u"], {"first": e["t"], "z": "", "dev": "", "new": False})
            i.update(z=e.get("z", i["z"]), dev=e.get("dev", i["dev"]))
            i["new"] = i["new"] or bool(e.get("n"))

    def who(u):
        return u if u not in ids else f"{(info.get(u) or {}).get('dev', 'Appareil')} n°{u[:4]}"
    ids = {e["u"] for e in raw if e.get("u")}

    def hm(t):
        return datetime.fromtimestamp(t, tz).strftime("%d/%m %H:%M")

    vis = S.visits(evs)
    acts = S.night_activity(evs)
    clicks = [e for e in evs if e["k"] in S.CLIENT_KINDS]
    m = st.columns(5)
    m[0].metric("Visiteurs", len({v["u"] for v in vis}), help="Appareils différents (un téléphone et un PC = 2)")
    m[1].metric("Dont nouveaux", sum(1 for i in info.values() if i["new"]))
    m[2].metric("Visites", len(vis), help="30 minutes sans rien = nouvelle visite")
    m[3].metric("Durée moyenne", S.fmt_dur(sum(v["end"] - v["start"] for v in vis) / len(vis)) if vis else "–",
                help="Temps où la page est restée affichée. La visite en cours n'est comptée qu'au chargement suivant.")
    m[4].metric("Vidéos lancées", sum(1 for e in clicks if e["k"] in "vxqRX"))
    if not raw:
        st.info("Pas encore de visite enregistrée sur cette période. Les visites arrivent ici quelques minutes après "
                "(envoi toutes les 5 minutes) ; les clics d'une visite, à son chargement suivant.")

    # Quand ?
    if vis:
        g1, g2 = st.columns(2)
        hours = [0] * 24
        for v in vis:
            hours[datetime.fromtimestamp(v["start"], tz).hour] += 1
        g1.markdown(f"**Heure d'arrivée** (heure de {zone})")
        g1.bar_chart(pd.DataFrame({"Visites": hours}, index=[f"{h:02d}h" for h in range(24)]), height=220)
        per_day = defaultdict(set)
        for v in vis:
            per_day[datetime.fromtimestamp(v["start"], tz).strftime("%d/%m")].add(v["u"])
        g2.markdown("**Visiteurs par jour**")
        g2.bar_chart(pd.DataFrame({"Visiteurs": [len(x) for x in per_day.values()]}, index=list(per_day)), height=220)

    # Nuit par nuit
    st.markdown("#### Nuit par nuit")
    st.caption("Vidéos et stats : nombre de matchs différents ouverts. Une nuit = jour du match aux États-Unis.")
    nights = defaultdict(lambda: {"u": set(), "v": 0, "x": 0, "s": 0, "R": 0, "X": 0, "n": 0})
    for (u, d), a in acts.items():
        n = nights[d]
        n["u"].add(u)
        for k in ("v", "x", "s"):
            n[k] += len(a[k])
        for k in ("R", "X", "n"):
            n[k] += a[k]
    if nights:
        st.dataframe(pd.DataFrame([{
            "Nuit": night_label(date.fromisoformat(d), zone), "Visiteurs": len(n["u"]), "Résumés vidéo": n["v"], "Stats": n["s"],
            "Résumé de la nuit": n["R"], "NBA Extra (match)": n["x"], "NBA Extra (émission)": n["X"], "Récap révélé": n["n"]}
            for d, n in sorted(nights.items(), reverse=True)]), hide_index=True, width="stretch")

        st.markdown("#### Qui a regardé quoi")
        yes = lambda b: "✓" if b else ""
        st.dataframe(pd.DataFrame([{
            "Nuit": night_label(date.fromisoformat(d), zone), "Visiteur": who(u),
            "Résumés vidéo": len(a["v"]) or "", "Stats": len(a["s"]) or "", "Scores révélés": len(a["r"]) or "",
            "Résumé de la nuit": yes(a["R"]), "NBA Extra": (f"{len(a['x'])} match(s)" if a["x"] else "") + (" + émission" if a["X"] else ""),
            "Récap révélé": yes(a["n"]), "Cartes de tirs": a["p"] or "", "Dernier passage": hm(a["last"])}
            for (u, d), a in sorted(acts.items(), key=lambda kv: (kv[0][1], kv[1]["last"]), reverse=True)]),
            hide_index=True, width="stretch")

    # Visiteurs
    if vis:
        st.markdown("#### Les visiteurs")
        per_u = defaultdict(list)
        for v in vis:
            per_u[v["u"]].append(v)
        rows = []
        for u, vs in sorted(per_u.items(), key=lambda kv: -kv[1][-1]["end"]):
            i = info.get(u, {})
            rows.append({"Visiteur": who(u), "Appareil": i.get("dev", ""), "Fuseau": i.get("z", ""),
                         "Visites": len(vs), "Temps total": S.fmt_dur(sum(v["end"] - v["start"] for v in vs)),
                         "Vidéos": sum(1 for e in clicks if e["u"] == u and e["k"] in "vxqRX"),
                         "Première": hm(vs[0]["start"]), "Dernière": hm(vs[-1]["end"])})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        with st.expander("✏️ Nommer, regrouper ou retirer des visiteurs"):
            st.caption("Un même nom pour plusieurs lignes = une seule personne (son téléphone et son PC, par exemple). "
                       "« Ce sont mes appareils » les retire des chiffres.")
            first = {p: min(v["start"] for v in vs) for p, vs in per_u.items()}
            sel = st.multiselect("Visiteurs", list(per_u), key="adm_u", placeholder="Choisir une ou plusieurs lignes",
                                 format_func=lambda p: f"{who(p)} · {info.get(p, {}).get('z', '')} · {hm(first[p])}")
            nm = st.text_input("Nom", key="adm_nm", placeholder="Ex. : Pote Montréal")
            is_me = st.checkbox("Ce sont mes appareils (ne pas les compter)", key="adm_me")
            if st.button("Enregistrer", key="adm_save", disabled=not sel):
                real = {u for u in ids if u in sel or names.get(u) in sel}   # numéros derrière les lignes choisies

                def change(d):
                    for u in real:
                        if nm.strip():
                            d[u] = nm.strip()[:30]
                    if is_me:
                        d["_moi"] = sorted(set(d.get("_moi", [])) | real)
                store.update("names.json", {}, change, "Statistiques : visiteurs nommés")
                st.rerun()

    # Journal
    with st.expander("📜 Journal des 150 derniers événements"):
        rows = []
        for e in sorted([e for e in evs if e["k"] != "hb"], key=lambda e: -e["t"])[:150]:
            label = S.KINDS.get(e["k"], e["k"])
            if e.get("g") and e.get("d"):
                g = next((g for g in day_games(date.fromisoformat(e["d"])) if g["id"] == e["g"]), None)
                if g:
                    label += f" · {team(g['away']['id'])['name']} @ {team(g['home']['id'])['name']}"
            rows.append({"Heure": hm(e["t"]), "Visiteur": who(e["u"]), "Quoi": label,
                         "Nuit": night_label(date.fromisoformat(e["d"]), zone) if e.get("d") else "", "Détail": e.get("x", "")})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    # Ce qui ne marche pas
    st.markdown("#### Erreurs")
    if errs:
        st.dataframe(pd.DataFrame([{"Heure": hm(e["t"]), "Erreur": e["x"]} for e in sorted(errs, key=lambda e: -e["t"])[:60]]),
                     hide_index=True, width="stretch")
    else:
        st.caption("Aucune erreur sur la période.")
    w = video_watcher()
    if not _secret("youtube", "api_key", ""):
        yt = "⚠️ Pas de clé YouTube : seulement les 15 dernières vidéos de chaque chaîne (+ la veille)."
    elif API_STATUS["ok"] is False:
        yt = f"⚠️ {API_STATUS['msg']}"
    else:
        yt = "✅ Clé YouTube active"
    nb = sum(len(v) for v in w["seen"].values())
    st.caption(f"{yt} · veille : {nb} vidéos gardées"
               + (f", dernier passage à {fr_hour(datetime.fromtimestamp(w['last'], tz))}" if w["last"] else ""))
    st.caption(("✅ Statistiques enregistrées sur GitHub (branche « " + store.branch + " », dossier stats/)") if store.remote
               else "⚠️ Pas de jeton GitHub ([github] token / repo) : statistiques gardées sur le disque, perdues au redémarrage du site.")
    st.caption(f"Version {APP_VERSION}")


def main():
    st.set_page_config(page_title="Bada Bing NBA", page_icon="🏀", layout="wide")
    st.markdown(CSS + PAGES_CSS + PLAYERS_CSS + BRIEF_CSS, unsafe_allow_html=True)
    go_cmd = st.session_state.get("go_to")
    st.session_state.go_to = ""
    with st.container(key="gobox"):  # champ caché des liens internes (voir `link`)
        st.text_input("Aller à", key="go_to", label_visibility="collapsed")
    try:
        cookies = st.context.cookies
    except Exception:
        cookies = {}
    if "favs" not in st.session_state:  # une seule équipe (les anciens cookies à plusieurs équipes gardent la 1re)
        st.session_state.favs = [x for x in (cookies.get("nba_fav", "") or "").split(".") if x][:1]
    if "seen" not in st.session_state:
        st.session_state.seen = read_seen(cookies)
    if "opts" not in st.session_state:  # réglages gardés dans un cookie (nba_opt) ; les anciens liens ?scores=1 marchent encore
        opt = cookies.get("nba_opt", "") or ""
        try:
            tzname = st.context.timezone or ""
        except Exception:
            tzname = ""
        st.session_state.opts = {"indice": "i0" not in opt and st.query_params.get("indice") != "0",
                                 "scores": "s1" in opt or st.query_params.get("scores") == "1",
                                 "pays": "CA" if "cCA" in opt else ("FR" if "cFR" in opt else ("CA" if tzname.startswith("America/") else "FR"))}
        st.query_params.pop("indice", None)
        st.query_params.pop("scores", None)
    zone = user_zone()
    trk = start_tracking(cookies)
    if trk["new"]:  # numéro de l'appareil écrit tout de suite (si la page est interrompue, le prochain chargement le garde)
        set_cookie("nba_id", trk["u"])
    today = datetime.now(NY).date()
    season = season_of(today)
    show_all = st.session_state.opts["scores"]
    interest = st.session_state.opts["indice"]

    # Page admin : seulement avec le lien secret ?admin=<code> ([admin] code dans les secrets), aucun bouton pour y aller
    code = str(_secret("admin", "code", ""))
    if code and hmac.compare_digest(str(st.query_params.get("admin", "")), code):
        trk["me"] = True
        admin_page(zone)
        set_cookie("nba_me", "1")
        finish_run(today)
        return

    with st.spinner("Chargement du calendrier…"):
        schedule = season_games(season, bucket(3600))
        idx = team_index(season, bucket(3600))
    st.session_state._schedule = schedule
    days = sorted({g["day"] for g in schedule})
    game_days = set(days)
    opening = season_opening(schedule)
    if go_cmd:
        apply_go(go_cmd)
    if "day" not in st.session_state:
        try:  # la nuit choisie est gardée dans l'adresse (?nuit=AAAA-MM-JJ) : rechargement et liens partagés tombent dessus
            st.session_state.day = date.fromisoformat(st.query_params.get("nuit", ""))
        except ValueError:
            st.session_state.day = default_day(days, today)
    if "view" not in st.session_state:
        st.session_state.view = (st.query_params.get("vue") if st.query_params.get("vue") in VIEWS
                                 else ("nuit" if st.query_params.get("nuit") else "brief"))
    if "team" not in st.session_state:
        st.session_state.team = team_by_abbr(st.query_params.get("eq", "")) or team_by_abbr((st.session_state.favs or [""])[0])
    day, view = st.session_state.day, st.session_state.view
    if view in ("nuit", "semaine"):  # l'adresse garde la nuit choisie ; sans rien, c'est le brief (page d'accueil)
        st.query_params["nuit"] = day.isoformat()
    else:
        st.query_params.pop("nuit", None)
    if view not in ("nuit", "brief"):
        st.query_params["vue"] = view
    else:
        st.query_params.pop("vue", None)
    if view == "equipe" and st.session_state.team:
        st.query_params["eq"] = team(st.session_state.team)["abbr"]
    else:
        st.query_params.pop("eq", None)
    if "player" not in st.session_state:  # fiche d'un joueur gardée dans l'adresse (?vue=joueurs&joueur=…)
        st.session_state.player = st.query_params.get("joueur") or None
        if st.session_state.player:
            st.session_state.psec = "fiche"
        elif st.query_params.get("rub") in ("fiche", "meilleurs", "nous", "infirmerie"):
            st.session_state.psec = st.query_params["rub"]
    if view == "joueurs" and st.session_state.player and st.session_state.get("psec") == "fiche":
        st.query_params["joueur"] = st.session_state.player
    else:
        st.query_params.pop("joueur", None)
    st.query_params.pop("rub", None)
    if trk.get("last") != (view, day):  # arrivée (notée en fin de page), puis chaque changement de nuit ou de vue
        if trk.get("last"):
            track("nav", d=day.isoformat(), x=view)
        else:
            trk["pending"] = {"t": int(time.time()), "u": trk["u"], "k": "open", "d": day.isoformat(), "x": view, "z": trk["z"],
                              "dev": trk["dev"], **({"n": 1} if trk["new"] else {}), **({"me": 1} if trk["me"] else {})}
        trk["last"] = (view, day)

    def go(d, v="nuit"):
        st.session_state.day, st.session_state.view = d, v
        st.rerun()

    # En-tête : marque + réglages, puis les onglets (icônes + mots), toujours au même endroit
    monday, num = week_of(day, opening)
    week_days = [monday + timedelta(days=i) for i in range(7)]
    with st.container(key="hdr"):
        c1, c3 = st.columns([1, 0.001], vertical_alignment="center")
        c1.markdown("<div class='bb-brand'>Bada Bing <span>NBA</span></div>", unsafe_allow_html=True)
        with c3.popover("Réglages", icon=":material/settings:", help="Réglages"):
            settings_panel(interest, show_all)
    with st.container(key="tabs"):
        cols = st.columns(len(TABS))
        for col, (v, label, icon) in zip(cols, TABS):
            if v == "equipe" and st.session_state.favs and team_by_abbr(st.session_state.favs[0]):
                label = team(team_by_abbr(st.session_state.favs[0]))["name"]
            if col.button(label, key=f"tab_{v}", icon=icon, type="primary" if view == v else "secondary", width="stretch"):
                if v == "nuit" and view == "nuit":
                    go(default_day(days, today))
                go(day, v)
    video_watcher()  # la veille des vidéos tourne en fond (son état est sur la page admin)
    welcome(cookies)

    if view == "fantasy":  # le jeu (prototype) : plus de bouton, seulement l'adresse ?vue=fantasy
        fantasy_page(schedule, idx, opening, today, zone, show_all)
        finish_run(day)
        return
    seen = st.session_state.seen
    cut, _last = spoil_cut(days, today, seen, show_all)
    if view == "programme":
        programme_page(today, zone, idx, season, cut)
        page_footer()
        finish_run(day)
        return
    if view == "classement":
        standings_page(idx, season, cut, days, today, zone)
        page_footer()
        finish_run(day)
        return
    if view == "equipe":
        team_page(schedule, idx, season, cut, days, today, zone, show_all)
        page_footer()
        finish_run(day)
        return
    if view == "joueurs":
        players_page(schedule, idx, season, cut, days, today, zone)
        page_footer()
        finish_run(day)
        return
    if view == "brief":
        brief_page(schedule, idx, season, days, today, zone, show_all, interest)
        page_footer()
        finish_run(day)
        return

    games_by_day = {d: day_games(d) for d in week_days}
    if view == "nuit" and night_state(games_by_day.get(day) or [], zone)[0] in ("done", "live") and day not in seen:
        seen.add(day)
        st.session_state.seen_changed = True
    styles = []
    with st.container(key="navw" if view == "semaine" else "nav"):
        if view == "semaine":   # ‹  Semaine N · du … au …  ›
            cols = st.columns([1, 8, 1])
            label = f"Semaine {num}" if num else ("Play-offs" if day.month in (4, 5, 6) else "Hors saison")
            cols[1].markdown(f"<div class='wk-t'><b>{label}</b><span>du {short_date(week_days[0])} au {short_date(week_days[-1])}</span></div>",
                             unsafe_allow_html=True)
            arrows = (cols[0], cols[2])
        else:                   # ‹  7 nuits (jour en petit, dates en grand)  ›  📅
            cols = st.columns(11)
            arrows = (cols[0], cols[8])
            if cols[10].button("", icon=":material/insights:", key="wk_view", help="Le bilan de la semaine", width="stretch"):
                go(day, "semaine")
            for col, d in zip(cols[1:8], week_days):
                gs = games_by_day.get(d) or []
                key, txt = night_state(gs, zone)
                top, big = chip_text(d, zone, today)
                dot = "#ffc75a" if key == "done" and d not in seen else ("#ff5a5a" if key == "live" else "")
                if key == "done" and d not in seen:
                    txt += " · pas encore vue"
                styles.append(f".st-key-n_{d} button::before {{content:'{top}';}}"
                              + (f".st-key-n_{d} button::after {{background:{dot};}}" if dot else ""))
                if col.button(big, key=f"n_{d}", type="primary" if d == day else "secondary",
                              disabled=key == "none" and d not in game_days, width="stretch",
                              help=f"{night_title(d, zone)} · {txt}" + (f" · {len(gs)} matchs" if gs else "")):
                    go(d)
            with cols[9].popover("", icon=":material/calendar_month:", help="Aller à une date"):
                if st.button("Revenir à la dernière nuit", icon=":material/today:", key="last_night", width="stretch"):
                    go(default_day(days, today))
                other = st.date_input("Choisir une date (jour du match aux États-Unis)", value=day, format="DD/MM/YYYY", key=f"cal_{day}")
                if other != day:
                    go(other)
        if arrows[0].button("", icon=":material/chevron_left:", key="wk_prev", help="Semaine précédente", width="stretch"):
            prev = [d for d in days if monday - timedelta(days=7) <= d < monday]
            go(prev[-1] if prev else monday - timedelta(days=1), view)
        if arrows[1].button("", icon=":material/chevron_right:", key="wk_next", help="Semaine suivante", width="stretch"):
            nxt = [d for d in days if monday + timedelta(days=7) <= d < monday + timedelta(days=14)]
            target = nxt[0] if nxt else monday + timedelta(days=7)
            if target <= today <= target + timedelta(days=7):
                target = default_day(days, today)
            go(target, view)
    if styles:
        st.markdown("<style>" + "".join(styles) + "</style>", unsafe_allow_html=True)

    nba_vids, extra_vids = videos_since(min(day, today - timedelta(days=1)))
    ai_on = bool(_secret("anthropic", "api_key", ""))
    ctx = {"zone": zone, "idx": idx, "nba_vids": nba_vids, "extra_vids": extra_vids, "show_all": show_all,
           "favs": set(st.session_state.favs), "ranks": {}, "ai": ai_on, "durs": {}, "open": st.session_state.pop("open_game", None),
           "pays": st.session_state.opts.get("pays", "FR")}

    if view == "semaine":
        played = [g for d in week_days for g in games_by_day.get(d, []) if g["state"] != "pre"]
        with st.spinner("Bilan de la semaine…"), ThreadPoolExecutor(8) as pool:
            summs = dict(zip([g["id"] for g in played], pool.map(game_summary, played)))
        watch = {g["id"]: watch_score(g, summs.get(g["id"]), idx) for g in played} if interest else {}
        watch = {k: v for k, v in watch.items() if v}
        ctx.update(summ=summs, watch=watch)
        top = sorted(played, key=lambda g: -(watch.get(g["id"]) or (0, 0, -99))[2])[:12]
        wn, wx = videos_since(week_days[0])
        with ThreadPoolExecutor(8) as pool:  # le résumé vidéo des matchs conseillés
            ctx["wv"] = dict(zip([g["id"] for g in top], pool.map(lambda g: game_videos(g, wn, wx)[0] if g["state"] == "post" else None, top)))
        st.markdown(week_html(week_days, games_by_day, summs, watch, ctx), unsafe_allow_html=True)
        page_footer()
        finish_run(day)
        auto_refresh(played, show_all)
        return

    games = games_by_day.get(day) if day in games_by_day else day_games(day)
    with ThreadPoolExecutor(8) as pool:  # fiches ESPN en parallèle (gardées en cache ensuite)
        summs = dict(zip([g["id"] for g in games], pool.map(game_summary, games)))
    watch = {g["id"]: watch_score(g, summs.get(g["id"]), idx) for g in games} if interest else {}
    watch = {k: v for k, v in watch.items() if v}
    if games:
        f0 = team_form(idx, games[0]["home"]["id"], day, games[0]["season"])
        if f0["n"] >= 8:
            ctx["ranks"] = conf_ranks(idx, day, games[0]["season"])
    ctx.update(summ=summs, watch=watch)

    # Affiche de la nuit (matchs à venir) et durées des vidéos trouvées
    upcoming = [g for g in games if g["state"] == "pre"]
    if len(upcoming) >= 3:
        ctx["affiche"] = max(upcoming, key=lambda g: hype(g, idx, pre_info(g, summs.get(g["id"]))))["id"]
    with ThreadPoolExecutor(8) as pool:  # vidéos : listes des chaînes, puis recherche YouTube pour ce qui manque
        vids = pool.map(lambda g: game_videos(g, nba_vids, extra_vids) if g["state"] == "post" else (None, None), games)
        ctx["vids"] = dict(zip([g["id"] for g in games], vids))
    ctx["recap"], ctx["show"] = night_videos(day, nba_vids, extra_vids)
    # Vidéos bloquées dans le pays (résumés NBA en France) : on les remplace par un autre résumé qui passe
    country = "FR" if zone == "Paris" else "CA"
    found = [v for pair in ctx["vids"].values() for v in pair if v] + [v for v in (ctx["recap"], ctx["show"]) if v]
    info = video_info(tuple(sorted({v["id"] for v in found})))
    if info:
        need = [g for g in games if g["state"] == "post" and not playable(ctx["vids"][g["id"]][0], info, country)]
        with ThreadPoolExecutor(8) as pool:
            cands = dict(zip([g["id"] for g in need], pool.map(lambda g: alt_video(g, {v["id"] for v in ctx["vids"][g["id"]] if v}), need)))
        more = video_info(tuple(sorted({v["id"] for c in cands.values() for v in c}))) if cands else {}
        info = {**info, **more}
        for g in need:
            alt = next((v for v in cands.get(g["id"], []) if v["id"] in info and playable(v, info, country)), None)
            nba, extra = ctx["vids"][g["id"]]
            ctx["vids"][g["id"]] = (alt, extra if playable(extra, info, country) else None)
        for k in ("recap", "show"):
            if ctx[k] and not playable(ctx[k], info, country):
                ctx[k] = None
    ctx["durs"] = {k: v["mins"] for k, v in info.items() if v["mins"]} or video_durations(tuple(sorted({v["id"] for v in found})))
    ctx["yt_key"] = bool(_secret("youtube", "api_key", ""))

    st.markdown(night_html(day, games, ctx, today), unsafe_allow_html=True)
    if not games:
        st.info("Pas de match NBA ce jour-là.")

    # Ordre : mes équipes, puis (nuit terminée) les matchs à voir d'abord, sinon l'horaire
    def order(g):
        fav = team(g["home"]["id"])["abbr"] in ctx["favs"] or team(g["away"]["id"])["abbr"] in ctx["favs"]
        sc = watch[g["id"]][2] if g["id"] in watch else -99
        return (0 if fav else 1, -sc if watch else 0, g["utc"] or "")
    if games:
        ordered = sorted(games, key=order)
        best = max((g for g in games if watch.get(g["id"]) and watch[g["id"]][0] >= 2), key=lambda g: watch[g["id"]][2], default=None)
        if not best and ctx.get("affiche"):
            best = next((g for g in games if g["id"] == ctx["affiche"]), None)
        hero = game_card(best, ctx, hero=True) if best else ""
        rows = "".join(game_card(g, ctx) for g in ordered if not best or g["id"] != best["id"])
        st.markdown(hero + (f"<div class='rows'>{rows}</div>" if rows else ""), unsafe_allow_html=True)

    if st.session_state.pop("seen_changed", False):
        write_seen(seen)
    page_footer()
    finish_run(day)
    auto_refresh(games, show_all)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # plantage : noté pour la page admin, puis affiché comme d'habitude
        where = traceback.extract_tb(e.__traceback__)[-1]
        S.add_error(f"Plantage {type(e).__name__} : {str(e)[:150]} (ligne {where.lineno}, {where.name})")
        raise
