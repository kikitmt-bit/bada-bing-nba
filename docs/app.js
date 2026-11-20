"use strict";
/* ============================================================
   Bada Bing NBA v2 — app.js
   Site statique : le navigateur parle directement à ESPN.
   Règle d'or : AUCUN spoil tant que le score n'est pas révélé
   (pas de score, pas de « prolongation », pas de bilan à jour,
   pas de quart-temps en cours sur un match caché).
   ============================================================ */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const RM = matchMedia("(prefers-reduced-motion: reduce)").matches;
const QS = new URLSearchParams(location.search);
const DEMO = QS.has("demo");

/* ---------- stockage local (remplace les cookies, par appareil) ---------- */
const store = {
  get(k, d) { try { const v = localStorage.getItem("bb2_" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("bb2_" + k, JSON.stringify(v)); } catch (e) { /* navigation privée */ } },
};

/* ---------- les 30 équipes (id ESPN) ---------- */
const TEAMS = {
  1:["ATL","Atlanta","Hawks","#E03A3E","atl"], 2:["BOS","Boston","Celtics","#007A33","bos"],
  3:["NOP","New Orleans","Pelicans","#B4975A","no"], 4:["CHI","Chicago","Bulls","#CE1141","chi"],
  5:["CLE","Cleveland","Cavaliers","#860038","cle"], 6:["DAL","Dallas","Mavericks","#0064B1","dal"],
  7:["DEN","Denver","Nuggets","#FEC524","den"], 8:["DET","Detroit","Pistons","#C8102E","det"],
  9:["GSW","Golden State","Warriors","#FFC72C","gs"], 10:["HOU","Houston","Rockets","#CE1141","hou"],
  11:["IND","Indiana","Pacers","#FDBB30","ind"], 12:["LAC","Los Angeles","Clippers","#1D428A","lac"],
  13:["LAL","Los Angeles","Lakers","#702F8A","lal"], 14:["MIA","Miami","Heat","#98002E","mia"],
  15:["MIL","Milwaukee","Bucks","#00713C","mil"], 16:["MIN","Minnesota","Timberwolves","#236192","min"],
  17:["BKN","Brooklyn","Nets","#8d9096","bkn"], 18:["NYK","New York","Knicks","#F58426","ny"],
  19:["ORL","Orlando","Magic","#0077C0","orl"], 20:["PHI","Philadelphie","76ers","#006BB6","phi"],
  21:["PHX","Phoenix","Suns","#E56020","phx"], 22:["POR","Portland","Trail Blazers","#E03A3E","por"],
  23:["SAC","Sacramento","Kings","#5A2D81","sac"], 24:["SAS","San Antonio","Spurs","#8a9199","sa"],
  25:["OKC","Oklahoma City","Thunder","#007AC1","okc"], 26:["UTA","Utah","Jazz","#3E5EA9","utah"],
  27:["WAS","Washington","Wizards","#E31837","wsh"], 28:["TOR","Toronto","Raptors","#CE1141","tor"],
  29:["MEM","Memphis","Grizzlies","#5D76A9","mem"], 30:["CHA","Charlotte","Hornets","#00788C","cha"],
};
// 2e couleur de chaque équipe (lisible sur fond de nuit), prise par les VISITEURS quand les deux couleurs se ressemblent
const ALT = { 1: "#C1D32F", 2: "#BA9653", 3: "#C8102E", 4: "#D9D9D9", 5: "#FDBB30", 6: "#B8C4CA", 7: "#1D428A", 8: "#1D42BA",
  9: "#1D428A", 10: "#C4CED4", 11: "#BEC0C2", 12: "#C8102E", 13: "#FDB927", 14: "#F9A01B", 15: "#EEE1C6", 16: "#78BE20",
  17: "#F2F2F2", 18: "#006BB6", 19: "#C4CED4", 20: "#ED174C", 21: "#F9AD1B", 22: "#BAC3C9", 23: "#9EA2A2", 24: "#E8E8E8",
  25: "#EF3B24", 26: "#F9A01B", 27: "#C4CED4", 28: "#A1A1A4", 29: "#FFBB22", 30: "#A1A1A4" };
function colorGap(c1, c2) { // écart perçu entre deux couleurs (« redmean »), 0 = identiques, ~765 = noir/blanc
  const v = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16)), [r1, g1, b1] = v(c1), [r2, g2, b2] = v(c2), rm = (r1 + r2) / 2;
  return Math.sqrt((2 + rm / 256) * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + (2 + (255 - rm) / 256) * (b1 - b2) ** 2);
}
function vsColor(awayId, homeId) { // la couleur des visiteurs face à ce domicile (le domicile garde toujours la sienne)
  const ca = (TEAMS[awayId] || [])[3] || "#555", ch = (TEAMS[homeId] || [])[3] || "#555";
  if (colorGap(ca, ch) >= 170) return ca;
  const alt = ALT[awayId];
  if (alt && colorGap(alt, ch) >= 170) return alt;
  return "#E8E8E8"; // en dernier recours : blanc cassé, toujours distinct d'une couleur d'équipe
}
function teamIn(g, tid) { const t = g && (g.teams.away.id === tid ? g.teams.away : g.teams.home.id === tid ? g.teams.home : null); return t || team(tid); }
function team(id) {
  const t = TEAMS[id] || ["NBA", "", "Équipe", "#555", null];
  return { id, tri: t[0], city: t[1], name: t[2], color: t[3], logo: t[4] };
}
window.__team = team; // utilisé par le mode démo
function logoHTML(t, extra) {
  const img = t.logo && !DEMO ? `<img src="https://a.espncdn.com/i/teamlogos/nba/500/${t.logo}.png" alt="" loading="lazy" onerror="this.parentNode.classList.add('noimg')">` : "";
  return `<span class="lg ${t.logo && !DEMO ? "" : "noimg"} ${extra || ""}" style="--mc:${t.color}">${img}<span>${t.tri}</span></span>`;
}

/* ---------- dates : « jour du match » = calendrier de New York ---------- */
const TZ = (Intl.DateTimeFormat().resolvedOptions().timeZone) || "Europe/Paris";
const EURO = !/^America\//.test(TZ);
function nyKey(date) { // AAAAMMJJ à New York
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(date).replaceAll("-", "");
}
function defaultNight() { // la nuit qui vient de se jouer (ou se joue) : on recule de 8 h
  return nyKey(new Date(Date.now() - 8 * 3600e3));
}
function keyDate(key) { // midi UTC ce jour-là (stable quel que soit le fuseau)
  return new Date(Date.UTC(+key.slice(0, 4), +key.slice(4, 6) - 1, +key.slice(6, 8), 12));
}
function addDays(key, n) { const d = keyDate(key); d.setUTCDate(d.getUTCDate() + n); return nyKey(d); }
const FR = (opts) => new Intl.DateTimeFormat("fr-FR", { timeZone: "UTC", ...opts });
function chipText(key) {
  const d = keyDate(key), d2 = keyDate(addDays(key, 1));
  const wd = s => FR({ weekday: "short" }).format(s).replace(".", "");
  const cap = s => s[0].toUpperCase() + s.slice(1);
  if (EURO) return { s: `${cap(wd(d))}. → ${cap(wd(d2))}.`, b: `${d.getUTCDate()} → ${d2.getUTCDate()}` };
  return { s: cap(wd(d)) + ".", b: FR({ day: "numeric", month: "short" }).format(d) };
}
function nightTitle(key) {
  const d = keyDate(key), d2 = keyDate(addDays(key, 1));
  const long = s => FR({ weekday: "long", day: "numeric" }).format(s);
  const mois = s => FR({ month: "long" }).format(s);
  if (EURO) {
    const m1 = mois(d), m2 = mois(d2);
    return `Nuit du ${long(d)}${m1 === m2 ? "" : " " + m1} au ${long(d2)} ${m2}`;
  }
  const t = FR({ weekday: "long", day: "numeric", month: "long" }).format(d);
  return t[0].toUpperCase() + t.slice(1);
}
const ledColon = t => String(t).replace(/:/g, '<i class="cl">:</i>'); // deux-points calés sur la hauteur des chiffres
function hourLocal(date) {
  return new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" }).format(date).replace(":", "h");
}

/* ---------- état ---------- */
const state = {
  vue: "nuit",
  night: null,          // clé AAAAMMJJ affichée
  games: [],
  revealed: new Set(),  // ids révélés (jamais gardé d'une visite à l'autre : c'est voulu)
  timer: null,
  lastLoad: 0,
  tok: 0,               // jeton de la dernière page demandée
};
const settings = {
  fav: store.get("fav", null),           // id d'équipe favorite
  showAll: store.get("showall", false),  // toujours montrer les scores
};
const seen = new Set(store.get("vues", []));

/* ---------- ESPN ---------- */
const API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/";
async function fetchJSON(url) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), 12000);
  try { const r = await fetch(url, { signal: ctl.signal }); if (!r.ok) throw new Error(r.status); return await r.json(); }
  finally { clearTimeout(t); }
}
function normEvent(ev) {
  const comp = ev.competitions[0];
  const st = comp.status || ev.status;
  const stt = st.type || {};
  const g = {
    id: String(ev.id), date: new Date(ev.date),
    state: stt.state === "in" ? "live" : (stt.state === "post" ? "post" : "pre"),
    period: st.period || 0, clock: st.displayClock || "",
    teams: {}, leaders: [],
  };
  for (const c of comp.competitors || []) {
    const side = c.homeAway === "home" ? "home" : "away";
    const rec = (c.records || []).find(r => r.type === "total" || r.name === "overall");
    const recOf = ty => { const r = (c.records || []).find(x => x.type === ty); return r ? r.summary : ""; };
    g.teams[side] = {
      ...team(+c.team.id), score: +c.score || 0, record: rec ? rec.summary : "",
      recHome: recOf("home"), recRoad: recOf("road"),
      ls: (c.linescores || []).map(l => +l.value || 0), // points par quart-temps (pour le match en accéléré)
    };
    for (const L of c.leaders || []) { // leaders de la SAISON : ESPN ne les donne qu'avant le match
      const l = (L.leaders || [])[0]; if (!l || !l.athlete) continue;
      if (L.name === "pointsPerGame") g.teams[side].top = { n: l.athlete.shortName, ppg: +l.value || 0 };
      if (L.name === "rating") g.teams[side].star = l.athlete.shortName;
    }
    for (const L of c.leaders || []) for (const l of L.leaders || [])
      if (L.name === "pointsLeader" || L.abbreviation === "PTS")
        g.leaders.push({ name: l.athlete && l.athlete.shortName || "", pts: +l.value || 0 });
  }
  g.ot = g.state === "post" && g.period > 4;
  pairColors(g);
  return g;
}
function pairColors(g) { if (g.teams.away && g.teams.home) g.teams.away.color = vsColor(g.teams.away.id, g.teams.home.id); return g; }
async function scoreboard(key) {
  if (DEMO) return (await window.DEMO.scoreboard(key)).map(pairColors);
  const url = API + "scoreboard?dates=" + key;
  try {
    const j = await fetchJSON(url);
    const games = (j.events || []).map(normEvent).sort((a, b) => a.date - b.date);
    // copie de secours : si ESPN retombe, on garde la dernière liste reçue
    store.set("sb_" + key, { t: Date.now(), games: games.map(g => ({ ...g, date: g.date.toISOString() })) });
    return games;
  } catch (e) {
    const c = store.get("sb_" + key, null);
    if (c) { alertBar("ESPN ne répond pas : scores de " + new Date(c.t).toLocaleTimeString("fr-FR") + "."); return c.games.map(g => pairColors({ ...g, date: new Date(g.date) })); }
    throw e;
  }
}
async function summary(id) {
  if (DEMO) return window.DEMO.summary(id);
  const j = await fetchJSON(API + "summary?event=" + id);
  return normSummary(j);
}
function normSummary(j) {
  const out = { quarters: null, series: null, players: [], ot: false };
  // quart-temps
  try {
    const comps = j.header.competitions[0].competitors;
    const home = comps.find(c => c.homeAway === "home"), away = comps.find(c => c.homeAway === "away");
    const ls = c => (c.linescores || []).map(l => +l.displayValue || +l.value || 0);
    out.quarters = { home: { id: +home.team.id, q: ls(home), tot: +home.score }, away: { id: +away.team.id, q: ls(away), tot: +away.score } };
    out.ot = ls(home).length > 4;
  } catch (e) { /* pas encore de feuille */ }
  // film du match : l'écart après chaque panier (+ = domicile devant), le même calcul que le Replay +
  try {
    const f = typeof Chrono !== "undefined" ? Chrono.film(j) : null;
    if (f) { out.series = f.pts; out.span = f.span; }
  } catch (e) { /* tant pis pour la courbe */ }
  // feuille de match complète (tous les joueurs, toutes les colonnes utiles)
  try {
    for (const side of j.boxscore.players || []) {
      const tid = +side.team.id;
      const stt = side.statistics[0];
      const ix = n => stt.names.indexOf(n);
      const [iM, iF, i3, iR, iA, iP, iB] = [ix("MIN"), ix("FG"), ix("3PT"), ix("REB"), ix("AST"), ix("PTS"), ix("BLK")];
      for (const a of stt.athletes || []) {
        if (!a.athlete || !a.stats || !a.stats.length) continue;
        out.players.push({
          aid: String(a.athlete.id || ""), name: a.athlete.shortName || a.athlete.displayName,
          full: a.athlete.displayName || "", tid,
          min: a.stats[iM] || "0", fg: a.stats[iF] || "", tp: a.stats[i3] || "",
          pts: +a.stats[iP] || 0, reb: +a.stats[iR] || 0, ast: +a.stats[iA] || 0, blk: iB >= 0 ? +a.stats[iB] || 0 : 0,
          shots: [],
        });
      }
    }
    out.players.sort((a, b) => (b.pts + 1.2 * b.reb + 1.5 * b.ast) - (a.pts + 1.2 * a.reb + 1.5 * a.ast));
  } catch (e) { /* pas de box score */ }
  // les tirs de chaque joueur (pour la carte de tirs)
  try {
    for (const p of j.plays || []) {
      if (!p.shootingPlay || !p.coordinate) continue;
      let { x, y } = p.coordinate;
      if (y > 47) { y = 94 - y; x = 50 - x; } // les deux moitiés de terrain → une seule
      y += 5.25; // ESPN mesure y depuis le PANIER, la carte depuis la ligne de fond (sans ça, les 3 pts tombaient devant la ligne)
      if (x < 0 || x > 50 || y < 0 || y > 47) continue;
      if (p.type && /free throw/i.test(p.type.text || "")) continue; // pas de lancers francs sur la carte
      const aid = p.participants && p.participants[0] && p.participants[0].athlete ? String(p.participants[0].athlete.id) : "";
      const pl = out.players.find(q => (aid && q.aid === aid) || (q.full && (p.text || "").startsWith(q.full)));
      if (pl) pl.shots.push({ x, y, m: !!p.scoringPlay, v: p.scoreValue || 2, q: p.period ? p.period.number : 0 });
    }
  } catch (e) { /* pas de tirs */ }
  return out;
}

