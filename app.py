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

APP_VERSION = "2026-10-v001"
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
            "color": "#" + (t.get("color") or "888888"), "conf": "",
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
            return f"{t['name']} ({rec(f)}" + (f", {r}e à l'{t['conf']})" if r else ")")
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


def pre_info(g, summ):
    """Ce qu'on savait avant le match (blessés, cotes, meilleurs marqueurs) ; rien si le match est passé et qu'on ne l'a pas vu avant."""
    if g["state"] == "pre":
        return summ
    # Après le match : ce qui a été gardé avant, sinon seulement la cote (fixée avant le match, sans spoil)
    return disk_get(f"pre_{g['id']}.json") or ({"line": summ.get("line")} if summ else None)


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
    th, ta = team(h["id"]), team(a["id"])
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
# AFFICHAGE
# =========================================================================
CSS = """
<style>
.block-container {padding-top: 1.6rem; max-width: 980px;}
.nb-top {display:flex; align-items:center; justify-content:space-between; gap:.6rem; flex-wrap:wrap;}
.nb-title {font-size:1.7rem; font-weight:800; letter-spacing:-.02em; margin:0;}
.nb-title span {color:#F58426;}
.nb-sub {opacity:.65; font-size:.85rem; margin-top:-.2rem;}
.nb-day {font-size:1.25rem; font-weight:700; margin:.4rem 0 .1rem;}
.nb-game {display:grid; grid-template-columns: 1fr auto; gap:.4rem; align-items:center;}
.nb-row {display:flex; align-items:center; gap:.55rem; padding:.12rem 0; font-size:1.05rem;}
.nb-row img {width:30px; height:30px; object-fit:contain;}
.nb-row .rec {opacity:.55; font-size:.8rem;}
.nb-row .sc {margin-left:auto; font-variant-numeric:tabular-nums; font-weight:700; min-width:2.2rem; text-align:right;}
.nb-row.lose {opacity:.55;}
.nb-row.win b {color:#F58426;}
.nb-side {text-align:right; font-size:.85rem; opacity:.85; line-height:1.35; padding-left:.8rem; border-left:1px solid rgba(128,128,128,.25);}
.nb-side .live {color:#ff4b4b; font-weight:700;}
.nb-side .done {font-weight:700;}
.nb-pts {margin:.15rem 0 0; padding-left:0; list-style:none;}
.nb-pts li {margin:.2rem 0; font-size:.93rem; line-height:1.4;}
.nb-form {width:100%; border-collapse:collapse; font-size:.85rem;}
.nb-form td, .nb-form th {padding:.18rem .35rem; border-bottom:1px solid rgba(128,128,128,.18); text-align:left;}
.nb-form .w {color:#21c354; font-weight:700;} .nb-form .l {color:#ff4b4b; font-weight:700;}
.nb-form .old {opacity:.45;}
.nb-q {border-collapse:collapse; font-variant-numeric:tabular-nums; font-size:.92rem;}
.nb-q td, .nb-q th {padding:.2rem .55rem; text-align:center; border-bottom:1px solid rgba(128,128,128,.2);}
.nb-q td:first-child, .nb-q th:first-child {text-align:left;}
.nb-plays {font-size:.84rem; line-height:1.45; max-height:360px; overflow-y:auto;}
.nb-plays .t {opacity:.55; font-variant-numeric:tabular-nums; display:inline-block; min-width:3.2rem;}
.nb-plays .s {font-variant-numeric:tabular-nums; font-weight:700; float:right; padding-left:.5rem;}
.nb-card {border:1px solid rgba(245,132,38,.45); border-radius:.6rem; padding:.55rem .8rem; background:rgba(245,132,38,.07);}
@media (max-width: 640px) {
  .nb-game {grid-template-columns: 1fr;}
  .nb-side {text-align:left; border-left:none; padding-left:0;}
  .nb-row {font-size:1rem;}
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


def night_title(day, zone, today):
    """Titre d'un jour de matchs, selon le fuseau : « Nuit du mercredi 22 au jeudi 23 octobre » à Paris, « Mercredi 22 octobre » à Montréal."""
    rel = {0: ("Cette nuit", "Ce soir"), -1: ("La nuit dernière", "Hier soir"), 1: ("La nuit prochaine", "Demain soir")}.get((day - today).days)
    if zone == "Paris":
        nxt = day + timedelta(days=1)
        if day.month == nxt.month:
            core = f"Nuit du {JOURS[day.weekday()]} {day.day} au {fr_long(nxt)}"
        else:
            core = f"Nuit du {fr_long(day)} au {fr_long(nxt)}"
    else:
        core = fr_long(day).capitalize()
    return (f"{rel[0 if zone == 'Paris' else 1]} · " if rel else "") + core


