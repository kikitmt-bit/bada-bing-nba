"use strict";
/* ============================================================
   Bada Bing NBA v2 — mode démo (?demo=1)
   Une fausse saison, stable d'un chargement à l'autre, pour
   voir le site sans ESPN (l'équivalent de BB_FAUX_ESPN=1).
   Mêmes formes de données que normEvent / normSummary d'app.js.
   ============================================================ */
(function () {
  const STARS = {
    1: "T. Young", 2: "J. Tatum", 3: "Z. Williamson", 4: "C. White", 5: "D. Mitchell",
    6: "L. Dončić", 7: "N. Jokić", 8: "C. Cunningham", 9: "S. Curry", 10: "A. Şengün",
    11: "T. Haliburton", 12: "K. Leonard", 13: "L. James", 14: "T. Herro", 15: "G. Antetokounmpo",
    16: "A. Edwards", 17: "C. Thomas", 18: "J. Brunson", 19: "P. Banchero", 20: "J. Embiid",
    21: "D. Booker", 22: "S. Henderson", 23: "D. Sabonis", 24: "V. Wembanyama", 25: "S. Gilgeous-Alexander",
    26: "L. Markkanen", 27: "J. Poole", 28: "S. Barnes", 29: "J. Morant", 30: "B. Miller",
  };
  function rng(seedStr) {
    let s = 0; for (const c of seedStr) s = (s * 31 + c.charCodeAt(0)) % 2147483647;
    return () => (s = (s * 48271) % 2147483647) / 2147483647;
  }
  const cache = new Map(); // id → {game, key}

  function makeGames(key) {
    const r = rng("nuit" + key);
    const tonight = (function () { // même calcul que app.js, sans dépendre de lui
      return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" })
        .format(new Date(Date.now() - 8 * 3600e3)).replaceAll("-", "");
    })();
    const ids = [...Array(30)].map((_, i) => i + 1).sort(() => r() - .5);
    const n = 3 + Math.floor(r() * 4); // 3 à 6 matchs
    const games = [];
    const base = Date.UTC(+key.slice(0, 4), +key.slice(4, 6) - 1, +key.slice(6, 8), 24, 0); // ~ 19h New York
    for (let k = 0; k < n; k++) {
      const away = ids[k * 2], home = ids[k * 2 + 1];
      const id = key + "-" + k;
      const date = new Date(base + Math.floor(r() * 4) * 1800e3 + k * 600e3);
      let st = "post";
      if (key > tonight) st = "pre";
      else if (key === tonight) st = k === n - 1 ? "live" : (k === 0 ? "pre" : "post");
      const sa = 92 + Math.floor(r() * 40), diff = Math.floor(r() * 24) - 11;
      const sb = Math.max(85, sa + (diff === 0 ? 2 : diff));
      const ot = st === "post" && Math.abs(sa - sb) <= 3 && r() < .35;
      const W = t => `${6 + Math.floor(r() * 7)}-${2 + Math.floor(r() * 7)}`;
      const g = {
        id, date, state: st, period: st === "live" ? 3 : st === "post" ? (ot ? 5 : 4) : 0,
        clock: st === "live" ? "04:1" + Math.floor(r() * 9) : "",
        ot,
        teams: {
          away: { id: away, score: st === "pre" ? 0 : (st === "live" ? Math.floor(sa * .6) : sa), record: W() },
          home: { id: home, score: st === "pre" ? 0 : (st === "live" ? Math.floor(sb * .6) : sb), record: W() },
        },
        leaders: st === "post" ? [{ name: STARS[away], pts: 22 + Math.floor(r() * 25) }, { name: STARS[home], pts: 20 + Math.floor(r() * 22) }] : [],
      };
      // app.js complète tri/couleurs via team() : on les fusionne ici comme normEvent le ferait
      cache.set(id, g);
      games.push(g);
    }
    return games;
  }

  window.DEMO = {
    scoreboard(key) {
      const games = makeGames(key).map(g => ({
        ...g,
        teams: {
          away: { ...window.__team(g.teams.away.id), ...g.teams.away },
          home: { ...window.__team(g.teams.home.id), ...g.teams.home },
        },
      }));
      return Promise.resolve(games);
    },
    summary(id) {
      const g = cache.get(id);
      if (!g) return Promise.reject(new Error("démo : match inconnu"));
      const r = rng("sum" + id);
      const tot = { away: g.teams.away.score, home: g.teams.home.score };
      const split = (t, ot) => {
        const nq = ot ? 5 : 4, base = Math.floor(t / nq), q = []; let s = 0;
        for (let k = 0; k < nq - 1; k++) { const v = base + Math.floor(r() * 9) - 4; q.push(v); s += v; }
        q.push(t - s); return q;
      };
      const fin = tot.home - tot.away, N = g.state === "live" ? 32 : (g.ot ? 53 : 48);
      const pts = [0];
      for (let k = 1; k < N; k++) pts.push(Math.round(fin * k / N + (r() - .5) * 14 * Math.sin(k / N * Math.PI)));
      pts.push(g.state === "live" ? g.teams.home.score - g.teams.away.score : fin);
      const players = [];
      for (const side of ["away", "home"]) {
        const tid = g.teams[side].id;
        players.push({ name: STARS[tid], tid, pts: 20 + Math.floor(r() * 25), reb: 3 + Math.floor(r() * 10), ast: 2 + Math.floor(r() * 10) });
        players.push({ name: "R. Dubois", tid, pts: 8 + Math.floor(r() * 14), reb: 2 + Math.floor(r() * 7), ast: 1 + Math.floor(r() * 6) });
        players.push({ name: "M. Lefranc", tid, pts: 5 + Math.floor(r() * 12), reb: 1 + Math.floor(r() * 6), ast: 1 + Math.floor(r() * 5) });
      }
      players.sort((a, b) => (b.pts + 1.2 * b.reb + 1.5 * b.ast) - (a.pts + 1.2 * a.reb + 1.5 * a.ast));
      return Promise.resolve({
        quarters: {
          away: { id: g.teams.away.id, q: split(tot.away, g.ot), tot: tot.away },
          home: { id: g.teams.home.id, q: split(tot.home, g.ot), tot: tot.home },
        },
        series: pts, players, ot: g.ot,
      });
    },
  };
})();