/* ---------- note « à voir » (volontairement floue : ne jamais trahir le scénario) ---------- */
function jitter(id) { let s = 0; for (const c of String(id)) s = (s * 31 + c.charCodeAt(0)) % 997; return (s / 997 - .5) * .7; }
function winpct(rec) { const m = /^(\d+)-(\d+)/.exec(rec || ""); if (!m) return .5; const w = +m[1], l = +m[2]; return (w + l) ? w / (w + l) : .5; }
function watchLevel(g) {
  const pa = winpct(g.teams.away.record), ph = winpct(g.teams.home.record);
  if (g.state === "pre") { // affiche d'avant-match : la qualité des deux équipes
    let n = 1.8 + (pa + ph - 1) * 3 + jitter(g.id);
    return Math.max(0, Math.min(4, Math.round(n)));
  }
  const margin = Math.abs(g.teams.home.score - g.teams.away.score);
  let n = 0;
  n += margin <= 3 ? 3 : margin <= 6 ? 2.2 : margin <= 10 ? 1.4 : margin <= 15 ? .7 : 0;
  if (margin >= 25) n -= 1;
  if (g.ot) n += 1.4;
  const top = Math.max(0, ...g.leaders.map(l => l.pts));
  n += top >= 45 ? 1.2 : top >= 38 ? .7 : top >= 32 ? .3 : 0;
  if (g.teams.home.score + g.teams.away.score >= 245) n += .4;
  n += (pa + ph - 1) * 1.2;
  n += jitter(g.id);
  if (g.state === "live") n = Math.max(n, 2.2); // un direct mérite un œil
  return Math.max(0, Math.min(5, Math.round(n * 5 / 4.6)));
}
const RAR = [
  ["nop", "⛔ À fuir"], ["low", "💤 Bof"], ["mid", "😐 Sans plus"],
  ["rar", "🔥 Sympa"], ["epi", "🔥🔥 À voir"], ["leg", "🔥🔥🔥 Immanquable"],
];

/* ---------- les infos clés d'avant-match : jusqu'à 3 par match, aussi sur les matchs joués, JAMAIS de spoil ----------
   Avant le match : données ESPN du jour (bilans, leaders de la saison) + blessés (ESPN /injuries).
   Après : la « photo » prise avant le coup d'envoi par le téléphone-serveur (v2/avant/<nuit>.json) ; sans photo,
   les bilans d'avant-match sont recalculés en retirant le résultat (rien n'est affiché qui le trahisse). */
let INJ = null, INJT = 0;
async function loadInjuries() {
  if (DEMO) return (INJ = {});
  if (INJ && Date.now() - INJT < 15 * 60e3) return INJ;
  try {
    const j = await fetchJSON(API + "injuries");
    const m = {};
    for (const t of j.injuries || []) m[+t.id] = (t.injuries || []).map(i => ({
      n: i.athlete ? i.athlete.shortName : "", st: i.status || "", ty: (i.details && i.details.type) || "" }));
    INJ = m; INJT = Date.now();
  } catch (e) { INJ = INJ || {}; }
  return INJ;
}
let AVANT = {}, AVKEY = null;
async function loadAvant(key) {
  if (AVKEY === key || DEMO) return;
  try { AVANT = await fetchJSON(RAWDATA + "avant/" + key + ".json?t=" + Math.floor(Date.now() / 600e3)); } catch (e) { AVANT = {}; }
  AVKEY = key;
}
const BLESS = { ankle: "cheville", knee: "genou", hamstring: "ischio-jambiers", calf: "mollet", back: "dos", hip: "hanche",
  foot: "pied", shoulder: "épaule", groin: "aine", wrist: "poignet", hand: "main", illness: "malade", concussion: "commotion",
  achilles: "tendon d'Achille", thigh: "cuisse", elbow: "coude", finger: "doigt", toe: "orteil", rest: "repos", personal: "raisons personnelles",
  quadriceps: "quadriceps", abdomen: "abdominaux", oblique: "obliques", neck: "cou", head: "tête", chest: "poitrine", leg: "jambe", lower: "bas du dos" };
const blessFr = ty => BLESS[(ty || "").toLowerCase().split(/[\s/]/)[0]] || (ty || "").toLowerCase();
function moins(rec, gagne) { // un bilan « 13-3 » d'après-match, ramené à avant le match
  const m = /^(\d+)-(\d+)/.exec(rec || ""); if (!m) return rec || "";
  return gagne ? `${Math.max(0, +m[1] - 1)}-${m[2]}` : `${m[1]}-${Math.max(0, +m[2] - 1)}`;
}
function avantMatch(g) { // les données d'avant-match de chaque équipe
  const A = g.teams.away, H = g.teams.home;
  if (g.state === "pre") {
    const inj = INJ || {};
    return { a: { ...A, out: inj[A.id] || [] }, h: { ...H, out: inj[H.id] || [] } };
  }
  const ph = AVANT[g.id];
  if (ph) return { a: { ...A, ...ph.a, name: A.name }, h: { ...H, ...ph.h, name: H.name } };
  if (g.state !== "post") return { a: { ...A, record: "", recHome: "", recRoad: "" }, h: { ...H, record: "", recHome: "", recRoad: "" }, live: true };
  const awayWon = A.score > H.score; // sert seulement à retirer le résultat des bilans, jamais affiché
  return { a: { ...A, top: null, star: null, out: [], record: moins(A.record, awayWon), recRoad: moins(A.recRoad, awayWon), recHome: A.recHome },
           h: { ...H, top: null, star: null, out: [], record: moins(H.record, !awayWon), recHome: moins(H.recHome, !awayWon), recRoad: H.recRoad } };
}
const fr1 = x => String((+x).toFixed(1)).replace(".", ",");
let PREVNIGHT = null, PREVKEY = null; // équipes qui jouaient déjà la nuit précédente
async function loadPrevNight(key) {
  if (PREVKEY === key) return;
  try { const games = await scoreboard(addDays(key, -1)); PREVNIGHT = new Set(games.flatMap(g => [g.teams.away.id, g.teams.home.id])); }
  catch (e) { PREVNIGHT = new Set(); }
  PREVKEY = key;
}
function played(rec) { const m = /^(\d+)-(\d+)/.exec(rec || ""); return m ? +m[1] + +m[2] : 0; }
function keyFacts(g) {
  const D = avantMatch(g), a = D.a, h = D.h, F = [], kinds = new Set();
  const add = (p, k, t, x) => { if (!kinds.has(k)) { kinds.add(k); F.push({ p, t, x }); } };
  // les absences de marque : la star ou le meilleur marqueur de l'équipe
  for (const t of [a, h]) {
    const vips = [t.star, t.top && t.top.n].filter(Boolean);
    for (const o of t.out || []) {
      if (!vips.includes(o.n)) continue;
      const what = o.ty ? ` · ${blessFr(o.ty)}` : "";
      if (/^out$/i.test(o.st)) { F.push({ p: 10, t: "Grosse absence", x: `${o.n} (${t.tri}) forfait${what}` }); break; }
      if (/day|question|doubt|probable/i.test(o.st)) { F.push({ p: 7, t: "Incertain", x: `${o.n} (${t.tri}) incertain${what}` }); break; }
    }
  }
  const pa = winpct(a.record), ph = winpct(h.record), n = Math.min(played(a.record), played(h.record));
  if (n >= 8 && pa >= .65 && ph >= .65) add(9, "niveau", "Choc au sommet", "Deux des meilleurs bilans de la ligue");
  else if (n >= 6 && Math.abs(pa - ph) >= .35) add(6, "niveau", "Grand favori", `Victoire attendue : ${pa > ph ? a.name : h.name}`);
  else if (n >= 6 && Math.abs(pa - ph) <= .06) add(4, "niveau", "Pile ou face", "Impossibles à départager sur le papier");
  const ta = a.top, th = h.top;
  if (ta && th && ta.ppg >= 25 && th.ppg >= 25) add(8, "stars", "Duel de stars", `${ta.n} ${fr1(ta.ppg)} pts – ${th.n} ${fr1(th.ppg)} pts`);
  else { const st = [ta, th].filter(x => x && x.ppg >= 26).sort((x, y) => y.ppg - x.ppg)[0];
    if (st) add(7, "stars", "L'homme en forme", `${st.n} : ${fr1(st.ppg)} pts par match`); }
  if (PREVNIGHT && PREVNIGHT.has(a.id) && PREVNIGHT.has(h.id)) add(5, "fatigue", "Fatigue", "Les deux équipes jouent leur 2e soir de suite");
  else if (PREVNIGHT && (PREVNIGHT.has(a.id) || PREVNIGHT.has(h.id))) {
    const t = PREVNIGHT.has(a.id) ? a : h;
    add(5, "fatigue", "Fatigue", `${t.name} : 2e soir de suite${t === a ? ", en déplacement" : ""}`);
  }
  if (played(h.recHome) >= 5 && winpct(h.recHome) >= .8) add(5, "lieux", "Forteresse", `${h.name} : ${h.recHome} à domicile`);
  else if (played(a.recRoad) >= 5 && winpct(a.recRoad) <= .2) add(5, "lieux", "En galère dehors", `${a.name} : ${a.recRoad} à l'extérieur`);
  else if (played(a.recRoad) >= 5 && winpct(a.recRoad) >= .8) add(4, "lieux", "Solides en voyage", `${a.name} : ${a.recRoad} à l'extérieur`);
  else if (played(h.recHome) >= 5 && winpct(h.recHome) <= .25) add(4, "lieux", "Mal chez eux", `${h.name} : ${h.recHome} à domicile`);
  // infos de secours : il y a toujours quelque chose à dire
  const outs = t => (t.out || []).filter(o => /^out$/i.test(o.st)).length;
  if (outs(a) + outs(h) >= 3) add(3, "infirmerie", "Infirmerie", `${outs(a)} absent${outs(a) > 1 ? "s" : ""} côté ${a.name} · ${outs(h)} côté ${h.name}`);
  if (ta && th) add(2.5, "stars", "Les meneurs", `${ta.n} ${fr1(ta.ppg)} · ${th.n} ${fr1(th.ppg)} pts`);
  if (a.record && h.record) add(2, "bilans", "Les bilans", `${a.name} ${a.record} · ${h.name} ${h.record}`);
  if (h.recHome && a.recRoad) add(1.5, "lieux", "Dom. / ext.", `${h.name} ${h.recHome} chez eux · ${a.name} ${a.recRoad} dehors`);
  return F.sort((x, y) => y.p - x.p).slice(0, 3);
}
function kfHTML(g) {
  const fs = keyFacts(g);
  return fs.length ? `<div class="kfs">${fs.map(f => `<div class="kf"><b>${f.t}</b><span>${f.x}</span></div>`).join("")}</div>` : "";
}

