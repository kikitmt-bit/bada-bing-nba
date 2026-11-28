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
// fuseau : réglable (Paris / Montréal) dans les réglages, sinon celui de l'appareil. Il change les heures, les titres des nuits
// (« Nuit du … au … » à Paris, « Mercredi 21 » à Montréal) et les étiquettes (« Cette nuit » / « Ce soir »)
const TZ_AUTO = (Intl.DateTimeFormat().resolvedOptions().timeZone) || "Europe/Paris";
const TZ = store.get("tz", null) || TZ_AUTO;
const EURO = !/^America\//.test(TZ);
function nyKey(date) { // AAAAMMJJ à New York
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" })
    .format(date).replaceAll("-", "");
}
function defaultNight() { // la DERNIÈRE NUIT JOUÉE (ou en cours) : on recule de 18 h à New York, donc on passe à la nuit
  // suivante à 18 h (heure de NY, minuit à Paris), juste avant les premiers matchs (21/11, demande de Kiki : avant, à 8 h NY
  // soit 14 h à Paris, le site affichait déjà la nuit à venir, pas encore jouée)
  return nyKey(new Date(Date.now() - 18 * 3600e3));
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
  return new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" }).format(date).replace(":", "h");
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
  const note = ((comp.notes || [])[0] || {}).headline || "";
  g.cup = !/NBA Cup/i.test(note) ? null : /group/i.test(note) ? "group" : /quarter/i.test(note) ? "qf" : /semi/i.test(note) ? "sf" : /champion|final/i.test(note) ? "final" : null;
  g.city = (comp.venue && comp.venue.address && comp.venue.address.city) || "";
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
    if (c) { alertBar("ESPN ne répond pas : scores de " + new Date(c.t).toLocaleTimeString("fr-FR", { timeZone: TZ }) + "."); return c.games.map(g => pairColors({ ...g, date: new Date(g.date) })); }
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
          starter: !!a.starter, shots: [],
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
// la note fine d'un match terminé : calculée sur son déroulé ESPN (docs/note.js), gardée sur l'appareil (un match fini ne change plus)
const NOTE_KEY = "notes" + (typeof Note !== "undefined" ? Note.V : 0); // nouvelle version des règles = notes recalculées
const NOTES = store.get(NOTE_KEY, {});
const noteOf = g => g.state === "post" && typeof NOTES[g.id] === "number" ? NOTES[g.id] : null;
async function loadNotes(games) {
  if (DEMO || typeof Note === "undefined") return false;
  const todo = games.filter(g => g.state === "post" && noteOf(g) === null);
  if (!todo.length) return false;
  await Promise.all(todo.map(async g => {
    try {
      const j = await fetchJSON(API + "summary?event=" + g.id);
      const r = Note.rate(j); if (r) NOTES[g.id] = r.s;
      if (!SUMCACHE.has(g.id)) SUMCACHE.set(g.id, normSummary(j)); // déjà téléchargé : resservira (l'essentiel, la fiche)
    } catch (e) { /* ESPN muet : la note simple en attendant */ }
  }));
  const ks = Object.keys(NOTES); if (ks.length > 400) ks.slice(0, ks.length - 400).forEach(k => delete NOTES[k]);
  store.set(NOTE_KEY, NOTES);
  return true;
}
// pour trier : la note fine si on l'a, sinon le milieu de la tranche du niveau simple
function watchScore(g) {
  const n = noteOf(g); if (n !== null) return n;
  const C = typeof Note !== "undefined" ? Note.CUT : [0, 1.3, 3.0, 5.0, 7.2], l = watchLevel(g);
  const fin = g.state === "pre" ? afficheOf(g).s * .01 : 0; // entre deux affiches du même niveau : la plus hype d'abord
  return fin + (l === 0 ? C[0] - .5 : l >= 5 ? C[4] + .5 : (C[l - 1] + C[l]) / 2);
}
function watchLevel(g) {
  const nt = noteOf(g); if (nt !== null) return Note.level(nt);
  const pa = winpct(g.teams.away.record), ph = winpct(g.teams.home.record);
  if (g.state === "pre") return hypeLevel(g); // avant le match : la hype sur le papier (classement, stars, séries, rivalités)
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
/* hype d'avant-match (28/11, retour Kiki : Lakers-Spurs, 1er contre 2e de l'Ouest, Doncic contre Wembanyama, n'avait que 3 barres) :
   la jauge suit la note d'affiche (afficheOf), 5 barres = le choc de la saison ; ≥ 3,5 = 3 barres, comme le ◆ du programme */
const HYPE = [0.7, 2, 3.5, 5, 7];
const HYPL = ["Sans enjeu", "Discret", "Correct", "Belle affiche", "Grosse affiche", "Le choc"];
function hypeLevel(g) { const s = afficheOf(g).s; return HYPE.filter(x => s >= x).length; }
function hypeTip(g) { const w = afficheOf(g).why; return w.length ? ` title="${w.join(" · ").replace(/"/g, "&quot;")}"` : ""; }
const RAR = [
  ["nop", "⛔ À fuir"], ["low", "💤 Bof"], ["mid", "😐 Sans plus"],
  ["rar", "🔥 Sympa"], ["epi", "🔥🔥 Génial"], ["leg", "🔥🔥🔥 Immanquable"],
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
  // ce qui fait la hype (28/11, demande de Kiki : dire clairement pourquoi c'est un gros match) : classement, séries, rivalité.
  // Le classement ESPN est celui d'aujourd'hui : seulement AVANT le match (après, il contient le résultat)
  const R = g.state === "pre" && RANKS ? RANKS : null, ra = R && R.get(a.id), rh = R && R.get(h.id);
  if (ra && rh && Math.min(ra.gp, rh.gp) >= 8) {
    const conf = r => /east/i.test(r.conf) ? "de l'Est" : "de l'Ouest", ord = k => k === 1 ? "1er" : k + "e";
    const [x, y] = ra.rank <= rh.rank ? [ra, rh] : [rh, ra];
    if (ra.rank <= 3 && rh.rank <= 3) add(9.5, "niveau", "Choc au sommet", ra.conf === rh.conf
      ? `${ord(x.rank)} contre ${ord(y.rank)} ${conf(x)}` : `${ord(ra.rank)} ${conf(ra)} contre ${ord(rh.rank)} ${conf(rh)}`);
    else if (ra.conf === rh.conf && ra.rank <= 10 && rh.rank <= 10 && Math.abs(ra.rank - rh.rank) <= 2)
      add(7.5, "niveau", "Duel direct", `${ord(x.rank)} contre ${ord(y.rank)} ${conf(x)}`);
    else if (ra.rank <= 6 && rh.rank <= 6) add(7, "niveau", "Haut de tableau",
      `${ord(ra.rank)} ${conf(ra)} contre ${ord(rh.rank)} ${conf(rh)}`);
    const hot = [[ra, a], [rh, h]].filter(([r]) => r.streak >= 5).sort((u, v) => v[0].streak - u[0].streak)[0];
    if (hot) add(6.5, "serie", "En feu", `${hot[1].name} : ${hot[0].streak} victoires de suite`);
  }
  if (RIVAL.has([a.tri, h.tri].sort().join("-"))) add(6, "rival", "Rivalité", `${a.name} – ${h.name}, un classique de la NBA`);
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
  if (g.state === "post" && state.revealed.has(g.id) && MF.has(g.id)) return MF.get(g.id); // révélé : ce qui s'est passé
  return `<div class="kfs">${fs.map(f => `<div class="kf"><b>${f.t}</b><span>${f.x}</span></div>`).join("")}</div>`;
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
// le résumé de la nuit chapitré, préparé par le téléphone (v2/nuit/<nuit>.json) : chapitres reliés aux matchs,
// chrono lu chapitre par chapitre, joueur de la nuit lu à l'écran
const NUIT = {};
async function loadNuit(key) {
  // analyse pas finie (`fait` faux) : on relit le fichier toutes les 5 min, le « + » arrive tout seul
  if (DEMO || (key in NUIT && (!NUIT[key] || NUIT[key].fait || Date.now() - (NUIT[key]._at || 0) < 300e3))) return NUIT[key];
  try { NUIT[key] = await fetchJSON(RAWDATA + "nuit/" + key + ".json?t=" + Math.floor(Date.now() / 300e3)); if (NUIT[key]) NUIT[key]._at = Date.now(); } catch (e) { NUIT[key] = null; }
  return NUIT[key];
}
const nuitCh = (key, k) => { const N = NUIT[key]; return N && N.ch ? N.ch.find(c => c.k === k) || null : null; };
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
// la vidéo « NBA's Top 5 (ou 10) Plays of the Night | <date> » de la chaîne NBA
function findTopPlays(key) {
  if (!VIDS) return null;
  const md = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "long", day: "numeric" }).format(keyDate(key)).toLowerCase();
  return VIDS.find(v => v.c === "nba" && /top (5|10) plays of the night/.test(norm(v.t)) && norm(v.t).includes(md + ",")) || null;
}
function openNightPlus(key, solo) {
  if (solo === "top") { // la vraie vidéo du top de la nuit, en plein écran
    const v = findTopPlays(key);
    if (v) { playVideo(v.id, "Les plus belles actions de la nuit", null, { fs: true }); return; }
  }
  const N = NUIT[key]; if (!N) return;
  const c = solo ? N.ch.find(x => x.k === solo) : null;
  if (solo && !c) return;
  playVideo(N.v, solo === "potn" ? `${c.n || "Le joueur de la nuit"} · ses meilleures actions` : solo === "top" ? "Les plus belles actions de la nuit" : "Le résumé de la nuit NBA",
    null, c ? { start: c.s, end: c.e, fs: true } : { night: N }); // extrait seul (depuis l'essentiel) : la vidéo, sans stats (choix de Kiki)
}
function playVideo(vid, label, gid, opts) { // lecteur intégré, sans quitter le site ; opts : { start, end } (un extrait), { night } (résumé de la nuit +)
  // beIN SPORTS interdit la lecture de ses vidéos hors de YouTube (« Vidéo non disponible ») : NBA Extra s'ouvre sur YouTube.
  if (VIDS && VIDS.some(v => v.id === vid && v.c === "bein")) {
    window.open("https://www.youtube.com/watch?v=" + vid, "_blank", "noopener"); return;
  }
  opts = opts || {};
  const night = opts.night && typeof Chrono !== "undefined" ? opts.night : null;
  const live = (gid || night) && typeof Chrono !== "undefined"; // stats en direct à côté du résumé (le panneau se retire s'il n'a rien à montrer)
  const cut = (opts.start ? "&start=" + Math.floor(opts.start) : "") + (opts.end ? "&end=" + Math.ceil(opts.end) : "");
  const frame = vid ? `<iframe src="https://www.youtube.com/embed/${vid}?autoplay=1&rel=0&hl=fr${cut}${live || opts.fs ? "&enablejsapi=1&origin=" + encodeURIComponent(location.origin) : ""}"
      title="${label}" allow="autoplay; fullscreen; encrypted-media" allowfullscreen></iframe>`
    : `<div class="vdemo">Démo : la vidéo YouTube serait ici</div>`;
  const full = live && (night || Chrono.wantsFull(vid)); // plein écran d'office quand il y aura des stats (plus immersif, place dessous)
  vplayer.classList.toggle("live", !!live); vplayer.classList.toggle("full", !!full); vidovl.classList.toggle("full", !!full);
  vplayer.classList.toggle("nightp", !!night); vplayer.classList.toggle("solo", !!(night && opts.solo));
  vplayer.innerHTML = `
    <button class="x" aria-label="Fermer">✕</button>
    ${full && vidovl.requestFullscreen ? `<button class="fsb" aria-label="Plein écran" title="Remettre en plein écran"><svg viewBox="0 0 24 24"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/></svg></button>` : ""}
    <div class="vmain"><div class="vframe">${frame}</div>
    <div class="vfoot"><span>${opts.labHTML || label}</span>
      ${vid ? `<a href="https://www.youtube.com/watch?v=${vid}" target="_blank" rel="noopener">Ouvrir sur YouTube ↗</a>` : ""}</div></div>
    ${night && opts.solo ? `<aside class="nps" id="npside"></aside><section class="lv-below" id="lvbelow"></section>`
      : night ? `<aside class="np" id="nplist"></aside><section class="lv-below" id="lvbelow"></section>`
      : live ? `<aside class="lv" id="lvpanel"></aside><section class="lv-below" id="lvbelow"></section>` : ""}`;
  vidovl.classList.add("open"); document.body.style.overflow = "hidden"; document.body.classList.add("vidon");
  if (full && vidovl.requestFullscreen && !document.fullscreenElement) vidovl.requestFullscreen().catch(() => {}); // pendant le clic : le navigateur l'exige
  // extraits de l'essentiel (top de la nuit, actions du MVP) : la vidéo seule, directement en plein écran (demande de Kiki)
  const vf = vplayer.querySelector(".vframe");
  if (opts.fs && vf && vf.requestFullscreen && !document.fullscreenElement) vf.requestFullscreen().catch(() => {});
  if (opts.fs && vf) { const f = vf.querySelector("iframe"); // lecture lancée d'office (au cas où le navigateur ignore autoplay)
    if (f) f.addEventListener("load", () => setTimeout(() => f.contentWindow && f.contentWindow.postMessage(JSON.stringify({ event: "command", func: "playVideo", args: [], id: 1, channel: "widget" }), "*"), 600)); }
  if (night) Chrono.attachNight(night, $("#nplist"), vplayer.querySelector(".vframe"), $("#lvbelow"), { solo: opts.solo, side: $("#npside") });
  else if (live) Chrono.attach(gid, $("#lvpanel"), vplayer.querySelector(".vframe"), vid, $("#lvbelow"));
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
  const lab = `${g.teams.away.name} – ${g.teams.home.name} · ${extra ? "Replay FR (NBA Extra)" : v.c === "gt" ? "replay GameTime" : "replay NBA"}`;
  // la légende du film du match passe dans le bandeau sous la vidéo : ■ Nuggets ■ Bulls · replay GameTime
  const sq = t => `<i class="vleg" style="--mc:${t.color}"></i>${t.name}`;
  const labHTML = extra ? null : `${sq(g.teams.away)}${sq(g.teams.home)}<em>·</em>${v.c === "gt" ? "replay GameTime" : "replay NBA"}`;
  playVideo(v.id, lab, extra ? null : g.id, labHTML ? { labHTML } : undefined);
}
// après Échap, le bouton « plein écran » réapparaît (seulement hors plein écran)
document.addEventListener("fullscreenchange", () => vplayer.classList.toggle("fs", document.fullscreenElement === vidovl));
function closeResume() {
  if (typeof Chrono !== "undefined") Chrono.close();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  vplayer.innerHTML = ""; vplayer.classList.remove("full", "nightp", "solo"); vidovl.classList.remove("open", "full"); document.body.style.overflow = ""; document.body.classList.remove("vidon");
}

/* ---------- briques d'affichage ---------- */
const RARL = ["À fuir", "Bof", "Sans plus", "Sympa", "Génial", "Immanquable"];
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
      <div class="jtop"><span></span>
        <span class="when r${lvl}"${pre ? hypeTip(g) : ""}>${heatHTML(lvl)}<span>${pre ? `${HYPL[lvl]} · ${hourLocal(g.date)}` : RARL[lvl]}</span></span></div>
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
      <div class="bh">${clockHTML(g)}${fav ? `<span class="fav">★</span>` : ""}<span class="hyp"${pre ? hypeTip(g) : ""}>${heatHTML(lvl)}<span class="hl">${pre ? HYPL[lvl] : RARL[lvl]}</span></span></div>
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
  setFacts(g);
  if (fx && !RM) {
    if (wside) for (const r of $$(`[data-row="${g.id}:${wside}"]`)) { r.classList.remove("won"); void r.offsetWidth; r.classList.add("won"); }
    const lvl = watchLevel(g);
    if (lvl >= 4) particles($(`[data-card="${g.id}"]`), lvl === 5);
  }
  updateRevealAll();
}
function reveal(id, instant, quick) {
  const g = state.games.find(x => x.id === id);
  if (!g || g.state === "pre") return;
  const first = !state.revealed.has(id);
  state.revealed.add(id);
  const cells = $$(`.led[data-g="${id}"]`);
  const la = g.teams.away.ls || [], lh = g.teams.home.ls || [];
  const canRace = first && !instant && !quick && !RM && g.state === "post" && la.length >= 4 && lh.length >= 4;
  if (!canRace) {
    if (first && !instant && !RM) {
      cells.forEach(c => { c.classList.remove("hid"); c.classList.add("flash"); countUp(c.querySelector(".v"), g.teams[c.dataset.side].score, quick ? 600 : 650); });
      setTimeout(() => finishReveal(g, !quick), quick ? 650 : 700);
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
  const left = state.games.filter(g => g.state !== "pre" && !state.revealed.has(g.id)).length;
  if (!left && state.games.some(g => g.state === "post")) revealEss();
}
/* ---------- UN SEUL bouton pour tout le site (28/11, idée de Kiki) : « Révéler la nuit », dans la barre du haut ----------
   Il dévoile tout ce qui est joué jusqu'à la dernière nuit : les scores et les faits de toutes les nuits, l'essentiel,
   la NBA Cup, le classement à jour. Un 2e appui recache tout. Gardé le temps de la visite seulement (comme les scores). */
const MBSVG = `<svg class="mb" viewBox="0 0 64 64" aria-hidden="true"><use href="#moonball"/></svg>`;
function paintRev() {
  const b = $("#revall"); if (!b) return;
  const on = !!(settings.showAll || state.allOpen);
  const d1 = keyDate(defaultNight()), d2 = keyDate(addDays(defaultNight(), 1));
  const nt = EURO ? `${d1.getUTCDate()} → ${d2.getUTCDate()}` : FR({ day: "numeric", month: "short" }).format(d1);
  b.hidden = false;
  b.classList.toggle("done", on);
  b.disabled = !!settings.showAll;
  b.title = settings.showAll ? "Les scores sont toujours montrés (réglage « Toujours montrer les scores »)"
    : on ? "Toucher pour tout recacher" : `Dévoile tous les résultats jusqu'à la nuit du ${nt} : scores, NBA Cup, classement`;
  b.setAttribute("aria-label", b.title);
  // libellé parlant (28/11, Kiki) : long sur PC, court sur téléphone (.rl / .rs ; pas .lg = les logos)
  b.innerHTML = on ? `<span class="rl">✓ Résultats révélés</span><span class="rs">✓ Révélé</span>${settings.showAll ? "" : `<small class="rc">· recacher</small>`}`
    : `<span class="rl">Révéler tous les résultats</span><span class="rs">Tout révéler</span>`;
}
function toggleRevealAll() {
  if (settings.showAll) return;
  state.allOpen = !state.allOpen;
  if (!state.allOpen) { state.revealed.clear(); state.essOpen = null; }
  paintRev();
  if (state.vue === "nuit") {
    if (!state.allOpen) { renderNight(true); return; }
    // la cérémonie : du moins bon au meilleur, le match de la nuit en dernier ; tous les scores s'allument en moins d'une seconde
    let order = state.games.filter(g => g.state !== "pre" && !state.revealed.has(g.id)).sort((x, y) => watchScore(x) - watchScore(y));
    order = order.filter(g => g.id !== state.heroId).concat(order.filter(g => g.id === state.heroId));
    order.forEach((g, i) => setTimeout(() => reveal(g.id, false, true), RM ? 0 : i * 60));
    if (!order.length) revealEss();
  } else if (state.vue === "cup") renderCup();
  else if (state.vue === "classement") renderStandings();
}

/* ---------- le brief : la nuit, comme une retransmission ---------- */
function greeting() {
  const hr = +new Intl.DateTimeFormat("fr-FR", { timeZone: TZ, hour: "numeric", hourCycle: "h23" }).format(new Date());
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
  // « + » seulement quand le téléphone a fini toute la vidéo (`fait`) ; avant, le résumé de la nuit tout court (26/11, Kiki)
  const NN = NUIT[state.night], nplus = started && NN && NN.fait && NN.ch && NN.ch.some(c => c.k === "match");
  const nvid = nr ? nr.id : started && NN && NN.v;
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
      ${started || nvid || jr || nplus ? `<div class="actions">
      ${nplus ? `<button class="btn amber" data-nuitplus="${state.night}" title="Le résumé de la nuit, avec la liste des matchs et les scores qui suivent la vidéo"><span class="pl">▶</span>Résumé de la nuit<span class="plus">+</span></button>`
        : nvid ? `<button class="btn amber" data-vplay="${nvid}" data-vlabel="Le résumé de la nuit NBA"><span class="pl">▶</span>Résumé de la nuit</button>` : ""}
      ${jr ? `<button class="btn amber" data-vplay="${jr.id}" data-vlabel="NBA Extra · le journal du matin"><span class="pl">▶</span>NBA Extra</button>` : ""}
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
  if (settings.showAll || state.allOpen) games.forEach(g => { if (g.state !== "pre") state.revealed.add(g.id); });
  if (games.some(g => g.state !== "pre")) markSeen(state.night);
  // pour les infos clés : « 2e soir », blessés (avant le match), photo d'avant-match (après)
  await Promise.all([loadPrevNight(state.night), games.some(g => g.state === "pre") ? loadInjuries() : null,
    games.some(g => g.state === "pre") ? loadRanks() : null,
    games.some(g => g.state !== "pre") ? loadAvant(state.night) : null, games.some(g => g.state === "post") ? loadNuit(state.night) : null]);
  if (tok !== state.tok) return;

  // la note fine des matchs terminés (déroulé ESPN) : on l'attend 2,5 s au plus, sinon la page se remet en ordre à son arrivée
  const notes = loadNotes(games);
  const late = await Promise.race([notes.then(() => false), new Promise(r => setTimeout(() => r(true), 2500))]);
  if (tok !== state.tok) return;
  if (late) notes.then(ch => { if (ch && tok === state.tok && !document.body.classList.contains("vidon")) renderNight(true); });
  const scored = games.map(g => ({ g, lvl: watchLevel(g), s: watchScore(g) })).sort((x, y) => y.s - x.s || jitter(x.g.id) - jitter(y.g.id));
  const hero = scored.length && scored[0].lvl >= 4 ? scored[0] : null;
  state.heroId = hero ? hero.g.id : null;
  const isFav = g => settings.fav && (g.teams.away.id === settings.fav || g.teams.home.id === settings.fav) ? 1 : 0;
  const rest = games.filter(g => !hero || g.id !== hero.g.id)
    .sort((x, y) => isFav(y) - isFav(x) || watchScore(y) - watchScore(x) || x.date - y.date);
  const nPost = games.filter(g => g.state === "post").length;

  main.innerHTML = `${skyHTML(games, hero, scored)}
    ${!games.length ? `<p class="loadmsg">Pas de match cette nuit-là. Les joueurs dorment aussi. 🌙</p>` : ""}
    ${hero ? sect(hero.g.state === "pre" ? "L'affiche de la nuit" : "Le match de la nuit") + heroHTML(hero.g, hero.lvl) : ""}
    ${rest.length ? sect(hero ? "Les autres matchs" : "Les matchs de la nuit") + `
    <div class="bugs">${rest.map((g, i) => cardHTML(g, i)).join("")}</div>` : ""}
    ${nPost >= 2 ? `<div id="mvpbody"><div class="ess hide">${sect("Le MVP et les grosses perfs")}
      <div class="skel"><div class="ph" style="height:220px"></div></div></div></div>` : ""}
    <div id="nextstrip"></div>`;

  for (const id of state.revealed) reveal(id, true);
  for (const v of $$("[data-count]")) countUp(v, +v.dataset.count, 900);
  startCountdown();
  if (nPost >= 2) loadEss();
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
// le nom dans une ligne de fait : en entier s'il est court, sinon « S. Gilgeous-Alexander » (une ligne, jamais coupée)
const nm = p => { const f = (p.full || p.name || "").trim(); return f.length <= 15 ? f : (p.name || f); };
function gameFacts(g, s) { // les faits d'un match terminé (c = le texte court pour la tuile du match)
  const F = [];
  const A = g.teams.away, H = g.teams.home, aw = A.score > H.score, W = aw ? A : H, L = aw ? H : A, m = Math.abs(A.score - H.score);
  const base = { g, aw };
  // la surprise : le moins bon bilan d'avant-match l'emporte nettement
  const ra = moins(A.record, aw), rh = moins(H.record, !aw), rw = aw ? ra : rh, rl = aw ? rh : ra;
  if (Math.min(played(ra), played(rh)) >= 6 && winpct(rl) - winpct(rw) >= .2)
    F.push({ ...base, p: 7 + (winpct(rl) - winpct(rw)) * 6, k: "surprise", tag: "La surprise", t: `Exploit ${du(W)} face ${au(L)}`, c: `Exploit ${du(W)} (${rw} contre ${rl} avant le match)` });
  const nOt = s.quarters ? s.quarters.home.q.length - 4 : 1;
  if (s.ot) F.push({ ...base, p: 9, k: "fin", tag: "Prolongation", t: `${A.name} – ${H.name} en prolongation`, c: nOt > 1 ? `${nOt} prolongations pour se départager` : "Il a fallu une prolongation" });
  else if (m <= 3) F.push({ ...base, p: 8, k: "fin", tag: "Le thriller", t: `Décidé à ${plural(m, "point")}`, c: `Décidé à ${plural(m, "point")}, jusqu'au bout` });
  // la remontée : le vainqueur a été mené de 15 points ou plus (écart après chaque panier, + = domicile devant)
  if (s.series && s.series.length) {
    const dv = s.series.map(p => Array.isArray(p) ? p[1] : p);
    const deficit = aw ? Math.max(...dv) : -Math.min(...dv);
    if (deficit >= 15) F.push({ ...base, p: 7 + deficit / 10, k: "remontee", tag: "La remontée", t: `Remontée de ${deficit} points pour ${le(W)}`, c: `${cap1(le(W))} ${SING.has(W.name) ? "revient" : "reviennent"} de ${deficit} points` });
  }
  if (m >= 25) F.push({ ...base, p: 4 + m / 20, k: "raclee", tag: "La démonstration", t: `Victoire ${du(W)} avec ${m} points d'écart`, c: `${m} points d'écart, sans appel` });
  // les perfs individuelles
  for (const pl of s.players || []) {
    const t3 = +((pl.tp || "").split("-")[0]) || 0, nom = pl.full || pl.name, nc = nm(pl);
    if (pl.pts >= 40) F.push({ ...base, p: 9 + (pl.pts - 40) / 4, k: "perf", tag: "La perf", t: `${pl.pts} points pour ${nom}`, c: `${nc} : ${pl.pts} pts · ${pl.reb} reb · ${pl.ast} pd`, pl });
    else if (pl.pts >= 10 && pl.reb >= 10 && pl.ast >= 10) F.push({ ...base, p: 8, k: "perf", tag: "Triple-double", t: `Triple-double de ${nom}`, c: `${nc} : ${pl.pts} pts · ${pl.reb} reb · ${pl.ast} pd`, pl });
    else if (t3 >= 8) F.push({ ...base, p: 7, k: "perf", tag: "Adresse folle", t: `${t3} paniers à 3 points pour ${nom}`, c: `${nc} : ${t3} paniers à 3 pts, ${pl.pts} pts`, pl });
  }
  return F;
}
/* les 3 faits d'un match, qui remplacent ses 3 infos d'avant-match une fois le score révélé (28/11, demande de Kiki ;
   remplace la rubrique « Les faits marquants » de l'essentiel) */
function matchFacts(g, s, extra) {
  const A = g.teams.away, H = g.teams.home, aw = A.score > H.score, W = aw ? A : H, L = aw ? H : A, m = Math.abs(A.score - H.score);
  const F = gameFacts(g, s).concat((extra || []).filter(f => f.g.id === g.id));
  const named = new Set(F.filter(f => f.pl).map(f => f.pl.aid));
  const best = tid => s.players.filter(p => p.tid === tid).sort((a, b) => gscore(b) - gscore(a))[0];
  const line = p => `${nm(p)} : ${p.pts} pts · ${p.reb} reb · ${p.ast} pd`;
  const bw = best(W.id), bl = best(L.id);
  if (bw && !named.has(bw.aid)) F.push({ p: 5, k: "patron", tag: "Le patron", c: line(bw) });
  const la = A.ls || [], lh = H.ls || []; // le quart-temps qui a fait la différence
  let bq = -1, bd = 0;
  for (let q = 0; q < Math.min(la.length, lh.length); q++) { const d = aw ? la[q] - lh[q] : lh[q] - la[q]; if (d > bd) { bd = d; bq = q; } }
  if (bq >= 0 && bd >= 7) F.push({ p: 4.5, k: "tournant", tag: "Le tournant",
    c: `${bq >= 4 ? "La prolongation" : (bq === 0 ? "1er" : bq + 1 + "e") + " quart-temps"} : ${Math.max(la[bq], lh[bq])}-${Math.min(la[bq], lh[bq])} pour ${le(W)}` });
  if (bl && !named.has(bl.aid)) F.push({ p: 3, k: "enface", tag: "En face", c: line(bl) });
  if (!F.some(f => f.k === "fin" || f.k === "raclee"))
    F.push({ p: 2, k: "ecart", tag: m >= 12 ? "Sans trembler" : "La victoire", c: `${cap1(le(W))} ${SING.has(W.name) ? "s'impose" : "s'imposent"} de ${plural(m, "point")}` });
  F.sort((a, b) => b.p - a.p);
  const out = [], kinds = new Map();
  for (const f of F) { if ((kinds.get(f.k) || 0) >= (f.k === "perf" ? 2 : 1)) continue; kinds.set(f.k, (kinds.get(f.k) || 0) + 1); out.push(f); if (out.length === 3) break; }
  return out;
}
const MF = new Map(); // id du match -> les 3 faits (HTML), une fois calculés
async function setFacts(g) {
  if (g.state !== "post") return;
  if (!MF.has(g.id)) {
    let sm = null; try { sm = await cachedSummary(g.id); } catch (e) { /* ESPN muet : on garde l'avant-match */ }
    if (!sm || !sm.players.length) return;
    const ex = await nightExtras().catch(() => []);
    MF.set(g.id, `<div class="kfs post">${matchFacts(g, sm, ex).map(f => `<div class="kf"><b>${f.tag}</b><span>${f.c || f.t}</span></div>`).join("")}</div>`);
  }
  if (!state.revealed.has(g.id)) return;
  for (const el of $$(`[data-card="${g.id}"] .kfs`)) el.outerHTML = MF.get(g.id);
}
// les blessés sortis pendant la nuit et ce qui a bougé au classement (rangés ensuite avec le match concerné)
let EXN = null, EXK = "";
function nightExtras() {
  const posts = state.games.filter(g => g.state === "post"), key = state.night + ":" + posts.length;
  if (EXN && EXK === key) return EXN;
  EXK = key;
  return (EXN = (async () => {
    const sums = await Promise.all(posts.map(g => cachedSummary(g.id).catch(() => null)));
    const isLast = state.night === defaultNight();
    const [moves] = await Promise.all([isLast && !DEMO ? standingMoves(posts).catch(() => []) : [], posts.some(g => AVANT[g.id]) ? loadInjuries() : null]);
    const extra = [];
    const vb = (t, one, many) => SING.has(t.name) ? one : many;
    if (INJ) posts.forEach((g, i) => {
      const ph = AVANT[g.id], sm = sums[i]; if (!ph || !sm) return;
      for (const [side, T] of [["a", g.teams.away], ["h", g.teams.home]]) {
        const before = new Set(((ph[side] && ph[side].out) || []).map(o => o.n));
        for (const o of INJ[T.id] || []) {
          if (before.has(o.n) || !/out|day|question/i.test(o.st)) continue;
          // seulement un joueur qui compte : titulaire, ou vraies minutes / vrais points ce soir-là (pas le bout de banc)
          const pl = sm.players.find(p => p.tid === T.id && (p.name === o.n || p.full === o.n));
          const mins = pl ? parseInt(pl.min, 10) || 0 : 0;
          if (!pl || !(pl.starter || mins >= 18 || pl.pts >= 10)) continue;
          const out = /^out$/i.test(o.st);
          extra.push({ g, p: 6 + (pl.starter ? 1 : 0) + (out ? .5 : 0), k: "blesse", tag: "Sorti blessé",
            c: `${nm(pl)} · ${o.ty ? blessFr(o.ty) : "blessure"} · ${out ? "forfait" : "incertain"}` });
        }
      }
    });
    for (const m of moves) {
      const T = team(m.id), g = posts.find(x => x.teams.away.id === m.id || x.teams.home.id === m.id); if (!g) continue;
      const up = m.a < m.b, n = Math.abs(m.a - m.b);
      const t = m.crossed === "prend la tête" ? `${cap1(le(T))} ${vb(T, "prend", "prennent")} la tête de l'${m.conf}`
        : m.crossed ? `${cap1(le(T))} ${m.crossed.startsWith("entre") ? vb(T, "entre", "entrent") : vb(T, "sort", "sortent")} ${m.crossed.replace(/^(entre|sort) /, "")}`
        : `${cap1(le(T))} ${up ? vb(T, "gagne", "gagnent") : vb(T, "perd", "perdent")} ${plural(n, "place")}`;
      extra.push({ g, p: 4 + m.sc / 15, k: "classement", tag: "Au classement", c: m.crossed ? t : `${t} (${m.a + 1}e à l'${m.conf})` });
    }
    return extra;
  })());
}
// les Français : lieu de naissance des effectifs ESPN (gardé une semaine sur l'appareil)
async function frenchPlayers(teamIds) { // id -> { n: nom, tid: équipe }
  const c = store.get("fr2", null), fresh = c && Date.now() - c.t < 7 * 864e5 ? c : { t: Date.now(), teams: {} };
  const miss = teamIds.filter(id => !(id in fresh.teams));
  await Promise.all(miss.map(async id => {
    try {
      const j = await fetchJSON(API + "teams/" + id + "/roster");
      fresh.teams[id] = (j.athletes || []).filter(a => /france/i.test((a.birthPlace && a.birthPlace.country) || "") || /france|french/i.test(a.citizenship || "")).map(a => ({ id: String(a.id), n: a.displayName || a.fullName || "" }));
    } catch (e) { /* tant pis pour cette équipe */ }
  }));
  if (miss.length) store.set("fr2", fresh);
  const m = new Map();
  for (const id of teamIds) for (const a of fresh.teams[id] || []) m.set(a.id, { n: a.n, tid: +id });
  return m;
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
/* L'essentiel (28/11, demande de Kiki) : plus de bouton « Voir l'essentiel », tout est déjà en place à l'écran, mais masqué
   (« ? » à la place de la photo du MVP et des grosses perfs, « ?? » à la place des stats) jusqu'à « Révéler la nuit »
   ou « Révéler l'essentiel ». Les Français sont connus d'avance (effectifs) : photo, nom et adversaire visibles, stats masquées.
   x-h = ce qu'on voit avant, x-r = ce qu'on voit après (CSS .ess.hide). */
const hr = (h, r) => `<x-h>${h}</x-h><x-r>${r}</x-r>`;
// un titre de rubrique : petit, gris, avec un trait (le même partout, demande de Kiki 28/11) ; `after` = un bouton juste après le titre
const sect = (t, after) => `<div class="sect"><h2>${t}</h2>${after || ""}</div>`;
function revealEss() {
  const e = $("#mvpbody .ess"); state.essOpen = state.night;
  if (!e || !e.classList.contains("hide") || !e.dataset.ready) return;
  e.classList.remove("hide");
  for (const v of e.querySelectorAll("[data-count]")) countUp(v, +v.dataset.count, 1100);
}
async function loadEss() {
  const tok = state.tok, night = state.night;
  const posts = state.games.filter(g => g.state === "post");
  const sums = await Promise.all(posts.map(g => cachedSummary(g.id).catch(() => null)));
  await loadVideos(); // pour le bouton du top de la nuit (5 ou 10 actions selon la vidéo de la NBA)
  const teamIds = [...new Set(posts.flatMap(g => [g.teams.away.id, g.teams.home.id]))];
  const frMap = DEMO ? new Map() : await frenchPlayers(teamIds).catch(() => new Map());
  if (tok !== state.tok || night !== state.night) return;
  const body = $("#mvpbody"); if (!body) return;
  const all = [];
  sums.forEach((s, i) => { if (s) for (const p of s.players) all.push({ ...p, g: posts[i] }); });
  if (!all.length) { body.innerHTML = `<div class="ess">${sect("L'essentiel de la nuit")}<p class="essn pad">L'essentiel arrive dès que les feuilles de match sont disponibles.</p></div>`; return; }
  all.sort((a, b) => gscore(b) - gscore(a));
  // le MVP = le « Player of the Night » choisi par la NBA dans son résumé de la nuit (lu à l'écran par le téléphone),
  // sinon notre calcul (meilleur « game score »)
  const N = NUIT[night], potn = nuitCh(night, "potn"), top = nuitCh(night, "top");
  const pi = potn && potn.aid ? all.findIndex(p => p.aid === potn.aid) : -1;
  if (pi > 0) all.unshift(all.splice(pi, 1)[0]);
  const mvp = all[0], t = team(mvp.tid);
  const mvpPlay = pi >= 0 && N ? `<button class="btn amber mvplay" data-nuitsolo="potn" data-night="${night}"><span class="pl">▶</span>Ses meilleures actions</button>` : "";
  // les plus belles actions : une rubrique à part, titre + bouton « ▶ Top 10 » (ou 5) (demande de Kiki 28/11)
  const topV = findTopPlays(night), topN = topV ? (/top 10/i.test(topV.t) ? 10 : 5) : top && top.plays && top.plays.length;
  // titre + bouton « ▶ Top 10 » (28/11). Visuel avec les joueurs seulement quand le téléphone saura les reconnaître À COUP SÛR
  const nT = topN || 5;
  const cta = topV || (top && N) ? sect(`Les ${nT} plus belles actions de la nuit`,
    `<button class="btn amber" data-nuitsolo="top" data-night="${night}"><span class="pl">▶</span>Top ${nT}</button>`) : "";
  const opp = mvp.g.teams.away.id === mvp.tid ? mvp.g.teams.home : mvp.g.teams.away;
  const face = (aid, lazy, cl) => /^\d+$/.test(aid) && !DEMO ? `<img${cl ? ` class="${cl}"` : ""} src="https://a.espncdn.com/i/headshots/nba/players/full/${aid}.png" alt=""${lazy ? ' loading="lazy"' : ""} onerror="this.remove()">` : "";
  const stat = (v, l) => `<div class="stat">${hr(`<span class="led off"><span class="v">?</span></span>`, `<span class="led"><span class="v" data-count="${v}">0</span></span>`)}<small>${l}</small></div>`;
  const full = (mvp.full || mvp.name).trim(), sp = full.indexOf(" ");
  const nameHTML = sp > 0 ? `<span>${full.slice(0, sp)}</span><span>${full.slice(sp + 1)}</span>` : `<span>${full}</span>`;
  const qm = `<span class="qm">?</span>`;
  const mvpBlock = `<div class="mvpw"><div class="mvp">
      <div class="card" style="--tc:${t.color}">${hr(qm, face(mvp.aid, false, "mph") + logoHTML(t))}</div>
      <div style="min-width:0">
        <h3>${hr("", nameHTML)}</h3>
        <div class="sub">${hr("MVP de la nuit", `${t.city} ${t.name} · contre ${le(opp)}`)}</div>
        ${mvpPlay ? `<x-r>${mvpPlay}</x-r>` : ""}
        <div class="row">${stat(mvp.pts, "points")}${stat(mvp.reb, "rebonds")}${stat(mvp.ast, "passes")}${stat(mvp.blk || 0, "contres")}</div>
      </div></div>
    <div class="perfs"><span class="tag ghost">Les grosses perfs</span>${all.slice(1, 7).map((p, i) => {
      const pt = team(p.tid);
      return `<div class="perf" style="--tc:${pt.color};animation-delay:${200 + i * 70}ms"><span class="slab">${hr(qm, logoHTML(pt))}</span>
        <b>${hr(`Grosse perf n° ${i + 2}`, p.full || p.name)}</b><small>${hr("", `${p.pts} PTS · ${p.reb} REB · ${p.ast} PAS${p.blk >= 3 ? ` · ${p.blk} CTR` : ""}`)}</small></div>`;
    }).join("")}</div></div>`;
  // les Français : connus d'avance (effectifs des équipes de la nuit) ; un MVP français est déjà en vedette au-dessus
  const mvpFr = frMap.has(mvp.aid);
  const frs = [...frMap].map(([aid, f]) => {
    const g = posts.find(x => x.teams.away.id === f.tid || x.teams.home.id === f.tid); if (!g) return null;
    const p = all.find(x => x.aid === aid);
    return { aid, n: (p && (p.full || p.name)) || f.n, tid: f.tid, g, p };
  }).filter(Boolean).sort((a, b) => a.n.localeCompare(b.n));
  const rank = new Map([...frs].filter(f => f.p).sort((a, b) => gscore(b.p) - gscore(a.p)).map((f, i) => [f.aid, i]));
  const nFr = frs.length - (mvpFr ? 1 : 0);
  const frCols = n => n <= 5 ? Math.max(1, n) : n === 6 ? 3 : 4; // 1 à 5 sur une ligne, 6 = 2 × 3, puis 4 par ligne
  const frBlock = `${sect(mvpFr ? hr("Les Français de la nuit", "Les autres Français de la nuit") : "Les Français de la nuit")}${frs.length ? `<div class="frg" style="--n:${frCols(frs.length)};--nr:${frCols(nFr)}">${frs.map((f, i) => {
      const pt = team(f.tid), og = f.g.teams.away.id === f.tid ? f.g.teams.home : f.g.teams.away, p = f.p;
      const real = p ? `<span class="frs"><b>${p.pts}</b><small>pts</small><b>${p.reb}</b><small>reb</small><b>${p.ast}</b><small>pd</small>${p.blk ? `<b>${p.blk}</b><small>ctr</small>` : ""}<small class="frm">· ${p.min} min</small></span>`
        : `<span class="frs"><small>N'a pas joué</small></span>`;
      return `<div class="frt${f.aid === mvp.aid ? " ismvp" : ""}" style="--tc:${pt.color};--o:${rank.has(f.aid) ? rank.get(f.aid) : 99};animation-delay:${i * 60}ms"><span class="frp">${face(f.aid, true)}${logoHTML(pt)}</span>
        <span class="frn"><b>${f.n}</b><small>${pt.tri} contre ${og.tri}</small>
        ${hr("", real)}</span></div>`;
    }).join("")}</div>` : `<p class="essn pad">Aucun Français sur les parquets cette nuit.</p>`}`;
  const open = settings.showAll || state.essOpen === night || !state.games.some(g => g.state !== "pre" && !state.revealed.has(g.id));
  body.innerHTML = `<div class="ess hide" data-ready="1">${sect("Le MVP et les grosses perfs")}${mvpBlock}${frBlock}${cta}</div>`;
  if (open) revealEss();
}

/* la nuit prochaine, en un clin d'œil */
async function nextStrip() {
  const el = $("#nextstrip"); if (!el || state.night !== defaultNight()) return;
  const next = addDays(state.night, 1);
  let games;
  try { [games] = await Promise.all([scoreboard(next), loadRanks()]); } catch (e) { return; }
  const pre = games.filter(g => g.state === "pre");
  if (!pre.length || state.night !== defaultNight() || !$("#nextstrip")) return;
  // 28/11 (Kiki) : une rubrique comme les autres, le plus sobre possible : les affiches et l'heure, rien d'autre
  const m = g => `<div class="nxm" title="${g.teams.away.name} – ${g.teams.home.name}">${logoHTML(g.teams.away)}<b>${g.teams.away.tri}</b><i>@</i><b>${g.teams.home.tri}</b>${logoHTML(g.teams.home)}<small>${hourLocal(g.date)}</small></div>`;
  $("#nextstrip").innerHTML = sect("La nuit prochaine", `<button class="btn" data-night-go="${next}">Voir la nuit ›</button>`) +
    `<div class="nxl">${[...pre].sort((x, y) => x.date - y.date).map(m).join("")}</div>`;
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
        ${g.state === "post" ? `<button class="btn amber fhrep" data-resume="${g.id}">${replayLabel(g)}</button>` : ""}
        <div class="fteam">${logoHTML(h)}<b>${h.name}</b><small>${h.city} ${h.record ? `(${h.record})` : ""}</small></div>
      </div>
    </div>
    <div class="fbody"><p class="loadmsg">Feuille de match en route…</p></div>`;
  sheet.classList.add("fiche");
  ovl.classList.add("open"); document.body.style.overflow = "hidden";
  let s;
  try { s = await summary(id); }
  catch (e) { sheet.querySelector(".fbody").innerHTML = `<p class="loadmsg">Impossible de charger les détails. Réessaie dans un instant.</p>`; return; }
  const body = sheet.querySelector(".fbody");
  // sur PC : un tableau de bord sans défilement — à gauche le film du match (qui remplit la hauteur) et les quarts-temps ;
  // à droite les deux feuilles de match, et dessous un grand demi-terrain : les tirs du joueur touché (au départ, le meilleur marqueur)
  const dash = DASH();
  body.innerHTML = `<div class="fcol fa">
    ${s.series ? `<div class="fsect ffilm"><h3><span class="tag">Le film du match</span><i></i></h3><div class="ffilmbox">${chartHTML(g, s.series, s.span)}</div></div>` : ""}
    ${dash ? `<div class="fsect fshots"><div class="fshot" id="fshot"></div></div>` : ""}
    ${s.quarters && !dash ? `<div class="fsect"><h3><span class="tag">Par quart-temps</span><i></i></h3>${quartersHTML(g, s)}</div>` : ""}
    ${s.players.length ? `<div class="fsect"><h3><span class="tag">Les patrons du match</span><i></i></h3>${prosHTML(s.players.slice(0, 6), g)}</div>` : ""}
    ${g.state === "post" ? `<div class="fbtns"><button class="btn amber big" data-resume="${g.id}">${replayLabel(g)}</button></div>` : ""}</div>
    ${s.players.length ? `<div class="fcol fb"><div class="fsect"><h3><span class="tag">La feuille de match</span><i></i><small class="bx-hint">Touche un joueur : tous ses tirs 🎯</small></h3>
      <div class="bxpair">${boxHTML(g, s, "away")}${boxHTML(g, s, "home")}</div></div>
      ${s.quarters && dash ? `<div class="fsect fqt"><h3><span class="tag">Par quart-temps</span><i></i></h3>${quartersHTML(g, s)}</div>` : ""}</div>` : ""}`;
  state.fiche = s; state.ficheG = g; // pour la carte de tirs
  if (dash) {
    // le film du match à la taille de sa place (le SVG garde ses textes nets : on change sa hauteur, pas son étirement)
    const fb = body.querySelector(".ffilmbox");
    if (fb && s.series) { const r = fb.getBoundingClientRect(); if (r.width > 100 && r.height > 80) fb.innerHTML = chartHTML(g, s.series, s.span, Math.max(180, Math.round(720 * (r.height - 24) / r.width))); }
    const top = [...s.players].filter(p => p.shots.length).sort((a, b) => b.pts - a.pts)[0];
    if (top) shotPanel(top);
  }
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
function chartHTML(g, pts, span0, H0) {
  const W = 720, H = H0 || 230, P = { l: 34, r: 14, t: 18, b: 26 };
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
  // classés par points (puis rebonds + passes), comme on lit une feuille de match
  const list = s.players.filter(p => p.tid === t.id).sort((a, b) => b.pts - a.pts || (b.reb + b.ast) - (a.reb + a.ast));
  if (!list.length) return "";
  const row = p => `<tr class="${p.shots.length ? "shootable" : ""}" ${p.shots.length ? `data-shot="${p.aid || p.name}"` : ""}>
    <td><span class="bxn">${p.name}</span>${p.shots.length ? `<span class="tgt">🎯</span>` : ""}</td>
    <td class="tot">${p.pts}</td><td>${p.fg}</td><td>${p.tp}</td><td>${p.reb}</td><td>${p.ast}</td><td>${p.blk || 0}</td><td class="mn">${p.min}</td></tr>`;
  return `<div class="bxteam"><div class="bxh" style="--mc:${t.color}">${logoHTML(t)}<b>${t.name}</b></div>
    <div class="qtwrap"><table class="qt bx"><thead><tr><th>Joueur</th><th>Pts</th><th>Tirs</th><th>3 pts</th><th>Reb</th><th>Pd</th><th title="Contres">Ctr</th><th title="Minutes jouées">Min</th></tr></thead>
    <tbody>${list.map(row).join("")}</tbody></table></div></div>`;
}

/* ---------- la carte de tirs (tous les tirs du joueur, dans l'ordre du match) ---------- */
const shotovl = $("#shotovl"), shotsheet = $("#shotsheet");
function courtSVG(shots, color, still) {
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
    const cx = sh.x * S, cy = Math.min(sh.y, 39) * S, d = RM || still ? 0 : i * step;
    return sh.m
      ? `<circle class="ring" cx="${cx}" cy="${cy}" r="7" fill="none" stroke="${color}" stroke-width="2" style="animation-delay:${d}ms"/><circle class="shot" cx="${cx}" cy="${cy}" r="7" fill="${color}" stroke="#fff" stroke-width="2" style="animation-delay:${d}ms"/>`
      : `<g class="shot" style="animation-delay:${d}ms"><line x1="${cx - 6}" y1="${cy - 6}" x2="${cx + 6}" y2="${cy + 6}" stroke="#8a8fa8" stroke-width="2.5"/><line x1="${cx - 6}" y1="${cy + 6}" x2="${cx + 6}" y2="${cy - 6}" stroke="#8a8fa8" stroke-width="2.5"/></g>`;
  }).join("");
  return { svg: `<svg class="court" viewBox="0 0 ${W} ${H}">${lines}${marks}</svg>`, step };
}
let shotTimer = null;
const DASH = () => matchMedia("(min-width:1100px) and (min-height:600px)").matches; // la fiche en tableau de bord (PC)
// les tirs d'un joueur dans la fiche (PC) : le demi-terrain en bas à droite, mis à jour au clic sur un joueur
function shotPanel(p) {
  const el = $("#fshot"); if (!el) return;
  const t = teamIn(state.ficheG, p.tid);
  const made = p.shots.filter(x => x.m).length, three = p.shots.filter(x => x.v === 3);
  const { svg } = courtSVG(p.shots, t.color, true);
  el.innerHTML = `<div class="fsi" style="--mc:${t.color}"><span class="tag">Les tirs</span>
      <div class="fsn">${logoHTML(t)}<b>${p.full || p.name}</b></div>
      <div class="fss"><div><b>${p.pts}</b><small>points</small></div><div><b>${made}/${p.shots.length}</b><small>tirs</small></div>
        <div><b>${three.filter(x => x.m).length}/${three.length}</b><small>à 3 pts</small></div><div><b>${p.reb}</b><small>rebonds</small></div></div>
      <div class="clegend"><span><i style="background:${t.color}"></i>Panier</span><span style="color:#8a8fa8">✕ Raté</span></div>
      <small class="fsh">Touche un autre joueur dans la feuille de match</small></div>
    <div class="fsc">${svg}</div>`;
  sheet.querySelectorAll("tr.shootable").forEach(r => r.classList.toggle("sel", r.dataset.shot === (p.aid || p.name)));
}
function openShots(key) {
  const s = state.fiche; if (!s) return;
  const p = s.players.find(q => q.aid === key || q.name === key); if (!p) return;
  if ($("#fshot") && DASH()) { shotPanel(p); return; } // PC : dans la fiche, pas de nouvelle fenêtre
  const t = teamIn(state.ficheG, p.tid);
  const made = p.shots.filter(x => x.m).length, three = p.shots.filter(x => x.v === 3);
  const { svg, step } = courtSVG(p.shots, t.color);
  shotsheet.classList.add("shots");
  shotsheet.innerHTML = `<div class="setbody">
    <button class="x" aria-label="Fermer">✕</button>
    <div class="sinfo"><div class="shead" style="--mc:${t.color}">${logoHTML(t)}<div><h2>${p.full || p.name}</h2><small>${t.city} ${t.name}</small></div></div>
    <div class="stiles">
      <div class="stat"><span class="led"><span class="v">${p.pts}</span></span><small>points</small></div>
      <div class="stat"><span class="led"><span class="v">${made}/${p.shots.length}</span></span><small>aux tirs</small></div>
      <div class="stat"><span class="led"><span class="v">${three.filter(x => x.m).length}/${three.length}</span></span><small>à 3 pts</small></div>
      <div class="stat"><span class="led"><span class="v">${p.reb}</span></span><small>rebonds</small></div>
    </div>
    <div class="scount" id="scount">&nbsp;</div>
    <div class="clegend"><span><i style="background:${t.color}"></i>Panier</span><span style="color:#8a8fa8">✕ Tir manqué</span></div>
    <button class="btn replay" data-replay="${key}">↻ Rejouer</button></div>
    <div class="scourt">${svg}</div>
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
  const fr = { Paris: "Paris", Montreal: "Montréal", Toronto: "Montréal", Brussels: "Bruxelles", Zurich: "Zurich", London: "Londres", New_York: "New York", "New York": "New York" };
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
  const head = `<div class="sect top"><h2>Les prochaines nuits <small>(${tzName()})</small></h2></div>`;
  main.innerHTML = head + `<div class="skel"><div class="ph" style="height:120px"></div><div class="ph" style="height:120px"></div></div>`;
  const tonight = nyKey(new Date()) > defaultNight() ? nyKey(new Date()) : defaultNight(); // la prochaine nuit à jouer
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
  main.innerHTML = `<div class="skel" style="margin-top:26px"><div class="ph" style="height:300px"></div></div>`;
  let data;
  try {
    data = DEMO ? await window.DEMO.standings()
      : await fetchJSON("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings");
  } catch (e) { if (tok === state.tok) main.innerHTML = `<p class="loadmsg">Impossible de charger le classement.</p>`; return; }

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
  // plus d'interrupteur (28/11, Kiki : « moche, pas très utile ») : le classement suit la révélation. La dernière nuit compte
  // dès qu'elle a été révélée (bouton « Révéler la nuit ») ou avec « toujours montrer » ; sinon il s'arrête juste avant.
  let lastGames = []; try { lastGames = (await scoreboard(defaultNight())).filter(g => g.state === "post"); } catch (e) { /* déjà vu plus haut */ }
  const cut = cutPossible && !settings.showAll && !state.allOpen && !lastGames.every(g => state.revealed.has(g.id));
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
    confs.push({ name: /east/i.test(ch.name) ? "Conférence Est" : /west/i.test(ch.name) ? "Conférence Ouest" : ch.name, rows, west: /west/i.test(ch.name) });
  }
  confs.sort((a, b) => b.west - a.west); // l'Ouest à gauche (28/11, Kiki)
  const pct = r => (r.w + r.l) ? (r.w / (r.w + r.l)) : 0;
  const confHTML = c => {
    const lead = c.rows[0];
    return `<div class="conf">${sect(c.name)}
      ${c.rows.map((r, i) => {
        const t = team(r.id);
        // des sous-parties plutôt qu'une légende (28/11, carte blanche de Kiki)
        const part = i === 0 ? `<div class="srow spart po"><span class="pl">Play-offs</span><span class="n">V</span><span class="n">D</span><span class="n">%</span><span class="n gb">Écart</span></div>` : i === 6 ? `<div class="spart pi">Play-in</div>` : i === 10 ? `<div class="spart out">Hors course</div>` : "";
        const gb = lead ? ((lead.w - r.w) + (r.l - lead.l)) / 2 : 0;
        return part + `<div class="srow ${i < 6 ? "po" : i < 10 ? "pi" : ""} ${r.id === settings.fav ? "favrow" : ""}" style="--tc:${t.color};animation-delay:${i * 30}ms">
          <span class="rk">${i + 1}</span>${logoHTML(t)}<span class="tn">${t.name}</span>
          <span class="n">${r.w}</span><span class="n">${r.l}</span><span class="n pc">${(pct(r) * 100).toFixed(1).replace(".", ",")}</span>
          <span class="n gb">${gb === 0 ? "–" : gb.toFixed(1).replace(".0", "").replace(".", ",")}</span></div>`;
      }).join("")}</div>`;
  };
  // plus de grand titre (déjà dans le menu, comme le programme) : étiquette, coupure sans spoil et légende sur UNE ligne
  const d1 = keyDate(defaultNight()), d2 = keyDate(addDays(defaultNight(), 1));
  const nuitTxt = EURO ? `${d1.getUTCDate()} → ${d2.getUTCDate()}` : FR({ day: "numeric", month: "short" }).format(d1);
  main.innerHTML = `<div class="standwrap">${confs.map(confHTML).join("")}</div>
    ${cut ? `<p class="standnote">Sans les résultats de la nuit du ${nuitTxt} : « Révéler tous les résultats », en haut, les ajoute.</p>` : ""}`;

}

/* ---------- la NBA Cup (28/11, carte blanche de Kiki) ----------
   ESPN marque chaque match (« NBA Cup - Group Play », « - Quarterfinals », « - Semifinals », « NBA Cup Championship »), mais ne donne
   pas les groupes : on les retrouve (dans un groupe de 5, chacun joue les 4 autres : les matchs de groupe forment 6 paquets).
   Sans spoil : un résultat ne compte que s'il est d'une nuit d'avant la dernière, ou révélé (même ensemble que les nuits :
   un match révélé sur la page de la nuit l'est aussi ici), ou avec « toujours montrer ». Le tableau ne se remplit qu'avec ce qui
   compte : tant qu'un match de groupe est caché, les qualifiés restent « ? ». Onglet visible jusqu'au lendemain de la finale. */
const CUP = { year: 2026, dates: ["20261030", "20261106", "20261113", "20261120", "20261124", "20261125", "20261127", "20261204", "20261205", "20261208", "20261211"], until: "20261212" };
const EAST = new Set([1, 2, 4, 5, 8, 11, 14, 15, 17, 18, 19, 20, 27, 28, 30]);
const cupOn = () => nyKey(new Date()) <= CUP.until || QS.get("vue") === "cup";
function cupShown(g) { // ce résultat peut-il être montré ?
  return g.state === "post" && (settings.showAll || state.revealed.has(g.id) || nyKey(g.date) < defaultNight());
}
async function renderCup() {
  const tok = ++state.tok;
  const main = $("#main");
  setURL();
  main.innerHTML = `<div class="skel"><div class="ph" style="height:260px"></div><div class="ph" style="height:420px"></div></div>`;
  let all;
  try { all = (await Promise.all(CUP.dates.map(k => scoreboard(k).catch(() => [])))).flat().filter(g => g.cup); }
  catch (e) { all = []; }
  if (tok !== state.tok) return;
  if (settings.showAll || state.allOpen) all.forEach(g => { if (g.state === "post") state.revealed.add(g.id); });
  if (!all.length) { main.innerHTML = `<p class="loadmsg">La NBA Cup n'est pas encore disponible chez ESPN. Réessaie dans un instant.</p>`; return; }
  const grp = all.filter(g => g.cup === "group"), ko = all.filter(g => g.cup !== "group");
  // les groupes : composantes du graphe des matchs de groupe
  const par = new Map(), find = x => { while (par.get(x) !== x) x = par.get(x); return x; };
  for (const g of grp) for (const t of [g.teams.away.id, g.teams.home.id]) if (!par.has(t)) par.set(t, t);
  for (const g of grp) par.set(find(g.teams.away.id), find(g.teams.home.id));
  const groups = new Map();
  for (const t of par.keys()) { const r = find(t); if (!groups.has(r)) groups.set(r, []); groups.get(r).push(t); }
  const groupsDone = grp.every(cupShown);
  // les qualifiés : les équipes des quarts (connues seulement quand toute la phase de groupes peut être montrée)
  const qfs = ko.filter(g => g.cup === "qf").sort((a, b) => a.date - b.date);
  const qual = new Set(groupsDone ? qfs.flatMap(g => [g.teams.away.id, g.teams.home.id]).filter(id => TEAMS[id]) : []);
  const table = ids => {
    const R = new Map(ids.map(id => [id, { id, w: 0, l: 0, pf: 0, pa: 0, gp: 0 }]));
    for (const g of grp) if (cupShown(g) && R.has(g.teams.home.id)) {
      const a = R.get(g.teams.away.id), h = R.get(g.teams.home.id), as = g.teams.away.score, hs = g.teams.home.score;
      a.gp++; h.gp++; a.pf += as; a.pa += hs; h.pf += hs; h.pa += as;
      if (as > hs) { a.w++; h.l++; } else { h.w++; a.l++; }
    }
    const h2h = (x, y) => { const g = grp.find(g => cupShown(g) && [g.teams.away.id, g.teams.home.id].includes(x.id) && [g.teams.away.id, g.teams.home.id].includes(y.id));
      if (!g) return 0; const xw = (g.teams.away.id === x.id) === (g.teams.away.score > g.teams.home.score); return xw ? -1 : 1; };
    return [...R.values()].sort((x, y) => y.w - x.w || (x.w === y.w && h2h(x, y)) || (y.pf - y.pa) - (x.pf - x.pa) || y.pf - x.pf);
  };
  // le vrai classement d'un groupe départage aussi les égalités à trois : les qualifiés (vainqueur, puis repêché) passent devant
  const ranked = ids => { const r = table(ids); return r.filter(x => qual.has(x.id)).concat(r.filter(x => !qual.has(x.id))); };
  const gl = [...groups.values()].map(ids => ({ east: EAST.has(ids[0]), rows: ranked(ids), key: Math.min(...ids) }))
    .sort((a, b) => (a.east - b.east) || a.key - b.key); // l'Ouest d'abord (à gauche, comme sur une carte)
  let ne = 0, nw = 0;
  gl.forEach(G => { G.name = `Groupe ${G.east ? "Est" : "Ouest"} ${G.east ? ++ne : ++nw}`; });
  const left = grp.filter(g => g.state !== "post").length, hiddenG = grp.filter(g => g.state === "post" && !cupShown(g)).length;
  const groupHTML = G => `<div class="cgrp"><div class="cgh">${G.name}</div>
    <div class="cgr head"><span></span><span></span><span>Équipe</span><span class="n">V-D</span><span class="n">Diff.</span><span></span></div>
    ${G.rows.map((r, i) => { const t = team(r.id), d = r.pf - r.pa, q = qual.has(r.id);
      const tag = !q ? "" : G.rows.findIndex(x => qual.has(x.id)) === i ? `<span class="ctag">Qualifié</span>` : `<span class="ctag wc">Repêché</span>`;
      return `<div class="cgr${q ? " q" : ""}${r.id === settings.fav ? " favrow" : ""}" style="--tc:${t.color}"><span class="rk">${r.gp ? i + 1 : "–"}</span>${logoHTML(t)}<span class="tn">${t.name}</span>
        <span class="n">${r.w}-${r.l}</span><span class="n">${r.gp ? (d > 0 ? "+" : "") + d : "–"}</span>${tag}</div>`; }).join("")}</div>`;
  // le tableau final : les vainqueurs ne montent que si le match peut être montré
  const winnerOf = g => g && cupShown(g) ? (g.teams.away.score > g.teams.home.score ? g.teams.away.id : g.teams.home.id) : null;
  const confOf = g => EAST.has(g.teams.home.id) || EAST.has(g.teams.away.id);
  const qfE = qfs.filter(g => groupsDone && confOf(g)), qfW = qfs.filter(g => groupsDone && !confOf(g));
  const sfs = ko.filter(g => g.cup === "sf").sort((a, b) => a.date - b.date), fin = ko.find(g => g.cup === "final");
  const sfFor = (pair) => { // la demi-finale qui oppose les vainqueurs de ces deux quarts (vrais noms seulement s'ils sont montrables)
    const w = pair.map(winnerOf);
    const real = sfs.find(g => w.every(id => id && [g.teams.away.id, g.teams.home.id].includes(id)));
    return { g: real || null, ids: w, date: (real || sfs[0] || {}).date };
  };
  const sfE = sfFor(qfE.length === 2 ? qfE : [null, null]), sfW = sfFor(qfW.length === 2 ? qfW : [null, null]);
  const fw = [sfE.g && winnerOf(sfE.g), sfW.g && winnerOf(sfW.g)];
  const realF = fin && fw.every(id => id && [fin.teams.away.id, fin.teams.home.id].includes(id)) ? fin : null;
  const champ = realF && winnerOf(realF);
  const when = d => d ? `${cap1(FR({ weekday: "short", day: "numeric", month: "short" }).format(d)).replace(/\./g, "")} · ${hourLocal(d)}` : "";
  const slot = (g, id, side) => { // une rangée d'équipe dans une plaque du tableau
    if (!id) return `<div class="cmr unk"><span class="lg noimg"><span>?</span></span><b>À venir</b><span class="sc"></span></div>`;
    const t = team(id), shown = g && cupShown(g), hid = g && g.state === "post" && !shown;
    const sc = !g || g.state === "pre" ? "" : hid ? `<span class="led hid cupled" data-cg="${g.id}" role="button" tabindex="0"><span class="v">??</span></span>`
      : g.state === "live" ? `<span class="led live"><span class="v">${g.teams[side].score}</span></span>` : `<span class="led"><span class="v">${g.teams[side].score}</span></span>`;
    const win = shown && winnerOf(g) === id, lose = shown && winnerOf(g) !== id;
    return `<div class="cmr${win ? " win" : ""}${lose ? " lose" : ""}" style="--tc:${t.color}">${logoHTML(t)}<b title="${t.city} ${t.name}">${t.name}</b>${sc}</div>`;
  };
  const plate = (g, ids, label, date, big) => {
    const st = !g ? (date ? when(date) : "") : g.state === "pre" ? when(g.date) : g.state === "live" ? `<span class="lv">● En direct</span>` : cupShown(g) ? "Final" : "Terminé";
    const sideOf = id => g && g.teams.away.id === id ? "away" : "home";
    return `<div class="cm${big ? " big" : ""}"><div class="cmh"><span>${label}</span><span>${st}</span></div>
      ${slot(g, ids[0], ids[0] ? sideOf(ids[0]) : "away")}${slot(g, ids[1], ids[1] ? sideOf(ids[1]) : "home")}</div>`;
  };
  const qfPlate = g => plate(g, [g.teams.away.id, g.teams.home.id], "Quart de finale");
  const blankQF = d => plate(null, [null, null], "Quart de finale", d);
  const colQF = (L) => L.length === 2 ? L.map(qfPlate).join("") : blankQF(qfs[0] && qfs[0].date) + blankQF(qfs[2] && qfs[2].date);
  const sfPlate = (S) => plate(S.g, S.g ? [S.g.teams.away.id, S.g.teams.home.id] : S.ids, "Demi-finale", S.date);
  const fPlate = plate(realF, realF ? [realF.teams.away.id, realF.teams.home.id] : [fw[1] || null, fw[0] || null], "Finale", fin && fin.date, true);
  const trophy = `<img class="ctro" src="nba-cup.png?v=1" alt="Le trophée de la NBA Cup" width="196" height="480">`; // le vrai trophée (image fournie par Kiki), fond retiré
  const champHTML = champ ? (() => { const t = team(champ); return `<div class="cchamp" style="--tc:${t.color}">${logoHTML(t)}<span><small>Vainqueur de la NBA Cup</small><b>${t.city} ${t.name}</b></span></div>`; })() : "";
  const hidKO = ko.filter(g => g.state === "post" && !cupShown(g)).length;
  const toReveal = hiddenG + hidKO;
  // où on en est : entre parenthèses dans le titre de chaque partie (28/11, Kiki)
  const koLeft = ko.filter(g => g.state !== "post").length;
  const stGroups = left ? `(en cours · ${plural(left, "match")} à jouer)` : "(terminée)";
  const stKO = !qfs.length || ko.every(g => g.state === "pre") ? "" : koLeft ? "(en cours)" : "(terminé)";
  // 28/11 (Kiki) : d'abord le principe de la Coupe, puis où on en est, tout à la même taille (plus de gros titre)
  main.innerHTML = `<div class="cuptop"><p><span>6 groupes de 5 · le 1er de chaque groupe et le meilleur 2e de chaque conférence vont en quarts.</span></p>
</div>
    ${sect(`Le tableau final${stKO ? ` <small>${stKO}</small>` : ""}`)}
    <div class="cbr">
      <div class="cbc"><div class="cbt">Ouest</div>${colQF(qfW)}</div>
      <div class="cbc mid1">${sfPlate(sfW)}</div>
      <div class="cbc fin">${trophy}${fPlate}${champHTML}</div>
      <div class="cbc mid1">${sfPlate(sfE)}</div>
      <div class="cbc"><div class="cbt">Est</div>${colQF(qfE)}</div>
    </div>
    ${sect(`La phase de groupes <small>${stGroups}</small>`)}
    <div class="cgrid">${gl.map(groupHTML).join("")}</div>`;
}
document.addEventListener("click", e => { // un afficheur « ?? » du tableau : ce match seulement
  const l = e.target.closest(".cupled"); if (!l) return;
  state.revealed.add(l.dataset.cg); renderCup();
});

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
    <div><h3>Fuseau horaire</h3>
      <div class="tzpick">${[[null, "Automatique", TZ_AUTO.split("/").pop().replace(/_/g, " ")], ["Europe/Paris", "Paris", "Nuit du … au …"], ["America/Montreal", "Montréal", "Mercredi 21 …"]]
        .map(([z, l, sub]) => `<button class="tzb ${(store.get("tz", null) || null) === z ? "on" : ""}" data-tz="${z || ""}"><b>${l}</b><small>${sub}</small></button>`).join("")}</div></div>
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
      paintRev();
      return;
    }
    const tz = e.target.closest("[data-tz]");
    if (tz) { store.set("tz", tz.dataset.tz || null); location.reload(); return; } // toutes les dates changent : on recharge
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
    const dot = ""; // plus aucune pastille de notification sur la frise des nuits (demande de Kiki, 23/11)
    // seule la dernière nuit (celle d'il y a quelques heures) et la suivante ont un nom ; la veille passe en « Retour sur la nuit »
    // comme les autres (« Nuit dernière » prêtait à confusion avec « Cette nuit »)
    // la suivante : « La nuit à venir » (21/11 : « Demain » tombait sur l'après-demain une fois la nuit jouée)
    const today = k === nyKey(new Date());
    const lab = k === tonight ? (EURO ? "Cette nuit" : today ? "Ce soir" : "Hier soir") : k === addDays(tonight, 1) ? (EURO ? "La nuit à venir" : today ? "Ce soir" : "Demain") : c.s;
    // le contexte (« Retour sur la nuit »…) seulement quand l'étiquette ne dit pas déjà « Cette nuit » ou « La nuit à venir »
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
  track("/" + vue, { nuit: "Les nuits", cup: "La NBA Cup", programme: "Le programme", classement: "Le classement" }[vue] || vue);
  $$(".tab[data-vue]").forEach(t => t.classList.toggle("on", t.dataset.vue === vue));
  if (vue === "nuit") renderNight();
  else if (vue === "cup") renderCup();
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
  if (vp) { playVideo(vp.dataset.vplay, vp.dataset.vlabel || "Vidéo", null, vp.dataset.vs ? { start: +vp.dataset.vs, end: +vp.dataset.ve } : null); return; }
  const np = e.target.closest("[data-nuitplus]");
  if (np) { openNightPlus(np.dataset.nuitplus); return; }
  const ns = e.target.closest("[data-nuitsolo]");
  if (ns) { openNightPlus(ns.dataset.night, ns.dataset.nuitsolo); return; }
  const rp = e.target.closest("[data-replay]");
  if (rp) { openShots(rp.dataset.replay); return; }
  const sh = e.target.closest("[data-shot]");
  if (sh) { openShots(sh.dataset.shot); return; }
  if (e.target.closest(".fsb") && vidovl.requestFullscreen) { vidovl.requestFullscreen().catch(() => {}); return; }
  if (e.target === vidovl || (e.target.closest(".x") && e.target.closest("#vidovl"))) { closeResume(); return; }
  if (e.target === shotovl || (e.target.closest(".x") && e.target.closest("#shotovl"))) { closeShots(); return; }
  if (e.target.closest("#gear") || e.target.closest("#gear2")) { openSettings(); return; }
  if (e.target.closest("#revall")) { toggleRevealAll(); return; }
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
    touche un afficheur pour un seul match, ou <b>« Révéler tous les résultats »</b>, en haut, pour tout dévoiler d'un coup (scores, NBA Cup, classement).</p>
    <button class="btn prime" id="hellok">Compris</button></div>`;
  $("#hellok").addEventListener("click", () => { store.set("hello", true); w.hidden = true; });
}

/* ---------- statistiques de visite (GoatCounter : gratuit, sans cookie, sans compte pour les visiteurs) ----------
   Le tableau de bord est sur https://<GC>.goatcounter.com (compte de Kiki). On compte : chaque page vue (« /nuit »,
   « /programme »…), et une fois par jour « qui/<nom> » pour les appareils ouverts avec un lien personnel (?qui=tom).
   Les appareils de Kiki sont exclus (page ?admin → « Ne pas compter cet appareil »). */
const GC = "nocturne-nba";
const LOCALHOST = /^(localhost|127\.|192\.168\.)/.test(location.hostname);
(function personalLink() { // ?qui=tom : on retient le nom sur l'appareil, puis on nettoie l'adresse
  const q = (QS.get("qui") || "").toLowerCase().replace(/[^a-z0-9-]/g, "").slice(0, 20);
  if (!q) return;
  store.set("qui", q);
  const u = new URL(location.href); u.searchParams.delete("qui"); history.replaceState(null, "", u.pathname + u.search + u.hash);
})();
const statsOff = () => DEMO || LOCALHOST || QS.has("admin") || (() => { try { return localStorage.getItem("skipgc") === "t"; } catch (e) { return false; } })();
let gcReady = null;
function gcLoad() {
  if (gcReady || statsOff()) return gcReady;
  gcReady = new Promise(res => {
    const sc = document.createElement("script");
    sc.async = true; sc.src = "https://gc.zgo.at/count.js";
    sc.dataset.goatcounter = `https://${GC}.goatcounter.com/count`;
    sc.dataset.goatcounterSettings = JSON.stringify({ no_onload: true });
    sc.onload = () => res(window.goatcounter || null); sc.onerror = () => res(null);
    document.head.appendChild(sc);
  });
  return gcReady;
}
async function track(path, title, event) {
  if (statsOff()) return;
  const gc = await gcLoad(); if (!gc || !gc.count) return;
  try { gc.count({ path, title: title || path, event: !!event }); } catch (e) { /* tant pis */ }
}
// qui est venu, SANS lien personnel (un seul lien pour tout le monde, choix de Kiki) : une fois par jour, chaque appareil se
// signale par sa ville (d'après son fuseau), son type et un petit code au hasard qui lui reste (« Montréal · iPhone · k3f2 »)
function deviceTag() {
  let id = store.get("dev", null);
  if (!id) { id = Math.random().toString(36).slice(2, 6); store.set("dev", id); }
  const ua = navigator.userAgent;
  const kind = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? (/Mobile/.test(ua) ? "Android" : "tablette Android")
    : /Xbox/.test(ua) ? "Xbox" : /Macintosh/.test(ua) ? "Mac" : /Windows/.test(ua) ? "PC Windows" : /Linux/.test(ua) ? "Linux" : "appareil";
  const z = TZ_AUTO, city = /Montreal|Toronto/.test(z) ? "Montréal" : /^America\//.test(z) ? "Amérique" : z === "Europe/Paris" ? "France" : z.split("/").pop().replace(/_/g, " ");
  const q = store.get("qui", null); // un ancien lien personnel (?qui=…) garde son nom
  return { path: "visiteur/" + (q || `${city}-${kind}-${id}`).toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/\s+/g, "-"),
    title: q ? q : `${city} · ${kind} · ${id}` };
}
function trackVisitor() {
  const day = new Date().toISOString().slice(0, 10);
  if (store.get("quiday", "") === day) return;
  store.set("quiday", day);
  const t = deviceTag();
  track(t.path, t.title, true);
}

