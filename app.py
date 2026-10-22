"""Bada Bing NBA : les matchs NBA sans spoil.

Liste des matchs par nuit, preview écrite avant le match, résumés vidéo (NBA, NBA Extra de beIN SPORTS),
journal NBA Extra du jour, et, seulement quand on le demande, le score, l'analyse et la feuille de match.
Données : API publique d'ESPN (sans clé) et YouTube (flux public, ou API YouTube si une clé est fournie).
"""
import html
import json
import logging
import os
import re
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

APP_VERSION = "2026-10-v002"
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
    d = get_json(f"{ESPN}/scoreboard", {"dates": day_iso.replace("-", "")}) or {}
    games = [_parse_event(e) for e in d.get("events") or []]
    return sorted(games, key=lambda g: (g["utc"] or "", g["id"]))


def day_games(day):
    """Matchs d'un jour : rafraîchis chaque minute autour d'aujourd'hui, une fois par jour pour les jours anciens."""
    today = datetime.now(NY).date()
    recent = abs((day - today).days) <= 1
    return scoreboard(day.isoformat(), bucket(60) if recent else bucket(86400))


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
                "name": (a.get("athlete") or {}).get("displayName", ""), "short": (a.get("athlete") or {}).get("shortName", ""),
                "starter": bool(a.get("starter")), "dnp": bool(a.get("didNotPlay")), "reason": a.get("reason") or "",
                "stats": dict(zip(labels, a.get("stats") or [])),
            })
        out["box"][(t.get("team") or {}).get("id")] = rows
    out["team_stats"] = {}
    for t in (d.get("boxscore") or {}).get("teams") or []:
        out["team_stats"][(t.get("team") or {}).get("id")] = {s.get("label") or s.get("name"): s.get("displayValue") for s in t.get("statistics") or []}
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
            break
        if r.status_code != 200:
            log.warning("API YouTube : HTTP %s", r.status_code)
            break
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
    """Vidéos de la chaîne publiées depuis `oldest_iso` : flux public (15 dernières) + API YouTube si une clé est donnée."""
    videos = {}
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
        if not pub or not tip or pub < tip or pub > tip + timedelta(days=2):
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
        if not pub or not tip or pub < tip or pub > tip + timedelta(days=3):
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
            txt = f"{wh}-{len(h2h) - wh} pour {th['name']} sur les {len(h2h)} derniers face-à-face"
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
    def made_att(k):
        try:
            m, a = str(stats.get(k, "0-0")).split("-")
            return int(m), int(a)
        except ValueError:
            return 0, 0
    fgm, fga = made_att("FG")
    ftm, fta = made_att("FT")
    n = lambda k: _num(stats, k)
    return (n("PTS") + 0.4 * fgm - 0.7 * fga - 0.4 * (fta - ftm) + 0.7 * n("OREB") + 0.3 * n("DREB")
            + n("STL") + 0.7 * n("AST") + 0.7 * n("BLK") - 0.4 * n("PF") - n("TO"))


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
WATCH_LEVELS = [("💤", "Sans suspense"), ("🔥", "Correct"), ("🔥🔥", "Bon match"), ("🔥🔥🔥", "À ne pas rater")]


