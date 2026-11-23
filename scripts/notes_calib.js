// Étalonnage de la note « à voir » (docs/note.js) sur les vrais matchs : node scripts/notes_calib.js [AAAAMMJJ début] [AAAAMMJJ fin]
// Affiche chaque match (ingrédients, note, niveau), puis la répartition des notes. ESPN est joignable depuis GitHub Actions.
const Note = require("../docs/note.js");
const API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/";
const get = async u => { for (let i = 0; i < 4; i++) { try { const r = await fetch(u); if (r.ok) return r.json(); } catch (e) { /* on réessaie */ } await new Promise(r => setTimeout(r, 800)); } throw new Error("ESPN " + u); };
const day = s => new Date(Date.UTC(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)));
const key = d => d.toISOString().slice(0, 10).replaceAll("-", "");
(async () => {
  const from = process.argv[2] || "20261020", to = process.argv[3] || key(new Date(Date.now() - 864e5));
  const rows = [];
  for (let d = day(from); d <= day(to); d = new Date(+d + 864e5)) {
    const sb = await get(API + "scoreboard?dates=" + key(d));
    const evs = (sb.events || []).filter(e => e.status && e.status.type && e.status.type.state === "post");
    const res = await Promise.all(evs.map(async e => { try { return [e, Note.rate(await get(API + "summary?event=" + e.id))]; } catch (x) { return [e, null]; } }));
    for (const [e, r] of res) {
      if (!r) continue;
      const c = e.competitions[0].competitors, A = c.find(x => x.homeAway === "away"), H = c.find(x => x.homeAway === "home");
      rows.push({ d: key(d), id: e.id, m: `${A.team.abbreviation} ${A.score}-${H.score} ${H.team.abbreviation}`, ...r });
    }
  }
  rows.sort((a, b) => b.s - a.s);
  const N = ["FUIR", "BOF ", "SANS", "SYMP", "VOIR", "IMMA"];
  for (const r of rows) { const f = r.f;
    console.log(`${r.s.toFixed(2).padStart(6)} ${N[r.lvl]} ${r.d} ${r.m.padEnd(17)} cl3=${f.close} m2=${f.m2} m5=${f.m5} fm=${f.fm} ot=${f.ot} cl=${f.clutch} lc=${f.lc} go=${f.go === null ? "-" : Math.round(f.go)} def=${f.maxDef} late=${f.minLate} top=${f.top}${f.td ? " TD" : ""} tot=${f.tot}`); }
  const n = rows.length, cnt = [0, 0, 0, 0, 0, 0]; rows.forEach(r => cnt[r.lvl]++);
  console.log("\n" + n + " matchs ; répartition :", N.map((x, i) => `${x} ${cnt[i]} (${Math.round(100 * cnt[i] / n)} %)`).join(" · "));
  const q = p => rows[Math.min(n - 1, Math.floor(n * p))].s;
  console.log("centiles (du haut) : 5 % " + q(.05) + " · 10 % " + q(.1) + " · 20 % " + q(.2) + " · 35 % " + q(.35) + " · 50 % " + q(.5) + " · 70 % " + q(.7) + " · 85 % " + q(.85));
})();