def pill_label(day, zone, today):
    rel = {0: ("Cette nuit", "Ce soir"), -1: ("Nuit dernière", "Hier soir"), 1: ("Demain", "Demain")}.get((day - today).days)
    if rel:
        return rel[0 if zone == "Paris" else 1]
    return f"Nuit du {day.day}" if zone == "Paris" else fr_short(day)


def default_day(days, today):
    """Le dernier jour où des matchs ont commencé (la nuit qu'on vient de vivre), sinon le prochain."""
    started = [g for g in day_games(today) if g["state"] != "pre"]
    if started:
        return today
    before = [d for d in days if d < today]
    return before[-1] if before else (days[0] if days else today)


def logo(tid, size=30):
    url = team(tid)["logo"]
    return f'<img src="{esc(url)}" width="{size}" height="{size}" alt="">' if url else ""


def game_header(g, zone, revealed, rec):
    """Les deux équipes (visiteurs en haut, comme aux États-Unis), l'heure et l'état du match."""
    tip = parse_dt(g["utc"])
    local = tip.astimezone(ZONES[zone]) if tip else None
    rows = []
    for side in ("away", "home"):
        s = g[side]
        t = team(s["id"])
        cls = ""
        score = ""
        if revealed and s["score"] is not None and g["state"] != "pre":
            score = str(s["score"])
            if g["state"] == "post":
                cls = "win" if s["winner"] else "lose"
        rows.append(f'<div class="nb-row {cls}">{logo(s["id"])}<b>{esc(t["name"])}</b>'
                    f'<span class="rec">{esc(rec.get(s["id"], ""))}</span><span class="sc">{score}</span></div>')
    side = []
    if g["state"] == "pre":
        if g["status"] == "STATUS_POSTPONED":
            side.append('<span class="done">Reporté</span>')
        elif local:
            side.append(f'<b>{fr_hour(local)}</b>' + (f" <span style='opacity:.6'>({fr_short(local.date())})</span>" if local.date() != g["day"] and zone != "Paris" else ""))
    elif g["state"] == "in":
        side.append('<span class="live">● En cours</span>' + (f"<br>{esc(g['detail'])}" if revealed else ""))
    else:
        label = esc(re.sub(r"/(\d*)OT", lambda m: f" ({m.group(1) + ' ' if m.group(1) else ''}prol.)", re.sub(r"^Final", "Terminé", g["detail"]))) if revealed else "Terminé"
        side.append(f'<span class="done">{label}</span>')
    place = g["city"] if g["neutral"] else ""
    if g["tv"] and g["state"] == "pre":
        side.append(f"<span style='opacity:.6'>{esc(g['tv'])}</span>")
    if place:
        side.append(f"📍 {esc(place)}")
    return f'<div class="nb-game"><div>{"".join(rows)}</div><div class="nb-side">{"<br>".join(side)}</div></div>'


def points_html(points):
    return '<ul class="nb-pts">' + "".join(f"<li>{esc(p)}</li>" for p in points) + "</ul>"