/* ---------- vidéos : liste tenue par le robot GitHub (branche data), lecteur intégré ---------- */
const RAWDATA = "https://raw.githubusercontent.com/kikitmt-bit/bada-bing-nba/data/v2/";
let VIDS = null;
async function loadVideos() {
  if (VIDS !== null) return VIDS;
  if (DEMO) return (VIDS = []);
  try { const j = await fetchJSON(RAWDATA + "videos.json?t=" + Math.floor(Date.now() / 600e3)); VIDS = j.videos || []; }
  catch (e) { VIDS = []; }
  return VIDS;
}
function enDate(g) {
  return new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "long", day: "numeric", year: "numeric" }).format(g.date).toLowerCase();
}
const norm = s => (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
function nicks(t) { // surnoms possibles dans un titre (« SIXERS at BLAZERS »)
  const n = t.name.toLowerCase();
  if (n === "76ers") return ["76ers", "sixers"];
  if (n === "trail blazers") return ["trail blazers", "blazers"];
  return [n];
}
const hasTeam = (t, team_) => nicks(team_).some(n => t.includes(n));
function findVideo(g) { // le bon résumé du bon match : GameTime d'abord (choix de Kiki), sinon NBA
  if (!VIDS || g.state !== "post") return null;
  const d = enDate(g);
  const cand = VIDS.filter(v => {
    if (v.c === "bein") return false;
    const t = norm(v.t);
    if (!hasTeam(t, g.teams.away) || !hasTeam(t, g.teams.home) || !t.includes("highlight")) return false;
    if (t.includes(d)) return true;
    return Math.abs(new Date(v.p) - g.date) < 40 * 3600e3; // publiée autour du match
  });
  return cand.find(v => v.c === "gt") || cand[0] || null;
}
function findExtra(g) { // le résumé de NBA Extra (beIN) : « Résumé : WARRIORS @ LAKERS, … »
  if (!VIDS || g.state !== "post") return null;
  return VIDS.find(v => {
    if (v.c !== "bein") return false;
    const t = norm(v.t);
    return t.startsWith("resume") && hasTeam(t, g.teams.away) && hasTeam(t, g.teams.home)
      && Math.abs(new Date(v.p) - g.date) < 40 * 3600e3;
  }) || null;
}
function findJournal(key) { // le journal NBA Extra du matin : « REPLAY - NBA Extra (13/11) »
  if (!VIDS) return null;
  const d = keyDate(addDays(key, 1)); // la nuit du 12 au 13 → journal du 13
  for (const v of VIDS) {
    if (v.c !== "bein") continue;
    const t = norm(v.t);
    const m = /nba extra\s*\((\d{1,2})\/(\d{1,2})\)/.exec(t);
    if (m && !t.includes("short") && +m[1] === d.getUTCDate() && +m[2] === d.getUTCMonth() + 1) return v;
  }
  return null;
}
function findNightRecap(key) { // le résumé de la nuit sur la chaîne NBA
  if (!VIDS) return null;
  const md = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "long", day: "numeric" }).format(keyDate(key)).toLowerCase();
  return VIDS.find(v => v.c === "nba" && norm(v.t).includes("nightly recap") && norm(v.t).includes(md)) || null;
}
function ytURL(g) { // filet de sécurité : la recherche YouTube
  const q = `${g.teams.away.city} ${g.teams.away.name} vs ${g.teams.home.city} ${g.teams.home.name} full game highlights ${enDate(g)}`;
  return "https://www.youtube.com/results?search_query=" + encodeURIComponent(q);
}
const vidovl = $("#vidovl"), vplayer = $("#vplayer");
function playVideo(vid, label, gid) { // lecteur intégré, sans quitter le site
  // beIN SPORTS interdit la lecture de ses vidéos hors de YouTube (« Vidéo non disponible ») : NBA Extra s'ouvre sur YouTube.
  if (VIDS && VIDS.some(v => v.id === vid && v.c === "bein")) {
    window.open("https://www.youtube.com/watch?v=" + vid, "_blank", "noopener"); return;
  }
  const live = gid && typeof Chrono !== "undefined"; // stats en direct à côté du résumé (le panneau se retire s'il n'a rien à montrer)
  const frame = vid ? `<iframe src="https://www.youtube.com/embed/${vid}?autoplay=1&rel=0&hl=fr${live ? "&enablejsapi=1&origin=" + encodeURIComponent(location.origin) : ""}"
      title="${label}" allow="autoplay; fullscreen; encrypted-media" allowfullscreen></iframe>`
    : `<div class="vdemo">Démo : la vidéo YouTube serait ici</div>`;
  const full = live && Chrono.wantsFull(vid); // plein écran d'office quand il y aura des stats (plus immersif, place dessous)
  vplayer.classList.toggle("live", !!live); vplayer.classList.toggle("full", !!full); vidovl.classList.toggle("full", !!full);
  vplayer.innerHTML = `
    <button class="x" aria-label="Fermer">✕</button>
    ${full && vidovl.requestFullscreen ? `<button class="fsb" aria-label="Plein écran" title="Remettre en plein écran"><svg viewBox="0 0 24 24"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg></button>` : ""}
    <div class="vmain"><div class="vframe">${frame}</div>
    <div class="vfoot"><span>${label}</span>
      ${vid ? `<a href="https://www.youtube.com/watch?v=${vid}" target="_blank" rel="noopener">Ouvrir sur YouTube ↗</a>` : ""}</div></div>
    ${live ? `<aside class="lv" id="lvpanel"></aside><section class="lv-below" id="lvbelow"></section>` : ""}`;
  vidovl.classList.add("open"); document.body.style.overflow = "hidden"; document.body.classList.add("vidon");
  if (full && vidovl.requestFullscreen && !document.fullscreenElement) vidovl.requestFullscreen().catch(() => {}); // pendant le clic : le navigateur l'exige
  if (live) Chrono.attach(gid, $("#lvpanel"), vplayer.querySelector(".vframe"), vid, $("#lvbelow"));
}
async function openResume(id, extra) {
  const g = state.games.find(x => x.id === id); if (!g) return;
  if (!extra && typeof Chrono !== "undefined") { const v0 = VIDS ? findVideo(g) : null; Chrono.onResumeClick(v0 && v0.id); } // partage demandé pendant le clic (exigé par le navigateur), sauf si la vidéo est déjà analysée
  if (DEMO) {
    if (extra || !(typeof Chrono !== "undefined" && Chrono.CAN)) { toast("Démo : ici, le vrai résumé vidéo se lancerait dans le site"); return; }
    playVideo(null, `${g.teams.away.name} – ${g.teams.home.name} · démo`, g.id); return;
  }
  await loadVideos();
  const v = extra ? findExtra(g) : findVideo(g);
  if (!v) { window.open(ytURL(g), "_blank", "noopener"); return; }
  playVideo(v.id, `${g.teams.away.name} – ${g.teams.home.name} · ${extra ? "Replay FR (NBA Extra)" : v.c === "gt" ? "replay GameTime" : "replay NBA"}`, extra ? null : g.id);
}
// après Échap, le bouton « plein écran » réapparaît (seulement hors plein écran)
document.addEventListener("fullscreenchange", () => vplayer.classList.toggle("fs", document.fullscreenElement === vidovl));
function closeResume() {
  if (typeof Chrono !== "undefined") Chrono.close();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  vplayer.innerHTML = ""; vplayer.classList.remove("full"); vidovl.classList.remove("open", "full"); document.body.style.overflow = ""; document.body.classList.remove("vidon");
}

/* ---------- briques d'affichage ---------- */
const RARL = ["À fuir", "Bof", "Sans plus", "Sympa", "À voir", "Immanquable"];
function ledHTML(g, side) {
  const t = g.teams[side];
  return `<span class="led hid" data-g="${g.id}" data-side="${side}" role="button" tabindex="0" aria-label="Révéler le score des ${t.name}"><span class="v">??</span></span>`;
}
function statusText(g, revealed) {
  if (g.state === "pre") return hourLocal(g.date);
  if (g.state === "live") return revealed ? `Q${Math.min(g.period, 4)}${g.period > 4 ? " + prol." : ""} · ${g.clock}` : "En direct";
  return revealed && g.ot ? "Final · prol." : "Final";
}
function clockHTML(g) {
  const cls = g.state === "live" ? "live" : g.state === "pre" ? "pre" : "";
  return `<span class="clock ${cls}" data-st="${g.id}">${statusText(g)}</span>`;
}
function heatHTML(lvl) {
  return `<span class="heat" aria-hidden="true">${[0, 1, 2, 3, 4].map(k => `<i class="${k < lvl ? "on" : ""}" style="--k:${k}"></i>`).join("")}</span>`;
}
function recHTML(t, g) { // bilan : seulement avant le match ou une fois révélé (sinon il trahit le résultat)
  const show = g.state === "pre" || state.revealed.has(g.id) || settings.showAll;
  return show && t.record ? `(${t.record})` : "";
}
function heroHTML(g, lvl) {
  const a = g.teams.away, h = g.teams.home, pre = g.state === "pre";
  const side = (t, s) => `<div class="jteam">${logoHTML(t)}
      <div class="plate"><small>${t.city}</small><b>${t.name}</b></div>
      <div class="rec" data-rec="${g.id}:${s}">${recHTML(t, g)}</div></div>`;
  const mid = pre
    ? `<div class="jscore"><span class="st">Coup d'envoi</span>
         <div class="leds"><span class="led time"><span class="v">${ledColon(hourLocal(g.date).replace("h", ":"))}</span></span></div>
         <span class="hint">heure de chez toi</span></div>`
    : `<div class="jscore"><span class="st ${g.state === "live" ? "live" : ""}" data-st="${g.id}">${statusText(g)}</span>
         <div class="leds">${ledHTML(g, "away")}${ledHTML(g, "home")}</div>
         <span class="hint" data-hint="${g.id}">Touche le score pour revivre le match</span></div>`;
  const foot = kfHTML(g) + (pre ? "" : `<div class="acts">${btnsHTML(g)}</div>`);
  return `<section class="jumbo" data-card="${g.id}" style="--ca:${a.color};--cb:${h.color}">
    <div class="glow"></div>
    <div class="jumbo-in">
      <div class="beam l"></div><div class="beam r"></div>
      <div class="jtop"><span class="tag">${pre ? "L'affiche de la nuit" : "Le match de la nuit"}</span>
        <span class="when r${lvl}">${pre ? `Affiche · ${hourLocal(g.date)}` : `${heatHTML(lvl)}<span>${RARL[lvl]}</span>`}</span></div>
      <div class="jmid">${side(a, "away")}${mid}${side(h, "home")}</div>
      ${foot ? `<div class="jfoot">${foot}</div>` : ""}
    </div>
    <div class="pz"></div>
  </section>`;
}
// « Replay » = le résumé vidéo ; « Replay + » = le résumé avec les stats qui suivent la vidéo (analysé par le téléphone-serveur)
function hasPlus(g) { const v = VIDS ? findVideo(g) : null; return !!(v && typeof Chrono !== "undefined" && Chrono.hasMap(v.id)); }
function replayLabel(g) { return `<span class="pl">▶</span>Replay${hasPlus(g) ? `<b class="plus">+</b>` : ""}`; }
function refreshReplays() { // l'index des vidéos analysées arrive parfois après l'affichage : on met les boutons à jour
  for (const b of document.querySelectorAll("[data-resume]")) {
    const g = state.games.find(x => x.id === b.dataset.resume);
    if (g) { const html = replayLabel(g); if (b.innerHTML !== html) b.innerHTML = html; }
  }
}
function btnsHTML(g) {
  if (g.state === "pre") return "";
  const r = g.state === "post" ? `<button class="btn amber" data-resume="${g.id}">${replayLabel(g)}</button>` : "";
  // plus de « Replay FR » par match (choix de Kiki, 20/11) : seul reste le journal NBA Extra du matin, en tête de la nuit
  return `${r}<button class="btn" data-fiche="${g.id}">Stats</button>`;
}
function cardHTML(g, i) {
  const a = g.teams.away, h = g.teams.home, pre = g.state === "pre";
  const lvl = watchLevel(g);
  const fav = settings.fav && (a.id === settings.fav || h.id === settings.fav);
  const row = (t, s) => `<div class="brow" data-row="${g.id}:${s}" style="--tc:${t.color}">
      <span class="slab">${logoHTML(t)}</span>
      <span class="nm"><b>${t.name}</b><small data-rec="${g.id}:${s}">${recHTML(t, g)}</small></span>
      ${pre ? "" : ledHTML(g, s)}</div>`;
  const kf = kfHTML(g), acts = btnsHTML(g);
  return `<article class="bug r${lvl} ${g.state === "live" ? "is-live" : ""}" data-card="${g.id}" style="--d:${Math.min(i * 80, 640)}ms">
    <div class="floor"></div>
    <div class="bug-in">
      <div class="bh">${clockHTML(g)}${fav ? `<span class="fav">★</span>` : ""}${heatHTML(lvl)}<span class="hl">${pre ? "Affiche" : RARL[lvl]}</span></div>
      ${row(a, "away")}${row(h, "home")}
      ${kf || acts ? `<div class="bf">${kf}${acts ? `<div class="acts">${acts}</div>` : ""}</div>` : ""}
    </div>
    <div class="pz"></div>
  </article>`;
}

/* ---------- révélation : l'afficheur s'allume et le match défile en accéléré ---------- */
function countUp(el, v, d) {
  if (RM) { el.textContent = v; return; }
  const t0 = performance.now(), dur = d || 650;
  (function f(t) { const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3); el.textContent = Math.round(v * e); if (p < 1) requestAnimationFrame(f); })(t0);
}
function particles(card, gold) {
  if (RM || !card) return;
  const pz = card.querySelector(".pz"); if (!pz) return;
  const cols = gold ? ["#f7e08a", "#f3c552", "#fff7d6", "#ffb02e"] : ["#eef2fa", "#aeb8d0", "#fff"];
  for (let k = 0; k < 30; k++) {
    const s = document.createElement("i");
    const a = Math.random() * Math.PI * 2, r = 70 + Math.random() * 170, sz = 6 + Math.random() * 9;
    s.style.cssText = `--tx:${Math.cos(a) * r}px;--ty:${Math.sin(a) * r - 30}px;--pc:${cols[k % cols.length]};animation-delay:${Math.random() * 140}ms;width:${sz}px;height:${sz}px`;
    pz.appendChild(s); setTimeout(() => s.remove(), 1200);
  }
}
function setLed(el, v, roll) {
  const s = el.querySelector(".v"); s.textContent = v;
  if (roll && !RM) { s.classList.remove("roll"); void s.offsetWidth; s.classList.add("roll"); }
}
function finishReveal(g, fx) {
  const wside = g.state === "post" ? (g.teams.away.score > g.teams.home.score ? "away" : "home") : null;
  for (const c of $$(`.led[data-g="${g.id}"]`)) {
    const s = c.dataset.side;
    c.classList.remove("hid", "lead", "trail");
    c.removeAttribute("role"); c.removeAttribute("tabindex");
    c.classList.toggle("win", wside === s); c.classList.toggle("lose", !!wside && wside !== s);
    setLed(c, g.teams[s].score, false);
  }
  for (const st of $$(`[data-st="${g.id}"]`)) st.textContent = statusText(g, true);
  for (const r of $$(`[data-rec^="${g.id}:"]`)) { const s = r.dataset.rec.split(":")[1]; r.textContent = recHTML(g.teams[s], g); }
  const hint = $(`[data-hint="${g.id}"]`); if (hint) hint.style.visibility = "hidden";
  if (fx && !RM) {
    if (wside) for (const r of $$(`[data-row="${g.id}:${wside}"]`)) { r.classList.remove("won"); void r.offsetWidth; r.classList.add("won"); }
    const lvl = watchLevel(g);
    if (lvl >= 4) particles($(`[data-card="${g.id}"]`), lvl === 5);
  }
  updateRevealAll();
}
function reveal(id, instant) {
  const g = state.games.find(x => x.id === id);
  if (!g || g.state === "pre") return;
  const first = !state.revealed.has(id);
  state.revealed.add(id);
  const cells = $$(`.led[data-g="${id}"]`);
  const la = g.teams.away.ls || [], lh = g.teams.home.ls || [];
  const canRace = first && !instant && !RM && g.state === "post" && la.length >= 4 && lh.length >= 4;
  if (!canRace) {
    if (first && !instant && !RM) {
      cells.forEach(c => { c.classList.remove("hid"); c.classList.add("flash"); countUp(c.querySelector(".v"), g.teams[c.dataset.side].score); });
      setTimeout(() => finishReveal(g, true), 700);
    } else finishReveal(g, false);
    return;
  }
  // ⭐ LE MATCH EN ACCÉLÉRÉ : les deux afficheurs s'affrontent quart-temps par quart-temps
  cells.forEach(c => { c.classList.remove("hid"); c.classList.add("flash"); setLed(c, 0, false); });
  const sts = $$(`[data-st="${id}"]`);
  const cum = (arr, k) => arr.slice(0, k + 1).reduce((s, v) => s + v, 0);
  const n = Math.max(la.length, lh.length);
  const stepMs = n > 4 ? 480 : 540;
  let k = 0;
  const tick = () => {
    const sa = cum(la, k), sh = cum(lh, k);
    const lab = k < 4 ? `Fin Q${k + 1}` : (n > 5 ? `Prol. ${k - 3}` : "Prolongation");
    for (const c of cells) {
      const mine = c.dataset.side === "away" ? sa : sh, other = c.dataset.side === "away" ? sh : sa;
      setLed(c, mine, true);
      c.classList.toggle("lead", mine > other); c.classList.toggle("trail", mine < other);
    }
    sts.forEach(s => s.textContent = lab);
    k++;
    if (k < n) setTimeout(tick, stepMs);
    else setTimeout(() => finishReveal(g, true), stepMs + 80);
  };
  setTimeout(tick, 260);
}
function updateRevealAll() {
  const b = $("#revall"); if (!b) return;
  const left = state.games.filter(g => g.state !== "pre" && !state.revealed.has(g.id)).length;
  if (!left) { b.disabled = true; b.innerHTML = "✓ Nuit révélée"; }
}

