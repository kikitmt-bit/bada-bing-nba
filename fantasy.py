"""« Le 5 de la semaine » : la fantasy simplifiée de Bada Bing NBA.

Règles (décidées avec Kiki le 26/10/2026) :
- Une équipe par semaine NBA (lundi → dimanche, jours de match aux États-Unis), verrouillée au premier match de la semaine.
- 5 de départ : 2 arrières, 2 ailiers, 1 pivot, plus un 6e homme (n'importe quel poste). Budget : 100 000 €.
- Un joueur rapporte sa MOYENNE de points fantasy sur les matchs qu'il a joués dans la semaine ; toute apparition compte.
- Le 6e homme remplace un des 5 qui n'a joué AUCUN match de la semaine (un seul remplacement).
- « Coup de cœur » : un des 5, à 10 000 € ou moins, dont les points comptent double. Pas de capitaine.
- Prix recalculés chaque semaine d'après la forme (10 derniers matchs 70 %, saison 30 %), variation limitée à ±20 %.
- Résultat officiel quand la semaine est finie ; équipe parfaite de la semaine ; une équipe robot pour avoir un adversaire.

Ce module ne dépend pas de Streamlit : tout ce qui vient d'ESPN ou de GitHub lui est passé en paramètre (testable seul).
"""
import base64
import hashlib
import json
import math
import os
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

BUDGET = 100_000
COEUR_MAX = 10_000          # prix maximum d'un « coup de cœur »
SLOTS = [("G", "Arrière"), ("G", "Arrière"), ("F", "Ailier"), ("F", "Ailier"), ("C", "Pivot")]
ROBOT = "Robot"             # pseudo de l'équipe robot
PRIX_MIN, PRIX_MAX = 4_000, 50_000
PRIOR, PRIOR_N = 12.0, 2    # forme supposée d'un joueur sans historique, et son poids (en matchs)
CAP = 0.20                  # variation maximale du prix d'une semaine à l'autre


# ---------------------------------------------------------------------------
# Points fantasy et postes
# ---------------------------------------------------------------------------
def _n(stats, key):
    try:
        return float(str(stats.get(key, "0")).lstrip("+") or 0)
    except ValueError:
        return 0.0


def minutes(stats):
    m = str(stats.get("MIN", "")).split(":")[0]
    try:
        return float(m)
    except ValueError:
        return 0.0


def fantasy_points(stats):
    """1 par point, 1,2 par rebond, 1,5 par passe, 3 par interception, 3 par contre, −1 par balle perdue."""
    return round(_n(stats, "PTS") + 1.2 * _n(stats, "REB") + 1.5 * _n(stats, "AST")
                 + 3 * _n(stats, "STL") + 3 * _n(stats, "BLK") - _n(stats, "TO"), 1)


def played(row):
    """Le joueur est entré en jeu (même 1 minute) : le match compte."""
    return not row.get("dnp") and minutes(row.get("stats") or {}) > 0


def positions(abbr):
    """Postes possibles à partir de l'abréviation ESPN (PG, SG, G, SF, PF, F, C, G-F, F-C…)."""
    a = (abbr or "").upper().replace("/", "-")
    out = set()
    for part in a.split("-"):
        if part in ("PG", "SG", "G"):
            out.add("G")
        elif part in ("SF", "PF", "F"):
            out.add("F")
        elif part == "C":
            out.add("C")
    return out or {"F"}


# ---------------------------------------------------------------------------
# Semaines
# ---------------------------------------------------------------------------
def monday_of(d):
    return d - timedelta(days=d.weekday())


def week_days(monday):
    return [monday + timedelta(days=i) for i in range(7)]


# ---------------------------------------------------------------------------
# Journal des matchs : {id du match: {"d": jour, "p": {id joueur: [pts fantasy, minutes, titulaire, équipe]}}}
# ---------------------------------------------------------------------------
def log_game(log, game_id, day, summary):
    """Ajoute au journal les lignes de stats d'un match terminé (seulement les joueurs entrés en jeu)."""
    rows = {}
    for tid, players in ((summary or {}).get("box") or {}).items():
        for r in players:
            if r.get("id") and played(r):
                rows[r["id"]] = [fantasy_points(r["stats"]), round(minutes(r["stats"])), 1 if r.get("starter") else 0, tid]
    if rows:
        log[str(game_id)] = {"d": day.isoformat(), "p": rows}
    return bool(rows)


