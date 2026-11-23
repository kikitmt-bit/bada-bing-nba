"use strict";
/* ============================================================
   Nocturne — stats en direct sur le résumé vidéo (prototype)
   Le site ne peut pas lire l'image d'un lecteur YouTube intégré.
   Avec l'accord du visiteur (partage de l'onglet, comme en visio),
   on lit le bandeau du match à l'écran (quart-temps + chrono) avec
   tesseract.js, puis on recalcule les stats ESPN jusqu'à ce moment.
   Rien ne sort du navigateur. Sans spoil : jamais au-delà de l'écran.
   ============================================================ */
const Chrono = (() => {
  // le mode direct (partage de l'onglet + lecture du chrono) n'est plus proposé (pas assez fiable, choix de Kiki) : seulement avec ?live=1 pour les essais.
  // Sans table préparée, le Replay est la vidéo seule ; « Replay + » = table préparée par le téléphone-serveur.
  const CAN = QS.has("live") && (DEMO || !!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia) && !/Android|iPhone|iPad|Mobile/i.test(navigator.userAgent));
  const TESS = "https://cdn.jsdelivr.net/npm/tesseract.js@5.1.1/dist/tesseract.min.js";
  let S = null; // session en cours (un match, un lecteur)

  /* ---------- le déroulé ESPN, réduit à ce qui sert ---------- */
  const secOf = d => { // « 11:12 » → 672 ; « 45.3 » → 45.3
    let m = /^(\d+):(\d+)/.exec(d || ""); if (m) return +m[1] * 60 + +m[2];
    m = /^(\d+(?:\.\d)?)$/.exec(d || ""); return m ? +m[1] : 0;
  };
  function parsePlays(j) {
    const names = {};
    try {
      for (const side of j.boxscore.players || []) for (const a of side.statistics[0].athletes || [])
        if (a.athlete) names[String(a.athlete.id)] = { n: a.athlete.shortName || a.athlete.displayName, t: +side.team.id, st: !!a.starter, o: Object.keys(names).length };
    } catch (e) { /* pas de feuille */ }
    let ids = {};
    try { for (const c of j.header.competitions[0].competitors) ids[c.homeAway] = +c.team.id; } catch (e) { /* */ }
    const plays = (j.plays || []).map(p => {
      const tt = (p.type && p.type.text) || "", tx = p.text || "";
      const pa = (p.participants || []).map(x => x.athlete ? String(x.athlete.id) : "");
      let sx = null, sy = null;
      if (p.shootingPlay && p.coordinate && !/free throw/i.test(tt)) {
        let { x, y } = p.coordinate;
        if (y > 47) { y = 94 - y; x = 50 - x; }
        y += 5.25; // ESPN mesure y depuis le PANIER (vérifié : 3 pts tous derrière la ligne) ; le dessin, depuis la ligne de fond
        if (x >= 0 && x <= 50 && y >= 0 && y <= 47) { sx = x; sy = y; }
      }
      return { sx, sy,
        per: p.period ? p.period.number : 1, sec: secOf(p.clock && p.clock.displayValue),
        clk: p.clock ? p.clock.displayValue : "", tid: p.team ? +p.team.id : 0,
        hs: +p.homeScore || 0, as: +p.awayScore || 0, tx, tt,
        shoot: !!p.shootingPlay, made: !!p.scoringPlay,
        ft: /free throw/i.test(tt), three: p.pointsAttempted ? p.pointsAttempted === 3 : /three point/i.test(tx),
        a0: pa[0] || "", a1: pa[1] || "", ast: /assists?\)/i.test(tx), stl: /steals?\)/i.test(tx), blk: /\bblocks\b/i.test(tx),
      };
    });
    return { names, plays, home: ids.home, away: ids.away };
  }

  /* ---------- démo : un faux déroulé plausible ---------- */
  function demoPlays(sum, g) {
    let seed = 7; for (const c of g.id) seed = (seed * 31 + c.charCodeAt(0)) % 99991;
    const r = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    const names = {}; sum.players.forEach((p, i) => { names[p.aid] = { n: p.name, t: p.tid, st: true, o: i }; });
    const home = g.teams.home.id, away = g.teams.away.id;
    const roster = t => sum.players.filter(p => p.tid === t);
    const plays = []; let hs = 0, as = 0;
    const nq = sum.ot ? 5 : 4;
    for (let per = 1; per <= nq; per++) {
      let sec = per <= 4 ? 720 : 300, side = per % 2 ? away : home;
      while ((sec -= 8 + Math.floor(r() * 22)) > 0) {
        const ro = roster(side), sh = ro[Math.floor(r() * r() * ro.length)];
        const three = r() < .36, made = r() < (three ? .37 : .52), val = three ? 3 : 2;
        const mm = Math.floor(sec / 60), ss = String(Math.floor(sec % 60)).padStart(2, "0"), clk = sec >= 60 ? `${mm}:${ss}` : (sec % 60).toFixed(1);
        let a1 = "", ast = false;
        if (made) { if (side === home) hs += val; else as += val; if (r() < .6) { const o = ro.filter(p => p !== sh); a1 = o[Math.floor(r() * o.length)].aid; ast = true; } }
        plays.push({ per, sec, clk, tid: side, hs, as, tt: "Shot", tx: `${sh.name} ${made ? "makes" : "misses"} ${three ? "three point jumper" : "driving layup"}${ast ? ` (${names[a1].n} assists)` : ""}`,
          shoot: true, made, ft: false, three, a0: sh.aid, a1, ast, stl: false });
        if (!made) { const t2 = r() < .73 ? (side === home ? away : home) : side; const rb = roster(t2)[Math.floor(r() * 4)];
          plays.push({ per, sec, clk, tid: t2, hs, as, tt: (t2 === side ? "Offensive" : "Defensive") + " Rebound", tx: `${rb.name} ${t2 === side ? "offensive" : "defensive"} rebound`, shoot: false, made: false, ft: false, three: false, a0: rb.aid, a1: "", ast: false, stl: false });
          side = t2; }
        else side = side === home ? away : home;
        if (r() < .08) { plays.push({ per, sec, clk, tid: side, hs, as, tt: "Bad Pass Turnover", tx: `${roster(side)[0].name} bad pass (turnover)`, shoot: false, made: false, ft: false, three: false, a0: roster(side)[0].aid, a1: "", ast: false, stl: false }); side = side === home ? away : home; }
      }
    }
    return { names, plays, home, away };
  }

  const DEBUG = QS.has("debug");
  function playIndex(D, at) { // nombre d'actions déjà passées : les stats ne changent qu'avec lui
    let n = 0; for (const p of D.plays) { if (p.per > at.per || (p.per === at.per && p.sec <= at.sec)) break; n++; } return n;
  }
  /* ---------- les stats jusqu'au moment affiché ---------- */
  function statsAt(D, per, sec) {
    const T = {}; const P = {};
    for (const t of [D.home, D.away]) T[t] = { fg: 0, fga: 0, tp: 0, tpa: 0, ftm: 0, fta: 0, reb: 0, ast: 0, to: 0, pf: 0, blk: 0 };
    let hs = 0, as = 0, last = [];
    const pl = id => P[id] || (P[id] = { pts: 0, reb: 0, ast: 0, blk: 0, fg: 0, fga: 0, tp: 0, tpa: 0 });
    for (const p of D.plays) {
      if (p.per > per || (p.per === per && p.sec <= sec)) break; // strictement avant le moment affiché : jamais en avance
      hs = p.hs; as = p.as;
      const t = T[p.tid];
      if (!t) continue;
      if (p.shoot) {
        if (p.ft) { t.fta++; if (p.made) t.ftm++; }
        else { t.fga++; if (p.made) t.fg++; if (p.three) { t.tpa++; if (p.made) t.tp++; } }
        if (p.a0) { const q = pl(p.a0); if (!p.ft) { q.fga++; if (p.made) q.fg++; if (p.three) { q.tpa++; if (p.made) q.tp++; } } if (p.made) q.pts += p.ft ? 1 : p.three ? 3 : 2; }
        if (p.made && p.ast && p.a1) { pl(p.a1).ast++; t.ast++; }
        if (!p.made && p.blk && p.a1) { pl(p.a1).blk++; const o = T[p.tid === D.home ? D.away : D.home]; if (o) o.blk++; } // le contreur est le 2e nommé, dans l'autre équipe
      } else if (/rebound/i.test(p.tt)) { if (p.a0) { t.reb++; pl(p.a0).reb++; } } // rebonds « d'équipe » exclus, comme la feuille ESPN
      else if (/turnover/i.test(p.tt)) t.to++;
      else if (/foul/i.test(p.tt) && !/technical/i.test(p.tt)) t.pf++;
      if (p.shoot || /rebound|turnover/i.test(p.tt)) last.push(p);
    }
    return { T, P, hs, as, last: last.slice(-3).reverse() };
  }
  function fr(tx) { // le texte ESPN, en français approximatif
    return tx.replace(/\bmakes\b/g, "réussit").replace(/\bmisses\b/g, "rate")
      .replace(/three point (jumper|jump shot|shot|pullup jump shot|step back jump shot)/gi, "un tir à 3 pts")
      .replace(/free throw (\d) of (\d)/gi, "le lancer franc $1/$2").replace(/\b(\d+)-foot\b/g, "à $1 pieds,")
      .replace(/driving floating (jump shot|jumper|bank jump shot)/gi, "un floater en pénétration").replace(/running (jump shot|jumper|pullup jump shot)/gi, "un tir en course")
      .replace(/driving (layup|dunk)/gi, "$1 en pénétration").replace(/\blayup\b/gi, "un lay-up").replace(/\bdunk\b/gi, "un dunk")
      .replace(/(pullup |step back |turnaround |fadeaway )?jump(er| shot)/gi, "un tir").replace(/defensive rebound/gi, "rebond défensif")
      .replace(/offensive rebound/gi, "rebond offensif").replace(/\((.+?) assists\)/g, "(passe de $1)").replace(/bad pass/gi, "mauvaise passe")
      .replace(/\(turnover\)|turnover/gi, "(balle perdue)").replace(/\((.+?) steals\)/g, "(interception de $1)").replace(/blocks/g, "contre");
  }

  /* ---------- lecture du bandeau ----------
     1) Recherche : on lit le bas de la vidéo pour trouver le quart-temps (« 1ST », « 2ND »…).
     2) Verrou : on ne lit plus qu'une petite zone autour (chrono + quart-temps), inversée,
        en mode « bloc de texte » de tesseract : ~0,1 s par lecture et fiable. */
  const QRX = /^(?:([1lIi|!])[sS58][tT7]|(2)[nN][dD0]|(3)[rR][dD0]|(4)[tT][hH]|([0O]T|2[0O]T|3[0O]T))/;
  function readQuarter(s) {
    const m = QRX.exec(s); if (!m) return 0;
    if (m[1]) return 1; if (m[2]) return 2; if (m[3]) return 3; if (m[4]) return 4;
    return 4 + (+m[5][0] > 1 ? +m[5][0] : 1);
  }
  function readClock(s) { // renvoie [secondes, variante] ; « 1:05 » peut être un « 11:05 » mal lu
    s = s.replace(/[oO]/g, "0").replace(/[lI|!]/g, "1");
    let m = /(?:^|[^\d])(n|\d{1,2})[:;](\d{2})(?!\d)/.exec(" " + s);
    if (m) {
      const mm = m[1] === "n" ? 11 : +m[1], ss = +m[2];
      if (mm <= 12 && ss < 60 && mm * 60 + ss <= 720) return [mm * 60 + ss, m[1].length === 1 && mm <= 2 ? (mm + 10) * 60 + ss : null];
    }
    m = /^(\d{1,2})\.(\d)$/.exec(s); // dernière minute : « 45.3 »
    if (m && +m[1] < 60) return [+m[1] + +m[2] / 10, null];
    return null;
  }
  const bx = w => w.bbox;
  function findQuarter(words) {
    let q = null;
    for (const w of words) { const per = readQuarter(w.text.trim()); if (per && (!q || w.confidence > q.w.confidence)) q = { per, w }; }
    return q;
  }
  function findClock(words, near) { // le chrono le plus proche du quart-temps (évite le minutage YouTube « 0:01 / 9:54 »)
    let best = null;
    const nb = near && bx(near), h = nb ? Math.max(6, nb.y1 - nb.y0) : 0;
    for (const w of words) {
      if (near && w === near) continue;
      const c = readClock(w.text.trim()); if (!c) continue;
      let d = 0;
      if (nb) {
        const b = bx(w), dx = (b.x0 + b.x1 - nb.x0 - nb.x1) / 2, dy = (b.y0 + b.y1 - nb.y0 - nb.y1) / 2;
        d = Math.hypot(dx, dy * 1.5); if (d > h * 10) continue;
      }
      if (!best || d < best.d) best = { sec: c[0], alt: c[1], d, w };
    }
    return best;
  }

  let WORKER = null;
  function worker() {
    return WORKER || (WORKER = (async () => {
      if (!window.Tesseract) await new Promise((ok, ko) => { const s = document.createElement("script"); s.src = TESS; s.onload = ok; s.onerror = ko; document.head.appendChild(s); });
      return Tesseract.createWorker("eng");
    })().catch(e => { WORKER = null; throw e; }));
  }
  let PSM = "";
  async function ocr(canvas, psm) {
    const w = await worker();
    if (PSM !== psm) { await w.setParameters({ tessedit_pageseg_mode: psm }); PSM = psm; }
    const { data } = await w.recognize(canvas);
    return (data.words || []).filter(x => x.text && x.text.trim());
  }
  let CV = null;
  function prep(src, sx, sy, sw, sh, scale, mode) { // mode : "inv" (texte clair → noir), "thr", "gray"
    const c = CV || (CV = document.createElement("canvas"));
    c.width = Math.max(8, Math.round(sw * scale)); c.height = Math.max(8, Math.round(sh * scale));
    const x = c.getContext("2d", { willReadFrequently: true });
    x.imageSmoothingQuality = "high";
    x.drawImage(src, sx, sy, sw, sh, 0, 0, c.width, c.height);
    const d = x.getImageData(0, 0, c.width, c.height), p = d.data;
    for (let i = 0; i < p.length; i += 4) {
      const g = .3 * p[i] + .59 * p[i + 1] + .11 * p[i + 2];
      const v = mode === "gray" ? g : mode === "inv" ? (g > 150 ? 0 : 255) : (g > 150 ? 255 : 0);
      p[i] = p[i + 1] = p[i + 2] = v;
    }
    x.putImageData(d, 0, 0);
    return c;
  }
  const clip = (r, W, H) => { const x = Math.max(0, r.x), y = Math.max(0, r.y); return { x, y, w: Math.max(4, Math.min(W, r.x + r.w) - x), h: Math.max(4, Math.min(H, r.y + r.h) - y) }; };

  // une lecture ; R = place de la vidéo dans l'image (ou toute l'image en secours)
  async function readFrame(src, W, H, R) {
    S.reads++;
    if (S.lock) {
      const L = clip(S.lock, W, H), scale = Math.max(1.5, Math.min(4, 210 / L.h));
      const mode = S.polar ? "thr" : "inv";
      const c = prep(src, L.x, L.y, L.w, L.h, scale, mode);
      const words = await ocr(c, "6");
      S.diagTxt = words.map(w => w.text).join(" "); if (S.diag) S.diagImg = c.toDataURL("image/png");
      const q = findQuarter(words), k = findClock(words, q && q.w);
      if (!k) { S.polar = !S.polar; return null; }
      const per = q ? q.per : S.at ? S.at.per : 0;
      return per ? { per, sec: k.sec, alt: k.alt, sure: !!q } : null;
    }
    // recherche du bandeau (le bas de la vidéo, agrandi)
    const A = clip({ x: R.x, y: R.y + R.h * .7, w: R.w, h: R.h * .3 }, W, H);
    const scale = Math.max(.8, Math.min(2.4, 2000 / A.w));
    const mode = S.polar ? "inv" : "gray";
    const c = prep(src, A.x, A.y, A.w, A.h, scale, mode);
    const words = await ocr(c, "11");
    S.diagTxt = words.map(w => w.text).join(" "); if (S.diag) S.diagImg = c.toDataURL("image/jpeg", .6);
    const q = findQuarter(words), k = findClock(words, q && q.w);
    if (!q && !k) { S.polar = !S.polar; return null; }
    const toF = b => ({ x0: A.x + b.x0 / scale, y0: A.y + b.y0 / scale, x1: A.x + b.x1 / scale, y1: A.y + b.y1 / scale });
    let L;
    if (q && k) { // la zone couvre le chrono et le quart-temps, avec un peu de marge
      const a1 = toF(bx(q.w)), a2 = toF(bx(k.w)), tw = a1.x1 - a1.x0, th = a1.y1 - a1.y0;
      const x0 = Math.min(a1.x0, a2.x0), y0 = Math.min(a1.y0, a2.y0), x1 = Math.max(a1.x1, a2.x1), y1 = Math.max(a1.y1, a2.y1);
      const mw = (x1 - x0) * .12 + tw * .25, mh = (y1 - y0) * .1 + th * .3;
      L = { x: x0 - mw, y: y0 - mh, w: x1 - x0 + 2 * mw, h: y1 - y0 + 2 * mh };
    } else if (q) { // le quart-temps seul : le chrono est à côté ou au-dessus
      const a1 = toF(bx(q.w)), tw = a1.x1 - a1.x0, th = a1.y1 - a1.y0;
      L = { x: a1.x0 - tw * 1.6, y: a1.y0 - th * 2.4, w: tw * 4.2, h: th * 3.8 };
    } else { // le chrono seul : le quart-temps est dessous ou à côté
      const a2 = toF(bx(k.w)), cw = a2.x1 - a2.x0, ch = a2.y1 - a2.y0;
      L = { x: a2.x0 - cw * .7, y: a2.y0 - ch * .4, w: cw * 2.4, h: ch * 2.3 };
    }
    S.lock = L; S.polar = false;
    return q && k ? { per: q.per, sec: k.sec, alt: k.alt, sure: true } : null;
  }

  /* ---------- filtre : on n'accepte qu'un chrono plausible ---------- */
  // Règle anti-spoil : dans le doute, on choisit le moment le plus TÔT du match, et on n'avance
  // loin dans le match que si la lecture est confirmée plusieurs fois (ou si on a sauté dans la vidéo).
  const frac = (per, sec) => per <= 4 ? ((per - 1) * 720 + 720 - sec) / 2880 : 1 + ((per - 5) * 300 + 300 - sec) / 2880;
  function accept(hit) {
    const nper = Math.max(4, ...S.D.plays.map(p => p.per));
    let opts = [hit.sec, hit.alt].filter(x => x !== null && x !== undefined && x <= (hit.per > 4 ? 300 : 720));
    if (hit.per > nper || !opts.length) return false;
    const cur = S.at;
    if (opts.length > 1) { // « 1:05 » ou « 11:05 » ?
      const fwd = cur ? opts.filter(x => hit.per === cur.per && cur.sec - x >= -3 && cur.sec - x <= 90) : [];
      if (fwd.length === 1) opts = fwd;
      else if (S.ytT !== undefined && S.ytDur > 60) { // la place dans la vidéo donne une idée de la place dans le match
        const f = S.ytT / S.ytDur;
        opts = [opts.reduce((a, b) => Math.abs(frac(hit.per, a) - f) <= Math.abs(frac(hit.per, b) - f) ? a : b)];
      } else opts = [Math.max(...opts)];
    }
    const sec = opts[0], prev = S.cand;
    S.agree = prev && prev.per === hit.per && Math.abs(prev.sec - sec) <= 8 ? (S.agree || 1) + 1 : 1;
    S.cand = { per: hit.per, sec };
    const forward = cur && ((hit.per === cur.per && cur.sec - sec >= -3 && cur.sec - sec <= 90) || (hit.per === cur.per + 1 && sec >= 540));
    const backward = cur && frac(hit.per, sec) < frac(cur.per, cur.sec); // retour en arrière : sans risque de spoil
    const farAhead = !cur || (!forward && !backward);
    const ok = forward || (backward && S.agree >= 2) || (farAhead && (S.agree >= 3 || (S.jump && hit.sure && S.agree >= 2)));
    if (ok) { S.at = { per: hit.per, sec }; S.jump = false; }
    return ok;
  }

  /* ---------- le partage d'écran : un seul par visite ---------- */
  let STREAM = null, SURF = "browser", GRAB = null, VEL = null;
  async function ensureStream() {
    if (STREAM && STREAM.active) return true;
    let st;
    try {
      st = await navigator.mediaDevices.getDisplayMedia({ video: { displaySurface: "browser", frameRate: 5, width: { ideal: 2560 }, height: { ideal: 1440 } }, audio: false,
        preferCurrentTab: true, selfBrowserSurface: "include", surfaceSwitching: "exclude", systemAudio: "exclude" });
    } catch (e) { return false; }
    STREAM = st;
    const tr = st.getVideoTracks()[0];
    SURF = (tr.getSettings && tr.getSettings().displaySurface) || "browser";
    tr.addEventListener("ended", () => { STREAM = null; GRAB = null; if (S) { S.on = false; S.at = null; render(true); } });
    GRAB = typeof ImageCapture !== "undefined" ? new ImageCapture(tr) : null;
    if (!VEL) { VEL = document.createElement("video"); VEL.muted = true; VEL.playsInline = true;
      VEL.style.cssText = "position:fixed;left:0;bottom:0;width:2px;height:2px;opacity:0;pointer-events:none"; document.body.appendChild(VEL); }
    VEL.srcObject = st; await VEL.play().catch(() => {});
    return true;
  }
  async function frameNow() {
    if (GRAB) { // ImageCapture peut attendre indéfiniment une image qui ne change pas : 700 ms max
      try {
        const b = await Promise.race([GRAB.grabFrame(), new Promise((_, ko) => setTimeout(() => ko(new Error("lent")), 700))]);
        return { src: b, W: b.width, H: b.height, close: () => b.close() };
      } catch (e) { /* on passe à la vidéo */ }
    }
    if (VEL && VEL.videoWidth) return { src: VEL, W: VEL.videoWidth, H: VEL.videoHeight, close() {} };
    return null;
  }
  function videoRect(W, H) { // où est le lecteur YouTube dans l'image capturée ?
    const r = S.iframe.getBoundingClientRect();
    let k, ox = 0, oy = 0;
    if (SURF === "browser") k = W / innerWidth;
    else {
      const bxw = Math.max(0, (outerWidth - innerWidth) / 2), byw = Math.max(0, outerHeight - innerHeight - bxw);
      if (SURF === "monitor") { k = W / screen.width; ox = screenX + bxw; oy = screenY + byw; }
      else { k = W / outerWidth; ox = bxw; oy = byw; }
    }
    return { x: (r.left + ox) * k, y: (r.top + oy) * k, w: r.width * k, h: r.height * k };
  }

  /* ---------- le lecteur YouTube nous dit où en est la vidéo (pause, saut en avant/arrière) ---------- */
  window.addEventListener("message", e => {
    let host = ""; try { host = new URL(e.origin).hostname; } catch (x) { return; }
    if (!S || !/(^|\.)youtube(-nocookie)?\.com$/.test(host)) return;
    let m; try { m = typeof e.data === "string" ? JSON.parse(e.data) : e.data; } catch (x) { return; }
    const info = m && m.info; if (!info || typeof info !== "object") return;
    if (typeof info.playerState === "number") S.ytState = info.playerState;
    if (typeof info.duration === "number") S.ytDur = info.duration;
    if (typeof info.currentTime === "number") {
      const now = performance.now(), t = info.currentTime;
      if (S.ytT !== undefined && S.ytState === 1) {
        const expect = S.ytT + (now - S.ytAt) / 1000;
        if (Math.abs(t - expect) > 4) { S.jump = true; S.miss = 0; } // l'utilisateur a sauté dans la vidéo
      }
      S.ytT = t; S.ytAt = now;
    }
  });
  function listenYT() { // sans charger l'API YouTube : on demande au lecteur de nous envoyer son état
    const f = S && S.iframe && S.iframe.querySelector("iframe");
    if (f && f.contentWindow) f.contentWindow.postMessage(JSON.stringify({ event: "listening", id: 1, channel: "widget" }), "*");
  }

  /* ---------- le panneau ---------- */
  const clockTxt = (per, sec) => sec < 0 ? "Final" : `${per > 4 ? "Prol." + (per > 5 ? per - 4 : "") : "Q" + per} · ${sec >= 60 ? Math.floor(sec / 60) + ":" + String(Math.floor(sec % 60)).padStart(2, "0") : sec.toFixed(1)}`;
  function panelIdle() {
    const auto = store.get("live", true);
    return `<div class="lv-idle">
      <div class="lv-kick">Stats en direct</div>
      <p>Le panneau suit le résumé : à chaque instant, les stats du match <b>jusqu'au moment affiché</b>, pas plus loin.</p>
      <button class="btn amber" data-live-start>📡 Activer</button>
      <label class="lv-auto"><input type="checkbox" data-live-auto ${auto ? "checked" : ""}> Proposer le partage dès que j'ouvre un résumé</label>
      <p class="lv-small">Le navigateur demande de partager <b>cet onglet</b> (une fois par visite) : c'est la seule façon pour le site de voir le chrono du match.
      L'image reste sur ton ordinateur, rien n'est envoyé.</p>${DEMO ? `<p class="lv-small">Démo : pas de vraie vidéo, un curseur simule le chrono.</p>` : ""}</div>`;
  }
  const STXT = { load: "Préparation…", seek: "Recherche du bandeau…", ok: "● Synchro", lost: "Bandeau caché", pause: "En pause", prep: "● Synchro", wait: "En attente du chrono…" };
  function render(force) {
    const el = S && S.el; if (!el) return;
    const key = [S.on, S.status, S.at && S.at.per, S.at && S.at.fin, S.at && (S.map && !DEBUG ? playIndex(S.D, S.at) : S.at.sec), S.diag && S.reads].join("|");
    if (!force && key === S.key) return;
    S.key = key;
    if (!S.on) { el.innerHTML = panelIdle(); return; }
    const st = S.status;
    const diag = S.diag ? `<div class="lv-diag">${S.diagImg ? `<img src="${S.diagImg}" alt="">` : ""}<code>${S.lock ? "verrou" : "recherche"} · lectures ${S.reads} · ${SURF} · vidéo ${S.ytT !== undefined ? Math.round(S.ytT) + "/" + Math.round(S.ytDur || 0) + " s" : "?"} · lu : ${(S.diagTxt || "—").replace(/</g, "&lt;").slice(0, 120)}</code></div>` : "";
    const head = `<div class="lv-head">${DEBUG || !S.map ? `<span class="led lv-clock"><span class="v">${String(S.at ? clockTxt(S.at.per, S.at.sec) : "--:--").replace(/:/g, '<i class="cl">:</i>')}</span></span>` : `<span class="lv-kick sm">Stats au fil du replay</span>`}
      <span class="lv-st ${S.at && st === "ok" ? "ok" : ""}">${STXT[st] || ""}</span>
      ${S.map ? "" : `<button class="lv-ico" data-live-diag title="Diagnostic">🔧</button><button class="lv-ico" data-live-stop title="Arrêter le partage">■</button>`}</div>
      ${DEMO ? `<input class="lv-demo" type="range" min="0" max="${S.D.plays.length - 1}" value="${S.demoI || 0}" aria-label="Simuler le moment du match">` : ""}${diag}`;
    if (!S.at) { el.innerHTML = head + `<p class="lv-wait">Lance la vidéo : dès que le bandeau du match est à l'écran, les stats apparaissent.</p>`; if (S.below) S.below.innerHTML = ""; return; }
    const D = S.D, A = statsAt(D, S.at.per, S.at.sec), h = team(D.home), a = { ...team(D.away), color: vsColor(D.away, D.home) }, th = A.T[D.home], ta = A.T[D.away];
    const pc = (m, n) => n ? Math.round(100 * m / n) + " %" : "–";
    const row = (lab, va, vh, sa, sh) => { const tot = (sa + sh) || 1;
      return `<div class="lv-row"><b data-k="${lab}a">${va}</b><span>${lab}</span><b data-k="${lab}h">${vh}</b><i style="--a:${a.color};--h:${h.color};--p:${(sa / tot * 100).toFixed(1)}%"></i></div>`; };
    const Z0 = { pts: 0, reb: 0, ast: 0, blk: 0 };
    const top = t => {
      const ids = Object.keys(D.names).filter(id => D.names[id].t === t);
      const val = id => A.P[id] || Z0;
      ids.sort((x, y) => (val(y).pts - val(x).pts) || ((val(y).reb + val(y).ast) - (val(x).reb + val(x).ast))
        || (D.names[y].st - D.names[x].st) || (D.names[x].o - D.names[y].o));
      return ids.slice(0, 5).map(id => { const p = val(id);
        return `<tr><td>${D.names[id].n}</td><td><b data-k="p${id}">${p.pts}</b></td><td><b data-k="r${id}">${p.reb}</b></td><td><b data-k="a${id}">${p.ast}</b></td><td><b data-k="b${id}">${p.blk}</b></td></tr>`; }).join("");
    };
    const ptab = (tm, t) => `<table><thead><tr><th style="--mc:${tm.color}">${tm.name}</th><th>Pts</th><th>Reb</th><th>Pd</th><th title="Contres">Ctr</th></tr></thead><tbody>${top(t)}</tbody></table>`;
    el.innerHTML = head + (DEBUG || !S.map ? `
      <div class="lv-score"><span class="lv-t" style="--mc:${a.color}">${a.tri}</span><span class="led">${A.as}</span><span class="lv-dash">–</span><span class="led">${A.hs}</span><span class="lv-t" style="--mc:${h.color}">${h.tri}</span></div>` : "") + `
      <div class="lv-rows">
        ${row("Tirs", `${ta.fg}/${ta.fga}`, `${th.fg}/${th.fga}`, ta.fg, th.fg)}
        ${row("Réussite", pc(ta.fg, ta.fga), pc(th.fg, th.fga), ta.fga ? ta.fg / ta.fga : 0, th.fga ? th.fg / th.fga : 0)}
        ${row("3 points", `${ta.tp}/${ta.tpa}`, `${th.tp}/${th.tpa}`, ta.tp, th.tp)}
        ${row("Lancers", `${ta.ftm}/${ta.fta}`, `${th.ftm}/${th.fta}`, ta.ftm, th.ftm)}
        ${row("Rebonds", ta.reb, th.reb, ta.reb, th.reb)}
        ${row("Passes", ta.ast, th.ast, ta.ast, th.ast)}
        ${row("Contres", ta.blk, th.blk, ta.blk, th.blk)}
        ${row("Balles perdues", ta.to, th.to, ta.to, th.to)}
      </div>
      <div class="lv-pl">${ptab(a, D.away)}${ptab(h, D.home)}</div>`;
    const F = flow(D, S.at);
    // sous la vidéo : le film du match + les tendances à côté ; la colonne des stats garde le terrain des tirs en grand
    el.insertAdjacentHTML("beforeend", (S.below ? "" : trendsHTML(D, F)) + shotsHTML(D, S.at));
    if (S.below) S.below.innerHTML = curveHTML(D, S.at, F) + trendsHTML(D, F);
    const prev = S.vals || {}, vals = {};
    for (const n of el.querySelectorAll("[data-k]")) {
      const k = n.dataset.k, v = n.textContent; vals[k] = v;
      if (S.vals && prev[k] !== undefined && prev[k] !== v) n.classList.add("up");
    }
    S.vals = vals;
  }

  /* ---------- le fil du match jusqu'au moment affiché : courbe + quart-temps (sous la vidéo), tendances (à droite) ---------- */
  const elapsed = (per, sec) => per <= 4 ? (per - 1) * 720 + 720 - sec : 2880 + (per - 5) * 300 + 300 - sec;
  function flow(D, at) {
    const pts = [[0, 0]], qEnd = {}; // pts : l'écart après chaque panier (secondes de jeu, + = domicile devant)
    let hs = 0, as = 0, maxH = 0, maxA = 0, leads = 0, lastLead = 0, runT = 0, runP = 0, bestT = 0, bestP = 0;
    let lastX = 0, leadH = 0, leadA = 0; // temps passé en tête (en secondes de jeu)
    for (const p of D.plays) {
      if (p.per > at.per || (p.per === at.per && p.sec <= at.sec)) break;
      if (p.hs !== hs || p.as !== as) {
        const d = p.hs - p.as, gain = (p.hs - hs) + (p.as - as), who = p.hs > hs ? D.home : D.away;
        if (gain > 0) { if (who === runT) runP += gain; else { runT = who; runP = gain; } }
        if (runP > bestP) { bestP = runP; bestT = runT; }
        const x = elapsed(p.per, p.sec), d0 = hs - as;
        if (d0 > 0) leadH += x - lastX; else if (d0 < 0) leadA += x - lastX;
        lastX = x;
        const sg = Math.sign(d);
        if (sg && lastLead && sg !== lastLead) leads++;
        if (sg) lastLead = sg;
        maxH = Math.max(maxH, d); maxA = Math.max(maxA, -d);
        hs = p.hs; as = p.as;
        pts.push([elapsed(p.per, p.sec), d]);
      }
      qEnd[p.per] = [as, hs];
    }
    const now = elapsed(at.per, at.sec);
    pts.push([now, hs - as]);
    if (hs > as) leadH += now - lastX; else if (as > hs) leadA += now - lastX;
    return { pts, qEnd, hs, as, maxH, maxA, leads, runT, runP, bestT, bestP, leadH, leadA, now };
  }
  function curveHTML(D, at, F) {
    const h = team(D.home), a = { ...team(D.away), color: vsColor(D.away, D.home) };
    // l'axe couvre le temps réglementaire ; une prolongation n'apparaît qu'une fois atteinte (sans spoil)
    const nq = Math.max(4, at.per), span = 2880 + (nq - 4) * 300, W = 1000, H = 200, mid = 100;
    const amp = Math.max(8, ...F.pts.map(p => Math.abs(p[1]))) * 1.12;
    const X = x => (x / span * W).toFixed(1), Y = d => (mid - d / amp * (mid - 6)).toFixed(1);
    const line = F.pts.map((p, i) => (i ? "L" : "M") + X(p[0]) + " " + Y(p[1])).join(" ");
    const area = line + ` L${X(F.now)} ${mid} L0 ${mid} Z`;
    const grid = Array.from({ length: nq - 1 }, (_, i) => i < 3 ? (i + 1) * 720 : 2880 + (i - 3) * 300)
      .map(x => `<line x1="${X(x)}" x2="${X(x)}" y1="0" y2="${H}" class="g"/>`).join("");
    const dNow = F.hs - F.as;
    const svg = `<svg class="lv-curve" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Écart au score jusqu'ici">
      <defs><clipPath id="lvU"><rect x="0" y="0" width="${W}" height="${mid}"/></clipPath><clipPath id="lvD"><rect x="0" y="${mid}" width="${W}" height="${mid}"/></clipPath></defs>
      ${grid}<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" class="z"/>
      <path d="${area}" fill="${h.color}" opacity=".5" clip-path="url(#lvU)"/><path d="${area}" fill="${a.color}" opacity=".5" clip-path="url(#lvD)"/>
      <path d="${line}" class="l"/></svg>`;
    // le point du moment, en HTML pour rester rond malgré l'étirement du graphique
    const dot = `<i class="lv-dot" style="left:${(F.now / span * 100).toFixed(2)}%;top:${(Y(dNow) / H * 100).toFixed(2)}%"></i>`;
    // les quart-temps, alignés sous la courbe : le score des quarts TERMINÉS (celui en cours suit la vidéo)
    const cols = Array.from({ length: nq }, (_, i) => i + 1);
    const qcell = q => {
      const lab = q <= 4 ? "Q" + q : "Prol." + (q > 5 ? q - 4 : "");
      if ((q < at.per || (at.fin && q === at.per)) && F.qEnd[q]) {
        const pr = q > 1 && F.qEnd[q - 1] ? F.qEnd[q - 1] : [0, 0], va = F.qEnd[q][0] - pr[0], vh = F.qEnd[q][1] - pr[1];
        return `<div class="lv-q"><span>${lab}</span><b class="${va > vh ? "w" : ""}" style="--mc:${a.color}">${va}</b><b class="${vh > va ? "w" : ""}" style="--mc:${h.color}">${vh}</b></div>`;
      }
      return `<div class="lv-q ${q === at.per ? "cur" : "no"}"><span>${lab}</span><em>${q === at.per ? "en cours" : ""}</em></div>`;
    };
    const tmpl = cols.map(q => (q <= 4 ? 720 : 300) + "fr").join(" ");
    return `<div class="lv-sec lv-film">
      <div class="lv-filmh"><h4>Le film du match</h4><div class="lv-leg"><i style="--mc:${a.color}"></i>${a.name}<i style="--mc:${h.color}"></i>${h.name}</div>
        <div class="lv-fx"><span>Temps en tête <b>${F.now > 0 ? `${a.tri} ${pct(F.leadA, F.now)} · ${h.tri} ${pct(F.leadH, F.now)}` : "—"}</b></span>
        <span>Changements de leader <b>${F.leads}</b></span></div></div>
      <div class="lv-plot">${svg}${dot}</div>
      <div class="lv-qs" style="grid-template-columns:${tmpl}">${cols.map(qcell).join("")}</div></div>`;
  }
  const pct = (x, tot) => Math.round(100 * x / tot) + " %";
  /* ---------- le mini-terrain : les tirs des deux équipes (visiteurs à gauche, domicile à droite), jusqu'au moment affiché ---------- */
  const HALF = `<rect x="0" y="17" width="19" height="16"/><circle cx="19" cy="25" r="6"/><path d="M0 3H14A23.75 23.75 0 0 1 14 47H0"/>
    <path d="M4 22V28"/><circle cx="5.25" cy="25" r=".75"/><path d="M5.25 21A4 4 0 0 1 5.25 29"/>`;
  function shotsHTML(D, at) {
    const h = team(D.home), a = { ...team(D.away), color: vsColor(D.away, D.home) };
    const Z = { [D.away]: [[0, 0], [0, 0], [0, 0]], [D.home]: [[0, 0], [0, 0], [0, 0]] }; // raquette, mi-distance, 3 pts : [réussis, tentés]
    const dots = []; let last = null;
    for (const p of D.plays) {
      if (p.per > at.per || (p.per === at.per && p.sec <= at.sec)) break;
      if (!p.shoot || p.ft || p.sx == null || !Z[p.tid]) continue;
      const zone = p.three ? 2 : (p.sx >= 17 && p.sx <= 33 && p.sy <= 19) ? 0 : 1;
      Z[p.tid][zone][1]++; if (p.made) Z[p.tid][zone][0]++;
      const home = p.tid === D.home, X = home ? 94 - p.sy : p.sy, Y = home ? p.sx : 50 - p.sx, col = home ? h.color : a.color;
      last = { X, Y, col };
      dots.push(p.made ? `<circle cx="${X.toFixed(1)}" cy="${Y.toFixed(1)}" r="1.05" fill="${col}" class="mk"/>`
        : `<path d="M${(X - .75).toFixed(1)} ${(Y - .75).toFixed(1)}l1.5 1.5m0-1.5l-1.5 1.5" stroke="${col}" class="ms"/>`);
    }
    const ring = last ? `<circle cx="${last.X.toFixed(1)}" cy="${last.Y.toFixed(1)}" r="1.4" stroke="${last.col}" class="ring" key="${dots.length}"/>` : "";
    const z = (t, i) => `${Z[t][i][0]}/${Z[t][i][1]}`;
    const inner = `<g class="ln"><rect x="0" y="0" width="94" height="50"/><path d="M47 0V50"/><circle cx="47" cy="25" r="6"/>
        ${HALF}<g transform="matrix(-1 0 0 1 94 0)">${HALF}</g></g>${dots.join("")}${ring}`;
    // deux terrains : en largeur (visiteurs à gauche) et en hauteur (visiteurs en haut, tourné d'un quart de tour) ;
    // le CSS montre celui qui remplit le mieux la colonne (en hauteur sur les écrans hauts, 21/11)
    return `<div class="lv-shots"><div class="lv-courth"><h4>Les tirs</h4><span style="--mc:${a.color}"><em class="cl-h">◀</em><em class="cl-v">▲</em> ${a.tri}</span><span style="--mc:${h.color}">${h.tri} <em class="cl-h">▶</em><em class="cl-v">▼</em></span></div>
      <svg class="lv-court ch" viewBox="-1 -1 96 52" role="img" aria-label="Les tirs des deux équipes jusqu'ici">${inner}</svg>
      <svg class="lv-court cv" viewBox="-1 -1 52 96" role="img" aria-label="Les tirs des deux équipes jusqu'ici"><g transform="matrix(0 1 -1 0 50 0)">${inner}</g></svg>
      <div class="lv-zones"><span></span><b>Raquette</b><b>Mi-distance</b><b>3 points</b>
        <span style="--mc:${a.color}">${a.tri}</span><i>${z(D.away, 0)}</i><i>${z(D.away, 1)}</i><i>${z(D.away, 2)}</i>
        <span style="--mc:${h.color}">${h.tri}</span><i>${z(D.home, 0)}</i><i>${z(D.home, 1)}</i><i>${z(D.home, 2)}</i></div></div>`;
  }
  function trendsHTML(D, F) {
    const h = team(D.home), a = { ...team(D.away), color: vsColor(D.away, D.home) }, dNow = F.hs - F.as;
    const tile = (lab, val, sub) => `<div class="lv-tile"><span>${lab}</span><b>${val}</b><small>${sub || "&nbsp;"}</small></div>`;
    return `<div class="lv-trends"><div class="lv-filmh"><h4>Les tendances</h4></div><div class="lv-tiles">
      ${tile("Écart", dNow ? `+${Math.abs(dNow)} ${(dNow > 0 ? h : a).tri}` : "Égalité", dNow ? "en tête" : "")}
      ${tile("Série en cours", F.runP >= 4 ? `${F.runP}-0 ${team(F.runT).tri}` : "—", F.runP >= 4 ? "points d'affilée" : "aucune")}
      ${tile("Plus gros run", F.bestP >= 4 ? `${F.bestP}-0 ${team(F.bestT).tri}` : "—", F.bestP >= 4 ? "depuis le début" : "pas encore")}
      ${tile("Plus grosse avance", `${a.tri} +${F.maxA} · ${h.tri} +${F.maxH}`)}
</div></div>`;
  }

  /* ---------- boucle de lecture ---------- */
  const wait = ms => new Promise(r => setTimeout(r, ms));
  async function loop(my) {
    if (my.looping) return; my.looping = true;
    let n = 0;
    while (S === my && my.on && STREAM && STREAM.active) {
      if (++n % 5 === 1) listenYT();
      if (my.ytState === 2) { if (my.status !== "pause") { my.status = "pause"; render(); } await wait(400); continue; }
      const f = await frameNow();
      let hit = null;
      if (f && f.W > 100) {
        let R = videoRect(f.W, f.H);
        if (my.fails >= 4 || R.w < 80) R = { x: 0, y: 0, w: f.W, h: f.H }; // la page n'est pas où on croit : toute l'image
        try { hit = await readFrame(f.src, f.W, f.H, R); } catch (e) { hit = null; }
        f.close();
      }
      if (S !== my) return;
      if (hit && accept(hit)) { my.miss = 0; my.fails = 0; my.status = "ok"; }
      else if (my.lock) { if (++my.miss >= 6) { my.lock = null; my.miss = 0; my.status = my.at ? "lost" : "seek"; } }
      else { my.fails++; my.status = my.at ? "lost" : "seek"; }
      render();
      await wait(my.lock ? (my.status === "ok" ? 650 : 250) : 200);
    }
    my.looping = false;
  }
  async function start(fromClick) {
    if (!S) return;
    const my = S;
    if (DEMO) { S.on = true; S.status = "ok"; S.demoI = Math.floor(S.D.plays.length * .3); const p = S.D.plays[S.demoI]; S.at = { per: p.per, sec: p.sec }; render(true); return; }
    worker().catch(() => {}); // on charge le lecteur de texte pendant que le navigateur demande l'accord
    if (!(STREAM && STREAM.active)) {
      if (!fromClick) return;
      const ok = await ensureStream();
      if (!ok) { toast("Partage refusé : pas de stats en direct cette fois"); return; }
    }
    if (S !== my) return;
    my.on = true; my.status = "load"; render(true);
    try { await worker(); } catch (e) { toast("Impossible de charger le lecteur de chrono"); my.on = false; render(true); return; }
    if (S !== my) return;
    my.status = "seek"; render(true);
    loop(my);
  }
  function stop() {
    if (STREAM) STREAM.getTracks().forEach(t => t.stop());
    STREAM = null; GRAB = null;
    if (S) { S.on = false; S.at = null; S.cand = null; S.lock = null; render(true); }
  }

  /* ---------- mode préparé : le téléphone-serveur a déjà lu le chrono de la vidéo ----------
     Table « seconde de la vidéo -> moment du match » (branche data, v2/chrono/<vidéo>.json).
     Le lecteur YouTube donne sa position : on suit, sans partage d'écran, sur tous les appareils. */
  let MAPS = null;
  const tick5 = () => Math.floor(Date.now() / 300e3);
  async function loadIndex() {
    if (MAPS) return MAPS;
    if (DEMO) return (MAPS = new Set());
    try { const j = await fetchJSON(RAWDATA + "chrono/index.json?t=" + tick5()); MAPS = new Set(j.v || []); }
    catch (e) { MAPS = new Set(); }
    return MAPS;
  }
  loadIndex();
  // Le moment du match à la seconde t de la vidéo. Les points sont espacés de 2 s : à l'intérieur d'une même action
  // (même quart, chrono qui descend au rythme de la vidéo), on fait couler le chrono entre deux points ; sinon (changement
  // d'action, chrono arrêté, saut), on reste sur le dernier point passé. Jamais au-delà du point suivant : jamais en avance.
  function momentAt(map, t) {
    let lo = 0, hi = map.length - 1, i = -1;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (map[m][0] <= t) { i = m; lo = m + 1; } else hi = m - 1; }
    if (i < 0) return null;
    const p = map[i], q = map[i + 1];
    let sec = p[2];
    if (q && q[1] === p[1]) {
      const dt = q[0] - p[0], ds = p[2] - q[2];
      if (dt > 0 && dt <= 4.5 && ds > 0 && ds <= dt * 1.3 + .5) sec = p[2] - Math.min(ds, (t - p[0]) * ds / dt);
    }
    return { per: p[1], sec, sc: p.length >= 5 ? [p[3], p[4]] : null }; // sc : le score lu à l'écran (tables récentes)
  }
  function ytCmd(my, func, args) {
    const f = my && my.iframe && my.iframe.querySelector("iframe");
    if (f && f.contentWindow) f.contentWindow.postMessage(JSON.stringify({ event: "command", func, args: args || [], id: 1, channel: "widget" }), "*");
  }
  // le match fini : dernier quart-temps joué, chrono à zéro (fin = tout le déroulé)
  function finalAt(D) { return { per: Math.max(4, ...D.plays.map(p => p.per)), sec: -1, fin: true }; }
  async function prepLoop(my) {
    let n = 0;
    while (S === my) {
      if (n++ % 6 === 0) listenYT();
      // entre deux messages du lecteur, on avance au plus de 1,5 s (pub, vidéo bloquée : on s'arrête au lieu de courir devant)
      const t = my.ytT === undefined ? null : my.ytT + (my.ytState === 1 ? Math.min(1.5, (performance.now() - my.ytAt) / 1000) : 0);
      // avant le premier chrono lu (ou avant le lancement) : le début du match, stats à zéro (rien ne peut être spoilé)
      const m0 = t === null ? null : momentAt(my.map, t), m = m0 && clampAt(my.D, m0, m0.sc);
      my.at = m || { per: 1, sec: 720 };
      // la fin du match : le dernier bandeau lu + 3 s. Au-delà, le résumé GameTime/NBA montre son tableau des stats
      // (demande de Kiki) : on met la vidéo en pause juste avant, et le match passe en « terminé » (score final, tous les quarts)
      if (t !== null && t >= my.endT) {
        if (my.ytState === 1) ytCmd(my, "pauseVideo");
        my.at = finalAt(my.D);
      }
      my.status = my.ytState === 2 ? "pause" : m ? "prep" : "wait";
      render();
      await wait(150);
    }
  }

  /* ---------- branchement sur le lecteur vidéo ---------- */
  async function attach(gid, panel, iframe, vid, below) {
    if (S) S.on = false;
    const my = S = { gid, vid, el: panel, below, iframe, on: false, miss: 0, fails: 0, reads: 0, D: null, polar: false };
    panel.innerHTML = `<p class="lv-wait">Chargement du déroulé du match…</p>`;
    const idx = await loadIndex();
    const prepared = vid && idx.has(vid);
    if (!DEMO && !prepared && CAN) worker().catch(() => {});
    let map = null;
    try {
      const [sum, m] = await Promise.all([
        DEMO ? window.DEMO.summary(gid) : fetchJSON(API + "summary?event=" + gid),
        prepared ? fetchJSON(RAWDATA + "chrono/" + vid + ".json?t=" + tick5()).catch(() => null) : null]);
      my.D = DEMO ? demoPlays(sum, state.games.find(x => x.id === gid)) : parsePlays(sum);
      map = m;
    } catch (e) { my.D = null; }
    if (S !== my) return;
    const hide = () => {
      panel.remove(); if (below) below.remove();
      iframe.closest(".vplayer").classList.remove("live", "full"); vidovl.classList.remove("full");
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    };
    if (!my.D || my.D.plays.length < 20) { if (CAN) panel.innerHTML = `<p class="lv-wait">Pas de déroulé ESPN pour ce match : pas de stats en direct.</p>`; else hide(); return; }
    if (map && map.pts && map.pts.length >= 5) { my.map = map.pts; my.endT = map.pts[map.pts.length - 1][0] + 3; my.on = true; my.status = "prep"; render(true); prepLoop(my); return; }
    if (!CAN) { hide(); return; } // téléphone sans table préparée : pas de panneau
    render(true);
    if (STREAM && STREAM.active) start(false); // déjà partagé pendant cette visite : rien à redemander
  }

  /* ---------- le résumé de la nuit + : la liste des matchs à gauche, qui se remplit au fil de la vidéo ----------
     Chapitres préparés par le téléphone (v2/nuit/<nuit>.json) : chaque match, le joueur de la nuit, les plus belles actions.
     Un match pas encore atteint reste éteint ; celui qui passe s'allume à ses couleurs, son score est CELUI LU À L'ÉCRAN
     (le téléphone lit le score du bandeau et le recoupe avec la suite des scores ESPN) ; un match regardé jusqu'au bout
     garde son score final. Un clic sur un match y saute dans la vidéo.
     Mode « extrait » (solo : depuis l'essentiel) : seulement le chapitre du joueur de la nuit, ou des plus belles actions. */
  function seekYT(t) {
    const f = S && S.iframe && S.iframe.querySelector("iframe");
    if (f && f.contentWindow) f.contentWindow.postMessage(JSON.stringify({ event: "command", func: "seekTo", args: [t, true], id: 1, channel: "widget" }), "*");
    if (S) { S.ytT = t; S.ytAt = performance.now(); }
  }
  const fromEl = el => el < 2880 ? { per: Math.min(4, Math.floor(el / 720) + 1), sec: 720 - (el - (Math.min(4, Math.floor(el / 720) + 1) - 1) * 720) }
    : { per: 5 + Math.floor((el - 2880) / 300), sec: 300 - (el - 2880 - Math.floor((el - 2880) / 300) * 300) };
  // le moment du match, borné à l'intérieur du score vu à l'écran (le chrono qui coule entre deux images ne doit jamais
  // faire passer un panier qu'on n'a pas encore vu)
  function clampAt(D, at, sc) {
    if (!sc || !D || !at) return at;
    const P = D.plays;
    let i0 = -1;
    if (sc[0] + sc[1] > 0) {
      i0 = P.findIndex(p => p.as === sc[0] && p.hs === sc[1]);
      if (i0 < 0) { // score de l'écran absent du fil ESPN (panier corrigé après coup) : le plus proche
        let best = 4;
        P.forEach((p, i) => { const d = Math.abs(p.as - sc[0]) + Math.abs(p.hs - sc[1]); if (d < best) { best = d; i0 = i; } });
        if (i0 < 0) return at;
        sc = [P[i0].as, P[i0].hs];
      }
    }
    const lo = i0 >= 0 ? elapsed(P[i0].per, P[i0].sec) + .01 : 0;
    let hi = Infinity;
    for (let i = i0 + 1; i < P.length; i++) if (P[i].as !== sc[0] || P[i].hs !== sc[1]) { hi = elapsed(P[i].per, P[i].sec) - .3; break; }
    const el = elapsed(at.per, at.sec), e2 = Math.min(Math.max(el, lo), hi);
    return Math.abs(e2 - el) < .001 ? at : fromEl(e2);
  }
  async function attachNight(N, list, iframe, below, opts) {
    if (S) S.on = false;
    opts = opts || {};
    const my = S = { night: N, el: list, below, side: opts.side || null, solo: opts.solo || null, iframe, on: true, D: {}, key: null, done: new Set() };
    my.games = c => (typeof state !== "undefined" ? state.games : []).find(g => g.id === c.gid);
    renderNight(true);
    // les déroulés ESPN des matchs (score, film du match, tirs, stats des joueurs)
    const gids = new Set();
    for (const c of N.ch) { if (c.gid) gids.add(c.gid); for (const a of c.plays || []) if (a.gid) gids.add(a.gid); }
    await Promise.all([...gids].map(async gid => {
      try { my.D[gid] = parsePlays(await fetchJSON(API + "summary?event=" + gid)); } catch (e) { /* ce match restera sans score en direct */ }
    }));
    if (S !== my) return;
    my.key = null;
    nightLoop(my);
  }
  async function nightLoop(my) {
    let n = 0;
    while (S === my) {
      if (n++ % 6 === 0) listenYT();
      renderNight();
      await wait(200);
    }
  }
  const nowT = () => S.ytT === undefined ? -1 : S.ytT + (S.ytState === 1 ? Math.min(1.5, (performance.now() - S.ytAt) / 1000) : 0);
  // le moment du match à la seconde t d'un chapitre (chrono + score lus à l'écran)
  function chapAt(c, t) {
    if (!c.pts || !c.pts.length || !c.gid) return null;
    const m = momentAt(c.pts, t); if (!m) return null;
    const D = S.D[c.gid];
    const last = c.pts[c.pts.length - 1];
    if (D && t >= last[0] + 2 && (last[1] > 4 || (last[1] === 4 && last[2] < 60))) return finalAt(D); // la fin du match est passée à l'écran
    const at = clampAt(D, m, m.sc);
    return at ? { ...at, sc: m.sc } : at; // sc : le score de l'écran, affiché tel quel
  }
  function nightState() {
    const N = S.night, t = nowT();
    return N.ch.map((c, i) => {
      let st = t >= c.e - .5 ? "past" : t >= c.s ? "cur" : "next";
      if (S.solo && c.k === S.solo) st = "cur"; // extrait seul : son chapitre, du début à la fin
      // un match n'est « vu » (score final affiché) que si on a regardé sa fin ; sauté (clic plus loin) = toujours caché
      if (st === "cur" && t >= c.e - 8) S.done.add(i);
      if (st === "past" && !S.done.has(i)) st = "skip";
      const at = st === "cur" && (c.k === "match" || (c.k === "potn" && S.solo)) ? chapAt(c, t) : null;
      return { c, i, st, at, t };
    });
  }
  const photoURL = aid => /^\d+$/.test(aid || "") ? `https://a.espncdn.com/i/headshots/nba/players/full/${aid}.png` : "";
  function renderNight(force) {
    const my = S; if (!my || !my.night) return;
    const L = nightState();
    const cur = L.find(x => x.st === "cur");
    const topI = cur && cur.c.k === "top" ? (cur.c.plays || []).filter(a => cur.t >= a.s).length : 0;
    const key = L.map(x => x.st[0] + (x.at ? (x.at.fin ? "F" : "") + x.at.per + ":" + (my.D[x.c.gid] ? playIndex(my.D[x.c.gid], x.at) : "") : "")).join("|") + "|" + topI;
    if (!force && key === my.key) return;
    my.key = key;
    if (my.el) {
      my.el.innerHTML = listHTML(L);
      // la liste défile (beaucoup de matchs) : le match en cours reste en vue
      const l = my.el.querySelector(".npl"), ci = my.el.querySelector(".npi.cur");
      if (l && ci && l.scrollHeight > l.clientHeight + 2) {
        const top = ci.offsetTop - l.offsetTop;
        if (top < l.scrollTop || top + ci.offsetHeight > l.scrollTop + l.clientHeight) l.scrollTop = Math.max(0, top - 40);
      }
    }
    if (!cur) {
      if (my.below) my.below.innerHTML = `<div class="lv-sec np-idle"><span class="lv-kick sm">Lance la vidéo</span>
        <p>Les matchs s'allument à gauche au fil du résumé, avec le score qui suit l'écran. Clique sur un match pour y aller.</p></div>`;
      return;
    }
    const c = cur.c;
    if (c.k === "match" && my.D[c.gid]) {
      const D = my.D[c.gid], at = cur.at || { per: 1, sec: 720 }, F = flow(D, at);
      if (my.below) my.below.innerHTML = curveHTML(D, at, F) + trendsHTML(D, F);
    } else if (c.k === "potn" && c.aid) {
      const D = my.D[c.gid];
      if (my.solo) {
        if (my.side) my.side.innerHTML = potnCard(c) + potnCourt(c);
        if (my.below) my.below.innerHTML = D ? curveHTML(D, cur.at || { per: 1, sec: 720 }, flow(D, cur.at || { per: 1, sec: 720 })) : "";
      } else if (my.below) my.below.innerHTML = potnBand(c);
    } else if (c.k === "top") {
      const plays = c.plays || [], n = plays.filter(a => cur.t >= a.s).length;
      if (my.below) my.below.innerHTML = topCards(c, cur.t);
      if (my.side) my.side.innerHTML = n ? topBig(plays[n - 1], plays.length - n + 1) : `<div class="np-wait"><span class="lv-kick sm">Les plus belles actions</span><p>Elles se dévoilent une par une.</p></div>`;
    } else if (my.below) my.below.innerHTML = `<div class="lv-sec np-idle"><span class="lv-kick sm">${c.t}</span></div>`;
  }
  // les icônes de la liste (même boîte, même trait : alignées sur les logos des matchs)
  const ICO = {
    star: `<svg viewBox="0 0 24 24"><path d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2l-5.7 3.1 1.2-6.4-4.7-4.4 6.4-.8z"/></svg>`,
    flame: `<svg viewBox="0 0 24 24"><path d="M12 2.5c.6 3.4 5.5 6 5.5 11.2A5.5 5.5 0 0 1 12 19.2a5.5 5.5 0 0 1-5.5-5.5c0-2.6 1.4-4.2 2.6-5.3.1 1.6.8 2.9 2 3.4-.4-3.3.3-6.4.9-9.3z"/></svg>`,
    play: `<svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z"/></svg>`,
    table: `<svg viewBox="0 0 24 24"><path d="M4 6h3M10 6h10M4 12h3M10 12h10M4 18h3M10 18h10" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>`,
  };
  // les titres des chapitres de la NBA, en français
  function chapTitle(t) {
    if (/eastern conference standings/i.test(t)) return "Classement de l'Est";
    if (/western conference standings/i.test(t)) return "Classement de l'Ouest";
    if (/standings/i.test(t)) return "Le classement";
    return t;
  }
  function listHTML(L) {
    const my = S;
    const nM = L.filter(x => x.c.k === "match").length, seen = L.filter(x => x.c.k === "match" && x.st === "past").length;
    // beaucoup de matchs (ou écran peu haut) : une ligne par match (le match en cours garde ses deux lignes)
    const nX = L.length - nM;
    const dense = typeof innerHeight !== "number" || innerWidth <= 900 ? nM > 8 : nM * 100 + nX * 58 + 60 > innerHeight;
    if (my.el) my.el.classList.toggle("dense", dense);
    const item = x => {
      const c = x.c;
      if (c.k === "match") {
        const g = my.games(c), D = my.D[c.gid];
        if (!g) return `<button class="npi ${x.st}" data-np-seek="${c.s}"><span class="npt one">${c.t}</span></button>`;
        const A = g.teams.away, H = g.teams.home;
        let as = null, hs = null, lab = "";
        if (x.st === "past") { as = A.score; hs = H.score; lab = g.ot ? "Final · prol." : "Final"; }
        else if (x.st === "skip") lab = "Pas encore vu";
        else if (x.st === "cur") {
          if (x.at && D) { const F = flow(D, x.at); [as, hs] = x.at.sc || [F.as, F.hs]; lab = x.at.fin ? (x.at.per > 4 ? "Final · prol." : "Final") : clockTxt(x.at.per, x.at.sec); }
          else lab = "En cours";
        }
        const win = as === null ? "" : as > hs ? "a" : hs > as ? "h" : "";
        const row = (T, v, side) => `<span class="npr ${side} ${win === side ? "w" : ""}" style="--tc:${T.color}"><span class="nplg">${logoHTML(T)}</span><b><span class="fn">${T.name}</span><span class="tr">${T.tri}</span></b>
          <span class="led ${v === null ? "off" : ""}"><span class="v">${v === null ? "??" : v}</span></span></span>`;
        return `<button class="npi m ${x.st}" data-np-seek="${c.s}" style="--ca:${A.color};--cb:${H.color}">
          <span class="nph">${x.st === "cur" ? `<i class="npdot"></i>` : ""}${lab || "Match " + (L.filter(y => y.c.k === "match").indexOf(x) + 1)}</span>${row(A, as, "a")}${row(H, hs, "h")}</button>`;
      }
      if (c.k === "potn") {
        const known = x.st !== "next" && x.st !== "skip" && c.aid, ph = known ? photoURL(c.aid) : "";
        return `<button class="npi xt potn ${x.st}" data-np-seek="${c.s}"><span class="npx ${ph ? "ph" : ""}">${ph ? `<img src="${ph}" alt="" onerror="this.remove()">` : ""}${ICO.star}</span>`
          + (known ? `<span class="npt"><small>Le joueur de la nuit</small>${c.n}</span>` : `<span class="npt one">Le joueur de la nuit <em>?</em></span>`) + `</button>`;
      }
      if (c.k === "top") {
        const n = (c.plays || []).length;
        return `<button class="npi xt ${x.st}" data-np-seek="${c.s}"><span class="npx">${ICO.flame}</span><span class="npt one">${n ? `Les ${n} plus belles actions` : "Les plus belles actions"}</span></button>`;
      }
      return `<button class="npi xt ${x.st}" data-np-seek="${c.s}"><span class="npx">${/standings/i.test(c.t) ? ICO.table : ICO.play}</span><span class="npt one">${chapTitle(c.t)}</span></button>`;
    };
    return `<div class="nphead"><span class="lv-kick sm">La nuit</span><span class="npcount"><b>${seen}</b> / ${nM} matchs vus</span></div>
      <div class="npl">${L.map(item).join("")}</div>`;
  }
  // le joueur de la nuit : sa carte, ses stats du match, et le compteur de ce qu'on a vu dans la vidéo
  function teamOf(D, tid) { const t = team(tid); return D && tid === D.away ? { ...t, color: vsColor(D.away, D.home) } : t; }
  function playerTid(D, aid) { return D && D.names[aid] ? D.names[aid].t : 0; }
  function potnInfo(c) {
    const D = S.D[c.gid]; if (!D) return null;
    const tid = playerTid(D, c.aid), T = teamOf(D, tid), O = team(tid === D.home ? D.away : D.home);
    return { D, T, O, s: statsAt(D, 99, -1).P[c.aid] || {}, ph: photoURL(c.aid) };
  }
  const potnCells = s => [[s.pts, "Points"], [s.reb, "Rebonds"], [s.ast, "Passes"], [s.blk, "Contres"], [`${s.fg || 0}/${s.fga || 0}`, "Tirs"], [`${s.tp || 0}/${s.tpa || 0}`, "À 3 pts"]]
    .map(([v, l]) => `<div class="npc"><b>${v || 0}</b><small>${l}</small></div>`).join("");
  // extrait seul (colonne de droite) : la carte en hauteur
  function potnCard(c) {
    const P = potnInfo(c); if (!P) return "";
    return `<div class="np-card tall" style="--tc:${P.T.color}">
      <div class="np-ph">${P.ph ? `<img src="${P.ph}" alt="" onerror="this.remove()">` : ""}${logoHTML(P.T)}</div>
      <div class="np-id"><span class="lv-kick sm">Le joueur de la nuit</span><b>${c.n}</b><small>${P.T.city} ${P.T.name} · contre ${P.O.name}</small></div>
      <div class="npcs">${potnCells(P.s)}</div></div>`;
  }
  // dans le résumé de la nuit (sous la vidéo) : une bande sur toute la largeur — photo, nom, stats en grand, ses tirs
  function potnBand(c) {
    const P = potnInfo(c);
    if (!P) return `<div class="lv-sec np-idle"><span class="lv-kick sm">Le joueur de la nuit</span><p>${c.n || ""}</p></div>`;
    return `<div class="pn" style="--tc:${P.T.color}">
      <div class="pn-ph">${P.ph ? `<img src="${P.ph}" alt="" onerror="this.remove()">` : ""}${logoHTML(P.T)}</div>
      <div class="pn-id"><span class="lv-kick sm">Le joueur de la nuit</span><b>${c.n}</b><small>${P.T.city} ${P.T.name}</small><small>contre les ${P.O.name}</small></div>
      <div class="pn-st">${potnCells(P.s)}</div>
      ${potnCourt(c)}</div>`;
  }
  // tous ses tirs du match sur un demi-terrain, affichés d'un coup (● réussi, ✕ raté)
  function potnCourt(c) {
    const D = S.D[c.gid]; if (!D) return "";
    const T = teamOf(D, playerTid(D, c.aid));
    const shots = D.plays.filter(p => p.shoot && !p.ft && p.a0 === c.aid && p.sx != null);
    const DEEP = 32; // le demi-terrain jusqu'un peu au-delà de la ligne à 3 pts (les tirs plus lointains posés au bord)
    const dots = shots.map(p => {
      const x = p.sx.toFixed(1), y = Math.min(p.sy, DEEP - .8).toFixed(1);
      return p.made ? `<circle cx="${x}" cy="${y}" r="1.15" fill="${T.color}" class="mk"/>`
        : `<path d="M${x - .8} ${y - .8}l1.6 1.6m0-1.6l-1.6 1.6" class="ms"/>`;
    });
    // les ratés d'abord, les paniers par-dessus
    dots.sort((a, b) => (a[1] === "c") - (b[1] === "c"));
    const made = shots.filter(p => p.made).length;
    return `<div class="np-court"><div class="lv-courth"><h4>Ses tirs</h4><span>${made}/${shots.length}</span>
        <span class="np-key"><i style="--tc:${T.color}"></i>réussi <em>✕</em>raté</span></div>
      <svg class="np-hc" viewBox="-1 -1 52 ${DEEP + 2}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Ses tirs du match">
        <g class="ln"><rect x="0" y="0" width="50" height="${DEEP}"/><rect x="17" y="0" width="16" height="19"/><circle cx="25" cy="19" r="6"/>
        <path d="M3 0V14A23.75 23.75 0 0 0 47 14V0"/><path d="M22 4H28"/><circle cx="25" cy="5.25" r=".75"/></g>${dots.join("")}</svg></div>`;
  }
  // les plus belles actions : une carte par action, dévoilée quand elle passe (n° 5 → n° 1)
  // le joueur de chaque action n'est pas assez sûr (lu à l'image) : on montre seulement le match (les deux équipes)
  function topCards(c, t) {
    const plays = c.plays || [];
    if (!plays.length) return `<div class="lv-sec np-idle"><span class="lv-kick sm">Les plus belles actions de la nuit</span><p>Profite.</p></div>`;
    const n = plays.filter(a => t >= a.s).length;
    return `<div class="np-tops" style="--n:${plays.length}">${plays.map((a, i) => {
      const rank = a.r || plays.length - i, open = i < n, curr = i === n - 1;
      if (!open) return `<div class="np-top off"><span class="np-rk">${rank}</span><span class="np-q">?</span></div>`;
      return `<div class="np-top rk ${curr ? "cur" : ""}"><span class="np-rkbig">${rank}</span><b>Top ${rank}</b></div>`; // ni joueur ni match : la lecture n'est pas assez sûre
    }).join("")}</div>`;
  }
  function gameTeams(a) {
    const D = a.gid && S.D[a.gid];
    if (D) return { A: teamOf(D, D.away), H: team(D.home) };
    const g = a.gid && typeof state !== "undefined" ? state.games.find(x => x.id === a.gid) : null; // déroulé absent : la liste des matchs
    return g ? { A: g.teams.away, H: g.teams.home } : null;
  }
  function gameCard(a, rank, curr) {
    const M = gameTeams(a);
    if (!M) return `<div class="np-top gm none ${curr ? "cur" : ""}"><span class="np-rk">${rank}</span><b>Action n° ${rank}</b></div>`;
    return `<div class="np-top gm ${curr ? "cur" : ""}" style="--ca:${M.A.color};--cb:${M.H.color}"><span class="np-rk">${rank}</span>
      <div class="np-gl">${logoHTML(M.A)}${logoHTML(M.H)}</div><b>${M.A.name} – ${M.H.name}</b><small>Action n° ${rank}</small></div>`;
  }
  function topBig(a, rank) {
    rank = a.r || rank;
    const M = gameTeams(a);
    return `<div class="np-card tall gmb" ${M ? `style="--ca:${M.A.color};--cb:${M.H.color}"` : ""}><span class="np-bigrk">N° ${rank}</span>
      ${M ? `<div class="np-gl">${logoHTML(M.A)}${logoHTML(M.H)}</div>` : ""}
      <div class="np-id"><span class="lv-kick sm">La plus belle action n° ${rank}</span><b>${M ? `${M.A.name} – ${M.H.name}` : "Action n° " + rank}</b></div></div>`;
  }
  document.addEventListener("click", e => {
    const b = e.target.closest("[data-np-seek]"); if (!b || !S || !S.night) return;
    seekYT(+b.dataset.npSeek + .5); S.key = null; renderNight(true);
  });
  function close() { if (S) { S.on = false; S = null; } }
  // plein écran d'office quand il y aura des stats : vidéo analysée, ou ordinateur (mode direct)
  function wantsFull(vid) { return DEMO ? CAN : !!((vid && MAPS && MAPS.has(vid)) || CAN); } // le partage reste ouvert pour le résumé suivant
  // appelé au clic « Résumé » (geste de l'utilisateur, exigé par le navigateur pour demander le partage)
  function onResumeClick(vid) {
    if (vid && MAPS && MAPS.has(vid)) return; // table préparée : pas besoin de partage
    if (CAN && !DEMO && store.get("live", true) && store.get("liveused", false)) ensureStream();
  }
  document.addEventListener("click", e => {
    if (e.target.closest("[data-live-start]")) { store.set("liveused", true); start(true); }
    else if (e.target.closest("[data-live-stop]")) stop();
    else if (e.target.closest("[data-live-diag]") && S) { S.diag = !S.diag; render(true); }
  });
  document.addEventListener("change", e => { if (e.target.matches && e.target.matches("[data-live-auto]")) store.set("live", e.target.checked); });
  document.addEventListener("input", e => {
    if (!S || !e.target.classList.contains("lv-demo")) return;
    S.demoI = +e.target.value; const p = S.D.plays[S.demoI]; S.at = { per: p.per, sec: p.sec };
    const v = e.target.value; render(true); const n = S.el.querySelector(".lv-demo"); if (n) { n.value = v; n.focus(); }
  });

  // tests : rejouer la lecture sur des images fixes (captures) ; rect = place de la vidéo dans l'image
  async function testFrames(list, D) {
    const keep = S; const out = [];
    S = { lock: null, polar: false, reads: 0, miss: 0, fails: 0, D: D || { plays: [{ per: 4 }] }, at: null, cand: null };
    for (const it of list) {
      const t0 = performance.now(); let hit = null, tries = 0;
      while (!hit && tries++ < 4) hit = await readFrame(it.img, it.img.width, it.img.height, it.rect || { x: 0, y: 0, w: it.img.width, h: it.img.height });
      const ok = hit && accept(hit);
      out.push({ ms: Math.round(performance.now() - t0), tries, hit: hit && [hit.per, hit.sec, hit.alt], at: S.at && [S.at.per, S.at.sec], ok: !!ok, lock: !!S.lock, txt: S.diagTxt });
    }
    S = keep; return out;
  }
  const hasMap = vid => !!(vid && MAPS && MAPS.has(vid));
  const indexReady = loadIndex();
  indexReady.then(() => loadVideos()).then(() => refreshReplays()).catch(() => {}); // « Replay + » dès que l'index est là
  function film(j) { // [[secondes de jeu, écart]] après chaque panier, + la fin du dernier quart-temps joué
    const D = parsePlays(j); if (D.plays.length < 10) return null;
    const lastPer = Math.max(4, ...D.plays.map(p => p.per));
    const F = flow(D, { per: lastPer, sec: -1 }); // tout le match
    const end = elapsed(lastPer, 0), pts = F.pts.filter(q => q[0] <= end);
    pts[pts.length - 1][0] < end ? pts.push([end, F.hs - F.as]) : 0;
    return { pts, span: end, nq: lastPer };
  }
  return { CAN, attach, attachNight, film, close, onResumeClick, wantsFull, hasMap, indexReady, testFrames, _flow: flow, _reindex() { MAPS = null; return loadIndex(); }, _plays: parsePlays, _stats: statsAt, _clock: readClock, _q: readQuarter };
})();
