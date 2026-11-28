// Sonde ponctuelle (28/11) : comment ESPN et la NBA décrivent les matchs de la NBA Cup (groupes, tableau final), et si le
// navigateur peut les lire (en-têtes CORS). Lancée par .github/workflows/sonde-cup.yml, résultat dans le journal.
const get = async (u, raw) => { const r = await fetch(u); const h = r.headers.get("access-control-allow-origin"); const t = await r.text(); return { s: r.status, cors: h, j: raw ? t : (() => { try { return JSON.parse(t); } catch (e) { return null; } })() }; };
(async () => {
  const dates = [];
  for (let d = new Date("2026-10-28"); d <= new Date("2026-12-20"); d.setDate(d.getDate() + 1)) dates.push(d.toISOString().slice(0, 10).replace(/-/g, ""));
  let shown = 0;
  for (const k of dates) {
    const { s, cors, j } = await get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=" + k);
    if (k === dates[0]) console.log("scoreboard CORS:", cors, "status", s);
    for (const ev of (j && j.events) || []) {
      const c = ev.competitions[0];
      const notes = (c.notes || []).map(n => n.headline).join(" | ");
      const extra = JSON.stringify({ type: c.type, tournamentId: c.tournamentId, groups: c.groups, conferenceCompetition: c.conferenceCompetition, neutral: c.neutralSite, series: c.series && c.series.summary });
      if (notes || /cup|tournament/i.test(JSON.stringify(c).slice(0, 4000))) {
        const t = c.competitors.map(x => x.team.abbreviation + " " + (x.score || "") + (x.winner ? "*" : "")).join(" @ ");
        console.log(k, ev.id, c.status.type.state, t, "|| NOTES:", notes, "||", extra);
        if (shown++ < 1) { console.log("EXEMPLE COMPETITION:", JSON.stringify(c).slice(0, 3000)); console.log("EXEMPLE SEASON:", JSON.stringify(ev.season)); }
      }
    }
  }
  // la NBA : calendrier officiel (étiquettes des matchs de Coupe)
  const sch = await get("https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json");
  console.log("NBA schedule CORS:", sch.cors, "status", sch.s);
  if (sch.j) {
    const games = sch.j.leagueSchedule.gameDates.flatMap(d => d.games);
    const cup = games.filter(g => /cup/i.test((g.gameLabel || "") + (g.gameSubLabel || "") + (g.gameSubtype || "")));
    console.log("matchs de Coupe NBA:", cup.length);
    for (const g of cup.slice(0, 200)) console.log(g.gameDateEst, g.gameId, g.awayTeam.teamTricode, "@", g.homeTeam.teamTricode, "|", g.gameLabel, "|", g.gameSubLabel, "|", g.gameSubtype, "|", g.seriesText, "|", g.ifNecessary, "|", g.arenaName);
    if (cup[0]) console.log("EXEMPLE NBA:", JSON.stringify(cup[0]).slice(0, 2500));
  }
  for (const u of ["https://cdn.nba.com/static/json/staticData/EmiratesNBACupBracket.json", "https://cdn.nba.com/static/json/liveData/cup/bracket.json",
    "https://stats.nba.com/stats/iststandings?LeagueID=00&Season=2026-27&Section=group", "https://site.api.espn.com/apis/v2/sports/basketball/nba/standings?group=cup"]) {
    try { const r = await get(u, true); console.log("SONDE", u, r.s, "cors", r.cors, String(r.j).slice(0, 600)); } catch (e) { console.log("SONDE", u, "ERR", e.message); }
  }
})();