/* ---------- le brief : la nuit, comme une retransmission ---------- */
function greeting() {
  const hr = new Date().getHours();
  return hr < 5 ? "Bonne nuit" : hr < 12 ? "Bonjour" : hr < 18 ? "Bon après-midi" : "Bonsoir";
}
const plural = (n, w) => `${n} ${w}${n > 1 ? "s" : ""}`;
function cdText(t) { // « 02:14:33 », ou « 1 j 03 h » au-delà d'un jour
  let d = Math.max(0, Math.round((t - Date.now()) / 1000));
  if (d <= 0) return "Imminent";
  const j = Math.floor(d / 86400), h = Math.floor(d % 86400 / 3600), m = Math.floor(d % 3600 / 60), sec = d % 60;
  const p2 = n => String(n).padStart(2, "0");
  return j ? `${j} j ${p2(h)} h` : `${p2(h)}:${p2(m)}:${p2(sec)}`;
}
let CDT = null;
function startCountdown() { // une seule horloge à la fois, arrêtée quand l'afficheur disparaît
  clearInterval(CDT);
  const el = $("#cdown"); if (!el) return;
  CDT = setInterval(() => { const e = $("#cdown"); if (!e) { clearInterval(CDT); return; } e.innerHTML = `<span class="v">${ledColon(cdText(+e.dataset.t))}</span>`; }, 1000);
}
function skyHTML(games, hero, scored) {
  const d1 = keyDate(state.night), d2 = keyDate(addDays(state.night, 1));
  const cap = s => s[0].toUpperCase() + s.slice(1);
  const big = EURO ? `${d1.getUTCDate()}<em>→</em>${d2.getUTCDate()}` : `${d1.getUTCDate()} ${FR({ month: "short" }).format(d1).replace(".", "")}`;
  const small = EURO
    ? `Nuit du ${FR({ weekday: "long" }).format(d1)} au ${FR({ weekday: "long" }).format(d2)} · ${FR({ month: "long" }).format(d2)}`
    : cap(FR({ weekday: "long", month: "long" }).format(d1));
  const nLive = games.filter(g => g.state === "live").length;
  const nFin = games.filter(g => g.state === "post").length;
  const started = nLive + nFin > 0;
  const top = games.filter(g => watchLevel(g) >= 4).length;
  const isLast = state.night === defaultNight();
  const ctx = !games.length ? "Nuit sans match"
    : nLive ? "La nuit est en cours"
    : !started ? "La nuit à venir"
    : isLast && nFin === games.length ? "Pendant que tu dormais"
    : isLast ? "La nuit se termine" : "Retour sur la nuit";
  const nr = started && !DEMO ? findNightRecap(state.night) : null;
  const jr = started && !DEMO ? findJournal(state.night) : null;
  const left = games.filter(g => g.state !== "pre" && !state.revealed.has(g.id)).length;
  // en-tête sur UNE ligne (20/11, carte blanche de Kiki) : la nuit d'avant, celle affichée, celle d'après, le calendrier,
  // puis les boutons. Le contexte (« Retour sur la nuit »…) passe en petite étiquette au-dessus de la nuit affichée.
  // l'afficheur de droite, selon le moment de la nuit : compte à rebours avant, matchs en direct pendant (puis les boutons)
  const nPre = games.filter(g => g.state === "pre").length;
  const first = games.filter(g => g.state === "pre").sort((x, y) => x.date - y.date)[0];
  const board = !games.length ? "" : !started && first
    ? `<div class="board"><span class="btxt"><span class="blab">Coup d'envoi dans</span><small>${plural(games.length, "match")} cette nuit · premier à ${hourLocal(first.date)}</small></span>
        <span class="led bcd" id="cdown" data-t="${first.date.getTime()}"><span class="v">${ledColon(cdText(first.date.getTime()))}</span></span></div>`
    : nLive ? `<div class="board live"><span class="btxt"><span class="blab">La nuit est en cours</span><small>${nFin ? plural(nFin, "terminé") : "aucun terminé"}${nPre ? ` · ${nPre} à venir` : ""}</small></span>
        <span class="blive"><i></i>${nLive} en direct</span></div>` : "";
  return `<section class="sky one">
    <div class="skyrow">
      <div class="nights" id="nights" data-ctx="${ctx}"></div>
      ${board}
      ${started || nr || jr ? `<div class="actions">
      ${started ? `<button class="btn amber big" id="revall" ${left ? "" : "disabled"}>${left ? "🎬 Révéler la nuit" : "✓ Nuit révélée"}</button>` : ""}
      ${nr ? `<button class="btn" data-vplay="${nr.id}" data-vlabel="Le résumé de la nuit NBA"><span class="pl">▶</span>Résumé de la nuit</button>` : ""}
      ${jr ? `<button class="btn" data-vplay="${jr.id}" data-vlabel="NBA Extra · le journal du matin"><span class="pl">▶</span>NBA Extra · le journal</button>` : ""}
      </div>` : ""}
    </div>
  </section>`;
}
async function renderNight(soft) {
  const tok = ++state.tok;
  const main = $("#main");
  setURL();
  if (!soft) main.innerHTML = `<div class="skel"><div class="ph" style="height:160px"></div><div class="ph" style="height:330px"></div><div class="ph" style="height:180px"></div></div>`;
  let games;
  try { [games] = await Promise.all([scoreboard(state.night), loadVideos()]); }
  catch (e) { if (tok === state.tok) main.innerHTML = `<p class="loadmsg">Impossible de joindre ESPN pour cette nuit. Réessaie dans un instant.</p>`; return; }
  if (tok !== state.tok) return;
  state.games = games;
  state.lastLoad = Date.now();
  if (settings.showAll) games.forEach(g => state.revealed.add(g.id));
  if (games.some(g => g.state !== "pre")) markSeen(state.night);
  // pour les infos clés : « 2e soir », blessés (avant le match), photo d'avant-match (après)
  await Promise.all([loadPrevNight(state.night), games.some(g => g.state === "pre") ? loadInjuries() : null,
    games.some(g => g.state !== "pre") ? loadAvant(state.night) : null]);
  if (tok !== state.tok) return;

  const scored = games.map(g => ({ g, lvl: watchLevel(g) })).sort((x, y) => y.lvl - x.lvl || jitter(x.g.id) - jitter(y.g.id));
  const hero = scored.length && scored[0].lvl >= 4 ? scored[0] : null;
  const isFav = g => settings.fav && (g.teams.away.id === settings.fav || g.teams.home.id === settings.fav) ? 1 : 0;
  const rest = games.filter(g => !hero || g.id !== hero.g.id)
    .sort((x, y) => isFav(y) - isFav(x) || watchLevel(y) - watchLevel(x) || x.date - y.date);
  const nPost = games.filter(g => g.state === "post").length;

  main.innerHTML = `${skyHTML(games, hero, scored)}
    ${!games.length ? `<p class="loadmsg">Pas de match cette nuit-là. Les joueurs dorment aussi. 🌙</p>` : ""}
    ${hero ? heroHTML(hero.g, hero.lvl) : ""}
    ${rest.length ? `<div class="sect"><h2>${hero ? "Les autres matchs" : "Les matchs de la nuit"}</h2><i></i></div>
    <div class="bugs">${rest.map((g, i) => cardHTML(g, i)).join("")}</div>` : ""}
    ${nPost >= 2 ? `<section class="stage" id="stage">
      <button class="teaser" id="mvpbtn"><span><span class="q">L'essentiel <em>de la nuit</em></span>
        <small>Tout ce qu'il faut retenir, en une minute · contient les résultats</small></span>
        <span class="btn amber big">Voir l'essentiel</span></button>
      <div id="mvpbody"></div></section>` : ""}
    <div id="nextstrip"></div>`;

  for (const id of state.revealed) reveal(id, true);
  for (const v of $$("[data-count]")) countUp(v, +v.dataset.count, 900);
  startCountdown();
  const all = $("#revall");
  if (all) all.addEventListener("click", () => {
    // la cérémonie : du moins bon au meilleur, le match de la nuit en dernier
    let order = games.filter(g => g.state !== "pre" && !state.revealed.has(g.id)).sort((x, y) => watchLevel(x) - watchLevel(y));
    if (hero) order = order.filter(g => g.id !== hero.g.id).concat(order.filter(g => g.id === hero.g.id));
    let d = 0;
    for (const g of order) {
      setTimeout(() => {
        const el = $(`[data-card="${g.id}"]`);
        if (el && !RM) el.scrollIntoView({ behavior: "smooth", block: "center" });
        reveal(g.id);
      }, d);
      d += RM ? 0 : 1300;
    }
  });
  const mb = $("#mvpbtn");
  if (mb) mb.addEventListener("click", () => loadMVP(mb));
  nextStrip();
  renderChips();
  scheduleRefresh();
}

/* le MVP et les grosses perfs : calculés depuis les feuilles de match, sous les projecteurs (spoil) */
const SUMCACHE = new Map();
async function cachedSummary(id) {
  if (!SUMCACHE.has(id)) SUMCACHE.set(id, await summary(id));
  return SUMCACHE.get(id);
}
const gscore = p => p.pts + 1.2 * p.reb + 1.5 * p.ast;
/* ---------- L'essentiel de la nuit (20/11) : faits marquants, MVP et grosses perfs, Français, classement, sortis blessés ----------
   Tout est caché derrière le bouton : c'est la seule rubrique qui assume les résultats. */