const ADMIN_HASH = "683dc3cbd81afd097ea1e08ae9527547f68a5ccc50770ef55c65fe564367d0fd"; // SHA-256 du code secret de Kiki (le code lui-même n'est pas dans le site)
async function isAdmin() {
  if (store.get("admin", false) === ADMIN_HASH) return true;
  const code = QS.get("admin") || "";
  if (!code || !(window.crypto && crypto.subtle)) return false;
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(code));
  const hex = [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
  if (hex !== ADMIN_HASH) return false;
  store.set("admin", ADMIN_HASH); // cet appareil est celui de Kiki : ?admin suffira désormais
  try { localStorage.setItem("skipgc", "t"); } catch (e) { /* */ } // et ses visites ne sont pas comptées
  return true;
}
/* ---------- la page d'administration (?admin) : les visites, les liens personnels, exclure ses appareils ---------- */
function renderAdmin() {
  const main = $("#main");
  let skip = false; try { skip = localStorage.getItem("skipgc") === "t"; } catch (e) { /* */ }
  main.innerHTML = `<section class="adm">
    <p class="greet"><i></i>Administration</p>
    <div class="adcard"><h3>Les visites</h3>
      <p>Le compteur (GoatCounter, gratuit et sans cookie) note chaque page ouverte et quels appareils sont venus.
      Tableau de bord : nombre de visites par jour, pages vues, pays, téléphone ou ordinateur, et une ligne par appareil.</p>
      <a class="btn prime big" href="https://${GC}.goatcounter.com" target="_blank" rel="noopener">Ouvrir le tableau de bord ↗</a></div>
    <div class="adcard"><h3>Qui est venu</h3>
      <p>Un seul lien pour tout le monde. Chaque appareil se signale une fois par jour, dans la rubrique « Events » du tableau
      de bord, par sa ville (d'après son fuseau horaire), son type et un petit code qui lui reste : par exemple
      « Montréal · iPhone · k3f2 » ou « France · Android · 7tq1 ». Une fois tes appareils exclus ci-dessous, les autres sont tes amis.</p>
      <div class="adl"><span><b>Cet appareil</b><small>${deviceTag().title}</small></span></div></div>
    <div class="adcard"><h3>Cet appareil</h3>
      <div class="swrow"><p>Ne pas compter mes visites<small>À activer sur ton téléphone et ton ordinateur, pour que les chiffres ne montrent que tes amis.</small></p>
        <button class="sw ${skip ? "on" : ""}" id="adskip" role="switch" aria-checked="${skip}"></button></div></div>
  </section>`;
  main.onclick = async e => {
    const sw = e.target.closest(".adcard .swrow") ? $("#adskip") : null; // toute la ligne se touche (téléphone)
    if (sw) { skip = !skip; try { skip ? localStorage.setItem("skipgc", "t") : localStorage.removeItem("skipgc"); } catch (x) { /* */ }
      sw.classList.toggle("on", skip); sw.setAttribute("aria-checked", skip); toast(skip ? "Cet appareil n'est plus compté" : "Cet appareil est compté"); return; }
  };
}

/* ---------- démarrage ---------- */
(function init() {
  if (DEMO) $("#demopill").hidden = false;
  const nuit = QS.get("nuit");
  state.night = nuit && /^\d{4}-\d{2}-\d{2}$/.test(nuit) ? nuit.replaceAll("-", "") : defaultNight();
  welcome();
  loadVideos(); // en avance, pour que le premier clic « Résumé » soit instantané
  if (QS.has("admin")) { // page admin verrouillée : ?admin=<code secret> (seule son empreinte est dans le code) ; ensuite l'appareil est reconnu
    isAdmin().then(ok => { if (ok) renderAdmin(); else { history.replaceState(null, "", location.pathname); startSite(); } });
    return;
  }
  startSite();
})();
function startSite() {
  trackVisitor();
  const vue = QS.get("vue");
  if (cupOn()) $$(".tab.cuptab").forEach(t => { t.hidden = false; });
  paintRev();
  go(vue === "programme" || vue === "classement" || (vue === "cup" && cupOn()) ? vue : "nuit");
}