def form_html(g, idx):
    """Forme du moment (5 derniers matchs avant celui-ci) et 5 derniers face-à-face."""
    out = []
    for side in ("away", "home"):
        tid = g[side]["id"]
        f = team_form(idx, tid, g["day"], g["season"])
        cells = []
        for m in reversed(f["last"]):
            res = "w" if m[2] > m[3] else "l"
            old = " old" if m[5] != g["season"] else ""
            where = "vs" if m[4] else "@"
            cells.append(f'<td class="{old.strip()}"><span class="{res}">{"V" if res == "w" else "D"}</span> '
                         f'{m[2]}-{m[3]} {where} {esc(team(m[1])["abbr"])}</td>')
        s = streak_text(f["streak"])
        title = f"{logo(tid, 20)} <b>{esc(team(tid)['name'])}</b> " + (f"{f['w']}-{f['l']}" if f["n"] else "début de saison") + (f" · {s}" if s else "") + (" · 2e match en 2 soirs" if f["b2b"] else "")
        out.append(f"<tr><th colspan='5'>{title}</th></tr><tr>{''.join(cells) or '<td>Aucun match</td>'}</tr>")
    h2h = head_to_head(idx, g["home"]["id"], g["away"]["id"], g["day"])[-5:]
    rows = []
    for m in reversed(h2h):
        home_name = team(g["home"]["id"])["abbr"] if m[4] else team(g["away"]["id"])["abbr"]
        away_name = team(g["away"]["id"])["abbr"] if m[4] else team(g["home"]["id"])["abbr"]
        hs, as_ = (m[2], m[3]) if m[4] else (m[3], m[2])
        winner = home_name if hs > as_ else away_name
        tag = " (play-offs)" if m[6] == "P" else ""
        rows.append(f"<tr><td>{m[0].day:02d}/{m[0].month:02d}/{m[0].year}</td><td>{esc(away_name)} {as_} @ {esc(home_name)} {hs}</td>"
                    f"<td><b>{esc(winner)}</b>{tag}</td></tr>")
    table = f"<table class='nb-form'>{''.join(out)}</table>"
    caption = "<div style='opacity:.6;font-size:.78rem;margin:.2rem 0 .6rem'>Avant ce match · en grisé : la saison passée</div>"
    h2h_html = ("<div style='font-weight:700;margin-top:.3rem'>🆚 Derniers face-à-face</div><table class='nb-form'>" + "".join(rows) + "</table>"
                if rows else "<div style='opacity:.6'>Pas de face-à-face depuis 2016.</div>")
    return table + caption + h2h_html


def quarters_html(g):
    n = max(len(g["home"]["lines"]), len(g["away"]["lines"]), 4)
    head = "".join(f"<th>{'Q' + str(i + 1) if i < 4 else 'P' + str(i - 3)}</th>" for i in range(n))
    rows = []
    for side in ("away", "home"):
        s = g[side]
        cells = "".join(f"<td>{v}</td>" for v in s["lines"]) + "<td></td>" * (n - len(s["lines"]))
        rows.append(f"<tr><td>{logo(s['id'], 18)} {esc(team(s['id'])['abbr'])}</td>{cells}<td><b>{s['score'] if s['score'] is not None else ''}</b></td></tr>")
    return f"<table class='nb-q'><tr><th></th>{head}<th>Total</th></tr>{''.join(rows)}</table>"


def box_table(rows):
    cols = ["MIN", "PTS", "REB", "AST", "FG", "3PT", "FT", "STL", "BLK", "TO", "PF", "+/-"]
    names = {"REB": "RBD", "AST": "PD", "FG": "TIRS", "3PT": "3 PTS", "FT": "LF", "STL": "INT", "BLK": "CTR", "TO": "BP", "PF": "FTES"}
    data = []
    for r in rows:
        if r["dnp"]:
            continue
        line = {"Joueur": ("★ " if r["starter"] else "") + r["name"]}
        for c in cols:
            line[names.get(c, c)] = r["stats"].get(c, "")
        data.append(line)
    return data