// le Jazz, le Magic, le Heat, le Thunder (singulier) ; les Lakers… (pluriel)
const SING = new Set(["Jazz", "Magic", "Heat", "Thunder"]);
const le = t => (SING.has(t.name) ? "le " : "les ") + t.name;
const du = t => (SING.has(t.name) ? "du " : "des ") + t.name;
const au = t => (SING.has(t.name) ? "au " : "aux ") + t.name;
const cap1 = x => x[0].toUpperCase() + x.slice(1);
function nightFacts(posts, sums) {
  const F = [];
  posts.forEach((g, i) => {
    const s = sums[i]; if (!s) return;
    const A = g.teams.away, H = g.teams.home, aw = A.score > H.score, W = aw ? A : H, L = aw ? H : A, m = Math.abs(A.score - H.score);
    const base = { g, aw };
    // la surprise : le moins bon bilan d'avant-match l'emporte nettement
    const ra = moins(A.record, aw), rh = moins(H.record, !aw), rw = aw ? ra : rh, rl = aw ? rh : ra;
    if (Math.min(played(ra), played(rh)) >= 6 && winpct(rl) - winpct(rw) >= .2)
      F.push({ ...base, p: 7 + (winpct(rl) - winpct(rw)) * 6, k: "surprise", tag: "La surprise", t: `Exploit ${du(W)} face ${au(L)}`, x: `Bilans avant le match : ${W.tri} ${rw} · ${L.tri} ${rl}` });
    if (s.ot) F.push({ ...base, p: 9, k: "fin", tag: "Prolongation", t: `${A.name} – ${H.name} en prolongation`, x: `Il a fallu jouer ${s.quarters ? s.quarters.home.q.length - 4 : 1} prolongation${s.quarters && s.quarters.home.q.length > 5 ? "s" : ""}` });
    else if (m <= 3) F.push({ ...base, p: 8, k: "fin", tag: "Le thriller", t: `Décidé à ${plural(m, "point")}`, x: `${A.name} – ${H.name}, jusqu'au bout` });
    // la remontée : le vainqueur a été mené de 15 points ou plus (écart après chaque panier, + = domicile devant)
    if (s.series && s.series.length) {
      const dv = s.series.map(p => Array.isArray(p) ? p[1] : p);
      const deficit = aw ? Math.max(...dv) : -Math.min(...dv);
      if (deficit >= 15) F.push({ ...base, p: 7 + deficit / 10, k: "remontee", tag: "La remontée", t: `Remontée de ${deficit} points pour ${le(W)}`, x: `${deficit} points de retard au pire moment` });
    }
    if (m >= 25) F.push({ ...base, p: 4 + m / 20, k: "raclee", tag: "La démonstration", t: `Victoire ${du(W)} avec ${m} points d'écart`, x: `${cap1(le(L))} jamais dans le match` });
    // les perfs individuelles
    for (const pl of s.players || []) {
      const t3 = +((pl.tp || "").split("-")[0]) || 0, nom = pl.full || pl.name;
      if (pl.pts >= 40) F.push({ ...base, p: 9 + (pl.pts - 40) / 4, k: "perf", tag: "La perf", t: `${pl.pts} points pour ${nom}`, x: `${pl.reb} reb · ${pl.ast} pd · ${pl.fg} au tir`, pl });
      else if (pl.pts >= 10 && pl.reb >= 10 && pl.ast >= 10) F.push({ ...base, p: 8, k: "perf", tag: "Triple-double", t: `Triple-double de ${nom}`, x: `${pl.pts} pts · ${pl.reb} reb · ${pl.ast} pd`, pl });
      else if (t3 >= 8) F.push({ ...base, p: 7, k: "perf", tag: "Adresse folle", t: `${t3} paniers à 3 points pour ${nom}`, x: `${pl.pts} pts · ${pl.tp} à 3 pts`, pl });
    }
  });
  F.sort((a, b) => b.p - a.p);
  const out = [], perGame = new Map(), perKind = new Map();
  for (const f of F) { // de la variété : 2 faits max par match et par type
    if ((perGame.get(f.g.id) || 0) >= 2 || (perKind.get(f.k) || 0) >= 2) continue;
    out.push(f); perGame.set(f.g.id, (perGame.get(f.g.id) || 0) + 1); perKind.set(f.k, (perKind.get(f.k) || 0) + 1);
    if (out.length === 6) break;
  }
  return out;
}
function factHTML(f, i) {
  const A = f.g.teams.away, H = f.g.teams.home;
  const face = f.pl && /^\d+$/.test(f.pl.aid) && !DEMO ? `<img class="fph" src="https://a.espncdn.com/i/headshots/nba/players/full/${f.pl.aid}.png" alt="" loading="lazy" onerror="this.remove()">` : "";
  return `<article class="fact ${face ? "has-ph" : ""}" style="--ca:${A.color};--cb:${H.color};animation-delay:${i * 70}ms">${face}
    <span class="ftag">${f.tag}</span><h4>${f.t}</h4><p>${f.x}</p>
    <div class="fsc">${logoHTML(A)}<b class="${f.aw ? "w" : ""}">${A.score}</b><i>–</i><b class="${f.aw ? "" : "w"}">${H.score}</b>${logoHTML(H)}</div></article>`;
}
// les Français : lieu de naissance des effectifs ESPN (gardé une semaine sur l'appareil)
async function frenchIds(teamIds) {
  const c = store.get("fr", null), fresh = c && Date.now() - c.t < 7 * 864e5 ? c : { t: Date.now(), teams: {} };
  const miss = teamIds.filter(id => !(id in fresh.teams));
  await Promise.all(miss.map(async id => {
    try {
      const j = await fetchJSON(API + "teams/" + id + "/roster");
      fresh.teams[id] = (j.athletes || []).filter(a => /france/i.test((a.birthPlace && a.birthPlace.country) || "") || /france|french/i.test(a.citizenship || "")).map(a => String(a.id));
    } catch (e) { /* tant pis pour cette équipe */ }
  }));
  if (miss.length) store.set("fr", fresh);
  return new Set(Object.values(fresh.teams).flat());
}
// le classement avant / après la nuit (seulement pour la dernière nuit jouée)
async function standingMoves(posts) {
  const data = await fetchJSON("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings");
  const res = new Map();
  for (const g of posts) {
    const aw = g.teams.away.score > g.teams.home.score;
    res.set(g.teams.away.id, aw ? "w" : "l"); res.set(g.teams.home.id, aw ? "l" : "w");
  }
  const moves = [];
  for (const ch of data.children || []) {
    const conf = /east/i.test(ch.name) ? "Est" : "Ouest";
    const rows = ((ch.standings && ch.standings.entries) || []).map(en => {
      const sv = n => { const x = (en.stats || []).find(y => y.name === n); return x ? +x.value : 0; };
      const id = +en.team.id, w = sv("wins"), l = sv("losses"), r = res.get(id);
      return { id, w, l, w0: r === "w" ? w - 1 : w, l0: r === "l" ? l - 1 : l };
    });
    const rank = (k1, k2) => [...rows].sort((a, b) => (b[k1] / Math.max(1, b[k1] + b[k2])) - (a[k1] / Math.max(1, a[k1] + a[k2])) || b[k1] - a[k1]).map(r => r.id);
    const after = rank("w", "l"), before = rank("w0", "l0");
    for (const id of res.keys()) {
      const a = after.indexOf(id), b = before.indexOf(id); if (a < 0 || b < 0 || a === b) continue;
      const crossed = (b >= 6 && a < 6) ? "entre dans le top 6" : (b < 6 && a >= 6) ? "sort du top 6" : (b >= 10 && a < 10) ? "entre dans le top 10" : (b < 10 && a >= 10) ? "sort du top 10" : a === 0 ? "prend la tête" : "";
      const sc = (a === 0 ? 30 : 0) + (crossed ? 20 : 0) + Math.abs(a - b) * 4;
      moves.push({ id, a, b, conf, crossed, sc });
    }
  }
  // seulement ce qui compte : 2 places ou plus, ou un changement de zone (1re place, top 6, top 10)
  return moves.filter(m => m.crossed || Math.abs(m.a - m.b) >= 2).sort((x, y) => y.sc - x.sc).slice(0, 5);
}
async function loadMVP(btn) {
  btn.disabled = true;
  const lab = btn.querySelector(".btn"); if (lab) lab.textContent = "On fait le tour de la nuit…";
  const posts = state.games.filter(g => g.state === "post");
  const sums = await Promise.all(posts.map(g => cachedSummary(g.id).catch(() => null)));
  const all = [];
  sums.forEach((s, i) => { if (s) for (const p of s.players) all.push({ ...p, g: posts[i] }); });
  if (!all.length) { if (lab) lab.textContent = "Indisponible pour l'instant"; btn.disabled = false; return; }
  const isLast = state.night === defaultNight();
  const [frIds, moves] = await Promise.all([
    DEMO ? Promise.resolve(new Set()) : frenchIds([...new Set(posts.flatMap(g => [g.teams.away.id, g.teams.home.id]))]).catch(() => new Set()),
    isLast && !DEMO ? standingMoves(posts).catch(() => []) : Promise.resolve([]),
    posts.some(g => AVANT[g.id]) ? loadInjuries() : null]);
  all.sort((a, b) => gscore(b) - gscore(a));
  // le MVP et les grosses perfs
  const mvp = all[0], t = team(mvp.tid);
  const opp = mvp.g.teams.away.id === mvp.tid ? mvp.g.teams.home : mvp.g.teams.away;
  const photo = /^\d+$/.test(mvp.aid) && !DEMO ? `<img src="https://a.espncdn.com/i/headshots/nba/players/full/${mvp.aid}.png" alt="" onerror="this.remove()">` : "";
  const stat = (v, l) => `<div class="stat"><span class="led"><span class="v" data-count="${v}">0</span></span><small>${l}</small></div>`;
  const full = (mvp.full || mvp.name).trim(), cut = full.indexOf(" ");
  const nameHTML = cut > 0 ? `<span>${full.slice(0, cut)}</span><span>${full.slice(cut + 1)}</span>` : `<span>${full}</span>`;
  const mvpBlock = `<div class="mvpw"><div class="mvp">
      <div class="card" style="--tc:${t.color}">${photo}${logoHTML(t)}</div>
      <div style="min-width:0">
        <h3>${nameHTML}</h3>
        <div class="sub">${t.city} ${t.name} · contre ${le(opp)}</div>
        <div class="row">${stat(mvp.pts, "points")}${stat(mvp.reb, "rebonds")}${stat(mvp.ast, "passes")}</div>
      </div></div>
    <div class="perfs"><span class="tag ghost">Les grosses perfs</span>${all.slice(1, 7).map((p, i) => {
      const pt = team(p.tid);
      return `<div class="perf" style="--tc:${pt.color};animation-delay:${200 + i * 70}ms"><span class="slab">${logoHTML(pt)}</span><b>${p.full || p.name}</b><small>${p.pts} PTS · ${p.reb} REB · ${p.ast} PAS</small></div>`;
    }).join("")}</div></div>`;
  // les faits marquants
  const facts = nightFacts(posts, sums);
  const factsBlock = facts.length ? `<div class="ess-h"><span class="tag">Les faits marquants</span><i></i></div><div class="facts">${facts.map(factHTML).join("")}</div>` : "";
  // les Français
  // un MVP français est déjà en vedette juste au-dessus : la rubrique montre alors les AUTRES Français
  const mvpFr = frIds.has(mvp.aid);
  const fr = all.filter(p => frIds.has(p.aid) && p !== mvp).sort((a, b) => gscore(b) - gscore(a));
  const frCols = fr.length <= 5 ? Math.max(1, fr.length) : fr.length === 6 ? 3 : 4; // 1 à 5 sur une ligne, 6 = 2 × 3, puis 4 par ligne
  const frBlock = `<div class="ess-h"><span class="tag">${mvpFr ? "Les autres Français de la nuit" : "Les Français de la nuit"}</span><i></i></div>${fr.length ? `<div class="frg" style="--n:${frCols}">${fr.map((p, i) => {
      const pt = team(p.tid), og = p.g.teams.away.id === p.tid ? p.g.teams.home : p.g.teams.away;
      const ph = /^\d+$/.test(p.aid) && !DEMO ? `<img src="https://a.espncdn.com/i/headshots/nba/players/full/${p.aid}.png" alt="" loading="lazy" onerror="this.remove()">` : "";
      return `<div class="frt" style="--tc:${pt.color};animation-delay:${i * 60}ms"><span class="frp">${ph}${logoHTML(pt)}</span>
        <span class="frn"><b>${p.full || p.name}</b><small>${pt.tri} contre ${og.tri} · ${p.min} min</small>
        <span class="frs"><b>${p.pts}</b><small>pts</small><b>${p.reb}</b><small>reb</small><b>${p.ast}</b><small>pd</small></span></span></div>`;
    }).join("")}</div>` : `<p class="essn pad">${mvpFr ? "Aucun autre Français sur les parquets cette nuit." : "Aucun Français sur les parquets cette nuit."}</p>`}`;
  // le classement
  const mvBlock = moves.length ? `<div class="essb"><h4>Ça a bougé au classement</h4>${moves.map(m => {
      const tt = team(m.id), up = m.a < m.b;
      return `<div class="mvl ${up ? "up" : "down"}">${logoHTML(tt)}<span class="mvn"><b>${tt.name}</b><small>${m.crossed ? m.crossed : (up ? "gagne " : "perd ") + plural(Math.abs(m.a - m.b), "place")} · ${m.conf}</small></span>
        <span class="mvr"><i>${m.b + 1}e</i><em>${up ? "▲" : "▼"}</em><b>${m.a + 1}e</b></span></div>`;
    }).join("")}</div>` : "";
  // sortis blessés : les blessés du matin qui n'étaient pas sur la photo d'avant-match
  let hurt = [];
  if (INJ) for (const g of posts) {
    const ph = AVANT[g.id]; if (!ph) continue;
    for (const [side, T] of [["a", g.teams.away], ["h", g.teams.home]]) {
      const before = new Set(((ph[side] && ph[side].out) || []).map(o => o.n));
      for (const o of INJ[T.id] || []) if (!before.has(o.n) && /out|day|question/i.test(o.st)) hurt.push({ o, T });
    }
  }
  const huBlock = hurt.length ? `<div class="essb hu"><h4>Sortis blessés</h4>${hurt.slice(0, 5).map(({ o, T }) => { const out = /^out$/i.test(o.st);
      return `<div class="hul">${logoHTML(T)}<span class="mvn"><b>${o.n}</b><small>${T.name} · ${o.ty ? blessFr(o.ty) : "blessure"}</small></span><span class="hst ${out ? "out" : ""}">${out ? "Forfait" : "Incertain"}</span></div>`; }).join("")}</div>` : "";
  btn.hidden = true;
  const body = $("#mvpbody");
  const more = mvBlock || huBlock ? `<div class="ess-h"><span class="tag">Et aussi</span><i></i></div><div class="essrow">${mvBlock}${huBlock}</div>` : "";
  body.innerHTML = `<div class="ess"><div class="ess-top"><span class="q">L'essentiel <em>de la nuit</em></span><small>Tout ce qu'il faut retenir, en une minute</small></div>
    ${factsBlock}<div class="ess-h"><span class="tag">Le MVP et les grosses perfs</span><i></i></div>${mvpBlock}${frBlock}${more}</div>`;
  for (const v of body.querySelectorAll("[data-count]")) countUp(v, +v.dataset.count, 1100);
}

/* la nuit prochaine, en un clin d'œil */
async function nextStrip() {
  const el = $("#nextstrip"); if (!el || state.night !== defaultNight()) return;
  const next = addDays(state.night, 1);
  let games;
  try { games = await scoreboard(next); } catch (e) { return; }
  const pre = games.filter(g => g.state === "pre");
  if (!pre.length || state.night !== defaultNight() || !$("#nextstrip")) return;
  const top = [...pre].sort((x, y) => watchLevel(y) - watchLevel(x))[0];
  $("#nextstrip").innerHTML = `<div class="next"><span class="tt">La nuit prochaine</span>
    <span>${pre.length} match${pre.length > 1 ? "s" : ""} · l'affiche : ${top.teams.away.name} – ${top.teams.home.name} à ${hourLocal(top.date)}</span>
    <button class="btn" data-night-go="${next}">Voir la nuit ›</button></div>`;
}

function markSeen(key) { if (!seen.has(key)) { seen.add(key); store.set("vues", [...seen].slice(-90)); } }

/* mise à jour automatique pendant les matchs (le vrai direct, sans recharger) */
function scheduleRefresh() {
  clearTimeout(state.timer);
  if (state.vue !== "nuit") return;
  const live = state.games.some(g => g.state === "live");
  const upcoming = state.games.some(g => g.state === "pre" && g.date - Date.now() < 30 * 60e3);
  if (live || upcoming) state.timer = setTimeout(() => { if (!$("#ovl").classList.contains("open")) renderNight(true); else scheduleRefresh(); }, 60e3);
}
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.vue === "nuit" && Date.now() - state.lastLoad > 3 * 60e3) renderNight(true);
});