def player_games(log, until=None):
    """{id joueur: [(jour, pts, minutes, titulaire, équipe), ...]} trié, jusqu'au jour `until` exclu."""
    out = defaultdict(list)
    for g in log.values():
        d = date.fromisoformat(g["d"])
        if until and d >= until:
            continue
        for pid, (fp, mn, st, tid) in g["p"].items():
            out[pid].append((d, fp, mn, st, tid))
    for v in out.values():
        v.sort()
    return out


def form_of(games):
    """Forme : 70 % les 10 derniers matchs, 30 % la saison, tirée vers une valeur moyenne tant qu'il y a peu de matchs."""
    if not games:
        return PRIOR
    fps = [g[1] for g in games]
    last = fps[-10:]
    raw = 0.7 * (sum(last) / len(last)) + 0.3 * (sum(fps) / len(fps))
    n = len(fps)
    return (raw * n + PRIOR * PRIOR_N) / (n + PRIOR_N)


def raw_price(form):
    """La meilleure star (~60 pts/match) vaut ~48 000 € ; supplément pour les stars (puissance 1,5)."""
    p = 5_000 + 92.5 * max(form, 0) ** 1.5
    return int(min(PRIX_MAX, max(PRIX_MIN, round(p / 500) * 500)))


def week_prices(log, monday, previous=None):
    """Prix de tous les joueurs connus pour la semaine du lundi `monday`, avec la variation limitée à ±20 %."""
    games = player_games(log, until=monday)
    prices = {}
    for pid, gs in games.items():
        p = raw_price(form_of(gs))
        old = (previous or {}).get(pid)
        if old:
            p = int(min(old * (1 + CAP), max(old * (1 - CAP), p)) // 500 * 500)
        prices[pid] = max(PRIX_MIN, p)
    return prices


def player_info(log, pid, monday, games=None):
    """Forme, minutes par match, titulaire ou non, nombre de matchs joués (avant la semaine).
    `games` : résultat de player_games(log, until=monday), à passer quand on interroge beaucoup de joueurs."""
    gs = (games if games is not None else player_games(log, until=monday)).get(pid) or []
    if not gs:
        return {"form": PRIOR, "mpg": 0, "starter": False, "n": 0}
    last = gs[-10:]
    return {"form": round(form_of(gs), 1), "mpg": round(sum(g[2] for g in last) / len(last), 1),
            "starter": sum(g[3] for g in last) * 2 >= len(last), "n": len(gs)}


# ---------------------------------------------------------------------------
# Équipes : validation et score de la semaine
# ---------------------------------------------------------------------------
def validate(team, prices, pos_of):
    """Erreurs d'une équipe {"five": [5 ids dans l'ordre des postes], "six": id, "coeur": id}. Liste vide = valide."""
    errors = []
    five, six, coeur = team.get("five") or [], team.get("six"), team.get("coeur")
    if len(five) != 5 or not all(five) or not six:
        return ["Il faut choisir les 5 joueurs et le 6e homme."]
    ids = five + [six]
    if len(set(ids)) != len(ids):
        errors.append("Un même joueur ne peut pas être choisi deux fois.")
    for pid, (need, label) in zip(five, SLOTS):
        if need not in pos_of(pid):
            errors.append(f"Poste « {label} » : ce joueur n'y joue pas.")
    cost = sum(prices.get(p, PRIX_MAX) for p in ids)
    if cost > BUDGET:
        errors.append(f"Budget dépassé : {cost:,} € pour {BUDGET:,} €.".replace(",", " "))
    if coeur and (coeur not in five or prices.get(coeur, PRIX_MAX) > COEUR_MAX):
        errors.append(f"Le coup de cœur doit être un des 5, à {COEUR_MAX:,} € ou moins.".replace(",", " "))
    return errors


def week_points(log, monday):
    """{id joueur: [pts fantasy de chaque match joué pendant la semaine]}"""
    days = {d.isoformat() for d in week_days(monday)}
    out = defaultdict(list)
    for g in log.values():
        if g["d"] in days:
            for pid, row in g["p"].items():
                out[pid].append(row[0])
    return out


def score_team(team, pts):
    """Score de la semaine : (total, détail [(id, moyenne comptée, nb matchs, rôle)]).
    Moyenne par match joué ; le 6e homme remplace le premier des 5 qui n'a joué aucun match ; coup de cœur ×2."""
    detail, total, bench_used = [], 0.0, False
    six = team.get("six")
    for pid in team.get("five") or []:
        games = pts.get(pid) or []
        role = "titulaire"
        if not games and not bench_used and pts.get(six):
            bench_used, role, use = True, "remplacé par le 6e homme", six
            games = pts.get(six)
        else:
            use = pid
        avg = sum(games) / len(games) if games else 0.0
        if pid == team.get("coeur") and use == pid:
            avg *= 2
            role = "coup de cœur ×2"
        detail.append((use, round(avg, 1), len(games), role))
        total += avg
    return round(total, 1), detail


# ---------------------------------------------------------------------------
# Équipe parfaite et robot
# ---------------------------------------------------------------------------
def _pairs(cands):
    out = []
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            out.append((cands[i][1] + cands[j][1], cands[i][2] + cands[j][2], (cands[i][0], cands[j][0])))
    return out


def best_team(values, prices, pos_of, budget=BUDGET, top=30):
    """Meilleurs 5 (2 G, 2 F, 1 C) sous le budget pour des valeurs données {id: valeur}. Renvoie (valeur, [ids]) ou None."""
    by = {"G": [], "F": [], "C": []}
    for pid, v in values.items():
        if v <= 0 or pid not in prices:
            continue
        for p in pos_of(pid):
            by[p].append((pid, v, prices[pid]))
    for k in by:
        by[k] = sorted(by[k], key=lambda x: -x[1])[:top]
    gp, fp = _pairs(by["G"]), _pairs(by["F"])
    if not gp or not fp or not by["C"]:
        return None
    fp.sort(key=lambda x: x[1])                       # paires d'ailiers triées par prix, meilleure valeur cumulée
    best_upto, cur = [], None
    for f in fp:
        if cur is None or f[0] > cur[0]:
            cur = f
        best_upto.append(cur)
    costs = [f[1] for f in fp]
    best = None
    for g in gp:
        for c in by["C"]:
            ids = set(g[2]) | {c[0]}
            if len(ids) < 3:
                continue
            room = budget - g[1] - c[2]
            lo, hi = 0, len(costs)                    # dernière paire d'ailiers abordable
            while lo < hi:
                mid = (lo + hi) // 2
                if costs[mid] <= room:
                    lo = mid + 1
                else:
                    hi = mid
            if lo == 0:
                continue
            f = best_upto[lo - 1]
            if ids & set(f[2]):                        # doublon (joueur à deux postes) : on cherche à la main
                f = max((x for x in fp if x[1] <= room and not ids & set(x[2])), key=lambda x: x[0], default=None)
                if not f:
                    continue
            val = g[0] + c[1] + f[0]
            if best is None or val > best[0]:
                best = (val, [g[2][0], g[2][1], f[2][0], f[2][1], c[0]])
    return best


def perfect_team(pts, prices, pos_of):
    """L'équipe parfaite d'une semaine finie (moyennes réelles), avec le meilleur coup de cœur possible."""
    avgs = {pid: sum(v) / len(v) for pid, v in pts.items() if v}
    best = best_team(avgs, prices, pos_of)
    if not best:
        return None
    five = best[1]
    cheap = [p for p in five if prices.get(p, PRIX_MAX) <= COEUR_MAX]
    coeur = max(cheap, key=lambda p: avgs[p], default=None)
    team = {"five": five, "six": None, "coeur": coeur}
    return team, score_team(team, pts)[0]


def robot_team(log, monday, prices, pos_of):
    """L'équipe robot : les meilleurs joueurs en forme que le budget permet (une stratégie simple, sans finesse)."""
    games = player_games(log, until=monday)
    forms = {pid: player_info(log, pid, monday, games)["form"] for pid in prices}
    reserve = min(prices.values())                    # de quoi payer le 6e homme
    best = best_team(forms, prices, pos_of, budget=BUDGET - reserve)
    if not best:
        return None
    five = best[1]
    left = BUDGET - sum(prices[p] for p in five)
    six = max((p for p in prices if p not in five and prices[p] <= left), key=lambda p: forms[p], default=None)
    cheap = [p for p in five if prices[p] <= COEUR_MAX]
    return {"five": five, "six": six, "coeur": max(cheap, key=lambda p: forms[p], default=None), "at": "robot"}


# ---------------------------------------------------------------------------
# Comptes (pseudo + code, sans mot de passe en clair)
# ---------------------------------------------------------------------------
def code_hash(pseudo, code):
    return hashlib.sha256(f"bada-bing|{pseudo.strip().lower()}|{code}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Sauvegarde : un fichier JSON sur GitHub (branche « data » pour ne pas redémarrer le site), sinon sur le disque
# ---------------------------------------------------------------------------
class Store:
    def __init__(self, session, token="", repo="", branch="data", local_dir=".cache"):
        self.s, self.token, self.repo, self.branch, self.dir = session, token, repo, branch or "data", local_dir
        self.sha = {}
        self.lock = threading.Lock()

    @property
    def remote(self):
        return bool(self.token and self.repo)

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    def _ensure_branch(self):
        r = self.s.get(f"https://api.github.com/repos/{self.repo}/branches/{self.branch}", headers=self._h(), timeout=10)
        if r.status_code == 200:
            return True
        info = self.s.get(f"https://api.github.com/repos/{self.repo}", headers=self._h(), timeout=10).json()
        base = self.s.get(f"https://api.github.com/repos/{self.repo}/git/ref/heads/{info.get('default_branch', 'main')}",
                          headers=self._h(), timeout=10).json()
        sha = (base.get("object") or {}).get("sha")
        if not sha:
            return False
        r = self.s.post(f"https://api.github.com/repos/{self.repo}/git/refs", headers=self._h(), timeout=10,
                        json={"ref": f"refs/heads/{self.branch}", "sha": sha})
        return r.status_code in (200, 201)

    def load(self, name, default):
        if self.remote:
            try:
                r = self.s.get(f"https://api.github.com/repos/{self.repo}/contents/fantasy/{name}", headers=self._h(),
                               params={"ref": self.branch}, timeout=15)
                if r.status_code == 200:
                    j = r.json()
                    self.sha[name] = j.get("sha")
                    raw = base64.b64decode(j["content"]) if j.get("content") else self._raw(j)
                    return json.loads(raw.decode("utf-8"))
                if r.status_code == 404:
                    return default
            except Exception:
                pass
        try:
            with open(os.path.join(self.dir, f"fantasy_{name}"), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _raw(self, j):  # fichier de plus de 1 Mo : l'API ne renvoie pas le contenu, on le lit à part
        r = self.s.get(j["download_url"], headers=self._h(), timeout=20)
        return r.content

    def save(self, name, data, message):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self.lock:
            try:
                os.makedirs(self.dir, exist_ok=True)
                with open(os.path.join(self.dir, f"fantasy_{name}"), "wb") as f:
                    f.write(body)
            except Exception:
                pass
            if not self.remote:
                return True
            for _ in range(2):
                payload = {"message": message, "content": base64.b64encode(body).decode(), "branch": self.branch}
                if self.sha.get(name):
                    payload["sha"] = self.sha[name]
                r = self.s.put(f"https://api.github.com/repos/{self.repo}/contents/fantasy/{name}", headers=self._h(),
                               json=payload, timeout=20)
                if r.status_code in (200, 201):
                    self.sha[name] = (r.json().get("content") or {}).get("sha")
                    return True
                if r.status_code == 404 and self._ensure_branch():
                    continue
                if r.status_code in (409, 422):           # quelqu'un a écrit entre-temps : on relit le sha et on réessaie
                    self.load(name, None)
                    continue
                return False
            return False

    def update(self, name, default, change, message):
        """Relit le fichier, applique `change(data)` puis enregistre ; recommence une fois si quelqu'un a écrit entre-temps.
        Renvoie les données à jour (ou None si l'enregistrement a échoué)."""
        for _ in range(3):
            data = self.load(name, default)
            change(data)
            if self.save_once(name, data, message):
                return data
        return None

    def save_once(self, name, data, message):
        """Comme save, mais sans réessayer en cas de conflit (l'appelant relit et réapplique son changement)."""
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self.lock:
            try:
                os.makedirs(self.dir, exist_ok=True)
                with open(os.path.join(self.dir, f"fantasy_{name}"), "wb") as f:
                    f.write(body)
            except Exception:
                pass
            if not self.remote:
                return True
            payload = {"message": message, "content": base64.b64encode(body).decode(), "branch": self.branch}
            if self.sha.get(name):
                payload["sha"] = self.sha[name]
            r = self.s.put(f"https://api.github.com/repos/{self.repo}/contents/fantasy/{name}", headers=self._h(), json=payload, timeout=20)
            if r.status_code == 404 and self._ensure_branch():
                r = self.s.put(f"https://api.github.com/repos/{self.repo}/contents/fantasy/{name}", headers=self._h(), json=payload, timeout=20)
            if r.status_code in (200, 201):
                self.sha[name] = (r.json().get("content") or {}).get("sha")
                return True
            return False