def plays_html(summ, g, period):
    lines = []
    for p, clock, aw, hm, scoring, text, tid in summ.get("plays") or []:
        if p != period or not scoring:
            continue
        abbr = team(tid)["abbr"] if tid else ""
        lines.append(f"<div><span class='t'>{esc(clock)}</span> <b>{esc(abbr)}</b> {esc(text)}<span class='s'>{aw}-{hm}</span></div>")
    return "<div class='nb-plays'>" + ("".join(reversed(lines)) or "<i>Aucun panier</i>") + "</div>"


def ai_material(g, summ, points):
    th, ta = team(g["home"]["id"]), team(g["away"]["id"])
    art = (summ or {}).get("article") or {}
    lines = [f"Match : {ta['full']} chez {th['full']}.", "Infos calculées :"] + [f"- {p}" for p in points]
    if art.get("text"):
        lines += ["", f"Article AP ({art.get('type')}) : {art.get('headline')}", art["text"][:6000]]
    return "\n".join(lines)


def remember_seen():
    """Garde dans un cookie du navigateur les matchs dont on a déjà regardé le score."""
    ids = ",".join(sorted(st.session_state.vu)[-300:])
    components.html(f"<script>parent.document.cookie='nba_vu={ids}; path=/; max-age=31536000; SameSite=Lax';</script>", height=0)


def render_game(g, zone, idx, vids, show_all):
    nba_vids, extra_vids = vids
    summ = game_summary(g)
    pre = pre_info(g, summ)
    revealed = show_all or g["id"] in st.session_state.vu
    f_rec = {}
    for side in ("away", "home"):
        f = team_form(idx, g[side]["id"], g["day"], g["season"])
        f_rec[g[side]["id"]] = f"{f['w']}-{f['l']}" if f["n"] else ""
    with st.container(border=True):
        st.markdown(game_header(g, zone, revealed, f_rec), unsafe_allow_html=True)

        # Vidéos et bouton du score
        cols = st.columns([1, 1, 1])
        if g["state"] == "post":
            v = nba_video(nba_vids, g)
            if v:
                cols[0].link_button("▶️ Résumé NBA", yt_url(v), width="stretch")
            else:
                cols[0].link_button("🔎 Résumé NBA", yt_search_url(g), width="stretch",
                                    help="Pas encore trouvé : recherche sur YouTube (les titres de la NBA ne donnent pas le score)")
            x = extra_video(extra_vids, g)
            if x:
                cols[1].link_button("🇫🇷 Résumé NBA Extra", yt_url(x), width="stretch")
            else:
                cols[1].button("🇫🇷 Pas de résumé NBA Extra", disabled=True, width="stretch", key=f"nx{g['id']}")
        if g["state"] != "pre" and not show_all:
            if revealed:
                if cols[2].button("🙈 Cacher le score", key=f"hide{g['id']}", width="stretch"):
                    st.session_state.vu.discard(g["id"])
                    st.session_state.vu_changed = True
                    st.rerun()
            elif cols[2].button("👁️ Voir le score", key=f"show{g['id']}", width="stretch", type="primary"):
                st.session_state.vu.add(g["id"])
                st.session_state.vu_changed = True
                st.rerun()

        # Avant-match
        points = preview_points(g, idx, pre)
        ai = ai_points("preview", g, ai_material(g, summ, points)) if (g["state"] == "pre" or disk_get(f"ai_preview_{g['id']}.json")) else None
        with st.expander("📝 Les enjeux", expanded=g["state"] == "pre"):
            st.markdown(points_html(ai or points), unsafe_allow_html=True)
            if ai:
                st.caption("✨ Écrit par Claude d'après ESPN et l'AP")
        with st.expander("📊 Forme · face-à-face"):
            st.markdown(form_html(g, idx), unsafe_allow_html=True)

        # Après le score
        if revealed and summ and g["state"] != "pre":
            if g["state"] == "post" and g["completed"]:
                rp = recap_points(g, summ, idx)
                ai_r = ai_points("recap", g, ai_material(g, summ, rp)) if (summ.get("article") or {}).get("type") == "Recap" else None
                with st.expander("🧠 L'analyse", expanded=True):
                    st.markdown(points_html(ai_r or rp), unsafe_allow_html=True)
                    if ai_r:
                        st.caption("✨ Écrit par Claude d'après le compte rendu AP et les stats")
            with st.expander("🧾 Feuille de match", expanded=g["state"] == "in"):
                st.markdown(quarters_html(g), unsafe_allow_html=True)
                tabs = st.tabs([f"{team(g['away']['id'])['name']}", f"{team(g['home']['id'])['name']}", "📈 Écart", "🏀 Paniers"])
                for tab, side in zip(tabs[:2], ("away", "home")):
                    with tab:
                        rows = (summ.get("box") or {}).get(g[side]["id"]) or []
                        data = box_table(rows)
                        if data:
                            st.dataframe(data, hide_index=True, width="stretch")
                        dnp = [f"{r['name']} ({r['reason'].lower()})" if r["reason"] else r["name"] for r in rows if r["dnp"]]
                        if dnp:
                            st.caption("N'ont pas joué : " + ", ".join(dnp))
                        if not rows:
                            st.caption("Feuille de match pas encore disponible.")
                with tabs[2]:
                    pts, max_h, max_a, changes = flow(summ)
                    if len(pts) > 2:
                        th, ta = team(g["home"]["id"]), team(g["away"]["id"])
                        st.line_chart({"Minute": [p[0] for p in pts], f"Écart (+ = {th['name']})": [p[1] for p in pts]},
                                      x="Minute", height=220)
                        st.caption(f"Plus grosse avance : {th['name']} +{max_h}, {ta['name']} +{max_a} · {changes} changements de leader")
                with tabs[3]:
                    periods = sorted({p[0] for p in summ.get("plays") or [] if p[0]})
                    if periods:
                        labels = {p: (f"Q{p}" if p <= 4 else f"P{p - 4}") for p in periods}
                        pick = st.segmented_control("Quart-temps", periods, format_func=labels.get, default=periods[-1],
                                                    key=f"q{g['id']}", label_visibility="collapsed")
                        st.markdown(plays_html(summ, g, pick or periods[-1]), unsafe_allow_html=True)
                    else:
                        st.caption("Pas encore d'actions.")