/* ---------- fiche du match ---------- */
const ovl = $("#ovl"), sheet = $("#sheet");
async function openFiche(id) {
  const g = state.games.find(x => x.id === id); if (!g) return;
  reveal(id); // ouvrir la fiche = vouloir le score
  const a = g.teams.away, h = g.teams.home;
  const win = g.state === "post" ? (a.score > h.score ? "away" : "home") : null;
  sheet.innerHTML = `
    <div class="fh" style="--ca:${a.color};--cb:${h.color}">
      <button class="x" aria-label="Fermer">✕</button>
      <div class="fgrid">
        <div class="fteam">${logoHTML(a)}<b>${a.name}</b><small>${a.city} ${a.record ? `(${a.record})` : ""}</small></div>
        <div class="fmid"><div class="leds">
            <span class="led ${win === "away" ? "win" : win ? "lose" : ""}"><span class="v">${a.score}</span></span>
            <span class="led ${win === "home" ? "win" : win ? "lose" : ""}"><span class="v">${h.score}</span></span></div>
          <div class="fstat">${statusText(g, true)}</div></div>
        <div class="fteam">${logoHTML(h)}<b>${h.name}</b><small>${h.city} ${h.record ? `(${h.record})` : ""}</small></div>
      </div>
    </div>
    <div class="fbody"><p class="loadmsg">Feuille de match en route…</p></div>`;
  ovl.classList.add("open"); document.body.style.overflow = "hidden";
  let s;
  try { s = await summary(id); }
  catch (e) { sheet.querySelector(".fbody").innerHTML = `<p class="loadmsg">Impossible de charger les détails. Réessaie dans un instant.</p>`; return; }
  const body = sheet.querySelector(".fbody");
  body.innerHTML = `
    ${s.series ? `<div class="fsect"><h3><span class="tag">Le film du match</span><i></i></h3>${chartHTML(g, s.series, s.span)}</div>` : ""}
    ${s.quarters ? `<div class="fsect"><h3><span class="tag">Par quart-temps</span><i></i></h3>${quartersHTML(g, s)}</div>` : ""}
    ${s.players.length ? `<div class="fsect"><h3><span class="tag">Les patrons du match</span><i></i></h3>${prosHTML(s.players.slice(0, 6), g)}</div>` : ""}
    ${s.players.length ? `<div class="fsect"><h3><span class="tag">La feuille de match</span><i></i></h3>
      <p class="bx-hint">Touche un joueur pour voir tous ses tirs sur le terrain 🎯</p>
      ${boxHTML(g, s, "away")}${boxHTML(g, s, "home")}</div>` : ""}
    <div class="fbtns">${g.state === "post" ? `<button class="btn amber big" data-resume="${g.id}">${replayLabel(g)}</button>` : ""}</div>
    <div class="next-note">Bientôt dans la fiche : face-à-face des deux équipes, avant-match détaillé, absents.</div>`;
  state.fiche = s; state.ficheG = g; // pour la carte de tirs
  requestAnimationFrame(() => {
    body.querySelectorAll(".fl").forEach(b => b.style.width = b.dataset.w + "%");
    const line = body.querySelector(".filmline");
    if (line && !RM) {
      const L = line.getTotalLength();
      line.style.strokeDasharray = L; line.style.strokeDashoffset = L;
      line.style.transition = "stroke-dashoffset 1.4s cubic-bezier(.3,.7,.3,1)";
      requestAnimationFrame(() => line.style.strokeDashoffset = 0);
    }
  });
  hookChart(g, s.series, s.span);
}
function closeFiche() { ovl.classList.remove("open"); document.body.style.overflow = ""; scheduleRefresh(); }

function filmPts(pts, span) { // [[secondes, écart]] ; l'ancien format (un écart par minute, mode démo) est converti
  const P = typeof pts[0] === "number" ? pts.map((v, i) => [i * 60, v]) : pts;
  return { P, span: span || P[P.length - 1][0] || 2880 };
}
function chartHTML(g, pts, span0) {
  const W = 720, H = 230, P = { l: 34, r: 14, t: 18, b: 26 };
  const { P: pp, span } = filmPts(pts, span0);
  const vals = pp.map(q => q[1]);
  const mx = Math.max(4, ...vals.map(Math.abs));
  const X = t => P.l + t * (W - P.l - P.r) / span, Y = v => P.t + (1 - (v + mx) / (2 * mx)) * (H - P.t - P.b);
  // une ligne qui change à chaque panier : les allers-retours dessinent des dents
  const dL = pp.map((q, i) => (i ? "L" : "M") + `${X(q[0]).toFixed(1)},${Y(q[1]).toFixed(1)}`).join("");
  const area = dL + `L${X(span).toFixed(1)},${Y(0).toFixed(1)}L${X(0).toFixed(1)},${Y(0).toFixed(1)}Z`;
  const marks = []; for (let t = 720; t <= span; t += (t < 2880 ? 720 : 300)) marks.push(t);
  const qs = marks.map(t => `<line x1="${X(t)}" y1="${P.t}" x2="${X(t)}" y2="${H - P.b}" stroke="rgba(255,255,255,.06)"/>
    <text x="${X(t) - 4}" y="${H - 8}" fill="#62667f" font-size="11" text-anchor="end">${t === span ? "Fin" : t <= 2880 ? "Q" + Math.round(t / 720) : "P" + Math.round((t - 2880) / 300)}</text>`).join("");
  const a = g.teams.away, h = g.teams.home;
  const mxi = vals.indexOf(Math.max(...vals)), mni = vals.indexOf(Math.min(...vals));
  const ann = (i, c, tri) => { const v = vals[i]; return v === 0 ? "" : `<circle cx="${X(pp[i][0])}" cy="${Y(v)}" r="3.5" fill="${c}" stroke="#0d0e18" stroke-width="2"/>
    <text x="${X(pp[i][0])}" y="${Y(v) + (v > 0 ? -9 : 16)}" fill="#f2f3f8" font-size="12" font-weight="700" text-anchor="middle" font-family="Barlow Condensed">+${Math.abs(v)} ${tri}</text>`; };
  const cid = "fc" + g.id;
  return `<div class="chartbox">
  <svg class="chart" viewBox="0 0 ${W} ${H}">
    <defs><clipPath id="${cid}u"><rect x="0" y="0" width="${W}" height="${Y(0)}"/></clipPath><clipPath id="${cid}d"><rect x="0" y="${Y(0)}" width="${W}" height="${H}"/></clipPath></defs>
    <path d="${area}" fill="${h.color}" opacity=".3" clip-path="url(#${cid}u)"/><path d="${area}" fill="${a.color}" opacity=".3" clip-path="url(#${cid}d)"/>${qs}
    <line x1="${P.l}" y1="${Y(0)}" x2="${W - P.r}" y2="${Y(0)}" stroke="rgba(255,255,255,.3)"/>
    <text x="${P.l}" y="${P.t + 2}" fill="#a8acc4" font-size="11">${h.name} devant</text>
    <text x="${P.l}" y="${H - P.b - 6}" fill="#a8acc4" font-size="11">${a.name} devant</text>
    <path d="${dL}" fill="none" stroke="#f2f3f8" stroke-width="1.6" stroke-linejoin="round" class="filmline"/>
    ${ann(mxi, h.color, h.tri)}${ann(mni, a.color, a.tri)}
    <line class="cross" x1="0" y1="${P.t}" x2="0" y2="${H - P.b}" stroke="rgba(255,255,255,.35)" stroke-dasharray="3 3" visibility="hidden"/>
  </svg><div class="ttip"></div>
  <div class="clegend"><span><i style="background:${a.color}"></i>${a.name}</span><span><i style="background:${h.color}"></i>${h.name}</span></div></div>`;
}
function hookChart(g, pts, span0) {
  if (!pts) return;
  const svg = sheet.querySelector(".chart"), tip = sheet.querySelector(".ttip"), cross = svg && svg.querySelector(".cross");
  if (!svg) return;
  const { P: pp, span } = filmPts(pts, span0);
  const W = 720, P = { l: 34, r: 14 };
  svg.addEventListener("pointermove", e => {
    const r = svg.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width * W;
    const t = Math.max(0, Math.min(span, (fx - P.l) / (W - P.l - P.r) * span));
    let v = 0; for (const q of pp) { if (q[0] > t) break; v = q[1]; } // l'écart à cet instant (dernier panier passé)
    const X = P.l + t * (W - P.l - P.r) / span;
    cross.setAttribute("x1", X); cross.setAttribute("x2", X); cross.setAttribute("visibility", "visible");
    tip.style.display = "block"; tip.style.left = (X / W * 100) + "%"; tip.style.top = "14px";
    const when = t <= 0 ? "Début" : t >= span ? "Fin" : t <= 2880 ? `Q${Math.min(4, Math.floor(t / 720) + 1)} · ${Math.floor(t / 60) + 1}ᵉ min` : "Prolongation";
    tip.innerHTML = `${when} — <b>${v === 0 ? "égalité" : v > 0 ? g.teams.home.name + " +" + v : g.teams.away.name + " +" + (-v)}</b>`;
  });
  svg.addEventListener("pointerleave", () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); });
}
function quartersHTML(g, s) {
  const lab = ["Q1", "Q2", "Q3", "Q4"];
  const n = Math.max(s.quarters.home.q.length, s.quarters.away.q.length);
  for (let k = 4; k < n; k++) lab.push("P" + (k - 3));
  const row = (side) => {
    const t = g.teams[side], qq = s.quarters[side].q;
    const win = g.state === "post" && t.score > g.teams[side === "away" ? "home" : "away"].score;
    return `<tr class="${win ? "" : "tr2"}"><td>${t.name}</td>${lab.map((_, i) => `<td>${qq[i] ?? ""}</td>`).join("")}<td class="tot">${s.quarters[side].tot}</td></tr>`;
  };
  return `<div class="qtwrap"><table class="qt"><thead><tr><th>Équipe</th>${lab.map(l => `<th>${l}</th>`).join("")}<th>Total</th></tr></thead>
    <tbody>${row("away")}${row("home")}</tbody></table></div>`;
}
function prosHTML(players, g) {
  return `<div class="pros">` + players.map(p => {
    const t = teamIn(g, p.tid);
    const bar = (lab, v, max) => `<div class="bar"><em>${lab}</em><div class="tr"><div class="fl" data-w="${Math.min(100, v / max * 100)}"></div></div><b>${v}</b></div>`;
    return `<div class="pro" style="--mc:${t.color}">
      <div class="pteam">${logoHTML(t)}<span>${t.name}</span></div>
      <div class="who"><b>${p.name}</b></div>
      <div class="big">${p.pts}<small>pts</small></div>
      <div class="bars">${bar("REB", p.reb, 15)}${bar("PD", p.ast, 15)}${bar("CTR", p.blk || 0, 6)}</div></div>`;
  }).join("") + `</div>`;
}

/* ---------- la feuille de match ---------- */
function boxHTML(g, s, side) {
  const t = g.teams[side];
  const list = s.players.filter(p => p.tid === t.id);
  if (!list.length) return "";
  const row = p => `<tr class="${p.shots.length ? "shootable" : ""}" ${p.shots.length ? `data-shot="${p.aid || p.name}"` : ""}>
    <td><span class="bxn">${p.name}</span>${p.shots.length ? `<span class="tgt">🎯</span>` : ""}</td>
    <td>${p.min}</td><td>${p.fg}</td><td>${p.tp}</td><td>${p.reb}</td><td>${p.ast}</td><td>${p.blk || 0}</td><td class="tot">${p.pts}</td></tr>`;
  return `<div class="bxteam"><div class="bxh" style="--mc:${t.color}">${logoHTML(t)}<b>${t.name}</b></div>
    <div class="qtwrap"><table class="qt bx"><thead><tr><th>Joueur</th><th>Min</th><th>Tirs</th><th>3 pts</th><th>Reb</th><th>Pas</th><th title="Contres">Ctr</th><th>Pts</th></tr></thead>
    <tbody>${list.map(row).join("")}</tbody></table></div></div>`;
}