def watch_score(g, summ):
    """Intérêt d'un match terminé, sans dire qui a gagné : (niveau 0-3, mots-clés). None si on ne sait pas."""
    if not summ or g["state"] != "post" or not g["completed"] or g["home"]["score"] is None:
        return None
    h, a = g["home"]["score"], g["away"]["score"]
    margin = abs(h - a)
    pts, max_h, max_a, changes = flow(summ)
    if len(pts) < 20:
        return None
    ot = max(len(g["home"]["lines"]), len(g["away"]["lines"])) > 4
    comeback = max_a if h > a else max_h
    tight_end = any(abs(d) <= 4 for m, d in pts if m >= 46)
    top_pts, triple = 0, False
    for rows in (summ.get("box") or {}).values():
        for r in rows:
            if r["dnp"]:
                continue
            top_pts = max(top_pts, _num(r["stats"], "PTS"))
            triple = triple or sum(1 for k in ("PTS", "REB", "AST", "STL", "BLK") if _num(r["stats"], k) >= 10) >= 3
    s = (3 if ot else 0) + (3 if margin <= 3 else 2 if margin <= 6 else 1 if margin <= 10 else 0)
    s += 2 if tight_end else 0
    s += 2 if comeback >= 18 else 1 if comeback >= 12 else 0
    s += 1 if changes >= 15 else 0
    s += 2 if top_pts >= 50 else 1 if top_pts >= 40 else 0
    s += 1 if triple else 0
    level = 3 if s >= 7 else 2 if s >= 4 else 1 if s >= 2 else 0
    tags = []
    if ot:
        tags.append("Prolongation")
    elif tight_end:
        tags.append("Fin serrée")
    if comeback >= 12:
        tags.append("Remontée")
    if changes >= 15:
        tags.append("Rebondissements")
    if top_pts >= 40 or triple:
        tags.append("Perf XXL")
    return level, tags


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
    m = durs.get(v["id"]) if v else None
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
    cols = [("MIN", "MIN"), ("PTS", "PTS"), ("REB", "RBD"), ("AST", "PD"), ("FG", "TIRS"), ("3PT", "3 PTS"), ("FT", "LF"),
            ("STL", "INT"), ("BLK", "CTR"), ("TO", "BP"), ("+/-", "+/-")]
    out = []
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
            body.append(f"<tr class='{'st' if r['starter'] else ''}'><td>{esc(r['short'] or r['name'])}</td>{''.join(cells)}</tr>")
        dnp = [f"{r['short'] or r['name']}" + (f" ({INJURY_FR.get(reason_fr(r['reason']), '')})" if reason_fr(r["reason"]) else "")
               for r in rows if r["dnp"]]
        out.append(f"<table class='box'><caption>{logo(tid, 18)} {esc(team(tid)['name'])}</caption><tr><th>Joueur</th>{head}</tr>{''.join(body)}</table>"
                   + (f"<div class='dnp'>N'ont pas joué : {esc(', '.join(dnp))}</div>" if dnp else ""))
    return "".join(out) or "<div class='note'>Feuille de match pas encore disponible.</div>"


def plays_html(summ):
    by_q = defaultdict(list)
    for p, clock, aw, hm, scoring, text, tid in summ.get("plays") or []:
        if p and scoring:
            by_q[p].append(f"<div class='p'><span class='c'>{esc(clock)}</span><b>{esc(team(tid)['abbr'] if tid else '')}</b>"
                           f"<span>{esc(text)}</span><span class='s'>{aw}-{hm}</span></div>")
    if not by_q:
        return "<div class='note'>Pas encore d'actions.</div>"
    parts = []
    for p in sorted(by_q, reverse=True):
        parts.append(f"<div class='qh'>{'QUART-TEMPS ' + str(p) if p <= 4 else 'PROLONGATION ' + str(p - 4)}</div>" + "".join(reversed(by_q[p])))
    return "<div class='plays'>" + "".join(parts) + "</div>"


