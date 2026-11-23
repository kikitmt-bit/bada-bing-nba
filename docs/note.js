"use strict";
/* ============================================================
   Nocturne — la note « à voir » d'un match terminé, calculée sur son déroulé ESPN (action par action).
   Mêmes règles sur le site (navigateur) et dans l'étalonnage (node scripts/notes_calib.js).
   Entrée : le JSON brut de summary?event=… ; sortie : { s (note continue), lvl (0 à 5), f (les ingrédients) }.
   Niveaux : 0 À fuir · 1 Bof · 2 Sans plus · 3 Sympa · 4 À voir · 5 Immanquable.
   ============================================================ */
const Note = (() => {
  const secOf = d => { let m = /^(\d+):(\d+)/.exec(d || ""); if (m) return +m[1] * 60 + +m[2]; m = /^(\d+(?:\.\d)?)$/.exec(d || ""); return m ? +m[1] : 0; };
  const el = (per, sec) => per <= 4 ? (per - 1) * 720 + 720 - sec : 2880 + (per - 5) * 300 + 300 - sec; // secondes de jeu écoulées
  // seuils des niveaux (étalonnés sur les matchs de la saison 2026-27, voir scripts/notes_calib.js)
  const CUT = [1.0, 2.2, 3.6, 5.2, 7.2];

  function features(j) {
    const comps = j.header.competitions[0].competitors;
    const home = comps.find(c => c.homeAway === "home"), away = comps.find(c => c.homeAway === "away");
    const hs = +home.score || 0, as = +away.score || 0;
    const P = (j.plays || []).map(p => ({ per: p.period ? p.period.number : 1, sec: secOf(p.clock && p.clock.displayValue), hs: +p.homeScore || 0, as: +p.awayScore || 0 }))
      .filter(p => p.per >= 1);
    if (P.length < 30) return null;
    const nper = Math.max(4, ...P.map(p => p.per)), end = el(nper, 0);
    const win = Math.sign(hs - as); // + = domicile
    // l'écart (+ = domicile devant) à un instant donné
    const at = t => { let d = 0; for (const p of P) { if (el(p.per, p.sec) > t) break; d = p.hs - p.as; } return d; };
    let lc = 0, ties = 0, clutch = 0, lead = 0, prev = 0, maxDef = 0, lastGo = null, minLate = Infinity, maxLate = 0;
    for (const p of P) {
      const d = p.hs - p.as, t = el(p.per, p.sec);
      if (d === prev) continue;
      const sg = Math.sign(d);
      if (sg === 0) { ties++; if (t >= 2580) clutch++; } // égalité
      else if (lead && sg !== lead) { lc++; if (t >= 2580) clutch++; }
      if (sg && sg !== lead) { if (sg === win) lastGo = t; lead = sg; } else if (sg === 0) lead = 0;
      if (win && Math.sign(d) === -win) maxDef = Math.max(maxDef, Math.abs(d)); // le vainqueur mené de…
      prev = d;
    }
    // le match plié : l'écart pendant les 8 dernières minutes du temps réglementaire
    for (let t = 2400; t <= 2880; t += 30) { const a = Math.abs(at(t)); minLate = Math.min(minLate, a); maxLate = Math.max(maxLate, a); }
    // les perfs (feuille de match)
    let top = 0, td = 0;
    try {
      for (const side of j.boxscore.players || []) {
        const st = side.statistics[0], ix = n => st.names.indexOf(n), iP = ix("PTS"), iR = ix("REB"), iA = ix("AST");
        for (const a of st.athletes || []) {
          if (!a.stats || !a.stats.length) continue;
          const pts = +a.stats[iP] || 0, reb = +a.stats[iR] || 0, ast = +a.stats[iA] || 0;
          top = Math.max(top, pts);
          if (pts >= 10 && reb >= 10 && ast >= 10) td++;
        }
      }
    } catch (e) { /* pas de feuille */ }
    return {
      fm: Math.abs(hs - as), ot: nper - 4, tot: hs + as,
      m5: Math.abs(at(2580)), m2: Math.abs(at(2760)), // écart à 5 min et 2 min de la fin du temps réglementaire
      lc, ties, clutch, maxDef, go: lastGo === null ? null : end - lastGo, // secondes restantes au panier qui donne l'avance pour de bon
      minLate, maxLate, top, td,
    };
  }
  function score(f) {
    let s = 0;
    // la fin de match
    if (f.ot) s += 3 + 1.8 + (f.ot - 1) * 1.2;
    else s += f.m2 <= 3 ? 3 : f.m2 <= 6 ? 2.2 : f.m2 <= 9 ? 1.3 : f.m2 <= 12 ? .6 : 0;
    s += f.fm <= 3 ? 1 : f.fm <= 5 ? .5 : 0;
    s += Math.min(2, .45 * f.clutch); // retournements et égalités dans les 5 dernières minutes (et la prolongation)
    if (f.go !== null) s += f.go <= 5 ? 1.5 : f.go <= 24 ? .8 : f.go <= 60 ? .3 : 0; // panier décisif
    // le scénario
    s += f.maxDef >= 20 ? 2 : f.maxDef >= 15 ? 1.4 : f.maxDef >= 10 ? .7 : 0; // remontée du vainqueur
    s += f.lc >= 20 ? .8 : f.lc >= 12 ? .4 : 0;
    // plié tôt : écart toujours ≥ 15 (ou 20) pendant les 8 dernières minutes
    if (!f.ot) s -= f.minLate >= 20 ? 2.5 : f.minLate >= 15 ? 1.5 : f.minLate >= 11 ? .6 : 0;
    // le spectacle
    s += f.top >= 55 ? 2.2 : f.top >= 50 ? 1.8 : f.top >= 45 ? 1.3 : f.top >= 40 ? .8 : f.top >= 35 ? .3 : 0;
    s += f.td ? .5 : 0;
    s += f.tot >= 250 ? .5 : f.tot >= 240 ? .25 : 0;
    return Math.round(s * 100) / 100;
  }
  const level = s => CUT.filter(c => s >= c).length;
  function rate(j) {
    let f = null; try { f = features(j); } catch (e) { return null; }
    if (!f) return null;
    const s = score(f);
    return { s, lvl: level(s), f };
  }
  return { rate, score, level, features, CUT };
})();
if (typeof module !== "undefined") module.exports = Note;