/* ---------- la carte de tirs (tous les tirs du joueur, dans l'ordre du match) ---------- */
const shotovl = $("#shotovl"), shotsheet = $("#shotsheet");
function courtSVG(shots, color) {
  // repère de la carte : panier en (25, 5.25), x sur la largeur (0-50 pieds), y depuis la ligne de fond (ESPN + 5,25 : voir normSummary)
  const S = 10, W = 500, H = 400; // on montre jusqu'à 40 pieds (au-delà : exploits de fin de quart)
  const hoop = { x: 25 * S, y: 5.25 * S };
  const lines = `
    <rect x="0" y="0" width="${W}" height="${H}" fill="#0d0f1c"/><rect x="${17 * S}" y="0" width="${16 * S}" height="${19 * S}" fill="${color}" opacity=".10"/>
    <rect x="${17 * S}" y="0" width="${16 * S}" height="${19 * S}" fill="none" stroke="rgba(255,255,255,.18)"/>
    <circle cx="${hoop.x}" cy="${19 * S}" r="${6 * S}" fill="none" stroke="rgba(255,255,255,.18)"/>
    <circle cx="${hoop.x}" cy="${hoop.y}" r="${.75 * S}" fill="none" stroke="#f3c552" stroke-width="2"/>
    <line x1="${hoop.x - 3 * S}" y1="${4 * S}" x2="${hoop.x + 3 * S}" y2="${4 * S}" stroke="rgba(255,255,255,.4)" stroke-width="2"/>
    <line x1="${3 * S}" y1="0" x2="${3 * S}" y2="${14 * S}" stroke="rgba(255,255,255,.18)"/>
    <line x1="${47 * S}" y1="0" x2="${47 * S}" y2="${14 * S}" stroke="rgba(255,255,255,.18)"/>
    <path d="M ${3 * S} ${14 * S} A ${23.75 * S} ${23.75 * S} 0 0 0 ${47 * S} ${14 * S}" fill="none" stroke="rgba(255,255,255,.18)"/>`;
  const step = Math.max(130, Math.min(260, Math.floor(5200 / Math.max(1, shots.length)))); // ~5 s de replay
  const marks = shots.map((sh, i) => {
    const cx = sh.x * S, cy = Math.min(sh.y, 39) * S, d = RM ? 0 : i * step;
    return sh.m
      ? `<circle class="ring" cx="${cx}" cy="${cy}" r="7" fill="none" stroke="${color}" stroke-width="2" style="animation-delay:${d}ms"/><circle class="shot" cx="${cx}" cy="${cy}" r="7" fill="${color}" stroke="#fff" stroke-width="2" style="animation-delay:${d}ms"/>`
      : `<g class="shot" style="animation-delay:${d}ms"><line x1="${cx - 6}" y1="${cy - 6}" x2="${cx + 6}" y2="${cy + 6}" stroke="#8a8fa8" stroke-width="2.5"/><line x1="${cx - 6}" y1="${cy + 6}" x2="${cx + 6}" y2="${cy - 6}" stroke="#8a8fa8" stroke-width="2.5"/></g>`;
  }).join("");
  return { svg: `<svg class="court" viewBox="0 0 ${W} ${H}">${lines}${marks}</svg>`, step };
}
let shotTimer = null;
function openShots(key) {
  const s = state.fiche; if (!s) return;
  const p = s.players.find(q => q.aid === key || q.name === key); if (!p) return;
  const t = teamIn(state.ficheG, p.tid);
  const made = p.shots.filter(x => x.m).length, three = p.shots.filter(x => x.v === 3);
  const { svg, step } = courtSVG(p.shots, t.color);
  shotsheet.innerHTML = `<div class="setbody">
    <button class="x" aria-label="Fermer">✕</button>
    <div class="shead" style="--mc:${t.color}">${logoHTML(t)}<div><h2>${p.full || p.name}</h2><small>${t.city} ${t.name}</small></div>
      <button class="btn replay" data-replay="${key}">↻ Rejouer</button></div>
    <div class="stiles">
      <div class="stat"><span class="led"><span class="v">${p.pts}</span></span><small>points</small></div>
      <div class="stat"><span class="led"><span class="v">${made}/${p.shots.length}</span></span><small>aux tirs</small></div>
      <div class="stat"><span class="led"><span class="v">${three.filter(x => x.m).length}/${three.length}</span></span><small>à 3 pts</small></div>
      <div class="stat"><span class="led"><span class="v">${p.reb}</span></span><small>rebonds</small></div>
    </div>
    ${svg}
    <div class="scount" id="scount">&nbsp;</div>
    <div class="clegend"><span><i style="background:${t.color}"></i>Panier</span><span style="color:#8a8fa8">✕ Tir manqué</span></div>
  </div>`;
  shotovl.classList.add("open");
  // le compteur suit le replay : quart-temps, tirs, points sur tirs cumulés
  clearInterval(shotTimer);
  const cEl = $("#scount");
  if (RM) { cEl.textContent = `${p.shots.length} tirs · ${made} réussis`; return; }
  let i = 0, pts = 0;
  shotTimer = setInterval(() => {
    if (i >= p.shots.length) { clearInterval(shotTimer); cEl.textContent = `Fin du match · ${made}/${p.shots.length} aux tirs, ${pts} points sur tirs`; return; }
    const sh = p.shots[i];
    if (sh.m) pts += sh.v;
    cEl.textContent = `${sh.q ? (sh.q <= 4 ? "Q" + sh.q : "Prolongation") + " · " : ""}tir ${i + 1}/${p.shots.length} · ${pts} points sur tirs`;
    i++;
  }, step);
}
function closeShots() { clearInterval(shotTimer); shotovl.classList.remove("open"); }

/* ---------- l'affiche : un vrai match à enjeu (choix de Kiki : équipes bien classées, superstars, séries, rivalités…) ---------- */
let RANKS = null; // id -> { conf, rank, streak (+5 = 5 victoires de suite, -3 = 3 défaites), gp }
async function loadRanks() {
  if (RANKS) return RANKS;
  const m = new Map();
  try {
    const data = DEMO ? await window.DEMO.standings() : await fetchJSON("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings");
    for (const ch of data.children || []) {
      const rows = ((ch.standings && ch.standings.entries) || []).map(en => {
        const f = n => (en.stats || []).find(x => x.name === n || x.type === n);
        const w = f("wins") ? +f("wins").value : 0, l = f("losses") ? +f("losses").value : 0;
        const sv = f("streak"); let st = 0;
        if (sv) { const mm = /^([WL])(\d+)/i.exec(sv.displayValue || ""); st = mm ? (mm[1].toUpperCase() === "W" ? +mm[2] : -mm[2]) : +sv.value || 0; }
        return { id: +en.team.id, w, l, st };
      }).sort((x, y) => (y.w / Math.max(1, y.w + y.l)) - (x.w / Math.max(1, x.w + x.l)) || y.w - x.w);
      rows.forEach((r, i) => m.set(r.id, { conf: ch.name, rank: i + 1, streak: r.st, gp: r.w + r.l }));
    }
  } catch (e) { /* sans classement : l'affiche se contente des bilans et des stars */ }
  return (RANKS = m);
}
const RIVAL = new Set(["BOS-LAL", "LAC-LAL", "BOS-NYK", "GSW-LAL", "BOS-PHI", "CHI-DET", "MIA-NYK", "DAL-SAS", "CLE-GSW", "BKN-NYK", "DEN-LAL", "BOS-MIA", "LAL-PHX", "GSW-HOU", "LAL-SAS", "CHI-NYK", "PHI-NYK", "MEM-OKC"]);
function afficheOf(g) { // { s: note, why: [raisons] } : une affiche = note ≥ 3,5 (et 2 par nuit au plus, voir markAffiches)
  const A = g.teams.away, H = g.teams.home, R = RANKS || new Map();
  const ra = R.get(A.id), rh = R.get(H.id);
  const gp = Math.min(ra ? ra.gp : 0, rh ? rh.gp : 0), sure = Math.min(1, gp / 10); // début de saison : on se méfie des bilans
  let s = 0; const why = [];
  const lvl = r => !r ? 0 : r.rank <= 2 ? 1.6 : r.rank <= 4 ? 1.2 : r.rank <= 6 ? .8 : r.rank <= 8 ? .3 : 0;
  const top = (lvl(ra) + lvl(rh)) * sure; s += top;
  if (ra && rh && ra.rank <= 3 && rh.rank <= 3) { s += 1.2 * sure; why.push(ra.conf === rh.conf ? "choc au sommet" : "les leaders des deux conférences"); }
  else if (top >= 1.6) why.push("deux équipes du haut de tableau");
  if (ra && rh && ra.conf === rh.conf && ra.rank <= 10 && rh.rank <= 10 && Math.abs(ra.rank - rh.rank) <= 2) { s += .6 * sure; if (!why.length) why.push("duel direct au classement"); }
  const star = t => !t.top ? 0 : t.top.ppg >= 30 ? 1.4 : t.top.ppg >= 27 ? 1 : t.top.ppg >= 25 ? .5 : 0;
  const sa = star(A), sh = star(H); s += sa + sh;
  if (sa >= 1 && sh >= 1) { s += .6; why.push(`duel de stars : ${A.top.n} – ${H.top.n}`); }
  else if (sa >= 1 || sh >= 1) { const t = sa >= sh ? A : H; why.push(`${t.top.n} (${t.top.ppg.toFixed(1)} pts/m)`); }
  const hot = r => !r ? 0 : r.streak >= 8 ? 1.4 : r.streak >= 5 ? 1 : r.streak >= 4 ? .5 : 0;
  for (const [r, t] of [[ra, A], [rh, H]]) { const v = hot(r); s += v; if (v >= 1) why.push(`${t.name} : ${r.streak} victoires de suite`); }
  const pa = winpct(A.record), ph = winpct(H.record);
  if (pa >= .65 && ph >= .65) s += .6 * sure;
  if (Math.min(pa, ph) < .4 && gp >= 5) s -= 2.5; // une équipe en pleine galère : pas d'affiche, même face à un cador
  const key = [A.tri, H.tri].sort().join("-");
  if (RIVAL.has(key)) { s += .9; why.push("une rivalité historique"); }
  return { s, why };
}
function markAffiches(games) { // au plus 2 affiches par nuit, les meilleures, et seulement si la note est franche
  const sc = games.map(g => ({ g, ...afficheOf(g) })).filter(x => x.s >= 3.5).sort((x, y) => y.s - x.s).slice(0, 2);
  return new Map(sc.map(x => [x.g.id, x.why]));
}

/* ---------- vue « Programme » : la grille télé (une colonne par nuit, les matchs sous leur heure) ---------- */
function tzName() { // « heure de Paris », « heure de Montréal »…
  const c = (TZ.split("/").pop() || "").replace(/_/g, " ");
  const fr = { Paris: "Paris", Montreal: "Montréal", Toronto: "Toronto", Brussels: "Bruxelles", Zurich: "Zurich", London: "Londres", New_York: "New York", "New York": "New York" };
  return c ? `heure de ${fr[c] || c}` : "heure locale";
}
function progNight(key) { // « Nuit du jeudi 19 » / « au vendredi 20 novembre » (2 lignes), ou « Jeudi 19 novembre » au Québec
  const d = keyDate(key), d2 = keyDate(addDays(key, 1));
  const long = x => FR({ weekday: "long", day: "numeric" }).format(x), mois = x => FR({ month: "long" }).format(x);
  if (EURO) return [`Nuit du ${long(d)}${mois(d) === mois(d2) ? "" : " " + mois(d)}`, `au ${long(d2)} <em>${mois(d2)}</em>`];
  return [long(d)[0].toUpperCase() + long(d).slice(1), `<em>${mois(d)}</em>`];
}
async function renderProgramme() {
  const tok = ++state.tok;
  const main = $("#main");
  setURL();
  const head = `<section class="tvhead"><p class="greet"><i></i>Les prochaines nuits · ${tzName()}</p></section>`;
  main.innerHTML = head + `<div class="skel"><div class="ph" style="height:120px"></div><div class="ph" style="height:120px"></div></div>`;
  const tonight = defaultNight();
  const keys = [...Array(7)].map((_, i) => addDays(tonight, i));
  let nights;
  try { [nights] = await Promise.all([Promise.all(keys.map(k => scoreboard(k).catch(() => []))), loadRanks()]); }
  catch (e) { if (tok === state.tok) main.innerHTML = `<p class="loadmsg">Impossible de joindre ESPN.</p>`; return; }
  if (tok !== state.tok) return;
  let n = 0, hasFav = false, hasHype = false;
  const cols = keys.map((k, i) => {
    const games = nights[i].filter(g => g.state === "pre").sort((a, b) => a.date - b.date);
    if (!games.length) return "";
    const AFF = markAffiches(games);
    const slots = []; // les matchs groupés par heure de début
    for (const g of games) {
      const h = hourLocal(g.date);
      if (!slots.length || slots[slots.length - 1].h !== h) slots.push({ h, gs: [] });
      slots[slots.length - 1].gs.push(g);
    }
    const [l1, l2] = progNight(k);
    const body = slots.map(sl => `<div class="tvslot">
        <span class="led time"><span class="v">${ledColon(sl.h.replace("h", ":"))}</span></span>
        <div class="tvgs">${sl.gs.map(g => {
          const a = g.teams.away, h = g.teams.home;
          const fav = settings.fav && (a.id === settings.fav || h.id === settings.fav);
          const hype = AFF.has(g.id), why = hype ? AFF.get(g.id) : [];
          if (fav) hasFav = true; if (hype) hasHype = true;
          // une seule ligne par match : logo + sigle, @ au centre (le nom complet au survol)
          return `<div class="tvg ${fav ? "fav" : ""} ${hype ? "hype" : ""}" style="animation-delay:${Math.min(n++ * 30, 600)}ms"
              title="${a.name} @ ${h.name}${a.record ? ` (${a.record} · ${h.record})` : ""}${fav ? " · mon équipe" : ""}${hype ? ` · l'affiche${why.length ? " : " + why.join(", ") : ""}` : ""}">
            <span class="tvt a">${logoHTML(a)}<b>${a.tri}</b></span><span class="tvat">@</span><span class="tvt h"><b>${h.tri}</b>${logoHTML(h)}</span>
            ${hype ? `<i class="tvmk">◆</i>` : fav ? `<i class="tvmk">★</i>` : ""}</div>`;
        }).join("")}</div></div>`).join("");
    return `<section class="tvcol">
      <button class="tvday" data-prog-night="${k}" title="Voir cette nuit"><span>${l1}</span><span>${l2}</span>
        <small>${plural(games.length, "match")}</small></button>${body}</section>`;
  }).join("");
  const legend = hasFav || hasHype ? `<p class="tvleg">${hasFav ? `<span><i class="tvmk">★</i>mon équipe</span>` : ""}${hasHype ? `<span><i class="tvmk h">◆</i>l'affiche : match à enjeu (haut de tableau, superstars, séries, rivalité) · détails au survol</span>` : ""}</p>` : "";
  main.innerHTML = head + legend + (cols ? `<div class="tvgrid">${cols}</div>` : `<p class="loadmsg">Aucun match programmé sur les 7 prochaines nuits.</p>`);
}