def render_journal(extra_vids, zone):
    """Le dernier journal NBA Extra (diffusé à 12h45 à Paris, replay sur YouTube dans l'après-midi)."""
    js = journals(extra_vids)
    today_paris = datetime.now(ZONES["Paris"]).date()
    show_time = "12h45" if zone == "Paris" else fr_hour(datetime.combine(today_paris, datetime.min.time(), ZONES["Paris"]).replace(hour=12, minute=45).astimezone(ZONES[zone]))
    if today_paris in js:
        v = js[today_paris]
        c1, c2 = st.columns([3, 1.3])
        c1.markdown(f"<div class='nb-card'>📺 <b>NBA Extra du jour</b> ({today_paris.day:02d}/{today_paris.month:02d}) est en ligne.</div>", unsafe_allow_html=True)
        c2.link_button("▶️ Regarder le journal", yt_url(v), width="stretch", type="primary")
    else:
        last = max(js) if js else None
        note = f"Le journal du jour ({show_time}{', heure de Montréal' if zone != 'Paris' else ''}) n'est pas encore en ligne, en général " + ("dans l'après-midi." if zone == "Paris" else "en fin de matinée.")
        if today_paris.weekday() >= 5:
            note = "Pas de NBA Extra le week-end (en général)."
        c1, c2 = st.columns([3, 1.3])
        c1.markdown(f"<div class='nb-card'>📺 {note}</div>", unsafe_allow_html=True)
        if last:
            c2.link_button(f"▶️ Journal du {last.day:02d}/{last.month:02d}", yt_url(js[last]), width="stretch")


