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
    g.teams[side] = {
      ...team(+c.team.id), score: +c.score || 0, record: rec ? rec.summary : "",
      ls: (c.linescores || []).map(l => +l.value || 0), // points par quart-temps (pour le match en accéléré)
    };
    for (const L of c.leaders || []) for (const l of L.leaders || [])
      if (L.name === "pointsLeader" || L.abbreviation === "PTS")
        g.leaders.push({ name: l.athlete && l.athlete.shortName || "", pts: +l.value || 0 });
  }
  g.ot = g.state === "post" && g.period > 4;
  return g;
}
async function scoreboard(key) {
  if (DEMO) return window.DEMO.scoreboard(key);
  const url = API + "scoreboard?dates=" + key;
  try {
    const j = await fetchJSON(url);
    const games = (j.events || []).map(normEvent).sort((a, b) => a.date - b.date);
    // copie de secours : si ESPN retombe, on garde la dernière liste reçue
    store.set("sb_" + key, { t: Date.now(), games: games.map(g => ({ ...g, date: g.date.toISOString() })) });
    return games;
  } catch (e) {
    const c = store.get("sb_" + key, null);
    if (c) { alertBar("ESPN ne répond pas : scores de " + new Date(c.t).toLocaleTimeString("fr-FR") + "."); return c.games.map(g => ({ ...g, date: new Date(g.date) })); }
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
  // film du match (écart minute par minute, + = domicile devant)
  try {
    const plays = j.plays || [];
    if (plays.length > 10) {
      const maxMin = 48 + Math.max(0, ((out.quarters ? out.quarters.home.q.length : 4) - 4)) * 5;
      const arr = new Array(maxMin + 1).fill(null); arr[0] = 0;
      let lastEl = 0;
      for (const p of plays) {
        if (p.homeScore === undefined) continue;
        const per = p.period ? p.period.number : 1;
        let mm = 0, ss = 0;
        const m = /^(\d+):(\d+)/.exec(p.clock ? p.clock.displayValue : "");
        if (m) { mm = +m[1]; ss = +m[2]; }
        const len = per <= 4 ? 12 : 5;
        const start = per <= 4 ? (per - 1) * 12 : 48 + (per - 5) * 5;
        const el = Math.min(maxMin, Math.round(start + (len - mm - ss / 60)));
        arr[el] = p.homeScore - p.awayScore;
        if (el > lastEl) lastEl = el;
      }
      let last = 0;
      out.series = arr.slice(0, Math.max(lastEl + 1, 13)).map(v => (v === null ? last : (last = v)));
    }
  } catch (e) { /* tant pis pour la courbe */ }
  // feuille de match complète (tous les joueurs, toutes les colonnes utiles)
  try {
    for (const side of j.boxscore.players || []) {
      const tid = +side.team.id;
      const stt = side.statistics[0];
      const ix = n => stt.names.indexOf(n);
      const [iM, iF, i3, iR, iA, iP] = [ix("MIN"), ix("FG"), ix("3PT"), ix("REB"), ix("AST"), ix("PTS")];
      for (const a of stt.athletes || []) {
        if (!a.athlete || !a.stats || !a.stats.length) continue;
        out.players.push({
          aid: String(a.athlete.id || ""), name: a.athlete.shortName || a.athlete.displayName,
          full: a.athlete.displayName || "", tid,
          min: a.stats[iM] || "0", fg: a.stats[iF] || "", tp: a.stats[i3] || "",
          pts: +a.stats[iP] || 0, reb: +a.stats[iR] || 0, ast: +a.stats[iA] || 0,
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

/* ---------- l'info clé d'avant-match (une seule, la plus importante, jamais de spoil) ---------- */
let PREVNIGHT = null, PREVKEY = null; // équipes qui jouaient déjà la nuit précédente
async function loadPrevNight(key) {
  if (PREVKEY === key) return;
  try { const games = await scoreboard(addDays(key, -1)); PREVNIGHT = new Set(games.flatMap(g => [g.teams.away.id, g.teams.home.id])); }
  catch (e) { PREVNIGHT = new Set(); }
  PREVKEY = key;
}
function played(rec) { const m = /^(\d+)-(\d+)/.exec(rec || ""); return m ? +m[1] + +m[2] : 0; }
function keyFact(g) {
  if (g.state !== "pre") return null; // après le coup d'envoi, plus d'avant-match
  const a = g.teams.away, h = g.teams.home, pa = winpct(a.record), ph = winpct(h.record);
  const n = Math.min(played(a.record), played(h.record));
  if (n >= 8 && pa >= .65 && ph >= .65) return ["Choc au sommet", `${a.name} et ${h.name}, deux des meilleurs bilans de la ligue`];
  const star = [...g.leaders].sort((x, y) => y.pts - x.pts)[0];
  if (star && star.pts >= 27) return ["L'homme en forme", `${star.name} tourne à ${String(star.pts.toFixed(1)).replace(".", ",")} points par match`];
  if (n >= 6 && Math.abs(pa - ph) >= .35) return ["Grand favori", `Victoire attendue côté ${pa > ph ? a.name : h.name}`];
  if (PREVNIGHT && (PREVNIGHT.has(a.id) || PREVNIGHT.has(h.id))) {
    const t = PREVNIGHT.has(a.id) ? a : h;
    return ["Fatigue", `${t.name} : 2e match en 2 soirs${t === a ? ", en déplacement" : ""}`];
  }
  if (n >= 6 && Math.abs(pa - ph) <= .06) return ["Pile ou face", "Deux équipes impossibles à départager sur le papier"];
  return null;
}
function kfHTML(g) {
  const f = keyFact(g);
  return f ? `<div class="mkf"><b>${f[0]}</b><span>${f[1]}</span></div>` : "";
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
function playVideo(vid, label) { // lecteur intégré, sans quitter le site
  vplayer.innerHTML = `
    <button class="x" aria-label="Fermer">✕</button>
    <div class="vframe"><iframe src="https://www.youtube-nocookie.com/embed/${vid}?autoplay=1&rel=0&hl=fr"
      title="${label}" allow="autoplay; fullscreen; encrypted-media" allowfullscreen></iframe></div>
    <div class="vfoot"><span>${label}</span>
      <a href="https://www.youtube.com/watch?v=${vid}" target="_blank" rel="noopener">Ouvrir sur YouTube ↗</a></div>`;
  vidovl.classList.add("open"); document.body.style.overflow = "hidden";
}
async function openResume(id, extra) {
  const g = state.games.find(x => x.id === id); if (!g) return;
  if (DEMO) { toast("Démo : ici, le vrai résumé vidéo se lancerait dans le site"); return; }
  await loadVideos();
  const v = extra ? findExtra(g) : findVideo(g);
  if (!v) { window.open(ytURL(g), "_blank", "noopener"); return; }
  playVideo(v.id, `${g.teams.away.name} – ${g.teams.home.name} · ${extra ? "NBA Extra" : v.c === "gt" ? "résumé GameTime" : "résumé NBA"}`);
}
function closeResume() { vplayer.innerHTML = ""; vidovl.classList.remove("open"); document.body.style.overflow = ""; }

/* ---------- briques d'affichage ---------- */
function scHTML(g, side, mini) {
  const t = g.teams[side];
  return `<span class="sc" data-g="${g.id}" data-side="${side}" style="--mc:${t.color}" role="button" tabindex="0" aria-label="Révéler le score"><span class="q">?</span><span class="n"></span></span>`;
}
function statusText(g, revealed) {
  if (g.state === "pre") return hourLocal(g.date);
  if (g.state === "live") return revealed ? `● En direct · Q${Math.min(g.period, 4)}${g.period > 4 ? "+P" : ""} ${g.clock}` : "● En direct";
  return revealed && g.ot ? "Final · Prolongation" : "Final";
}
function recHTML(t, g) { // bilan : seulement avant le match ou une fois révélé (sinon il trahit le résultat)
  const show = g.state === "pre" || state.revealed.has(g.id) || settings.showAll;
  return show && t.record ? `(${t.record})` : "";
}
function artHTML(a, h) { // les grands logos en diagonale, l'ADN visuel du site
  const img = t => t.logo && !DEMO ? `<img src="https://a.espncdn.com/i/teamlogos/nba/500/${t.logo}.png" alt="" loading="lazy" onerror="this.remove()">` : `<i>${t.tri}</i>`;
  return `<div class="art" aria-hidden="true"><span class="a">${img(a)}</span><span class="b">${img(h)}</span></div><div class="scrim"></div>`;
}
function heroHTML(g, lvl) {
  const a = g.teams.away, h = g.teams.home;
  const label = g.state === "pre" ? "L'affiche de la nuit" : "Le match de la nuit";
  const mid = g.state === "pre"
    ? `<div class="sc pre"><span class="q">${hourLocal(g.date)}</span></div>`
    : `${scHTML(g, "away")}<div class="hstat ${g.state === "live" ? "liv" : ""}" data-st="${g.id}">${statusText(g)}</div>${scHTML(g, "home")}
       <div class="hint-eye" data-hint="${g.id}">👁 toucher pour revivre le match</div>`;
  return `<div class="hero-zone">
    <div class="hlabel"><span>${"🔥".repeat(Math.max(1, lvl - 2))} ${label}</span><i></i></div>
    <article class="holo" data-card="${g.id}" style="--ca:${a.color};--cb:${h.color}">
      <div class="holo-in">
        ${artHTML(a, h)}
        <div class="rar-tag">${RAR[lvl][1].replace(/^\S+ /, "")}</div>
        <div class="hhour">${hourLocal(g.date)}</div>
        <div class="hgrid">
          <div class="hteam">${logoHTML(a)}<div class="tx">
            <div class="hcity">${a.city}</div><div class="hname">${a.name}</div><div class="hrec" data-rec="${g.id}:away">${recHTML(a, g)}</div></div></div>
          <div class="hmid">${mid}</div>
          <div class="hteam right">${logoHTML(h)}<div class="tx">
            <div class="hcity">${h.city}</div><div class="hname">${h.name}</div><div class="hrec" data-rec="${g.id}:home">${recHTML(h, g)}</div></div></div>
        </div>
        <div class="hfoot">
          ${kfHTML(g)}
          <div class="hbtns">${btnsHTML(g)}</div>
        </div>
      </div>
      <div class="pz"></div>
    </article></div>`;
}
function btnsHTML(g) {
  if (g.state === "pre") return "";
  const r = g.state === "post" ? `<button class="bt gold" data-resume="${g.id}"><span class="pl">▶</span> Résumé</button>` : "";
  const x = g.state === "post" && findExtra(g) ? `<button class="bt extra" data-extra="${g.id}"><i class="fr"></i>NBA Extra</button>` : "";
  return `${r}${x}<button class="bt" data-fiche="${g.id}">Stats ›</button>`;
}
function cardHTML(g, i) {
  const a = g.teams.away, h = g.teams.home;
  const lvl = watchLevel(g), [cls, lab] = RAR[lvl];
  const fav = settings.fav && (a.id === settings.fav || h.id === settings.fav);
  const trow = (t, side) => `<div class="trow">${logoHTML(t)}
      <div class="tnm"><b>${t.name}</b><small data-rec="${g.id}:${side}">${recHTML(t, g)}</small>${t.id === settings.fav ? `<span class="star">★</span>` : ""}</div>
      ${g.state === "pre" ? "<span></span>" : scHTML(g, side, true)}</div>`;
  return `<article class="mcard ${cls}" data-card="${g.id}" style="--ca:${a.color};--cb:${h.color};animation-delay:${Math.min(i * 70, 500)}ms">
    <div class="rband"></div>
    <div class="mhead"><span class="mrar">${g.state === "pre" ? "Affiche " + "🔥".repeat(Math.max(0, lvl - 1)) : lab}</span>
      <span class="mstat ${g.state === "live" ? "liv" : ""}" data-st="${g.id}">${statusText(g)}${fav ? " · ★" : ""}</span></div>
    <div class="mteams">${trow(a, "away")}${trow(h, "home")}</div>
    ${(g.state !== "pre" || keyFact(g)) ? `<div class="mfoot">${kfHTML(g)}<div class="mbtns">${btnsHTML(g)}</div></div>` : ""}
    <div class="pz"></div>
  </article>`;
}

/* ---------- révélation ---------- */
function countUp(el, v) {
  if (RM) { el.textContent = v; return; }
  const t0 = performance.now(), d = 650;
  (function f(t) { const p = Math.min(1, (t - t0) / d), e = 1 - Math.pow(1 - p, 3); el.textContent = Math.round(v * e); if (p < 1) requestAnimationFrame(f); })(t0);
}
function particles(card, gold) {
  if (RM || !card) return;
  const pz = card.querySelector(".pz"); if (!pz) return;
  const cols = gold ? ["#f7e08a", "#f3c552", "#fff7d6", "#b8860b"] : ["#eef2fa", "#aeb8d0", "#fff"];
  for (let k = 0; k < 26; k++) {
    const s = document.createElement("i");
    const a = Math.random() * Math.PI * 2, r = 60 + Math.random() * 160;
    s.style.cssText = `--tx:${Math.cos(a) * r}px;--ty:${Math.sin(a) * r - 40}px;--pc:${cols[k % cols.length]};animation-delay:${Math.random() * 120}ms;width:${4 + Math.random() * 6}px;height:${4 + Math.random() * 6}px`;
    pz.appendChild(s); setTimeout(() => s.remove(), 1100);
  }
}
function finishReveal(g, withParticles) {
  for (const c of $$(`.sc[data-g="${g.id}"]`)) {
    const t = g.teams[c.dataset.side];
    const lose = g.state === "post" && t.score < g.teams[c.dataset.side === "away" ? "home" : "away"].score;
    c.classList.add("rev"); c.classList.remove("lead", "trail"); c.classList.toggle("lose", lose);
    c.querySelector(".n").textContent = t.score;
  }
  for (const st of $$(`[data-st="${g.id}"]`)) { st.textContent = statusText(g, true); st.classList.remove("race"); }
  for (const r of $$(`[data-rec^="${g.id}:"]`)) { const side = r.dataset.rec.split(":")[1]; r.textContent = recHTML(g.teams[side], g); }
  const hint = $(`[data-hint="${g.id}"]`); if (hint) hint.style.visibility = "hidden";
  if (withParticles) {
    const lvl = watchLevel(g);
    if (lvl >= 4) particles($(`[data-card="${g.id}"]`), lvl === 5);
  }
}
function reveal(id, instant) {
  const g = state.games.find(x => x.id === id);
  if (!g || g.state === "pre") return;
  const first = !state.revealed.has(id);
  state.revealed.add(id);
  const la = g.teams.away.ls || [], lh = g.teams.home.ls || [];
  const canRace = first && !instant && !RM && g.state === "post" && la.length >= 4 && lh.length >= 4;
  if (!canRace) { // révélation simple (direct, re-rendu, préférence « toujours montrer »…)
    if (first && !instant && !RM) {
      for (const c of $$(`.sc[data-g="${id}"]`)) { c.classList.add("rev"); countUp(c.querySelector(".n"), g.teams[c.dataset.side].score); }
      setTimeout(() => finishReveal(g, true), 700);
    } else finishReveal(g, false);
    return;
  }
  // ⭐ LE MATCH EN ACCÉLÉRÉ : les deux scores s'affrontent quart-temps par quart-temps
  const cells = $$(`.sc[data-g="${id}"]`);
  cells.forEach(c => c.classList.add("rev"));
  const sts = $$(`[data-st="${id}"]`); sts.forEach(s => s.classList.add("race"));
  const cum = (arr, k) => arr.slice(0, k + 1).reduce((s, v) => s + v, 0);
  const n = Math.max(la.length, lh.length);
  const stepMs = n > 4 ? 520 : 600;
  let k = 0;
  const tick = () => {
    const sa = cum(la, k), sh = cum(lh, k);
    const lab = k < 4 ? "Q" + (k + 1) : (n > 5 ? "Prol. " + (k - 3) : "Prolongation");
    for (const c of cells) {
      const mine = c.dataset.side === "away" ? sa : sh, other = c.dataset.side === "away" ? sh : sa;
      const el = c.querySelector(".n");
      el.textContent = mine;
      el.classList.remove("pop"); void el.offsetWidth; el.classList.add("pop");
      c.classList.toggle("lead", mine > other); c.classList.toggle("trail", mine < other);
    }
    sts.forEach(s => s.textContent = lab);
    k++;
    if (k < n) setTimeout(tick, stepMs);
    else setTimeout(() => finishReveal(g, true), stepMs + 100);
  };
  setTimeout(tick, 420); // le temps que les cases se retournent
}

/* ---------- vue « Matchs » (la nuit) ---------- */
async function renderNight(soft) {
  const main = $("#main");
  setURL();
  renderChips();
  if (!soft) main.innerHTML = `<div class="skel">${`<div class="ph" style="height:220px"></div><div class="ph" style="height:140px"></div><div class="ph" style="height:140px"></div>`}</div>`;
  let games;
  try { [games] = await Promise.all([scoreboard(state.night), loadVideos()]); }
  catch (e) { main.innerHTML = `<p class="loadmsg">Impossible de joindre ESPN pour cette nuit. Réessaie dans un instant.</p>`; return; }
  state.games = games;
  state.lastLoad = Date.now();
  if (settings.showAll) games.forEach(g => state.revealed.add(g.id));
  if (games.some(g => g.state !== "pre")) markSeen(state.night);
  if (games.some(g => g.state === "pre")) await loadPrevNight(state.night); // pour l'info « 2e soir »

  if (!games.length) { main.innerHTML = `<div class="nightline"><h1 class="night">${nightTitle(state.night)}</h1></div><p class="loadmsg">Pas de match cette nuit-là. 🏖️</p>`; scheduleRefresh(); return; }

  const scored = games.map(g => ({ g, lvl: watchLevel(g) })).sort((x, y) => y.lvl - x.lvl || jitter(x.g.id) - jitter(y.g.id));
  const hero = scored[0].lvl >= 4 ? scored[0] : null;
  const rest = games.filter(g => !hero || g.id !== hero.g.id)
    .sort((x, y) => {
      const fx = settings.fav && (x.teams.away.id === settings.fav || x.teams.home.id === settings.fav) ? 1 : 0;
      const fy = settings.fav && (y.teams.away.id === settings.fav || y.teams.home.id === settings.fav) ? 1 : 0;
      return fy - fx || watchLevel(y) - watchLevel(x) || x.date - y.date;
    });
  const nLive = games.filter(g => g.state === "live").length;
  const nFin = games.filter(g => g.state === "post").length;
  const meta = [`${games.length} match${games.length > 1 ? "s" : ""}`,
    nFin ? `${nFin} terminé${nFin > 1 ? "s" : ""}` : "",
    nLive ? `<span class="liv">${nLive} en cours</span>` : ""].filter(Boolean).join(" · ");

  const started = games.some(g => g.state !== "pre");
  const nr = started && !DEMO ? findNightRecap(state.night) : null;
  const jr = started && !DEMO ? findJournal(state.night) : null;
  const eyebrow = nLive ? "La nuit est en cours" : (nFin === games.length ? "Pendant que tu dormais" : (nFin ? "La nuit se termine" : "La nuit à venir"));
  main.innerHTML = `
    <p class="eyebrow">${eyebrow}<i></i></p>
    <div class="nightline"><h1 class="night">${nightTitle(state.night)}</h1>
      <span class="nnav">
        <button class="narrow" data-nav="-1" title="Nuit précédente">‹</button>
        <button class="narrow" data-nav="1" title="Nuit suivante">›</button>
        <button class="narrow" title="Choisir une date">📅<input type="date" id="dpick" value="${state.night.slice(0, 4)}-${state.night.slice(4, 6)}-${state.night.slice(6, 8)}"></button>
      </span></div>
    <div class="nsub"><span class="nmeta">${meta}</span>
      <span class="nbtns">
        ${nr ? `<button class="bt gold" data-vplay="${nr.id}" data-vlabel="Le résumé de la nuit NBA"><span class="pl">▶</span> Résumé de la nuit</button>` : ""}
        ${jr ? `<button class="bt extra" data-vplay="${jr.id}" data-vlabel="NBA Extra — le journal du matin"><i class="fr"></i>NBA Extra</button>` : ""}
        ${started ? `<button class="btn-all" id="revall">🎬 Révéler la nuit</button>` : ""}
      </span></div>
    ${hero ? heroHTML(hero.g, hero.lvl) : ""}
    ${rest.length ? `<div class="sect"><h2>${hero ? "Les autres matchs" : "Les matchs de la nuit"}</h2><i></i></div>
    <div class="grid">${rest.map((g, i) => cardHTML(g, i)).join("")}</div>` : ""}
    ${games.filter(g => g.state === "post").length >= 2 ? `
    <section class="hide-sect"><button class="teaser" id="mvpbtn"><span class="ti">💥</span>
      <span><b>Le MVP et les grosses perfs de la nuit</b><small>Qui a tout cassé cette nuit ? Révèle-le quand tu es prêt.</small></span>
      <span class="see">👁 Voir</span></button><div id="mvpbody"></div></section>` : ""}
    <div id="nextstrip"></div>`;

  for (const id of state.revealed) reveal(id, true);
  const all = $("#revall");
  if (all) all.addEventListener("click", () => {
    // la cérémonie : du moins bon au meilleur, le match de la nuit en dernier
    let order = games.filter(g => g.state !== "pre").sort((x, y) => watchLevel(x) - watchLevel(y));
    if (hero) order = order.filter(g => g.id !== hero.g.id).concat(games.filter(g => g.id === hero.g.id));
    let d = 0;
    for (const g of order) { setTimeout(() => reveal(g.id), d); d += RM ? 0 : 800; }
  });
  const dp = $("#dpick");
  if (dp) dp.addEventListener("change", () => { if (dp.value) { state.night = dp.value.replaceAll("-", ""); state.revealed.clear(); renderNight(); } });
  const mb = $("#mvpbtn");
  if (mb) mb.addEventListener("click", () => loadMVP(mb));
  nextStrip();
  renderChips();
  scheduleRefresh();
}

/* le MVP et les grosses perfs : calculés depuis les feuilles de match, derrière un teaser (spoil) */
const SUMCACHE = new Map();
async function cachedSummary(id) {
  if (!SUMCACHE.has(id)) SUMCACHE.set(id, await summary(id));
  return SUMCACHE.get(id);
}
const gscore = p => p.pts + 1.2 * p.reb + 1.5 * p.ast;
async function loadMVP(btn) {
  btn.disabled = true; btn.querySelector(".see").textContent = "…";
  const posts = state.games.filter(g => g.state === "post");
  const all = [];
  try {
    const sums = await Promise.all(posts.map(g => cachedSummary(g.id).catch(() => null)));
    sums.forEach((s, i) => { if (s) for (const p of s.players) all.push({ ...p, g: posts[i] }); });
  } catch (e) { /* au pire, rien */ }
  if (!all.length) { btn.querySelector(".see").textContent = "indisponible"; return; }
  all.sort((a, b) => gscore(b) - gscore(a));
  const mvp = all[0], t = team(mvp.tid);
  const opp = mvp.g.teams.away.id === mvp.tid ? mvp.g.teams.home : mvp.g.teams.away;
  const others = all.slice(1, 7);
  const photo = /^\d+$/.test(mvp.aid) ? `<img class="ph" src="https://a.espncdn.com/i/headshots/nba/players/full/${mvp.aid}.png" alt="" onerror="this.style.visibility='hidden'" style="--mc:${t.color}">` : `<span class="ph" style="--mc:${t.color}"></span>`;
  btn.hidden = true;
  $("#mvpbody").innerHTML = `<div class="mvpwrap">
    <div class="mvphead">${photo}
      <div class="mvpwho"><span class="mvptag">MVP DE LA NUIT</span>
        <h3>${mvp.full || mvp.name}</h3><small>${t.city} ${t.name} · contre ${opp.name}</small></div>
      <div class="mvpline">
        <div class="stile"><b>${mvp.pts}</b><small>points</small></div>
        <div class="stile"><b>${mvp.reb}</b><small>rebonds</small></div>
        <div class="stile"><b>${mvp.ast}</b><small>passes</small></div>
        <div class="stile"><b>${mvp.fg || "–"}</b><small>aux tirs</small></div>
      </div></div>
    <div class="opg">${others.map(p => { const pt = team(p.tid); return `<div class="op">${logoHTML(pt)}<b>${p.name}</b><small>${p.pts} pts · ${p.reb} rbd · ${p.ast} pas</small></div>`; }).join("")}</div>
  </div>`;
}

/* la nuit prochaine, en un clin d'œil */
async function nextStrip() {
  const el = $("#nextstrip"); if (!el || state.night !== defaultNight()) return;
  const next = addDays(state.night, 1);
  let games;
  try { games = await scoreboard(next); } catch (e) { return; }
  const pre = games.filter(g => g.state === "pre").sort((a, b) => a.date - b.date);
  if (!pre.length || state.night !== defaultNight()) return;
  const top = [...pre].sort((x, y) => watchLevel(y) - watchLevel(x))[0];
  el.innerHTML = `<div class="nextstrip"><span class="ti">🌙</span>
    <b>La nuit prochaine</b>
    <span>${pre.length} match${pre.length > 1 ? "s" : ""} · l'affiche : ${top.teams.away.name} @ ${top.teams.home.name} à ${hourLocal(top.date)}</span>
    <button class="bt" data-night-go="${next}">Voir le programme ›</button></div>`;
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
        <div class="fmid"><div class="fsc"><span class="${win === "home" ? "l" : ""}">${a.score}</span> – <span class="${win === "away" ? "l" : ""}">${h.score}</span></div>
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
    ${s.series ? `<div class="fsect"><h3>Le film du match<i></i></h3>${chartHTML(g, s.series)}</div>` : ""}
    ${s.quarters ? `<div class="fsect"><h3>Par quart-temps<i></i></h3>${quartersHTML(g, s)}</div>` : ""}
    ${s.players.length ? `<div class="fsect"><h3>Les patrons du match<i></i></h3>${prosHTML(s.players.slice(0, 6))}</div>` : ""}
    ${s.players.length ? `<div class="fsect"><h3>La feuille de match<i></i></h3>
      <p class="bx-hint">Touche un joueur pour voir tous ses tirs sur le terrain 🎯</p>
      ${boxHTML(g, s, "away")}${boxHTML(g, s, "home")}</div>` : ""}
    <div class="fbtns">${g.state === "post" ? `<button class="bt gold" data-resume="${g.id}"><span class="pl">▶</span> Résumé vidéo</button>` : ""}</div>
    <div class="next-note">Bientôt dans la fiche : face-à-face des deux équipes, avant-match détaillé, absents.</div>`;
  state.fiche = s; // pour la carte de tirs
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
  hookChart(g, s.series);
}
function closeFiche() { ovl.classList.remove("open"); document.body.style.overflow = ""; scheduleRefresh(); }

function chartHTML(g, pts) {
  const W = 720, H = 230, P = { l: 34, r: 14, t: 18, b: 26 };
  const N = pts.length - 1;
  const mx = Math.max(4, ...pts.map(Math.abs));
  const X = i => P.l + i * (W - P.l - P.r) / N, Y = v => P.t + (1 - (v + mx) / (2 * mx)) * (H - P.t - P.b);
  let dL = "", dP = `M${X(0)},${Y(0)}`, dN = `M${X(0)},${Y(0)}`;
  pts.forEach((v, i) => { dL += (i ? "L" : "M") + `${X(i)},${Y(v)}`; dP += `L${X(i)},${Y(Math.max(0, v))}`; dN += `L${X(i)},${Y(Math.min(0, v))}`; });
  dP += `L${X(N)},${Y(0)}Z`; dN += `L${X(N)},${Y(0)}Z`;
  const marks = []; for (let q = 12; q <= N; q += (q < 48 ? 12 : 5)) marks.push(q);
  const qs = marks.map(q => `<line x1="${X(q)}" y1="${P.t}" x2="${X(q)}" y2="${H - P.b}" stroke="rgba(255,255,255,.06)"/>
    <text x="${X(q) - 4}" y="${H - 8}" fill="#62667f" font-size="11" text-anchor="end">${q === N ? "Fin" : q <= 48 ? "Q" + Math.ceil(q / 12) : "P" + Math.ceil((q - 48) / 5)}</text>`).join("");
  const a = g.teams.away, h = g.teams.home;
  const mxi = pts.indexOf(Math.max(...pts)), mni = pts.indexOf(Math.min(...pts));
  const ann = (i, v, c, tri) => v === 0 ? "" : `<circle cx="${X(i)}" cy="${Y(v)}" r="3.5" fill="${c}" stroke="#0d0e18" stroke-width="2"/>
    <text x="${X(i)}" y="${Y(v) + (v > 0 ? -9 : 16)}" fill="#f2f3f8" font-size="12" font-weight="700" text-anchor="middle" font-family="Barlow Condensed">+${Math.abs(v)} ${tri}</text>`;
  return `<div class="chartbox">
  <svg class="chart" viewBox="0 0 ${W} ${H}">
    <path d="${dP}" fill="${h.color}" opacity=".3"/><path d="${dN}" fill="${a.color}" opacity=".3"/>${qs}
    <line x1="${P.l}" y1="${Y(0)}" x2="${W - P.r}" y2="${Y(0)}" stroke="rgba(255,255,255,.3)"/>
    <text x="${P.l}" y="${P.t + 2}" fill="#a8acc4" font-size="11">${h.name} devant</text>
    <text x="${P.l}" y="${H - P.b - 6}" fill="#a8acc4" font-size="11">${a.name} devant</text>
    <path d="${dL}" fill="none" stroke="#f2f3f8" stroke-width="2" stroke-linejoin="round" class="filmline"/>
    ${ann(mxi, pts[mxi], h.color, h.tri)}${ann(mni, pts[mni], a.color, a.tri)}
    <line class="cross" x1="0" y1="${P.t}" x2="0" y2="${H - P.b}" stroke="rgba(255,255,255,.35)" stroke-dasharray="3 3" visibility="hidden"/>
  </svg><div class="ttip"></div>
  <div class="clegend"><span><i style="background:${a.color}"></i>${a.name}</span><span><i style="background:${h.color}"></i>${h.name}</span></div></div>`;
}
function hookChart(g, pts) {
  if (!pts) return;
  const svg = sheet.querySelector(".chart"), tip = sheet.querySelector(".ttip"), cross = svg && svg.querySelector(".cross");
  if (!svg) return;
  const W = 720, P = { l: 34, r: 14 }, N = pts.length - 1;
  svg.addEventListener("pointermove", e => {
    const r = svg.getBoundingClientRect();
    const fx = (e.clientX - r.left) / r.width * W;
    const i = Math.max(0, Math.min(N, Math.round((fx - P.l) / (W - P.l - P.r) * N)));
    const v = pts[i], X = P.l + i * (W - P.l - P.r) / N;
    cross.setAttribute("x1", X); cross.setAttribute("x2", X); cross.setAttribute("visibility", "visible");
    tip.style.display = "block"; tip.style.left = (X / W * 100) + "%"; tip.style.top = "14px";
    const when = i === 0 ? "Début" : i >= N ? "Fin" : i <= 48 ? `Q${Math.min(4, Math.ceil(i / 12))} · ${i}ᵉ min` : `Prolongation`;
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
function prosHTML(players) {
  return `<div class="pros">` + players.map((p, i) => {
    const t = team(p.tid);
    return `<div class="pro" style="--mc:${t.color}">${i === 0 ? '<span class="mvp">TOP MATCH</span>' : ""}
      <div class="who"><b>${p.name}</b><small>${t.tri}</small></div>
      <div class="big">${p.pts}<small>pts</small></div>
      <div class="bars">
        <div class="bar"><em>PTS</em><div class="tr"><div class="fl" data-w="${Math.min(100, p.pts * 2)}"></div></div><b>${p.pts}</b></div>
        <div class="bar"><em>REB</em><div class="tr"><div class="fl" data-w="${Math.min(100, p.reb / 15 * 100)}"></div></div><b>${p.reb}</b></div>
        <div class="bar"><em>AST</em><div class="tr"><div class="fl" data-w="${Math.min(100, p.ast / 15 * 100)}"></div></div><b>${p.ast}</b></div>
      </div></div>`;
  }).join("") + `</div>`;
}

/* ---------- la feuille de match ---------- */
function boxHTML(g, s, side) {
  const t = g.teams[side];
  const list = s.players.filter(p => p.tid === t.id);
  if (!list.length) return "";
  const row = p => `<tr class="${p.shots.length ? "shootable" : ""}" ${p.shots.length ? `data-shot="${p.aid || p.name}"` : ""}>
    <td><span class="bxn">${p.name}</span>${p.shots.length ? `<span class="tgt">🎯</span>` : ""}</td>
    <td>${p.min}</td><td>${p.fg}</td><td>${p.tp}</td><td>${p.reb}</td><td>${p.ast}</td><td class="tot">${p.pts}</td></tr>`;
  return `<div class="bxteam"><div class="bxh" style="--mc:${t.color}">${logoHTML(t)}<b>${t.name}</b></div>
    <div class="qtwrap"><table class="qt bx"><thead><tr><th>Joueur</th><th>Min</th><th>Tirs</th><th>3 pts</th><th>Reb</th><th>Pas</th><th>Pts</th></tr></thead>
    <tbody>${list.map(row).join("")}</tbody></table></div></div>`;
}

/* ---------- la carte de tirs (tous les tirs du joueur, dans l'ordre du match) ---------- */
const shotovl = $("#shotovl"), shotsheet = $("#shotsheet");
function courtSVG(shots, color) {
  // repère ESPN : panier en (25, 5.25), x sur la largeur (0-50 pieds), y depuis la ligne de fond
  const S = 10, W = 500, H = 400; // on montre jusqu'à 40 pieds (au-delà : exploits de fin de quart)
  const hoop = { x: 25 * S, y: 5.25 * S };
  const lines = `
    <rect x="0" y="0" width="${W}" height="${H}" rx="10" fill="rgba(255,255,255,.025)"/>
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
      ? `<circle class="shot" cx="${cx}" cy="${cy}" r="7" fill="${color}" stroke="#07070d" stroke-width="2" style="animation-delay:${d}ms"/>`
      : `<g class="shot" style="animation-delay:${d}ms"><line x1="${cx - 6}" y1="${cy - 6}" x2="${cx + 6}" y2="${cy + 6}" stroke="#8a8fa8" stroke-width="2.5"/><line x1="${cx - 6}" y1="${cy + 6}" x2="${cx + 6}" y2="${cy - 6}" stroke="#8a8fa8" stroke-width="2.5"/></g>`;
  }).join("");
  return { svg: `<svg class="court" viewBox="0 0 ${W} ${H}">${lines}${marks}</svg>`, step };
}
let shotTimer = null;
function openShots(key) {
  const s = state.fiche; if (!s) return;
  const p = s.players.find(q => q.aid === key || q.name === key); if (!p) return;
  const t = team(p.tid);
  const made = p.shots.filter(x => x.m).length, three = p.shots.filter(x => x.v === 3);
  const { svg, step } = courtSVG(p.shots, t.color);
  shotsheet.innerHTML = `<div class="setbody">
    <button class="x" aria-label="Fermer">✕</button>
    <div class="shead" style="--mc:${t.color}">${logoHTML(t)}<div><h2>${p.full || p.name}</h2><small>${t.city} ${t.name}</small></div>
      <button class="bt replay" data-replay="${key}">↻ Rejouer</button></div>
    <div class="stiles">
      <div class="stile"><b>${p.pts}</b><small>points</small></div>
      <div class="stile"><b>${made}/${p.shots.length}</b><small>aux tirs</small></div>
      <div class="stile"><b>${three.filter(x => x.m).length}/${three.length}</b><small>à 3 points</small></div>
      <div class="stile"><b>${p.reb} · ${p.ast}</b><small>reb · passes</small></div>
    </div>
    ${svg}
    <div class="scount" id="scount">&nbsp;</div>
    <div class="clegend"><span><i style="background:${t.color};border-radius:50%"></i>Tir réussi</span><span style="color:#8a8fa8">✕ Tir raté</span></div>
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

/* ---------- vue « Programme » ---------- */
async function renderProgramme() {
  const main = $("#main");
  setURL();
  main.innerHTML = `<div class="skel"><div class="ph" style="height:120px"></div><div class="ph" style="height:120px"></div></div>`;
  const tonight = defaultNight();
  const keys = [...Array(7)].map((_, i) => addDays(tonight, i));
  let nights;
  try { nights = await Promise.all(keys.map(k => scoreboard(k).catch(() => []))); }
  catch (e) { main.innerHTML = `<p class="loadmsg">Impossible de joindre ESPN.</p>`; return; }
  main.innerHTML = keys.map((k, i) => {
    const games = nights[i].filter(g => g.state === "pre");
    if (!games.length) return "";
    const rows = games.sort((a, b) => a.date - b.date).map(g => {
      const a = g.teams.away, h = g.teams.home;
      const fav = settings.fav && (a.id === settings.fav || h.id === settings.fav);
      const hype = winpct(a.record) > .6 && winpct(h.record) > .6;
      return `<div class="prow ${fav ? "fav" : ""}">
        <span class="ph2">${hourLocal(g.date)}</span>
        <span class="plg">${logoHTML(a)}${logoHTML(h)}</span>
        <span class="pvs"><b>${a.name}</b><small>${a.record ? `(${a.record})` : ""} @</small><b>${h.name}</b><small>${h.record ? `(${h.record})` : ""}</small></span>
        <span class="ptag">${fav ? "★ Mon équipe" : hype ? "🔥 L'affiche" : ""}</span></div>`;
    }).join("");
    return `<section class="pnight"><h2>${nightTitle(k)}<small>${games.length} match${games.length > 1 ? "s" : ""}</small></h2>${rows}</section>`;
  }).join("") || `<p class="loadmsg">Aucun match programmé sur les 7 prochaines nuits.</p>`;
}

/* ---------- classement (sans spoil : la dernière nuit est retirée tant qu'on ne l'inclut pas) ---------- */
async function renderStandings() {
  const main = $("#main");
  setURL();
  main.innerHTML = `<p class="eyebrow">La hiérarchie<i></i></p>
    <div class="nightline"><h1 class="night">Le classement</h1></div>
    <div class="skel"><div class="ph" style="height:300px"></div></div>`;
  let data;
  try {
    data = DEMO ? await window.DEMO.standings()
      : await fetchJSON("https://site.api.espn.com/apis/v2/sports/basketball/nba/standings");
  } catch (e) { main.querySelector(".skel").outerHTML = `<p class="loadmsg">Impossible de charger le classement.</p>`; return; }
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
    return `<div class="conf"><h2>${c.name}</h2><div class="qtwrap"><table class="qt st">
      <thead><tr><th>Équipe</th><th>V</th><th>D</th><th>%</th><th>Écart</th>${cut ? "" : "<th>Série</th>"}</tr></thead>
      <tbody>${c.rows.map((r, i) => {
        const t = team(r.id);
        const gb = lead ? ((lead.w - r.w) + (r.l - lead.l)) / 2 : 0;
        const srk = r.streak ? r.streak.replace(/^W/, "V").replace(/^L/, "D") : "–";
        return `<tr class="${i < 6 ? "po" : i < 10 ? "pi" : ""} ${r.id === settings.fav ? "favrow" : ""}">
          <td><span class="rk">${i + 1}</span>${logoHTML(t)}<span class="stn">${t.name}</span></td>
          <td>${r.w}</td><td>${r.l}</td><td>${(pct(r) * 100).toFixed(1).replace(".", ",")}</td>
          <td>${gb === 0 ? "–" : gb.toFixed(1).replace(".0", "").replace(".", ",")}</td>${cut ? "" : `<td>${srk}</td>`}</tr>`;
      }).join("")}</tbody></table></div></div>`;
  };
  main.innerHTML = `<p class="eyebrow">La hiérarchie<i></i></p>
    <div class="nightline"><h1 class="night">Le classement</h1></div>
    <div class="cutbar">
      ${cutPossible ? `<span>${cut ? "Arrêté avant la dernière nuit, pour ne rien te gâcher." : "À jour, dernière nuit comprise."}</span>
      <button class="sw ${cut ? "" : "on"}" id="swcut" role="switch" aria-checked="${!cut}"></button>
      <span>Inclure la dernière nuit</span>` : `<span>Classement à jour.</span>`}
      <span style="margin-left:auto">🟢 1-6 play-offs · 🟠 7-10 play-in</span></div>
    <div class="standwrap">${confs.map(confHTML).join("")}</div>`;
  const sw = $("#swcut");
  if (sw) sw.addEventListener("click", () => { state.cutLast = !state.cutLast; renderStandings(); });
}

/* ---------- réglages ---------- */
const setovl = $("#setovl"), setsheet = $("#setsheet");
function openSettings() {
  const picker = Object.keys(TEAMS).map(id => {
    const t = team(+id);
    return `<button class="tpk ${settings.fav === +id ? "on" : ""}" data-fav="${id}">${logoHTML(t)}<b>${t.name}</b></button>`;
  }).join("");
  setsheet.innerHTML = `<div class="setbody">
    <button class="x" aria-label="Fermer">✕</button>
    <h2>Réglages</h2>
    <div><h3>Mon équipe</h3><div class="tpick">${picker}</div>
      ${settings.fav ? `<p style="margin:10px 0 0"><button class="bt" id="nofav">Ne plus suivre d'équipe</button></p>` : ""}</div>
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
  if (state.vue === "nuit") renderNight(true); else renderProgramme();
}

/* ---------- bande des nuits ---------- */
function renderChips() {
  const el = $("#nights");
  if (state.vue !== "nuit") { el.hidden = true; return; }
  el.hidden = false;
  const tonight = defaultNight();
  const last = state.night > tonight ? state.night : tonight;
  const keys = [...Array(7)].map((_, i) => addDays(last, i - 6));
  const live = state.games.some(g => g.state === "live");
  el.innerHTML = keys.map(k => {
    const c = chipText(k);
    const cur = k === state.night;
    let dot = "";
    if (k === tonight && k === state.night && live) dot = `<span class="dot red"></span>`;
    else if (k < tonight && !seen.has(k)) dot = `<span class="dot gold"></span>`;
    return `<button class="chip ${cur ? "on" : ""}" data-night="${k}"><small>${c.s}</small><b>${c.b}</b>${dot}</button>`;
  }).join("");
  // sur téléphone, centrer la bande sur la nuit affichée
  const on = el.querySelector(".chip.on");
  if (on) el.scrollLeft = on.offsetLeft - (el.clientWidth - on.offsetWidth) / 2;
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
  else { $("#nights").hidden = true; if (vue === "classement") renderStandings(); else renderProgramme(); }
}

/* ---------- événements globaux ---------- */
document.addEventListener("click", e => {
  const sc = e.target.closest(".sc:not(.rev):not(.pre)");
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
  if (e.target === vidovl || (e.target.closest(".x") && e.target.closest("#vidovl"))) { closeResume(); return; }
  if (e.target === shotovl || (e.target.closest(".x") && e.target.closest("#shotovl"))) { closeShots(); return; }
  if (e.target.closest("#gear") || e.target.closest("#gear2")) { openSettings(); return; }
  const tab = e.target.closest(".tab[data-vue]");
  if (tab) { go(tab.dataset.vue); return; }
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
    const sc = e.target.closest && e.target.closest(".sc:not(.rev):not(.pre)");
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
  w.innerHTML = `<div class="welcome"><p><b>Bienvenue !</b> Ici, aucun score ne s'affiche tant que <b>tu</b> ne l'as pas demandé :
    touche les cases « ? » pour révéler un match, et seulement celui-là. Bonne nuit NBA 🌙</p>
    <button class="bt gold" id="hellok">C'est parti</button></div>`;
  $("#hellok").addEventListener("click", () => { store.set("hello", true); w.hidden = true; });
}

/* ---------- démarrage ---------- */
(function init() {
  if (DEMO) { $("#demopill").hidden = false; $("#demopill2").hidden = false; }
  const nuit = QS.get("nuit");
  state.night = nuit && /^\d{4}-\d{2}-\d{2}$/.test(nuit) ? nuit.replaceAll("-", "") : defaultNight();
  welcome();
  loadVideos(); // en avance, pour que le premier clic « Résumé » soit instantané
  const vue = QS.get("vue");
  go(vue === "programme" ? "programme" : "nuit");
})();