/* ---------- classement (sans spoil : la dernière nuit est retirée tant qu'on ne l'inclut pas) ---------- */
async function renderStandings() {
  const tok = ++state.tok;
  const main = $("#main");
  setURL();
  main.innerHTML = `<section class="tvhead"><p class="greet"><i></i>La hiérarchie</p></section>
    <div class="skel"><div class="ph" style="height:300px"></div></div>`;
  let data;
  try {
    data = DEMO ? await window.DEMO.standings()
      : await fetchJSON("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings");
  } catch (e) { if (tok === state.tok) main.innerHTML = `<p class="loadmsg">Impossible de charger le classement.</p>`; return; }
  if (state.cutLast === undefined) state.cutLast = !settings.showAll;
  // la coupure : on retire les résultats de la dernière nuit jouée
  let adj = new Map(), cutPossible = false;
  try {
    const lg = await scoreboard(defaultNight());
    for (const g of lg) if (g.state === "post") {
      cutPossible = true;
      const wside = g.teams.away.score > g.teams.home.score ? "away" : "home";
      const wId = g.teams[wside].id, lId = g.teams[wside === "away" ? "home" : "away"].id;
      const aw = adj.get(wId) || { w: 0, l: 0 }; aw.w++; adj.set(wId, aw);
      const al = adj.get(lId) || { w: 0, l: 0 }; al.l++; adj.set(lId, al);
    }
  } catch (e) { /* pas grave : pas de coupure possible */ }
  if (tok !== state.tok) return;
  const cut = state.cutLast && cutPossible;
  const confs = [];
  for (const ch of data.children || []) {
    const rows = [];
    for (const en of (ch.standings && ch.standings.entries) || []) {
      const find = n => (en.stats || []).find(x => x.name === n || x.type === n);
      const sv = n => { const s = find(n); return s && s.value !== undefined ? +s.value : null; };
      let w = sv("wins") ?? 0, l = sv("losses") ?? 0;
      const st = find("streak");
      if (cut && adj.has(+en.team.id)) { w -= adj.get(+en.team.id).w; l -= adj.get(+en.team.id).l; }
      rows.push({ id: +en.team.id, w: Math.max(0, w), l: Math.max(0, l), streak: st ? (st.displayValue || "") : "" });
    }
    rows.sort((a, b) => (b.w / Math.max(1, b.w + b.l)) - (a.w / Math.max(1, a.w + a.l)) || b.w - a.w);
    confs.push({ name: /east/i.test(ch.name) ? "Conférence Est" : /west/i.test(ch.name) ? "Conférence Ouest" : ch.name, rows });
  }
  const pct = r => (r.w + r.l) ? (r.w / (r.w + r.l)) : 0;
  const confHTML = c => {
    const lead = c.rows[0];
    return `<div class="conf"><h2>${c.name}</h2>
      <div class="srow head"><span></span><span></span><span>Équipe</span><span class="n">V</span><span class="n">D</span><span class="n">%</span><span class="n gb">Écart</span></div>
      ${c.rows.map((r, i) => {
        const t = team(r.id);
        const gb = lead ? ((lead.w - r.w) + (r.l - lead.l)) / 2 : 0;
        return `<div class="srow ${i < 6 ? "po" : i < 10 ? "pi" : ""} ${i === 5 || i === 9 ? "cutline" : ""} ${r.id === settings.fav ? "favrow" : ""}" style="--tc:${t.color};animation-delay:${i * 30}ms">
          <span class="rk">${i + 1}</span>${logoHTML(t)}<span class="tn">${t.name}</span>
          <span class="n">${r.w}</span><span class="n">${r.l}</span><span class="n pc">${(pct(r) * 100).toFixed(1).replace(".", ",")}</span>
          <span class="n gb">${gb === 0 ? "–" : gb.toFixed(1).replace(".0", "").replace(".", ",")}</span></div>`;
      }).join("")}</div>`;
  };
  // plus de grand titre (déjà dans le menu, comme le programme) : étiquette, coupure sans spoil et légende sur UNE ligne
  main.innerHTML = `<div class="cutbar onel"><p class="greet"><i></i>La hiérarchie</p>
      ${cutPossible ? `<span>${cut ? "Arrêté avant la dernière nuit, pour ne rien te gâcher." : "À jour, dernière nuit comprise."}</span>
      <button class="sw ${cut ? "" : "on"}" id="swcut" role="switch" aria-checked="${!cut}"></button>
      <span>Inclure la dernière nuit</span>` : `<span>Classement à jour.</span>`}
      <span class="legend"><span><i style="background:#43c47a"></i>Play-offs</span><span><i style="background:#e7a33c"></i>Play-in</span></span></div>
    <div class="standwrap">${confs.map(confHTML).join("")}</div>`;
  const sw = $("#swcut");
  if (sw) sw.addEventListener("click", () => { state.cutLast = !state.cutLast; renderStandings(); });
}

/* ---------- réglages ---------- */
const setovl = $("#setovl"), setsheet = $("#setsheet");
function openSettings() {
  const picker = Object.keys(TEAMS).map(id => {
    const t = team(+id);
    return `<button class="tpk ${settings.fav === +id ? "on" : ""}" data-fav="${id}" style="--tc:${t.color}">${logoHTML(t)}<b>${t.name}</b></button>`;
  }).join("");
  setsheet.innerHTML = `<div class="setbody">
    <button class="x" aria-label="Fermer">✕</button>
    <h2>Réglages</h2>
    <div><h3>Mon équipe</h3><div class="tpick">${picker}</div>
      ${settings.fav ? `<p style="margin:10px 0 0"><button class="btn" id="nofav">Ne plus suivre d'équipe</button></p>` : ""}</div>
    <div><h3>Spoilers</h3>
      <div class="swrow"><p>Toujours montrer les scores<small>Pour ceux qui ne craignent pas le spoil : tout est révélé d'office.</small></p>
        <button class="sw ${settings.showAll ? "on" : ""}" id="swall" role="switch" aria-checked="${settings.showAll}"></button></div></div>
    <p style="color:var(--ink3);font-size:12.5px;margin:0">Ces réglages sont gardés sur cet appareil, sans compte ni cookie tiers.</p>
  </div>`;
  setovl.classList.add("open"); document.body.style.overflow = "hidden";
  setsheet.onclick = e => { // onclick (et non addEventListener) : la fiche se régénère à chaque ouverture
    const sw = e.target.closest("#swall");
    if (sw) {
      settings.showAll = !settings.showAll; store.set("showall", settings.showAll);
      sw.classList.toggle("on", settings.showAll); sw.setAttribute("aria-checked", settings.showAll);
      return;
    }
    const f = e.target.closest("[data-fav]");
    if (f) { settings.fav = +f.dataset.fav; store.set("fav", settings.fav); openSettings(); return; }
    if (e.target.closest("#nofav")) { settings.fav = null; store.set("fav", null); openSettings(); }
  };
}
function closeSettings() {
  setovl.classList.remove("open"); document.body.style.overflow = "";
  go(state.vue);
}

/* ---------- bande des nuits ---------- */
function renderChips() {
  const el = $("#nights");
  if (!el) return;
  const tonight = defaultNight();
  // seulement 3 nuits : celle d'avant, celle affichée, celle d'après ; le calendrier pour aller plus loin
  const keys = [addDays(state.night, -1), state.night, addDays(state.night, 1)];
  const live = state.games.some(g => g.state === "live");
  const cal = `<div class="chip calchip" id="calbtn" role="button" tabindex="0" title="Choisir une autre nuit"><small>Autre nuit</small><b><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="1"/><path d="M3 10h18M8 3v4M16 3v4"/></svg></b><input type="date" id="dpick" tabindex="-1" aria-label="Autre nuit" value="${state.night.slice(0, 4)}-${state.night.slice(4, 6)}-${state.night.slice(6, 8)}"></div>`;
  el.innerHTML = cal + keys.map(k => {
    const c = chipText(k);
    const cur = k === state.night;
    let dot = "";
    if (k === tonight && k === state.night && live) dot = `<span class="dot red"></span>`;
    else if (k < tonight && !seen.has(k)) dot = `<span class="dot gold"></span>`;
    // seule la dernière nuit (celle d'il y a quelques heures) et la suivante ont un nom ; la veille passe en « Retour sur la nuit »
    // comme les autres (« Nuit dernière » prêtait à confusion avec « Cette nuit »)
    const lab = k === tonight ? (EURO ? "Cette nuit" : "Ce soir") : k === addDays(tonight, 1) ? "Demain" : c.s;
    // le contexte (« Retour sur la nuit »…) seulement quand l'étiquette ne dit pas déjà « Cette nuit » ou « Demain »
    const ctxOn = cur && lab === c.s && el.dataset.ctx;
    return `<button class="chip ${cur ? "on" : ""}" data-night="${k}">${ctxOn ? `<em>${el.dataset.ctx}</em>` : ""}<small>${lab}</small><b>${c.b}</b>${dot}</button>`;
  }).join("");
  const dp = $("#dpick");
  // un <input> dans un <button> ne reçoit pas le clic (Firefox) et un champ date invisible n'ouvre pas son calendrier :
  // le bouton ouvre lui-même le sélecteur (showPicker), sinon donne le focus au champ
  const cb = $("#calbtn");
  const pick = () => { try { dp.showPicker(); } catch { dp.focus(); dp.click(); } };
  if (cb && dp) {
    cb.addEventListener("click", e => { if (e.target !== dp) pick(); });
    cb.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
  }
  if (dp) dp.addEventListener("change", () => { if (dp.value) { state.night = dp.value.replaceAll("-", ""); state.revealed.clear(); renderNight(); } });
}

/* ---------- navigation / adresse ---------- */
function setURL() {
  const p = new URLSearchParams();
  if (state.vue !== "nuit") p.set("vue", state.vue);
  if (state.vue === "nuit" && state.night !== defaultNight()) p.set("nuit", `${state.night.slice(0, 4)}-${state.night.slice(4, 6)}-${state.night.slice(6, 8)}`);
  if (DEMO) p.set("demo", "1");
  history.replaceState(null, "", location.pathname + (p.toString() ? "?" + p : ""));
}
function go(vue) {
  state.vue = vue;
  $$(".tab[data-vue]").forEach(t => t.classList.toggle("on", t.dataset.vue === vue));
  if (vue === "nuit") renderNight();
  else if (vue === "classement") renderStandings(); else renderProgramme();
  const m = $("#main"); // petite entrée en scène à chaque changement d'onglet
  if (m && !RM) { m.style.animation = "none"; void m.offsetWidth; m.style.animation = ""; }
  window.scrollTo({ top: 0, behavior: RM ? "auto" : "smooth" });
}

/* ---------- événements globaux ---------- */
document.addEventListener("click", e => {
  const sc = e.target.closest(".led.hid");
  if (sc) { reveal(sc.dataset.g); return; }
  const f = e.target.closest("[data-fiche]");
  if (f) { openFiche(f.dataset.fiche); return; }
  const rz = e.target.closest("[data-resume]");
  if (rz) { openResume(rz.dataset.resume); return; }
  const xz = e.target.closest("[data-extra]");
  if (xz) { openResume(xz.dataset.extra, true); return; }
  const vp = e.target.closest("[data-vplay]");
  if (vp) { playVideo(vp.dataset.vplay, vp.dataset.vlabel || "Vidéo"); return; }
  const rp = e.target.closest("[data-replay]");
  if (rp) { openShots(rp.dataset.replay); return; }
  const sh = e.target.closest("[data-shot]");
  if (sh) { openShots(sh.dataset.shot); return; }
  if (e.target.closest(".fsb") && vidovl.requestFullscreen) { vidovl.requestFullscreen().catch(() => {}); return; }
  if (e.target === vidovl || (e.target.closest(".x") && e.target.closest("#vidovl"))) { closeResume(); return; }
  if (e.target === shotovl || (e.target.closest(".x") && e.target.closest("#shotovl"))) { closeShots(); return; }
  if (e.target.closest("#gear") || e.target.closest("#gear2")) { openSettings(); return; }
  const tab = e.target.closest(".tab[data-vue]");
  if (tab) { go(tab.dataset.vue); return; }
  const pn = e.target.closest("[data-prog-night]");
  if (pn) { state.night = pn.dataset.progNight; state.revealed.clear(); go("nuit"); return; }
  const ng = e.target.closest("[data-night-go]");
  if (ng) { state.night = ng.dataset.nightGo; state.revealed.clear(); renderNight(); return; }
  const chip = e.target.closest(".chip[data-night]");
  if (chip && chip.dataset.night !== state.night) { state.night = chip.dataset.night; state.revealed.clear(); renderNight(); return; }
  const nav = e.target.closest("[data-nav]");
  if (nav && !e.target.closest("input")) { state.night = addDays(state.night, +nav.dataset.nav); state.revealed.clear(); renderNight(); return; }
  if (e.target === ovl || (e.target.closest(".x") && e.target.closest("#ovl"))) closeFiche();
  if (e.target === setovl || (e.target.closest(".x") && e.target.closest("#setovl"))) closeSettings();
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") {
    if (vidovl.classList.contains("open")) { closeResume(); return; }
    if (shotovl.classList.contains("open")) { closeShots(); return; }
    if (ovl.classList.contains("open")) closeFiche();
    if (setovl.classList.contains("open")) closeSettings();
  }
  if (e.key === "Enter" || e.key === " ") {
    const sc = e.target.closest && e.target.closest(".led.hid");
    if (sc) { e.preventDefault(); reveal(sc.dataset.g); }
  }
});
$("#brand").addEventListener("click", e => { e.preventDefault(); state.night = defaultNight(); state.revealed.clear(); go("nuit"); });

/* ---------- bandeau d'alerte & toast ---------- */
function alertBar(msg) { const a = $("#alertbar"); a.hidden = false; a.className = "alert"; a.textContent = msg; setTimeout(() => a.hidden = true, 8000); }
let tmr; function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("on"); clearTimeout(tmr); tmr = setTimeout(() => t.classList.remove("on"), 2600); }

/* ---------- bienvenue (première visite) ---------- */
function welcome() {
  if (store.get("hello", false)) return;
  const w = $("#welcome");
  w.hidden = false;
  w.innerHTML = `<div class="welcome"><p><b>Nouveau sur Nocturne ?</b> Aucun score ne s'allume tant que <b>tu</b> ne le demandes pas :
    touche un afficheur pour revivre ce match, et seulement celui-là.</p>
    <button class="btn amber" id="hellok">Compris</button></div>`;
  $("#hellok").addEventListener("click", () => { store.set("hello", true); w.hidden = true; });
}

/* ---------- démarrage ---------- */
(function init() {
  if (DEMO) $("#demopill").hidden = false;
  const nuit = QS.get("nuit");
  state.night = nuit && /^\d{4}-\d{2}-\d{2}$/.test(nuit) ? nuit.replaceAll("-", "") : defaultNight();
  welcome();
  loadVideos(); // en avance, pour que le premier clic « Résumé » soit instantané
  const vue = QS.get("vue");
  go(vue === "programme" ? "programme" : "nuit");
})();