def main():
    st.set_page_config(page_title="Bada Bing NBA", page_icon="🏀", layout="centered")
    st.markdown(CSS, unsafe_allow_html=True)
    if "vu" not in st.session_state:
        cookie = ""
        try:
            cookie = st.context.cookies.get("nba_vu", "") or ""
        except Exception:
            pass
        st.session_state.vu = {x for x in cookie.split(",") if x.isdigit()}
    zone = user_zone()
    today = datetime.now(NY).date()
    season = season_of(today)

    top_l, top_r = st.columns([3, 1.2], vertical_alignment="center")
    top_l.markdown("<div class='nb-title'>🏀 Bada Bing <span>NBA</span></div><div class='nb-sub'>Tous les matchs, sans spoil.</div>",
                   unsafe_allow_html=True)
    with top_r.popover("⚙️ Réglages", width="stretch"):
        new_zone = st.radio("Heures affichées", list(ZONES), index=list(ZONES).index(zone), horizontal=True,
                            help="Choisi automatiquement d'après le navigateur ; gardé dans l'adresse de la page.")
        if new_zone != zone:
            st.query_params["tz"] = new_zone
            st.rerun()
        show_all = st.toggle("Toujours montrer les scores", value=st.query_params.get("scores") == "1")
        if show_all != (st.query_params.get("scores") == "1"):
            if show_all:
                st.query_params["scores"] = "1"
            else:
                st.query_params.pop("scores", None)
            st.rerun()
        if st.session_state.vu and st.button("🙈 Recacher tous les scores vus", width="stretch"):
            st.session_state.vu = set()
            st.session_state.vu_changed = True
            st.rerun()
        st.caption(f"Version {APP_VERSION} · données ESPN et YouTube")
    show_all = st.query_params.get("scores") == "1"

    with st.spinner("Chargement du calendrier…"):
        schedule = season_games(season, bucket(3600))
        idx = team_index(season, bucket(3600))
    days = sorted({g["day"] for g in schedule})
    if "day" not in st.session_state:
        st.session_state.day = default_day(days, today)
    day = st.session_state.day

    nba_vids, extra_vids = videos_since(min(day, today - timedelta(days=1)))
    render_journal(extra_vids, zone)

    # Choix de la nuit
    near = [d for d in days if d < today][-3:] + [d for d in days if d >= today][:3]
    if day not in near:
        near = sorted(set(near) | {day})
    picked = st.segmented_control("Nuit", near, format_func=lambda d: pill_label(d, zone, today), default=day,
                                  key=f"days_{day}", label_visibility="collapsed")
    if picked and picked != day:
        st.session_state.day = picked
        st.rerun()
    with st.expander("📅 Autre date"):
        other = st.date_input("Date (jour du match aux États-Unis)", value=day, format="DD/MM/YYYY", key=f"other_{day}")
        if other != day:
            st.session_state.day = other
            st.rerun()

    st.markdown(f"<div class='nb-day'>{esc(night_title(day, zone, today))}</div>", unsafe_allow_html=True)
    games = day_games(day)
    links = []
    recap = nightly_recap(nba_vids, day)
    if recap:
        links.append(("🎬 Le résumé de la nuit (NBA)", yt_url(recap)))
    js = journals(extra_vids)
    if (day + timedelta(days=1)) in js:
        jd = day + timedelta(days=1)
        links.append((f"📺 NBA Extra du {jd.day:02d}/{jd.month:02d}", yt_url(js[jd])))
    if links:
        cols = st.columns(len(links))
        for c, (label, url) in zip(cols, links):
            c.link_button(label, url, width="stretch")
    if not games:
        st.info("Pas de match NBA ce jour-là.")
    else:
        with ThreadPoolExecutor(8) as pool:  # charger les fiches ESPN en parallèle (gardées en cache ensuite)
            list(pool.map(game_summary, games))
        st.caption(f"{len(games)} match{'s' if len(games) > 1 else ''} · heures de {zone}")
        for g in games:
            render_game(g, zone, idx, (nba_vids, extra_vids), show_all)

    if st.session_state.pop("vu_changed", False):
        remember_seen()


if __name__ == "__main__":
    main()