def form_html(g, idx):
    """Forme (5 derniers matchs avant celui-ci) et 5 derniers face-à-face."""
    rows = []
    for side in ("away", "home"):
        tid = g[side]["id"]
        f = team_form(idx, tid, g["day"], g["season"])
        s = streak_text(f["streak"])
        title = (f"{logo(tid, 18)} <b>{esc(team(tid)['name'])}</b> · " + (f"{f['w']}-{f['l']}" if f["n"] else "début de saison")
                 + (f" · {s}" if s else "") + (" · 2e match en 2 soirs" if f["b2b"] else ""))
        cells = []
        for m in reversed(f["last"]):
            res = "w" if m[2] > m[3] else "l"
            cells.append(f"<td class='{'old' if m[5] != g['season'] else ''}'><span class='{res}'>{'V' if res == 'w' else 'D'}</span> "
                         f"{m[2]}-{m[3]} {'vs' if m[4] else '@'} {esc(team(m[1])['abbr'])}</td>")
        rows.append(f"<tr class='hd'><td colspan='5'>{title}</td></tr><tr>{''.join(cells) or '<td>Aucun match</td>'}</tr>")
    h2h = head_to_head(idx, g["home"]["id"], g["away"]["id"], g["day"])[-5:]
    hrows = []
    for m in reversed(h2h):
        home_t, away_t = (g["home"]["id"], g["away"]["id"]) if m[4] else (g["away"]["id"], g["home"]["id"])
        hs, as_ = (m[2], m[3]) if m[4] else (m[3], m[2])
        win = home_t if hs > as_ else away_t
        hrows.append(f"<tr><td>{m[0].day:02d}/{m[0].month:02d}/{str(m[0].year)[2:]}</td><td>{esc(team(away_t)['abbr'])} {as_} @ {esc(team(home_t)['abbr'])} {hs}</td>"
                     f"<td>{logo(win, 16)} <b>{esc(team(win)['abbr'])}</b>{' · play-offs' if m[6] == 'P' else ''}</td></tr>")
    return ("<div class='sec'>La forme avant ce match</div><div class='form-wrap'><table class='form'>" + "".join(rows) + "</table></div>"
            "<div class='note'>Du plus récent au plus ancien · en grisé : la saison passée</div>"
            "<div class='sec'>Les 5 derniers face-à-face</div>"
            + ("<div class='form-wrap'><table class='form'>" + "".join(hrows) + "</table></div>" if hrows else "<div class='note'>Pas de face-à-face depuis 2016.</div>"))


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
        level, words = w
        icon, label = WATCH_LEVELS[level]
        tags.append(f"<span class='tag {'hot' if level >= 2 else 'cold' if level == 0 else ''}'>{icon} {label}</span>")
        tags += [f"<span class='tag'>{esc(x)}</span>" for x in words[:2]]
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
        v = nba_video(ctx["nba_vids"], g)
        x = extra_video(ctx["extra_vids"], g)
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
        elif g["state"] == "in":
            parts.append(f"<div class='note'>{esc(g['detail'])}</div>")
        worm = worm_svg(g, summ)
        if worm:
            parts.append("<div class='sec'>Le match en un coup d'œil</div>" + worm)
        parts.append(f"<details class='more'><summary>🧾 Stats des joueurs</summary><div class='in'>{box_html(g, summ)}</div></details>")
        parts.append(f"<details class='more'><summary>🏀 Tous les paniers</summary><div class='in'>{plays_html(summ)}</div></details>")
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
    js = journals(ctx["extra_vids"])
    show_time = datetime.combine(show_day, datetime.min.time(), ZONES["Paris"]).replace(hour=12, minute=45)
    show_local = show_time.astimezone(ZONES[zone])
    label = f"NBA Extra du {JOURS[show_day.weekday()][:3]}. {show_day.day:02d}/{show_day.month:02d}"
    if show_day in js:
        v = js[show_day]
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

    recap = nightly_recap(ctx["nba_vids"], day)
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
    ranked = sorted(((ctx["watch"][g["id"]][0], g) for g in games if ctx["watch"].get(g["id"])), key=lambda x: -x[0])
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
        st.session_state.day = default_day(days, today)
    day = st.session_state.day

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
    watch = {g["id"]: watch_score(g, summs.get(g["id"])) for g in games} if interest else {}
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
    found = [v for g in games if g["state"] == "post" for v in (nba_video(nba_vids, g), extra_video(extra_vids, g)) if v]
    found += [v for v in (nightly_recap(nba_vids, day), journals(extra_vids).get(day + timedelta(days=1))) if v]
    ctx["durs"] = video_durations(tuple(sorted({v["id"] for v in found})))

    st.markdown(night_html(day, games, ctx, today), unsafe_allow_html=True)
    if not games:
        st.info("Pas de match NBA ce jour-là.")

    # Ordre : mes équipes, puis (nuit terminée) les matchs à voir d'abord, sinon l'horaire
    def order(g):
        fav = team(g["home"]["id"])["abbr"] in ctx["favs"] or team(g["away"]["id"])["abbr"] in ctx["favs"]
        lv = watch.get(g["id"], (None,))[0]
        return (0 if fav else 1, -(lv if lv is not None else -1) if watch else 0, g["utc"] or "")
    for g in sorted(games, key=order):
        st.markdown(game_card(g, ctx), unsafe_allow_html=True)

    if st.session_state.pop("fav_changed", False):
        set_cookie("nba_fav", ".".join(st.session_state.favs))


if __name__ == "__main__":
    main()
